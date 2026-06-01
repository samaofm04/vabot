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
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

import requests

DATA_DIR = Path("data")
SCHEDULES_FILE = DATA_DIR / "geelark_schedules.json"
WATCHERS_FILE = DATA_DIR / "geelark_watchers.json"
HISTORY_FILE = DATA_DIR / "geelark_history.json"

GEELARK_BASE = "https://openapi.geelark.com"
IDENTITIES_DIR = DATA_DIR / "identities"


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


def _bearer() -> Optional[str]:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    tok = os.getenv("GEELARK_BEARER", "").strip()
    return tok or None


def list_geelark_groups() -> List[Dict[str, Any]]:
    """Fetch les groupes GeeLark via l API. Retourne [{id, name}, ...]."""
    tok = _bearer()
    if not tok:
        return []
    try:
        r = requests.post(
            f"{GEELARK_BASE}/open/v1/phone/list",
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json",
                "trace-id": uuid.uuid4().hex,
            },
            json={"page": 1, "page_size": 1, "groups": []},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        # GeeLark renvoie les groupes dans un endpoint specifique
        rr = requests.post(
            f"{GEELARK_BASE}/open/v1/phone/group/list",
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json",
                "trace-id": uuid.uuid4().hex,
            },
            json={"page": 1, "page_size": 100},
            timeout=15,
        )
        if rr.status_code != 200:
            return []
        j = rr.json()
        items = j.get("data", {}).get("items", []) or []
        return [{"id": g.get("id", ""), "name": g.get("name", "?")} for g in items]
    except Exception:
        return []


def list_local_identities() -> List[str]:
    """Liste les identites disponibles localement (dossiers data/identities/*)."""
    if not IDENTITIES_DIR.exists():
        return []
    return sorted([p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir()])


def create_schedule(groupe: str, identite: str,
                    reels: int = 0, stories: int = 0, storyctas: int = 0,
                    hour_paris: int = 0, minute_paris: int = 0) -> Dict[str, Any]:
    """Cree un push planifie quotidien. Retourne {ok, schedule|error}."""
    groupe = (groupe or "").strip()
    identite = (identite or "").strip()
    if not groupe or not identite:
        return {"ok": False, "error": "groupe et identite requis"}
    if not (0 <= hour_paris <= 23) or not (0 <= minute_paris <= 59):
        return {"ok": False, "error": "heure/minute invalides"}
    if reels < 0 or stories < 0 or storyctas < 0:
        return {"ok": False, "error": "comptes negatifs"}
    if reels + stories + storyctas == 0:
        return {"ok": False, "error": "au moins 1 reel/story/CTA"}
    schedule = {
        "id": uuid.uuid4().hex[:8],
        "groupe": groupe,
        "identite": identite,
        "reels": int(reels),
        "stories": int(stories),
        "storyctas": int(storyctas),
        "hour_paris": int(hour_paris),
        "minute_paris": int(minute_paris),
        "recurring": True,
        "channel_id": None,
        "created_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_run_date": None,
    }
    items = _load(SCHEDULES_FILE)
    items.append(schedule)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"ok": True, "schedule": schedule}


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
