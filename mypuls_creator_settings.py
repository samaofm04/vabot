"""mypuls_creator_settings.py - Settings persistes par createur MyPuls Live.

Pour chaque createur, on stocke :
- start_date / end_date (periode)
- infinite_mode (campagne continue)
- mode_active ('autopost' | 'autostory' | 'edt')
- posts (count + slots [{time, visibility}])
- stories (count + slots [{time, visibility}])
- captions (texte par defaut + overrides specifiques)
- media_pool (refs vers les fichiers selectionnes pour ce createur)
- auto_delete (config de suppression automatique)

Stockage : data/mypuls_creator_settings.json
Structure :
{
    "creators": {
        "769": {
            "start_date": "2026-06-01",
            "end_date": "2026-06-07",
            "infinite_mode": false,
            "mode_active": "autopost",
            "posts": {
                "count": 9,
                "slots": [
                    {"time": "01:00", "visibility": "public"},
                    {"time": "02:00", "visibility": "private"},
                    ...
                ]
            },
            "stories": {
                "count": 0,
                "slots": []
            },
            "captions": [
                "Caption 1",
                "Caption 2"
            ],
            "media_pool": [],
            "auto_delete": {
                "enabled": false,
                "after_days": null,
                "from_date": null
            },
            "updated_at": "ISO timestamp"
        }
    }
}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

DATA_DIR = Path("data")
SETTINGS_FILE = DATA_DIR / "mypuls_creator_settings.json"


# Defaults par createur (utilises si jamais ouvert)
DEFAULT_SETTINGS = {
    "start_date": "",
    "end_date": "",
    "infinite_mode": False,
    "mode_active": "autopost",
    "posts": {
        "count": 9,
        "slots": [
            {"time": "01:00", "visibility": "public"},
            {"time": "02:00", "visibility": "private"},
            {"time": "04:00", "visibility": "public"},
            {"time": "08:00", "visibility": "private"},
            {"time": "13:00", "visibility": "public"},
            {"time": "15:00", "visibility": "private"},
            {"time": "18:00", "visibility": "public"},
            {"time": "19:00", "visibility": "private"},
            {"time": "20:00", "visibility": "public"},
        ],
    },
    "stories": {
        "count": 0,
        "slots": [],
    },
    "captions": [],
    "media_pool": [],
    "auto_delete": {
        "enabled": False,
        "after_days": None,
        "from_date": None,
    },
}


def _load() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {"creators": {}}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if "creators" not in data:
            data["creators"] = {}
        return data
    except Exception:
        return {"creators": {}}


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _normalize_id(creator_id) -> str:
    """Cast to str pour les cles json."""
    try:
        return str(int(creator_id))
    except (TypeError, ValueError):
        return str(creator_id or "").strip()


def get_settings(creator_id) -> Dict[str, Any]:
    """Retourne les settings d un createur. Si jamais saved, renvoie les defaults
    (mais ne les persiste pas - lazy)."""
    cid = _normalize_id(creator_id)
    if not cid:
        return dict(DEFAULT_SETTINGS)
    data = _load()
    stored = data["creators"].get(cid, {})
    # Merge avec defaults pour gerer les fields manquants
    out = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    for k, v in stored.items():
        out[k] = v
    return out


def save_settings(creator_id, settings: Dict[str, Any]) -> bool:
    """Sauvegarde COMPLETE des settings d un createur (overwrite)."""
    cid = _normalize_id(creator_id)
    if not cid:
        return False
    if not isinstance(settings, dict):
        return False
    data = _load()
    settings = dict(settings)
    settings["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    data["creators"][cid] = settings
    _save(data)
    return True


def update_settings(creator_id, **partial) -> bool:
    """Patch partiel : merge les fields fournis sans toucher au reste."""
    cid = _normalize_id(creator_id)
    if not cid:
        return False
    data = _load()
    existing = data["creators"].get(cid, dict(DEFAULT_SETTINGS))
    for k, v in partial.items():
        if v is not None:
            existing[k] = v
    existing["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    data["creators"][cid] = existing
    _save(data)
    return True


def list_creators_with_settings() -> Dict[str, Dict[str, Any]]:
    """Retourne tous les creators ayant des settings."""
    return _load().get("creators", {})


def delete_settings(creator_id) -> bool:
    cid = _normalize_id(creator_id)
    if not cid:
        return False
    data = _load()
    if cid in data["creators"]:
        del data["creators"][cid]
        _save(data)
        return True
    return False
