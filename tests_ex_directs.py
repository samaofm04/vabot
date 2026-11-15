"""Les liens passés de lien direct à page gardent leurs visites d'avant (15/11/2026).

Propriétaire : « les liens directs des VA, tu mets juste des landing pages à
la place ». Les 69 liens directs des VA de TRUST TWITTER et de TRUST THREADS
sont devenus des pages le 15/11 au soir, même identifiant. Constaté ce soir-là
sur 15 liens de Threads, du 1er au 15/11 : 286 visites, 0 clic de bouton — un
lien converti, relu comme une page, perdait toute sa quinzaine.

gms.boutons_par_pays compte donc un lien converti (gms.EX_DIRECTS) à ses
visites jusqu'au jour de la bascule inclus, à ses clics de bouton ensuite.
Sans réseau : gms._pays_par_metrique est remplacé.

Lancer depuis la racine du dépôt : python tests_ex_directs.py
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


import gms                # noqa: E402

APPELS = []
ECHEC = set()             # les métriques qui « échouent »


def _faux(ids, metric, d0, d1):
    APPELS.append((tuple(ids), metric, str(d0), str(d1)))
    if metric in ECHEC:
        return None, None
    # une visite vaut 10, un clic de bouton 1 : la somme dit ce qui a été lu
    n = (10 if metric == "pageviews" else 1) * len(ids)
    return n, {"US": n}


_vrai = gms._pays_par_metrique
gms._pays_par_metrique = _faux
try:
    print("1. Le registre")
    ex = gms.EX_DIRECTS
    check("69 liens convertis le 15/11 : 49 de Twitter, 20 de Threads, sans doublon",
          len(ex) == 69 and len(gms._PAGES_DU_15_11_TWITTER) == 49 and len(gms._PAGES_DU_15_11_THREADS) == 20
          and set(ex.values()) == {"2026-11-15"} and all(k.startswith("lnk_") and len(k) == 28 for k in ex), len(ex))
    CONVERTI = gms._PAGES_DU_15_11_THREADS[0]
    PAGE = "lnk_une_page_de_toujours"
    DIRECT = "lnk_un_lien_direct"

    print("2. Une page de toujours et un lien direct : rien ne change")
    APPELS.clear()
    t, p = gms.boutons_par_pays([PAGE, DIRECT], "2026-11-01", "2026-11-30", directs=[DIRECT])
    check("la page à ses clics de bouton, le direct à ses visites, sur toute la période",
          sorted(APPELS) == sorted([((PAGE,), "button_clicks", "2026-11-01", "2026-11-30"),
                                    ((DIRECT,), "pageviews", "2026-11-01", "2026-11-30")])
          and t == 11 and p == {"US": 11}, (APPELS, t, p))

    print("3. Un lien converti")
    APPELS.clear()
    t, _p = gms.boutons_par_pays([CONVERTI], "2026-11-01", "2026-11-15")
    check("période finie le jour de la bascule : ses visites, comme avant (les archives ne bougent pas)",
          APPELS == [((CONVERTI,), "pageviews", "2026-11-01", "2026-11-15")] and t == 10, APPELS)
    APPELS.clear()
    t, _p = gms.boutons_par_pays([CONVERTI], "2026-11-16", "2026-11-30")
    check("période commencée le lendemain : ses clics de bouton", APPELS == [
        ((CONVERTI,), "button_clicks", "2026-11-16", "2026-11-30")] and t == 1, APPELS)
    APPELS.clear()
    t, p = gms.boutons_par_pays([CONVERTI], "2026-11-10", "2026-11-20")
    check("période à cheval : visites jusqu'au 15 inclus + clics de bouton dès le 16, additionnés",
          APPELS == [((CONVERTI,), "pageviews", "2026-11-10", "2026-11-15"),
                     ((CONVERTI,), "button_clicks", "2026-11-16", "2026-11-20")]
          and t == 11 and p == {"US": 11}, (APPELS, t, p))
    APPELS.clear()
    t, _p = gms.boutons_par_pays([CONVERTI], "2024-01-01", "2026-11-15")
    check("l'all-time lu le soir de la bascule garde toutes ses visites (il retombait à 0)",
          APPELS == [((CONVERTI,), "pageviews", "2024-01-01", "2026-11-15")] and t == 10, APPELS)

    print("4. Mélangés, dans le même lot")
    APPELS.clear()
    t, _p = gms.boutons_par_pays([PAGE, CONVERTI, DIRECT], "2026-11-14", "2026-11-17", directs=[DIRECT])
    check("chacun dans sa mesure, rien de compté deux fois",
          sorted(APPELS) == sorted([((PAGE,), "button_clicks", "2026-11-14", "2026-11-17"),
                                    ((DIRECT,), "pageviews", "2026-11-14", "2026-11-17"),
                                    ((CONVERTI,), "pageviews", "2026-11-14", "2026-11-15"),
                                    ((CONVERTI,), "button_clicks", "2026-11-16", "2026-11-17")])
          and t == 1 + 10 + 10 + 1, (APPELS, t))
    APPELS.clear()
    gms.boutons_par_pays([CONVERTI], "2026-11-10", "2026-11-20", directs=[CONVERTI])
    check("un lien converti redevenu direct : ses visites sur toute la période",
          APPELS == [((CONVERTI,), "pageviews", "2026-11-10", "2026-11-20")], APPELS)

    print("5. Un appel raté : jamais un total partiel")
    ECHEC.add("button_clicks")
    r = gms.boutons_par_pays([CONVERTI], "2026-11-10", "2026-11-20")
    check("la moitié « clics de bouton » illisible : (None, None), pas les seules visites", r == (None, None), r)
    ECHEC.clear()
    check("aucun lien : (None, None)", gms.boutons_par_pays([], "2026-11-10", "2026-11-20") == (None, None))
finally:
    gms._pays_par_metrique = _vrai

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
