"""Va IG : le podium et la quinzaine disent « Instagram VA n ».

Propriétaire, 13/10/2026, devant le Championnat des subs de Va IG : « tu peux
écrire Instagram à la place de Jessye etc. » ; numéros : « Instagram VA n,
mêmes numéros » (deux models peuvent avoir chacune leur VA 2, c'est son choix).

Vérifié ici, sans réseau (rendu direct, têtes du thème coupées) :
  1. _marque : models FR, Amélia accentué, Jessye (VA US) ; pas un mot collé ;
     Twitter et Threads tels quels ;
  2. le podium de la semaine : lignes, primes, avertissements, plus aucun nom
     de model ;
  3. la quinzaine : lignes, totaux all-time GARDÉS (ils sont rangés sous
     « Amelia VA 3 »), avertissements ; pages mesurées après la marque ;
  4. sans la clé « marque », tout redevient comme avant.

Lancer depuis la racine du dépôt : python tests_podium_marque.py
"""
from __future__ import annotations

import datetime as dt
import io
import os
import pathlib
import re
import sys

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import podium_discord as pd             # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


IG, TW, TH = pd.VA_IG_ID if hasattr(pd, "VA_IG_ID") else "1505418484052394004", \
    pd.TWITTER_ID, "1498948161039896586"
MODELE = re.compile(r"\b(?:Amelia|Amélia|Emma|Sarah|Julia|Lola|Alicia|Jessye) VA \d")


def L(va, clics, numero=1, model=""):
    return {"va": va, "numero": numero, "clics": clics, "liens": 1, "spam": False, "model": model}


# ------------------------------------------------------------------ 1
print("\n— 1. _marque")
t = ("👑 **Jessye VA 28** — 462 subs\n11. Lola VA 2 — 171\n"
     "⚠️ Sans relevé : Jessye VA 5, Amélia VA 3, Sarah VA 12 — absent")
check("models FR, Amélia accentué et Jessye : « Instagram VA n », numéros gardés",
      pd._marque(IG, t) == ("👑 **Instagram VA 28** — 462 subs\n11. Instagram VA 2 — 171\n"
                            "⚠️ Sans relevé : Instagram VA 5, Instagram VA 3, Instagram VA 12 — absent"),
      pd._marque(IG, t))
check("un mot collé n'est pas un nom de model (« xLola VA 9 », « LolaVA 4 »)",
      pd._marque(IG, "xLola VA 9 LolaVA 4") == "xLola VA 9 LolaVA 4")
check("Twitter, Threads et un appel sans serveur : rien ne change",
      pd._marque(TW, t) == t and pd._marque(TH, t) == t and pd._marque(None, t) == t)

# ------------------------------------------------------------------ 2
print("\n— 2. le podium de la semaine")
cl = {"lignes": [L("Amelia VA 3", 40, 3, "amelia"), L("Lola VA 2", 12, 2, "lola")],
      "illisibles": ["Emma VA 7"], "frais": True}
us = {"lignes": [L("VA 28", 100, 28), L("VA 2", 5, 2)], "illisibles": ["VA 5"], "frais": True}
e = pd.embed_podium(cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18), en_cours=True,
                    gid=IG, us=us, tetes=False)
d = e["description"]
check("les lignes : « Instagram VA 28 » 1er (VA US), « Instagram VA 3 » 2e, primes à leur place",
      "**Instagram VA 28** — **100** subs" in d and "**Instagram VA 3** — **40** subs" in d
      and "**10$**" in d, d)
check("les avertissements aussi (classement incomplet, sans relevé)",
      "Classement incomplet** : Instagram VA 7" in d and "Sans relevé** : Instagram VA 5" in d, d)
check("plus aucun nom de model dans le message", not MODELE.search(d), MODELE.findall(d))

# ------------------------------------------------------------------ 3
print("\n— 3. la quinzaine")
ps = pd.pages_subs(cl, dt.date(2026, 10, 1), dt.date(2026, 10, 15),
                   {"Amelia VA 3": 900, "Lola VA 2": 50}, gid=IG, us=us,
                   totaux_us={"VA 28": 896}, tetes=False)
d = "\n".join(p["description"] for p in ps)
check("les totaux all-time restent ceux de chacun (rangés sous l'ancien nom)",
      "**Instagram VA 28** — **100** subs · 🌐 896 all-time" in d
      and "**Instagram VA 3** — **40** subs · 🌐 900 all-time" in d
      and "**Instagram VA 2** — **12** subs · 🌐 50 all-time" in d, d)
check("pied et avertissements sous la marque, aucun nom de model",
      "Instagram VA 7" in d and "Instagram VA 5" in d and not MODELE.search(d), MODELE.findall(d))
gros = {"lignes": [L(f"Amelia VA {n}", 1000 - n, n, "amelia") for n in range(1, 160)],
        "illisibles": [], "frais": True}
ps = pd.pages_subs(gros, dt.date(2026, 10, 1), dt.date(2026, 10, 15),
                   {f"Amelia VA {n}": 10 ** 6 for n in range(1, 160)}, gid=IG, tetes=False)
check("160 VA : plusieurs pages, chacune sous la limite de Discord une fois la marque posée",
      len(ps) > 1 and all(len(p["description"]) <= 4096 for p in ps)
      and sum(p["description"].count("Instagram VA") for p in ps) == 159,
      [len(p["description"]) for p in ps])

# ------------------------------------------------------------------ 4
print("\n— 4. sans la clé")
_m = pd.SERVEURS[IG].pop("marque")
try:
    d = pd.embed_podium(cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18), en_cours=True,
                        gid=IG, us=us, tetes=False)["description"]
finally:
    pd.SERVEURS[IG]["marque"] = _m
check("clé retirée : « Jessye VA 28 », « Amelia VA 3 », comme avant",
      "**Jessye VA 28**" in d and "**Amelia VA 3**" in d and "Instagram" not in d, d)

print(f"\nRESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
