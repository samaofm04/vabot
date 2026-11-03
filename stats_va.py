"""La page perso d'un VA de TRUST INSTAGRAM : ses chiffres, à lui seul.

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
  VA), Gagné = sa paie selon la grille de TRUST INSTAGRAM (GRILLE). Jamais le
  revenu de l'agence en total, ni paiement ni gain / perte du propriétaire.
- En bas, les sources, et rien d'autre (propriétaire, 03/11, devant un bloc
  de preuves détaillé : « pas fan, plus propre, juste en bas : API officielle
  d'Infloww utilisée, avec la doc, et aussi pour GetMySocial, c'est tout ») :
  chaque API nommée, liée à sa documentation officielle.
"""
from __future__ import annotations

import datetime as dt
import hmac
import html as _html
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

AGENCY_IG_ID = "1488331963575177247"
#: Les serveurs dont « Mes stats » donne le lien de la page.
SERVEURS = {AGENCY_IG_ID}
SITE = "https://youl4b.com"
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
    return f"{SITE}/mes-stats?t={jeton(gid, uid)}"


# ─── les chiffres ────────────────────────────────────────────────────────
def _codes(trackings: List[str], createrice: str) -> List[str]:
    out = []
    for u in trackings:
        m = _RE_TRACKING.search(str(u or ""))
        # « c040 » chez OnlyFans est « 40 » chez Infloww (_code_infloww)
        if m and m.group(1).lower() == createrice and str(int(m.group(2))) not in out:
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
#: Au plus ce nombre de quinzaines lues pour « Gagné » (une lecture MyPuls par
#: quinzaine) ; au-delà, « — ».
QUINZAINES_MAX = 12


def prix_du_sub(n: int) -> float:
    """Le prix d'un sub quand la quinzaine en compte `n` en tout."""
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


def _gagne(of: List[str], mym: List[str], d0: str, d1: str) -> Optional[float]:
    """Sa paie sur [d0, d1] selon GRILLE, quinzaine par quinzaine (1-15,
    16-fin, le calendrier du classement) : les subs de la période tombés dans
    une quinzaine, au prix que TOUTE cette quinzaine (jusqu'à aujourd'hui)
    atteint. None si un nombre manque, jamais une paie inventée."""
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
        q1 = min(q1, auj)
        n_q = subs(q0, q1)
        lo, hi = max(q0, a), min(q1, b)
        n_in = n_q if (lo, hi) == (q0, q1) else subs(lo, hi)
        if n_q is None or n_in is None:
            return None
        total += n_in * prix_du_sub(n_q)
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


def chiffres(gid: str, uid: str, du: str = "", au: str = "") -> Dict[str, Any]:
    """{numero, pseudo, du, au, us, glob, infloww, subs, communs,
    lu_a} sur [du, au] (jours de Paris, bornes incluses) ; sans du : depuis
    toujours. Une valeur illisible vaut None. Lève LookupError sans fiche."""
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
        gagne = _gagne(of, mym, d0_g, d1) if ts else None
    except Exception as e:                                   # noqa: BLE001
        print(f"[stats-va] CVR, $ par sub ou gain illisibles : {type(e).__name__}: {e}", flush=True)
    return {"numero": f.get("numero"), "pseudo": str(f.get("pseudo") or ""),
            "du": "" if toujours else d0, "au": "" if toujours else d1,
            "us": c[0] if c else None, "glob": c[1] if c else None,
            "infloww": i["n"], "subs": subs,
            "cvr": (subs * 100.0 / visites) if subs is not None and visites else None,
            "par_sub": (net / 100.0 / subs) if net is not None and subs else None,
            "gagne": gagne, "communs": communs, "lu_a": time.time()}


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
body{font:14px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif;padding:20px 16px 32px;max-width:960px;margin:0 auto}
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
/* 375 px : comme la page Lia, ce qui ne tient pas défile dans la boîte, jamais la page ; les en-têtes passent
   sur deux lignes */
@media (max-width:480px){.periode .lib{flex-basis:100%} th{font-size:11px;white-space:normal} th,td{padding:9px 5px} th:first-child,td:first-child{padding-left:10px} th:last-child,td:last-child{padding-right:10px} h1{font-size:18px} td{font-size:14px} td.nom{white-space:normal;overflow-wrap:anywhere;min-width:92px} .nv{padding:1px 4px}}
"""


def _gabarit(titre: str, corps: str) -> str:
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="dark">
<title>{_e(titre)}</title><style>{_STYLE}</style></head><body>
<div class="marque">TRUST INSTAGRAM</div>
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


def page_html(d: Dict[str, Any], t: str = "", jour: Optional[dt.date] = None) -> str:
    """La page, sans JavaScript. Tout est échappé : un pseudo ne peut rien casser."""
    import podium_discord as pod
    jour = jour or pod._aujourdhui()
    du, au = str(d.get("du") or ""), str(d.get("au") or "")
    nom = f"Instagram VA {d['numero']}" if str(d.get("numero") or "").isdigit() else "Ton lien"
    sous = f"<b>{_e(_titre_periode(du, au, jour))}</b>" + (f" · @{_e(d['pseudo'])}" if d.get("pseudo") else "")
    import infloww_liens as il
    infl = _nb(d.get("infloww"))
    cvr = il._pastille(il._pct(d.get("cvr")), il.niveau(d.get("cvr"), il.SEUIL_CVR))
    par_sub = il._pastille(il._dollars(d.get("par_sub")), il.niveau(d.get("par_sub"), il.SEUIL_PAR_SUB))
    lu_t = _paris(d.get("lu_a") or time.time())
    # en bas, les sources et rien d'autre ; une marque n'est expliquée que si
    # elle est sur la page
    marques = []
    if any(d.get(k) is None for k in ("us", "glob", "infloww", "subs", "gagne")):
        marques.append("— : pas encore lisible")
    if d.get("communs"):
        marques.append("un lien de suivi commun à plusieurs VA n'est pas compté")
    sources = " · ".join(f'API officielle <a href="{_e(u)}" rel="noopener noreferrer">{_e(n)}</a>'
                         for n, u in SOURCES)
    pied = (f'<p class="pied">Sources : {sources}</p>'
            + (f'<p class="pied">{" · ".join(marques)}</p>' if marques else "")
            + '<p class="pied">' + (f"Lu le {_e(lu_t.strftime('%d/%m à %H:%M'))} (heure de Paris) · " if lu_t else "")
            + "ce lien est à toi, ne le partage pas</p>")
    corps = (f'<h1>📈 Tes stats · {_e(nom)}</h1><p class="sous">{sous}</p>'
             + _formulaire(t, du, au, jour)
             + '<div class="boite"><table><thead><tr><th class="g">Personne</th><th>Clics US GMS</th>'
             '<th>Clics globaux GMS</th><th>Clics Infloww</th><th>Subs</th><th>CVR</th><th>$ / sub</th>'
             '<th>Gagné</th></tr></thead><tbody><tr>'
             f'<td class="nom">{("@" + _e(d["pseudo"])) if d.get("pseudo") else _e(nom)}'
             + (f'<span class="det">{_e(nom)}</span>' if d.get("pseudo") else "") + '</td>'
             f'<td>{_nb(d.get("us"))}</td><td>{_nb(d.get("glob"))}</td><td>{infl}</td>'
             f'<td class="subs">{_nb(d.get("subs"))}</td><td>{cvr}</td><td>{par_sub}</td>'
             f'<td>{il._dollars(d.get("gagne"))}</td></tr></tbody></table></div>'
             + pied)
    return _gabarit(f"Tes stats · {nom}", corps)


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
                             + _formulaire(str(t), "", "", pod._aujourdhui()))
    except Exception as e:                                   # noqa: BLE001
        return 200, _gabarit("Tes stats", f'<h1>📈 Tes stats</h1><div class="err"><b>Lecture '
                             f'impossible.</b><br>{_e(type(e).__name__)} : {_e(str(e)[:200])}</div>')
    try:
        return 200, page_html(d, str(t))
    except Exception as e:                                   # noqa: BLE001
        return 200, _gabarit("Tes stats", f'<h1>📈 Tes stats</h1><div class="err"><b>La page n\'a pas '
                             f'pu être construite.</b><br>{_e(type(e).__name__)} : {_e(str(e)[:200])}</div>')
