"""La page perso d'un VA de TRUST INSTAGRAM (et de TRUST TWITTER et THREADS depuis le 04/11) :
ses chiffres, à lui seul.

Propriétaire, 03/11/2026 : « un petit lien perso pour chaque VA où il voit
uniquement son tracking link. Il voit depuis toujours, aujourd'hui, cette
quinzaine, quinzaine précédente. Il voit les clics sur Get My Social, les clics
globaux, les clics sur Inflow et les subs », puis « c'est pour le serveur
Instagram », donné par un bouton du ticket. Devant la maquette : pas la liste
de ses trackings, et « le truc de base, quinzaine et tout, comme d'hab » : le
choix de la période de la page Lia (raccourcis et dates), une période à la fois.
« 📈 Mes stats » y était déjà (subs_va._texte_stats) : son message porte
maintenant le lien, plutôt qu'un sixième bouton qui aurait fait refuser tout
le menu (5 par rangée).

- Les chiffres sont ceux de « Mes stats », par les MÊMES fonctions : subs
  MyPuls de tous ses trackings à son nom (Lia, sa variante Seren, Emy d'avant
  le 28/10 : subs_va.subs_du_va et subs_depuis_toujours), clics de son lien
  GetMySocial (podium_discord.clics_du_va, US et tous pays). Deux règles
  auraient donné au VA deux chiffres pour la même chose.
- Clics Infloww : ses liens de suivi Lia (compte Infloww « aileney »), par les
  relevés quotidiens de la page Lia (infloww_liens, profil « lia ») — Infloww
  ne donne que des cumuls. Seren n'est pas chez Infloww ; ses anciens liens
  Emy n'ont que leur cumul : ils ne comptent que dans « depuis toujours »
  (sans marque sur la page : propriétaire, 03/11, « retire ça »).
- Une clé par VA (data/stats_va_cles.json, 0600, hors git), comparée en temps
  constant. Clé fausse, VA sans fiche ou parti : 404, la même page, pour ne
  rien apprendre à qui devine.
- Comme une ligne de la page Lia (propriétaire, 03/11 : « je veux comme ça :
  @ du mec, CVR, truc par sub et après combien il gagne ») : CVR = subs ÷
  visites MyPuls de ses liens de suivi (le même compteur d'OnlyFans que les
  clics Infloww, vérifié le 03/11 : 87 = 87, et Seren y est), $ / sub =
  revenu net MyPuls de ses liens ÷ subs (le « par abonné », admis chez les
  VA), Gagné = sa paie selon la grille de TRUST INSTAGRAM (GRILLE) — aux
  clics pour TRUST THREADS (GRILLE_CLICS_ICI, 04/11/2026). Jamais le
  revenu de l'agence en total, ni paiement ni gain / perte du propriétaire.
- En bas, les sources, et rien d'autre (propriétaire, 03/11, devant un bloc
  de preuves détaillé : « pas fan, plus propre, juste en bas : API officielle
  d'Infloww utilisée, avec la doc, et aussi pour GetMySocial, c'est tout ») :
  chaque API nommée, liée à sa documentation officielle.
"""
from __future__ import annotations

import datetime as dt
import functools
import hmac
import html as _html
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import domaines
import safe_json

AGENCY_IG_ID = "1488331963575177247"
TWITTER_ID = "1445108485090971710"
#: Les serveurs dont « Mes stats » donne le lien de la page. TRUST TWITTER
#: depuis le 04/11/2026 (propriétaire, devant « pas lisible » dans Mes stats :
#: « mets en place le lien avec l'API Infloww, l'API GetMySocial et tout, un
#: peu comme sur Instagram, pour qu'ils aient directement accès à ce lien-là
#: avec leurs statistiques ») ; même grille de paie (« la même qu'Instagram »).
#: TRUST THREADS depuis le 04/11/2026 aussi (propriétaire, devant le menu en
#: blocs de Threads : « il manque les trucs pour mes stats et tout [...] un
#: peu comme sur Twitter ») : même page, même grille.
THREADS_ID = "1498948161039896586"
SERVEURS = {AGENCY_IG_ID, TWITTER_ID, THREADS_ID}
#: Le bandeau de la page et le nom du lien, par serveur.
MARQUES = {AGENCY_IG_ID: ("TRUST INSTAGRAM", "Instagram"), TWITTER_ID: ("TRUST TWITTER", "Twitter"),
           THREADS_ID: ("TRUST THREADS", "Threads")}
# POLE TWITTER FR (27/11/2026) : la même page, ses chiffres viennent de
# pole_twitter_fr.chiffres_stats (son propre registre de liens, une page par model)
POLE_TWITTER_FR_ID = "1575133611311763578"
MARQUES[POLE_TWITTER_FR_ID] = ("POLE TWITTER FR", "Twitter")
#: trust-ofm.com depuis le 07/11/2026 (domaines.py) : les liens youl4b.com
#: déjà donnés marchent toujours, c'est la même application.
SITE = domaines.SITE_TRUST
DATA_DIR = Path(__file__).resolve().parent / "data"
CLES_FICHIER = DATA_DIR / "stats_va_cles.json"
#: Les sources des chiffres et leur documentation officielle, en bas de la page
#: (la doc API de GetMySocial ne s'ouvre qu'à un compte connecté).
SOURCES = (("Infloww", "https://infloww-openapi.stoplight.io"),
           ("GetMySocial", "https://getmysocial.com/docs"),
           ("MyPuls", "https://mypuls.app/api/doc"))
#: Une page relue au plus toutes les 10 min : chaque lecture coûte une dizaine
#: d'appels GetMySocial (quota de 10 000 lectures par jour et par clé).
CACHE_S = 600
#: La créatrice et le compte Infloww des liens comptés en « Clics Infloww ».
CREATRICE_INFLOWW = "liasxcret"
EMY = "emy.brw"

_VERROU = threading.Lock()
_VERROUS_VA: Dict[str, threading.Lock] = {}
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_RE_TRACKING = re.compile(r"onlyfans\.com/([^/?#]+)/c(\d+)", re.I)


# ─── la clé de chaque VA ─────────────────────────────────────────────────
def _cles() -> Dict[str, Any]:
    d = safe_json.load(CLES_FICHIER, {})
    return d if isinstance(d, dict) else {}


def jeton(gid: Any, uid: Any) -> str:
    """La clé de ce VA, créée au premier appel puis toujours la même : un VA
    qui garde son lien ne le perd pas à chaque clic. Lève OSError si elle n'a
    pas pu être écrite (un lien qui n'ouvrirait rien ne doit pas partir)."""
    k = f"{gid}:{uid}"
    with _VERROU:
        d = _cles()
        f = d.get(k)
        if isinstance(f, dict) and len(str(f.get("jeton") or "")) >= 20:
            return str(f["jeton"])
        t = secrets.token_urlsafe(24)
        d[k] = {"jeton": t, "cree": int(time.time())}
        if not safe_json.write(CLES_FICHIER, d):
            raise OSError(f"clé de la page perso non écrite ({CLES_FICHIER})")
        try:
            CLES_FICHIER.chmod(0o600)
        except Exception:
            pass
        return t


def qui(t: Any) -> Optional[Tuple[str, str]]:
    """(gid, uid) du VA dont c'est la clé, None sinon. Toutes les clés sont
    comparées, sans sortie anticipée. Ne lève pas."""
    s = str(t or "").encode("utf-8")
    if len(s) < 20:
        return None
    trouve = None
    try:
        cles = _cles()
    except Exception as e:
        print(f"[stats-va] clés illisibles : {type(e).__name__}: {e}", flush=True)
        return None
    for k, f in cles.items():
        bonne = str((f or {}).get("jeton") or "").encode("utf-8") if isinstance(f, dict) else b""
        if bonne and hmac.compare_digest(s, bonne) and ":" in str(k):
            trouve = tuple(str(k).split(":", 1))
    return trouve


def lien(gid: Any, uid: Any) -> str:
    """L'adresse de la page de ce VA ; "" hors des SERVEURS."""
    if str(gid or "") not in SERVEURS or not str(uid or "").isdigit():
        return ""
    return f"{domaines.site(gid)}/mes-stats?t={jeton(gid, uid)}"


# ─── les chiffres ────────────────────────────────────────────────────────
def _codes(trackings: List[str], createrice: str) -> List[str]:
    import podium_discord as pod
    out = []
    for u in trackings:
        m = _RE_TRACKING.search(str(u or ""))
        # « c040 » chez OnlyFans est « 40 » chez Infloww (_code_infloww) ; un
        # compte renommé (emy.brww) garde son ancien nom (pod.pseudo_of)
        if m and pod.pseudo_of(m.group(1)) == createrice and str(int(m.group(2))) not in out:
            out.append(str(int(m.group(2))))
    return out


def _paris(ts: Any) -> Optional[dt.datetime]:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(float(ts), ZoneInfo("Europe/Paris"))
    except Exception:
        return None


def _infloww_cumuls(createrice: str) -> Tuple[Optional[Dict[str, int]], str]:
    """{code: clics depuis la création} des liens de suivi de cette créatrice
    chez Infloww (lecture seule, sans relevé)."""
    import infloww_liens as il
    i = il._infloww(createrice)
    if i.get("erreur"):
        return None, str(i["erreur"])[:200]
    out: Dict[str, int] = {}
    for x in i.get("liens") or []:
        code, n = il._code_infloww(x), il._entier(x.get("clics"))
        if code and n is not None:
            out[code] = n
    return out, ""


def _clics_infloww(trackings: List[str], du: str, au: str, toujours: bool) -> Dict[str, Any]:
    """{n} : clics Infloww de ses liens Lia sur la période (+ ses anciens liens
    Emy depuis toujours : Infloww ne date pas leurs clics) ; None si un de ses
    liens n'a pas de relevé, jamais un zéro inventé."""
    import infloww_liens as il
    codes_lia, codes_emy = _codes(trackings, CREATRICE_INFLOWW), _codes(trackings, EMY)
    if not codes_lia and not codes_emy:
        return {"n": None}
    try:
        lia = il.profil("lia")
        m, _r = lia._clics_cvr() if toujours else lia._clics_cvr(du, au)
    except Exception as e:                                   # noqa: BLE001
        print(f"[stats-va] clics Infloww illisibles : {type(e).__name__}: {e}", flush=True)
        m = None
    n = sum(int(m[c]) for c in codes_lia) if m is not None and all(c in m for c in codes_lia) else None
    if not codes_emy:
        return {"n": n}
    if toujours:
        emy, _raison = _infloww_cumuls(EMY)
        if n is not None and emy is not None and all(c in emy for c in codes_emy):
            return {"n": n + sum(int(emy[c]) for c in codes_emy)}
        return {"n": None}
    return {"n": n}


#: La grille de paie de TRUST INSTAGRAM (propriétaire, 03/11/2026, « comme pour
#: la paye Instagram ») : TOUS les subs d'une quinzaine au prix du palier que
#: leur nombre total sur la quinzaine atteint.
GRILLE = ((1250, 1.20), (1000, 1.00), (800, 0.90), (500, 0.80), (0, 0.70))
#: Un prix unique par sub, pour UNE quinzaine (sa clé : son premier jour) et par
#: serveur : il passe devant GRILLE, qui reste telle quelle. Propriétaire, le
#: 16/11/2026 : « sur Twitter et sur Instagram, durant cette quinzaine, je vais
#: payer chaque sub $1 [...] uniquement pour cette quinzaine, du 16 au 31, je
#: te redis si je continue [...] tu gardes bien le truc. Si je te dis vas-y
#: remets, tu remets ». Threads n'y est pas : il est payé aux clics.
#: La quinzaine d'après retombe SEULE sur la grille (rien à faire le 01/12).
#: POUR CONTINUER : ajouter la quinzaine suivante ("2026-12-01": {...}).
#: POUR REVENIR tout de suite à la grille : retirer la ligne — mais pas une fois
#: la quinzaine payée à 1 $, sinon « depuis toujours » la recompte à la grille.
PRIX_UNIQUE: Dict[str, Dict[str, float]] = {
    "2026-11-16": {AGENCY_IG_ID: 1.00, TWITTER_ID: 1.00},
}
#: Au plus ce nombre de quinzaines lues pour « Gagné » (une lecture MyPuls par
#: quinzaine) ; au-delà, « — ».
QUINZAINES_MAX = 12


#: La grille de TRUST THREADS (propriétaire, 04/11/2026, image « Système de
#: paiement par clics » : « toutes les 2 semaines », « US · UK · CA ») : les
#: clics de la quinzaine, comptés comme sa ligne de la quinzaine
#: (podium_discord.clics_du_va : US + UK + CA, uniques), par tranches de 100 —
#: 5 $ de base par tranche, plus la prime de la tranche (« la prime du palier
#: atteint s'ajoute au paiement de base »). Moins de 100 : rien. La grille
#: s'arrête à 3 000 ; au-delà, le dernier palier (propriétaire, le même jour :
#: « au dessus de 3000 tu mets 188 $ pareil »).
GRILLE_CLICS_ICI = {THREADS_ID}
#: La prime des tranches 100-200, 200-300… 2 900-3 000 (29 tranches).
PRIMES_CLICS = (0, 1, 2, 3, 5, 6, 7, 9, 11, 13, 14, 16, 18, 20, 22, 23, 25, 27, 28, 30,
                31, 33, 34, 36, 37, 39, 40, 42, 43)
BASE_TRANCHE = 5


def paie_clics(n: Optional[int]) -> Optional[float]:
    """Le total (base + prime) d'une quinzaine à `n` clics ; None sans nombre.
    3 000 et plus : le dernier palier (188 $)."""
    if n is None:
        return None
    k = min(int(n) // 100, len(PRIMES_CLICS))
    return 0.0 if k < 1 else float(BASE_TRANCHE * k + PRIMES_CLICS[k - 1])


def _gagne_clics(gid: str, uid: str, d0: str, d1: str) -> Optional[float]:
    """Sa paie sur [d0, d1] selon la grille aux clics, quinzaine par quinzaine
    (1-15, 16-fin) : le total de la quinzaine (jusqu'à aujourd'hui), au
    prorata de ses clics quand la période n'en couvre qu'une partie. None si
    un nombre manque."""
    import podium_discord as pod
    auj = pod._aujourdhui()
    a, b = dt.date.fromisoformat(d0), min(dt.date.fromisoformat(d1), auj)
    if a > b:
        return 0.0
    qs: List[Tuple[dt.date, dt.date]] = []
    q0, q1 = pod.saison_en_cours(a)
    while q0 <= b:
        if len(qs) >= QUINZAINES_MAX:
            return None
        qs.append((q0, min(q1, auj)))
        q0 = q1 + dt.timedelta(days=1)
        q1 = pod.saison_en_cours(q0)[1]
    parts = [(max(q0, a), min(q1, b)) for q0, q1 in qs]
    partiels = [p for p, q in zip(parts, qs) if p != q]
    lus = pod.clics_du_va(str(gid), str(uid), qs + partiels)
    if not lus or len(lus) != len(qs) + len(partiels):
        return None
    du_partiel = dict(zip(partiels, lus[len(qs):]))
    total = 0.0
    for q, p, l in zip(qs, parts, lus[:len(qs)]):
        n_q = l[0] if l else None
        paie = paie_clics(n_q)
        if paie is None:
            return None
        if p == q:
            total += paie
            continue
        n_in = (du_partiel.get(p) or (None,))[0]
        if n_in is None:
            return None
        total += paie * min(n_in, n_q) / n_q if n_q else 0.0
    return round(total, 2)


def prix_du_sub(n: int, gid: Any = "", q0: Any = "") -> float:
    """Le prix d'un sub quand la quinzaine en compte `n` en tout : le prix
    unique de cette quinzaine (`q0`, son premier jour) sur ce serveur s'il y en
    a un (PRIX_UNIQUE), sinon le palier de GRILLE."""
    unique = (PRIX_UNIQUE.get(str(q0)) or {}).get(str(gid))
    if unique is not None:
        return float(unique)
    for seuil, prix in GRILLE:
        if n >= seuil:
            return prix
    return GRILLE[-1][1]


def _somme_mypuls(urls: List[str], a: str, b: str, champ: str) -> Optional[int]:
    """La somme de `champ` (visites, total, net…) de ces trackings dans la
    lecture MyPuls de [a, b] — celle des subs, gardée 90 s. Un tracking absent
    de MyPuls compte 0, comme ses subs (subs_va._subs_of) ; None si MyPuls
    n'a pas répondu ou ne rend pas le champ."""
    import podium_discord as pod
    vus, _r = pod._lire_mypuls(a, b)
    if vus is None:
        return None
    n = 0
    for u in urls:
        v = vus.get(pod.tracking_de(u))
        if v is None:
            continue
        if v.get(champ) is None:
            return None
        n += int(v[champ])
    return n


def _debut_liens(fiche: Dict[str, Any]) -> Optional[dt.date]:
    """Le premier jour de ses liens (le lien, sa variante, la bascule) : la
    paie « depuis toujours » part de SA quinzaine, entière -- un ancien lien
    (Emy) peut avoir ramené des subs avant le lien d'aujourd'hui."""
    jours = [_paris(t) for t in (fiche.get("quand"), (fiche.get("variante") or {}).get("quand"),
                                  (fiche.get("bascule") or {}).get("quand")) if t]
    jours = [t.date() for t in jours if t]
    return min(jours) if jours else None


def _gagne(of: List[str], mym: List[str], d0: str, d1: str,
           fige: Optional[Any] = None, gid: Any = "") -> Optional[float]:
    """Sa paie sur [d0, d1] selon GRILLE, quinzaine par quinzaine (1-15,
    16-fin, le calendrier du classement) : les subs de la période tombés dans
    une quinzaine, au prix que TOUTE cette quinzaine (jusqu'à aujourd'hui)
    atteint — ou au prix unique de cette quinzaine sur le serveur `gid`
    (PRIX_UNIQUE). None si un nombre manque, jamais une paie inventée."""
    import podium_discord as pod
    import subs_va

    def subs(a: dt.date, b: dt.date) -> Optional[int]:
        n_of = subs_va._subs_of(of, a.isoformat(), b.isoformat())
        n_mym = subs_va._subs_mym(mym, a.isoformat(), b.isoformat())
        return None if n_of is None or n_mym is None else n_of + n_mym
    auj = pod._aujourdhui()
    a, b = dt.date.fromisoformat(d0), min(dt.date.fromisoformat(d1), auj)
    if a > b:
        return 0.0
    total, lues = 0.0, 0
    q0, q1 = pod.saison_en_cours(a)
    while q0 <= b:
        lues += 1
        if lues > QUINZAINES_MAX:
            return None
        fini = q1 < auj
        q1 = min(q1, auj)
        n_q = subs(q0, q1)
        if n_q is None and fini and fige:
            # quinzaine finie illisible (Seren partie avec MyPuls, 03/11) :
            # le chiffre de sa page figée, celui qui a été payé
            n_q = fige(q0.isoformat())
        lo, hi = max(q0, a), min(q1, b)
        n_in = n_q if (lo, hi) == (q0, q1) else subs(lo, hi)
        if n_q is None or n_in is None:
            return None
        total += n_in * prix_du_sub(n_q, gid, q0.isoformat())
        q0 = pod.saison_en_cours(q0)[1] + dt.timedelta(days=1)
        q1 = pod.saison_en_cours(q0)[1]
    return round(total, 2)


def _subs(gid: str, uid: str, ts: List[Tuple[str, str]], du: str, au: str,
          toujours: bool) -> Tuple[Optional[int], List[str]]:
    """(subs, trackings écartés) : le calcul de subs_va.subs_du_va (« à son
    nom », OF + MYM), sur n'importe quelle période ; depuis toujours,
    subs_depuis_toujours. Sans tracking : None, pas zéro."""
    import subs_va
    if not ts:
        return None, []
    pseudo = subs_va.pseudo_du_va(gid, uid)
    communs = subs_va._communs(ts, pseudo)
    if toujours:
        return subs_va.subs_depuis_toujours(ts, pseudo), sorted(communs)
    of = [u for p, u in ts if p == "of" and u not in communs]
    mym = [u for p, u in ts if p == "mym" and u not in communs]
    n_of, n_mym = subs_va._subs_of(of, du, au), subs_va._subs_mym(mym, du, au)
    return (None if n_of is None or n_mym is None else n_of + n_mym), sorted(communs)


def _revenu_partiel(of: List[str], d0: str, d1: str, toujours: bool) -> bool:
    """Le revenu net MyPuls de ces trackings oublie-t-il des subs payés ?
    Emy et Seren sont remises dans la lecture MyPuls avec un net à 0 (voir
    podium_discord._retirees) : Seren toujours (relevé de subs seul), Emy sauf
    depuis toujours (Infloww ne date pas son revenu), et absentes quand leur
    relevé manque. Partiel seulement si une page retirée manque à la lecture
    du net, ou y compte des subs (donc payés) sans leur revenu. Sans cette
    marque, la page de la direction affichait des pertes inventées sur les VA
    à ancien tracking Emy ou à variante Seren ; sur le seul nom du tracking,
    presque tous les VA sortaient « — » (relectures du 07/11/2026)."""
    import podium_discord as pod
    retires = [pod.tracking_de(u) for u in of if pod.page_retiree(pod.tracking_de(u))]
    if not retires:
        return False
    vus, _r = pod._lire_mypuls(pod.ALLTIME_DEPUIS if toujours else d0, d1)   # celle du net, gardée 90 s
    if vus is None:
        return True
    for t in retires:
        v = vus.get(t)
        if v is None:
            return True
        marque = v.get("retiree")
        if not marque:
            continue                    # rendue par MyPuls : son net fait foi
        if toujours and marque == "infloww":
            continue                    # le net d'Emy depuis toujours est lu chez Infloww
        if int((v.get("subs_total") if toujours else v.get("subs")) or 0) > 0:
            return True
    return False


def chiffres(gid: str, uid: str, du: str = "", au: str = "") -> Dict[str, Any]:
    """{numero, pseudo, du, au, us, glob, infloww, subs, communs,
    lu_a} sur [du, au] (jours de Paris, bornes incluses) ; sans du : depuis
    toujours. Une valeur illisible vaut None. Lève LookupError sans fiche."""
    if str(gid) == POLE_TWITTER_FR_ID:
        import pole_twitter_fr
        return pole_twitter_fr.chiffres_stats(uid, du, au)
    import liens_va
    import podium_discord as pod
    import subs_va
    f = liens_va.lien_de(gid, uid)
    if not f:
        raise LookupError("pas de fiche")
    toujours = not du
    d0 = du or pod.ALLTIME_DEPUIS
    d1 = au or pod._aujourdhui().isoformat()
    ts = subs_va.trackings_du_va(gid, uid)
    try:
        c = (pod.clics_du_va(str(gid), str(uid), [(dt.date.fromisoformat(d0), dt.date.fromisoformat(d1))])
             or [None])[0]
    except Exception as e:                                   # noqa: BLE001
        print(f"[stats-va] clics GetMySocial illisibles : {type(e).__name__}: {e}", flush=True)
        c = None
    try:
        subs, communs = _subs(gid, uid, ts, d0, d1, toujours)
    except Exception as e:                                   # noqa: BLE001
        print(f"[stats-va] subs illisibles : {type(e).__name__}: {e}", flush=True)
        subs, communs = None, []

    def fige(saison: str) -> Optional[int]:
        try:
            return pod.subs_fige_du_va(gid, saison, f.get("numero"))
        except Exception as e:                               # noqa: BLE001
            print(f"[stats-va] quinzaine figée illisible : {type(e).__name__}: {e}", flush=True)
            return None
    # 04/11/2026, « période précédente figée » : une quinzaine finie, entière,
    # devenue illisible -- le chiffre de sa page figée
    if (subs is None and ts and not toujours
            and pod.saison_en_cours(dt.date.fromisoformat(d0)) == (dt.date.fromisoformat(d0),
                                                                   dt.date.fromisoformat(d1))
            and dt.date.fromisoformat(d1) < pod._aujourdhui()):
        subs = fige(d0)
    # un lien commun (pas à son nom) n'est pas compté dans ses subs : ses clics
    # Infloww, ceux de tout le monde, ne le sont pas non plus
    i = _clics_infloww([u for _p, u in ts if u not in communs], d0, d1, toujours)
    of = [u for p, u in ts if p == "of" and u not in communs]
    mym = [u for p, u in ts if p == "mym" and u not in communs]
    visites = net = gagne = None
    try:
        if toujours:
            # les compteurs depuis la création, ceux des subs depuis toujours
            visites = _somme_mypuls(of, d1, d1, "total")
            net = _somme_mypuls(of, pod.ALLTIME_DEPUIS, d1, "net")
        else:
            visites = _somme_mypuls(of, d0, d1, "visites")
            net = _somme_mypuls(of, d0, d1, "net")
        if mym:
            visites = net = None             # MYM : ni visites ni revenu par tracking ici
        d0_g = d0
        if toujours:
            # depuis toujours : de la quinzaine de ses premiers liens, pas du
            # 01/01/2024 (une lecture MyPuls par quinzaine)
            deb = _debut_liens(f) or (dt.date.fromisoformat(d1) - dt.timedelta(days=180))
            d0_g = pod.saison_en_cours(deb)[0].isoformat()
        if str(gid) in GRILLE_CLICS_ICI:
            # Threads : payé aux clics (« Système de paiement par clics »)
            gagne = _gagne_clics(str(gid), str(uid), d0_g, d1)
        else:
            gagne = _gagne(of, mym, d0_g, d1, fige, gid=str(gid)) if ts else None
    except Exception as e:                                   # noqa: BLE001
        print(f"[stats-va] CVR, $ par sub ou gain illisibles : {type(e).__name__}: {e}", flush=True)
    # le revenu pour la page de la direction : sans tracking à lui, il n'est
    # pas mesurable (0 « lu » faisait de toute sa paie une perte, Threads payé
    # aux clics) ; avec une page retirée, il est partiel
    partiel = False
    if net is not None and of:
        try:
            partiel = _revenu_partiel(of, d0, d1, toujours)
        except Exception as e:                               # noqa: BLE001
            print(f"[stats-va] pages retirées illisibles : {type(e).__name__}: {e}", flush=True)
            partiel = True
    return {"numero": f.get("numero"), "pseudo": str(f.get("pseudo") or ""),
            "du": "" if toujours else d0, "au": "" if toujours else d1,
            "us": c[0] if c else None, "glob": c[1] if c else None,
            "infloww": i["n"], "subs": subs,
            "cvr": (subs * 100.0 / visites) if subs is not None and visites else None,
            "par_sub": (net / 100.0 / subs) if net is not None and subs else None,
            # le revenu net MyPuls de ses liens, en dollars : lu par la page de la
            # direction (stats_trust, Gain / perte), JAMAIS affiché sur la page du VA
            # (None sans tracking à lui ; revenu_partiel : une page retirée y manque)
            "revenu": (net / 100.0) if net is not None and of and not partiel else None,
            "revenu_partiel": partiel,
            "gagne": gagne, "communs": communs, "lu_a": time.time(), "gid": str(gid)}


_CACHE_MAX = 300
#: Périodes choisies à la main (hors raccourcis) qu'un VA peut faire lire par
#: jour. Relecture du 03/11 : chaque date nouvelle coûte des appels
#: GetMySocial et MyPuls, les quotas mêmes du podium et de la paie ; une clé
#: qui ferait défiler les dates les viderait. Les raccourcis restent libres.
PERIODES_JOUR_MAX = 40
_LECTURES: Dict[str, int] = {}


class TropDePeriodes(Exception):
    """Le VA a fait lire assez de périodes à la main aujourd'hui."""


def chiffres_caches(gid: str, uid: str, du: str = "", au: str = "") -> Dict[str, Any]:
    """chiffres(), gardés CACHE_S par VA et par période ; une lecture à la fois
    par VA (deux onglets ouverts ne relisent pas deux fois GetMySocial). Lève
    TropDePeriodes au-delà de PERIODES_JOUR_MAX périodes à la main par jour."""
    import podium_discord as pod
    k = f"{gid}:{uid}"
    with _VERROU:
        v = _VERROUS_VA.setdefault(k, threading.Lock())
    with v:
        c = _CACHE.get(f"{k}:{du}:{au}")
        if c and time.time() - c[0] < CACHE_S:
            return c[1]
        jour = pod._aujourdhui()
        if (du, au) not in {(a, b) for _l, a, b in _raccourcis(jour)}:
            cle_j = f"{k}:{jour.isoformat()}"
            with _VERROU:
                for vieux in [x for x in _LECTURES if not x.endswith(":" + jour.isoformat())]:
                    _LECTURES.pop(vieux, None)
                if _LECTURES.get(cle_j, 0) >= PERIODES_JOUR_MAX:
                    raise TropDePeriodes()
                _LECTURES[cle_j] = _LECTURES.get(cle_j, 0) + 1
        d = chiffres(gid, uid, du, au)
        with _VERROU:
            _CACHE[f"{k}:{du}:{au}"] = (time.time(), d)
            for vieux in sorted(_CACHE, key=lambda x: _CACHE[x][0])[:-_CACHE_MAX]:
                _CACHE.pop(vieux, None)
        return d


def periode(args: Any) -> Tuple[str, str]:
    """(du, au) demandés dans l'adresse, ramenés entre le 01/01/2024 et
    aujourd'hui (la règle de la page Lia) ; ?tout=1 : ("", ""), depuis
    toujours. Sans rien : CETTE QUINZAINE (propriétaire, 03/11 : « comme
    préréglage, pas depuis toujours mais toujours cette quinzaine »)."""
    import infloww_liens as il
    import podium_discord as pod
    import subs_va
    args = args or {}
    if str(args.get("tout") or "") == "1":
        return "", ""
    try:
        p = il.periode_des_args(args)
    except Exception:
        p = None
    if p:
        return p
    a, b = {c: (x, y) for c, x, y in subs_va.periodes(pod._aujourdhui())}["periode"]
    return a.isoformat(), b.isoformat()


# ─── la page ─────────────────────────────────────────────────────────────
def _e(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def _nb(v: Any) -> str:
    return "—" if v is None else f"{int(v):,}".replace(",", " ")


def _jj_mm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if len(iso) >= 10 else ""


def _raccourcis(jour: dt.date) -> List[Tuple[str, str, str]]:
    """[(libellé, du, au)] : ceux de la page Lia. Les quinzaines sont celles
    du classement (subs_va.periodes : 1-15, 16-fin), un seul calendrier."""
    import subs_va
    p = {c: (a.isoformat(), b.isoformat()) for c, a, b in subs_va.periodes(jour)}
    j = jour.isoformat()
    return [("Depuis toujours", "", ""), ("Aujourd'hui", j, j),
            ("Cette quinzaine",) + p["periode"], ("Quinzaine précédente",) + p["precedente"],
            ("7 derniers jours", (jour - dt.timedelta(days=6)).isoformat(), j),
            ("30 derniers jours", (jour - dt.timedelta(days=29)).isoformat(), j)]


def _adresse(t: str, du: str = "", au: str = "") -> str:
    from urllib.parse import quote
    # sans dates, la page ouvre la quinzaine : « depuis toujours » se demande
    q = f"?t={quote(t, safe='')}" + (f"&du={du}&au={au}" if du else "&tout=1")
    return _e(q)


_STYLE = """
:root{--fond:#0e0e10;--carte:#18181b;--bord:#2a2a2f;--texte:#f4f4f5;--faible:#a1a1aa;--acc:#f97341;--ambre:#f59e0b}
*{box-sizing:border-box}
html,body{margin:0;background:var(--fond);color:var(--texte)}
body{font:14px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif;padding:20px 16px 32px;max-width:1040px;margin:0 auto}
.marque{color:var(--acc);font-weight:700;font-size:12px;letter-spacing:.06em;text-transform:uppercase}
h1{font-size:20px;margin:4px 0 2px;overflow-wrap:anywhere}
.sous{color:var(--faible);font-size:13px;margin:0 0 16px;overflow-wrap:anywhere}
.sous b{color:var(--texte);font-weight:600}
.periode{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 8px}
.periode .lib{color:var(--faible);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.periode input{flex:1 1 128px;min-width:0;max-width:180px;background:var(--carte);color:var(--texte);border:1px solid var(--bord);border-radius:8px;padding:7px 8px;font:inherit;font-size:14px;color-scheme:dark}
.periode .fl{color:var(--faible)}
.periode button{background:var(--acc);color:#1c0a02;border:0;border-radius:8px;padding:8px 16px;font:inherit;font-weight:700;cursor:pointer}
.raccourcis{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.raccourcis a{color:var(--faible);text-decoration:none;border:1px solid var(--bord);border-radius:999px;padding:4px 10px;font-size:12px;white-space:nowrap}
.raccourcis a.on{color:var(--acc);border-color:var(--acc)}
.boite{background:var(--carte);border:1px solid var(--bord);border-radius:12px;overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px;border-bottom:1px solid var(--bord);text-align:right;vertical-align:top;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
th{font-size:12px;font-weight:600;color:var(--faible);white-space:nowrap}
th.g,td.nom{text-align:left}
td{font-size:15px;font-weight:700;white-space:nowrap}
td.subs{color:var(--acc)}
td.nom{white-space:nowrap}
.det{display:block;color:var(--faible);font-size:11.5px;font-weight:400;margin-top:3px}
.nv{display:inline-block;border-radius:6px;padding:1px 7px;font-weight:700}
.nv.v1{background:#4ade80;color:#052e16} .nv.v2{background:#16a34a;color:#fff}
.nv.v3{background:#166534;color:#fff} .nv.o1{background:#fbbf24;color:#1c1203}
.nv.o2{background:#f97316;color:#1c0a02} .nv.r{background:#dc2626;color:#fff}
.pied{color:var(--faible);font-size:12px;margin:12px 0 0;overflow-wrap:anywhere}
.pied a{color:var(--acc);text-decoration:none}
.err{background:rgba(239,68,68,.12);border:1px solid #ef4444;border-radius:12px;padding:14px 16px}
/* l'adresse USDC : un QR à scanner, l'adresse en tout petit dessous ; un clic l'ouvre en grand au centre (.zoom).
   Le QR garde son fond blanc sur la page sombre : sans lui, aucun téléphone ne le lit.
   L'adresse entière (.za) déborde de 8 px sur la marge de la carte : 44 caractères tiennent sur une ligne dès 360 px */
.adrb{display:flex;flex-direction:column;align-items:flex-end;gap:5px}
.qr{display:block;background:none;border:0;padding:0;margin:0;line-height:0;cursor:zoom-in;border-radius:6px}
.qr svg{display:block;width:var(--qr,64px);height:var(--qr,64px);border-radius:6px}
.adrt{display:block;color:var(--faible);font-size:10.5px;font-weight:400;line-height:1.35;text-align:right}
.adrt b{display:block;font-weight:500;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.manque{color:var(--ambre)}
/* les logos USDC et réseau : deux pastilles qui se chevauchent, à la taille du texte qui les suit. Un filet
   clair autour : le logo Solana est un disque NOIR, il disparaissait sur la carte sombre (il n'en restait que
   les trois barres) */
.adrr{display:block;white-space:nowrap;margin-top:2px}
.lgs{display:inline-flex;vertical-align:-.28em;margin-right:.4em}
.lgs img{display:block;width:1.3em;height:1.3em;border-radius:50%;box-shadow:0 0 0 1px rgba(255,255,255,.28)}
.lgs img+img{margin-left:-.3em}
.adrt .lgs img{width:15px;height:15px}
.adrm{display:block;color:var(--acc);font-size:10.5px;font-weight:600;text-decoration:none;margin-top:2px}
.zoom{position:fixed;top:0;right:0;bottom:0;left:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.82);cursor:zoom-out}
.zc{width:100%;max-width:350px;background:var(--carte);border:1px solid var(--bord);border-radius:18px;padding:18px;text-align:center}
.zc svg{display:block;width:100%;height:auto;border-radius:10px}
.zr{margin:14px 0 6px;font-size:15px;font-weight:700}
.za{display:block;width:calc(100% + 16px);background:none;border:0;padding:0;margin:0 -8px;color:var(--faible);font:10.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere;word-break:break-all;text-wrap:balance;cursor:copy;-webkit-user-select:all;user-select:all}
.ze{min-height:16px;margin-top:4px;color:#4ade80;font-size:12px;font-weight:600}
/* 375 px : comme la page Lia, ce qui ne tient pas défile dans la boîte, jamais la page ; les en-têtes passent
   sur deux lignes */
@media (max-width:480px){.periode .lib{flex-basis:100%} th{font-size:11px;white-space:normal} th,td{padding:9px 5px} th:first-child,td:first-child{padding-left:10px} th:last-child,td:last-child{padding-right:10px} h1{font-size:18px} td{font-size:14px} td.nom{white-space:normal;overflow-wrap:anywhere;min-width:92px} .nv{padding:1px 4px}}
"""


def _gabarit(titre: str, corps: str, gid: Any = AGENCY_IG_ID) -> str:
    marque = MARQUES.get(str(gid or ""), MARQUES[AGENCY_IG_ID])[0]
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="dark">
<title>{_e(titre)}</title>{domaines.ICONE_LIEN}<style>{_STYLE}</style></head><body>
<div class="marque">{_e(marque)}</div>
{corps}
</body></html>'''


def page_introuvable() -> str:
    return _gabarit("Page introuvable", '<h1>Page introuvable.</h1>'
                    '<p class="sous">Ce lien n\'ouvre rien. Reprends le tien avec « 📈 Mes stats » '
                    'dans ton ticket.</p>')


def _formulaire(t: str, du: str, au: str, jour: dt.date) -> str:
    """Le choix de la période, sans JavaScript, comme sur la page Lia : un
    formulaire GET qui garde la clé (sans elle, valider fermerait la page) et
    les raccourcis en simples liens."""
    j = jour.isoformat()
    liens, deja = [], False
    for lib, d, a in _raccourcis(jour):
        # deux raccourcis peuvent tomber sur les mêmes jours (le 7, « cette
        # quinzaine » = « 7 derniers jours ») : seul le premier est allumé
        on = ""
        if (d, a) == (du, au) and not deja:
            on, deja = ' class="on" aria-current="page"', True
        liens.append(f'<a href="{_adresse(t, d, a)}"{on}>{_e(lib)}</a>')
    import podium_discord as pod
    bornes = f'min="{_e(pod.ALLTIME_DEPUIS)}" max="{_e(j)}"'
    return (f'<form class="periode" method="get"><input type="hidden" name="t" value="{_e(t)}">'
            '<span class="lib">Période</span>'
            f'<input type="date" name="du" value="{_e(du)}" {bornes} aria-label="Date de début">'
            '<span class="fl" aria-hidden="true">→</span>'
            f'<input type="date" name="au" value="{_e(au)}" {bornes} aria-label="Date de fin">'
            '<button type="submit">OK</button></form>'
            f'<nav class="raccourcis" aria-label="Périodes">{"".join(liens)}</nav>')


def _titre_periode(du: str, au: str, jour: dt.date) -> str:
    for lib, d, a in _raccourcis(jour):
        if (d, a) == (du, au):
            return lib + ("" if lib in ("Depuis toujours", "Aujourd'hui") else
                          f" (du {_jj_mm(du)} au {_jj_mm(au)})")
    return f"Le {_jj_mm(du)}" if du == au else f"Du {_jj_mm(du)} au {_jj_mm(au)}"


# ─── l'adresse USDC, dernière colonne ────────────────────────────────────
# Propriétaire, 17/11/2026, devant la page d'un VA : « rajouter une catégorie
# à la toute fin [...] pour savoir c'est quoi son adresse crypto ». LECTURE
# SEULE : la page s'ouvre par un simple lien à clé ; si ce lien fuit, personne
# ne doit pouvoir changer l'adresse de paie d'ici. Elle se change dans Discord
# (💳 du ticket).
def paiements() -> Optional[Dict[str, Dict[str, Any]]]:
    """suivi_va.paiements() sans lever : {« gid:uid » : {adresse, reseau…}},
    None si les adresses ne sont pas lisibles."""
    try:
        import suivi_va
        return suivi_va.paiements()
    except Exception as e:                                   # noqa: BLE001
        print(f"[stats-va] adresses USDC illisibles : {type(e).__name__}: {e}", flush=True)
        return None


def paiement_de(tous: Optional[Mapping[str, Any]], gid: Any, uid: Any) -> Optional[Dict[str, str]]:
    """{adresse, reseau} du VA dans `tous` (paiements()), {} s'il n'a pas
    d'adresse, None si elles sont illisibles : « à renseigner » ne s'écrit
    que quand on SAIT qu'il n'en a pas donné."""
    if tous is None:
        return None
    e = tous.get(f"{gid}:{uid}") or {}
    return {"adresse": str(e.get("adresse") or ""), "reseau": str(e.get("reseau") or "solana")} \
        if e.get("adresse") else {}


@functools.lru_cache(maxsize=8)
def _logo_url(fichier: str) -> str:
    """/static/<fichier>?v=<empreinte> ; "" si le fichier manque : la page
    reste entière, sans logo, plutôt qu'avec une image cassée."""
    try:
        import hashlib
        octets = (Path(__file__).resolve().parent / "static" / fichier).read_bytes()
    except OSError as e:
        print(f"[stats-va] logo {fichier} illisible : {e}", flush=True)
        return ""
    return f"/static/{fichier}?v={hashlib.md5(octets).hexdigest()[:8]}"


def logo(fichier: str, alt: str = "") -> str:
    u = _logo_url(fichier)
    return (f'<img src="{_e(u)}" alt="{_e(alt)}" width="16" height="16" loading="lazy" decoding="async">'
            if u else "")


def logo_reseau(reseau: Any) -> str:
    """Le logo du réseau (Solana, Ethereum) : ceux du menu Discord
    (tickets_discord.USDC_EMOJIS), une seule table pour les deux."""
    import tickets_discord as tk
    return logo((tk.USDC_EMOJIS.get(str(reseau)) or tk.USDC_EMOJIS["solana"])[1])


def logos_usdc(reseau: Any) -> str:
    """Propriétaire, 17/11/2026 : « mets les logo usdc et le logo icône
    solana », « ou eth ». Le logo USDC et celui du réseau, l'un contre
    l'autre, devant le nom du réseau ; leur taille suit celle du texte."""
    import tickets_discord as tk
    h = logo(tk.USDC_ICONE, "USDC") + logo_reseau(reseau)
    return f'<span class="lgs">{h}</span>' if h else ""


def cellule_adresse(p: Optional[Mapping[str, Any]], modifier: str = "") -> str:
    """La case « Adresse USDC », la même sur la page du VA et sur celle de la
    direction (propriétaire, 17/11/2026 : « juste un QR code, avec le texte
    écrit en tout petit ; quand je clique, ça zoome ») : le QR de l'adresse,
    puis l'adresse courte comme dans le menu du ticket (4…4) et le réseau.
    Un clic l'ouvre en grand au centre (SCRIPT_ADRESSE). Sans adresse :
    « à renseigner », jamais une case vide. `modifier` : l'adresse de la page
    où la direction la change (adresse_usdc), donnée par la SEULE page de la
    direction ouverte avec un compte ; jamais sur la page d'un VA ni avec une
    clé de manager. Adresses illisibles : pas de lien non plus, on ne change
    pas ce qu'on ne lit pas."""
    if p is None:
        return '<td class="adr">—</td>'
    lien = f'<a class="adrm" href="{_e(modifier)}">Modifier</a>' if modifier else ""
    a = str(p.get("adresse") or "")
    if not a:
        return f'<td class="adr"><span class="manque">à renseigner</span>{lien}</td>'
    import suivi_va
    reseau = suivi_va.RESEAUX.get(str(p.get("reseau") or ""), suivi_va.RESEAUX["solana"])
    court = a if len(a) <= 11 else f"{a[:4]}…{a[-4:]}"
    texte = (f'<span class="adrt"><b>{_e(court)}</b><span class="adrr">{logos_usdc(p.get("reseau"))}'
             f'{_e(reseau)}</span>{lien}</span>')
    try:
        import qr_code
        dessin = qr_code.svg(a)
    except Exception as e:                                   # noqa: BLE001
        # pas de QR ne doit pas emporter la page : l'adresse reste écrite
        print(f"[stats-va] QR de l'adresse non dessiné : {type(e).__name__}: {e}", flush=True)
        return (f'<td class="adr"><div class="adrb"><span class="adrt" title="{_e(a)}"><b>{_e(court)}</b>'
                f'<span class="adrr">{logos_usdc(p.get("reseau"))}{_e(reseau)}</span>{lien}</span></div></td>')
    return (f'<td class="adr"><div class="adrb"><button type="button" class="qr" data-a="{_e(a)}" '
            f'data-r="USDC · {_e(reseau)}" title="{_e(a)}" aria-label="Agrandir le QR code de l\'adresse USDC">'
            f'{dessin}</button>{texte}</div></td>')


#: Le seul JavaScript des deux pages : un clic sur le QR l'ouvre en grand au
#: centre, avec le réseau et l'adresse entière ; un clic sur l'adresse la
#: copie, un clic ailleurs (ou Échap) referme. Sans JavaScript, le QR de la
#: case reste un vrai QR et la page reste entière. Rien n'est écrit en HTML :
#: que du texte (textContent) et une copie du dessin déjà sur la page.
#: Que des guillemets doubles, aucune barre oblique inverse : ce texte vit
#: dans une chaîne Python.
SCRIPT_ADRESSE = """<script>
(function(){
  function fermer(){
    var z=document.getElementById("zoomqr");
    if(z){z.parentNode.removeChild(z);}
  }
  function copier(a,fin){
    function secours(){
      var ok=false;
      var t=document.createElement("textarea");
      t.value=a;
      t.setAttribute("readonly","");
      t.style.position="fixed";
      t.style.opacity="0";
      document.body.appendChild(t);
      t.select();
      try{ok=document.execCommand("copy");}catch(e){ok=false;}
      document.body.removeChild(t);
      fin(ok);
    }
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(a).then(function(){fin(true);},secours);
    }else{
      secours();
    }
  }
  function ouvrir(b){
    fermer();
    var z=document.createElement("div");
    z.id="zoomqr";
    z.className="zoom";
    var c=document.createElement("div");
    c.className="zc";
    var s=b.querySelector("svg");
    if(s){c.appendChild(s.cloneNode(true));}
    var r=document.createElement("div");
    r.className="zr";
    var l=b.parentNode.querySelector(".lgs");
    if(l){r.appendChild(l.cloneNode(true));}
    r.appendChild(document.createTextNode(b.getAttribute("data-r")||""));
    var a=document.createElement("button");
    a.type="button";
    a.className="za";
    a.textContent=b.getAttribute("data-a")||"";
    var e=document.createElement("div");
    e.className="ze";
    c.appendChild(r);
    c.appendChild(a);
    c.appendChild(e);
    z.appendChild(c);
    document.body.appendChild(z);
  }
  document.addEventListener("click",function(ev){
    var c=ev.target;
    if(!c||!c.closest){return;}
    var b=c.closest("button.qr");
    if(b){ouvrir(b);return;}
    var a=c.closest(".za");
    if(a){
      copier(a.textContent,function(ok){
        var e=a.parentNode.querySelector(".ze");
        if(e){e.textContent=ok?"Adresse copiée ✓":"";}
      });
      return;
    }
    if(c.closest("#zoomqr")){fermer();}
  });
  document.addEventListener("keydown",function(ev){
    if(ev.key==="Escape"){fermer();}
  });
})();
</script>"""


def page_html(d: Dict[str, Any], t: str = "", jour: Optional[dt.date] = None) -> str:
    """La page. Tout est échappé : un pseudo ne peut rien casser. Un seul
    script, le QR de l'adresse USDC en grand (SCRIPT_ADRESSE) ; le reste marche sans.
    d["paiement"] : {adresse, reseau}, {} sans adresse, None (ou absent) si
    illisible."""
    import podium_discord as pod
    jour = jour or pod._aujourdhui()
    du, au = str(d.get("du") or ""), str(d.get("au") or "")
    plateforme = MARQUES.get(str(d.get("gid") or ""), MARQUES[AGENCY_IG_ID])[1]
    nom = f"{plateforme} VA {d['numero']}" if str(d.get("numero") or "").isdigit() else "Ton lien"
    sous = f"<b>{_e(_titre_periode(du, au, jour))}</b>" + (f" · @{_e(d['pseudo'])}" if d.get("pseudo") else "")
    import infloww_liens as il
    infl = _nb(d.get("infloww"))
    cvr = il._pastille(il._pct(d.get("cvr")), il.niveau(d.get("cvr"), il.SEUIL_CVR))
    par_sub = il._pastille(il._dollars(d.get("par_sub")), il.niveau(d.get("par_sub"), il.SEUIL_PAR_SUB))
    lu_t = _paris(d.get("lu_a") or time.time())
    # en bas, les sources et rien d'autre ; une marque n'est expliquée que si
    # elle est sur la page
    marques = []
    if any(d.get(k) is None for k in ("us", "glob", "infloww", "subs", "gagne", "paiement")):
        marques.append("— : pas encore lisible")
    if d.get("communs"):
        marques.append("un lien de suivi commun à plusieurs VA n'est pas compté")
    pole = str(d.get("gid") or "") == POLE_TWITTER_FR_ID
    # POLE TWITTER FR : ni Infloww ni clics US — les visites MyPuls de ses
    # trackings et les clics de France
    sources = " · ".join(f'API officielle <a href="{_e(u)}" rel="noopener noreferrer">{_e(n)}</a>'
                         for n, u in SOURCES if not (pole and n == "Infloww"))
    pied = (f'<p class="pied">Sources : {sources}</p>'
            + (f'<p class="pied">{" · ".join(marques)}</p>' if marques else "")
            + '<p class="pied">' + (f"Lu le {_e(lu_t.strftime('%d/%m à %H:%M'))} (heure de Paris) · " if lu_t else "")
            + "ce lien est à toi, ne le partage pas</p>")
    corps = (f'<h1>📈 Tes stats · {_e(nom)}</h1><p class="sous">{sous}</p>'
             + _formulaire(t, du, au, jour)
             + '<div class="boite"><table><thead><tr><th class="g">Personne</th>'
             f'<th>Clics {"FR" if pole else "US·UK·CA" if str(d.get("gid") or "") in GRILLE_CLICS_ICI else "US"} GMS</th>'
             f'<th>Clics globaux GMS</th><th>{"Visites MyPuls" if pole else "Clics Infloww"}</th>'
             '<th>Subs</th><th>CVR</th><th>$ / sub</th>'
             '<th>Gagné</th><th>Adresse USDC</th></tr></thead><tbody><tr>'
             f'<td class="nom">{("@" + _e(d["pseudo"])) if d.get("pseudo") else _e(nom)}'
             + (f'<span class="det">{_e(nom)}</span>' if d.get("pseudo") else "") + '</td>'
             f'<td>{_nb(d.get("us"))}</td><td>{_nb(d.get("glob"))}</td><td>{infl}</td>'
             f'<td class="subs">{_nb(d.get("subs"))}</td><td>{cvr}</td><td>{par_sub}</td>'
             f'<td>{il._dollars(d.get("gagne"))}</td>{cellule_adresse(d.get("paiement"))}'
             '</tr></tbody></table></div>'
             + pied + SCRIPT_ADRESSE)
    return _gabarit(f"Tes stats · {nom}", corps, d.get("gid"))


def page(t: Any, args: Any = None) -> Tuple[int, str]:
    """(code HTTP, HTML) de la page de la clé `t`, sur la période de `args`
    (du, au). Ne lève jamais : une panne s'affiche sur la page."""
    q = qui(t)
    if not q:
        return 404, page_introuvable()
    gid, uid = q
    try:
        import tickets_discord
        if uid in tickets_discord.partis(gid):
            return 404, page_introuvable()
    except Exception as e:                                   # noqa: BLE001
        print(f"[stats-va] départs illisibles : {type(e).__name__}: {e}", flush=True)
    du, au = periode(args)
    try:
        d = chiffres_caches(gid, uid, du, au)
    except LookupError:
        return 404, page_introuvable()
    except TropDePeriodes:
        import podium_discord as pod
        return 429, _gabarit("Tes stats", '<h1>📈 Tes stats</h1><p class="sous">Tu as demandé beaucoup de '
                             'périodes aujourd\'hui. Reprends un des raccourcis (depuis toujours, '
                             'aujourd\'hui, les quinzaines…) : ils marchent toujours.</p>'
                             + _formulaire(str(t), "", "", pod._aujourdhui()), gid)
    except Exception as e:                                   # noqa: BLE001
        return 200, _gabarit("Tes stats", f'<h1>📈 Tes stats</h1><div class="err"><b>Lecture '
                             f'impossible.</b><br>{_e(type(e).__name__)} : {_e(str(e)[:200])}</div>', gid)
    try:
        # l'adresse est lue à CHAQUE affichage, hors du cache des chiffres
        # (10 min) : un VA qui vient de la changer par 💳 la retrouve ici
        # tout de suite, sinon il croit que rien n'a été enregistré
        return 200, page_html(dict(d, paiement=paiement_de(paiements(), gid, uid)), str(t))
    except Exception as e:                                   # noqa: BLE001
        return 200, _gabarit("Tes stats", f'<h1>📈 Tes stats</h1><div class="err"><b>La page n\'a pas '
                             f'pu être construite.</b><br>{_e(type(e).__name__)} : {_e(str(e)[:200])}</div>', gid)
