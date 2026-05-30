"""mypuls_scheduler.py - Planification live de stories sur MyPuls via cookies.

Reverse-engineered depuis HAR de l'utilisateur (May 2026).

ENDPOINTS DECOUVERTS :
- GET  /api/creator/media?creator={id}&limit={N}&cursor={C} -> bibliotheque media
- GET  /api/collections?creator={id}                        -> collections (scripts/folders)
- GET  /api/media/thumbs?ids[]=X&ids[]=Y&...                -> URLs signees fresh
- GET  /planification/calendar/events?creator[]={id}&start={iso}&end={iso}
       -> liste events (posts + stories) sur une periode
- DELETE /stories/{id}  (X-CSRF-Token requis)               -> supprime story planifiee

ENDPOINTS A DECOUVRIR (HAR2) :
- POST de creation de story planifiee
- PATCH/PUT de modification de campagne (nb stories/jour, slots)
- POST de start/pause campagne

AUTH :
- Cookies de session reutilises depuis mypuls.py (_make_session)
- X-CSRF-Token requis pour les modifications (DELETE, POST, PUT, PATCH)
- Le CSRF est dans un <meta name="csrf-token" content="..."> du HTML
  des pages SPA (a fetch via /planification/calendar)
- X-Requested-With: XMLHttpRequest

NOTE JWT thumbs :
- Les URLs `thumb` et `src` contiennent un JWT qui expire au bout d'1 HEURE.
- Donc ne JAMAIS cacher ces URLs en base, toujours refetch a chaque acces.
- Endpoint /api/media/thumbs permet de re-signer un batch d'IDs.
"""
from __future__ import annotations

import re
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode

# On reutilise la session HTTP de mypuls.py pour avoir l'auth par cookies
from mypuls import (
    _make_session,
    _detect_login_redirect,
    _save_rotated_cookies,
    BASE_URL,
    TIMEOUT,
    is_configured,
)


# ============ CSRF token cache ============

_CSRF_CACHE: Dict[str, Any] = {"token": "", "ts": 0}
_CSRF_TTL = 1800  # 30 min - on refresh souvent


def _get_csrf_token(force: bool = False) -> str:
    """Recupere le X-CSRF-Token en parsant le HTML d'une page authentifiee.

    Le HTML de Symfony embarque un <meta name="csrf-token" content="...">.
    On le cache 30 min car la page HTML pese ~plusieurs centaines de KB.
    """
    import time as _t
    if not force and _CSRF_CACHE["token"] and (_t.time() - _CSRF_CACHE["ts"]) < _CSRF_TTL:
        return _CSRF_CACHE["token"]

    s = _make_session()
    if s is None:
        return ""
    # On charge /planification/calendar (page autorisee, leger HTML SPA)
    try:
        r = s.get(f"{BASE_URL}/planification/calendar", timeout=TIMEOUT)
    except Exception:
        return ""
    if r.status_code != 200 or _detect_login_redirect(r.text):
        return ""
    _save_rotated_cookies(s)
    m = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', r.text)
    if not m:
        # Symfony parfois utilise <input name="_token" value="..."> ou data-csrf
        m = re.search(r'data-csrf-token=["\']([^"\']+)["\']', r.text)
    if not m:
        m = re.search(r'csrf[_-]?token["\']?\s*[:=]\s*["\']([a-zA-Z0-9._-]{32,})["\']', r.text)
    if m:
        _CSRF_CACHE["token"] = m.group(1)
        _CSRF_CACHE["ts"] = int(_t.time())
        return m.group(1)
    return ""


# ============ HTTP helpers ============

def _build_session_with_csrf(needs_csrf: bool = False):
    s = _make_session()
    if s is None:
        return None, "Cookies MyPuls non configures"
    s.headers.update({
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": f"{BASE_URL}/planification/calendar",
        "Origin": BASE_URL,
    })
    if needs_csrf:
        tok = _get_csrf_token()
        if not tok:
            return None, "Impossible de recuperer le CSRF token (cookies expires ?)"
        s.headers["X-CSRF-Token"] = tok
    return s, None


def _do(method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None, json_payload: Optional[Dict[str, Any]] = None,
        needs_csrf: bool = False) -> Dict[str, Any]:
    s, err = _build_session_with_csrf(needs_csrf=needs_csrf)
    if err:
        return {"ok": False, "error": err}
    try:
        url = f"{BASE_URL}{path}"
        if params:
            # Support repeated keys for Symfony arrays (creator[]=1&creator[]=2)
            from urllib.parse import urlencode as _ue
            url += "?" + _ue(params, doseq=True)
        kwargs: Dict[str, Any] = {"timeout": TIMEOUT}
        if json_payload is not None:
            kwargs["json"] = json_payload
        elif data is not None:
            kwargs["data"] = data
        r = s.request(method, url, **kwargs)
    except Exception as e:
        return {"ok": False, "error": f"Erreur reseau : {e}"}
    if r.status_code in (401, 403):
        return {"ok": False, "error": f"Auth/CSRF KO (HTTP {r.status_code})"}
    if _detect_login_redirect(r.text):
        return {"ok": False, "error": "Cookies expires"}
    _save_rotated_cookies(s)
    out: Dict[str, Any] = {"ok": r.status_code < 400, "status": r.status_code}
    if r.status_code == 204:
        return out  # no content
    ctype = r.headers.get("Content-Type", "")
    if "application/json" in ctype:
        try:
            out["json"] = r.json()
        except Exception:
            out["text"] = r.text
    else:
        out["text"] = r.text
    if not out["ok"]:
        out["error"] = f"HTTP {r.status_code}"
    return out


# ============ Media library ============

def list_media(creator_id: int, cursor: Optional[int] = None, limit: int = 24) -> Dict[str, Any]:
    """Liste la bibliotheque de medias d'un createur.

    Returns: {ok, items: [{id, type:'photo'|'video', src, thumb, posted_at, ...}], next_cursor}
    Note: les URLs `src` et `thumb` contiennent un JWT qui expire en 1h, NE PAS CACHER.
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    params: Dict[str, Any] = {"creator": int(creator_id), "limit": int(limit)}
    if cursor is not None:
        params["cursor"] = int(cursor)
    res = _do("GET", "/api/creator/media", params=params)
    if not res.get("ok"):
        return res
    j = res.get("json", {})
    return {
        "ok": True,
        "items": j.get("items", []),
        "next_cursor": j.get("next_cursor"),
    }


def list_all_media(creator_id: int, hard_limit: int = 500) -> Dict[str, Any]:
    """Pagine et retourne TOUS les medias d'un createur (jusqu'a hard_limit).

    Utile pour la planification : on veut la liste complete des IDs disponibles.
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    all_items: List[Dict[str, Any]] = []
    cursor: Optional[int] = None
    pages = 0
    while True:
        res = list_media(creator_id, cursor=cursor, limit=100)
        if not res.get("ok"):
            return res
        items = res.get("items", [])
        all_items.extend(items)
        cursor = res.get("next_cursor")
        pages += 1
        if not cursor or not items or len(all_items) >= hard_limit or pages > 50:
            break
    return {"ok": True, "items": all_items, "total": len(all_items)}


def refresh_media_thumbs(media_ids: List[int]) -> Dict[str, Any]:
    """Re-signe les URLs thumb d'une liste d'IDs (les JWT expirent en 1h).

    Returns: {ok, thumbs: {id_str: thumb_url, ...}}
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    if not media_ids:
        return {"ok": True, "thumbs": {}}
    params = {"ids[]": [int(i) for i in media_ids]}
    res = _do("GET", "/api/media/thumbs", params=params)
    if not res.get("ok"):
        return res
    j = res.get("json", {})
    return {"ok": True, "thumbs": j.get("thumbs", {})}


# ============ Collections (scripts / folders) ============

def list_collections(creator_id: int) -> Dict[str, Any]:
    """Liste les collections (genre 'Script 1', 'Script 2', etc) d'un createur.

    Returns: {ok, items: [{id, name, counts:{photo,video}, count, last_media_at}]}
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    res = _do("GET", "/api/collections", params={"creator": int(creator_id)})
    if not res.get("ok"):
        return res
    j = res.get("json", {})
    return {"ok": True, "items": j.get("items", [])}


# ============ Calendar / planning ============

def list_calendar_events(
    creator_ids: List[int],
    start_iso: str,  # ex "2026-05-30T00:00:00"
    end_iso: str,    # ex "2026-06-06T00:00:00"
) -> Dict[str, Any]:
    """Liste tous les events (posts + stories) planifies sur une periode.

    Returns: {ok, events: [{id, type:'feed'|'story', start, end, extendedProps:{...}}]}
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    params: Dict[str, Any] = {
        "creator[]": [int(c) for c in creator_ids],
        "start": start_iso,
        "end": end_iso,
    }
    res = _do("GET", "/planification/calendar/events", params=params)
    if not res.get("ok"):
        return res
    return {"ok": True, "events": res.get("json", [])}


# ============ Stories - delete ============

def delete_story(story_id: int) -> Dict[str, Any]:
    """Supprime une story planifiee. Retourne {ok} ou {ok:False, error}.

    Confirme dans le HAR : DELETE /stories/{id} -> 204 No Content.
    Requiert X-CSRF-Token.
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    res = _do("DELETE", f"/stories/{int(story_id)}", needs_csrf=True)
    if res.get("status") == 204:
        return {"ok": True}
    return res


# ============ Stories - create (TODO: needs HAR2) ============

def schedule_story(
    creator_id: int,
    media_id: int,
    date_iso: str,  # "YYYY-MM-DD HH:MM:SS"
) -> Dict[str, Any]:
    """Planifie une story unique pour un createur.

    TODO: endpoint de creation pas encore reverse-engineered. L'utilisateur
    doit fournir un 2eme HAR contenant l'action "creer une story planifiee"
    pour qu'on puisse implementer ca.
    """
    return {
        "ok": False,
        "error": (
            "Endpoint de creation de story pas encore reverse-engineered. "
            "Le 1er HAR contenait juste de la navigation. Envoie un 2eme HAR "
            "avec l'action 'creer une story planifiee' (clic + drag sur le "
            "calendrier ou bouton 'Programmer une story')."
        ),
    }


# ============ High-level bulk scheduling ============

def bulk_schedule_stories(
    creator_id: int,
    media_ids: List[int],
    date_start: str,
    date_end: str,
    hour_slots: List[int],
) -> Dict[str, Any]:
    """Planifie en masse des stories. Pour l'instant fail tant que schedule_story()
    n'est pas implementee.

    Pour chaque jour de la periode et chaque heure dans hour_slots :
    - pioche un media_id (cycle)
    - genere une minute aleatoire 3-25
    - appelle schedule_story()
    """
    import random
    from datetime import datetime, timedelta

    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    if not media_ids:
        return {"ok": False, "error": "Aucun media_id"}
    try:
        d_start = datetime.strptime(date_start, "%Y-%m-%d").date()
        d_end = datetime.strptime(date_end, "%Y-%m-%d").date()
    except Exception as e:
        return {"ok": False, "error": f"Date invalide : {e}"}
    if d_end < d_start:
        return {"ok": False, "error": "date_end < date_start"}
    if not hour_slots:
        return {"ok": False, "error": "Aucun creneau horaire"}

    planned, failed = 0, 0
    errors: List[str] = []
    media_idx = 0
    day = d_start
    while day <= d_end:
        for h in hour_slots:
            m = random.randint(3, 25)
            dt = datetime(day.year, day.month, day.day, h, m, 0)
            mid = media_ids[media_idx % len(media_ids)]
            res = schedule_story(
                creator_id=creator_id,
                media_id=mid,
                date_iso=dt.strftime("%Y-%m-%d %H:%M:%S"),
            )
            if res.get("ok"):
                planned += 1
            else:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{dt}: {res.get('error', '?')[:80]}")
            media_idx += 1
        day += timedelta(days=1)
    return {
        "ok": planned > 0,
        "planned": planned,
        "failed": failed,
        "errors": errors,
    }


# ============ Image proxy (refresh JWT-signed URLs in pages) ============

def proxy_media_thumb(creator_hash: str, media_id: int) -> Dict[str, Any]:
    """Proxy : fetch un thumb depuis media.mypuls.app avec un token frais.

    On demande d'abord un fresh token via /api/media/thumbs, puis on telecharge.
    Retourne {ok, content: bytes, content_type}.
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    # Get fresh signed URL
    res = refresh_media_thumbs([int(media_id)])
    if not res.get("ok"):
        return res
    url = res.get("thumbs", {}).get(str(media_id))
    if not url:
        return {"ok": False, "error": "Thumb URL introuvable"}
    import requests
    try:
        r = requests.get(url, timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur reseau thumb: {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"Thumb HTTP {r.status_code}"}
    return {
        "ok": True,
        "content": r.content,
        "content_type": r.headers.get("Content-Type", "image/jpeg"),
    }
