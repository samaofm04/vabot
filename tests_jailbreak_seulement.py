"""Les models « Jailbreak seulement » (type_identite.JAILBREAK_SEULEMENT).

Propriétaire, 08/11/2026, devant la Bibliothèque où Lia venait d'apparaître :
« je veux pas Lia ici, je veux juste au niveau de Accounts … elle n'a pas de
photos, de vidéos et tout, comme pour Jessye ».

Ce que ce fichier prouve, sans réseau et sans rien écrire dans data/ :
  1. Une seule liste : le site, la rotation, /setidentite, les menus de
     models et la synchro Drive lisent tous type_identite.JAILBREAK_SEULEMENT
     (il y avait trois copies réduites à « jessye »).
  2. Lia en fait partie, comme Jessye.
  3. Par le vrai code : hors de la Bibliothèque, hors de la rotation des
     nouveaux VA, hors du menu des models US, hors du Drive (et dit comme
     tel) ; la page Jailbreak, elle, la garde.

    python tests_jailbreak_seulement.py
"""
from __future__ import annotations

import io
import os
import pathlib
import sys
import tempfile

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


import type_identite as ti  # noqa: E402

print("1. Une seule liste")
check("Jessye et Lia sont « Jailbreak seulement »", {"jessye", "lia"} <= set(ti.JAILBREAK_SEULEMENT))
check("la liste ne se modifie pas par accident (frozenset)", isinstance(ti.JAILBREAK_SEULEMENT, frozenset))

import gdrive_sync as gd  # noqa: E402
from cogs import welcome as we  # noqa: E402
from cogs import user as us  # noqa: E402
import web_upload as wu  # noqa: E402

for nom, valeur in (("web_upload.JAILBREAK_ONLY_IDENTITIES", wu.JAILBREAK_ONLY_IDENTITIES),
                    ("cogs/welcome.JAILBREAK_ONLY_IDENTITIES", we.JAILBREAK_ONLY_IDENTITIES),
                    ("cogs/user.EXCLURE_MENU", us.EXCLURE_MENU),
                    ("gdrive_sync.EXCLURE_DRIVE", gd.EXCLURE_DRIVE)):
    check(f"{nom} = la liste unique", set(valeur) == set(ti.JAILBREAK_SEULEMENT), sorted(valeur))
for f in ("cogs/admin.py", "cogs/bases_identite.py"):
    src = (BOT / f).read_text(encoding="utf-8")
    check(f"{f} : plus de repli réduit à « jessye »", '{"jessye"}' not in src)

print("2. Par le vrai code")
TOUTES = ["jessye", "julia", "lia", "lola"]
_vrai_li = wu._list_identities
wu._list_identities = lambda: list(TOUTES)
contenu = wu._list_content_identities()
wu._list_identities = _vrai_li
check("Bibliothèque : ni Jessye ni Lia, les autres oui",
      "lia" not in contenu and "jessye" not in contenu and {"julia", "lola"} <= set(contenu), contenu)

_vrai_wli, _vrai_act = we.list_identities, we.is_identity_active
we.list_identities = lambda *a, **k: list(TOUTES)
we.is_identity_active = lambda n: True
rotation = we.list_active_identities()
check("rotation des nouveaux VA : ni Jessye ni Lia", "lia" not in rotation and "jessye" not in rotation
      and {"julia", "lola"} <= set(rotation), rotation)
_vrai_mk, _vrai_pause = us._market_of, us._jb_en_pause
us._market_of = lambda n: "us"
us._jb_en_pause = lambda n: False
menu = us._jb_models_marche("us")
us._market_of, us._jb_en_pause = _vrai_mk, _vrai_pause
we.list_identities, we.is_identity_active = _vrai_wli, _vrai_act
check("menu des models US : ni Jessye ni Lia", "lia" not in menu and "jessye" not in menu
      and {"julia", "lola"} <= set(menu), menu)

tmp = pathlib.Path(tempfile.mkdtemp(prefix="jb_seul_"))
for n in TOUTES:
    (tmp / n).mkdir()
_vrai_dir = gd.IDENTITIES_DIR
gd.IDENTITIES_DIR = tmp
couvertes, exclues = gd._identites_a_sauvegarder()
gd.IDENTITIES_DIR = _vrai_dir
noms_couverts = {c[0].name for c in couvertes}
check("Drive : Lia et Jessye écartées, et dit pourquoi (pas en silence)",
      "lia" in exclues and "jessye" in exclues and "EXCLURE_DRIVE" in exclues.get("lia", ""), exclues)
check("Drive : les autres restent couvertes", noms_couverts == {"julia", "lola"}, noms_couverts)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for x in KO:
        print("  - " + x)
print("=" * 70)
sys.exit(1 if KO else 0)
