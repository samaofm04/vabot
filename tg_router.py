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

import base64
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import requests

DATA_DIR = Path("data")
CFG_FILE = DATA_DIR / "tg_router.json"
CACHE_FILE = DATA_DIR / "tg_router_cache.json"
TG = "https://api.telegram.org"
_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()   # protège l'écriture du cache (routages concurrents)
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
    with _CACHE_LOCK:
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


def _veille_texts(v: dict) -> list:
    """Textes à poster en MESSAGES SÉPARÉS (style envoi veille) :
    [texte incrusté BRUT, description] — sans ✍️, sans guillemets, sans liens."""
    out = []
    ov = (v.get("overlay") or "").strip()
    if ov:
        out.append(ov)
    cap = _no_links(v.get("caption"))
    if cap and cap not in out:
        out.append(cap)
    desc = _no_links(v.get("desc"))
    if desc and desc not in out:
        out.append(desc)
    return out


def _veille_caption(v: dict) -> str:
    """Concat des textes (sert aux checks « y a-t-il du texte ? » et aux logs)."""
    return "\n\n".join(_veille_texts(v))[:1020]


# ── Transcription IA du texte incrusté sur la vidéo (3 premières secondes) ──
_OCR_PROMPT = (
    "Ces images sont des frames des premières secondes d'un reel Instagram. "
    "Retranscris EXACTEMENT le texte incrusté sur la vidéo (la caption ajoutée "
    "par l'auteur), AVEC ses emojis.\n"
    "RÈGLE ABSOLUE sur la mise en forme : reproduis EXACTEMENT les sauts de ligne "
    "visibles à l'écran. Mets un vrai retour à la ligne à CHAQUE endroit où le "
    "texte passe à la ligne suivante sur la vidéo. NE recolle JAMAIS plusieurs "
    "lignes en une seule phrase — même si ça coupe une phrase au milieu.\n"
    "Exemple : si l'écran affiche ces 3 lignes :\n"
    "Lui : « Je suis marié avec\n"
    "3 enfants faut qu'on arrête\n"
    "de se voir »\n"
    "alors ta réponse doit contenir EXACTEMENT ces 3 lignes séparées, pas une seule.\n"
    "Ignore les éléments d'interface, watermarks, usernames et sous-titres "
    "automatiques. Réponds UNIQUEMENT avec le texte retranscrit (avec ses retours "
    "à la ligne), sans commentaire. "
    "S'il n'y a AUCUN texte incrusté, réponds exactement : AUCUN"
)


# Mode INTELLIGENT : frames réparties sur TOUTE la vidéo, Claude reconstitue la
# séquence des textes (un montage peut afficher un texte, puis le même + un
# nouveau, etc.) en dédupliquant ce qui reste affiché.
_OCR_PROMPT_FULL = (
    "Ces images sont des frames d'un reel Instagram, dans l'ORDRE CHRONOLOGIQUE "
    "(du début à la fin de la vidéo). Le texte incrusté peut CHANGER au fil de la "
    "vidéo : un premier texte apparaît, puis un nouveau s'ajoute en dessous ou le "
    "remplace, etc.\n"
    "Ta mission : retranscrire LA SÉQUENCE COMPLÈTE des textes incrustés, dans "
    "l'ordre d'apparition, AVEC les emojis et les retours à la ligne de chaque bloc.\n"
    "RÈGLE ANTI-RÉPÉTITION (absolue) : chaque texte ne doit apparaître QU'UNE SEULE "
    "FOIS dans ta réponse. Si une frame montre l'ancien texte toujours affiché + un "
    "nouveau texte, ne retranscris QUE le nouveau. Ne répète jamais un bloc déjà "
    "retranscrit.\n"
    "Sépare chaque moment/bloc par UNE ligne vide.\n"
    "Ignore interface, watermarks, usernames et sous-titres automatiques. Réponds "
    "UNIQUEMENT avec les textes. S'il n'y a AUCUN texte incrusté : AUCUN"
)


def _video_duration(src, headers=None):
    """Durée (secondes, float) d'une vidéo locale OU d'une URL via ffprobe.
    None si indéterminable."""
    cmd = ["ffprobe", "-v", "error"]
    if headers:
        cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    cmd += ["-show_entries", "format=duration", "-of", "csv=p=0", str(src)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=25, text=True)
        return float(r.stdout.strip())
    except Exception:
        return None


def _full_timestamps(duration):
    """8 instants répartis sur toute la vidéo (ou défaut si durée inconnue)."""
    if not duration or duration <= 4:
        return ["0.5", "1.2", "2.0", "2.8"]
    n = 8
    start, end = 0.5, max(1.0, duration - 0.4)
    step = (end - start) / (n - 1)
    return [f"{start + i * step:.1f}" for i in range(n)]


def _env_api_key() -> str:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if key:
        return key
    try:
        env = Path(__file__).resolve().parent / ".env"
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                return line.strip().split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        return True
    except Exception:
        return False


def _ocr_ready() -> bool:
    """Un moteur OCR dispo : Gemini (gratuit) OU IA Anthropic (payant) OU
    Tesseract (gratuit, local)."""
    return bool(_env_gemini_key()) or bool(_env_api_key()) or _tesseract_available()


def _clean_ocr(txt: str) -> str:
    """Nettoie une sortie OCR brute : garde les lignes qui ont >=3 lettres,
    recolle en une phrase, compresse les espaces."""
    keep = []
    for line in (txt or "").splitlines():
        s = line.strip()
        if sum(c.isalpha() for c in s) >= 3:
            keep.append(s)
    return re.sub(r"\s+", " ", " ".join(keep)).strip()


def _preprocess_variants(src):
    """Plusieurs versions préparées d'une frame pour Tesseract, en NOIR sur BLANC
    (ce que Tesseract lit le mieux — le texte incrusté est clair, donc on binarise
    PUIS on inverse). Plusieurs seuils + une variante autocontrast : on tentera
    toutes et on gardera la meilleure. Upscale x3 = lettres plus grosses."""
    from PIL import Image, ImageOps, ImageEnhance, ImageFilter
    base = Image.open(src).convert("L")
    w, h = base.size
    scale = 3 if max(w, h) < 950 else 2
    base = base.resize((w * scale, h * scale), Image.LANCZOS)
    base = base.filter(ImageFilter.SHARPEN)
    base = ImageEnhance.Contrast(base).enhance(1.7)
    out = []
    for thr in (140, 175, 205):
        b = base.point(lambda p, t=thr: 255 if p > t else 0)  # texte clair -> blanc
        out.append(ImageOps.invert(b))                        # -> texte NOIR sur BLANC
    out.append(ImageOps.invert(ImageOps.autocontrast(base, cutoff=1)))
    return out


def _score_ocr(txt: str) -> int:
    """Nb de mots plausibles (>=2 lettres) — pour choisir la meilleure variante."""
    return len([w for w in re.split(r"\s+", txt or "")
                if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", w)) >= 2])


def _ocr_tesseract(frame_paths, tag: str = "") -> str:
    """OCR GRATUIT hors-ligne (Tesseract, français) — aucune API, 0€.
    Pour CHAQUE frame teste plusieurs pré-traitements (noir/blanc, seuils) en
    parallèle et garde le résultat au meilleur SCORE (le plus de vrais mots)."""
    try:
        import pytesseract
    except Exception:
        return ""
    from concurrent.futures import ThreadPoolExecutor
    jobs = []
    for fp in frame_paths:
        try:
            variants = _preprocess_variants(fp)
        except Exception:
            continue
        for vi, im in enumerate(variants):
            pre = str(fp) + f".v{vi}.png"
            try:
                im.save(pre)
                jobs.append(pre)
            except Exception:
                pass
    if not jobs:
        return ""

    def _one(pre):
        try:
            raw = pytesseract.image_to_string(pre, lang="fra", config="--psm 6")
            txt = _clean_ocr(raw)
            return (_score_ocr(txt), txt)
        except Exception:
            return (-1, "")
        finally:
            try:
                Path(pre).unlink()
            except Exception:
                pass

    best, best_sc = "", -1
    with ThreadPoolExecutor(max_workers=4) as ex:
        for sc, txt in ex.map(_one, jobs):
            if sc > best_sc:
                best_sc, best = sc, txt
    if best:
        _trace(f"✍️ texte lu (gratuit/Tesseract) {tag}: {best[:45]}…")
    return best[:300]


def _ocr_claude(frame_paths, tag: str = "", prompt: str = None,
                max_frames: int = 3, max_len: int = 300) -> str:
    """OCR IA (Anthropic) — lit emojis + texte stylé. `prompt`/`max_frames`
    personnalisables (mode intelligent = 8 frames + prompt séquence)."""
    key = _env_api_key()
    if not key:
        return ""
    content = []
    for fp in frame_paths[:max_frames]:
        try:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(Path(fp).read_bytes()).decode()}})
        except Exception:
            pass
    if not content:
        return ""
    content.append({"type": "text", "text": prompt or _OCR_PROMPT})
    try:
        rr = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 600,
                  "messages": [{"role": "user", "content": content}]},
            timeout=90)
        data = rr.json()
        if rr.status_code != 200:
            _trace(f"ocr: API {(data.get('error') or {}).get('message', '?')}")
            return ""
        text = "".join(b.get("text", "") for b in (data.get("content") or [])).strip()
        if text and not text.upper().startswith("AUCUN"):
            _trace(f"✍️ texte lu (IA) {tag}: {text[:45]}…")
            return text[:max_len]
    except Exception as e:
        _trace(f"ocr IA: {e}")
    return ""


_OCR_ENGINE_USED = ""


def _run_ocr(frame_paths, tag: str = "") -> str:
    """Lit le texte incrusté, par ordre de préférence :
    1) Claude (Anthropic) si ANTHROPIC_API_KEY — lit emojis + texte stylé, fiable
    2) Gemini (Google, gratuit) si GEMINI_API_KEY
    3) Tesseract (gratuit local, mais pas les emojis). '' si rien."""
    global _OCR_ENGINE_USED
    if _env_api_key():
        t = _ocr_claude(frame_paths, tag)
        if t:
            _OCR_ENGINE_USED = "ia"
            return t
    if _env_gemini_key():
        t = _ocr_gemini(frame_paths, tag)
        if t:
            _OCR_ENGINE_USED = "gemini"
            return t
    t = _ocr_tesseract(frame_paths, tag)
    _OCR_ENGINE_USED = "tesseract"
    return t


def _frames_from_video_file(vid, slug, timestamps=None):
    """Extrait des frames JPEG d'un fichier vidéo LOCAL déjà téléchargé.
    Retourne list[Path]. timestamps = liste de secondes (str), défaut 4 instants."""
    tmpdir = Path(vid).parent
    frames = []
    for ts in (timestamps or ("0.4", "1.2", "2.0", "2.8")):
        out = tmpdir / f"fr_{slug}_{str(ts).replace('.', '_')}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(ts), "-i", str(vid), "-frames:v", "1",
                 "-vf", "scale=640:-2", "-q:v", "3", str(out)],
                capture_output=True, timeout=30)
            if out.exists() and out.stat().st_size > 1000:
                frames.append(out)
        except Exception:
            pass
    if not frames:
        _trace("ocr: extraction frames échouée (ffmpeg ?)")
    return frames


def _extract_frames(file_id, tag: str = "", slug: str = "", timestamps=None):
    """Télécharge la vidéo (file_id Telegram) et extrait des frames JPEG sur
    disque. Retourne (list[Path], Path video) — nettoyer via _cleanup_frames().
    ([], None) si échec."""
    token = _token()
    tmpdir = DATA_DIR / "tg_tmp"
    slug = slug or str(abs(hash(file_id)) % 10**8)
    vid = tmpdir / f"ocr_{slug}.mp4"
    try:
        gf = _api("getFile", {"file_id": file_id})
        if not gf.get("ok"):
            _trace(f"ocr: getFile KO ({gf.get('description', '?')})")
            return [], None
        fp = (gf.get("result") or {}).get("file_path")
        if not fp:
            return [], None
        r = requests.get(f"{TG}/file/bot{token}/{fp}", timeout=90)
        if r.status_code != 200:
            return [], None
        tmpdir.mkdir(parents=True, exist_ok=True)
        vid.write_bytes(r.content)
        frames = _frames_from_video_file(vid, slug, timestamps)
        return frames, vid
    except Exception as e:
        _trace(f"ocr extract: {e}")
        return [], vid


def download_file_bytes(file_id: str):
    """Récupère les bytes d'un fichier Telegram (file_id) via getFile. None si KO."""
    if not file_id:
        return None
    try:
        gf = _api("getFile", {"file_id": file_id})
        if not gf.get("ok"):
            return None
        fp = (gf.get("result") or {}).get("file_path")
        if not fp:
            return None
        r = requests.get(f"{TG}/file/bot{_token()}/{fp}", timeout=90)
        return r.content if r.status_code == 200 else None
    except Exception:
        return None


def _download_fid_to(file_id: str, path, deadline: float = 45) -> bool:
    """Télécharge un file_id Telegram sur DISQUE, en STREAMING avec une limite de
    temps DURE (`deadline` s). False si trop gros (>20 Mo, limite getFile), trop
    lent (dépasse deadline) ou erreur réseau. Retourne aussi le nb d'octets via
    l'attribut path (on lit path.stat après)."""
    token = _token()
    if not (file_id and token):
        return False
    try:
        gf = _api("getFile", {"file_id": file_id})
        if not gf.get("ok"):
            return False
        r = (gf.get("result") or {})
        fp = r.get("file_path")
        if not fp:
            return False
        sz = r.get("file_size") or 0
        if sz and sz > 20 * 1024 * 1024:   # >20 Mo : inutile d'essayer
            return False
        t0 = time.time()
        with requests.get(f"{TG}/file/bot{token}/{fp}",
                          timeout=(10, 30), stream=True) as resp:
            if resp.status_code != 200:
                return False
            with open(path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=262144):
                    if chunk:
                        fh.write(chunk)
                    if time.time() - t0 > deadline:
                        _trace(f"swap son: download > {deadline:.0f}s -> abandon")
                        return False
        return path.stat().st_size > 0
    except Exception:
        return False


def _probe_duration(path) -> float:
    """Durée (s) d'un fichier local via ffprobe. 0.0 si inconnu."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", str(path)],
            capture_output=True, text=True, timeout=15)
        return float((r.stdout or "").strip())
    except Exception:
        return 0.0


def _swap_audio(video_fid: str, audio_fid: str, slug: str):
    """Produit une vidéo = IMAGE de `video_fid` (la brute de la modèle) + SON de
    `audio_fid` (le reel exemple, son tendance). Le son d'origine de la brute est
    entièrement RETIRÉ. Le son de l'exemple est bouclé si besoin pour couvrir
    toute la brute, puis coupé à la durée de la brute (vidéo jamais tronquée).
    Retourne un Path (à supprimer après envoi) ou None si impossible
    (fichier > 20 Mo, exemple sans piste audio, ffmpeg absent…)."""
    tmpdir = DATA_DIR / "tg_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    vsrc = tmpdir / f"swap_v_{slug}.mp4"
    asrc = tmpdir / f"swap_a_{slug}.mp4"
    out = tmpdir / f"swap_out_{slug}.mp4"
    t0 = time.time()
    try:
        if not _download_fid_to(video_fid, vsrc):
            _trace("swap son: brute non téléchargeable (>20 Mo / trop lent)")
            return None
        if not _download_fid_to(audio_fid, asrc):
            _trace("swap son: exemple non téléchargeable (>20 Mo / trop lent)")
            return None
        t_dl = time.time() - t0
        # BORNE ffmpeg à la durée de la brute -> il ne peut JAMAIS boucler l'audio
        # à l'infini ni se bloquer.
        vdur = _probe_duration(vsrc)
        cmd = ["ffmpeg", "-y", "-i", str(vsrc),
               "-stream_loop", "-1", "-i", str(asrc),
               "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
               "-shortest", "-movflags", "+faststart"]
        if vdur and vdur > 0:
            cmd += ["-t", f"{min(vdur, 180):.2f}"]
        cmd.append(str(out))
        tf = time.time()
        p = subprocess.run(cmd, capture_output=True, timeout=45)
        t_ff = time.time() - tf
        if p.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
            err = (p.stderr[-200:] if p.stderr else b"").decode("utf-8", "ignore")
            _trace(f"swap son: ffmpeg KO ({err})")
            try:
                out.unlink()
            except Exception:
                pass
            return None
        mb = out.stat().st_size / 1024 / 1024
        _trace(f"swap son prêt: dl {t_dl:.0f}s + ffmpeg {t_ff:.0f}s -> {mb:.1f} Mo")
        return out
    except Exception as e:
        _trace(f"swap son: {e}")
        return None
    finally:
        for f in (vsrc, asrc):
            try:
                f.unlink()
            except Exception:
                pass


def _send_album_local_brute(dest, tid, example_fid, local_path, timeout=150):
    """sendMediaGroup [exemple (file_id), brute LOCALE uploadée] — la brute est
    envoyée en multipart (attach://), l'exemple reste un file_id. Chronométré :
    l'upload de la vidéo est souvent le poste le plus lourd sur un VPS."""
    token = _token()
    if not token:
        return {"ok": False, "description": "bot_token manquant"}
    media = [{"type": "video", "media": example_fid},
             {"type": "video", "media": "attach://brute"}]
    data = {"chat_id": str(dest), "media": json.dumps(media)}
    if tid:
        data["message_thread_id"] = str(tid)
    t0 = time.time()
    try:
        with open(local_path, "rb") as fh:
            r = requests.post(f"{TG}/bot{token}/sendMediaGroup",
                              data=data, files={"brute": fh},
                              timeout=(10, timeout))
        out = r.json()
        _trace(f"upload album: {time.time() - t0:.0f}s (ok={out.get('ok')})")
        return out
    except Exception as e:
        _trace(f"upload album: échec après {time.time() - t0:.0f}s ({e})")
        return {"ok": False, "description": str(e)}


def ocr_video_bytes(video_bytes: bytes, second=None) -> dict:
    """OCR pour le SITE : lit le texte incrusté d'une vidéo fournie en BYTES
    (téléchargée par le site depuis video_url/Telegram), à un instant précis
    (second) ou sur 4 instants. Retourne {ok, text, engine}."""
    if not _ocr_ready():
        return {"ok": False, "text": "", "error": "Aucun OCR (installe Tesseract)"}
    if not video_bytes:
        return {"ok": False, "text": "", "error": "vidéo vide"}
    tmpdir = DATA_DIR / "tg_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    slug = f"site_{int(time.time() * 1000) % 10**9}"
    vid = tmpdir / f"ocr_{slug}.mp4"
    try:
        vid.write_bytes(video_bytes)
        ts = None
        if second is not None and str(second) != "":
            try:
                ts = [f"{max(0.0, float(second)):.1f}"]
            except Exception:
                ts = None
        frames = _frames_from_video_file(vid, slug, ts)
        try:
            text = _run_ocr(frames, "site") if frames else ""
            return {"ok": True, "text": text, "engine": _OCR_ENGINE_USED or "tesseract"}
        finally:
            _cleanup_frames(frames, None)
    except Exception as e:
        return {"ok": False, "text": "", "error": str(e)}
    finally:
        try:
            vid.unlink()
        except Exception:
            pass


def _frames_from_url(video_url, slug, timestamps=None, headers=None):
    """Extrait des frames DIRECTEMENT depuis une URL vidéo via ffmpeg (seek +
    Range HTTP) — lit seulement quelques Ko, PAS tout le fichier. `headers` =
    dict (User-Agent/Referer pour le CDN Instagram)."""
    tmpdir = DATA_DIR / "tg_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    hdr = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    frames = []
    for ts in (timestamps or ("0.5", "1.2", "2.0", "2.8")):
        out = tmpdir / f"fu_{slug}_{str(ts).replace('.', '_')}.jpg"
        cmd = ["ffmpeg", "-y"]
        if hdr:
            cmd += ["-headers", hdr]
        cmd += ["-ss", str(ts), "-i", video_url, "-frames:v", "1",
                "-vf", "scale=720:-2", "-q:v", "3", str(out)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=40)
            if out.exists() and out.stat().st_size > 1000:
                frames.append(out)
        except Exception:
            pass
    return frames


def ocr_video_url(video_url, second=None, headers=None, full=False, end=None) -> dict:
    """OCR pour le SITE en lisant les frames DIRECTEMENT depuis l'URL (rapide,
    pas de download complet, pas de limite 50 Mo).
    full=True = mode INTELLIGENT : 8 frames sur TOUTE la vidéo + reconstitution
    de la séquence des textes (dédupliquée) — nécessite une clé IA.
    end = borne de FIN (secondes) : l'analyse s'arrête à ce point de la vidéo
    (l'user place le curseur du lecteur là où le texte s'arrête).
    Retourne {ok, text, engine, frame(b64 JPEG de l'image analysée)}."""
    if not _ocr_ready():
        return {"ok": False, "text": "", "error": "Aucun OCR configuré"}
    if not video_url:
        return {"ok": False, "text": "", "error": "url vide"}
    slug = f"url_{int(time.time() * 1000) % 10**9}"
    if full:
        dur = _video_duration(video_url, headers)
        if end is not None:
            try:
                e = float(end)
                if e > 0.5:
                    dur = min(dur, e) if dur else e  # analyse 0 -> point choisi
            except Exception:
                pass
        ts = _full_timestamps(dur)
    else:
        ts = None
        if second is not None and str(second) != "":
            try:
                ts = [f"{max(0.0, float(second)):.1f}"]
            except Exception:
                ts = None
    frames = _frames_from_url(video_url, slug, ts, headers)
    if not frames:
        return {"ok": False, "text": "", "error": "frames non extraites (URL expirée ?)"}
    try:
        anth_key = bool(_env_api_key())
        gem_key = bool(_env_gemini_key())
        prompt = _OCR_PROMPT_FULL if full else None
        mf = 8 if full else 3
        ml = 900 if full else 300
        gem_err = ""
        text = ""
        engine = "tesseract"
        # 1) PRIORITÉ Claude (Anthropic) — lit emojis + texte stylé
        if anth_key:
            text = _ocr_claude(frames, "site", prompt=prompt, max_frames=mf, max_len=ml)
            if text:
                engine = "ia"
        # 2) Gemini si pas de Claude (ou Claude vide)
        if not text and gem_key:
            g = _ocr_gemini(frames, "site", prompt=prompt, max_frames=mf, max_len=ml)
            if g:
                text, engine = g, "gemini"
            else:
                gem_err = _GEMINI_LAST_ERR  # ex: 429 quota
        # 3) Tesseract en dernier recours (pas de dédup en mode full -> message clair)
        if not text:
            if full and not (anth_key or gem_key):
                return {"ok": False, "text": "",
                        "error": "Le mode intelligent nécessite une clé IA (Settings → Clé IA)"}
            t2 = _ocr_tesseract(frames, "site")
            if t2:
                text, engine = t2, "tesseract"
        fb = ""
        try:
            fb = base64.b64encode(Path(frames[0]).read_bytes()).decode()
        except Exception:
            pass
        return {"ok": True, "text": text, "engine": engine, "frame": fb,
                "gemini_key": gem_key, "gemini_err": gem_err, "full": full}
    finally:
        _cleanup_frames(frames, None)


def _cleanup_frames(frames, vid):
    for f in (frames or []):
        try:
            Path(f).unlink()
        except Exception:
            pass
    try:
        if vid:
            Path(vid).unlink()
    except Exception:
        pass


def _env_gemini_key() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if key:
        return key
    try:
        env = Path(__file__).resolve().parent / ".env"
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                return line.strip().split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


_GEMINI_LAST_ERR = ""


def _ocr_gemini(frame_paths, tag: str = "", prompt: str = None,
                max_frames: int = 3, max_len: int = 300) -> str:
    """OCR via Gemini (Google, tier GRATUIT, clé aistudio.google.com) — lit le
    texte STYLÉ et les EMOJIS. Pose la raison d'échec dans _GEMINI_LAST_ERR."""
    global _GEMINI_LAST_ERR
    _GEMINI_LAST_ERR = ""
    key = _env_gemini_key()
    if not key:
        _GEMINI_LAST_ERR = "clé Gemini absente (Settings → Clé IA)"
        return ""
    parts = []
    for fp in frame_paths[:max_frames]:
        try:
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                          "data": base64.b64encode(Path(fp).read_bytes()).decode()}})
        except Exception:
            pass
    if not parts:
        _GEMINI_LAST_ERR = "aucune image à analyser"
        return ""
    parts.append({"text": prompt or _OCR_PROMPT})
    try:
        # clé via header x-goog-api-key (robuste pour les 2 formats Google : AIza… ET AQ.…)
        rr = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.0-flash:generateContent",
            headers={"content-type": "application/json", "x-goog-api-key": key},
            json={"contents": [{"parts": parts}]}, timeout=60)
        try:
            data = rr.json()
        except Exception:
            data = {}
        if rr.status_code != 200:
            msg = (data.get("error") or {}).get("message", "") or (rr.text or "")[:120]
            _GEMINI_LAST_ERR = f"HTTP {rr.status_code} — {msg}"
            _trace(f"ocr Gemini: {_GEMINI_LAST_ERR}")
            return ""
        cands = data.get("candidates") or []
        if not cands:
            _GEMINI_LAST_ERR = "réponse Gemini vide (contenu bloqué ?)"
            return ""
        txt = "".join(p.get("text", "") for p in
                      ((cands[0].get("content") or {}).get("parts") or [])).strip()
        if txt and not txt.upper().startswith("AUCUN"):
            _trace(f"✍️ texte lu (Gemini) {tag}: {txt[:45]}…")
            return txt[:max_len]
        _GEMINI_LAST_ERR = "Gemini n'a détecté aucun texte sur cette image"
        return ""
    except Exception as e:
        _GEMINI_LAST_ERR = str(e)[:140]
        _trace(f"ocr Gemini: {e}")
    return ""


def _transcribe_veille_async(vkey):
    """Lit le texte incrusté de la veille en arrière-plan (thread dédié).
    Marche avec Gemini/IA (clé) OU gratuitement avec Tesseract."""
    if not _ocr_ready():
        return
    threading.Thread(target=_transcribe_veille, args=(vkey,), daemon=True).start()


def _ocr_file_id(file_id: str, tag: str = "") -> str:
    """Lit le texte incrusté d'une vidéo (file_id Telegram). IA si clé, sinon
    Tesseract (gratuit). Retourne le texte, "" si aucun/erreur. Synchrone."""
    if not (file_id and _ocr_ready()):
        return ""
    frames, vid = _extract_frames(file_id, tag)
    try:
        return _run_ocr(frames, tag) if frames else ""
    finally:
        _cleanup_frames(frames, vid)


def _transcribe_veille(vkey):
    v = _VEILLES.get(vkey)
    if not v or v.get("overlay") is not None:
        return
    frames, vid = _extract_frames(v["file_id"], tag=f"({v.get('model')})", slug=f"v_{vkey[1]}")
    try:
        if not frames:
            return
        text = _run_ocr(frames, tag=f"({v.get('model')})")
        v["overlay"] = text[:300] if text else ""  # "" = analysé, pas de texte
        _cache_save()
        # met à jour le message « en attente » avec le texte lu
        cfg = _load()
        _update_pending_caption(cfg, v)
    except Exception as e:
        _trace(f"transcription: {e}")
    finally:
        _cleanup_frames(frames, vid)


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


def send_veille_to_model(model: str, tg_file_id: str, link: str = "", desc: str = "",
                         overlay=None) -> dict:
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
    # 3 MESSAGES SÉPARÉS : ① la vidéo, ② la caption incrustée, ③ la description.
    # Les deux textes répondent TOUJOURS à la vidéo (copie facile, contexte clair).
    def _send_reply_text(txt):
        pp = {"chat_id": bm["chat_id"], "text": txt[:4000],
              "reply_to_message_id": vid_msg, "disable_web_page_preview": True}
        if bm.get("thread"):
            pp["message_thread_id"] = bm["thread"]
        rr = _api("sendMessage", pp)
        return (rr.get("result") or {}).get("message_id") if rr.get("ok") else None

    ov = (overlay or "").strip() if overlay is not None else ""
    cap_msg_id = _send_reply_text(ov) if ov else None
    text_msg_id = _send_reply_text(desc.strip()) if (desc or "").strip() else None
    v = {"file_id": tg_file_id, "caption": (link or "").strip(),
         "desc": (desc or "").strip() or None, "text_msg_id": text_msg_id,
         "cap_msg_id": cap_msg_id,
         "dest_msg_id": None, "model": model, "ts": time.time(), "routed": False}
    # overlay PRÉ-VALIDÉ sur le site -> on l'utilise direct (pas de re-OCR côté TG)
    if overlay is not None:
        v["overlay"] = (overlay or "").strip()
    _VEILLES[(bm["chat_id"], vid_msg)] = v
    _LAST_VEILLE[(bm["chat_id"], bm.get("thread"))] = (time.time(), vid_msg)
    if cfg.get("dest_chat_id"):
        _post_pending(cfg, v, model)
    _cache_save()
    _trace(f"veille envoyée depuis le SITE -> {model}")
    # Lecture du texte incrusté en arrière-plan SEULEMENT si pas pré-validé
    if overlay is None:
        _transcribe_veille_async((bm["chat_id"], vid_msg))
    return {"ok": True}


def _post_pending(cfg: dict, v: dict, model: str):
    """Poste la veille dans le sujet de la modèle — STYLE VEILLE : la vidéo
    SEULE, puis la caption incrustée et la description en messages SÉPARÉS
    qui répondent à la vidéo."""
    tid = _topic_for(cfg, model)
    p = {"chat_id": cfg["dest_chat_id"], "video": v["file_id"]}
    if tid:
        p["message_thread_id"] = tid
    res = _api("sendVideo", p)
    if res.get("ok"):
        v["dest_msg_id"] = (res.get("result") or {}).get("message_id")
        v.setdefault("dest_cap_id", None)
        v.setdefault("dest_desc_id", None)
        _update_pending_caption(cfg, v)
        _trace(f"veille postée dans le sujet {model} (en attente de la modèle)")
    else:
        _trace(f"post veille échoué ({model}) : {res.get('description', '?')}")


def _update_pending_caption(cfg: dict, v: dict):
    """Aligne les messages TEXTE du pending (caption incrustée / description) :
    envoie chaque texte en message séparé (réponse à la vidéo), ou l'édite
    s'il existe déjà (OCR/description arrivés après coup)."""
    if not v.get("dest_msg_id"):
        return
    dest = cfg["dest_chat_id"]
    tid = _topic_for(cfg, v.get("model"))

    def _sync(text, key):
        text = (text or "").strip()
        if not text:
            return
        mid = v.get(key)
        if mid:
            _api("editMessageText", {"chat_id": dest, "message_id": mid,
                                     "text": text[:4000],
                                     "disable_web_page_preview": True})
        else:
            pp = {"chat_id": dest, "text": text[:4000],
                  "reply_to_message_id": v["dest_msg_id"],
                  "disable_web_page_preview": True}
            if tid:
                pp["message_thread_id"] = tid
            rr = _api("sendMessage", pp)
            if rr.get("ok"):
                v[key] = (rr.get("result") or {}).get("message_id")

    _sync(v.get("overlay"), "dest_cap_id")
    _sync(_no_links(v.get("desc")), "dest_desc_id")


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
        if _env_api_key():
            ocr_on = "✅ CLAUDE (Anthropic) — lit le texte stylé ET les emojis, qualité max 🎯"
        elif _env_gemini_key():
            ocr_on = "✅ GEMINI (Google, gratuit) — lit le texte stylé ET les emojis"
        elif _tesseract_available():
            ocr_on = "✅ GRATUIT (Tesseract local) — texte net OK, mais PAS les emojis"
        else:
            ocr_on = "❌ aucun OCR configuré → texte incrusté non lu"
        _reply(chat_id, f"🔍 Dernières décisions du routeur :\n{ev}\n\n🤖 OCR : {ocr_on}"
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
            # ACCUMULE : plusieurs messages entre 2 reels = la description complète
            prev = (v.get("desc") or "").strip()
            if text not in prev:
                v["desc"] = (prev + "\n" + text).strip() if prev else text
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
        # Lecture IA du texte incrusté (3 premières secondes) en arrière-plan
        _transcribe_veille_async((chat_id, msg.get("message_id")))
        return

    # ---- VIDÉO EN RÉPONSE = LA MODÈLE A FAIT SA VERSION ----
    raw_fid = (msg.get("video") or {}).get("file_id")
    # retrouve la veille : réponse à la vidéo, ou au texte de description
    v = _VEILLES.get((chat_id, ref.get("message_id")))
    if not v:
        for vv in _VEILLES.values():
            if (ref.get("message_id") in (vv.get("text_msg_id"), vv.get("cap_msg_id"))
                    and vv.get("model") == model):
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
    # Si la veille n'a pas de description liée, prends le DERNIER texte long vu
    # dans le sujet (l'user écrit la description juste après le reel) — <2 h.
    if not (v.get("desc") or "").strip():
        lt = _LAST_TEXT.get((chat_id, msg.get("message_thread_id")))
        if lt and now - lt[0] < 7200 and (lt[1] or "").strip():
            v["desc"] = lt[1]
            _cache_save()
            _trace(f"description récupérée du sujet ({model}) : {lt[1][:40]}…")
    # Marque la veille comme routée TOUT DE SUITE (évite un double-routage si le
    # poller revoit le message) puis fait le traitement LOURD (téléchargements +
    # ffmpeg swap son + ré-upload) en ARRIÈRE-PLAN : le poller reste réactif et
    # plusieurs vidéos se traitent en même temps au lieu de faire la queue.
    v["routed"] = True
    _cache_save()
    _trace(f"réponse reçue ({model}) — traitement du son en arrière-plan…")
    threading.Thread(
        target=_finish_route,
        args=(cfg, v, raw_fid, dest, tid, model, chat_id,
              ref.get("message_id"), msg.get("message_id")),
        daemon=True, name=f"route-{model}").start()


def _finish_route(cfg, v, raw_fid, dest, tid, model, chat_id, reply_msg_id, video_msg_id):
    """Traitement LOURD d'une réponse de modèle, en ARRIÈRE-PLAN : OCR de secours,
    swap du son (son de l'exemple sur la vidéo de la modèle), envoi de l'album,
    textes séparés, suppression des messages « en attente », réaction 🔥."""
    caption = _veille_caption(v)
    # FALLBACK : légende vide (description perdue / OCR pas encore fait) -> on lit
    # le texte incrusté de la vidéo exemple MAINTENANT (l'album a toujours un texte)
    if not caption.strip() and v.get("file_id") and not v.get("overlay"):
        ocr = _ocr_file_id(v["file_id"], f"({model} fallback)")
        if ocr:
            v["overlay"] = ocr
            _cache_save()

    res = {"ok": False}
    if v.get("file_id") and raw_fid:
        # 🎵 SON DE L'EXEMPLE sur la vidéo de la modèle (son d'origine de la brute
        # RETIRÉ) → album [exemple, brute-avec-le-bon-son]. Si impossible
        # (>20 Mo, exemple sans audio, ffmpeg…), on retombe sur l'album normal.
        slug = f"{model}_{video_msg_id}"
        swapped = _swap_audio(raw_fid, v["file_id"], slug)
        if swapped:
            res = _send_album_local_brute(dest, tid, v["file_id"], swapped)
            try:
                swapped.unlink()
            except Exception:
                pass
            if res.get("ok"):
                _trace(f"🎵 son de l'exemple posé sur la vidéo de {model}")
            else:
                _trace(f"swap son: envoi KO ({res.get('description', '?')}) -> album normal")
        # STYLE VEILLE : album SANS légende, les textes partent en messages séparés
        if not res.get("ok"):
            media = [{"type": "video", "media": v["file_id"]},
                     {"type": "video", "media": raw_fid}]
            p = {"chat_id": dest, "media": media}
            if tid:
                p["message_thread_id"] = tid
            res = _api("sendMediaGroup", p)
    elif raw_fid:
        p = {"chat_id": dest, "video": raw_fid}
        if tid:
            p["message_thread_id"] = tid
        res = _api("sendVideo", p)
    if not res.get("ok"):
        _trace(f"album KO ({model}) : {res.get('description', '?')} -> fallback copie")
        _copy(dest, tid, chat_id, reply_msg_id)
        res = _copy(dest, tid, chat_id, video_msg_id)

    if res.get("ok"):
        # textes (caption incrustée, description) en MESSAGES SÉPARÉS, en réponse
        # au premier média de l'album
        first_id = None
        rr = res.get("result")
        if isinstance(rr, list) and rr:
            first_id = rr[0].get("message_id")
        elif isinstance(rr, dict):
            first_id = rr.get("message_id")
        for txt in _veille_texts(v):
            pp = {"chat_id": dest, "text": txt[:4000], "disable_web_page_preview": True}
            if first_id:
                pp["reply_to_message_id"] = first_id
            if tid:
                pp["message_thread_id"] = tid
            _api("sendMessage", pp)
        # remplace les messages « en attente » (vidéo + textes) par l'album
        for key in ("dest_msg_id", "dest_cap_id", "dest_desc_id"):
            if v.get(key):
                _api("deleteMessage", {"chat_id": dest, "message_id": v[key]})
                v[key] = None
        STATUS["routed"] = STATUS.get("routed", 0) + 1
        _cache_save()
        _trace(f"✅ routé ({model}) -> album dans le sujet {tid}")
        _api("setMessageReaction", {
            "chat_id": chat_id, "message_id": video_msg_id,
            "reaction": [{"type": "emoji", "emoji": "🔥"}],
        })
    else:
        # échec TOTAL (même la copie de secours) : on rouvre la veille pour
        # qu'une nouvelle réponse puisse retenter
        v["routed"] = False
        _cache_save()
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
