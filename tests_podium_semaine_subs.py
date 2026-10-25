# -*- coding: utf-8 -*-
"""tests_podium_semaine_subs.py — le podium de la semaine de Twitter aux abonnés.

Propriétaire, 24/10/2026, devant « VA 41 — 1469 subs » (des clics de
tracking, affichés « subs ») : « j'ai l'impression que c'est faux pour le
calcul de la semaine ». Depuis : la semaine et le bonus du jour de Twitter
comptent les abonnés OF des trackings (Emy + sa variante Seren), comme la
quinzaine (« mesure_podium »).

Ce qui est vérifié :
  - _mesure_podium : « tracking_abonnes » pour Twitter, rien ailleurs ;
  - classement(mesure="tracking_abonnes") lit les abonnés (abonnes=True) ;
  - chaque calcul de la semaine et du bonus passe cette mesure (podium posé,
    rafraîchi, figé, semaine terminée, primes retenues, bonus du jour et de
    la veille) ;
  - les messages le disent : « Abonnés tracking OF via Twitter », plus
    « clics tracking OF ».

Aucun appel réseau. Lancement : python tests_podium_semaine_subs.py
"""
from __future__ import annotations

import datetime as dt
import inspect
import io
import pathlib
import sys

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import podium_discord as pd            # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


TW = pd.TWITTER_ID
check("Twitter : la semaine et le bonus aux abonnés", pd._mesure_podium(TW) == "tracking_abonnes")
check("… les autres serveurs gardent leur mesure",
      all(pd._mesure_podium(g) is None for g in pd.SERVEURS if g != TW))

vus = []
_vrai = pd._classement_tracking
try:
    pd._classement_tracking = lambda debut, fin, gid=None, abonnes=False, **kw: (
        vus.append(abonnes) or {"lignes": [], "illisibles": [], "frais": True})
    _g = pd._garder_repris
    pd._garder_repris = lambda *a, **k: None
    j = dt.date(2026, 10, 20)
    pd.classement(j, j, gid=TW, mesure=pd._mesure_podium(TW))
    pd.classement(j, j, gid=TW)
    check("classement : « tracking_abonnes » lit les abonnés, sans mesure les clics",
          vus == [True, False], vus)
finally:
    pd._classement_tracking = _vrai
    pd._garder_repris = _g

for f in (pd.poster_podium, pd.rafraichir, pd._figer_semaine, pd._semaine_terminee,
          pd._primes_retenues, pd._rafraichir_bonus_mypuls, pd._bonus_veille):
    src = inspect.getsource(f)
    appels = [l for l in src.splitlines() if "classement(" in l and "def " not in l
              and "_classement" not in l.split("classement(")[0][-1:]]
    check(f"{f.__name__} : chaque calcul passe la mesure du podium",
          appels and all("mesure=_mesure_podium(gid)" in l for l in appels), appels)

cl = {"lignes": [{"va": "VA 41", "clics": 152, "entite": "41"},
                 {"va": "VA 43", "clics": 84, "entite": "43"}],
      "illisibles": [], "frais": True}
e = pd.embed_podium(cl, dt.date(2026, 10, 19), dt.date(2026, 10, 24), en_cours=True, gid=TW)
# au format du bonus du jour depuis le 25/10/2026 (tests_minuteur.py) : plus d'en-tête
check("podium de Twitter : des subs, plus des « clics »",
      "**VA 41** — **152 subs** → **10$**" in e["description"]
      and "clics" not in e["description"], e["description"][:300])
b = pd.embed_bonus(cl, dt.date(2026, 10, 25), TW)
# le bonus du jour au format du 25/10/2026 : les abonnés en ligne, sans en-tête
check("bonus du jour de Twitter : les abonnés de chaque ligne, sans « clics »",
      "**VA 41** — **152 subs** → **5.00$**" in b["description"] and "clics" not in b["description"],
      b["description"][:200])

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
