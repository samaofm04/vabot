"""Les clics GetMySocial ne sont pas relus plus d'une fois par heure.

Propriétaire, 06/10/2026 : « pour les clics fais un refresh toutes les 1h, pas
avant ; là je crois c'est toutes les 5 minutes ». Le widget des VA était relu
toutes les 5 minutes, le report Discord toutes les 30 minutes et à chaque
redémarrage (29 le 05/10), le cache commun des clics ne gardait un relevé que
90 secondes.

Vérifié ici sans réseau ni vrai data/.
Lancer depuis la racine du dépôt : python tests_clics_heure.py
"""
from __future__ import annotations

import datetime as dt
import io
import pathlib
import shutil
import sys
import tempfile
import time

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import gms                              # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


APPELS = []
REPONSE = {"v": {"ok": True, "data": {"total_clicks": 7, "top_countries": [
    {"country_code": "US", "count": 5}]}}}
_vrai_overview = gms.get_analytics_overview
TMP = pathlib.Path(tempfile.mkdtemp(prefix="clics_heure_"))
try:
    gms.get_analytics_overview = lambda s="", e="", link_ids=None: (
        APPELS.append((s, e, tuple(link_ids or ()))) or REPONSE["v"])

    print("\n— 1. le cache commun des clics : une heure")
    gms._ANA_CACHE.clear()
    check("une heure pour une période en cours comme pour une période close",
          gms.TTL_OUVERT == 3600 and gms.TTL_ANALYTICS == 3600)
    jour = gms._jour_paris()
    gms.analytics_for_link("lnk_a", jour, jour)
    gms.analytics_for_link("lnk_a", jour, jour)
    check("le même relevé relu dans l'heure ne repart pas chez GetMySocial", len(APPELS) == 1)
    cle = next(iter(gms._ANA_CACHE))
    gms._ANA_CACHE[cle] = (time.time() - 3601, gms._ANA_CACHE[cle][1])
    gms.analytics_for_link("lnk_a", jour, jour)
    check("au-delà d'une heure, il est relu", len(APPELS) == 2)
    check("la clé du jour est la date de PARIS (le VPS tourne en UTC)",
          cle[3] == jour == dt.datetime.now(__import__("zoneinfo").ZoneInfo("Europe/Paris"))
          .strftime("%Y-%m-%d"), cle)

    print("\n— 2. le report et Mes clics passent par ce cache")
    gms._ANA_CACHE.clear()
    APPELS.clear()
    ids = [f"lnk_{i}" for i in range(45)]
    t1 = gms.clicks_for_ids(ids, jour, jour)
    t2 = gms.clicks_for_ids(ids, jour, jour)
    check("clicks_for_ids : lots de 20, puis plus rien dans l'heure",
          t1 == t2 == 21 and len(APPELS) == 3 and [len(a[2]) for a in APPELS] == [20, 20, 5],
          APPELS)
    APPELS.clear()
    check("clicks_for_link : par le cache aussi (relu une fois dans l'heure)",
          gms.clicks_for_link("lnk_0", jour, jour) == 7
          and gms.clicks_for_link("lnk_0", jour, jour) == 7 and len(APPELS) == 1, APPELS)
    gms._ANA_CACHE.clear()
    REPONSE["v"] = {"ok": False, "error": "HTTP 429"}
    check("un échec rend None (« indispo »), jamais 0, et n'est pas gardé",
          gms.clicks_for_ids(["lnk_x"], jour, jour) is None and not gms._ANA_CACHE)
    REPONSE["v"] = {"ok": True, "data": "Error: quelque chose"}
    check("une réponse qui n'est pas un relevé est illisible, pas « 0 clic » gardé une heure",
          gms.analytics_for_link("lnk_y", jour, jour) == (None, None) and not gms._ANA_CACHE)
    REPONSE["v"] = {"ok": True, "data": {"total_clicks": 0, "top_countries": []}}
    check("un vrai zéro reste un zéro", gms.analytics_for_link("lnk_z", jour, jour) == (0, {}))
finally:
    gms.get_analytics_overview = _vrai_overview
    gms._ANA_CACHE.clear()

print("\n— 3. le report Discord : à l'heure pleine, une fois, même après un redémarrage")
try:
    import cogs.clickrecap as cr
    vrai_fichier = cr._CRENEAU_FILE
    cr._CRENEAU_FILE = TMP / "report_click_creneau.json"
    try:
        h = dt.datetime(2026, 10, 6, 9, 0)
        check("09h00 et 09h59 : même créneau ; 10h00 : le suivant",
              cr._creneau_60(h) == cr._creneau_60(h.replace(minute=59))
              != cr._creneau_60(h.replace(hour=10)))
        check("la même heure un autre jour n'est pas le même créneau",
              cr._creneau_60(h) != cr._creneau_60(h + dt.timedelta(days=1)))
        check("rien sur disque : aucun créneau connu", cr._creneau_lu() is None)
        cr._creneau_ecrit(cr._creneau_60(h))
        check("le créneau publié est relu après un redémarrage",
              cr._creneau_lu() == cr._creneau_60(h))
        prochain = cr._next_heure_unix()
        check("le compte à rebours vise l'heure pleine suivante",
              prochain % 3600 == 0 and 0 < prochain - time.time() <= 3600)
        check("le bouton Rafraîchir : une fois par heure au plus",
              cr._REFRESH_ATTENTE_S == 3600)
        src = (BOT / "cogs" / "clickrecap.py").read_text(encoding="utf-8")
        check("la boucle compare au créneau d'une heure, et l'écrit",
              "creneau = _creneau_60(now)" in src and "_creneau_ecrit(creneau)" in src
              and "self._report_creneau = _creneau_lu()" in src)
        check("le report dit « every hour », plus « every 30 min »",
              "every hour" in src and "every 30 min" not in src)
    finally:
        cr._CRENEAU_FILE = vrai_fichier
except ImportError as e:
    check("cogs.clickrecap importable", False, e)

print("\n— 4. les autres relevés de clics")
src_w = (BOT / "web_upload.py").read_text(encoding="utf-8")
check("widget des VA : une heure (il était relu toutes les 5 min)",
      "_VA_DAILY_TTL = 3600" in src_w)
import infloww_liens as il                    # noqa: E402
check("page Liens Infloww : clics US et liste GetMySocial, une heure",
      il.US_REESSAI_S == 3600 and il.GMS_FRAIS_S == 3600)
import clics_portail as cp                    # noqa: E402
check("page publique des clics : une heure (un échec, moins)",
      cp.TTL_RENDU == 3600 and cp.TTL_ECHEC < cp.TTL_RENDU)
check("facture : clics VA du mois, une heure",
      "< 3600:" in (BOT / "facture_web.py").read_text(encoding="utf-8"))

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
