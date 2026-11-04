"""« Période précédente figée » (04/11/2026).

Seren partie avec MyPuls, la quinzaine du 16 au 31/10 de « 📈 Mes stats »
était « pas lisible » pour tout VA qui l'avait ; le propriétaire a choisi le
chiffre de la quinzaine figée, tel que ses pages Discord l'affichent. Ce
fichier prouve, sans réseau :
  1. subs_fige_du_va lit le chiffre du VA sur les pages figées (Twitter
     « VA n », Agency « Instagram VA n »), une fois par heure ; rien pour une
     quinzaine pas figée, un VA absent ou « sans relevé », une page en clics ;
  2. Mes stats : la période précédente illisible prend ce chiffre, marqué
     « (quinzaine figée) » ; lisible, elle garde la lecture du moment ;
  3. stats_va._gagne : une quinzaine finie illisible est payée sur ce chiffre.

Lancer depuis la racine du dépôt : python tests_quinzaine_figee.py
"""
from __future__ import annotations

import datetime as dt
import io
import os
import pathlib
import sys

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
import subs_va                 # noqa: E402
import stats_va                # noqa: E402
import liens_va                # noqa: E402

TW, AG = pod.TWITTER_ID, pod.AGENCY_IG_ID
pod._aujourdhui = lambda: dt.date(2026, 11, 4)
ETAT = {"subs_figes": {TW: {"2026-10-16": {"messages": ["m1", "m2"], "complet": True}},
                       AG: {"2026-10-16": {"messages": ["a1"], "complet": True}}}}
pod._etat = lambda: ETAT
LUES = []
PAGES = {TW: ([("VA 95", 67), ("VA 41", 793), ("VA 12", 3)], ["VA 12"], "subs", ""),
         AG: ([("Instagram VA 92", 22)], [], "subs", "")}


def _affichee(gid, saison):
    LUES.append((gid, saison))
    return PAGES[gid]


pod._quinzaine_affichee = _affichee

print("1. subs_fige_du_va")
check("Twitter VA 95 : 67, le chiffre de sa page", pod.subs_fige_du_va(TW, "2026-10-16", 95) == 67)
check("Agency VA 92 : « Instagram VA 92 », 22", pod.subs_fige_du_va(AG, "2026-10-16", 92) == 22)
check("un VA « sans relevé » sur la page : rien (jamais un zéro)", pod.subs_fige_du_va(TW, "2026-10-16", 12) is None)
check("un VA absent des pages : rien", pod.subs_fige_du_va(TW, "2026-10-16", 300) is None)
check("une quinzaine pas figée : rien, et ses pages ne sont pas lues",
      pod.subs_fige_du_va(TW, "2026-11-01", 95) is None and ("tw", "2026-11-01") not in LUES)
check("numéro absent : rien", pod.subs_fige_du_va(TW, "2026-10-16", None) is None)
n = len(LUES)
pod.subs_fige_du_va(TW, "2026-10-16", 41)
check("relue au plus une fois par heure (gardée)", len(LUES) == n, LUES)
pod._FIGEES_LUES.clear()
PAGES[TW] = ([("VA 95", 400)], [], "clics", "")
check("une page en clics (avant le 19/10) : rien", pod.subs_fige_du_va(TW, "2026-10-16", 95) is None)
PAGES[TW] = ([("VA 95", 67)], [], "subs", "")
pod._FIGEES_LUES.clear()

print("2. Mes stats")
LECTURE = {"precedente": None}
subs_va.trackings_du_va = lambda g, u: [("of", "https://onlyfans.com/liasxcret/c75"),
                                        ("of", "https://onlyfans.com/seren.vale/c224")]
subs_va._communs = lambda ts, pseudo, jour=None: set()
subs_va.pseudo_du_va = lambda g, u: "rodolpheks"


def _subs_of(urls, d0, d1):
    return LECTURE["precedente"] if d0 == "2026-10-16" else 5


subs_va._subs_of = _subs_of
liens_va.lien_de = lambda g, u: {"numero": 95, "pseudo": "rodolpheks"}
r = subs_va.subs_du_va(TW, "u95")
check("période précédente illisible : 67, marquée figée",
      r["precedente"]["n"] == 67 and r["precedente"].get("fige") is True, r["precedente"])
check("aujourd'hui et cette période : la lecture du moment", r["aujourdhui"]["n"] == 5 and r["periode"]["n"] == 5)
LECTURE["precedente"] = 70
r2 = subs_va.subs_du_va(TW, "u95")
check("lisible : la lecture du moment, pas le chiffre figé",
      r2["precedente"]["n"] == 70 and not r2["precedente"].get("fige"), r2["precedente"])
LECTURE["precedente"] = None
lignes = []
for cle in ("aujourdhui", "periode", "precedente"):
    p = r[cle]
    lignes.append((f"**{p['n']}**" + (" (quinzaine figée)" if p.get("fige") else "")) if p["n"] is not None else "pas lisible")
check("le texte dit « (quinzaine figée) » sur la seule période précédente",
      lignes == ["**5**", "**5**", "**67** (quinzaine figée)"], lignes)

print("3. La paie de la page perso")
subs_va._subs_mym = lambda urls, d0, d1: 0
g = stats_va._gagne(["https://onlyfans.com/liasxcret/c75"], [], "2026-10-16", "2026-10-31",
                    lambda saison: 67 if saison == "2026-10-16" else None)
check("quinzaine finie illisible : payée sur son chiffre figé (67 × 0,70)", g == round(67 * 0.70, 2), g)
g2 = stats_va._gagne(["https://onlyfans.com/liasxcret/c75"], [], "2026-10-16", "2026-10-31")
check("sans chiffre figé : rien (jamais une paie inventée)", g2 is None, g2)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
