"""Le podium de Twitter compte les clics des liens de TRACKING (MyPuls).

Propriétaire, 06/10/2026 : « compte uniquement que les clics sur inflow »,
pour les seuls VA US. Les liens de JESSY LE RETOUR venaient de passer sur des
pages Emy, chacune avec le tracking Infloww de son VA, et il voulait nommer
les liens GetMySocial exactement comme dans Infloww (« Roucham - ( normal ) ») —
ce que le podium, qui reconnaissait les VA au nom du lien, ne supportait pas.

Ce qui est vérifié ici, sans réseau ni vrai data/ (GetMySocial, MyPuls,
Discord et l'horloge sont faux ; DATA_DIR est un dossier temporaire) :
  - un VA est reconnu à son tracking, et garde le numéro qu'il avait — même
    si son lien a été renommé avant que le podium ne voie le tracking ;
  - plusieurs liens sur un même tracking ne le comptent qu'une fois ; un
    tracking derrière les liens de deux personnes n'est donné à aucune ;
  - la semaine où un VA change de tracking garde ses clics d'avant ;
  - un MyPuls en panne, ou qui ne rend pas un tracking, n'est jamais un zéro ;
  - aucun appel d'analytics GetMySocial pour Twitter ; Va IG garde les clics
    GetMySocial de ses VA US ;
  - les messages disent ce qu'ils comptent, et ce qui manque.

Lancer depuis la racine du dépôt : python tests_podium_tracking.py
"""
from __future__ import annotations

import copy
import datetime as dt
import io
import json
import pathlib
import shutil
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

CLOCK = {"now": dt.datetime(2026, 10, 6, 12, 0)}      # un mardi

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


def page(id_, nom, *urls, status="active"):
    """Une page GetMySocial : pas d'url, le tracking est dans un bouton."""
    return {"id": id_, "display_name": nom, "type": "landing", "url": None, "status": status,
            "buttons": [{"url": u} for u in urls]}


def direct(id_, nom, url, status="active"):
    return {"id": id_, "display_name": nom, "type": "directlink", "url": url,
            "status": status, "buttons": []}


OF = "https://onlyfans.com/"
LIENS = {}
LISTE_MUETTE = set()                   # équipes dont la liste ne répond pas


def liens_du_06_10():
    """Les liens de VA tels qu'après le passage sur Emy (06/10/2026)."""
    LIENS.clear()
    LIENS[EQ_TW1] = [
        page("l1", "(Roucham) 1", OF + "emy.brw/c42", "https://mym.fans/emy"),
        page("l2", "(Roucham) 2", OF + "Emy.Brw/c42/"),          # même tracking
        page("l3", "(Roucham) 1SPAM", OF + "emy.brw/c43"),
        direct("l4", "Laboule ( X )", OF + "jessyewdiference/c126"),
        direct("l5", "Micky", OF + "jessyewdiference/c126", status="inactive"),
        direct("l14", "(PAMPAM) 1", OF + "jessyewdiference/c96", status="inactive"),
        page("l6", "tsiry 1", OF + "emy.brw/c37"),
        page("l7", "tsiry 2", OF + "emy.brw/c37"),
        page("l8", "(Ricardo) 1", OF + "emy.brw/c44"),
        page("l9", "(VA 7 Rahtouk)", OF + "emy.brw/c19"),
        page("l10", "TWITTER", OF + "emy.brw"),                  # sans tracking
        page("l11", "TEMPLATE ibenhaastrup", OF + "emy.brw/c99"),  # gabarit
        page("l12", "(DOLAD) 1", OF + "emy.brw/c55"),            # pas encore dans MyPuls
    ]
    LIENS[EQ_TW2] = [direct("l13", "Twitter VA 31 @abdoul_9684", OF + "emy.brw/c6")]
    LIENS[EQ_FR] = [direct("f3", "Amelia VA 3 @seven", OF + "amelia.mrn/c3")]


ANALYTICS = []                         # chaque appel d'analytics GetMySocial


def _analytics(ids, d0, d1):
    ANALYTICS.append((tuple(ids), d0, d1))
    return 10, {"FR": 6, "US": 3}


_faux_gms = types.ModuleType("gms")
_faux_gms.analytics_for_links = _analytics
_faux_gms.list_links_team = lambda team, force_refresh=False: (
    {"ok": False, "error": "muet"} if team in LISTE_MUETTE
    else {"ok": True, "links": copy.deepcopy(LIENS.get(team, []))})
_faux_gms.pause_restante = lambda: 0
sys.modules["gms"] = _faux_gms

# ------------------------------------------------------- faux MyPuls -------
NOMS_BASE = {
    "emy.brw/c42": "Roucham - ( normal )", "emy.brw/c43": "Roucham - ( spam )",
    "jessyewdiference/c126": "Laboule ( X )", "emy.brw/c37": "Tsiry - ( normal )",
    "emy.brw/c44": "Ricrado  - ( normal )", "emy.brw/c19": "Rahtouk - ( normal )",
    "emy.brw/c6": "Twitter VA 31 @abdoul_9684", "jessyewdiference/c88": "Roucham",
    "emy.brw/c99": "TEMPLATE", "amelia.mrn/c3": "Amelia VA 3",
    "jessyewdiference/c96": "Pampam", "jessyewdiference/c92": "Ricardo",
}
NOMS_MP = {}                           # le nom de chaque tracking que MyPuls connaît
VISITES = {}                           # tracking → {jour iso: visites}
MP = {"panne": False, "tronque": False, "decale": False, "sans_emy": 0, "appels": []}


def _mp_api_get(path, params=None, _essai=0):
    params = dict(params or {})
    MP["appels"].append((path, params.get("from"), params.get("to")))
    if MP["panne"]:
        return {"ok": False, "error": "Connexion API impossible"}
    du, au = params["from"], params["to"]
    sans_emy = MP["sans_emy"] > 0          # une clé qui ne voit pas emy.brw
    MP["sans_emy"] = max(0, MP["sans_emy"] - 1)
    items = []
    for t, nom in NOMS_MP.items():
        pseudo, code = t.split("/")
        if sans_emy and pseudo == "emy.brw":
            continue
        jours = VISITES.get(t, {})
        items.append({"creator_id": 1, "code": code, "name": nom,
                      "url": f"https://onlyfans.com/{pseudo}/{code}", "active": True,
                      # la période, et le compteur depuis la création jusqu'à `au`
                      "visits_period": sum(v for j, v in jours.items() if du <= j <= au),
                      "visits_total": sum(v for j, v in jours.items() if j <= au),
                      "subscribers_period": 0, "subscribers_total": 0, "new_subscribers": 0,
                      "revenue": {"total": 0}, "group_ids": []})
    debut = (dt.date.fromisoformat(du) + dt.timedelta(days=1)).isoformat() if MP["decale"] else du
    return {"ok": True, "data": {
        "period": {"from": debut + "T00:00:00+02:00", "to": au + "T23:59:59+02:00"},
        "currency": "USD", "count": len(items) + (5 if MP["tronque"] else 0), "data": items}}


_faux_mypuls = types.ModuleType("mypuls")
_faux_mypuls.api_get = _mp_api_get
sys.modules["mypuls"] = _faux_mypuls

import podium_discord as pd            # noqa: E402
import safe_json                       # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, IG = pd.TWITTER_ID, pd.VA_IG_ID
NUMEROS = {"Roucham": 12, "Roucham SPAM": 24, "X": 34, "Micky": 40, "tsiry 1": 43,
           "tsiry 2": 44, "Ricardo": 22, "DOLAD": 16, "abdoul_9684": 31, "TWITTER": 26,
           "PAMPAM": 20}


class FauxDiscord:
    def __init__(self):
        self.appels, self.n = [], 0

    def api(self, methode, chemin, **kw):
        self.appels.append({"m": methode, "p": chemin, "json": copy.deepcopy(kw.get("json"))})
        if methode == "POST":
            self.n += 1
            return 200, {"id": f"M{self.n}"}
        return 200, {"id": chemin.rstrip("/").split("/")[-1]}


DISCORD = FauxDiscord()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="podium_tracking_test_"))
_SAUVE = {k: getattr(pd, k) for k in (
    "DATA_DIR", "ETAT_FICHIER", "CONFIG_FICHIER", "NUMEROS_FICHIER", "LIENS_CACHE",
    "ALLTIME_FICHIER", "_maintenant", "_aujourdhui", "_api", "_salon", "_pause_gms", "time")}
PAUSE = {"on": False}
_NB = [0]


def installer():
    """Un bac neuf : dossier, horloge, Discord, faux services remis à zéro."""
    global DISCORD
    _NB[0] += 1
    d = TMP / f"bac{_NB[0]}"
    d.mkdir()
    safe_json.write_text(d / "podium_numeros.json", json.dumps(NUMEROS))
    pd.DATA_DIR = d
    pd.ETAT_FICHIER = d / "podium.json"
    pd.CONFIG_FICHIER = d / "podium_config.json"
    pd.NUMEROS_FICHIER = d / "podium_numeros.json"
    pd.LIENS_CACHE = d / "gmsdash_links.json"
    pd.ALLTIME_FICHIER = d / "podium_alltime.json"
    CLOCK["now"] = dt.datetime(2026, 10, 6, 12, 0)
    pd._maintenant = lambda: CLOCK["now"]
    pd._aujourdhui = lambda: CLOCK["now"].date()
    pd.time = types.SimpleNamespace(time=lambda: CLOCK["now"].timestamp(), sleep=lambda s: None)
    pd._pause_gms = lambda: PAUSE["on"]
    pd._salon = lambda gid, voulu="": f"{gid}-{'subs' if 'subs' in (voulu or '') else 'bonus' if 'bonus' in (voulu or '') else 'podium'}"
    DISCORD = FauxDiscord()
    pd._api = lambda methode, chemin, **kw: DISCORD.api(methode, chemin, **kw)
    pd._RELEVES.clear()
    pd._RELEVES_LUS = False
    pd._MP_LUS.clear()
    ANALYTICS.clear()
    MP.update(panne=False, tronque=False, decale=False, sans_emy=0)
    MP["appels"].clear()
    VISITES.clear()
    NOMS_MP.clear()
    NOMS_MP.update(NOMS_BASE)
    LISTE_MUETTE.clear()
    PAUSE["on"] = False
    _PRIMES.clear()
    liens_du_06_10()
    return d


def frais():
    """Le prochain relevé relit MyPuls (le cache de 90 s ne sert qu'à un passage)."""
    pd._MP_LUS.clear()


def registre():
    return (safe_json.load(pd._fichier_trackings(), default={}) or {}).get("trackings") or {}


def attente():
    return (safe_json.load(pd._fichier_trackings(), default={}) or {}).get("attente") or {}


def table():
    return safe_json.load(pd.NUMEROS_FICHIER, default={}) or {}


def par_va(cl):
    return {x["va"]: x["clics"] for x in cl["lignes"]}


LUN, MAR = dt.date(2026, 10, 5), dt.date(2026, 10, 6)

try:
    # ------------------------------------------------------------------ 0
    print("\n— 0. lire un tracking, lire un nom")
    check("Twitter compte les clics des trackings (clé « mesure »), Va IG ceux de GetMySocial",
          pd._source(TW) == "tracking" and pd._source(IG) == "gms"
          and pd._source(TW, "gms") == "gms")
    check("url de tracking : créatrice et code, en minuscules, zéros de tête ôtés",
          pd.tracking_de("https://OnlyFans.com/Emy.Brw/C042/?a=1") == "emy.brw/c42"
          and pd.tracking_de("onlyfans.com/jessyewdiference/c126#x") == "jessyewdiference/c126")
    check("la page de la créatrice seule, ou un autre site, n'est pas un tracking",
          pd.tracking_de("https://onlyfans.com/emy.brw") == ""
          and pd.tracking_de("https://mym.fans/emy/c12") == ""
          and pd.tracking_de("https://onlyfans.com/emy.brw/c12x") == "")
    check("les trackings d'une page sont dans ses boutons, une seule fois chacun",
          pd.trackings_du_lien(page("p", "x", OF + "a/c1", OF + "A/c01/", "https://mym.fans/a"))
          == ["a/c1"])
    check("un bouton qui se dit éteint n'envoie personne",
          pd.trackings_du_lien({"buttons": [{"url": OF + "a/c1", "enabled": False}]}) == [])
    check("nom Infloww : la personne avant les parenthèses, spam à part, variantes tapées à la main",
          pd.personne("Roucham - ( normal )") == ("Roucham", False)
          and pd.personne("Gaspacho  - ( Spam )") == ("Gaspacho", True)
          and pd.personne("Kanto - (normal) 2") == ("Kanto", False)
          and pd.personne("(Roucham) - ( spam )") == ("Roucham", True)
          and pd.personne("Twitter VA 31 @abdoul_9684 - ( normal )") == ("abdoul_9684", False)
          and pd.personne("( BO7 ) 1") == ("BO7", False))
    check("deux téléphones d'une personne, pas deux personnes",
          pd._meme_personne("tsiry 1", "tsiry 2") and pd._meme_personne("tsiry 1 SPAM", "tsiry 2 SPAM")
          and not pd._meme_personne("VA 1 Noum", "VA 2 Noum")
          and not pd._meme_personne("X", "Micky"))
    check("un renommage à moitié fait reste une personne (« VA 2 Narovana » / « Narovana »)",
          pd._meme_personne("VA 2 Narovana", "Narovana") and len(pd._personnes(
              ["VA 2 Narovana", "Narovana", "Kanto"])) == 2)
    check("un nom proche d'un ancien (faute de frappe) : « Ricrado » / « Ricardo »",
          pd._proche("Ricrado", ["Ricardo"]) and pd._proche("Niavo", ["VA 1 Niavo"])
          and not pd._proche("Newguy", ["Roucham", "VA 12"]))

    # ------------------------------------------------------------------ 1
    print("\n— 1. premier relevé : chacun garde son numéro")
    installer()
    VISITES.update({
        "emy.brw/c42": {"2026-10-05": 30, "2026-10-06": 12},
        "emy.brw/c43": {"2026-10-06": 4},
        "jessyewdiference/c126": {"2026-10-05": 7, "2026-10-06": 2},
        "emy.brw/c37": {"2026-10-06": 5},
        "emy.brw/c44": {"2026-10-06": 9},
        "emy.brw/c19": {"2026-10-06": 1},
        "emy.brw/c6": {"2026-10-06": 3},
        "emy.brw/c99": {"2026-10-06": 500},
        "jessyewdiference/c96": {"2026-10-06": 70},
    })
    cl = pd.classement(LUN, MAR, gid=TW)
    v = par_va(cl)
    reg = registre()
    check("le VA garde le numéro du nom de ses liens (« (Roucham) 1 » → VA 12)",
          reg["emy.brw/c42"]["numero"] == 12 and v.get("VA 12") == 42, (reg.get("emy.brw/c42"), v))
    check("deux liens sur un même tracking ne le comptent qu'une fois", v.get("VA 12") == 42)
    check("le lien SPAM reste un VA à part", v.get("VA 24") == 4)
    check("un tracking dont le seul lien actif est celui de X va à X (Micky est désactivé)",
          reg["jessyewdiference/c126"]["numero"] == 34 and v.get("VA 34") == 9)
    check("un lien désactivé ne compte pas (PAMPAM) : son tracking n'est même pas suivi",
          "VA 20" not in v and "jessyewdiference/c96" not in reg)
    check("deux téléphones d'une même personne, deux numéros : le plus petit (tsiry 1 et 2)",
          reg["emy.brw/c37"]["numero"] == 43 and v.get("VA 43") == 5 and "VA 44" not in v)
    check("tracking au nom mal orthographié (« Ricrado ») : le numéro du lien (Ricardo, 22)",
          reg["emy.brw/c44"]["numero"] == 22 and v.get("VA 22") == 9)
    check("… et son nom Infloww devient un alias de ce numéro",
          table().get("Ricrado") == 22 and table().get("Tsiry") == 43, table())
    check("un VA inconnu prend un numéro neuf, comme avant",
          reg["emy.brw/c19"]["numero"] == 1 and v.get("VA 1") == 1 and table().get("Rahtouk") == 1)
    check("… et le nom de son lien aussi : Va IG (qui lit les noms) lui donne le même",
          table().get("VA 7 Rahtouk") == 1)
    check("un lien EMY TWITTER (« Twitter VA 31 @… ») garde aussi son numéro", v.get("VA 31") == 3)
    check("un gabarit n'est personne (ni numéro, ni clics)",
          "emy.brw/c99" not in reg and all(x["clics"] != 500 for x in cl["lignes"]))
    check("un lien sans tracking n'est pas compté, mais il est dit",
          cl["sans_tracking"] == ["TWITTER"])
    check("un tracking que MyPuls ne connaît pas encore attend, il n'est pas gravé",
          "emy.brw/c55" not in reg and "emy.brw/c55" in attente())
    check("… et son VA probable passe sans relevé (jamais un zéro qu'on paierait)",
          "VA 16" in cl["illisibles"] and "VA 16" not in v)
    check("AUCUN appel d'analytics GetMySocial pour Twitter", ANALYTICS == [], ANALYTICS)
    check("une seule lecture MyPuls pour toute la période", len(MP["appels"]) == 1, MP["appels"])
    check("le relevé des trackings n'est pas gardé pour Va IG (il mêle des clics GetMySocial)",
          not pd._RELEVES)

    # MyPuls apprend le tracking : il prend son numéro, avec ses clics de la période
    NOMS_MP["emy.brw/c55"] = "Donald - ( normal )"
    VISITES["emy.brw/c55"] = {"2026-10-06": 8}
    frais()
    cl1b = pd.classement(LUN, MAR, gid=TW)
    check("dès que MyPuls le connaît : gravé au numéro de son lien, clics de la période compris",
          registre()["emy.brw/c55"]["numero"] == 16 and par_va(cl1b).get("VA 16") == 8
          and "VA 16" not in cl1b["illisibles"] and "emy.brw/c55" not in attente())

    # ------------------------------------------------------------------ 2
    print("\n— 2. renommer les liens comme dans Infloww ne change rien")
    noms_infloww = {"l1": "Roucham - ( normal )", "l2": "Roucham - ( normal )",
                    "l3": "Roucham - ( spam )", "l8": "Ricrado - ( normal )",
                    "l6": "Tsiry - ( normal )", "l7": "Tsiry - ( normal )",
                    "l9": "Rahtouk - ( normal )"}
    for l in LIENS[EQ_TW1]:
        l["display_name"] = noms_infloww.get(l["id"], l["display_name"])
    avant_num = dict(table())
    frais()
    cl2 = pd.classement(LUN, MAR, gid=TW)
    check("mêmes numéros, mêmes clics après le renommage", par_va(cl2) == par_va(cl1b),
          (par_va(cl2), par_va(cl1b)))
    check("le renommage n'a créé aucun numéro", table() == avant_num,
          set(table()) ^ set(avant_num))
    check("le relevé GetMySocial que garde Va IG les reconnaît aussi (alias)",
          sorted({pd.numeros([pd.cle_entite(*pd.personne(n))], attribuer=False)
                  .get(pd.cle_entite(*pd.personne(n))) for n in noms_infloww.values()})
          == [1, 12, 22, 24, 43])

    # ------------------------------------------------------------------ 3
    print("\n— 3. la semaine du changement de tracking garde ses clics d'avant")
    installer()
    # lundi soir : Roucham est encore en lien direct sur son tracking Jessye
    CLOCK["now"] = dt.datetime(2026, 10, 5, 23, 0)
    LIENS[EQ_TW1][0] = direct("l1", "(Roucham) 1", OF + "jessyewdiference/c88")
    VISITES.update({"jessyewdiference/c88": {"2026-10-05": 200, "2026-10-06": 50,
                                             "2026-10-07": 80},
                    "emy.brw/c42": {"2026-10-06": 15}})
    pd.classement(LUN, LUN, gid=TW)
    check("le tracking Jessye est connu, au VA 12, avec son lien",
          registre()["jessyewdiference/c88"]["numero"] == 12
          and "l1" in registre()["jessyewdiference/c88"]["ids"])
    # mardi : la page Emy a pris sa place
    CLOCK["now"] = dt.datetime(2026, 10, 6, 12, 0)
    liens_du_06_10()
    frais()
    cl3 = pd.classement(LUN, MAR, gid=TW)
    reg3 = registre()
    check("l'ancien tracking n'est plus actif, il compte jusqu'au jour où on l'a vu partir",
          reg3["jessyewdiference/c88"]["actif"] is False
          and reg3["jessyewdiference/c88"]["vu"] == "2026-10-06")
    check("la semaine compte l'ancien tracking (200 + 50) et le nouveau (15)",
          par_va(cl3).get("VA 12") == 265, par_va(cl3))
    CLOCK["now"] = dt.datetime(2026, 10, 7, 12, 0)
    frais()
    cl3b = pd.classement(LUN, dt.date(2026, 10, 7), gid=TW)
    check("le lendemain, le trafic venu d'ailleurs sur l'ancien tracking ne compte pas",
          par_va(cl3b).get("VA 12") == 265, par_va(cl3b))
    check("deux lectures MyPuls : la semaine, et l'ancien tracking jusqu'au jour du départ",
          sorted({(a, b) for _, a, b in MP["appels"][-2:]})
          == [("2026-10-05", "2026-10-06"), ("2026-10-05", "2026-10-07")], MP["appels"][-3:])

    # renommé AVANT que le podium ne voie le nouveau tracking : le lien le dit
    installer()
    CLOCK["now"] = dt.datetime(2026, 10, 5, 23, 0)
    LIENS[EQ_TW1][8] = direct("l8", "(Ricardo) 1", OF + "jessyewdiference/c92")
    pd.classement(LUN, LUN, gid=TW)
    CLOCK["now"] = dt.datetime(2026, 10, 6, 12, 0)
    liens_du_06_10()
    LIENS[EQ_TW1][8]["display_name"] = "Ricrado - ( normal )"
    NOMS_MP["emy.brw/c44"] = "Ricardo VA - ( normal )"      # aucun nom connu
    VISITES["emy.brw/c44"] = {"2026-10-06": 9}
    frais()
    cl3c = pd.classement(LUN, MAR, gid=TW)
    check("lien renommé avant la première lecture : le numéro suit le LIEN (ancien tracking)",
          registre()["emy.brw/c44"]["numero"] == 22 and par_va(cl3c).get("VA 22") == 9,
          registre().get("emy.brw/c44"))

    # une page avec les deux boutons, normal et spam
    installer()
    LIENS[EQ_TW1][0] = page("l1", "(Roucham) 1", OF + "emy.brw/c42", OF + "emy.brw/c43")
    LIENS[EQ_TW1][2]["status"] = "inactive"
    VISITES.update({"emy.brw/c42": {"2026-10-06": 30}, "emy.brw/c43": {"2026-10-06": 8}})
    cl3d = pd.classement(LUN, MAR, gid=TW)
    check("une page aux deux boutons : le bouton spam va au VA SPAM, pas au VA normal",
          registre()["emy.brw/c43"]["numero"] == 24 and par_va(cl3d).get("VA 24") == 8
          and par_va(cl3d).get("VA 12") == 30, par_va(cl3d))

    # ------------------------------------------------------------------ 4
    print("\n— 4. un tracking partagé par deux personnes n'est donné à personne")
    installer()
    LIENS[EQ_TW1][4]["status"] = "active"                  # Micky, sur c126 avec X
    VISITES["jessyewdiference/c126"] = {"2026-10-06": 90}
    cl4 = pd.classement(LUN, MAR, gid=TW)
    check("c126 derrière X et Micky : pas gravé, en conflit",
          "jessyewdiference/c126" not in registre()
          and attente()["jessyewdiference/c126"]["numeros"] == [34, 40]
          and attente()["jessyewdiference/c126"]["conflit"] is True, attente())
    e4 = pd.embed_podium(cl4, LUN, MAR, en_cours=True, gid=TW)
    check("… le message dit qu'un tracking est partagé, à corriger",
          "1 tracking partagé entre plusieurs VA" in e4["description"], e4["description"][-400:])
    check("… X et Micky passent sans relevé, personne ne touche les clics de l'autre",
          {"VA 34", "VA 40"} <= set(cl4["illisibles"]) and "VA 34" not in par_va(cl4))
    LIENS[EQ_TW1][4]["status"] = "inactive"
    frais()
    cl4b = pd.classement(LUN, MAR, gid=TW)
    check("Micky désactivé : le conflit se lève, c126 va à X",
          registre()["jessyewdiference/c126"]["numero"] == 34 and par_va(cl4b).get("VA 34") == 90
          and "jessyewdiference/c126" not in attente())

    # déjà gravé, puis un lien d'une autre personne s'y ajoute : en doute
    LIENS[EQ_TW1].append(page("l30", "(Carter) 1", OF + "jessyewdiference/c126"))
    NUMEROS_CARTER = dict(table(), Carter=38)
    safe_json.write_text(pd.NUMEROS_FICHIER, json.dumps(NUMEROS_CARTER))
    frais()
    cl4c = pd.classement(LUN, MAR, gid=TW)
    check("un tracking gravé qui passe derrière le lien d'un autre : ses VA sans relevé",
          {"VA 34", "VA 38"} <= set(cl4c["illisibles"]) and "VA 34" not in par_va(cl4c)
          and registre()["jessyewdiference/c126"]["numero"] == 34
          and cl4c["conflits"] == ["jessyewdiference/c126"], (cl4c["illisibles"], cl4c["conflits"]))
    LIENS[EQ_TW1][-1]["display_name"] = "Newguy"          # une personne sans numéro
    frais()
    cl4d = pd.classement(LUN, MAR, gid=TW)
    check("… même quand l'autre n'a pas encore de numéro",
          "VA 34" in cl4d["illisibles"] and cl4d["conflits"] == ["jessyewdiference/c126"])
    LIENS[EQ_TW1].pop()
    frais()
    cl4e = pd.classement(LUN, MAR, gid=TW)
    check("… et quand le lien de trop s'en va, tout redevient lisible",
          "VA 34" not in cl4e["illisibles"] and cl4e["conflits"] == []
          and "doute" not in registre()["jessyewdiference/c126"])

    # un tracking neuf derrière un VA connu ET un VA inconnu
    installer()
    LIENS[EQ_TW1].append(page("l31", "Newguy", OF + "emy.brw/c42"))
    VISITES["emy.brw/c42"] = {"2026-10-06": 40}
    cl4f = pd.classement(LUN, MAR, gid=TW)
    check("tracking neuf derrière « (Roucham) 1 » et « Newguy » : à personne, VA 12 sans relevé",
          "emy.brw/c42" not in registre() and "VA 12" in cl4f["illisibles"]
          and "VA 12" not in par_va(cl4f))

    # un lien repris par quelqu'un d'autre, qui passe sur un tracking neuf
    installer()
    CLOCK["now"] = dt.datetime(2026, 10, 5, 23, 0)
    LIENS[EQ_TW1][0] = direct("l1", "(Roucham) 1", OF + "jessyewdiference/c88")
    LIENS[EQ_TW1][1]["status"] = "inactive"
    pd.classement(LUN, LUN, gid=TW)
    CLOCK["now"] = dt.datetime(2026, 10, 6, 12, 0)
    LIENS[EQ_TW1][0] = page("l1", "Newguy - ( normal )", OF + "emy.brw/c500")
    NOMS_MP["emy.brw/c500"] = "Newguy - ( normal )"
    VISITES["emy.brw/c500"] = {"2026-10-06": 25}
    frais()
    cl4g = pd.classement(LUN, MAR, gid=TW)
    check("lien repris par un VA neuf : il n'hérite pas du numéro de Roucham",
          "emy.brw/c500" not in registre()
          and "repris" in attente()["emy.brw/c500"]["pourquoi"], attente().get("emy.brw/c500"))
    check("… et l'ancien VA passe sans relevé tant que ce n'est pas tranché",
          "VA 12" in cl4g["illisibles"])

    # un libellé MyPuls qui n'est pas un nom de VA ne départage rien
    installer()
    LIENS[EQ_TW1].append(page("l32", "(Brandnew) 1", OF + "emy.brw/c4"))
    NOMS_MP["emy.brw/c4"] = "Twitter"
    VISITES["emy.brw/c4"] = {"2026-10-06": 6}
    pd.classement(LUN, MAR, gid=TW)
    check("MyPuls nomme un tracking « Twitter » : pas le VA « TWITTER » (26), un numéro neuf",
          registre()["emy.brw/c4"]["numero"] not in (26, None), registre().get("emy.brw/c4"))

    # un tracking vu après la période ne la trouble pas
    installer()
    cl_av = pd.classement(dt.date(2026, 9, 28), dt.date(2026, 10, 4), gid=TW)
    check("la semaine d'avant : le tracking en attente depuis aujourd'hui ne la trouble pas",
          "VA 16" not in cl_av["illisibles"], cl_av["illisibles"])

    # ------------------------------------------------------------------ 5
    print("\n— 5. une lecture MyPuls ratée n'est jamais un zéro")
    for cas, reglage in (("en panne", "panne"), ("tronqué", "tronque"), ("décalé", "decale")):
        installer()
        VISITES["emy.brw/c42"] = {"2026-10-06": 12}
        pd.classement(LUN, MAR, gid=TW)             # le registre se remplit
        reg_avant = registre()
        frais()
        MP[reglage] = True
        clp = pd.classement(LUN, MAR, gid=TW)
        check(f"MyPuls {cas} : aucun relevé (rien à afficher, rien à payer)",
              clp["lignes"] == [] and clp["illisibles"] == [] and clp["erreur"], clp)
        check(f"MyPuls {cas} : le registre n'a pas bougé", registre() == reg_avant)
    installer()
    VISITES["emy.brw/c42"] = {"2026-10-06": 12}
    check("message vivant posté", pd.rafraichir(TW) == "M1")
    n_appels = len(DISCORD.appels)
    frais()
    MP["panne"] = True
    CLOCK["now"] += dt.timedelta(hours=2)
    pd.rafraichir(TW)
    check("MyPuls en panne : le message vivant n'est pas remplacé par du vide",
          len(DISCORD.appels) == n_appels, DISCORD.appels[n_appels:])
    MP["panne"] = False

    # une clé MyPuls qui ne voit pas emy.brw
    installer()
    VISITES.update({"emy.brw/c42": {"2026-10-06": 12}, "jessyewdiference/c126": {"2026-10-06": 4}})
    pd.classement(LUN, MAR, gid=TW)
    frais()
    MP["sans_emy"] = 1
    clk = pd.classement(LUN, MAR, gid=TW)
    check("un tracking déjà rendu qui manque : relu une fois (l'autre clé le voit)",
          par_va(clk).get("VA 12") == 12, (par_va(clk), clk["illisibles"]))
    frais()
    MP["sans_emy"] = 9
    clk2 = pd.classement(LUN, MAR, gid=TW)
    check("toujours absent : son VA passe sans relevé, pas à zéro",
          "VA 12" in clk2["illisibles"] and "VA 12" not in par_va(clk2)
          and par_va(clk2).get("VA 34") == 4, (par_va(clk2), clk2["illisibles"]))
    MP["sans_emy"] = 0

    # un lien vers un tracking que MyPuls n'a jamais rendu, bien après l'attente
    installer()
    NOMS_MP["emy.brw/c55"] = "Donald - ( normal )"
    LIENS[EQ_TW1].append(page("l20", "(Ricardo) 3", OF + "emy.brw/c777"))
    VISITES["emy.brw/c44"] = {"2026-10-06": 9}
    pd.classement(LUN, MAR, gid=TW)
    check("dans l'attente, le VA passe sans relevé", "emy.brw/c777" in attente())
    CLOCK["now"] = dt.datetime(2026, 10, 9, 12, 0)
    frais()
    cl5 = pd.classement(LUN, dt.date(2026, 10, 9), gid=TW)
    check("au-delà de l'attente : gravé à son lien, compté zéro, et dit « à vérifier »",
          registre()["emy.brw/c777"]["numero"] == 22 and par_va(cl5).get("VA 22") == 9
          and cl5["introuvables"] == ["emy.brw/c777"], (par_va(cl5), cl5["illisibles"]))
    e = pd.embed_podium(cl5, LUN, dt.date(2026, 10, 9), en_cours=True, gid=TW)
    check("… et le message le dit", "1 tracking introuvable dans MyPuls" in e["description"])

    # ------------------------------------------------------------------ 6
    print("\n— 6. GetMySocial muet ou en pause : on compte les trackings connus")
    installer()
    VISITES["emy.brw/c42"] = {"2026-10-06": 12}
    pd.classement(LUN, MAR, gid=TW)
    reg_avant = registre()
    frais()
    LISTE_MUETTE.add(EQ_TW1)
    LIENS[EQ_TW1].append(page("l20", "(Nouveau) 1", OF + "emy.brw/c70"))
    clm = pd.classement(LUN, MAR, gid=TW)
    check("liste muette : les trackings connus comptent quand même",
          par_va(clm).get("VA 12") == 12)
    check("… aucun tracking neuf, aucun numéro neuf, registre intact",
          registre() == reg_avant and "Nouveau" not in table())
    check("… liste lue il y a moins d'un jour : pas d'alarme", clm["frais"] is True)
    CLOCK["now"] = dt.datetime(2026, 10, 7, 13, 0)
    frais()
    clm2 = pd.classement(LUN, dt.date(2026, 10, 7), gid=TW)
    e = pd.embed_podium(clm2, LUN, dt.date(2026, 10, 7), en_cours=True, gid=TW)
    check("liste muette depuis plus d'un jour : le message dit qu'elle n'est pas fraîche",
          clm2["frais"] is False and "non rafraîchie" in e["description"])
    installer()
    PAUSE["on"] = True
    check("pause de GetMySocial : Twitter ne s'arrête pas (le bonus du jour est payé)",
          pd.a_rafraichir(TW) and pd.a_rafraichir_bonus(TW) and not pd._pause_pour(TW))
    check("… Va IG, lui, attend comme avant", pd._pause_pour(IG) and not pd.a_rafraichir(IG))
    PAUSE["on"] = False

    # ------------------------------------------------------------------ 7
    print("\n— 7. les messages disent ce qu'ils comptent")
    installer()
    VISITES.update({"emy.brw/c42": {"2026-10-06": 12}, "emy.brw/c6": {"2026-10-06": 3}})
    LIENS[EQ_TW1].append(page("l21", "Quelqu un", OF + "emy.brw/c71"))   # VA neuf, pas dans MyPuls
    cl7 = pd.classement(LUN, MAR, gid=TW)
    e = pd.embed_podium(cl7, LUN, MAR, en_cours=True, gid=TW)
    check("podium Twitter : « clics tracking OF », plus « clics US »",
          "clics **tracking OF**" in e["description"] and "clics **US**" not in e["description"])
    check("podium : lien sans tracking et tracking neuf en attente dits, en nombre seulement",
          "1 lien sans tracking OnlyFans" in e["description"]
          and "1 tracking neuf pas encore dans MyPuls" in e["description"]
          and "Quelqu" not in e["description"], e["description"][-500:])
    pages = pd.pages_subs(cl7, LUN, MAR, {}, gid=TW)
    check("classement subs : « Clics tracking OF »", "Clics **tracking OF**" in pages[0]["description"])
    frais()
    b = pd.embed_bonus(pd.classement(MAR, MAR, gid=TW), MAR, gid=TW)
    check("bonus du jour : « clics tracking OF »", "clics **tracking OF**" in b["description"])
    check("Va IG garde « clics FR »",
          "clics **FR**" in pd.embed_podium({"lignes": [], "illisibles": [], "frais": True},
                                            LUN, MAR, en_cours=True, gid=IG)["description"])
    check("un relevé manquant nomme MyPuls sur Twitter, GetMySocial sur Va IG",
          "MyPuls n'a pas rendu" in pd._avert_dernier_releve({}, "la semaine", TW)
          and "GetMySocial n'a pas rendu" in pd._avert_dernier_releve({}, "la semaine", IG))

    # ------------------------------------------------------------------ 8
    print("\n— 8. le total « depuis toujours » : le compteur de chaque tracking")
    installer()
    NOMS_MP["emy.brw/c55"] = "Donald - ( normal )"
    VISITES.update({"emy.brw/c42": {"2025-03-01": 1000, "2026-10-06": 12}})
    safe_json.write_text(pd.ALLTIME_FICHIER, json.dumps(
        {"jour": "2026-10-06", "totaux": {"VA 12": 7114, "VA 99": 5}}))
    check("le total GetMySocial des VA US reste à part (Va IG l'affiche encore)",
          pd._alltime_lu(TW) == {} and pd._alltime_lu(TW, "gms").get("VA 12") == 7114)
    at = pd.alltime(TW)
    check("total depuis toujours = compteur MyPuls du tracking",
          at.get("VA 12") == 1012 and "VA 99" not in at, at)
    lu = safe_json.load(pd.DATA_DIR / "podium_alltime_tracking.json", default={})
    check("dans son propre fichier, gravé pour la journée", lu.get("jour") == "2026-10-06"
          and safe_json.load(pd.ALLTIME_FICHIER, default={})["totaux"]["VA 12"] == 7114)
    n = len(MP["appels"])
    pd.alltime(TW)
    check("une fois par jour seulement", len(MP["appels"]) == n)
    check("_alltime_lu relit le nouveau total", pd._alltime_lu(TW).get("VA 12") == 1012)

    # ------------------------------------------------------------------ 9
    print("\n— 9. les vrais passages : message vivant, bonus, quinzaine, Va IG")
    installer()
    VISITES.update({"emy.brw/c42": {"2026-10-05": 30, "2026-10-06": 12},
                    "emy.brw/c6": {"2026-10-06": 3}})
    check("message vivant de Twitter posté", pd.rafraichir(TW) == "M1")
    post = [x for x in DISCORD.appels if x["m"] == "POST"][-1]["json"]["embeds"][0]
    check("… avec les clics des trackings", "**VA 12** — **42** subs" in post["description"],
          post["description"][:600])
    check("bonus du jour posté", bool(pd.rafraichir_bonus(TW)))
    check("classement de la quinzaine posté", bool(pd.rafraichir_subs(TW, forcer=True)))
    check("Twitter n'a fait aucun appel d'analytics GetMySocial", ANALYTICS == [], ANALYTICS)
    us = pd._releve_us(LUN, MAR)
    check("Va IG relève ses VA US en clics GetMySocial (les clics US des liens)",
          us is not None and par_va(us).get("VA 12") == 3 and ANALYTICS, par_va(us or {}))
    check("… et le garde : le passage suivant ne refait pas d'appel",
          (lambda n: pd._releve_us(LUN, MAR) is not None and len(ANALYTICS) == n)(len(ANALYTICS)))
    check("aucune prime payée sur un passage vivant", _PRIMES == [])

    # ------------------------------------------------------------------ 10
    print("\n— 10. le podium du lundi ne paie pas sur un relevé troué")
    installer()
    NOMS_MP["emy.brw/c55"] = "Donald - ( normal )"
    LIENS[EQ_TW1][4]["status"] = "active"                  # Micky sur c126, avec X
    VISITES.update({"emy.brw/c42": {"2026-10-06": 40}, "jessyewdiference/c126": {"2026-10-06": 90},
                    "emy.brw/c44": {"2026-10-07": 30}})
    pd.classement(LUN, MAR, gid=TW)
    CLOCK["now"] = dt.datetime(2026, 10, 12, 9, 5)
    frais()
    mid = pd.poster_podium(TW, jour=dt.date(2026, 10, 12))
    fg = pd._etat()["figes"][TW]["2026-10-05"]
    check("podium posté (il dit « à confirmer »), mais AUCUNE prime annoncée",
          bool(mid) and _PRIMES == [] and fg.get("primes_attente"), (mid, _PRIMES, fg))
    LIENS[EQ_TW1][4]["status"] = "inactive"
    CLOCK["now"] = dt.datetime(2026, 10, 12, 9, 35)
    frais()
    pd.poster_podium(TW, jour=dt.date(2026, 10, 12))
    check("relu au plus une fois l'heure", _PRIMES == [])
    CLOCK["now"] = dt.datetime(2026, 10, 12, 10, 10)
    frais()
    pd.poster_podium(TW, jour=dt.date(2026, 10, 12))
    fg = pd._etat()["figes"][TW]["2026-10-05"]
    paye = [x["va"] for x in (_PRIMES[-1][2]["lignes"] if _PRIMES else [])][:3]
    check("relevé complet : primes annoncées sur le podium corrigé, X compris",
          _PRIMES and paye[0] == "VA 34" and not fg.get("primes_attente") and fg.get("complet"),
          (paye, fg))

    # ------------------------------------------------------------------ 10b
    print("\n— 10b. MyPuls se met à jour par paliers : la veille complétée le matin")
    installer()
    NOMS_MP["emy.brw/c55"] = "Donald - ( normal )"
    VISITES["emy.brw/c42"] = {"2026-10-06": 10}
    CLOCK["now"] = dt.datetime(2026, 10, 6, 23, 30)
    m1 = pd.rafraichir_bonus(TW)
    CLOCK["now"] = dt.datetime(2026, 10, 7, 8, 0)
    frais()
    m2 = pd.rafraichir_bonus(TW)
    check("un message neuf pour le nouveau jour, celui d'hier gardé pour être complété",
          m2 != m1 and pd._etat()["bonus_veille"][TW] == {"jour": "2026-10-06", "message": m1})
    VISITES["emy.brw/c42"]["2026-10-06"] = 31            # le palier de MyPuls est arrivé
    CLOCK["now"] = dt.datetime(2026, 10, 7, 9, 5)
    frais()
    n = len(DISCORD.appels)
    pd.rafraichir_bonus(TW)
    patch = [x for x in DISCORD.appels[n:] if x["m"] == "PATCH" and x["p"].endswith(m1)]
    check("le matin, le bonus d'hier est réédité avec les clics arrivés depuis",
          patch and "**VA 12** — **31** subs" in patch[0]["json"]["embeds"][0]["description"],
          [x["p"] for x in DISCORD.appels[n:]])
    CLOCK["now"] = dt.datetime(2026, 10, 7, 12, 30)
    frais()
    n = len(DISCORD.appels)
    pd.rafraichir_bonus(TW)
    check("passé midi, la veille ne bouge plus",
          not [x for x in DISCORD.appels[n:] if x["p"].endswith(m1)]
          and TW not in (pd._etat().get("bonus_veille") or {}))
    installer()
    rec = {"fin": "2026-10-15", "depuis": dt.datetime(2026, 10, 16, 0, 10).timestamp()}
    CLOCK["now"] = dt.datetime(2026, 10, 16, 0, 10)
    n = len(MP["appels"])
    r = pd._figer_quinzaine(TW, pd._etat(), "sal", "2026-10-01", rec)
    check("la quinzaine finie attend le lendemain midi pour se figer (pas de relevé à 00h10)",
          r is False and len(MP["appels"]) == n)
    CLOCK["now"] = dt.datetime(2026, 10, 16, 12, 5)
    frais()
    pd._figer_quinzaine(TW, pd._etat(), "sal", "2026-10-01", rec)
    check("… à midi, elle se relève pour se figer", len(MP["appels"]) > n)

    # ------------------------------------------------------------------ 11
    print("\n— 11. le registre corrigé à la main, et les autres chemins")
    installer()
    pd.classement(LUN, MAR, gid=TW)
    brut = safe_json.load(pd._fichier_trackings(), default={})
    brut["trackings"]["emy.brw/c42"]["numero"] = "douze"
    brut["trackings"]["x/c1"] = {"numero": 5, "vu": "hier", "premier": "2026-10-06"}
    safe_json.write(pd._fichier_trackings(), brut)
    frais()
    try:
        clr = pd.classement(LUN, MAR, gid=TW)
        ok = True
    except Exception as ex:                                  # noqa: BLE001
        ok, clr = repr(ex), {"lignes": []}
    check("une entrée mal écrite à la main est écartée, la boucle continue", ok is True, ok)
    installer()
    LIENS[EQ_TW1][0]["display_name"] = "Inconnu total - ( normal )"
    avant_num = dict(table())
    pd.classement(LUN, MAR, gid=TW, mesure="gms")
    check("le relevé GetMySocial des VA US (Va IG) ne crée aucun numéro Twitter",
          table() == avant_num, set(table()) ^ set(avant_num))

    # ------------------------------------------------------------------ 12
    print("\n— 12. l'écriture du registre")
    src = (BOT / "podium_discord.py").read_text(encoding="utf-8")
    check("safe_json.write sur le registre, jamais write_text direct",
          "safe_json.write(_fichier_trackings(), reg)" in src)
    check("le podium lit MyPuls par l'API brute (une panne n'est pas une liste vide)",
          'mypuls.api_get("tracking-links"' in src and "api_tracking_links(" not in src)
finally:
    for k, val in _SAUVE.items():
        setattr(pd, k, val)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
