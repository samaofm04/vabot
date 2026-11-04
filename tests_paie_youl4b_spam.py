# -*- coding: utf-8 -*-
"""tests_paie_youl4b_spam.py — la grille des VA de Youl4b (Spam) sur la page
JESSY LE RETOUR (/infloww/liens?c=emy), 04/11/2026.

Propriétaire : « Système de rémunération » (14 jours, payés le 1er et le 16),
puis « il doit faire 70 subs pour avoir son paiement fixe, 60 $ [...] s'il fait
160 subs, tu retires 70, ça fait 90 subs [...] 0,5 le sub [...] plus les 60 du
fixe », « si le mec est en dessous de 70 subs, mets-lui 0,40 par sub ».
Ce fichier prouve, sans réseau :
  1. paie_grille : sous 70, 0,40 $ / sub ; dès 70, 60 $ + (subs − 70) au taux
     du palier des subs en plus (0–99 : 0,50 ; 100–199 : 0,60 ; 200–499 :
     0,70 ; 500+ : 0,80), non cumulable ;
  2. la colonne « Gagné » de la page : sur une quinzaine entière (ou celle en
     cours jusqu'à aujourd'hui) depuis le 01/11 seulement, pour tout le
     monde ; « — » pour toute autre vue ; la page Lia ne change pas ;
  3. la page montre « Gagné » et les clics globaux.

Lancement : python tests_paie_youl4b_spam.py
"""
from __future__ import annotations

import io
import os
import pathlib
import sys

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import infloww_liens as il  # noqa: E402

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:400]}]"))


emy = il.profil("emy")
lia = il.profil("lia")
G = emy.PAIE_GRILLE

print("1. La grille")
CAS = [(0, 0.0), (1, 0.40), (69, 27.60), (70, 60.0), (160, 105.0), (169, 109.50), (170, 120.0),
       (269, 179.40), (270, 200.0), (569, 409.30), (570, 460.0)]
for n, attendu in CAS:
    check(f"{n} subs : {attendu:.2f} $", emy.paie_grille(n) == attendu, emy.paie_grille(n))
check("l'exemple du propriétaire : 160 subs → 90 × 0,50 + 60 = 105 $", emy.paie_grille(160) == 105.0)
check("sans nombre : rien d'inventé", emy.paie_grille(None) is None)
check("la grille vaut pour Youl4b Spam (page Emy) seulement",
      G and G["depuis"] == "2026-11-01" and lia.PAIE_GRILLE is None and il.PAIE_GRILLE is None)

print("2. La colonne « Gagné »")
emy._aujourdhui = lambda: "2026-11-04"


def vue(du, au, lignes):
    return {"periode": {"du": du, "au": au}, "lignes": [dict(x) for x in lignes], "totaux": {}}


LIGNES = [{"cle": "Mihkim", "subs": 173}, {"cle": "Printsy", "subs": 160}, {"cle": "Kikie", "subs": 72},
          {"cle": "Eddy", "subs": 39}, {"cle": "Rina", "subs": None}]
emy.lire_paie = lambda: ({"Eddy": {"type": "fixe", "montant": 50, "devise": "USD"}}, [])
t = emy._ajouter_gagne(vue("2026-11-01", "2026-11-04", LIGNES))
g = {x["cle"]: x["gagne"] for x in t["lignes"]}
check("cette quinzaine (01/11 → aujourd'hui) : la grille, pour chacun",
      g == {"Mihkim": 60 + 103 * 0.60, "Printsy": 105.0, "Kikie": 61.0, "Eddy": 15.60, "Rina": None}, g)
check("… un réglage de paie d'avant ne passe pas devant (Eddy : 39 × 0,40)", g["Eddy"] == 15.60)
check("… le total, celui des VA", t["totaux"]["gagne"] == round(60 + 103 * 0.60 + 105 + 61 + 15.6, 2), t["totaux"])
t = emy._ajouter_gagne(vue("2026-11-01", "2026-11-15", LIGNES))
check("la quinzaine 1→15 entière : la grille", t["lignes"][1]["gagne"] == 105.0)
for du, au, quoi in (("2026-11-04", "2026-11-04", "aujourd'hui"), ("2026-10-29", "2026-11-04", "7 derniers jours"),
                     ("2026-10-16", "2026-10-31", "la quinzaine du 16/10, avant le nouveau système"),
                     ("2026-11-01", "2026-11-03", "une part de quinzaine")):
    t = emy._ajouter_gagne(vue(du, au, LIGNES))
    check(f"{quoi} : « — » (une part de quinzaine n'a pas de prix)",
          all(x["gagne"] is None for x in t["lignes"]) and t["totaux"]["gagne"] is None, t["lignes"][:2])
t = emy._ajouter_gagne({"lignes": [dict(x) for x in LIGNES], "totaux": {}})
check("depuis toujours : « — »", all(x["gagne"] is None for x in t["lignes"]))
check("page Lia : toujours 0,70 $ au sub",
      lia._ajouter_gagne({"periode": {}, "lignes": [{"cle": "VA 1", "subs": 10}], "totaux": {}})["lignes"][0]["gagne"]
      == 7.0)

print("3. La page")
check("la page Emy porte la colonne « Gagné » et les clics globaux",
      emy.COLONNE_GAGNE and emy.CLICS_GLOBAUX)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
