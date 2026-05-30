"""veille.py - Stockage des reels bookmarked pour la veille.

Stockage : data/veille_reels.json
Structure :
{
    "reels": [
        {
            "id": "abc123",         # unique
            "url": "https://...",   # URL du reel insta
            "video_url": "https://...",
            "thumb": "https://...",
            "caption": "...",
            "owner": "@xxx",
            "owner_pp": "https://...",
            "views": 12000,
            "likes": 500,
            "comments": 30,
            "added_at": "2026-05-30T14:32:11",  # ISO date
            "sent_to_telegram": false,
            "sent_at": null
        }
    ]
}
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, List

DATA_DIR = Path("data")
VEILLE_FILE = DATA_DIR / "veille_reels.json"


def _load() -> Dict[str, Any]:
    if not VEILLE_FILE.exists():
        return {"reels": []}
    try:
        data = json.loads(VEILLE_FILE.read_text(encoding="utf-8"))
        if "reels" not in data:
            data["reels"] = []
        return data
    except Exception:
        return {"reels": []}


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VEILLE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_reels() -> List[Dict[str, Any]]:
    return _load().get("reels", [])


def is_bookmarked(url: str) -> bool:
    if not url:
        return False
    for r in list_reels():
        if r.get("url") == url:
            return True
    return False


def add_reel(reel: Dict[str, Any]) -> Dict[str, Any]:
    """Bookmark un reel. Retourne {ok, reel|already_exists}."""
    url = (reel.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "URL manquant"}
    data = _load()
    for r in data["reels"]:
        if r.get("url") == url:
            return {"ok": False, "error": "already_exists", "reel_id": r.get("id")}
    new_reel = {
        "id": uuid.uuid4().hex[:12],
        "url": url,
        "video_url": reel.get("video_url", ""),
        "thumb": reel.get("thumb", ""),
        "caption": (reel.get("caption") or "")[:500],
        "owner": reel.get("owner", ""),
        "owner_pp": reel.get("owner_pp", ""),
        "views": int(reel.get("views") or 0),
        "likes": int(reel.get("likes") or 0),
        "comments": int(reel.get("comments") or 0),
        "added_at": datetime.utcnow().isoformat(timespec="seconds"),
        "sent_to_telegram": False,
        "sent_at": None,
    }
    data["reels"].insert(0, new_reel)  # plus recent en haut
    _save(data)
    return {"ok": True, "reel": new_reel}


def remove_reel(reel_id: str) -> bool:
    data = _load()
    before = len(data["reels"])
    data["reels"] = [r for r in data["reels"] if r.get("id") != reel_id]
    if len(data["reels"]) != before:
        _save(data)
        return True
    return False


def remove_by_url(url: str) -> bool:
    data = _load()
    before = len(data["reels"])
    data["reels"] = [r for r in data["reels"] if r.get("url") != url]
    if len(data["reels"]) != before:
        _save(data)
        return True
    return False


def mark_sent(reel_id: str) -> bool:
    data = _load()
    for r in data["reels"]:
        if r.get("id") == reel_id:
            r["sent_to_telegram"] = True
            r["sent_at"] = datetime.utcnow().isoformat(timespec="seconds")
            _save(data)
            return True
    return False


def get_reel(reel_id: str) -> Dict[str, Any]:
    for r in list_reels():
        if r.get("id") == reel_id:
            return r
    return {}


def reels_by_day() -> Dict[str, List[Dict[str, Any]]]:
    """Retourne {YYYY-MM-DD: [reels...]} trie par jour decroissant."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in list_reels():
        d = (r.get("added_at") or "")[:10] or "unknown"
        out.setdefault(d, []).append(r)
    return out


def stats() -> Dict[str, Any]:
    reels = list_reels()
    by_day = reels_by_day()
    return {
        "total": len(reels),
        "sent_count": sum(1 for r in reels if r.get("sent_to_telegram")),
        "unsent_count": sum(1 for r in reels if not r.get("sent_to_telegram")),
        "days_count": len(by_day),
        "today_count": len(by_day.get(date.today().isoformat(), [])),
    }
