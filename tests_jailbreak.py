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

# Fiche IMPLICITE : list_vas_for_identity fabrique une fiche pour tout nom
# porte par un compte mais absent de vas[]. Elle s affiche donc dans la barre
# laterale, avec ses comptes — mais update_va ne la trouvait pas et repondait
# « VA introuvable ». Le proprietaire voyait une fiche bien reelle refuser
# d etre renommee.
_IMP = "_tst_implicite_rename"
_d = jb._load(); _d.pop(_IMP, None); jb._save(_d)
jb.add_account(_IMP, "compte_imp", va="Abdoul")
_d = jb._load(); _d[_IMP]["vas"] = []          # on la rend implicite
jb._save(_d)
check("implicite : la fiche s affiche bien alors qu elle n est pas dans vas[]",
      [v["name"] for v in jb.list_vas_for_identity(_IMP)] == ["Abdoul"]
      and jb._load()[_IMP]["vas"] == [])
check("implicite : elle peut etre renommee",
      jb.update_va(_IMP, "Abdoul", new_name="AbdoulX1") is True)
check("implicite : ses comptes suivent le nouveau nom",
      [a["va"] for a in jb._load()[_IMP]["accounts"]] == ["AbdoulX1"],
      str(jb._load()[_IMP]["accounts"]))
check("implicite : un nom qui n existe vraiment nulle part reste refuse",
      jb.update_va(_IMP, "PersonneIci", new_name="Z") is False)
_d = jb._load(); _d.pop(_IMP, None); jb._save(_d)

# Pierre tombale sur l ANCIEN nom. C est ce qui empeche la synchro Sheets de
# ressusciter la fiche renommee : le Sheet porte encore l ancien nom tant que
# le push suivant n a pas eu lieu, et le poller (toutes les 2 min) recreait
# alors une seconde fiche — l une avec les comptes, l autre vide. Doublon
# constate par le proprietaire le 22/08.
_tv = (jb.tombstones().get("vas") or {})
check("rename : l ancien nom recoit une pierre tombale",
      f"{IDENT}|alpha" in _tv, str(list(_tv)[:6]))
check("rename : le NOUVEAU nom n en a pas (sinon il se bloquerait lui-meme)",
      f"{IDENT}|alpha2" not in _tv)
# Renommer VERS un nom recemment supprime doit rester possible.
jb.tomb_add("vas", IDENT, "Renaissance")
jb.update_va(IDENT, "Alpha2", new_name="Renaissance")
check("rename vers un nom recemment supprime : la tombe est levee",
      f"{IDENT}|renaissance" not in (jb.tombstones().get("vas") or {})
      and "Renaissance" in vanames(), vanames())
jb.update_va(IDENT, "Renaissance", new_name="Alpha2")   # on remet en etat

# Le garde-fou cote synchro : la resurrection d un VA doit RESPECTER la tombe,
# pas l effacer. Avant, ce chemin appelait tomb_clear — la protection existait
# pour les comptes et etait activement annulee pour les VA.
_srcSS = pathlib.Path("sheets_sync.py").read_text(encoding="utf-8")
_blocSS = _srcSS[_srcSS.index("Coherence : les 'va' des comptes"):][:1400] \
    if "Coherence : les 'va' des comptes" in _srcSS else \
    (_srcSS[_srcSS.index("Cohérence : les 'va' des comptes"):][:1400]
     if "Cohérence : les 'va' des comptes" in _srcSS else "")
check("synchro : la resurrection d un VA respecte la pierre tombale",
      bool(_blocSS) and "skipped_tomb.add" in _blocSS
      and "tomb_clear" not in _blocSS,
      _blocSS[:120])

# Le semeur du demarrage : il reconnaissait un VA a son NOM. Renomme, le VA
# semblait disparu et etait recree sous son ancien nom AVEC son pseudo — une
# fiche de plus a chaque redemarrage du bot. Pire, add_va levait au passage la
# pierre tombale qui protege de la synchro Sheets.
import seed_jailbreak as _sj
_savSeeds = _sj.VAS_SEEDS
try:
    _sj.VAS_SEEDS = {IDENT: [{"name": "Semé", "discord_username": "seme_1234"}]}
    _r1 = _sj.seed_vas()
    check("seed : cree le VA absent sur une installation neuve",
          _r1[IDENT].get("Semé") == "added", str(_r1))
    # On le renomme, comme le proprietaire le fait.
    jb.update_va(IDENT, "Semé", new_name="Semé X1")
    _r2 = _sj.seed_vas()
    check("seed : un VA RENOMME n est pas recree (reconnu a son pseudo)",
          _r2[IDENT].get("Semé") == "renomme", str(_r2))
    check("seed : la pierre tombale du renommage a survecu au seed",
          f"{IDENT}|semé" in (jb.tombstones().get("vas") or {}),
          str(list((jb.tombstones().get("vas") or {}))[:6]))
    check("seed : une seule fiche subsiste, pas deux",
          len([n for n in vanames() if n.lower().startswith("semé")]) == 1,
          str(vanames()))
    # Sans pseudo, la pierre tombale reste le dernier rempart.
    _sj.VAS_SEEDS = {IDENT: [{"name": "Semé", "discord_username": ""}]}
    _r3 = _sj.seed_vas()
    check("seed : sans pseudo, la pierre tombale bloque quand meme",
          _r3[IDENT].get("Semé") == "pierre_tombale", str(_r3))
finally:
    _sj.VAS_SEEDS = _savSeeds

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
for _u in ("prive", "aveugle", "aveugle_hist", "fautif", "readd"):
    jb.add_account(IDENT, _u, va="Paie")
with jb.transaction():
    _d = jb._load()
    for _a in _d[IDENT]["accounts"]:
        # 'readd' = ré-ajout AUJOURD'HUI d'un compte établi (created_at récent) ;
        # les autres sont anciens (pas de warm-up).
        _a["created_at"] = _now if _a["username"] == "readd" else _now - 90 * 86400
    jb._save(_d)
_cache13 = {
    "prive":   {"followers": 5, "posts_count": 30, "scraped_at": _now, "reel_days": {},
                "is_private": True, "reels_seen": 0},
    "aveugle": {"followers": 5, "posts_count": 30, "scraped_at": _now, "reel_days": {},
                "is_private": False, "reels_seen": 0},
    # illisible (0 media rendu) MAIS avec un historique reel_days ancien : le
    # dernier scrape n'a rien rendu (hoquet API) -> indécidable, ne doit PAS être
    # accusé pour les jours récents non couverts (regression #6 de l'audit argent).
    "aveugle_hist": {"followers": 5, "posts_count": 30, "scraped_at": _now, "reels_seen": 0,
                     "is_private": False,
                     "reel_days": {_D(k): 1 for k in range(10, 14)},
                     "last_reel_at": (dt.datetime.now() - dt.timedelta(days=10)).isoformat()},
    "fautif":  {"followers": 5, "posts_count": 30, "scraped_at": _now, "reels_seen": 12,
                "reel_days": {_D(k): 1 for k in range(6, 14)},
                "last_reel_at": (dt.datetime.now() - dt.timedelta(days=6)).isoformat()},
    # ré-ajout aujourd'hui MAIS historique prouvant une activité avant l'ajout ->
    # pas de warm-up indu (regression #10 de l'audit argent).
    "readd":   {"followers": 5, "posts_count": 30, "scraped_at": _now, "reels_seen": 5,
                "reel_days": {_D(k): 1 for k in range(8, 13)},
                "last_reel_at": (dt.datetime.now() - dt.timedelta(days=8)).isoformat()},
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
check("compte illisible AVEC historique jamais accuse", "aveugle_hist" not in _det, str(set(_det)))
check("vrai fautif detecte", "fautif" in _det, str(set(_det)))
check("re-ajout d'un compte etabli : pas de warm-up indu (accuse)", "readd" in _det, str(set(_det)))
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
_recents = {(_today - dt.timedelta(days=k)).isoformat() for k in range(0, 3)}
check("nouveaux jours ajoutes", bool(_recents & set(_o["reel_days"])), str(sorted(_o["reel_days"])))
_store["err"] = {"followers": 99, "posts_count": 20, "scraped_at": _now - 7200,
                 "reel_days": {_D(2): 1}, "profile_pic_url": "/x.png"}
w._scrape_via_ig_public = lambda h: {"error": "429 rate limit"}
import insta_scraper as _isc
_isc.scrape_profile = lambda h, limit=50: {"error": "429 rate limit"}
_o2 = w._compute_insta_3_stats("err", force=True)
check("erreur de scrape : donnees conservees",
      _o2.get("followers") == 99 and _o2.get("reel_days") == {_D(2): 1}, str(_o2.get("followers")))
check("erreur de scrape : marque stale", _o2.get("stale") is True)

print("\n", "=" * 70, "\nPANNEAU US : boutons permanents\n", "=" * 70)
try:
    import asyncio as _aioP
    import inspect as _inspP
    import cogs.user as _uP

    _sigP = list(_inspP.signature(_uP.UserCog._run_for_model).parameters)
    check("panneau : signature (interaction, model, cmd, count, supports_count)",
          _sigP[1:6] == ["interaction", "model", "cmd", "count", "supports_count"],
          str(_sigP))

    _recuP = {}

    class _CogP:
        reelcaption = "CMD_REELCAPTION"

        async def _run_for_model(self, interaction, model, cmd,
                                 count=None, supports_count=False):
            _recuP.clear()
            _recuP.update(model=model, cmd=cmd, count=count,
                          supports_count=supports_count)

    class _RepP:
        def __init__(self):
            self.msgs = []

        async def send_message(self, *a, **k):
            self.msgs.append(k)

        async def defer(self, *a, **k):
            pass

    class _ItxP:
        def __init__(self, cog):
            self.client = type("C", (), {"get_cog": lambda s, n: cog})()
            self.response = _RepP()
            self.guild = self.user = self.channel = None

    _vraiP = _uP._jb_can_use
    _uP._jb_can_use = lambda i: True
    try:
        _bP = _uP.JBActionButton("e30princesss", "reelcaption", 7)
        _aioP.get_event_loop().run_until_complete(_bP.callback(_ItxP(_CogP())))
        # model et cmd inverses = « n'a pas repondu a temps » cote Discord
        check("panneau : le bouton passe les bons arguments",
              _recuP.get("model") == "e30princesss"
              and _recuP.get("cmd") == "CMD_REELCAPTION"
              and _recuP.get("count") == 7
              and _recuP.get("supports_count") is True, str(_recuP))
    finally:
        _uP._jb_can_use = _vraiP

    # le contenu doit TOUJOURS quitter le salon -menu
    class _ChR:
        def __init__(self, nom, cid, cat=None):
            self.name, self.id, self.category, self.recu = nom, cid, cat, []

        async def send(self, content=None, **kw):
            self.recu.append(content)

    _menuR = _ChR("abdoul_9684-menu", 1)
    _contR = _ChR("abdoul_9684-content", 2)
    _catR = type("Cat", (), {"text_channels": [_menuR, _contR]})()
    _menuR.category = _contR.category = _catR
    _gR = type("G", (), {"text_channels": [_menuR, _contR]})()
    _itxR = type("I", (), {"channel": _menuR, "guild": _gR, "user": None})()
    check("redirection : le -content se trouve depuis le -menu de la personne",
          _uP._us_content_target(_itxR) is _contR)

    class _FwR:
        def __init__(self):
            self.recu = []

        async def send(self, content=None, **kw):
            self.recu.append((content, kw.get("ephemeral")))

    _fwR = _FwR()
    _aioP.get_event_loop().run_until_complete(
        _uP._RedirectFollowup(_fwR, None).send("contenu sans destination"))
    check("redirection : sans -content, ephemere plutot que polluer le menu",
          _fwR.recu == [("contenu sans destination", True)] and not _menuR.recu,
          str(_fwR.recu))

    _embP, _viewP = _uP._jb_panel(None, "e30princesss", 5)
    _idsP = [getattr(getattr(i, "item", None), "custom_id", None) for i in _viewP.children]
    check("panneau : quantite et identite dans chaque custom_id",
          all(str(x or "").endswith(":5") and "e30princesss" in str(x or "") for x in _idsP),
          str(_idsP[:2]))
    check("panneau : permanent (sans timeout)", _viewP.timeout is None)
except Exception as _eP:
    check("panneau US : testable", False, repr(_eP)[:120])

print("\n", "=" * 70, "\nNETTOYAGE\n", "=" * 70)
reset()
with jb.transaction():
    check("identité test supprimée", IDENT not in (jb._load() or {}))

print()
print("\n", "=" * 70, "\nFusion des fiches VA dupliquees\n", "=" * 70)
import fusion_vas as _fv

# Le cas exact des captures : une fiche « machine » (sans pseudo) detient les
# comptes, la fiche editee porte le pseudo et affiche 0.
_FU = "_tst_fusion_suite"
_d = jb._load(); _d.pop(_FU, None); jb._save(_d)
for _i in range(14):
    jb.add_account(_FU, "r%d" % _i, va="Roucham")
_d = jb._load()
_d[_FU]["vas"] = [{"name": "Roucham", "discord_username": ""},
                  {"name": "Roucham X1", "discord_username": "roucham_79944"}]
jb._save(_d)

_avant = _fv._total_comptes(jb._load())
_plan = _fv.analyser(jb._load(), _FU)
check("fusion : les deux fiches sont regroupees",
      len(_plan) == 1 and _plan[0]["comptes_deplaces"] == 14, str(_plan))
check("fusion : la fiche PORTANT LE PSEUDO survit",
      _plan[0]["survivant"] == "Roucham X1", str(_plan[0]))
_ok, _msg = _fv.appliquer(_plan)
_d = jb._load()
check("fusion : ecrite sans perdre un seul compte",
      _ok and _fv._total_comptes(_d) == _avant
      and len(_d[_FU]["accounts"]) == 14, _msg[:100])
check("fusion : tous les comptes portent le survivant",
      {a["va"] for a in _d[_FU]["accounts"]} == {"Roucham X1"},
      str({a["va"] for a in _d[_FU]["accounts"]}))
check("fusion : la fiche absorbee a disparu",
      [v["name"] for v in _d[_FU]["vas"]] == ["Roucham X1"],
      str(_d[_FU]["vas"]))
# Sans pierre tombale, le prochain pull du Sheet ferait revenir le nom retire.
check("fusion : pierre tombale sur le nom retire",
      f"{_FU}|roucham" in (jb.tombstones().get("vas") or {}))

# Deux pseudos DIFFERENTS : on ne tranche pas a la place du proprietaire.
_CF = "_tst_fusion_conflit"
_d = jb._load(); _d.pop(_CF, None)
_d[_CF] = {"vas": [{"name": "Jaurel", "discord_username": "aaa"},
                   {"name": "Jaurel X1", "discord_username": "bbb"}],
           "accounts": []}
jb._save(_d)
_pc = _fv.analyser(jb._load(), _CF)
check("fusion : deux pseudos differents = conflit, rien n est fusionne",
      len(_pc) == 1 and _pc[0]["conflit"] is True, str(_pc))
_okc, _ = _fv.appliquer(_pc)
check("fusion : un conflit laisse les deux fiches intactes",
      len(jb._load()[_CF]["vas"]) == 2)

# Deux VA sans rapport ne doivent JAMAIS se rejoindre.
_SR = "_tst_fusion_sansrapport"
_d = jb._load(); _d.pop(_SR, None)
_d[_SR] = {"vas": [{"name": "Alice", "discord_username": "a"},
                   {"name": "Bob", "discord_username": "b"}], "accounts": []}
jb._save(_d)
check("fusion : deux VA distincts ne sont pas regroupes",
      _fv.analyser(jb._load(), _SR) == [])

_d = jb._load()
for _k in (_FU, _CF, _SR):
    _d.pop(_k, None)
jb._save(_d)
import glob as _glob, os as _os
for _b in _glob.glob(str(jb.DATA_DIR / "jailbreak.avant-fusion-*.json")):
    try: _os.unlink(_b)
    except Exception: pass


print("=" * 70)
print("ORDRE DES IDENTITES (range par le proprietaire, vu par les VA)")
print("=" * 70)
try:
    import inspect as _inspOr
    import identites_ordre as _ioOr

    _ordOr = ["lola", "emma", "sarah"]
    check("ordre : les identites rangees passent devant, dans l ordre",
          _ioOr.trier(["zoe", "emma", "lola", "anna"], _ordOr)[:2] == ["lola", "emma"])
    # Les non-rangees ne disparaissent pas : elles suivent, en alphabetique.
    check("ordre : les non-rangees suivent, en alphabetique",
          _ioOr.trier(["zoe", "emma", "lola", "anna"], _ordOr)[2:] == ["anna", "zoe"])
    check("ordre : le rang commence a 1, pas a 0",
          _ioOr.rang("lola", _ordOr) == 1 and _ioOr.rang("emma", _ordOr) == 2)
    check("ordre : une identite non rangee n a pas de rang",
          _ioOr.rang("zoe", _ordOr) is None)

    # Numeroter une liste alphabetique donnerait un FAUX classement : le VA
    # lirait « 1 » comme « celle qui marche le mieux » alors que personne
    # n aurait rien decide.
    check("ordre : sans rangement, aucun numero n est affiche",
          _ioOr.etiqueter(["lola", "zoe"], []) == {"lola": "Lola", "zoe": "Zoe"})
    check("ordre : avec rangement, les numeros partent de 1",
          _ioOr.etiqueter(["emma", "lola"], _ordOr)
          == {"lola": "1. Lola", "emma": "2. Emma"})
    check("ordre : une identite non rangee reste sans numero",
          _ioOr.etiqueter(["lola", "zoe"], _ordOr)["zoe"] == "Zoe")
    check("ordre : un fichier absent ne fait pas tomber la lecture",
          isinstance(_ioOr.lire(), list))

    # LE point qui a failli passer inapercu. Sur les vraies donnees, les six
    # identites FR occupent les rangs 1 a 6 du fichier — mais le menu US ne
    # montre que les models US. Numeroter d apres le FICHIER y aurait affiche
    # « 7. Ibenhaastrup » en premiere ligne, un numero sans aucun sens pour le
    # VA qui le lit. Le numero doit venir de la liste AFFICHEE.
    _globalOr = ["lola", "alicia", "julia", "amelia", "emma", "sarah",
                 "ibenhaastrup", "e30princesss", "zezatwins"]
    _usOr = ["zezatwins", "ibenhaastrup", "e30princesss"]
    _libUs = _ioOr.etiqueter(_usOr, _globalOr)
    check("ordre : un menu filtre numerote a partir de 1, pas du rang global",
          _libUs["ibenhaastrup"] == "1. Ibenhaastrup",
          "obtenu : %r" % _libUs.get("ibenhaastrup"))
    check("ordre : le menu filtre garde l ordre choisi entre elles",
          [_libUs[m] for m in _ioOr.trier(_usOr, _globalOr)]
          == ["1. Ibenhaastrup", "2. E30princesss", "3. Zezatwins"])

    # Le site et le bot doivent trier PAREIL. Deux implementations finiraient
    # par diverger — le depot a deja paye ca avec les deux tables du Drive.
    import web_upload as _wOr
    _srcTri = _inspOr.getsource(_wOr._apply_identity_order)
    check("ordre : le site delegue a la regle partagee",
          "identites_ordre" in _srcTri,
          "le site aurait sa propre regle, qui divergerait")

    # Couper a 25 AVANT de trier ferait disparaitre la model classee premiere
    # si elle est en fin d alphabet.
    import pathlib as _plOr
    _srcBot = _plOr.Path("cogs/user.py").read_text(encoding="utf-8")
    _apres = _srcBot.count("_io.trier(list(models), ordre)[:25]") \
        + _srcBot.count("_io.trier(list(models), _ordre)[:25]")
    check("ordre : on trie AVANT de couper a 25, aux deux endroits",
          _apres == 2, "%d endroit(s) sur 2" % _apres)
    # Les libelles doivent etre calcules sur la liste VISIBLE, aux deux
    # endroits : c est ce qui donne « 1. » et non le rang global.
    _etiq = (_srcBot.count("_io.etiqueter(visibles, ordre)")
             + _srcBot.count("_io.etiqueter(_visibles, _ordre)"))
    check("ordre : les libelles viennent de la liste visible, aux deux endroits",
          _etiq == 2, "%d endroit(s) sur 2" % _etiq)

    # Un numero sans explication n est qu un numero : le VA doit lire QUE
    # c est un classement, sinon « 1. Lola » ne lui apprend rien.
    _phr = _ioOr.phrase_classement(["lola", "emma"], _ordOr)
    check("ordre : le menu explique que les numeros sont un classement",
          "classement" in _phr.lower() and "1" in _phr,
          "phrase : %r" % _phr[:60])
    # Annoncer un classement qui n existe pas serait pire que se taire.
    check("ordre : rien n est annonce quand rien n est range",
          _ioOr.phrase_classement(["zoe", "anna"], _ordOr) == "")
    check("ordre : la phrase est bien posee dans le menu des models",
          "_io.phrase_classement(models)" in _srcBot,
          "les numeros s afficheraient sans etre expliques")
    check("ordre : plus aucune coupe sur la liste non triee",
          "models[:25]" not in _srcBot,
          "une coupe alphabetique subsiste")
except Exception as _eOr:
    check("ordre : testable", False, repr(_eOr)[:170])

print()
print("=" * 70)
print("QUANTITE LIBRE (taper un nombre au lieu de le choisir)")
print("=" * 70)
try:
    import pathlib as _plQ
    from cogs.user import (_JB_QTY_OPTIONS, _JB_QTY_AUTRE, _JB_QTY_MAX,
                           _jb_qty_options)

    _o3 = _jb_qty_options(3)
    check("quantite : les valeurs predefinies sont toujours proposees",
          len(_o3) == len(_JB_QTY_OPTIONS) + 1,
          "%d entrees pour %d valeurs" % (len(_o3), len(_JB_QTY_OPTIONS)))
    check("quantite : l entree de saisie libre est la derniere",
          _o3[-1].value == _JB_QTY_AUTRE,
          "derniere entree : %r" % _o3[-1].value)
    check("quantite : la valeur courante est cochee",
          [o.value for o in _o3 if o.default] == ["3"])

    # Sans reinjection, apres avoir tape 7 le menu n avait plus aucune ligne
    # cochee : on ne savait plus ce qui etait selectionne.
    _o7 = _jb_qty_options(7)
    check("quantite : une valeur libre est reinjectee dans la liste",
          "7" in [o.value for o in _o7])
    check("quantite : et elle apparait cochee",
          [o.value for o in _o7 if o.default] == ["7"])
    check("quantite : la liste reste sous la limite Discord de 25",
          len(_jb_qty_options(_JB_QTY_MAX)) <= 25,
          "%d entrees" % len(_jb_qty_options(_JB_QTY_MAX)))

    # DEUX selects de quantite existent : le menu ephemere et le panneau
    # epingle. N en brancher qu un laisse la moitie des VA sans saisie libre,
    # et rien ne le signale. C est deja arrive avec les icones.
    _srcQ = _plQ.Path("cogs/user.py").read_text(encoding="utf-8")
    check("quantite : les DEUX selects utilisent la meme liste",
          _srcQ.count("_jb_qty_options(") == 3,   # 1 definition + 2 usages
          "%d occurrence(s), 3 attendues" % _srcQ.count("_jb_qty_options("))
    check("quantite : les DEUX callbacks ouvrent la fenetre de saisie",
          _srcQ.count("_JBQtyModal(_suite)") == 2,
          "%d sur 2" % _srcQ.count("_JBQtyModal(_suite)"))
    check("quantite : plus aucune construction d options en dur",
          "for q in _JB_QTY_OPTIONS]" not in _srcQ
          and "for q in _JB_QTY_OPTIONS\n" not in _srcQ,
          "un select fabrique encore sa liste de son cote")
    # Un garde-fou de saisie : sans borne, un VA tapait 9999 et le bot partait
    # chercher neuf mille medias.
    check("quantite : la saisie libre est bornee",
          isinstance(_JB_QTY_MAX, int) and 10 <= _JB_QTY_MAX <= 500)
except Exception as _eQ:
    check("quantite : testable", False, repr(_eQ)[:170])

print()
print("=" * 70)
print("ICONES DES BOUTONS DISCORD (style du site)")
print("=" * 70)
try:
    import re as _reIc
    from pathlib import Path as _PIc
    from cogs.user import (_ICONES_ACTIONS, _JB_ACTIONS_US,
                           _libelle_sans_emoji, icones_actions)

    # Une icone qui ne vise aucune action ne s affichera jamais, et une action
    # sans icone garde son emoji standard : deux oublis silencieux. On exige
    # la correspondance exacte.
    _clesAct = {c for c, _l, _a, _s in _JB_ACTIONS_US}
    _orphelines = sorted(set(_ICONES_ACTIONS) - _clesAct)
    check("icones : aucune icone ne vise une action inexistante",
          not _orphelines, ", ".join(_orphelines))
    _sansIc = sorted(_clesAct - set(_ICONES_ACTIONS))
    check("icones : chaque action du panneau US a son icone",
          not _sansIc, ", ".join(_sansIc))

    _dossierIc = _PIc(__file__).parent / "emojis"
    _manquants, _mauvais = [], []
    for _cle, _nom in _ICONES_ACTIONS.items():
        # Discord refuse tout ce qui sort de [a-z0-9_], et coupe a 32.
        if not _reIc.fullmatch(r"[a-z0-9_]{2,32}", _nom):
            _mauvais.append(_nom)
        if not (_dossierIc / f"{_nom}.png").exists():
            _manquants.append(_nom)
    check("icones : les noms sont acceptables par Discord",
          not _mauvais, ", ".join(_mauvais))
    check("icones : tous les fichiers PNG sont presents",
          not _manquants, "absents : " + ", ".join(_manquants))

    # Un PNG trop lourd ou mal dimensionne est refuse au televersement, et on
    # ne s en apercoit que le jour ou le menu est repose.
    try:
        from PIL import Image as _ImIc
        _pbIc = []
        for _nom in _ICONES_ACTIONS.values():
            _f = _dossierIc / f"{_nom}.png"
            if not _f.exists():
                continue
            if _f.stat().st_size > 256000:
                _pbIc.append(f"{_nom} trop lourd")
                continue
            with _ImIc.open(_f) as _im:
                if _im.size != (128, 128):
                    _pbIc.append(f"{_nom} en {_im.size[0]}x{_im.size[1]}")
                elif _im.mode != "RGBA":
                    _pbIc.append(f"{_nom} sans transparence ({_im.mode})")
        check("icones : 128x128, transparentes, sous la limite Discord",
              not _pbIc, " | ".join(_pbIc))
    except ImportError:
        check("icones : PIL disponible pour verifier les PNG", True, "PIL absent")

    # Sans ce retrait, le bouton afficherait DEUX icones : celle du serveur et
    # l emoji reste dans le libelle.
    check("icones : l emoji de tete est retire du libelle",
          _libelle_sans_emoji("\U0001F4AC Reel caption") == "Reel caption")
    check("icones : un libelle sans emoji n est pas ampute",
          _libelle_sans_emoji("Reel caption") == "Reel caption")
    # Au clic, on LIT seulement : televerser prendrait treize appels API dans
    # le delai de 3 s d une interaction, et le bouton paraitrait mort.
    check("icones : la lecture sans serveur ne leve pas",
          icones_actions(None) == {})

    # Il existe DEUX implementations de boutons d action : celle du menu
    # ephemere et celle du panneau EPINGLE du salon. N en brancher qu une
    # laisse le panneau qu on regarde toute la journee avec ses vieux emojis,
    # et rien ne le signale. C est arrive.
    import inspect as _inspIc
    from cogs.user import JBActionButton as _BtnPerm
    from cogs.user import _JailbreakActionButton as _BtnEph
    from cogs.user import _jb_panel as _PanIc
    check("icones : le bouton du panneau EPINGLE accepte une icone",
          "icone" in _inspIc.signature(_BtnPerm.__init__).parameters,
          "le panneau du salon garderait les emojis standard")
    check("icones : le bouton du menu ephemere accepte une icone",
          "icone" in _inspIc.signature(_BtnEph.__init__).parameters)
    check("icones : le panneau epingle recoit le serveur",
          "guild" in _inspIc.signature(_PanIc).parameters,
          "sans serveur, impossible de retrouver les icones televersees")
except Exception as _eIc:
    check("icones : testable", False, repr(_eIc)[:170])

# ==============================================================================
# Pastilles « ce qui marche » : la MEME table pour le site et pour les menus
# ==============================================================================
try:
    import identity_styles as _ist
    import pathlib as _plSt
    _fSt = _ist.FICHIER
    _savSt = _fSt.read_text(encoding="utf-8") if _fSt.exists() else None
    _prevSt = _fSt.with_suffix(".json.prev")
    _savPrevSt = _prevSt.read_text(encoding="utf-8") if _prevSt.exists() else None
    _EMO_CAP, _EMO_FLASH = "💬", "⚡"
    try:
        check("styles : quatre styles, et le flash en fait partie",
              len(_ist.STYLES) == 4 and "flash" in _ist.CLES
              and dict((c, e) for c, e, _l, _co, _t in _ist.STYLES)["flash"] == _EMO_FLASH)

        # Aller-retour, et ordre NORMALISE : deux models aux memes styles
        # doivent se lire pareil, quel que soit l ordre des clics.
        _ist.definir("zz_style", ["flash", "caption"])
        check("styles : enregistre puis relu, dans l ordre de la table",
              _ist.de("zz_style") == ["caption", "flash"], str(_ist.de("zz_style")))
        check("styles : les emoji sortent colles, sans separateur",
              _ist.emojis("zz_style") == _EMO_CAP + _EMO_FLASH,
              "%d caractere(s)" % len(_ist.emojis("zz_style")))
        check("styles : une model sans style ne rend rien",
              _ist.emojis("zz_jamais_cochee") == "")

        # Tout decocher est une ecriture : sinon on ne peut jamais retirer la
        # derniere pastille.
        _ist.definir("zz_style", [])
        check("styles : tout decocher marche, et ne laisse pas d entree morte",
              _ist.de("zz_style") == [] and "zz_style" not in _ist._table())

        # Le libelle des menus Discord : rang + pastilles, en UN seul endroit.
        from cogs.user import _libelle_model
        _ist.definir("zz_style", ["caption", "flash"])
        _attSt = "3. Zz_style " + _EMO_CAP + _EMO_FLASH
        check("styles : le libelle du menu porte le rang PUIS les pastilles",
              _libelle_model("zz_style", {"zz_style": "3. Zz_style"}) == _attSt,
              "%d caractere(s) rendus"
              % len(_libelle_model("zz_style", {"zz_style": "3. Zz_style"})))
        check("styles : une model sans style garde son libelle intact",
              _libelle_model("zz_jamais_cochee", {"zz_jamais_cochee": "5. Ellieann"})
              == "5. Ellieann")

        # Discord plafonne un libelle de bouton a 80 caracteres. La coupe doit
        # tomber sur le NOM : couper la fin emporterait justement ce qu on
        # vient d ajouter, et le bouton redeviendrait muet.
        _longSt = "9. " + ("Zoe" * 40)
        _labSt = _libelle_model("zz_style", {"zz_style": _longSt})
        check("styles : un nom demesure est coupe, pas les pastilles",
              len(_labSt) <= 80 and _labSt.endswith(_ist.emojis("zz_style")),
              "len=%d" % len(_labSt))

        # Les DEUX menus qui listent des models doivent passer par ce seul
        # fabricant : sinon l un des deux garde les vieux libelles au premier
        # style ajoute. Meme garde que pour _io.etiqueter, juste au-dessus.
        _srcSt = _plSt.Path("cogs/user.py").read_text(encoding="utf-8")
        check("styles : les deux menus passent par le meme fabricant",
              _srcSt.count("_libelle_model(m, ") == 2,
              "%d appel(s) sur 2" % _srcSt.count("_libelle_model(m, "))

        # Une seule table : le site ne doit pas en tenir une deuxieme.
        _srcWu = _plSt.Path("web_upload.py").read_text(encoding="utf-8")
        check("styles : le site puise dans le module, il ne recopie pas la table",
              "import identity_styles as _styles_mod" in _srcWu
              and _srcWu.count('("caption", "' + _EMO_CAP + '"') == 0)
    finally:
        for _pSt, _vSt in ((_fSt, _savSt), (_prevSt, _savPrevSt)):
            if _vSt is not None:
                _pSt.write_text(_vSt, encoding="utf-8")
            else:
                _pSt.unlink(missing_ok=True)
        _ist._CACHE.update(sig=None, data={})
except Exception as _eSt:
    check("styles : testable", False, repr(_eSt)[:200])


# ==============================================================================
# Mise a jour AUTOMATIQUE des menus Discord quand une pastille change
# ==============================================================================
try:
    import asyncio as _aioMj
    import threading as _thMj
    import time as _tMj
    import cogs.welcome as _wMj

    class _SalonMj:
        def __init__(self, nom, guild):
            self.name, self.guild = nom, guild
            self.id = abs(hash(nom)) % 10**9

    class _GuildMj:
        def __init__(self, nom, salons):
            self.name = nom
            self.text_channels = [_SalonMj(s, self) for s in salons]

    class _BotMj:
        def __init__(self, guilds, boucle):
            self.guilds, self.loop = guilds, boucle
            self.user = type("U", (), {"id": 1})()

    _boucleMj = _aioMj.new_event_loop()
    _thMj.Thread(target=_boucleMj.run_forever, daemon=True).start()
    _vraiMaj = _wMj.maj_menu_marche
    _vraiPause = _wMj.PAUSE_ENTRE_SALONS_S
    _vraiDelai = _wMj.DELAI_REGROUPEMENT_S
    try:
        _botMj = _BotMj([_GuildMj("US", ["a-menu", "b-menu", "c-menu", "d-menu",
                                         "a-content", "general"]),
                         _GuildMj("FR", ["va-emma-menu", "annonces"])], _boucleMj)
        _vusMj = []

        async def _mouchardMj(b, ch, marche=None):
            _vusMj.append(ch.name)
            return True

        _wMj.maj_menu_marche = _mouchardMj
        _wMj.PAUSE_ENTRE_SALONS_S = 0.01
        _wMj.DELAI_REGROUPEMENT_S = 0.4

        _resMj = _aioMj.run_coroutine_threadsafe(
            _wMj.rafraichir_menus_jailbreak(_botMj, raison="banc"), _boucleMj).result(timeout=60)
        check("majmenu : seuls les salons -menu sont redessines",
              sorted(_vusMj) == sorted(["a-menu", "b-menu", "c-menu", "d-menu",
                                        "va-emma-menu"]),
              str(sorted(_vusMj))[:110])
        check("majmenu : ni les -content ni les salons ordinaires",
              "a-content" not in _vusMj and "general" not in _vusMj
              and "annonces" not in _vusMj)
        check("majmenu : le bilan compte ce qui est passe",
              _resMj == {"salons": 5, "faits": 5, "rates": 0}, str(_resMj))

        # Cocher six models d affilee ne doit PAS lancer six passages sur tout
        # le parc : les demandes proches se regroupent, la derniere gagne.
        _vusMj.clear()
        for _iMj in range(6):
            _wMj.demander_rafraichissement(_botMj, raison="coche %d" % _iMj)
            _tMj.sleep(0.03)
        _tMj.sleep(1.6)
        check("majmenu : une salve de coches ne donne qu un seul passage",
              len(_vusMj) == 5, "%d edition(s) au lieu de 5" % len(_vusMj))

        # Un salon qui refuse ne doit pas emporter les autres avec lui.
        _vusMj.clear()

        async def _capricieuxMj(b, ch, marche=None):
            _vusMj.append(ch.name)
            if ch.name == "b-menu":
                raise RuntimeError("Discord a dit non")
            return True

        _wMj.maj_menu_marche = _capricieuxMj
        _resMj2 = _aioMj.run_coroutine_threadsafe(
            _wMj.rafraichir_menus_jailbreak(_botMj, raison="banc2"), _boucleMj).result(timeout=60)
        check("majmenu : un salon en panne n arrete pas la tournee",
              _resMj2["salons"] == 5 and _resMj2["faits"] == 4
              and _resMj2["rates"] == 1, str(_resMj2))

        # Le site tourne aussi sans bot (poste local, bot a l arret) : la
        # demande doit se taire, pas lever.
        check("majmenu : sans bot, on ne reveille rien et on ne plante pas",
              _wMj.demander_rafraichissement(None, raison="rien") is False)
        check("majmenu : sans boucle vivante non plus",
              _wMj.demander_rafraichissement(
                  type("B", (), {"loop": None})(), raison="rien") is False)
    finally:
        _wMj.maj_menu_marche = _vraiMaj
        _wMj.PAUSE_ENTRE_SALONS_S = _vraiPause
        _wMj.DELAI_REGROUPEMENT_S = _vraiDelai
        _boucleMj.call_soon_threadsafe(_boucleMj.stop)
except Exception as _eMj:
    check("majmenu : testable", False, repr(_eMj)[:200])


# ==============================================================================
# Brutes nues : toutes les voies doivent passer par la MEME reecriture
# ==============================================================================
try:
    import asyncio as _aioBr
    import tempfile as _tmpBr
    import pathlib as _plBr
    import cogs.user as _uBr

    _dosBr = _plBr.Path(_tmpBr.mkdtemp(prefix="tstbrut_"))
    _srcBr = _dosBr / "brute.mp4"
    _srcBr.write_bytes(b"x" * 5000)
    _vraiCfgBr = _uBr.load_transform_config
    _vraiTrBr = _uBr.transform_metadata_strict
    try:
        _appelsBr = []

        def _essaiBr(actif, rendu, ecrit=True, vide=False):
            _uBr.load_transform_config = lambda: {"enabled": actif}

            def _fauxBr(entree, sortie, *a, **k):
                _appelsBr.append(_plBr.Path(entree).name)
                if ecrit:
                    _plBr.Path(sortie).write_bytes(b"" if vide else b"y" * 4000)
                return rendu

            _uBr.transform_metadata_strict = _fauxBr
            with _tmpBr.TemporaryDirectory() as _d:
                _f, _r, _rs = _aioBr.run(_uBr.brute_a_envoyer(_srcBr, _d, "julia"))
                return _f, _r

        # Interrupteur eteint : on ne touche a rien, et on n appelle meme pas
        # ffmpeg — sinon une brute de 200 Mo passerait au remux pour rien.
        _appelsBr.clear()
        _fBr, _rBr = _essaiBr(False, True)
        check("brutmeta : interrupteur eteint, la brute part telle quelle",
              _plBr.Path(_fBr) == _srcBr and _rBr is False and not _appelsBr,
              "%s / %s / %d appel(s)" % (_plBr.Path(_fBr).name, _rBr, len(_appelsBr)))

        _appelsBr.clear()
        _fBr, _rBr = _essaiBr(True, True)
        check("brutmeta : allume, c est le fichier REECRIT qui part",
              _plBr.Path(_fBr) != _srcBr and _rBr is True and len(_appelsBr) == 1)

        # ffmpeg absent ou en echec : la video part QUAND MEME. Un envoi ne
        # doit pas s arreter pour ca.
        _fBr, _rBr = _essaiBr(True, False)
        check("brutmeta : ffmpeg en echec, la video part quand meme",
              _plBr.Path(_fBr) == _srcBr and _rBr is False)

        # On ne croit pas le booleen sur parole : un ffmpeg qui rend 0 en
        # laissant un fichier vide, c est arrive.
        _fBr, _rBr = _essaiBr(True, True, vide=True)
        check("brutmeta : une sortie vide n est pas une reussite",
              _plBr.Path(_fBr) == _srcBr and _rBr is False)
        _fBr, _rBr = _essaiBr(True, True, ecrit=False)
        check("brutmeta : une sortie absente non plus",
              _plBr.Path(_fBr) == _srcBr and _rBr is False)

        # LA garde qui compte : trois boutons envoient une brute NUE (Video
        # brut, Video brut Banger, et « Telle quelle » apres Choisir ma brute).
        # « Telle quelle » envoyait le fichier du disque : l uniquification
        # etait allumee et ne s appliquait pas la, sans un mot.
        _srcUBr = _plBr.Path("cogs/user.py").read_text(encoding="utf-8")
        check("brutmeta : le VA est averti quand la brute part inchangee",
              _srcUBr.count("pas** pu etre rendue unique") == 2,
              "%d avertissement(s) sur 2"
              % _srcUBr.count("pas** pu etre rendue unique"))
        check("brutmeta : toutes les voies passent par le meme reecrivain",
              _srcUBr.count("await brute_a_envoyer(") == 2,
              "%d appel(s) sur 2" % _srcUBr.count("await brute_a_envoyer("))
        check("brutmeta : plus aucune brute nue envoyee droit du disque",
              "file=discord.File(str(self.video), filename=self.video.name)"
              not in _srcUBr)
        # Un seul endroit decide s il faut uniquifier — sinon deux boutons
        # peuvent diverger sans que rien ne le signale.
        check("brutmeta : un seul endroit lit l interrupteur",
              _srcUBr.count('cfg.get("enabled", False)') == 1,
              "%d lecture(s)" % _srcUBr.count('cfg.get("enabled", False)'))
        # Et un seul endroit choisit le MODE : metadonnees seules si le VA
        # monte la brute, transformation complete s il la poste telle quelle.
        check("brutmeta : le mode vient de la page, pas d une constante",
              _srcUBr.count('cfg.get("metadata_only", True)') == 1
              and "transform_full_strict" in _srcUBr,
              "%d lecture(s) du mode" % _srcUBr.count('cfg.get("metadata_only", True)'))
        check("brutmeta : le re-encodage est reessaye avant d abandonner",
              "_BRUTE_ESSAIS" in _srcUBr and _uBr._BRUTE_ESSAIS >= 2,
              str(getattr(_uBr, "_BRUTE_ESSAIS", None)))
        check("brutmeta : la derniere tentative passe en mode sur",
              "mono_thread" in _srcUBr)
        check("brutmeta : la sortie est bornee pour tenir sur Discord",
              "plafond_mo" in _srcUBr and 0 < _uBr._PLAFOND_DISCORD_MO <= 10,
              str(getattr(_uBr, "_PLAFOND_DISCORD_MO", None)))
    finally:
        _uBr.load_transform_config = _vraiCfgBr
        _uBr.transform_metadata_strict = _vraiTrBr
        import shutil as _shBr
        _shBr.rmtree(_dosBr, ignore_errors=True)
except Exception as _eBr:
    check("brutmeta : testable", False, repr(_eBr)[:200])


# ==============================================================================
# Panneau orphelin : un bouton pose par un bot qui n a plus le code
# ==============================================================================
try:
    import asyncio as _aioPe
    from cogs.general import PanneauPerime as _PePe, General as _GePe
    from cogs.numeros import NumPanelView as _NpPe

    def _idsPe(vue):
        return sorted(str(getattr(c, "custom_id", "")) for c in vue.children
                      if getattr(c, "custom_id", None))

    _vuePe = _PePe()
    # Les identifiants doivent coller EXACTEMENT a ceux du vrai panneau :
    # c est par eux que Discord retrouve le repondant. Un seul qui differe et
    # ce bouton-la retombe sur « n a pas repondu a temps ».
    # Le filet doit couvrir TOUT ce qu un ancien panneau porte — donc au moins
    # les boutons du panneau actuel, plus ceux qui en ont ete retires depuis
    # (« Autre service »). Un message Discord ne se redessine pas : le bouton
    # d hier est toujours cliquable demain.
    from cogs.numeros import _PanneauAncienView as _PaPe
    _vraisPe = set(_idsPe(_NpPe(None))) | set(_idsPe(_PaPe(None)))
    check("perime : le filet couvre tous les boutons d un ancien panneau",
          set(_idsPe(_vuePe)) >= _vraisPe,
          "manque : %s" % sorted(_vraisPe - set(_idsPe(_vuePe))))
    check("perime : la vue est persistante (elle survit au redemarrage)",
          _vuePe.timeout is None)
    check("perime : elle dit quoi faire, pas seulement que c est casse",
          "panelnumero" in _PePe._MOT and "périmé" in _PePe._MOT)

    # Elle ne doit se poser QUE sur un bot qui n a pas le vrai cog, sinon
    # elle volerait ses propres clics au bot admin.
    class _BotPe:
        def __init__(self, avec_cog):
            self._avec = avec_cog
            self.vues = []

        def get_cog(self, nom):
            return object() if (self._avec and nom == "NumerosCog") else None

        def add_view(self, v):
            self.vues.append(v)

    _bSans = _BotPe(False)
    _aioPe.run(_GePe(_bSans).cog_load())
    check("perime : le filet se pose quand le vrai cog est absent",
          len(_bSans.vues) == 1 and isinstance(_bSans.vues[0], _PePe))
    _bAvec = _BotPe(True)
    _aioPe.run(_GePe(_bAvec).cog_load())
    check("perime : et JAMAIS sur le bot qui sert vraiment les panneaux",
          _bAvec.vues == [], "il volerait les clics du bot admin")

    # Les deux cogs ne doivent pas vivre sur le meme bot : c est ce qui rend
    # le filet sans risque.
    import main as _mainPe
    check("perime : general et numeros ne sont pas sur le meme bot",
          ("general" in _mainPe.MAIN_COGS and "numeros" not in _mainPe.MAIN_COGS
           and "numeros" in _mainPe.ADMIN_COGS),
          "MAIN=%s ADMIN=%s" % (_mainPe.MAIN_COGS[-3:], _mainPe.ADMIN_COGS))
except Exception as _ePe:
    check("perime : testable", False, repr(_ePe)[:200])


# ==============================================================================
# /resetpanels : emporter AUSSI le panneau orphelin de l autre bot
# ==============================================================================
try:
    import inspect as _insRs
    import pathlib as _plRs
    from cogs.numeros import NumerosCog as _NcRs

    _srcRs = _insRs.getsource(_NcRs.resetpanels.callback
                              if hasattr(_NcRs.resetpanels, "callback")
                              else _NcRs.resetpanels)
    # Le panneau pose avant le demenagement du cog appartient a l AUTRE
    # application : ne nettoyer que nos propres messages laissait le cadavre
    # epingle a cote du neuf, deux panneaux identiques dont un mort.
    check("reset : le nettoyage ne se limite plus a nos propres messages",
          "p.author.id == me" not in _srcRs,
          "il ne verrait toujours pas le panneau orphelin")
    check("reset : mais il reste borne aux messages de BOT",
          'getattr(p.author, "bot", False)' in _srcRs)
    check("reset : et au titre de nos panneaux",
          "any(k in t for k in titles)" in _srcRs)
    check("reset : les deux libelles du panneau numero sont vises",
          "Numéro & Mail" in _srcRs and "Numéros & Mails" in _srcRs,
          "un panneau ancien libelle survivrait")

    # Le titre a change en cours de route : la reconnaissance cherchait encore
    # l ancien, qui n est pas un morceau du nouveau -> un panneau de plus a
    # chaque passage.
    _srcWe = _plRs.Path("cogs/welcome.py").read_text(encoding="utf-8")
    _iWe = _srcWe.index("async def _ensure_num_panel")
    _blocWe = _srcWe[_iWe:_iWe + 1800]
    check("panneau : le titre reellement pose est reconnu",
          "Numéros & Mails" in _blocWe,
          "_ensure_num_panel reposterait un panneau a chaque passage")
    from cogs.numeros import panel_embed as _peRs
    check("panneau : et c est bien celui que panel_embed produit",
          "Numéros & Mails" in (_peRs().title or ""), (_peRs().title or "")[:40])
except Exception as _eRs:
    check("reset : testable", False, repr(_eRs)[:200])


# ==============================================================================
# « Aucun salon » doit dire POURQUOI, pas seulement constater
# ==============================================================================
try:
    from cogs.numeros import _pourquoi_aucun_salon as _pqPq

    class _ChPq:
        def __init__(s, n): s.name = n

    class _GuPq:
        def __init__(s, noms): s.text_channels = [_ChPq(n) for n in noms]

    # Le cas reel : le bot est bien sur le serveur, mais ne voit que deux
    # salons — les tickets sont fermes pour lui. « Aucun salon » laissait
    # croire qu ils n existaient pas.
    _m1 = _pqPq(_GuPq(["general", "annonces"]), None, ("-menu", "-numero-mail"))
    check("pourquoi : il dit combien de salons il VOIT",
          "2" in _m1 and "visible" in _m1, _m1[:80])
    check("pourquoi : et il nomme la permission qui manque",
          "Voir les salons" in _m1, _m1[:120])

    # Un nom presque bon est la piste la plus utile : on le montre.
    _m2 = _pqPq(_GuPq(["6994-numero", "6994-content", "a", "b", "c", "d"]),
                None, ("-numero-mail",))
    check("pourquoi : un salon presque bon est montre",
          "6994-numero" in _m2 and "finir" in _m2, _m2[:130])

    # Beaucoup de salons visibles : ce n est plus la permission qu on soupconne
    # en premier, on ne doit pas envoyer l admin sur une fausse piste.
    _m3 = _pqPq(_GuPq(list("abcdefgh")), None, ("-numero-mail",))
    check("pourquoi : avec beaucoup de salons, pas de faux diagnostic",
          "C'est peu" not in _m3 and "8" in _m3, _m3[:90])

    # Le message reste envoyable : Discord coupe a 2000 caracteres.
    _m4 = _pqPq(_GuPq(["salon-tres-long-%03d" % i for i in range(300)]),
                None, ("-numero-mail",))
    check("pourquoi : il donne toujours une issue qui marche",
          all("/panelnumero" in m for m in (_m1, _m2, _m3)),
          "un message laisse l admin sans rien a faire")
    check("pourquoi : le message tient dans une reponse Discord",
          len(_m4) < 1900, "%d caracteres" % len(_m4))
except Exception as _ePq:
    check("pourquoi : testable", False, repr(_ePq)[:200])


# ==============================================================================
# Le panneau numero saute quand le bot n a pas le cog : ca doit se DIRE
# ==============================================================================
try:
    import inspect as _insSa
    import cogs.welcome as _weSa
    _srcSa = _insSa.getsource(_weSa._ensure_num_panel)
    check("saut : le bot sans NumerosCog le journalise au lieu de se taire",
          "log.warning" in _srcSa and "NumerosCog" in _srcSa,
          "le panneau etait saute sans une trace")
    check("saut : et le message dit quoi faire",
          "panelnumeroall" in _srcSa)
    # Le bot principal cree les tickets mais n a PAS le cog : c est bien ce
    # chemin-la qui se declenche en production.
    import main as _mnSa
    check("saut : c est bien le cas du bot qui cree les tickets",
          "welcome" in _mnSa.MAIN_COGS and "numeros" not in _mnSa.MAIN_COGS)
except Exception as _eSa:
    check("saut : testable", False, repr(_eSa)[:200])

# ==============================================================================
# /panelnumero : la voie sure, dans le salon ou l on est
# ==============================================================================
try:
    import inspect as _insIc
    from cogs.numeros import NumerosCog as _NcIc
    _srcIc = _insIc.getsource(_NcIc.panelnumero.callback
                              if hasattr(_NcIc.panelnumero, "callback")
                              else _NcIc.panelnumero)
    # Aucun filtre sur le nom : la convention -numero-mail n existe que sur le
    # serveur des tickets. Ailleurs le salon s appelle sms-email ou autrement,
    # et les commandes « all » ne trouvent rien parmi 156 salons.
    # On vise le CODE, pas la prose : la docstring explique justement
    # pourquoi le filtre n existe pas, elle cite donc le suffixe.
    _codeIc = _srcIc.split('"""')[-1]
    check("ici : aucun filtre sur le nom du salon",
          "endswith(" not in _codeIc and "interaction.channel" in _codeIc,
          "un filtre de nom est revenu dans le corps")
    # Le panneau mort, epingle, appartient a l autre application : sans
    # nettoyage on pose le neuf a cote du cadavre.
    check("ici : les anciens panneaux epingles sont retires",
          'getattr(p.author, "bot", False)' in _srcIc
          and "Numéros & Mails" in _srcIc and "Numéro & Mail" in _srcIc)
    # L epinglage a demenage dans poser_trois, qui pose les TROIS messages.
    import cogs.numeros as _n3b
    check("ici : les trois messages sont epingles",
          "msg.pin()" in _insIc.getsource(_n3b.poser_trois))
    # Une pose incomplete ne doit pas passer pour une reussite muette.
    check("ici : une pose incomplete est dite",
          "incomplète" in _srcIc or "incomplete" in _srcIc)
    check("ici : et le nombre d anciens retires est rendu",
          "ancien(s) panneau(x) retiré(s)" in _srcIc)
except Exception as _eIc:
    check("ici : testable", False, repr(_eIc)[:200])


# ==============================================================================
# « ils sont pourtant la » : comparer avec ce que voit l AUTRE bot
# ==============================================================================
try:
    import sys as _syCp, types as _tyCp
    import cogs.numeros as _nuCp

    class _ChCp:
        def __init__(s, n): s.name = n

    class _GuCp:
        def __init__(s, noms): s.text_channels = [_ChCp(n) for n in noms]; s.id = 7

    class _BoCp:
        def __init__(s, g): s._g = g
        def get_guild(s, gid): return s._g

    _admCp = _GuCp(["général", "test", "sms-email"])
    _prCp = _GuCp(["bid_a-menu", "bid_a-numero-mail",
                   "abdoul_9684-numero-mail"] + ["x%d" % i for i in range(40)])
    _fauxCp = _tyCp.ModuleType("main")
    _fauxCp.main_bot = _BoCp(_prCp)
    _fauxCp.admin_bot = None
    _vraiCp = _syCp.modules.get("main")
    _syCp.modules["main"] = _fauxCp
    _syCp.modules["__main__"].main_bot = _fauxCp.main_bot
    _syCp.modules["__main__"].admin_bot = _fauxCp.admin_bot
    try:
        _mCp = _nuCp._pourquoi_aucun_salon(_admCp, _BoCp(_admCp), ("-numero-mail",))
    finally:
        if _vraiCp is not None:
            _syCp.modules["main"] = _vraiCp
        else:
            _syCp.modules.pop("main", None)

    # Les deux bots tournent dans le meme processus : on peut trancher entre
    # « mauvais nom » et « acces manquant » au lieu de supposer.
    check("compare : il dit combien l AUTRE bot en voit",
          "principal" in _mCp and "**2**" in _mCp, _mCp[-260:])
    check("compare : et il tranche — un acces, pas un nom",
          "pas un problème de nom" in _mCp)
    check("compare : l issue de secours reste donnee",
          "/panelnumero" in _mCp)

    # Sans autre bot joignable, le message doit rester entier et sans trace
    # d erreur : un diagnostic en plus ne peut pas casser celui d avant.
    _videCp = _tyCp.ModuleType("main")
    _videCp.main_bot = None
    _videCp.admin_bot = None
    _syCp.modules["main"] = _videCp
    _syCp.modules["__main__"].main_bot = None
    _syCp.modules["__main__"].admin_bot = None
    try:
        _m2Cp = _nuCp._pourquoi_aucun_salon(_admCp, _BoCp(_admCp), ("-numero-mail",))
    finally:
        if _vraiCp is not None:
            _syCp.modules["main"] = _vraiCp
        else:
            _syCp.modules.pop("main", None)
    # L absence de la ligne « il en voit N » etait deja la reponse, mais une
    # ligne qui ne s affiche pas ne dit rien : on cherchait une permission
    # alors que les deux bots etaient d accord — ces salons sont ailleurs.
    _frCp = _GuCp(["général", "test", "sms-email"])
    _usCp = _GuCp(["bid_a-menu", "bid_a-numero-mail"])
    _frCp.id, _usCp.id = 1, 2
    _frCp.name, _usCp.name = "YouLab AGENCY", "Youl4b"

    class _Bo2Cp:
        def __init__(s, gs): s.guilds = gs
        def get_guild(s, gid): return next((g for g in s.guilds if g.id == gid), None)

    _m2b = _tyCp.ModuleType("main")
    _m2b.main_bot = _Bo2Cp([_frCp, _usCp])
    _m2b.admin_bot = None
    _syCp.modules["main"] = _m2b
    _syCp.modules["__main__"].main_bot = _m2b.main_bot
    _syCp.modules["__main__"].admin_bot = _m2b.admin_bot
    try:
        _mAil = _nuCp._pourquoi_aucun_salon(_frCp, _Bo2Cp([_frCp]), ("-numero-mail",))
    finally:
        if _vraiCp is not None:
            _syCp.modules["main"] = _vraiCp
        else:
            _syCp.modules.pop("main", None)
    check("compare : quand les salons sont AILLEURS, il nomme le serveur",
          "Youl4b" in _mAil and "AUTRE serveur" in _mAil, _mAil[-200:])
    check("compare : et il n accuse plus une permission a tort",
          "acces qui manque" not in _mAil)

    # Le programme tourne sous « __main__ » : « import main » en fabriquerait
    # une copie neuve, aux bots deconnectes, et la comparaison rendrait
    # toujours zero. Elle l a fait, et son silence a ete pris pour une reponse.
    _srcCp = _plSt.Path("cogs/numeros.py").read_text(encoding="utf-8")         if "_plSt" in dir() else __import__("pathlib").Path(
            "cogs/numeros.py").read_text(encoding="utf-8")
    check("compare : on lit le programme qui TOURNE, pas une copie",
          "__main__" in _srcCp and "import main as" not in _srcCp,
          "un import main recreerait des bots deconnectes")

    check("compare : sans second bot, le message tient quand meme",
          "Voir les salons" in _m2Cp and "/panelnumero" in _m2Cp
          and "🔎" not in _m2Cp)
except Exception as _eCp:
    check("compare : testable", False, repr(_eCp)[:200])


# ==============================================================================
# « juste le menu dans leur salon » : nettoyer avant de reposer
# ==============================================================================
try:
    import inspect as _insNe
    from cogs.numeros import NumerosCog as _NcNe
    _sNe = _insNe.getsource(_NcNe.panelnumeroall.callback
                            if hasattr(_NcNe.panelnumeroall, "callback")
                            else _NcNe.panelnumeroall)
    check("nettoyer : l option existe et est fausse par defaut",
          "nettoyer: bool = False" in _sNe,
          "vider un salon ne doit jamais etre le comportement par defaut")
    # On efface ce que les BOTS ont pose — les deux applications, l ancien
    # panneau venant de l autre. Les messages des humains restent : ils sont
    # irrecuperables et personne n a demande a les perdre.
    check("nettoyer : la purge ne vise que les messages de bot",
          "m.author.bot" in _sNe and "purge(limit=" in _sNe)
    # Ce ne sont plus un panneau mais les TROIS messages qui sont reposes.
    check("nettoyer : les trois messages sont reposes juste apres",
          "poser_trois" in _sNe.split("purge")[1][:600])
    check("nettoyer : et le salon repasse en lecture seule",
          "verrouiller_salon" in _sNe)
    check("nettoyer : le compte rendu dit combien a ete efface",
          "message(s) de bot effac" in _sNe)
    check("nettoyer : et l option se rappelle quand on ne l a pas mise",
          "nettoyer:true" in _sNe)
except Exception as _eNe:
    check("nettoyer : testable", False, repr(_eNe)[:200])


# ==============================================================================
# RENOMMER UNE FICHE : ne fusionne personne, et le passe de paie suit
# ==============================================================================
# Deux defauts trouves par une chasse adverse sur le pipeline de paie. Les
# deux se reproduisent des qu on retire le correctif : verifie en remettant
# l ancien comportement, pas seulement en constatant que ca marche.
try:
    import json as _jR, tempfile as _tR, pathlib as _pR
    import jb_objectifs as _obR

    _svR = (_obR.HISTO_FILE, _obR.OBJECTIFS_FILE)
    _dosR = _pR.Path(_tR.mkdtemp())
    _obR.HISTO_FILE = _dosR / "h.json"
    _obR.OBJECTIFS_FILE = _dosR / "o.json"
    _memR = {}
    _vraiLoad, _vraiSave = jb._load, jb._save
    _vraiTa, _vraiTc = jb.tomb_add, jb.tomb_clear
    jb._load = lambda: _jR.loads(_jR.dumps(_memR))
    jb._save = lambda d: (_memR.clear(), _memR.update(_jR.loads(_jR.dumps(d))))
    jb.tomb_add = lambda *a, **k: None
    jb.tomb_clear = lambda *a, **k: None

    def _baseR():
        """Une identite avec une fiche IMPLICITE : « Roucham X2 » est porte par
        vingt comptes mais absent de vas[]. Cet etat n est pas theorique — la
        synchro Sheet le produit (bloc de coherence, sheets_sync), et
        list_vas_for_identity affiche donc la fiche dans la barre laterale."""
        return {"jessye": {
            "vas": [{"name": "Roucham X1", "discord_username": "roucham_2213"},
                    {"name": "Fatou X1", "discord_username": "fatou_9081"}],
            "accounts": [{"va": "Roucham X1", "username": f"r{_i}"} for _i in range(8)]
                      + [{"va": "Fatou X1", "username": f"f{_i}"} for _i in range(6)]
                      + [{"va": "Roucham X2", "username": f"x{_i}"} for _i in range(20)]}}

    # ---- 1. renommer SUR une fiche implicite fusionnait deux personnes -----
    _memR.clear(); _memR.update(_baseR())
    _avantR = sorted(jb.list_va_names_for_identity("jessye"))
    _rR = jb.update_va("jessye", "Roucham X1", new_name="Roucham X2")
    _nX2 = sum(1 for _a in _memR["jessye"]["accounts"] if _a["va"] == "Roucham X2")
    check("renommage : sur un nom deja porte par des comptes -> refuse",
          _rR is False, _rR)
    check("renommage : aucune fiche n a bouge",
          sorted(jb.list_va_names_for_identity("jessye")) == _avantR,
          sorted(jb.list_va_names_for_identity("jessye")))
    check("renommage : les deux jeux de comptes restent separes",
          _nX2 == 20, _nX2)

    # Le meme scenario avec l ANCIEN test de conflit : il doit casser, sinon
    # ces trois verifications ne prouvent rien.
    _memR.clear(); _memR.update(_baseR())
    _vraiNoms = jb.noms_occupes
    jb.noms_occupes = lambda e: {jb._va_name(v).strip().lower()
                                 for v in (e.get("vas") or [])}
    _rVieux = jb.update_va("jessye", "Roucham X1", new_name="Roucham X2")
    _nVieux = sum(1 for _a in _memR["jessye"]["accounts"] if _a["va"] == "Roucham X2")
    jb.noms_occupes = _vraiNoms
    check("renommage : sans le correctif, la fusion se produit (test non vide)",
          _rVieux is True and _nVieux == 28, (_rVieux, _nVieux))

    # ---- 2. l historique de paie doit suivre le nom ------------------------
    _memR.clear(); _memR.update(_baseR())
    for _j in ("2026-08-01", "2026-08-02", "2026-08-03"):
        _obR.enregistrer_jour([{"identite": "jessye", "va": "Fatou X1",
                                "objectif": 12, "actifs": 11, "atteint": True}], _j)
    _obR.fixer_objectif("jessye", "Fatou X1", 12)
    _bAv = _obR.bilan_mois("jessye", "Fatou X1", "2026-08-03")
    check("renommage : la fiche a bien un passe avant qu on la renomme",
          (_bAv["q1_tenus"], _bAv["q1_notes"]) == (3, 3), _bAv)
    check("renommage : le renommage vers un nom libre passe",
          jb.update_va("jessye", "Fatou X1", new_name="Fatou X3") is True)
    _bAp = _obR.bilan_mois("jessye", "Fatou X3", "2026-08-03")
    check("renommage : les jours tenus suivent le nouveau nom",
          (_bAp["q1_tenus"], _bAp["q1_notes"]) == (3, 3), _bAp)
    # L objectif comptait double : sans lui, une fiche reglee a 12 voyait son
    # seuil passer de 10 a 24 et echouait toutes les nuits suivantes.
    check("renommage : l objectif personnalise suit aussi",
          _obR.objectif_de("jessye", "Fatou X3") == 12,
          _obR.objectif_de("jessye", "Fatou X3"))
    check("renommage : et l ancienne cle ne traine plus",
          _obR.bilan_mois("jessye", "Fatou X1", "2026-08-03")["q1_notes"] == 0)

    # Non vide, la aussi : sans la migration, tout le passe disparait.
    _memR.clear(); _memR.update(_baseR())
    for _j in ("2026-08-01", "2026-08-02", "2026-08-03"):
        _obR.enregistrer_jour([{"identite": "jessye", "va": "Fatou X1",
                                "objectif": 12, "actifs": 11, "atteint": True}], _j)
    _obR.fixer_objectif("jessye", "Fatou X1", 12)
    _vraiRen = _obR.renommer_fiche
    _obR.renommer_fiche = lambda *a, **k: {"histo": 0, "objectifs": 0, "fusions": 0}
    jb.update_va("jessye", "Fatou X1", new_name="Fatou X9")
    _bMort = _obR.bilan_mois("jessye", "Fatou X9", "2026-08-03")
    _objMort = _obR.objectif_de("jessye", "Fatou X9")
    _obR.renommer_fiche = _vraiRen
    check("renommage : sans migration, le passe est efface (test non vide)",
          (_bMort["q1_tenus"], _bMort["q1_notes"]) == (0, 0) and _objMort == 30,
          (_bMort["q1_notes"], _objMort))

    # ---- 3. renommer une IDENTITE emporte toutes ses fiches ----------------
    _memR.clear(); _memR.update(_baseR())
    for _j in ("2026-08-01", "2026-08-02"):
        _obR.enregistrer_jour([
            {"identite": "jessye", "va": "Fatou X1", "objectif": 12,
             "actifs": 11, "atteint": True},
            {"identite": "jessye", "va": "Roucham X1", "objectif": 30,
             "actifs": 28, "atteint": True}], _j)
    _obR.fixer_objectif("jessye", "Fatou X1", 12)
    check("renommage : renommer l identite passe",
          jb.rename_identity_in_storage("jessye", "jessyca") is True)
    _b1 = _obR.bilan_mois("jessyca", "Fatou X1", "2026-08-02")
    _b2 = _obR.bilan_mois("jessyca", "Roucham X1", "2026-08-02")
    check("renommage : TOUTES les fiches de l identite gardent leur passe",
          (_b1["q1_notes"], _b2["q1_notes"]) == (2, 2), (_b1["q1_notes"], _b2["q1_notes"]))
    check("renommage : et leurs objectifs aussi",
          _obR.objectif_de("jessyca", "Fatou X1") == 12,
          _obR.objectif_de("jessyca", "Fatou X1"))

    # ---- 4. ajouter un nom deja porte par des comptes ----------------------
    # Ce n etait pas une fiche neuve : ca ADOPTAIT vingt comptes existants en
    # repondant « ajoute ». La barre laterale montrait deja cette fiche.
    _memR.clear(); _memR.update(_baseR())
    check("ajout : un nom deja porte par des comptes est un doublon",
          jb.add_va("jessye", "Roucham X2") is False)
    check("ajout : un nom libre passe toujours",
          jb.add_va("jessye", "Tiana X1") is True)

    jb._load, jb._save = _vraiLoad, _vraiSave
    jb.tomb_add, jb.tomb_clear = _vraiTa, _vraiTc
    (_obR.HISTO_FILE, _obR.OBJECTIFS_FILE) = _svR
except Exception as _eR:
    check("renommage : testable", False, repr(_eR)[:200])
    try:
        jb._load, jb._save = _vraiLoad, _vraiSave
        jb.tomb_add, jb.tomb_clear = _vraiTa, _vraiTc
        (_obR.HISTO_FILE, _obR.OBJECTIFS_FILE) = _svR
    except Exception:
        pass


# ==============================================================================
# Les trois messages permanents du salon d un VA
# ==============================================================================
try:
    import cogs.numeros as _n3
    # Les six etats des deux blocs. Ils ne DISPARAISSENT jamais : c est leur
    # texte qui change. Un bloc qui s efface fait douter de l endroit ou il
    # etait, et le VA reclique le panneau pour rien.
    check("trois : sans numero, la place existe et le dit",
          "Aucun numéro en cours" in _n3._emb_numero(None).description)
    check("trois : avec un numero, il est en gros et se saisit a la main",
          "+1555" in _n3._emb_numero({"valeur": "+1555"}).description
          and "à la main" in _n3._emb_numero({"valeur": "+1555"}).description)
    # Solde vide chez le fournisseur : demande user — le bloc reste, c est le
    # texte qui annonce le probleme.
    check("trois : un souci s affiche DANS la place, elle ne disparait pas",
          _n3._emb_numero(None, souci="pas de solde").description == "pas de solde")
    check("trois : le code s annonce avant d exister",
          "dès qu" in _n3._emb_code(None).description)
    check("trois : puis il s affiche seul, sans clic",
          "123456" in _n3._emb_code({"x": 1}, "123456").description)
    check("trois : et l attente se voit",
          "En attente" in _n3._emb_code({"x": 1}).description)

    # Les actions vivent sur le message 2, en permanence.
    _vA3 = _n3.ActionsView(None)
    _ids3 = sorted(str(c.custom_id) for c in _vA3.children if getattr(c, "custom_id", None))
    check("trois : les trois actions sont permanentes",
          _ids3 == ["numgen:annuler", "numgen:autre", "numgen:retry"]
          and _vA3.timeout is None, str(_ids3))

    import inspect as _i3
    _s3 = _i3.getsource(_n3.NumerosCog.nouvelle_activation)
    # Plus rien d ephemere : le VA doit retrouver le meme ecran apres un
    # rechargement de Discord.
    check("trois : la prise d un numero n est plus ephemere",
          "ephemeral" not in _s3)
    check("trois : un echec s ecrit dans la place du numero",
          "souci_num" in _s3)
    # LE piege : un salon qui n a recu que le panneau n a ni place pour le
    # numero ni place pour le code. Le clic achetait alors un numero que rien
    # n affichait — perdu, avec l argent.
    check("trois : on pose les places AVANT de commander quoi que ce soit",
          "poser_trois" in _s3 and _s3.index("poser_trois") < _s3.index("get_number"),
          "on depense avant d avoir ou l ecrire")
    _s3p = _i3.getsource(_n3.NumerosCog.panelnumero.callback
                         if hasattr(_n3.NumerosCog.panelnumero, "callback")
                         else _n3.NumerosCog.panelnumero)
    check("trois : /panelnumero pose les trois, pas le seul panneau",
          "poser_trois" in _s3p and "verrouiller_salon" in _s3p)

    # L ecoute est scindee : une enveloppe qui rattrape, et le corps qui
    # interroge le fournisseur.
    _s3b = _i3.getsource(_n3.NumerosCog._suivre)
    check("trois : le code est ecrit par le bot, sans qu on le demande",
          "maj_trois" in _s3b and "get_code" in _s3b)
    # Le code peut etre DEJA arrive chez le fournisseur alors que le bloc est
    # reste vide — l ecoute avait lache. Redemander un SMS dans ce cas ferait
    # perdre celui qu on a deja.
    _s3r = _i3.getsource(_n3.NumerosCog.action_salon)
    check("trois : « Redemander » regarde d abord si le code est deja la",
          "get_code" in _s3r and _s3r.index("get_code") < _s3r.index("numgen.retry"),
          "on redemande avant d avoir regarde")
    # Une tache de fond qui leve meurt sans un mot : c est arrive, le bloc
    # restait vide et rien ne disait pourquoi.
    _s3s = _i3.getsource(_n3.NumerosCog.suivre)
    check("trois : une ecoute qui echoue l ecrit dans le bloc du code",
          "except Exception" in _s3s and "souci_code" in _s3s)
    check("trois : et son demarrage laisse une trace au journal",
          "log.info" in _i3.getsource(_n3.NumerosCog._suivre))

    # LE doublon : la pose allait CHERCHER chaque message avant de l editer.
    # Une lecture qui echoue une seconde — une limite d API suffit — faisait
    # croire que le message n existait plus, et un deuxieme « Code » etait
    # poste. On edite desormais sans lire, et seul un NotFound autorise a
    # reposter.
    _s3q = _i3.getsource(_n3.poser_trois)
    check("trois : la pose edite sans aller lire le message",
          "get_partial_message" in _s3q and "fetch_message" not in _s3q,
          "un fetch qui echoue recree un doublon")
    check("trois : seul un message VRAIMENT absent est repose",
          "discord.NotFound" in _s3q)
    check("trois : les mises a jour non plus ne lisent rien",
          "fetch_message" not in _i3.getsource(_n3.maj_trois))
    # /panelnumero doit LAISSER trois messages, pas en ajouter trois.
    _s3p2 = _i3.getsource(_n3.NumerosCog.panelnumero.callback
                          if hasattr(_n3.NumerosCog.panelnumero, "callback")
                          else _n3.NumerosCog.panelnumero)
    check("trois : /panelnumero nettoie avant de poser",
          "purge(" in _s3p2 and _s3p2.index("purge(") < _s3p2.index("poser_trois"))

    # Chaque clic achete. Si le bloc ne peut pas etre ECRIT, le VA ne verra
    # jamais le numero : le garder, c est le payer pour rien. Constate en
    # vrai — le bloc restait sur « Recherche d un numero… » et le solde
    # baissait a chaque clic.
    _s3n = _i3.getsource(_n3.NumerosCog.nouvelle_activation)
    check("trois : un numero inaffichable est RENDU, pas perdu",
          "numgen.cancel" in _s3n and "montre" in _s3n,
          "un achat invisible reste a la charge du compte")
    check("trois : et l incident va au journal",
          "INAFFICHABLE" in _s3n)
    check("trois : la mise a jour dit ce qu elle a reussi a ecrire",
          "return poses" in _i3.getsource(_n3.maj_trois))

    # Exactement trois, jamais quatre : un message laisse par un incident
    # passe n est dans aucun registre, donc personne ne le met a jour — il
    # reste la a repeter un texte perime. La pose le supprime.
    _s3q2 = _i3.getsource(_n3.poser_trois)
    check("trois : la pose supprime tout message de bot en trop",
          "channel.history" in _s3q2 and "vieux.id not in gardes" in _s3q2)
    check("trois : mais jamais un message d humain",
          'getattr(vieux.author, "bot", False)' in _s3q2)
    # On ne fait le menage que si les trois sont bien identifies : sinon on
    # supprimerait ceux qu on vient de rater.
    check("trois : pas de menage tant que les trois ne sont pas surs",
          "len(gardes) == 3" in _s3q2)

    _s3c = _i3.getsource(_n3.verrouiller_salon)
    check("trois : le salon passe en lecture seule",
          "send_messages=False" in _s3c and "default_role" in _s3c)
except Exception as _e3:
    check("trois : testable", False, repr(_e3)[:200])


# ==============================================================================
# Trends : les videos deja FINIES, et le panneau qui doit rester affichable
# ==============================================================================
try:
    import cogs.user as _uTr
    import discord as _dTr
    import pathlib as _pTr
    import shutil as _shTr

    # LA garde qui compte : Discord plafonne a 5 boutons par rangee et 5
    # rangees, dont une prise par le menu deroulant. Depasser ne casse pas le
    # bouton fautif — ca fait echouer la vue ENTIERE, donc tout le panneau.
    _embTr, _vueTr = _uTr._jb_panel(None, "julia", 3)
    _libTr = []
    for _itTr in _vueTr.children:
        _bTr = getattr(_itTr, "item", None) or _itTr
        _lTr = getattr(_bTr, "label", None)
        if _lTr:
            _libTr.append((getattr(_itTr, "row", None), _lTr, getattr(_bTr, "style", None)))
    from collections import Counter as _CTr
    _parRangeeTr = _CTr(r for r, _l, _s in _libTr)
    check("trends : le menu porte les trois familles",
          len([1 for _r, _l, _s in _libTr if "⭐⭐⭐" in _l]) == 3,
          str([_l for _r, _l, _s in _libTr if "⭐" in _l])[:130])
    check("trends : et le menu reste dans les limites de Discord",
          all(_n <= 5 for _n in _parRangeeTr.values())
          and len(_parRangeeTr) <= 5 and len(_vueTr.children) <= 25,
          str(dict(sorted(_parRangeeTr.items()))))
    check("trends : les trois boutons sont verts",
          all(_s == _dTr.ButtonStyle.success
              for _r, _l, _s in _libTr if "⭐⭐⭐" in _l))
    # Chaque ⭐⭐⭐ est dans la rangee de SA famille : c est ce qui permet de
    # lire les degres dans l ordre au lieu de chercher dans tout le panneau.
    _rangTr = {_l: _r for _r, _l, _s in _libTr}
    for _famTr, _baseTr in (("⭐⭐⭐ Caption", "💬 Caption"),
                            ("⭐⭐⭐ Template", "🎞️ Template"),
                            ("⭐⭐⭐ Flash", "⚡ Flash")):
        check("trends : %s est dans la rangee de sa famille" % _famTr,
              _rangTr.get(_famTr) is not None
              and _rangTr.get(_famTr) == _rangTr.get(_baseTr),
              "%s vs %s" % (_rangTr.get(_famTr), _rangTr.get(_baseTr)))
    # La quantite est passee en BOUTON : un menu deroulant occupe une rangee
    # entiere, soit cinq places. Sans ce changement, les trois ⭐⭐⭐ auraient
    # demande d en supprimer deux autres.
    check("trends : la quantite est un bouton, pas un menu deroulant",
          any("Quantité" in _l for _r, _l, _s in _libTr),
          str([_l for _r, _l, _s in _libTr])[:90])

    # Aucune commande slash consommee : le bot principal est deja au-dela du
    # plafond de 100, et chaque commande en trop en fait disparaitre une autre
    # sans le moindre message.
    for _famTr in ("caption", "template", "flash"):
        _entTr = _uTr._jb_action("trend" + _famTr)
        check("trends : l action trend%s est declaree" % _famTr, _entTr is not None)
        _cibleTr = getattr(_uTr.UserCog, _entTr[2], None) if _entTr else None
        check("trends : sa cible existe sur le cog", _cibleTr is not None,
              str(_entTr))
        # Le bot principal est a 100 commandes sur 100 : une de plus en ferait
        # disparaitre une autre, sans le moindre message.
        check("trends : trend%s ne coute AUCUNE commande slash" % _famTr,
              _cibleTr is not None and not hasattr(_cibleTr, "callback"))
    check("trends : le panneau sait appeler une methode ordinaire",
          'getattr(cmd, "callback", None)' in
          _pTr.Path("cogs/user.py").read_text(encoding="utf-8"))
    # Le bouton de quantite doit etre enregistre comme item dynamique, sinon
    # il cesse de repondre apres un redemarrage : le panneau reste a l ecran,
    # le clic ne fait rien, et rien ne le dit.
    check("trends : le bouton de quantite survit a un redemarrage",
          "add_dynamic_items(JBQtySelect, JBQtyButton, JBActionButton)" in
          _pTr.Path("cogs/user.py").read_text(encoding="utf-8"))
    # Le menu deroulant de quantite vit desormais dans un message ephemere :
    # il doit reecrire le panneau PERMANENT, pas l ephemere d ou il s ouvre.
    check("trends : la quantite reecrit le panneau, pas l ephemere",
          "_reposer_panneau(" in _pTr.Path("cogs/user.py").read_text(encoding="utf-8"))

    # Le stock : petit par nature, tire au hasard, et jamais un fichier voisin.
    _dosTr = _uTr.IDENTITIES_DIR / "_tst_trends" / "trends"
    _shTr.rmtree(_dosTr.parent, ignore_errors=True)
    check("trends : dossier absent -> liste vide, pas d erreur",
          _uTr.trends_for("_tst_trends") == [])
    _dosTr.mkdir(parents=True, exist_ok=True)
    for _nTr in ("a.mp4", "b.mp4", "c.mp4", "d.mp4"):
        (_dosTr / _nTr).write_bytes(b"x" * 10)
    (_dosTr / "a.txt").write_text("le son a utiliser", encoding="utf-8")
    _gotTr = _uTr.trends_for("_tst_trends", limit=3)
    check("trends : le stock est plafonne a ce qu on demande", len(_gotTr) == 3)
    check("trends : le texte voisin n est pas pris pour une video",
          all(_p.suffix == ".mp4" for _p in _gotTr))
    _shTr.rmtree(_dosTr.parent, ignore_errors=True)

    # Elles sont postees TELLES QUELLES : ce sont donc celles qui ont le plus
    # besoin d une empreinte propre a chaque envoi.
    _srcTr2 = _pTr.Path("cogs/user.py").read_text(encoding="utf-8")
    _blocTr = _srcTr2.split("async def _send_trends")[1][:2600]
    check("trends : elles passent par la meme uniquification que les brutes",
          "_envoyer_brutes_meta" in _blocTr)
    check("trends : la consigne de son part avec la video",
          "avec_texte=True" in _blocTr and "SON / CONSIGNE" in _srcTr2)
except Exception as _eTr2:
    check("trends bot : testable", False, repr(_eTr2)[:200])

print("\n" + "=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  -", f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
