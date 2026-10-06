"""Dashboard clics : un relevé ne vaut que pour la période qu'il décrit.

Le 06/10/2026, l'onglet « Dashboard clics » montrait encore le 12/09. Le
13/09 à 00h14 (Paris), le VPS -- en UTC -- était encore le 12 : le relevé
« aujourd'hui » a été pris sur le 12, après la fin du 12 à Paris, donc jugé
définitif et plus jamais refait. Même chose pour « 7 jours », la quinzaine,
« hier » : tout le tableau, et la carte de l'accueil, sont restés figés.

Le propriétaire veut aussi les clics relus une fois par heure, pas avant.

Vérifié ici sans réseau (calcul et lancement simulés), avec le vrai
web_upload. Lancer depuis la racine du dépôt : python tests_gmsdash_periode.py
"""
from __future__ import annotations

import datetime as dt
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.environ["VABOT_BANC_ESSAI"] = "1"
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import web_upload as w                  # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


TEAM = w.GMSDASH_TEAMS[0][0]
LANCES = []
SAUVE = {n: getattr(w, n) for n in ("_gmsdash_kick", "_paris_now_web", "_gmsdash_compute",
                                    "_gmsdash_store", "_gmsdash_regarde_recemment",
                                    "_gmsdash_save_disk", "GMSDASH_CACHE_FILE")}
TMP = pathlib.Path(tempfile.mkdtemp(prefix="gmsdash_periode_"))
w.GMSDASH_CACHE_FILE = TMP / "gmsdash_cache.json"
w._gmsdash_save_disk = lambda: None
w._gmsdash_kick = lambda team, period, force=False: LANCES.append((team, period, force)) or True


def paris(*a):
    """Fige l'heure de Paris que voit le tableau."""
    w._paris_now_web = lambda: dt.datetime(*a)


def releve(period, ts, start=None, end=None, **extra):
    """Une entrée du cache telle que le démon l'écrit."""
    s, e, lib = w._gmsdash_period_range(period)
    pl = {"ok": True, "team": TEAM, "label": lib,
          "start": start or s.isoformat(), "end": end or e.isoformat(),
          "ver": w.GMSDASH_PAYLOAD_VER, "failed": 0, "partial": False,
          "links": [{"id": "lnk_1", "shortcode": "sc", "name": "VA 2 (Safidy)",
                     "clicks": 12, "lu": True}]}
    pl.update(extra)
    return {"ts": int(ts), "payload": pl}


def servir(period, hit, force=False, echec_il_y_a=None):
    LANCES.clear()
    key = f"{TEAM}|{period}"
    with w._GMSDASH_LOCK:
        w._GMSDASH_MEM.clear()
        w._GMSDASH_INFLIGHT.clear()
        w._GMSDASH_LASTFAIL.clear()
        if hit:
            w._GMSDASH_MEM[key] = hit
        if echec_il_y_a is not None:
            w._GMSDASH_LASTFAIL[key] = {"ts": int(time.time() - echec_il_y_a), "error": "HTTP 429"}
    return w._gmsdash_get(TEAM, period, force=force)


def fin_paris(iso):
    return w._fin_journee_paris_ts(iso)


try:
    print("\n— 1. le jour est celui de Paris, pas celui du VPS")
    # 12/09 22:14 UTC = 13/09 00:14 à Paris : l'instant exact du relevé figé
    paris(2026, 9, 13, 0, 14)
    s, e, _l = w._gmsdash_period_range("today")
    check("« aujourd'hui » à 00h14 Paris le 13/09 : le 13, pas le 12",
          s.isoformat() == e.isoformat() == "2026-09-13", (s, e))
    s, e, _l = w._gmsdash_period_range("yesterday")
    check("« hier » à cette heure-là : le 12", s.isoformat() == "2026-09-12", s)
    paris(2026, 9, 16, 0, 30)
    s, e, _l = w._gmsdash_period_range("q2")
    check("le 16 à 00h30 Paris, la quinzaine 16-fin commence (le VPS est encore le 15)",
          (s.isoformat(), e.isoformat()) == ("2026-09-16", "2026-09-16"), (s, e))

    print("\n— 2. le relevé du 12/09, servi le 06/10")
    paris(2026, 10, 6, 11, 0)
    ts_fige = int(dt.datetime(2026, 9, 12, 22, 14, 33, tzinfo=dt.timezone.utc).timestamp())
    vieux = releve("today", ts_fige, start="2026-09-12", end="2026-09-12")
    check("il ne décrit pas « aujourd'hui »", not w._gmsdash_courant(vieux, "today"))
    check("il n'est donc pas définitif pour « aujourd'hui »",
          not w._gmsdash_definitif(vieux, "today"))
    check("… alors qu'il l'était (le défaut : la période seule, sans la date du jour)",
          w._gmsdash_definitif(vieux) is True)
    r = servir("today", vieux)
    check("la page relance le calcul tout de suite", LANCES == [(TEAM, "today", False)], LANCES)
    check("et dit que ce n'est pas le relevé demandé, avec ses dates",
          r.get("perime") and "12/09" in r.get("label", "") and "pas celui demandé" in r["label"],
          r.get("label"))
    check("son âge dit trois semaines et plus", r.get("age_min", 0) > 20 * 1440, r.get("age_min"))
    for per, deb, fin in (("7", "2026-09-06", "2026-09-12"), ("q1", "2026-09-01", "2026-09-12"),
                          ("q2", "2026-08-16", "2026-08-31"), ("yesterday", "2026-09-11", "2026-09-11")):
        r = servir(per, releve(per, ts_fige, start=deb, end=fin))
        check(f"« {per} » du 12/09 : recalculé aussi", LANCES and r.get("perime"), (LANCES, r.get("label")))
    sans_dates = releve("today", time.time())
    del sans_dates["payload"]["start"], sans_dates["payload"]["end"]
    check("un relevé sans dates (ancien format) n'est jamais « du jour »",
          not w._gmsdash_courant(sans_dates, "today"))

    # la suite compare à l'heure réelle (time.time()) : on rend la vraie date
    w._paris_now_web = SAUVE["_paris_now_web"]

    print("\n— 3. une heure, pas avant")
    check("la durée de fraîcheur est d'une heure", w._GMSDASH_TTL == 3600)
    r = servir("today", releve("today", time.time() - 50 * 60))
    check("relevé de 50 min : servi tel quel, rien ne repart", LANCES == [] and not r.get("perime"),
          LANCES)
    check("… et la page dit quand partira le prochain (dans ~10 min)",
          r.get("prochain_min") == 10, r.get("prochain_min"))
    r = servir("today", releve("today", time.time() - 50 * 60), force=True)
    check("↻ sur un relevé de moins d'une heure : rien ne repart", LANCES == [], LANCES)
    r = servir("today", releve("today", time.time() - 61 * 60))
    check("au-delà d'une heure, le relevé est refait", LANCES == [(TEAM, "today", False)], LANCES)
    r = servir("today", releve("today", time.time() - 61 * 60), force=True)
    check("↻ au-delà d'une heure : refait, et la liste des liens relue",
          LANCES == [(TEAM, "today", True)], LANCES)

    print("\n— 4. après un échec, dix minutes")
    r = servir("today", releve("today", time.time() - 2 * 3600), echec_il_y_a=5 * 60)
    check("échec il y a 5 min : on ne relance pas", LANCES == [], LANCES)
    check("… et la page dit dans combien de temps", r.get("prochain_min") == 5, r.get("prochain_min"))
    r = servir("today", releve("today", time.time() - 2 * 3600), force=True, echec_il_y_a=5 * 60)
    check("↻ non plus ne relance pas sur une API qui vient de refuser", LANCES == [], LANCES)
    r = servir("today", releve("today", time.time() - 2 * 3600), echec_il_y_a=11 * 60)
    check("échec il y a 11 min : on relance", LANCES == [(TEAM, "today", False)], LANCES)
    r = servir("today", None, echec_il_y_a=5 * 60)
    check("rien en cache et échec récent : la barre dit l'attente",
          r.get("loading") and "nouvelle tentative" in (r.get("progress") or {}).get("stage", ""), r)

    print("\n— 5. une période close reste close, si elle a été lue en entier après sa fin")
    hier = w._gmsdash_period_range("yesterday")[1].isoformat()
    apres = fin_paris(hier) + 600
    r = servir("yesterday", releve("yesterday", apres))
    check("« hier » lu après minuit : définitif, rien ne repart",
          LANCES == [] and r.get("definitif") is True, (LANCES, r.get("definitif")))
    servir("yesterday", releve("yesterday", apres), force=True)
    check("… même avec ↻", LANCES == [], LANCES)
    check("un relevé incomplet n'est jamais définitif",
          not w._gmsdash_definitif(releve("yesterday", apres, partial=True, failed=3), "yesterday"))
    check("un calcul COMMENCÉ avant minuit et enregistré après n'est pas définitif",
          not w._gmsdash_definitif(releve("yesterday", apres, debut_calcul=fin_paris(hier) - 60),
                                   "yesterday"))
    check("commencé après minuit : définitif",
          w._gmsdash_definitif(releve("yesterday", apres, debut_calcul=fin_paris(hier) + 60),
                               "yesterday"))
    r = servir("q1", releve("q1", time.time() - 2 * 3600))
    check("la quinzaine en cours n'est jamais définitive",
          LANCES and not r.get("definitif"), (LANCES, r.get("definitif")))

    print("\n— 6. le démon de préchauffage")

    class FinDuTour(BaseException):
        pass

    CALCULES, DORT = [], []

    def faux_sommeil(s):
        DORT.append(s)
        if s in (30 * 60, w._GMSDASH_ECHEC_S):
            raise FinDuTour()

    def faux_calcul(team, period, **k):
        CALCULES.append((team, period))
        if ECHEC["v"]:
            return {"ok": False, "error": "HTTP 429"}
        return releve(period, time.time())["payload"]

    ECHEC = {"v": False}
    import gms
    vrai_sleep, vrai_conf = time.sleep, gms.is_configured
    time.sleep = faux_sommeil
    gms.is_configured = lambda: True
    w._gmsdash_compute = faux_calcul
    w._gmsdash_store = lambda team, period, payload: None
    w._gmsdash_regarde_recemment = lambda: True
    try:
        def un_tour(mem):
            CALCULES.clear()
            DORT.clear()
            with w._GMSDASH_LOCK:
                w._GMSDASH_MEM.clear()
                w._GMSDASH_MEM.update(mem)
            try:
                w._gmsdash_warm_loop()
            except FinDuTour:
                pass

        equipes = [t for t, _n in w.GMSDASH_TEAMS]
        un_tour({f"{t}|{p}": releve(p, ts_fige, start="2026-09-12", end="2026-09-12")
                 for t in equipes for p in w._GMSDASH_WARM_PERIODS})
        check("cache du 12/09 : toutes les périodes de toutes les catégories sont refaites",
              len(CALCULES) == len(equipes) * len(w._GMSDASH_WARM_PERIODS), CALCULES)
        un_tour({f"{t}|{p}": releve(p, time.time() - 3600)
                 for t in equipes for p in w._GMSDASH_WARM_PERIODS})
        check("cache du jour, vieux d'une heure : rien n'est refait (fenêtre de 6 h)",
              CALCULES == [], CALCULES)
        ECHEC["v"] = True
        un_tour({})
        check("un échec : nouvel essai dans 10 min, plus 3",
              DORT and DORT[-1] == w._GMSDASH_ECHEC_S == 600, DORT[-3:])
    finally:
        time.sleep, gms.is_configured = vrai_sleep, vrai_conf

    print("\n— 7. la carte de l'accueil")
    vrai_cache = w._clicrank_cache
    try:
        per = w._clicrank_quinzaine()[0]
        w._clicrank_cache = lambda _p: releve(per, ts_fige, start="2026-09-01", end="2026-09-12")
        h = w._render_clicrank_html()
        check("le relevé du 01/09 → 12/09 n'est plus dit « définitif »",
              "définitifs" not in h and "pas la quinzaine en cours" in h and "01/09" in h, h[-300:])
        w._clicrank_cache = lambda _p: releve(per, time.time() - 600)
        h = w._render_clicrank_html()
        check("le relevé de la quinzaine en cours : « se met à jour »", "se met à jour" in h, h[-300:])
    finally:
        w._clicrank_cache = vrai_cache

    print("\n— 8. la page")
    src = (BOT / "web_upload.py").read_text(encoding="utf-8")
    check("plus de « recalcul auto toutes les 30 min · ↻ pour forcer »",
          "toutes les 30 min · ↻ pour forcer" not in src)
    check("l'analyse croisée ne prend que les « 7 jours » de la semaine",
          'if not _gmsdash_courant(hit, "7"):' in src)
    html = None
    vrai_conf = gms.is_configured
    gms.is_configured = lambda: True
    try:
        html = w._render_gmsdash_html()
    except Exception as e:                   # noqa: BLE001
        check("la page se rend", False, repr(e))
    finally:
        gms.is_configured = vrai_conf
    if html:
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        check("la page porte son script", bool(scripts) and "function gdAge" in "".join(scripts))
        js = TMP / "gmsdash.js"
        js.write_text("\n".join(scripts), encoding="utf-8")
        try:
            r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
            check("node --check : le script de la page est valide", r.returncode == 0,
                  r.stderr[-300:])
            age = re.search(r"function gdAge\(m\)\{.*?\n\}", "\n".join(scripts), re.S).group(0)
            r = subprocess.run(["node", "-e", age + ";console.log([gdAge(0),gdAge(50),"
                                "gdAge(300),gdAge(34560)].join('|'))"],
                               capture_output=True, text=True)
            check("l'âge se lit : maintenant | 50 min | 5 h | 24 j",
                  r.stdout.strip() == "maintenant|il y a 50 min|il y a 5 h|il y a 24 j",
                  r.stdout + r.stderr)
        except FileNotFoundError:
            print("     (node absent : script non vérifié)")
finally:
    for n, v in SAUVE.items():
        setattr(w, n, v)
    with w._GMSDASH_LOCK:
        w._GMSDASH_MEM.clear()
        w._GMSDASH_LASTFAIL.clear()
        w._GMSDASH_INFLIGHT.clear()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
