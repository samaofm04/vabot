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
import os
import re
import threading as _th
from html import unescape
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import date, timedelta

import requests
import safe_json

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
    # Écriture ATOMIQUE (temp + replace) : un crash en plein write ne tronque plus
    # le fichier (sinon PHPSESSID + REMEMBERME perdus -> ré-auth manuelle).
    import os as _os
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".tmp")
    safe_json.write_text(tmp, json.dumps(cfg, indent=2, ensure_ascii=False))
    _os.replace(str(tmp), str(CONFIG_FILE))


# ---------------------------------------------------------------------------
# API OFFICIELLE MyPuls (X-API-TOKEN). Bien plus fiable que le scraping HTML et
# surtout COMPLÈTE : le tableau des ventes scrapé ne contient pas les revenus
# "Publications" (posts), l'API si.
# ---------------------------------------------------------------------------
def save_api_token(token: str) -> bool:
    cfg = load_config()
    cfg["api_token"] = (token or "").strip()
    cfg["api_token_ok"] = False   # revalidé juste après par l'appelant
    save_config(cfg)
    return bool(cfg["api_token"])


def set_api_token_ok(ok: bool) -> None:
    """Mémorise si le token a été accepté par MyPuls (pour l'affichage)."""
    cfg = load_config()
    cfg["api_token_ok"] = bool(ok)
    save_config(cfg)


def api_token() -> str:
    return (load_config().get("api_token") or "").strip()


def api_configured() -> bool:
    return bool(api_token())


def api_get(path: str, params: dict = None) -> dict:
    """GET sur l'API MyPuls. Retourne {ok, data} ou {ok: False, error}."""
    tok = api_token()
    if not tok:
        return {"ok": False, "error": "Aucun token API MyPuls (Settings → MyPuls)"}
    import requests
    url = f"{BASE_URL}/api/v1/{path.lstrip('/')}"
    try:
        r = requests.get(url, headers={"X-API-TOKEN": tok, "Accept": "application/json"},
                         params=params or {}, timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Connexion API impossible : {e}"}
    if r.status_code in (401, 403):
        return {"ok": False, "error": f"Token API refusé (HTTP {r.status_code})"}
    if r.status_code == 404:
        return {"ok": False, "error": f"Endpoint introuvable : {url}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code} : {r.text[:200]}"}
    try:
        return {"ok": True, "data": r.json()}
    except Exception:
        return {"ok": False, "error": f"Réponse non-JSON : {r.text[:150]}"}


def api_session() -> dict:
    """Vérifie le token (GET /session)."""
    return api_get("session")


def api_creators() -> dict:
    """Liste des creators du périmètre (GET /creators)."""
    return api_get("creators")


def api_creators_parsed() -> list:
    """Créateurs normalisés : [{id, pseudo, platform, currency, active}].
    L'API donne EXPLICITEMENT la plateforme (mym/onlyfans) et la devise ->
    plus besoin de deviner à partir du nom ou de la devise."""
    res = api_creators()
    if not res.get("ok"):
        return []
    d = res.get("data")
    items = d if isinstance(d, list) else None
    if items is None and isinstance(d, dict):
        inner = d.get("data")
        items = inner.get("data") if isinstance(inner, dict) else inner
    out = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        out.append({
            "id": it.get("id"),
            "pseudo": (it.get("pseudo") or it.get("name") or "").strip(),
            "platform": (it.get("platform") or "").strip().lower(),
            "currency": (it.get("currency") or "").strip().upper(),
            "active": bool(it.get("active", True)),
        })
    return out


_API_CREATORS_CACHE: Dict[str, Any] = {}     # {"t": ts, "v": [...]}
_API_CREATORS_TTL = 300                      # 5 min, comme _API_OVERVIEW_TTL


def api_creators_cached(force: bool = False) -> list:
    """api_creators_parsed() avec cache 5 min PARTAGÉ dashboard + facture.
    La page Facture appelait /creators une fois PAR LIGNE (N+1) : ici, 1 fois."""
    import time as _t
    hit = _API_CREATORS_CACHE.get("v")
    if hit and not force and (_t.time() - _API_CREATORS_CACHE.get("t", 0)) < _API_CREATORS_TTL:
        return hit
    out = api_creators_parsed()
    if out:                      # on ne met JAMAIS une liste vide en cache
        _API_CREATORS_CACHE["v"] = out
        _API_CREATORS_CACHE["t"] = _t.time()
        return out
    return hit or []             # API en vrac -> on ressert le dernier bon état


_API_STATS_CACHE: Dict[str, Any] = {}
_API_STATS_TTL = 300


# ---- Dernier BON relevé par (créatrice, période), persisté sur disque ----
# L'API MyPuls a des ratés réguliers -> sans ça, chaque créatrice en erreur
# tombait à 0 $ et le dashboard affichait « Total PARTIEL » en boucle.
_LASTGOOD_FILE = DATA_DIR / "mypuls_stats_lastgood.json"
_LASTGOOD_LOCK = _th.Lock()
_LASTGOOD_MEM: Dict[str, Any] = {}
_LASTGOOD_LOADED = [False]


def _lastgood_load():
    if _LASTGOOD_LOADED[0]:
        return
    _LASTGOOD_LOADED[0] = True
    try:
        if _LASTGOOD_FILE.exists():
            d = json.loads(_LASTGOOD_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                _LASTGOOD_MEM.update(d)
    except Exception:
        pass


def _lastgood_save():
    import time as _t
    try:
        # purge : les périodes de plus de 45 jours ne seront plus re-demandées
        cut = _t.time() - 45 * 86400
        for k in [k for k, v in _LASTGOOD_MEM.items() if (v or {}).get("ts", 0) < cut]:
            _LASTGOOD_MEM.pop(k, None)
        tmp = _LASTGOOD_FILE.with_suffix(".json.tmp")
        safe_json.write_text(tmp, json.dumps(_LASTGOOD_MEM, ensure_ascii=False))
        os.replace(str(tmp), str(_LASTGOOD_FILE))
    except Exception:
        pass


def api_creator_stats_cached(creator_id, date_from: str, date_to: str) -> dict:
    """api_creator_stats() avec cache 5 min par (créatrice, période).
    Les ÉCHECS ne sont pas mis en cache (un 429 passager se rattrape seul) MAIS
    on ressert alors le DERNIER BON relevé (persisté) marqué stale=True :
    mieux vaut un chiffre d'il y a 10 min qu'un faux 0."""
    import time as _t
    key = f"{creator_id}|{date_from}|{date_to}"
    hit = _API_STATS_CACHE.get(key)
    if hit and (_t.time() - hit[0]) < _API_STATS_TTL:
        return hit[1]
    r = api_creator_stats(creator_id, date_from, date_to)
    if r.get("ok"):
        _API_STATS_CACHE[key] = (_t.time(), r)
        if len(_API_STATS_CACHE) > 200:
            _API_STATS_CACHE.clear()
        try:
            rev = ((r.get("data") or {}).get("revenue") or {})
            with _LASTGOOD_LOCK:
                _lastgood_load()
                _LASTGOOD_MEM[key] = {"ts": _t.time(), "revenue": rev}
                _lastgood_save()
        except Exception:
            pass
        return r
    # Échec -> dernier bon relevé si on en a un
    with _LASTGOOD_LOCK:
        _lastgood_load()
        lg = _LASTGOOD_MEM.get(key)
    if lg and isinstance(lg.get("revenue"), dict):
        return {"ok": True, "stale": True, "stale_ts": lg.get("ts"),
                "data": {"revenue": lg["revenue"]}}
    return r


def api_creator_stats(creator_id, date_from: str = "", date_to: str = "") -> dict:
    """Statistiques d'un creator sur une période (GET /creators/{id}/stats)."""
    p = {}
    if date_from:
        p["from"] = date_from
    if date_to:
        p["to"] = date_to
    return api_get(f"creators/{creator_id}/stats", p)


_API_DAY_CACHE: Dict[str, Any] = {}
_API_DAY_TTL = 300  # 5 min, comme les autres caches API


def api_revenue_by_day(creator_id, date_from: str = "", date_to: str = "") -> dict:
    """Revenus journaliers d'un creator (GET /creators/{id}/revenue-by-day).

    Cache 5 min PAR CREATRICE, succes uniquement — meme regle que
    api_creator_stats_cached. Sans lui, api_revenue_series ne pouvait etre
    econome qu'en mettant en cache la SERIE AGREGEE : une seule creatrice en
    429 et la courbe amputee etait servie 5 minutes comme si elle etait
    complete. Avec ce cache, refuser une serie incomplete ne coute qu'un
    rappel des creatrices qui ont echoue, pas de toutes.
    """
    import time as _t
    key = f"{creator_id}|{date_from}|{date_to}"
    hit = _API_DAY_CACHE.get(key)
    if hit and (_t.time() - hit[0]) < _API_DAY_TTL:
        return hit[1]
    p = {}
    if date_from:
        p["from"] = date_from
    if date_to:
        p["to"] = date_to
    r = api_get(f"creators/{creator_id}/revenue-by-day", p)
    if r.get("ok"):
        _API_DAY_CACHE[key] = (_t.time(), r)
        if len(_API_DAY_CACHE) > 200:
            _API_DAY_CACHE.clear()
    return r


_API_OVERVIEW_CACHE: Dict[str, Any] = {}
_API_OVERVIEW_TTL = 300  # 5 min

# OnlyFans marché US (ids MyPuls). Le reste des comptes OnlyFans = marché FR.
OF_US_CREATOR_IDS = {3107, 3108}   # Jessye, Khloe


def api_overview(date_from: str, date_to: str, eur_usd: float = 1.14,
                 force: bool = False, exclude=None) -> dict:
    """Revenus agrégés via l'API officielle, sur une période.

    IMPORTANT : l'API renvoie déjà du NET (frais plateforme déduits) — on
    n'applique donc AUCUNE déduction supplémentaire. Les montants EUR (MyM) sont
    convertis en USD. Retourne {ok, total_usd, segments, types, creators}.
    """
    import time as _t
    # modèles écartées (ex bella) : mêmes règles de match que le chemin scraping
    _excl = {re.sub(r"[^a-z0-9]", "", str(x).lower()) for x in (exclude or set())}
    key = f"{date_from}|{date_to}|{eur_usd}|{','.join(sorted(_excl))}"
    hit = _API_OVERVIEW_CACHE.get(key)
    if hit and not force and (_t.time() - hit[0]) < _API_OVERVIEW_TTL:
        return hit[1]
    if not api_configured():
        return {"ok": False, "error": "Token API MyPuls absent"}
    creators = api_creators_cached(force=force)
    if not creators:
        return {"ok": False, "error": "Aucun creator renvoyé par l'API"}

    seg = {"mym": 0.0, "of_fr": 0.0, "of_us": 0.0}
    types = {"Subscriptions": 0.0, "Posts": 0.0, "Messages": 0.0,
             "Tips": 0.0, "Referrals": 0.0, "Streams": 0.0}
    # split par famille de plateforme : permet au dashboard de calculer un BRUT
    # par type (les commissions different : OnlyFans 20 %, MyM 26 %)
    types_of = dict(types)
    types_mym = dict(types)
    per_creator, errors, stale = [], [], []
    # Ce qu'aucune carte ne reconnait : compte a part, jamais perdu.
    hors_type = {"montant": 0.0, "libelles": []}

    def _hors_libelle(k):
        """Note un libelle mis a l'ecart : sans doublon, et plafonne pour ne
        pas transformer la reponse en liste a rallonge."""
        t = str(k)
        if t not in hors_type["libelles"] and len(hors_type["libelles"]) < 12:
            hors_type["libelles"].append(t)
    _MAP = {  # libellés API -> cartes du dashboard
        "message": "Messages", "post": "Posts", "tip": "Tips",
        "subscription": "Subscriptions", "sub": "Subscriptions",
        "stream": "Streams", "referral": "Referrals",
    }
    def _retenue(c) -> bool:
        """Créatrice à compter. Un seul point de décision : le préchargement et
        la boucle doivent porter EXACTEMENT sur le même ensemble."""
        if not c.get("active"):
            return False
        _ps = re.sub(r"[^a-z0-9]", "", str(c.get("pseudo") or "").lower())
        # modèle écartée (le scraping l'excluait, l'API doit aussi)
        return not (_excl and any(_ps == e or _ps.startswith(e) for e in _excl))

    # Préchargement en parallèle. Chaque relevé coûtait un aller-retour HTTP de
    # 30 s au pire, ET ILS PARTAIENT L'UN APRÈS L'AUTRE : avec une vingtaine de
    # créatrices la page Revenus tenait un worker pendant des minutes, si bien
    # que /home/overview finissait en 503 — le serveur n'avait plus un seul
    # worker libre pour ses propres pages.
    # On ne remplit ici que le CACHE. La boucle qui suit reste séquentielle et
    # inchangée : c'est elle qui additionne de l'argent, on n'y touche pas. Si
    # le préchargement échoue, elle se comporte exactement comme avant.
    try:
        from concurrent.futures import ThreadPoolExecutor as _Pool
        _a_charger = [c for c in creators if _retenue(c)]
        if len(_a_charger) > 1:
            with _Pool(max_workers=6) as _ex:
                list(_ex.map(
                    lambda _c: api_creator_stats_cached(_c["id"], date_from, date_to),
                    _a_charger))
    except Exception:
        pass          # préchargement best-effort : la boucle sait se débrouiller

    for c in creators:
        if not _retenue(c):
            continue
        r = api_creator_stats_cached(c["id"], date_from, date_to)
        if not r.get("ok"):
            errors.append(f"{c.get('pseudo') or c.get('id')}: {str(r.get('error'))[:60]}")
            continue
        if r.get("stale"):
            stale.append(str(c.get("pseudo") or c.get("id")))
        rev = ((r.get("data") or {}).get("revenue") or {})
        cur = (rev.get("currency") or c.get("currency") or "USD").upper()
        rate = eur_usd if cur == "EUR" else 1.0
        total_usd = float(rev.get("total") or 0) * rate
        if c.get("platform") == "onlyfans":
            seg["of_us" if c.get("id") in OF_US_CREATOR_IDS else "of_fr"] += total_usd
        else:
            seg["mym"] += total_usd
        for k, v in (rev.get("by_type") or {}).items():
            bucket = _MAP.get(str(k).strip().lower())
            try:
                _amt = float(v or 0) * rate
            except (TypeError, ValueError):
                # Convertir AVANT de trancher faisait dependre tout l'agregat
                # d'un champ qu'on a justement decide de ne pas comprendre :
                # by_type={'message': 100, 'breakdown': {...}} levait une
                # TypeError, et api_overview partait en erreur EN ENTIER.
                # Son seul appelant (page Revenus) avale l'exception dans un
                # except large : la page retombait SANS RIEN DIRE sur les
                # chiffres du scraping, qui ne contiennent pas les revenus
                # « post » — total sous-evalue, seule trace un log.warning.
                # Une case illisible est donc mise de cote avec son libelle
                # (son montant, lui, reste inconnu : il ne peut pas entrer
                # dans "montant"), et le reste de la creatrice est compte.
                _hors_libelle("%s (montant illisible)" % k)
                continue
            if not bucket:
                # Un libelle que _MAP ne connait pas etait jete : le montant
                # restait dans total_usd mais dans AUCUNE carte, si bien que
                # la somme des cartes ne recoupait plus le total et que
                # personne ne pouvait dire d'ou venait l'ecart. C'est
                # exactement ainsi que « Media prive » avait disparu du cote
                # scraping. On le garde, avec son libelle en clair.
                hors_type["montant"] += _amt
                _hors_libelle(k)
                continue
            types[bucket] += _amt
            (types_of if c.get("platform") == "onlyfans" else types_mym)[bucket] += _amt
        if total_usd:
            per_creator.append({"pseudo": c.get("pseudo"), "usd": round(total_usd, 2),
                                "platform": c.get("platform")})
    per_creator.sort(key=lambda x: -x["usd"])
    out = {"ok": True, "total_usd": round(sum(seg.values()), 2),
           "segments": {k: round(v, 2) for k, v in seg.items()},
           "types": {k: round(v, 2) for k, v in types.items()},
           "types_of": {k: round(v, 2) for k, v in types_of.items()},
           "types_mym": {k: round(v, 2) for k, v in types_mym.items()},
           # Tant que "montant" vaut 0, la somme des cartes recoupe total_usd.
           "types_hors": {"montant": round(hors_type["montant"], 2),
                          "libelles": hors_type["libelles"]},
           "creators": per_creator, "errors": errors, "stale": stale}
    # un agrégat AMPUTÉ (créatrice en 429/timeout) n'est jamais mis en cache :
    # sinon un total partiel s'affichait comme complet pendant 5 minutes.
    # Pareil pour un agrégat contenant du STALE : on veut retenter vite les
    # créatrices en erreur (leurs derniers relevés comblent en attendant).
    if not errors and not stale:
        _API_OVERVIEW_CACHE[key] = (_t.time(), out)
        if len(_API_OVERVIEW_CACHE) > 40:
            _API_OVERVIEW_CACHE.clear()
    return out


_API_SERIES_CACHE: Dict[str, Any] = {}
_API_SERIES_TTL = 300


def api_revenue_series(date_from: str, date_to: str, eur_usd: float = 1.14) -> dict:
    """Série journalière AGRÉGÉE toutes créatrices actives, en USD (API officielle).

    Somme les /creators/{id}/revenue-by-day de chaque créatrice active, converti
    par devise (EUR MyM -> USD au taux fourni). Contrairement au scraping, la
    série couvre TOUTES les créatrices (le chart scrapé tronquait au top 10) et
    convertit au lieu d'additionner EUR et USD bruts. Cache 5 min.
    Retourne {ok, days:[...], usd:[...], errors:[...]}.
    """
    import time as _t
    key = f"{date_from}|{date_to}|{eur_usd}"
    hit = _API_SERIES_CACHE.get(key)
    if hit and (_t.time() - hit[0]) < _API_SERIES_TTL:
        return hit[1]
    if not api_configured():
        return {"ok": False, "error": "Token API MyPuls absent"}
    creators = api_creators_cached()
    if not creators:
        return {"ok": False, "error": "Aucun creator renvoyé par l'API"}
    sums: Dict[str, float] = {}
    sums_of: Dict[str, float] = {}    # split par plateforme : permet au
    sums_mym: Dict[str, float] = {}   # dashboard de calculer un BRUT par jour
    order: List[str] = []          # ordre des jours du 1er retour OK (même
    errors = []                    # période partout -> mêmes labels)
    for c in creators:
        if not c.get("active"):
            continue
        r = api_revenue_by_day(c["id"], date_from, date_to)
        if not r.get("ok"):
            errors.append(f"{c.get('pseudo') or c.get('id')}: {str(r.get('error'))[:60]}")
            continue
        dd = (r.get("data") or {})
        labels = [str(x) for x in (dd.get("labels") or [])]
        vals = dd.get("revenue_by_day") or []
        cur = (dd.get("currency") or c.get("currency") or "USD").upper()
        rate = eur_usd if cur == "EUR" else 1.0
        bucket = sums_of if c.get("platform") == "onlyfans" else sums_mym
        if not order:
            order = labels
        for d_i, v in zip(labels, vals):
            try:
                amt = float(v or 0) * rate
                sums[d_i] = sums.get(d_i, 0.0) + amt
                bucket[d_i] = bucket.get(d_i, 0.0) + amt
            except Exception:
                pass
    days = [d for d in order if d in sums] + sorted(k for k in sums if k not in order)
    if not days and hit:
        # API en vrac (429, timeout) -> on ressert la dernière bonne série
        # plutôt que de faire retomber la courbe sur le scraping
        return hit[1]
    out = {"ok": bool(days), "days": days,
           "usd": [round(sums[d], 2) for d in days],
           "usd_of": [round(sums_of.get(d, 0.0), 2) for d in days],
           "usd_mym": [round(sums_mym.get(d, 0.0), 2) for d in days],
           "errors": errors}
    if not days:
        out["error"] = "; ".join(errors) or "Aucune donnée"
    # Jamais d'échec en cache — et jamais de série AMPUTÉE non plus : une
    # créatrice en 429/timeout laissait `days` non vide, donc ok=True, donc la
    # courbe partielle était servie 5 minutes comme si elle était complète.
    # api_overview refuse déjà ce cas pour la même raison (« un total partiel
    # s'affichait comme complet ») ; c'était un oubli, pas un compromis.
    # Sans cache, l'appel suivant retente les créatrices manquantes.
    if out["ok"] and not errors:
        _API_SERIES_CACHE[key] = (_t.time(), out)
        if len(_API_SERIES_CACHE) > 40:
            _API_SERIES_CACHE.clear()
    return out


SFS_INBOX_FILE = DATA_DIR / "sfs_inbox.json"
_SFS_INBOX_CACHE: Dict[str, Any] = {}
_SFS_INBOX_TTL = 120


def api_sfs_inbox(force: bool = False) -> dict:
    """Messages ENTRANTS des fans (propositions SFS potentielles), via l'API.

    Source : GET /creators/{id}/conversations/unread pour chaque créatrice
    active (1 appel chacune — MyM ET OnlyFans, l'API couvre les deux). L'API ne
    liste QUE les non-lues : chaque passage FUSIONNE dans data/sfs_inbox.json
    (jamais d'écrasement) pour qu'un message déjà lu par un chatteur ne
    disparaisse pas de l'historique. Cache mémoire 2 min.
    Retourne {ok, items:[{key, creator, platform, fan_id, fan_name, content,
    at, seen_at}]} trié du plus récent au plus ancien.
    """
    import time as _t
    hit = _SFS_INBOX_CACHE.get("v")
    if hit and not force and (_t.time() - _SFS_INBOX_CACHE.get("t", 0)) < _SFS_INBOX_TTL:
        return hit
    if not api_configured():
        return {"ok": False, "error": "Token API MyPuls absent"}
    try:
        store = json.loads(SFS_INBOX_FILE.read_text(encoding="utf-8"))
        if not isinstance(store, dict):
            store = {}
    except Exception:
        store = {}
    items: Dict[str, Any] = store.get("items") or {}
    errors = []
    nouveaux = 0
    for c in api_creators_cached():
        if not c.get("active"):
            continue
        r = api_get(f"creators/{c['id']}/conversations/unread")
        if not r.get("ok"):
            errors.append(f"{c.get('pseudo') or c['id']}: {str(r.get('error'))[:60]}")
            continue
        data = ((r.get("data") or {}).get("data")) or []
        for conv in data:
            if not isinstance(conv, dict):
                continue
            lm = conv.get("last_message") or {}
            if (lm.get("from") or "") != "fan":
                continue                      # on ne garde que l'ENTRANT
            key = f"{c['id']}|{conv.get('chat_ref') or conv.get('fan_id')}|{lm.get('at') or ''}"
            if key in items:
                continue
            items[key] = {
                "key": key,
                "creator": (c.get("pseudo") or "").strip() or f"#{c['id']}",
                "creator_id": c.get("id"),
                "platform": c.get("platform") or "",
                "fan_id": conv.get("fan_id"),
                "fan_name": (conv.get("fan_name") or "").strip(),
                "content": str(lm.get("content") or "")[:600],
                "at": lm.get("at") or "",
                "unread_count": conv.get("unread_count") or 0,
                "seen_at": int(_t.time()),
            }
            nouveaux += 1
    if nouveaux:
        try:
            # borne : garder les 3000 plus récents (par date de découverte)
            if len(items) > 3000:
                keep = sorted(items.values(), key=lambda x: x.get("seen_at", 0),
                              reverse=True)[:3000]
                items = {x["key"]: x for x in keep}
            SFS_INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
            safe_json.write_text(SFS_INBOX_FILE, json.dumps({"items": items}, ensure_ascii=False))
        except Exception as e:
            errors.append(f"sauvegarde: {e}")
    lst = sorted(items.values(), key=lambda x: str(x.get("at") or ""), reverse=True)
    out = {"ok": True, "items": lst[:400], "nouveaux": nouveaux, "errors": errors}
    _SFS_INBOX_CACHE["v"] = out
    _SFS_INBOX_CACHE["t"] = _t.time()
    return out


def refresh_pushs(creator_id) -> Dict[str, Any]:
    """Déclenche le bouton orange « MAJ » de la page Pushs d'une créatrice.

    Endpoint découvert par la sonde : /creator/{id}/refresh-push (attribut rel
    du bouton #action-btn). Demande à MYPULS de resynchroniser SES données —
    aucun appel vers OnlyFans/MyM de notre côté. POST d'abord, repli GET.
    """
    if not is_configured():
        return {"ok": False, "error": "Cookies MyPuls non configurés"}
    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Session MyPuls indisponible"}
    url = f"{BASE_URL}/creator/{int(creator_id)}/refresh-push"
    try:
        r = s.post(url, timeout=TIMEOUT,
                   headers={"X-Requested-With": "XMLHttpRequest"})
        if r.status_code in (404, 405):
            r = s.get(url, timeout=TIMEOUT,
                      headers={"X-Requested-With": "XMLHttpRequest"})
        _save_rotated_cookies(s)
        # un refresh déjà en cours / cooldown peut répondre autre chose que 200 :
        # on remonte le statut, l'appelant loggue sans s'arrêter
        return {"ok": r.status_code in (200, 202), "status": r.status_code,
                "body": (r.text or "")[:160]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def refresh_all_pushs(pause_s: float = 4.0) -> Dict[str, Any]:
    """Clique « MAJ » pour TOUTES les créatrices, avec une pause entre chaque
    (on reste poli avec MyPuls). Retourne le détail par créatrice."""
    import time as _t
    cr = list_creators()
    creators = cr.get("creators") or {}
    if not creators:
        return {"ok": False, "error": cr.get("error") or "Aucune créatrice"}
    detail, ok_n = {}, 0
    for name, cid in creators.items():
        r = refresh_pushs(cid)
        detail[name] = r.get("status") or r.get("error")
        if r.get("ok"):
            ok_n += 1
        _t.sleep(max(1.0, pause_s))
    print(f"[refresh-pushs] {ok_n}/{len(creators)} créatrices rafraîchies", flush=True)
    return {"ok": ok_n > 0, "reussites": ok_n, "total": len(creators), "detail": detail}


_PUSH_REFRESH_DAILY = {"on": False}


def start_pushs_refresh_daily(hour: int = 0, minute: int = 5) -> bool:
    """Chaque nuit à 00h05 (heure serveur) : clique « MAJ » pour chaque
    créatrice, attend 2 min que MyPuls resynchronise, puis recollecte les SFS
    reçus. Plus jamais de pushs figés depuis une semaine."""
    if _PUSH_REFRESH_DAILY["on"]:
        return False
    import threading
    import time as _t
    import datetime as _dt

    def _loop():
        while True:
            now = _dt.datetime.now()
            nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if nxt <= now:
                nxt += _dt.timedelta(days=1)
            _t.sleep(max(60, (nxt - now).total_seconds()))
            try:
                if is_configured():
                    refresh_all_pushs()
                    _t.sleep(120)              # laisser MyPuls resynchroniser
                    if api_configured():
                        api_sfs_inbox(force=True)
                    # compteurs d'abonnés du Setup SFS : mis à jour chaque nuit
                    # (le tri de la sidebar par audience reste juste tout seul)
                    try:
                        import sfs_setup
                        n = sfs_setup.autofill_mypuls_if_stale(force=True)
                        print(f"[refresh-pushs] compteurs abonnés : {n} identité(s) à jour",
                              flush=True)
                    except Exception as e:
                        print(f"[refresh-pushs] autofill subs: {e}", flush=True)
            except Exception as e:
                print(f"[refresh-pushs] nightly: {type(e).__name__}: {e}", flush=True)

    threading.Thread(target=_loop, daemon=True, name="pushs-refresh-daily").start()
    _PUSH_REFRESH_DAILY["on"] = True
    print(f"[refresh-pushs] job nocturne armé ({hour:02d}h{minute:02d})", flush=True)
    return True


_SFS_POLLER = {"on": False}


def start_sfs_inbox_poller(interval: int = 300) -> bool:
    """Collecte AUTOMATIQUE des SFS reçus, en tâche de fond (thread démon).

    L'API ne liste que les conversations NON LUES : plus on passe souvent,
    moins on rate de messages lus rapidement par un chatteur. Toutes les
    `interval` secondes (min 60) : 1 appel API par créatrice active, fusion
    dans data/sfs_inbox.json. Si le token API n'est pas (encore) configuré,
    le cycle est simplement sauté — le poser plus tard suffit, sans redémarrage.
    """
    if _SFS_POLLER["on"]:
        return False
    import threading
    import time as _t

    def _loop():
        while True:
            try:
                if api_configured():
                    r = api_sfs_inbox(force=True)
                    n = r.get("nouveaux") or 0
                    if n:
                        print(f"[sfs-inbox] {n} nouveau(x) message(s) entrant(s) archivé(s)",
                              flush=True)
                    for e in (r.get("errors") or [])[:3]:
                        print(f"[sfs-inbox] {e}", flush=True)
            except Exception as e:
                print(f"[sfs-inbox] poller: {type(e).__name__}: {e}", flush=True)
            _t.sleep(max(60, interval))

    threading.Thread(target=_loop, daemon=True, name="sfs-inbox-poller").start()
    _SFS_POLLER["on"] = True
    print(f"[sfs-inbox] collecte auto démarrée (toutes les {max(60, interval)}s)", flush=True)
    return True


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


def _norm_currency(c: str) -> str:
    """'€'/'eur' -> EUR, '$'/'usd' -> USD. Défaut EUR (MyM)."""
    c = (c or "").strip().upper()
    if "USD" in c or "$" in c:
        return "USD"
    if "EUR" in c or "€" in c:
        return "EUR"
    return "EUR"


# Familles de revenus du dashboard. Sert de vocabulaire commun a tous ceux
# qui classent une vente : cartes de la page Revenus, registre, feuille de paie.
CATEGORIES_TRANSACTION = ("Messages", "Tips", "Subscriptions", "Posts",
                          "Streams", "Referrals")


def _sans_accent(t: str) -> str:
    """« Média privé » -> « media prive ». Le libelle MyPuls arrive accentue ou
    non selon la page scrapee ; comparer sur la forme nue evite d'avoir a
    prevoir les deux orthographes a chaque test."""
    import unicodedata
    plat = unicodedata.normalize("NFD", (t or "").strip().lower())
    return "".join(c for c in plat if unicodedata.category(c) != "Mn")


def categorie_transaction(libelle: str) -> str:
    """Type de vente MyPuls -> famille de revenus. Chaine EXCLUSIVE : une vente
    ne compte que dans une seule famille.

    UN SEUL endroit decide de ce classement. Quand la regle etait recopiee dans
    la feuille de paie, la copie cherchait « ppv » alors que MyPuls ecrit
    « Media prive » : la colonne PPV affichait zero et ne recoupait jamais le CA.

    Retourne "" si aucune famille ne reconnait le libelle — l'appelant doit
    compter ces montants a part, jamais les laisser tomber en silence.
    """
    ty = _sans_accent(libelle)
    if not ty:
        return ""
    if "media prive" in ty or "ppv" in ty or "message" in ty:
        return "Messages"
    if "pourboire" in ty or "tip" in ty:
        return "Tips"
    if "abonnement" in ty or "subscription" in ty:
        return "Subscriptions"
    # MyPuls est en francais : « Publication » ne contient pas « post »
    if "post" in ty or "publication" in ty:
        return "Posts"
    if "stream" in ty:
        return "Streams"
    if "referral" in ty or "parrain" in ty:
        return "Referrals"
    return ""


def ca_par_categorie_usd(transactions, eur_usd: float) -> tuple:
    """Log de ventes -> (montant par famille en USD, ce qui n'entre nulle part).

    Le second element n'est pas decoratif : un libelle nouveau chez MyPuls
    (c'est ainsi que « Media prive » etait passe a la trappe) doit se VOIR,
    pas disparaitre du total. Il porte le montant, le nombre de ventes et
    quelques libelles en clair pour pouvoir corriger la regle.
    """
    par = {k: 0.0 for k in CATEGORIES_TRANSACTION}
    montant_hors, nb_hors, libelles = 0.0, 0, []
    for t in (transactions or []):
        try:
            montant = float(t.get("amount") or 0)
        except (TypeError, ValueError):
            montant = 0.0
        usd = montant * (1.0 if _norm_currency(t.get("currency")) == "USD" else eur_usd)
        famille = categorie_transaction(t.get("type"))
        if famille:
            par[famille] += usd
            continue
        montant_hors += usd
        nb_hors += 1
        lib = (t.get("type") or "").strip() or "(type vide)"
        if lib not in libelles and len(libelles) < 12:
            libelles.append(lib)
    return ({k: round(v, 2) for k, v in par.items()},
            {"montant": round(montant_hors, 2), "ventes": nb_hors,
             "libelles": libelles})


def ca_usd_chatteur(c: dict, eur_usd: float) -> float:
    """CA d'un chatteur ramene en dollars, une seule devise.

    La table de performance de MyPuls empile les euros MyM et les dollars
    OnlyFans dans la meme colonne « CA Total » : tout convertir comme des euros
    gonfle la part OnlyFans d'environ 6,5 %. La ventilation par devise vient du
    log de transactions (`ca_eur` / `ca_usd`, poses par fetch_team_stats).

    Elle n'est retenue que si elle recoupe le CA affiche a 5 % pres : les deux
    tables de MyPuls ne concordent pas toujours, et un split qui ne colle pas
    au total serait pire que la conversion approchee.
    """
    total = float(c.get("ca_total") or 0)
    eur, usd = c.get("ca_eur"), c.get("ca_usd")
    if eur is not None and usd is not None and (eur + usd) > 0:
        if abs((eur + usd) - total) <= max(1.0, 0.05 * total):
            return round(eur * eur_usd + usd, 2)
    # Pas de ventilation exploitable : on retombe sur l'hypothese MyM (EUR).
    return round(total * eur_usd, 2)


def _ca_by_currency(transactions) -> dict:
    """Somme des montants par devise (EUR = MyM, USD = OnlyFans)."""
    out: Dict[str, float] = {}
    for t in (transactions or []):
        cur = _norm_currency(t.get("currency"))
        try:
            out[cur] = round(out.get(cur, 0.0) + float(t.get("amount") or 0), 2)
        except Exception:
            pass
    return out


def _parse_amount(s: str) -> float:
    """Parse '18,32', '18,32 EUR', '1.234,56', '1,234.56', '18.32 USD' -> float.

    Ce qui ne se lit pas vaut 0.0 — et un 0.0 sur une colonne de montant ne
    se voit pas : la vente est simplement absente du total. Mesure sur
    l'ancienne version, qui remplacait toutes les virgules par des points sans
    regarder :
        '1.234,56'   -> 0.0   (millier a la francaise)
        '1,234.56'   -> 0.0   (millier a l'anglaise)
        '18.32 USD'  -> 0.0   (seuls « EUR » et « € » etaient retires)
        '$1,234.56'  -> 0.0
    Une seule ligne « CA Total » a 1 234,56 lue comme 0 suffit a faire
    disparaitre le chatteur du classement et sa part du chiffre.

    Regle : le DERNIER separateur rencontre est le separateur decimal, l'autre
    marque les milliers. Quand il n'y en a qu'un, on garde le comportement
    d'avant (decimal) — '1,234' vaut donc toujours 1.234, aucune lecture
    existante ne change.
    """
    if not s:
        return 0.0
    brut = str(s)
    # Une date ou une heure tombee dans une colonne de montant (decalage de
    # colonnes chez MyPuls) doit rester a zero : sans ce refus, « 05/08/2026 »
    # devient 5 082 026 une fois les separateurs otes, et un chiffre absurde
    # est bien pire qu'un zero.
    if "/" in brut or ":" in brut:
        return 0.0
    # Tout ce qui n'est pas un chiffre, un signe ou un separateur s'en va :
    # symboles et codes devise compris, dans les deux sens ('$18', '18 USD').
    t = re.sub(r"[^0-9,.\-+]", "", brut)
    if not t:
        return 0.0
    dernier_p, dernier_v = t.rfind("."), t.rfind(",")
    if dernier_p >= 0 and dernier_v >= 0:
        milliers, decimal = (",", ".") if dernier_p > dernier_v else (".", ",")
        t = t.replace(milliers, "").replace(decimal, ".")
    else:
        t = t.replace(",", ".")
    # Forme finale verifiee AVANT float() : '12.34.56' reste illisible, comme
    # avant, plutot que d'etre devine.
    if not re.fullmatch(r"[-+]?\d*\.?\d+", t):
        return 0.0
    try:
        return float(t)
    except Exception:
        return 0.0


def _montant_illisible(brut: str) -> bool:
    """Vrai quand la case porte quelque chose et que rien n'a pu en etre lu.

    Sert a COMPTER ces cases : un montant qui ne se lit pas vaut 0.0, et un
    0.0 se confond avec une vente a zero euro. Sans ce compteur, le seul
    symptome est un CA trop bas que personne ne sait expliquer.
    """
    t = (brut or "").strip()
    if not t:
        return False
    return _parse_amount(t) == 0.0 and re.search(r"[1-9]", t) is not None


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


# ---------------------------------------------------------------------------
# LIRE PAR EN-TETE, PAS PAR POSITION
#
# Les deux tableaux etaient lus par index : row[0] le createur, row[3] le
# montant, row[8] le CA total. Ca tient tant que MyPuls ne touche a rien.
# Le 05/09/2026 il a touche : le CA total est tombe a 0 alors que CA PPV et
# CA Tips se lisaient encore, et les noms de modeles sont devenus de petits
# nombres (1 a 15 pour 23 ventes) -- soit une colonne inseree en tete du log
# et une autre avant le total.
#
# Rien ne le signalait, parce qu'une colonne decalee ne LEVE pas d'erreur :
# elle rend un nom la ou on attendait un montant, et _parse_amount rend 0.0.
# Le CA s'effondre en silence, et le classement des chatteurs se vide.
#
# On lit donc les <th>. Une colonne ajoutee, deplacee ou renommee dans une
# forme qu'on reconnait ne casse plus rien ; une colonne qu'on ne reconnait
# PAS est signalee dans le diagnostic au lieu de valoir zero.
# ---------------------------------------------------------------------------

def _norm_entete(t: str) -> str:
    """Un en-tete comparable : sans accents, sans ponctuation, en minuscules."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("'", " ").replace("-", " ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _largeur(rows: List[List[str]]) -> int:
    """Le nombre de colonnes que les LIGNES portent vraiment.

    Les <th> ne suffisent pas : une page peut en compter plus que ses cellules
    (deux rangees d'en-tete, un <th> dans le corps). Un index tire des seuls
    en-tetes tomberait alors au-dela de la ligne, et `_cellule` rendrait le
    defaut -- c'est-a-dire zero, sans un mot. On confronte donc les deux.
    """
    return max((len(r) for r in (rows or [])), default=0)


def _colonne(entetes: List[str], *mots: str) -> int:
    """L'index de la premiere colonne dont l'en-tete correspond, sinon -1.

    On compare sur l'en-tete NORMALISE, en exigeant un mot entier ou un
    prefixe : « ca total » ne doit pas etre trouve par « total », qui
    designerait aussi bien « total propose ». L'ordre des `mots` est celui de
    la preference.
    """
    normes = [_norm_entete(e) for e in (entetes or [])]
    for m in mots:
        m = _norm_entete(m)
        if not m:
            continue
        for i, e in enumerate(normes):
            if e == m:
                return i
        for i, e in enumerate(normes):
            if e.startswith(m + " ") or e.endswith(" " + m) or (" " + m + " ") in " %s " % e:
                return i
    return -1


def _cellule(row: List[str], i: int, defaut: str = "") -> str:
    """La cellule d'index i, ou `defaut` — un index absent ne doit pas lever."""
    if i is None or i < 0 or i >= len(row):
        return defaut
    return row[i]


def _table_par_entetes(tables, *exigences) -> int:
    """L'index du tableau qui porte TOUTES ces colonnes, sinon -1.

    Identifier les tableaux par leur contenu plutot que par leur rang : un
    tableau ajoute a la page decalait « tables[1] » et faisait lire les
    performances dans autre chose.
    """
    for i, (entetes, _rows) in enumerate(tables or []):
        if all(_colonne(entetes, *variantes) >= 0 for variantes in exigences):
            return i
    return -1


# ---------------------------------------------------------------------------
# DECOUVRIR CE QUE L'API SERT VRAIMENT
#
# Sans jeton, MyPuls repond 401 a TOUT chemin sous /api/v1 -- meme a un nom
# invente (verifie le 05/09/2026 : /api/v1/zzz-nexiste-pas-du-tout -> 401).
# Leur authentification passe avant le routage : sonder de l'exterieur ne
# distingue donc pas « existe » de « n'existe pas ». Avec le jeton, 200 et
# 404 redeviennent lisibles.
#
# ON NE REND QUE LA FORME : chemin, code HTTP, noms des champs. Jamais un
# montant, jamais un nom de personne, jamais le jeton. C'est ce qui permet
# d'exposer cette lecture derriere le jeton du parc sans elargir ce qui est
# accessible : on apprend la STRUCTURE de l'API, pas les donnees.
# ---------------------------------------------------------------------------

def _forme_reponse(d) -> dict:
    """Les cles d'une reponse, sans son contenu."""
    f = {}
    if isinstance(d, dict):
        f["cles"] = sorted(d.keys())[:15]
        inner = d.get("data")
        if isinstance(inner, list):
            f["data"] = "liste de %d" % len(inner)
            if inner and isinstance(inner[0], dict):
                f["champs"] = sorted(inner[0].keys())[:30]
        elif isinstance(inner, dict):
            f["data"] = "objet"
            f["champs"] = sorted(inner.keys())[:30]
    elif isinstance(d, list):
        f["cles"] = "liste de %d" % len(d)
        if d and isinstance(d[0], dict):
            f["champs"] = sorted(d[0].keys())[:30]
    return f


def decouvrir_api(jours: int = 6) -> dict:
    """Quels endpoints l'API sert, et avec quels champs. Forme seulement."""
    if not api_configured():
        return {"ok": False, "error": "Aucun token API MyPuls (Settings > MyPuls)"}

    fin = date.today().isoformat()
    debut = (date.today() - timedelta(days=max(0, jours))).isoformat()
    periode = {"from": debut, "to": fin, "start": debut, "end": fin}

    # Un createur REEL : un id invente rendrait 404 pour la mauvaise raison.
    cid = ""
    try:
        crs = api_creators_cached()
        cid = str((crs[0] or {}).get("id") or "") if crs else ""
    except Exception:
        pass

    candidats = [
        ("session", None), ("creators", None),
        ("team", None), ("teams", None), ("team/members", None),
        ("chatters", periode), ("chatter", None), ("chatters/stats", periode),
        ("users", None), ("employees", None), ("staff", None),
        ("transactions", periode), ("sales", periode), ("earnings", periode),
        ("messages", periode), ("messaging-money", periode),
        ("messaging-money-team", periode),
        ("payouts", periode), ("statistics", periode), ("stats", periode),
        ("performance", periode), ("performances", periode),
        ("tracking-links", None), ("subscribers", periode),
    ]
    if cid:
        candidats += [
            ("creators/%s" % cid, None),
            ("creators/%s/stats" % cid, periode),
            ("creators/%s/revenue-by-day" % cid, periode),
            ("creators/%s/transactions" % cid, periode),
            ("creators/%s/sales" % cid, periode),
            ("creators/%s/chatters" % cid, periode),
            ("creators/%s/messages" % cid, periode),
            ("creators/%s/earnings" % cid, periode),
        ]

    tok = api_token()
    servis, absents, autres = [], [], []
    for chemin, params in candidats:
        url = "%s/api/v1/%s" % (BASE_URL, chemin)
        try:
            r = requests.get(url, headers={"X-API-TOKEN": tok,
                                           "Accept": "application/json"},
                             params=params or {}, timeout=15)
        except Exception as e:
            autres.append({"chemin": chemin, "erreur": type(e).__name__})
            continue
        if r.status_code == 404:
            absents.append(chemin)
            continue
        if r.status_code != 200:
            autres.append({"chemin": chemin, "code": r.status_code})
            continue
        try:
            forme = _forme_reponse(r.json())
        except Exception:
            forme = {"cles": "reponse non-JSON"}
        servis.append({"chemin": chemin, **forme})

    return {"ok": True, "createur_teste": cid or "(aucun)",
            "servis": servis, "absents": absents, "autres": autres,
            "periode": [debut, fin]}


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
        # CACHE NÉGATIF 60 s : seul le SUCCÈS était mis en cache — cookies
        # morts = chaque chargement de page re-payait un scrape/timeout de
        # 2-30 s. Une erreur récente est resservie telle quelle 1 min.
        _neg = cached.get("neg") if cached else None
        if _neg and (_t.time() - _neg["ts"]) < 60:
            return _neg["data"]

    def _fail_ts(err: str) -> Dict[str, Any]:
        out = {"ok": False, "error": err}
        _STATS_CACHE.setdefault(cache_key, {"ts": 0, "data": None})["neg"] = {
            "ts": _t.time(), "data": out}
        return out

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
        return _fail_ts(f"Erreur réseau : {e}")
    if r.status_code != 200:
        return _fail_ts(f"HTTP {r.status_code}")
    if _detect_login_redirect(r.text):
        return _fail_ts("Cookies expirés — reconnecte-toi sur MyPuls et recopie tes cookies")
    # Sauvegarder les cookies rotatés (REMEMBERME prolongé)
    _save_rotated_cookies(s)

    tables = _extract_tables(r.text)
    if len(tables) < 2:
        return {"ok": False, "error": f"Format de page inattendu (seulement {len(tables)} tableaux trouvés)"}

    # LES DEUX TABLEAUX SE RECONNAISSENT A LEURS COLONNES, pas a leur rang :
    # une table ajoutee a la page decalait tables[1] et faisait lire les
    # performances dans autre chose. On garde le rang comme dernier recours,
    # pour ne rien casser si les en-tetes disparaissent.
    _COLS_LOG = (("fan",), ("montant net", "montant", "net", "amount"))
    _COLS_PERF = (("presence",), ("ca total", "total"))
    i_log = _table_par_entetes(tables, *_COLS_LOG)
    i_perf = _table_par_entetes(tables, *_COLS_PERF)
    entetes_manquants = (i_log < 0 or i_perf < 0)
    if i_log < 0:
        i_log = 0
    if i_perf < 0:
        i_perf = 1 if len(tables) > 1 else 0

    e_log = tables[i_log][0]
    # Table du log : Créateur | User (chatter) | Fan | Montant net | Devise |
    #                Type | Date | Contexte | Action
    c_creator = _colonne(e_log, "createur", "creator", "modele", "model")
    c_chatter = _colonne(e_log, "user", "chatter", "chatteur", "utilisateur")
    c_fan = _colonne(e_log, "fan", "client")
    c_amount = _colonne(e_log, "montant net", "montant", "net", "amount")
    c_cur = _colonne(e_log, "devise", "currency")
    c_type = _colonne(e_log, "type", "categorie")
    c_date = _colonne(e_log, "date")
    c_ctx = _colonne(e_log, "contexte", "context")
    # Repli sur les positions HISTORIQUES quand un en-tete manque : mieux vaut
    # l'ancienne lecture que rien. Les colonnes reellement introuvables sont
    # comptees plus bas — c'est ce compte qui doit alerter, pas un CA a zero.
    # Un index tire des en-tetes mais introuvable dans les lignes ne vaut
    # rien : on le traite comme absent, pour qu'il tombe sur le repli et soit
    # COMPTE, au lieu de rendre une case vide a chaque ligne.
    _lg = _largeur(tables[i_log][1])
    if _lg:
        c_creator, c_chatter, c_fan, c_amount, c_cur, c_type, c_date, c_ctx = [
            (i if i < _lg else -1) for i in
            (c_creator, c_chatter, c_fan, c_amount, c_cur, c_type, c_date, c_ctx)]
    _defauts_log = {"creator": 0, "chatter": 1, "fan": 2, "amount": 3,
                    "cur": 4, "type": 5, "date": 6, "ctx": 7}
    colonnes_log_manquantes = [n for n, i in (
        ("createur", c_creator), ("chatteur", c_chatter), ("fan", c_fan),
        ("montant", c_amount), ("devise", c_cur), ("type", c_type),
        ("date", c_date)) if i < 0]
    if c_creator < 0: c_creator = _defauts_log["creator"]
    if c_chatter < 0: c_chatter = _defauts_log["chatter"]
    if c_fan < 0: c_fan = _defauts_log["fan"]
    if c_amount < 0: c_amount = _defauts_log["amount"]
    if c_cur < 0: c_cur = _defauts_log["cur"]
    if c_type < 0: c_type = _defauts_log["type"]
    if c_date < 0: c_date = _defauts_log["date"]
    if c_ctx < 0: c_ctx = _defauts_log["ctx"]

    transactions: List[Dict[str, Any]] = []
    # Lignes du tableau qu'on n'a pas su lire (moins de colonnes que prevu).
    # Avant, elles disparaissaient en silence : une vente ecartee ici
    # n'apparaissait plus nulle part, et rien ne le signalait.
    lignes_illisibles = 0
    # Cases « Montant net » qui portent un chiffre mais qu'on n'a pas su lire :
    # elles valent 0.0, ce qui se confond avec une vente a zero. On les compte,
    # sinon le seul symptome est un CA trop bas que rien n'explique.
    montants_illisibles = 0
    _mini = max(c_creator, c_chatter, c_fan, c_amount, c_date) + 1
    for row in tables[i_log][1]:
        if len(row) < _mini:
            if any((c or "").strip() for c in row):
                lignes_illisibles += 1
            continue
        if _montant_illisible(_cellule(row, c_amount)):
            montants_illisibles += 1
        transactions.append({
            "creator": _cellule(row, c_creator),
            "chatter": _cellule(row, c_chatter),
            "fan": _cellule(row, c_fan),
            "amount": _parse_amount(_cellule(row, c_amount)),
            "currency": _cellule(row, c_cur, "EUR") or "EUR",
            "type": _cellule(row, c_type),
            "date": _cellule(row, c_date),
            "context": _cellule(row, c_ctx),
        })

    # Table 1 = chatter performance
    # Headers: Chatter | Présence | Réactivité | Proposé | Vendu | Taux conv. | CA PPV | CA Tips | CA Total
    # Meme regle que le registre des ventes, definie a un seul endroit.
    # Import local : ventes_export n'a pas a etre charge pour le reste.
    try:
        from ventes_export import est_non_attribue as _est_non_attribue
    except Exception:                       # module absent : on ne marque rien
        def _est_non_attribue(_n):
            return False

    # Table des performances : Chatter | Présence | Réactivité | Proposé |
    #                          Vendu | Taux conv. | CA PPV | CA Tips | CA Total
    e_perf = tables[i_perf][0]
    p_name = _colonne(e_perf, "chatter", "chatteur", "user", "utilisateur")
    p_pres = _colonne(e_perf, "presence")
    p_reac = _colonne(e_perf, "reactivite", "reactivity")
    p_prop = _colonne(e_perf, "propose", "proposed")
    p_vend = _colonne(e_perf, "vendu", "sold")
    p_conv = _colonne(e_perf, "taux conv", "conversion", "conv")
    p_ppv = _colonne(e_perf, "ca ppv", "ppv")
    p_tips = _colonne(e_perf, "ca tips", "tips", "pourboires")
    p_tot = _colonne(e_perf, "ca total", "total")
    _lp = _largeur(tables[i_perf][1])
    if _lp:
        p_name, p_pres, p_reac, p_prop, p_vend, p_conv, p_ppv, p_tips, p_tot = [
            (i if i < _lp else -1) for i in
            (p_name, p_pres, p_reac, p_prop, p_vend, p_conv, p_ppv, p_tips, p_tot)]
    colonnes_perf_manquantes = [n for n, i in (
        ("chatteur", p_name), ("ca ppv", p_ppv), ("ca tips", p_tips),
        ("ca total", p_tot)) if i < 0]
    # Repli sur les positions historiques, colonne par colonne.
    if p_name < 0: p_name = 0
    if p_pres < 0: p_pres = 1
    if p_reac < 0: p_reac = 2
    if p_prop < 0: p_prop = 3
    if p_vend < 0: p_vend = 4
    if p_conv < 0: p_conv = 5
    if p_ppv < 0: p_ppv = 6
    if p_tips < 0: p_tips = 7
    if p_tot < 0: p_tot = 8

    chatters: List[Dict[str, Any]] = []
    chatters_illisibles = 0
    _mini_perf = max(p_name, p_ppv, p_tips, p_tot) + 1
    for row in tables[i_perf][1]:
        if len(row) < _mini_perf:
            if any((c or "").strip() for c in row):
                chatters_illisibles += 1
            continue
        # « Indetermine (Creatrice) » n'est pas quelqu'un : MyPuls met ce
        # libelle quand la vente n'est rattachee a aucun chatteur. On le
        # MARQUE sans le retirer — l'argent a bien ete encaisse, il doit
        # rester dans le CA ; c'est la PART A PAYER qui doit l'ignorer.
        _nom = _cellule(row, p_name)
        chatters.append({
            "non_attribue": _est_non_attribue(_nom),
            "name": _nom,
            "presence": _cellule(row, p_pres),
            "reactivity": _cellule(row, p_reac),
            "proposed": _parse_amount(_cellule(row, p_prop)) if _cellule(row, p_prop) else 0,
            "sold": _parse_amount(_cellule(row, p_vend)) if _cellule(row, p_vend) else 0,
            "conv_rate": _cellule(row, p_conv),
            "ca_ppv": _parse_amount(_cellule(row, p_ppv)),
            "ca_tips": _parse_amount(_cellule(row, p_tips)),
            "ca_total": _parse_amount(_cellule(row, p_tot)),
        })
    # CA par DEVISE et par CHATTEUR, reconstruit depuis le log de transactions
    # (la table perf additionne EUR MyM et USD OnlyFans dans la même colonne :
    # payer là-dessus en convertissant tout comme des EUR surpaie les ventes OF).
    _by_chatter_cur: Dict[str, Dict[str, float]] = {}
    for t in transactions:
        key = (t.get("chatter") or "").strip().lower()
        if not key:
            continue
        cs = str(t.get("currency") or "").upper()
        cur = "USD" if ("USD" in cs or "$" in cs) else "EUR"
        d2 = _by_chatter_cur.setdefault(key, {"EUR": 0.0, "USD": 0.0})
        d2[cur] += float(t.get("amount") or 0)
    for c in chatters:
        split = _by_chatter_cur.get((c.get("name") or "").strip().lower())
        c["ca_eur"] = round(split["EUR"], 2) if split else None
        c["ca_usd"] = round(split["USD"], 2) if split else None
    # Tri par CA Total décroissant
    chatters.sort(key=lambda c: c["ca_total"], reverse=True)

    # Taux du jour, deja mis en cache 24 h dans la config : sert a rendre le CA
    # dans UNE seule devise. Sans lui on retombe sur la valeur de repli, jamais
    # sur un melange silencieux.
    try:
        _taux_eur_usd = float(get_eur_usd_rate()["rate"]) or 1.14
    except Exception:
        _taux_eur_usd = 1.14
    _par_devise = _ca_by_currency(transactions)
    _cat_usd, _hors_cat = ca_par_categorie_usd(transactions, _taux_eur_usd)

    # Totaux
    totals = {
        # ATTENTION : somme BRUTE de la colonne « CA Total » de MyPuls, qui
        # empile des euros MyM et des dollars OnlyFans. Elle n'est dans aucune
        # devise — l'afficher suivie d'un « € » surevalue la part OnlyFans
        # d'environ 6,5 %. Pour un montant affichable : "ca_total_usd".
        "ca_total": round(sum(c["ca_total"] for c in chatters), 2),
        "ca_ppv": round(sum(c["ca_ppv"] for c in chatters), 2),
        "ca_tips": round(sum(c["ca_tips"] for c in chatters), 2),
        # Part du CA que MyPuls n'a rattachee a personne. Elle compte dans le
        # chiffre d'affaires — elle ne doit compter dans aucune remuneration.
        "ca_non_attribue": round(
            sum(c["ca_total"] for c in chatters if c.get("non_attribue")), 2),
        "nb_non_attribue": sum(1 for c in chatters if c.get("non_attribue")),
        # CA ventilé PAR DEVISE (depuis les transactions, seule table qui la porte).
        # EUR = MyM, USD = OnlyFans -> permet de convertir proprement et
        # d'appliquer les frais OF, au lieu d'additionner des € et des $.
        "ca_by_currency": _par_devise,
        # Le meme CA, mais dans UNE devise : chaque chatteur est converti avec
        # sa propre ventilation (ca_usd_chatteur), pas le total en bloc. C'est
        # ce montant-la qui peut etre affiche avec un symbole.
        "ca_total_usd": round(sum(ca_usd_chatteur(c, _taux_eur_usd)
                                  for c in chatters), 2),
        "eur_usd": _taux_eur_usd,
        # Les deux parts, telles que le log les porte : EUR = MyM, USD = OF.
        "ca_eur": round(_par_devise.get("EUR", 0.0), 2),
        "ca_usd": round(_par_devise.get("USD", 0.0), 2),
        # Ventilation par famille de vente, en dollars, issue du LOG (la table
        # de performance ne donne ni la devise ni le detail par type).
        # "ca_hors_categorie" recense ce qu'aucune famille ne reconnait :
        # tant qu'il vaut 0, les familles recoupent le CA du log.
        "ca_categories_usd": _cat_usd,
        "ca_hors_categorie": _hors_cat,
        "nb_transactions": len(transactions),
        "nb_chatters": len(chatters),
        # Compte des PERSONNES : les lignes « Indetermine (Creatrice) » sont
        # des ventes orphelines, pas des chatteurs de plus.
        "active_chatters": sum(1 for c in chatters
                               if c["ca_total"] > 0 and not c.get("non_attribue")),
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

    # Ce que la lecture a laisse de cote : sans ca, un ecart entre le CA
    # affiche et la somme des ventes n'a aucune explication consultable.
    _sans_nom = [t for t in transactions if not (t.get("chatter") or "").strip()]
    diagnostic = {
        # CE QUE MYPULS A ENVOYE, mot pour mot. C'est ce qui manquait le
        # 05/09 : le CA etait a zero et rien ne permettait de voir que les
        # colonnes avaient bouge. Une capture d'ecran de moins a demander.
        "entetes_log": list(tables[i_log][0] or []),
        "entetes_perf": list(tables[i_perf][0] or []),
        "colonnes_manquantes": colonnes_log_manquantes + colonnes_perf_manquantes,
        "tables_reconnues": not entetes_manquants,
        "nb_tables": len(tables),
        "lignes_illisibles": lignes_illisibles,
        "montants_illisibles": montants_illisibles,
        "chatters_illisibles": chatters_illisibles,
        "ventes_lues": len(transactions),
        "ventes_sans_chatteur": len(_sans_nom),
        "montant_sans_chatteur": round(sum(t.get("amount") or 0 for t in _sans_nom), 2),
    }

    result = {
        "ok": True,
        "transactions": transactions,
        "chatters": chatters,
        "diagnostic": diagnostic,
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


# ============ Factures du CRM (onglet Factures & Paiements de /profil) ============

_INVOICES_CACHE: Dict[str, Any] = {}


def fetch_invoices(use_cache: bool = True) -> Dict[str, Any]:
    """Factures & Paiements du CRM MyPuls (ce que MyPuls facture à l'agence).

    Scrape /profil (onglet #tab-invoices, présent dans le HTML de la page) et
    parse la table Date | Compte Créateur | N° facture | Montant | Statut.
    Cache mémoire 5 min.

    Retourne : {ok, invoices: [{date, date_iso, creator, number, amount, status}]}
    """
    import time as _t
    if use_cache and _INVOICES_CACHE and (_t.time() - _INVOICES_CACHE.get("ts", 0)) < 300:
        return _INVOICES_CACHE["data"]
    s = _make_session()
    if s is None:
        return {"ok": False, "error": "Cookies MyPuls non configurés"}
    # Les factures sont sur un endpoint DÉDIÉ (/profil/invoices), pas dans /profil
    # (chargé en AJAX). Confirmé via HAR 09/07 : table complète, non paginée.
    try:
        r = s.get(f"{BASE_URL}/profil/invoices", timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code != 200 or _detect_login_redirect(r.text):
        return {"ok": False, "error": "Cookies expirés — reconnecte-toi sur MyPuls"}
    _save_rotated_cookies(s)

    invoices: List[Dict[str, Any]] = []
    for headers, rows in _extract_tables(r.text):
        # la table des factures est celle dont un entête contient "facture"
        if not any("facture" in (h or "").lower() for h in headers):
            continue
        for row in rows:
            if len(row) < 5:
                continue
            d = (row[0] or "").strip()  # "07/07/2026 15:17"
            iso = ""
            try:
                parts = d.split(" ")[0].split("/")
                if len(parts) == 3:
                    iso = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
            except Exception:
                pass
            invoices.append({
                "date": d,
                "date_iso": iso,
                "creator": row[1],
                "number": row[2],
                "amount": _parse_amount(row[3]),
                "status": row[4],
            })
    if not invoices:
        return {"ok": False, "error": "Tableau des factures introuvable sur /profil"}
    result = {"ok": True, "invoices": invoices}
    _INVOICES_CACHE["ts"] = int(_t.time())
    _INVOICES_CACHE["data"] = result
    return result


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
    safe_json.write_text(CHATTERS_FILE, json.dumps(data, indent=2, ensure_ascii=False))


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


def _period_bounds(pid: str):
    """('2026-07-01_2026-07-15') -> (debut, fin) ou None."""
    try:
        a, b = str(pid or "").split("_", 1)
        if len(a) == 10 and len(b) == 10:
            return a, b
    except Exception:
        pass
    return None


def is_chatter_paid(name: str, period_id: str) -> bool:
    """True si le chatteur a été marqué payé pour cette période.

    La case était mémorisée sur la plage de dates EXACTE : changer de préréglage
    (7 j / 30 j / quinzaine) la faisait disparaître alors que la personne avait
    bien été payée. On considère donc aussi comme payée toute plage INCLUSE dans
    une période déjà réglée.
    """
    if not period_id:
        return False
    meta = get_chatter_meta(name)
    paid = meta.get("paid_periods", []) or []
    if period_id in paid:
        return True
    cur = _period_bounds(period_id)
    if not cur:
        return False
    for p in paid:
        b = _period_bounds(p)
        if b and b[0] <= cur[0] and cur[1] <= b[1]:
            return True          # plage affichée incluse dans une période payée
    return False


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


def get_eur_usd_rate_for_date(iso_date: str) -> Dict[str, Any]:
    """Taux EUR->USD BCE HISTORIQUE pour une date (mois clos). Immuable -> caché
    à vie par date dans config['eur_usd_hist']. Sert à figer un mois clos sur SON
    taux d'époque et non sur le 'latest' du jour de consultation.
    Retourne {rate, date, source} ; source in {api, cache, error}.
    (Frankfurter renvoie le dernier jour ouvré si la date tombe un week-end.)"""
    cfg = load_config()
    hist = cfg.get("eur_usd_hist") or {}
    if iso_date in hist:
        try:
            v = float(hist[iso_date])
            if v > 0:
                return {"rate": v, "date": iso_date, "source": "cache"}
        except Exception:
            pass
    try:
        r = requests.get(
            f"https://api.frankfurter.dev/v1/{iso_date}?base=EUR&symbols=USD",
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            rate = float(data["rates"]["USD"])
            if rate > 0:
                hist[iso_date] = rate
                cfg["eur_usd_hist"] = hist
                save_config(cfg)
                return {"rate": rate, "date": data.get("date", iso_date), "source": "api"}
    except Exception:
        pass
    return {"rate": 0.0, "date": iso_date, "source": "error"}


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
    safe_json.write_text(CREATOR_ORDER_FILE, json.dumps([int(x) for x in creator_ids], indent=2))


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

    # CACHE NÉGATIF (mémoire, 60 s) : list_creators est appelé par ~6 rendus du
    # chargement de page. Sans lui, cookies morts = chaque GET / re-payait un
    # scrape de 30 s (TIMEOUT) -> les gros pics de lenteur constatés.
    _neg = getattr(list_creators, "_neg", None)
    if not force_refresh and _neg and (_t.time() - _neg[0]) < 60:
        return _neg[1]

    def _fail(err: str) -> Dict[str, Any]:
        out = {"ok": False, "error": err}
        if cache:
            out["creators"] = cache      # on ressert le dernier bon état connu
        list_creators._neg = (_t.time(), out)
        return out

    s = _make_session()
    if s is None:
        return _fail("Cookies non configurés")
    try:
        r = s.get(f"{BASE_URL}/creators", timeout=TIMEOUT)
    except Exception as e:
        return _fail(f"Erreur réseau : {e}")
    if r.status_code != 200 or _detect_login_redirect(r.text):
        return _fail("Cookies expirés")
    list_creators._neg = None

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

    # Parse à 0 créateur (markup MyPuls changé, page A/B, rendu client…) : NE PAS
    # écraser le cache avec {} — sinon avatars/top-créateurs disparaissent 5 min
    # avec ok=True. On garde le dernier bon cache et on signale l'échec.
    if not creators:
        return {"ok": False, "error": "parser: 0 créateur (markup MyPuls changé ?)",
                "creators": cfg.get("creators_cache", {})}

    # Sauvegarder en cache
    cfg["creators_cache"] = creators
    cfg["creators_cache_ts"] = int(_t.time())
    save_config(cfg)
    return {"ok": True, "creators": creators}


def list_pushs(creator_id: int, max_pages: int = 1, days: int = 0) -> Dict[str, Any]:
    """Liste les push (messages de masse) d'un creator.

    Flux observe : GET /switch-creator/{id}?from=app_pushs (selectionne le creator),
    puis GET /pushs/page/N -> JSON {items:[...], hasMore, page}.
    Chaque item : {id, description, sentAt 'JJ/MM/AAAA HH:MM', types[], price,
    promoPrice, sales, ca, hasMod, medias:[{thumbUrl,...}]}.

    days > 0 : on pagine (dans la limite de max_pages) jusqu'a couvrir `days`
    jours en arriere — les pushs arrivent tries du plus recent au plus ancien,
    donc on s'arrete des qu'une page entiere est plus vieille que la fenetre,
    sans aspirer l'historique complet.

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
    import datetime as _dt
    cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)) if days > 0 else None
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
        page_dates = []
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
            if cutoff is not None:
                try:
                    page_dates.append(_dt.datetime.strptime(
                        (it.get("sentAt") or "").strip(), "%d/%m/%Y %H:%M"))
                except Exception:
                    pass
        if not j.get("hasMore"):
            break
        # Fenetre couverte ? (le PLUS RECENT de la page est deja hors fenetre
        # -> toutes les pages suivantes le seront aussi, tri anti-chronologique)
        if cutoff is not None and page_dates and max(page_dates) < cutoff:
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


# ---- Liens de suivi (Stats > Liens de suivi) --------------------------------
#
# Un lien de suivi porte un CODE (« c85 ») qu'on retrouve a la fin de la
# destination des liens GetMySocial : onlyfans.com/<pseudo>/c85. C'est par ce
# code qu'on rattache les abonnes MyPuls aux clics GetMySocial — jamais par le
# nom, qui s'ecrit « Bo07 » ici et « BO7 » la, « Pam Pam » ici et « PAMPAM »
# la : aucun rapprochement de noms ne tiendrait.
_TRACKING_CACHE: Dict[str, Any] = {}     # {"t": ts, "v": [...]}
_TRACKING_TTL = 600                      # 10 min


def api_tracking_links(force: bool = False) -> list:
    """Les liens de suivi, normalises. [] si l'API refuse.

    UN SEUL appel pour les ~468 lignes, garde 10 minutes. L'API MyPuls limite
    le debit — une sonde a deja pris un 429 et rendu des 403 sur tout le reste.
    Un appel par personne serait le plus sur moyen de tout faire tomber.
    """
    import time as _t
    hit = _TRACKING_CACHE.get("v")
    if hit is not None and not force and (_t.time() - _TRACKING_CACHE.get("t", 0)) < _TRACKING_TTL:
        return hit
    res = api_get("tracking-links", {"per_page": 500})
    if not res.get("ok"):
        # On ne met PAS en cache un echec : la prochaine tentative doit
        # reessayer, pas servir une liste vide pendant dix minutes.
        return _TRACKING_CACHE.get("v") or []
    d = res.get("data")
    items = d if isinstance(d, list) else None
    if items is None and isinstance(d, dict):
        inner = d.get("data")
        items = inner.get("data") if isinstance(inner, dict) else inner
    out = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        code = str(it.get("code") or "").strip()
        if not code:
            continue
        out.append({
            "code": code,
            "nom": str(it.get("name") or "").strip(),
            "creator_id": it.get("creator_id"),
            "abonnes": it.get("subscribers_total"),
            "abonnes_periode": it.get("subscribers_period"),
            "nouveaux": it.get("new_subscribers"),
            "visites": it.get("visits_total"),
            "visites_periode": it.get("visits_period"),
            "actif": bool(it.get("active", True)),
        })
    _TRACKING_CACHE.update({"t": _t.time(), "v": out})
    return out


def tracking_par_code(creator_id=None) -> dict:
    """{code: lien de suivi}, eventuellement limite a une creatrice.

    Le code n'est unique QUE dans une creatrice : « c85 » chez l'une n'est pas
    « c85 » chez l'autre. Sans le filtre, deux modeles se voleraient leurs
    abonnes.
    """
    out = {}
    for t in api_tracking_links():
        if creator_id is not None and t.get("creator_id") != creator_id:
            continue
        out[t["code"]] = t
    return out
