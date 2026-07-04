"""tg_router.py — Routeur Telegram : range les vidéos des modèles par sujet.

Workflow (2 temps) :
1. Le boss poste la VEILLE dans le sujet branché (ex: IG CONTENT) d'un groupe
   de modèle : vidéo (+ lien en caption) + texte de description.
   -> Le bot poste IMMÉDIATEMENT la vidéo exemple + lien + description dans le
      sujet de la modèle du groupe destination (état « en attente »).
2. La modèle RÉPOND (à la vidéo OU au texte) avec sa vidéo brute.
   -> Le bot REMPLACE le message d'attente par un ALBUM : vidéo exemple +
      vidéo brute côte à côte, avec lien + description en légende. Réaction 🔥.

Config Telegram-native :
- groupe destination (Sujets activés + bot admin)      : /setdestination
- lier un sujet créé à la main à une modèle            : /settopic emma (dans le sujet)
- chat de travail d'une modèle, DANS le sujet des reels : /setmodel emma
- debug : /routerdebug · statut : /routerstatus · retirer : /unsetmodel

Stockage : data/tg_router.json (config) + data/tg_router_cache.json (veilles
en attente + descriptions — persistés pour survivre aux redéploiements).
Tourne dans un THREAD daemon (long-polling getUpdates) via cogs/tgrouter.py.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import requests

DATA_DIR = Path("data")
CFG_FILE = DATA_DIR / "tg_router.json"
CACHE_FILE = DATA_DIR / "tg_router_cache.json"
TG = "https://api.telegram.org"
_LOCK = threading.Lock()
_THREAD = None
_STOP = threading.Event()
STATUS = {"running": False, "last_update": 0, "routed": 0, "error": ""}
EVENTS = []  # ring buffer des 15 dernières décisions (debug)

# ── Registre des veilles ────────────────────────────────────────────────────
# {(chat_id, video_msg_id): {file_id, caption, desc, text_msg_id, dest_msg_id,
#                            model, ts}}  — persisté (cache file)
_VEILLES = {}
# Dernière veille par sujet (pour lier un texte qui arrive APRÈS la vidéo)
_LAST_VEILLE = {}   # {(chat,thread): (ts, video_msg_id)}
# Dernier texte par sujet (pour lier une description qui arrive AVANT la vidéo)
_LAST_TEXT = {}     # {(chat,thread): (ts, text, text_msg_id)}


def _trace(txt: str):
    EVENTS.append(f"{time.strftime('%H:%M:%S')} {txt}")
    del EVENTS[:-15]
    print(f"[tg_router] {txt}", flush=True)


def _load() -> dict:
    try:
        d = json.loads(CFG_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("topics", {})
            d.setdefault("sources", {})
            return d
    except Exception:
        pass
    return {"dest_chat_id": None, "topics": {}, "sources": {}, "offset": 0}


def _save(d: dict):
    with _LOCK:
        CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CFG_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _cache_load():
    try:
        d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        for k, v in (d.get("veilles") or {}).items():
            c, m = k.split("|", 1)
            _VEILLES[(int(c), int(m))] = v
        for k, v in (d.get("last_veille") or {}).items():
            c, t = k.split("|", 1)
            _LAST_VEILLE[(int(c), None if t == "None" else int(t))] = tuple(v)
        for k, v in (d.get("last_text") or {}).items():
            c, t = k.split("|", 1)
            _LAST_TEXT[(int(c), None if t == "None" else int(t))] = tuple(v)
    except Exception:
        pass


def _cache_save():
    try:
        while len(_VEILLES) > 200:
            _VEILLES.pop(next(iter(_VEILLES)))
        for d in (_LAST_VEILLE, _LAST_TEXT):
            while len(d) > 100:
                d.pop(next(iter(d)))
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "veilles": {f"{k[0]}|{k[1]}": v for k, v in _VEILLES.items()},
            "last_veille": {f"{k[0]}|{k[1]}": list(v) for k, v in _LAST_VEILLE.items()},
            "last_text": {f"{k[0]}|{k[1]}": list(v) for k, v in _LAST_TEXT.items()},
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _token():
    cfg = _load()
    if cfg.get("router_token"):
        return cfg["router_token"]
    try:
        import veille_telegram
        return (veille_telegram.load_config() or {}).get("bot_token") or ""
    except Exception:
        return ""


def set_router_token(token: str):
    cfg = _load()
    cfg["router_token"] = (token or "").strip()
    _save(cfg)


def _api(method: str, payload: dict, timeout=20):
    token = _token()
    if not token:
        return {"ok": False, "description": "bot_token manquant (Settings → Veille Telegram)"}
    try:
        r = requests.post(f"{TG}/bot{token}/{method}", json=payload, timeout=timeout)
        return r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


def _reply(chat_id, text, thread_id=None):
    p = {"chat_id": chat_id, "text": text}
    if thread_id:
        p["message_thread_id"] = thread_id
    _api("sendMessage", p)


def _is_video_msg(msg: dict) -> bool:
    if not msg:
        return False
    if msg.get("video") or msg.get("video_note") or msg.get("animation"):
        return True
    doc = msg.get("document") or {}
    return str(doc.get("mime_type") or "").startswith("video/")


def _real_reply(msg: dict):
    """La VRAIE réponse, ou None. (Quirk forums : un message non-réponse dans
    un sujet a quand même reply_to_message = racine du sujet.)"""
    ref = msg.get("reply_to_message")
    if not ref:
        return None
    if ref.get("forum_topic_created"):
        return None
    if msg.get("message_thread_id") and ref.get("message_id") == msg.get("message_thread_id"):
        return None
    return ref


def _topic_for(cfg: dict, model: str):
    tid = cfg["topics"].get(model)
    if tid:
        return tid
    res = _api("createForumTopic", {"chat_id": cfg["dest_chat_id"], "name": model})
    if res.get("ok"):
        tid = (res.get("result") or {}).get("message_thread_id")
        if tid:
            cfg["topics"][model] = tid
            _save(cfg)
            _reply(cfg["dest_chat_id"], f"📁 Sujet « {model} » prêt — les vidéos arrivent ici.", tid)
            return tid
    return None


def _copy(dest, thread_id, from_chat, message_id):
    p = {"chat_id": dest, "from_chat_id": from_chat, "message_id": message_id}
    if thread_id:
        p["message_thread_id"] = thread_id
    return _api("copyMessage", p)


def _no_links(t: str) -> str:
    """Retire les URLs (l'user ne veut QUE les vidéos + la description)."""
    return re.sub(r"https?://\S+", "", t or "").strip()


def _veille_caption(v: dict) -> str:
    parts = []
    cap = _no_links(v.get("caption"))
    if cap:
        parts.append(cap)
    desc = _no_links(v.get("desc"))
    if desc and desc not in parts:
        parts.append(desc)
    return "\n\n".join(parts)[:1020]


def bound_models() -> dict:
    """{model: {"chat_id": …, "thread": …}} depuis la config du routeur."""
    cfg = _load()
    out = {}
    for cid, src in (cfg.get("sources") or {}).items():
        if isinstance(src, str):
            src = {"model": src, "thread": None}
        m = src.get("model")
        if m and m not in out:
            try:
                out[m] = {"chat_id": int(cid), "thread": src.get("thread")}
            except Exception:
                pass
    return out


def send_veille_to_model(model: str, tg_file_id: str, link: str = "", desc: str = "") -> dict:
    """Envoie une veille (vidéo via file_id Telegram) dans le sujet IG CONTENT
    de la modèle + l'enregistre : elle apparaît aussi « en attente » dans le
    sujet de la modèle du groupe destination. Appelé par le SITE (bouton veille).
    NB: le poller ne voit pas les messages du bot lui-même -> on enregistre ici."""
    bm = bound_models().get((model or "").lower())
    if not bm:
        return {"ok": False, "error": f"« {model} » non branchée (/setmodel dans son groupe)"}
    cfg = _load()
    p = {"chat_id": bm["chat_id"], "video": tg_file_id, "supports_streaming": True}
    if link:
        p["caption"] = link[:1020]
    if bm.get("thread"):
        p["message_thread_id"] = bm["thread"]
    res = _api("sendVideo", p)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("description", "?")}
    vid_msg = (res.get("result") or {}).get("message_id")
    text_msg_id = None
    if (desc or "").strip():
        p2 = {"chat_id": bm["chat_id"], "text": desc.strip()[:4000],
              "reply_to_message_id": vid_msg, "disable_web_page_preview": True}
        if bm.get("thread"):
            p2["message_thread_id"] = bm["thread"]
        r2 = _api("sendMessage", p2)
        if r2.get("ok"):
            text_msg_id = (r2.get("result") or {}).get("message_id")
    v = {"file_id": tg_file_id, "caption": (link or "").strip(),
         "desc": (desc or "").strip() or None, "text_msg_id": text_msg_id,
         "dest_msg_id": None, "model": model, "ts": time.time(), "routed": False}
    _VEILLES[(bm["chat_id"], vid_msg)] = v
    _LAST_VEILLE[(bm["chat_id"], bm.get("thread"))] = (time.time(), vid_msg)
    if cfg.get("dest_chat_id"):
        _post_pending(cfg, v, model)
    _cache_save()
    _trace(f"veille envoyée depuis le SITE -> {model}")
    return {"ok": True}


def _post_pending(cfg: dict, v: dict, model: str):
    """Poste la veille (vidéo + lien + description) dans le sujet de la modèle."""
    tid = _topic_for(cfg, model)
    p = {"chat_id": cfg["dest_chat_id"], "video": v["file_id"]}
    cap = _veille_caption(v)
    if cap:
        p["caption"] = cap
    if tid:
        p["message_thread_id"] = tid
    res = _api("sendVideo", p)
    if res.get("ok"):
        v["dest_msg_id"] = (res.get("result") or {}).get("message_id")
        _trace(f"veille postée dans le sujet {model} (en attente de la modèle)")
    else:
        _trace(f"post veille échoué ({model}) : {res.get('description', '?')}")


def _update_pending_caption(cfg: dict, v: dict):
    if not v.get("dest_msg_id"):
        return
    _api("editMessageCaption", {
        "chat_id": cfg["dest_chat_id"], "message_id": v["dest_msg_id"],
        "caption": _veille_caption(v),
    })


# ── Commandes ───────────────────────────────────────────────────────────────
def _handle_command(cfg: dict, msg: dict, text: str):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    thread_id = msg.get("message_thread_id")
    cmd = text.split("@")[0].split()[0].lower()
    arg = " ".join(text.split()[1:]).strip().lower()

    if cmd == "/setdestination":
        if not chat.get("is_forum"):
            _reply(chat_id, "⚠️ Ce groupe n'a pas les « Sujets » activés.\n"
                            "Paramètres du groupe → Sujets → Activer, puis refais /setdestination.",
                   thread_id)
            return
        cfg["dest_chat_id"] = chat_id
        _save(cfg)
        _reply(chat_id, "✅ Ce groupe est maintenant la DESTINATION.\n"
                        "Un sujet par modèle sera créé automatiquement.\n"
                        "Dans chaque chat de travail, tape /setmodel <nom> pour brancher.", thread_id)

    elif cmd == "/setmodel":
        if cfg.get("dest_chat_id") == chat_id:
            _reply(chat_id, "⚠️ Pas ici ! Ce groupe est la DESTINATION.\n"
                            "Tape /setmodel <nom> dans le GROUPE de la modèle, "
                            "DANS le sujet où passent les reels (ex: IG CONTENT).",
                   thread_id)
            return
        if not arg:
            _reply(chat_id, "Usage : /setmodel emma\n"
                            "(à taper dans le groupe de la modèle, DANS le sujet "
                            "des reels — ex: IG CONTENT)", thread_id)
            return
        # On retient QUI a branché (le boss) : seules SES vidéos sans « Répondre »
        # deviennent des veilles — celles de la modèle doivent RÉPONDRE.
        boss_id = ((msg.get("from") or {}).get("id"))
        cfg["sources"][str(chat_id)] = {"model": arg, "thread": thread_id, "boss": boss_id}
        _save(cfg)
        # Crée le sujet de la modèle TOUT DE SUITE dans le groupe destination
        # (avant, il n'apparaissait qu'à la 1ère veille -> confusion)
        if cfg.get("dest_chat_id"):
            _topic_for(cfg, arg)
        where = "de CE SUJET uniquement" if thread_id else "de ce chat"
        _reply(chat_id, f"✅ Branché : les veilles {where} partent dans le sujet « {arg} ».\n"
                        "Son sujet est prêt dans le groupe destination. Dès que tu postes "
                        "une veille je la mets là-bas, et quand la modèle répond avec sa "
                        "vidéo je fais l'album des deux.", thread_id)

    elif cmd == "/settopic":
        if cfg.get("dest_chat_id") != chat_id:
            _reply(chat_id, "⚠️ /settopic se tape DANS le groupe destination, "
                            "à l'intérieur du sujet à lier.", thread_id)
            return
        if not arg:
            _reply(chat_id, "Usage : dans le sujet AMELIA, tape /settopic amelia", thread_id)
            return
        if not thread_id:
            _reply(chat_id, "⚠️ Tape la commande À L'INTÉRIEUR du sujet (pas dans General).")
            return
        cfg["topics"][arg] = thread_id
        _save(cfg)
        _reply(chat_id, f"✅ Ce sujet est maintenant celui de « {arg} » — "
                        "ses vidéos arriveront ici.", thread_id)

    elif cmd == "/unsetmodel":
        cfg["sources"].pop(str(chat_id), None)
        _save(cfg)
        _reply(chat_id, "✅ Chat débranché du routeur.", thread_id)

    elif cmd == "/routerdebug":
        ev = "\n".join(EVENTS[-12:]) or "(aucun événement depuis le démarrage)"
        _reply(chat_id, f"🔍 Dernières décisions du routeur :\n{ev}"
               + (f"\n\n⚠️ Erreur : {STATUS.get('error')}" if STATUS.get("error") else ""),
               thread_id)

    elif cmd == "/routerstatus":
        dest = cfg.get("dest_chat_id")
        # Détail par branchement : modèle -> NOM du groupe Telegram (getChat)
        lines = []
        seen_models = {}
        for cid, v in cfg["sources"].items():
            m = v.get("model") if isinstance(v, dict) else v
            title = "?"
            try:
                gc = _api("getChat", {"chat_id": int(cid)})
                if gc.get("ok"):
                    title = (gc.get("result") or {}).get("title") or "(chat privé)"
            except Exception:
                pass
            dup = " ⚠️ DOUBLON" if m in seen_models else ""
            seen_models[m] = True
            lines.append(f"  • {m} → « {title} »{dup}")
        pending = sum(1 for v in _VEILLES.values() if v.get("dest_msg_id") and not v.get("routed"))
        _reply(chat_id,
               f"📡 Routeur reels\n• Destination : {'✅ configurée' if dest else '❌ /setdestination dans le groupe à sujets'}\n"
               f"• Branchements ({len(lines)}) :\n" + ("\n".join(lines) or "  (aucun)") + "\n"
               f"• Veilles en attente d'une vidéo : {pending}\n"
               f"• Vidéos rangées : {STATUS.get('routed', 0)}", thread_id)


# ── Cœur du routage ─────────────────────────────────────────────────────────
def _handle_update(cfg: dict, upd: dict):
    edited = "edited_message" in upd
    msg = upd.get("message") or upd.get("edited_message") or {}
    if not msg:
        return
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()

    if text.startswith("/"):
        if not edited:
            _handle_command(cfg, msg, text)
        return

    # Message ÉDITÉ : si c'est une veille connue, on met juste à jour sa légende
    if edited and _is_video_msg(msg):
        v = _VEILLES.get((chat_id, msg.get("message_id")))
        if v and not v.get("routed"):
            v["caption"] = (msg.get("caption") or "").strip()
            _update_pending_caption(cfg, v)
            _cache_save()
            _trace(f"veille éditée -> légende mise à jour ({v.get('model')})")
        return

    src = cfg["sources"].get(str(chat_id))
    if isinstance(src, str):
        src = {"model": src, "thread": None}
    if not src or not cfg.get("dest_chat_id"):
        return
    model = src.get("model")
    want_thread = src.get("thread")
    if want_thread and msg.get("message_thread_id") != want_thread:
        return
    tkey = (chat_id, msg.get("message_thread_id"))
    now = time.time()

    # ---- TEXTE : description de veille ----
    if text and len(text) > 12:
        _LAST_TEXT[tkey] = (now, text, msg.get("message_id"))
        v = None
        tref = _real_reply(msg)
        if tref and _is_video_msg(tref):
            v = _VEILLES.get((chat_id, tref.get("message_id")))
        if not v:
            lv = _LAST_VEILLE.get(tkey)
            if lv and now - lv[0] < 600:
                v = _VEILLES.get((chat_id, lv[1]))
        if v and not v.get("routed"):
            v["desc"] = text
            v["text_msg_id"] = msg.get("message_id")
            _update_pending_caption(cfg, v)
            _trace(f"description liée à la veille ({model}) : {text[:40]}…")
        else:
            _trace(f"texte mémorisé ({model}) : {text[:40]}…")
        _cache_save()
        return

    if not _is_video_msg(msg):
        return

    ref = _real_reply(msg)

    # ---- VIDÉO SANS RÉPONSE = NOUVELLE VEILLE (seulement du BOSS) ----
    if not ref:
        boss = src.get("boss")
        sender = (msg.get("from") or {}).get("id")
        if boss and sender and sender != boss:
            _trace(f"vidéo de la modèle sans « Répondre » ignorée ({model}) — elle doit répondre à la veille")
            return
        fid = (msg.get("video") or {}).get("file_id")
        if not fid:
            _trace(f"veille ignorée ({model}) : pas une vidéo classique (note/doc)")
            return
        v = {"file_id": fid, "caption": (msg.get("caption") or "").strip(),
             "desc": None, "text_msg_id": None, "dest_msg_id": None,
             "model": model, "ts": now, "routed": False}
        # description arrivée AVANT la vidéo ?
        lt = _LAST_TEXT.get(tkey)
        if lt and now - lt[0] < 600:
            v["desc"] = lt[1]
            v["text_msg_id"] = lt[2]
        _VEILLES[(chat_id, msg.get("message_id"))] = v
        _LAST_VEILLE[tkey] = (now, msg.get("message_id"))
        _post_pending(cfg, v, model)
        _cache_save()
        return

    # ---- VIDÉO EN RÉPONSE = LA MODÈLE A FAIT SA VERSION ----
    raw_fid = (msg.get("video") or {}).get("file_id")
    # retrouve la veille : réponse à la vidéo, ou au texte de description
    v = _VEILLES.get((chat_id, ref.get("message_id")))
    if not v:
        for vv in _VEILLES.values():
            if vv.get("text_msg_id") == ref.get("message_id") and vv.get("model") == model:
                v = vv
                break
    if not v and _is_video_msg(ref):
        # veille inconnue (postée avant le bot) : on la reconstruit depuis la réponse
        v = {"file_id": (ref.get("video") or {}).get("file_id"),
             "caption": (ref.get("caption") or ref.get("text") or "").strip(),
             "desc": None, "text_msg_id": None, "dest_msg_id": None,
             "model": model, "ts": now, "routed": False}
        lt = _LAST_TEXT.get(tkey)
        if lt and now - lt[0] < 7200:
            v["desc"] = lt[1]
    if not v:
        _trace(f"réponse ignorée ({model}) : impossible de retrouver la veille d'origine")
        return

    tid = _topic_for(cfg, model)
    dest = cfg["dest_chat_id"]
    caption = _veille_caption(v)

    res = {"ok": False}
    if v.get("file_id") and raw_fid:
        media = [{"type": "video", "media": v["file_id"]},
                 {"type": "video", "media": raw_fid}]
        if caption:
            media[0]["caption"] = caption
        p = {"chat_id": dest, "media": media}
        if tid:
            p["message_thread_id"] = tid
        res = _api("sendMediaGroup", p)
    elif raw_fid:
        p = {"chat_id": dest, "video": raw_fid}
        if caption:
            p["caption"] = caption
        if tid:
            p["message_thread_id"] = tid
        res = _api("sendVideo", p)
    if not res.get("ok"):
        _trace(f"album KO ({model}) : {res.get('description', '?')} -> fallback copie")
        _copy(dest, tid, chat_id, ref.get("message_id"))
        res = _copy(dest, tid, chat_id, msg.get("message_id"))

    if res.get("ok"):
        # remplace le message « en attente » par l'album
        if v.get("dest_msg_id"):
            _api("deleteMessage", {"chat_id": dest, "message_id": v["dest_msg_id"]})
            v["dest_msg_id"] = None
        v["routed"] = True
        STATUS["routed"] = STATUS.get("routed", 0) + 1
        _cache_save()
        _trace(f"✅ routé ({model}) -> album dans le sujet {tid}")
        _api("setMessageReaction", {
            "chat_id": chat_id, "message_id": msg.get("message_id"),
            "reaction": [{"type": "emoji", "emoji": "🔥"}],
        })
    else:
        _trace(f"routage échoué ({model}) : {res.get('description', '?')}")


def _poll_loop():
    STATUS["running"] = True
    STATUS["error"] = ""
    cfg = _load()
    offset = int(cfg.get("offset") or 0)
    while not _STOP.is_set():
        try:
            res = _api("getUpdates", {
                "offset": offset + 1, "timeout": 50,
                "allowed_updates": ["message", "edited_message"],
            }, timeout=60)
            if not res.get("ok"):
                STATUS["error"] = res.get("description", "?")
                time.sleep(15)
                continue
            batch = res.get("result") or []
            if batch:
                # ACK D'ABORD : on persiste l'offset AVANT de traiter. Si le bot
                # est tué en plein traitement (déploiement), Telegram ne relivre
                # PAS les mêmes messages -> zéro réponse en double.
                for upd in batch:
                    offset = max(offset, int(upd.get("update_id") or 0))
                cfg = _load()
                cfg["offset"] = offset
                _save(cfg)
            for upd in batch:
                try:
                    cfg = _load()
                    _handle_update(cfg, upd)
                except Exception as e:
                    STATUS["error"] = str(e)
                STATUS["last_update"] = int(time.time())
        except Exception as e:
            STATUS["error"] = str(e)
            time.sleep(10)
    STATUS["running"] = False


def start():
    """Démarre le poller (idempotent)."""
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return False
    _cache_load()
    _STOP.clear()
    _THREAD = threading.Thread(target=_poll_loop, daemon=True, name="tg-router")
    _THREAD.start()
    return True


def stop():
    _STOP.set()
