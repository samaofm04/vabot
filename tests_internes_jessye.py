# -*- coding: utf-8 -*-
"""tests_internes_jessye.py — la ligne des comptes internes compte aussi leurs
trackings Jessye, lus chez Infloww.

Propriétaire, 28/10/2026 : « il faut bien additionner de chez Jesse plus de
chez Emy », « c'est toujours les mêmes personnes au même lien ».

Ce qui est vérifié (podium_discord, INTERNES_JESSYE) :
  - Twitter, en abonnés : un tracking Jessye EN ATTENTE dont tous les numéros
    possibles sont internes compte dans VA 41 (Emy chez MyPuls + Jessye chez
    Infloww), chaque tracking une fois ; c133 « VA 27 ou 137 » aussi ;
  - un numéro possible de VA Discord : rien ne change, il reste sans relevé ;
  - un tracking que MyPuls n'a pas rendu : sans relevé, comme avant ;
  - Infloww muet : la part MyPuls reste, ces comptes passent « sans relevé »
    dans la ligne réunie, et le journal le dit ;
  - Threads : le lien d'un tracking en attente revient dans Threads 142 ;
  - les « abonnés » datés de la création d'un lien Jessye ne comptent pas ;
  - Infloww muet n'est pas relu pendant INFLOWW_MUET_S ;
  - INTERNES_JESSYE = False : tout comme avant.

Faux Infloww, faux registre : aucun appel réseau. Lancement :
python tests_internes_jessye.py
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
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


# Jessye chez Infloww : c146 (Eddy) 3 abonnés dans la semaine dont un en
# double, c135 (Tiger) 2, c133 (Robot) 1 ; un abonné d'avant la semaine
FANS = {"L146": [{"id": "9", "subscribedTime": ms(2026, 10, 27, 17)},
                 {"id": "8", "subscribedTime": ms(2026, 10, 28, 9)},
                 {"id": "8", "subscribedTime": ms(2026, 10, 28, 9)},
                 {"id": "7", "subscribedTime": ms(2026, 10, 28, 10)}],
        "L135": [{"id": "6", "subscribedTime": ms(2026, 10, 27, 18)},
                 {"id": "5", "subscribedTime": ms(2026, 10, 28, 1)},
                 {"id": "4", "subscribedTime": ms(2026, 10, 20, 1)}],
        "L133": [{"id": "3", "subscribedTime": ms(2026, 10, 28, 2)}],
        # c144 créé le 27/10 à 15:53:20 : deux lignes à la seconde de la
        # création (avant tout envoi GetMySocial), une vraie à 16:43
        "L144": [{"id": "2", "subscribedTime": ms(2026, 10, 27, 15, 53, 20)},
                 {"id": "1", "subscribedTime": ms(2026, 10, 27, 15, 53, 50)},
                 {"id": "0", "subscribedTime": ms(2026, 10, 27, 16, 43)}]}
FAUX = {"muet": False}


def _get(chemin, p):
    if FAUX["muet"]:
        raise RuntimeError("Infloww 503")
    return {"data": FANS[p["linkId"]], "hasMore": False}


faux_iw = types.SimpleNamespace(
    PLATEFORME="OnlyFans", PAGES_FANS_MAX=150,
    creatrice=lambda pseudo: {"id": "JES"} if pseudo == "jessyewdiference" else None,
    liens=lambda cid, type_lien="TRACKING", depuis=None: {"liens": [
        {"id": "L146", "code": "146", "abonnes": 3}, {"id": "L135", "code": "135", "abonnes": 3},
        {"id": "L133", "code": "133", "abonnes": 1},
        {"id": "L144", "code": "144", "abonnes": 3, "cree_ms": ms(2026, 10, 27, 15, 53, 20)}]},
    _get=_get, _liste=lambda d: list((d or {}).get("data") or []))

J = "jessyewdiference/c"
REG = {"trackings": {
    "emy.brw/c35": {"numero": 41, "actif": True, "vu": "2026-10-28", "premier": "2026-10-04"},
    "emy.brw/c67": {"numero": 67, "actif": False, "vu": "2026-10-27", "premier": "2026-10-04"},
    "emy.brw/c72": {"numero": 27, "actif": False, "vu": "2026-10-27", "premier": "2026-10-04"},
    "emy.brw/c40": {"numero": 10, "actif": True, "vu": "2026-10-28", "premier": "2026-10-04"},
    "liasxcret/c80": {"numero": 95, "actif": True, "vu": "2026-10-28", "premier": "2026-10-28"}},
    "attente": {
        J + "146": {"premier": "2026-10-27", "numeros": [41], "conflit": False},
        J + "135": {"premier": "2026-10-27", "numeros": [67], "conflit": False},
        J + "133": {"premier": "2026-10-27", "numeros": [27, 137], "conflit": False},
        J + "999": {"premier": "2026-10-27", "numeros": [12, 95], "conflit": False}}}
INTERNES = {41, 67, 27, 137, 12, 10}
# ce que _classement_tracking rend pour la semaine : les numéros cités par une
# attente sans relevé, VA 10 sans relevé (MyPuls n'a pas rendu c40)
BASE = {"lignes": [{"va": "VA 96", "numero": 96, "clics": 40, "liens": 1, "spam": False, "model": ""}],
        "illisibles": ["VA 10", "VA 12", "VA 137", "VA 27", "VA 41", "VA 67", "VA 95"],
        "par_tracking": {"emy.brw/c35": 100, "emy.brw/c67": 20, "emy.brw/c72": 5,
                         "liasxcret/c80": 50},
        "introuvables": [], "erreur": "", "frais": True}
D0, D1 = dt.date(2026, 10, 26), dt.date(2026, 11, 1)

_SAUVE = {k: getattr(pd, k) for k in ("_lire_registre", "numeros_internes", "INTERNES_JESSYE",
                                       "_classement_sans_internes")}
_SAUVE_IW = sys.modules.get("infloww")
try:
    sys.modules["infloww"] = faux_iw
    pd._lire_registre = lambda: copy.deepcopy(REG)
    pd.numeros_internes = lambda reg=None: set(INTERNES)
    pd._INFLOWW_FANS.clear()
    pd._INFLOWW_DITS.clear()
    pd._INTERNES_DITS.clear()

    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        cl = pd._avec_jessye(copy.deepcopy(BASE), D0, D1)
        tw = pd._reunir(cl, pd.TWITTER_ID, {f"VA {n}": n for n in INTERNES}, pd._tri_tracking)
    par = {x["va"]: x["clics"] for x in cl["lignes"]}
    check("Eddy : Emy (MyPuls 100) + Jessye c146 (Infloww 3, la ligne en double une fois)",
          par.get("VA 41") == 103, par)
    check("Tiger : c67 quitté le 27 (20) + c135 sur la semaine seulement (2, pas celui du 20/10)",
          par.get("VA 67") == 22, par)
    check("c133 « VA 27 ou 137 » (deux internes) : au 27, avec son Emy c72 (5 + 1)",
          par.get("VA 27") == 6 and "VA 137" not in cl["illisibles"] and "VA 137" not in par,
          (par, cl["illisibles"]))
    check("un numéro possible de VA Discord (c999 : 12 ou 95) : les deux restent sans relevé",
          "VA 95" in cl["illisibles"] and "VA 12" in cl["illisibles"] and "VA 95" not in par,
          cl["illisibles"])
    check("un tracking que MyPuls n'a pas rendu (c40, VA 10) : sans relevé, comme avant",
          "VA 10" in cl["illisibles"] and "VA 10" not in par, cl["illisibles"])
    check("les autres lignes ne bougent pas (VA 96)", par.get("VA 96") == 40, par)
    x = next((y for y in tw["lignes"] if y.get("interne")), {})
    check("VA 41 réuni = 103 + 22 + 6, sans relevé : VA 10 et VA 12 seulement",
          x.get("clics") == 131 and x.get("sans_releve") == ["VA 10", "VA 12"], x)
    check("… le journal dit les trackings Jessye lus chez Infloww",
          "3 tracking(s) Jessye lus chez Infloww (6 abonnés)" in sortie.getvalue(),
          sortie.getvalue())

    FAUX["muet"] = True
    pd._INFLOWW_FANS.clear()
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        clm = pd._avec_jessye(copy.deepcopy(BASE), D0, D1)
        twm = pd._reunir(clm, pd.TWITTER_ID, {f"VA {n}": n for n in INTERNES}, pd._tri_tracking)
    FAUX["muet"] = False
    APPELS = []
    faux_iw._get = lambda chemin, p: APPELS.append(p) or _get(chemin, p)
    r_muet = pd.subs_infloww("2026-10-26", {J + "146"}, au="2026-11-01", creatrice="jessyewdiference")
    faux_iw._get = _get
    check("Infloww muet : pas relu avant INFLOWW_MUET_S (aucun appel, None)",
          r_muet is None and not APPELS, (r_muet, APPELS))
    pd._INFLOWW_MUET.clear()
    xm = next((y for y in twm["lignes"] if y.get("interne")), {})
    check("Infloww muet : la part MyPuls reste comptée (100 + 20 + 5)", xm.get("clics") == 125, xm)
    check("… ces comptes sont « sans relevé » dans la ligne réunie",
          {"VA 41", "VA 67", "VA 27"} <= set(xm.get("sans_releve") or []), xm)
    check("… et le journal le dit", "Infloww muet" in sortie.getvalue()
          and "la part Jessye de VA 27, VA 41, VA 67" in sortie.getvalue(), sortie.getvalue())

    APPELS = []
    faux_iw._get = lambda chemin, p: APPELS.append(p) or _get(chemin, p)
    pd._INFLOWW_FANS.clear()
    sans_pt = {k: v for k, v in copy.deepcopy(BASE).items() if k != "par_tracking"}
    with contextlib.redirect_stdout(io.StringIO()):
        c_np = pd._avec_jessye(copy.deepcopy(sans_pt), D0, D1)
    faux_iw._get = _get
    check("un classement sans par_tracking (pas celui de MyPuls) : tel quel, Infloww pas lu",
          c_np == sans_pt and not APPELS, (c_np, APPELS))

    pd._INFLOWW_FANS.clear()
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        r144 = pd.subs_infloww("2026-10-27", {J + "144"}, au="2026-10-27", creatrice="jessyewdiference")
    check("c144 : les 2 lignes datées de la création du lien (+ 60 s) ne comptent pas, la vraie oui",
          r144 == {J + "144": 1}, r144)
    check("… et le journal le dit", "2 abonné(s) datés de sa création" in sortie.getvalue(),
          sortie.getvalue())

    # le crochet dans classement() : Twitter en abonnés seulement
    pd._INFLOWW_FANS.clear()
    pd._classement_sans_internes = lambda *a, **k: copy.deepcopy(BASE)
    with contextlib.redirect_stdout(io.StringIO()):
        c_ab = pd.classement(D0, D1, gid=pd.TWITTER_ID, mesure="tracking_abonnes")
        c_vi = pd.classement(D0, D1, gid=pd.TWITTER_ID, mesure="tracking")
    xa = next((y for y in c_ab["lignes"] if y.get("interne")), {})
    xv = next((y for y in c_vi["lignes"] if y.get("interne")), None)
    check("classement() de Twitter en abonnés : VA 41 avec Jessye (131)", xa.get("clics") == 131, xa)
    check("… aux visites (Infloww ne les date pas) : comme avant, VA 41 sans relevé",
          xv is None and "VA 41" in c_vi["illisibles"], c_vi)

    pd.INTERNES_JESSYE = False
    with contextlib.redirect_stdout(io.StringIO()):
        c_off = pd.classement(D0, D1, gid=pd.TWITTER_ID, mesure="tracking_abonnes")
    check("INTERNES_JESSYE = False : comme avant (VA 41 sans relevé, aucune lecture Infloww)",
          not [y for y in c_off["lignes"] if y.get("interne")] and "VA 41" in c_off["illisibles"],
          c_off)
    pd.INTERNES_JESSYE = True
    pd._classement_sans_internes = _SAUVE["_classement_sans_internes"]

    # Threads : les liens des trackings en attente reviennent dans Threads 142
    liens = [{"id": "A", "display_name": "VA 2 - ( Eddy ) 1", "buttons": [{"url": "https://onlyfans.com/jessyewdiference/c146"}]},
             {"id": "B", "display_name": "(Robot)", "buttons": [{"url": "https://onlyfans.com/jessyewdiference/c133"}]},
             {"id": "C", "display_name": "Twitter VA 95 @x", "buttons": [{"url": "https://onlyfans.com/jessyewdiference/c999"}]},
             {"id": "E", "display_name": "VA 2 - ( Eddy ) 2", "url": "https://onlyfans.com/emy.brw/c35"}]
    with contextlib.redirect_stdout(io.StringIO()):
        ents = pd._entites_jessye(liens)
    check("Threads : Eddy 1 (attente) et Eddy 2 (registre) au 41, Robot au 27, c999 écarté",
          ents == {41: ["A", "E"], 27: ["B"]}, ents)
    pd.INTERNES_JESSYE = False
    with contextlib.redirect_stdout(io.StringIO()):
        ents0 = pd._entites_jessye(liens)
    pd.INTERNES_JESSYE = True
    check("… INTERNES_JESSYE = False : comme avant (Eddy 2 seul)", ents0 == {41: ["E"]}, ents0)
finally:
    for k, val in _SAUVE.items():
        setattr(pd, k, val)
    if _SAUVE_IW is not None:
        sys.modules["infloww"] = _SAUVE_IW
    else:
        sys.modules.pop("infloww", None)
    pd._INFLOWW_FANS.clear()
    pd._INFLOWW_MUET.clear()

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
