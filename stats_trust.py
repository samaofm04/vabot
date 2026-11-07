"""Tous les VA de TRUST TWITTER, TRUST INSTAGRAM et TRUST THREADS sur une seule
page, triable : la page de la direction.

Propriétaire, 07/11/2026, devant le lien JESSY LE RETOUR de Youl4b (Spam)
(/infloww/liens?c=emy) : « j'aimerais avoir un lien exprès pour le Trust. Pour
Trust Twitter, Trust Instagram et même Trust Thread », « trié par rentable » :
« par nombre de subs, ascendant, descendant, nombre de clics ascendant,
descendant, la meilleure LTV, la pire LTV, le coût par sub ». Pour lui et les
managers seulement (réponse du même jour) : le coût par sub est un montant
d'agence, il ne va pas chez les VA.

- Les chiffres d'un VA sont ceux de sa page perso (stats_va.chiffres) : mêmes
  clics GetMySocial, mêmes subs MyPuls « à son nom », mêmes clics Infloww, même
  « Gagné » (grille aux subs de TRUST INSTAGRAM et TWITTER, aux clics pour
  THREADS). Deux règles auraient donné deux chiffres pour la même chose.
- LTV = le « $ / sub » de sa page : revenu net MyPuls de ses liens ÷ ses subs.
  Coût / sub = Gagné ÷ subs. Marge / sub = LTV − coût / sub : ce que rapporte un
  sub une fois le VA payé (« rentable »).
- La page montre près de 80 VA. Ils sont relus EN FOND, un VA après l'autre,
  par un seul fil : la page s'affiche tout de suite avec ce qui est déjà lu et
  se recharge seule jusqu'à la fin. Une période relue est gardée CACHE_S. La
  liste de chaque espace GetMySocial n'est lue qu'une fois par lecture
  (podium_discord.listes_du_lot) ; une période en file que plus personne ne
  regarde en sort ; trois VA lents d'affilée (source muette) arrêtent la
  lecture, le reste est dit au pied de la page et un nouvel essai suit.
- Une clé (data/stats_trust_cle.json, 0600, hors git) ouvre la page sans compte,
  à donner aux managers ; un admin connecté l'ouvre sans clé et y lit le lien.
- Un VA illisible n'est jamais écarté en silence : sa ligne reste, avec « — »
  et la raison au pied de la page.
"""
from __future__ import annotations

import datetime as dt
import hmac
import html as _html
import secrets
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

import domaines
import safe_json
import stats_va as sv

#: (guild, code dans l'adresse, nom) dans l'ordre des onglets.
SERVEURS: Tuple[Tuple[str, str, str], ...] = (
    (sv.TWITTER_ID, "tw", "Twitter"),
    (sv.AGENCY_IG_ID, "ig", "Instagram"),
    (sv.THREADS_ID, "th", "Threads"),
)
_PAR_CODE = {c: (g, n) for g, c, n in SERVEURS}
_PAR_GID = {g: (c, n) for g, c, n in SERVEURS}
CLE_FICHIER = sv.DATA_DIR / "stats_trust_cle.json"
#: la page de direction reste sur youl4b.com ; celle des VA (sv.SITE) est
#: passée sur trust-ofm.com le 07/11/2026
SITE = domaines.SITE
CHEMIN = "/trust/liens"
#: Une période relue est gardée 10 min, comme la page perso.
CACHE_S = 600
#: Périodes choisies à la main (hors raccourcis) qu'on peut faire lire par
#: jour : chacune relit tous les VA, sur les quotas du podium et de la paie
#: (10 000 lectures GetMySocial par jour et par clé) -- à froid, ~80 à 180
#: lectures de pays par période ; 30 permettaient jusqu'à ~6 000 lectures.
PERIODES_JOUR_MAX = 10
#: Périodes gardées en mémoire ; au-delà, la plus ancienne sort.
LOTS_MAX = 12
#: Recharge de la page tant que la lecture n'est pas finie, en secondes.
RECHARGE_S = 8
#: Une période EN FILE que plus personne ne regarde depuis ça (la page en
#: attente se recharge toutes les RECHARGE_S) en sort sans être lue : sans ça,
#: quatre dates essayées par un manager passaient avant la quinzaine du
#: propriétaire, plusieurs minutes chacune. Une lecture commencée va au bout :
#: un onglet de téléphone suspendu une minute la faisait repartir de zéro.
ABANDON_S = 60
#: Un VA lu en plus de LENT_S a attendu le délai d'une source muette (30 s par
#: appel MyPuls, ~94 s par appel Infloww) ; LENTS_MAX d'affilée : la lecture
#: s'arrête, le reste est dit au pied de la page, et un nouvel essai part
#: ESSAI_S plus tard (la page se recharge jusque-là). Une lecture complète
#: d'avant reste affichée : elle n'est pas remplacée par des lignes vides.
LENT_S = 60
LENTS_MAX = 3
ESSAI_S = 300

#: Les tris : clé dans l'adresse -> (libellé de colonne, sens par défaut).
TRIS: Dict[str, Tuple[str, str]] = {
    "nom": ("VA", "asc"),
    "us": ("Clics US GMS", "desc"), "glob": ("Clics globaux GMS", "desc"),
    "infloww": ("Clics Infloww", "desc"), "subs": ("Subs", "desc"),
    "cvr": ("CVR", "desc"), "ltv": ("LTV", "desc"), "gagne": ("Gagné", "desc"),
    "cout": ("Coût / sub", "asc"), "marge": ("Marge / sub", "desc"),
    "gain": ("Gain / perte", "desc"),
}
TRI_DEFAUT = ("subs", "desc")
#: Les tris demandés par le propriétaire, en raccourcis au-dessus du tableau.
RACCOURCIS_TRI: Tuple[Tuple[str, str, str], ...] = (
    ("Plus de subs", "subs", "desc"), ("Moins de subs", "subs", "asc"),
    ("Plus de clics", "glob", "desc"), ("Moins de clics", "glob", "asc"),
    ("Meilleure LTV", "ltv", "desc"), ("Pire LTV", "ltv", "asc"),
    ("Coût / sub le plus bas", "cout", "asc"), ("Coût / sub le plus haut", "cout", "desc"),
    ("Plus rentables", "marge", "desc"), ("Moins rentables", "marge", "asc"),
    ("Plus gros gains", "gain", "desc"), ("Plus grosses pertes", "gain", "asc"),
)

_VERROU = threading.Lock()
#: (du, au) -> {"fait": lot fini ou None, "encours": lot en lecture ou None}
_LOTS: Dict[Tuple[str, str], Dict[str, Any]] = {}
_FILE: List[Tuple[str, str]] = []
_FIL: Optional[threading.Thread] = None
_LECTURES: Dict[str, int] = {}
#: (du, au) -> dernier affichage de la période
_VUS: Dict[Tuple[str, str], float] = {}
#: jour -> périodes déjà comptées ce jour-là : une période sortie de la file
#: sans être lue n'est ni dans _LOTS ni dans _FILE, et chaque retour du manager
#: la recomptait sans un seul VA lu
_COMPTEES: Dict[str, set] = {}


# ─── la clé ──────────────────────────────────────────────────────────────
def cle() -> str:
    """La clé de la page, créée au premier appel puis toujours la même. Lève
    OSError si elle n'a pas pu être écrite."""
    with _VERROU:
        d = safe_json.load(CLE_FICHIER, {})
        k = str((d or {}).get("cle") or "") if isinstance(d, dict) else ""
        if len(k) >= 20:
            return k
        k = secrets.token_urlsafe(24)
        if not safe_json.write(CLE_FICHIER, {"cle": k, "cree": int(time.time())}):
            raise OSError(f"clé de la page TRUST non écrite ({CLE_FICHIER})")
        try:
            CLE_FICHIER.chmod(0o600)
        except Exception:
            pass
        return k


def cle_ok(k: Any) -> bool:
    """La clé donnée est-elle celle de la page ? Comparée en temps constant ;
    sans clé créée, rien n'ouvre. Ne lève pas."""
    s = str(k or "").encode("utf-8")
    if len(s) < 20:
        return False
    try:
        d = safe_json.load(CLE_FICHIER, {})
    except Exception as e:                                   # noqa: BLE001
        print(f"[stats-trust] clé illisible : {type(e).__name__}: {e}", flush=True)
        return False
    bonne = str((d or {}).get("cle") or "").encode("utf-8") if isinstance(d, dict) else b""
    return bool(bonne) and hmac.compare_digest(s, bonne)


def lien() -> str:
    return f"{SITE}{CHEMIN}?k={cle()}"


# ─── qui est sur la page ─────────────────────────────────────────────────
def personnes() -> Tuple[List[Dict[str, Any]], List[str]]:
    """([VA], [remarques]) : les fiches de liens_va des trois serveurs, sauf
    les VA partis. Une fiche sans numéro est gardée (sa ligne dira « — ») ;
    une source illisible est remontée, pas tue."""
    import liens_va
    import tickets_discord
    remarques: List[str] = []
    try:
        fiches = (liens_va._etat().get("liens") or {})
    except Exception as e:                                   # noqa: BLE001
        return [], [f"fiches des VA illisibles : {type(e).__name__}: {e}"]
    out: List[Dict[str, Any]] = []
    for gid, code, nom in SERVEURS:
        try:
            partis = tickets_discord.partis(gid)
        except Exception as e:                               # noqa: BLE001
            partis = {}
            remarques.append(f"départs de TRUST {nom.upper()} illisibles ({type(e).__name__}) : "
                             "les VA partis peuvent y figurer")
        for k, f in fiches.items():
            g, _s, uid = str(k).partition(":")
            if g != gid or not uid or not isinstance(f, dict) or uid in partis:
                continue
            out.append({"gid": gid, "uid": uid, "code": code, "plateforme": nom,
                        "numero": f.get("numero"), "pseudo": str(f.get("pseudo") or "")})
    return out, remarques


# ─── la lecture en fond ──────────────────────────────────────────────────
def _nouveau_lot() -> Dict[str, Any]:
    return {"debut": time.time(), "fin": None, "gens": [], "lignes": {}, "pannes": {}, "remarques": []}


def _abandonnee(du: str, au: str) -> bool:
    """Plus regardée depuis ABANDON_S. Jamais affichée (appel direct) : non."""
    t = _VUS.get((du, au))
    return t is not None and time.time() - t > ABANDON_S


def _calculer(du: str, au: str) -> Dict[str, Any]:
    """Lit tous les VA sur [du, au] (("", "") : depuis toujours), un par un,
    dans le lot « encours » de la période ; le lot passe « fait » à la fin
    (sauf arrêt « source muette » quand une lecture complète existe déjà)."""
    import podium_discord as pod
    with _VERROU:
        e = _LOTS.setdefault((du, au), {"fait": None, "encours": None})
        lot = e.get("encours") or _nouveau_lot()
        e["encours"] = lot
    gens, remarques = personnes()
    lot["gens"], lot["remarques"] = gens, list(remarques)
    lents, arrete = 0, False
    with pod.listes_du_lot():
        for i, p in enumerate(gens):
            if lents >= LENTS_MAX:
                for q in gens[i:]:
                    lot["pannes"][f"{q['gid']}:{q['uid']}"] = "pas lu : une source ne répond plus"
                lot["remarques"].append(
                    f"Lecture arrêtée après {LENTS_MAX} VA de plus de {LENT_S} s chacun (MyPuls, Infloww "
                    f"ou GetMySocial ne répond plus) : {len(gens) - i} VA pas lus")
                print(f"[stats-trust] lecture {du or 'toujours'}→{au} arrêtée : {len(gens) - i} VA pas lus",
                      flush=True)
                arrete = True
                break
            k = f"{p['gid']}:{p['uid']}"
            t = time.time()
            try:
                d = sv.chiffres(p["gid"], p["uid"], du, au)
            except LookupError:
                d, lot["pannes"][k] = None, "pas de fiche"
            except Exception as e:                           # noqa: BLE001
                d, lot["pannes"][k] = None, f"{type(e).__name__} : {str(e)[:120]}"
            if d is not None:
                lot["lignes"][k] = d
            lents = lents + 1 if time.time() - t > LENT_S else 0
    lot["fin"] = time.time()
    with _VERROU:
        e = _LOTS.setdefault((du, au), {"fait": None, "encours": None})
        ancien = e.get("fait")
        e["encours"] = None
        if arrete:
            e["essai_apres"], e["echec"] = time.time() + ESSAI_S, lot["remarques"][-1]
            lot["incomplet"] = True
            # source muette : une lecture complète d'avant reste affichée
            if not (ancien and not ancien.get("incomplet")):
                e["fait"] = lot
        else:
            e.pop("essai_apres", None)
            e.pop("echec", None)
            e["fait"] = lot
        if len(_LOTS) > LOTS_MAX:
            vieux = sorted((x for x in _LOTS if x != (du, au)),
                           key=lambda x: ((_LOTS[x].get("fait") or {}).get("fin") or 0))
            for x in vieux[:len(_LOTS) - LOTS_MAX]:
                if not _LOTS[x].get("encours"):
                    _LOTS.pop(x, None)
    return lot


def _boucle() -> None:
    global _FIL
    while True:
        with _VERROU:
            _FILE[:] = [x for x in _FILE if not _abandonnee(*x)]
            if not _FILE:
                _FIL = None
                return
            p = _FILE.pop(0)
            # marquée en lecture sous le même verrou que le pop : sans ça, une
            # 2e requête arrivée pendant personnes() la remettait en file, et
            # les ~80 VA étaient relus deux fois de suite
            _LOTS.setdefault(p, {"fait": None, "encours": None})["encours"] = _nouveau_lot()
        try:
            _calculer(*p)
        except Exception as e:                               # noqa: BLE001
            print(f"[stats-trust] lecture {p} en panne : {type(e).__name__}: {e}", flush=True)
            with _VERROU:
                (_LOTS.get(p) or {})["encours"] = None


def demander(du: str, au: str) -> None:
    """Met la période en file si elle n'est ni lue depuis moins de CACHE_S, ni
    déjà en lecture ou en attente ; un seul fil lit, une période après
    l'autre."""
    global _FIL
    with _VERROU:
        _VUS[(du, au)] = time.time()
        for x in [x for x, t in _VUS.items() if time.time() - t > 86400]:
            _VUS.pop(x, None)
        e = _LOTS.get((du, au)) or {}
        fait = e.get("fait")
        if e.get("encours") or (du, au) in _FILE:
            return
        if time.time() < float(e.get("essai_apres") or 0):
            return
        if fait and not fait.get("incomplet") and time.time() - float(fait.get("fin") or 0) < CACHE_S:
            return
        _FILE.append((du, au))
        if _FIL is None or not _FIL.is_alive():
            _FIL = threading.Thread(target=_boucle, name="stats-trust", daemon=True)
            _FIL.start()


class TropDePeriodes(Exception):
    """Assez de périodes choisies à la main aujourd'hui."""


def _compter_periode(du: str, au: str, jour: dt.date) -> None:
    """Lève TropDePeriodes au-delà de PERIODES_JOUR_MAX périodes à la main
    par jour ; une période déjà en mémoire ne recompte pas, les raccourcis
    jamais."""
    if (du, au) in {(a, b) for _l, a, b in sv._raccourcis(jour)}:
        return
    with _VERROU:
        # une période déjà en mémoire ou en file ne recompte pas : sa page
        # « Lecture en attente » se recharge toutes les RECHARGE_S, et chaque
        # rechargement vidait le quota du jour, pour tout le monde
        j = jour.isoformat()
        if (du, au) in _LOTS or (du, au) in _FILE or (du, au) in _COMPTEES.get(j, ()):
            return
        for vieux in [x for x in _LECTURES if x != j]:
            _LECTURES.pop(vieux, None)
        for vieux in [x for x in _COMPTEES if x != j]:
            _COMPTEES.pop(vieux, None)
        if _LECTURES.get(j, 0) >= PERIODES_JOUR_MAX:
            raise TropDePeriodes()
        _LECTURES[j] = _LECTURES.get(j, 0) + 1
        _COMPTEES.setdefault(j, set()).add((du, au))


# ─── les lignes ──────────────────────────────────────────────────────────
def _ligne(p: Mapping[str, Any], d: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """La ligne d'un VA : ses chiffres, et les trois qui en découlent."""
    d = d or {}
    subs, gagne, ltv = d.get("subs"), d.get("gagne"), d.get("par_sub")
    if d.get("revenu_partiel"):
        # un revenu sans Emy ou Seren (retirées de MyPuls) : LTV et marge
        # seraient fausses comme le gain, « — » et la raison au pied
        ltv = None
    cout = (float(gagne) / subs) if gagne is not None and subs else None
    # Threads est payé aux clics : 0 sub et un Gagné > 0, ce n'est pas une
    # ligne illisible, c'est la plus chère (130 $ pour 0 sub sortait en bas)
    paye_sans_sub = subs == 0 and bool(gagne)
    # Gain / perte (propriétaire, 07/11 : « combien d'argent j'ai perdu sur le
    # VA ») : la règle de la page du Spam (infloww_liens), revenu net MyPuls de
    # ses liens sur la période − ce qu'il a gagné, en centimes entiers
    revenu = d.get("revenu")
    gain = (round(float(revenu) * 100) - round(float(gagne) * 100)) / 100 \
        if revenu is not None and gagne is not None else None
    num = str(p.get("numero") or "")
    return {"gid": p["gid"], "code": p["code"], "plateforme": p["plateforme"],
            "nom": f"{p['plateforme']} VA {num}" if num.isdigit() else f"{p['plateforme']} (sans numéro)",
            "numero": int(num) if num.isdigit() else None,
            "pseudo": str(d.get("pseudo") or p.get("pseudo") or ""),
            "lu": bool(d), "us": d.get("us"), "glob": d.get("glob"), "infloww": d.get("infloww"),
            "subs": subs, "cvr": d.get("cvr"), "ltv": ltv, "gagne": gagne, "cout": cout,
            "paye_sans_sub": paye_sans_sub, "revenu": revenu, "gain": gain,
            "revenu_partiel": bool(d.get("revenu_partiel")),
            "marge": (ltv - cout) if ltv is not None and cout is not None else None}


def trier(lignes: List[Dict[str, Any]], tri: str, sens: str) -> List[Dict[str, Any]]:
    """Triées par `tri` dans `sens` ; une valeur illisible (None) toujours en
    bas, quel que soit le sens. À égalité : serveur puis numéro."""
    def depart(x: Mapping[str, Any]) -> Tuple[int, int]:
        return ([c for _g, c, _n in SERVEURS].index(x["code"]), x["numero"] if x["numero"] is not None else 10**6)
    base = sorted(lignes, key=depart)
    if tri == "nom":
        cle_t = lambda x: (x["pseudo"] or x["nom"]).lower()     # noqa: E731
    else:
        def cle_t(x: Mapping[str, Any]) -> Any:
            if tri in ("cout", "marge") and x.get("paye_sans_sub"):
                return float("inf") if tri == "cout" else float("-inf")
            return x.get(tri)
    lus = [x for x in base if cle_t(x) is not None]
    vides = [x for x in base if cle_t(x) is None]
    return sorted(lus, key=cle_t, reverse=(sens == "desc")) + vides


def totaux(lignes: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """La ligne « Total » : sommes des chiffres lus ; LTV, coût / sub et marge
    pondérés par les subs, sur un seul groupe de VA (n_groupe)."""
    def somme(c: str) -> Optional[float]:
        v = [x[c] for x in lignes if x.get(c) is not None]
        return sum(v) if v else None
    # LTV, coût et marge sur LE MÊME groupe : les VA dont paie, subs et revenu
    # sont lus (à 0 sub, aucun revenu à attribuer : sa paie compte quand même).
    # Sans ça la marge du Total pouvait contredire sa LTV et son coût.
    groupe = [x for x in lignes if x.get("gagne") is not None and x.get("subs") is not None
              and (x.get("ltv") is not None or x["subs"] == 0)]
    n = sum(x["subs"] for x in groupe)
    paie = sum(x["gagne"] for x in groupe)
    ltv = (sum((x["ltv"] or 0) * x["subs"] for x in groupe) / n) if n else None
    cout = (paie / n) if n else None
    avec_gain = [x for x in lignes if x.get("gain") is not None]
    gain = (sum(round(x["gain"] * 100) for x in avec_gain) / 100) if avec_gain else None
    return {"us": somme("us"), "glob": somme("glob"), "infloww": somme("infloww"), "subs": somme("subs"),
            "gagne": somme("gagne"), "ltv": ltv, "cout": cout, "gain": gain, "n_gain": len(avec_gain),
            "marge": (ltv - cout) if ltv is not None and cout is not None else None,
            "paye_sans_sub": bool(groupe) and not n and paie > 0, "n_groupe": len(groupe),
            "th_groupe": any(x.get("code") == "th" for x in groupe)}


# ─── la page ─────────────────────────────────────────────────────────────
def _e(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def _adresse(cle_: str, s: str, du: str, au: str, tri: str, sens: str) -> str:
    from urllib.parse import urlencode
    q: Dict[str, str] = {}
    if cle_:
        q["k"] = cle_
    if s != "tous":
        q["s"] = s
    if du:
        q["du"], q["au"] = du, au
    else:
        q["tout"] = "1"
    if (tri, sens) != TRI_DEFAUT:
        q["tri"], q["sens"] = tri, sens
    return _e(CHEMIN + "?" + urlencode(q))


def _argent(v: Any, signe: bool = False) -> str:
    import infloww_liens as il
    if v is None:
        return "—"
    if signe and v < 0:
        return "−" + il._dollars(-v)
    return il._dollars(v)


def _formulaire(cle_: str, s: str, du: str, au: str, tri: str, sens: str, jour: dt.date) -> str:
    """La période, sans JavaScript, comme la page perso : un formulaire GET qui
    garde la clé, le serveur et le tri ; les raccourcis en simples liens."""
    import podium_discord as pod
    liens, deja = [], False
    for lib, d, a in sv._raccourcis(jour):
        on = ""
        if (d, a) == (du, au) and not deja:
            on, deja = ' class="on" aria-current="page"', True
        liens.append(f'<a href="{_adresse(cle_, s, d, a, tri, sens)}"{on}>{_e(lib)}</a>')
    caches = "".join(f'<input type="hidden" name="{n}" value="{_e(v)}">'
                     for n, v in (("k", cle_), ("s", s if s != "tous" else ""),
                                  ("tri", tri if (tri, sens) != TRI_DEFAUT else ""),
                                  ("sens", sens if (tri, sens) != TRI_DEFAUT else "")) if v)
    bornes = f'min="{_e(pod.ALLTIME_DEPUIS)}" max="{_e(jour.isoformat())}"'
    return (f'<form class="periode" method="get">{caches}<span class="lib">Période</span>'
            f'<input type="date" name="du" value="{_e(du)}" {bornes} aria-label="Date de début">'
            '<span class="fl" aria-hidden="true">→</span>'
            f'<input type="date" name="au" value="{_e(au)}" {bornes} aria-label="Date de fin">'
            '<button type="submit">OK</button></form>'
            f'<nav class="raccourcis" aria-label="Périodes">{"".join(liens)}</nav>')


_STYLE_EN_PLUS = """
body{max-width:1240px}
.onglets{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.onglets a{color:var(--texte);text-decoration:none;background:var(--carte);border:1px solid var(--bord);border-radius:8px;padding:6px 12px;font-size:13px;font-weight:600;white-space:nowrap}
.onglets a.on{background:var(--acc);border-color:var(--acc);color:#1c0a02}
.onglets a span{opacity:.7;font-weight:500}
.tris{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 0 14px}
.tris .lib{color:var(--faible);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-right:2px}
.tris a{color:var(--faible);text-decoration:none;border:1px solid var(--bord);border-radius:999px;padding:4px 10px;font-size:12px;white-space:nowrap}
.tris a.on{color:var(--acc);border-color:var(--acc)}
th a{color:inherit;text-decoration:none}
th a.on{color:var(--acc)}
td.rang{color:var(--faible);font-weight:600;font-size:12px;text-align:right;width:1%}
td.neg{color:#f87171} td.pos{color:#4ade80}
tr.total td{background:rgba(249,115,65,.08);border-bottom:2px solid var(--bord)}
tr.vide td{color:var(--faible);font-weight:400}
.encours{border:1px solid var(--ambre);color:var(--ambre);border-radius:10px;padding:8px 12px;margin:0 0 12px;font-size:13px}
.lienmgr{background:var(--carte);border:1px dashed var(--bord);border-radius:10px;padding:8px 12px;margin:0 0 14px;font-size:12px;color:var(--faible);overflow-wrap:anywhere}
.lienmgr code{color:var(--texte);user-select:all}
"""


def _gabarit(titre: str, corps: str, recharge: bool = False, recharge_s: int = RECHARGE_S) -> str:
    meta = f'<meta http-equiv="refresh" content="{int(recharge_s)}">' if recharge else ""
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="dark">{meta}
<title>{_e(titre)}</title><style>{sv._STYLE}{_STYLE_EN_PLUS}</style></head><body>
<div class="marque">TRUST · Twitter · Instagram · Threads</div>
{corps}
</body></html>'''


def page_html(lot: Optional[Mapping[str, Any]], encours: Optional[Mapping[str, Any]], *,
              cle_: str, s: str, du: str, au: str, tri: str, sens: str,
              jour: dt.date, lien_mgr: str = "", en_file: bool = False,
              essai_apres: float = 0.0, echec: str = "") -> str:
    """La page, sans JavaScript. `lot` : la dernière lecture finie (ou None) ;
    `encours` : celle qui tourne (ou None) ; `en_file` : une relecture attend
    son tour. Tout est échappé."""
    import infloww_liens as il
    montre = lot or encours or {}
    gens = list(montre.get("gens") or [])
    lignes_tous = [_ligne(p, (montre.get("lignes") or {}).get(f"{p['gid']}:{p['uid']}")) for p in gens]
    lignes = [x for x in lignes_tous if s == "tous" or x["code"] == s]
    lignes = trier(lignes, tri, sens)
    tot = totaux(lignes)

    onglets = []
    for code, nom in [("tous", "Tous")] + [(c, n) for _g, c, n in SERVEURS]:
        n = sum(1 for x in lignes_tous if code == "tous" or x["code"] == code)
        on = ' class="on" aria-current="page"' if code == s else ""
        onglets.append(f'<a href="{_adresse(cle_, code, du, au, tri, sens)}"{on}>{_e(nom)} <span>{n}</span></a>')
    puces = []
    for lib, t, se in RACCOURCIS_TRI:
        on = ' class="on" aria-current="true"' if (t, se) == (tri, sens) else ""
        puces.append(f'<a href="{_adresse(cle_, s, du, au, t, se)}"{on}>{_e(lib)}</a>')

    def entete(t: str) -> str:
        lib, sens_def = TRIS[t]
        if t == tri:
            nouveau = "asc" if sens == "desc" else "desc"
            fl = " ↓" if sens == "desc" else " ↑"
            return (f'<th class="{"g" if t == "nom" else ""}"><a class="on" href="'
                    f'{_adresse(cle_, s, du, au, t, nouveau)}">{_e(lib)}{fl}</a></th>')
        return (f'<th class="{"g" if t == "nom" else ""}"><a href="{_adresse(cle_, s, du, au, t, sens_def)}">'
                f'{_e(lib)}</a></th>')

    def nb(v: Any) -> str:
        return sv._nb(v)

    def marge_td(v: Any) -> str:
        cls = "" if v is None else (' class="neg"' if v < 0 else ' class="pos"')
        return f"<td{cls}>{_argent(v, signe=True)}</td>"

    def th_td(v: Any, marge: bool, threads: bool) -> str:
        # Threads : Gagné paie tous les clics, les subs ne comptent que les
        # visiteurs trackés : coût / sub trop haut, marge trop basse
        if v is None or not threads:
            return marge_td(v) if marge else f"<td>{_argent(v)}</td>"
        cls = (' class="neg"' if v < 0 else ' class="pos"') if marge else ""
        return (f'<td{cls} title="subs des visiteurs envoyés sans tracking non comptés">'
                f'{_argent(v, signe=marge)}*</td>')

    def gain_td(v: Any, threads: bool) -> str:
        # Threads : Gagné paie tous les clics du lien, mais une partie des
        # visiteurs part sur une page sans tracking : leur revenu n'est compté
        # nulle part, la perte affichée est un maximum (relecture du 07/11)
        if v is None or not threads:
            return marge_td(v)
        cls = ' class="neg"' if v < 0 else ' class="pos"'
        return (f'<td{cls} title="revenu des visiteurs envoyés sans tracking non compté">'
                f'{_argent(v, signe=True)}*</td>')

    corps_t = []
    det_tot = f"{len(lignes)} VA"
    if lignes and tot["n_groupe"] < len(lignes):
        det_tot += f" · LTV, coût, marge : {tot['n_groupe']} VA"
    if lignes and tot["n_gain"] < len(lignes):
        det_tot += f" · gain / perte : {tot['n_gain']} VA"
    corps_t.append('<tr class="total"><td class="rang"></td><td class="nom"><b>Total</b>'
                   f'<span class="det">{_e(det_tot)}</span></td>'
                   f'<td>{nb(tot["us"])}</td><td>{nb(tot["glob"])}</td><td>{nb(tot["infloww"])}</td>'
                   f'<td class="subs">{nb(tot["subs"])}</td><td></td>'
                   f'<td>{_argent(tot["ltv"])}</td><td>{_argent(tot["gagne"])}</td>'
                   + ('<td class="neg">payé, 0 sub</td><td class="neg">payé, 0 sub</td>' if tot["paye_sans_sub"]
                      else th_td(tot["cout"], False, tot["th_groupe"]) + th_td(tot["marge"], True, tot["th_groupe"]))
                   + gain_td(tot["gain"], any(x["code"] == "th" and x.get("gain") is not None for x in lignes))
                   + '</tr>')
    for i, x in enumerate(lignes, 1):
        cvr = il._pastille(il._pct(x["cvr"]), il.niveau(x["cvr"], il.SEUIL_CVR))
        ltv = il._pastille(il._dollars(x["ltv"]), il.niveau(x["ltv"], il.SEUIL_PAR_SUB))
        qui = ("@" + _e(x["pseudo"])) if x["pseudo"] else _e(x["nom"])
        det = f'<span class="det">{_e(x["nom"])}</span>' if x["pseudo"] else ""
        cls_tr = "" if x["lu"] else ' class="vide"'
        corps_t.append(f'<tr{cls_tr}><td class="rang">{i}</td>'
                       f'<td class="nom">{qui}{det}</td>'
                       f'<td>{nb(x["us"])}</td><td>{nb(x["glob"])}</td><td>{nb(x["infloww"])}</td>'
                       f'<td class="subs">{nb(x["subs"])}</td><td>{cvr}</td><td>{ltv}</td>'
                       f'<td>{_argent(x["gagne"])}</td>'
                       + ('<td class="neg">payé, 0 sub</td><td class="neg">payé, 0 sub</td>'
                          if x.get("paye_sans_sub")
                          else th_td(x["cout"], False, x["code"] == "th") + th_td(x["marge"], True, x["code"] == "th"))
                       + gain_td(x["gain"], x["code"] == "th") + '</tr>')
    tableau = ('<div class="boite"><table><thead><tr><th></th>'
               + "".join(entete(t) for t in ("nom", "us", "glob", "infloww", "subs", "cvr",
                                             "ltv", "gagne", "cout", "marge", "gain"))
               + '</tr></thead><tbody>' + "".join(corps_t) + '</tbody></table></div>')

    bandeau = ""
    if encours:
        fait_n = len(encours.get("lignes") or {}) + len(encours.get("pannes") or {})
        total_n = len(encours.get("gens") or [])
        bandeau = (f'<div class="encours">Lecture en cours : {fait_n} / {total_n} VA. '
                   + ("La page montre la lecture précédente et se met à jour seule."
                      if lot else "La page se complète seule.") + '</div>')
    elif essai_apres > time.time():
        h = sv._paris(essai_apres)
        bandeau = (f'<div class="encours">{_e(echec)}. '
                   + ("La page montre la dernière lecture complète. " if lot and not lot.get("incomplet") else "")
                   + f'Nouvel essai à {_e(h.strftime("%H:%M") if h else "?")}, la page se recharge seule.</div>')
    elif en_file and lot:
        bandeau = ('<div class="encours">Mise à jour en attente (une autre période est en lecture). '
                   'La page montre la lecture précédente et se met à jour seule.</div>')
    elif not montre:
        bandeau = '<div class="encours">Lecture en attente. La page se complète seule.</div>'

    marques = ["— : pas encore lisible",
               "LTV : revenu net MyPuls des liens du VA ÷ ses subs",
               "Coût / sub : Gagné ÷ subs · Marge / sub : LTV − coût / sub · payé, 0 sub : Gagné sans "
               "aucun sub sur la période (Threads, payé aux clics)",
               "Gain / perte : revenu net MyPuls des liens du VA sur la période − Gagné (vert : on gagne, "
               "rouge : on perd) ; « — » quand le revenu net ou le Gagné n'est pas lisible (MyPuls muet, "
               "VA sans tracking à lui, VA non lu)",
               "* Threads : Gagné paie tous les clics US·UK·CA du lien, mais une partie des visiteurs part "
               "sur une page sans tracking : ni leurs subs ni leur revenu ne sont comptés ; coût / sub et "
               "perte affichés sont des maximums, marge et gain des minimums",
               "Threads : clics US·UK·CA, payé aux clics ; Twitter et Instagram : payés aux subs"]
    n_partiel = sum(1 for x in lignes if x.get("revenu_partiel"))
    if n_partiel:
        marques.append(f"{n_partiel} VA avec un ancien tracking Emy ou une variante Seren (retirées de "
                       "MyPuls, revenu non daté) : LTV, marge et gain / perte « — »")
    pannes = dict(montre.get("pannes") or {})
    if pannes:
        noms = {f"{p['gid']}:{p['uid']}": f"{p['plateforme']} VA {p.get('numero') or '?'}" for p in gens}
        marques.append("Non lus : " + " · ".join(f"{noms.get(k, k)} ({v})" for k, v in sorted(pannes.items())))
    marques += list(montre.get("remarques") or [])
    lu_t = sv._paris(montre.get("fin") or montre.get("debut") or time.time())
    sources = " · ".join(f'API officielle <a href="{_e(u)}" rel="noopener noreferrer">{_e(n)}</a>'
                         for n, u in sv.SOURCES)
    pied = (f'<p class="pied">Sources : {sources}</p>'
            + "".join(f'<p class="pied">{_e(m)}</p>' for m in marques)
            + (f'<p class="pied">Lu le {_e(lu_t.strftime("%d/%m à %H:%M"))} (heure de Paris)'
               ' · page réservée à la direction, ne pas la donner aux VA</p>' if lu_t else ""))
    lienmgr = (f'<div class="lienmgr">Lien à donner aux managers (sans compte) : <code>{_e(lien_mgr)}</code></div>'
               if lien_mgr else "")
    corps = ('<h1>📊 VA TRUST · clics et subs</h1>'
             f'<p class="sous"><b>{_e(sv._titre_periode(du, au, jour))}</b></p>'
             + lienmgr + _formulaire(cle_, s, du, au, tri, sens, jour)
             + f'<nav class="onglets" aria-label="Serveurs">{"".join(onglets)}</nav>'
             + f'<nav class="tris" aria-label="Tri"><span class="lib">Trier</span>{"".join(puces)}</nav>'
             + bandeau + tableau + pied)
    attente = int(essai_apres - time.time()) + 1 if essai_apres > time.time() and not encours else 0
    return _gabarit("VA TRUST · clics et subs", corps,
                    recharge=bool(encours) or en_file or not montre or attente > 0,
                    recharge_s=min(ESSAI_S, max(RECHARGE_S, attente)) if attente > 0 else RECHARGE_S)


def page(args: Any, cle_: str = "", lien_mgr: str = "") -> Tuple[int, str]:
    """(code HTTP, HTML) de la page pour `args` (s, du, au, tout, tri, sens).
    Lance la lecture en fond si besoin et rend tout de suite ce qui est lu.
    Ne lève jamais : une panne s'affiche sur la page."""
    import podium_discord as pod
    args = args or {}
    try:
        jour = pod._aujourdhui()
        s = str(args.get("s") or "tous").lower()
        if s not in _PAR_CODE:
            s = "tous"
        tri = str(args.get("tri") or TRI_DEFAUT[0]).lower()
        if tri not in TRIS:
            tri = TRI_DEFAUT[0]
        sens = str(args.get("sens") or "").lower()
        if sens not in ("asc", "desc"):
            sens = TRI_DEFAUT[1] if tri == TRI_DEFAUT[0] else TRIS[tri][1]
        du, au = sv.periode(args)
        try:
            _compter_periode(du, au, jour)
        except TropDePeriodes:
            return 429, _gabarit("VA TRUST", '<h1>📊 VA TRUST</h1><p class="sous">Beaucoup de périodes '
                                 'demandées à la main aujourd\'hui. Les raccourcis (quinzaines, 7 et 30 '
                                 'jours…) marchent toujours.</p>'
                                 + _formulaire(cle_, s, "", "", tri, sens, jour))
        demander(du, au)
        with _VERROU:
            e = dict(_LOTS.get((du, au)) or {})
            en_file = (du, au) in _FILE
        return 200, page_html(e.get("fait"), e.get("encours"), cle_=cle_, s=s, du=du, au=au,
                              tri=tri, sens=sens, jour=jour, lien_mgr=lien_mgr, en_file=en_file,
                              essai_apres=float(e.get("essai_apres") or 0), echec=str(e.get("echec") or ""))
    except Exception as e:                                   # noqa: BLE001
        return 200, _gabarit("VA TRUST", f'<h1>📊 VA TRUST</h1><div class="err"><b>Lecture impossible.</b>'
                             f'<br>{_e(type(e).__name__)} : {_e(str(e)[:200])}</div>')
