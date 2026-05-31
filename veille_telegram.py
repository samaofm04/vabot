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
    """Envoie un URL au chat configure. Retourne {ok, result|error}."""
    cfg = load_config()
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id:
        return {"ok": False, "error": "Bot Telegram non configure"}

    text = url
    if caption:
        text = f"{caption}\n{url}"
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


def download_video_bytes(video_url: str, timeout: int = 60) -> Optional[bytes]:
    """Telecharge une video depuis un CDN Instagram.

    Retourne les bytes (ou None si erreur / >50 MB).
    Telegram limite les uploads de bot a 50 MB - les reels typiques (10-30s)
    sont generalement < 10 MB.
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
    if not video_bytes:
        return _fallback("Telechargement video impossible (URL morte ou >50MB)")

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
            timeout=120,
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
