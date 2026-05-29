"""Scraper du dashboard MyPuls.app via cookies de session.

MyPuls n'expose pas d'API publique. On scrape directement le HTML de leur
dashboard authentifié `/creator/messaging-money-team` qui contient :
- Tableau des transactions (créateur | chatteur | fan | montant | type | date)
- Tableau des performances par chatteur (Présence | Réactivité | Proposé |
  Vendu | Taux conv. | CA PPV | CA Tips | CA Total)

Auth = cookies de session navigateur (PHPSESSID + REMEMBERME). Le user doit
les copier depuis sa session Chrome.

Filtres URL supportés :
- ?start=YYYY-MM-DD&end=YYYY-MM-DD (filtre période)

Stockage : data/mypuls_cookies.json (gitignored).
"""
from __future__ import annotations
import json
import re
from html import unescape
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import date, timedelta

import requests

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "mypuls_cookies.json"
BASE_URL = "https://mypuls.app"
TIMEOUT = 30


# ============ Config / cookies ============

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


def save_cookies(phpsessid: str, rememberme: str = ""):
    cfg = load_config()
    cfg["PHPSESSID"] = (phpsessid or "").strip()
    if rememberme:
        cfg["REMEMBERME"] = rememberme.strip()
    save_config(cfg)


def get_cookies() -> Dict[str, str]:
    cfg = load_config()
    out: Dict[str, str] = {}
    if cfg.get("PHPSESSID"):
        out["PHPSESSID"] = cfg["PHPSESSID"]
    if cfg.get("REMEMBERME"):
        out["REMEMBERME"] = cfg["REMEMBERME"]
    return out


def is_configured() -> bool:
    c = get_cookies()
    return bool(c.get("PHPSESSID")) or bool(c.get("REMEMBERME"))


# ============ Mapping identité VA -> nom modèle MyPuls ============

def get_model_for_identity(identity: str) -> str:
    return load_config().get("model_map", {}).get(identity.lower().strip(), "")


def set_model_for_identity(identity: str, model_name: str):
    cfg = load_config()
    mapping = cfg.get("model_map", {})
    ident = identity.lower().strip()
    clean = model_name.strip()
    if clean:
        mapping[ident] = clean
    else:
        mapping.pop(ident, None)
    cfg["model_map"] = mapping
    save_config(cfg)


def list_model_map() -> Dict[str, str]:
    return load_config().get("model_map", {})


# ============ HTTP session ============

def _make_session() -> Optional[requests.Session]:
    cookies = get_cookies()
    if not cookies:
        return None
    s = requests.Session()
    s.cookies.update(cookies)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })
    return s


def _detect_login_redirect(html: str) -> bool:
    """Détecte si on est redirigé vers la page login (cookie expiré)."""
    if "<title>Connexion" in html:
        return True
    if 'name="login"' in html or "Mot de passe oublié" in html:
        return True
    return False


# ============ Parsing ============

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_cell(html: str) -> str:
    txt = _HTML_TAG_RE.sub(" ", html)
    txt = unescape(txt)
    txt = _WS_RE.sub(" ", txt).strip()
    return txt


def _parse_amount(s: str) -> float:
    """Parse '18,32' ou '18,32 EUR' -> 18.32"""
    if not s:
        return 0.0
    s = s.replace("EUR", "").replace("€", "").strip()
    s = s.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _extract_tables(html: str) -> List[Tuple[List[str], List[List[str]]]]:
    """Retourne une liste de (headers, rows). Chaque row est une liste de cellules nettoyées."""
    out: List[Tuple[List[str], List[List[str]]]] = []
    for tbl in re.findall(r"<table[^>]*>.*?</table>", html, re.DOTALL):
        headers = [_clean_cell(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", tbl, re.DOTALL)]
        rows_html: List[str] = []
        tbody_m = re.search(r"<tbody[^>]*>(.*?)</tbody>", tbl, re.DOTALL)
        body = tbody_m.group(1) if tbody_m else tbl
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL):
            if "<th" in tr.lower():
                continue
            cells = [_clean_cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)]
            if cells:
                rows_html.append(cells)
        if headers or rows_html:
            out.append((headers, rows_html))
    return out


# ============ Fetch + parse ============

def fetch_team_stats(start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    """Récupère les stats de l'équipe (transactions + chatteurs) sur une période.

    Si pas de dates : 30 derniers jours.
    Retourne : {ok, transactions: [...], chatters: [...], totals: {...}, error}
    """
    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Cookies MyPuls non configurés"}

    # Période par défaut : 30 derniers jours
    today = date.today()
    if not end_date:
        end_date = today.isoformat()
    if not start_date:
        start_date = (today - timedelta(days=29)).isoformat()

    url = f"{BASE_URL}/creator/messaging-money-team?start={start_date}&end={end_date}"
    try:
        r = s.get(url, timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    if _detect_login_redirect(r.text):
        return {"ok": False, "error": "Cookies expirés — reconnecte-toi sur MyPuls et recopie tes cookies"}

    tables = _extract_tables(r.text)
    if len(tables) < 2:
        return {"ok": False, "error": f"Format de page inattendu (seulement {len(tables)} tableaux trouvés)"}

    # Table 0 = transactions log
    # Headers: Créateur | User (chatter) | Fan | Montant net | Devise | Type | Date | Contexte | Action
    transactions: List[Dict[str, Any]] = []
    for row in tables[0][1]:
        if len(row) < 7:
            continue
        transactions.append({
            "creator": row[0],
            "chatter": row[1],
            "fan": row[2],
            "amount": _parse_amount(row[3]),
            "currency": row[4] if len(row) > 4 else "EUR",
            "type": row[5] if len(row) > 5 else "",
            "date": row[6] if len(row) > 6 else "",
            "context": row[7] if len(row) > 7 else "",
        })

    # Table 1 = chatter performance
    # Headers: Chatter | Présence | Réactivité | Proposé | Vendu | Taux conv. | CA PPV | CA Tips | CA Total
    chatters: List[Dict[str, Any]] = []
    for row in tables[1][1]:
        if len(row) < 9:
            continue
        chatters.append({
            "name": row[0],
            "presence": row[1],
            "reactivity": row[2],
            "proposed": _parse_amount(row[3]) if row[3] else 0,
            "sold": _parse_amount(row[4]) if row[4] else 0,
            "conv_rate": row[5],
            "ca_ppv": _parse_amount(row[6]),
            "ca_tips": _parse_amount(row[7]),
            "ca_total": _parse_amount(row[8]),
        })
    # Tri par CA Total décroissant
    chatters.sort(key=lambda c: c["ca_total"], reverse=True)

    # Totaux
    totals = {
        "ca_total": round(sum(c["ca_total"] for c in chatters), 2),
        "ca_ppv": round(sum(c["ca_ppv"] for c in chatters), 2),
        "ca_tips": round(sum(c["ca_tips"] for c in chatters), 2),
        "nb_transactions": len(transactions),
        "nb_chatters": len(chatters),
        "active_chatters": sum(1 for c in chatters if c["ca_total"] > 0),
        "period_start": start_date,
        "period_end": end_date,
    }

    return {
        "ok": True,
        "transactions": transactions,
        "chatters": chatters,
        "totals": totals,
    }


def ping() -> Dict[str, Any]:
    """Vérifie que les cookies sont valides en chargeant /profil."""
    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Cookies non configurés"}
    try:
        r = s.get(f"{BASE_URL}/profil", timeout=TIMEOUT, allow_redirects=False)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code == 302:
        return {"ok": False, "error": "Cookies expirés — redirige vers login"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    if _detect_login_redirect(r.text):
        return {"ok": False, "error": "Cookies expirés"}
    # Extraire l'email pour confirmer l'identité
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", r.text)
    return {"ok": True, "email": email_match.group(0) if email_match else "?"}
