"""Client MCP minimal pour l'API GetMySocial.

L'endpoint MCP de GetMySocial (https://mcp.getmysocial.com/mcp) parle
JSON-RPC sur HTTP avec une réponse en Server-Sent Events.

Ce module expose une API simple : ping, list_links, create_directlink,
delete_link, enable_link, disable_link.

La clé API est stockée dans data/gms_config.json.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "gms_config.json"
MCP_URL = "https://mcp.getmysocial.com/mcp"
TIMEOUT = 60


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
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def save_api_key(key: str):
    cfg = load_config()
    cfg["api_key"] = key.strip()
    save_config(cfg)


def get_api_key() -> str:
    return load_config().get("api_key", "")


def is_configured() -> bool:
    k = get_api_key()
    return bool(k) and k.startswith("gms_")


# ============ MCP transport ============

def _parse_sse(text: str) -> Optional[dict]:
    """Extrait le payload JSON d'une réponse SSE de la forme `data: {...}`."""
    m = re.search(r"data:\s*(\{.*\})", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _make_session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    return s


def _initialize(s: requests.Session) -> bool:
    """Effectue le handshake MCP (initialize + notifications/initialized)."""
    try:
        init_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "va-bot", "version": "1.0"},
            },
        }
        r = s.post(MCP_URL, json=init_body, timeout=TIMEOUT)
        if r.status_code != 200:
            return False
        sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        if sid:
            s.headers["Mcp-Session-Id"] = sid
        # notifications/initialized — pas de réponse attendue
        s.post(MCP_URL, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=TIMEOUT)
        return True
    except Exception:
        return False


def list_tools() -> Dict[str, Any]:
    """Liste les outils MCP exposés par GetMySocial (découverte : teams, etc.)."""
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "error": "Clé API GetMySocial non configurée"}
    s = _make_session(api_key)
    if not _initialize(s):
        return {"ok": False, "error": "Impossible d'initialiser la session MCP"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    try:
        r = s.post(MCP_URL, json=body, timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code} : {r.text[:200]}"}
    data = _parse_sse(r.text)
    tools = ((data or {}).get("result") or {}).get("tools") or []
    return {"ok": True, "tools": [{"name": t.get("name"), "desc": (t.get("description") or "")[:80]} for t in tools]}


def _call_tool(tool_name: str, args: Optional[dict] = None) -> Dict[str, Any]:
    """Appelle un outil MCP. Retourne {'ok': bool, 'data': ..., 'error': ...}."""
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "error": "Clé API GetMySocial non configurée"}
    s = _make_session(api_key)
    if not _initialize(s):
        return {"ok": False, "error": "Impossible d'initialiser la session MCP"}
    body = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 1_000_000,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args or {}},
    }
    try:
        r = s.post(MCP_URL, json=body, timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code} : {r.text[:300]}"}
    data = _parse_sse(r.text)
    if not data:
        return {"ok": False, "error": f"Réponse invalide : {r.text[:300]}"}
    if "error" in data:
        err = data["error"]
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        return {"ok": False, "error": msg or "Erreur MCP"}
    result = data.get("result") or {}
    # Le résultat des outils MCP est sous result.content[0].text (JSON sérialisé)
    content = result.get("content") or []
    if content and isinstance(content[0], dict) and "text" in content[0]:
        raw_text = content[0]["text"]
        try:
            payload = json.loads(raw_text)
        except Exception:
            # Sometimes MCP returns Python-repr instead of JSON (single quotes etc.)
            try:
                import ast as _ast
                payload = _ast.literal_eval(raw_text)
            except Exception:
                payload = raw_text
        # Détecter les erreurs renvoyées par l'outil GMS
        if isinstance(payload, dict) and payload.get("error"):
            return {"ok": False, "error": str(payload.get("error"))[:500]}
        # Certaines erreurs arrivent en plain text "Error 400 (...)" — les attraper
        if isinstance(payload, str):
            stripped = payload.strip()
            if stripped.lower().startswith("error ") or stripped.lower().startswith("error("):
                return {"ok": False, "error": stripped[:500]}
        return {"ok": True, "data": payload}
    return {"ok": True, "data": result}


# ============ Wrappers haut-niveau ============

def ping() -> Dict[str, Any]:
    """Test de connectivité + auth. Retourne {ok, user_id, error}."""
    res = _call_tool("_ping")
    if not res["ok"]:
        return res
    data = res["data"]
    if isinstance(data, dict) and data.get("ok"):
        return {"ok": True, "user_id": data.get("user_id", "")}
    return {"ok": False, "error": f"Réponse inattendue : {data}"}


def list_links(limit: int = 100) -> Dict[str, Any]:
    """Une page de liens (max 100). Retourne {ok, links, has_more, next_cursor, error}."""
    res = _call_tool("list_links", {"limit": min(max(limit, 1), 100)})
    if not res["ok"]:
        return res
    data = res["data"] or {}
    return {
        "ok": True,
        "links": (data.get("data") if isinstance(data, dict) else []) or [],
        "has_more": bool(data.get("has_more")) if isinstance(data, dict) else False,
        "next_cursor": data.get("next_cursor") if isinstance(data, dict) else None,
    }


def list_all_links(max_pages: int = 50) -> Dict[str, Any]:
    """Paginate pour récupérer TOUS les liens du compte.

    Limite de sécurité : max_pages * 100 liens (par défaut 5000).
    """
    all_links: List[dict] = []
    cursor: Optional[str] = None
    for _ in range(max_pages):
        args: Dict[str, Any] = {"limit": 100}
        if cursor:
            args["cursor"] = cursor
        res = _call_tool("list_links", args)
        if not res["ok"]:
            return res
        data = res["data"] or {}
        # Si MCP retourne du texte brut (réponse trop large pour le parse JSON),
        # on essaie de la re-parser ici. Sinon on stoppe la pagination proprement.
        if isinstance(data, str):
            try:
                import json as _json_p
                data = _json_p.loads(data)
            except Exception:
                break
        if not isinstance(data, dict):
            break
        page = data.get("data") or []
        all_links.extend(page)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return {"ok": True, "links": all_links}


def categorize_link(link: dict) -> str:
    """Détecte la catégorie (= modèle) d'un lien.

    Stratégie (par ordre de priorité) :
    1. SHORTCODE contient un nom d'identité connue (`xxxxamelia`, `jessyXXX`, …)
       — c'est le signal le plus fiable pour les dupes VA N qui sinon
       seraient catégorisés comme "VA N" littéral.
    2. Display_name nettoyé matche un nom connu.
    3. URL OnlyFans : déduire l'identité du path.
    4. Fallback : "VA N" si display_name est juste "VA <chiffre>", sinon
       premier mot du display_name.
    """
    import re as _re
    name = (link.get("display_name") or "").strip()
    url = link.get("url") or ""
    shortcode = (link.get("shortcode") or "").lower()

    KNOWN = ["Amelia", "Lola", "Julia", "Sarah", "Emma", "Khloe", "Jessy",
             "Boo7", "Mirabelle", "Enzo", "Dem boss"]

    # 1) Shortcode : signal le plus fiable pour les dupes nommés "VA N"
    for k in KNOWN:
        if k.lower() in shortcode:
            return k

    # 2) Display_name nettoyé
    clean = _re.sub(r"\s*\(Copy\)\s*", " ", name, flags=_re.IGNORECASE).strip()
    m = _re.match(r"^VA\s+(.+)$", clean, _re.IGNORECASE)
    if m:
        rest = m.group(1).strip()
        if rest.isdigit() or _re.match(r"^\d+$", rest):
            if "jessyewdiference" in url.lower():
                return "Jessy"
            return f"VA {rest}"
        clean = rest

    lower = clean.lower()
    for k in KNOWN:
        if k.lower() in lower:
            return k

    # 3) URL OnlyFans
    if url:
        m2 = _re.search(r"onlyfans\.com/([a-z0-9_]+)", url, _re.IGNORECASE)
        if m2:
            user = m2.group(1).lower()
            for k in KNOWN:
                if k.lower() in user:
                    return k

    # 4) Premier mot du display_name
    if clean:
        first = clean.split()[0]
        if len(first) >= 2:
            return first.title()

    return "Autre"


def create_directlink(shortcode: str, url: str, display_name: str = "") -> Dict[str, Any]:
    """Crée un directlink (redirect simple). Retourne {ok, link, error}."""
    args = {
        "shortcode": shortcode.strip(),
        "type": "directlink",
        "url": url.strip(),
    }
    if display_name.strip():
        args["display_name"] = display_name.strip()
    res = _call_tool("create_link", args)
    if not res["ok"]:
        return res
    return {"ok": True, "link": res["data"]}


def get_analytics_overview(start_date: str = "", end_date: str = "",
                            link_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Récupère les analytics (clics + visiteurs) sur une période.

    start_date / end_date : format YYYY-MM-DD (inclusif).
    link_ids : optionnel, restreindre à un sous-ensemble de liens.
    Retourne : {ok, data: {totals, daily}, error}
    """
    args: Dict[str, Any] = {}
    if start_date:
        args["start_date"] = start_date
    if end_date:
        args["end_date"] = end_date
    if link_ids:
        args["link_ids"] = link_ids[:200]
    res = _call_tool("get_analytics_overview", args)
    return res


def clicks_for_link(link_id: str, start_date: str, end_date: str) -> Optional[int]:
    """Nombre de clics d'UN lien sur une periode (YYYY-MM-DD inclusif).
    Retourne None si l'appel echoue, sinon un int (0 si pas de clics)."""
    if not link_id:
        return None
    res = get_analytics_overview(start_date, end_date, link_ids=[link_id])
    if not res.get("ok"):
        return None
    d = res.get("data")
    if not isinstance(d, dict):
        d = res
    try:
        return int(d.get("total_clicks") or 0)
    except Exception:
        return 0


def clicks_for_ids(link_ids: List[str], start_date: str, end_date: str) -> Optional[int]:
    """Total de clics pour une LISTE de liens sur une periode (YYYY-MM-DD).
    Batch par 200 (limite analytics). Retourne None si UN SEUL batch echoue
    (le total serait partiel/faux — chiffre de paie, on prefere « indispo » a
    un sous-comptage credible), sinon la somme (0 si liste vide)."""
    if not link_ids:
        return 0
    total = 0
    for i in range(0, len(link_ids), 200):
        chunk = link_ids[i:i + 200]
        res = get_analytics_overview(start_date, end_date, link_ids=chunk)
        if not res.get("ok"):
            return None  # batch echoue -> total non fiable
        d = res.get("data")
        if not isinstance(d, dict):
            d = res
        try:
            total += int(d.get("total_clicks") or 0)
        except Exception:
            return None  # reponse illisible -> total non fiable
    return total


def _norm_handle(s: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_link_for_handle(handle: str, links: List[dict]) -> Optional[dict]:
    """Retrouve le lien GMS d'un VA a partir de son pseudo Discord (handle).
    Les liens crees recemment ont display_name = 'va_@<handle>'. Match :
      1) display_name normalise == 'va' + handle   (ex: va_@ozen28 -> vaozen28)
      2) le handle apparait dans le display_name ou le shortcode
    Retourne le 1er lien correspondant, sinon None."""
    h = _norm_handle(handle)
    if not h or not links:
        return None
    target = "va" + h
    for l in links:
        if _norm_handle(l.get("display_name")) == target:
            return l
    for l in links:
        dn = _norm_handle(l.get("display_name"))
        if dn and h in dn and dn.startswith("va"):
            return l
    for l in links:
        if h in _norm_handle(l.get("shortcode")):
            return l
    return None


_GROUPED_CACHE: Dict[str, Any] = {"ts": 0, "data": None}
_GROUPED_TTL = 300  # 5 min


def get_links_grouped_by_model(force_refresh: bool = False) -> Dict[str, List[str]]:
    """Récupère tous les liens et les groupe par modèle détecté.

    Cache 5 min pour éviter de paginer tous les liens à chaque render.
    Retourne : {model_name: [link_id_1, link_id_2, ...]}
    """
    import time as _t
    now = _t.time()
    if not force_refresh and _GROUPED_CACHE.get("data") and (now - _GROUPED_CACHE.get("ts", 0)) < _GROUPED_TTL:
        return _GROUPED_CACHE["data"]
    res = list_all_links()
    if not res.get("ok"):
        return _GROUPED_CACHE.get("data") or {}
    grouped: Dict[str, List[str]] = {}
    for link in res["links"]:
        model = categorize_link(link)
        grouped.setdefault(model, []).append(link.get("id", ""))
    _GROUPED_CACHE["ts"] = now
    _GROUPED_CACHE["data"] = grouped
    return grouped


def invalidate_grouping_cache():
    """À appeler après create/delete/update de lien pour forcer un refresh."""
    _GROUPED_CACHE["ts"] = 0
    _GROUPED_CACHE["data"] = None


_TEMPLATES_FILE = DATA_DIR / "gms_templates.json"


def load_templates() -> Dict[str, str]:
    """Mapping {model_lowercase: link_id} - template link par modèle."""
    if not _TEMPLATES_FILE.exists():
        return {}
    try:
        return json.loads(_TEMPLATES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_templates(data: Dict[str, str]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _TEMPLATES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def set_template_for_model(model: str, link_id: str):
    tpls = load_templates()
    key = (model or "").strip().lower()
    if not key:
        return
    if link_id and link_id.startswith("lnk_"):
        tpls[key] = link_id
    else:
        tpls.pop(key, None)
    save_templates(tpls)


def generate_random_prefix(length: int = 4) -> str:
    """Génère N lettres minuscules aléatoires."""
    import random
    import string
    return "".join(random.choices(string.ascii_lowercase, k=length))


def duplicate_link(source_link_id: str, new_shortcode: str,
                    new_display_name: str = "", new_url: str = "",
                    team_id: Optional[str] = None) -> Dict[str, Any]:
    """Duplique un lien existant — copie TOUTE la config (boutons, pixels, design,
    bot protection, etc.) avec un nouveau shortcode + display_name.

    Optionnel : new_url pour changer l'URL de destination (directlink uniquement).
    Pour ça on appelle update_link après le duplicate.

    team_id : optionnel — si fourni, le duplicate est créé dans ce team
              (workspace). Sans ça, le duplicate va dans le workspace owner.

    Retourne {ok, link, error}.
    """
    sc = new_shortcode.strip()
    if not source_link_id or not sc:
        return {"ok": False, "error": "source_link_id et new_shortcode requis"}
    args = {
        "link_id": source_link_id,
        "shortcode": sc,
        "display_name": (new_display_name or sc).strip()[:60],
    }
    if team_id:
        args["team_id"] = team_id if team_id.startswith("tm_") else f"tm_{team_id}"
    res = _call_tool("duplicate_link", args)
    if not res.get("ok"):
        return res
    new_link = res.get("data") or {}
    # MCP renvoie parfois du repr string -> on tente un re-parse safe
    if isinstance(new_link, str):
        try:
            import ast as _ast
            new_link = _ast.literal_eval(new_link)
        except Exception:
            try:
                import json as _json
                new_link = _json.loads(new_link)
            except Exception:
                new_link = {}
    new_id = new_link.get("id") if isinstance(new_link, dict) else None

    # Si une nouvelle URL est fournie ET qu'on a bien l'id, on patch le lien.
    # update_link exige link_id + url + display_name + typeLink="directlink"
    new_url_clean = (new_url or "").strip()
    if new_url_clean and new_id:
        try:
            upd_res = _call_tool("update_link", {
                "link_id": new_id,
                "url": new_url_clean,
                "display_name": args["display_name"],
                "typeLink": "directlink",
            })
            if upd_res.get("ok"):
                new_link = upd_res.get("data") or new_link
        except Exception:
            pass
    # Invalider le cache pour rafraîchir la liste à la prochaine lecture
    try:
        invalidate_grouping_cache()
    except Exception:
        pass
    return {"ok": True, "link": new_link}


def delete_link(link_id: str) -> Dict[str, Any]:
    res = _call_tool("delete_link", {"link_id": link_id})
    return res


def enable_link(link_id: str) -> Dict[str, Any]:
    return _call_tool("enable_link", {"link_id": link_id})


def disable_link(link_id: str) -> Dict[str, Any]:
    return _call_tool("disable_link", {"link_id": link_id})


# ============ Groupes dashboard (API privée getmysocial.com/api) ============
# L'API MCP publique n'expose pas la création/listage des groupes du dashboard.
# On utilise l'API privée que le frontend GetMySocial appelle directement, avec
# le cookie de session récupéré par l'utilisateur depuis son navigateur.
#
# Endpoint : PATCH https://getmysocial.com/api/links/{linkIdSansPrefix}/group
# Body     : {"groupId": "<24hex>", "beforeLinkId": null, "afterLinkId": null}
# Auth     : Cookie de session GMS (à pasted via /gms/set_session_cookie).

_GROUPS_FILE = DATA_DIR / "gms_groups.json"
PRIVATE_API_BASE = "https://getmysocial.com/api"

# Groupes connus, indexes par "<team_id_or_empty>:<folder_lowercase>".
# Empty team_id = workspace Personal/default. Avec prefix tm_ = workspace team.
# Pre-rempli depuis HAR + decouverte API (Personal + marche francais).
_DEFAULT_GROUPS = {
    # Personal workspace
    ":jessye": "6a1998353b5d0de542f7974d",
    ":lola": "6a1ea42fd882dd2173b8a492",
    ":tempalte us jessy": "6a1d5640d925609fedf92c14",
    ":enzo ads": "69fd62631a577cba4face0a4",
    # marche francais workspace (tm_6a1ea410d882dd2173b8a315)
    "tm_6a1ea410d882dd2173b8a315:lola": "6a1eab3bece5b8bb28394e75",
    "tm_6a1ea410d882dd2173b8a315:emma": "6a1eab57ece5b8bb2839506a",
    "tm_6a1ea410d882dd2173b8a315:amelia": "6a1eab40bc03b4376dd14e5e",
    "tm_6a1ea410d882dd2173b8a315:julia": "6a1eab43bc03b4376dd14f28",
}


def load_groups_mapping() -> Dict[str, str]:
    """Mapping {f'{team_id_or_empty}:{folder_lower}': group_id_24hex}."""
    if not _GROUPS_FILE.exists():
        return dict(_DEFAULT_GROUPS)
    try:
        on_disk = json.loads(_GROUPS_FILE.read_text(encoding="utf-8"))
        merged = dict(_DEFAULT_GROUPS)
        # Migration : ancien format sans prefix ":" était considéré Personal
        for k, v in on_disk.items():
            if ":" not in k:
                merged[f":{k.lower()}"] = v
            else:
                merged[k] = v
        return merged
    except Exception:
        return dict(_DEFAULT_GROUPS)


def save_groups_mapping(mapping: Dict[str, str]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _GROUPS_FILE.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")


def set_group_for_folder(folder: str, group_id: str, team_id: Optional[str] = None):
    m = load_groups_mapping()
    folder_key = (folder or "").strip().lower()
    if not folder_key:
        return
    tid = (team_id or "").strip()
    if tid and not tid.startswith("tm_"):
        tid = "tm_" + tid
    key = f"{tid}:{folder_key}"
    if group_id and group_id.strip():
        m[key] = group_id.strip()
    else:
        m.pop(key, None)
    save_groups_mapping(m)


def get_group_id_for_folder(folder: str, team_id: Optional[str] = None) -> Optional[str]:
    m = load_groups_mapping()
    folder_key = (folder or "").strip().lower()
    if not folder_key:
        return None
    tid = (team_id or "").strip()
    if tid and not tid.startswith("tm_"):
        tid = "tm_" + tid
    # Lookup team-scoped first, fallback sur Personal
    return m.get(f"{tid}:{folder_key}") or (m.get(f":{folder_key}") if tid else None) or m.get(f":{folder_key}")


def save_session_cookie(cookie: str):
    cfg = load_config()
    cfg["session_cookie"] = (cookie or "").strip()
    save_config(cfg)


def get_session_cookie() -> str:
    return load_config().get("session_cookie", "")


PUBLIC_REST_BASE = "https://api.getmysocial.com/v3"


def _assign_via_v3(link_id: str, group_id: str, link_obj: Optional[dict] = None,
                    team_id: Optional[str] = None) -> Dict[str, Any]:
    """PATCH officiel v3 /links/{id} avec group_id. Pas de cookie, juste l'API key.

    team_id requis pour les groupes qui vivent dans un workspace team (sinon
    le validator rejette avec group_not_found). Format team_id : 24-hex SANS
    prefix tm_ (l'API privée veut sans prefix sur ce param).
    """
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "error": "API key GMS absente"}
    lid = (link_id or "").strip()
    if not lid.startswith("lnk_"):
        lid = "lnk_" + lid
    if not link_obj:
        try:
            r = requests.get(
                f"{PUBLIC_REST_BASE}/links/{lid}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            if r.status_code == 200:
                link_obj = r.json()
        except Exception:
            pass
    if not link_obj:
        return {"ok": False, "error": "impossible de fetch le link pour le PATCH v3"}
    link_type = link_obj.get("type") or "directlink"
    body = {
        "group_id": group_id,
        "display_name": link_obj.get("display_name") or lid,
        "typeLink": "directlink" if link_type == "directlink" else "landing",
    }
    # Pour les directlinks il faut envoyer url (requis par validator).
    # Pour les landing, on omet url pour ne pas écraser la config.
    if link_type == "directlink":
        body["url"] = link_obj.get("url") or ""
    if team_id:
        # Strip le prefix tm_ si présent (l'API v3 le veut sans)
        body["team_id"] = team_id[3:] if team_id.startswith("tm_") else team_id
    try:
        r = requests.patch(
            f"{PUBLIC_REST_BASE}/links/{lid}",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
    except Exception as e:
        return {"ok": False, "error": f"reseau v3: {e}"}
    if r.status_code == 200:
        return {"ok": True, "via": "v3"}
    return {"ok": False, "error": f"v3 HTTP {r.status_code}: {r.text[:200]}"}


def _assign_via_private(link_id: str, group_id: str,
                          after_link_id: Optional[str] = None) -> Dict[str, Any]:
    """Fallback via API privée dashboard (cookie session requis)."""
    cookie = get_session_cookie()
    if not cookie:
        return {"ok": False, "error": "session cookie GMS absent"}
    lid = (link_id or "").strip()
    if lid.startswith("lnk_"):
        lid = lid[4:]
    after = after_link_id
    if after and after.startswith("lnk_"):
        after = after[4:]
    headers = {
        "Cookie": cookie,
        "Content-Type": "application/json",
        "Origin": "https://getmysocial.com",
        "Referer": "https://getmysocial.com/dashboard",
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0 (compatible; vabot/1.0)",
    }
    body = {"groupId": group_id, "beforeLinkId": None, "afterLinkId": after}
    last_err = ""
    for attempt in range(4):
        try:
            r = requests.patch(f"{PRIVATE_API_BASE}/links/{lid}/group", headers=headers, json=body, timeout=20)
        except Exception as e:
            return {"ok": False, "error": f"reseau prive: {e}"}
        if r.status_code == 200:
            return {"ok": True, "via": "private"}
        if r.status_code in (401, 403):
            return {"ok": False, "error": "cookie session expire"}
        if r.status_code == 409:
            last_err = "Rank conflict"
            time.sleep(0.5 * (attempt + 1))
            continue
        return {"ok": False, "error": f"prive HTTP {r.status_code}: {r.text[:200]}"}
    return {"ok": False, "error": f"409 persistant: {last_err}"}


def assign_link_to_group(link_id: str, group_id: str,
                          after_link_id: Optional[str] = None,
                          link_obj: Optional[dict] = None,
                          team_id: Optional[str] = None) -> Dict[str, Any]:
    """Place un lien dans un groupe dashboard.

    Stratégie selon le type de lien :
    - LANDING : API privée uniquement (v3 PATCH wipe les buttons côté serveur
                même si on ne les envoie pas — bug connu de l'API v3).
    - DIRECTLINK : v3 PATCH d'abord, fallback API privée.

    team_id : workspace owner du groupe (requis pour groupes dans un team).
    """
    if not group_id or len(group_id) < 20:
        return {"ok": False, "error": f"group_id invalide : {group_id!r}"}
    # Détecte le type. Si on n'a pas link_obj, on fetch pour savoir.
    link_type = None
    if link_obj:
        link_type = link_obj.get("type")
    if not link_type:
        api_key = get_api_key()
        if api_key:
            try:
                lid_f = link_id if link_id.startswith("lnk_") else f"lnk_{link_id}"
                r = requests.get(f"{PUBLIC_REST_BASE}/links/{lid_f}",
                                 headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
                if r.status_code == 200:
                    link_obj = r.json()
                    link_type = link_obj.get("type")
            except Exception:
                pass
    link_type = link_type or "directlink"

    if link_type == "landing":
        # Landing : v3 PATCH wipe les buttons. On va direct sur l'API privée.
        fb = _assign_via_private(link_id, group_id, after_link_id=after_link_id)
        if fb.get("ok"):
            return fb
        return {"ok": False, "error": f"landing prive echoue : {fb.get('error')}"}

    # Directlink : v3 PATCH d'abord
    res = _assign_via_v3(link_id, group_id, link_obj=link_obj, team_id=team_id)
    if res.get("ok"):
        return res
    fb = _assign_via_private(link_id, group_id, after_link_id=after_link_id)
    if fb.get("ok"):
        return fb
    return {"ok": False, "error": f"v3 echoue ({res.get('error')}) + prive echoue ({fb.get('error')})"}


# ============ Helpers haut-niveau ============

def list_team_groups(team_id: str) -> Dict[str, Any]:
    """Liste les groupes d'un workspace team via l'API privée dashboard.

    Utilise le hack `?as=team&teamId=<24hex>` découvert empiriquement —
    `/api/links/board` n'expose normalement que les groupes du context user.
    """
    cookie = get_session_cookie()
    if not cookie:
        return {"ok": False, "error": "session cookie absent"}
    tid = team_id[3:] if team_id.startswith("tm_") else team_id
    try:
        r = requests.get(
            f"{PRIVATE_API_BASE}/links/board?as=team&teamId={tid}",
            headers={"Cookie": cookie}, timeout=15,
        )
    except Exception as e:
        return {"ok": False, "error": f"reseau: {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    try:
        d = r.json()
    except Exception:
        return {"ok": False, "error": "JSON invalide"}
    return {"ok": True, "groups": d.get("groups") or []}


def group_id_by_name(team_id: str, name: str) -> Optional[str]:
    """Retourne l'id du groupe nommé `name` (insensible a la casse) dans un
    workspace team, ou None. Tolere les champs id/_id/groupId."""
    nl = (name or "").strip().lower()
    if not nl:
        return None
    r = list_team_groups(team_id)
    if not r.get("ok"):
        return None
    for g in r.get("groups", []):
        gn = (g.get("name") or g.get("title") or "").strip().lower()
        if gn == nl:
            gid = g.get("id") or g.get("_id") or g.get("groupId") or ""
            return str(gid).strip() or None
    return None


def link_ids_in_group(team_id: str, group_id: str) -> Optional[List[str]]:
    """Liste des link_ids (format lnk_<hex>) places dans `group_id`, via les
    `placements` du board dashboard.

    IMPORTANT : distingue ECHEC de VIDE.
    - None  : impossible de recuperer le board (cookie absent, HTTP != 200,
              reseau/JSON KO) -> l'appelant NE DOIT PAS afficher « 0 clic ».
    - []    : board recupere mais le groupe ne contient aucun lien (vrai vide).
    """
    cookie = get_session_cookie()
    if not cookie or not group_id:
        return None
    tid = team_id[3:] if team_id.startswith("tm_") else team_id
    try:
        r = requests.get(
            f"{PRIVATE_API_BASE}/links/board?as=team&teamId={tid}",
            headers={"Cookie": cookie}, timeout=15,
        )
        if r.status_code != 200:
            return None
        d = r.json()
    except Exception:
        return None
    out: List[str] = []
    for p in d.get("placements") or []:
        if str(p.get("groupId")) == str(group_id):
            lid = p.get("linkId")
            if lid:
                out.append(lid if str(lid).startswith("lnk_") else "lnk_" + str(lid))
    return out


def next_va_number_in_group(team_id: Optional[str], folder_or_group: str) -> int:
    """Calcule le prochain numéro VA disponible dans un groupe.

    On scan tous les links du workspace, filtre par catégorie/groupe, et
    cherche le max VA n existant + 1.
    """
    import re as _re
    tid = team_id or ""
    try:
        if tid:
            tid_p = tid if tid.startswith("tm_") else f"tm_{tid}"
            res = list_links_team(tid_p)
        else:
            res = list_all_links()
    except Exception:
        return 1
    if not res.get("ok"):
        return 1
    target = (folder_or_group or "").lower()
    max_n = 0
    for l in res.get("links", []):
        model = categorize_link(l).lower()
        if model != target:
            continue
        name = l.get("display_name") or ""
        m = _re.match(r"^VA\s+(\d+)", name, _re.IGNORECASE)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n + 1


# ============ Compteur VA atomique (evite la race condition entre 2 Generate) ============

_VA_COUNTERS_FILE = DATA_DIR / "gms_va_counters.json"


def _load_counters() -> Dict[str, int]:
    if not _VA_COUNTERS_FILE.exists():
        return {}
    try:
        return json.loads(_VA_COUNTERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_counters(d: Dict[str, int]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _VA_COUNTERS_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def claim_next_va_number(team_id: Optional[str], folder: str) -> int:
    """Réserve atomiquement le prochain VA n pour (team, folder).

    Premier appel : initialise depuis le max API. Appels suivants : lit le
    counter et incremente. Evite la race condition entre plusieurs Generate
    rapprochés (sinon ils tomberaient tous sur VA 1).
    """
    counters = _load_counters()
    tid = (team_id or "").strip()
    if tid and not tid.startswith("tm_"):
        tid = "tm_" + tid
    key = f"{tid}:{(folder or '').lower()}"
    if key not in counters:
        counters[key] = next_va_number_in_group(team_id, folder)
    n = counters[key]
    counters[key] = n + 1
    _save_counters(counters)
    return n


def reset_va_counter(team_id: Optional[str], folder: str):
    """Force la prochaine claim à re-scanner via l'API (apres delete manuel)."""
    counters = _load_counters()
    tid = (team_id or "").strip()
    if tid and not tid.startswith("tm_"):
        tid = "tm_" + tid
    key = f"{tid}:{(folder or '').lower()}"
    counters.pop(key, None)
    _save_counters(counters)


def list_links_team(team_id: str) -> Dict[str, Any]:
    """List_all_links scopé à un team via API publique v3."""
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "error": "API key absente"}
    tid = team_id if team_id.startswith("tm_") else f"tm_{team_id}"
    all_links: List[dict] = []
    cursor: Optional[str] = None
    for _ in range(50):
        url = f"{PUBLIC_REST_BASE}/links?team_id={tid}&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        except Exception as e:
            return {"ok": False, "error": f"reseau: {e}"}
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        d = r.json()
        all_links.extend(d.get("data") or [])
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    return {"ok": True, "links": all_links}


# Team (workspace) "marche francais" — meme constante que la route web
MARCHE_FRANCAIS_TID = "tm_6a1ea410d882dd2173b8a315"
# Team (workspace) "Threads US" — pour l'identite hybride (marché US)
THREADS_US_TID = "tm_6a3853ddfd98d2441274d270"
# Workspaces connus à scanner pour retrouver le team d'un template.
KNOWN_TEAMS = (MARCHE_FRANCAIS_TID, THREADS_US_TID)
# Suffixe de shortcode par identité (défaut = nom de l'identité, pour categorize_link).
# Pour hybride (Threads US) on veut un lien "secret" plutôt que le nom visible.
_SHORTCODE_SUFFIX = {"hybride": "secret", "hybrid": "secret"}
# Workspace préféré par identité : évite qu'un groupe homonyme dans 2 workspaces
# (ex: "Hybride" en FR ET en Threads US) résolve sur le mauvais (marché FR gagne
# sinon car premier dans KNOWN_TEAMS). L'identité hybride vit dans Threads US.
IDENTITY_TEAM = {"hybride": THREADS_US_TID, "hybrid": THREADS_US_TID}
# Domaine public des liens GetMySocial
PUBLIC_LINK_DOMAIN = "https://getmysocial.com"


def quick_generate_for_identity(ident: str, va_handle: str = "") -> Dict[str, Any]:
    """Genere un nouveau lien GMS pour une identite, a partir de son template :
    - duplique le template de l'identite (toute la config conservee)
    - shortcode = 4 chars random + identite (retry si pris)
    - nom du lien = va_@<pseudo Discord du VA> si fourni, sinon 'VA N' (compteur)
    - assigne au groupe de l'identite dans le bon workspace

    Retourne {ok, shortcode, public_url, va_name, dest_url, group, error}.
    Logique partagee entre la route web /gms/quick_generate et la commande
    Discord (boss-only)."""
    ident = (ident or "").strip().lower()
    if not ident:
        return {"ok": False, "error": "Identité manquante"}
    templates = load_templates()
    tpl_id = templates.get(ident)
    if not tpl_id:
        return {"ok": False, "error": f"Aucun template GMS défini pour @{ident}. Configure-le d'abord sur le site (onglet SFS/GMS)."}

    # Detecte le workspace du template (marché FR ou Threads US…)
    team_id = None
    for _tid in KNOWN_TEAMS:
        try:
            r = list_links_team(_tid)
            if r.get("ok") and any(l.get("id") == tpl_id for l in r["links"]):
                team_id = _tid
                break
        except Exception:
            pass

    folder_name = ident.capitalize()
    # Nom du lien : pseudo Discord du VA (va_@handle) si fourni, sinon compteur "VA N"
    import re as _re
    handle = _re.sub(r"[^a-zA-Z0-9_.]", "", (va_handle or "").strip().lstrip("@"))[:32]
    if handle:
        new_name = f"va_@{handle}"
    else:
        try:
            n = claim_next_va_number(team_id, folder_name)
        except Exception:
            n = 1
        new_name = f"VA {n}"

    # Shortcode = 4 chars random + suffixe (identité, ou "secret" pour hybride).
    # Retry si pris.
    sc_suffix = _SHORTCODE_SUFFIX.get(ident, ident)
    last_err = ""
    dup_res: Dict[str, Any] = {}
    new_shortcode = ""
    for _ in range(5):
        new_shortcode = generate_random_prefix(4) + sc_suffix
        dup_res = duplicate_link(tpl_id, new_shortcode, new_name, team_id=team_id)
        if dup_res.get("ok"):
            break
        last_err = str(dup_res.get("error", ""))
        if "shortcode_taken" not in last_err.lower():
            break
    if not dup_res.get("ok"):
        return {"ok": False, "error": last_err or "Génération échouée"}

    grp = ""
    try:
        gid = get_group_id_for_folder(folder_name, team_id=team_id)
        # Auto-decouverte : si pas de mapping, cherche un groupe nommé comme
        # l'identité (ex: "Hybride") dans le workspace, et mémorise le mapping
        # pour les prochaines générations.
        if not gid and team_id:
            try:
                tg = list_team_groups(team_id)
                if tg.get("ok"):
                    fn_low = folder_name.lower()
                    for g in tg.get("groups", []):
                        gname = (g.get("name") or g.get("title") or "").strip().lower()
                        if gname == fn_low:
                            cand = g.get("id") or g.get("_id") or g.get("groupId") or ""
                            cand = str(cand).strip()
                            if cand:
                                gid = cand
                                set_group_for_folder(folder_name, gid, team_id=team_id)
                            break
            except Exception:
                pass
        if gid:
            ar = assign_link_to_group(
                dup_res["link"]["id"], gid,
                link_obj=dup_res["link"], team_id=team_id, after_link_id=tpl_id,
            )
            if ar.get("ok"):
                grp = folder_name
    except Exception:
        pass

    link = dup_res.get("link") or {}
    return {
        "ok": True,
        "shortcode": new_shortcode,
        "public_url": f"{PUBLIC_LINK_DOMAIN}/{new_shortcode}",
        "va_name": new_name,
        "dest_url": link.get("url") or "",
        "group": grp,
    }
