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
                return _aioBr.run(_uBr.brute_a_envoyer(_srcBr, _d, "julia"))

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
        check("brutmeta : toutes les voies passent par le meme reecrivain",
              _srcUBr.count("await brute_a_envoyer(") == 2,
              "%d appel(s) sur 2" % _srcUBr.count("await brute_a_envoyer("))
        check("brutmeta : plus aucune brute nue envoyee droit du disque",
              "file=discord.File(str(self.video), filename=self.video.name)"
              not in _srcUBr)
        check("brutmeta : un seul endroit lit l interrupteur",
              _srcUBr.count("load_transform_config().get(") == 1,
              "%d lecture(s)" % _srcUBr.count("load_transform_config().get("))
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
    _vraisPe = _idsPe(_NpPe(None))
    check("perime : les memes identifiants que le vrai panneau",
          _idsPe(_vuePe) == _vraisPe,
          "%s vs %s" % (_idsPe(_vuePe), _vraisPe))
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

print("\n" + "=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  -", f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
