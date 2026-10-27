"""Va IG : le podium et la quinzaine disent « Instagram VA n », sans doublon.

Propriétaire, 13/10/2026, devant le Championnat des subs de Va IG : « tu peux
écrire Instagram à la place de Jessye etc. », puis, devant deux « Instagram
VA 2 » : « donne-leur un numéro exprès pour que personne n'ait le même ». Le
14/10, devant « Instagram VA 236 » : « y a pas de VA comme ça, c'est faux » —
les numéros partent de 1, pour les seuls VA qui paraissent au classement.

Vérifié ici, sans réseau, DATA_DIR dans un dossier temporaire :
  1. numeros_instagram : à partir de 1, dans l'ordre (model, numéro), les
     seuls VA vus ; un numéro donné ne change plus ; un nouveau prend le
     suivant ; `eviter` est sauté ;
  2. _marque : chaque VA FR son numéro ; Amélia accentué ; pas un mot collé ;
     Twitter et Threads tels quels, sans rien écrire ;
  3. le podium de la semaine (Va IG seul, comme en production) : lignes,
     primes, avertissements ; aucun nom de model, aucun libellé en double ;
     sans le thème Mario (🥇🥈🥉, comme les autres serveurs) ;
  4. VA US remêlés (« avec_us ») : leurs numéros ne sont donnés à aucun VA FR ;
  5. la quinzaine : totaux all-time GARDÉS ; pages sous la limite, sans doublon ;
  6. sans la clé « marque », tout redevient comme avant, et rien n'est écrit.

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
# les noms seulement : ses chiffres d'exemple sont sous le minimum de la semaine
# de Va IG (100 subs depuis le 27/10/2026, tests_podium_va_ig_subs.py)
pd.MINIMUM_SEMAINE = {k: v for k, v in pd.MINIMUM_SEMAINE.items() if k != IG}
MODELE = re.compile(r"\b(?:Amelia|Amélia|Emma|Sarah|Julia|Lola|Alicia|Jessye) VA \d")
LIBELLE = re.compile(r"Instagram VA (\d+)")


def L(va, clics, numero=1, model=""):
    return {"va": va, "numero": numero, "clics": clics, "liens": 1, "spam": False, "model": model}


def table():
    f = TMP / "numeros_va_instagram.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def nouveau_bac():
    global TMP
    TMP = pathlib.Path(tempfile.mkdtemp(prefix="podium_marque_"))
    pd.DATA_DIR = TMP
    (TMP / "podium_trackings.json").write_text(json.dumps({"trackings": {
        "emy.brw/c1": {"numero": 1, "spam": False, "premier": "2026-10-01", "vu": "2026-10-13", "actif": True},
        "emy.brw/c2": {"numero": 2, "spam": False, "premier": "2026-10-01", "vu": "2026-10-13", "actif": True}},
        "attente": {}}), encoding="utf-8")
    BACS.append(TMP)


BACS = []
TMP = None
_DATA = pd.DATA_DIR
try:
    nouveau_bac()
    # -------------------------------------------------------------- 1
    print("\n— 1. les numéros Instagram des VA FR")
    t = pd.numeros_instagram({"lola:2", "amelia:43", "lola:22", "amelia:3"})
    check("à partir de 1, dans l'ordre (model, numéro), les seuls VA vus",
          t == {"amelia:3": 1, "amelia:43": 2, "lola:2": 3, "lola:22": 4}, t)
    check("gardés sur disque, dans une table neuve", table() == t
          and not (TMP / "numeros_instagram.json").exists())
    t2 = pd.numeros_instagram({"lola:7", "amelia:3"})
    check("un numéro donné ne change plus ; un nouveau VA (Lola VA 7) prend le suivant",
          all(t2[k] == v for k, v in t.items()) and t2["lola:7"] == 5, t2)
    check("`eviter` est sauté", pd.numeros_instagram({"emma:9"}, eviter={6})["emma:9"] == 7)

    # -------------------------------------------------------------- 2
    print("\n— 2. _marque")
    txt = "11. Lola VA 2 — 171\n⚠️ Sans relevé : Amélia VA 3, Amelia VA 43 — absents"
    check("chaque VA FR son numéro (Lola VA 2 → 3, Amélia VA 3 → 1, Amelia VA 43 → 2)",
          pd._marque(IG, txt) == "11. Instagram VA 3 — 171\n⚠️ Sans relevé : Instagram VA 1, "
                                 "Instagram VA 2 — absents", pd._marque(IG, txt))
    check("un mot collé n'est pas un nom de model (« xLola VA 9 », « LolaVA 4 »)",
          pd._marque(IG, "xLola VA 9 LolaVA 4") == "xLola VA 9 LolaVA 4")
    avant = table()
    check("Twitter, Threads et un appel sans serveur : rien ne change, rien n'est écrit",
          pd._marque(TW, txt) == txt and pd._marque(TH, txt) == txt and pd._marque(None, txt) == txt
          and table() == avant)

    # -------------------------------------------------------------- 3
    print("\n— 3. le podium de la semaine, comme en production")
    nouveau_bac()
    check("le profil livré : ni thème Mario, ni VA US", not pd._profil(IG).get("theme")
          and not pd._mele(IG) and not pd._theme(IG))
    cl = {"lignes": [L("Amelia VA 3", 40, 3, "amelia"), L("Lola VA 2", 12, 2, "lola"),
                     L("Amelia VA 2", 9, 2, "amelia")], "illisibles": ["Lola VA 22"], "frais": True}
    d = pd.embed_podium(cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18), en_cours=True,
                        gid=IG, tetes=False)["description"]
    vus = [l for l in d.split("\n") if re.match(r"^(\S+ \*\*|\d+\. )", l) and " subs" in l]
    nums = [LIBELLE.search(l).group(1) for l in vus if LIBELLE.search(l)]
    check("les lignes : 🥇🥈🥉 comme les autres serveurs, numéros 1 à 3, primes à leur place",
          vus[:3] == ["🥇 **Instagram VA 2** — **40** subs · 💰 **10$**",
                      "🥈 **Instagram VA 3** — **12** subs · 💰 **5$**",
                      "🥉 **Instagram VA 1** — **9** subs · 💰 **3$**"], vus)
    check("l'avertissement aussi, et plus aucun nom de model ni libellé en double",
          "Instagram VA 4" in d and not MODELE.search(d) and len(set(nums)) == len(nums) == 3,
          (MODELE.findall(d), nums))
    check("plus de vocabulaire Mario (🪙, Grand Prix, course)",
          "🪙" not in d and "course" not in d.lower(), d)

    # -------------------------------------------------------------- 4
    print("\n— 4. si les VA US revenaient (« avec_us »)")
    nouveau_bac()
    pd.SERVEURS[IG]["avec_us"] = True
    try:
        us = {"lignes": [L("VA 1", 100, 1), L("VA 2", 5, 2)], "illisibles": [], "frais": True}
        d = pd.embed_podium(cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18), en_cours=True,
                            gid=IG, us=us, tetes=False)["description"]
    finally:
        pd.SERVEURS[IG].pop("avec_us", None)
    nums = [LIBELLE.search(l).group(1) for l in d.split("\n") if " subs" in l and LIBELLE.search(l)]
    check("les numéros du registre (1, 2) ne sont donnés à aucun VA FR : pas de doublon",
          sorted(nums) == ["1", "2", "3", "4", "5"] and len(set(nums)) == 5
          and all(v not in (1, 2) for v in table().values()), (nums, table()))

    # -------------------------------------------------------------- 5
    print("\n— 5. la quinzaine")
    nouveau_bac()
    ps = pd.pages_subs(cl, dt.date(2026, 10, 1), dt.date(2026, 10, 15),
                       {"Amelia VA 3": 900, "Lola VA 2": 50}, gid=IG, tetes=False)
    d = "\n".join(p["description"] for p in ps)
    check("les totaux all-time restent ceux de chacun (rangés sous l'ancien nom)",
          "**Instagram VA 2** — **40** subs · 🌐 900 all-time" in d
          and "**Instagram VA 3** — **12** subs · 🌐 50 all-time" in d, d)
    gros = {"lignes": [L(f"Amelia VA {n}", 1000 - n, n, "amelia") for n in range(1, 160)]
            + [L(f"Lola VA {n}", 10 + n, n, "lola") for n in range(1, 40)],
            "illisibles": [], "frais": True}
    ps = pd.pages_subs(gros, dt.date(2026, 10, 1), dt.date(2026, 10, 15),
                       {f"Amelia VA {n}": 10 ** 6 for n in range(1, 160)}, gid=IG, tetes=False)
    tous = [int(n) for p in ps for n in LIBELLE.findall(p["description"])]
    doubles = [n for n, k in collections.Counter(tous).items() if k > 1]
    check("198 VA (159 Amelia, 39 Lola) : pages sous la limite, numéros 1 à 198 sans doublon",
          len(ps) > 1 and all(len(p["description"]) <= 4096 for p in ps)
          and sorted(tous) == list(range(1, 199)) and not doubles,
          ([len(p["description"]) for p in ps], len(tous), doubles))

    # -------------------------------------------------------------- 6
    print("\n— 6. sans la clé")
    nouveau_bac()
    _m = pd.SERVEURS[IG].pop("marque")
    try:
        d = pd.embed_podium(cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18), en_cours=True,
                            gid=IG, tetes=False)["description"]
    finally:
        pd.SERVEURS[IG]["marque"] = _m
    check("clé retirée : « Amelia VA 3 », comme avant, rien d'écrit",
          "**Amelia VA 3**" in d and "Instagram VA" not in d and table() == {}, d)

    # -------------------------------------------------------------- 7
    # Propriétaire, 27/10/2026 : Lumière, 1re (« Instagram VA 4 » au podium),
    # lisait « Amelia VA 46 » dans son avis de prime -- il a cru que les subs
    # du 1er étaient allés chez une autre.
    print("\n— 7. l'avis de prime dit le nom du podium")
    nouveau_bac()
    import types
    import liens_fr
    import requests
    import safe_json
    import suivi_va as sv
    d = pd.embed_podium(cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18), en_cours=False,
                        gid=IG, tetes=False)["description"]
    publics = re.findall(r"^\S+ \*\*(Instagram VA \d+)\*\* — \*\*(\d+)\*\* subs · 💰", d, re.M)
    (TMP / "numeros_va_fr.json").write_text(json.dumps(
        {"amelia": {"u3": 3, "u2": 2}, "lola": {"u5": 2}}), encoding="utf-8")
    users = {u: {"channel_id": f"salon-{u}"} for u in ("u2", "u3", "u5")}
    annonces = []
    vrai_load = safe_json.load
    sauve = (liens_fr.NUMEROS, safe_json.load, requests.post, sv.ETAT_FICHIER,
             os.environ.get("DISCORD_TOKEN"))
    try:
        liens_fr.NUMEROS = TMP / "numeros_va_fr.json"
        sv.ETAT_FICHIER = TMP / "suivi_va.json"
        safe_json.load = lambda chemin, default=None: (
            users if pathlib.Path(chemin).name == "users.json" else vrai_load(chemin, default=default))
        requests.post = lambda url, timeout=None, headers=None, json=None: (
            annonces.append(json) or types.SimpleNamespace(status_code=200))
        os.environ["DISCORD_TOKEN"] = "faux-jeton"
        b = sv._annoncer_primes_fr(IG, cl, dt.date(2026, 10, 12), dt.date(2026, 10, 18))
    finally:
        liens_fr.NUMEROS, safe_json.load, requests.post, sv.ETAT_FICHIER = sauve[:4]
        if sauve[4] is None:
            os.environ.pop("DISCORD_TOKEN", None)
        else:
            os.environ["DISCORD_TOKEN"] = sauve[4]
    prives = [re.search(r"· \*\*(.+?)\*\* · \*\*(\d+)\*\* subs", a["embeds"][0]["description"]).groups()
              for a in annonces]
    textes = " ".join(a["embeds"][0]["description"] for a in annonces)
    check("chaque gagnant lit en privé le nom et les subs de SA ligne du podium",
          len(publics) == 3 and prives == publics, (prives, publics))
    check("aucun nom de model dans l'avis privé", not MODELE.search(textes), textes)
    check("le bilan (journal du propriétaire) garde le nom interne",
          b["dits"] == ["Amelia VA 3 : 10.00$", "Lola VA 2 : 5.00$", "Amelia VA 2 : 3.00$"], b)
finally:
    pd.DATA_DIR = _DATA
    for b in BACS:
        shutil.rmtree(b, ignore_errors=True)

print(f"\nRESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
