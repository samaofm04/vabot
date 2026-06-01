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

def list_folders() -> Dict[str, Any]:
    """Liste les dossiers (groupes) avec leur count de links."""
    return _request("GET", "/folders")


def get_links_grouped_by_folder() -> Dict[str, List[Dict[str, Any]]]:
    """Retourne {folder_name: [links...]} - utile pour l UI groupee."""
    all_res = list_all_links()
    if not all_res.get("ok"):
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {"(sans dossier)": []}
    for link in all_res.get("links", []):
        folders = link.get("folders") or []
        if not folders:
            out["(sans dossier)"].append(link)
            continue
        for f in folders:
            # folder peut etre un id string ou un dict {id, name}
            fname = f.get("name") if isinstance(f, dict) else str(f)
            out.setdefault(fname or "(sans dossier)", []).append(link)
    # Drop la categorie vide
    if not out.get("(sans dossier)"):
        out.pop("(sans dossier)", None)
    return out
