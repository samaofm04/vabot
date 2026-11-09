"""Un compte OnlyFans renommé : Emy, « emy.brw » devenue « emy.brww » (03/11/2026).

MyPuls ne rend plus que onlyfans.com/emy.brww/cN ; les fiches des VA, le
registre du podium et les relevés gardent emy.brw/cN. Sans équivalence, un
tracking semblait disparu et 37 VA avaient leurs subs « pas lisibles ».

Ce que ce fichier prouve, sans réseau et sans rien écrire dans le vrai data/ :
  1. podium_discord.tracking_de ramène l'adresse nouvelle à la clé ancienne ;
     les autres comptes ne bougent pas.
  2. subs_va._subs_of compte un tracking gardé « emy.brw » que MyPuls rend
     « emy.brww ».
  3. La page Emy (infloww_liens) : code_de_l_url, _suivi_de et la lecture
     MyPuls acceptent les deux pseudos.
  4. La page perso du VA (stats_va._codes) aussi.

Lancer depuis la racine du dépôt : python tests_pseudo_renomme.py
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


import podium_discord as pod    # noqa: E402
import subs_va                  # noqa: E402
import infloww_liens as il      # noqa: E402
import stats_va                 # noqa: E402

print("1. La clé d'un tracking")
check("emy.brww/c117 → emy.brw/c117", pod.tracking_de("https://onlyfans.com/emy.brww/c117") == "emy.brw/c117")
check("l'ancienne adresse ne change pas", pod.tracking_de("https://onlyfans.com/Emy.Brw/c042/") == "emy.brw/c42")
check("les autres comptes ne bougent pas",
      pod.tracking_de("https://onlyfans.com/liasxcret/c104") == "liasxcret/c104"
      and pod.tracking_de("https://onlyfans.com/seren.vale/c236") == "seren.vale/c236"
      and pod.pseudo_of("Emy.Brww") == "emy.brw" and pod.pseudo_of("jessyewdiference") == "jessyewdiference")

print("2. Les subs d'un VA")
_lire = pod._lire_mypuls
vus = {pod.tracking_de(u): {"subs": s, "visites": 1, "total": 1, "subs_total": s, "nom": "x"}
       for u, s in (("https://onlyfans.com/emy.brww/c117", 2), ("https://onlyfans.com/liasxcret/c104", 3))}
pod._lire_mypuls = lambda a, b, forcer=False: (vus, "")
try:
    n = subs_va._subs_of(["https://onlyfans.com/emy.brw/c117", "https://onlyfans.com/liasxcret/c104"],
                         "2026-10-16", "2026-10-31")
finally:
    pod._lire_mypuls = _lire
check("le tracking gardé emy.brw est trouvé dans la réponse emy.brww (2 + 3)", n == 5, n)

print("3. La page Emy")
emy = il.profil("emy")
check("code_de_l_url accepte emy.brww sur la page Emy",
      emy.code_de_l_url("https://onlyfans.com/emy.brww/c66") == ("66", "")
      and emy.code_de_l_url("https://onlyfans.com/emy.brw/c66") == ("66", ""))
check("_suivi_de : la clé du registre", il._suivi_de("https://onlyfans.com/emy.brww/c40") == "emy.brw/c40")
rep = {"data": {"data": [{"url": "https://onlyfans.com/emy.brww/c66", "name": "Twitter VA 1",
                          "subscribers_period": 4, "visits_period": 10, "revenue": {"total": 2.5}},
                         {"url": "https://onlyfans.com/liasxcret/c66", "name": "Lia",
                          "subscribers_period": 9, "visits_period": 9, "revenue": {"total": 1}}],
                "count": 2, "period": {"from": "2026-11-01", "to": "2026-11-03"}}}
# Le mécanisme d'alias, sans compte imposé (comme avant le 09/11/2026)
_cid = emy.MYPULS_CREATOR_ID
emy.MYPULS_CREATOR_ID = None
try:
    lu = emy._lire_mypuls(rep["data"])
finally:
    emy.MYPULS_CREATOR_ID = _cid
codes = [(x["code"], x["abonnes"]) for x in lu.get("liens") or []]
check("lecture MyPuls (sans compte imposé) : la ligne emy.brww comptée, celle de Lia non", codes == [("66", 4)], lu)
# Depuis le 09/11/2026, la page Emy lit la NOUVELLE Emy (MyPuls 4126, emy.brw) :
# une ligne de l'ancienne (3352, rendue emy.brww) ne compte plus, même code
rep2 = {"data": [{"url": "https://onlyfans.com/emy.brww/c66", "name": "ancienne", "creator_id": 3352,
                  "subscribers_period": 4, "visits_period": 10, "revenue": {"total": 2.5}},
                 {"url": "https://onlyfans.com/emy.brw/c66", "name": "nouvelle", "creator_id": 4126,
                  "subscribers_period": 7, "visits_period": 10, "revenue": {"total": 1}},
                 {"url": "https://onlyfans.com/liasxcret/c66", "name": "Lia", "creator_id": 3992,
                  "subscribers_period": 9, "visits_period": 9, "revenue": {"total": 1}}]}
lu2 = emy._lire_mypuls(rep2)
codes2 = [(x["code"], x["abonnes"]) for x in lu2.get("liens") or []]
check("page Emy : seule la nouvelle Emy (4126) est lue, ni l'ancienne ni Lia", codes2 == [("66", 7)], lu2)

print("4. La page perso du VA")
check("stats_va._codes : un tracking emy.brww compte pour emy.brw",
      stats_va._codes(["https://onlyfans.com/emy.brww/c117", "https://onlyfans.com/emy.brw/c118"], "emy.brw")
      == ["117", "118"])

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
