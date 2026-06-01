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
             json_body: Optional[dict] = None) -> Dict[str, Any]:
    """Appel HTTP unifie. Retourne {ok, data|error, status}."""
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
    err_msg = ""
    if isinstance(body, dict):
        err_msg = body.get("message") or body.get("error") or str(body)[:200]
    else:
        err_msg = str(body)[:200]
    return {"ok": False, "error": f"HTTP {r.status_code}: {err_msg}",
            "status": r.status_code, "raw": body}


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
    raw = src.get("raw") or {}
    data = raw.get("data") if isinstance(raw, dict) else raw
    if not isinstance(data, dict):
        return {"ok": False, "error": "donnees du link source invalides"}
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


def get_folder_links_with_clicks(folder_id: str, days: int = 7) -> Dict[str, Any]:
    """Retourne {ok, links: [{id, u, url, clicks}]} pour un folder donne.

    L API expose les links d un folder via /folders/{id}/stats avec
    include_clicks=true et traffic_data_type=links. Sur 1 a 7 jours
    typiquement (sinon memory limit serveur).

    Note : les links inactifs (0 clicks) ne sont PAS renvoyes par cet
    endpoint. Donc on n a que les "active" links du folder.
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
    # Aggrege par link _id (sum des clicks sur la periode)
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
                "bots": 0,
            }
        by_id[lid]["clicks"] += int(t.get("clicks") or 0)
        by_id[lid]["bots"] += int(t.get("bots") or 0)
    # Tri par clicks descendant
    out = sorted(by_id.values(), key=lambda x: -x["clicks"])
    return {"ok": True, "links": out}


def get_links_grouped_by_folder() -> Dict[str, List[Dict[str, Any]]]:
    """Retourne {folder_name: [...]} - vide pour les folders, juste pour
    initialiser la structure UI. Le detail des links est fetch lazy au
    click sur un folder (via get_folder_links_with_clicks)."""
    return {f["name"]: [] for f in list_folders()}
