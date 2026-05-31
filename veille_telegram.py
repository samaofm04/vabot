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
    """Compat : wrapper qui retourne juste le video_url frais."""
    data = refresh_post_data(post_url)
    return data.get("video_url") or None


def _scrape_og_caption(post_url: str) -> str:
    """Fallback no-auth : recupere le og:description meta tag de la page IG
    publique. Ne marche pas toujours (IG cache certains posts derriere un
    wall) mais utile quand instaloader n est pas configure."""
    if not post_url:
        return ""
    try:
        import re as _re
        from html import unescape
        r = requests.get(
            post_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; Telegrambot/1.0; "
                    "+http://telegram.org)"
                ),
                "Accept": "text/html",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
            allow_redirects=True,
        )
        if r.status_code != 200:
            return ""
        # og:description ou meta description
        for pat in (
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
        ):
            m = _re.search(pat, r.text)
            if m:
                desc = unescape(m.group(1)).strip()
                # IG met souvent un prefixe "X likes, Y comments - @user on..."
                # On extrait juste le texte de la legende qui est apres le ':'
                # Format typique : '127 likes, 8 comments - "Caption ici"'
                # ou '@user on Instagram: "Caption ici"'
                quote_m = _re.search(r'[:""]\s*["“]([^"”]+)["”]', desc)
                if quote_m:
                    return quote_m.group(1).strip()[:1000]
                # Fallback : on prend tout apres le dernier ':' si y en a un
                if ':' in desc:
                    return desc.rsplit(':', 1)[1].strip().strip('"').strip()[:1000]
                return desc[:1000]
    except Exception:
        pass
    return ""


def refresh_post_data(post_url: str) -> Dict[str, str]:
    """Re-scrape video_url ET caption depuis le permalink IG.

    Strategie multi-source :
    - instaloader (si configure) : video_url + caption en une passe
    - fallback no-auth : og:description meta tag pour le caption seulement

    Retourne {video_url, caption}. Tous les champs vides si tout echoue.
    """
    import re as _re
    out: Dict[str, str] = {"video_url": "", "caption": ""}
    if not post_url:
        return out
    m = _re.search(r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)', post_url)
    if not m:
        return out
    shortcode = m.group(1)
    # 1) instaloader (le plus complet si auth dispo)
    try:
        import insta_scraper
        auth_ok = True
        if hasattr(insta_scraper, "is_auth_configured"):
            auth_ok = bool(insta_scraper.is_auth_configured())
        if auth_ok:
            loader = insta_scraper._make_loader()
            if loader is not None:
                import instaloader
                post = instaloader.Post.from_shortcode(loader.context, shortcode)
                if post.is_video:
                    out["video_url"] = post.video_url or ""
                out["caption"] = (post.caption or "")[:1000]
    except Exception:
        pass
    # 2) Fallback no-auth pour le caption uniquement
    if not out["caption"]:
        out["caption"] = _scrape_og_caption(post_url)
    return out


def send_video_from_url(video_url: str, caption: str = "",
                        fallback_url: str = "",
                        followup_text: str = "") -> Dict[str, Any]:
    """Telecharge une video IG et la poste sur Telegram via sendVideo.

    Comportement comme un bot downloader Discord/Telegram :
    - On telecharge la video Instagram en local (bytes)
    - On l upload sur Telegram via sendVideo (multipart)
    - La caption (lien) apparait en dessous de la video
    - Si followup_text est fourni, on envoie un 2e message texte juste
      apres (utilise pour separer la description de la video)

    Args:
        video_url      : URL CDN de la video Instagram
        caption        : Caption sous la video (typiquement juste le lien IG)
        fallback_url   : Si le download / sendVideo echoue, on retombe sur
                         sendMessage avec ce lien Instagram
        followup_text  : Texte d un 2e message envoye juste apres la video
                         (typiquement la description du reel)

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
        # Lien Instagram en premier message
        res = send_url(fallback_url, caption=caption)
        if res.get("ok"):
            res["mode"] = "link"
            res["fallback_reason"] = reason
            # 2e message texte avec la description si dispo
            if followup_text and followup_text.strip():
                try:
                    requests.post(
                        f"{TG_API_BASE}/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": followup_text.strip()[:4000],
                            "disable_web_page_preview": True,
                            "reply_to_message_id": res.get("message_id"),
                        },
                        timeout=15,
                    )
                except Exception:
                    pass
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
        msg_id = j.get("result", {}).get("message_id")
    except Exception as e:
        return _fallback(f"Reponse invalide : {e}")

    # 3) Followup texte (la description IG) en message separe
    if followup_text and followup_text.strip():
        try:
            requests.post(
                f"{TG_API_BASE}/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": followup_text.strip()[:4000],  # Telegram cap 4096
                    "disable_web_page_preview": True,  # Pas d apercu, c est juste du texte
                    "reply_to_message_id": msg_id,  # Threade sous la video
                },
                timeout=15,
            )
        except Exception:
            pass  # Followup pas critique, on log pas
    return {
        "ok": True,
        "mode": "video",
        "message_id": msg_id,
    }


def test_connection() -> Dict[str, Any]:
    """Test : envoie un message court pour verifier que le bot peut poster."""
    cfg = load_config()
    if not cfg.get("bot_token") or not cfg.get("chat_id"):
        return {"ok": False, "error": "Pas de config"}
    return send_url("✅ Test de connexion VA Bot - Veille Telegram")
