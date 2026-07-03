"""tg_router.py — Routeur Telegram : range les vidéos des modèles par sujet.

Workflow :
- Dans un chat/groupe « de travail » avec une modèle, le boss envoie la veille
  (vidéo exemple). La modèle RÉPOND à cette vidéo avec sa version brute.
- Le bot (même token que la Veille) détecte la réponse-vidéo et copie
  LA VIDÉO EXEMPLE + LA VIDÉO BRUTE dans le groupe de destination,
  dans le SUJET (topic) de la modèle — créé automatiquement.

Config Telegram-native (commandes à taper DANS Telegram) :
- dans le groupe de destination (avec « Sujets » activés + bot admin) :
      /setdestination        -> ce groupe reçoit les vidéos rangées
- dans chaque chat de travail d'une modèle (bot admin pour voir les messages) :
      /setmodel amelia       -> les vidéos d'ici partent dans le sujet « amelia »
      /unsetmodel            -> retire ce chat du routeur
- n'importe où : /routerstatus

Stockage : data/tg_router.json
{"dest_chat_id": ..., "topics": {"amelia": 123}, "sources": {"<chat_id>": "amelia"}, "offset": 0}

Tourne dans un THREAD daemon (long-polling getUpdates) démarré par cogs/tgrouter.py.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import requests

DATA_DIR = Path("data")
CFG_FILE = DATA_DIR / "tg_router.json"
TG = "https://api.telegram.org"
_LOCK = threading.Lock()
_THREAD = None
_STOP = threading.Event()
STATUS = {"running": False, "last_update": 0, "routed": 0, "error": ""}


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


def _token():
    try:
        import veille_telegram
        return (veille_telegram.load_config() or {}).get("bot_token") or ""
    except Exception:
        return ""


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


def _topic_for(cfg: dict, model: str):
    """thread_id du sujet de la modèle (créé si absent)."""
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
    # Fallback : sujet "General" (thread_id absent = message racine)
    return None


def _copy(dest, thread_id, from_chat, message_id):
    p = {"chat_id": dest, "from_chat_id": from_chat, "message_id": message_id}
    if thread_id:
        p["message_thread_id"] = thread_id
    return _api("copyMessage", p)


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
        # Mémorise AUSSI le sujet où la commande est tapée : le bot n'écoutera
        # que ce sujet (ex: IG CONTENT), pas THREADS/General.
        cfg["sources"][str(chat_id)] = {"model": arg, "thread": thread_id}
        _save(cfg)
        where = "de CE SUJET uniquement" if thread_id else "de ce chat"
        _reply(chat_id, f"✅ Branché : les vidéos {where} partent dans le sujet « {arg} ».\n"
                        "Quand quelqu'un RÉPOND à une vidéo avec une vidéo, "
                        "j'envoie l'exemple + la brute là-bas.", thread_id)

    elif cmd == "/settopic":
        # À taper DANS un sujet du groupe destination : lie ce sujet à une modèle
        # (utile si les sujets ont été créés à la main).
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

    elif cmd == "/routerstatus":
        dest = cfg.get("dest_chat_id")
        models = []
        for v in cfg["sources"].values():
            models.append(v.get("model") if isinstance(v, dict) else v)
        _reply(chat_id,
               f"📡 Routeur reels\n• Destination : {'✅ configurée' if dest else '❌ /setdestination dans le groupe à sujets'}\n"
               f"• Sujets sources branchés : {len(models)} ({', '.join(sorted(set(models))) or '—'})\n"
               f"• Vidéos rangées : {STATUS.get('routed', 0)}", thread_id)


def _handle_update(cfg: dict, upd: dict):
    msg = upd.get("message") or {}
    if not msg:
        return
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()

    # Commandes de config (dans n'importe quel chat où le bot est)
    if text.startswith("/"):
        _handle_command(cfg, msg, text)
        return

    # Routage : vidéo en RÉPONSE dans un chat/sujet branché
    src = cfg["sources"].get(str(chat_id))
    if not src or not cfg.get("dest_chat_id"):
        return
    if isinstance(src, str):           # rétro-compat ancien format
        src = {"model": src, "thread": None}
    model = src.get("model")
    want_thread = src.get("thread")
    if want_thread and msg.get("message_thread_id") != want_thread:
        return  # autre sujet du groupe (THREADS, General…) -> on ignore
    if not _is_video_msg(msg):
        return
    ref = msg.get("reply_to_message")
    if not ref:
        return  # vidéo sans réponse = pas un « recopiage », on ignore
    # Quirk des forums Telegram : un message NON-réponse dans un sujet a quand
    # même reply_to_message = racine du sujet. Ce n'est PAS une vraie réponse.
    if ref.get("forum_topic_created"):
        return
    if msg.get("message_thread_id") and ref.get("message_id") == msg.get("message_thread_id"):
        return

    tid = _topic_for(cfg, model)
    dest = cfg["dest_chat_id"]
    # 1) l'exemple (le message auquel on répond : vidéo OU lien veille)
    _copy(dest, tid, chat_id, ref.get("message_id"))
    # 2) la vidéo brute de la modèle
    res = _copy(dest, tid, chat_id, msg.get("message_id"))
    if res.get("ok"):
        STATUS["routed"] = STATUS.get("routed", 0) + 1
        # petit accusé dans le chat source (réaction impossible en bot API simple -> message discret)
        _api("setMessageReaction", {
            "chat_id": chat_id, "message_id": msg.get("message_id"),
            "reaction": [{"type": "emoji", "emoji": "🔥"}],
        })


def _poll_loop():
    STATUS["running"] = True
    STATUS["error"] = ""
    cfg = _load()
    offset = int(cfg.get("offset") or 0)
    while not _STOP.is_set():
        try:
            res = _api("getUpdates", {
                "offset": offset + 1, "timeout": 50,
                "allowed_updates": ["message"],
            }, timeout=60)
            if not res.get("ok"):
                STATUS["error"] = res.get("description", "?")
                # token manquant / conflit -> on attend avant de retenter
                time.sleep(15)
                continue
            for upd in res.get("result") or []:
                offset = max(offset, int(upd.get("update_id") or 0))
                try:
                    cfg = _load()  # config fraîche (commandes récentes)
                    _handle_update(cfg, upd)
                except Exception as e:
                    STATUS["error"] = str(e)
                STATUS["last_update"] = int(time.time())
            if res.get("result"):
                cfg = _load()
                cfg["offset"] = offset
                _save(cfg)
        except Exception as e:
            STATUS["error"] = str(e)
            time.sleep(10)
    STATUS["running"] = False


def start():
    """Démarre le poller (idempotent)."""
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return False
    _STOP.clear()
    _THREAD = threading.Thread(target=_poll_loop, daemon=True, name="tg-router")
    _THREAD.start()
    return True


def stop():
    _STOP.set()
