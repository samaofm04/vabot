"""mypuls_creator_settings.py - Settings MyPuls Live : global + par createur.

Le user veut :
- HORAIRES / DATES / SLOTS : partages entre TOUS les createurs (changement
  sur Amelia se propage a Julia, Lola, etc.)
- CAPTIONS : par identite (chaque createur a ses propres captions)
- MEDIA POOL : par identite (chaque createur a sa propre bibliotheque)

Stockage : data/mypuls_creator_settings.json
Structure :
{
    "global": {
        "start_date": "...",
        "end_date": "...",
        "infinite_mode": false,
        "mode_active": "autopost",
        "posts": {"count": 9, "slots": [...]},
        "stories": {"count": 0, "slots": []},
        "auto_delete": {...},
        "updated_at": "ISO"
    },
    "creators": {
        "769": {
            "captions": ["..."],
            "media_pool": ["abc", "def"],
            "updated_at": "ISO"
        }
    }
}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

DATA_DIR = Path("data")
SETTINGS_FILE = DATA_DIR / "mypuls_creator_settings.json"

# Defaults globaux (partages) - 14 slots posts comme demande par l user
DEFAULT_GLOBAL = {
    "start_date": "",
    "end_date": "",
    "infinite_mode": False,
    "mode_active": "autopost",
    "posts": {
        "count": 14,
        "slots": [
            {"time": "01:00", "visibility": "public"},   # 01:00 AM
            {"time": "02:00", "visibility": "private"},  # 02:00 AM
            {"time": "08:00", "visibility": "public"},   # 08:00 AM
            {"time": "08:00", "visibility": "private"},  # 08:00 AM (doublon)
            {"time": "13:00", "visibility": "public"},   # 01:00 PM
            {"time": "15:00", "visibility": "private"},  # 03:00 PM
            {"time": "15:00", "visibility": "public"},   # 03:00 PM (doublon)
            {"time": "16:00", "visibility": "private"},  # 04:00 PM
            {"time": "18:00", "visibility": "public"},   # 06:00 PM
            {"time": "19:00", "visibility": "private"},  # 07:00 PM
            {"time": "20:00", "visibility": "public"},   # 08:00 PM
            {"time": "21:00", "visibility": "private"},  # 09:00 PM
            {"time": "22:00", "visibility": "public"},   # 10:00 PM
            {"time": "23:00", "visibility": "private"},  # 11:00 PM
        ],
    },
    "stories": {
        "count": 0,
        "slots": [],
    },
    "auto_delete": {
        "enabled": False,
        "after_days": None,
        "from_date": None,
    },
}

# Defaults par createur (les fields per-identite)
DEFAULT_CREATOR = {
    "captions": [],
    "media_pool": [],
}


def _load() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {"global": {}, "creators": {}}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        # Migration depuis l ancien format (per-creator complet)
        if "creators" in data and "global" not in data:
            data = _migrate_from_v1(data)
        if "global" not in data:
            data["global"] = {}
        if "creators" not in data:
            data["creators"] = {}
        return data
    except Exception:
        return {"global": {}, "creators": {}}


def _migrate_from_v1(old_data: Dict[str, Any]) -> Dict[str, Any]:
    """Migration depuis l ancien schema ou TOUT etait per-creator."""
    new_data: Dict[str, Any] = {"global": {}, "creators": {}}
    creators = old_data.get("creators", {})
    if not creators:
        return new_data
    # Prend les settings du PREMIER creator comme global (les horaires, dates...)
    first_cid = next(iter(creators))
    first = creators[first_cid]
    global_fields = ("start_date", "end_date", "infinite_mode", "mode_active",
                     "posts", "stories", "auto_delete")
    for f in global_fields:
        if f in first:
            new_data["global"][f] = first[f]
    new_data["global"]["updated_at"] = first.get("updated_at", "")
    # Garde les fields per-creator pour chaque
    for cid, settings in creators.items():
        creator_data = {}
        for f in ("captions", "media_pool"):
            if f in settings:
                creator_data[f] = settings[f]
        if "updated_at" in settings:
            creator_data["updated_at"] = settings["updated_at"]
        if creator_data:
            new_data["creators"][cid] = creator_data
    return new_data


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _normalize_id(creator_id) -> str:
    try:
        return str(int(creator_id))
    except (TypeError, ValueError):
        return str(creator_id or "").strip()


# ===== GLOBAL settings =====

def get_global_settings() -> Dict[str, Any]:
    """Retourne les settings globaux (horaires, dates, slots, auto_delete).
    Merge avec defaults pour les fields manquants."""
    data = _load()
    stored = data.get("global", {})
    out = json.loads(json.dumps(DEFAULT_GLOBAL))  # deep copy
    for k, v in stored.items():
        out[k] = v
    return out


def save_global_settings(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    data = _load()
    payload = dict(payload)
    payload["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    data["global"] = payload
    _save(data)
    return True


# ===== PER-CREATOR settings =====

def get_creator_settings(creator_id) -> Dict[str, Any]:
    """Retourne les settings per-creator (captions + media_pool)."""
    cid = _normalize_id(creator_id)
    if not cid:
        return dict(DEFAULT_CREATOR)
    data = _load()
    stored = data["creators"].get(cid, {})
    out = json.loads(json.dumps(DEFAULT_CREATOR))
    for k, v in stored.items():
        out[k] = v
    return out


def save_creator_settings(creator_id, payload: Dict[str, Any]) -> bool:
    cid = _normalize_id(creator_id)
    if not cid or not isinstance(payload, dict):
        return False
    data = _load()
    payload = dict(payload)
    payload["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    data["creators"][cid] = payload
    _save(data)
    return True


# ===== Combined : helper pour le front =====

def get_settings(creator_id) -> Dict[str, Any]:
    """Retourne le merge global + per-creator pour un creator.
    C est ce que renvoie l API /mypulslive/settings/<cid>."""
    g = get_global_settings()
    c = get_creator_settings(creator_id)
    out = dict(g)
    out["captions"] = c.get("captions", [])
    out["media_pool"] = c.get("media_pool", [])
    return out


def save_settings(creator_id, payload: Dict[str, Any]) -> bool:
    """Compat helper : split le payload entre global et per-creator."""
    if not isinstance(payload, dict):
        return False
    creator_fields = ("captions", "media_pool")
    global_payload = {k: v for k, v in payload.items() if k not in creator_fields}
    creator_payload = {k: payload[k] for k in creator_fields if k in payload}
    ok_g = True
    ok_c = True
    if global_payload:
        ok_g = save_global_settings(global_payload)
    if creator_payload:
        ok_c = save_creator_settings(creator_id, creator_payload)
    return ok_g and ok_c
