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


# ---------------------------------------------------------------------------
# LE TROUSSEAU — plusieurs cles, une seule interface
#
# POURQUOI PLUSIEURS. Le quota de MyPuls est de 60 requetes par minute. Si ce
# compte est tenu PAR CLE, plusieurs cles multiplient le debit ; s'il est tenu
# par compte ou par IP, elles ne changent rien. L'en-tete
# `x-ratelimit-limit` ne dit pas lequel, et personne ne le sait sans essayer.
#
# La rotation TRANCHE LA QUESTION toute seule : si le quota est par cle, une
# cle au repos laisse la place a une autre et le debit monte ; sinon rien ne
# se casse, on retombe simplement sur le meme plafond. Dans les deux cas le
# code est correct -- c'est ce qui permet d'ajouter des cles sans avoir a
# demontrer quoi que ce soit d'abord.
#
# CE N'EST PAS UNE SOLUTION A LA CONSOMMATION. Le site brulait 129 requetes
# par chargement de page ; multiplier le budget aurait cache le defaut au lieu
# de l'eteindre. Le trousseau sert a ISOLER (un gros rattrapage sur sa propre
# cle, pour qu'il ne fasse pas tomber le tableau de bord) et a encaisser une
# pointe, pas a se dispenser de compter.
#
# UNE CLE AU REPOS N'EST PAS UNE CLE MORTE. Un 429 porte `Retry-After` : on
# note l'heure de reveil et on passe a la suivante. Sans ca, on reessaierait
# la meme cle en boucle pendant qu'une autre attend, inutilisee.
# ---------------------------------------------------------------------------

def _cles_brutes() -> list:
    """Le trousseau tel qu'il est range, en migrant l'ancienne cle unique."""
    cfg = load_config()
    cles = cfg.get("api_keys")
    if isinstance(cles, list) and cles:
        return [c for c in cles if isinstance(c, dict) and (c.get("token") or "").strip()]
    # Migration douce : la cle unique historique devient la premiere du
    # trousseau, sans que personne n'ait a la recoller.
    seul = (cfg.get("api_token") or "").strip()
    if seul:
        return [{"id": "k1", "label": "Clé 1", "token": seul,
                 "ok": bool(cfg.get("api_token_ok"))}]
    return []


def api_keys(masquer: bool = True) -> list:
    """Les cles, pretes a afficher. Le jeton n'en sort JAMAIS en entier."""
    import time as _t
    out = []
    for i, c in enumerate(_cles_brutes()):
        tok = (c.get("token") or "").strip()
        e = {"id": c.get("id") or ("k%d" % (i + 1)),
             "label": c.get("label") or ("Clé %d" % (i + 1)),
             "ok": bool(c.get("ok")),
             "derniere_erreur": c.get("derniere_erreur") or "",
             "au_repos": max(0, int((c.get("repos_jusqua") or 0) - _t.time())),
             "appels": int(c.get("appels") or 0)}
        # Quatre caracteres suffisent a reconnaitre une cle sans la divulguer.
        e["apercu"] = ("…" + tok[-4:]) if len(tok) >= 4 else "…"
        if not masquer:
            e["token"] = tok
        out.append(e)
    return out


def save_api_keys(cles: list) -> None:
    """Range le trousseau. La premiere cle reste `api_token` pour compat."""
    cfg = load_config()
    propres = []
    for i, c in enumerate(cles or []):
        tok = str((c or {}).get("token") or "").strip()
        if not tok:
            continue
        propres.append({"id": str(c.get("id") or "k%d" % (i + 1))[:20],
                        "label": str(c.get("label") or "Clé %d" % (i + 1))[:40],
                        "token": tok,
                        "ok": bool(c.get("ok")),
                        "derniere_erreur": str(c.get("derniere_erreur") or "")[:120],
                        "repos_jusqua": float(c.get("repos_jusqua") or 0),
                        "appels": int(c.get("appels") or 0)})
    cfg["api_keys"] = propres
    # TOUT CE QUI LIT `api_token` CONTINUE DE MARCHER. Une bascule d'un seul
    # tenant aurait demande de reprendre chaque appelant en meme temps ; ici
    # l'ancien champ suit le trousseau, et on migre au rythme qu'on veut.
    cfg["api_token"] = propres[0]["token"] if propres else ""
    cfg["api_token_ok"] = bool(propres[0]["ok"]) if propres else False
    save_config(cfg)


def ajouter_api_key(token: str, label: str = "") -> dict:
    """Ajoute une cle. Refuse un doublon : deux fois la meme ne double rien."""
    tok = (token or "").strip()
    if not tok:
        return {"ok": False, "error": "Jeton vide"}
    cles = _cles_brutes()
    if any((c.get("token") or "").strip() == tok for c in cles):
        return {"ok": False, "error": "Cette clé est déjà dans le trousseau"}
    n = len(cles) + 1
    ids = {c.get("id") for c in cles}
    i = n
    while ("k%d" % i) in ids:
        i += 1
    cles.append({"id": "k%d" % i, "label": (label or "").strip() or ("Clé %d" % n),
                 "token": tok, "ok": False})
    save_api_keys(cles)
    return {"ok": True, "id": "k%d" % i, "total": len(cles)}


def retirer_api_key(cle_id: str) -> dict:
    cles = [c for c in _cles_brutes() if c.get("id") != (cle_id or "")]
    save_api_keys(cles)
    return {"ok": True, "total": len(cles)}


def renommer_api_key(cle_id: str, label: str) -> dict:
    cles = _cles_brutes()
    for c in cles:
        if c.get("id") == cle_id:
            c["label"] = (label or "").strip()[:40] or c.get("label")
    save_api_keys(cles)
    return {"ok": True}


def _noter_cle(cle_id: str, ok: bool = None, repos_s: float = 0,
               erreur: str = "", compter: bool = False) -> None:
    """Met a jour l'etat d'une cle sans reecrire les autres."""
    import time as _t
    cles = _cles_brutes()
    for c in cles:
        if c.get("id") != cle_id:
            continue
        if ok is not None:
            c["ok"] = bool(ok)
        if repos_s > 0:
            c["repos_jusqua"] = _t.time() + repos_s
        if erreur:
            c["derniere_erreur"] = erreur[:120]
        elif ok:
            c["derniere_erreur"] = ""
        if compter:
            c["appels"] = int(c.get("appels") or 0) + 1
    save_api_keys(cles)


#: Ou en est la rotation. En memoire : deux processus tourneraient chacun sur
#: sa propre position, ce qui reste correct -- l'ordre importe peu, seul le
#: fait de ne pas taper toujours la meme cle compte.
_ROTATION = {"i": 0}


def _cle_disponible():
    """La prochaine cle utilisable : (id, jeton), ou (None, "") si toutes au
    repos. Rend la MOINS longtemps au repos en dernier recours, pour ne
    jamais bloquer completement."""
    import time as _t
    cles = _cles_brutes()
    if not cles:
        return None, ""
    maintenant = _t.time()
    libres = [c for c in cles if float(c.get("repos_jusqua") or 0) <= maintenant]
    if libres:
        _ROTATION["i"] = (_ROTATION["i"] + 1) % len(libres)
        c = libres[_ROTATION["i"]]
        return c.get("id"), (c.get("token") or "").strip()
    # Toutes au repos : on prend celle qui se reveille le plus tot. Elle
    # rendra peut-etre 429, et c'est mieux que de ne rien tenter -- l'appelant
    # saura que le quota est atteint au lieu de recevoir « pas de cle ».
    c = min(cles, key=lambda x: float(x.get("repos_jusqua") or 0))
    return c.get("id"), (c.get("token") or "").strip()


def api_token() -> str:
    """La cle a utiliser MAINTENANT. Une seule cle : c'est elle, comme avant."""
    _id, tok = _cle_disponible()
    return tok


def api_configured() -> bool:
    return bool(api_token())


def api_get(path: str, params: dict = None, _essai: int = 0) -> dict:
    """GET sur l'API MyPuls. Retourne {ok, data} ou {ok: False, error}.

    TOURNE SUR LE TROUSSEAU. Une cle qui prend un 429 est mise au repos
    pendant la duree que MyPuls annonce (`Retry-After`), et l'appel est
    RETENTE avec la suivante. Sans cette reprise, la rotation ne servirait a
    rien : on rendrait l'erreur alors qu'une autre cle attend, inutilisee.

    Une seule reprise : au-dela, soit toutes les cles sont saturees -- et le
    quota est manifestement compte ailleurs que par cle -- soit le probleme
    n'est pas le quota. Insister ferait tourner la boucle sans rien apprendre.
    """
    cle_id, tok = _cle_disponible()
    if not tok:
        return {"ok": False, "error": "Aucun token API MyPuls (Settings → MyPuls)"}
    import requests
    url = f"{BASE_URL}/api/v1/{path.lstrip('/')}"
    try:
        r = requests.get(url, headers={"X-API-TOKEN": tok, "Accept": "application/json"},
                         params=params or {}, timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": f"Connexion API impossible : {e}"}

    if r.status_code == 429:
        # MyPuls dit quand revenir : on le croit, plutot que de deviner.
        try:
            repos = float(r.headers.get("Retry-After") or 60)
        except (TypeError, ValueError):
            repos = 60.0
        _noter_cle(cle_id, repos_s=max(1.0, min(300.0, repos)),
                   erreur="quota atteint (429)")
        if _essai == 0 and len(_cles_brutes()) > 1:
            return api_get(path, params, _essai=1)
        return {"ok": False, "error": "Quota MyPuls atteint (429), "
                                      "réessai dans %ds" % int(repos)}

    if r.status_code in (401, 403):
        # 401 = la cle est mauvaise ; 403 = elle est bonne mais n'a pas la
        # portee. On ne les confond pas : la premiere se remplace, la
        # seconde demande un compte owner / team leader.
        _noter_cle(cle_id, ok=(r.status_code == 403),
                   erreur=("clé refusée (401)" if r.status_code == 401
                           else "hors périmètre (403)"))
        return {"ok": False, "error": f"Token API refusé (HTTP {r.status_code})"}
    if r.status_code == 404:
        return {"ok": False, "error": f"Endpoint introuvable : {url}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code} : {r.text[:200]}"}
    _noter_cle(cle_id, ok=True, compter=True)
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

#: REPOS APRES UN AGREGAT PARTIEL.
#:
#: Un agregat ampute (une creatrice en 429 ou en timeout) n'etait PAS mis en
#: cache, pour ne pas afficher un total partiel comme s'il etait complet. La
#: precaution est juste, la consequence ne l'etait pas : sans cache, le rendu
#: suivant relancait les trente-trois requetes, qui retombaient sur la meme
#: minute saturee, qui produisait un nouvel agregat partiel. La saturation
#: s'entretenait elle-meme, et le premier 429 suffisait a l'installer.
#:
#: On garde donc le resultat -- AVEC ses drapeaux `errors` et `stale`, que
#: l'ecran affiche deja -- mais tres brievement : de quoi absorber la rafale
#: de rendus d'une meme page sans figer une valeur incomplete.
_API_PARTIEL_TTL = 45

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
    if hit and not force:
        _age = _t.time() - hit[0]
        _ttl = (_API_PARTIEL_TTL
                if (hit[1].get("errors") or hit[1].get("stale"))
                else _API_OVERVIEW_TTL)
        if _age < _ttl:
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
    # UN AGRÉGAT AMPUTÉ EST GARDÉ, MAIS BRIÈVEMENT (45 s au lieu de 5 min).
    # Ne rien garder du tout relançait les trente-trois requêtes au rendu
    # suivant, sur la même minute saturée : la panne se réalimentait. Le
    # résultat part avec ses drapeaux `errors` / `stale`, que l'écran affiche
    # — un total partiel ne peut donc pas passer pour complet.
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
    if hit:
        # Même règle que l'agrégat : une série amputée ne vaut que 45 s, une
        # série complète cinq minutes.
        _ttl = (_API_PARTIEL_TTL if hit[1].get("error") or hit[1].get("errors")
                else _API_SERIES_TTL)
        if (_t.time() - hit[0]) < _ttl:
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
    # Une série AMPUTÉE est gardée 45 s, pas 5 minutes : servir une courbe
    # partielle comme si elle était complète serait faux, mais ne rien garder
    # faisait retenter seize requêtes à chaque rendu, sur la minute même où
    # l'API venait de refuser. Un échec franc, lui, n'est jamais mis en cache.
    if out["ok"]:
        _API_SERIES_CACHE[key] = (_t.time(), out)
        if len(_API_SERIES_CACHE) > 40:
            _API_SERIES_CACHE.clear()
    return out


SFS_INBOX_FILE = DATA_DIR / "sfs_inbox.json"
_SFS_INBOX_CACHE: Dict[str, Any] = {}
#: LE CACHE DOIT COUVRIR L'INTERVALLE DES DEMANDEURS, sinon il ne sert a rien.
#: Le navigateur redemande l'inbox toutes les 180 s et le cache durait 120 s :
#: il etait TOUJOURS expire a l'arrivee du poll, donc chaque onglet ouvert
#: payait 16 requetes reelles toutes les trois minutes -- environ 5 par minute,
#: en permanence, sur un quota de 60. Le collecteur de fond (force=True, toutes
#: les 300 s) est le seul qui doive vraiment aller chercher ; les navigateurs
#: lisent ce qu'il a rapporte.
_SFS_INBOX_TTL = 300


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


def _premier_nombre(brut: str) -> int:
    """Le premier entier d'une case, ou 0. Pour les COMPTES, pas les montants.

    La nouvelle page ecrit « 33 (+13) » : trente-trois ventes, treize de plus
    que la periode d'avant. _parse_amount rend 0 la-dessus -- un compte faux
    qui ressemble a un compte vrai, et le seul symptome serait un tableau ou
    tout le monde a zero vente.
    """
    m = re.search(r"-?\d[\d\s.,]*", str(brut or ""))
    if not m:
        return 0
    try:
        return int(float(re.sub(r"[^\d-]", "", m.group(0)) or 0))
    except Exception:
        return 0


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
# L'EQUIPE PAR L'API — ce que le scraping faisait, en mieux
#
# /team/money rend le journal des ventes AVEC l'attribution chatteur, et
# /team/messages/stats les agregats par chatteur. C'est exactement ce que la
# page « messaging money team » affichait, et que nous lisions en grattant son
# HTML -- avec trois avantages : la devise est un champ, le type de vente est
# normalise (« ppv » / « tip » au lieu d'un libelle a interpreter), et une
# colonne ajoutee chez eux ne casse plus rien.
#
# CES ROUTES EXISTAIENT DEPUIS LE DEBUT. Elles n'avaient pas ete trouvees
# parce qu'on avait sonde « team », « transactions », « chatters » -- des
# chemins qui n'existent pas -- et que MyPuls repond 403 la ou d'autres
# repondraient 404. Un mauvais chemin ressemble donc a un refus de droits.
# Lecon : lire /api/doc avant de deduire quoi que ce soit d'un code HTTP.
#
# PAGINATION ET QUOTA. 60 requetes par minute, et une page de ventes en
# contient `per_page`. Sur quinze jours a 1392 ventes, per_page=50 demande 28
# requetes -- presque la moitie du quota d'une minute pour un seul affichage.
# On demande donc de grandes pages, et on s'arrete net a une limite de
# securite plutot que de tourner sans fin si `has_more` restait vrai.
# ---------------------------------------------------------------------------

#: Grandes pages : moins de requetes pour la meme donnee. Si l'API plafonne
#: en dessous, elle rend simplement moins d'elements et la pagination suit.
PAGE_TEAM = 500

#: Garde-fou : au-dela, on prefere une reponse incomplete ET SIGNALEE a une
#: boucle qui viderait le quota.
MAX_PAGES_TEAM = 40


def _borne_jour(v: str, fin: bool) -> str:
    """« 2026-08-31 » -> « 2026-08-31T23:59:59 » pour une fin de periode.

    UNE JOURNEE ENTIERE SE PERD SANS CA. La page de MyPuls va de 12:00 AM a
    11:59 PM ; l'API, elle, prend une date nue au debut du jour. Mesure du
    05/09/2026 sur le 16-31 aout : 1291 ventes rendues contre 1392 affichees,
    soit 101 ventes et 4 807 $ evapores -- le dernier jour, en entier. Aucune
    erreur, aucun avertissement : juste un total plus petit.

    Une valeur qui porte deja une heure est laissee telle quelle.
    """
    t = str(v or "").strip()
    if not t or "T" in t or " " in t:
        return t
    return t + ("T23:59:59" if fin else "T00:00:00")


def api_team_money(start: str, end: str, creator: str = "all",
                   chatter: str = "all", type_vente: str = "all") -> dict:
    """Toutes les ventes attribuees de la periode. Suit la pagination.

    Rend {ok, ventes:[...], pages, tronque, total_annonce} ou {ok: False}.
    `tronque` dit qu'on s'est arrete au garde-fou : le total serait faux, et
    l'appelant doit le SAVOIR plutot que de croire avoir tout lu.
    """
    ventes, page, total, tronque = [], 1, None, False
    while page <= MAX_PAGES_TEAM:
        r = api_get("team/money", {"start": _borne_jour(start, False),
                                   "end": _borne_jour(end, True),
                                   "creator": creator, "chatter": chatter,
                                   "type": type_vente,
                                   "page": page, "per_page": PAGE_TEAM})
        if not r.get("ok"):
            # Une page perdue au milieu rend le total FAUX : on le dit, on ne
            # rend pas un sous-ensemble qui ressemble a un tout.
            return {"ok": False, "error": r.get("error"),
                    "page_en_echec": page, "ventes": ventes}
        d = r.get("data") or {}
        lot = d.get("data") if isinstance(d, dict) else None
        if not isinstance(lot, list):
            return {"ok": False, "error": "Format inattendu sur team/money"}
        ventes.extend(lot)
        pg = (d.get("pagination") or {}) if isinstance(d, dict) else {}
        if total is None:
            total = pg.get("total")
        if not pg.get("has_more"):
            break
        page += 1
    else:
        tronque = True
    return {"ok": True, "ventes": ventes, "pages": page,
            "total_annonce": total, "tronque": tronque}


def api_team_messages_stats(start: str, end: str, creator: str = "all") -> dict:
    """Agregats par chatteur : messages, mots, fans, PPV proposes/vendus.

    C'est ce qui remplace « Presence / Reactivite / Propose / Vendu / Taux
    conv. », colonnes que la nouvelle page ne porte plus.
    """
    r = api_get("team/messages/stats", {"start": _borne_jour(start, False),
                                        "end": _borne_jour(end, True),
                                        "creator": creator, "chatter": "all",
                                        "type": "all"})
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    d = r.get("data") or {}
    lignes = d.get("data") if isinstance(d, dict) else None
    return {"ok": True, "par_chatteur": lignes if isinstance(lignes, list) else [],
            "non_attribues": (d or {}).get("unattributed_messages")}


def api_users() -> dict:
    """Les membres de l'equipe : relie un attributed_user_id a un nom."""
    r = api_get("users")
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    d = r.get("data") or {}
    lignes = d.get("data") if isinstance(d, dict) else (d if isinstance(d, list) else [])
    return {"ok": True, "membres": lignes if isinstance(lignes, list) else []}


def _vente_api_vers_ligne(v: dict) -> dict:
    """Une vente de l'API mise a la forme que le site attend deja.

    ON GARDE LE VOCABULAIRE DU SITE. Tout ce qui consomme fetch_team_stats
    parle de creator / chatter / fan / amount / currency / type / date : le
    traduire ici plutot que partout ailleurs evite de reecrire la moitie des
    pages -- et de casser la paie en le faisant.

    `amount` ET PAS `net`, MESURE PLUTOT QUE DEDUIT. La colonne s'appelle
    « Montant net » sur leur page, ce qui invite a prendre le champ `net` --
    c'est faux. Confrontation du 05/09/2026 sur le 16-31 aout :

        champ « net »     EUR 12 817,14   USD 16 605,80
        champ « amount »  EUR 12 817,14   USD 20 757,10
        page MyPuls       EUR 12 817,14   USD 20 757,10

    Les deux champs sont identiques sur MyM et differents de 20 % sur
    OnlyFans : `net` retire deja la commission de la plateforme. Le prendre
    ferait fondre toutes les remunerations OnlyFans d'un cinquieme, sans une
    erreur nulle part. Le site applique lui-meme ces frais plus loin (OF 20 %,
    MyM 26 %) : les retirer ici les compterait deux fois.

    `net` reste rendu a part, pour qui voudra le montant apres commission
    sans le recalculer.
    """
    try:
        montant = float(v.get("amount") or 0)
    except (TypeError, ValueError):
        montant = 0.0
    try:
        apres_frais = float(v.get("net") or 0)
    except (TypeError, ValueError):
        apres_frais = 0.0
    # Le libelle lisible, pour que categorie_transaction s'applique comme
    # avant. `kind` est normalise (ppv / tip), `type` est le libelle brut.
    kind = str(v.get("kind") or "").strip().lower()
    libelle = str(v.get("type") or "").strip()
    if not libelle:
        libelle = {"ppv": "Média privé", "tip": "Pourboires"}.get(kind, kind)
    return {
        "creator": str(v.get("creator") or ""),
        "chatter": str(v.get("attributed_user") or ""),
        "fan": str(v.get("fan") or ""),
        "amount": montant,
        "net_apres_frais": apres_frais,
        "currency": str(v.get("currency") or "EUR"),
        "type": libelle,
        "date": str(v.get("date") or ""),
        "context": "",
        # Ce que le scraping ne donnait pas, et qui sert a rapprocher.
        "payment_id": v.get("payment_id"),
        "attributed_user_id": v.get("attributed_user_id"),
    }


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

    # LA LIMITE DE DEBIT EST REELLE. Une premiere passe a une trentaine
    # d'appels d'affilee a rendu 429 sur trois endpoints -- dont les deux que
    # le tableau de bord utilise vraiment. Sonder ne doit pas degrader ce qui
    # marche : on espace, et on REESSAIE les 429 apres une pause, sinon on
    # les prendrait pour des refus.
    import time as _t

    def _appel(chemin, params):
        url = "%s/api/v1/%s" % (BASE_URL, chemin)
        return requests.get(url, headers={"X-API-TOKEN": tok,
                                          "Accept": "application/json"},
                            params=params or {}, timeout=15)

    servis, absents, autres, a_reessayer = [], [], [], []

    def _ranger(chemin, r):
        if r.status_code == 404:
            absents.append(chemin)
            return
        if r.status_code == 429:
            a_reessayer.append(chemin)
            return
        if r.status_code != 200:
            autres.append({"chemin": chemin, "code": r.status_code})
            return
        try:
            forme = _forme_reponse(r.json())
        except Exception:
            forme = {"cles": "reponse non-JSON"}
        servis.append({"chemin": chemin, **forme})

    par_chemin = dict(candidats)
    for chemin, params in candidats:
        try:
            _ranger(chemin, _appel(chemin, params))
        except Exception as e:
            autres.append({"chemin": chemin, "erreur": type(e).__name__})
        _t.sleep(0.4)

    if a_reessayer:
        _t.sleep(8)
        encore = list(a_reessayer)
        a_reessayer = []
        for chemin in encore:
            try:
                r = _appel(chemin, par_chemin.get(chemin))
                if r.status_code == 429:
                    autres.append({"chemin": chemin, "code": 429,
                                   "note": "limite de debit, deux fois"})
                else:
                    _ranger(chemin, r)
            except Exception as e:
                autres.append({"chemin": chemin, "erreur": type(e).__name__})
            _t.sleep(1.0)

    # LES DROITS DU JETON, pas ses donnees. Un 403 partout a deux lectures
    # opposees : MyPuls n'expose pas ces routes, ou ce jeton-ci n'a pas la
    # portee. `roles` tranche, et ce n'est ni un montant ni un nom.
    droits = {}
    try:
        se = api_get("session")
        if se.get("ok"):
            d = se.get("data") or {}
            d = d.get("data") if isinstance(d.get("data"), dict) else d
            droits = {
                "roles": d.get("roles"),
                "creators_count": d.get("creators_count"),
                "nb_creator_ids": len(d.get("creator_ids") or [])
                                  if isinstance(d.get("creator_ids"), list) else None,
                "authenticated": d.get("authenticated"),
            }
    except Exception:
        pass

    return {"ok": True, "createur_teste": cid or "(aucun)",
            "servis": servis, "absents": absents, "autres": autres,
            "droits_du_jeton": droits, "periode": [debut, fin]}


def limite_api() -> dict:
    """Ce que MyPuls dit de son quota, en UN seul appel.

    POURQUOI PAS UNE RAFALE. La question « combien d'appels avant 429 » se
    mesure en tapant jusqu'au refus -- et cette mesure-la degrade ce qui
    marche : la premiere passe de decouverte (30 appels) a fait tomber en 429
    les deux endpoints dont le tableau de bord depend. Les en-tetes de
    reponse portent presque toujours la meme information, gratuitement.

    LA QUESTION DERRIERE. Si le quota est compte PAR CLE, plusieurs jetons
    multiplient le debit. S'il est compte par compte, par IP ou par
    abonnement, ils ne changent rien -- et on aurait cree des comptes pour
    rien. Les en-tetes le disent parfois explicitement.

    Ne rend que des EN-TETES : aucun contenu de reponse.
    """
    if not api_configured():
        return {"ok": False, "error": "Aucun token API MyPuls"}
    try:
        r = requests.get("%s/api/v1/session" % BASE_URL,
                         headers={"X-API-TOKEN": api_token(),
                                  "Accept": "application/json"}, timeout=15)
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    interessants = {}
    for k, v in (r.headers or {}).items():
        kb = k.lower()
        if ("ratelimit" in kb or "rate-limit" in kb or kb == "retry-after"
                or kb.startswith("x-") or kb in ("server", "via")):
            interessants[k] = v[:120]
    return {"ok": True, "code": r.status_code,
            "entetes": interessants,
            "tous_les_noms": sorted((r.headers or {}).keys())}


def _team_stats_par_api(start_date: str, end_date: str) -> Dict[str, Any]:
    """Les memes renseignements que la page, depuis /team/money.

    RENDRE EXACTEMENT LA MEME FORME que le scraping n'est pas de la
    politesse : une trentaine d'endroits lisent transactions / chatters /
    totals / chart. Changer la forme ici obligerait a les reecrire tous, et
    a casser la paie en le faisant.

    CE QUI CHANGE EN MIEUX :
      - la devise est un champ, plus une colonne a deviner ;
      - le type est normalise (« ppv » / « tip »), plus un libelle a
        interpreter ;
      - les montants par famille sont exacts, calcules vente par vente au
        lieu d'etre lus dans un tableau qui ne les porte plus ;
      - « Presence / Reactivite / Propose / Vendu », disparus de leur page,
        reviennent par /team/messages/stats (messages, mots, fans distincts,
        PPV proposes / vendus).
    """
    r = api_team_money(start_date, end_date)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or "team/money indisponible"}

    transactions = [_vente_api_vers_ligne(v) for v in r.get("ventes") or []]

    # Les agregats par chatteur. Absents ? On continue : ils enrichissent,
    # ils ne conditionnent rien -- et perdre le CA parce qu'un agregat manque
    # serait un mauvais echange.
    st = api_team_messages_stats(start_date, end_date)
    par_membre = {}
    if st.get("ok"):
        for m in st.get("par_chatteur") or []:
            nom = str(m.get("user") or "").strip()
            if nom:
                par_membre[nom.lower()] = m

    try:
        from ventes_export import est_non_attribue as _est_non_attribue
    except Exception:
        def _est_non_attribue(_n):
            return False

    # UN CHATTEUR PAR NOM, monte depuis les ventes. La page en donnait un
    # tableau tout fait ; ici on le construit, ce qui a l'avantage de ne
    # jamais diverger du journal qu'on affiche a cote.
    par_nom: Dict[str, Dict[str, Any]] = {}
    ordre: List[str] = []
    for t in transactions:
        nom = (t.get("chatter") or "").strip()
        cle = nom.lower()
        c = par_nom.get(cle)
        if c is None:
            c = {"non_attribue": (not nom) or _est_non_attribue(nom),
                 "name": nom or "(non attribué)",
                 "presence": "", "reactivity": "", "proposed": 0, "sold": 0,
                 "conv_rate": "", "ca_ppv": 0.0, "ca_tips": 0.0,
                 "ca_total": 0.0, "nb_ventes": 0,
                 "nb_medias_prives": 0, "nb_pourboires": 0}
            par_nom[cle] = c
            ordre.append(cle)
        montant = float(t.get("amount") or 0)
        c["ca_total"] += montant
        c["nb_ventes"] += 1
        famille = categorie_transaction(t.get("type"))
        if famille == "Messages":
            c["ca_ppv"] += montant
            c["nb_medias_prives"] += 1
        elif famille == "Tips":
            c["ca_tips"] += montant
            c["nb_pourboires"] += 1

    for cle, c in par_nom.items():
        for champ in ("ca_total", "ca_ppv", "ca_tips"):
            c[champ] = round(c[champ], 2)
        m = par_membre.get(cle)
        if m:
            # « Propose » et « Vendu » redeviennent mesurables : ce sont les
            # PPV envoyes et ceux qui ont trouve preneur.
            c["proposed"] = int(m.get("ppv_messages") or 0)
            c["sold"] = int(m.get("ppv_sold") or 0)
            c["messages"] = int(m.get("total_messages") or 0)
            c["mots"] = int(m.get("total_words") or 0)
            c["fans"] = int(m.get("distinct_fans") or 0)
            if c["proposed"]:
                c["conv_rate"] = "%.0f%%" % (100.0 * c["sold"] / c["proposed"])

    chatters = [par_nom[k] for k in ordre]
    chatters.sort(key=lambda c: c["ca_total"], reverse=True)

    diagnostic = {
        "source": "api",
        "ventes_lues": len(transactions),
        "total_annonce": r.get("total_annonce"),
        "pages": r.get("pages"),
        # Une reponse tronquee rend un total FAUX : il faut que ca se voie.
        "tronque": r.get("tronque"),
        "lignes_illisibles": 0, "montants_illisibles": 0,
        "chatters_illisibles": 0,
        "agregats_chatteurs": st.get("ok"),
        "agregats_erreur": st.get("error"),
        "ventes_sans_chatteur": sum(1 for t in transactions
                                    if not (t.get("chatter") or "").strip()),
        "montant_sans_chatteur": round(
            sum(float(t.get("amount") or 0) for t in transactions
                if not (t.get("chatter") or "").strip()), 2),
    }
    return _assembler_stats(transactions, chatters, start_date, end_date,
                            diagnostic)


# ============ Fetch + parse ============

def _assembler_stats(transactions, chatters, start_date, end_date,
                     diagnostic):
    """Les totaux, la ventilation par devise et le graphique.

    LES DEUX CHEMINS PASSENT ICI. L'API et le scraping produisent les
    memes deux listes ; tout le reste -- split par devise, familles de
    vente, series par jour -- est identique. Le laisser en double
    garantirait qu'une correction n'aille que d'un cote, et c'est de
    l'argent.
    """
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
    return result


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

    # ── L'API D'ABORD ────────────────────────────────────────────────────
    #
    # /team/money rend le meme journal que la page, mais en JSON : la devise
    # est un champ, le type est normalise, et une colonne ajoutee chez eux ne
    # casse plus rien. Le scraping reste dessous, en repli -- il a fallu deux
    # pannes silencieuses pour comprendre qu'une page tierce ne se lit pas
    # par position, et rien ne garantit que l'API soit toujours joignable.
    #
    # LE REPLI EST DIT, jamais devine : le diagnostic porte la source, sinon
    # on ne saurait pas d'ou vient le chiffre qu'on regarde.
    if api_configured():
        _api = _team_stats_par_api(start_date, end_date)
        if _api.get("ok"):
            _STATS_CACHE[cache_key] = {"ts": int(_t.time()), "data": _api}
            return _api
        _err_api = _api.get("error") or "API indisponible"
    else:
        _err_api = "aucun token API"

    s = _make_session()
    if s is None:
        return _fail_ts("Pas de token API (%s) et pas de cookies MyPuls" % _err_api)

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
    i_log = _table_par_entetes(tables, *_COLS_LOG)

    # LES TABLEAUX PAR CHATTEUR : ceux qui portent un chatteur ET un montant,
    # mais PAS de colonne « Fan » (sinon on prendrait le log lui-meme).
    #
    # Il y en a PLUSIEURS : depuis la refonte, MyPuls sort un tableau PAR
    # DEVISE (« EUR · 34 chatteurs classes », puis un bloc USD). C'est une
    # bonne nouvelle -- l'ancienne colonne « CA Total » empilait les euros MyM
    # et les dollars OnlyFans, ce que ce fichier signalait deja comme un
    # montant « dans aucune devise ». On les lit tous.
    #
    # Un tableau vide est ECARTE : la page garde la coquille de l'ancien
    # tableau de performance (huit en-tetes, une seule colonne, aucune
    # donnee). La prendre pour la source ferait tout tomber a zero.
    i_perfs = [i for i, (ent, lig) in enumerate(tables)
               if i != i_log
               and _colonne(ent, "chatter", "chatteur") >= 0
               and _colonne(ent, "montant net", "ca total", "montant") >= 0
               and _largeur(lig) >= 3]
    entetes_manquants = (i_log < 0 or not i_perfs)
    if i_log < 0:
        i_log = 0
    if not i_perfs:
        i_perfs = [1] if len(tables) > 1 else [0]
    i_perf = i_perfs[0]

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

    # LES CHATTEURS, DEUX FORMES POSSIBLES.
    #
    # Nouvelle (05/09/2026) : « # | Chatter | Ventes | Medias prives |
    # Pourboires | Montant net | Periode prec. | Evolution | Rang », un
    # tableau par devise.
    # Ancienne : « Chatter | Presence | Reactivite | Propose | Vendu |
    # Taux conv. | CA PPV | CA Tips | CA Total ».
    #
    # ATTENTION AU CHANGEMENT DE NATURE. Dans la nouvelle, « Medias prives »
    # et « Pourboires » sont des COMPTES (12 medias, 21 pourboires), pas des
    # euros. Les brancher sur ca_ppv / ca_tips afficherait « 21 € » pour 21
    # pourboires : un chiffre faux qui a l'air vrai. Les montants par famille
    # sont donc recalcules depuis le LOG, qui porte le type de chaque vente.
    chatters: List[Dict[str, Any]] = []
    chatters_illisibles = 0
    colonnes_perf_manquantes: List[str] = []
    _par_nom: Dict[str, Dict[str, Any]] = {}
    _ordre: List[str] = []

    for _ip in i_perfs:
        e_perf, l_perf = tables[_ip][0], tables[_ip][1]
        largeur = _largeur(l_perf)
        p_name = _colonne(e_perf, "chatter", "chatteur", "user", "utilisateur")
        p_tot = _colonne(e_perf, "montant net", "ca total")
        p_nb_ventes = _colonne(e_perf, "ventes", "sales")
        p_nb_ppv = _colonne(e_perf, "medias prives", "media prive", "ppv")
        p_nb_tips = _colonne(e_perf, "pourboires", "tips")
        # Les colonnes de l'ANCIENNE forme : absentes de la nouvelle, et ce
        # n'est pas une anomalie -- elles valent alors vide, jamais un chiffre
        # invente.
        p_pres = _colonne(e_perf, "presence")
        p_reac = _colonne(e_perf, "reactivite", "reactivity")
        p_prop = _colonne(e_perf, "propose", "proposed")
        p_vend = _colonne(e_perf, "vendu", "sold")
        p_conv = _colonne(e_perf, "taux conv", "conversion")
        p_ppv_eur = _colonne(e_perf, "ca ppv")
        p_tips_eur = _colonne(e_perf, "ca tips")
        if largeur:
            (p_name, p_tot, p_nb_ventes, p_nb_ppv, p_nb_tips, p_pres, p_reac,
             p_prop, p_vend, p_conv, p_ppv_eur, p_tips_eur) = [
                (x if x < largeur else -1) for x in
                (p_name, p_tot, p_nb_ventes, p_nb_ppv, p_nb_tips, p_pres,
                 p_reac, p_prop, p_vend, p_conv, p_ppv_eur, p_tips_eur)]
        for nom, idx in (("chatteur", p_name), ("montant net", p_tot)):
            if idx < 0 and nom not in colonnes_perf_manquantes:
                colonnes_perf_manquantes.append(nom)
        if p_name < 0 or p_tot < 0:
            continue                        # ce tableau ne dit rien d'utile

        for row in l_perf:
            if len(row) <= max(p_name, p_tot):
                if any((c or "").strip() for c in row):
                    chatters_illisibles += 1
                continue
            nom = _cellule(row, p_name).strip()
            if not nom:
                continue
            cle = nom.lower()
            c = _par_nom.get(cle)
            if c is None:
                # « Indetermine (Creatrice) » n'est pas quelqu'un : MyPuls met
                # ce libelle quand la vente n'est rattachee a aucun chatteur.
                # On le MARQUE sans le retirer — l'argent a bien ete encaisse,
                # il doit rester dans le CA ; c'est la PART A PAYER qui doit
                # l'ignorer.
                c = {"non_attribue": _est_non_attribue(nom), "name": nom,
                     "presence": "", "reactivity": "", "proposed": 0,
                     "sold": 0, "conv_rate": "",
                     "ca_ppv": 0.0, "ca_tips": 0.0, "ca_total": 0.0,
                     "nb_ventes": 0, "nb_medias_prives": 0, "nb_pourboires": 0}
                _par_nom[cle] = c
                _ordre.append(cle)
            # Le montant s'ADDITIONNE entre les tableaux de devise : la
            # ventilation propre vient de ca_eur / ca_usd, poses plus bas
            # depuis le log.
            c["ca_total"] += _parse_amount(_cellule(row, p_tot))
            for champ, idx in (("nb_ventes", p_nb_ventes),
                               ("nb_medias_prives", p_nb_ppv),
                               ("nb_pourboires", p_nb_tips)):
                if idx >= 0:
                    c[champ] += _premier_nombre(_cellule(row, idx))
            for champ, idx in (("presence", p_pres), ("reactivity", p_reac),
                               ("conv_rate", p_conv)):
                if idx >= 0 and not c[champ]:
                    c[champ] = _cellule(row, idx)
            for champ, idx in (("proposed", p_prop), ("sold", p_vend)):
                if idx >= 0:
                    c[champ] += _parse_amount(_cellule(row, idx)) or 0
            # Ancienne forme : les montants par famille etaient donnes.
            if p_ppv_eur >= 0:
                c["ca_ppv"] += _parse_amount(_cellule(row, p_ppv_eur))
            if p_tips_eur >= 0:
                c["ca_tips"] += _parse_amount(_cellule(row, p_tips_eur))

    chatters = [_par_nom[k] for k in _ordre]

    # LES MONTANTS PAR FAMILLE VIENNENT DU LOG quand la page ne les donne
    # plus. Le log porte le type de chaque vente (« Media prive »,
    # « Pourboires »...) et categorie_transaction sait le classer -- c'est la
    # meme regle que partout ailleurs, pas une seconde definition.
    if not any(c["ca_ppv"] or c["ca_tips"] for c in chatters):
        _fam: Dict[str, Dict[str, float]] = {}
        for t in transactions:
            cle = (t.get("chatter") or "").strip().lower()
            if not cle:
                continue
            f = categorie_transaction(t.get("type"))
            d = _fam.setdefault(cle, {"Messages": 0.0, "Tips": 0.0})
            if f in d:
                d[f] += float(t.get("amount") or 0)
        for c in chatters:
            d = _fam.get((c["name"] or "").strip().lower())
            if d:
                c["ca_ppv"] = round(d["Messages"], 2)
                c["ca_tips"] = round(d["Tips"], 2)


    # Ce que la lecture a laisse de cote : sans ca, un ecart entre le CA
    # affiche et la somme des ventes n'a aucune explication consultable.
    _sans_nom = [t for t in transactions if not (t.get("chatter") or "").strip()]
    diagnostic = {
        # CE QUE MYPULS A ENVOYE, mot pour mot. C'est ce qui manquait le
        # 05/09 : le CA etait a zero et rien ne permettait de voir que les
        # colonnes avaient bouge. Une capture d'ecran de moins a demander.
        # D'OU VIENT LE CHIFFRE. Deux chemins mènent ici, l'API et le
        # scraping ; sans ce mot, on ne sait pas lequel a parlé.
        "source": "scraping",
        "entetes_log": list(tables[i_log][0] or []),
        "entetes_perf": list(tables[i_perf][0] or []),
        # Un tableau par devise depuis la refonte : on dit combien on en a
        # lu, sinon « 34 chatteurs classes » cote MyPuls et 34 chez nous
        # peuvent cacher un bloc USD entier laisse de cote.
        "tables_chatteurs": list(i_perfs),
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

    _res = _assembler_stats(transactions, chatters, start_date, end_date,
                            diagnostic)
    # Mettre en cache pour accélérer les prochains chargements
    _STATS_CACHE[cache_key] = {"ts": int(_t.time()), "data": _res}
    return _res


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
