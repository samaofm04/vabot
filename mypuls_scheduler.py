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


# ============ Planif config (CSRF tokens + URLs from /planification/calendar) ============

# Le frontend MyPuls embarque tous les tokens + URLs dans un <div id="planif-root"
# data-csrf-story-create=... data-csrf-post-create=... data-csrf-update=...
# data-csrf-delete=... data-url-create-story=... etc>.
# On scrape cette page une fois et on cache tout.

_PLANIF_CACHE: Dict[str, Any] = {"config": {}, "ts": 0}
_PLANIF_TTL = 900  # 15 min (les tokens peuvent rotater, on refresh souvent)


def _get_planif_config(force: bool = False) -> Dict[str, str]:
    """Retourne {csrf_story_create, csrf_post_create, csrf_update, csrf_delete,
    url_create_story, url_create_post, url_update_base, url_delete_base,
    url_events, api_media, api_collections, api_media_thumbs, api_collection_media_base}.

    Cache 15 min. Si echec, retourne {} (l'appelant doit gerer).
    """
    import time as _t
    if not force and _PLANIF_CACHE["config"] and (_t.time() - _PLANIF_CACHE["ts"]) < _PLANIF_TTL:
        return _PLANIF_CACHE["config"]

    s = _make_session()
    if s is None:
        return {}
    try:
        r = s.get(f"{BASE_URL}/planification/calendar", timeout=TIMEOUT)
    except Exception:
        return {}
    if r.status_code != 200 or _detect_login_redirect(r.text):
        return {}
    _save_rotated_cookies(s)

    # Extract <div id="planif-root" data-...>
    m = re.search(r'<div[^>]+id=["\']planif-root["\'][^>]*>', r.text)
    if not m:
        return {}
    root_tag = m.group(0)
    cfg: Dict[str, str] = {}
    for attr_m in re.finditer(r'data-([a-z-]+)=["\']([^"\']*)["\']', root_tag):
        key = attr_m.group(1).replace("-", "_")
        cfg[key] = attr_m.group(2)

    # Aussi le csrf-token global (meta) pour les calls qui en ont besoin
    meta_m = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', r.text)
    if meta_m:
        cfg["csrf_meta"] = meta_m.group(1)

    _PLANIF_CACHE["config"] = cfg
    _PLANIF_CACHE["ts"] = int(_t.time())
    return cfg


def _get_csrf_token(force: bool = False) -> str:
    """Backward-compat : retourne le csrf-token meta (utilise pour /api/* requests)."""
    cfg = _get_planif_config(force=force)
    return cfg.get("csrf_meta", "")


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
    """Supprime une story planifiee (DELETE /stories/{id}, 204 No Content).

    Le frontend MyPuls utilise data-csrf-delete dans le X-CSRF-Token header
    pour les deletes (token specifique, different du meta).
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    cfg = _get_planif_config()
    csrf = cfg.get("csrf_delete", "")
    if not csrf:
        return {"ok": False, "error": "CSRF delete token introuvable"}
    base = cfg.get("url_delete_base") or "/stories"
    s, err = _build_session_with_csrf(needs_csrf=False)
    if err:
        return {"ok": False, "error": err}
    s.headers["X-CSRF-Token"] = csrf
    try:
        r = s.delete(f"{BASE_URL}{base}/{int(story_id)}", timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur reseau : {e}"}
    _save_rotated_cookies(s)
    if r.status_code == 204:
        return {"ok": True}
    if r.status_code == 419:
        _PLANIF_CACHE["config"] = {}
        _PLANIF_CACHE["ts"] = 0
        return {"ok": False, "error": "CSRF expire (HTTP 419)"}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


# ============ Stories & Posts - create ============

# Default timezone offset for dateSchedule field.
# MyPuls expects "YYYY-MM-DDTHH:MM:SS+02:00" (or +01:00 in winter, Europe/Paris).
# On lit le bon offset automatiquement.
def _iso_with_tz(dt) -> str:
    """Convertit un datetime en string ISO avec offset Europe/Paris.

    Accepte aussi une string "YYYY-MM-DD HH:MM:SS" → parse + ajoute offset.
    """
    from datetime import datetime, timezone, timedelta
    if isinstance(dt, str):
        # parse
        s = dt.strip().replace("T", " ")
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
            except Exception:
                return dt  # caller's problem
    # Detection offset Paris : DST entre dernier dim de mars (02h) et dernier dim d'oct (03h)
    y = dt.year
    # Last sunday of march
    import calendar
    march_last_day = max(d for d in range(25, 32)
                         if datetime(y, 3, d).weekday() == 6)
    oct_last_day = max(d for d in range(25, 32)
                       if datetime(y, 10, d).weekday() == 6)
    dst_start = datetime(y, 3, march_last_day, 2, 0)
    dst_end = datetime(y, 10, oct_last_day, 3, 0)
    is_dst = dst_start <= dt < dst_end
    offset = "+02:00" if is_dst else "+01:00"
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + offset


def _post_multipart(path: str, fields: Dict[str, Any], csrf_token: str) -> Dict[str, Any]:
    """POST en multipart/form-data avec _token dans le body (replique le frontend MyPuls).

    csrf_token : le token CSRF specifique a ce formulaire (story/post/update/delete).
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    if not csrf_token:
        return {"ok": False, "error": "CSRF token vide (page calendrier inaccessible ?)"}
    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Cookies non configures"}
    s.headers.update({
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/planification/calendar",
    })
    multipart_fields = [("_token", (None, csrf_token))]
    for k, v in fields.items():
        multipart_fields.append((k, (None, str(v))))
    try:
        r = s.post(f"{BASE_URL}{path}", files=multipart_fields, timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur reseau : {e}"}
    if r.status_code in (401, 403):
        return {"ok": False, "error": f"Auth/CSRF KO (HTTP {r.status_code})"}
    if r.status_code == 419:
        # CSRF invalide : on invalide le cache pour forcer un refresh au prochain call
        _PLANIF_CACHE["config"] = {}
        _PLANIF_CACHE["ts"] = 0
        return {"ok": False, "error": "CSRF expire (HTTP 419) - retry"}
    if _detect_login_redirect(r.text):
        return {"ok": False, "error": "Cookies expires"}
    _save_rotated_cookies(s)
    out: Dict[str, Any] = {"ok": r.status_code < 400, "status": r.status_code}
    ctype = r.headers.get("Content-Type", "")
    if "application/json" in ctype:
        try:
            out["json"] = r.json()
        except Exception:
            out["text"] = r.text[:300]
    else:
        out["text"] = r.text[:300]
    if not out["ok"]:
        out["error"] = f"HTTP {r.status_code}: {out.get('text','')[:200]}"
    return out


def schedule_story(
    creator_id: int,
    media_id: int,
    date_iso: str,
    audience: str = "everyone",
    auto_delete_after_sec: Optional[int] = None,
) -> Dict[str, Any]:
    """Planifie une story (POST /stories, multipart/form-data).

    Fields confirmes par HAR2 :
      _token (csrf-story-create), mediaId, dateSchedule (ISO+TZ Paris),
      storyAudience, creatorId
    -> 201 {id, status:"schedule", dateSchedule}

    Si auto_delete_after_sec est fourni, on track la story dans
    data/mypuls_pending_deletes.json pour qu'un cron la supprime au moment voulu.
    (MyPuls n'expose pas l'auto-delete pour stories dans leur API, donc on
    le fait cote nous.)
    """
    cfg = _get_planif_config()
    csrf = cfg.get("csrf_story_create", "")
    url = cfg.get("url_create_story") or "/stories"
    fields = {
        "mediaId": int(media_id),
        "dateSchedule": _iso_with_tz(date_iso),
        "storyAudience": audience or "everyone",
        "creatorId": int(creator_id),
    }
    res = _post_multipart(url, fields, csrf)
    if res.get("ok"):
        j = res.get("json") or {}
        story_id = j.get("id")
        # Track local auto-delete if requested
        if story_id and auto_delete_after_sec and auto_delete_after_sec > 0:
            try:
                _add_pending_delete(int(story_id), date_iso, int(auto_delete_after_sec), "story")
            except Exception:
                pass
        return {"ok": True, "story_id": story_id, "status": j.get("status"),
                "date_schedule": j.get("dateSchedule")}
    return res


def schedule_post(
    creator_id: int,
    media_id: int,
    date_iso: str,
    caption: str = "",
    visibility: str = "public",       # "public" | "private"
    action: str = "delete",           # "none" | "delete"
    delay_sec: int = 172800,           # delai auto-delete (48h par defaut)
) -> Dict[str, Any]:
    """Planifie un post feed (POST /posts, multipart/form-data).

    Fields confirmes par HAR2 + JS frontend :
      _token (csrf-post-create), mediaId, dateSchedule, feedVisibility,
      postAction, caption, creatorId
      + optionnel postActionDelaySeconds si action=delete et visibility=public
    -> 201 {id, status:"schedule", dateSchedule}

    NOTE: MyPuls force postAction=none pour les posts prives (vu dans le JS).
    On respecte la meme logique pour eviter les erreurs serveur.
    """
    cfg = _get_planif_config()
    csrf = cfg.get("csrf_post_create", "")
    url = cfg.get("url_create_post") or "/posts"
    # Pour les posts prives, postAction est force a 'none'
    effective_action = action if visibility == "public" else "none"
    fields: Dict[str, Any] = {
        "mediaId": int(media_id),
        "dateSchedule": _iso_with_tz(date_iso),
        "feedVisibility": visibility or "public",
        "postAction": effective_action or "none",
        "caption": caption or "",
        "creatorId": int(creator_id),
    }
    if effective_action == "delete":
        # Field name = postActionDelaySeconds (avec 's') d'apres le JS frontend
        fields["postActionDelaySeconds"] = int(delay_sec)
    res = _post_multipart(url, fields, csrf)
    if res.get("ok"):
        j = res.get("json") or {}
        return {"ok": True, "post_id": j.get("id"), "status": j.get("status"),
                "date_schedule": j.get("dateSchedule")}
    return res


# ============ High-level bulk scheduling ============

def _parse_time_slot(s: str) -> Optional[tuple]:
    """Parse "HH:MM" en (hour, minute). Retourne None si invalide."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        # Accepter "9", "09:30", "9:0", "13:00"
        if ":" in s:
            hh, mm = s.split(":", 1)
            h = int(hh)
            m = int(mm)
        else:
            h = int(s)
            m = 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
    except Exception:
        pass
    return None


VALID_STORY_AUDIENCES = {"everyone", "subscribers", "former_subscribers", "interested"}


def bulk_schedule_stories(
    creator_id: int,
    media_ids: List[int],
    date_start: str,
    date_end: str,
    story_slots,  # liste de "HH:MM" OU liste de {time, audience}
    audience: str = "everyone",  # fallback global si slot n'a pas d audience
    auto_delete_after_sec: Optional[int] = None,
    shuffle_media: bool = False,
    randomize_minutes: bool = True,
    hour_slots: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Planifie en masse des stories.

    story_slots :
      - liste de "HH:MM" (backward compat -> audience globale appliquee)
      - OU liste de {"time":"HH:MM", "audience":"everyone|subscribers|former_subscribers|interested"}

    Si randomize_minutes : minutes overridees aleatoirement (3-25).
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

    # Parse slots avec audience
    parsed_slots: List[tuple] = []  # (hour, minute, audience)
    if hour_slots:  # backward compat
        for h in hour_slots:
            parsed_slots.append((int(h), 0, audience))
    for sl in (story_slots or []):
        if isinstance(sl, dict):
            t = sl.get("time", "")
            aud = (sl.get("audience") or audience or "everyone").strip()
            if aud not in VALID_STORY_AUDIENCES:
                aud = "everyone"
        else:
            t = str(sl)
            aud = audience
        p = _parse_time_slot(t)
        if p:
            parsed_slots.append((p[0], p[1], aud))
    if not parsed_slots:
        return {"ok": False, "error": "Aucun creneau horaire valide"}

    if shuffle_media:
        media_ids = list(media_ids)
        random.shuffle(media_ids)

    planned, failed = 0, 0
    errors: List[str] = []
    success_ids: List[int] = []
    media_idx = 0
    day = d_start
    while day <= d_end:
        for (h, base_m, aud) in parsed_slots:
            m = random.randint(3, 25) if randomize_minutes else base_m
            dt = datetime(day.year, day.month, day.day, h, m, 0)
            mid = media_ids[media_idx % len(media_ids)]
            res = schedule_story(
                creator_id=creator_id,
                media_id=mid,
                date_iso=dt.strftime("%Y-%m-%d %H:%M:%S"),
                audience=aud,
                auto_delete_after_sec=auto_delete_after_sec,
            )
            if res.get("ok"):
                planned += 1
                if res.get("story_id"):
                    success_ids.append(res["story_id"])
            else:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{dt} [{aud}]: {res.get('error', '?')[:80]}")
            media_idx += 1
        day += timedelta(days=1)
    return {
        "ok": planned > 0,
        "planned": planned,
        "failed": failed,
        "errors": errors,
        "story_ids": success_ids,
    }


def bulk_schedule_posts(
    creator_id: int,
    media_ids: List[int],
    captions: List[str],
    date_start: str,
    date_end: str,
    post_slots: List[Dict[str, str]],  # [{"time":"HH:MM", "visibility":"public"|"private"}, ...]
    action: str = "delete",
    delay_sec: int = 172800,
    shuffle_media: bool = False,
    randomize_minutes: bool = True,
    # Backward compat
    public_hours: Optional[List[int]] = None,
    private_hours: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Planifie en masse des posts.

    post_slots = liste de {time:"HH:MM", visibility:"public"|"private"}.
    Une publication par (jour, slot). Minutes randomisees 3-25 si
    randomize_minutes=True.
    """
    import random
    from datetime import datetime, timedelta

    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    if not media_ids:
        return {"ok": False, "error": "Aucun media_id"}
    if not captions:
        captions = [""]
    try:
        d_start = datetime.strptime(date_start, "%Y-%m-%d").date()
        d_end = datetime.strptime(date_end, "%Y-%m-%d").date()
    except Exception as e:
        return {"ok": False, "error": f"Date invalide : {e}"}
    if d_end < d_start:
        return {"ok": False, "error": "date_end < date_start"}

    # Parse slots
    parsed_slots: List[tuple] = []  # (hour, minute, visibility)
    # backward compat
    for h in (public_hours or []):
        try:
            parsed_slots.append((int(h), 0, "public"))
        except Exception:
            pass
    for h in (private_hours or []):
        try:
            parsed_slots.append((int(h), 0, "private"))
        except Exception:
            pass
    for sl in (post_slots or []):
        p = _parse_time_slot(sl.get("time", ""))
        if not p:
            continue
        vis = (sl.get("visibility") or "public").strip().lower()
        if vis not in ("public", "private"):
            vis = "public"
        parsed_slots.append((p[0], p[1], vis))
    if not parsed_slots:
        return {"ok": False, "error": "Aucun slot post valide"}

    if shuffle_media:
        media_ids = list(media_ids)
        random.shuffle(media_ids)

    # Trier les slots par heure pour avoir un timeline propre
    parsed_slots.sort(key=lambda x: (x[0], x[1]))

    planned, failed = 0, 0
    errors: List[str] = []
    success_ids: List[int] = []
    media_idx = 0
    day = d_start
    while day <= d_end:
        for (h, base_m, vis) in parsed_slots:
            m = random.randint(3, 25) if randomize_minutes else base_m
            dt = datetime(day.year, day.month, day.day, h, m, 0)
            mid = media_ids[media_idx % len(media_ids)]
            cap = random.choice(captions)
            res = schedule_post(
                creator_id=creator_id,
                media_id=mid,
                date_iso=dt.strftime("%Y-%m-%d %H:%M:%S"),
                caption=cap,
                visibility=vis,
                action=action,
                delay_sec=delay_sec,
            )
            if res.get("ok"):
                planned += 1
                if res.get("post_id"):
                    success_ids.append(res["post_id"])
            else:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{dt} {vis}: {res.get('error', '?')[:80]}")
            media_idx += 1
        day += timedelta(days=1)
    return {
        "ok": planned > 0,
        "planned": planned,
        "failed": failed,
        "errors": errors,
        "post_ids": success_ids,
    }


# ============ Delete post (pour symetrie) ============

def delete_post(post_id: int) -> Dict[str, Any]:
    """Supprime un post planifie. MyPuls utilise /stories/{id} pour TOUT
    (delete generique, le nom est trompeur)."""
    return delete_story(post_id)


def delete_event(event_id: int) -> Dict[str, Any]:
    """Alias generique : supprime un event planifie (story OU post)."""
    return delete_story(event_id)


# ============ Local pending-delete tracker (story auto-delete) ============

import json as _json
from pathlib import Path as _Path

_PENDING_FILE = _Path("data") / "mypuls_pending_deletes.json"


def _load_pending() -> List[Dict[str, Any]]:
    if not _PENDING_FILE.exists():
        return []
    try:
        return _json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_pending(items: List[Dict[str, Any]]):
    _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PENDING_FILE.write_text(_json.dumps(items, indent=2), encoding="utf-8")


def _add_pending_delete(item_id: int, scheduled_date_iso: str,
                        delay_sec: int, kind: str = "story"):
    """Enregistre une suppression future. delete_at = scheduled_date + delay."""
    from datetime import datetime, timedelta
    # parse scheduled date (sans tz)
    s = scheduled_date_iso.strip().replace("T", " ")[:19]
    try:
        sched = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            sched = datetime.strptime(s, "%Y-%m-%d %H:%M")
        except Exception:
            return
    delete_at = sched + timedelta(seconds=int(delay_sec))
    items = _load_pending()
    items.append({
        "id": int(item_id),
        "kind": kind,
        "scheduled_at": sched.isoformat(),
        "delete_at": delete_at.isoformat(),
        "added_at": datetime.utcnow().isoformat(),
    })
    _save_pending(items)


def process_pending_deletes(now=None) -> Dict[str, Any]:
    """A appeler par un cron. Supprime les items dont delete_at est passe.

    Retourne {processed, deleted, failed, errors}.
    """
    from datetime import datetime
    if now is None:
        now = datetime.now()
    items = _load_pending()
    if not items:
        return {"processed": 0, "deleted": 0, "failed": 0, "errors": []}
    remaining: List[Dict[str, Any]] = []
    deleted, failed = 0, 0
    errors: List[str] = []
    for it in items:
        try:
            dt = datetime.fromisoformat(it["delete_at"])
        except Exception:
            # Item corrompu : on le drop
            continue
        if dt > now:
            remaining.append(it)
            continue
        # On supprime
        res = delete_story(int(it["id"]))
        if res.get("ok"):
            deleted += 1
        else:
            failed += 1
            err = str(res.get("error", "?"))[:80]
            errors.append(f"id={it['id']}: {err}")
            # En cas d'erreur on garde dans la file et on retentera plus tard,
            # SAUF si c'est 404 (deja supprime ou inexistant -> drop)
            if "404" not in err and "introuvable" not in err.lower():
                remaining.append(it)
    _save_pending(remaining)
    return {
        "processed": len(items),
        "deleted": deleted,
        "failed": failed,
        "remaining": len(remaining),
        "errors": errors[:10],
    }


def list_pending_deletes() -> List[Dict[str, Any]]:
    """Retourne la liste actuelle des suppressions en attente."""
    return _load_pending()


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
