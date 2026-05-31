"""veille_telegram.py - Envoi de liens de reels au bot downloader sur Telegram.

Config stockee dans data/veille_telegram.json :
{
    "bot_token": "...",       # token du BOT TELEGRAM (pas celui du downloader)
    "chat_id": "-100..."       # ID du groupe / chat ou poster
}

Usage typique :
- L user configure une fois le token + chat_id depuis Settings
- Quand il clique 'Envoyer a Veille' sur un reel, on POST l URL au chat
- Le bot downloader (qui est dans ce chat) detecte le lien et telecharge
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional

import requests

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "veille_telegram.json"
TG_API_BASE = "https://api.telegram.org"
TIMEOUT = 15


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("bot_token")) and bool(cfg.get("chat_id"))


def set_credentials(bot_token: str, chat_id: str):
    cfg = load_config()
    cfg["bot_token"] = (bot_token or "").strip()
    cfg["chat_id"] = (chat_id or "").strip()
    save_config(cfg)


def send_url(url: str, caption: Optional[str] = None) -> Dict[str, Any]:
    """Envoie un URL au chat configure. Retourne {ok, result|error}.

    Note : si le caption contient deja l URL, on ne la duplique pas.
    """
    cfg = load_config()
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id:
        return {"ok": False, "error": "Bot Telegram non configure"}

    # Construit le texte final - evite la duplication de l URL
    if caption:
        if url and url in caption:
            text = caption  # URL deja dans le caption, pas besoin de l ajouter
        else:
            text = f"{caption}\n{url}" if url else caption
    else:
        text = url
    try:
        r = requests.post(
            f"{TG_API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=TIMEOUT,
        )
    except Exception as e:
        return {"ok": False, "error": f"Erreur reseau : {e}"}
    if r.status_code != 200:
        try:
            j = r.json()
            return {"ok": False, "error": f"HTTP {r.status_code}: {j.get('description', '?')}"}
        except Exception:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
    try:
        j = r.json()
        if not j.get("ok"):
            return {"ok": False, "error": j.get("description", "?")}
        return {"ok": True, "message_id": j.get("result", {}).get("message_id")}
    except Exception as e:
        return {"ok": False, "error": f"Reponse invalide : {e}"}


# ============ Download + sendVideo (comme un bot downloader Discord) ============

_IG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "Instagram 250.0.0.21.109"
    ),
    "Accept": "*/*",
    "Accept-Language": "fr-FR,en-US;q=0.7,en;q=0.3",
}


def download_video_bytes(video_url: str, timeout: int = 25) -> Optional[bytes]:
    """Telecharge une video depuis un CDN Instagram.

    Retourne les bytes (ou None si erreur / >50 MB / timeout).
    - timeout = 25s (un reel 10-30s pese 2-15 MB, doit downloader en ~5s)
    - 50 MB max (limite Telegram bot upload)
    """
    if not video_url:
        return None
    try:
        r = requests.get(video_url, headers=_IG_HEADERS, timeout=timeout, stream=True)
        if r.status_code not in (200, 206):
            return None
        max_size = 50 * 1024 * 1024  # 50 MB
        chunks = []
        total = 0
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total > max_size:
                return None  # Trop gros, abandon
        return b"".join(chunks)
    except Exception:
        return None


def _refresh_video_url(post_url: str) -> Optional[str]:
    """Re-scrape le video_url depuis le permalink IG (le stocke peut etre
    expire - les CDN IG signent les URLs avec une TTL de quelques heures).

    Utilise instaloader si configure et dispo. Retourne None sinon
    rapidement (pas de hang).
    """
    import re as _re
    if not post_url:
        return None
    m = _re.search(r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)', post_url)
    if not m:
        return None
    shortcode = m.group(1)
    try:
        import insta_scraper
        # Si pas d auth IG configuree, ne pas tenter (evite un hang)
        if hasattr(insta_scraper, "is_auth_configured"):
            if not insta_scraper.is_auth_configured():
                return None
        loader = insta_scraper._make_loader()
        if loader is None:
            return None
        import instaloader
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        if post.is_video:
            return post.video_url
    except Exception:
        pass
    return None


def send_video_from_url(video_url: str, caption: str = "",
                        fallback_url: str = "") -> Dict[str, Any]:
    """Telecharge une video IG et la poste sur Telegram via sendVideo.

    Comportement comme un bot downloader Discord/Telegram :
    - On telecharge la video Instagram en local (bytes)
    - On l upload sur Telegram via sendVideo (multipart)
    - La caption (description + lien) apparait en dessous de la video

    Args:
        video_url    : URL CDN de la video Instagram (champ video_url du reel)
        caption      : Texte de caption (max 1024 char par Telegram)
        fallback_url : Si le download / sendVideo echoue, on retombe sur
                       sendMessage avec ce lien Instagram

    Retourne {ok, mode: "video"|"link", message_id|error}.
    """
    cfg = load_config()
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id:
        return {"ok": False, "error": "Bot Telegram non configure"}

    def _fallback(reason: str) -> Dict[str, Any]:
        if not fallback_url:
            return {"ok": False, "error": reason}
        res = send_url(fallback_url, caption=caption)
        if res.get("ok"):
            res["mode"] = "link"
            res["fallback_reason"] = reason
        return res

    # 1) Telecharge la video depuis l URL IG
    video_bytes = download_video_bytes(video_url)
    last_err = ""
    if not video_bytes:
        last_err = "URL video manquante / expiree / >50MB"
        # Retry : re-scrape un video_url frais depuis le permalink IG
        fresh = _refresh_video_url(fallback_url)
        if fresh and fresh != video_url:
            video_bytes = download_video_bytes(fresh)
            if video_bytes:
                last_err = ""
            else:
                last_err = "URL refresh OK mais download IG echoue"
    if not video_bytes:
        return _fallback(f"Telechargement impossible : {last_err}")

    # 2) Upload via sendVideo (multipart, fichier en memoire)
    try:
        r = requests.post(
            f"{TG_API_BASE}/bot{token}/sendVideo",
            data={
                "chat_id": chat_id,
                "caption": (caption or "")[:1024],
                "supports_streaming": "true",
            },
            files={"video": ("reel.mp4", video_bytes, "video/mp4")},
            timeout=60,  # 60s suffit pour un upload de <50MB
        )
    except Exception as e:
        return _fallback(f"Erreur reseau Telegram : {e}")

    if r.status_code != 200:
        try:
            j = r.json()
            return _fallback(f"HTTP {r.status_code}: {j.get('description', '?')}")
        except Exception:
            return _fallback(f"HTTP {r.status_code}")

    try:
        j = r.json()
        if not j.get("ok"):
            return _fallback(j.get("description", "Reponse Telegram non ok"))
        return {
            "ok": True,
            "mode": "video",
            "message_id": j.get("result", {}).get("message_id"),
        }
    except Exception as e:
        return _fallback(f"Reponse invalide : {e}")


def test_connection() -> Dict[str, Any]:
    """Test : envoie un message court pour verifier que le bot peut poster."""
    cfg = load_config()
    if not cfg.get("bot_token") or not cfg.get("chat_id"):
        return {"ok": False, "error": "Pas de config"}
    return send_url("✅ Test de connexion VA Bot - Veille Telegram")
