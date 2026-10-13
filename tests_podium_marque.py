"""Va IG : le podium et la quinzaine disent « Instagram VA n », sans doublon.

Propriétaire, 13/10/2026, devant le Championnat des subs de Va IG : « tu peux
écrire Instagram à la place de Jessye etc. », puis, devant les deux
« Instagram VA 2 » (Jessye VA 2 et Lola VA 2) : « donne-leur un numéro exprès
pour que personne n'ait le même ».

Vérifié ici, sans réseau, DATA_DIR dans un dossier temporaire :
  1. numeros_instagram : chaque VA FR (model, numéro) reçoit un numéro à
     partir de 100, dans l'ordre (model, numéro) ; un numéro du registre US
     est sauté ; un numéro donné ne change plus ; un nouveau prend le suivant ;
  2. _marque : VA US « Instagram VA <son numéro> », VA FR « Instagram VA
     <le sien> » ; Amélia accentué ; pas un mot collé ; Twitter et Threads
     tels quels ;
  3. le podium de la semaine : lignes, primes, avertissements ; aucun nom de
     model, aucun libellé en double ;
  4. la quinzaine : totaux all-time GARDÉS (rangés sous « Amelia VA 3 ») ;
     pages mesurées après la marque ;
  5. sans la clé « marque », tout redevient comme avant, et rien n'est écrit.

Lancer depuis la racine du dépôt : python tests_podium_marque.py
"""
from __future__ import annotations

import collections
import datetime as dt
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

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


IG, TW, TH = "1505418484052394004", pd.TWITTER_ID, "1498948161039896586"
MODELE = re.compile(r"\b(?:Amelia|Amélia|Emma|Sarah|Julia|Lola|Alicia|Jessye) VA \d")
LIBELLE = re.compile(r"Instagram VA (\d+)")


def L(va, clics, numero=1, model=""):
    return {"va": va, "numero": numero, "clics": clics, "liens": 1, "spam": False, "model": model}


def ecrire(nom, d):
    (TMP / nom).write_text(json.dumps(d), encoding="utf-8")


def table():
    f = TMP / "numeros_instagram.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


TMP = pathlib.Path(tempfile.mkdtemp(prefix="podium_marque_"))
_DATA = pd.DATA_DIR
pd.DATA_DIR = TMP
try:
    # les VA FR connus, et un registre US dont le VA 101 tombe dans la plage
    ecrire("numeros_va_fr.json", {"lola": {"u1": 2, "u2": 22}, "amelia": {"u1": 3, "u3": 43}})
    ecrire("podium_trackings.json", {"trackings": {
        "emy.brw/c1": {"numero": 2, "spam": False, "premier": "2026-10-01", "vu": "2026-10-13", "actif": True},
        "emy.brw/c2": {"numero": 101, "spam": False, "premier": "2026-10-01", "vu": "2026-10-13", "actif": True}},
        "attente": {}})

    # -------------------------------------------------------------- 1
    print("\n— 1. les numéros Instagram des VA FR")
    t = pd.numeros_instagram()
    check("tous les VA FR connus, à partir de 100, dans l'ordre (model, numéro), 101 (registre US) sauté",
          t == {"amelia:3": 100, "amelia:43": 102, "lola:2": 103, "lola:22": 104}, t)
    check("gardés sur disque", table() == t)
    ecrire("numeros_va_fr.json", {"lola": {"u2": 22, "u1": 2, "u9": 7}, "amelia": {"u3": 43, "u1": 3}})
    t2 = pd.numeros_instagram()
    check("un numéro donné ne change plus ; un nouveau VA (Lola VA 7) prend le suivant",
          all(t2[k] == v for k, v in t.items()) and t2["lola:7"] == 105, t2)
    check("une clé vue dans un texte mais inconnue du fichier est numérotée aussi",
          pd.numeros_instagram({"emma:9"})["emma:9"] == 106)

    # -------------------------------------------------------------- 2
    print("\n— 2. _marque")
    txt = ("👑 **Jessye VA 2** — 462 subs\n11. Lola VA 2 — 171\n"
           "⚠️ Sans relevé : Jessye VA 5, Amélia VA 3 — absent")
    check("VA US : son numéro ; VA FR : le sien — plus deux « Instagram VA 2 »",
          pd._marque(IG, txt) == ("👑 **Instagram VA 2** — 462 subs\n11. Instagram VA 103 — 171\n"
                                  "⚠️ Sans relevé : Instagram VA 5, Instagram VA 100 — absent"),
          pd._marque(IG, txt))
    check("un mot collé n'est pas un nom de model (« xLola VA 9 », « LolaVA 4 »)",
          pd._marque(IG, "xLola VA 9 LolaVA 4") == "xLola VA 9 LolaVA 4")
    avant = table()
    check("Twitter, Threads et un appel sans serveur : rien ne change, rien n'est écrit",
          pd._marque(TW, txt) == txt and pd._marque(TH, txt) == txt and pd._marque(None, txt) == txt
          and table() == avant)

    # -------------------------------------------------------------- 3
    print("\n— 3. le podium de la semaine")
    cl = {"lignes": [L("Amelia VA 3", 40, 3, "amelia"), L("Lola VA 2", 12, 2, "lola")],
          "illisibles": ["Lola VA 22"], "frais": True}
    us = {"lignes": [L("VA 28", 100, 28), L("VA 2", 5, 2)], "illisibles": ["VA 5"], "frais": True}
    d = pd.embed_podium(cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18), en_cours=True,
                        gid=IG, us=us, tetes=False)["description"]
    check("les lignes : VA US 28 1er, Amelia VA 3 → Instagram VA 100 2e, primes à leur place",
          "**Instagram VA 28** — **100** subs" in d and "**Instagram VA 100** — **40** subs" in d
          and "**10$**" in d, d)
    check("les avertissements aussi (classement incomplet, sans relevé)",
          "Classement incomplet** : Instagram VA 104" in d and "Sans relevé** : Instagram VA 5" in d, d)
    vus = [l for l in d.split("\n") if re.match(r"^(\S+ \*\*|\d+\. )", l) and " subs" in l]
    nums = [LIBELLE.search(l).group(1) for l in vus if LIBELLE.search(l)]
    check("plus aucun nom de model, et aucun libellé en double (Jessye VA 2 ≠ Lola VA 2)",
          not MODELE.search(d) and len(nums) == 4 and len(set(nums)) == 4, (MODELE.findall(d), nums))

    # -------------------------------------------------------------- 4
    print("\n— 4. la quinzaine")
    ps = pd.pages_subs(cl, dt.date(2026, 10, 1), dt.date(2026, 10, 15),
                       {"Amelia VA 3": 900, "Lola VA 2": 50}, gid=IG, us=us,
                       totaux_us={"VA 28": 896}, tetes=False)
    d = "\n".join(p["description"] for p in ps)
    check("les totaux all-time restent ceux de chacun (rangés sous l'ancien nom)",
          "**Instagram VA 28** — **100** subs · 🌐 896 all-time" in d
          and "**Instagram VA 100** — **40** subs · 🌐 900 all-time" in d
          and "**Instagram VA 103** — **12** subs · 🌐 50 all-time" in d, d)
    check("pied et avertissements sous la marque, aucun nom de model",
          "Instagram VA 104" in d and "Instagram VA 5" in d and not MODELE.search(d), MODELE.findall(d))
    gros = {"lignes": [L(f"Amelia VA {n}", 1000 - n, n, "amelia") for n in range(1, 160)]
            + [L(f"Lola VA {n}", 10 + n, n, "lola") for n in range(1, 40)],
            "illisibles": [], "frais": True}
    ps = pd.pages_subs(gros, dt.date(2026, 10, 1), dt.date(2026, 10, 15),
                       {f"Amelia VA {n}": 10 ** 6 for n in range(1, 160)}, gid=IG, tetes=False,
                       us={"lignes": [L(f"VA {n}", 5, n) for n in range(1, 40)], "illisibles": [],
                           "frais": True})
    tous = [n for p in ps for n in LIBELLE.findall(p["description"])]
    doubles = [n for n, k in collections.Counter(tous).items() if k > 1]
    check("237 VA (159 Amelia, 39 Lola, 39 US) : plusieurs pages sous la limite de Discord, "
          "pas un libellé en double",
          len(ps) > 1 and all(len(p["description"]) <= 4096 for p in ps)
          and len(tous) == 237 and not doubles, ([len(p["description"]) for p in ps], len(tous), doubles))

    # -------------------------------------------------------------- 5
    print("\n— 5. sans la clé")
    _m = pd.SERVEURS[IG].pop("marque")
    avant = table()
    try:
        d = pd.embed_podium(cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18), en_cours=True,
                            gid=IG, us=us, tetes=False)["description"]
    finally:
        pd.SERVEURS[IG]["marque"] = _m
    check("clé retirée : « Jessye VA 28 », « Amelia VA 3 », comme avant, rien d'écrit",
          "**Jessye VA 28**" in d and "**Amelia VA 3**" in d and "Instagram" not in d
          and table() == avant, d)
finally:
    pd.DATA_DIR = _DATA
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nRESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
