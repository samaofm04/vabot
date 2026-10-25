# -*- coding: utf-8 -*-
"""tests_bonus_infloww.py — le bonus du jour lit les abonnés d'Emy chez Infloww.

Propriétaire, 25/10/2026 : « Oui, Infloww pour Emy ». MyPuls range des
abonnés sur un jour plus tardif (Eddy c35 : 194 le 24/10, Infloww 122 à
leur vraie heure) et ne publie que par paliers.

Ce qui est vérifié (podium_discord, section « Infloww ») :
  - pendant le bonus du jour seulement (rafraichir_bonus), et pour un jour :
    les abonnés des trackings Emy du registre viennent d'Infloww ;
  - Seren (pas chez Infloww), la semaine, la quinzaine : MyPuls, intact ;
  - un tracking Emy qu'Infloww ne connaît pas : MyPuls pour lui ;
  - toutes les pages de /v1/linkfans sont lues (elles ne sont pas rangées
    par date), les lignes en double comptent une fois, le jour est celui de
    Paris ;
  - la liste d'un lien n'est relue que si son compteur bouge (ou après
    INFLOWW_FANS_S) ;
  - Infloww muet : MyPuls, et le journal le dit ;
  - le cache de MyPuls n'est jamais modifié ;
  - INFLOWW_BONUS = False : MyPuls partout.

Faux Infloww, faux MyPuls : aucun appel réseau. Lancement :
python tests_bonus_infloww.py
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import pathlib
import sys
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

from zoneinfo import ZoneInfo          # noqa: E402

import podium_discord as pd            # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


PARIS = ZoneInfo("Europe/Paris")


def ms(*a):
    return int(dt.datetime(*a, tzinfo=PARIS).timestamp() * 1000)


J = "2026-10-24"
# les fans des liens : c35 sur trois pages, NON rangées par date, une ligne en
# double ; un abonné à 00h30 le 25/10 de Paris (23h30 UTC le 24) compte le 25
FANS = {"L35": [{"id": "900", "subscribedTime": ms(2026, 10, 20, 9)},
                {"id": "899", "subscribedTime": ms(2026, 10, 24, 10)},
                {"id": "898", "subscribedTime": ms(2026, 10, 24, 11)},
                {"id": "897", "subscribedTime": ms(2026, 10, 18, 9)},
                {"id": "896", "subscribedTime": ms(2026, 10, 24, 23, 50)},
                {"id": "896", "subscribedTime": ms(2026, 10, 24, 23, 50)},   # en double
                {"id": "895", "subscribedTime": ms(2026, 10, 25, 0, 30)},
                {"id": "894", "subscribedTime": ms(2026, 10, 24, 1)}],
        "L42": [{"id": "500", "subscribedTime": ms(2026, 10, 24, 12)}]}
COMPTEUR = {"L35": 7, "L42": 1}
APPELS = []


def _get(chemin, p):
    APPELS.append((chemin, dict(p)))
    if FAUX.get("muet"):
        raise RuntimeError("Infloww 503")
    lignes = FANS[p["linkId"]]
    # 3 lignes par page, en descendant les id, le curseur « id < cursor »
    cur = int(p.get("cursor") or 10 ** 9)
    reste = [y for y in lignes if int(y["id"]) < cur]
    lot = reste[:3]
    return {"data": lot, "hasMore": len(reste) > 3}


FAUX = {"muet": False}
faux_iw = types.SimpleNamespace(
    PLATEFORME="OnlyFans", PAGES_FANS_MAX=150,
    creatrice=lambda pseudo: {"id": "CID"} if pseudo == "emy.brw" else None,
    liens=lambda cid, type_lien="TRACKING", depuis=None: {"liens": [
        {"id": "L35", "code": "35", "abonnes": COMPTEUR["L35"]},
        {"id": "L42", "code": "42", "abonnes": COMPTEUR["L42"]}]},
    _get=_get, _liste=lambda d: list((d or {}).get("data") or []))

MYPULS = {"emy.brw/c35": {"visites": 50, "total": 900, "subs": 194, "subs_total": 413, "nom": "Eddy"},
          "emy.brw/c42": {"visites": 9, "total": 300, "subs": 3, "subs_total": 394, "nom": "Roucham"},
          "emy.brw/c99": {"visites": 2, "total": 20, "subs": 5, "subs_total": 9, "nom": "inconnu d'Infloww"},
          "seren.vale/c195": {"visites": 1, "total": 5, "subs": 2, "subs_total": 3, "nom": "Seren"}}
REG = {"trackings": {t: {"numero": n, "actif": True} for t, n in
                     (("emy.brw/c35", 41), ("emy.brw/c42", 12), ("emy.brw/c99", 99),
                      ("seren.vale/c195", 32))}}

_SAUVE = {k: getattr(pd, k) for k in ("_lire_mypuls_seul", "_lire_registre", "INFLOWW_BONUS")}
_SAUVE_IW = sys.modules.get("infloww")
try:
    sys.modules["infloww"] = faux_iw
    lus = []

    def faux_mypuls(du, au, forcer=False):
        lus.append((du, au))
        return MYPULS, ""
    pd._lire_mypuls_seul = faux_mypuls
    pd._lire_registre = lambda: json.loads(json.dumps(REG))
    pd._INFLOWW_FANS.clear()
    pd._INFLOWW_DITS.clear()
    avant = json.dumps(MYPULS, sort_keys=True)

    hors, _ = pd._lire_mypuls(J, J)
    check("hors du bonus du jour : MyPuls tel quel", hors["emy.brw/c35"]["subs"] == 194 and not APPELS)

    sortie = io.StringIO()
    jeton = pd._BONUS_EN_COURS.set(True)
    try:
        with contextlib.redirect_stdout(sortie):
            v, _ = pd._lire_mypuls(J, J)
            sem, _ = pd._lire_mypuls("2026-10-19", J)
    finally:
        pd._BONUS_EN_COURS.reset(jeton)
    check("bonus du jour : c35 compté chez Infloww — 4 abonnés le 24 (heure de Paris), "
          "la ligne en double une fois, toutes les pages lues",
          v["emy.brw/c35"]["subs"] == 4, v["emy.brw/c35"])
    check("… 00h30 le 25 à Paris (23h30 UTC le 24) compte le 25, pas le 24",
          pd._INFLOWW_FANS["L35"][2].get("2026-10-25") == 1, pd._INFLOWW_FANS["L35"])
    check("… c42 aussi (1), Seren et le tracking inconnu d'Infloww restent à MyPuls",
          v["emy.brw/c42"]["subs"] == 1 and v["seren.vale/c195"]["subs"] == 2
          and v["emy.brw/c99"]["subs"] == 5)
    # 8 lignes, 3 par page, la ligne de la frontière relue (curseur = plus petit
    # id + 1, comme infloww.fans_lien) : 4 pages, jusqu'à « hasMore » faux
    check("… les pages suivies au curseur, jusqu'au bout (c35 : 4 pages)",
          [a[1].get("cursor") for a in APPELS if a[1]["linkId"] == "L35"] == [None, "899", "897", "896"],
          APPELS)
    check("… la semaine (plusieurs jours) : MyPuls", sem["emy.brw/c35"]["subs"] == 194)
    check("… le journal le dit, une fois", "abonnés d'Emy lus chez Infloww (2 tracking(s) sur 3)"
          in sortie.getvalue(), sortie.getvalue())
    check("… le cache de MyPuls n'est jamais touché", json.dumps(MYPULS, sort_keys=True) == avant)

    n = len(APPELS)
    jeton = pd._BONUS_EN_COURS.set(True)
    try:
        pd._lire_mypuls(J, J)
        COMPTEUR["L42"] = 2
        FANS["L42"].append({"id": "499", "subscribedTime": ms(2026, 10, 24, 18)})
        v2, _ = pd._lire_mypuls(J, J)
    finally:
        pd._BONUS_EN_COURS.reset(jeton)
    check("une liste n'est relue que si le compteur de son lien bouge",
          [a[1]["linkId"] for a in APPELS[n:]] == ["L42"] and v2["emy.brw/c42"]["subs"] == 2,
          APPELS[n:])

    FAUX["muet"] = True
    pd._INFLOWW_FANS.clear()
    sortie = io.StringIO()
    jeton = pd._BONUS_EN_COURS.set(True)
    try:
        with contextlib.redirect_stdout(sortie):
            vm, _ = pd._lire_mypuls(J, J)
    finally:
        pd._BONUS_EN_COURS.reset(jeton)
    FAUX["muet"] = False
    check("Infloww muet : MyPuls, et c'est dit au journal",
          vm["emy.brw/c35"]["subs"] == 194 and "Infloww muet pour le bonus du 2026-10-24"
          in sortie.getvalue(), sortie.getvalue())

    pd.INFLOWW_BONUS = False
    jeton = pd._BONUS_EN_COURS.set(True)
    try:
        vo, _ = pd._lire_mypuls(J, J)
    finally:
        pd._BONUS_EN_COURS.reset(jeton)
    pd.INFLOWW_BONUS = True
    check("INFLOWW_BONUS = False : MyPuls partout", vo["emy.brw/c35"]["subs"] == 194)

    vu_ctx = []
    _vrai = pd._rafraichir_bonus_mypuls
    pd._rafraichir_bonus_mypuls = lambda gid, jour=None: vu_ctx.append(pd._BONUS_EN_COURS.get()) or "M"
    try:
        r = pd.rafraichir_bonus(pd.TWITTER_ID)
    finally:
        pd._rafraichir_bonus_mypuls = _vrai
    check("rafraichir_bonus ouvre le bonus du jour (le bonus d'hier, complété, aussi), puis le referme",
          r == "M" and vu_ctx == [True] and pd._BONUS_EN_COURS.get() is False)
finally:
    for k, val in _SAUVE.items():
        setattr(pd, k, val)
    if _SAUVE_IW is not None:
        sys.modules["infloww"] = _SAUVE_IW
    else:
        sys.modules.pop("infloww", None)
    pd._INFLOWW_FANS.clear()

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
