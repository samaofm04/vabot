"""chatting.py - Planning des chatteurs (emploi du temps hebdo).

Stockage : data/chatting_shifts.json
Structure :
{
    "shifts": [
        {
            "id": "shift_xxx",
            "chatter": "Lola",
            "day": "lun",          # lun mar mer jeu ven sam dim
            "start": "08:00",
            "end": "12:00",
            "model": "Amelia_xoxo",
            "created_at": "..."
        }, ...
    ]
}
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

DATA_DIR = Path("data")
SHIFTS_FILE = DATA_DIR / "chatting_shifts.json"

DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
DAYS_FULL = {
    "lun": "Lundi", "mar": "Mardi", "mer": "Mercredi",
    "jeu": "Jeudi", "ven": "Vendredi", "sam": "Samedi", "dim": "Dimanche",
}


def _load() -> Dict[str, Any]:
    if not SHIFTS_FILE.exists():
        return {"shifts": []}
    try:
        data = json.loads(SHIFTS_FILE.read_text(encoding="utf-8"))
        if "shifts" not in data:
            data["shifts"] = []
        return data
    except Exception:
        return {"shifts": []}


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SHIFTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_shifts() -> List[Dict[str, Any]]:
    return _load().get("shifts", [])


def shifts_by_chatter() -> Dict[str, List[Dict[str, Any]]]:
    """Retourne {chatter_name: [shifts...]} trie par jour/heure."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    day_order = {d: i for i, d in enumerate(DAYS)}
    for s in list_shifts():
        chat = s.get("chatter", "?")
        out.setdefault(chat, []).append(s)
    for chat in out:
        out[chat].sort(key=lambda s: (day_order.get(s.get("day", "lun"), 99), s.get("start", "00:00")))
    return out


def shifts_by_day() -> Dict[str, List[Dict[str, Any]]]:
    """Retourne {day_key: [shifts...]} trie par heure."""
    out: Dict[str, List[Dict[str, Any]]] = {d: [] for d in DAYS}
    for s in list_shifts():
        d = s.get("day", "lun")
        if d in out:
            out[d].append(s)
    for d in out:
        out[d].sort(key=lambda s: s.get("start", "00:00"))
    return out


def add_shift(chatter: str, day: str, start: str, end: str,
              model: str = "") -> Dict[str, Any]:
    """Ajoute un shift. Retourne {ok, shift|error}."""
    chatter = (chatter or "").strip()
    if not chatter:
        return {"ok": False, "error": "Nom du chatteur manquant"}
    if day not in DAYS:
        return {"ok": False, "error": f"Jour invalide : {day}"}
    # Validate HH:MM
    def _valid_time(t: str) -> bool:
        try:
            h, m = t.split(":")
            return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
        except Exception:
            return False
    if not _valid_time(start) or not _valid_time(end):
        return {"ok": False, "error": "Format heure invalide (HH:MM attendu)"}
    if start >= end:
        return {"ok": False, "error": "L heure de fin doit etre apres celle de debut"}

    shift = {
        "id": f"shift_{uuid.uuid4().hex[:10]}",
        "chatter": chatter,
        "day": day,
        "start": start,
        "end": end,
        "model": (model or "").strip(),
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    data = _load()
    data["shifts"].append(shift)
    _save(data)
    return {"ok": True, "shift": shift}


def delete_shift(shift_id: str) -> bool:
    data = _load()
    before = len(data["shifts"])
    data["shifts"] = [s for s in data["shifts"] if s.get("id") != shift_id]
    if len(data["shifts"]) != before:
        _save(data)
        return True
    return False


def update_shift(shift_id: str, **fields) -> bool:
    data = _load()
    for s in data["shifts"]:
        if s.get("id") == shift_id:
            for k, v in fields.items():
                if k in ("chatter", "day", "start", "end", "model"):
                    s[k] = v
            _save(data)
            return True
    return False


def get_chatter_list() -> List[str]:
    """Liste unique des chatteurs ayant au moins un shift."""
    return sorted({s.get("chatter", "") for s in list_shifts() if s.get("chatter")})


def coverage_stats() -> Dict[str, Any]:
    """Stats globales : heures totales / jour / chatteur."""
    by_day = {d: 0.0 for d in DAYS}
    by_chatter: Dict[str, float] = {}
    total = 0.0
    for s in list_shifts():
        try:
            sh, sm = map(int, s.get("start", "00:00").split(":"))
            eh, em = map(int, s.get("end", "00:00").split(":"))
            hrs = (eh * 60 + em - sh * 60 - sm) / 60.0
            if hrs < 0:
                hrs = 0
        except Exception:
            hrs = 0
        d = s.get("day", "lun")
        if d in by_day:
            by_day[d] += hrs
        by_chatter[s.get("chatter", "?")] = by_chatter.get(s.get("chatter", "?"), 0) + hrs
        total += hrs
    return {
        "by_day": by_day,
        "by_chatter": by_chatter,
        "total_hours": round(total, 1),
        "shifts_count": len(list_shifts()),
    }
