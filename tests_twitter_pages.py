"""TRUST TWITTER en pages, comme TRUST INSTAGRAM (03/11/2026).

Propriétaire : « mets aussi des landing pages pour Twitter comme pour IG ».
Les liens existants ont été passés en page ce soir-là ; ce fichier prouve que
les liens NEUFS naissent en page, sans réseau :
  1. espace(Twitter) : gabarit = la page modèle, landing, et les copies des
     branches de l'A/B partent de l'ancien gabarit DIRECT (source_variante).
  2. creer_gms sur Twitter : copie de la page sans adresse, puis le tracking
     du VA posé sur son bouton OnlyFans (comme Agency).
  3. Threads et Agency ne bougent pas.

Lancer depuis la racine du dépôt : python tests_twitter_pages.py
"""
from __future__ import annotations

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


import liens_va as lv     # noqa: E402
import gms                # noqa: E402

DIRECT = "lnk_ancien_direct"
lv.config = lambda: {"gabarit": DIRECT, "equipe": "tm_twitter", "modele": "Lia"}

print("1. L'espace Twitter")
e = lv.espace(lv.TWITTER_ID)
check("gabarit = la page modèle, en page", e["gabarit"] == lv.GABARIT_PAGE_TWITTER and e.get("landing") is True, e)
check("les copies des branches de l'A/B partent de l'ancien gabarit direct", e.get("source_variante") == DIRECT, e)
check("espace() sans serveur = Twitter, pareil", lv.espace("")["gabarit"] == lv.GABARIT_PAGE_TWITTER)
check("la Lia seule (70/30) reste", e.get("base_seule") == lv.LIA_SEULE, e.get("base_seule"))

print("2. Un lien neuf sur Twitter")
APPELS = []


def _dup(src, sc, nom, url="", team=None):
    APPELS.append(("dup", src, url, team))
    return {"ok": True, "link": {"id": "lnk_neuf", "shortcode": sc}}


def _tool(nom, args):
    APPELS.append((nom, args.get("link_id")))
    if nom == "get_link":
        return {"ok": True, "data": {"buttons": [{"label": "“exclusive” stuff lol", "url": BOUTONS[0]}]}}
    if nom == "update_link":
        BOUTONS[0] = args["buttons"][0]["url"]
        return {"ok": True}
    return {"ok": True}


BOUTONS = ["https://onlyfans.com/liasxcret"]
_d, _t = gms.duplicate_link, gms._call_tool
gms.duplicate_link, gms._call_tool = _dup, _tool
try:
    r = lv.creer_gms("Twitter VA 200 @essai", "https://onlyfans.com/liasxcret/c999", lv.TWITTER_ID)
finally:
    gms.duplicate_link, gms._call_tool = _d, _t
dups = [a for a in APPELS if a[0] == "dup"]
check("copie de la PAGE modèle, sans adresse (une page n'en prend pas)",
      dups and dups[0][1] == lv.GABARIT_PAGE_TWITTER and dups[0][2] == "", dups)
check("le tracking du VA posé sur le bouton OnlyFans", r.get("ok") and BOUTONS[0] == "https://onlyfans.com/liasxcret/c999",
      (r, BOUTONS))

print("2b. Bénin et Madagascar gardent le tracking, comme les US (03/11)")
geo = lv.regles_pays("https://onlyfans.com/liasxcret")
codes = {x["country_code"] for x in geo}
check("BJ et MG ne sont pas renvoyés vers le compte de base, les US non plus ; FR oui",
      not ({"BJ", "MG", "US", "CA", "AU", "GB", "NZ", "IE"} & codes) and "FR" in codes and len(geo) == 248, len(geo))

print("3. Threads et Agency ne bougent pas")
check("Threads : pas la page Twitter", lv.espace(lv.THREADS_ID).get("gabarit") != lv.GABARIT_PAGE_TWITTER)
check("Agency : sa page à elle", lv.espace(lv.AGENCY_IG_ID).get("gabarit") == lv.ESPACE_AGENCY_IG["gabarit"])

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
