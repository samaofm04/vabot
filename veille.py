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


def set_prepared(reel_id: str, overlay: str = "", desc: str = "", models: str = "") -> bool:
    """Enregistre un BROUILLON « prêt » pour un reel : caption incrustée validée
    (overlay), description, et modèles choisis (chaîne « a,b,c »). Rend la carte
    « PRÊT » sur la grille et pré-remplit le modal à la réouverture."""
    data = _load()
    for r in data["reels"]:
        if r.get("id") == reel_id:
            r["prepared"] = True
            r["prep_overlay"] = overlay or ""
            r["prep_desc"] = desc or ""
            r["prep_models"] = models or ""
            r["prepared_at"] = datetime.utcnow().isoformat(timespec="seconds")
            _save(data)
            return True
    return False


def mark_ready(reel_id: str, fallback_desc: str = "") -> bool:
    """Marque un reel « PRÊT » depuis la grille (interrupteur de la carte), SANS
    écraser une caption déjà préparée dans le modal. Initialise juste les champs
    manquants."""
    data = _load()
    for r in data["reels"]:
        if r.get("id") == reel_id:
            r["prepared"] = True
            r.setdefault("prep_overlay", "")
            if not (r.get("prep_desc") or "").strip() and fallback_desc:
                r["prep_desc"] = fallback_desc
            r.setdefault("prep_desc", "")
            r.setdefault("prep_models", "")
            r["prepared_at"] = datetime.utcnow().isoformat(timespec="seconds")
            _save(data)
            return True
    return False


def clear_prepared(reel_id: str) -> bool:
    """Retire le brouillon « prêt » d'un reel."""
    data = _load()
    for r in data["reels"]:
        if r.get("id") == reel_id:
            changed = False
            for k in ("prepared", "prep_overlay", "prep_desc", "prep_models", "prepared_at"):
                if k in r:
                    r.pop(k, None)
                    changed = True
            if changed:
                _save(data)
            return changed
    return False


def update_reel(reel_id: str, **fields) -> bool:
    """Met a jour des champs d un reel stocke (caption, video_url, thumb...)."""
    if not fields:
        return False
    data = _load()
    for r in data["reels"]:
        if r.get("id") == reel_id:
            for k, v in fields.items():
                if v:
                    r[k] = v
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
