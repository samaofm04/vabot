"""mypuls_campaigns.py - Campagnes recurrentes MyPuls.

Une "campagne" = config de planification qui s'execute en continu :
- L'utilisateur configure les slots, medias, options
- On schedule les 2 prochains jours immediatement
- Un cron (toutes les heures) etend de 2 jours quand on arrive a 1 jour
  de la fin schedulee, ce qui permet de tourner a l'infini sans pousser
  des milliers de stories/posts d'un coup (=> evite les rate-limits
  MyPuls).

Stockage : data/mypuls_campaigns.json
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional

DATA_DIR = Path("data")
CAMPAIGNS_FILE = DATA_DIR / "mypuls_campaigns.json"

# Combien de jours on planifie en une fois (chunk size)
CHUNK_DAYS = 2

# Quand etendre la campagne : quand il reste moins de N jours planifies
EXTEND_THRESHOLD_DAYS = 1


def _load_all() -> List[Dict[str, Any]]:
    if not CAMPAIGNS_FILE.exists():
        return []
    try:
        data = json.loads(CAMPAIGNS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_all(campaigns: List[Dict[str, Any]]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CAMPAIGNS_FILE.write_text(
        json.dumps(campaigns, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_campaigns(active_only: bool = False) -> List[Dict[str, Any]]:
    items = _load_all()
    if active_only:
        items = [c for c in items if c.get("active")]
    return items


def get_campaign(campaign_id: str) -> Optional[Dict[str, Any]]:
    for c in _load_all():
        if c.get("id") == campaign_id:
            return c
    return None


def create_campaign(
    creator_id: int,
    creator_name: str,
    campaign_type: str,  # "post" | "story"
    slots: List[Any],     # post_slots (list of dict) ou story_slots (list of str)
    media_ids: List[int],
    captions: List[str],
    options: Dict[str, Any],
    post_action: str = "delete",
    delay_sec: int = 172800,
    start_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Cree une nouvelle campagne infinie. Schedule immediatement les 2 premiers jours.

    Returns {ok, campaign, planned, errors}
    """
    import mypuls_scheduler

    if not slots:
        return {"ok": False, "error": "Aucun slot configure"}
    if not media_ids:
        return {"ok": False, "error": "Aucun media_id"}
    if campaign_type not in ("post", "story"):
        return {"ok": False, "error": f"Type invalide: {campaign_type}"}

    today = date.today()
    if start_date:
        try:
            d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        except Exception:
            d_start = today
    else:
        d_start = today
    # Pas plus tot qu'aujourd'hui
    if d_start < today:
        d_start = today

    # Premiere chunk : start -> start + CHUNK_DAYS - 1
    d_end = d_start + timedelta(days=CHUNK_DAYS - 1)

    campaign_id = f"cmp_{uuid.uuid4().hex[:12]}"
    campaign = {
        "id": campaign_id,
        "creator_id": int(creator_id),
        "creator_name": creator_name or "",
        "type": campaign_type,
        "slots": slots,
        "media_ids": [int(m) for m in media_ids],
        "captions": list(captions or []),
        "options": dict(options or {}),
        "post_action": post_action,
        "delay_sec": int(delay_sec),
        "active": True,
        "started_at": d_start.isoformat(),
        "scheduled_until": None,  # sera set apres premier push
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        "last_extended_at": None,
        "total_planned": 0,
        "total_failed": 0,
        "media_cursor": 0,  # ou on est dans la liste media (recyclage)
    }

    # Push initial : start -> start + CHUNK_DAYS - 1
    res = _execute_chunk(campaign, d_start, d_end)
    campaign["scheduled_until"] = d_end.isoformat()
    campaign["last_extended_at"] = datetime.utcnow().isoformat(timespec="seconds")
    campaign["total_planned"] = res.get("planned", 0)
    campaign["total_failed"] = res.get("failed", 0)
    campaign["media_cursor"] = res.get("media_cursor_end", 0)

    # Sauvegarder
    campaigns = _load_all()
    campaigns.append(campaign)
    _save_all(campaigns)

    return {
        "ok": True,
        "campaign": campaign,
        "planned": res.get("planned", 0),
        "failed": res.get("failed", 0),
        "errors": res.get("errors", []),
    }


def set_campaign_active(campaign_id: str, active: bool) -> bool:
    campaigns = _load_all()
    for c in campaigns:
        if c.get("id") == campaign_id:
            c["active"] = bool(active)
            _save_all(campaigns)
            return True
    return False


def delete_campaign(campaign_id: str) -> bool:
    campaigns = _load_all()
    before = len(campaigns)
    campaigns = [c for c in campaigns if c.get("id") != campaign_id]
    if len(campaigns) != before:
        _save_all(campaigns)
        return True
    return False


def _execute_chunk(campaign: Dict[str, Any], d_start: date, d_end: date) -> Dict[str, Any]:
    """Schedule le chunk de jours [d_start, d_end] pour la campagne.

    Reutilise bulk_schedule_stories / bulk_schedule_posts avec le bon offset
    de media_cursor pour continuer la rotation.
    """
    import mypuls_scheduler

    opts = campaign.get("options", {})
    shuffle_media = bool(opts.get("shuffle_media", False))
    randomize_minutes = bool(opts.get("randomize_minutes", True))

    media_ids = list(campaign.get("media_ids", []))
    cursor = int(campaign.get("media_cursor", 0))
    if cursor and cursor < len(media_ids):
        # Rotation : on reorganise la liste pour commencer ou on en etait
        media_ids = media_ids[cursor:] + media_ids[:cursor]

    if campaign["type"] == "story":
        res = mypuls_scheduler.bulk_schedule_stories(
            creator_id=campaign["creator_id"],
            media_ids=media_ids,
            date_start=d_start.isoformat(),
            date_end=d_end.isoformat(),
            story_slots=campaign["slots"],
            shuffle_media=shuffle_media,
            randomize_minutes=randomize_minutes,
        )
    else:
        res = mypuls_scheduler.bulk_schedule_posts(
            creator_id=campaign["creator_id"],
            media_ids=media_ids,
            captions=campaign.get("captions", [""]),
            date_start=d_start.isoformat(),
            date_end=d_end.isoformat(),
            post_slots=campaign["slots"],
            action=campaign.get("post_action", "delete"),
            delay_sec=campaign.get("delay_sec", 172800),
            shuffle_media=shuffle_media,
            randomize_minutes=randomize_minutes,
        )

    # Calcul du nouveau curseur media
    planned = res.get("planned", 0)
    new_cursor = (cursor + planned) % max(1, len(media_ids))
    res["media_cursor_end"] = new_cursor
    return res


def extend_due_campaigns(now: Optional[datetime] = None) -> Dict[str, Any]:
    """A appeler par le cron. Etend de CHUNK_DAYS toutes les campagnes
    actives dont scheduled_until - today < EXTEND_THRESHOLD_DAYS.

    Returns {processed, extended, planned, failed, errors}
    """
    if now is None:
        now = datetime.now()
    today = now.date()

    campaigns = _load_all()
    extended = 0
    total_planned = 0
    total_failed = 0
    errors: List[str] = []

    changed = False
    for c in campaigns:
        if not c.get("active"):
            continue
        try:
            sched_until = datetime.strptime(c.get("scheduled_until", ""), "%Y-%m-%d").date()
        except Exception:
            continue
        # Combien de jours il reste planifies a partir d'aujourd'hui ?
        days_left = (sched_until - today).days
        if days_left >= EXTEND_THRESHOLD_DAYS:
            continue
        # On etend : prochain chunk = sched_until+1 a sched_until+CHUNK_DAYS
        d_start = sched_until + timedelta(days=1)
        d_end = d_start + timedelta(days=CHUNK_DAYS - 1)
        res = _execute_chunk(c, d_start, d_end)
        c["scheduled_until"] = d_end.isoformat()
        c["last_extended_at"] = now.isoformat(timespec="seconds")
        c["total_planned"] = int(c.get("total_planned", 0)) + res.get("planned", 0)
        c["total_failed"] = int(c.get("total_failed", 0)) + res.get("failed", 0)
        c["media_cursor"] = res.get("media_cursor_end", c.get("media_cursor", 0))
        extended += 1
        total_planned += res.get("planned", 0)
        total_failed += res.get("failed", 0)
        if res.get("errors"):
            errors.extend(res["errors"][:2])
        changed = True

    if changed:
        _save_all(campaigns)

    return {
        "processed": sum(1 for c in campaigns if c.get("active")),
        "extended": extended,
        "planned": total_planned,
        "failed": total_failed,
        "errors": errors[:10],
    }
