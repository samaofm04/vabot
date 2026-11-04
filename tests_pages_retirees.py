"""Emy et Seren retirées de MyPuls (03/11/2026) : leurs trackings remis dans
chaque lecture, pour qu'aucun VA ne reste « sans relevé ».

Propriétaire, 03/11 vers minuit : « j'ai déjà remove Emy et Seren de
MyPuls », « y a plus que Lia » ; le 04/11 : Emy « lue chez Infloww », Seren
« remets-les » (le relevé du 03/11, RELEVE_SEREN). Ce fichier prouve, sans
réseau :
  1. avant RETIREES_DEPUIS, rien ne change ;
  2. la quinzaine du 01/11 : Seren au relevé, Emy chez Infloww, Lia telle
     que MyPuls la rend ; noms du registre, ou refaits depuis la fiche ;
  3. une période qui ne couvre pas tout le 01→03/11 (semaine du 02/11,
     bonus) : Seren présente, à 0 ;
  4. depuis toujours : les cumuls d'Infloww (clics, revenu) ;
  5. Infloww muet : Emy absente (le VA reste sans relevé, une panne n'est pas
     un zéro), Seren là, et la lecture suivante réessaie ;
  6. MyPuls qui rend encore un tracking Emy fait foi ;
  7. un lien Infloww sans abonné n'est pas lu jour par jour ;
  8. emy.brww (renommée) = emy.brw ;
  9. subs_va : le tracking Seren de la fiche est bien « à lui » et compté.

Lancer depuis la racine du dépôt : python tests_pages_retirees.py
"""
from __future__ import annotations

import datetime as dt
import io
import os
import pathlib
import sys
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


import podium_discord as pod   # noqa: E402
import liens_va as lv          # noqa: E402
import subs_va                 # noqa: E402

JOUR = {"j": dt.date(2026, 11, 4)}
pod._aujourdhui = lambda: JOUR["j"]

# MyPuls : ne rend plus que Lia (et Emy quand MP_EMY le dit)
LIA = "liasxcret/c50"
MP_EMY = {"on": False}
APPELS_MP = []


def _base(du, au, forcer=False):
    APPELS_MP.append((du, au))
    out = {LIA: {"visites": 40, "total": 90, "subs": 5, "subs_total": 9,
                 "nom": "Twitter VA 95 @rodolpheks", "net": 1000}}
    if MP_EMY["on"]:
        out["emy.brw/c35"] = {"visites": 1, "total": 2, "subs": 99, "subs_total": 99,
                              "nom": "Eddy - ( normal )", "net": 0}
    return out, ""


pod._lire_mypuls_sans_retirees = _base
REG = {"trackings": {
    "emy.brw/c35": {"numero": 41, "nom": "Eddy - ( normal )", "mp": True, "actif": True},
    "seren.vale/c224": {"numero": 95, "nom": "Twitter VA 95 @rodolpheks", "mp": True, "actif": True},
    LIA: {"numero": 95, "nom": "Twitter VA 95 @rodolpheks", "mp": True, "actif": True}}}
pod._lire_registre = lambda: REG
FICHES = {"liens": {
    f"{lv.AGENCY_IG_ID}:u92": {"numero": 92, "pseudo": "fiable0010",
                               "tracking": "https://onlyfans.com/liasxcret/c99",
                               "variante": {"tracking": "https://onlyfans.com/seren.vale/c241"}},
    f"{lv.TWITTER_ID}:u10": {"numero": 10, "pseudo": "ancien",
                             "tracking": "https://onlyfans.com/liasxcret/c77",
                             "anciens_trackings": ["https://onlyfans.com/emy.brww/c36"]}}}
lv._etat = lambda: FICHES
lv.config = lambda: {}

# Infloww : Emy « Emy finito » -- le vrai subs_infloww, sur un faux module
INF = {"muet": False}
APPELS_INF = []
fiw = types.ModuleType("infloww")
fiw.creatrice = lambda p: {"id": "E"} if p == "emy.brw" else None


LIENS_LUS = []


def _liens(cid, typ="TRACKING", depuis=None):
    LIENS_LUS.append(cid)
    if INF["muet"]:
        raise RuntimeError("Infloww en panne")
    return {"liens": [
        {"id": "L35", "code": "35", "abonnes": 6, "clics": 300, "net": 1250, "nom": "Eddy - ( normal )"},
        {"id": "L36", "code": "36", "abonnes": 0, "clics": 4, "net": 0, "nom": "Twitter VA 10 @ancien"}]}


fiw.liens = _liens
sys.modules["infloww"] = fiw
PAR_JOUR = {"L35": {"2026-10-20": 4, "2026-11-02": 2}}


def _par_jour(iw, cid, lien_id, plancher_ms=0):
    APPELS_INF.append(lien_id)
    return dict(PAR_JOUR.get(lien_id, {}))


pod._abonnes_par_jour_infloww = _par_jour


def lire(du, au):
    pod._RETIREES_LUES.clear()
    pod._INFLOWW_MUET.clear()
    vus, _ = pod._lire_mypuls_seul(du, au)
    return vus


print("1. Avant le retrait")
JOUR["j"] = dt.date(2026, 11, 2)
v = lire("2026-11-01", "2026-11-02")
check("avant le 03/11 : la lecture de MyPuls telle quelle", set(v) == {LIA}, set(v))
JOUR["j"] = dt.date(2026, 11, 4)

print("2. La quinzaine du 01/11")
v = lire("2026-11-01", "2026-11-04")
check("Seren de VA 95 : ses 10 subs relevés", v["seren.vale/c224"]["subs"] == 10, v.get("seren.vale/c224"))
check("… sous son nom du registre", v["seren.vale/c224"]["nom"] == "Twitter VA 95 @rodolpheks")
check("Seren de VA 92 (Agency, hors registre) : 7, nommée depuis la fiche",
      v["seren.vale/c241"]["subs"] == 7 and v["seren.vale/c241"]["nom"] == "Instagram VA 92 @fiable0010",
      v.get("seren.vale/c241"))
check("Emy c35 : les abonnés d'Infloww de la période (2)", v["emy.brw/c35"]["subs"] == 2, v.get("emy.brw/c35"))
check("Lia : ce que MyPuls rend, intact", v[LIA]["subs"] == 5 and v[LIA]["visites"] == 40)
check("les Seren du relevé hors registre et hors fiches sont là aussi (à 0 ou leur relevé)",
      v.get("seren.vale/c201", {}).get("subs") == 1)
check("clics et revenu de la période : 0 (Infloww ne les date pas)",
      v["emy.brw/c35"]["visites"] == 0 and v["emy.brw/c35"]["net"] == 0)

print("3. Une période qui ne couvre pas tout le 01→03/11")
v = lire("2026-11-02", "2026-11-04")
check("semaine du 02/11 : Seren présente, à 0 (pas sans relevé)",
      v["seren.vale/c224"]["subs"] == 0 and "seren.vale/c224" in v)
v = lire("2026-11-03", "2026-11-03")
check("bonus du 03/11 : pareil", v["seren.vale/c224"]["subs"] == 0)
check("… mais depuis la création, ses 10 comptent", v["seren.vale/c224"]["subs_total"] == 10)

v = lire("2026-10-16", "2026-10-31")
check("16→31/10 (avant le relevé) : Seren absente, « pas lisible », jamais un faux 0",
      "seren.vale/c224" not in v and "emy.brw/c35" in v, sorted(v))
print("4. Depuis toujours")
v = lire(pod.ALLTIME_DEPUIS, "2026-11-04")
check("Emy c35 depuis toujours : 6 abonnés, 300 clics, 12,50 $ (Infloww : déjà en centimes)",
      v["emy.brw/c35"]["subs"] == 6 and v["emy.brw/c35"]["visites"] == 300
      and v["emy.brw/c35"]["net"] == 1250, v.get("emy.brw/c35"))

print("5. Infloww muet")
INF["muet"] = True
v = lire("2026-11-01", "2026-11-04")
check("Emy absente (le VA reste sans relevé), Seren là",
      "emy.brw/c35" not in v and v["seren.vale/c224"]["subs"] == 10, sorted(v))
n_avant = len(LIENS_LUS)
pod._RETIREES_LUES.clear()
vus, _ = pod._lire_mypuls_seul("2026-11-01", "2026-11-04")
check("Infloww muet : la lecture suivante ne le réessaie pas tout de suite (pause INFLOWW_MUET_S)",
      n_avant > 0 and "emy.brw/c35" not in vus and len(LIENS_LUS) == n_avant, (n_avant, len(LIENS_LUS)))
INF["muet"] = False
pod._RETIREES_MUETTES.clear()
pod._MP_LUS.clear()
pod._INFLOWW_MUET.clear()
vus, _ = pod._lire_mypuls_seul("2026-11-01", "2026-11-04")
check("Infloww revenu : la lecture suivante le reprend (rien gardé de la panne)",
      "emy.brw/c35" in vus)

print("6. MyPuls fait foi")
MP_EMY["on"] = True
v = lire("2026-11-01", "2026-11-04")
check("un tracking Emy que MyPuls rend encore garde le chiffre de MyPuls", v["emy.brw/c35"]["subs"] == 99)
MP_EMY["on"] = False

print("7. Les liens sans abonné")
APPELS_INF.clear()
v = lire("2026-11-01", "2026-11-04")
check("c36 (0 abonné chez Infloww) : pas lu jour par jour, compté 0",
      "L36" not in APPELS_INF and v["emy.brw/c36"]["subs"] == 0, APPELS_INF)

print("8. emy.brww")
check("l'ancien tracking emy.brww/c36 de la fiche est remis sous emy.brw/c36, nommé depuis la fiche",
      v["emy.brw/c36"]["nom"] == "Twitter VA 10 @ancien", v.get("emy.brw/c36"))
check("page_retiree reconnaît emy.brww et seren.vale, pas Lia",
      pod.page_retiree("emy.brww/c1") and pod.page_retiree("seren.vale/c2") and not pod.page_retiree(LIA))

print("9. subs_va")
pod._RETIREES_LUES.clear()
pod._MP_LUS.clear()
n = subs_va._subs_of(["https://onlyfans.com/liasxcret/c50", "https://onlyfans.com/seren.vale/c224"],
                     "2026-11-01", "2026-11-04")
check("_subs_of : Lia 5 + Seren 10", n == 15, n)
pod._RETIREES_LUES.clear()
vus, _ = pod._lire_mypuls_seul("2026-11-04", "2026-11-04")
check("_a_lui : le tracking Seren de VA 92 est à lui (son nom porte son pseudo)",
      subs_va._a_lui(vus["seren.vale/c241"]["nom"], "fiable0010"))

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
