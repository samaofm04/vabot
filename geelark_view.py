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
    """Fetch les groupes GeeLark via l API. Retourne [{id, name}, ...].

    Utilise EXACTEMENT le meme endpoint que le cog Discord :
    POST /open/v1/group/list avec {page, pageSize} et reponse dans data.list.
    """
    tok = _bearer()
    if not tok:
        return []
    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    }
    out: List[Dict[str, Any]] = []
    page = 1
    try:
        while len(out) < 200:
            r = requests.post(
                f"{GEELARK_BASE}/open/v1/group/list",
                headers=headers,
                json={"page": page, "pageSize": 100},
                timeout=15,
            )
            if r.status_code != 200:
                break
            body = r.json()
            if body.get("code") != 0:
                break
            data = body.get("data", {}) or {}
            items = data.get("list", []) or []
            if not items:
                break
            for g in items:
                out.append({
                    "id": str(g.get("id", "")),
                    "name": g.get("name", "?"),
                })
            total = data.get("total", 0)
            if len(out) >= total:
                break
            page += 1
    except Exception:
        return out
    return out


def list_local_identities() -> List[str]:
    """Liste les identites disponibles localement (dossiers data/identities/*)."""
    if not IDENTITIES_DIR.exists():
        return []
    return sorted([p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir()])


def create_schedule(groupe: str, identite: str,
                    reels: int = 0, stories: int = 0, storyctas: int = 0,
                    hour_paris: int = 0, minute_paris: int = 0,
                    frequency: str = "daily",
                    days_of_week: Optional[List[int]] = None) -> Dict[str, Any]:
    """Cree un push planifie. Retourne {ok, schedule|error}.

    frequency :
    - 'daily' : tous les jours (default)
    - 'weekdays' : lun-ven
    - 'weekend' : sam-dim
    - 'custom' : days_of_week explicite
    - 'once' : une seule fois puis le bot supprime le schedule
    """
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
    # Validation/normalisation de la frequence
    valid_freqs = ("daily", "weekdays", "weekend", "custom", "once")
    if frequency not in valid_freqs:
        frequency = "daily"
    if days_of_week is None:
        if frequency == "daily":
            days_of_week = [0, 1, 2, 3, 4, 5, 6]
        elif frequency == "weekdays":
            days_of_week = [0, 1, 2, 3, 4]
        elif frequency == "weekend":
            days_of_week = [5, 6]
        elif frequency == "once":
            days_of_week = []
        else:
            days_of_week = []
    # Filtre les valeurs valides 0-6
    days_of_week = sorted({int(d) for d in days_of_week if 0 <= int(d) <= 6})
    if frequency == "custom" and not days_of_week:
        return {"ok": False, "error": "au moins 1 jour requis en mode custom"}
    schedule = {
        "id": uuid.uuid4().hex[:8],
        "groupe": groupe,
        "identite": identite,
        "reels": int(reels),
        "stories": int(stories),
        "storyctas": int(storyctas),
        "hour_paris": int(hour_paris),
        "minute_paris": int(minute_paris),
        "frequency": frequency,
        "days_of_week": days_of_week,
        "recurring": frequency != "once",
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


FREQ_LABELS = {
    "daily": "Tous les jours",
    "weekdays": "Lun-Ven",
    "weekend": "Sam-Dim",
    "custom": "Custom",
    "once": "Une fois",
}
DAY_NAMES_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]


def freq_label(s: Dict[str, Any]) -> str:
    """Label humain de la frequence du schedule."""
    freq = s.get("frequency", "daily")
    if freq == "custom":
        days = s.get("days_of_week") or []
        return ", ".join(DAY_NAMES_FR[d] for d in days if 0 <= d <= 6) or "Custom"
    return FREQ_LABELS.get(freq, freq)


def upcoming_executions(limit: int = 10) -> List[Dict[str, Any]]:
    """Pour chaque schedule, calcule la prochaine execution selon la
    frequency. Trie par distance ascendante.

    - daily / weekdays / weekend / custom : prochain jour qui matche
      days_of_week a HH:MM (aujourd hui si pas encore passe, sinon
      le prochain jour valide)
    - once : prochain HH:MM si jamais run, sinon skip
    """
    try:
        from zoneinfo import ZoneInfo
        paris_tz = ZoneInfo("Europe/Paris")
    except Exception:
        from datetime import timezone as _tz, timedelta as _td_only
        paris_tz = _tz(_td_only(hours=1))
    from datetime import timedelta as _td

    now = datetime.now(paris_tz)
    out: List[Dict[str, Any]] = []
    for s in list_schedules():
        try:
            h = int(s.get("hour_paris", 0))
            mn = int(s.get("minute_paris", 0))
        except Exception:
            continue
        freq = s.get("frequency", "daily")
        # Cas 'once' : si deja lance -> skip
        if freq == "once" and s.get("last_run_date"):
            continue
        # Determine les jours valides (0=Mon ... 6=Sun)
        days = s.get("days_of_week") or [0, 1, 2, 3, 4, 5, 6]
        if not days:
            days = [0, 1, 2, 3, 4, 5, 6]
        # Cherche le prochain jour de la semaine qui matche
        candidate = None
        for delta in range(8):  # max 7 jours en avant
            cand = (now + _td(days=delta)).replace(hour=h, minute=mn, second=0, microsecond=0)
            if cand <= now:
                continue
            if cand.weekday() in days:
                candidate = cand
                break
        if not candidate:
            continue
        diff_minutes = int((candidate - now).total_seconds() // 60)
        out.append({
            "id": s.get("id"),
            "groupe": s.get("groupe"),
            "identite": s.get("identite"),
            "reels": s.get("reels", 0),
            "stories": s.get("stories", 0),
            "storyctas": s.get("storyctas", 0),
            "frequency": freq,
            "freq_label": freq_label(s),
            "when": candidate.isoformat(),
            "when_label": candidate.strftime("%H:%M"),
            "when_day": "Aujourd'hui" if candidate.date() == now.date() else (
                "Demain" if candidate.date() == (now + _td(days=1)).date() else
                candidate.strftime("%a %d %b")
            ),
            "in_minutes": diff_minutes,
        })
    out.sort(key=lambda x: x.get("in_minutes", 9999))
    return out[:limit]


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
