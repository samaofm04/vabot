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
import safe_json

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR / "gms_config.json"
MCP_URL = "https://mcp.getmysocial.com/mcp"
TIMEOUT = 60
READ_TIMEOUT = 12  # lectures (list/get/analytics) : ne pas figer la page 60s sur un blocage


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
    safe_json.write_text(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))


def save_api_key(key: str):
    cfg = load_config()
    cfg["api_key"] = key.strip()
    save_config(cfg)


def get_api_key() -> str:
    return load_config().get("api_key", "")


def save_dash_key(key: str):
    """Clé API DÉDIÉE au dashboard clics (quota séparé du report/paie)."""
    cfg = load_config()
    cfg["api_key_dash"] = (key or "").strip()
    save_config(cfg)


def get_dash_key() -> str:
    """1re clé dédiée (rétro-compat use_key(get_dash_key()))."""
    ks = get_dash_keys()
    return ks[0] if ks else ""


def get_dash_keys() -> list:
    """TOUTES les clés dédiées au dashboard (séparées par virgule/espace/retour
    à la ligne). Le quota GMS est PAR CLÉ -> N clés = N voies en parallèle."""
    raw = load_config().get("api_key_dash", "") or ""
    out = []
    for part in re.split(r"[\s,;]+", raw):
        part = part.strip()
        if part.startswith("gms_") and part not in out:
            out.append(part)
    return out


_DASH_RR = [0]


def next_dash_key() -> str:
    """Clé dédiée suivante (round-robin sur le POOL) : chaque appel du dashboard
    part sur une voie différente -> N clés = ~N fois plus vite. '' si aucun pool
    (use_key('') est un no-op -> clé principale)."""
    ks = [k for k in get_dash_keys() if not cle_ecartee(k)]
    if not ks:
        # TOUTES ecartees (ou aucune configuree) : on retombe sur la cle
        # principale plutot que d'insister sur des voies mortes. C'est ce
        # repli qui manquait : sans lui, un pool hors service emportait la
        # totalite des clics par lien.
        #
        # Mais un repli MUET serait le meme travers d'un cran plus loin : le
        # trafic du dashboard part alors sur la cle du report et de la PAIE,
        # et le soir la paie prend des 429 sans que rien n'explique pourquoi.
        # On le compte. Sans pool configure, en revanche, il n'y a rien a
        # signaler : c'est le fonctionnement normal.
        if get_dash_keys():
            with _SANTE_LOCK:
                _REPLIS["n"] += 1
                _REPLIS["quand"] = time.time()
        return ""
    with _GMS_GATE_LOCK:
        i = _DASH_RR[0]
        _DASH_RR[0] = (i + 1) % len(ks)
    return ks[i % len(ks)]


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
    data = _parse_sse(r.content.decode("utf-8", "replace"))
    tools = ((data or {}).get("result") or {}).get("tools") or []
    return {"ok": True, "tools": [{"name": t.get("name"), "desc": (t.get("description") or "")[:80]} for t in tools]}


import threading as _threading
from collections import deque as _deque
_MCP_LOCK = _threading.Lock()
_MCP_CACHE: Dict[str, Any] = {}          # api_key -> session MCP (multi-clés)
_READ_TOOLS = {"list_links", "get_analytics_overview", "get_time_series", "_ping"}
_KEY_LOCAL = _threading.local()


class use_key:
    """Contexte : les appels GMS de ce thread utilisent CETTE clé API.
    use_key(None) = no-op (clé principale). Sert à donner au dashboard sa clé
    dédiée -> quota séparé du report horaire / de la paie."""

    def __init__(self, key):
        self.key = (key or "").strip() or None

    def __enter__(self):
        self.prev = getattr(_KEY_LOCAL, "key", None)
        if self.key:
            _KEY_LOCAL.key = self.key
        return self

    def __exit__(self, *exc):
        _KEY_LOCAL.key = self.prev
        return False


def _effective_key() -> str:
    return getattr(_KEY_LOCAL, "key", None) or get_api_key()


def _get_session() -> Optional[requests.Session]:
    """Session MCP initialisée et RÉUTILISÉE entre les appels, PAR CLÉ API."""
    api_key = _effective_key()
    if not api_key:
        return None
    with _MCP_LOCK:
        s = _MCP_CACHE.get(api_key)
        if s is not None:
            return s
        s = _make_session(api_key)
        if not _initialize(s):
            _MCP_CACHE.pop(api_key, None)
            return None
        _MCP_CACHE[api_key] = s
        return s


def _reset_session():
    with _MCP_LOCK:
        _MCP_CACHE.pop(_effective_key(), None)


# ---- Limiteur d'appels GetMySocial ----
# GMS renvoie des HTTP 429 quand on tape trop vite (mesuré : ~2,5 req/s passe,
# 8 threads en rafale = 429 en masse). Fenêtre glissante partagée par tous les
# threads + backoff sur 429, pour que le dashboard clics (1 appel par lien) et
# les reports ne se fassent plus jeter.
# Le freinage est ADAPTATIF : par défaut on ne ralentit RIEN (sinon les pages du
# dashboard, qui font des dizaines d'appels GMS, mettent des minutes à s'afficher).
# On n'espace les appels que dans 2 cas : (1) un 429 vient d'être reçu -> on
# temporise le temps que ça retombe ; (2) un traitement en LOT s'est déclaré via
# bulk_mode() (dashboard clics), qui doit rester poli avec l'API.
_GMS_RPS = 1.5                      # requêtes/seconde quand on freine
_GMS_GATE_LOCK = _threading.Lock()
_GMS_LAST: Dict[str, float] = {}            # PAR CLÉ : dernier appel (le quota GMS est par clé)
_GMS_THROTTLE_UNTIL: Dict[str, float] = {}  # PAR CLÉ : fin de pénalité après un 429
_GMS_BULK = [0]                     # nb de traitements en lot en cours


class bulk_mode:
    """Contexte : « je vais faire des centaines d'appels, freine-moi »."""

    def __enter__(self):
        with _GMS_GATE_LOCK:
            _GMS_BULK[0] += 1
        return self

    def __exit__(self, *exc):
        with _GMS_GATE_LOCK:
            _GMS_BULK[0] = max(0, _GMS_BULK[0] - 1)
        return False


def _gms_note_429():
    """Un 429 est tombé -> on freine CETTE clé pendant 120 s (les autres voies continuent)."""
    with _GMS_GATE_LOCK:
        _GMS_THROTTLE_UNTIL[_effective_key()] = time.time() + 120.0


# ---- Instrumentation : QUI consomme l'API GMS ----
# Chaque appel est journalisé (horodatage, étiquette du consommateur, statut HTTP).
# api_usage() agrège sur les N dernières minutes -> affiché dans le dashboard quand
# ça 429, pour identifier le consommateur qui sature l'IP du VPS.
_API_LOCAL = _threading.local()
_API_LOG = _deque(maxlen=4000)


class api_tag:
    """Contexte : étiquette les appels GMS faits dans ce thread (ex: 'report')."""

    def __init__(self, tag):
        self.tag = tag

    def __enter__(self):
        self.prev = getattr(_API_LOCAL, "tag", None)
        _API_LOCAL.tag = self.tag
        return self

    def __exit__(self, *exc):
        _API_LOCAL.tag = self.prev
        return False


# ---- Le budget du jour : ce qui empeche de vider la quota --------------
#
# CORRIGE LE 06/10/2026 : la quota n'est PAS commune aux cles. La doc de
# l'API v3 (getmysocial.com/docs) : « Per-API-key, per-tier, rolling window »,
# 10 000 lectures par jour et par cle, les ecritures a part. Le releve de la
# semaine du 29/09 le confirme : la cle principale a ~10 250 appels par jour
# (au-dessus de 10 000), les quatre cles « dash » a ~1 860 chacune. Ce budget
# est donc celui de la cle PRINCIPALE, celle de la paie ; les autres cles
# prennent le relais (_choisir_cle) au lieu d'attendre avec elle.
#
# Ce qu'on en avait cru d'abord, une quota commune aux quatre cles, vient du
# 03/10/2026 : elle est tombee a zero, et le
# podium, qui paie, n'a plus rien pu relever de la soiree, pendant qu'un demon
# de prechauffage continuait a servir un tableau que personne ne regardait.
#
# On compte donc NOS appels, par heure, SUR DISQUE (le bot redemarre a chaque
# deploiement). Et on apprend le plafond : le jour ou l'API dit « today: 0 »,
# le nombre d'appels des 24 dernieres heures EST le plafond. Tant qu'on ne l'a
# jamais vu, on ne refuse rien -- on ne devine pas un budget.
#
# La fenetre est GLISSANTE, pas « depuis minuit » : le refus du 03/10 disait
# « retry after 7836s » a 05h18, donc la remise a zero de GetMySocial tombe
# vers 07h28, pas a minuit. Compter par jour calendaire aurait decale le
# plafond appris d'un tiers de journee.
_BUDGET_FICHIER = Path(__file__).resolve().parent / "data" / "gms_budget.json"
_BUDGET = {"heures": {}, "plafond": None, "lu": False, "ecrit": 0.0, "depuis": None}
_BUDGET_LOCK = _threading.Lock()
#: Les appels de CHAQUE cle par heure, en memoire : de quoi voir la charge se
#: repartir (etat_quota). Seule la principale a un budget sur disque.
_APPELS_CLE: Dict[str, Dict[str, int]] = {}

#: Ce que vaut chaque etiquette d'appel quand le budget baisse. Les etiquettes
#: sont celles d'api_tag, deja posees dans le depot.
PRIORITES = {
    "podium": "paie", "paie": "paie", "prime": "paie", "report": "paie",
    "dashboard": "fond", "widget-vas": "fond", "warm": "fond",
    # l'entretien du salon des bases US (compteur, groupe TEMPLATES) :
    # cosmetique, personne n'attend -- bases_identite_us.ETIQUETTE_FOND
    "bases-us-fond": "fond",
}
#: EN DESSOUS, ON NE CROIT PAS CE QU ON MESURE. Notre compteur ne vaut que
#: s'il a tourne toute la fenetre. Au premier demarrage — ou apres une remise a
#: zero — il part de zero alors que la journee de GetMySocial est peut-etre
#: deja consommee : un refus « today: 0 » arrive alors qu'on n'a compte que
#: cinq appels, et on apprendrait un plafond de cinq. C'est arrive en
#: production le 04/10/2026, et ca a bloque le podium (reste = -4, tout
#: refuse). Sous ce seuil, un refus est signale et JETE.
PLAFOND_MINI = 1000
#: Les reserves sont des PARTS du plafond, pas des nombres fixes : un plafond
#: de 1 200 avec une reserve fixe de 6 000 aurait tout refuse d'entree.
PART_PAIE = 0.15        # les 15 derniers pour cent n'appartiennent qu'a la paie
PART_FOND = 0.40        # le travail de fond s'efface bien avant


def _heure_cle(t=None) -> str:
    return time.strftime("%Y-%m-%dT%H", time.localtime(t or time.time()))


def _budget_charger() -> None:
    if _BUDGET["lu"]:
        return
    _BUDGET["lu"] = True
    # le compteur part de maintenant, sauf s'il est relu plus bas : tant qu'il
    # ne couvre pas vingt-quatre heures, il ne sait pas ce que GetMySocial a
    # deja compte (_budget_noter_plafond)
    _BUDGET["depuis"] = time.time()
    try:
        d = json.loads(_BUDGET_FICHIER.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return
    if not isinstance(d, dict):
        return
    if d.get("version") != 2:
        # avant le 06/10/2026, toutes les cles comptaient ensemble (~17 000 par
        # jour) : relues comme celles de la principale, elles lui auraient
        # appris un plafond de 17 000 pour une limite de 10 000
        return
    try:
        _BUDGET["depuis"] = float(d.get("depuis") or _BUDGET["depuis"])
    except (TypeError, ValueError):
        pass
    h = d.get("heures")
    if isinstance(h, dict):
        _BUDGET["heures"] = {str(k): int(v or 0) for k, v in h.items()
                             if str(k)[:4].isdigit()}
    p = d.get("plafond")
    if isinstance(p, int) and p > 0:
        _BUDGET["plafond"] = p


def _budget_ecrire(force: bool = False) -> None:
    """Au plus une ecriture par minute : ce compteur bouge a chaque appel."""
    t = time.time()
    if not force and t - float(_BUDGET["ecrit"]) < 60:
        return
    _BUDGET["ecrit"] = t
    try:
        safe_json.write(_BUDGET_FICHIER, {"version": 2, "depuis": _BUDGET.get("depuis"),
                                          "heures": _BUDGET["heures"],
                                          "plafond": _BUDGET["plafond"]})
    except Exception:                                        # noqa: BLE001
        pass          # compter est un confort : ca ne doit jamais casser un appel


def appels_24h() -> int:
    """Nos appels des vingt-quatre dernieres heures (fenetre glissante), sur
    la cle principale."""
    with _BUDGET_LOCK:
        _budget_charger()
        cles = {_heure_cle(time.time() - i * 3600) for i in range(24)}
        return sum(v for k, v in _BUDGET["heures"].items() if k in cles)


def budget() -> dict:
    """De quoi l'AFFICHER et le comprendre : consomme, plafond, reste."""
    with _BUDGET_LOCK:
        _budget_charger()
        plafond = _BUDGET["plafond"]
    # un plafond deja ecrit sous le seuil (version d'avant ce garde-fou) est
    # ignore plutot que de bloquer la paie
    if plafond and int(plafond) < PLAFOND_MINI:
        plafond = None
    faits = appels_24h()
    return {"appels_24h": faits, "plafond": plafond,
            "reste": (plafond - faits) if plafond else None,
            "reserve_paie": int(plafond * PART_PAIE) if plafond else None,
            "reserve_fond": int(plafond * PART_FOND) if plafond else None}


def _budget_noter_plafond(faits: int) -> None:
    """« today: 0 » : ce qu'on avait consomme EST le plafond — si on y croit.

    On n'apprend rien d'un compteur qui ne couvre pas la journee de
    GetMySocial (voir PLAFOND_MINI) : mieux vaut aucun plafond qu'un plafond
    de cinq, qui refuserait tout, podium compris.
    """
    if faits < PLAFOND_MINI:
        print(f"[gms] refus « today: 0 » apres seulement {faits} appel(s) comptes "
              f"(moins de {PLAFOND_MINI}) : notre compteur ne couvre pas la "
              "journee de GetMySocial, plafond NON appris", flush=True)
        return
    depuis = _BUDGET.get("depuis")
    if depuis and time.time() - float(depuis) < 86400:
        # Un compteur neuf (deploiement du 06/10/2026, fichier d'avant ecarte)
        # ignore ce que GetMySocial avait deja compte : 6 000 appels vus
        # seraient devenus un plafond, garde pour toujours (on garde le plus
        # bas). Il n'apprend qu'une fois sa fenetre entiere couverte.
        print(f"[gms] refus « today: 0 » a {faits} appels comptes, mais le compteur "
              f"n'a que {int((time.time() - float(depuis)) // 3600)} h : plafond NON appris",
              flush=True)
        return
    with _BUDGET_LOCK:
        _budget_charger()
        avant = _BUDGET["plafond"]
        _BUDGET["plafond"] = faits if not avant else min(int(avant), faits)
        change = _BUDGET["plafond"] != avant
        _budget_ecrire(force=True)
    if change:
        print(f"[gms] plafond journalier appris : {_BUDGET['plafond']} appels "
              "(mesure sur un refus « today: 0 »)", flush=True)


_BUDGET_DIT = [0.0]


def _budget_dire_refus() -> None:
    t = time.time()
    if t - _BUDGET_DIT[0] < 60:
        return
    _BUDGET_DIT[0] = t
    b = budget()
    print(f"[gms] budget du jour : {b['appels_24h']}/{b['plafond']} appels, "
          f"il reste {b['reste']} — les appels non prioritaires attendent "
          f"(etiquette « {getattr(_API_LOCAL, 'tag', None) or 'autres'} »)", flush=True)


def budget_ok(tag: Optional[str] = None) -> bool:
    """Cet appel a-t-il encore le droit de partir ?

    Sans plafond connu, OUI : on ne refuse jamais sur une supposition. Sinon,
    chacun garde sa reserve -- la paie passe tant qu'il reste un appel, le
    travail de fond s'efface bien avant.
    """
    b = budget()
    if not b["plafond"]:
        return True
    reste = b["reste"]
    rang = PRIORITES.get(str(tag or getattr(_API_LOCAL, "tag", None) or "autres"), "normal")
    if rang == "paie":
        return reste > 0
    if rang == "fond":
        return reste > b["reserve_fond"]
    return reste > b["reserve_paie"]


def _api_note(status, genre: str = "lecture"):
    cle = _effective_key()
    try:
        _API_LOG.append((time.time(), getattr(_API_LOCAL, "tag", None) or "autres", int(status or 0)))
    except Exception:
        pass
    try:
        with _BUDGET_LOCK:
            h = _APPELS_CLE.setdefault(cle, {})
            k = _heure_cle()
            h[k] = h.get(k, 0) + 1
            for vieux in sorted(h)[:-25]:
                h.pop(vieux, None)
    except Exception:
        pass
    if cle != get_api_key() or genre != "lecture":
        # le budget est celui des LECTURES de la principale (voir plus haut) :
        # les ecritures ont leurs paniers a elles chez GetMySocial
        return
    try:
        with _BUDGET_LOCK:
            _budget_charger()
            k = _heure_cle()
            _BUDGET["heures"][k] = int(_BUDGET["heures"].get(k, 0)) + 1
            # on ne garde que trente heures : de quoi couvrir la fenetre
            # glissante, pas l'historique du mois
            if len(_BUDGET["heures"]) > 40:
                for vieux in sorted(_BUDGET["heures"])[:-30]:
                    _BUDGET["heures"].pop(vieux, None)
            _budget_ecrire()
    except Exception:
        pass


def api_usage(minutes: int = 10) -> dict:
    cut = time.time() - minutes * 60
    by, by429 = {}, {}
    for ts, tag, st in list(_API_LOG):
        if ts < cut:
            continue
        by[tag] = by.get(tag, 0) + 1
        if st == 429:
            by429[tag] = by429.get(tag, 0) + 1
    return {"minutes": minutes, "total": sum(by.values()), "by": by,
            "e429": sum(by429.values()), "e429_by": by429}


def _gms_is_bulk() -> bool:
    with _GMS_GATE_LOCK:
        return _GMS_BULK[0] > 0


def _gms_gate():
    """Freine UNIQUEMENT les traitements en lot (bulk_mode).

    Les appels des pages web ne sont JAMAIS retenus ici : freiner tout le monde
    après un 429 occupait les threads du serveur web en attentes de plusieurs
    minutes -> plus AUCUNE page ne répondait (Cloudflare 524, site down)."""
    if not _gms_is_bulk():
        return
    k = _effective_key()
    while True:
        with _GMS_GATE_LOCK:
            now = time.time()
            throttled = now < _GMS_THROTTLE_UNTIL.get(k, 0.0)
            gap = (1.0 / max(0.5, _GMS_RPS)) if throttled else 0.5    # 1,5/s freiné, 2/s sinon
            wait = _GMS_LAST.get(k, 0.0) + gap - now
            if wait <= 0:
                _GMS_LAST[k] = now
                return
        time.sleep(min(wait, 2.0))


def _call_tool_brut(tool_name: str, args: Optional[dict] = None,
                    _retry: bool = True, _429: int = 0) -> Dict[str, Any]:
    """Appelle un outil MCP. Retourne {'ok': bool, 'data': ..., 'error': ...}.
    Réutilise une session MCP cachée ; si elle a expiré (réseau / 4xx), on la
    recrée et on réessaie UNE fois."""
    if not get_api_key():
        return {"ok": False, "error": "Clé API GetMySocial non configurée"}
    # La cle et le budget sont choisis par _call_tool (_choisir_cle) : la
    # principale garde sa journee pour la paie, une cle en pause passe la main.
    genre = genre_outil(tool_name)
    _reste = pause_cle(_effective_key(), genre)
    if _reste > 0:
        # « Do not retry before then » : on n'ouvre meme pas la connexion.
        # Continuer a cogner sur une porte fermee a fait exactement ca toute
        # la journee - chaque ouverture de la page relancait quatre-vingt-douze
        # appels, tous refuses, qui ne faisaient qu'entretenir le refus.
        return {"ok": False,
                "error": "Quota GetMySocial epuise — reprise vers %s (%d min)"
                         % (heure_paris(time.time() + _reste), _reste // 60)}
    s = _get_session()
    if s is None:
        return {"ok": False, "error": "Impossible d'initialiser la session MCP"}
    body = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 1_000_000,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args or {}},
    }
    _to = READ_TIMEOUT if tool_name in _READ_TOOLS else TIMEOUT
    _gms_gate()
    try:
        r = s.post(MCP_URL, json=body, timeout=_to)
        _api_note(r.status_code, genre)
    except Exception as e:
        _api_note(0, genre)
        if _retry:  # session peut-être morte -> on la recrée et on réessaie
            _reset_session()
            return _call_tool_brut(tool_name, args, _retry=False, _429=_429)
        return {"ok": False, "error": f"Erreur réseau : {e}"}
    if r.status_code == 429:
        # Rate-limit GMS. En LOT : backoff patient (le chiffre doit finir juste).
        # Depuis une PAGE : 1 seul retry court — une page qui attend 30 s par appel
        # gèle un thread du serveur web (cause du 524 « site down »).
        _gms_note_429()
        _noter_refus(r.text or "", _effective_key(), genre)
        if pause_cle(_effective_key(), genre) > 0:
            # Budget du jour de CETTE cle epuise : ni sommeil, ni reprise ici.
            # _call_tool passe a une autre cle libre, s'il y en a une.
            return {"ok": False, "error": (r.text or "")[:300]}
        _max, _sleeps = (3, (2.0, 5.0, 9.0)) if _gms_is_bulk() else (1, (1.0,))
        if _429 < _max:
            time.sleep(_sleeps[_429])
            return _call_tool_brut(tool_name, args, _retry=_retry, _429=_429 + 1)
        return {"ok": False, "error": "HTTP 429 (rate-limit GetMySocial)"}
    if r.status_code in (400, 401, 404) and _retry:
        # session MCP probablement expirée -> on la recrée et on réessaie 1×
        _reset_session()
        return _call_tool_brut(tool_name, args, _retry=False, _429=_429)
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code} : {r.text[:300]}"}
    # UTF-8, toujours : le flux SSE arrive sans « charset », requests suppose
    # du latin-1 et chaque emoji / accent revenait casse (« profite enð\x9f\x99\x84 »).
    # Relire puis renvoyer des boutons ainsi aurait abime les pages (03/10/2026).
    data = _parse_sse(r.content.decode("utf-8", "replace"))
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
            # un outil renomme chez GetMySocial : sans ca, « Unknown tool:
            # delete_link » passait pour une suppression reussie
            if stripped.lower().startswith("unknown tool"):
                return {"ok": False, "error": f"{stripped[:200]} (outil absent chez GetMySocial)"}
        return {"ok": True, "data": payload}
    return {"ok": True, "data": result}


# ============ Wrappers haut-niveau ============

# ============ Sante des cles ============
#
# Constate en production : une cle dediee du pool ne repondait plus, et comme
# `use_key` n'a aucun repli, TOUS les appels du report partaient dessus et
# echouaient. `analytics_for_link` transformait chaque echec en (None, None),
# et le tableau se remplissait de « — » — exactement ce que produirait un
# lien sur lequel personne n'a clique. Deux jours durant, personne n'a pu
# faire la difference.
#
# Une cle qui echoue en SERIE sort donc de la rotation, et ce qui s'est passe
# reste lisible.

_re_quota = re.compile(r"retry after (\d+)\s*s", re.I)
_re_jour = re.compile(r"today:\s*(\d+)", re.I)

_SANTE = {}                      # cle -> {"echecs", "jusqu", "dernier", "quand"}
_SANTE_LOCK = _threading.Lock()
SEUIL_ECHECS = 3                 # echecs CONSECUTIFS avant mise a l'ecart
DUREE_ECART = 600                # secondes : on retente au bout de 10 min


def _masque(cle: str) -> str:
    cle = str(cle or "")
    return (cle[:12] + "…" + cle[-4:]) if len(cle) > 18 else (cle[:6] + "…")


def noter_cle(cle: str, ok: bool, message: str = "") -> None:
    """Un succes efface l'ardoise ; trois echecs de suite mettent la cle a
    l'ecart. CONSECUTIFS et pas cumules : une cle saine qui prend un 429
    isole ne doit pas etre condamnee pour autant."""
    cle = str(cle or "")
    if not cle:
        return
    with _SANTE_LOCK:
        e = _SANTE.setdefault(cle, {"echecs": 0, "jusqu": 0.0,
                                    "dernier": "", "quand": 0.0})
        if ok:
            e["echecs"] = 0
            e["jusqu"] = 0.0
            return
        e["echecs"] += 1
        e["dernier"] = str(message or "")[:200]
        e["quand"] = time.time()
        if e["echecs"] >= SEUIL_ECHECS:
            e["jusqu"] = time.time() + DUREE_ECART


_REPLIS = {"n": 0, "quand": 0.0}    # dashboard reparti sur la cle de paie

# ============ Le quota JOURNALIER ============
#
# On a longtemps cru a une limite par minute, et toute l'architecture est
# batie la-dessus : rotation de cles, semaphores, backoff court. Le message
# de refus dit autre chose, en toutes lettres :
#
#   Error 429 (rate_limit_exceeded): RATE_LIMITED: retry after 25794s.
#   Do not retry before then. Requests remaining this minute: 117, today: 0.
#
# Cent dix-sept requetes disponibles cette minute-la, et ZERO pour la
# journee. Ce n'est pas un pic a lisser, c'est un budget epuise pour sept
# heures. Reessayer ne fait que garder la porte fermee : on obeit.
#
# PAR CLE, ET PAR GENRE D'APPEL (06/10/2026). La pause etait unique : la cle
# principale, a 10 250 appels pour une limite de 10 000, fermait chaque matin
# les quatre autres avec elle, qui avaient encore ~8 000 lectures chacune.
# Et un refus de LECTURE fermait aussi les ECRITURES, que GetMySocial compte a
# part : a 8h06, « Generer le lien » d'un VA Lola a echoue pour rien.
_PAUSES: Dict[Any, Dict[str, Any]] = {}      # (cle, genre) -> {jusqu, raison, restant_jour}


def genre_outil(nom: str) -> str:
    """« lecture » (list_*, get_*, _ping) ou « ecriture » : GetMySocial ne
    les compte pas dans le meme panier."""
    return "lecture" if str(nom or "").startswith(("list_", "get_", "search_", "_ping")) \
        else "ecriture"


def _cles_compte() -> list:
    """Les cles du compte, la principale d'abord."""
    out = []
    for k in [get_api_key()] + get_dash_keys():
        if k and k not in out:
            out.append(k)
    return out


def pause_cle(cle: str, genre: str = "lecture") -> int:
    """Secondes avant de rappeler GetMySocial avec CETTE cle, pour ce genre."""
    with _SANTE_LOCK:
        j = (_PAUSES.get((str(cle or ""), genre)) or {}).get("jusqu") or 0.0
    return max(0, int(j - time.time())) if j else 0


def _noter_refus(message: str, cle: Optional[str] = None, genre: str = "lecture") -> None:
    """Lit « retry after N » et « today: N » dans un refus, et se tait jusque-la
    -- pour CETTE cle et ce genre d'appel, les autres continuent.

    Seules les longues pauses arment le disjoncteur : un « retry after 17s »
    est un pic de debit, que le backoff existant absorbe tres bien. Au-dela de
    deux minutes, c'est le budget du jour, et il n'y a rien a attendre.
    """
    cle = str(cle if cle is not None else _effective_key())
    txt = str(message or "")
    m = _re_quota.search(txt)
    if not m:
        return
    try:
        secondes = int(m.group(1))
    except Exception:
        return
    reste = None
    mj = _re_jour.search(txt)
    if mj:
        try:
            reste = int(mj.group(1))
        except Exception:
            reste = None
    if secondes < 120:
        return
    with _SANTE_LOCK:
        _PAUSES[(cle, genre)] = {"jusqu": time.time() + min(secondes, 86400),
                                 "raison": txt[:200], "restant_jour": reste,
                                 "depuis": time.time()}
    print(f"[gms] cle {_masque(cle)} en pause ({genre}) pour {secondes // 60} min : "
          f"{'la principale' if cle == get_api_key() else 'une cle du pool'}, "
          "les autres prennent le relais", flush=True)
    if reste == 0 and cle == get_api_key() and genre == "lecture":
        # « today: 0 » : ce qu'on avait consomme dans la fenetre glissante EST
        # le plafond. C'est la seule occasion de l'apprendre -- un appel qui
        # passe ne dit pas combien il en reste.
        _budget_noter_plafond(appels_24h())


def pause_restante(genre: str = "lecture") -> int:
    """Secondes avant de pouvoir rappeler GetMySocial. 0 = une voie est libre.

    Une lecture passe par n'importe quelle cle du compte : il suffit qu'UNE
    soit libre. Une ecriture ne part que de la principale (_choisir_cle)."""
    cles = [get_api_key()] if genre == "ecriture" else _cles_compte()
    utiles = [k for k in cles if k == get_api_key() or not cle_ecartee(k)]
    if not utiles:
        return 0
    return min(pause_cle(k, genre) for k in utiles)


def heure_paris(ts: float) -> str:
    """« 09:33 », l'heure de Paris d'un instant. Le VPS tourne en UTC :
    time.localtime y disait « reprise vers 07:33 » d'une quota que le
    propriétaire voit revenir à 09h33 (06/10/2026)."""
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo
        return _dt.datetime.fromtimestamp(ts, ZoneInfo("Europe/Paris")).strftime("%H:%M")
    except Exception:                                        # noqa: BLE001
        return time.strftime("%H:%M", time.localtime(ts))


def etat_quota() -> dict:
    """De quoi l'AFFICHER : combien de temps encore (0 tant qu'une cle est
    libre), ce qu'il restait, et la charge de chaque cle."""
    reste = pause_restante()
    principale = get_api_key()
    with _SANTE_LOCK:
        p = dict(_PAUSES.get((principale, "lecture")) or {})
    heures = {_heure_cle(time.time() - i * 3600) for i in range(24)}
    with _BUDGET_LOCK:
        par_cle = {k: sum(v for h, v in (_APPELS_CLE.get(k) or {}).items() if h in heures)
                   for k in _cles_compte()}
    out = {"pause_s": reste,
           "reprise": heure_paris(time.time() + reste) if reste else "",
           "restant_jour": p.get("restant_jour"), "raison": p.get("raison") or "",
           "cles": [{"cle": _masque(k), "principale": k == principale,
                     "lecture_s": pause_cle(k), "ecriture_s": pause_cle(k, "ecriture"),
                     "appels_24h_memoire": par_cle.get(k, 0), "ecartee": cle_ecartee(k)}
                    for k in _cles_compte()]}
    try:
        out["budget"] = budget()
    except Exception:                                        # noqa: BLE001
        pass
    return out


def _quota_libere(cle: Optional[str] = None, genre: str = "lecture",
                  parti: Optional[float] = None) -> None:
    """Un appel qui passe prouve que la pause de CETTE cle est finie -- si
    elle a ete posee AVANT son depart (`parti`). Sinon, c'est un appel deja
    en vol qui revient : la pause qu'un autre fil vient de poser tient."""
    k = (str(cle if cle is not None else _effective_key()), genre)
    with _SANTE_LOCK:
        e = _PAUSES.get(k)
        if e and (parti is None or float(e.get("depuis") or 0) <= parti):
            _PAUSES.pop(k, None)


def _choisir_cle(genre: str = "lecture", tag: Optional[str] = None):
    """(cle, "") pour cet appel, ou (None, pourquoi). Le 06/10/2026, la
    principale portait seule ~10 250 appels par jour, sa limite etant de
    10 000, quand les quatre « dash » en portaient ~1 860 chacune.

    - Une ECRITURE part de la principale (les cles du pool n'ont jamais ecrit :
      on ne decouvre pas leurs droits sur la page d'un VA), sans budget : seule
      sa pause d'ecritures l'arrete.
    - Une LECTURE de fond (dashboard, widget des VA, prechauffage) part du
      pool : la principale garde sa journee pour la paie.
    - Les autres lectures partent de la principale, ou d'une cle du pool
      quand elle est en pause ou dans la reserve de la paie (budget_ok).
    - La cle choisie par l'appelant (use_key) passe d'abord, si elle est libre.
    """
    principale = get_api_key()
    if not principale:
        return None, "Clé API GetMySocial non configurée"
    tag = str(tag or getattr(_API_LOCAL, "tag", None) or "autres")
    if genre == "ecriture":
        # Les ecritures ont leurs propres paniers chez GetMySocial : le budget
        # (des LECTURES de la principale) ne les retient pas. Sans ca, la
        # generation du lien d'un VA restait refusee « pour la paie » quand
        # les lectures de la principale approchaient de leur limite.
        if pause_cle(principale, "ecriture"):
            r = pause_cle(principale, "ecriture")
            return None, ("Quota GetMySocial epuise (ecritures) — reprise vers %s (%d min)"
                          % (heure_paris(time.time() + r), r // 60))
        return principale, ""
    pool = [k for k in get_dash_keys() if k != principale and not cle_ecartee(k)]
    if pool:
        with _GMS_GATE_LOCK:
            i = _DASH_RR[0]
            _DASH_RR[0] = (i + 1) % len(pool)
        pool = pool[i % len(pool):] + pool[:i % len(pool)]
    explicite = str(getattr(_KEY_LOCAL, "key", None) or "")
    ordre = [explicite] if explicite else []
    ordre += (pool + [principale]) if PRIORITES.get(tag) == "fond" else ([principale] + pool)
    vus, budget_refuse = set(), False
    for k in ordre:
        if not k or k in vus:
            continue
        vus.add(k)
        if pause_cle(k, "lecture"):
            continue
        if k == principale and not budget_ok(tag):
            budget_refuse = True
            continue
        return k, ""
    if budget_refuse and not pause_cle(principale, "lecture"):
        _budget_dire_refus()
        return None, ("Budget GetMySocial du jour reserve a la paie (podium, primes) "
                      "— relance plus tard")
    r = pause_restante("lecture")
    return None, ("Quota GetMySocial epuise — reprise vers %s (%d min)"
                  % (heure_paris(time.time() + r), r // 60))


def replis_principale() -> dict:
    """Combien d'appels sont partis sur la cle principale faute de pool sain.

    A regarder quand la paie se met a echouer sans raison apparente : si ce
    compteur monte, c'est le dashboard qui occupe sa voie.
    """
    with _SANTE_LOCK:
        n, q = _REPLIS["n"], _REPLIS["quand"]
    return {"n": n, "depuis_s": int(time.time() - q) if q else None}


def cles_saines() -> int:
    """Combien de cles dediees repondent encore. Le panneau affichait le
    nombre de cles CONFIGUREES : pendant les dix minutes ou les huit voies
    etaient mortes, il annoncait « 8 cles dediees actives ». Pas seulement
    muet : faux."""
    return sum(1 for k in get_dash_keys() if not cle_ecartee(k))


def cle_ecartee(cle: str) -> bool:
    with _SANTE_LOCK:
        e = _SANTE.get(str(cle or ""))
        return bool(e and e["jusqu"] > time.time())


def sante_cles() -> list:
    """Ce que les cles ont vecu recemment, pour l'afficher : [{cle, echecs,
    ecartee, dernier}]. Masquee : une cle ne se lit pas dans un rapport."""
    out = []
    now = time.time()
    with _SANTE_LOCK:
        for cle, e in _SANTE.items():
            if not e["echecs"] and not e["jusqu"]:
                continue
            out.append({"cle": _masque(cle), "echecs": e["echecs"],
                        "ecartee": e["jusqu"] > now,
                        "dernier": e["dernier"],
                        "depuis_s": int(now - e["quand"]) if e["quand"] else None})
    out.sort(key=lambda r: -r["echecs"])
    return out


# ── Les liens d'un appel : jamais vides, jamais supprimes, jamais trop ──
# Releve de la semaine du 29/09/2026 : ~1 830 appels list_recent_visitors par
# jour echouaient et comptaient quand meme dans la quota -- ~1 395 en 400
# invalid_request, ~437 en 404 link_not_found (liens supprimes). Le 400 n'etait
# pas un identifiant vide : GetMySocial refuse PLUS DE 20 LIENS par appel de
# statistiques (verifie le 06/10 : 20 passent, 21 rendent « link_id must
# contain at least one value », malgre la doc qui dit 200), et le widget des VA
# envoyait tout le groupe d'une model.
_LIENS_SUPPRIMES: Dict[Any, float] = {}     # lnk_* ou frozenset(lnk_*) -> jusqu'a quand
DUREE_LIEN_SUPPRIME = 6 * 3600              # un lien supprime ne revient pas ; un doute, 6 h
MAX_LIENS_STATS = 20
#: Les seuls appels ou un lien supprime est oublie : les STATISTIQUES. Une
#: copie de lien toute neuve peut repondre « link_not_found » une seconde
#: (get_link juste apres duplicate_link) : l'oublier six heures bloquerait la
#: generation du lien d'un VA. Les identifiants VIDES, eux, ne partent jamais.
_OUTILS_STATS = {"list_recent_visitors", "get_analytics_overview", "get_time_series",
                 "get_link_metrics"}
_RE_LNK = re.compile(r"\blnk_[0-9A-Za-z]+")
_DIT_TROP = {}                              # outil -> dernier « plus de 20 liens » dit


def _liens_a_lire(tool_name: str, args: Optional[dict]):
    """(args nettoyes, "") ou (None, pourquoi ne PAS appeler).

    - Un identifiant vide n'est jamais envoye ; s'il ne reste aucun lien, pas
      d'appel (une liste vide voudrait dire « tout le compte »).
    - Statistiques : plus de MAX_LIENS_STATS liens, pas d'appel (GetMySocial
      refuse, et le refus compterait) ; un lien connu comme supprime est
      RETIRE pour le travail de fond (widget, dashboard), mais REFUSE, nomme,
      pour tout le reste : un total de paie calcule sans un lien serait un
      chiffre faux rendu comme juste."""
    if not isinstance(args, dict) or ("link_id" not in args and "link_ids" not in args):
        return args, ""
    a = dict(args)
    seul = "link_ids" not in a
    bruts: List[Any] = []
    if "link_ids" in a:
        v = a.pop("link_ids")
        bruts += v.split(",") if isinstance(v, str) else list(v or [])
    if "link_id" in a:
        bruts.append(a.pop("link_id"))
    stats = tool_name in _OUTILS_STATS
    maintenant = time.time()
    with _SANTE_LOCK:
        for k in [k for k, t in _LIENS_SUPPRIMES.items() if t <= maintenant]:
            _LIENS_SUPPRIMES.pop(k, None)
        morts = set(_LIENS_SUPPRIMES) if stats else set()
    ids: List[str] = []
    for x in bruts:
        x = str(x or "").strip()
        if not x:
            continue
        if not x.startswith("lnk_") and re.fullmatch(r"[0-9a-f]{24}", x):
            x = "lnk_" + x
        if x not in ids:
            ids.append(x)
    if not ids:
        return None, (f"{tool_name} : aucun lien à lire (identifiants vides) — pas d'appel")
    if stats:
        if frozenset(ids) in morts:
            return None, (f"{tool_name} : lot de liens déjà refusé (link_not_found) — "
                          "pas d'appel")
        supprimes = [x for x in ids if x in morts]
        if supprimes:
            if PRIORITES.get(str(getattr(_API_LOCAL, "tag", None) or "")) != "fond":
                return None, (f"{tool_name} : lien(s) supprimé(s) chez GetMySocial : "
                              + ", ".join(supprimes[:5]) + " — pas d'appel, total incomplet")
            ids = [x for x in ids if x not in morts]
            if not ids:
                return None, f"{tool_name} : tous ces liens sont supprimés — pas d'appel"
        if len(ids) > MAX_LIENS_STATS:
            if time.time() - _DIT_TROP.get(tool_name, 0.0) > 600:
                _DIT_TROP[tool_name] = time.time()
                print(f"[gms] {tool_name} : {len(ids)} liens dans un appel, GetMySocial en "
                      f"refuse plus de {MAX_LIENS_STATS} (400) — pas d'appel "
                      f"(etiquette « {getattr(_API_LOCAL, 'tag', None) or 'autres'} »)",
                      flush=True)
            return None, (f"{tool_name} : {len(ids)} liens, GetMySocial en refuse plus de "
                          f"{MAX_LIENS_STATS} par appel — pas d'appel")
    if seul and len(ids) == 1:
        a["link_id"] = ids[0]
    else:
        a["link_ids"] = ids
    return a, ""


def _noter_liens_supprimes(tool_name: str, args: Optional[dict], res: Dict[str, Any]) -> None:
    """Un 404 link_not_found sur une statistique : le lien nomme (ou, a
    defaut, le lot entier) n'y sera plus demande pendant DUREE_LIEN_SUPPRIME."""
    err = str(res.get("error") or "")
    if (tool_name not in _OUTILS_STATS or res.get("ok") or "link_not_found" not in err
            or not isinstance(args, dict)):
        return
    ids = ([args["link_id"]] if args.get("link_id") else []) + list(args.get("link_ids") or [])
    nommes = [x for x in _RE_LNK.findall(err) if x in ids]
    cibles = nommes or (ids if len(ids) == 1 else [frozenset(ids)])
    jusqu = time.time() + DUREE_LIEN_SUPPRIME
    with _SANTE_LOCK:
        neufs = [c for c in cibles if c not in _LIENS_SUPPRIMES]
        for c in cibles:
            _LIENS_SUPPRIMES[c] = jusqu
    if neufs:
        print(f"[gms] lien(s) introuvable(s) chez GetMySocial, plus demandé(s) pendant "
              f"{DUREE_LIEN_SUPPRIME // 3600} h : "
              + ", ".join(sorted(str(c if isinstance(c, str) else f"lot de {len(c)}")
                                 for c in neufs))[:300], flush=True)


def _call_tool(tool_name: str, args: Optional[dict] = None, _retry: bool = True,
               _429: int = 0) -> Dict[str, Any]:
    """Le vrai appel : la cle choisie (_choisir_cle), les liens nettoyes, et la
    tenue du registre de sante de la cle employee. Une cle dont la journee
    vient de finir passe la main a une autre cle libre du compte."""
    genre = genre_outil(tool_name)
    args, pourquoi = _liens_a_lire(tool_name, args)
    if pourquoi:
        return {"ok": False, "error": pourquoi}
    res: Dict[str, Any] = {"ok": False, "error": "aucune cle"}
    for _essai in range(max(1, len(_cles_compte()))):
        cle, pourquoi = _choisir_cle(genre)
        if not cle:
            return {"ok": False, "error": pourquoi}
        parti = time.time()
        with use_key(cle):
            res = _call_tool_brut(tool_name, args, _retry=_retry, _429=_429)
        try:
            if res.get("ok"):
                _quota_libere(cle, genre, parti)
            elif not pause_cle(cle, genre):
                # deja notee par _call_tool_brut sur un HTTP 429 ; ici, le refus
                # rendu dans la reponse (« Error 429 ... today: 0 »)
                _noter_refus(res.get("error") or "", cle, genre)
            noter_cle(cle, bool(res.get("ok")), res.get("error") or "")
        except Exception:
            pass                 # l'instrumentation ne doit jamais casser l'appel
        if res.get("ok") or not pause_cle(cle, genre):
            break
    try:
        _noter_liens_supprimes(tool_name, args, res)
    except Exception:
        pass
    return res


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


#: Les espaces du compte, gardes dix minutes. Sans cache, teams_via_api
#: partait a CHAQUE rendu de l'accueil (web_upload._g appelle son producteur
#: tout de suite, sans paresse) : un appel par visite, plus un par demarrage du
#: site — soixante-six le 03/10/2026.
_TEAMS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_TEAMS_TTL = 600


def teams_via_api() -> List[Dict[str, Any]]:
    """Les workspaces du compte, par la CLE API. [] si l'appel echoue.

    A ne pas confondre avec la constante KNOWN_TEAMS, qui n'en liste que deux
    en dur : le compte en compte sept (Threads US, marche francais, BOYA,
    KHLOE, JESSY LE RETOUR, Jessye Twitter, Agence Noctus). Tout ce qui se
    fonde sur KNOWN_TEAMS ignore donc les cinq autres — c'est ce qui rendait
    l'autocompletion des groupes vide pour la plupart d'entre eux.

    Passe par la cle API et non par le cookie de session : le cookie expire, la
    cle non.
    """
    if (_TEAMS_CACHE["data"] is not None
            and 0 <= time.time() - float(_TEAMS_CACHE["ts"]) < _TEAMS_TTL):
        return list(_TEAMS_CACHE["data"])
    res = _call_tool("list_teams", {"limit": 100})
    if not res.get("ok"):
        # UN ECHEC NE SE MET PAS EN CACHE : une secousse passagere deviendrait
        # dix minutes de liste vide.
        return []
    d = res.get("data") or {}
    out = []
    for t in (d.get("data") if isinstance(d, dict) else []) or []:
        tid = str(t.get("id") or "").strip()
        if tid:
            out.append({"id": tid, "name": str(t.get("name") or "").strip(),
                        "link_count": t.get("link_count")})
    _TEAMS_CACHE.update({"ts": time.time(), "data": list(out)})
    return out


def groups_via_api(team_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Les groupes d'UN workspace (ou de l'espace personnel), par la CLE API.

    [] si l'appel echoue. Meme raison qu'au-dessus de preferer la cle au
    cookie : list_team_groups, qui passe par le board prive, rend une liste
    vide des que la session a expire — sans le dire.
    """
    args: Dict[str, Any] = {"limit": 100}
    if team_id:
        args["team_id"] = team_id
    res = _call_tool("list_groups", args)
    if not res.get("ok"):
        return []
    d = res.get("data") or {}
    out = []
    for g in (d.get("data") if isinstance(d, dict) else []) or []:
        gid = str(g.get("id") or "").strip()
        nom = str(g.get("name") or "").strip()
        if gid and nom:
            out.append({"id": gid, "name": nom,
                        "link_count": g.get("link_count") or 0})
    return out


_LINKS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_LINKS_TEAM_CACHE: Dict[str, Any] = {}  # team_id -> {"ts","data"}
_LINKS_TTL = 900  # 15 min (invalidé par invalidate_grouping_cache sur create/delete)


def list_all_links(max_pages: int = 50, force_refresh: bool = False) -> Dict[str, Any]:
    """Paginate pour récupérer TOUS les liens du compte.

    Limite de sécurité : max_pages * 100 liens (par défaut 5000).
    Cache 2 min — sinon les mêmes liens sont re-paginés ~4× par render de page.
    """
    if (not force_refresh and _LINKS_CACHE["data"] is not None
            and (time.time() - _LINKS_CACHE["ts"]) < _LINKS_TTL):
        return {"ok": True, "links": _LINKS_CACHE["data"]}
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
    _LINKS_CACHE["ts"] = time.time()
    _LINKS_CACHE["data"] = all_links
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
    if start_date or end_date:
        # même fuseau que le dashboard GMS -> les totaux par jour correspondent
        args["timezone"] = "Europe/Paris"
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
        return None  # payload illisible -> « indispo » (—), pas un faux 0 (sous-paie)


def _lire_analytics(res):
    """(total_clicks, {country_code: count}) depuis une reponse d'overview.

    Le detail pays vient de `top_countries` (top ~10 -> un pays eligible hors
    du top peut manquer = leger sous-comptage, cote "on ne surpaye pas").
    Rend (None, None) si l'appel a echoue - surtout pas (0, {}), qui se
    lirait « personne n'a clique ».
    """
    if not res.get("ok"):
        return None, None
    d = res.get("data")
    if not isinstance(d, dict):
        d = res
    try:
        total = int(d.get("total_clicks") or 0)
    except Exception:
        return None, None
    countries = {}
    for c in (d.get("top_countries") or []):
        code = (c.get("country_code") or "").upper()
        if not code:
            continue
        try:
            countries[code] = int(c.get("count") or 0)
        except Exception:
            pass
    return total, countries


_ANA_CACHE = {}
_ANA_LOCK = _threading.Lock()
TTL_ANALYTICS = 180      # periode CLOSE : elle ne changera plus
TTL_OUVERT = 90          # periode en cours : elle bouge encore


def _analytics_cachee(ids, start_date: str, end_date: str):
    """Le releve d'un lien (ou d'un lot), servi depuis une memoire courte.

    Le report horaire et la page publique calculent EXACTEMENT la meme chose,
    chacun de son cote : quatre-vingt-dix appels a une minute d'intervalle
    pour un resultat identique, sur un quota qui ne suit deja pas. Trois
    minutes de memoire n'en font qu'un.

    HYPOTHESE ASSUMEE : toutes les cles configurees appartiennent au MEME
    compte GetMySocial et voient donc les memes chiffres. C'est ce qui permet
    au releve pris par le pool de servir a la voie principale, et c'est tout
    l'interet de ce cache. Une cle d'un autre compte rendrait ici des chiffres
    qui ne sont pas ceux de l'espace — le panneau n'accepte que des cles du
    compte, mais l'hypothese merite d'etre dite.

    UN ECHEC N'EST JAMAIS MIS EN CACHE. Geler un 429 pendant trois minutes
    transformerait une secousse passagere en panne franche, et la page
    afficherait « non lu » longtemps apres que la source soit revenue.
    """
    # LE JOUR COURANT ENTRE DANS LA CLE. Un releve de « aujourd hui » pris a
    # 23h59 restait servi a 00h01 pour ce qui etait devenu « hier », ampute
    # de sa derniere minute et fige comme definitif. Changer de jour vide de
    # fait les entrees de la veille.
    aujourdhui = time.strftime("%Y-%m-%d")
    cle = (tuple(ids), str(start_date), str(end_date), aujourdhui)
    maintenant = time.time()
    # Une periode ENCORE OUVERTE (elle se termine aujourd hui ou plus tard)
    # bouge a chaque clic : on la garde moins longtemps qu'une periode close,
    # qui, elle, ne changera plus jamais.
    ttl = TTL_ANALYTICS if str(end_date) < aujourdhui else TTL_OUVERT
    with _ANA_LOCK:
        v = _ANA_CACHE.get(cle)
        if v and (maintenant - v[0]) < ttl:
            return v[1]
    res = _lire_analytics(
        get_analytics_overview(start_date, end_date, link_ids=list(ids)))
    if res[0] is not None:
        with _ANA_LOCK:
            _ANA_CACHE[cle] = (maintenant, res)
            if len(_ANA_CACHE) > 4000:
                # Borne dure : on ne garde pas la memoire de tous les liens de
                # tous les jours. Les plus vieux partent en premier.
                for k in sorted(_ANA_CACHE, key=lambda x: _ANA_CACHE[x][0])[:1000]:
                    _ANA_CACHE.pop(k, None)
    return res


def analytics_for_link(link_id: str, start_date: str, end_date: str):
    """(total_clicks, {country_code: count}) pour UN lien sur une periode."""
    if not link_id:
        return None, None
    return _analytics_cachee((link_id,), start_date, end_date)


def analytics_for_links(link_ids, start_date: str, end_date: str):
    """Le meme releve pour un LOT de liens, en UN SEUL appel.

    Le total d'un groupe se tirait jusqu'ici en additionnant les relevés
    lien par lien : trente appels la ou l'API en accepte un, et un resultat
    MOINS juste - chaque lien ne rend que son top ~10 de pays, si bien que la
    somme des tops perdait la traine. Ici le top est calcule par GetMySocial
    sur l'ensemble.
    """
    ids = [i for i in (link_ids or []) if i]
    if not ids:
        return None, None
    return _analytics_cachee(tuple(ids), start_date, end_date)


def time_series_for_link(link_id: str, start_date: str, end_date: str,
                         tz: str = "Europe/Paris") -> Optional[Dict[str, int]]:
    """Clics JOUR PAR JOUR d'un lien en UN SEUL appel (outil MCP get_time_series),
    au lieu d'un get_analytics_overview par jour. Retourne {"YYYY-MM-DD": clics}
    ou None si échec (jamais un faux 0)."""
    res = _call_tool("get_time_series", {
        "link_id": link_id, "start_date": start_date, "end_date": end_date,
        "interval": "day", "timezone": tz,
    })
    if not res.get("ok"):
        return None
    data = res.get("data") or {}
    rows = data.get("data") if isinstance(data, dict) else None
    if rows is None:
        rows = data if isinstance(data, list) else []
    out: Dict[str, int] = {}
    for b in rows or []:
        if not isinstance(b, dict):
            continue
        day = str(b.get("bucket") or "")[:10]
        if not day:
            continue
        v = b.get("pageviews")
        if v is None:
            v = b.get("clicks") or 0
        out[day] = int(v or 0)
    return out


def time_series_for_links(link_ids, start_date: str, end_date: str,
                          tz: str = "Europe/Paris") -> Optional[Dict[str, int]]:
    """Comme time_series_for_link mais AGRÈGE un LOT de liens (≤200) en UN appel
    — sert aux courbes « par modèle » (tous les liens d'une identité sommés).
    Retourne {"YYYY-MM-DD": clics} ou None si échec."""
    ids = [i for i in (link_ids or []) if i][:200]
    if not ids:
        return {}
    # L'API REFUSE >20 link_ids (Error 400, malgré la doc qui dit 200) -> on
    # découpe par 20 et on SOMME les séries. Un lot en échec = None (jamais une
    # courbe partielle présentée comme complète).
    out: Dict[str, int] = {}
    for i in range(0, len(ids), 20):
        res = _call_tool("get_time_series", {
            "link_ids": ids[i:i + 20], "start_date": start_date, "end_date": end_date,
            "interval": "day", "timezone": tz,
        })
        if not res.get("ok"):
            return None
        data = res.get("data") or {}
        rows = data.get("data") if isinstance(data, dict) else None
        if rows is None:
            rows = data if isinstance(data, list) else []
        for b in rows or []:
            if not isinstance(b, dict):
                continue
            day = str(b.get("bucket") or "")[:10]
            if not day:
                continue
            v = b.get("pageviews")
            if v is None:
                v = b.get("clicks") or 0
            out[day] = out.get(day, 0) + int(v or 0)
    return out


def clicks_for_ids(link_ids: List[str], start_date: str, end_date: str) -> Optional[int]:
    """Total de clics pour une LISTE de liens sur une periode (YYYY-MM-DD).
    Batch par 20 (l'API analytics rejette >~20 link_ids : Error 400
    'link_id must contain at least one value'). Retourne None si UN SEUL batch
    echoue (le total serait partiel/faux — chiffre de paie, on prefere
    « indispo » a un sous-comptage credible), sinon la somme (0 si liste vide)."""
    if not link_ids:
        return 0
    total = 0
    for i in range(0, len(link_ids), 20):
        chunk = link_ids[i:i + 20]
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
    # 1) correspondance EXACTE : va_@<handle>
    for l in links:
        if _norm_handle(l.get("display_name")) == target:
            return l
    # 2) le handle est un MOT ENTIER du display_name (« va @toky », « VA toky 3 »).
    #    Avant : simple sous-chaîne -> « lia » matchait « amelia », « mia »
    #    matchait « mialee »… et les clics (donc l'argent) d'un AUTRE VA
    #    étaient attribués au mauvais.
    import re as _re_fl
    for l in links:
        raw = (l.get("display_name") or "").lower()
        if not _norm_handle(raw).startswith("va"):
            continue
        toks = [t for t in _re_fl.split(r"[^a-z0-9]+", raw) if t]
        if h in toks:
            return l
    # 3) shortcode : mot entier également
    for l in links:
        raw = (l.get("shortcode") or "").lower()
        toks = [t for t in _re_fl.split(r"[^a-z0-9]+", raw) if t]
        if h in toks:
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
    _LINKS_CACHE["ts"] = 0.0
    _LINKS_CACHE["data"] = None
    _LINKS_TEAM_CACHE.clear()


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
    safe_json.write_text(_TEMPLATES_FILE, json.dumps(data, indent=2, ensure_ascii=False))


def set_template_for_model(model: str, link_id: str):
    tpls = load_templates()
    key = (model or "").strip().lower()
    if not key:
        return
    # Normalise l'id (l'API GMS renvoie parfois sans le préfixe lnk_). Sans ça,
    # un id sans préfixe POPpait silencieusement le template (et la route web
    # renvoyait quand même « ✅ défini »).
    link_id = (link_id or "").strip()
    if link_id and not link_id.startswith("lnk_"):
        link_id = "lnk_" + link_id
    if link_id:
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
    """Supprime UN lien -- definitif, GetMySocial n'a pas de corbeille.

    L'outil s'appelle delete_links (par lots, `ids`). L'ancien « delete_link »
    n'existe plus : GetMySocial repondait « Unknown tool » et ca passait pour
    un succes -- /resetlien et la page des liens annoncaient des suppressions
    qui n'avaient pas lieu (constate le 03/10/2026). Le succes se lit dans
    `deleted` : un id refuse n'echoue pas l'appel, il part dans `failed`."""
    res = _call_tool("delete_links", {"ids": [link_id]})
    if not res.get("ok"):
        return res
    d = res.get("data") if isinstance(res.get("data"), dict) else {}
    if link_id not in (d.get("deleted") or []):
        rate = next((f for f in d.get("failed") or []
                     if isinstance(f, dict) and f.get("id") == link_id), {})
        err = rate.get("error") if isinstance(rate.get("error"), dict) else {}
        return {"ok": False, "data": d,
                "error": f"non supprimé : {err.get('message') or err.get('code') or d or 'réponse vide'}"}
    try:
        invalidate_grouping_cache()  # sinon le lien supprimé reste en cache
    except Exception:
        pass
    return res


def enable_link(link_id: str) -> Dict[str, Any]:
    return _call_tool("enable_link", {"link_id": link_id})


def disable_link(link_id: str) -> Dict[str, Any]:
    return _call_tool("disable_link", {"link_id": link_id})


# ============ Lire / modifier UN lien par MCP ============
# liens_fr lisait et reecrivait ses pages en appelant _call_tool a la main,
# avec son propre decodage de la reponse ; liens_identite_us en a besoin a son
# tour. Une seule facon de lire un lien plutot qu'une copie par module : la
# reponse arrive tantot en dict, tantot en texte JSON ou en repr Python, et
# parfois enveloppee dans « data ».
def _objet_lien(data: Any) -> Dict[str, Any]:
    """L'objet lien d'une reponse MCP (dict, texte JSON ou repr), {} sinon."""
    d = data
    if isinstance(d, str):
        import ast as _ast
        for lire in (json.loads, _ast.literal_eval):
            try:
                d = lire(d)
                break
            except Exception:
                continue
    if isinstance(d, dict) and isinstance(d.get("data"), dict) and "buttons" not in d:
        d = d["data"]
    return d if isinstance(d, dict) else {}


def get_link(link_id: str, team_id: Optional[str] = None) -> Dict[str, Any]:
    """Un lien complet (boutons compris) par l'outil MCP get_link.

    team_id : la portee de lecture (group_id / team_id rendus pour cette
    equipe). Retourne {ok, link, error} ; `link` vaut {} si la reponse est
    illisible -- ok reste vrai, a l'appelant de juger ce qui lui manque.
    """
    if not link_id:
        return {"ok": False, "error": "link_id requis"}
    args: Dict[str, Any] = {"link_id": link_id}
    if team_id:
        args["team_id"] = team_id if team_id.startswith("tm_") else f"tm_{team_id}"
    res = _call_tool("get_link", args)
    if not res.get("ok"):
        return res
    return {"ok": True, "link": _objet_lien(res.get("data"))}


def update_link(link_id: str, champs: Dict[str, Any],
                team_id: Optional[str] = None) -> Dict[str, Any]:
    """Modifie un lien par l'outil MCP update_link. Retourne {ok, link, error}.

    ATTENTION : les tableaux (`buttons`, `geofilters`…) sont REMPLACES en
    entier par GetMySocial. Lire le lien (get_link), copier, ne changer que
    ce qu'il faut. Ne JAMAIS passer `typeLink: "directlink"` pour une page :
    c'est ce que fait duplicate_link(new_url=…), pense pour un lien direct.
    """
    if not link_id:
        return {"ok": False, "error": "link_id requis"}
    args: Dict[str, Any] = dict(champs or {})
    args["link_id"] = link_id
    if team_id:
        args["team_id"] = team_id if team_id.startswith("tm_") else f"tm_{team_id}"
    res = _call_tool("update_link", args)
    if not res.get("ok"):
        return res
    try:
        invalidate_grouping_cache()   # le nom a pu changer : la liste doit le revoir
    except Exception:
        pass
    return {"ok": True, "link": _objet_lien(res.get("data"))}


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
    safe_json.write_text(_GROUPS_FILE, json.dumps(mapping, indent=2, ensure_ascii=False))


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
    # 0) Tentative via l'outil MCP officiel assign_links_to_group (le plus fiable :
    #    l'API privée peut répondre ok SANS effet sur un groupe vide — vu le 04/07
    #    avec les groupes BO7/ANDRY). Le group_id doit être préfixé grp_.
    try:
        gid_p = group_id if str(group_id).startswith("grp_") else f"grp_{group_id}"
        args = {"group_id": gid_p, "link_ids": [link_id]}
        if team_id:
            args["team_id"] = team_id if str(team_id).startswith("tm_") else f"tm_{team_id}"
        mcp_res = _call_tool("assign_links_to_group", args)
        if mcp_res.get("ok"):
            return {"ok": True, "via": "mcp_bulk"}
    except Exception:
        pass
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


_BOARD_MAP_CACHE: Dict[str, Any] = {}
_BOARD_MAP_TTL = 900


def link_groups_map(team_id: str, force_refresh: bool = False) -> Optional[Dict[str, str]]:
    """{link_id: nom_du_groupe} pour toute la team, en UN appel au board privé
    (cookie). C'est LA source de vérité pour rattacher un lien à son groupe
    (« AMELIA JB TOKY »…) — les noms de liens ne suffisent pas (ceux de toky
    s'appellent juste « VA 1 »). None = échec (cookie mort/HTTP) ; l'appelant
    retombe alors sur ses heuristiques de nommage. Cache 15 min par team."""
    cookie = get_session_cookie()
    if not cookie:
        return None
    tid = team_id[3:] if team_id.startswith("tm_") else team_id
    c = _BOARD_MAP_CACHE.get(tid)
    if (not force_refresh and c and c.get("data") is not None
            and (time.time() - c.get("ts", 0)) < _BOARD_MAP_TTL):
        return c["data"]
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
    if not isinstance(d, dict) or "placements" not in d:
        return None
    gnames: Dict[str, str] = {}
    for g in d.get("groups") or []:
        gid = str(g.get("id") or g.get("_id") or g.get("groupId") or "")
        name = str(g.get("name") or g.get("title") or "").strip()
        if gid and name:
            gnames[gid] = name
    out: Dict[str, str] = {}
    for pl in d.get("placements") or []:
        gid = str(pl.get("groupId") or "")
        lid = pl.get("linkId")
        if gid in gnames and lid:
            lid = lid if str(lid).startswith("lnk_") else "lnk_" + str(lid)
            out[lid] = gnames[gid]
    _BOARD_MAP_CACHE[tid] = {"ts": time.time(), "data": out}
    return out


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
    # board récupéré mais structure inattendue (clé 'placements' absente =
    # schéma changé) -> ÉCHEC (None), pas un faux « groupe vide ».
    if not isinstance(d, dict) or "placements" not in d:
        return None
    out: List[str] = []
    for p in d.get("placements") or []:
        if str(p.get("groupId")) == str(group_id):
            lid = p.get("linkId")
            if lid:
                out.append(lid if str(lid).startswith("lnk_") else "lnk_" + str(lid))
    return out


def report_link_ids(team_id: str, identity: Optional[str] = None,
                    group_id: Optional[str] = None,
                    tout: bool = False) -> Optional[List[str]]:
    """Link ids a inclure dans un report de clics, le plus ROBUSTEMENT possible.

    Priorite au SUFFIXE de shortcode (ex: hybride -> '…secret') via la CLE API
    publique (fiable, et exclut naturellement le template) ; sinon repli sur
    l'appartenance au GROUPE via le cookie de session (API privee, peut etre
    expire sur le VPS).
    None = impossible de recuperer (l'appelant NE DOIT PAS afficher « 0 clic »).
    []   = recupere mais aucun lien (vrai vide).
    """
    # `tout` = tous les liens du workspace, sans regarder les groupes. Derriere
    # un drapeau explicite : sans lui, un appel qui ne precise ni identite ni
    # groupe rendait None, et des appelants comptent la-dessus.
    if tout and team_id:
        r = list_links_team(team_id)
        if not r.get("ok"):
            return None
        return [l["id"] for l in r.get("links", []) if l.get("id")]
    suffix = _SHORTCODE_SUFFIX.get((identity or "").lower()) if identity else None
    if suffix and team_id:
        r = list_links_team(team_id)
        if not r.get("ok"):
            return None
        return [l["id"] for l in r.get("links", [])
                if l.get("id") and (l.get("shortcode") or "").lower().endswith(suffix)]
    if group_id and team_id:
        return link_ids_in_group(team_id, group_id)
    return None


def report_links_meta(team_id: str, identity: Optional[str] = None,
                      group_id: Optional[str] = None,
                      tout: bool = False) -> Optional[List[Dict[str, str]]]:
    """Comme report_link_ids mais renvoie les liens avec leur nom :
    [{id, shortcode, display_name}, …] pour un detail par lien (par VA).
    None = echec ; [] = vrai vide. Meme strategie clé API / cookie."""
    if tout and team_id:
        r = list_links_team(team_id)
        if not r.get("ok"):
            return None
        return [
            {"id": l.get("id"), "shortcode": l.get("shortcode") or "",
             "display_name": l.get("display_name") or "",
             # La destination sert a retrouver le code de suivi MyPuls, qui en
             # occupe le dernier segment : onlyfans.com/<pseudo>/c85.
             "destination": l.get("url") or ""}
            for l in r.get("links", []) if l.get("id")
        ]
    suffix = _SHORTCODE_SUFFIX.get((identity or "").lower()) if identity else None
    if suffix and team_id:
        r = list_links_team(team_id)
        if not r.get("ok"):
            return None
        return [
            {"id": l.get("id"), "shortcode": l.get("shortcode") or "",
             "display_name": l.get("display_name") or ""}
            for l in r.get("links", [])
            if l.get("id") and (l.get("shortcode") or "").lower().endswith(suffix)
        ]
    if group_id and team_id:
        ids = link_ids_in_group(team_id, group_id)
        if ids is None:
            return None
        r = list_links_team(team_id)
        if not r.get("ok"):
            return None
        by_id = {l.get("id"): l for l in r.get("links", [])}
        out = []
        for lid in ids:
            l = by_id.get(lid) or {}
            out.append({"id": lid, "shortcode": l.get("shortcode") or "",
                        "display_name": l.get("display_name") or ""})
        return out
    return None


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
    safe_json.write_text(_VA_COUNTERS_FILE, json.dumps(d, indent=2, ensure_ascii=False))


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


def list_links_team(team_id: str, force_refresh: bool = False) -> Dict[str, Any]:
    """List_all_links scopé à un team via API publique v3. Cache 2 min par team
    (mêmes liens re-demandés plusieurs fois par render de page sinon)."""
    if not get_api_key():
        return {"ok": False, "error": "API key absente"}
    # LE SEUL CHEMIN QUI TAPAIT SUR UNE PORTE FERMEE. Tout le reste passe par
    # _call_tool_brut, qui refuse d'ouvrir la connexion pendant une pause ;
    # celui-ci, non — et comme il ne notait pas non plus le refus, un 429 de
    # quota journalier ne fermait jamais rien ici. Il entretenait le refus.
    # (Depuis le 06/10/2026, la pause est par cle : celle-ci n'arrete tout que
    # si AUCUNE cle du compte n'est libre.)
    _reste = pause_restante()
    if _reste > 0:
        return {"ok": False,
                "error": "Quota GetMySocial epuise — reprise vers %s (%d min)"
                         % (heure_paris(time.time() + _reste), _reste // 60)}
    # la cle : la principale, ou une autre quand elle est en pause ou dans la
    # reserve de la paie -- le budget est consulte la (_choisir_cle)
    api_key, pourquoi = _choisir_cle("lecture")
    if not api_key:
        return {"ok": False, "error": pourquoi}
    tid = team_id if team_id.startswith("tm_") else f"tm_{team_id}"
    c = _LINKS_TEAM_CACHE.get(tid)
    if (not force_refresh and c and c.get("data") is not None
            and (time.time() - c.get("ts", 0)) < _LINKS_TTL):
        return {"ok": True, "links": c["data"]}
    all_links: List[dict] = []
    cursor: Optional[str] = None
    for _ in range(50):
        url = f"{PUBLIC_REST_BASE}/links?team_id={tid}&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        r = None
        _sleeps = (2.0, 6.0, 12.0) if _gms_is_bulk() else (1.0,)   # pages : 1 retry court
        relais = 0
        _try = 0
        while _try <= len(_sleeps):
            parti = time.time()
            with use_key(api_key):
                _gms_gate()
                try:
                    r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"},
                                     timeout=20)
                    _api_note(r.status_code)
                except Exception as e:
                    _api_note(0)
                    return {"ok": False, "error": f"reseau: {e}"}
                if r.status_code == 429:            # rate-limit -> on souffle puis on retente
                    _gms_note_429()
            if r.status_code == 429:
                # Le corps porte « today: 0 » quand c'est le budget du JOUR qui
                # est fini : le noter arme la pause de CETTE cle. Sans ca, cette
                # fonction etait la seule a ne jamais la declencher.
                _noter_refus(r.text or "", api_key, "lecture")
                if pause_cle(api_key, "lecture") > 0:
                    # sa journee est finie : une autre cle du compte reprend la
                    # meme page, sans attendre (une fois par cle au plus)
                    autre, _ = _choisir_cle("lecture")
                    if autre and autre != api_key and relais < len(_cles_compte()):
                        api_key, relais = autre, relais + 1
                        continue
                    return {"ok": False, "error": "Quota GetMySocial epuise "
                                                  "pour aujourd hui"}
                if _try < len(_sleeps):
                    time.sleep(_sleeps[_try])
                _try += 1
                continue
            if r.status_code == 200:
                _quota_libere(api_key, "lecture", parti)
            break
        if r is None or r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code if r is not None else '?'}"}
        d = r.json()
        all_links.extend(d.get("data") or [])
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    _LINKS_TEAM_CACHE[tid] = {"ts": time.time(), "data": all_links}
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

# Modèles du MARCHÉ FRANÇAIS (VA classiques). Les groupes JB ont des noms
# composés (« emma bo7 », « soulcet jaurel »…) : le match EXACT sur ces 6 noms
# ne prend QUE les groupes classiques, jamais les JB.
FR_MARKET_MODELS = ["lola", "amelia", "alicia", "julia", "emma", "sarah"]
# Pays éligibles à la paie VA (marché francophone).
ELIGIBLE_COUNTRIES = {"FR", "BE", "CH", "LU", "MC"}


def fr_market_eligible_clicks(start_date: str, end_date: str,
                              models: Optional[List[str]] = None) -> Dict[str, Any]:
    """Clics ÉLIGIBLES (FR/BE/CH/LU/MC) des liens dans les GROUPES des modèles
    du marché français, sur une période (YYYY-MM-DD inclusif). On ne regarde QUE
    ces groupes-là -> les groupes jailbreak sont naturellement exclus.

    Résolution du groupe : mapping connu (clé API-safe) sinon nom exact (cookie).
    Link ids : appartenance au groupe (board dashboard, cookie). Clics : clé API
    (fiable) via get_analytics_overview batché.

    Retourne {ok, eligible, total, links, per_model:{model:{ok, links|reason}}}.
    ok=False si AUCUN groupe résolu ou analytics indispo (l'appelant garde alors
    sa dernière valeur au lieu d'afficher un faux 0)."""
    models = models or FR_MARKET_MODELS
    tid = MARCHE_FRANCAIS_TID
    model_set = {(m or "").strip().lower() for m in models}
    per_model: Dict[str, Any] = {}
    all_ids: List[str] = []
    source = ""

    # 1) PRIMAIRE — CLÉ API (fiable, pas de cookie) : liste tous les liens du
    #    workspace marché FR et garde ceux dont le SHORTCODE ou le display_name
    #    contient un des 6 noms de modèle (ex 'xk2amelia' -> amelia). Match direct
    #    sur MES 6 noms (indépendant de categorize_link, dont la liste KNOWN
    #    n'inclut pas Alicia). Les liens JB sont nommés d'après le VA (bo7 N,
    #    andry N…), shortcode sans nom de modèle -> exclus.
    import re as _re_fm
    rt = list_links_team(tid)
    if rt.get("ok"):
        source = "api"
        for l in rt.get("links", []):
            if not l.get("id"):
                continue
            sc = (l.get("shortcode") or "").lower()
            dn = _re_fm.sub(r"[^a-z0-9]", "", (l.get("display_name") or "").lower())
            hay = sc + " " + dn
            mdl = next((m for m in model_set if m and m in hay), None)
            if mdl:
                all_ids.append(l["id"])
                pm = per_model.setdefault(mdl, {"ok": True, "links": 0})
                pm["links"] += 1

    # 2) SECOURS — cookie board (appartenance réelle au groupe) si l'API n'a rien
    if not all_ids:
        mapping = load_groups_mapping()
        resolved = 0
        for m in models:
            ml = (m or "").strip().lower()
            gid = mapping.get(f"{tid}:{ml}") or group_id_by_name(tid, ml)
            if not gid:
                per_model[m] = {"ok": False, "reason": "groupe introuvable"}
                continue
            ids = link_ids_in_group(tid, gid)
            if ids is None:
                per_model[m] = {"ok": False, "reason": "board indisponible"}
                continue
            resolved += 1
            source = "cookie"
            per_model[m] = {"ok": True, "links": len(ids)}
            all_ids.extend(ids)
        if resolved == 0:
            return {"ok": False, "error": "aucun lien marché FR résolu (API + cookie KO)",
                    "eligible": 0, "total": 0, "links": 0, "per_model": per_model}
    all_ids = list(dict.fromkeys(all_ids))  # dedupe
    if not all_ids:
        return {"ok": True, "eligible": 0, "total": 0, "links": 0, "per_model": per_model}

    # L'API analytics plafonne à ~20 link_ids par appel (25 -> Error 400). On
    # découpe en paquets de 20, appelés en parallèle (thread-safe, cf. paie).
    from concurrent.futures import ThreadPoolExecutor
    chunks = [all_ids[i:i + 20] for i in range(0, len(all_ids), 20)]

    def _batch(chunk):
        for _try in range(2):  # 1 retry (réseau)
            res = get_analytics_overview(start_date, end_date, link_ids=chunk)
            if res.get("ok"):
                d = res.get("data")
                if not isinstance(d, dict):
                    d = res
                tot = 0
                try:
                    tot = int(d.get("total_clicks") or 0)
                except Exception:
                    pass
                elig = 0
                for c in (d.get("top_countries") or []):
                    if (c.get("country_code") or "").upper() in ELIGIBLE_COUNTRIES:
                        try:
                            elig += int(c.get("count") or 0)
                        except Exception:
                            pass
                return (tot, elig, True)
        return (0, 0, False)

    eligible = 0
    total = 0
    ok_batches = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for tot, elig, okb in ex.map(_batch, chunks):
            total += tot
            eligible += elig
            if okb:
                ok_batches += 1
    failed_batches = len(chunks) - ok_batches
    if ok_batches == 0:  # tout a échoué -> indispo (l'appelant garde l'ancien)
        return {"ok": False, "error": "analytics indisponible",
                "eligible": 0, "total": 0, "links": len(all_ids), "per_model": per_model}
    if failed_batches:
        # PARTIEL : des lots ont échoué (429/timeout). Renvoyer « ok » avec un
        # total amputé le faisait FIGER en cache dans la Facture (clics FR
        # sous-comptés à vie pour ce mois). On signale l'échec : l'appelant
        # conserve sa dernière valeur complète.
        print(f"[gms] fr_market_eligible_clicks PARTIEL : {failed_batches}/{len(chunks)} lots KO "
              f"-> valeur ignorée (eligible={eligible})", flush=True)
        return {"ok": False, "error": f"lecture partielle ({failed_batches} lot(s) sur {len(chunks)})",
                "partial": True, "partial_eligible": eligible, "partial_total": total,
                "eligible": 0, "total": 0, "links": len(all_ids), "per_model": per_model}
    return {"ok": True, "eligible": eligible, "total": total,
            "links": len(all_ids), "per_model": per_model, "source": source,
            "batches_ok": ok_batches, "batches": len(chunks)}


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

    # Detecte le workspace du template (marché FR ou Threads US…).
    # Seed sur le workspace préféré de l'identité (ex: hybride -> Threads US) pour
    # ne pas mal-détecter si un scan répond avant un autre.
    team_id = IDENTITY_TEAM.get(ident)
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
