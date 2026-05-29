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
        try:
            payload = json.loads(content[0]["text"])
        except Exception:
            payload = content[0]["text"]
        # Détecter les erreurs renvoyées par l'outil GMS
        if isinstance(payload, dict) and payload.get("error"):
            return {"ok": False, "error": str(payload.get("error"))[:500]}
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
        page = (data.get("data") if isinstance(data, dict) else []) or []
        all_links.extend(page)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return {"ok": True, "links": all_links}


def categorize_link(link: dict) -> str:
    """Détecte la catégorie (= modèle) d'un lien à partir du display_name et de l'URL.

    Stratégie :
    1. Nettoyer le display_name (retirer "(Copy)", "VA " préfixe, espaces)
    2. Si ça matche un nom de modèle connu, c'est gagné
    3. Sinon on prend le premier mot du nom nettoyé
    4. Fallback : extraire le username du path OnlyFans/MYM (ex. ameliawdifference → Amelia)
    """
    import re as _re
    name = (link.get("display_name") or "").strip()
    url = link.get("url") or ""

    # Nettoyer le name : enlever (Copy) répétés, VA en préfixe, normaliser
    clean = _re.sub(r"\s*\(Copy\)\s*", " ", name, flags=_re.IGNORECASE).strip()
    # Si commence par "VA " et qu'il y a quelque chose après, garder ce qui suit
    m = _re.match(r"^VA\s+(.+)$", clean, _re.IGNORECASE)
    if m:
        rest = m.group(1).strip()
        # Si c'est juste un nombre (ex. "VA 10"), c'est la catégorie "Jessy" (cas spécifique de ton compte)
        # On le laisse tel quel sinon
        if rest.isdigit() or _re.match(r"^\d+$", rest):
            # Regarder l'URL pour déduire le modèle
            if "jessyewdiference" in url.lower():
                return "Jessy"
            return f"VA {rest}"
        clean = rest

    # Modèles connus en priorité (substring case-insensitive)
    KNOWN = ["Amelia", "Lola", "Julia", "Sarah", "Emma", "Khloe", "Jessy",
             "Boo7", "Mirabelle", "Enzo", "Dem boss"]
    lower = clean.lower()
    for k in KNOWN:
        if k.lower() in lower:
            return k

    # Sinon : fallback URL (extraire username du path)
    if url:
        m2 = _re.search(r"onlyfans\.com/([a-z0-9_]+)", url, _re.IGNORECASE)
        if m2:
            user = m2.group(1).lower()
            for k in KNOWN:
                if k.lower() in user:
                    return k

    # Sinon : premier mot du clean
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


def delete_link(link_id: str) -> Dict[str, Any]:
    res = _call_tool("delete_link", {"link_id": link_id})
    return res


def enable_link(link_id: str) -> Dict[str, Any]:
    return _call_tool("enable_link", {"link_id": link_id})


def disable_link(link_id: str) -> Dict[str, Any]:
    return _call_tool("disable_link", {"link_id": link_id})
