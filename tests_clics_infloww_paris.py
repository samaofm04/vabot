"""Clics Infloww d'un lien créé juste après minuit (04/11/2026).

Twitter VA 166 : son lien c119, créé le 01/11 à 00h10 à Paris, était daté
« 31/10 » par Infloww (UTC). Sa quinzaine du 01/11 cherchait alors le relevé
du 31/10, qu'il ne pouvait pas avoir, et ses 42 clics restaient « — » sur sa
page perso. Ce fichier prouve que la date de création est celle de Paris, et
qu'un lien créé pendant la période part de 0 ; un lien plus ancien, lui,
garde le cumul de la veille comme point de départ.

Lancer depuis la racine du dépôt : python tests_clics_infloww_paris.py
"""
from __future__ import annotations

import datetime as dt
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


import infloww_liens as il   # noqa: E402
import safe_json             # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp())
il.RELEVES_CVR_FICHIER = TMP / "releves.json"
# le relevé du 31/10 : c75 existait (1571 clics), c119 pas encore
safe_json.write(il.RELEVES_CVR_FICHIER, {"jours": {"2026-10-31": {"75": 1571}}, "crees": {"75": "2026-10-27"}})
LIENS = [{"code": "119", "clics": 42, "cree": "2026-10-31", "cree_ms": 1793488250000},   # 01/11 00h10 Paris
         {"code": "75", "clics": 2288, "cree": "2026-10-27", "cree_ms": 1793144016000},
         {"code": "200", "clics": 5, "cree": "2026-10-31"}]                               # sans cree_ms
il._infloww = lambda c: {"liens": LIENS}
il._aujourdhui = lambda: "2026-11-04"

rel = il._noter_releve(LIENS, "2026-11-04")
check("c119 : créé le 01/11 (Paris), pas le 31/10 (UTC)", rel["crees"].get("119") == "2026-11-01", rel["crees"])
check("sans cree_ms : la date d'Infloww telle quelle", rel["crees"].get("200") == "2026-10-31", rel["crees"])
m, _r = il._clics_cvr("2026-11-01", "2026-11-04")
check("c119 sur la quinzaine du 01/11 : ses 42 clics, partis de 0", m.get("119") == 42, m)
check("c75 (plus ancien) : le cumul d'aujourd'hui moins celui du 31/10", m.get("75") == 2288 - 1571, m)
check("c200 (31/10, pas de relevé ce jour-là) : absent, jamais un zéro inventé", "200" not in m, m)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
