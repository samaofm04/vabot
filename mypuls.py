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
CHATTERS_FILE = DATA_DIR / "mypuls_chatters.json"
CRYPTO_DIR = DATA_DIR / "mypuls_crypto"
BASE_URL = "https://mypuls.app"
TIMEOUT = 30

# Cache en mémoire pour accélérer les chargements
_STATS_CACHE: Dict[str, Any] = {}
_STATS_CACHE_TTL = 300  # 5 minutes


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
    # Set cookies with the domain so they get sent + Set-Cookie peut les remplacer
    for name, value in cookies.items():
        s.cookies.set(name, value, domain="mypuls.app", path="/")
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })
    return s


def _save_rotated_cookies(session: requests.Session) -> bool:
    """Après une requête, vérifie si MyPuls a rotaté nos cookies (Set-Cookie)
    et persiste les nouvelles valeurs. Retourne True si changement.

    REMEMBERME est rotaté à chaque request réussie (~+1 jour de validité).
    PHPSESSID peut aussi changer si l'ancien expire.
    """
    cfg = load_config()
    changed = False
    for c in session.cookies:
        if c.domain not in ("mypuls.app", ".mypuls.app", ""):
            continue
        if c.name in ("PHPSESSID", "REMEMBERME"):
            old = cfg.get(c.name, "")
            if c.value and c.value != old:
                cfg[c.name] = c.value
                changed = True
    if changed:
        import time as _t
        cfg["last_refreshed"] = int(_t.time())
        save_config(cfg)
    return changed


def auto_refresh() -> Dict[str, Any]:
    """Ping silencieux de MyPuls pour rafraîchir le REMEMBERME.

    Appelé périodiquement (cron) pour maintenir la session en vie sans que
    l'user ait à se reconnecter manuellement.

    Astuce : on envoie SEULEMENT le REMEMBERME (pas le PHPSESSID). Comme
    ça MyPuls considère qu'il n'y a pas de session active et invoque le
    "remember me" guard de Symfony, qui crée une nouvelle session ET émet
    un nouveau REMEMBERME avec expiry prolongé. Si on envoyait les 2
    cookies ensemble, Symfony utilise juste la session existante sans
    toucher au REMEMBERME.

    Tant que ce cron tourne (toutes les 12h), le cookie ne meurt jamais
    — sauf si l'user change son mot de passe MyPuls.
    """
    cfg = load_config()
    rememberme = cfg.get("REMEMBERME", "")
    if not rememberme:
        return {"ok": False, "error": "REMEMBERME non configuré — refresh impossible"}
    s = requests.Session()
    s.cookies.set("REMEMBERME", rememberme, domain="mypuls.app", path="/")
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })
    try:
        r = s.get(f"{BASE_URL}/profil", timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200 or _detect_login_redirect(r.text):
        return {"ok": False, "error": "Cookies expirés ou révoqués"}
    rotated = _save_rotated_cookies(s)
    return {"ok": True, "rotated": rotated}


def last_refresh_age_hours() -> Optional[float]:
    """Heures depuis le dernier refresh. None si jamais."""
    ts = load_config().get("last_refreshed")
    if not ts:
        return None
    import time as _t
    return (_t.time() - ts) / 3600.0


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

def fetch_team_stats(start_date: str = "", end_date: str = "", use_cache: bool = True) -> Dict[str, Any]:
    """Récupère les stats de l'équipe (transactions + chatteurs) sur une période.

    Si pas de dates : 30 derniers jours.
    L'API publique est INCLUSIVE pour end_date (end=29/05 → inclut le 29/05
    en entier). MyPuls traite end comme exclusif, donc on ajoute +1 jour
    en interne pour l'appel HTTP.

    Avec use_cache=True (par défaut), un résultat récent (<5 min) est
    retourné depuis le cache mémoire pour accélérer drastiquement les
    chargements de page (était 2-3s, devient <50ms).

    Retourne : {ok, transactions, chatters, daily, totals, error}
    """
    import time as _t
    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Cookies MyPuls non configurés"}

    # Période par défaut : 30 derniers jours (inclusif)
    today = date.today()
    if not end_date:
        end_date = today.isoformat()
    if not start_date:
        start_date = (today - timedelta(days=29)).isoformat()

    # Vérifier le cache
    cache_key = f"{start_date}|{end_date}"
    if use_cache:
        cached = _STATS_CACHE.get(cache_key)
        if cached and (_t.time() - cached["ts"]) < _STATS_CACHE_TTL:
            return cached["data"]

    # Convertir end inclusif (UI) → end exclusif (MyPuls)
    try:
        end_dt = date.fromisoformat(end_date)
        end_exclusive = (end_dt + timedelta(days=1)).isoformat()
    except Exception:
        end_exclusive = end_date

    url = f"{BASE_URL}/creator/messaging-money-team?start={start_date}&end={end_exclusive}"
    try:
        r = s.get(url, timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    if _detect_login_redirect(r.text):
        return {"ok": False, "error": "Cookies expirés — reconnecte-toi sur MyPuls et recopie tes cookies"}
    # Sauvegarder les cookies rotatés (REMEMBERME prolongé)
    _save_rotated_cookies(s)

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

    # Aggrégation pour graphique : revenus par jour ET par créateur
    # Convertit la date "29/05/2026 05:36" -> "2026-05-29"
    def _to_iso(date_str: str) -> str:
        try:
            d, _, _ = date_str.partition(" ")  # "29/05/2026"
            parts = d.split("/")
            if len(parts) == 3:
                return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        except Exception:
            pass
        return ""

    # Liste de tous les jours dans la période
    try:
        start_dt = date.fromisoformat(start_date)
        end_dt_inc = date.fromisoformat(end_date)
        days_list: List[str] = []
        cur = start_dt
        while cur <= end_dt_inc:
            days_list.append(cur.isoformat())
            cur += timedelta(days=1)
    except Exception:
        days_list = []

    # Total par créateur (pour ranking) + par (jour, créateur)
    creator_totals: Dict[str, float] = {}
    by_day_creator: Dict[Tuple[str, str], float] = {}
    for tx in transactions:
        iso = _to_iso(tx["date"])
        creator = tx["creator"] or "?"
        amt = tx["amount"]
        creator_totals[creator] = creator_totals.get(creator, 0) + amt
        if iso:
            by_day_creator[(iso, creator)] = by_day_creator.get((iso, creator), 0) + amt

    # Top créateurs par CA (limite à 10 pour le graphique lisible)
    top_creators = sorted(creator_totals.items(), key=lambda x: x[1], reverse=True)[:10]
    top_creator_names = [c[0] for c in top_creators]

    # Datasets : un par créateur, valeurs par jour
    datasets = []
    for name in top_creator_names:
        data_points = [round(by_day_creator.get((d, name), 0), 2) for d in days_list]
        datasets.append({
            "label": name,
            "data": data_points,
            "total": round(creator_totals[name], 2),
        })

    result = {
        "ok": True,
        "transactions": transactions,
        "chatters": chatters,
        "totals": totals,
        "chart": {
            "days": days_list,
            "datasets": datasets,
            "all_creators_total": round(sum(creator_totals.values()), 2),
        },
    }
    # Mettre en cache pour accélérer les prochains chargements
    _STATS_CACHE[cache_key] = {"ts": int(_t.time()), "data": result}
    return result


def invalidate_cache():
    """Vide le cache (utile après update du mapping chatter, etc.)."""
    _STATS_CACHE.clear()


# ============ Métadonnées par chatteur (commission % + screenshot crypto) ============

# Commission par défaut (base) appliquée à un chatteur jamais configuré.
# Les chatteurs avec un % explicitement enregistré gardent leur valeur.
DEFAULT_COMMISSION_PCT = 14.0


def _load_chatters() -> dict:
    if not CHATTERS_FILE.exists():
        return {}
    try:
        return json.loads(CHATTERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_chatters(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHATTERS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_chatter_meta(name: str) -> dict:
    """Retourne {commission_pct, crypto_file, crypto_type, crypto_network, crypto_address, paid_periods}."""
    data = _load_chatters()
    key = (name or "").strip().lower()
    meta = data.get(key, {})
    return {
        "commission_pct": float(meta.get("commission_pct", DEFAULT_COMMISSION_PCT)),
        "crypto_file": meta.get("crypto_file"),
        "crypto_type": meta.get("crypto_type", ""),  # USDC | ETH | SOL | TRX
        "crypto_network": meta.get("crypto_network", ""),  # ERC20 | TRC20 | SPL | etc.
        "crypto_address": meta.get("crypto_address", ""),
        # Periodes ou ce chatteur a deja ete paye (liste de strings "YYYY-MM-DD_YYYY-MM-DD")
        "paid_periods": list(meta.get("paid_periods") or []),
    }


def is_chatter_paid(name: str, period_id: str) -> bool:
    """True si le chatteur a ete marque payé pour cette période (period_id = 'start_end')."""
    if not period_id:
        return False
    meta = get_chatter_meta(name)
    return period_id in meta.get("paid_periods", [])


def set_chatter_paid(name: str, period_id: str, paid: bool) -> bool:
    """Marque/demarque un chatteur paye pour une periode donnee.
    period_id format : 'YYYY-MM-DD_YYYY-MM-DD' (start_end)."""
    if not name or not period_id:
        return False
    data = _load_chatters()
    key = (name or "").strip().lower()
    if key not in data:
        data[key] = {}
    periods = list(data[key].get("paid_periods") or [])
    if paid:
        if period_id not in periods:
            periods.append(period_id)
    else:
        periods = [p for p in periods if p != period_id]
    data[key]["paid_periods"] = periods
    data[key]["original_name"] = name
    _save_chatters(data)
    return True


# Mapping réseau (asset) -> liste de blockchains supportées
CRYPTO_NETWORKS = {
    "USDC": ["Ethereum", "Tron", "Solana", "BSC", "Polygon", "Arbitrum", "Optimism", "Base"],
    "ETH": ["Ethereum", "Arbitrum", "Optimism", "Base", "BSC", "Polygon", "Solana"],
    "SOL": ["Solana", "Ethereum", "BSC"],
    "TRX": ["Tron"],
}
CRYPTO_TYPES = list(CRYPTO_NETWORKS.keys())


def set_crypto_address(name: str, crypto_type: str, network: str, address: str):
    """Met à jour les infos crypto (type, réseau, adresse) d'un chatteur."""
    data = _load_chatters()
    key = (name or "").strip().lower()
    if key not in data:
        data[key] = {}
    data[key]["crypto_type"] = (crypto_type or "").strip().upper()
    data[key]["crypto_network"] = (network or "").strip()
    data[key]["crypto_address"] = (address or "").strip()
    data[key]["original_name"] = name
    _save_chatters(data)


def set_commission_pct(name: str, pct: float):
    data = _load_chatters()
    key = (name or "").strip().lower()
    if key not in data:
        data[key] = {}
    # Clamp 0..100
    p = max(0.0, min(100.0, float(pct)))
    data[key]["commission_pct"] = p
    data[key]["original_name"] = name
    _save_chatters(data)


def set_crypto_file(name: str, filename: str):
    data = _load_chatters()
    key = (name or "").strip().lower()
    if key not in data:
        data[key] = {}
    data[key]["crypto_file"] = filename
    data[key]["original_name"] = name
    _save_chatters(data)


def crypto_path_for(name: str) -> Optional[Path]:
    """Retourne le path local du screenshot crypto, ou None."""
    meta = get_chatter_meta(name)
    fn = meta.get("crypto_file")
    if not fn:
        return None
    p = CRYPTO_DIR / fn
    return p if p.exists() else None


def save_crypto_screenshot(name: str, file_bytes: bytes, original_filename: str) -> str:
    """Sauvegarde un fichier crypto pour un chatteur. Retourne le nom de fichier final."""
    CRYPTO_DIR.mkdir(parents=True, exist_ok=True)
    # Slugify name + détecter extension
    import re as _re
    slug = _re.sub(r"[^a-z0-9_-]", "_", name.lower().strip())[:40]
    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()[:5]
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        ext = ".png"
    filename = f"{slug}{ext}"
    target = CRYPTO_DIR / filename
    target.write_bytes(file_bytes)
    set_crypto_file(name, filename)
    return filename


# ============ Taux de change EUR -> USD ============

def get_eur_usd_rate(force_refresh: bool = False) -> Dict[str, Any]:
    """Retourne le taux EUR -> USD avec cache 24h.

    Source : api.frankfurter.dev (taux officiels BCE, gratuit, sans clé).
    Retourne : {rate: float, date: str, cached_age_h: float, source: str}
    """
    cfg = load_config()
    import time as _t
    cache_rate = cfg.get("eur_usd_rate")
    cache_ts = cfg.get("eur_usd_ts", 0)
    cache_date = cfg.get("eur_usd_date", "?")
    age_h = (_t.time() - cache_ts) / 3600 if cache_ts else 999

    if not force_refresh and cache_rate and age_h < 24:
        return {
            "rate": float(cache_rate),
            "date": cache_date,
            "cached_age_h": age_h,
            "source": "cache",
        }

    # Refresh depuis API
    try:
        r = requests.get(
            "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD",
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            rate = float(data["rates"]["USD"])
            cfg["eur_usd_rate"] = rate
            cfg["eur_usd_ts"] = int(_t.time())
            cfg["eur_usd_date"] = data.get("date", "?")
            save_config(cfg)
            return {
                "rate": rate,
                "date": data.get("date", "?"),
                "cached_age_h": 0,
                "source": "api",
            }
    except Exception:
        pass

    # Fallback : utiliser le cache même si vieux
    if cache_rate:
        return {
            "rate": float(cache_rate),
            "date": cache_date,
            "cached_age_h": age_h,
            "source": "stale_cache",
        }
    # Pas de cache, pas d'API → fallback 1.1
    return {"rate": 1.10, "date": "?", "cached_age_h": 999, "source": "fallback"}


def delete_crypto_file(name: str) -> bool:
    p = crypto_path_for(name)
    if p:
        try:
            p.unlink()
        except Exception:
            pass
    data = _load_chatters()
    key = (name or "").strip().lower()
    if key in data and "crypto_file" in data[key]:
        del data[key]["crypto_file"]
        _save_chatters(data)
        return True
    return False


CREATOR_ORDER_FILE = DATA_DIR / "mypuls_creator_order.json"


def load_creator_order() -> List[int]:
    """Liste des creator IDs dans l ordre choisi par l user. [] si jamais reorder."""
    if not CREATOR_ORDER_FILE.exists():
        return []
    try:
        data = json.loads(CREATOR_ORDER_FILE.read_text(encoding="utf-8"))
        return [int(x) for x in data if isinstance(x, (int, str)) and str(x).isdigit()]
    except Exception:
        return []


def save_creator_order(creator_ids: List[int]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CREATOR_ORDER_FILE.write_text(
        json.dumps([int(x) for x in creator_ids], indent=2), encoding="utf-8"
    )


def list_creators(force_refresh: bool = False) -> Dict[str, Any]:
    """Liste les créateurs gérés avec leur ID MyPuls.

    Scrape /creators et extrait les paires (name -> id) en splittant le HTML
    par carte <div class="creator-card"...>. Pour chaque carte :
    - name = contenu du <h5 class="...fw-bold">NAME</h5>
    - id   = premier ID trouvé via /creator/<id>/, /switch-creator/<id>,
             ou data-creator-id="<id>" dans la même carte.

    Robuste pour les createurs sans image avatar (rendu en initiale dans un
    <div class="c-avatar">) - l ancienne version regex sur img alt= les ratait.

    Cache 1h dans data/mypuls_cookies.json.
    Retourne : {ok, creators: {name: id_int}, error}
    """
    cfg = load_config()
    import time as _t
    cache = cfg.get("creators_cache", {})
    cache_ts = cfg.get("creators_cache_ts", 0)
    # TTL court (5min) - les ajouts/changements de createurs sont rares mais
    # un cache trop long masque les fixes de parser (ex: Kiara qui n etait
    # pas detectee avant)
    if not force_refresh and cache and (_t.time() - cache_ts) < 300:
        return {"ok": True, "creators": cache}

    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Cookies non configurés"}
    try:
        r = s.get(f"{BASE_URL}/creators", timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200 or _detect_login_redirect(r.text):
        return {"ok": False, "error": "Cookies expirés"}

    creators: Dict[str, int] = {}
    chunks = re.split(r'<div\s+class="creator-card', r.text)
    for chunk in chunks[1:]:  # skip preamble avant la 1ere card
        nm = re.search(r'<h5\s+class="[^"]*fw-bold[^"]*">([^<]+)</h5>', chunk)
        if not nm:
            continue
        name = nm.group(1).strip()
        if not name:
            continue
        # Trouve l ID via plusieurs patterns possibles dans la card
        cid = None
        for pat in (
            r'/creator/(\d+)/',
            r'/switch-creator/(\d+)',
            r'data-creator-id="(\d+)"',
        ):
            ids = re.findall(pat, chunk)
            if ids:
                cid = int(ids[0])
                break
        if cid:
            creators[name] = cid

    # Sauvegarder en cache
    cfg["creators_cache"] = creators
    cfg["creators_cache_ts"] = int(_t.time())
    save_config(cfg)
    return {"ok": True, "creators": creators}


def list_pushs(creator_id: int, max_pages: int = 1) -> Dict[str, Any]:
    """Liste les push (messages de masse) d'un creator.

    Flux observe : GET /switch-creator/{id}?from=app_pushs (selectionne le creator),
    puis GET /pushs/page/N -> JSON {items:[...], hasMore, page}.
    Chaque item : {id, description, sentAt 'JJ/MM/AAAA HH:MM', types[], price,
    promoPrice, sales, ca, hasMod, medias:[{thumbUrl,...}]}.

    Retourne {ok, pushs:[{id, description, sentAt, types, price, thumb}]}.
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configures"}
    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Session MyPuls indisponible"}
    try:
        s.get(f"{BASE_URL}/switch-creator/{int(creator_id)}?from=app_pushs",
              timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        return {"ok": False, "error": f"switch-creator: {e}"}
    pushs: List[Dict[str, Any]] = []
    page = 1
    while page <= max(1, max_pages):
        try:
            r = s.get(f"{BASE_URL}/pushs/page/{page}", timeout=TIMEOUT)
        except Exception as e:
            return {"ok": False, "error": f"pushs page {page}: {e}"}
        if r.status_code != 200:
            break
        try:
            j = r.json()
        except Exception:
            break
        items = j.get("items", []) or []
        for it in items:
            if not isinstance(it, dict):
                continue
            medias = it.get("medias") or []
            thumb = ""
            if medias and isinstance(medias[0], dict):
                thumb = medias[0].get("thumbUrl") or ""
            pushs.append({
                "id": it.get("id"),
                "description": it.get("description") or "",
                "sentAt": it.get("sentAt") or "",
                "types": it.get("types") or [],
                "price": it.get("price") or 0,
                "thumb": thumb,
            })
        if not j.get("hasMore"):
            break
        page += 1
    try:
        _save_rotated_cookies(s)
    except Exception:
        pass
    return {"ok": True, "pushs": pushs}


def get_avatar_bytes(creator_id: int) -> Dict[str, Any]:
    """Proxy : récupère l'image avatar d'un créateur MyPuls.

    Retourne {ok, content: bytes, content_type: str, error}.
    """
    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Cookies non configurés"}
    try:
        r = s.get(f"{BASE_URL}/creator/{int(creator_id)}/avatar", timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    return {
        "ok": True,
        "content": r.content,
        "content_type": r.headers.get("Content-Type", "image/jpeg"),
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
    # Sauvegarder les cookies rotatés
    _save_rotated_cookies(s)
    # Extraire l'email pour confirmer l'identité
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", r.text)
    return {"ok": True, "email": email_match.group(0) if email_match else "?"}
