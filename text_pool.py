"""text_pool.py - Bibliotheque de textes (Names, Usernames, Bios, CTAs).

Pools de textes a piocher pour les VAs (display names, usernames Insta,
bios de profil, story CTAs). Chaque entree peut etre marquee comme
utilisee par une identite specifique.

Stockage : data/text_pool.json
Structure :
{
    "names":     [{"id": "uuid", "text": "...", "used_by": null|"<identity>", "added_at": "ISO"}],
    "usernames": [...],
    "bios":      [...],
    "ctas":      [...]
}
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

DATA_DIR = Path("data")
POOL_FILE = DATA_DIR / "text_pool.json"

# Categories supportees (utilises comme cles json et tab IDs)
CATEGORIES = ("names", "usernames", "bios", "ctas")

CATEGORY_META = {
    "names": {
        "label": "Names",
        "icon": "👤",
        "color": "#3b82f6",
        "placeholder": "Sophie Martin",
        "desc": "Display names (nom affiche sur le profil Insta)",
        "max_len": 50,
    },
    "usernames": {
        "label": "Usernames",
        "icon": "@",
        "color": "#a855f7",
        "placeholder": "sophie_mtn22",
        "desc": "Handles @ pour le compte Instagram",
        "max_len": 30,
    },
    "bios": {
        "label": "Bios",
        "icon": "📝",
        "color": "#22c55e",
        "placeholder": "21 · 🇫🇷 · DM me",
        "desc": "Bios de profil Insta (max 150 char)",
        "max_len": 150,
    },
    "ctas": {
        "label": "CTAs",
        "icon": "📲",
        "color": "#f59e0b",
        "placeholder": "Lien dans la bio 💋",
        "desc": "Textes call-to-action pour story / posts",
        "max_len": 200,
    },
}


def _load() -> Dict[str, Any]:
    if not POOL_FILE.exists():
        return {c: [] for c in CATEGORIES}
    try:
        data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
        for c in CATEGORIES:
            if c not in data:
                data[c] = []
        return data
    except Exception:
        return {c: [] for c in CATEGORIES}


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_entries(category: str, only_available: bool = False) -> List[Dict[str, Any]]:
    if category not in CATEGORIES:
        return []
    items = _load().get(category, [])
    if only_available:
        items = [x for x in items if not x.get("used_by")]
    return items


def add_entry(category: str, text: str) -> Dict[str, Any]:
    """Ajoute une entree au pool. Retourne l entry ou None si invalide."""
    if category not in CATEGORIES:
        return {"ok": False, "error": "categorie invalide"}
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "vide"}
    max_len = CATEGORY_META[category]["max_len"]
    if len(text) > max_len:
        text = text[:max_len]
    data = _load()
    # Dedupe : skip si meme texte deja present
    for e in data[category]:
        if e.get("text") == text:
            return {"ok": False, "error": "already_exists", "entry": e}
    entry = {
        "id": uuid.uuid4().hex[:12],
        "text": text,
        "used_by": None,
        "added_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    data[category].append(entry)
    _save(data)
    return {"ok": True, "entry": entry}


def add_bulk(category: str, raw_text: str) -> Dict[str, Any]:
    """Bulk add : prend du texte multi-ligne et ajoute chaque ligne non vide."""
    if category not in CATEGORIES:
        return {"ok": False, "error": "categorie invalide"}
    lines = [l.strip() for l in (raw_text or "").splitlines()]
    added = 0
    dupes = 0
    for line in lines:
        if not line:
            continue
        res = add_entry(category, line)
        if res.get("ok"):
            added += 1
        elif res.get("error") == "already_exists":
            dupes += 1
    return {"ok": True, "added": added, "duplicates": dupes}


def delete_entry(category: str, entry_id: str) -> bool:
    if category not in CATEGORIES:
        return False
    data = _load()
    before = len(data[category])
    data[category] = [x for x in data[category] if x.get("id") != entry_id]
    if len(data[category]) != before:
        _save(data)
        return True
    return False


def mark_used(category: str, entry_id: str, identity: str) -> bool:
    """Marque une entree comme utilisee par une identite (ou None pour reset)."""
    if category not in CATEGORIES:
        return False
    data = _load()
    for e in data[category]:
        if e.get("id") == entry_id:
            e["used_by"] = (identity or "").strip() or None
            if e["used_by"]:
                e["used_at"] = datetime.utcnow().isoformat(timespec="seconds")
            _save(data)
            return True
    return False


def pick_next(category: str) -> Optional[Dict[str, Any]]:
    """Renvoie la premiere entree non utilisee (FIFO)."""
    for e in list_entries(category, only_available=True):
        return e
    return None


def stats() -> Dict[str, Any]:
    """Stats par categorie : total, available, used."""
    data = _load()
    out: Dict[str, Any] = {}
    for c in CATEGORIES:
        items = data.get(c, [])
        used = sum(1 for x in items if x.get("used_by"))
        out[c] = {
            "total": len(items),
            "used": used,
            "available": len(items) - used,
        }
    return out
