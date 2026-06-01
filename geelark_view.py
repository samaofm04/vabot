"""geelark_view.py - Lecture des schedules/watchers GeeLark pour la dashboard web.

Le bot Discord cogs/geelark.py gere les push GeeLark (multi-phones cloud).
Ce module lit ses storages JSON pour les afficher dans la dashboard.

Storages :
- data/geelark_schedules.json : push planifies recurrents (par heure Paris)
- data/geelark_watchers.json  : watchers actifs (surveillance auto des phones)
- data/geelark_history.json   : historique des runs (nouveau, geree ici)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

DATA_DIR = Path("data")
SCHEDULES_FILE = DATA_DIR / "geelark_schedules.json"
WATCHERS_FILE = DATA_DIR / "geelark_watchers.json"
HISTORY_FILE = DATA_DIR / "geelark_history.json"


def _load(file_path: Path, default=None) -> List[Dict[str, Any]]:
    if not file_path.exists():
        return default if default is not None else []
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else []


def list_schedules() -> List[Dict[str, Any]]:
    """Schedules quotidiens : {id, groupe, identite, reels, stories, storyctas,
    hour_paris, minute_paris, recurring, last_run_date}.
    """
    items = _load(SCHEDULES_FILE)
    # Sort par heure ascendante
    items.sort(key=lambda s: (s.get("hour_paris", 0), s.get("minute_paris", 0)))
    return items


def list_watchers() -> List[Dict[str, Any]]:
    """Watchers actifs : surveille les phones d un groupe."""
    return _load(WATCHERS_FILE)


def list_history(limit: int = 30) -> List[Dict[str, Any]]:
    """Historique des runs. Most recent first."""
    items = _load(HISTORY_FILE)
    items.sort(key=lambda h: h.get("finished_at", ""), reverse=True)
    return items[:limit]


def delete_schedule(schedule_id: str) -> bool:
    items = _load(SCHEDULES_FILE)
    before = len(items)
    items = [s for s in items if s.get("id") != schedule_id]
    if len(items) != before:
        SCHEDULES_FILE.write_text(
            json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return True
    return False


def delete_watcher(watcher_id: str) -> bool:
    items = _load(WATCHERS_FILE)
    before = len(items)
    items = [w for w in items if w.get("id") != watcher_id]
    if len(items) != before:
        WATCHERS_FILE.write_text(
            json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return True
    return False


def stats() -> Dict[str, Any]:
    """KPI pour le header."""
    sched = list_schedules()
    watch = list_watchers()
    hist = list_history(limit=999)
    # Phones impactes : sum sur 7 derniers jours
    success_count = 0
    fail_count = 0
    for h in hist[:50]:
        success_count += h.get("phones_ok", 0)
        fail_count += h.get("phones_failed", 0)
    return {
        "schedules_count": len(sched),
        "watchers_count": len(watch),
        "history_count": len(hist),
        "phones_success_recent": success_count,
        "phones_failed_recent": fail_count,
    }
