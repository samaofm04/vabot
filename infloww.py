"""Lecture de l'API officielle d'Infloww — un module À PART.

Rien d'existant n'importe ce fichier : ni le podium, ni MyPuls, ni les bots.
Le propriétaire l'a voulu ainsi pour ne rien casser de ce qui tourne. Si
l'API tombe, seule la page /infloww le dit ; le reste continue comme avant.

L'API (doc : infloww-openapi.stoplight.io, spéc. OpenAPI 1.4) est en LECTURE
SEULE et répond sur https://openapi.infloww.com/v1/...

DEUX EN-TÊTES, SANS QUOI CLOUDFLARE BLOQUE TOUT. `Authorization` porte la clé
brute (sans « Bearer »), et `x-oid` l'identifiant d'agence. Sans `x-oid`, la
requête ne passe même pas le pare-feu : la page « you have been blocked » de
Cloudflare, et pas une erreur de l'API — 64 essais l'ont montré avant de lire
la doc. L'identifiant d'agence est le nombre inscrit dans la clé elle-même
(« st_ifw_<oid>… »), vérifié : la clé seule suffit à le retrouver.

Les pièges de l'API, tous rencontrés :
- les compteurs, les montants ET les identifiants arrivent en TEXTE
  (« "210" ») : on les convertit, sans quoi une somme concatène au lieu
  d'additionner. Les montants sont en CENTIMES ;
- une requête couvre 31 jours au plus : au-delà, « Query time span exceeds
  the maximum allowed days ». On découpe ;
- `endTime` est OBLIGATOIRE (la doc le dit facultatif) et ne peut pas être
  dans le futur : « must be a past or present time » ;
- les listes (liens, messages automatiques, envois de masse) sont filtrées
  par DATE DE CRÉATION, pas par activité : pour les avoir toutes, il faut
  remonter tranche par tranche — y compris AVANT la connexion à Infloww :
  53 des 124 liens de Jessye datent d'avant, dont le plus gros ;
- une vente remboursée RESTE dans /v1/transactions, statut « undo », montant
  plein : il faut l'exclure ;
- les rapports /v1/creator-report/* répondent 200 même quand la clé n'a pas
  le droit de lire une créatrice : le refus est dans un champ `errors` à la
  racine. Il est remonté (_liste), jamais ignoré ;
- /v1/linkfans double certaines lignes et son curseur veut dire « id
  strictement inférieur » : on repart de dernier id + 1, puis on dédoublonne ;
- /v1/creator/status-change-log trie par id croissant mais pagine vers le
  bas : on n'y suit jamais le curseur ;
- les données d'OnlyFans arrivent avec 2 à 4 heures de retard.

LA PAGE /infloww a six vues, et chacune n'appelle QUE ses adresses
(ADRESSES) : le quota est de 1 000 requêtes/minute pour toute l'agence.
"""
from __future__ import annotations

import contextvars
import datetime as dt
import html as _html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CLE_FICHIER = DATA_DIR / "infloww_api_key"
CONFIG_FICHIER = DATA_DIR / "infloww_config.json"
CACHE_FICHIER = DATA_DIR / "infloww_cache.json"

BASE = "https://openapi.infloww.com"
FENETRE_MAX_JOURS = 31
CACHE_S = 600            # dix minutes : l'API plafonne à 1 000 requêtes/minute par agence
CACHE_PASSE_S = 3600     # une tranche passée bouge peu : une heure
CACHE_LONG_S = 6 * 3600  # affectations, facture : quasi immobiles
CACHE_MAX = 1500         # entrées ; 200 ne suffisaient plus (un jour de chat = une entrée)
PLATEFORME = "OnlyFans"
DEVISE = "USD"
# Un an d'historique : au-delà, les adresses qui le documentent (366 jours)
# rendent une liste VIDE sans erreur. On le dit sur la page.
HISTORIQUE_JOURS = 365
# Le journal des statuts n'existe qu'à partir de là (doc, et vérifié : vide avant).
JOURNAL_DEPUIS = dt.date(2026, 6, 1)
PAGES_MAX = 100          # garde-fou de pagination ; atteint, il est DIT sur la page
PAGES_FANS_MAX = 150     # le plus gros lien (4 723 fans, lignes doublées) en demande ~95
EN_MEME_TEMPS = 4        # requêtes simultanées au plus, toutes pages confondues
JOURS_CHAT_MAX = 31      # le détail jour par jour du chat coûte un appel par jour

# Les créatrices suivies ici. Jessye seulement, pour commencer : c'est le
# marché US que le propriétaire veut regarder avec cette source. Les autres
# (Emy, Khloe) s'ajoutent dans data/infloww_config.json : {"suivies": [...]}.
SUIVIES = ["jessyewdiference"]

PERIODES = (7, 30, 90)
VUES = (("apercu", "Vue d'ensemble"), ("revenus", "Revenus"), ("equipe", "Équipe"),
        ("marketing", "Marketing"), ("messages", "Messages"), ("journal", "Journal"))
NOMS_VUES = dict(VUES + (("lien", "Fans d'un lien"),))
TYPES_LIEN = ("TRACKING", "TRIAL", "CAMPAIGN")
TRIS_LIENS = ("revenus", "abonnes", "clics", "date")

# Ce que chaque vue a le droit d'appeler — et rien d'autre. Les tests le
# vérifient : charger les 23 adresses à chaque affichage userait le quota.
ADRESSES: Dict[str, Tuple[str, ...]] = {
    "apercu": ("/v1/creators", "/v1/creator-report/fans/subscriber-count",
               "/v1/creator-report/fans/count", "/v1/creator-report/fans/renew-on",
               "/v1/creator-report/fans/avg-subscription-length",
               "/v1/creator-report/reach/profile-visitor-count", "/v1/creator-report/rank"),
    "revenus": ("/v1/creators", "/v1/transactions", "/v1/refunds",
                "/v1/invoice-data/monthly-billing"),
    "equipe": ("/v1/creators", "/v1/transaction-perf/details", "/v1/employees",
               "/v1/employees/assigned-creators", "/v1/employee-report/employee-sales-summary",
               "/v1/employee-report/employee-chat-summary"),
    "marketing": ("/v1/creators", "/v1/links"),
    "lien": ("/v1/creators", "/v1/links", "/v1/linkfans"),
    "messages": ("/v1/creators", "/v1/creator-report/chat-summary", "/v1/automated-messages",
                 "/v1/priority-mass-messages", "/v1/employees"),
    "journal": ("/v1/creators", "/v1/all-creators", "/v1/creator/status-change-log",
                "/v1/transaction-perf/manual-assignment/details", "/v1/employees"),
}

# Titre et adresse de chaque section : une section en panne dit laquelle.
SECTIONS: Dict[str, Tuple[str, str]] = {
    "jours": ("Nouveaux abonnés", "/v1/creator-report/fans/subscriber-count"),
    "fans": ("Fans actifs et expirés", "/v1/creator-report/fans/count"),
    "renouv_auto": ("Renouvellement automatique", "/v1/creator-report/fans/renew-on"),
    "duree": ("Durée moyenne d'abonnement", "/v1/creator-report/fans/avg-subscription-length"),
    "visiteurs": ("Visiteurs du profil", "/v1/creator-report/reach/profile-visitor-count"),
    "rang": ("Classement OnlyFans", "/v1/creator-report/rank"),
    "ventes": ("Ventes", "/v1/transactions"),
    "remboursements": ("Remboursements", "/v1/refunds"),
    "facture": ("Facture Infloww de l'agence", "/v1/invoice-data/monthly-billing"),
    "perf": ("Ventes attribuées aux chatteurs", "/v1/transaction-perf/details"),
    "employes": ("Annuaire des employés", "/v1/employees"),
    "affectations": ("Équipe affectée à la créatrice", "/v1/employees/assigned-creators"),
    "rapport_ventes": ("Ventes par employé (rapport Infloww)",
                       "/v1/employee-report/employee-sales-summary"),
    "rapport_chat": ("Chat par employé (rapport Infloww)",
                     "/v1/employee-report/employee-chat-summary"),
    "liens": ("Liens de suivi", "/v1/links"),
    "essais": ("Liens d'essai gratuit", "/v1/links"),
    "campagnes": ("Promotions de profil", "/v1/links"),
    "lien_info": ("Le lien", "/v1/links"),
    "fans_lien": ("Fans arrivés par ce lien", "/v1/linkfans"),
    "chat": ("Messages envoyés", "/v1/creator-report/chat-summary"),
    "automatiques": ("Messages automatiques", "/v1/automated-messages"),
    "prioritaires": ("Envois de masse prioritaires", "/v1/priority-mass-messages"),
    "toutes": ("Créatrices de l'agence", "/v1/all-creators"),
    "statuts": ("Connexions et déconnexions des comptes", "/v1/creator/status-change-log"),
    "reassign": ("Ventes réattribuées à la main", "/v1/transaction-perf/manual-assignment/details"),
}

# Le 403 « Scope validation failure » de ces adresses ne vient pas du code :
# la clé n'a pas la portée. Vérifié : les paramètres passent la validation
# (limit=101 donne bien 400) avant d'échouer sur le droit.
_PORTEE_ORGA = ("Il manque à la clé API la portée « Organization scope ». À ouvrir dans "
                "Infloww, page de gestion des clés API (modifier la clé, ou en créer une qui "
                "l'a). Rien à corriger dans le code : la section s'affichera d'elle-même.")
_PORTEE_EMPL = ("La clé API n'a pas le périmètre employés des rapports. Dans Infloww, page de "
                "gestion des clés API : « Employee access » → « All employees ». Rien à "
                "corriger dans le code : la section s'affichera d'elle-même.")
PORTEES = {
    "/v1/transaction-perf/manual-assignment/details": _PORTEE_ORGA,
    "/v1/invoice-data/monthly-billing": _PORTEE_ORGA,
    "/v1/employee-report/employee-sales-summary": _PORTEE_EMPL,
    "/v1/employee-report/employee-chat-summary": _PORTEE_EMPL,
}


class ErreurInfloww(Exception):
    """Une erreur de l'API, avec l'identifiant que le support réclame."""

    def __init__(self, message: str, code: int = 0, request_id: str = ""):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


# ─── accès ───────────────────────────────────────────────────────────────
def cle() -> str:
    v = (os.environ.get("INFLOWW_API_KEY") or "").strip()
    if v:
        return v
    for p in (CLE_FICHIER, Path.home() / ".config" / "infloww_api_key"):
        try:
            v = p.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    return ""


def _config() -> Dict[str, Any]:
    # Un fichier réglé à la main peut contenir autre chose qu'un objet (une
    # simple liste de pseudos, observé en relecture) : sans ce contrôle,
    # `.get` levait et la page entière tombait en erreur 500.
    try:
        c = safe_json.load(CONFIG_FICHIER, default={}) or {}
    except Exception:
        return {}
    return c if isinstance(c, dict) else {}


def oid(k: Optional[str] = None) -> str:
    """L'identifiant d'agence : réglé à la main, sinon lu dans la clé."""
    v = str(_config().get("oid") or "").strip()
    if v:
        return v
    m = re.match(r"^st_ifw_(\d{8,20})", k if k is not None else cle())
    return m.group(1) if m else ""


def configure() -> bool:
    return bool(cle() and oid())


def suivies() -> List[str]:
    v = _config().get("suivies") or SUIVIES
    if isinstance(v, str):  # « "suivies": "jessyewdiference" » : un seul pseudo
        v = [v]
    if not isinstance(v, (list, tuple)):
        return list(SUIVIES)
    return [str(s).strip() for s in v if str(s).strip()] or list(SUIVIES)


# ─── suivi d'une page : combien d'appels, et depuis quand date le cache ───
# Une variable de contexte et non un global : deux pages ouvertes en même
# temps ne mélangent pas leurs comptes. Les fils de _parallele en reçoivent
# une copie qui pointe sur le même dict.
_SUIVI: contextvars.ContextVar = contextvars.ContextVar("infloww_suivi", default=None)
_VERROU = threading.RLock()


def _noter(appel: int = 0, cache: int = 0, t: Optional[float] = None) -> None:
    s = _SUIVI.get()
    if s is None:
        return
    with _VERROU:
        s["appels"] = s.get("appels", 0) + appel
        s["caches"] = s.get("caches", 0) + cache
        if t is not None:
            s["plus_ancien"] = min(s.get("plus_ancien") or t, t)


# ─── appels ──────────────────────────────────────────────────────────────
# Quatre requêtes en vol au plus, pour tout le processus : les vues lisent en
# parallèle, mais le quota est partagé avec le reste de l'agence.
_RESEAU = threading.BoundedSemaphore(EN_MEME_TEMPS)


def _get(chemin: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """GET sur l'API. Lève ErreurInfloww avec ce qui permet de comprendre."""
    k = cle()
    if not k:
        raise ErreurInfloww("clé API Infloww absente (data/infloww_api_key)")
    o = oid(k)
    if not o:
        raise ErreurInfloww("identifiant d'agence (x-oid) introuvable")
    _noter(appel=1)
    url = BASE + chemin + "?" + urllib.parse.urlencode(params, doseq=True)
    for essai in range(3):
        req = urllib.request.Request(url, headers={
            "Authorization": k, "x-oid": o, "Accept": "application/json",
            "User-Agent": "youl4b/1.0"})
        try:
            with _RESEAU:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            brut = e.read(2000)
            rid = e.headers.get("x-request-id") or ""
            if e.code == 429 and essai < 2:
                time.sleep(2 + 3 * essai)
                continue
            if b"Cloudflare" in brut:
                raise ErreurInfloww("bloqué par Cloudflare (en-têtes d'accès refusés)",
                                    e.code, rid)
            try:
                msg = json.loads(brut).get("errorMessage") or brut.decode("utf-8", "replace")
            except Exception:
                msg = brut.decode("utf-8", "replace")
            raise ErreurInfloww(str(msg)[:200], e.code, rid)
        except urllib.error.URLError as e:
            if essai < 2:
                time.sleep(2)
                continue
            raise ErreurInfloww(f"réseau : {e.reason}")
    raise ErreurInfloww("trop de requêtes (429) malgré les reprises", 429)


def _liste(d: Any) -> List[Dict[str, Any]]:
    """data.list d'une réponse — et le refus caché dans `errors`, remonté.

    Vérifié sur /v1/creator-report/rank : une créatrice hors du périmètre de
    la clé rend 200 avec une liste vide et {"errors": [{"creatorId", "errorMessage":
    "Scope validation failure"}]} à la racine. Sans ce contrôle, la page
    afficherait « zéro » là où la clé n'a simplement pas le droit de lire.
    """
    if not isinstance(d, dict):
        return []
    errs = d.get("errors") or []
    if errs:
        det = "; ".join(f'{x.get("creatorId") or x.get("employeeId") or "?"} : '
                        f'{x.get("errorMessage") or x}' if isinstance(x, dict) else str(x)
                        for x in errs)
        raise ErreurInfloww(f"Infloww refuse une partie de la demande ({det})", 200)
    data = d.get("data")
    lst = data.get("list") if isinstance(data, dict) else None
    return [x for x in lst if isinstance(x, dict)] if isinstance(lst, list) else []


def _pages(chemin: str, params: Dict[str, Any], pages_max: int = PAGES_MAX
           ) -> Tuple[List[Dict[str, Any]], bool]:
    """Toutes les pages d'une liste. Renvoie (lignes, tronquée ?).

    `cursor` = id de la dernière ligne, renvoyé tel quel (vérifié sur
    transactions, remboursements, liens, employés). Si le garde-fou arrête la
    lecture, ou si l'API dit « encore » sans donner de curseur, la liste est
    marquée tronquée : la page le dira au lieu de faire croire au total.
    """
    lot: List[Dict[str, Any]] = []
    cur: Any = None
    for _ in range(pages_max):
        p = dict(params)
        if cur is not None:
            p["cursor"] = cur
        d = _get(chemin, p)
        lot += _liste(d)
        if not (isinstance(d, dict) and d.get("hasMore")):
            return lot, False
        cur = d.get("cursor")
        if cur in (None, ""):
            return lot, True
    return lot, True


# ─── cache ───────────────────────────────────────────────────────────────
# Le fichier est relu seulement s'il a changé sur le disque : une vue peut
# faire cent lectures, et relire à chaque fois un cache de quelques Mo
# coûtait plus cher que l'API elle-même.
_MEMO: Dict[str, Any] = {"chemin": "", "mtime": None, "cache": {}}


def _cache_lu() -> Dict[str, Any]:
    p = CACHE_FICHIER
    try:
        mt = p.stat().st_mtime_ns
    except OSError:
        mt = None
    if _MEMO["chemin"] != str(p) or _MEMO["mtime"] != mt:
        try:
            c = safe_json.load(p, default={}) or {}
        except Exception:
            c = {}
        _MEMO.update(chemin=str(p), mtime=mt, cache=c if isinstance(c, dict) else {})
    return _MEMO["cache"]


def _cache_frais(cle_cache: str, duree: int) -> Optional[Dict[str, Any]]:
    with _VERROU:
        ent = _cache_lu().get(cle_cache) or {}
    if ent and time.time() - float(ent.get("t") or 0) < duree:
        return ent
    return None


def _avec_cache(cle_cache: str, fabrique, duree: int = CACHE_S):
    """Relit le cache s'il a moins de `duree` secondes, sinon rappelle l'API.

    Un échec n'est jamais mis en cache : la page suivante doit réessayer, pas
    servir une erreur pendant dix minutes. L'appel à l'API se fait HORS du
    verrou : les lectures parallèles ne s'attendent pas les unes les autres.
    """
    ent = _cache_frais(cle_cache, duree)
    if ent is not None:
        _noter(cache=1, t=float(ent["t"]))
        return ent.get("v"), float(ent["t"])
    v = fabrique()
    t = time.time()
    with _VERROU:
        cache = _cache_lu()
        # Une entrée plus vieille que la plus longue durée de vie ne resservira
        # jamais : sans ce ménage, chaque jour ajoutait ses fenêtres (elles
        # glissent avec la date) et le fichier ne faisait que grossir jusqu'au
        # plafond, relu en entier à chaque changement.
        for k in [k for k, e in cache.items()
                  if t - float((e or {}).get("t") or 0) >= CACHE_LONG_S]:
            cache.pop(k, None)
        cache[cle_cache] = {"t": t, "v": v}
        # plafond en plus, au cas où une seule journée en créerait trop
        if len(cache) > CACHE_MAX:
            for k in sorted(cache, key=lambda x: float(cache[x].get("t") or 0))[:len(cache) - CACHE_MAX]:
                cache.pop(k, None)
        safe_json.write_text(CACHE_FICHIER, json.dumps(cache, ensure_ascii=False))
        try:
            _MEMO["mtime"] = CACHE_FICHIER.stat().st_mtime_ns
        except OSError:
            pass
    _noter(t=t)
    return v, t


def _parallele(fonctions: List[Callable[[], Any]]) -> List[Tuple[Any, Optional[ErreurInfloww]]]:
    """Lance des lectures indépendantes ; rend, dans l'ordre, (valeur, erreur).

    Sans ça, 30 jours de chat jour par jour ou un an de liens se lisaient un
    appel après l'autre : dix à vingt secondes d'attente au premier affichage.
    Une erreur est RENDUE, pas avalée : l'appelant décide quoi en dire.
    """
    def un(fn):
        try:
            return fn(), None
        except ErreurInfloww as e:
            return None, e
        except Exception as e:  # une réponse de forme imprévue, dite sur la page
            return None, ErreurInfloww(f"{type(e).__name__} : {e}")
    if len(fonctions) <= 1:
        return [un(f) for f in fonctions]
    with ThreadPoolExecutor(max_workers=min(EN_MEME_TEMPS, len(fonctions))) as ex:
        futs = [ex.submit(contextvars.copy_context().run, un, f) for f in fonctions]
        return [f.result() for f in futs]


def _sections(out: Dict[str, Any], taches: List[Tuple[str, Callable[[], Any]]]) -> None:
    """Chaque section pour elle-même : une adresse en panne n'efface pas la page."""
    res = _parallele([f for _, f in taches])
    for (cle_, _), (v, e) in zip(taches, res):
        if e is not None:
            out.setdefault("erreurs", {})[cle_] = e
        else:
            out[cle_] = v


# ─── conversions ─────────────────────────────────────────────────────────
def _n(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _f(v: Any) -> Optional[float]:
    """Un nombre à virgule : le classement arrive en « 1.70 », que _n
    tronquerait en 1. Tolère « Top 5% » (l'exemple de la doc)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = re.sub(r"[^0-9.\-]", "", str(v).replace(",", "."))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _vrai(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def _tranches(debut: dt.date, fin: dt.date, jours: int = FENETRE_MAX_JOURS):
    """[debut, fin] découpé en morceaux de `jours` jours au plus."""
    d = debut
    while d <= fin:
        f = min(fin, d + dt.timedelta(days=jours - 1))
        yield d, f
        d = f + dt.timedelta(days=1)


def _aujourdhui() -> dt.date:
    # UTC et non l'heure locale : à 0 h 30 à Paris, la date locale est déjà
    # « demain » pour l'API, qui refuse alors endTime « dans le futur ».
    return dt.datetime.now(dt.timezone.utc).date()


def _maintenant() -> dt.datetime:
    # une minute de marge : endTime dans le futur est refusé
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(minutes=1)


_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def _ms(t: dt.datetime) -> str:
    # en entiers : timestamp()*1000 arrondit 23:59:59.999 à ...998
    return str((t - _EPOCH) // dt.timedelta(milliseconds=1))


def _tranches_heure(debut: dt.date, fin: dt.date, jours: int = FENETRE_MAX_JOURS):
    """Tranches en millisecondes UTC, de 00:00:00.000 à 23:59:59.999.

    En millisecondes et pas en « …T23:59:59Z » : une vente horodatée à
    23:59:59.5 tombait entre deux tranches. Le format ms est accepté partout
    (vérifié sur transactions, liens, journal des statuts).
    """
    m = _maintenant()
    for a, b in _tranches(debut, min(fin, m.date()), jours):
        s = dt.datetime.combine(a, dt.time(0, 0), dt.timezone.utc)
        e = min(dt.datetime.combine(b, dt.time(23, 59, 59, 999000), dt.timezone.utc), m)
        if e > s:
            yield a, b, _ms(s), _ms(e)


def _duree_pour(b: dt.date, recent_jours: int = 1) -> int:
    """Dix minutes pour ce qui bouge encore, une heure pour le passé."""
    return CACHE_S if b >= _aujourdhui() - dt.timedelta(days=recent_jours) else CACHE_PASSE_S


def _jour_utc(ms: Any) -> str:
    v = _n(ms)
    return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc).date().isoformat() if v else ""


def _quand(ms: Any) -> str:
    v = _n(ms)
    return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M") if v else ""


def _texte_html(s: Any, n: int = 160) -> str:
    """Le texte d'un message (Infloww l'envoie en HTML « <p>… {name} …</p> »),
    sans balises — échappé ensuite comme tout le reste."""
    # le contenu d'un script ou d'un style n'est pas du texte : sans ça,
    # « <b>welcome</b><script>x</script> » s'affichait « welcomex »
    t = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", str(s or ""), flags=re.I | re.S)
    t = re.sub(r"<br\s*/?>|</p>|</div>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]*>", "", t)
    t = re.sub(r"\s+", " ", _html.unescape(t)).strip()
    return t if len(t) <= n else t[:n - 1] + "…"


# ─── lectures : créatrices ───────────────────────────────────────────────
def creatrices() -> List[Dict[str, Any]]:
    """Les créatrices connectées à Infloww que la clé a le droit de lire."""
    def f():
        # limit=100 : par défaut l'API n'en rend que 10
        return _pages("/v1/creators", {"limit": 100})[0]
    return _avec_cache("creators", f)[0]


def creatrice(pseudo: str) -> Optional[Dict[str, Any]]:
    p = str(pseudo or "").lower()
    for c in creatrices():
        if str(c.get("userName") or "").lower() == p:
            return c
    return None


def _creatrice_ou_erreur(pseudo: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    toutes = creatrices()
    p = str(pseudo or "").lower()
    for c in toutes:
        if str(c.get("userName") or "").lower() == p:
            return c, toutes
    raise ErreurInfloww(f"« {pseudo} » n'est pas connectée à Infloww, ou la clé "
                        "n'a pas le droit de la lire")


def _connexion(c: Dict[str, Any]) -> Optional[dt.date]:
    """createdTime d'une créatrice = sa CONNEXION à Infloww (vérifié : Emy,
    liée le 2026-08-10 dans le journal des statuts), pas la création du compte."""
    j = _jour_utc(c.get("createdTime"))
    return dt.date.fromisoformat(j) if j else None


def toutes_creatrices() -> List[Dict[str, Any]]:
    """Toutes les créatrices de l'agence, déconnectées et supprimées comprises."""
    def f():
        return [{"id": str(x.get("id") or ""), "pid": str(x.get("platformPid") or ""),
                 "nom": str(x.get("name") or ""), "surnom": str(x.get("nickName") or ""),
                 "pseudo": str(x.get("userName") or ""), "statut": str(x.get("status") or ""),
                 "connexion": _n(x.get("createdTime")), "suppression": _n(x.get("deletedTime"))}
                for x in _pages("/v1/all-creators", {"limit": 100})[0]]
    return _avec_cache("all-creators", f)[0]


# ─── lectures : rapports /v1/creator-report/* ────────────────────────────
def _fenetre_rapport(prefixe: str, chemin: str, creator_id: str, a: dt.date, b: dt.date
                     ) -> List[Dict[str, Any]]:
    """Une fenêtre d'un rapport (dates seules, 31 jours au plus), en cache."""
    auj = _aujourdhui()

    def fab():
        p = {"creatorIds": creator_id, "platformCode": PLATEFORME,
             "startTime": a.isoformat(), "endTime": b.isoformat()}
        try:
            d = _get(chemin, p)
        except ErreurInfloww as e:
            # « past or present time » le jour même : l'horloge d'Infloww n'est
            # pas forcément en UTC. On relit sans aujourd'hui plutôt que de
            # perdre toute la tranche.
            if "past or present" in str(e) and b >= auj and b > a:
                p["endTime"] = (b - dt.timedelta(days=1)).isoformat()
                d = _get(chemin, p)
            else:
                raise
        return _liste(d)
    # un jour passé ne change plus : on le garde une heure, pas dix minutes
    return _avec_cache(f"{prefixe}:{creator_id}:{a}:{b}", fab, _duree_pour(b))[0] or []


def _rapport(prefixe: str, chemin: str, creator_id: str, debut: dt.date, fin: dt.date,
             normaliser: Callable[[Dict[str, Any]], Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Un rapport jour par jour sur n'importe quelle durée, trié par date.

    Les jours sans donnée sont ABSENTS de la réponse, pas mis à zéro (vérifié
    sur la durée d'abonnement : 29 lignes pour 31 jours). La page indexe donc
    par date, jamais par rang de ligne.
    """
    fin = min(fin, _aujourdhui())
    taches = [lambda a=a, b=b: _fenetre_rapport(prefixe, chemin, creator_id, a, b)
              for a, b in _tranches(debut, fin)]
    out: List[Dict[str, Any]] = []
    for v, e in _parallele(taches):
        if e is not None:
            raise e
        out += [normaliser(x) for x in v or []]
    out.sort(key=lambda x: str(x.get("date") or ""))
    return out


def abonnes_par_jour(creator_id: str, debut: dt.date, fin: dt.date) -> List[Dict[str, Any]]:
    """[{date, nouveaux, renouvellements}] jour par jour, sur n'importe quelle durée."""
    return _rapport("subs", "/v1/creator-report/fans/subscriber-count", creator_id, debut, fin,
                    lambda x: {"date": str(x.get("date")),
                               "nouveaux": _n(x.get("newSubscribers")),
                               "renouvellements": _n(x.get("subscriberRenewals"))})


def fans_par_jour(creator_id: str, debut: dt.date, fin: dt.date) -> List[Dict[str, Any]]:
    """Fans actifs et expirés : des STOCKS (photo du jour), pas des flux."""
    return _rapport("fans", "/v1/creator-report/fans/count", creator_id, debut, fin,
                    lambda x: {"date": str(x.get("date")), "actifs": _n(x.get("activeFans")),
                               "expires": _n(x.get("expiredFans"))})


def renouvellement_auto(creator_id: str, debut: dt.date, fin: dt.date) -> List[Dict[str, Any]]:
    return _rapport("renew", "/v1/creator-report/fans/renew-on", creator_id, debut, fin,
                    lambda x: {"date": str(x.get("date")), "fans": _n(x.get("fansWithRenewOn"))})


def duree_abonnement(creator_id: str, debut: dt.date, fin: dt.date) -> List[Dict[str, Any]]:
    return _rapport("duree", "/v1/creator-report/fans/avg-subscription-length", creator_id,
                    debut, fin, lambda x: {"date": str(x.get("date")),
                                           "jours": _n(x.get("avgSubscriptionLength"))})


def visiteurs_profil(creator_id: str, debut: dt.date, fin: dt.date) -> List[Dict[str, Any]]:
    """Visiteurs du profil. Une ligne à 0/0/0 n'est pas une journée sans
    visite : OnlyFans remplit ce compteur d'un bloc, après coup (observé le
    25/09 à 21 h 41 UTC : 0/0/0 pour le jour même alors que 65 abonnés du jour
    étaient déjà là, 3 000 à 6 000 les autres jours). Toute ligne vide est
    donc marquée « en attente » et sortie des totaux, pas seulement celle du
    jour : la veille peut l'être aussi juste après minuit UTC."""
    def norm(x):
        v = {"date": str(x.get("date")), "total": _n(x.get("profileVisitors")),
             "invites": _n(x.get("guestProfileVisitors")),
             "connectes": _n(x.get("loggedInUsersProfileVisitors"))}
        v["attente"] = not (v["total"] or v["invites"] or v["connectes"])
        return v
    return _rapport("visites", "/v1/creator-report/reach/profile-visitor-count", creator_id,
                    debut, fin, norm)


def classement(creator_id: str, debut: dt.date, fin: dt.date) -> List[Dict[str, Any]]:
    """Le classement OnlyFans en pourcentage (« 1.70 » = top 1,70 %) : plus bas = mieux."""
    return _rapport("rang", "/v1/creator-report/rank", creator_id, debut, fin,
                    lambda x: {"date": str(x.get("date")), "rang": _f(x.get("performanceRank")),
                               "brut": str(x.get("performanceRank") or "")})


def chat_resume(creator_id: str, debut: dt.date, fin: dt.date) -> Dict[str, Any]:
    """Messages envoyés par le compte : la période par tranches, et le détail
    jour par jour sur les 31 derniers jours au plus.

    Pas de date dans la réponse : UNE ligne pour toute la fenêtre. D'où un
    appel par jour pour le détail. Et deux pièges vérifiés sur 20→24/09 :
    fansChatted est DÉDOUBLONNÉ sur la fenêtre (249 en additionnant les jours,
    174 sur la fenêtre) et replyTime est une moyenne PONDÉRÉE. On ne les
    recalcule donc jamais en additionnant des jours.
    """
    auj = _aujourdhui()
    fin = min(fin, auj)

    def norm(lst):
        x = lst[0] if lst else None
        if x is None:
            return {"vide": True}
        return {"messages": _n(x.get("messagesSent")), "ppv": _n(x.get("ppvsSent")),
                "fans": _n(x.get("fansChatted")), "reponse_ms": _n(x.get("replyTime"))}
    tr = list(_tranches(debut, fin))
    jd = max(debut, fin - dt.timedelta(days=JOURS_CHAT_MAX - 1))
    jours = [jd + dt.timedelta(days=i) for i in range((fin - jd).days + 1)]
    chemin = "/v1/creator-report/chat-summary"
    taches = [lambda a=a, b=b: _fenetre_rapport("chat", chemin, creator_id, a, b) for a, b in tr]
    taches += [lambda d=d: _fenetre_rapport("chatj", chemin, creator_id, d, d) for d in jours]
    res = _parallele(taches)
    tranches = []
    for (a, b), (v, e) in zip(tr, res[:len(tr)]):
        if e is not None:
            raise e
        tranches.append(dict(norm(v), debut=a.isoformat(), fin=b.isoformat()))
    par_jour = []
    for d, (v, e) in zip(jours, res[len(tr):]):
        if e is not None:
            par_jour.append({"date": d.isoformat(), "erreur": str(e)})
        else:
            par_jour.append(dict(norm(v), date=d.isoformat()))
    return {"tranches": tranches, "jours": par_jour, "jours_depuis": jd.isoformat()}


# ─── lectures : listes par tranches de dates-heures ──────────────────────
def _liste_par_tranches(prefixe: str, chemin: str, params: Dict[str, Any], debut: dt.date,
                        fin: dt.date, normaliser: Callable[[Dict[str, Any]], Dict[str, Any]],
                        recent: int = 1, duree: Optional[int] = None) -> Dict[str, Any]:
    """Une liste paginée, lue tranche de 31 jours par tranche de 31 jours.

    Les lignes sont réduites à ce que la page affiche AVANT d'aller en cache :
    un mois de ventes brutes pèse plusieurs centaines de Ko.
    """
    taches, bornes = [], []
    for a, b, s, e in _tranches_heure(debut, fin):
        def f(a=a, b=b, s=s, e=e):
            def fab():
                lot, tronque = _pages(chemin, dict(params, startTime=s, endTime=e))
                return {"l": [normaliser(x) for x in lot], "tronque": tronque}
            return _avec_cache(f"{prefixe}:{a}:{b}", fab,
                               duree if duree is not None else _duree_pour(b, recent))[0]
        taches.append(f)
        bornes.append((a, b))
    lignes, tronque = [], []
    for (a, b), (v, err) in zip(bornes, _parallele(taches)):
        if err is not None:
            raise err
        lignes += (v or {}).get("l") or []
        if (v or {}).get("tronque"):
            tronque.append(f"{a} → {b}")
    return {"lignes": lignes, "tronque": tronque, "tranches": len(bornes),
            "debut": debut.isoformat(), "fin": fin.isoformat()}


def _vente(x: Dict[str, Any]) -> Dict[str, Any]:
    """Une ligne de /v1/transactions, réduite. Montants en centimes (TEXTE à
    l'arrivée : « 2499 » = 24,99 $ ; fee = 20 %, net = amount − fee, vérifié
    ligne à ligne)."""
    return {"id": str(x.get("id") or ""), "tx": str(x.get("transactionId") or ""),
            "t": _n(x.get("createdTime")), "type": str(x.get("type") or "?"),
            "source": str(x.get("tipSource") or ""), "statut": str(x.get("status") or "?"),
            "brut": _n(x.get("amount")), "frais": _n(x.get("fee")), "net": _n(x.get("net")),
            "devise": str(x.get("currency") or DEVISE), "fan": str(x.get("fanId") or ""),
            "fan_nom": str(x.get("fanName") or "")}


def _vente_perf(x: Dict[str, Any]) -> Dict[str, Any]:
    """Une ligne de /v1/transaction-perf/details. salesAmount = le BRUT
    (157/157 identiques à amount), pas le net. attributeEmployeeId vide =
    vente rattachée à personne : l'équivalent d'« Indéterminé (Créatrice) »
    chez MyPuls, à ne jamais payer."""
    v = _vente(x)
    v.update(regle=str(x.get("salesRule") or ""), employe=str(x.get("attributeEmployeeId") or ""),
             attribue=_n(x.get("salesAmount")))
    return v


def ventes(creator_id: str, debut: dt.date, fin: dt.date) -> Dict[str, Any]:
    """Le registre des ventes. « loading » = retenue OnlyFans (~7 jours,
    resynchronisée toutes les 12 h) : les tranches de moins de 8 jours ne
    restent que dix minutes en cache."""
    return _liste_par_tranches(f"ventes:{creator_id}", "/v1/transactions",
                               {"creatorId": creator_id, "platformCode": PLATEFORME, "limit": 100},
                               debut, fin, _vente, recent=8)


def ventes_attribuees(creator_id: str, debut: dt.date, fin: dt.date) -> Dict[str, Any]:
    return _liste_par_tranches(f"perf:{creator_id}", "/v1/transaction-perf/details",
                               {"creatorId": creator_id, "platformCode": PLATEFORME, "limit": 100},
                               debut, fin, _vente_perf, recent=8)


def _remboursement(x: Dict[str, Any]) -> Dict[str, Any]:
    # transactionId = le hash OnlyFans (celui de /v1/transactions), pas l'id Infloww
    return {"id": str(x.get("id") or ""), "tx": str(x.get("transactionId") or ""),
            "fan": str(x.get("fanId") or ""), "paye": _n(x.get("paymentTime")),
            "rembourse": _n(x.get("refundTime")), "statut": str(x.get("paymentStatus") or ""),
            "montant": _n(x.get("paymentAmount")), "type": str(x.get("transactionType") or ""),
            "devise": str(x.get("currency") or DEVISE)}


def remboursements(creator_id: str, debut: dt.date, fin: dt.date) -> Dict[str, Any]:
    """Filtrés sur la date du REMBOURSEMENT, pas du paiement (vérifié)."""
    return _liste_par_tranches(f"rembours:{creator_id}", "/v1/refunds",
                               {"creatorId": creator_id, "platformCode": PLATEFORME, "limit": 100},
                               debut, fin, _remboursement, recent=8)


def facture_mensuelle() -> List[Dict[str, Any]]:
    """La facture Infloww de l'agence, mois par mois, sur douze mois.

    10 requêtes par minute sur CETTE adresse : six heures de cache.
    """
    auj = _aujourdhui()
    m = auj.year * 12 + auj.month - 1 - 11          # douze mois, bornes comprises
    debut = f"{m // 12:04d}-{m % 12 + 1:02d}"
    fin = f"{auj.year:04d}-{auj.month:02d}"

    def fab():
        return [{"periode": str(x.get("billingPeriod") or ""), "devise": str(x.get("currency") or DEVISE),
                 "facture": str(x.get("invoiceId") or ""),
                 **{k: (None if x.get(k) is None else _n(x.get(k)))
                    for k in ("subscription", "discount", "igic", "total", "deductions",
                              "balanceDue", "paid", "pending")}}
                for x in _liste(_get("/v1/invoice-data/monthly-billing",
                                     {"startTime": debut, "endTime": fin}))]
    return _avec_cache(f"facture:{debut}:{fin}", fab, CACHE_LONG_S)[0]


# ─── lectures : équipe ───────────────────────────────────────────────────
def employes() -> Dict[str, Any]:
    """L'annuaire. Statuts réels : Activated, Deactivated, Deleted et
    « Inactive », absent de la doc."""
    def fab():
        lot, tronque = _pages("/v1/employees", {"limit": 100})
        return {"liste": [{"id": str(x.get("employeeId") or ""), "nom": str(x.get("employeeName") or ""),
                           "statut": str(x.get("status") or ""), "cree": _n(x.get("createdTime")),
                           "supprime": _n(x.get("deletedTime"))} for x in lot],
                "tronque": tronque}
    return _avec_cache("employes", fab, CACHE_PASSE_S)[0]


def affectations(liste_employes: List[Dict[str, Any]], forcer: bool = False) -> Dict[str, Any]:
    """Qui est affecté à quelle créatrice.

    Il n'existe PAS de route créatrice → employés : un appel par employé.
    Soit ~73 appels ; on ne les lance que sur demande (forcer), puis on les
    garde six heures. Les employés supprimés ne sont pas interrogés : aucun
    des 19 n'avait d'affectation, et la page le dit.
    """
    a_lire = [e for e in liste_employes if e.get("statut") != "Deleted" and e.get("id")]
    ignores = len(liste_employes) - len(a_lire)
    cles = {e["id"]: f"affect:{e['id']}" for e in a_lire}
    manquants = [i for i, k in cles.items() if _cache_frais(k, CACHE_LONG_S) is None]
    if manquants and not forcer:
        return {"a_charger": len(manquants), "total": len(a_lire), "ignores": ignores}

    def lire(eid):
        def fab():
            lot, tronque = _pages("/v1/employees/assigned-creators", {"employeeId": eid, "limit": 100})
            return {"c": sorted({str(x.get("creatorId") or "") for x in lot} - {""}), "tronque": tronque}
        return _avec_cache(cles[eid], fab, CACHE_LONG_S)[0]
    ids = list(cles)
    par, errs = {}, {}
    for eid, (v, e) in zip(ids, _parallele([lambda eid=eid: lire(eid) for eid in ids])):
        if e is not None:
            errs[eid] = e
        else:
            par[eid] = v
    return {"par_employe": par, "erreurs": errs, "total": len(a_lire), "ignores": ignores}


def rapport_employes(chemin: str, prefixe: str, ids: List[str], debut: dt.date, fin: dt.date,
                     normaliser: Callable[[Dict[str, Any]], Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Les rapports par employé : 10 employés et 31 jours (dates seules) par requête.

    Lu tranche après tranche, et arrêté à la première erreur : aujourd'hui la
    clé n'a pas le droit (403 pour TOUT employé essayé), inutile d'user le
    quota à le redemander tranche par tranche.
    """
    fin = min(fin, _aujourdhui())
    out: List[Dict[str, Any]] = []
    for a, b in _tranches(debut, fin):
        for i in range(0, len(ids), 10):
            lot = ids[i:i + 10]

            def fab(a=a, b=b, lot=lot):
                return _liste(_get(chemin, {"employeeIds": ",".join(lot), "platformCode": PLATEFORME,
                                            "startTime": a.isoformat(), "endTime": b.isoformat()}))
            # les données employés ont jusqu'à 25 h de retard : deux jours « récents »
            v = _avec_cache(f"{prefixe}:{','.join(lot)}:{a}:{b}", fab, _duree_pour(b, 2))[0]
            out += [normaliser(x) for x in v or []]
    return out


def _ligne_ventes_employe(x: Dict[str, Any]) -> Dict[str, Any]:
    # la doc écrit tantôt platformPid, tantôt performerId : on prend les deux
    return {"employe": str(x.get("employeeId") or ""), "date": str(x.get("date") or ""),
            "pid": str(x.get("platformPid") or x.get("performerId") or ""),
            "ventes": _n(x.get("salesAmount")), "ppv": _n(x.get("ppvSalesAmount")),
            "tips": _n(x.get("tipsSalesAmount")), "dm": _n(x.get("directMessageSalesAmount")),
            "mm_prio": _n(x.get("priorityMassMessageSalesAmount")),
            "mm": _n(x.get("massMessageSalesAmount")), "devise": str(x.get("currency") or DEVISE)}


def _ligne_chat_employe(x: Dict[str, Any]) -> Dict[str, Any]:
    return {"employe": str(x.get("employeeId") or ""), "date": str(x.get("date") or ""),
            "pid": str(x.get("platformPid") or x.get("performerId") or ""),
            "dm": _n(x.get("directMessagesSent")), "ppv": _n(x.get("directPpvsSent")),
            "debloques": _n(x.get("ppvsUnlocked")), "fans": _n(x.get("fansChatted")),
            "caracteres": _n(x.get("characterCount")),
            "rep_prevue": _n(x.get("responseTimeBasedOnScheduledHours")),
            "rep_pointee": _n(x.get("responseTimeBasedOnClockedHours")),
            "golden": str(x.get("goldenRatio") or ""), "taux": str(x.get("unlockRate") or "")}


def _reassignation(x: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(x.get("id") or ""), "tx": str(x.get("transactionId") or ""),
            "perf": str(x.get("transactionPerfId") or ""), "operation": str(x.get("operationType") or ""),
            "par": str(x.get("operationEmployeeId") or ""),
            "avant": str(x.get("beforeAttributeEmployeeId") or ""),
            "apres": str(x.get("afterAttributeEmployeeId") or ""), "t": _n(x.get("createdTime"))}


def reassignations(debut: dt.date, fin: dt.date) -> Dict[str, Any]:
    """Toute l'agence (pas de creatorId) : le contrôle anti-triche de la paie."""
    return _liste_par_tranches("reassign", "/v1/transaction-perf/manual-assignment/details",
                               {"limit": 100}, debut, fin, _reassignation, recent=1)


def journal_statuts(creator_ids: List[str], depuis: dt.date) -> List[Dict[str, Any]]:
    """Connexions et déconnexions des comptes.

    PAGINATION CASSÉE, vérifiée : la page est triée par id CROISSANT mais le
    curseur filtre « id < curseur » ; le suivre fait relire la première ligne
    et perdre les plus récentes. On ne le suit donc jamais : limit=100, et si
    une fenêtre est pleine, on la relance à partir de la dernière heure lue + 1 ms.
    """
    depuis = max(depuis, JOURNAL_DEPUIS)
    out: Dict[str, Dict[str, Any]] = {}
    taches = []
    for a, b, s, e in _tranches_heure(depuis, _aujourdhui()):
        for i in range(0, len(creator_ids), 10):
            lot = creator_ids[i:i + 10]

            def f(a=a, b=b, s=s, e=e, lot=lot):
                def fab():
                    lignes, debut_ms = [], s
                    for _ in range(20):
                        page = _liste(_get("/v1/creator/status-change-log",
                                           {"creatorIds": ",".join(lot), "platformCode": PLATEFORME,
                                            "startTime": debut_ms, "endTime": e, "limit": 100}))
                        lignes += page
                        if len(page) < 100:
                            return {"l": lignes, "tronque": False}
                        debut_ms = str(max(_n(x.get("operationTime")) for x in page) + 1)
                    return {"l": lignes, "tronque": True}
                return _avec_cache(f"statuts:{','.join(lot)}:{a}:{b}", fab, _duree_pour(b))[0]
            taches.append(f)
    tronque = False
    for v, err in _parallele(taches):
        if err is not None:
            raise err
        tronque = tronque or bool((v or {}).get("tronque"))
        for x in (v or {}).get("l") or []:
            out[str(x.get("id"))] = {
                "id": str(x.get("id") or ""), "creatrice": str(x.get("creatorId") or ""),
                "pid": str(x.get("platformPid") or ""),
                "avant": x.get("statusBefore"), "apres": str(x.get("statusAfter") or ""),
                "t": _n(x.get("operationTime")), "par": str(x.get("operationEmployeeId") or "")}
    lignes = sorted(out.values(), key=lambda x: -x["t"])
    if tronque:
        lignes.insert(0, {"tronque": True})
    return lignes


# ─── lectures : liens, fans des liens ────────────────────────────────────
def _lien_norm(x: Dict[str, Any], type_lien: str) -> Dict[str, Any]:
    """Un lien, tous types. Montants en centimes ; epc*/aeps* TRONQUÉS à
    l'entier par Infloww (code 47 : epcGross « 59 » pour 59,62). subCount =
    fans abonnés VIA le lien depuis sa création (cumul), pas les abonnés
    actuels contrairement à la doc."""
    clics = x.get("clickCount")
    net = _n(x.get("earningsNet"))
    return {
        "id": str(x.get("id") or ""), "type": type_lien, "nom": str(x.get("name") or ""),
        "code": str(x.get("code") or ""), "source": str(x.get("source") or ""),
        "clics": None if clics is None else _n(clics), "abonnes": _n(x.get("subCount")),
        "payants": _n(x.get("payingFansCount")), "brut": _n(x.get("earningsGross")), "net": net,
        "devise": str(x.get("currency") or DEVISE),
        "conversion": str(x.get("subscriptionCVR") or "0"), "cvr_abo": _f(x.get("subscriptionCVR")),
        "cvr_achat": _f(x.get("spendingCVR")),
        "epc_brut": _n(x.get("epcGross")), "epc_net": _n(x.get("epcNet")),
        "aeps_brut": _n(x.get("aepsGross")), "aeps_net": _n(x.get("aepsNet")),
        "revenus": net / 100.0, "termine": _vrai(x.get("finishedFlag")),
        "cree": _jour_utc(x.get("createdTime")), "cree_ms": _n(x.get("createdTime")),
        "expire": _jour_utc(x.get("expiredTime")), "maj": _n(x.get("updatedTime")),
        "liste": str(x.get("defaultListName") or ""),
        "tags": [str(t) for t in (x.get("relTagNames") or []) if t],
        "duree_essai": _n(x.get("subDuration")), "limite": _n(x.get("subLimit")),
        "message": _texte_html(x.get("message"), 200), "remise": str(x.get("discount") or ""),
        "type_campagne": str(x.get("type") or "")}


def liens(creator_id: str, type_lien: str = "TRACKING", depuis: Optional[dt.date] = None
          ) -> Dict[str, Any]:
    """Tous les liens d'un type créés depuis `depuis` (un an par défaut).

    Un an et non depuis la connexion : les liens créés AVANT sont renvoyés,
    et l'ancienne version les ratait — 55 % des abonnés et 75 % du revenu net
    des liens de Jessye, dont le plus gros (code 47).
    """
    depuis = depuis or (_aujourdhui() - dt.timedelta(days=HISTORIQUE_JOURS))
    r = _liste_par_tranches(f"liens:{type_lien}:{creator_id}", "/v1/links",
                            {"creatorId": creator_id, "linkType": type_lien,
                             "platformCode": PLATEFORME, "limit": 100},
                            depuis, _aujourdhui(), lambda x: _lien_norm(x, type_lien), recent=1)
    uniques: Dict[str, Dict[str, Any]] = {}
    for x in r["lignes"]:
        uniques[x["id"]] = x
    return {"liens": list(uniques.values()), "tronque": r["tronque"], "depuis": depuis.isoformat(),
            "doublons": len(r["lignes"]) - len(uniques)}


def liens_suivi(creator_id: str, depuis: dt.date) -> List[Dict[str, Any]]:
    """Tous les liens de suivi créés depuis `depuis`, avec leurs compteurs.

    Les compteurs (clics, abonnés) sont CUMULÉS depuis la création du lien,
    comme sur OnlyFans — ce n'est pas l'activité de la période.
    """
    out = liens(creator_id, "TRACKING", depuis)["liens"]
    out.sort(key=lambda x: (-x["abonnes"], -(x["clics"] or 0)))
    return out


CATEGORIES_FANS = (("abonnement", "subscriptionEarning"), ("posts", "postsEarning"),
                   ("messages", "messagesEarning"), ("streams", "streamsEarning"),
                   ("tips", "tipsEarning"))


def _fan_norm(x: Dict[str, Any]) -> Dict[str, Any]:
    f = {"id": str(x.get("id") or ""), "fan": str(x.get("fanId") or ""),
         "nom": str(x.get("fanName") or ""), "t": _n(x.get("subscribedTime")),
         "devise": str(x.get("currency") or DEVISE)}
    for k, api in CATEGORIES_FANS:
        f[k] = [_n(x.get(api + "Gross")), _n(x.get(api + "Net"))]
    f["total_brut"] = sum(f[k][0] for k, _ in CATEGORIES_FANS)
    f["total_net"] = sum(f[k][1] for k, _ in CATEGORIES_FANS)
    return f


def fans_lien(creator_id: str, type_lien: str, lien_id: str) -> Dict[str, Any]:
    """Les fans arrivés par un lien, dédoublonnés, et ce qu'ils ont dépensé.

    DEUX PIÈGES vérifiés sur le lien code 2 (476 lignes pour 247 fans) :
    1. des fans figurent deux fois, même id, parfois avec des gains différents
       (0 et 500) : on garde la ligne au total MAXIMAL — garder la première
       donnait 13 887 c au lieu de 56 587 ;
    2. le curseur veut dire « id strictement inférieur » : une page coupée
       entre deux jumeaux perdait le second. On repart de dernier id + 1, ce
       qui relit la paire entière, puis on dédoublonne.
    En cache : les fans qui ont payé en détail, les autres seulement comptés
    (94 % des fans n'ont rien dépensé ; 4 723 fiches pèseraient 1 Mo).
    """
    def fab():
        par_id: Dict[str, Dict[str, Any]] = {}
        recues, pages, cur, tronque = 0, 0, None, False
        while True:
            p = {"creatorId": creator_id, "platformCode": PLATEFORME, "linkType": type_lien,
                 "linkId": lien_id, "limit": 100}
            if cur is not None:
                p["cursor"] = cur
            d = _get("/v1/linkfans", p)
            lot = _liste(d)
            pages += 1
            recues += len(lot)
            for x in lot:
                f = _fan_norm(x)
                g = par_id.get(f["id"])
                if g is None or f["total_brut"] > g["total_brut"]:
                    par_id[f["id"]] = f
            if not (isinstance(d, dict) and d.get("hasMore")) or not lot:
                break
            ids = [int(i) for i in (str(y.get("id") or "") for y in lot) if i.isdigit()]
            if not ids:
                tronque = True       # pas d'id numérique : impossible d'avancer, on le dit
                break
            suivant = str(min(ids) + 1)
            if suivant == cur:
                # la page n'a rendu que la paire déjà relue (les deux jumeaux
                # sont donc lus) : on passe en dessous, sinon on tournerait en rond
                suivant = str(min(ids))
            if suivant == cur or pages >= PAGES_FANS_MAX:
                tronque = True       # aucune avancée possible, ou garde-fou : on s'arrête, et on le dit
                break
            cur = suivant
        fans = list(par_id.values())
        par_mois: Dict[str, int] = {}
        totaux = {k: [0, 0] for k, _ in CATEGORIES_FANS}
        for f in fans:
            m = _jour_utc(f["t"])[:7] or "?"
            par_mois[m] = par_mois.get(m, 0) + 1
            for k, _ in CATEGORIES_FANS:
                totaux[k][0] += f[k][0]
                totaux[k][1] += f[k][1]
        payants = sorted((f for f in fans if f["total_brut"] > 0),
                         key=lambda f: (-f["total_brut"], f["nom"]))
        return {"payants": payants, "nb_fans": len(fans), "par_mois": par_mois, "totaux": totaux,
                "recues": recues, "pages": pages, "tronque": tronque,
                "devises": sorted({f["devise"] for f in fans})}
    return _avec_cache(f"fans:{type_lien}:{creator_id}:{lien_id}", fab, CACHE_PASSE_S)[0]


def _trouver_lien(creator_id: str, type_lien: str, lien_id: str) -> Dict[str, Any]:
    L = liens(creator_id, type_lien)
    for x in L["liens"]:
        if x["id"] == lien_id:
            return {"lien": x, "depuis": L["depuis"]}
    return {"lien": None, "depuis": L["depuis"]}


# ─── lectures : messages ─────────────────────────────────────────────────
def _collection(c: Dict[str, Any]) -> Dict[str, Any]:
    return {"no": str(c.get("collectionNo") or ""),
            "messages": [{"texte": _texte_html(m.get("messageContent")), "prix": _n(m.get("price"))}
                         for m in (c.get("messages") or c.get("message") or []) if isinstance(m, dict)],
            "prix": _n(c.get("price")), "envois": _n(c.get("numberOfTimesSent")),
            "achats": _n(c.get("numberOfPurchases")), "revenu": _n(c.get("revenue"))}


def _envoi_norm(x: Dict[str, Any], cle_id: str) -> Dict[str, Any]:
    """Un message automatique ou un envoi de masse prioritaire. Le vrai champ
    s'appelle « messages » (la doc écrit « message ») ; les heures sont des
    ENTIERS en ms ici, alors que ce sont des textes dans /v1/links."""
    cols = x.get("collections")
    if cols is None and isinstance(x.get("collection"), dict):
        cols = [x["collection"]]          # envoi prioritaire : un OBJET, pas une liste
    return {"id": str(x.get(cle_id) or ""), "employe": str(x.get("employeeId") or ""),
            "statut": str(x.get("status") or ""),
            "listes": [str(v) for v in x.get("includeListNames") or []],
            "exclues": [str(v) for v in x.get("excludeListNames") or []],
            "cd_h": _n(x.get("messageCdHours")), "declencheur": x.get("trigger"),
            "frequence": x.get("triggerFrequency"),
            "en_ligne": _vrai(x.get("onlyOnlineFans")),
            "collections": [_collection(c) for c in cols or [] if isinstance(c, dict)],
            "prix": _n(x.get("price")), "envois": _n(x.get("totalNumberOfTimeSent")),
            "achats": _n(x.get("totalNumberOfPurchases")), "revenu": _n(x.get("totalRevenue")),
            "annule_par": str(x.get("canceledByEmployeeId") or ""),
            "retire_par": str(x.get("unsentByEmployeeId") or ""),
            "retire": x.get("unsentType"), "echec": str(x.get("failReason") or ""),
            "envoye": _n(x.get("sentTime")), "fin": _n(x.get("endTime")),
            "cree": _n(x.get("createdTime")), "modifie": _n(x.get("modifiedTime"))}


def automatiques(creator_id: str, depuis: dt.date) -> Dict[str, Any]:
    """Filtrés sur la date de CRÉATION, compteurs CUMULÉS depuis : les 7
    derniers jours sont vides alors que 7 automatisations actives envoient.
    D'où la lecture depuis la connexion. limit : 10 au plus ici."""
    return _liste_par_tranches(f"auto:{creator_id}", "/v1/automated-messages",
                               {"creatorId": creator_id, "platformCode": PLATEFORME, "limit": 10},
                               depuis, _aujourdhui(), lambda x: _envoi_norm(x, "automatedMessageId"),
                               duree=CACHE_S)


def prioritaires(creator_id: str, depuis: dt.date) -> Dict[str, Any]:
    return _liste_par_tranches(f"prio:{creator_id}", "/v1/priority-mass-messages",
                               {"creatorId": creator_id, "platformCode": PLATEFORME, "limit": 10},
                               depuis, _aujourdhui(),
                               lambda x: _envoi_norm(x, "priorityMassMessageId"), duree=CACHE_S)


# ─── agrégats (purs, testés sans réseau) ─────────────────────────────────
# Statuts de vente sortis des totaux. « pending_return » (remboursement en
# cours, doc v1.4) était compté comme encaissé : une vente en train d'être
# rendue gonflait le CA et la part du chatteur.
STATUTS_EXCLUS = ("undo", "pending_return")


def resume_ventes(lignes: List[Dict[str, Any]], devise: str = DEVISE, top: int = 20) -> Dict[str, Any]:
    """Totaux des ventes, remboursées EXCLUES (elles restent dans la liste
    avec leur montant plein) mais comptées à part, jamais effacées."""
    statuts: Dict[str, Dict[str, int]] = {}
    jours: Dict[str, Dict[str, Any]] = {}
    types: Dict[str, Dict[str, int]] = {}
    fans: Dict[str, Dict[str, Any]] = {}
    tot = {"nb": 0, "brut": 0, "frais": 0, "net": 0}
    exclues = {"nb": 0, "brut": 0}
    autres = 0
    for v in lignes:
        if (v.get("devise") or devise) != devise:
            autres += 1
            continue
        st = v.get("statut") or "?"
        s = statuts.setdefault(st, {"nb": 0, "brut": 0, "net": 0})
        s["nb"] += 1
        s["brut"] += v["brut"]
        s["net"] += v["net"]
        if st in STATUTS_EXCLUS:
            exclues["nb"] += 1
            exclues["brut"] += v["brut"]
            continue
        for k in ("brut", "frais", "net"):
            tot[k] += v[k]
        tot["nb"] += 1
        j = jours.setdefault(_jour_utc(v["t"]) or "?", {"nb": 0, "brut": 0, "net": 0, "types": {}})
        j["nb"] += 1
        j["brut"] += v["brut"]
        j["net"] += v["net"]
        j["types"][v["type"]] = j["types"].get(v["type"], 0) + v["brut"]
        lab = v["type"] + (" · " + v["source"] if v.get("source") else "")
        t = types.setdefault(lab, {"nb": 0, "brut": 0, "net": 0})
        t["nb"] += 1
        t["brut"] += v["brut"]
        t["net"] += v["net"]
        f = fans.setdefault(v.get("fan") or "?", {"nom": "", "nb": 0, "brut": 0, "net": 0})
        if v.get("fan_nom"):
            f["nom"] = v["fan_nom"]
        f["nb"] += 1
        f["brut"] += v["brut"]
        f["net"] += v["net"]
    classes = sorted(fans.items(), key=lambda kv: -kv[1]["brut"])
    reste = classes[top:]
    return dict(tot, statuts=statuts, jours=jours, types=types, exclues=exclues,
                autres_devises=autres, fans_nb=len(fans),
                panier=(tot["brut"] / tot["nb"]) if tot["nb"] else 0,
                fans_top=[dict(v, id=k) for k, v in classes[:top]],
                fans_reste={"nb": len(reste), "brut": sum(v["brut"] for _, v in reste)})


def resume_equipe(lignes: List[Dict[str, Any]], devise: str = DEVISE) -> Dict[str, Any]:
    """CA par chatteur. Une vente sans attributeEmployeeId n'est à PERSONNE
    (78 lignes sur 157 la semaine vérifiée) : comptée à part, jamais payée."""
    par: Dict[str, Dict[str, Any]] = {}
    sans = {"nb": 0, "brut": 0, "net": 0, "regles": {}}
    tot = {"nb": 0, "brut": 0, "net": 0}
    exclues = {"nb": 0, "brut": 0}
    autres = 0
    for v in lignes:
        if (v.get("devise") or devise) != devise:
            autres += 1
            continue
        montant = v.get("attribue", v["brut"])
        if v.get("statut") in STATUTS_EXCLUS:
            exclues["nb"] += 1
            exclues["brut"] += montant
            continue
        tot["nb"] += 1
        tot["brut"] += montant
        tot["net"] += v["net"]
        regle = v.get("regle") or "?"
        if not v.get("employe"):
            sans["nb"] += 1
            sans["brut"] += montant
            sans["net"] += v["net"]
            sans["regles"][regle] = sans["regles"].get(regle, 0) + 1
            continue
        e = par.setdefault(v["employe"], {"nb": 0, "brut": 0, "net": 0, "types": {}, "regles": {}})
        e["nb"] += 1
        e["brut"] += montant
        e["net"] += v["net"]
        e["types"][v["type"]] = e["types"].get(v["type"], 0) + montant
        e["regles"][regle] = e["regles"].get(regle, 0) + 1
    return dict(tot, par_employe=par, sans=sans, exclues=exclues, autres_devises=autres)


# ─── les vues ────────────────────────────────────────────────────────────
def _entete(c: Dict[str, Any], toutes: List[Dict[str, Any]], debut: dt.date, fin: dt.date,
            vue: str) -> Dict[str, Any]:
    return {"creatrice": c, "connectees": toutes, "debut": debut.isoformat(),
            "fin": fin.isoformat(), "vue": vue, "erreurs": {}, "lu_a": time.time()}


def _periode(jours: int) -> Tuple[dt.date, dt.date]:
    fin = _aujourdhui()
    return fin - dt.timedelta(days=max(1, jours) - 1), fin


def bilan(pseudo: str, jours: int = 30) -> Dict[str, Any]:
    """La vue d'ensemble d'une créatrice, sur les `jours` derniers jours."""
    c, toutes = _creatrice_ou_erreur(pseudo)
    cid = str(c["id"])
    debut, fin = _periode(jours)
    out = _entete(c, toutes, debut, fin, "apercu")
    _sections(out, [
        ("jours", lambda: abonnes_par_jour(cid, debut, fin)),
        ("fans", lambda: fans_par_jour(cid, debut, fin)),
        ("renouv_auto", lambda: renouvellement_auto(cid, debut, fin)),
        ("duree", lambda: duree_abonnement(cid, debut, fin)),
        ("visiteurs", lambda: visiteurs_profil(cid, debut, fin)),
        ("rang", lambda: classement(cid, debut, fin)),
    ])
    if "jours" in out:
        pj = out["jours"]
        nouveaux = sum(x["nouveaux"] for x in pj)
        # La moyenne se fait sur les jours PLEINS : le jour en cours n'a que
        # quelques heures de ventes et, compté comme un jour entier, il tirait
        # la moyenne vers le bas (le total, lui, le garde).
        auj = _aujourdhui().isoformat()
        pleins = [x for x in pj if str(x.get("date")) < auj]
        out.update(nouveaux=nouveaux, renouvellements=sum(x["renouvellements"] for x in pj),
                   moyenne=(round(sum(x["nouveaux"] for x in pleins) / len(pleins), 1)
                            if pleins else 0),
                   jours_pleins=len(pleins))
    out["lu_a"] = time.time()
    return out


def charger(vue: str, pseudo: str, jours: int, lien: str = "", type_lien: str = "TRACKING",
            affecter: bool = False) -> Dict[str, Any]:
    """Les données d'UNE vue — et seulement ses adresses (ADRESSES[vue])."""
    if vue == "apercu":
        return bilan(pseudo, jours)
    c, toutes = _creatrice_ou_erreur(pseudo)
    cid = str(c["id"])
    debut, fin = _periode(jours)
    out = _entete(c, toutes, debut, fin, vue)
    an = _aujourdhui() - dt.timedelta(days=HISTORIQUE_JOURS)
    connexion = _connexion(c) or an
    out["connexion"] = connexion.isoformat()
    if vue == "revenus":
        _sections(out, [("ventes", lambda: ventes(cid, debut, fin)),
                        ("remboursements", lambda: remboursements(cid, debut, fin)),
                        ("facture", facture_mensuelle)])
    elif vue == "equipe":
        _sections(out, [("perf", lambda: ventes_attribuees(cid, debut, fin)),
                        ("employes", employes)])
        if "employes" in out:
            try:
                out["affectations"] = affectations(out["employes"]["liste"], forcer=affecter)
            except ErreurInfloww as e:
                out["erreurs"]["affectations"] = e
            except Exception as e:
                out["erreurs"]["affectations"] = ErreurInfloww(f"{type(e).__name__} : {e}")
        else:
            out["erreurs"]["affectations"] = ErreurInfloww(
                "l'annuaire des employés n'a pas pu être lu : impossible de savoir qui interroger")
        # les rapports employés : ceux qui ont vendu sur la période, puis l'équipe affectée
        ids: List[str] = []
        if "perf" in out:
            r = resume_equipe(out["perf"]["lignes"])
            ids = sorted(r["par_employe"], key=lambda k: -r["par_employe"][k]["brut"])
        aff = out.get("affectations") or {}
        for eid, v in sorted((aff.get("par_employe") or {}).items()):
            if cid in (v or {}).get("c", []) and eid not in ids:
                ids.append(eid)
        ids = ids[:30]
        out["ids_rapports"] = ids
        if ids:
            _sections(out, [
                ("rapport_ventes", lambda: rapport_employes(
                    "/v1/employee-report/employee-sales-summary", "empventes", ids, debut, fin,
                    _ligne_ventes_employe)),
                ("rapport_chat", lambda: rapport_employes(
                    "/v1/employee-report/employee-chat-summary", "empchat", ids, debut, fin,
                    _ligne_chat_employe))])
    elif vue == "marketing":
        _sections(out, [("liens", lambda: liens(cid, "TRACKING", an)),
                        ("essais", lambda: liens(cid, "TRIAL", an)),
                        ("campagnes", lambda: liens(cid, "CAMPAIGN", an))])
    elif vue == "lien":
        out["lien_id"], out["type_lien"] = lien, type_lien
        _sections(out, [("lien_info", lambda: _trouver_lien(cid, type_lien, lien)),
                        ("fans_lien", lambda: fans_lien(cid, type_lien, lien))])
    elif vue == "messages":
        depuis = max(connexion, an)
        out["depuis"] = depuis.isoformat()
        _sections(out, [("chat", lambda: chat_resume(cid, debut, fin)),
                        ("automatiques", lambda: automatiques(cid, depuis)),
                        ("prioritaires", lambda: prioritaires(cid, depuis)),
                        ("employes", employes)])
    elif vue == "journal":
        # Le journal est lu pour TOUTES les créatrices de l'agence, pas seulement
        # les connectées : /v1/creators ne rend que ces dernières, et une
        # créatrice qui vient de se déconnecter — la ligne que ce journal sert
        # justement à montrer — disparaissait de sa propre histoire.
        def ids_journal():
            try:
                ids = [x["id"] for x in toutes_creatrices() if x.get("id")]
            except ErreurInfloww:
                ids = []
            return ids or [str(x.get("id")) for x in toutes if x.get("id")]
        _sections(out, [("toutes", toutes_creatrices),
                        ("statuts", lambda: journal_statuts(ids_journal(), an)),
                        ("reassign", lambda: reassignations(debut, fin)),
                        ("employes", employes)])
    else:
        raise ErreurInfloww(f"vue inconnue : {vue}")
    out["lu_a"] = time.time()
    return out


# ─── la page ─────────────────────────────────────────────────────────────
# Rendue ENTIÈREMENT côté serveur, sans JavaScript : le dashboard a déjà perdu
# des pages entières à cause d'une apostrophe dans du JS logé dans une chaîne
# Python. Ici il n'y en a pas, donc rien de ce genre ne peut casser. Tout
# texte venu de l'API passe par _e.
def _e(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def _nb(n: Any) -> str:
    """12 345 : l'espace des milliers, posé sur le nombre seul — jamais par un
    remplacement global, qui effacerait aussi les virgules des noms de liens."""
    return f"{_n(n):,}".replace(",", "\u202f")


def _dec(v: Any, k: int = 2) -> str:
    """1 234,56 : virgule décimale, espace fine pour les milliers."""
    x = _f(v)
    if x is None:
        return "—"
    return f"{x:,.{k}f}".replace(",", "\u202f").replace(".", ",")


def _argent(centimes: Any, devise: str = DEVISE) -> str:
    """Des centimes (« 2499 ») en dollars (« 24,99 $ »), avec la devise."""
    v = _n(centimes) / 100.0
    sym = {"USD": "$", "EUR": "€"}.get(str(devise or DEVISE).upper(), str(devise or DEVISE).upper())
    return ("-" if v < 0 else "") + _dec(abs(v), 2) + "\u00a0" + _e(sym)


def _pct(a: Any, b: Any, k: int = 1) -> str:
    return _dec(100.0 * (_f(a) or 0) / (_f(b) or 0), k) + "\u00a0%" if _f(b) else "—"


def _duree_ms(ms: Any) -> str:
    s = _n(ms) // 1000
    if not s:
        return "—"
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return (f"{h} h {m:02d}" if h else f"{m} min {s:02d} s")


def _tuile(v: str, libelle: str, sous: str = "") -> str:
    s = f'<div class="s">{sous}</div>' if sous else ""
    return f'<div class="tuile"><div class="v">{v}</div><div class="l">{libelle}</div>{s}</div>'


def _tuiles(t: List[str]) -> str:
    return f'<div class="tuiles">{"".join(t)}</div>' if t else ""


def _barre(v: Any, maxi: Any) -> str:
    m = _f(maxi) or 0
    w = round(100 * (_f(v) or 0) / m) if m > 0 else 0
    return f'<span class="barre"><span style="width:{max(0, min(100, w))}%"></span></span>'


def _table(entetes: List[Tuple[str, str]], lignes: List[Any], vide: str = "Aucune ligne.") -> str:
    """entetes : (titre, classe) ; une ligne = liste de cellules HTML, ou
    (cellules, classe de la ligne)."""
    if not lignes:
        return f'<p class="vide">{vide}</p>'
    th = "".join(f'<th class="{c}">{t}</th>' for t, c in entetes)
    corps = []
    for l in lignes:
        cells, cl = (l if isinstance(l, tuple) else (l, ""))
        tds = "".join(f'<td class="{entetes[i][1] if i < len(entetes) else ""}">{c}</td>'
                      for i, c in enumerate(cells))
        corps.append(f'<tr class="{cl}">{tds}</tr>' if cl else f"<tr>{tds}</tr>")
    return f'<div class="table-scroll"><table><tr>{th}</tr>{"".join(corps)}</table></div>'


def _manque(titre: str = "absent de la réponse d'Infloww") -> str:
    return f'<span class="faible" title="{_e(titre)}">—</span>'


def _conseil(e: ErreurInfloww, chemin: str = "") -> str:
    m = str(e)
    if "Scope validation failure" in m and getattr(e, "code", 0) == 403:
        return PORTEES.get(chemin) or ("La clé API n'a pas le droit de lire cette adresse : "
                                       "l'ouvrir dans Infloww, page de gestion des clés API.")
    if "Scope validation failure" in m:
        return ("Cette créatrice n'est pas dans le périmètre de la clé : Infloww n'y ajoute pas "
                "d'office les créatrices nouvelles ou reconnectées (page de gestion des clés API).")
    if getattr(e, "code", 0) == 429:
        return "Trop de requêtes pour l'agence en ce moment : réessayer dans une minute."
    if "Query time span" in m:
        return "Une requête a dépassé 31 jours : le découpage a une faille, à signaler."
    if "clé API" in m:
        return "Déposer la clé dans data/infloww_api_key (jamais dans git)."
    return ""


def _boite_err(titre: str, e: ErreurInfloww, chemin: str = "") -> str:
    code = f" (HTTP {e.code})" if getattr(e, "code", 0) else ""
    rid = (f"<br><small>x-request-id : <code>{_e(e.request_id)}</code> — à donner au support "
           f"Infloww</small>") if getattr(e, "request_id", "") else ""
    c = _conseil(e, chemin)
    conseil = f'<br><small class="conseil">{_e(c)}</small>' if c else ""
    adr = f'<br><small class="faible">Adresse : <code>GET {_e(chemin)}</code></small>' if chemin else ""
    return f'<div class="err"><b>{_e(titre)}</b><br>{_e(e)}{code}{rid}{conseil}{adr}</div>'


def _err(b: Dict[str, Any], cle_: str) -> str:
    e = (b.get("erreurs") or {}).get(cle_)
    if e is None:
        return ""
    titre, chemin = SECTIONS.get(cle_, (cle_, ""))
    return _boite_err(f"{titre} : indisponible", e, chemin)


def _avert(txt: str) -> str:
    return f'<div class="avert">{txt}</div>'


def _h2(titre: str, sous: str = "") -> str:
    s = f' <span class="faible">— {sous}</span>' if sous else ""
    return f"<h2>{titre}{s}</h2>"


def _url(vue: str, pseudo: str, jours: int, **extra: Any) -> str:
    """Un lien simple : la navigation se fait par l'URL, sans script. Chaque
    valeur est encodée, donc sans guillemet ni chevron possible."""
    q: List[Tuple[str, Any]] = []
    if vue and vue != "apercu":
        q.append(("vue", vue))
    q += [("creatrice", pseudo), ("jours", jours)]
    q += [(k, v) for k, v in extra.items() if v not in (None, "", False)]
    return "?" + "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in q)


def _nom_employe(eid: str, annuaire: Dict[str, Dict[str, Any]]) -> str:
    if not eid:
        return '<span class="faible">—</span>'
    e = annuaire.get(eid)
    if e is None:
        return f'<span class="faible" title="absent de l\'annuaire /v1/employees">#{_e(eid)}</span>'
    st = e.get("statut") or ""
    pill = "" if st == "Activated" else f' <span class="pill att">{_e(st)}</span>'
    return f"{_e(e.get('nom') or '#' + eid)}{pill}"


def _annuaire(b: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {e["id"]: e for e in ((b.get("employes") or {}).get("liste") or [])}


def _jours_de(debut: str, fin: str) -> List[str]:
    try:
        a, z = dt.date.fromisoformat(debut), dt.date.fromisoformat(fin)
    except (TypeError, ValueError):
        return []
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((z - a).days + 1)]


# ── vue d'ensemble ──
def _corps_apercu(b: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    jours = ctx["jours"]
    fin, debut = str(b.get("fin") or ""), str(b.get("debut") or "")
    series = {k: {str(x.get("date")): x for x in (b.get(k) or [])}
              for k in ("jours", "fans", "duree", "visiteurs", "rang", "renouv_auto")}
    subs, fans, dur, vis, rang = (series[k] for k in ("jours", "fans", "duree", "visiteurs", "rang"))
    ren = series["renouv_auto"]
    dates = set(_jours_de(debut, fin))
    for s in series.values():
        dates |= set(s)
    dates_l = sorted(dates, reverse=True)
    try:
        hier = (dt.date.fromisoformat(fin) - dt.timedelta(days=1)).isoformat()
    except ValueError:
        hier = ""
    t = []
    if "jours" in b:
        h = subs.get(hier)
        t += [_tuile(_nb(b.get("nouveaux", 0)), f"nouveaux abonnés · {jours} j"),
              _tuile(_dec(b.get("moyenne", 0), 1), "par jour en moyenne",
                     f"sur {_nb(b.get('jours_pleins', 0))} jours pleins, sans aujourd'hui"),
              _tuile(_nb(h["nouveaux"]) if h else "—", "hier"),
              _tuile(_nb(b.get("renouvellements", 0)), "renouvellements")]
    if fans:
        ds = sorted(fans)
        der, pre = fans[ds[-1]], fans[ds[0]]
        delta = der["actifs"] - pre["actifs"]
        t.append(_tuile(_nb(der["actifs"]), f"fans actifs le {_e(ds[-1])}",
                        f"{'+' if delta >= 0 else '−'}{_nb(abs(delta))} depuis le {_e(ds[0])} · "
                        f"{_nb(der['expires'])} expirés"))
    vis_ok = [v for v in vis.values() if not v.get("attente")]
    if vis_ok:
        total = sum(v["total"] for v in vis_ok)
        nouv = sum(subs[d]["nouveaux"] for d in (v["date"] for v in vis_ok) if d in subs)
        t.append(_tuile(_nb(total), "visiteurs du profil",
                        f"{_nb(sum(v['connectes'] for v in vis_ok))} connectés · "
                        f"{_nb(sum(v['invites'] for v in vis_ok))} invités"))
        if subs:
            t.append(_tuile(_pct(nouv, total, 2), "des visiteurs deviennent abonnés",
                            "nouveaux abonnés ÷ visiteurs, jours complets seulement"))
    if dur:
        d = dur[max(dur)]
        t.append(_tuile(f"{_nb(d['jours'])}\u00a0j", "durée moyenne d'abonnement", f"au {_e(d['date'])}"))
    rangs = [r for r in rang.values() if r.get("rang") is not None]
    if rangs:
        r = rang[max(rang)]
        t.append(_tuile(f"top {_dec(r.get('rang'))}\u00a0%" if r.get("rang") is not None else _e(r.get("brut")),
                        "classement OnlyFans", f"meilleur : top {_dec(min(x['rang'] for x in rangs))} % · "
                        "plus bas = mieux"))
    c = b.get("creatrice") or {}
    lu = dt.datetime.fromtimestamp(b.get("lu_a") or time.time()).strftime("%d/%m à %Hh%M")
    h = [_tuiles(t),
         f'<p class="note">@{_e(c.get("userName"))} · du {_e(debut)} au {_e(fin)} · lu le {lu}'
         " · OnlyFans transmet ses chiffres avec 2 à 4 h de retard : aujourd'hui est encore incomplet.</p>"]
    for k in ("jours", "fans", "renouv_auto", "duree", "visiteurs", "rang"):
        h.append(_err(b, k))
    # jours absents : dits, jamais comblés par des zéros
    trous = []
    for k, nom in (("jours", "abonnés"), ("fans", "fans actifs"), ("duree", "durée moyenne"),
                   ("visiteurs", "visiteurs"), ("rang", "classement")):
        if k in b:
            manquants = [d for d in _jours_de(debut, fin) if d not in series[k]]
            if manquants:
                trous.append(f"{nom} : {len(manquants)} jour(s) absent(s) "
                             f"({', '.join(_e(d[5:]) for d in manquants[:8])}"
                             f"{'…' if len(manquants) > 8 else ''})")
    if trous:
        h.append(_avert("Jours absents de la réponse d'Infloww, laissés vides (pas mis à zéro) : "
                        + " ; ".join(trous) + "."))
    if "renouv_auto" in b and not b.get("renouv_auto"):
        h.append('<p class="note">Renouvellement automatique : Infloww renvoie une liste VIDE sur la '
                 "période (pas zéro). Cohérent avec une page gratuite, sans renouvellement payant ; "
                 "ce n'est pas une mesure.</p>")
    cols = [("Date", "nw")]
    if "jours" in b:
        cols += [("Nouveaux", "n"), ("", "barre-c"), ("Renouv.", "n faible")]
    if "fans" in b:
        cols += [("Fans actifs", "n"), ("Expirés", "n faible")]
    if ren:
        cols += [("Renouv. auto", "n")]
    if "visiteurs" in b:
        cols += [("Visiteurs", "n"), ("dont connectés", "n faible")]
        if "jours" in b:
            cols += [("Conv.", "n faible")]
    if "duree" in b:
        cols += [("Durée moy.", "n")]
    if "rang" in b:
        cols += [("Classement", "n")]
    maxi = max([x["nouveaux"] for x in subs.values()] or [1]) or 1
    lignes = []
    for d in dates_l:
        l = [_e(d)]
        s = subs.get(d)
        if "jours" in b:
            l += ([_nb(s["nouveaux"]), _barre(s["nouveaux"], maxi), _nb(s["renouvellements"])]
                  if s else [_manque(), "", _manque()])
        if "fans" in b:
            f = fans.get(d)
            l += [_nb(f["actifs"]), _nb(f["expires"])] if f else [_manque(), _manque()]
        if ren:
            r = ren.get(d)
            l.append(_nb(r["fans"]) if r else _manque())
        if "visiteurs" in b:
            v = vis.get(d)
            if v and v.get("attente"):
                l += ['<span class="pill att" title="0/0/0 : pas encore synchronisé">en attente</span>', ""]
                if "jours" in b:
                    l.append("")
            elif v:
                l += [_nb(v["total"]), _nb(v["connectes"])]
                if "jours" in b:
                    l.append(_pct(s["nouveaux"], v["total"], 2) if s else _manque())
            else:
                l += [_manque(), _manque()] + ([_manque()] if "jours" in b else [])
        if "duree" in b:
            x = dur.get(d)
            l.append(f"{_nb(x['jours'])}\u00a0j" if x else _manque())
        if "rang" in b:
            x = rang.get(d)
            l.append(("top " + _dec(x["rang"]) + "\u00a0%") if x and x.get("rang") is not None
                     else (_e(x.get("brut")) if x else _manque()))
        lignes.append(l)
    h.append(_h2("Jour par jour", "le jour en cours est incomplet"))
    h.append(_table(cols, lignes))
    if "liens" in b:                      # ancienne forme du bilan : les liens y étaient
        h.append(_bloc_liens(b, ctx))
    return "".join(h)


# ── revenus ──
# Les deux orthographes : la doc v1.4 écrit « post », « stream », « subscribes »
# pour les remboursements, et les formes au pluriel ailleurs. Sans les
# premières, un remboursement d'abonnement s'affichait sous son code brut.
_TYPES_REMB = {"chat_messages": "Messages", "tips": "Tips", "posts": "Posts", "post": "Posts",
               "subscriptions": "Abonnement", "subscription": "Abonnement", "subscribes": "Abonnement",
               "streams": "Streams", "stream": "Streams"}
_STATUTS_VENTE = {"done": ("encaissé", "ok"), "loading": ("en attente (retenue OnlyFans)", "att"),
                  "undo": ("remboursé — exclu des totaux", "ko"),
                  "pending_return": ("remboursement en cours — exclu des totaux", "ko")}


def _corps_revenus(b: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    h = []
    V = b.get("ventes")
    tx_fan: Dict[str, str] = {}
    if V is not None:
        r = resume_ventes(V["lignes"])
        for v in V["lignes"]:
            if v.get("tx") and v.get("fan_nom"):
                tx_fan[v["tx"]] = v["fan_nom"]
        st = r["statuts"]
        h.append(_tuiles([
            _tuile(_argent(r["brut"]), "chiffre d'affaires brut", "remboursements exclus"),
            _tuile(_argent(r["net"]), "net après OnlyFans", f"frais : {_argent(r['frais'])}"),
            _tuile(_nb(r["nb"]), "ventes", f"panier moyen {_argent(r['panier'])}"),
            _tuile(_nb(r["fans_nb"]), "fans payants"),
            _tuile(_argent(st.get("loading", {}).get("brut", 0)), "en attente",
                   f"{_nb(st.get('loading', {}).get('nb', 0))} ventes de moins de ~7 jours"),
            _tuile(_argent(r["exclues"]["brut"]), "remboursé",
                   f"{_nb(r['exclues']['nb'])} vente(s) « undo », exclue(s)")]))
        h.append(f'<p class="note">Registre /v1/transactions, vente par vente, du {_e(V.get("debut"))} '
                 f"au {_e(V.get('fin'))} · jours en UTC · montants en dollars US, convertis depuis "
                 "les centimes de l'API · les ventes « en attente » sont resynchronisées toutes les 12 h.</p>")
        if V.get("tronque"):
            h.append(_avert("Lecture arrêtée par le garde-fou de pagination sur : "
                            + ", ".join(_e(x) for x in V["tronque"]) + ". Les totaux sont INCOMPLETS."))
        if r["autres_devises"]:
            h.append(_avert(f"{_nb(r['autres_devises'])} vente(s) dans une autre devise que le dollar : "
                            "non additionnées aux totaux ci-dessus."))
        h.append(_h2("Par statut"))
        h.append(_table([("Statut", ""), ("Ventes", "n"), ("Brut", "n"), ("Net", "n")],
                        [[f'<span class="pill {_STATUTS_VENTE.get(k, ("", "att"))[1]}">{_e(k)}</span> '
                          f'{_e(_STATUTS_VENTE.get(k, ("statut inconnu de la doc", ""))[0])}',
                          _nb(v["nb"]), _argent(v["brut"]), _argent(v["net"])]
                         for k, v in sorted(st.items(), key=lambda kv: -kv[1]["brut"])]))
        tous_types: Dict[str, int] = {}
        for j in r["jours"].values():
            for k, v in j["types"].items():
                tous_types[k] = tous_types.get(k, 0) + v
        colt = [k for k, _ in sorted(tous_types.items(), key=lambda kv: -kv[1])][:4]
        autres_t = [k for k in tous_types if k not in colt]
        maxi = max([j["brut"] for j in r["jours"].values()] or [1]) or 1
        lignes = []
        for d in sorted(set(r["jours"]) | set(_jours_de(str(V.get("debut")), str(V.get("fin")))),
                        reverse=True):
            j = r["jours"].get(d)
            if not j:
                lignes.append(([_e(d), "0", _argent(0), _argent(0)] + ["—"] * (len(colt) + bool(autres_t))
                               + [""], "faible"))
                continue
            lignes.append([_e(d), _nb(j["nb"]), _argent(j["brut"]), _argent(j["net"])]
                          + [_argent(j["types"].get(k, 0)) for k in colt]
                          + ([_argent(sum(j["types"].get(k, 0) for k in autres_t))] if autres_t else [])
                          + [_barre(j["brut"], maxi)])
        h.append(_h2("Jour par jour", "brut par type de vente"))
        h.append(_table([("Date (UTC)", "nw"), ("Ventes", "n"), ("Brut", "n"), ("Net", "n")]
                        + [(_e(k), "n faible") for k in colt]
                        + ([("Autres", "n faible")] if autres_t else []) + [("", "barre-c")], lignes))
        h.append(_h2("Par type", "Messages = PPV en message · Tips par origine · Posts"))
        h.append(_table([("Type", ""), ("Ventes", "n"), ("Brut", "n"), ("Net", "n"), ("Part", "n")],
                        [[_e(k), _nb(v["nb"]), _argent(v["brut"]), _argent(v["net"]),
                          _pct(v["brut"], r["brut"])]
                         for k, v in sorted(r["types"].items(), key=lambda kv: -kv[1]["brut"])]))
        lf = [[(_e(f["nom"]) or '<span class="faible">(sans nom)</span>')
               + f' <span class="faible">#{_e(f["id"])}</span>',
               _nb(f["nb"]), _argent(f["brut"]), _argent(f["net"]), _pct(f["brut"], r["brut"])]
              for f in r["fans_top"]]
        if r["fans_reste"]["nb"]:
            lf.append(([f'<span class="faible">les {_nb(r["fans_reste"]["nb"])} autres fans</span>', "",
                        _argent(r["fans_reste"]["brut"]), "", _pct(r["fans_reste"]["brut"], r["brut"])],
                       "faible"))
        h.append(_h2("Meilleurs fans", f"{len(r['fans_top'])} premiers sur {_nb(r['fans_nb'])}"))
        h.append(_table([("Fan", ""), ("Achats", "n"), ("Brut", "n"), ("Net", "n"), ("Part", "n")], lf))
    h.append(_err(b, "ventes"))
    R = b.get("remboursements")
    h.append(_h2("Remboursements", "filtrés sur la date du remboursement"))
    h.append(_err(b, "remboursements"))
    if R is not None:
        tot = sum(x["montant"] for x in R["lignes"])
        if R.get("tronque"):
            h.append(_avert("Lecture des remboursements arrêtée par le garde-fou : liste incomplète."))
        lignes = []
        for x in sorted(R["lignes"], key=lambda x: -x["rembourse"]):
            delai = (x["rembourse"] - x["paye"]) / 86400000 if x["paye"] and x["rembourse"] else None
            nom = tx_fan.get(x["tx"])
            lignes.append([_e(_quand(x["rembourse"])), _e(_quand(x["paye"])),
                           (_dec(delai, 1) + "\u00a0j") if delai is not None else _manque(),
                           _e(_TYPES_REMB.get(x["type"], x["type"] or "?")), _argent(x["montant"], x["devise"]),
                           f'<span class="pill">{_e(x["statut"] or "?")}</span>',
                           ((_e(nom) + " ") if nom else "") + f'<span class="faible">#{_e(x["fan"])}</span>'])
        h.append(_table([("Remboursé le (UTC)", "nw"), ("Payé le", "faible nw"), ("Délai", "n"), ("Type", ""),
                         ("Montant brut", "n"), ("Statut du paiement", ""), ("Fan", "")], lignes,
                        "Aucun remboursement sur la période (liste vide renvoyée par Infloww)."))
        if lignes:
            h.append(f'<p class="note">{_nb(len(lignes))} remboursement(s), {_argent(tot)} bruts. '
                     "Statut du paiement, non expliqué par la doc — observé : « undo » sur des ventes "
                     "remboursées 1,5 à 9 jours après paiement ; « done » sur des tips remboursés 28 jours "
                     "après (rétrofacturation après encaissement, probablement). La vente d'origine reste "
                     "dans le registre avec le statut « undo ».</p>")
    h.append(_h2("Facture Infloww de l'agence", "coût de l'outil, toutes créatrices, douze mois"))
    h.append(_err(b, "facture"))
    F = b.get("facture")
    if F is not None:
        h.append(_table([("Mois", ""), ("Abonnement", "n"), ("Remise", "n"), ("Taxe (IGIC)", "n"),
                         ("Total", "n"), ("Déductions", "n"), ("Reste dû", "n"), ("Payé", "n"),
                         ("En attente", "n"), ("Facture", "faible")],
                        [[_e(x["periode"])] + [(_argent(x[k], x["devise"]) if x.get(k) is not None else _manque())
                                               for k in ("subscription", "discount", "igic", "total",
                                                         "deductions", "balanceDue", "paid", "pending")]
                         + [_e(x["facture"]) or "—"] for x in sorted(F, key=lambda x: x["periode"], reverse=True)],
                        "Aucune facture sur douze mois (liste vide renvoyée par Infloww)."))
        if F:
            h.append('<p class="note">Unité des montants non documentée : centimes supposés, comme '
                     "partout ailleurs dans l'API.</p>")
    h.append('<p class="note">Le CA par chatteur est dans l\'onglet <a href="'
             + _url("equipe", ctx["pseudo"], ctx["jours"]) + '">Équipe</a>.</p>')
    return "".join(h)


# ── équipe ──
def _corps_equipe(b: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    h = []
    ann = _annuaire(b)
    c = b.get("creatrice") or {}
    cid, pid = str(c.get("id") or ""), str(c.get("platformPid") or "")
    P = b.get("perf")
    r = resume_equipe(P["lignes"]) if P is not None else None
    if r is not None:
        att = r["brut"] - r["sans"]["brut"]
        h.append(_tuiles([
            _tuile(_argent(att), "CA brut attribué à un chatteur", _pct(att, r["brut"]) + " du total"),
            _tuile(_argent(r["sans"]["brut"]), "attribué à personne",
                   f"{_nb(r['sans']['nb'])} vente(s) — à ne jamais payer"),
            _tuile(_nb(len(r["par_employe"])), "chatteurs ayant vendu"),
            _tuile(_argent(r["exclues"]["brut"]), "remboursé, exclu", f"{_nb(r['exclues']['nb'])} vente(s)")]))
        h.append(f'<p class="note">/v1/transaction-perf/details du {_e(P.get("debut"))} au {_e(P.get("fin"))}, '
                 "une ligne par vente · montant attribué = BRUT (salesAmount) · remboursées exclues.</p>")
        if P.get("tronque"):
            h.append(_avert("Lecture arrêtée par le garde-fou de pagination sur : "
                            + ", ".join(_e(x) for x in P["tronque"]) + ". Totaux INCOMPLETS."))
        if r["autres_devises"]:
            h.append(_avert(f"{_nb(r['autres_devises'])} vente(s) dans une autre devise, non additionnées."))
        types = sorted({t for e in r["par_employe"].values() for t in e["types"]})
        maxi = max([e["brut"] for e in r["par_employe"].values()] or [1]) or 1
        lignes = []
        for eid, e in sorted(r["par_employe"].items(), key=lambda kv: -kv[1]["brut"]):
            lignes.append([_nom_employe(eid, ann), _nb(e["nb"]), _argent(e["brut"]), _argent(e["net"]),
                           _pct(e["brut"], r["brut"])]
                          + [_argent(e["types"].get(t, 0)) for t in types]
                          + [", ".join(f"{_e(k)} {v}" for k, v in sorted(e["regles"].items())),
                             _barre(e["brut"], maxi)])
        if r["sans"]["nb"]:
            lignes.append(([f'<b>Personne</b> <span class="pill ko">non payé</span>', _nb(r["sans"]["nb"]),
                            _argent(r["sans"]["brut"]), _argent(r["sans"]["net"]),
                            _pct(r["sans"]["brut"], r["brut"])] + [""] * len(types)
                           + [", ".join(f"{_e(k)} {v}" for k, v in sorted(r["sans"]["regles"].items())), ""],
                           "sans"))
        h.append(_h2("Ventes par chatteur", "règle d'attribution Infloww"))
        h.append(_table([("Chatteur", ""), ("Ventes", "n"), ("Brut attribué", "n"), ("Net", "n"),
                         ("Part", "n")] + [(_e(t), "n faible") for t in types]
                        + [("Règles", "faible"), ("", "barre-c")], lignes,
                        "Aucune vente sur la période."))
    h.append(_err(b, "perf"))
    # rapports employés : 403 aujourd'hui, la section s'allumera avec le droit
    ids = b.get("ids_rapports") or []
    for k in ("rapport_ventes", "rapport_chat"):
        titre, _ = SECTIONS[k]
        h.append(_h2(titre, "par jour, filtré sur cette créatrice"))
        h.append(_err(b, k))
        if k not in b and k not in (b.get("erreurs") or {}):
            h.append('<p class="vide">Aucun employé à interroger : ni vente attribuée sur la période, '
                     "ni équipe affectée connue.</p>")
            continue
        if k not in b:
            continue
        lignes_r = b[k] or []
        a_elle = [x for x in lignes_r if not pid or x["pid"] == pid]
        ailleurs = len(lignes_r) - len(a_elle)
        agg: Dict[str, Dict[str, Any]] = {}
        for x in a_elle:
            g = agg.setdefault(x["employe"], {"jours": 0})
            g["jours"] += 1
            # seuls les compteurs s'additionnent ; les temps de réponse sont moyennés plus bas
            for kk, vv in x.items():
                if isinstance(vv, int) and kk not in ("rep_prevue", "rep_pointee", "fans"):
                    g[kk] = g.get(kk, 0) + vv
        if k == "rapport_ventes":
            cols = [("Employé", ""), ("Jours", "n faible"), ("Ventes", "n"), ("PPV", "n"), ("Tips", "n"),
                    ("Messages directs", "n"), ("Masse prioritaire", "n"), ("Masse", "n")]
            lig = [[_nom_employe(e, ann), _nb(g["jours"])] + [_argent(g.get(kk, 0)) for kk in
                                                             ("ventes", "ppv", "tips", "dm", "mm_prio", "mm")]
                   for e, g in sorted(agg.items(), key=lambda kv: -kv[1].get("ventes", 0))]
        else:
            cols = [("Employé", ""), ("Jours", "n faible"), ("Messages", "n"), ("PPV envoyés", "n"),
                    ("PPV débloqués", "n"), ("Taux", "n"), ("Caractères", "n faible"),
                    ("Réponse (moy. des jours)", "n")]
            lig = []
            for e, g in sorted(agg.items(), key=lambda kv: -kv[1].get("dm", 0)):
                reps = [x["rep_prevue"] for x in a_elle if x["employe"] == e and x["rep_prevue"]]
                lig.append([_nom_employe(e, ann), _nb(g["jours"]), _nb(g.get("dm", 0)), _nb(g.get("ppv", 0)),
                            _nb(g.get("debloques", 0)), _pct(g.get("debloques", 0), g.get("ppv", 0)),
                            _nb(g.get("caracteres", 0)),
                            _duree_ms(sum(reps) / len(reps)) if reps else _manque()])
        h.append(_table(cols, lig, "Aucune ligne pour cette créatrice (liste vide renvoyée par Infloww)."))
        if ailleurs:
            h.append(f'<p class="note">{_nb(ailleurs)} ligne(s) concernent d\'autres créatrices : '
                     "non comptées ici.</p>")
        if k == "rapport_chat" and lig:
            h.append('<p class="note">Fans contactés non additionnés : Infloww les dédoublonne sur la '
                     "fenêtre, une somme de jours surcompterait.</p>")
    if ids:
        h.append(f'<p class="note">Employés interrogés : {_nb(len(ids))} (ceux qui ont vendu, puis '
                 "l'équipe affectée), 10 par requête.</p>")
    # affectations
    h.append(_h2("Équipe affectée", f"@{_e(c.get('userName'))}"))
    h.append(_err(b, "affectations"))
    A = b.get("affectations")
    if A is not None and "a_charger" in A:
        h.append(f'<p class="vide">Infloww n\'a pas de route « créatrice → employés » : il faut un appel '
                 f"par employé ({_nb(A['a_charger'])} à faire sur {_nb(A['total'])}). "
                 f'<a class="ong" href="{_url("equipe", ctx["pseudo"], ctx["jours"], affectations=1)}">'
                 "Charger les affectations</a> — gardées six heures ensuite.</p>")
    elif A is not None:
        par = A.get("par_employe") or {}
        equipe = [eid for eid, v in par.items() if cid in (v or {}).get("c", [])]
        vendeurs = set((r or {}).get("par_employe", {}) if r else {})
        lignes = []
        for eid in sorted(equipe, key=lambda e: (ann.get(e, {}).get("statut") != "Activated",
                                                 -((r or {}).get("par_employe", {}).get(e, {}).get("brut", 0)),
                                                 ann.get(e, {}).get("nom", ""))):
            e = (r or {}).get("par_employe", {}).get(eid)
            autres = [x for x in par[eid]["c"] if x != cid]
            lignes.append([_nom_employe(eid, ann), _nb(e["nb"]) if e else '<span class="faible">0</span>',
                           _argent(e["brut"]) if e else '<span class="faible">—</span>',
                           _nb(len(autres))])
        h.append(_table([("Employé", ""), ("Ventes sur la période", "n"), ("Brut attribué", "n"),
                         ("Autres créatrices", "n faible")], lignes, "Personne n'est affecté à cette créatrice."))
        hors = sorted(vendeurs - set(equipe))
        if hors:
            h.append(_avert("Vendent sur la période sans être affectés à cette créatrice : "
                            + ", ".join(_nom_employe(x, ann) for x in hors) + "."))
        connus = {str(x.get("id")) for x in b.get("connectees") or []}
        inconnus = {x for v in par.values() for x in (v or {}).get("c", [])} - connus
        notes = [f"{_nb(len(par))} employés interrogés"]
        if A.get("ignores"):
            notes.append(f"{_nb(A['ignores'])} supprimés non interrogés (aucun n'avait d'affectation)")
        if inconnus:
            notes.append(f"{_nb(len(inconnus))} créatrices affectées hors du périmètre de la clé, sans nom lisible")
        if any((v or {}).get("tronque") for v in par.values()):
            notes.append("au moins une liste d'affectations tronquée par le garde-fou")
        h.append(f'<p class="note">{" · ".join(notes)}.</p>')
        for eid, e in sorted((A.get("erreurs") or {}).items()):
            h.append(_boite_err(f"Affectations de {ann.get(eid, {}).get('nom') or eid} : indisponibles", e,
                                SECTIONS["affectations"][1]))
    # annuaire
    h.append(_err(b, "employes"))
    E = b.get("employes")
    if E is not None:
        par_statut: Dict[str, int] = {}
        for e in E["liste"]:
            par_statut[e["statut"] or "?"] = par_statut.get(e["statut"] or "?", 0) + 1
        h.append(_h2("Annuaire des employés", " · ".join(f"{_e(k)} {v}" for k, v in
                                                          sorted(par_statut.items(), key=lambda kv: -kv[1]))))
        if E.get("tronque"):
            h.append(_avert("Annuaire tronqué par le garde-fou de pagination."))
        h.append(_table([("Nom", ""), ("Statut", ""), ("Créé le", "faible"), ("Supprimé le", "faible"),
                         ("Identifiant", "faible")],
                        [[_e(e["nom"]), f'<span class="pill {"ok" if e["statut"] == "Activated" else "att"}">'
                          f'{_e(e["statut"] or "?")}</span>', _e(_jour_utc(e["cree"])) or "—",
                          _e(_jour_utc(e["supprime"])) or "—", _e(e["id"])]
                         for e in sorted(E["liste"], key=lambda e: (e["statut"] != "Activated", e["nom"].lower()))],
                        "Annuaire vide."))
    return "".join(h)


# ── marketing ──
def _bloc_liens(b: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    L = b.get("liens")
    liste = L.get("liens", []) if isinstance(L, dict) else list(L or [])
    tri = ctx.get("tri") or "revenus"
    cles = {"revenus": lambda x: (-_n(x.get("net")), -_n(x.get("abonnes"))),
            "abonnes": lambda x: (-_n(x.get("abonnes")), -_n(x.get("clics"))),
            "clics": lambda x: (-_n(x.get("clics")), -_n(x.get("abonnes"))),
            "date": lambda x: (-_n(x.get("cree_ms")), str(x.get("cree") or ""))}
    if isinstance(L, dict):
        liste = sorted(liste, key=cles.get(tri, cles["revenus"]))
    tris = " ".join(f'<a class="ong{" on" if t == tri else ""}" '
                    f'href="{_url("marketing", ctx["pseudo"], ctx["jours"], tri=t)}">{n}</a>'
                    for t, n in (("revenus", "revenu"), ("abonnes", "abonnés"), ("clics", "clics"),
                                 ("date", "date")))
    lignes = []
    for x in liste:
        nom = _e(x.get("nom")) or '<span class="faible">(sans nom)</span>'
        if x.get("id"):
            nom = f'<a href="{_url("lien", ctx["pseudo"], ctx["jours"], lien=x["id"], type="TRACKING")}">{nom}</a>'
        a_ex = x.get("brut") is not None
        lignes.append(([nom, f'c{_e(x.get("code"))}', _e(x.get("source")) or '<span class="faible">—</span>',
                        _nb(x.get("clics")), f'<b>{_nb(x.get("abonnes"))}</b>',
                        _dec(x.get("cvr_abo") if x.get("cvr_abo") is not None else x.get("conversion"))
                        + "\u00a0%",
                        _nb(x.get("payants")) if a_ex else _manque(),
                        _argent(x.get("brut"), x.get("devise") or DEVISE) if a_ex else _manque(),
                        _argent(x.get("net"), x.get("devise") or DEVISE) if a_ex else _manque(),
                        _argent(x.get("aeps_net"), x.get("devise") or DEVISE) if a_ex else _manque(),
                        _e(x.get("cree")),
                        '<span class="pill">terminé</span>' if x.get("termine") else
                        '<span class="pill ok">actif</span>'],
                       "fini" if x.get("termine") else ""))
    sous = f"{len(liste)} liens, compteurs cumulés depuis leur création"
    return (_h2("Liens de suivi", sous) + f'<div class="ongs petit">Trier par : {tris}</div>'
            + _table([("Lien", ""), ("Code", "faible"), ("Source", "faible"), ("Clics", "n"), ("Abonnés", "n"),
                      ("Conversion", "n"), ("Payants", "n"), ("Brut", "n"), ("Net", "n"),
                      ("Net / abonné", "n faible"), ("Créé le", "faible"), ("État", "")], lignes,
                     "Aucun lien de suivi (liste vide renvoyée par Infloww)."))


def _corps_marketing(b: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    h = []
    connexion = str(b.get("connexion") or "")
    L = b.get("liens")
    if L is not None:
        liste = L["liens"]
        actifs = [x for x in liste if not x["termine"]]
        clics = sum(x["clics"] or 0 for x in liste)
        abo = sum(x["abonnes"] for x in liste)
        brut = sum(x["brut"] for x in liste)
        net = sum(x["net"] for x in liste)
        h.append(_tuiles([
            _tuile(_nb(len(liste)), "liens de suivi", f"{_nb(len(actifs))} actifs · "
                                                     f"{_nb(len(liste) - len(actifs))} terminés"),
            _tuile(_nb(clics), "clics cumulés"),
            _tuile(_nb(abo), "abonnés arrivés par un lien", f"conversion {_pct(abo, clics)}"),
            _tuile(_nb(sum(x["payants"] for x in liste)), "fans payants"),
            _tuile(_argent(net), "revenu net des fans venus par lien", f"brut {_argent(brut)}")]))
        avant = [x for x in liste if connexion and x["cree"] and x["cree"] < connexion]
        maj = max([x["maj"] for x in liste] or [0])
        note = (f"Liens créés depuis le {_e(L['depuis'])} (un an d'historique) · compteurs CUMULÉS depuis la "
                "création de chaque lien, pas l'activité de la période choisie")
        if avant:
            note += (f" · {_nb(len(avant))} lien(s) créé(s) avant la connexion à Infloww "
                     f"({_e(connexion)}) sont inclus : {_nb(sum(x['abonnes'] for x in avant))} abonnés, "
                     f"{_argent(sum(x['net'] for x in avant))} nets")
        if maj:
            note += f" · compteurs rafraîchis par Infloww le {_e(_quand(maj))} UTC"
        h.append(f'<p class="note">{note}.</p>')
        if L.get("tronque"):
            h.append(_avert("Pagination arrêtée par le garde-fou sur : " + ", ".join(_e(x) for x in L["tronque"])
                            + ". Liste INCOMPLÈTE."))
        src: Dict[str, Dict[str, int]] = {}
        for x in liste:
            s = src.setdefault(x["source"] or "(sans source)",
                               {"liens": 0, "clics": 0, "abonnes": 0, "payants": 0, "brut": 0, "net": 0})
            s["liens"] += 1
            s["clics"] += x["clics"] or 0
            s["abonnes"] += x["abonnes"]
            s["payants"] += x["payants"]
            s["brut"] += x["brut"]
            s["net"] += x["net"]
        maxi = max([s["net"] for s in src.values()] or [1]) or 1
        h.append(_h2("Par source", "Instagram, Twitter, Threads… classées au revenu, pas aux abonnés"))
        h.append(_table([("Source", ""), ("Liens", "n"), ("Clics", "n"), ("Abonnés", "n"), ("Conv.", "n"),
                         ("Payants", "n"), ("Brut", "n"), ("Net", "n"), ("Net / abonné", "n"), ("", "barre-c")],
                        [[_e(k), _nb(s["liens"]), _nb(s["clics"]), _nb(s["abonnes"]), _pct(s["abonnes"], s["clics"]),
                          _nb(s["payants"]), _argent(s["brut"]), _argent(s["net"]),
                          _argent(s["net"] / s["abonnes"]) if s["abonnes"] else "—", _barre(s["net"], maxi)]
                         for k, s in sorted(src.items(), key=lambda kv: -kv[1]["net"])]))
        h.append(_bloc_liens(b, ctx))
        h.append('<p class="note">Cliquer sur un lien pour voir ses fans et ce que chacun a dépensé.</p>')
    h.append(_err(b, "liens"))
    for k, titre in (("essais", "Liens d'essai gratuit"), ("campagnes", "Promotions de profil")):
        h.append(_h2(titre))
        h.append(_err(b, k))
        X = b.get(k)
        if X is None:
            continue
        vide = (f"Aucun (liste vide renvoyée par Infloww pour les liens créés depuis le {_e(X['depuis'])}).")
        lignes = []
        for x in sorted(X["liens"], key=lambda x: -x["cree_ms"]):
            nom = _e(x["nom"] or x["message"]) or '<span class="faible">(sans nom)</span>'
            if x["id"]:
                nom = f'<a href="{_url("lien", ctx["pseudo"], ctx["jours"], lien=x["id"], type=x["type"])}">{nom}</a>'
            base = [nom, _e(x["code"] or x["type_campagne"]) or "—",
                    f"{_nb(x['duree_essai'])}\u00a0j" if x["duree_essai"] else "—",
                    _nb(x["limite"]) if x["limite"] else '<span class="faible">sans</span>',
                    _nb(x["abonnes"]), _nb(x["payants"]), _argent(x["brut"], x["devise"]),
                    _argent(x["net"], x["devise"]), _e(x["cree"]), _e(x["expire"]) or "—",
                    '<span class="pill">terminé</span>' if x["termine"] else '<span class="pill ok">actif</span>']
            if k == "campagnes":
                base.insert(2, _e(x["remise"]) or "—")
            lignes.append((base, "fini" if x["termine"] else ""))
        cols = [("Lien", ""), ("Code" if k == "essais" else "Type", "faible"), ("Durée", "n"), ("Limite", "n"),
                ("Abonnés", "n"), ("Payants", "n"), ("Brut", "n"), ("Net", "n"), ("Créé le", "faible"),
                ("Expire le", "faible"), ("État", "")]
        if k == "campagnes":
            cols.insert(2, ("Remise", "n"))
        h.append(_table(cols, lignes, vide))
    return "".join(h)


def _corps_lien(b: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    h = [f'<p><a href="{_url("marketing", ctx["pseudo"], ctx["jours"])}">← tous les liens</a></p>']
    I = b.get("lien_info")
    x = (I or {}).get("lien")
    if x:
        h.append(f'<h2>{_e(x["nom"]) or "(sans nom)"} <span class="faible">— code {_e(x["code"])} · '
                 f'{_e(x["source"]) or "sans source"} · créé le {_e(x["cree"])}'
                 f'{" · terminé" if x["termine"] else ""}</span></h2>')
    elif I is not None:
        h.append(_avert(f"Lien #{_e(b.get('lien_id'))} introuvable parmi les liens créés depuis le "
                        f"{_e(I.get('depuis'))} : ses fans s'affichent quand même, sans recoupement."))
    h.append(_err(b, "lien_info"))
    h.append(_err(b, "fans_lien"))
    F = b.get("fans_lien")
    if F is None:
        return "".join(h)
    tb = sum(v[0] for v in F["totaux"].values())
    tn = sum(v[1] for v in F["totaux"].values())
    t = [_tuile(_nb(F["nb_fans"]), "fans distincts", f"{_nb(F['recues'])} lignes reçues en {_nb(F['pages'])} page(s)"),
         _tuile(_nb(len(F["payants"])), "fans payants", _pct(len(F["payants"]), F["nb_fans"])),
         _tuile(_argent(tb), "dépensé (brut)", f"net {_argent(tn)}")]
    if x:
        t.append(_tuile(_argent(x["brut"]), "revenu brut du lien", f"{_nb(x['abonnes'])} abonnés · "
                                                                  f"{_nb(x['payants'])} payants"))
    h.append(_tuiles(t))
    if x:
        if tb == x["brut"]:
            h.append(f'<p class="note">Recoupement : la somme par fan égale le revenu brut du lien '
                     f"({_argent(tb)}).</p>")
        else:
            h.append(_avert(f"Écart de recoupement : somme par fan {_argent(tb)}, revenu brut du lien "
                            f"{_argent(x['brut'])}. Les fans ont jusqu'à 4 h de retard sur les compteurs "
                            "du lien ; un écart durable voudrait dire des fans perdus."))
    if F.get("tronque"):
        h.append(_avert(f"Lecture arrêtée après {_nb(F['pages'])} pages (garde-fou, ou aucune avancée "
                        "du curseur) : liste INCOMPLÈTE."))
    if len(F.get("devises") or []) > 1:
        h.append(_avert("Plusieurs devises parmi ces fans : " + ", ".join(_e(d) for d in F["devises"]) + "."))
    h.append(f'<p class="note">Doublons d\'Infloww retirés (même ligne en double, on garde la plus haute ; '
             f"les pages se recouvrent volontairement d'une ligne pour ne pas perdre de jumeau) : "
             f"{_nb(F['recues'])} lignes reçues pour {_nb(F['nb_fans'])} fans.</p>")
    h.append(_h2("Par catégorie"))
    h.append(_table([("Catégorie", ""), ("Brut", "n"), ("Net", "n"), ("Part", "n")],
                    [[_e(k), _argent(v[0]), _argent(v[1]), _pct(v[0], tb)] for k, v in F["totaux"].items()]))
    pm = F.get("par_mois") or {}
    maxi = max(list(pm.values()) or [1]) or 1
    h.append(_h2("Abonnements par mois", "date d'abonnement des fans venus par ce lien"))
    h.append(_table([("Mois", ""), ("Fans", "n"), ("", "barre-c")],
                    [[_e(m), _nb(v), _barre(v, maxi)] for m, v in sorted(pm.items(), reverse=True)]))
    pay = F["payants"]
    montres = pay[:500]
    h.append(_h2("Fans payants", f"{_nb(len(pay))}, du plus dépensier au moins"))
    h.append(_table([("Fan", ""), ("Abonné le", "faible"), ("Messages", "n"), ("Tips", "n"), ("Posts", "n"),
                     ("Autres", "n"), ("Total brut", "n"), ("Total net", "n")],
                    [[(_e(f["nom"]) or '<span class="faible">(sans nom)</span>')
                      + f' <span class="faible">#{_e(f["fan"])}</span>', _e(_jour_utc(f["t"])),
                      _argent(f["messages"][0], f["devise"]), _argent(f["tips"][0], f["devise"]),
                      _argent(f["posts"][0], f["devise"]),
                      _argent(f["abonnement"][0] + f["streams"][0], f["devise"]),
                      f'<b>{_argent(f["total_brut"], f["devise"])}</b>', _argent(f["total_net"], f["devise"])]
                     for f in montres], "Aucun fan n'a dépensé via ce lien."))
    rest = []
    if len(pay) > len(montres):
        rest.append(f"{_nb(len(pay) - len(montres))} fans payants de plus, non listés (limite d'affichage 500)")
    if F["nb_fans"] > len(pay):
        rest.append(f"{_nb(F['nb_fans'] - len(pay))} fans sans aucune dépense, comptés mais pas listés un par un")
    if rest:
        h.append(f'<p class="note">{" · ".join(rest)}.</p>')
    return "".join(h)


# ── messages ──
# Liste complète de la doc v1.4 (pas de 4). L'API rend le code tantôt en
# nombre, tantôt en texte : on cherche avec _n(), sinon « 2 » restait
# « non documenté ».
_DECLENCHEURS = {1: "relance quand le fan se connecte", 2: "bienvenue (nouvel abonné)",
                 3: "suite d'achat (PPV acheté)", 5: "abonnement bientôt expiré",
                 6: "abonnement expiré", 7: "réabonnement", 8: "anniversaire du fan"}
_RETRAITS = {1: "retiré à la main", 2: "retiré par le système"}


def _apercu_msg(x: Dict[str, Any]) -> str:
    for c in x.get("collections") or []:
        for m in c.get("messages") or []:
            if m.get("texte"):
                return _e(m["texte"])
    return '<span class="faible">—</span>'


def _corps_messages(b: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    h = []
    ann = _annuaire(b)
    C = b.get("chat")
    h.append(_h2("Messages envoyés par le compte", "toutes équipes confondues"))
    h.append(_err(b, "chat"))
    if C is not None:
        tr = [t for t in C["tranches"] if not t.get("vide")]
        msg = sum(t["messages"] for t in tr)
        ppv = sum(t["ppv"] for t in tr)
        if len(C["tranches"]) == 1 and tr:
            t0 = tr[0]
            h.append(_tuiles([_tuile(_nb(msg), "messages envoyés"), _tuile(_nb(ppv), "PPV envoyés"),
                              _tuile(_nb(t0["fans"]), "fans distincts contactés"),
                              _tuile(_duree_ms(t0["reponse_ms"]), "délai moyen de réponse")]))
        else:
            h.append(_tuiles([_tuile(_nb(msg), "messages envoyés"), _tuile(_nb(ppv), "PPV envoyés")]))
            h.append(_table([("Tranche", ""), ("Messages", "n"), ("PPV", "n"), ("Fans distincts", "n"),
                             ("Délai moyen", "n")],
                            [[f"{_e(t['debut'])} → {_e(t['fin'])}"] + (
                                [_nb(t["messages"]), _nb(t["ppv"]), _nb(t["fans"]), _duree_ms(t["reponse_ms"])]
                                if not t.get("vide") else [_manque()] * 4) for t in C["tranches"]]))
            h.append('<p class="note">Fans distincts et délai par tranche de 31 jours : Infloww les '
                     "dédoublonne et les pondère sur la fenêtre, ils ne s'additionnent pas.</p>")
        vides = [t for t in C["tranches"] if t.get("vide")]
        if vides:
            h.append(_avert(f"{len(vides)} tranche(s) sans aucune ligne dans la réponse d'Infloww."))
        J = C["jours"]
        maxi = max([j.get("messages", 0) for j in J] or [1]) or 1
        lignes = []
        for j in reversed(J):
            if j.get("erreur"):
                lignes.append(([_e(j["date"]), f'<span class="pill ko" title="{_e(j["erreur"])}">erreur</span>',
                                "", "", "", ""], ""))
            elif j.get("vide"):
                lignes.append([_e(j["date"]), _manque(), "", _manque(), _manque(), _manque()])
            else:
                lignes.append([_e(j["date"]), _nb(j["messages"]), _barre(j["messages"], maxi), _nb(j["ppv"]),
                               _nb(j["fans"]), _duree_ms(j["reponse_ms"])])
        h.append(_h2("Jour par jour", f"depuis le {_e(C['jours_depuis'])} (31 jours au plus : un appel par jour)"))
        h.append(_table([("Date", "nw"), ("Messages", "n"), ("", "barre-c"), ("PPV", "n"), ("Fans", "n"),
                         ("Délai moyen", "n")], lignes))
        err_j = [j for j in J if j.get("erreur")]
        if err_j:
            h.append(_avert(f"{len(err_j)} jour(s) illisible(s) : {_e(err_j[0]['erreur'])}"))
    for k, titre, cle_decl in (("automatiques", "Messages automatiques", True),
                               ("prioritaires", "Envois de masse prioritaires", False)):
        h.append(_h2(titre, f"créés depuis le {_e(b.get('depuis'))} · compteurs cumulés depuis la création"))
        h.append(_err(b, k))
        X = b.get(k)
        if X is None:
            continue
        L = X["lignes"]
        if L:
            h.append(_tuiles([
                # un seul statut par tuile : compter « Active » dans les terminés
                # (ou l'inverse) gonflait le chiffre de ce qui tourne encore
                _tuile(_nb(len([x for x in L if x["statut"] == ("Active" if cle_decl else "Completed")])),
                       "actifs" if cle_decl else "terminés", f"sur {_nb(len(L))}"),
                _tuile(_nb(sum(x["envois"] for x in L)), "envois"),
                _tuile(_nb(sum(x["achats"] for x in L)), "achats"),
                _tuile(_argent(sum(x["revenu"] for x in L)), "revenu")]))
        if X.get("tronque"):
            h.append(_avert("Pagination arrêtée par le garde-fou : liste INCOMPLÈTE."))
        lignes = []
        ordre = (lambda x: (x["statut"] != "Active", -x["envois"])) if cle_decl else (lambda x: -x["cree"])
        for x in sorted(L, key=ordre):
            st = x["statut"] or "?"
            pill = "ok" if st in ("Active", "Completed") else ("ko" if st == "Canceled" else "att")
            etat = f'<span class="pill {pill}">{_e(st)}</span>'
            if x.get("retire"):
                r = _n(x["retire"])
                etat += (f' <span class="pill att" title="unsentType {_e(r)}">'
                         f'{_e(_RETRAITS.get(r, "retiré"))}</span>')
            if x.get("echec"):
                etat += f' <span class="pill ko">{_e(x["echec"])}</span>'
            decl = x.get("declencheur")
            decl_t = (f"{_e(decl)} — {_e(_DECLENCHEURS.get(_n(decl), 'non documenté'))}"
                      if decl is not None else "—")
            ligne = [_e(_quand(x["cree"])), etat]
            if cle_decl:
                ligne.append(decl_t)
            ligne += [_e(", ".join(x["listes"])) or "—", _e(", ".join(x["exclues"])) or "—",
                      _nb(x["envois"]), _nb(x["achats"]), _argent(x["revenu"]),
                      _argent(x["prix"]) if x["prix"] else '<span class="faible">gratuit</span>',
                      _nom_employe(x["employe"], ann),
                      _nom_employe(x["annule_par"] or x["retire_par"], ann) if (x["annule_par"] or x["retire_par"])
                      else '<span class="faible">—</span>',
                      _nb(len(x["collections"])), _apercu_msg(x)]
            lignes.append(ligne)
        # largeurs minimales : sans elles, les listes de fans s'écrasaient
        # sur six lignes ; le tableau défile plutôt en largeur
        cols = [("Créé le (UTC)", "faible nw"), ("État", "nw")]
        if cle_decl:
            cols.append(("Déclencheur", "liste"))
        cols += [("Listes visées", "liste"), ("Exclues", "faible liste"), ("Envois", "n"), ("Achats", "n"), ("Revenu", "n"),
                 ("Prix", "n"), ("Posé par", ""), ("Annulé / retiré par", "faible"), ("Variantes", "n faible"),
                 ("Premier message", "msg")]
        h.append(_table(cols, lignes, f"Aucun (liste vide renvoyée par Infloww depuis le {_e(b.get('depuis'))})."))
    if "prioritaires" in b:
        h.append('<p class="note">Seuls les envois « prioritaires » remontent par l\'API, pas les envois de '
                 "masse ordinaires (hypothèse tirée du volume). « Terminé » ne dit pas que le message est encore "
                 "visible : un envoi terminé peut porter « retiré ».</p>")
    h.append(_err(b, "employes"))
    return "".join(h)


# ── journal ──
def _corps_journal(b: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    h = []
    ann = _annuaire(b)
    c = b.get("creatrice") or {}
    T = b.get("toutes")
    lisibles = {str(x.get("id")) for x in b.get("connectees") or []}
    suiv = {s.lower() for s in suivies()}
    noms = {str(x.get("id")): str(x.get("userName") or x.get("name") or "") for x in b.get("connectees") or []}
    h.append(_h2("Créatrices de l'agence", "toutes, déconnectées et supprimées comprises"))
    h.append(_err(b, "toutes"))
    if T is not None:
        for x in T:
            noms.setdefault(x["id"], x["pseudo"] or x["nom"])
        h.append(_table([("Nom", ""), ("Pseudo", ""), ("Statut", ""), ("Connectée le", "faible"),
                         ("Supprimée le", "faible"), ("Lisible par la clé", ""), ("Suivie ici", "")],
                        [[_e(x["surnom"] or x["nom"]), "@" + _e(x["pseudo"]),
                          f'<span class="pill {"ok" if x["statut"] == "connected" else "ko"}">{_e(x["statut"] or "?")}</span>',
                          _e(_jour_utc(x["connexion"])) or "—", _e(_jour_utc(x["suppression"])) or "—",
                          "oui" if x["id"] in lisibles else '<span class="faible">non</span>',
                          "oui" if x["pseudo"].lower() in suiv else '<span class="faible">non</span>']
                         for x in T], "Aucune créatrice renvoyée."))
    h.append(_h2("Connexions et déconnexions", f"depuis le {_e(max(JOURNAL_DEPUIS, _aujourdhui() - dt.timedelta(days=HISTORIQUE_JOURS)))}"
                                                " (le journal n'existe pas avant le 1er juin 2026)"))
    h.append(_err(b, "statuts"))
    S = b.get("statuts")
    if S is not None:
        if S and S[0].get("tronque"):
            h.append(_avert("Plus de 2 000 changements dans une fenêtre : lecture arrêtée, liste INCOMPLÈTE."))
            S = S[1:]
        h.append(_table([("Quand (UTC)", "nw"), ("Créatrice", ""), ("Avant", "faible"), ("Après", ""), ("Par", "")],
                        [([_e(_quand(x["t"])), ("<b>" if x["creatrice"] == str(c.get("id")) else "")
                           + "@" + _e(noms.get(x["creatrice"]) or x["creatrice"])
                           + ("</b>" if x["creatrice"] == str(c.get("id")) else ""),
                           _e(x["avant"]) if x["avant"] is not None else '<span class="faible">(première liaison)</span>',
                           f'<span class="pill {"ok" if x["apres"] == "connected" else "ko"}">{_e(x["apres"])}</span>',
                           _nom_employe(x["par"], ann) if x["par"] else '<span class="faible">automatique</span>'])
                         for x in S], "Aucun changement de statut sur la période lue."))
    h.append(_h2("Ventes réattribuées à la main", "toute l'agence, sur la période choisie"))
    h.append(_err(b, "reassign"))
    R = b.get("reassign")
    if R is not None:
        if R.get("tronque"):
            h.append(_avert("Pagination arrêtée par le garde-fou : liste INCOMPLÈTE."))
        h.append(_table([("Quand (UTC)", "nw"), ("Opération", ""), ("Vente", "faible"), ("Avant", ""),
                         ("Après", ""), ("Faite par", "")],
                        [[_e(_quand(x["t"])), _e(x["operation"]), _e(x["tx"]),
                          _nom_employe(x["avant"], ann) if x["avant"] else '<span class="faible">personne</span>',
                          _nom_employe(x["apres"], ann) if x["apres"] else '<span class="faible">personne</span>',
                          _nom_employe(x["par"], ann)] for x in sorted(R["lignes"], key=lambda x: -x["t"])],
                        "Aucune vente réattribuée sur la période."))
    h.append(_err(b, "employes"))
    return "".join(h)


RENDUS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], str]] = {
    "apercu": _corps_apercu, "revenus": _corps_revenus, "equipe": _corps_equipe,
    "marketing": _corps_marketing, "lien": _corps_lien, "messages": _corps_messages,
    "journal": _corps_journal,
}


def page_html(pseudo: str, jours: int, bilan_: Optional[Dict[str, Any]] = None,
              erreur: Optional[ErreurInfloww] = None, vue: Optional[str] = None,
              opts: Optional[Dict[str, Any]] = None) -> str:
    opts = opts or {}
    b = bilan_ or {}
    vue = vue or b.get("vue") or "apercu"
    if vue not in RENDUS:
        vue = "apercu"
    ctx = {"pseudo": pseudo, "jours": jours, "vue": vue, "tri": opts.get("tri") or "revenus"}
    vue_nav = "marketing" if vue == "lien" else vue
    vues = "".join(f'<a class="vue{" on" if v == vue_nav else ""}" href="{_url(v, pseudo, jours)}">{_e(n)}</a>'
                   for v, n in VUES)
    extra = {"lien": opts.get("lien"), "type": opts.get("type")} if vue == "lien" else {}
    onglets = "".join(
        f'<a class="ong{" on" if p == jours else ""}" href="{_url(vue, pseudo, p, **extra)}">{p} jours</a>'
        for p in PERIODES)
    s = suivies()
    autres = "".join(
        f'<a class="ong{" on" if x == pseudo else ""}" href="{_url(vue_nav, x, jours)}">@{_e(x)}</a>'
        for x in s) if len(s) > 1 else ""
    if erreur is not None:
        corps = _boite_err("Infloww n'a pas répondu.", erreur)
    else:
        try:
            corps = RENDUS[vue](b, ctx)
        except Exception as e:
            # un bug d'affichage est dit sur la page, pas en page blanche
            corps = _boite_err("La page n'a pas pu être construite.", ErreurInfloww(f"{type(e).__name__} : {e}"))
    # les créatrices connectées que la page ne suit pas : dit, avec la marche à suivre
    non_suivies = [str(x.get("userName") or "") for x in b.get("connectees") or []
                   if str(x.get("userName") or "").lower() not in {v.lower() for v in s} and x.get("userName")]
    invite = ""
    if non_suivies:
        exemple = json.dumps({"suivies": s + non_suivies}, ensure_ascii=False)
        invite = (f'<p class="note">Également connectées à Infloww, non suivies ici : '
                  f'{", ".join("@" + _e(x) for x in non_suivies)}. Pour les afficher : '
                  f"<code>data/infloww_config.json</code> → <code>{_e(exemple)}</code></p>")
    suivi = opts.get("suivi") or {}
    pied = [f"Adresses lues par cette vue : {', '.join('<code>' + _e(a) + '</code>' for a in ADRESSES.get(vue, ()))}."]
    if suivi:
        pa = suivi.get("plus_ancien")
        pied.append(f"{_nb(suivi.get('appels', 0))} requête(s) envoyée(s) à Infloww pour cette page, "
                    f"{_nb(suivi.get('caches', 0))} lecture(s) servie(s) par le cache"
                    + (f" (la plus ancienne du {dt.datetime.fromtimestamp(pa).strftime('%d/%m à %Hh%M')})" if pa else "")
                    + ". Quota : 1 000 requêtes/minute pour toute l'agence.")
    titre = NOMS_VUES.get(vue, "")
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Infloww · {_e(titre)}</title>
<style>
:root{{--fond:#151515;--carte:#242424;--bord:#3a3a3a;--texte:#f2f2f2;--faible:#9a9a9a;--bleu:#1677FF;--rouge:#ef4444;--vert:#22c55e;--ambre:#f59e0b}}
body{{margin:0;background:var(--fond);color:var(--texte);font:14px/1.5 -apple-system,system-ui,sans-serif;padding:24px 16px;max-width:1200px;margin:auto}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:28px 0 10px}}
a{{color:#69a7ff}}
.sous{{color:var(--faible);margin:0 0 12px;font-size:13px}}
.vues{{display:flex;gap:2px;flex-wrap:wrap;border-bottom:1px solid var(--bord);margin:0 0 14px}}
.vue{{padding:8px 12px;color:var(--faible);text-decoration:none;border-bottom:2px solid transparent;font-size:14px}}
.vue.on{{color:var(--texte);border-bottom-color:var(--bleu);font-weight:600}}
.ongs{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;align-items:center}}
.ongs.petit{{font-size:12px;color:var(--faible);margin:-2px 0 10px}}
.ong{{padding:6px 12px;border:1px solid var(--bord);border-radius:8px;color:var(--faible);text-decoration:none;font-size:13px}}
.ongs.petit .ong{{padding:3px 9px;font-size:12px}}
.ong.on{{background:var(--bleu);border-color:var(--bleu);color:#fff}}
.tuiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr));gap:10px;margin:0 0 6px}}
.tuile{{background:var(--carte);border:1px solid var(--bord);border-radius:12px;padding:14px 16px}}
.tuile .v{{font-size:24px;font-weight:700;white-space:nowrap}} .tuile .l{{color:var(--faible);font-size:12px}}
.tuile .s{{color:var(--faible);font-size:11px;margin-top:4px}}
.note{{color:var(--faible);font-size:12px;margin:10px 0 0}}
.vide{{color:var(--faible);font-size:13px;background:var(--carte);border:1px dashed var(--bord);border-radius:12px;padding:12px 14px}}
table{{width:100%;border-collapse:collapse;background:var(--carte);border:1px solid var(--bord);border-radius:12px;overflow:hidden}}
th,td{{padding:7px 10px;border-bottom:1px solid var(--bord);text-align:left;font-size:13px;vertical-align:top}}
th{{color:var(--faible);font-weight:600;font-size:12px;white-space:nowrap}}
.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}} .fort{{font-weight:700;color:#fff}} .faible{{color:var(--faible)}}
td.msg{{min-width:220px;color:var(--faible);font-size:12px}} td.liste{{min-width:150px}} .nw{{white-space:nowrap}}
.barre-c{{width:22%;min-width:80px}} .barre{{display:block;background:rgba(255,255,255,.04);border-radius:4px}}
.barre span{{display:block;height:8px;border-radius:4px;background:var(--bleu)}}
tr.fini td{{opacity:.5}} tr.faible td{{color:var(--faible)}} tr.sans td{{background:rgba(239,68,68,.06)}}
.pill{{display:inline-block;padding:0 7px;border-radius:999px;font-size:11px;border:1px solid var(--bord);color:var(--faible);white-space:nowrap}}
.pill.ok{{color:var(--vert);border-color:rgba(34,197,94,.45)}} .pill.ko{{color:var(--rouge);border-color:rgba(239,68,68,.45)}}
.pill.att{{color:var(--ambre);border-color:rgba(245,158,11,.45)}}
.err{{background:rgba(239,68,68,.12);border:1px solid var(--rouge);border-radius:12px;padding:14px 16px;margin:10px 0}}
.err .conseil{{color:var(--texte)}}
.avert{{background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.6);border-radius:12px;padding:10px 14px;margin:10px 0;font-size:13px}}
.table-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.pied{{color:var(--faible);font-size:12px;border-top:1px solid var(--bord);margin-top:32px;padding-top:12px}}
code{{font-size:12px;overflow-wrap:anywhere}}
@media (max-width:480px){{.tuiles{{grid-template-columns:1fr 1fr}} .tuile{{padding:12px}} .tuile .v{{font-size:19px}}}}
</style></head><body>
<h1>Infloww · {_e(titre)}</h1>
<p class="sous">Source : API officielle d'Infloww, en lecture seule. Page à part : elle ne nourrit ni le podium ni la paie.</p>
<nav class="vues">{vues}</nav>
<div class="ongs">{onglets}</div>{f'<div class="ongs">{autres}</div>' if autres else ""}
{corps}
{invite}
<div class="pied">{"<br>".join(pied)}</div>
</body></html>'''


def page(args: Mapping[str, Any]) -> str:
    """La page entière à partir des paramètres de l'URL, validés ici.

    Ne lève jamais : une panne s'affiche SUR la page (une page blanche ferait
    croire que l'API ne renvoie rien, alors qu'elle a peut-être répondu faux).
    """
    # Même filet que plus bas : un réglage illisible ne doit pas faire une 500.
    try:
        s = suivies()
    except Exception:
        s = list(SUIVIES)
    pseudo = str(args.get("creatrice") or "")
    if pseudo not in s:
        pseudo = s[0]
    try:
        jours = int(args.get("jours") or 30)
    except (TypeError, ValueError):
        jours = 30
    if jours not in PERIODES:
        jours = 30
    vue = str(args.get("vue") or "apercu")
    if vue not in NOMS_VUES:
        vue = "apercu"
    lien = str(args.get("lien") or "")
    if not re.fullmatch(r"\d{1,20}", lien):
        lien = ""
    if vue == "lien" and not lien:
        vue = "marketing"
    type_lien = str(args.get("type") or "TRACKING").upper()
    if type_lien not in TYPES_LIEN:
        type_lien = "TRACKING"
    tri = str(args.get("tri") or "revenus")
    if tri not in TRIS_LIENS:
        tri = "revenus"
    affecter = str(args.get("affectations") or "") == "1"
    suivi: Dict[str, Any] = {"appels": 0, "caches": 0, "plus_ancien": None}
    opts = {"lien": lien, "type": type_lien, "tri": tri, "suivi": suivi}
    jeton = _SUIVI.set(suivi)
    try:
        if vue == "apercu":
            d = bilan(pseudo, jours)
        else:
            d = charger(vue, pseudo, jours, lien=lien, type_lien=type_lien, affecter=affecter)
        return page_html(pseudo, jours, d, vue=vue, opts=opts)
    except ErreurInfloww as e:
        return page_html(pseudo, jours, erreur=e, vue=vue, opts=opts)
    except Exception as e:
        return page_html(pseudo, jours, erreur=ErreurInfloww(f"{type(e).__name__} : {e}"), vue=vue, opts=opts)
    finally:
        _SUIVI.reset(jeton)
