# -*- coding: utf-8 -*-
"""tests_podium_us.py — Va IG montre aussi les VA US, pour le moment.

Demande du propriétaire (03/10/2026) : le podium et le classement subs de Va
IG avaient l'air vides (trois VA). « pour les subs mais aussi le mec du US,
comme ca ca fait comme si y'a des vrais mecs », « mets les VA US aussi »,
« juste pour le moment, je te dirai pour couper plus tard ». Un interrupteur :
la clé « avec_us » de podium_discord.SERVEURS[VA_IG_ID].

Ce qu'il voulait aussi : faire passer les VA US pour des VA « Alicia ».
Refusé (le travail d'un VA prêté à un autre, sur un classement qui paie).
Compromis annoncé : leur vrai libellé anonyme (« VA 12 »), un en-tête qui
dit que le classement couvre toute l'agence, aucune marque FR/US ligne à
ligne ; ce qui touche à la paie dit toujours « VA FR ».

Ce qui est vérifié :
  - une seule liste, du plus fort au plus faible : VA FR (« Amelia VA 3 »,
    clics FR/BE/CH/LU/MC) et VA US (« VA 1 », clics US), sans marché ligne
    à ligne ni nulle part dans le texte, hors paie ; en-têtes « toute
    l'agence », un seul total, avertissements neutres (« Sans relevé ») ;
  - l'argent : 💰 seulement à côté des VA FR vraiment payés (trois premiers
    FR avec au moins un sub), même quand un VA US est premier ou qu'un VA FR
    à zéro est dans le top 3, avec le rang FR que suivi_va leur annonce en
    privé (« (2e VA FR) ») ; suivi_va reçoit le classement FR SEUL ; un
    relevé FR raté ne donne jamais un podium fait de VA US ;
  - le quota : Va IG reprend le relevé que Twitter vient de faire, aucun
    appel GetMySocial de plus (ni pour les clics, ni pour l'all-time) ; après
    un redémarrage, deux relevés US au plus (semaine, quinzaine) ;
  - la semaine (vivant, « terminée », podium, gel du mardi) et la quinzaine
    (vivante, figée) mêlées, sur les chiffres de la période entière ;
  - un VA de Twitter sans relevé n'est jamais retiré en silence : un relevé
    troué ne remplace pas un relevé complet, la quinzaine attend Twitter
    pour figer, et ce qui manque encore est dit dans le message ;
  - SANS la clé, chaque appel à Discord est identique à celui du code d'avant
    l'interrupteur (commit 61e291f, lu dans git) ; AVEC la clé, ceux de
    Twitter le sont aussi ; et tests_podium_fige.py passe sur ce code-là.

Faux Discord, faux GetMySocial (le VRAI classement tourne dessus), horloge
simulée, dossier temporaire : aucun appel réseau, rien n'est écrit dans data/.
Lancement : python tests_podium_us.py

La comparaison avec 61e291f vaut tant que podium_discord ne change que pour
cet interrupteur. Quand il sera coupé pour de bon, retirer la clé, le code
« avec_us » et ce fichier ensemble (tests_podium_fige.py n'en dépend pas :
il ne touche _retenir et _RELEVES qu'à travers getattr, et la clé qu'à
travers .get, pour le total de la quinzaine mêlée) ; un autre
changement du podium d'ici là déplace REF sur le commit qui le précède.
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

REF = "61e291f"                        # le code d'avant l'interrupteur
CLOCK = {"now": dt.datetime(2026, 9, 22, 12, 0)}
J = dt.timedelta(days=1)

# ------------------------------------------------ faux suivi_va (la paie) --
_PRIMES = []
_faux_suivi = types.ModuleType("suivi_va")
_faux_suivi.annoncer_primes = lambda gid, cl, debut, fin: (
    _PRIMES.append((str(gid), debut.isoformat(), copy.deepcopy(cl)))
    or {"dits": [], "sans_adresse": [], "inconnus": []})
sys.modules["suivi_va"] = _faux_suivi

# ------------------------------------------------- faux GetMySocial --------
EQ_TW1, EQ_TW2 = "tm_6a0e4739bfa0c238f20a8bf5", "tm_6ab46ebb11a0232c11211b1a"
EQ_FR = "tm_6ac06401e06eabe3b9ef45f6"
# clics par heure et par pays. Chaque marché ne compte que SES pays : les
# clics FR d'un lien Twitter et les clics US d'un lien FR ne comptent pas.
LIENS = {
    EQ_TW1: {"t1": ("Twitter VA 1 @abdoul", {"US": 10, "FR": 1}),
             "t2": ("Twitter VA 2 @bryan", {"US": 7}),
             "t3": ("Twitter VA 3 @carl", {"US": 5, "BE": 2}),
             "t4": ("Twitter VA 4 @dino", {"US": 2})},
    EQ_TW2: {"t5": ("Twitter VA 5 @emy", {"US": 1})},
    EQ_FR: {"f3": ("Amelia VA 3 @seven", {"FR": 6, "BE": 2, "CH": 1, "US": 3}),
            "f1": ("Amelia VA 1 @prisca", {"FR": 5, "LU": 1}),
            "f2": ("Lola VA 2 @lea", {"FR": 3, "MC": 1, "US": 4}),
            "fb": ("Amelia 1", {"FR": 50})},          # lien de base : jamais classé
}
TAUX = {i: t for eq in LIENS.values() for i, (_n, t) in eq.items()}
IDS_TW = set(LIENS[EQ_TW1]) | set(LIENS[EQ_TW2])
NUMEROS_TW = {"abdoul": 1, "bryan": 2, "carl": 3, "dino": 4, "emy": 5}
# par heure, dans la mesure de chaque marché
HEURE = {"VA 1": 10, "VA 2": 7, "VA 3": 5, "VA 4": 2, "VA 5": 1,
         "Amelia VA 3": 9, "Amelia VA 1": 6, "Lola VA 2": 4}
FR_NOMS = {"Amelia VA 3", "Amelia VA 1", "Lola VA 2"}
US_NOMS = {"VA 1", "VA 2", "VA 3", "VA 4", "VA 5"}
ORDRE = ["VA 1", "Amelia VA 3", "VA 2", "Amelia VA 1", "VA 3", "Lola VA 2", "VA 4", "VA 5"]

GMS = []                               # chaque appel d'analytics
FR_MUET, TW_MUET = set(), set()        # (d0, d1) : GetMySocial ne rend rien
LIEN_MUET = set()                      # (id, d0, d1) : ce lien seul ne répond pas
PAUSE = {"on": False}


def heures(d0, d1):
    """Les heures écoulées de [d0, d1] à l'horloge simulée."""
    a, b = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)
    auj = CLOCK["now"].date()
    h = 0
    plein = min(b, auj - J)
    if plein >= a:
        h += 24 * ((plein - a).days + 1)
    if a <= auj <= b:
        h += CLOCK["now"].hour
    return h


def _analytics(ids, d0, d1):
    ids = [str(i) for i in ids]
    marche = "US" if ids[0] in IDS_TW else "FR"
    GMS.append({"ids": tuple(ids), "d0": d0, "d1": d1, "quand": CLOCK["now"], "marche": marche})
    if (d0, d1) in (TW_MUET if marche == "US" else FR_MUET):
        return None, None
    if any((i, d0, d1) in LIEN_MUET for i in ids):
        return None, None
    pays = {}
    for i in ids:
        for p, r in TAUX[i].items():
            pays[p] = pays.get(p, 0) + r * heures(d0, d1)
    return sum(pays.values()), pays


_faux_gms = types.ModuleType("gms")
_faux_gms.analytics_for_links = _analytics
_faux_gms.list_links_team = lambda team, force_refresh=False: {
    "ok": True, "links": [{"id": i, "display_name": n} for i, (n, _t) in LIENS.get(team, {}).items()]}
_faux_gms.pause_restante = lambda: 0
sys.modules["gms"] = _faux_gms

import podium_discord as pd            # noqa: E402
import safe_json                       # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, IG = pd.TWITTER_ID, pd.VA_IG_ID
GIDS = (TW, IG)


# ------------------------------------------------------- le faux Discord --
class FauxDiscord:
    """Un compteur d'identifiants PAR SALON : les messages de Twitter gardent
    les mêmes identifiants quoi que fasse Va IG, et se comparent tels quels."""

    def __init__(self):
        self.salons, self.appels, self.n = {}, [], {}

    def api(self, methode, chemin, **kw):
        js = copy.deepcopy(kw.get("json"))
        self.appels.append({"m": methode, "p": chemin, "json": js, "quand": CLOCK["now"]})
        parts = chemin.strip("/").split("/")
        if parts[0] != "channels":
            return 200, []
        msgs = self.salons.setdefault(parts[1], {})
        if methode == "POST" and len(parts) == 3:
            self.n[parts[1]] = self.n.get(parts[1], 0) + 1
            mid = f"{parts[1]}:{self.n[parts[1]]}"
            msgs[mid] = {"json": js, "rang": self.n[parts[1]]}
            return 200, {"id": mid}
        mid = parts[3]
        if methode == "PATCH":
            if mid not in msgs:
                return 404, {"message": "Unknown Message", "code": 10008}
            msgs[mid]["json"] = js
            return 200, {"id": mid}
        if methode == "DELETE":
            return (204, {}) if msgs.pop(mid, None) else (404, {})
        return 404, {}


DISCORD = FauxDiscord()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="podium_us_test_"))
_SAUVE = {k: getattr(pd, k) for k in (
    "DATA_DIR", "ETAT_FICHIER", "CONFIG_FICHIER", "NUMEROS_FICHIER", "LIENS_CACHE",
    "ALLTIME_FICHIER", "_maintenant", "_aujourdhui", "_api", "_salon", "_pause_gms", "time")}
_SAUVE_IG = dict(pd.SERVEURS[IG])
_NB_BAC = [0]


def installer(mod):
    """Un bac neuf pour ce module : dossier, horloge, Discord, pause."""
    global DISCORD
    _NB_BAC[0] += 1
    d = TMP / f"bac{_NB_BAC[0]}"
    d.mkdir()
    safe_json.write_text(d / "podium_numeros.json", json.dumps(NUMEROS_TW))
    mod.DATA_DIR = d
    mod.ETAT_FICHIER = d / "podium.json"
    mod.CONFIG_FICHIER = d / "podium_config.json"
    mod.NUMEROS_FICHIER = d / "podium_numeros.json"
    mod.LIENS_CACHE = d / "gmsdash_links.json"
    mod.ALLTIME_FICHIER = d / "podium_alltime.json"
    mod._maintenant = lambda: CLOCK["now"]
    mod._aujourdhui = lambda: CLOCK["now"].date()
    mod.time = types.SimpleNamespace(time=lambda: CLOCK["now"].timestamp(), sleep=lambda s: None)
    mod._pause_gms = lambda: PAUSE["on"]
    mod._salon = lambda gid, voulu="": (f"{gid}-subs" if "subs" in (voulu or "")
                                       else f"{gid}-bonus" if "bonus" in (voulu or "")
                                       else f"{gid}-podium")
    DISCORD = FauxDiscord()
    mod._api = lambda methode, chemin, **kw: DISCORD.api(methode, chemin, **kw)
    if hasattr(mod, "_RELEVES"):
        mod._RELEVES.clear()
    GMS.clear()
    _PRIMES.clear()
    FR_MUET.clear()
    TW_MUET.clear()
    LIEN_MUET.clear()
    PAUSE["on"] = False
    PASSES.clear()


PASSES = []                            # (gid, moment, appels GetMySocial de ce passage)


def a(mod, moment):
    """Un tour de la vraie boucle (web_upload._start_podium_semaine_daemon),
    Twitter d'abord, comme dans verif_discord.SERVEURS_EXTRA."""
    CLOCK["now"] = moment
    for gid in GIDS:
        n0 = len(GMS)
        if mod.a_poster():
            mod.poster_podium(gid)
        if mod.a_rafraichir(gid):
            mod.rafraichir(gid)
        if mod.a_rafraichir_subs(gid):
            mod.rafraichir_subs(gid)
        if mod.a_rafraichir_bonus(gid):
            mod.rafraichir_bonus(gid)
        PASSES.append((gid, moment, GMS[n0:]))


def us_par_ig(moment=None):
    """Les appels GetMySocial sur des liens de Twitter faits par Va IG."""
    return [x for g, m, appels in PASSES if g == IG and (moment is None or m == moment)
            for x in appels if x["marche"] == "US"]


def derouler(mod, calendrier, controles=None):
    installer(mod)
    for moment, action in calendrier:
        if action:
            action()
        a(mod, moment)
        if controles and moment in controles:
            controles[moment]()
    return [(x["m"], x["p"], x["json"]) for x in DISCORD.appels]


# ------------------------------------------------------------ lecture --
def P(gid):
    return f"{gid}-podium"


def S(gid):
    return f"{gid}-subs"


def emb(js):
    """Le premier embed d'un message, ou l'embed lui-même (rendu direct)."""
    if isinstance(js, dict) and "description" in js and "embeds" not in js:
        return js
    return ((js or {}).get("embeds") or [{}])[0]


def titre(js):
    return emb(js).get("title", "")


def desc(js):
    return emb(js).get("description", "")


def pied(js):
    return (emb(js).get("footer") or {}).get("text", "")


def msg(salon, mid):
    return (DISCORD.salons.get(salon, {}).get(mid) or {}).get("json")


# « · 💰 **10$** (1er VA FR) » : le montant, puis le rang FR, celui que
# suivi_va annonce en privé et auquel la prime se réclame. Le groupe
# « FR 📸 / US 🐦 » reste lu : une marque de marché revenue sur une ligne
# doit faire échouer les contrôles, pas les rendre aveugles.
RE_PODIUM = re.compile(r"^(?:(🥇|🥈|🥉)|(\d+)\.) \*{0,2}(.+?)\*{0,2} — \*\*(\d+)\*\* subs"
                       r"(?: · (FR 📸|US 🐦))?(?: · 💰 \*\*(\d+)\$\*\*(?: \((\d+)(?:er|e) VA FR\))?)?$")
RE_SUBS = re.compile(r"^(?:(🥇|🥈|🥉)|(\d+)\.) \*{0,2}(.+?)\*{0,2} — \*{0,2}(\d+)\*{0,2} subs"
                     r"(?: · (FR 📸|US 🐦))?(?: · 🌐 (\d+) all-time)?$")


def lignes(texte, rx=RE_PODIUM):
    out = []
    for l in texte.split("\n"):
        m = rx.match(l)
        if m:
            out.append({"med": m.group(1), "rang": int(m.group(2)) if m.group(2) else None,
                        "va": m.group(3), "clics": int(m.group(4)), "marche": m.group(5),
                        "extra": int(m.group(6)) if m.group(6) else None,
                        "rang_fr": (int(m.group(7)) if m.re.groups >= 7 and m.group(7) else None),
                        "brut": l})
    return out


def attendu(va, d0, d1):
    return HEURE[va] * heures(d0.isoformat(), d1.isoformat())


def classement_attendu(d0, d1):
    return [(va, attendu(va, d0, d1)) for va in ORDRE]


LUN_W, DIM_W = dt.date(2026, 9, 21), dt.date(2026, 9, 27)
LUN_W1 = dt.date(2026, 9, 28)
S_OLD, S_OLD_FIN, S_NEW = dt.date(2026, 9, 16), dt.date(2026, 9, 30), dt.date(2026, 10, 1)
ABO_MIX = "Abonnements de **toute l'agence**"
PRIMES_MIX = ["🎁 **Les 3 meilleurs VA FR de la semaine touchent une prime :**",
              "💰 1er VA FR → **10$**", "💰 2e VA FR → **5$**", "💰 3e VA FR → **3$**"]


def controle_podium_mix(etiquette, js, d0, d1, entier=True):
    """Le podium mêlé : ordre, libellés, clics de chaque marché, médailles, 💰."""
    t = desc(js)
    ls = lignes(t)
    attendus = classement_attendu(d0, d1)
    check(f"{etiquette} : une seule liste FR + US, du plus fort au plus faible",
          [(x["va"], x["clics"]) for x in ls] == attendus, [(x["va"], x["clics"]) for x in ls])
    check(f"{etiquette} : aucune ligne ne porte de marché (ni FR 📸 ni US 🐦)",
          all(x["marche"] is None and "📸" not in x["brut"] and "🐦" not in x["brut"] for x in ls)
          and len(ls) == len(ORDRE), [x["brut"] for x in ls])
    check(f"{etiquette} : le marché n'est dit nulle part, hors paie (« VA FR » du 💰 et des primes)",
          not marche_dit(t), marche_dit(t))
    check(f"{etiquette} : médailles aux trois premières places, quel que soit le marché",
          [x["med"] for x in ls[:3]] == ["🥇", "🥈", "🥉"] and ls[0]["va"] == "VA 1"
          and all(x["med"] is None for x in ls[3:]))
    primes = {x["va"]: x["extra"] for x in ls if x["extra"] is not None}
    check(f"{etiquette} : 💰 seulement aux trois VA FR payés (10 / 5 / 3 $), aucun aux VA US",
          primes == {"Amelia VA 3": 10, "Amelia VA 1": 5, "Lola VA 2": 3}, primes)
    rangs = {x["va"]: x["rang_fr"] for x in ls if x["extra"] is not None}
    check(f"{etiquette} : à côté du 💰, le rang FR (celui que suivi_va annonce), pas le rang mêlé",
          rangs == {"Amelia VA 3": 1, "Amelia VA 1": 2, "Lola VA 2": 3}
          and "· 💰 **10$** (1er VA FR)" in t and "· 💰 **5$** (2e VA FR)" in t, rangs)
    check(f"{etiquette} : la prime se réclame avec le rang parmi les VA FR",
          "avec **ton rang parmi les VA FR** et" in t and "ton rang de la semaine" not in t, t[-500:])
    check(f"{etiquette} : aucun VA manquant, aucun avertissement",
          "Sans relevé" not in t and "non rafraîchie" not in t and "⚠️" not in t, t[-400:])
    check(f"{etiquette} : en-tête « toute l'agence », juste sous les dates",
          t.split("\n")[1] == ABO_MIX, t[:300])
    check(f"{etiquette} : bloc des primes réservé aux VA FR, sans médaille",
          all(p in t for p in PRIMES_MIX) and "🥇 1er → **10$**" not in t, t[-700:])
    check(f"{etiquette} : pied « Marchés FR + US »",
          pied(js).startswith("YOULAB • Marchés FR + US · comptes VA, sans pseudo"), pied(js))


def controle_subs_mix(etiquette, js, d0, d1, totaux_us=None, totaux_fr=None):
    t = desc(js)
    ls = lignes(t, RE_SUBS)
    check(f"{etiquette} : quinzaine FR + US triée, aucune ligne avec un marché",
          [(x["va"], x["clics"]) for x in ls] == classement_attendu(d0, d1)
          and all(x["marche"] is None and "📸" not in x["brut"] and "🐦" not in x["brut"]
                  for x in ls), [x["brut"] for x in ls])
    check(f"{etiquette} : en-tête « Subs de toute l'agence · 8 comptes classés »",
          "\nSubs de **toute l'agence** · **8** comptes classés\n" in t, t[:300])
    check(f"{etiquette} : le marché n'est dit nulle part dans la page", not marche_dit(t), marche_dit(t))
    tot = sum(attendu(v, d0, d1) for v in FR_NOMS | US_NOMS)
    check(f"{etiquette} : un seul total, la somme de toutes les lignes ({tot})",
          tot == sum(x["clics"] for x in ls)
          and t.split("👥 **Total période**\n")[1].split("\n")[0] == f"**{tot}** subs", t[-300:])
    check(f"{etiquette} : pied « Marchés FR + US »", "YOULAB • Marchés FR + US · comptes VA" in pied(js),
          pied(js))
    if totaux_us is not None:
        at = {x["va"]: x["extra"] for x in ls}
        check(f"{etiquette} : all-time des VA US pris chez Twitter, des VA FR chez Va IG",
              all(at[v] == totaux_us.get(v) for v in US_NOMS)
              and all(at[v] == (totaux_fr or {}).get(v) for v in FR_NOMS), at)


def marche_dit(texte):
    """Ce qui, dans un texte mêlé, dirait encore le marché d'un VA : les lignes
    qui nomment FR, US, Twitter, Instagram ou leurs emojis. Seule la paie
    garde « VA FR » (💰 sur la ligne, bloc des primes, rang à réclamer)."""
    out = []
    for l in texte.split("\n"):
        if re.search(r"\bUS\b|🐦|📸|Twitter|Instagram|Marchés?\b", l):
            out.append(l)
        elif re.search(r"\bFR\b", l) and not (
                "💰" in l or "Les 3 meilleurs VA FR de la semaine touchent une prime" in l
                or "ton rang parmi les VA FR" in l):
            out.append(l)
    return out


def sans_us(js):
    """Aucune ligne de VA US, aucun mot du mélange : le message FR d'avant."""
    t = desc(js) + "\n" + pied(js)
    return (not [x for x in lignes(desc(js)) + lignes(desc(js), RE_SUBS) if x["va"] in US_NOMS]
            and "Marchés" not in t and "VA US" not in t and "US 🐦" not in t
            and "toute l'agence" not in t)


# ------------------------------------------------- le code d'avant (git) --
def charger_ancien():
    r = subprocess.run(["git", "-C", str(BOT), "show", f"{REF}:podium_discord.py"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0 or "def classement(" not in r.stdout:
        return None
    f = TMP / "podium_avant.py"
    f.write_text(r.stdout, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("podium_avant", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def muet_fr_semaine():
    FR_MUET.add((LUN_W.isoformat(), DIM_W.isoformat()))


def fr_revenu():
    FR_MUET.clear()


def pause_on():
    PAUSE["on"] = True
    FR_MUET.add((LUN_W.isoformat(), DIM_W.isoformat()))
    TW_MUET.add((LUN_W.isoformat(), DIM_W.isoformat()))


def pause_off():
    PAUSE["on"] = False


def m(*x):
    return dt.datetime(*x)


# la vie normale : semaine, lundi « terminée », podium de 9h, quinzaine figée
CAL_NORMAL = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 22, 13, 0), None),
              (m(2026, 9, 22, 14, 10), None), (m(2026, 9, 24, 12, 0), None),
              (m(2026, 9, 27, 20, 0), None), (m(2026, 9, 28, 0, 10), None),
              (m(2026, 9, 28, 3, 0), None), (m(2026, 9, 28, 9, 0), None),
              (m(2026, 9, 28, 9, 10), None), (m(2026, 9, 29, 10, 0), None),
              (m(2026, 9, 30, 23, 50), None), (m(2026, 10, 1, 0, 10), None),
              (m(2026, 10, 1, 12, 0), None), (m(2026, 10, 4, 22, 0), None),
              (m(2026, 10, 5, 0, 10), None), (m(2026, 10, 5, 9, 0), None),
              (m(2026, 10, 5, 9, 10), None)]
# le relevé FR rate tout le lundi : pas de podium, gel le mardi
CAL_FR_MUET = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 27, 20, 0), None),
               (m(2026, 9, 28, 0, 10), muet_fr_semaine), (m(2026, 9, 28, 9, 0), None),
               (m(2026, 9, 28, 12, 0), None), (m(2026, 9, 28, 23, 50), None),
               (m(2026, 9, 29, 0, 10), fr_revenu), (m(2026, 9, 29, 12, 0), None)]
# GetMySocial en pause du lundi 9h au mardi 18h : la semaine se fige sans lui
CAL_PAUSE = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 28, 0, 10), None),
             (m(2026, 9, 28, 9, 0), pause_on), (m(2026, 9, 28, 15, 0), None),
             (m(2026, 9, 29, 0, 0), None), (m(2026, 9, 29, 12, 0), None),
             (m(2026, 9, 29, 18, 0), pause_off)]

try:
    ancien = charger_ancien()
    check(f"le code d'avant l'interrupteur ({REF}) se lit dans git", ancien is not None)

    # ================================================================ 1. --
    print()
    print("=" * 70)
    print("1. La vie normale, interrupteur MIS : tout Va IG est mêlé, rien n'est payé aux VA US")
    print("=" * 70)

    def c_mardi():
        t = m(2026, 9, 22, 12, 0)
        etat = pd._etat()
        js = msg(P(IG), etat["vivants"][IG]["message"])
        controle_podium_mix("vivant mardi", js, LUN_W, t.date())
        check("vivant mardi : toujours « Semaine en cours » et « Rien n'est joué »",
              titre(js) == "🔴 PODIUM SUBS — SEMAINE EN COURS" and "Rien n'est joué" in desc(js))
        check("vivant mardi : Va IG n'a fait AUCUN appel GetMySocial sur les liens de Twitter "
              "(relevé de Twitter repris, all-time compris)", not us_par_ig(t), us_par_ig(t)[:3])
        page = msg(S(IG), etat["subs"][IG]["messages"][0])
        totaux_us = pd._alltime_lu(TW)
        totaux_fr = pd._alltime_lu(IG)
        check("vivant mardi : les deux all-time existent (Twitter et Va IG, chacun son fichier)",
              set(totaux_us) == US_NOMS and set(totaux_fr) == FR_NOMS, (totaux_us, totaux_fr))
        controle_subs_mix("quinzaine vivante", page, S_OLD, t.date(), totaux_us, totaux_fr)
        check("quinzaine vivante : toujours « la quinzaine » et « mis à jour »",
              titre(page) == "📊 Classement subs — la quinzaine" and "mis à jour" in pied(page))
        for nom, snap in (("semaine", etat["vivants"][IG]["dernier"]),
                          ("quinzaine", etat["subs"][IG]["dernier"])):
            check(f"relevé gardé pour figer ({nom}) : les seuls VA FR, sans marque ni prime",
                  {x["va"] for x in snap["lignes"]} == FR_NOMS
                  and not any(k in x for x in snap["lignes"] for k in ("marche", "pastille", "prime")),
                  snap["lignes"])
        tw = msg(P(TW), etat["vivants"][TW]["message"])
        check("Twitter mardi : ses VA seuls, ses mots d'avant",
              {x["va"] for x in lignes(desc(tw))} == US_NOMS
              and "Abonnements via Twitter 🐦 — clics **US**" in desc(tw)
              and pied(tw).startswith("YOULAB • Marché US ·"))

    def c_1300():
        check("13h00 : Twitter rafraîchit, Va IG attend ses deux heures",
              not [p for p in PASSES if p[0] == IG and p[1] == m(2026, 9, 22, 13, 0) and p[2]])

    def c_1410():
        t = m(2026, 9, 22, 14, 10)
        check("14h10 : Va IG rafraîchit sur le relevé que Twitter vient de faire, zéro appel US",
              [p for p in PASSES if p[0] == IG and p[1] == t and p[2]] and not us_par_ig(t),
              us_par_ig(t)[:3])
        js = msg(P(IG), pd._etat()["vivants"][IG]["message"])
        controle_podium_mix("vivant 14h10", js, LUN_W, t.date())

    def c_lundi0010():
        t = m(2026, 9, 28, 0, 10)
        etat = pd._etat()
        js = msg(P(IG), etat["vivants"][IG]["message"])
        check("lundi 00h10 : « semaine terminée » sur Va IG", titre(js) == "🏁 PODIUM SUBS — SEMAINE TERMINÉE")
        controle_podium_mix("lundi 00h10", js, LUN_W, DIM_W)
        check("lundi 00h10 : chiffres de la semaine ENTIÈRE, des deux côtés",
              "\n🥇 **VA 1** — **1680** subs\n" in desc(js)
              and "\n🥈 **Amelia VA 3** — **1512** subs · 💰 **10$** (1er VA FR)\n" in desc(js),
              desc(js)[:500])
        check("lundi 00h10 : zéro appel US de Va IG (le relevé « terminée » de Twitter est repris)",
              not us_par_ig(t), us_par_ig(t)[:3])

    def c_lundi9():
        t = m(2026, 9, 28, 9, 0)
        etat = pd._etat()
        mid = etat["postes"][f"{IG}:{LUN_W}"]
        js = msg(P(IG), mid)
        check("lundi 9h : le podium de Va IG est figé, mêlé", titre(js) == "🏆 PODIUM SUBS DE LA SEMAINE"
              and "il ne bougera plus" in desc(js) and pied(js).endswith("· résultat final"))
        controle_podium_mix("podium final", js, LUN_W, DIM_W)
        prim = [x for x in _PRIMES if x[0] == IG and x[1] == LUN_W.isoformat()]
        cl = prim[0][2] if prim else {}
        check("la paie reçoit le classement FR SEUL : ses trois VA FR, dans l'ordre FR, rien d'autre",
              len(prim) == 1 and [x["va"] for x in cl["lignes"]] == ["Amelia VA 3", "Amelia VA 1", "Lola VA 2"]
              and [x["clics"] for x in cl["lignes"]] == [1512, 1008, 672]
              and not any(k in x for x in cl["lignes"] for k in ("marche", "pastille", "prime")), prim)
        prim_tw = [x for x in _PRIMES if x[0] == TW and x[1] == LUN_W.isoformat()]
        check("la paie de Twitter reçoit ses VA seuls",
              len(prim_tw) == 1 and {x["va"] for x in prim_tw[0][2]["lignes"]} == US_NOMS)
        check("lundi 9h : zéro appel US de Va IG", not us_par_ig(t), us_par_ig(t)[:3])
        fg = etat["figes"][IG][LUN_W.isoformat()]
        check("lundi 9h : historique « podium », complet", fg["mode"] == "podium" and fg["complet"] is True)

    def c_quinzaine():
        t = m(2026, 10, 1, 0, 10)
        etat = pd._etat()
        fg = etat["subs_figes"][IG][S_OLD.isoformat()]
        js = msg(S(IG), fg["messages"][0])
        check("01/10 : la quinzaine finie de Va IG est figée",
              titre(js) == "📊 Classement subs — quinzaine du 16/09 au 30/09 (terminée)"
              and "Période terminée : classement arrêté, il ne bougera plus." in desc(js)
              and pied(js).endswith("· résultat final") and fg["complet"] is True, titre(js))
        controle_subs_mix("quinzaine figée", js, S_OLD, S_OLD_FIN)
        check("quinzaine figée : chiffres de la période ENTIÈRE (16 → 30/09), pas ceux de 23h50",
              re.search(r"^🥇 \*\*VA 1\*\* — \*\*3600\*\* subs( · 🌐 \d+ all-time)?$",
                        desc(js), re.M)
              and re.search(r"^🥈 \*\*Amelia VA 3\*\* — \*\*3240\*\* subs( · 🌐 \d+ all-time)?$",
                            desc(js), re.M), desc(js)[:400])
        check("01/10 : zéro appel US de Va IG pour figer", not us_par_ig(t), us_par_ig(t)[:3])
        check("quinzaine figée : rien n'y parle encore au présent",
              not [w for w in ("mis à jour", "prochain passage", "En cours") if w in desc(js) + pied(js)])

    controles = {m(2026, 9, 22, 12, 0): c_mardi, m(2026, 9, 22, 13, 0): c_1300,
                 m(2026, 9, 22, 14, 10): c_1410, m(2026, 9, 28, 0, 10): c_lundi0010,
                 m(2026, 9, 28, 9, 0): c_lundi9, m(2026, 10, 1, 0, 10): c_quinzaine}
    avec_normal = derouler(pd, CAL_NORMAL, controles)
    check("sur toute la quinzaine, Va IG n'a JAMAIS relevé un lien de Twitter (Twitter l'a fait pour lui)",
          not us_par_ig(), [(x["d0"], x["d1"], x["quand"]) for x in us_par_ig()][:4])
    etat = pd._etat()
    js = msg(P(IG), etat["postes"][f"{IG}:{LUN_W1}"])
    controle_podium_mix("podium du 05/10", js, LUN_W1, LUN_W1 + 6 * J)

    # ================================================================ 2. --
    print()
    print("=" * 70)
    print("2. Le quota : un relevé de Twitter repris moins de deux heures, ou pour toujours s'il est entier")
    print("=" * 70)
    installer(pd)
    a(pd, m(2026, 9, 22, 12, 0))
    CLOCK["now"] = m(2026, 9, 22, 13, 30)
    n0 = len(GMS)
    pd.rafraichir(IG)
    check("1h30 après Twitter : Va IG reprend son relevé, zéro appel US",
          not [x for x in GMS[n0:] if x["marche"] == "US"] and [x for x in GMS[n0:] if x["marche"] == "FR"])
    CLOCK["now"] = m(2026, 9, 22, 14, 5)                   # 2h05 sans que Twitter repasse
    n0 = len(GMS)
    pd.rafraichir(IG)
    us1 = [x for x in GMS[n0:] if x["marche"] == "US"]
    check("plus de 2 h : Va IG relève les VA US lui-même, UNE fois (un appel par VA de Twitter)",
          len(us1) == 5 and {x["ids"] for x in us1} == {(i,) for i in IDS_TW}, us1)
    n0 = len(GMS)
    pd.rafraichir(IG)
    check("… et le garde : le passage suivant ne relève rien chez Twitter",
          not [x for x in GMS[n0:] if x["marche"] == "US"])
    js = msg(P(IG), pd._etat()["vivants"][IG]["message"])
    controle_podium_mix("relevé US fait par Va IG", js, LUN_W, m(2026, 9, 22).date())
    # une période finie, relevée APRÈS sa fin : elle vaut pour toujours
    CLOCK["now"] = m(2026, 9, 22, 15, 0)
    n0 = len(GMS)
    r1 = pd._releve_us(dt.date(2026, 9, 14), dt.date(2026, 9, 20))
    CLOCK["now"] = m(2026, 9, 24, 15, 0)                   # deux jours plus tard
    r2 = pd._releve_us(dt.date(2026, 9, 14), dt.date(2026, 9, 20))
    check("période finie relevée après sa fin : reprise deux jours plus tard sans appel",
          r1 and r1 == r2 and len([x for x in GMS[n0:] if x["marche"] == "US"]) == 5)
    # la même période relevée AVANT sa fin ne la compte pas entière
    CLOCK["now"] = m(2026, 9, 27, 23, 50)
    pd._releve_us(LUN_W, DIM_W)
    CLOCK["now"] = m(2026, 9, 28, 0, 10)
    n0 = len(GMS)
    r3 = pd._releve_us(LUN_W, DIM_W)
    check("relevé du dimanche 23h50 : pas repris pour la semaine finie (il manque la fin du dimanche)",
          len([x for x in GMS[n0:] if x["marche"] == "US"]) == 5
          and r3["lignes"][0]["clics"] == 1680, r3 and r3["lignes"][:1])
    PAUSE["on"] = True
    n0 = len(GMS)
    check("GetMySocial en pause, rien d'entier en mémoire : pas de VA US, et aucun appel",
          pd._releve_us(dt.date(2026, 9, 7), dt.date(2026, 9, 13)) is None and len(GMS) == n0)
    check("en pause, un relevé entier déjà gardé sert quand même",
          pd._releve_us(LUN_W, DIM_W) is not None and len(GMS) == n0)
    PAUSE["on"] = False
    TW_MUET.add(("2026-09-01", "2026-09-06"))
    check("Twitter muet : pas de VA US (rien d'inventé), et rien de gardé",
          pd._releve_us(dt.date(2026, 9, 1), dt.date(2026, 9, 6)) is None
          and (TW, "2026-09-01", "2026-09-06") not in pd._RELEVES)
    CLOCK["now"] = m(2026, 10, 3, 12, 0)
    pd._retenir(TW, S_NEW, m(2026, 10, 3).date(), {"lignes": [{"va": "VA 1", "clics": 1}]})
    check("la mémoire se vide d'elle-même au-delà de quatre jours",
          (TW, "2026-09-14", "2026-09-20") not in pd._RELEVES
          and (TW, S_NEW.isoformat(), "2026-10-03") in pd._RELEVES)
    pd._retenir(IG, S_NEW, m(2026, 10, 3).date(), {"lignes": [{"va": "Amelia VA 3", "clics": 1}]})
    pd._retenir(None, S_NEW, m(2026, 10, 3).date(), {"lignes": [{"va": "VA 1", "clics": 1}]})
    check("seuls les relevés de Twitter sont gardés (ni Va IG, ni un appel sans serveur)",
          all(k[0] == TW for k in pd._RELEVES) and len(pd._RELEVES) == 1)

    # ================================================================ 3. --
    print()
    print("=" * 70)
    print("3. L'argent, sur des cas limites (rendu direct)")
    print("=" * 70)
    CLOCK["now"] = m(2026, 9, 28, 9, 30)

    def L(va, clics, numero=1, model=""):
        return {"va": va, "numero": numero, "clics": clics, "liens": 1, "spam": False, "model": model}

    cl_fr = {"lignes": [L("Amelia VA 3", 40, 3, "amelia"), L("Amelia VA 1", 0, 1, "amelia"),
                        L("Lola VA 2", 0, 2, "lola")], "illisibles": [], "frais": True}
    us2 = {"lignes": [L("VA 1", 100, 1), L("VA 2", 50, 2)], "illisibles": [], "frais": True}
    e = pd.embed_podium(cl_fr, LUN_W, DIM_W, gid=IG, us=us2)
    ls = lignes(desc(e))
    check("un VA US premier : il a la 🥇, pas de 💰",
          ls[0]["va"] == "VA 1" and ls[0]["med"] == "🥇" and ls[0]["extra"] is None, ls[:2])
    check("un VA FR à zéro sub dans le top 3 FR : pas de 💰 (suivi_va ne le paie pas)",
          [x["va"] for x in ls if x["extra"]] == ["Amelia VA 3"]
          and next(x for x in ls if x["va"] == "Amelia VA 3")["extra"] == 10
          and next(x for x in ls if x["va"] == "Amelia VA 3")["med"] == "🥉", [x["brut"] for x in ls])
    check("💰 n'apparaît qu'une fois dans le classement", sum("💰 **" in x["brut"] for x in ls) == 1)
    tout_zero = {"lignes": [dict(x, clics=0) for x in cl_fr["lignes"]], "illisibles": [], "frais": True}
    check("tout le monde à zéro côté FR : aucun 💰 dans le classement",
          not [x for x in lignes(desc(pd.embed_podium(tout_zero, LUN_W, DIM_W, gid=IG, us=us2)))
               if x["extra"]])
    # un VA FR loin derrière vingt VA US : toujours visible, avec sa prime
    us20 = {"lignes": [L(f"VA {i}", 200 - i, i) for i in range(1, 21)], "illisibles": [], "frais": True}
    cl3 = {"lignes": [L("Amelia VA 3", 40, 3, "amelia"), L("Amelia VA 1", 30, 1, "amelia"),
                      L("Lola VA 2", 20, 2, "lola")], "illisibles": [], "frais": True}
    t = desc(pd.embed_podium(cl3, LUN_W, DIM_W, gid=IG, us=us20))
    ls = lignes(t)
    check("VA FR au-delà des 15 premiers : affichés quand même, à leur vrai rang, avec leur 💰",
          [(x["rang"], x["va"], x["extra"]) for x in ls if x["va"] in FR_NOMS]
          == [(21, "Amelia VA 3", 10), (22, "Amelia VA 1", 5), (23, "Lola VA 2", 3)], t[-900:])
    check("… les quinze premiers d'abord, puis « … », puis les VA FR, puis le compte des autres",
          [x["rang"] or 0 for x in ls][:3] == [0, 0, 0] and [x["rang"] for x in ls][3:15] == list(range(4, 16))
          and "**15** subs" not in t and "\n…\n21. Amelia VA 3" in t
          and "… _et 5 autres_ 👏" in t, t[-600:])
    # à égalité de clics : VA FR d'abord, toujours le même ordre
    eg = {"lignes": [L("VA 1", 40, 1)], "illisibles": [], "frais": True}
    r_a = desc(pd.embed_podium(cl3, LUN_W, DIM_W, gid=IG, us=eg))
    r_b = desc(pd.embed_podium(cl3, LUN_W, DIM_W, gid=IG, us=eg))
    check("à égalité, le VA FR passe devant, et le rendu ne change pas d'un appel à l'autre",
          [x["va"] for x in lignes(r_a)][:2] == ["Amelia VA 3", "VA 1"] and r_a == r_b)
    # rien à mêler : exactement le message d'avant
    check("sans VA US (relevé indisponible), le message est le message FR d'avant",
          pd.embed_podium(cl3, LUN_W, DIM_W, gid=IG, us=None) == pd.embed_podium(cl3, LUN_W, DIM_W, gid=IG)
          and pd.embed_podium(cl3, LUN_W, DIM_W, gid=IG, us={"lignes": []})
          == pd.embed_podium(cl3, LUN_W, DIM_W, gid=IG))
    vide_fr = {"lignes": [], "illisibles": ["Amelia VA 3"], "frais": True}
    check("relevé FR vide : JAMAIS un classement fait des seuls VA US",
          pd._us_pour(IG, LUN_W, DIM_W, vide_fr) is None
          and sans_us(pd.embed_podium(vide_fr, LUN_W, DIM_W, gid=IG, us=us2))
          and sans_us({"embeds": pd.pages_subs(vide_fr, S_OLD, S_OLD_FIN, {}, gid=IG, us=us2)}))
    check("Twitter ne mêle jamais rien, même si on lui passait des VA US",
          pd._us_pour(TW, LUN_W, DIM_W, us2) is None)

    # ================================================================ 4. --
    print()
    print("=" * 70)
    print("4. Relevé FR raté tout le lundi : aucun podium (ni VA US seuls, ni primes), gel le mardi")
    print("=" * 70)

    def c_fr_lundi():
        etat = pd._etat()
        ig_final = [x for x in DISCORD.appels if x["p"].startswith(f"/channels/{P(IG)}/")
                    and titre(x["json"]) == "🏆 PODIUM SUBS DE LA SEMAINE"]
        check("lundi 23h50, FR muet : aucun podium sur Va IG, même avec les VA US disponibles",
              not ig_final and not (etat.get("postes") or {}).get(f"{IG}:{LUN_W}"))
        check("lundi, FR muet : aucune prime annoncée sur Va IG",
              not [x for x in _PRIMES if x[0] == IG])
        check("lundi, Twitter n'est pas gêné : son podium est parti",
              (etat.get("postes") or {}).get(f"{TW}:{LUN_W}"))
        js = msg(P(IG), etat["vivants"][IG]["message"])
        check("lundi, FR muet : « terminée » sur le dernier relevé FR, et il le dit",
              titre(js) == "🏁 PODIUM SUBS — SEMAINE TERMINÉE"
              and "Chiffres du dernier relevé (27/09 à 20h00)" in desc(js), desc(js)[-300:])

    def c_fr_mardi():
        etat = pd._etat()
        fg = etat["figes"][IG][LUN_W.isoformat()]
        js = msg(P(IG), fg["message"])
        check("mardi, FR revenu : la semaine de Va IG est figée sans podium, mêlée",
              fg["mode"] == "sans_podium" and titre(js) == "🏆 PODIUM SUBS DE LA SEMAINE"
              and fg["complet"] is True)
        controle_podium_mix("gel du mardi", js, LUN_W, DIM_W)
        check("mardi : toujours aucune prime sur Va IG (elles n'appartiennent qu'au podium)",
              not [x for x in _PRIMES if x[0] == IG])

    avec_fr_muet = derouler(pd, CAL_FR_MUET, {m(2026, 9, 28, 23, 50): c_fr_lundi,
                                              m(2026, 9, 29, 0, 10): c_fr_mardi})

    # ================================================================ 5. --
    print()
    print("=" * 70)
    print("5. GetMySocial en pause au moment de figer : mêlé sur ce qu'on a, ou FR seul, jamais d'appel")
    print("=" * 70)
    mardi = m(2026, 9, 29, 0, 0)

    def c_pause():
        etat = pd._etat()
        fg = etat["figes"][IG][LUN_W.isoformat()]
        js = msg(P(IG), fg["message"])
        controle_podium_mix("gel en pause", js, LUN_W, DIM_W)
        check("gel en pause : aucun appel GetMySocial depuis mardi 00h",
              not [x for x in GMS if x["quand"] >= mardi], [x for x in GMS if x["quand"] >= mardi][:2])

    avec_pause = derouler(pd, CAL_PAUSE, {mardi: c_pause})

    def oubli():
        pd._RELEVES.clear()            # le bot a redémarré : la mémoire est vide

    def c_pause_oubli():
        etat = pd._etat()
        js = msg(P(IG), etat["figes"][IG][LUN_W.isoformat()]["message"])
        check("gel en pause après un redémarrage : VA FR seuls, avec les mots d'avant (rien d'inventé)",
              sans_us(js) and "Abonnements via Instagram 📸 — clics **FR**" in desc(js)
              and pied(js) == "YOULAB • Marché FR · comptes VA, sans pseudo · résultat final"
              and "🎁 **Les 3 meilleurs de la semaine touchent une prime :**" in desc(js), desc(js)[:300])
        check("… et toujours aucun appel GetMySocial", not [x for x in GMS if x["quand"] >= mardi])

    derouler(pd, [(t, oubli if t == mardi else act) for t, act in CAL_PAUSE], {mardi: c_pause_oubli})

    # ================================================================ 6. --
    print()
    print("=" * 70)
    print(f"6. Interrupteur retiré : chaque appel à Discord est celui du code d'avant ({REF})")
    print("=" * 70)
    if ancien is not None:
        cals = (("vie normale", CAL_NORMAL, avec_normal), ("FR muet le lundi", CAL_FR_MUET, avec_fr_muet),
                ("pause", CAL_PAUSE, avec_pause))
        ref = {nom: derouler(ancien, cal) for nom, cal, _x in cals}
        try:
            pd.SERVEURS[IG].pop("avec_us", None)
            sans = {nom: derouler(pd, cal) for nom, cal, _x in cals}
            check("sans la clé, Va IG ne relève jamais un lien de Twitter", not us_par_ig())
        finally:
            pd.SERVEURS[IG].clear()
            pd.SERVEURS[IG].update(_SAUVE_IG)
        for nom, _cal, avec in cals:
            diff = next((i for i, (x, y) in enumerate(zip(ref[nom], sans[nom])) if x != y), None)
            check(f"{nom} : sans la clé, Twitter ET Va IG identiques au code d'avant, octet pour octet "
                  f"({len(ref[nom])} appels)",
                  ref[nom] == sans[nom] and len(ref[nom]) > 5,
                  (diff, ref[nom][diff] if diff is not None else len(ref[nom]),
                   sans[nom][diff] if diff is not None else len(sans[nom])))
            tw_ref = [x for x in ref[nom] if x[1].startswith(f"/channels/{TW}-")]
            tw_avec = [x for x in avec if x[1].startswith(f"/channels/{TW}-")]
            check(f"{nom} : AVEC la clé, les messages de Twitter sont ceux d'avant ({len(tw_ref)} appels)",
                  tw_ref == tw_avec and len(tw_ref) > 5)
            ig_ref = [x for x in ref[nom] if x[1].startswith(f"/channels/{IG}-")]
            ig_avec = [x for x in avec if x[1].startswith(f"/channels/{IG}-")]
            check(f"{nom} : AVEC la clé, Va IG fait les mêmes gestes (mêmes messages, mêmes éditions), "
                  "seul le contenu change",
                  [(x[0], x[1]) for x in ig_ref] == [(x[0], x[1]) for x in ig_avec]
                  and ig_ref != ig_avec)
        # les rendus seuls, pour un serveur FR et pour Twitter
        CLOCK["now"] = m(2026, 9, 28, 8, 0)
        cl_ill = dict(cl3, illisibles=["Lola VA 2"], frais=False)
        for g in (IG, TW, None):
            for kw in ({"en_cours": True}, {"termine": True}, {}):
                check(f"embed_podium {g or 'sans serveur'} {kw or 'final'} : rendu d'avant",
                      pd.embed_podium(cl_ill, LUN_W, DIM_W, gid=g, **kw)
                      == ancien.embed_podium(cl_ill, LUN_W, DIM_W, gid=g, **kw))
            for fin_ in (False, True):
                check(f"pages_subs {g or 'sans serveur'} final={fin_} : rendu d'avant",
                      pd.pages_subs(cl_ill, S_OLD, S_OLD_FIN, {"Amelia VA 3": 7}, gid=g, final=fin_)
                      == ancien.pages_subs(cl_ill, S_OLD, S_OLD_FIN, {"Amelia VA 3": 7}, gid=g, final=fin_))

    # ================================================================ 7. --
    print()
    print("=" * 70)
    print("7. Un seul interrupteur, temporaire, et la paie n'est pas touchée")
    print("=" * 70)
    src = (BOT / "podium_discord.py").read_text(encoding="utf-8")
    check("Va IG porte l'interrupteur, Twitter non",
          pd.SERVEURS[IG].get("avec_us") is True and "avec_us" not in pd.SERVEURS[TW])
    check("l'interrupteur n'est lu qu'à un seul endroit",
          src.count('.get("avec_us")') == 1 and src.count("avec_us") >= 2)
    _i = src.find('"avec_us": True')
    check("la clé dit qu'elle est temporaire et comment couper",
          _i > 0 and "juste pour le moment" in src[_i - 900:_i] and "POUR COUPER" in src[_i - 900:_i])
    check("la paie reçoit toujours `cl`, le classement FR",
          "suivi_va.annoncer_primes(gid, cl, debut, fin)" in src)

    # le 💰 affiché = ce que le VRAI suivi_va annonce et paie : on le fait
    # tourner (Discord, tickets et numéros simulés) sur les mêmes classements
    import os
    import liens_fr
    import requests
    _spec = importlib.util.spec_from_file_location("suivi_va_vrai", BOT / "suivi_va.py")
    sv = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sv)
    _num = TMP / "numeros_va_fr.json"
    safe_json.write_text(_num, json.dumps({"amelia": {"u3": 3, "u1": 1}, "lola": {"u2": 2, "u5": 5}}))
    _users = {u: {"channel_id": f"salon-{u}"} for u in ("u1", "u2", "u3", "u5")}
    _sauve_sv = (liens_fr.NUMEROS, safe_json.load, requests.post, os.environ.get("DISCORD_TOKEN"))
    _vrai_load = safe_json.load
    _annonces = []
    try:
        liens_fr.NUMEROS = _num
        safe_json.load = lambda chemin, default=None: (
            _users if pathlib.Path(chemin).name == "users.json" else _vrai_load(chemin, default=default))
        requests.post = lambda url, timeout=None, headers=None, json=None: (
            _annonces.append(json) or types.SimpleNamespace(status_code=200))
        os.environ["DISCORD_TOKEN"] = "faux-jeton"
        cas = {
            "un VA FR seul au-dessus de zéro": cl_fr,
            "trois VA FR payables": cl3,
            "quatre VA FR (le 4e jamais payé)": {"lignes": cl3["lignes"] + [L("Lola VA 5", 10, 5, "lola")],
                                                 "illisibles": [], "frais": True},
            "tous les VA FR à zéro": tout_zero,
        }
        for k, (nom, cl_) in enumerate(cas.items()):
            sv.ETAT_FICHIER = TMP / f"suivi_{k}.json"
            n_av = len(_annonces)
            b = sv._annoncer_primes_fr(IG, cl_, LUN_W, DIM_W)
            payes = {d.split(" : ")[0]: float(d.split(" : ")[1].rstrip("$")) for d in b["dits"]}
            rendu = lignes(desc(pd.embed_podium(cl_, LUN_W, DIM_W, gid=IG, us=us20)))
            affiches = {x["va"]: float(x["extra"]) for x in rendu if x["extra"] is not None}
            check(f"💰 = paie réelle de suivi_va ({nom})",
                  payes == affiches and (bool(payes) or cl_ is tout_zero), (payes, affiches))
            # le rang que le gagnant lit en privé (« 🥈 2e de la semaine ») est
            # celui qu'il lit à côté de son 💰 en public, et qu'il donne pour réclamer
            prives = {}
            for an in _annonces[n_av:]:
                e_ = an["embeds"][0]
                prives[re.search(r"· \*\*(.+?)\*\* ·", e_["description"]).group(1)] = int(
                    re.match(r"\S+ (\d+)e de la semaine", e_["title"]).group(1))
            publics = {x["va"]: x["rang_fr"] for x in rendu if x["extra"] is not None}
            check(f"rang FR affiché = rang annoncé en privé par suivi_va ({nom})",
                  prives == publics and all(publics.values()) or (not prives and not publics),
                  (prives, publics))
        check("suivi_va a bien annoncé dans les salons des gagnants (le test n'est pas vide)",
              len(_annonces) == 1 + 3 + 3 and all(x.get("content", "").startswith("<@u") for x in _annonces))
    finally:
        liens_fr.NUMEROS, safe_json.load, requests.post = _sauve_sv[:3]
        if _sauve_sv[3] is None:
            os.environ.pop("DISCORD_TOKEN", None)
        else:
            os.environ["DISCORD_TOKEN"] = _sauve_sv[3]

    # ================================================================ 8. --
    print()
    print("=" * 70)
    print("8. Un VA US sans relevé : jamais retiré en silence, jamais figé troué quand Twitter peut mieux")
    print("=" * 70)
    W = (LUN_W.isoformat(), DIM_W.isoformat())
    Q = (S_OLD.isoformat(), S_OLD_FIN.isoformat())
    CLE_W = (TW,) + W

    # -- A. le podium de 9h : un VA de Twitter ne répond pas, le relevé complet
    # de 00h10 reste celui que Va IG affiche (avant : VA 1 disparaissait,
    # Amelia VA 3 prenait sa 🥇, sans un mot, et l'historique disait « complet »)
    def t1_muet_semaine():
        LIEN_MUET.add(("t1",) + W)

    def c_9h_partiel():
        etat = pd._etat()
        e_ = pd._RELEVES.get(CLE_W) or {}
        check("9h, VA 1 muet chez Twitter : le relevé complet de 00h10 reste en mémoire",
              e_.get("jour") == "2026-09-28" and not e_["cl"]["illisibles"]
              and len(e_["cl"]["lignes"]) == 5, e_)
        tw = msg(P(TW), etat["postes"][f"{TW}:{LUN_W}"])
        check("… le podium de Twitter, lui, dit son classement incomplet (inchangé)",
              "⚠️ **Classement incomplet** : VA 1" in desc(tw))
        js = msg(P(IG), etat["postes"][f"{IG}:{LUN_W}"])
        controle_podium_mix("podium 9h, Twitter troué à 9h", js, LUN_W, DIM_W)
        check("… et l'historique de Va IG le dit complet, à raison",
              etat["figes"][IG][LUN_W.isoformat()]["complet"] is True)
        check("… sans un appel US de plus par Va IG", not us_par_ig(m(2026, 9, 28, 9, 0)))

    derouler(pd, [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 27, 20, 0), None),
                  (m(2026, 9, 28, 0, 10), None), (m(2026, 9, 28, 9, 0), t1_muet_semaine),
                  (m(2026, 9, 28, 9, 10), LIEN_MUET.clear)],
             {m(2026, 9, 28, 9, 0): c_9h_partiel})

    # -- B. VA 1 muet dès 00h10 et encore à 9h : rien de complet en mémoire.
    # « terminée » promet une relecture, le podium final dit qui manque.
    def c_0010_partiel():
        js = msg(P(IG), pd._etat()["vivants"][IG]["message"])
        t = desc(js)
        check("00h10, VA 1 muet : « terminée » le dit, sans marché, et promet la relecture du podium",
              "⚠️ **Sans relevé** : VA 1 — absent de ce classement, il sera relu pour le "
              "podium officiel." in t and "**VA 1**" not in t and not marche_dit(t), t[-500:])

    def c_9h_toujours():
        etat = pd._etat()
        js = msg(P(IG), etat["postes"][f"{IG}:{LUN_W}"])
        t = desc(js)
        ls = lignes(t)
        check("9h, VA 1 toujours muet : le podium final de Va IG le dit (pas de VA 1 inventé)",
              "⚠️ **Sans relevé** : VA 1 — absent de ce classement." in t and not marche_dit(t)
              and "VA 1" not in [x["va"] for x in ls] and len(ls) == 7, t[-600:])
        check("… les primes FR ne bougent pas (10 / 5 / 3 $ au rang FR)",
              {x["va"]: (x["extra"], x["rang_fr"]) for x in ls if x["extra"]}
              == {"Amelia VA 3": (10, 1), "Amelia VA 1": (5, 2), "Lola VA 2": (3, 3)})
        check("… et l'historique ne le dit pas complet",
              etat["figes"][IG][LUN_W.isoformat()]["complet"] is False)
        prim = [x for x in _PRIMES if x[0] == IG]
        check("… la paie reçoit toujours le classement FR seul",
              len(prim) == 1 and [x["va"] for x in prim[0][2]["lignes"]]
              == ["Amelia VA 3", "Amelia VA 1", "Lola VA 2"])

    derouler(pd, [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 27, 20, 0), None),
                  (m(2026, 9, 28, 0, 10), t1_muet_semaine), (m(2026, 9, 28, 9, 0), None)],
             {m(2026, 9, 28, 0, 10): c_0010_partiel, m(2026, 9, 28, 9, 0): c_9h_toujours})

    # -- C. la quinzaine : VA 3 muet chez Twitter à 00h10, revenu à 02h20.
    # Avant : Va IG figeait à 00h10 sans VA 3, pour toujours, « 7 comptes ».
    def t3_muet_quinzaine():
        LIEN_MUET.add(("t3",) + Q)

    def c_q_0010():
        etat = pd._etat()
        check("01/10 00h10, VA 3 muet : Twitter ET Va IG attendent pour figer la quinzaine",
              S_OLD.isoformat() in ((etat.get("subs_a_figer") or {}).get(IG) or {})
              and S_OLD.isoformat() in ((etat.get("subs_a_figer") or {}).get(TW) or {})
              and not ((etat.get("subs_figes") or {}).get(IG) or {}).get(S_OLD.isoformat()))
        check("… sans un appel US de Va IG (le relevé de Twitter, troué, est repris tel quel)",
              not us_par_ig(m(2026, 10, 1, 0, 10)), us_par_ig(m(2026, 10, 1, 0, 10))[:3])

    def c_q_0220():
        etat = pd._etat()
        fg = ((etat.get("subs_figes") or {}).get(IG) or {}).get(S_OLD.isoformat()) or {}
        js = msg(S(IG), (fg.get("messages") or [""])[0])
        check("02h20, VA 3 revenu : Va IG fige complet, juste après Twitter",
              fg.get("complet") is True and ((etat.get("subs_figes") or {}).get(TW) or {})
              .get(S_OLD.isoformat(), {}).get("complet") is True, fg)
        controle_subs_mix("quinzaine figée après relecture", js, S_OLD, S_OLD_FIN)
        tot_q = sum(attendu(v, S_OLD, S_OLD_FIN) for v in FR_NOMS | US_NOMS)
        check(f"… VA 3 y est, 1800 subs, total de toute l'agence {tot_q}, aucun avertissement",
              "\n5. VA 3 — 1800 subs · 🌐 " in desc(js)
              and f"👥 **Total période**\n**{tot_q}** subs" in desc(js)
              and "⚠️" not in desc(js), desc(js)[-500:])
        check("… sans un appel US de Va IG (le relevé complet de Twitter, 02h20, est repris)",
              not us_par_ig(m(2026, 10, 1, 2, 20)), us_par_ig(m(2026, 10, 1, 2, 20))[:3])

    derouler(pd, [(m(2026, 9, 29, 12, 0), None), (m(2026, 9, 30, 23, 50), None),
                  (m(2026, 10, 1, 0, 10), t3_muet_quinzaine), (m(2026, 10, 1, 2, 20), LIEN_MUET.clear)],
             {m(2026, 10, 1, 0, 10): c_q_0010, m(2026, 10, 1, 2, 20): c_q_0220})

    # -- D. VA 3 muet pour de bon : 48 h plus tard, figée avec ce qu'on a, en le disant
    def c_q_abandon():
        etat = pd._etat()
        fg = ((etat.get("subs_figes") or {}).get(IG) or {}).get(S_OLD.isoformat()) or {}
        js = msg(S(IG), (fg.get("messages") or [""])[0])
        t = desc(js)
        check("48 h sans VA 3 : la quinzaine de Va IG est figée, notée incomplète",
              fg.get("complet") is False and "il ne bougera plus" in t, fg)
        check("… et la page dit qui manque, au lieu de le taire",
              "⚠️ **Sans relevé** : VA 3 — absent de ce classement." in t and not marche_dit(t)
              and "· **7** comptes classés" in t
              and "VA 3" not in [x["va"] for x in lignes(t, RE_SUBS)],
              t[-500:])
        check("… sur 48 h, Va IG n'a jamais relevé un lien de Twitter (Twitter réessayait avant lui)",
              not us_par_ig(), [(x["d0"], x["d1"], x["quand"]) for x in us_par_ig()][:4])

    derouler(pd, [(m(2026, 9, 29, 12, 0), None), (m(2026, 9, 30, 23, 50), None),
                  (m(2026, 10, 1, 0, 10), t3_muet_quinzaine), (m(2026, 10, 1, 12, 0), None),
                  (m(2026, 10, 2, 12, 0), None), (m(2026, 10, 3, 0, 20), None)],
             {m(2026, 10, 3, 0, 20): c_q_abandon})

    # -- E. la mémoire elle-même
    installer(pd)
    CLOCK["now"] = m(2026, 9, 28, 0, 10)
    complet_ = {"lignes": [{"va": "VA 1", "clics": 9}, {"va": "VA 2", "clics": 5}],
                "illisibles": [], "frais": True}
    troue = {"lignes": [{"va": "VA 2", "clics": 5}], "illisibles": ["VA 1"], "frais": True}
    pd._retenir(TW, LUN_W, DIM_W, complet_)
    CLOCK["now"] = m(2026, 9, 28, 9, 0)
    pd._retenir(TW, LUN_W, DIM_W, troue)
    check("période finie : un relevé troué ne remplace pas un relevé complet",
          pd._RELEVES[CLE_W]["cl"]["lignes"] == complet_["lignes"])
    pd._retenir(TW, LUN_W, DIM_W, dict(complet_, frais=False))
    check("… ni un relevé fait sur la liste du cache (« des comptes peuvent manquer »)",
          pd._RELEVES[CLE_W]["cl"]["frais"] is True)
    pd._RELEVES.clear()
    pd._retenir(TW, LUN_W, DIM_W, troue)
    CLOCK["now"] = m(2026, 9, 28, 9, 30)
    pd._retenir(TW, LUN_W, DIM_W, complet_)
    check("… alors qu'un relevé complet remplace un relevé troué",
          pd._RELEVES[CLE_W]["cl"]["illisibles"] == [])
    CLOCK["now"] = m(2026, 9, 24, 12, 0)
    pd._retenir(TW, LUN_W, m(2026, 9, 24).date(), complet_)
    CLOCK["now"] = m(2026, 9, 24, 13, 0)
    pd._retenir(TW, LUN_W, m(2026, 9, 24).date(), troue)
    check("période en cours : le relevé le plus récent gagne, troué ou non (le message dit qui manque)",
          pd._RELEVES[(TW, LUN_W.isoformat(), "2026-09-24")]["cl"]["illisibles"] == ["VA 1"])
    # un relevé entier mais troué est relu deux heures après le dernier essai
    installer(pd)
    LIEN_MUET.add(("t2",) + W)
    CLOCK["now"] = m(2026, 9, 28, 0, 10)
    pd.classement(LUN_W, DIM_W, gid=TW)                   # Twitter, troué (VA 2)
    LIEN_MUET.clear()
    n0 = len(GMS)
    CLOCK["now"] = m(2026, 9, 28, 1, 0)
    r_ = pd._releve_us(LUN_W, DIM_W)
    check("relevé entier troué, essayé il y a moins de 2 h : repris tel quel, sans appel",
          r_["illisibles"] == ["VA 2"] and len(GMS) == n0)
    CLOCK["now"] = m(2026, 9, 28, 2, 20)
    r_ = pd._releve_us(LUN_W, DIM_W)
    n1 = len(GMS)
    check("… plus de 2 h après : relu une fois (un appel par VA de Twitter), et complet",
          r_["illisibles"] == [] and n1 - n0 == 5, (r_["illisibles"], n1 - n0))
    CLOCK["now"] = m(2026, 9, 28, 5, 0)
    check("… puis repris sans appel, pour toujours", pd._releve_us(LUN_W, DIM_W) is r_
          and len(GMS) == n1)
    installer(pd)
    LIEN_MUET.add(("t2",) + W)
    CLOCK["now"] = m(2026, 9, 28, 0, 10)
    pd.classement(LUN_W, DIM_W, gid=TW)
    PAUSE["on"] = True
    CLOCK["now"] = m(2026, 9, 28, 9, 0)
    n0 = len(GMS)
    check("en pause : le relevé entier troué est rendu tel quel (ses absents seront dits), sans appel",
          pd._releve_us(LUN_W, DIM_W)["illisibles"] == ["VA 2"] and len(GMS) == n0)
    PAUSE["on"] = False
    TW_MUET.add(W)
    check("relecture ratée : le relevé entier troué gardé vaut mieux que rien",
          pd._releve_us(LUN_W, DIM_W)["illisibles"] == ["VA 2"])

    # -- F. les avertissements, rendus directement
    CLOCK["now"] = m(2026, 9, 24, 12, 0)
    cl3b = {"lignes": [L("Amelia VA 3", 40, 3, "amelia"), L("Amelia VA 1", 30, 1, "amelia"),
                       L("Lola VA 2", 20, 2, "lola")], "illisibles": [], "frais": True}
    us_t = {"lignes": [L("VA 1", 100, 1)], "illisibles": ["VA 2", "VA 3"], "frais": False}
    t = desc(pd.embed_podium(cl3b, LUN_W, m(2026, 9, 24).date(), gid=IG, en_cours=True, us=us_t))
    check("vivant : « Sans relevé » (neutre) au pluriel, et ils remonteront au prochain passage",
          "⚠️ **Sans relevé** : VA 2, VA 3 — absents de ce classement, ils remonteront au "
          "prochain passage." in t and not marche_dit(t), t[-500:])
    check("vivant : liste des VA de Twitter non rafraîchie, dite sans marché",
          "⚠️ _Liste des liens non rafraîchie : des VA peuvent manquer._" in t
          and "Liste des liens non rafraîchie (GetMySocial" not in t)
    pg = pd.pages_subs(cl3b, S_OLD, S_OLD_FIN, {}, gid=IG, us=us_t)
    pgf = pd.pages_subs(cl3b, S_OLD, S_OLD_FIN, {}, gid=IG, final=True, us=us_t)
    check("quinzaine vivante / figée : les VA sans relevé y sont dits, sans marché",
          "⚠️ **Sans relevé** : VA 2, VA 3 — absents de ce classement, ils remonteront"
          in desc(pg[-1])
          and "⚠️ **Sans relevé** : VA 2, VA 3 — absents de ce classement." in desc(pgf[-1])
          and "⚠️ _Liste des liens non rafraîchie : des VA peuvent manquer._" in desc(pg[-1])
          and not marche_dit(desc(pg[-1])) and not marche_dit(desc(pgf[-1])),
          (desc(pg[-1])[-300:], desc(pgf[-1])[-300:]))
    # les deux listes périmées : sans marché, deux lignes presque identiques
    # ne diraient rien de plus — celle d'avant (VA FR) suffit, une seule fois
    cl3s = dict(cl3b, frais=False)
    t2 = desc(pd.embed_podium(cl3s, LUN_W, m(2026, 9, 24).date(), gid=IG, en_cours=True, us=us_t))
    pg2 = desc(pd.pages_subs(cl3s, S_OLD, S_OLD_FIN, {}, gid=IG, us=us_t)[-1])
    check("deux listes périmées : un seul avertissement de liste, celui d'avant (podium et quinzaine)",
          t2.count("Liste des liens non rafraîchie") == 1
          and "⚠️ _Liste des liens non rafraîchie (GetMySocial injoignable) : des comptes peuvent "
              "manquer._" in t2
          and pg2.count("Liste des liens non rafraîchie") == 1
          and "⚠️ _Liste des liens non rafraîchie : des comptes peuvent manquer._" in pg2
          and "⚠️ **Sans relevé** : VA 2, VA 3" in t2 and "⚠️ **Sans relevé** : VA 2, VA 3" in pg2,
          (t2[-500:], pg2[-500:]))

    # -- G. le coût réel d'un redémarrage (mémoire vide) quand Va IG passe avant Twitter
    installer(pd)
    a(pd, m(2026, 9, 22, 10, 0))
    a(pd, m(2026, 9, 22, 11, 30))                         # Twitter repasse, Va IG non
    pd._RELEVES.clear()                                   # redéploiement à 11h45
    a(pd, m(2026, 9, 22, 12, 0))                          # Va IG dû, Twitter non
    us_ = us_par_ig(m(2026, 9, 22, 12, 0))
    check("redémarrage, Va IG avant Twitter : DEUX relevés US (semaine et quinzaine), un appel par "
          "VA de Twitter chacun",
          len(us_) == 2 * 5 and sorted({(x["d0"], x["d1"]) for x in us_})
          == [("2026-09-16", "2026-09-22"), ("2026-09-21", "2026-09-22")], us_)

    # -- H. le jour de la coupe : tests_podium_fige.py tourne sur le code SANS
    # l'interrupteur (la coupe retire aussi _retenir et _RELEVES)
    if ancien is not None:
        coupe = TMP / "coupe"
        coupe.mkdir()
        shutil.copy(TMP / "podium_avant.py", coupe / "podium_discord.py")
        for f in ("safe_json.py", "tests_podium_fige.py"):
            shutil.copy(BOT / f, coupe / f)
        (coupe / "web_upload.py").symlink_to(BOT / "web_upload.py")
        r = subprocess.run([sys.executable, str(coupe / "tests_podium_fige.py")], cwd=str(coupe),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=600)
        fin_ = (r.stdout.strip().splitlines() or [""])[-1] if "ECHECS" not in r.stdout else r.stdout[-600:]
        check("après la coupe, tests_podium_fige.py passe toujours (rien n'y dépend du code temporaire)",
              r.returncode == 0 and re.search(r"RESULTAT : \d+ OK / 0 ECHEC", r.stdout), fin_)

except Exception as _e:
    import traceback
    check("podium US : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-1500:])
finally:
    for _k, _v in _SAUVE.items():
        setattr(pd, _k, _v)
    pd.SERVEURS[IG].clear()
    pd.SERVEURS[IG].update(_SAUVE_IG)
    pd._RELEVES.clear()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
