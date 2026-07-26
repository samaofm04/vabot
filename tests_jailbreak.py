"""tests_jailbreak.py — banc d'essai de la structure VA jailbreak.

Lancer :  python tests_jailbreak.py        (depuis le dossier bot/)

Crée une identité « test », la torture (CRUD, concurrence, corruption de
fichier, sync Sheet simulée, activité/paie, rendu des pages), puis la SUPPRIME.
Ne touche à aucune autre identité.

SÉCURITÉ : toute écriture vers Google Sheets est neutralisée au démarrage —
ce banc ne peut pas créer d'onglet « test » dans tes classeurs, même sur le VPS.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import sheets_sync as _ss_guard          # NE JAMAIS écrire dans les vrais Sheets
_ss_guard.push_all = lambda *a, **k: False
_ss_guard.push_all_async = lambda *a, **k: None
_ss_guard._push_all_folder = lambda *a, **k: False
_ss_guard._push_all_single = lambda *a, **k: False

import datetime as dt
import importlib, json, os, random, string, sys, threading, time
import pathlib

sys.path.insert(0, str(pathlib.Path.cwd()))
import jailbreak as jb

IDENT = "test"
SEP1 = "=" * 70
FAILS = []
OKS = []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{detail}]" if detail and not cond else ""))


def reset():
    with jb.transaction():
        data = jb._load()
        data.pop(IDENT, None)
        jb._save(data)
    # purge les tombstones de l'identité de test
    try:
        t = jb._tomb_load()
        for kind in ("vas", "accounts"):
            for k in [k for k in t[kind] if k.startswith(IDENT + "|")]:
                t[kind].pop(k, None)
        jb._tomb_save(t)
    except Exception:
        pass


def accounts():
    return jb.list_accounts(IDENT)


def unames():
    return sorted((a.get("username") or "") for a in accounts())


def vanames():
    with jb.transaction():
        e = (jb._load() or {}).get(IDENT) or {}
    return [(v.get("name") if isinstance(v, dict) else v) for v in (e.get("vas") or [])]


print("=" * 70, "\n1) CRUD de base\n", "=" * 70)
reset()
jb.add_va(IDENT, "Alpha", discord_username="alpha_1")
jb.add_va(IDENT, "Bêta", discord_username="beta_2")
check("2 VAs créés", vanames() == ["Alpha", "Bêta"], vanames())
check("doublon de VA refusé", jb.add_va(IDENT, "alpha") is False)
a1 = jb.add_account(IDENT, "acc_one", va="Alpha", password="p1", email="e@x.io")
check("compte ajouté", a1 and a1.get("id") and unames() == ["acc_one"], unames())
try:
    jb.add_account(IDENT, "ACC_ONE", va="Alpha")
    dup = False
except ValueError:
    dup = True
check("doublon de compte refusé (insensible à la casse)", dup)
check("update_account", jb.update_account(IDENT, a1["id"], notes="hello") and
      accounts()[0].get("notes") == "hello")

print("\n", "=" * 70, "\n2) Renommage de VA & propagation\n", "=" * 70)
jb.add_account(IDENT, "acc_two", va="Alpha")
jb.update_va(IDENT, "Alpha", new_name="Alpha2")
vas_after = [a.get("va") for a in accounts()]
check("rename VA propagé aux comptes", set(vas_after) == {"Alpha2"}, vas_after)
check("rename VA reflété dans la liste", "Alpha2" in vanames(), vanames())
check("rename vers un nom existant refusé", jb.update_va(IDENT, "Alpha2", new_name="Bêta") is False)
check("VA introuvable -> False", jb.update_va(IDENT, "Fantome", new_name="X") is False)

print("\n", "=" * 70, "\n3) Bulk + dédoublonnage\n", "=" * 70)
res = jb.bulk_add_accounts(IDENT, ["b1", "b2", "acc_two", " b3 ", "@b4", ""], va="Bêta")
check("bulk : 4 ajoutés", res["added"] == 4, res)
check("bulk : 1 doublon ignoré", res["skipped_dup"] == 1, res)
check("bulk : @ retiré", "b4" in unames(), unames())
check("bulk : espaces nettoyés", "b3" in unames(), unames())

print("\n", "=" * 70, "\n4) Réordonnancement des VAs\n", "=" * 70)
jb.reorder_vas(IDENT, ["Bêta", "Alpha2"])
check("ordre appliqué", vanames()[:2] == ["Bêta", "Alpha2"], vanames())
jb.reorder_vas(IDENT, ["Bêta"])
check("VA non cité conservé", set(vanames()) >= {"Bêta", "Alpha2"}, vanames())
check("liste vide refusée", jb.reorder_vas(IDENT, []) is False)

print("\n", "=" * 70, "\n5) Suppressions + tombstones\n", "=" * 70)
n_before = len(accounts())
n = jb.remove_va_and_accounts(IDENT, "Bêta")
check("VA supprimé avec ses comptes", n == 4 and len(accounts()) == n_before - 4, f"{n} / {len(accounts())}")
tb = jb.tombstones()
check("tombstone VA posée", f"{IDENT}|bêta" in tb["vas"], list(tb["vas"]))
check("tombstones comptes posées", any(k.startswith(IDENT + "|b1") for k in tb["accounts"]), list(tb["accounts"])[:4])
acc_id = accounts()[0]["id"]
jb.remove_account(IDENT, acc_id)
check("compte supprimé", len(accounts()) == 1)
check("re-ajout volontaire lève la tombstone",
      jb.add_va(IDENT, "Bêta") and f"{IDENT}|bêta" not in jb.tombstones()["vas"])

print("\n", "=" * 70, "\n6) Entrées limites (unicode, longueurs, caractères spéciaux)\n", "=" * 70)
weird = 'A<script>"\'&é ' + "é" * 5
jb.add_va(IDENT, weird)
check("VA à caractères spéciaux accepté", any(w.startswith("A<script>") for w in vanames()), vanames())
long_va = "V" * 120
jb.add_va(IDENT, long_va)
check("nom de VA tronqué à 60", any(len(v) == 60 for v in vanames()), [len(v) for v in vanames()])
long_u = "u" * 200
jb.add_account(IDENT, long_u, va="Bêta")
check("username tronqué à 80", any(len(u) == 80 for u in unames()), [len(u) for u in unames()])
check("identité vide refusée", jb.add_va("", "X") is False)
try:
    jb.add_account(IDENT, "   ", va="Bêta")
    empty_ok = False
except ValueError:
    empty_ok = True
check("username vide refusé", empty_ok)

print("\n", "=" * 70, "\n7) Concurrence : 8 threads × 12 ajouts simultanés\n", "=" * 70)
reset()
jb.add_va(IDENT, "Conc")
errors = []


def worker(k):
    for i in range(12):
        try:
            jb.add_account(IDENT, f"c{k}_{i}", va="Conc")
        except Exception as e:
            errors.append(repr(e))


ths = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
t0 = time.time()
for t in ths:
    t.start()
for t in ths:
    t.join()
got = len(accounts())
check("96 comptes écrits sans perte (verrou)", got == 96, f"{got}/96 en {time.time()-t0:.1f}s")
check("aucune exception concurrente", not errors, errors[:2])
ids = [a["id"] for a in accounts()]
check("ids tous uniques", len(set(ids)) == len(ids), f"{len(ids)-len(set(ids))} collisions")

print("\n", "=" * 70, "\n8) Résistance : fichier corrompu / vidé\n", "=" * 70)
before = len(accounts())
jb.JAILBREAK_FILE.write_text("{ ceci n est pas du json", encoding="utf-8")
rec = jb._load()
check("corruption -> restauré depuis backup", (rec.get(IDENT, {}).get("accounts") or []) != [],
      f"{len(rec.get(IDENT, {}).get('accounts') or [])} comptes")
check("restauration complète", len(rec.get(IDENT, {}).get("accounts") or []) == before,
      f"{len(rec.get(IDENT, {}).get('accounts') or [])} vs {before}")
jb.JAILBREAK_FILE.write_text("", encoding="utf-8")
rec2 = jb._load()
check("fichier vidé -> restauré aussi", len(rec2.get(IDENT, {}).get("accounts") or []) == before)
check("écriture atomique : pas de .tmp résiduel", not jb.JAILBREAK_FILE.with_suffix(".json.tmp").exists())

print("\n", "=" * 70, "\n9) Sync Sheet simulée (pull_and_merge)\n", "=" * 70)
import sheets_sync as ss
reset()
jb.add_va(IDENT, "Sync")
for i in range(10):
    jb.add_account(IDENT, f"s{i}", va="Sync")
ss.is_paused = lambda: False
# a) le Sheet garde 4 comptes sur 10 -> 6 suppressions appliquées
ss.pull_all = lambda: {f"{IDENT} Sync": [{"username": f"s{i}"} for i in range(4)]}
ch, summ = ss.pull_and_merge()
check("suppressions du Sheet appliquées", sorted(unames()) == [f"s{i}" for i in range(4)], unames())
# b) onglet VIDE -> aucune suppression (anti-wipe)
ss.pull_all = lambda: {f"{IDENT} Sync": []}
ss.pull_and_merge()
check("onglet vide n'efface rien", len(accounts()) == 4, unames())
# c) ajouts depuis le Sheet
ss.pull_all = lambda: {f"{IDENT} Sync": [{"username": f"s{i}"} for i in range(4)] +
                       [{"username": "nouveau1"}, {"username": "nouveau2"}]}
ss.pull_and_merge()
check("ajouts du Sheet importés", {"nouveau1", "nouveau2"} <= set(unames()), unames())
# d) doublons dans le Sheet
ss.pull_all = lambda: {f"{IDENT} Sync": [{"username": "dup"}, {"username": "dup"}, {"username": "DUP"}]}
ss.pull_and_merge()
check("doublons du Sheet -> 1 seul compte", sum(1 for u in unames() if u.lower() == "dup") == 1, unames())
# e) compte supprimé sur le site il y a < 15 min = pas ressuscité
jb.add_account(IDENT, "ghost", va="Sync")
gid = [a["id"] for a in accounts() if a["username"] == "ghost"][0]
jb.remove_account(IDENT, gid)
ss.pull_all = lambda: {f"{IDENT} Sync": [{"username": "ghost"}]}
ss.pull_and_merge()
check("anti-résurrection (< 15 min) tient", "ghost" not in unames(), unames())

print("\n", "=" * 70, "\n10) Activité VA & paie sur données réelles\n", "=" * 70)
import web_upload as w
import datetime as dt
reset()
now = int(time.time())
today = dt.date.today()
jb.add_va(IDENT, "Assidu")
jb.add_va(IDENT, "Absent")
for i in range(3):
    jb.add_account(IDENT, f"ok{i}", va="Assidu")
for i in range(2):
    jb.add_account(IDENT, f"ko{i}", va="Absent")
# comptes ANCIENS (created_at il y a 90 j) : sinon ils sont en warm-up 5 j et
# ne sont PAS comptabilises -- c'est la regle voulue, on la teste plus bas.
with jb.transaction():
    _d = jb._load()
    for _a in _d[IDENT]["accounts"]:
        _a["created_at"] = now - 90 * 86400
    jb._save(_d)
D = lambda k: (today - dt.timedelta(days=k)).isoformat()
cache = {}
for i in range(3):
    cache[f"ok{i}"] = {"followers": 10, "posts_count": 20, "scraped_at": now,
                       "reel_days": {D(k): 1 for k in range(0, 14)}}
for i in range(2):
    cache[f"ko{i}"] = {"followers": 5, "posts_count": 20, "scraped_at": now,
                       "reel_days": {D(k): 1 for k in range(9, 14)}}
w._load_insta_3_stats_cache = lambda: cache
w._vaact_cfg_load = lambda: {"vas": {"assidu": {"base": 300, "malus": 10, "cadence": "q", "quota": 3, "quota_pct": 100},
                                     "absent": {"base": 300, "malus": 10, "cadence": "q"}},
                             "warmup_days": 5, "rebuild_days": 5}
w._vaact_state_load = lambda: {"alerts": {}}
w._vaact_state_save = lambda d: None
pay = w._vaact_payload("14")
rows = {v["va"]: v for v in pay["vas"]}
check("VA assidu : 0 oubli", rows["assidu"]["oublis"] == 0, rows["assidu"]["statuses"])
check("VA absent : des oublis", rows["absent"]["oublis"] >= 7, rows["absent"]["statuses"])
check("jour en cours provisoire (p) pas compté",
      rows["absent"]["statuses"][-1] in ("p", "g") and
      rows["absent"]["oublis"] == rows["absent"]["statuses"].count("x"))
q = w._vaact_payload("q")
rq = {v["va"]: v for v in q["vas"]}
check("paie quinzaine = base - oublis×malus",
      rq["absent"]["pay"] == max(0, 300 - rq["absent"]["oublis"] * 10),
      f'{rq["absent"]["pay"]} / {rq["absent"]["oublis"]}')
check("quota atteint -> pas d'alerte", rows["assidu"]["alert"] is False, rows["assidu"])
jb.add_account(IDENT, "tout_neuf", va="Assidu")     # cree aujourd'hui
cache["tout_neuf"] = {"followers": 1, "posts_count": 0, "scraped_at": now, "reel_days": {}}
pay2 = w._vaact_payload("14")
r2 = {v["va"]: v for v in pay2["vas"]}
check("warm-up : compte du jour non comptabilise",
      r2["assidu"]["oublis"] == 0 and r2["assidu"]["n_warm"] == 1, r2["assidu"])

print("\n", "=" * 70, "\n11) Analyse vues sur les mêmes données\n", "=" * 70)
for h in cache:
    cache[h]["post_days"] = {D(0): 100, D(1): 50}
    cache[h]["weekly"] = 150
    cache[h]["daily"] = 100
    cache[h]["biweekly"] = 150
w._GMSDASH_MEM.clear()
an = w._jbanalyse_payload()
tid = {r["name"]: r for r in an["idents"]}
check("identité test présente", IDENT in tid, list(tid))
_exp_w = sum(int(v.get("weekly") or 0) for v in cache.values())
check("vues agrégées correctes", tid[IDENT]["weekly"] == _exp_w, f'{tid[IDENT]["weekly"]} vs {_exp_w}')
_exp_a = sum(1 for v in cache.values() if not v.get("error"))
check("comptes actifs comptés", tid[IDENT]["active"] == _exp_a, f'{tid[IDENT]["active"]} vs {_exp_a}')
tva = {r["name"]: r for r in an["vas"]}
_n_assidu = sum(1 for a in accounts() if a.get("va") == "Assidu")
check("ventilation par VA", tva.get("Assidu", {}).get("n") == _n_assidu and tva.get("Absent", {}).get("n") == 2,
      f'{tva.get("Assidu", {}).get("n")} vs {_n_assidu}')

print("\n", "=" * 70, "\n12) Rendu des pages (aucune exception, échappement)\n", "=" * 70)
reset()
jb.add_va(IDENT, 'X<script>alert(1)</script>')
jb.add_account(IDENT, "inject_test", va='X<script>alert(1)</script>', notes='"><b>oops</b>')
try:
    html = w._render_jailbreak_html()
    ok_render = True
except Exception as e:
    ok_render, html = False, repr(e)
check("page Jailbreak rendue", ok_render, html if not ok_render else "")
if ok_render:
    check("script injecté échappé", "<script>alert(1)</script>" not in html)
for fn in ("_render_jbanalyse_html", "_render_jbactivite_html"):
    try:
        getattr(w, fn)()
        check(f"{fn} OK", True)
    except Exception as e:
        check(f"{fn} OK", False, repr(e))

print(SEP1, "13) Paie : ne jamais accuser a tort (prive, illisible, erreur de scrape)", SEP1)
reset()
_now = int(time.time())
_today = dt.date.today()
_D = lambda k: (_today - dt.timedelta(days=k)).isoformat()
jb.add_va(IDENT, "Paie")
for _u in ("prive", "aveugle", "fautif"):
    jb.add_account(IDENT, _u, va="Paie")
with jb.transaction():
    _d = jb._load()
    for _a in _d[IDENT]["accounts"]:
        _a["created_at"] = _now - 90 * 86400
    jb._save(_d)
_cache13 = {
    "prive":   {"followers": 5, "posts_count": 30, "scraped_at": _now, "reel_days": {},
                "is_private": True, "reels_seen": 0},
    "aveugle": {"followers": 5, "posts_count": 30, "scraped_at": _now, "reel_days": {},
                "is_private": False, "reels_seen": 0},
    "fautif":  {"followers": 5, "posts_count": 30, "scraped_at": _now, "reels_seen": 12,
                "reel_days": {_D(k): 1 for k in range(6, 14)},
                "last_reel_at": (dt.datetime.now() - dt.timedelta(days=6)).isoformat()},
}
w._load_insta_3_stats_cache = lambda: _cache13
w._vaact_cfg_load = lambda: {"vas": {"paie": {"base": 300, "malus": 10, "cadence": "q"}},
                             "warmup_days": 5, "rebuild_days": 5}
w._vaact_state_load = lambda: {"alerts": {}}
w._vaact_state_save = lambda d: None
_p13 = w._vaact_payload("14")
_v13 = _p13["vas"][0]
_det = [u for day in _p13["days"] for u in (_v13["miss"].get(day) or [])]
check("compte prive jamais accuse", "prive" not in _det, str(set(_det)))
check("compte illisible (0 media) jamais accuse", "aveugle" not in _det, str(set(_det)))
check("vrai fautif detecte", "fautif" in _det, str(set(_det)))
check("retenue = oublis x malus", _v13["deduction"] == _v13["oublis"] * 10)

print(SEP1, "14) Cache Insta : historique fusionne, erreur non destructrice", SEP1)
_store = {}
w._load_insta_3_stats_cache = lambda: dict(_store)
w._cache_put_stats = lambda h, o: _store.__setitem__(h, o)
_store["hist"] = {"followers": 10, "posts_count": 30, "scraped_at": _now - 3600,
                  "post_days": {_D(9): 500}, "reel_days": {_D(9): 1}}
w._scrape_via_ig_public = lambda h: {
    "profile": {"username": h, "followers": 12, "posts_count": 31, "profile_pic_url": "", "is_private": False},
    "reels": [{"shortcode": "x", "is_video": True, "views": 100, "taken_at": _now - 86400}]}
_o = w._compute_insta_3_stats("hist", force=True)
check("jours anciens conserves (courbe 30 j)", _D(9) in _o["reel_days"], str(sorted(_o["reel_days"])))
check("nouveaux jours ajoutes", _D(1) in _o["reel_days"], str(sorted(_o["reel_days"])))
_store["err"] = {"followers": 99, "posts_count": 20, "scraped_at": _now - 7200,
                 "reel_days": {_D(2): 1}, "profile_pic_url": "/x.png"}
w._scrape_via_ig_public = lambda h: {"error": "429 rate limit"}
import insta_scraper as _isc
_isc.scrape_profile = lambda h, limit=50: {"error": "429 rate limit"}
_o2 = w._compute_insta_3_stats("err", force=True)
check("erreur de scrape : donnees conservees",
      _o2.get("followers") == 99 and _o2.get("reel_days") == {_D(2): 1}, str(_o2.get("followers")))
check("erreur de scrape : marque stale", _o2.get("stale") is True)

print("\n", "=" * 70, "\nNETTOYAGE\n", "=" * 70)
reset()
with jb.transaction():
    check("identité test supprimée", IDENT not in (jb._load() or {}))

print("\n" + "=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  -", f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
