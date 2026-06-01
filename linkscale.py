"""Client API Linkscale.to - link-in-bio tool pour OnlyFans/MyM.

Base URL : https://dashboard.linkscale.to/api/v1
Auth     : Authorization: Bearer <api_key>  (prefix 'lk_')

Endpoints utilises :
- GET    /links                  -> liste paginee
- PUT    /links                  -> creer un link
- GET    /links/{id}             -> details
- PATCH  /links/{id}             -> update partiel
- DELETE /links/{id}             -> supprimer
- GET    /folders                -> liste des dossiers (groupes)

La cle API est stockee dans data/linkscale_config.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "linkscale_config.json"
BASE_URL = "https://dashboard.linkscale.to/api/v1"
TIMEOUT = 30


# ============ Config (API key) ============

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def save_api_key(key: str):
    cfg = load_config()
    cfg["api_key"] = (key or "").strip()
    save_config(cfg)


def get_api_key() -> str:
    return load_config().get("api_key", "")


def is_configured() -> bool:
    k = get_api_key()
    return bool(k) and k.startswith("lk_") and len(k) >= 20


# ============ HTTP transport ============

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(method: str, path: str, *, params: Optional[dict] = None,
             json_body: Optional[dict] = None, _retry: int = 1) -> Dict[str, Any]:
    """Appel HTTP unifie. Retourne {ok, data|error, status}.

    Retry automatique sur 429 (rate limit) jusqu a _retry fois apres un sleep.
    """
    import time as _t
    if not is_configured():
        return {"ok": False, "error": "Cle API Linkscale non configuree (prefix lk_)"}
    url = BASE_URL + path
    try:
        r = requests.request(
            method, url, headers=_headers(),
            params=params, json=json_body, timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"Reseau : {e}"}
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:300]}
    if r.status_code in (200, 201, 204):
        if r.status_code == 204:
            return {"ok": True, "data": None, "status": 204}
        return {"ok": True, "data": body.get("data") if isinstance(body, dict) else body,
                "raw": body, "status": r.status_code}
    # Retry sur rate limit
    if r.status_code == 429 and _retry > 0:
        _t.sleep(1.0)
        return _request(method, path, params=params, json_body=json_body, _retry=_retry - 1)
    err_msg = ""
    if isinstance(body, dict):
        err_msg = body.get("message") or body.get("error") or str(body)[:200]
    else:
        err_msg = str(body)[:200]
    return {"ok": False, "error": f"HTTP {r.status_code}: {err_msg}",
            "status": r.status_code, "raw": body}


def _debug_log(msg: str):
    """Append a debug line to data/linkscale_debug.log for live troubleshooting."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_file = DATA_DIR / "linkscale_debug.log"
        from datetime import datetime
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.utcnow().isoformat(timespec='seconds')}] {msg}\n")
    except Exception:
        pass


# ============ Public API ============

def ping() -> Dict[str, Any]:
    """Verifie la connexion en listant 1 link."""
    return _request("GET", "/links", params={"page": 1, "limit": 1})


def list_links(page: int = 1, limit: int = 100,
               search: str = "", tag: str = "") -> Dict[str, Any]:
    """Liste paginee. limit max=100."""
    params: Dict[str, Any] = {"page": page, "limit": min(max(limit, 1), 100)}
    if search:
        params["search"] = search
    if tag:
        params["tag"] = tag
    return _request("GET", "/links", params=params)


def list_all_links(max_pages: int = 50) -> Dict[str, Any]:
    """Itere toutes les pages jusqu a max_pages. Retourne {ok, links[], total}."""
    items: List[Dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        res = list_links(page=page, limit=100)
        if not res.get("ok"):
            return res
        raw = res.get("raw") or {}
        data = raw.get("data") if isinstance(raw, dict) else None
        # Linkscale renvoie soit data = [...] direct, soit data = {items: [...]}
        chunk: List[Dict[str, Any]] = []
        if isinstance(data, list):
            chunk = data
        elif isinstance(data, dict):
            chunk = data.get("items") or data.get("links") or []
        if not chunk:
            break
        items.extend(chunk)
        # Check pagination
        pag = raw.get("pagination") if isinstance(raw, dict) else None
        if pag and isinstance(pag, dict):
            total_pages = pag.get("total_pages") or pag.get("totalPages")
            if total_pages and page >= int(total_pages):
                break
        if len(chunk) < 100:
            break
        page += 1
    return {"ok": True, "links": items, "total": len(items)}


def get_link(link_id: str) -> Dict[str, Any]:
    return _request("GET", f"/links/{link_id}")


def create_link(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cree un link. payload doit contenir au moins :
    - type : 'l_p' (landing page bio) ou 'd_l' (direct link)
    - u : shortcode/username unique
    - url : URL cible (pour direct link)
    Champs optionnels : domain, n (display name), bio, links[], pp, cover,
    background, template, shield, folders[], enabled, note.
    """
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload doit etre un dict"}
    return _request("PUT", "/links", json_body=payload)


def update_link(link_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    return _request("PATCH", f"/links/{link_id}", json_body=patch)


def delete_link(link_id: str) -> Dict[str, Any]:
    return _request("DELETE", f"/links/{link_id}")


def enable_link(link_id: str) -> Dict[str, Any]:
    return update_link(link_id, {"enabled": True})


def disable_link(link_id: str) -> Dict[str, Any]:
    return update_link(link_id, {"enabled": False})


def duplicate_link(link_id: str, new_shortcode: str = "") -> Dict[str, Any]:
    """Duplique un link en gardant ses folders + tous les autres champs.

    User wants : "quand je duplique je veux que tu range dans le meme dossier"
    -> on copie folders[] tel quel dans le nouveau link.

    Si new_shortcode est vide, on append "_copy" au shortcode original.
    """
    src = get_link(link_id)
    if not src.get("ok"):
        return src
    # Linkscale peut renvoyer le link sous differentes formes :
    # - {data: {_id, u, ...}}  -> raw.data
    # - {link: {_id, u, ...}}  -> raw.link
    # - {_id, u, ...}          -> raw direct
    raw = src.get("raw") or {}
    data = None
    if isinstance(raw, dict):
        if isinstance(raw.get("data"), dict):
            data = raw["data"]
        elif isinstance(raw.get("link"), dict):
            data = raw["link"]
        elif raw.get("_id") or raw.get("u"):
            data = raw
    if not isinstance(data, dict):
        # Fallback : utiliser src.data si dispo
        sd = src.get("data")
        if isinstance(sd, dict) and (sd.get("_id") or sd.get("u")):
            data = sd
    if not isinstance(data, dict):
        return {"ok": False, "error": f"donnees du link source invalides (raw keys: {list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__})"}
    # Copy les fields createur
    payload: Dict[str, Any] = {}
    for k in ("type", "u", "domain", "url", "n", "bio", "links", "pp", "cover",
              "background", "template", "cs_template", "shield", "folders",
              "enabled", "note", "dynamic_informations"):
        if k in data:
            payload[k] = data[k]
    # Override shortcode pour eviter collision
    orig_u = data.get("u") or ""
    payload["u"] = (new_shortcode or (orig_u + "_copy")).strip()
    return create_link(payload)


# ============ Folders ============

def list_folders() -> List[Dict[str, Any]]:
    """Retourne la liste plate des dossiers Linkscale : [{id, name, links_count}].

    L API renvoie : {project_id, project, folders: [{_id, name, links_count,
    created_at, ...}]}.
    """
    res = _request("GET", "/folders")
    if not res.get("ok"):
        return []
    raw = res.get("raw") or {}
    folders = raw.get("folders") if isinstance(raw, dict) else []
    if not isinstance(folders, list):
        return []
    out = []
    for f in folders:
        if isinstance(f, dict):
            out.append({
                "id": f.get("_id") or f.get("id") or "",
                "name": f.get("name") or "?",
                "links_count": int(f.get("links_count") or 0),
                "created_at": f.get("created_at") or "",
            })
    return out


def get_folder_id_by_name(name: str) -> Optional[str]:
    """Cherche un folder par nom (case-insensitive). Retourne son _id ou None."""
    if not name:
        return None
    needle = name.strip().lower()
    for f in list_folders():
        if f.get("name", "").strip().lower() == needle:
            return f.get("id")
    return None


def _iso_date_offset(days: int) -> str:
    """Retourne YYYY-MM-DD du jour - N jours (today si days=0)."""
    from datetime import date, timedelta
    return (date.today() - timedelta(days=max(days, 0))).isoformat()


def get_folder_stats(folder_id: str, from_date: str = "", to_date: str = "") -> Dict[str, Any]:
    """Stats d un folder Linkscale. Format response :
    {options, folder_id, date_range, project, stats: {summary, daily_traffic, ...}}

    Note : include_clicks=true crashe le serveur (memory limit) donc on ne le
    passe pas. On obtient juste les totaux dans stats.summary.
    """
    if not folder_id:
        return {"ok": False, "error": "folder_id requis"}
    params: Dict[str, Any] = {}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return _request("GET", f"/folders/{folder_id}/stats", params=params)


def _extract_total_clicks(stats_response: Dict[str, Any]) -> int:
    """Extrait stats.summary.totalClicks du raw response."""
    if not stats_response.get("ok"):
        return 0
    raw = stats_response.get("raw") or {}
    if not isinstance(raw, dict):
        return 0
    stats = raw.get("stats") or {}
    summary = stats.get("summary") if isinstance(stats, dict) else {}
    if not isinstance(summary, dict):
        return 0
    return int(summary.get("totalClicks") or summary.get("uniqueUsers") or 0)


def get_folder_click_summary(folder_id: str) -> Dict[str, int]:
    """Resume click pour un folder : {today, last_7d, last_30d}.

    Fait 3 appels API courts (1 par range). Plus rapide qu une seule grosse
    requete qui crashait le serveur Linkscale.
    """
    out = {"today": 0, "last_7d": 0, "last_30d": 0}
    if not folder_id:
        return out
    today = _iso_date_offset(0)
    out["today"] = _extract_total_clicks(get_folder_stats(folder_id, today, today))
    out["last_7d"] = _extract_total_clicks(get_folder_stats(folder_id, _iso_date_offset(6), today))
    out["last_30d"] = _extract_total_clicks(get_folder_stats(folder_id, _iso_date_offset(29), today))
    return out


def get_folder_total_clicks(folder_id: str, from_date: str, to_date: str) -> int:
    """Retourne juste le total de clicks d un folder sur une periode arbitraire.

    N appel pas include_clicks=true (qui crashe sur >7j) - juste summary.
    Marche jusqu a 30+ jours.
    """
    if not folder_id:
        return 0
    res = get_folder_stats(folder_id, from_date=from_date, to_date=to_date)
    return _extract_total_clicks(res)


def get_folder_daily_clicks(folder_id: str, days: int = 7) -> List[int]:
    """Liste des clicks par jour sur les N derniers jours.

    Utilise include_clicks=true qui crashe sur >7j, donc on cap a 7.
    Pour periodes plus longues -> on retourne des zeros aux jours hors range.
    """
    if not folder_id:
        return [0] * days
    # Capped a 7 pour eviter le crash
    span = min(days, 7)
    res = _request("GET", f"/folders/{folder_id}/stats", params={
        "from": _iso_date_offset(span),
        "to": _iso_date_offset(0),
        "include_clicks": "true",
        "traffic_data_type": "links",
    })
    daily_map: Dict[str, int] = {}
    if res.get("ok"):
        raw = res.get("raw") or {}
        stats = raw.get("stats", {}) if isinstance(raw, dict) else {}
        traffic = stats.get("trafficByLinks") or []
        for t in traffic if isinstance(traffic, list) else []:
            date_raw = (t.get("date") or "")[:10]
            if date_raw:
                daily_map[date_raw] = daily_map.get(date_raw, 0) + int(t.get("clicks") or 0)
    # Build la liste sur N jours (vieux -> recent), 0 si jour pas trouve
    from datetime import date, timedelta
    out = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        out.append(daily_map.get(d, 0))
    return out


def get_link_click_summary(link_id: str) -> Dict[str, int]:
    """Idem pour un link individuel (3 appels API)."""
    out = {"today": 0, "last_7d": 0, "last_30d": 0}
    if not link_id:
        return out
    today = _iso_date_offset(0)
    out["today"] = _extract_total_clicks(_request("GET", f"/links/{link_id}/stats", params={"from": today, "to": today}))
    out["last_7d"] = _extract_total_clicks(_request("GET", f"/links/{link_id}/stats", params={"from": _iso_date_offset(6), "to": today}))
    out["last_30d"] = _extract_total_clicks(_request("GET", f"/links/{link_id}/stats", params={"from": _iso_date_offset(29), "to": today}))
    return out


def list_all_links_full() -> List[Dict[str, Any]]:
    """Fetch TOUS les links du projet via pagination /links?limit=100.

    Retourne la liste plate des link objects (avec _id, u, url, cs_template,
    enabled, created_at, etc.).
    """
    out: List[Dict[str, Any]] = []
    offset = 0
    page = 1
    while True:
        res = _request("GET", "/links", params={"page": page, "limit": 100})
        if not res.get("ok"):
            break
        raw = res.get("raw") or {}
        links = raw.get("links") or []
        if not isinstance(links, list) or not links:
            break
        out.extend(links)
        # Check pagination
        pag = raw.get("pagination") or {}
        if not pag.get("has_more"):
            break
        page += 1
        if page > 20:  # safety
            break
    return out


# Cache persistant disque pour le mapping cs_template -> folder_name
TEMPLATE_MAP_FILE = DATA_DIR / "linkscale_template_map.json"

# Mappings pre-decouverts pour les folders de l user (precharger pour eviter
# les 27s de fetch au premier load). Ces IDs sont stables tant que les
# templates Linkscale ne changent pas.
KNOWN_TEMPLATE_MAP = {
    "69ecd46f0cb2b33cddd8569a": "amelia",
    "69ecd814a2e60929d5faa36a": "julia",
    "69ecd5a9409d299cce8a0eaf": "lola",
    "69ecffa1320e209903fcab14": "emma",
    "6a0e6170c6728b3ed29d0e77": "Jessy",
}


def _load_template_map() -> Dict[str, Any]:
    if not TEMPLATE_MAP_FILE.exists():
        return {"ts": 0, "map": dict(KNOWN_TEMPLATE_MAP)}
    try:
        d = json.loads(TEMPLATE_MAP_FILE.read_text(encoding="utf-8"))
        # Merge avec les known pour ne jamais perdre les pre-decouverts
        merged = dict(KNOWN_TEMPLATE_MAP)
        merged.update(d.get("map", {}))
        return {"ts": d.get("ts", 0), "map": merged}
    except Exception:
        return {"ts": 0, "map": dict(KNOWN_TEMPLATE_MAP)}


def _save_template_map(cache: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_MAP_FILE.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_template_to_folder_map(force_refresh: bool = False) -> Dict[str, str]:
    """Retourne {cs_template_id: folder_name}.

    - Cache disque (data/linkscale_template_map.json), valide 24h
    - Pre-charge avec KNOWN_TEMPLATE_MAP au premier load (instantane)
    - Refresh asynchrone si > 24h ou force_refresh

    Strategie pour les nouvelles entrees : pour chaque folder NON deja dans
    le map, fetch 1 link actif et lit son cs_template.
    """
    import time
    cache = _load_template_map()
    age = time.time() - cache.get("ts", 0)
    current_map = cache.get("map", {})
    # Si on a des entries connues et cache jeune, retourne direct
    if not force_refresh and current_map and age < 86400:
        return current_map
    # Sinon, fetch les folders manquants
    try:
        folders = list_folders()
    except Exception:
        return current_map
    existing_names = {v.lower() for v in current_map.values()}
    new_map = dict(current_map)
    for f in folders:
        fname = f.get("name", "")
        if not fname or fname.lower() in existing_names:
            continue
        try:
            res = get_folder_links_with_clicks(f["id"], days=7)
            active = res.get("links") or []
            if not active:
                continue
            detail = get_link(active[0]["id"])
            cs = detail.get("raw", {}).get("link", {}).get("cs_template")
            if cs:
                new_map[cs] = fname
            time.sleep(0.7)  # respect rate limit 2/sec
        except Exception:
            continue
    _save_template_map({"ts": time.time(), "map": new_map})
    return new_map


def get_all_links_in_folder(folder_name: str) -> List[Dict[str, Any]]:
    """Retourne TOUS les links d un folder (actifs + inactifs).

    Cross-reference :
    1. cs_template -> folder mapping (cache disque)
    2. Filtre les 88 links totaux par leur cs_template
    """
    if not folder_name:
        _debug_log("get_all_links_in_folder: folder_name vide")
        return []
    tpl_map = get_template_to_folder_map()
    _debug_log(f"get_all_links_in_folder({folder_name!r}) tpl_map={len(tpl_map)} entries")
    # Find cs_template(s) for this folder name
    target_templates = {tpl for tpl, fname in tpl_map.items() if fname.lower() == folder_name.lower()}
    if not target_templates:
        _debug_log(f"get_all_links_in_folder({folder_name!r}) AUCUN template trouve - tpl_map: {tpl_map}")
        return []
    _debug_log(f"get_all_links_in_folder({folder_name!r}) target_templates={target_templates}")
    all_links = list_all_links_full()
    _debug_log(f"list_all_links_full -> {len(all_links)} links")
    result = [l for l in all_links if l.get("cs_template") in target_templates]
    _debug_log(f"get_all_links_in_folder({folder_name!r}) -> {len(result)} links matchent")
    return result


def get_folder_links_with_clicks(folder_id: str, days: int = 7) -> Dict[str, Any]:
    """Retourne {ok, links: [{id, u, url, clicks, today, daily, bots}]}.

    Inclut le breakdown par jour pour pouvoir afficher des sparklines.
    daily = [{date, clicks}] ordonne du plus ancien au plus recent.
    today = clicks du jour J (date == today_str).
    clicks = total sur la periode.
    """
    if not folder_id:
        return {"ok": False, "links": []}
    res = _request("GET", f"/folders/{folder_id}/stats", params={
        "from": _iso_date_offset(days),
        "to": _iso_date_offset(0),
        "include_clicks": "true",
        "traffic_data_type": "links",
    })
    if not res.get("ok"):
        return {"ok": False, "links": [], "error": res.get("error")}
    raw = res.get("raw") or {}
    stats = raw.get("stats", {}) if isinstance(raw, dict) else {}
    traffic = stats.get("trafficByLinks") or stats.get("traffic_by_links") or []
    if not isinstance(traffic, list):
        return {"ok": True, "links": []}
    # Build daily series par link
    from datetime import date as _date
    today_str = _date.today().isoformat()
    by_id: Dict[str, Dict[str, Any]] = {}
    for t in traffic:
        if not isinstance(t, dict):
            continue
        lid = t.get("id") or t.get("_id")
        if not lid:
            continue
        if lid not in by_id:
            by_id[lid] = {
                "id": lid,
                "u": t.get("u") or "?",
                "url": t.get("url") or "",
                "host": t.get("host") or "",
                "note": t.get("note") or "",
                "clicks": 0,
                "today": 0,
                "bots": 0,
                "daily": {},  # {date_str: clicks}
            }
        clicks = int(t.get("clicks") or 0)
        by_id[lid]["clicks"] += clicks
        by_id[lid]["bots"] += int(t.get("bots") or 0)
        # Date format de l API : "2026-05-31 00:00:00"
        date_raw = (t.get("date") or "")[:10]
        if date_raw:
            by_id[lid]["daily"][date_raw] = by_id[lid]["daily"].get(date_raw, 0) + clicks
            if date_raw == today_str:
                by_id[lid]["today"] += clicks
    # Convertit daily dict -> liste ordonnee
    for lid, data in by_id.items():
        d = data.pop("daily", {})
        data["daily"] = [{"date": k, "clicks": d[k]} for k in sorted(d.keys())]
    out = sorted(by_id.values(), key=lambda x: -x["clicks"])
    return {"ok": True, "links": out}


def get_links_grouped_by_folder() -> Dict[str, List[Dict[str, Any]]]:
    """Retourne {folder_name: [...]} - vide pour les folders, juste pour
    initialiser la structure UI. Le detail des links est fetch lazy au
    click sur un folder (via get_folder_links_with_clicks)."""
    return {f["name"]: [] for f in list_folders()}
