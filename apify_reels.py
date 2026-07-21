"""apify_reels.py — Récupère les video_url des reels via l'actor Apify
`presetshubham/instagram-reel-downloader`.

Apify fait l'extraction avec SES proxies -> le compte Instagram de l'agence
n'est JAMAIS utilisé (aucun cookie, aucun risque de ban). L'actor prend une
LISTE de liens et renvoie {caption, likes, comments, owner_username, video_url}
par reel. On l'utilise comme source PRIORITAIRE du pré-téléchargement : un seul
appel batch résout des dizaines de reels d'un coup.

Le token API Apify est stocké dans data/apify_config.json (gitignore, VPS-only).
JAMAIS commité — même règle que le token MyPuls.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Any, List

import requests

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "apify_config.json"
ACTOR = "presetshubham~instagram-reel-downloader"
BASE = "https://api.apify.com/v2"


def _load() -> dict:
    try:
        d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def save_token(token: str):
    d = _load()
    d["token"] = (token or "").strip()
    _save(d)


def get_token() -> str:
    return (_load().get("token") or "").strip()


def configured() -> bool:
    return bool(get_token())


def _shortcode(url: str) -> str:
    m = re.search(r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)', url or "")
    return m.group(1) if m else ""


def test_token() -> dict:
    """Vérifie le token via /users/me. {ok, user|error}."""
    tok = get_token()
    if not tok:
        return {"ok": False, "error": "Aucun token Apify"}
    try:
        r = requests.get(f"{BASE}/users/me?token={tok}", timeout=20)
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code} (token invalide ?)"}
        d = (r.json() or {}).get("data") or {}
        return {"ok": True, "user": d.get("username") or d.get("id") or "?"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fetch_video_urls(reel_urls: List[str], timeout: int = 240) -> Dict[str, Dict[str, Any]]:
    """Résout une liste de liens reels via l'actor Apify (un seul run batch).

    Retourne {shortcode: {video_url, caption, likes, comments, owner}}.
    Silencieux en cas d'erreur (retourne ce qu'il a) : l'appelant retombe sur
    ses autres méthodes.
    """
    tok = get_token()
    urls = [u for u in (reel_urls or []) if u]
    if not tok or not urls:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        r = requests.post(
            f"{BASE}/acts/{ACTOR}/run-sync-get-dataset-items?token={tok}",
            json={"reelLinks": urls, "proxyConfiguration": {"useApifyProxy": True}},
            timeout=timeout,
        )
        if r.status_code not in (200, 201):
            return {}
        items = r.json()
        if not isinstance(items, list):
            return {}
        # repli positionnel : si l'actor renvoie autant d'items que d'URLs
        # envoyées et sans champ source, item[i] correspond à urls[i]
        positional = len(items) == len(urls)
        for idx, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            vu = (it.get("video_url") or "").strip()
            if not vu:
                continue
            sc = (it.get("shortcode") or _shortcode(it.get("url") or "")
                  or _shortcode(it.get("reelLink") or ""))
            if not sc and positional:
                sc = _shortcode(urls[idx])
            if not sc:
                continue
            out[sc] = {
                "video_url": vu,
                "caption": (it.get("caption") or "").strip(),
                "likes": it.get("likes"),
                "comments": it.get("comments"),
                "owner": it.get("owner_username") or "",
            }
    except Exception:
        return out
    return out
