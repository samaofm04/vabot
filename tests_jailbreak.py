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
# UNE SUPPRESSION A UNE HISTOIRE. Un compte que le Sheet n a jamais vu n a ete
# supprime par personne : son absence ne prouve que l echec du push. Il faut
# donc d abord que le Sheet le VOIE, sinon rien ne peut le supprimer — c est la
# protection qui empeche les comptes ajoutes par les VA de disparaitre.
ss.pull_all = lambda: {f"{IDENT} Sync": [{"username": f"s{i}"} for i in range(10)]}
ss.pull_and_merge()
check("le Sheet voit d abord les comptes", len(accounts()) == 10, unames())
check("jamais vu -> jamais supprime : la marque est posee",
      all(a.get("vu_sheet") for a in accounts()),
      [a.get("username") for a in accounts() if not a.get("vu_sheet")])
# Les comptes doivent aussi avoir passe la grace de 15 min, sinon leur jeunesse
# les protege quoi qu il arrive. On les vieillit d une heure.
# `accounts()` rend une COPIE : la muter ne change rien sur le disque, et
# `jb._save(jb._load())` relit le fichier puis le reecrit tel quel. Il faut
# charger UNE fois, modifier cet objet-la, et sauvegarder celui-la.
_dd = jb._load()
for _a in _dd[IDENT]["accounts"]:
    _a["created_at"] = int(__import__("time").time()) - 3600
jb._save(_dd)
# a) le Sheet garde 4 comptes sur 10 -> 6 suppressions appliquées
ss.pull_all = lambda: {f"{IDENT} Sync": [{"username": f"s{i}"} for i in range(4)]}
ch, summ = ss.pull_and_merge()
check("suppressions du Sheet appliquées", sorted(unames()) == [f"s{i}" for i in range(4)], unames())
# b) onglet VIDE -> aucune suppression (anti-wipe)
ss.pull_all = lambda: {f"{IDENT} Sync": []}
ss.pull_and_merge()
check("onglet vide n'efface rien", len(accounts()) == 4, unames())
# c) un compte AJOUTE sur le site et jamais pousse ne doit PAS disparaitre.
#    C est le scenario rapporte : « tres souvent, ca ne met pas le compte ».
jb.add_account(IDENT, "ajoute_par_le_va", va="Sync")
_dd = jb._load()
for _a in _dd[IDENT]["accounts"]:
    if _a.get("username") == "ajoute_par_le_va":
        _a["created_at"] = int(__import__("time").time()) - 3600   # hors grace
jb._save(_dd)
ss.pull_all = lambda: {f"{IDENT} Sync": [{"username": f"s{i}"} for i in range(4)]}
ss.pull_and_merge()
check("un compte que le Sheet n a jamais vu survit au pull",
      "ajoute_par_le_va" in unames(), unames())
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

    # Depuis le 25/09/2026 (menus directs), _jb_panel rend UNE LayoutView
    # « Components V2 » -- plus de couple (embed, vue) -- et ses elements vivent
    # dans un conteneur, sur des rangees : on les parcourt a toute profondeur
    # (walk_children). Les menus de famille portent eux aussi l'etat dans leur
    # custom_id ; une liste vide ne doit pas passer pour « tout va bien ».
    import discord as _dP
    _viewP = _uP._jb_panel(None, "e30princesss", 5)
    _idsP = [i.custom_id for i in _viewP.walk_children()
             if isinstance(i, _dP.ui.DynamicItem)]
    check("panneau : quantite et identite dans chaque custom_id",
          len(_idsP) == 1 + sum(len(r) - (_uP._JB_QTE in r) for r in _uP._JB_BOUTONS_V2)
          + len(_uP._FAMILLES_PANNEAU)
          and all(str(x or "").endswith(":5") and "e30princesss" in str(x or "") for x in _idsP),
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
    check("ordre : le podium remplace les numeros pour les trois premiers",
          _ioOr.etiqueter(["emma", "lola"], _ordOr)
          == {"lola": "🥇 Lola", "emma": "🥈 Emma"},
          str(_ioOr.etiqueter(["emma", "lola"], _ordOr)))
    # AUCUNE LIGNE SANS BADGE. Le podium seul portait un dessin, le reste un
    # chiffre nu (« 4. Genesaag »). Le proprietaire : « je veux une medaille
    # pour chacun » -- dans un menu deroulant, un chiffre colle au nom se lit
    # comme une partie du nom, et c'est vrai a la ligne 4 comme a la ligne 1.
    check("ordre : au-dela du podium, le rang porte une pastille chiffree",
          _ioOr.prefixe_rang(4) == "4\uFE0F\u20E3"
          and _ioOr.prefixe_rang(9) == "9\uFE0F\u20E3",
          repr(_ioOr.prefixe_rang(4)))
    check("ordre : dix a son propre dessin",
          _ioOr.prefixe_rang(10) == "\U0001F51F", repr(_ioOr.prefixe_rang(10)))
    # Au-dela de dix il n'existe pas de pastille : on pose les CHIFFRES un par
    # un. Le menu US compte vingt-deux models, la question se pose pour de bon.
    check("ordre : au-dela de dix, les chiffres se posent un par un",
          _ioOr.prefixe_rang(14) == "1\uFE0F\u20E3" + "4\uFE0F\u20E3"
          and _ioOr.prefixe_rang(22) == "2\uFE0F\u20E3" + "2\uFE0F\u20E3",
          repr(_ioOr.prefixe_rang(14)))
    # AUCUN CHIFFRE NU NE SUBSISTE : c'etait toute la demande.
    check("ordre : plus aucun rang ne s affiche en chiffre nu",
          all(_ioOr.prefixe_rang(n) and not _ioOr.prefixe_rang(n)[0].isdigit()
              or _ioOr.prefixe_rang(n).endswith("\u20E3")
              for n in range(1, 30)),
          str([_ioOr.prefixe_rang(n) for n in range(1, 6)]))
    # Un badge invente vaudrait un classement invente.
    check("ordre : ce qui n est pas un rang ne recoit aucun badge",
          _ioOr.prefixe_rang(0) == "" and _ioOr.prefixe_rang(-3) == ""
          and _ioOr.prefixe_rang("x") == "" and _ioOr.prefixe_rang(None) == "")
    # LE PODIUM EST DEFINI UNE SEULE FOIS. Deux tuples identiques dans deux
    # modules, c'est le defaut que le CLAUDE.md decrit : ils le restent
    # jusqu'au jour ou l'un bouge, et l'or de l'un ne vaut plus l'or de
    # l'autre.
    import clics_personnes as _cpOr
    check("ordre : le podium vient de clics_personnes, pas d une copie",
          _ioOr.MEDAILLES is _cpOr.MEDAILLES,
          "deux tuples separes redivergeront")
    _srcOrd = pathlib.Path("identites_ordre.py").read_text(encoding="utf-8")
    check("ordre : aucune seconde definition du podium",
          _srcOrd.count("MEDAILLES = (") == 0,
          "le tuple est recopie dans identites_ordre")
    # Les rangs 10+ pesent six unites : la mesure du plafond Discord compte
    # desormais pour de vrai.
    import cogs.user as _uLg
    check("ordre : la longueur se mesure en unites UTF-16, comme Discord",
          _uLg._long_discord("\U0001F947") == 2
          and _uLg._long_discord("4\uFE0F\u20E3") == 3
          and _uLg._long_discord("Lola") == 4,
          str(_uLg._long_discord("\U0001F947")))
    check("ordre : une coupe ne casse jamais une pastille en deux",
          _uLg._couper_discord("1\uFE0F\u20E3" + "4\uFE0F\u20E3" + " Nina", 4)
          == "1\uFE0F\u20E3",
          repr(_uLg._couper_discord("1\uFE0F\u20E3" + "4\uFE0F\u20E3" + " Nina", 4)))
    # CE TEST NE TRAVERSAIT PAS LA BRANCHE QU IL PRETENDAIT PROTEGER : une
    # identite inventee n a aucun style, donc `past` restait vide et
    # _libelle_model sortait par le chemin court. Il faut lui en donner pour
    # atteindre la coupe qui menage les styles.
    import identity_styles as _istLg
    _istLg.definir("zz_plafond", ["caption", "brut", "montage", "flash"])
    try:
        _nomLg = "zz_plafond"
        _brutLg = _ioOr.prefixe_rang(14) + " " + "Z" * 120
        _labLg = _uLg._libelle_model(_nomLg, {_nomLg: _brutLg})
        check("ordre : un libelle trop long tient sous le plafond de Discord",
              _uLg._long_discord(_labLg) <= 80, "%d unite(s) : %r"
              % (_uLg._long_discord(_labLg), _labLg[-30:]))
        check("ordre : la coupe menage les styles, elle mange le nom",
              _labLg.endswith(_istLg.mots(_nomLg)) and "…" in _labLg,
              repr(_labLg))
        check("ordre : le badge survit a la coupe, entier",
              _labLg.startswith(_ioOr.prefixe_rang(14)), repr(_labLg[:12]))
        # Le dernier filet : si les styles seuls devaient manger les 80
        # unites, le libelle sortait PLUS LONG que la limite -- et Discord
        # refuse alors tout le message, sans rien afficher.
        _svMots = _istLg.mots
        try:
            _istLg.mots = lambda i, separateur=" + ": "S" * 120
            _labX = _uLg._libelle_model(_nomLg, {_nomLg: _brutLg})
            check("ordre : meme des styles demesures ne depassent pas 80",
                  _uLg._long_discord(_labX) <= 80,
                  "%d unite(s)" % _uLg._long_discord(_labX))
        finally:
            _istLg.mots = _svMots
    finally:
        _istLg.definir("zz_plafond", [])
    check("ordre : une identite non rangee reste sans numero",
          _ioOr.etiqueter(["lola", "zoe"], _ordOr)["zoe"] == "Zoe")
    # Et le badge arrive bien jusqu'au libelle, pas seulement dans la
    # fonction : c'est ce que le VA lit.
    _ord14 = ["n%02d" % i for i in range(1, 15)]
    _lib14 = _ioOr.etiqueter(_ord14, _ord14)
    check("ordre : le badge arrive dans le libelle, du premier au dernier",
          _lib14["n01"] == "\U0001F947 N01"
          and _lib14["n04"] == "4\uFE0F\u20E3 N04"
          and _lib14["n10"] == "\U0001F51F N10"
          and _lib14["n14"] == "1\uFE0F\u20E3" + "4\uFE0F\u20E3" + " N14",
          str([_lib14[k] for k in ("n04", "n10", "n14")]))
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
          _libUs["ibenhaastrup"] == "🥇 Ibenhaastrup",
          "obtenu : %r" % _libUs.get("ibenhaastrup"))
    check("ordre : le menu filtre garde l ordre choisi entre elles",
          [_libUs[m] for m in _ioOr.trier(_usOr, _globalOr)]
          == ["🥇 Ibenhaastrup", "🥈 E30princesss",
              "🥉 Zezatwins"])

    # UN MENU NE SE POSTE PAS VIDE. Le 12/09/2026, /menujailbreakus a poste
    # un panneau SANS UN SEUL BOUTON : la garde comptait les models avec sa
    # propre copie des filtres -- a un pres, elle oubliait EXCLURE_MENU. La
    # seule model US restante etant Jessye, qui est justement exclue du menu
    # parce qu elle en est la SOURCE, la garde a laisse passer « 1 model » et
    # la vue n en a affiche aucune.
    import cogs.user as _uMe
    import cogs.welcome as _wMe
    _svLi, _svAc, _svMo = (_wMe.list_identities, _wMe.is_identity_active,
                           _wMe.est_une_model)
    _svMk = _uMe._market_of
    try:
        _noms = ["jessye", "julia", "ibenhaastrup"]
        _wMe.list_identities = lambda: _noms
        _wMe.is_identity_active = lambda n: True
        # La nature dit « ce n est pas une model » : le menu s en moque
        # depuis le 12/09/2026, on la laisse mentir pour le verifier.
        _wMe.est_une_model = lambda n: n != "ibenhaastrup"
        _uMe._market_of = lambda n: "us" if n == "jessye" else "fr"
        check("menu US : la garde voit EXACTEMENT ce que la vue affichera",
              _uMe._jb_us_models() == _uMe._jb_models_marche("us") == [],
              str(_uMe._jb_us_models()))
        # Et le vide s explique, chiffre par chiffre, au lieu de laisser
        # chercher.
        _diag = _uMe._jb_diagnostic_marche("us")
        check("menu US : quand c est vide, le message dit ou le filtre coupe",
              "jessye" in _diag and "0 affichable" in _diag, _diag[:150])
        # LE DRAPEAU DECIDE, ET LUI SEUL. ibenhaastrup est rangee en
        # « identite » ; elle doit quand meme etre proposee, sinon on
        # reproduit le menu vide du 12/09 -- le panneau de tri en masse range
        # en « identite » tout ce qui n est pas coche, ce qui avait demote
        # quinze entrees sur vingt-deux d un coup.
        _uMe._market_of = lambda n: "us"
        check("menu US : une entree rangee en « identite » reste proposee",
              _uMe._jb_us_models() == ["julia", "ibenhaastrup"],
              str(_uMe._jb_us_models()))
        # Le diagnostic doit compter CE QUE LA LISTE FILTRE : s il comptait
        # encore la nature, il annoncerait un chiffre que le menu dement.
        _diag2 = _uMe._jb_diagnostic_marche("us")
        check("menu US : le diagnostic compte ce que la liste retient",
              "2 affichable" in _diag2 and "modele" not in _diag2, _diag2[:180])
    finally:
        _wMe.list_identities, _wMe.is_identity_active = _svLi, _svAc
        _wMe.est_une_model, _uMe._market_of = _svMo, _svMk

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
    # UN CLASSEMENT DONT ON IGNORE LE SENS NE SE LIT PAS, il se suppose --
    # et une supposition sur deux est fausse. « Cette liste est un classement »
    # laissait entiere la question : classement de quoi, du meilleur vers le
    # pire ou l inverse ? Le proprietaire, en relisant le menu poste : « dis
    # ici c est un classement des meilleures identites a la moins bonne ».
    check("ordre : le menu dit que c est un classement, ET dans quel sens",
          "classement" in _phr.lower() and "moins bonne" in _phr.lower()
          and _ioOr.MEDAILLES[0] in _phr,
          "phrase : %r" % _phr[:100])
    # Annoncer un classement qui n existe pas serait pire que se taire.
    check("ordre : rien n est annonce quand rien n est range",
          _ioOr.phrase_classement(["zoe", "anna"], _ordOr) == "")
    # UNE LIGNE NUE AU MILIEU DE LIGNES QUI PORTENT UN BADGE se remarque, et
    # le proprietaire a demande « une medaille pour chacun ». On refuse
    # toujours d inventer un rang pour une identite qu il n a pas rangee --
    # mais on lui dit COMBIEN il en reste, et le geste qui les remplit.
    _phrNu = _ioOr.phrase_classement(["lola", "emma", "zoe", "anna", "nina"],
                                     _ordOr)
    check("ordre : le menu compte les models sans badge et dit quoi faire",
          "3 model" in _phrNu and "glisser" in _phrNu.lower(),
          "phrase : %r" % _phrNu[-120:])
    check("ordre : rien n est dit quand toutes portent leur badge",
          "pas encore class" not in _ioOr.phrase_classement(["lola", "emma"],
                                                            _ordOr),
          _ioOr.phrase_classement(["lola", "emma"], _ordOr)[-80:])
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
print()
print("=" * 70)
print("NATURE COTE DISCORD : un dossier de montage n est pas une model")
print("=" * 70)
try:
    import pathlib as _plN, safe_json as _sjN
    import type_identite as _tiN
    from cogs.welcome import (list_identities as _liN,
                              list_active_identities as _laN,
                              est_une_model as _emN)
    import cogs.user as _cuN
    _fN = _plN.Path("data/identity_type.json")
    _savN = _fN.read_text(encoding="utf-8") if _fN.exists() else None
    _dossiers = _liN()
    try:
        # Defaut « modele » : tant que rien n est coche, RIEN ne disparait.
        _sjN.write(_fN, {})
        _tiN._CACHE.update(sig=None, data={})
        check("nature Discord : sans reglage, la rotation ne perd personne",
              set(_laN()) == set(n for n in _dossiers if n != "jessye"),
              str(_laN())[:90])
        if _dossiers:
            _cible = next((n for n in _dossiers if n != "jessye"), None)
        else:
            _cible = None
        if _cible:
            _sjN.write(_fN, {_cible: "identite"})
            _tiN._CACHE.update(sig=None, data={})
            # LA NATURE NE RETIRE PLUS PERSONNE COTE DISCORD. Le 11/09/2026
            # elle filtrait la rotation et les menus ; le 12, le proprietaire
            # a tranche -- « identite, modele, c est la meme ». Le panneau de
            # tri en masse ecrit « identite » pour tout ce qui n est pas
            # coche : une sauvegarde avait vide son menu US de quinze models.
            check("nature Discord : une identite reste dans la rotation des VA",
                  _cible in _laN(), str(_laN())[:90])
            check("nature Discord : elle reste dans les menus par marche",
                  _cible in (_cuN._jb_models_marche("fr")
                             + _cuN._jb_models_marche("us")),
                  str(_cuN._jb_models_marche("fr"))[:90])
            check("nature Discord : elle reste dans la liste BRUTE des dossiers",
                  _cible in _liN(), "sinon les salons existants seraient perdus")
        else:
            check("nature Discord : une identite reste dans la rotation", True, "(aucun dossier local)")
        # Jessye ne sort jamais.
        _sjN.write(_fN, {"jessye": "identite"})
        _tiN._CACHE.update(sig=None, data={})
        check("nature Discord : jessye reste une model quoi qu on ecrive",
              _emN("jessye") is True)
        # LE MARCHE PAR DEFAUT EST FR depuis le 11/09/2026. Il etait « us » :
        # une entree creee sans choix partait sur le serveur americain, celui
        # que voient les VA US, avec un drapeau que personne n avait pose.
        import marche as _mkN
        _fMkN = _plN.Path("data/identity_market.json")
        _savMkN = _fMkN.read_text(encoding="utf-8") if _fMkN.exists() else None
        try:
            _sjN.write(_fMkN, {})
            _mkN._CACHE.update(sig=None, data={})
            check("marche : sans choix explicite, une entree reste en FR",
                  _mkN.de("zzzjamaisvue") == "fr" and _mkN.de("") == "fr")
            _sjN.write(_fMkN, {"zzzchoisie": "us"})
            _mkN._CACHE.update(sig=None, data={})
            check("marche : un choix explicite l emporte toujours",
                  _mkN.de("zzzchoisie") == "us")
            # JESSYE EST US, et deux endroits du depot le savaient deja :
            # OF_US_MODELS (web_upload) et OF_US_CREATOR_IDS (mypuls) la
            # comptent cote americain. Seul marche.py disait FR.
            _sjN.write(_fMkN, {})
            _mkN._CACHE.update(sig=None, data={})
            check("marche : jessye est US par defaut, comme cote revenus",
                  _mkN.de("jessye") == "us" and _mkN.de("khloe") == "us")
            check("marche : les autres restent FR",
                  _mkN.de("julia") == "fr" and _mkN.de("amelia") == "fr")
            _sjN.write(_fMkN, {"jessye": "fr"})
            _mkN._CACHE.update(sig=None, data={})
            check("marche : un choix pose l emporte meme sur jessye",
                  _mkN.de("jessye") == "fr")
        finally:
            if _savMkN is None:
                try:
                    _fMkN.unlink()
                except Exception:
                    pass
            else:
                _sjN.write_text(_fMkN, _savMkN)
            _mkN._CACHE.update(sig=None, data={})
    finally:
        if _savN is None:
            try:
                _fN.unlink()
            except Exception:
                pass
        else:
            _sjN.write_text(_fN, _savN)
        _tiN._CACHE.update(sig=None, data={})
    # LE REPLI EST « MODELE ». Un fichier illisible ne doit pas priver un VA.
    import builtins as _biN
    _vraiN = _biN.__import__
    def _fauxN(nom, *a, **k):
        if nom == "type_identite":
            raise ImportError("simule")
        return _vraiN(nom, *a, **k)
    _biN.__import__ = _fauxN
    try:
        check("nature Discord : module absent -> comportement d avant",
              _emN("nimporte") is True)
    finally:
        _biN.__import__ = _vraiN
    # LE REGLAGE N EST PAS MORT POUR AUTANT : il a ete demande pour alleger
    # Social Analytics (le perimetre de scrape), et il y sert toujours. Si ce
    # point de passage disparaissait, le perimetre redeviendrait la liste
    # entiere sans que personne ne le remarque.
    _srcSA = _plN.Path("web_upload.py").read_text(encoding="utf-8")
    check("nature : elle sert encore a restreindre Social Analytics",
          "filtrer_modeles" in _srcSA,
          "le perimetre de scrape ne se restreint plus")

    # Le filtre ne doit PAS toucher ce qui maintient les acces existants.
    _srcN = _plN.Path("cogs/welcome.py").read_text(encoding="utf-8")
    _d1 = _srcN.index("def sync_general_channel_access")
    _f1 = _srcN.index(chr(10) + "def ", _d1 + 40)
    check("nature Discord : la synchro des acces ne consulte pas le filtre",
          "est_une_model" not in _srcN[_d1:_f1],
          "un VA en place perdrait ses salons")
except Exception as _eN:
    check("nature Discord : testable", False, repr(_eN)[:200])

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
        _attSt = "3. Zz_style — Caption + Template"
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
        check("styles : un nom demesure est coupe, pas les styles",
              len(_labSt) <= 80 and _labSt.endswith(_ist.mots("zz_style")),
              "len=%d, fin=%r" % (len(_labSt), _labSt[-24:]))
        # Les emojis restent disponibles : le site les utilise ailleurs, et
        # une table qui perd une de ses deux formes finit par diverger.
        check("styles : les deux formes sortent de la MEME table",
              _ist.emojis("zz_style") and _ist.mots("zz_style")
              and len(_ist.de("zz_style")) == len(_ist.mots("zz_style").split(" + ")),
              "%r / %r" % (_ist.emojis("zz_style"), _ist.mots("zz_style")))

        # Les DEUX menus qui listent des models doivent passer par ce seul
        # fabricant : sinon l un des deux garde les vieux libelles au premier
        # style ajoute. Meme garde que pour _io.etiqueter, juste au-dessus.
        _srcSt = _plSt.Path("cogs/user.py").read_text(encoding="utf-8")
        check("styles : les deux menus passent par le meme fabricant",
              _srcSt.count("_libelle_model(m, ") == 2,
              "%d appel(s) sur 2" % _srcSt.count("_libelle_model(m, "))

        # LA LEGENDE N EXPLIQUE QUE CE QU ON VOIT. « Genesaag — Caption » ne
        # veut rien dire tant qu on n a pas appris que ce mot designe ce qui
        # marche sur ce compte-la ; le proprietaire : « brut c est que cette
        # identite marche plus avec du brut, caption avec de la caption ».
        # Mais expliquer un mot que PERSONNE ne porte, c est une ligne de plus
        # entre le VA et le bouton qu il cherche.
        _ist.definir("zz_style", ["caption", "flash"])
        _ist.definir("zz_autre", ["montage"])
        _legSt = _ist.legende(["zz_style", "zz_autre"])
        check("styles : la legende explique les styles PRESENTS, dans l ordre",
              [_l for _l, _t in _legSt] == ["Caption", "Montage", "Template"],
              str(_legSt))
        check("styles : elle n explique pas un style que personne ne porte",
              [_l for _l, _t in _ist.legende(["zz_autre"])] == ["Montage"],
              str(_ist.legende(["zz_autre"])))
        check("styles : sans aucun style, aucune legende",
              _ist.legende(["zz_jamais_cochee"]) == [] and _ist.legende([]) == [])
        check("styles : la legende dit vraiment ce que fait le style",
              dict(_ist.legende(["zz_autre"]))["Montage"] == "un montage",
              str(_ist.legende(["zz_autre"])))
        # Un style ajoute demain sans forme courte disparaitrait de la legende
        # SANS RIEN DIRE : c est precisement ce que le depot interdit.
        check("styles : chaque style a sa forme courte",
              set(_ist.CLES) == set(_ist.COURT),
              "sans forme courte : %s" % (set(_ist.CLES) - set(_ist.COURT)))
        check("styles : la legende est bien posee dans le menu",
              "_ist.legende(models)" in _srcSt,
              "le mot au bout de la ligne resterait a deviner")
        _ist.definir("zz_autre", [])

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
          (_bMort["q1_tenus"], _bMort["q1_notes"]) == (0, 0) and _objMort == 20,
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

    # LA garde qui compte : un message qui depasse les limites de Discord ne
    # perd pas l element fautif -- il est refuse ENTIER, donc tout le panneau.
    # Depuis le 25/09/2026 le panneau est une LayoutView « Components V2 » :
    # 40 composants au plus (conteneur et rangees compris), 5 elements par
    # rangee, 4000 caracteres de texte.
    _vueTr = _uTr._jb_panel(None, "julia", 3)
    _rangTr = [_r for _r in _vueTr.walk_children() if isinstance(_r, _dTr.ui.ActionRow)]
    _libTr = []
    for _itTr in _vueTr.walk_children():
        _bTr = getattr(_itTr, "item", None) or _itTr
        for _lTr in [getattr(_bTr, "label", None), getattr(_bTr, "placeholder", None)] + [
                _o.label for _o in (getattr(_bTr, "options", None) or [])]:
            if _lTr:
                _libTr.append((_lTr, getattr(_bTr, "style", None),
                               getattr(_bTr, "custom_id", "") or ""))
    # CHANGEMENT VOULU (25/09/2026) : le proprietaire a retire « ⭐⭐⭐ Trends »
    # du panneau (« pas encore good »). Avant, ce test exigeait le bouton ; il
    # exige maintenant son ABSENCE -- ni bouton, ni option de menu, ni
    # custom_id. L action reste definie pour les panneaux deja postes (voir
    # « un ancien bouton ⭐⭐⭐ » plus bas).
    check("trends : le panneau ne porte PLUS le ⭐⭐⭐ (retire par le proprietaire)",
          _libTr and not [_l for _l, _s, _c in _libTr if "⭐⭐⭐" in _l or ":trend:" in _c],
          str([_l for _l, _s, _c in _libTr if "⭐⭐⭐" in _l])[:130])
    check("trends : et le menu reste dans les limites de Discord",
          _vueTr.total_children_count <= 40 and _vueTr.content_length() <= 4000
          and _rangTr and all(len(_r.children) <= 5 for _r in _rangTr),
          "%d composants, %s" % (_vueTr.total_children_count,
                                 [len(_r.children) for _r in _rangTr]))
    # Le vert isole les trends (videos deja FINIES) : un ancien bouton
    # ⭐⭐⭐ reconstruit par discord.py au clic garde son custom_id et son vert.
    _btnTr = _uTr.JBActionButton("julia", "trend", 3)
    check("trends : un ancien bouton ⭐⭐⭐ se reconstruit vert, meme custom_id",
          _btnTr.item.style == _dTr.ButtonStyle.success
          and _btnTr.custom_id == "jbus:a:julia:trend:3"
          and "⭐⭐⭐" in (_btnTr.item.label or ""), str((_btnTr.item.style, _btnTr.custom_id)))
    # CHANGEMENT VOULU : la quantite n est plus un menu deroulant deplie (il
    # prenait une rangee entiere) mais le bouton « 📦 Quantité : N » de la
    # maquette validee, qui OUVRE le panneau : premier element de la premiere
    # rangee. Le test d avant (« la quantite reste depliee… ») echouait deja
    # depuis le passage au bouton.
    check("trends : la quantite ouvre le panneau (premier bouton, premiere rangee)",
          _rangTr and _rangTr[0].children
          and getattr(_rangTr[0].children[0], "custom_id", "") == "jbus:qb:julia:3"
          and "Quantité" in (_rangTr[0].children[0].item.label or ""),
          str([getattr(_c, "custom_id", None) for _c in (_rangTr[0].children if _rangTr else [])]))

    # Aucune commande slash consommee : le bot principal est deja au-dela du
    # plafond de 100, et chaque commande en trop en fait disparaitre une autre
    # sans le moindre message.
    _entTr = _uTr._jb_action("trend")
    check("trends : l action est declaree", _entTr is not None)
    _cibleTr = getattr(_uTr.UserCog, _entTr[2], None) if _entTr else None
    check("trends : sa cible existe sur le cog", _cibleTr is not None, str(_entTr))
    # Le bot principal est a 100 commandes sur 100 : une de plus en ferait
    # disparaitre une autre, sans le moindre message.
    check("trends : elle ne coute AUCUNE commande slash",
          _cibleTr is not None and not hasattr(_cibleTr, "callback"))
    # Et elle envoie DES LE PREMIER CLIC : pas de sous-menu qui demanderait
    # quelle famille — les trois servaient le meme stock de toute facon.
    check("trends : elle envoie des le premier clic",
          not hasattr(_uTr.UserCog, "trendmenu")
          and not hasattr(_uTr, "TrendActionButton"))
    check("trends : le panneau sait appeler une methode ordinaire",
          'getattr(cmd, "callback", None)' in
          _pTr.Path("cogs/user.py").read_text(encoding="utf-8"))
    # Le bouton de quantite doit etre enregistre comme item dynamique, sinon
    # il cesse de repondre apres un redemarrage : le panneau reste a l ecran,
    # le clic ne fait rien, et rien ne le dit.
    check("trends : les boutons du panneau survivent a un redemarrage",
          "add_dynamic_items(JBQtySelect, JBActionButton)" in
          _pTr.Path("cogs/user.py").read_text(encoding="utf-8"))

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

print()
print("=" * 70)
print("PAIE MERITEE : 75 $ la quinzaine, au prorata des comptes qui publient")
print("=" * 70)
try:
    import json as _jp, tempfile as _tp, datetime as _dp, pathlib as _pp
    import jb_objectifs as _obp

    _JP = "2026-09-07"                       # 7e jour d'une quinzaine de 15
    _d0, _d1 = _obp.quinzaine(_JP)

    def _histo(serie, jour=None):
        """Ecrit un historique bidon et branche le module dessus.

        `jour` decide OU s'arrete le calcul : la fonction ne compte que les
        journees ecoulees, donc une quinzaine « parfaite » lue le 7 ne vaut
        que 7 jours. Deux de ces tests l'ont appris a leurs depens.
        """
        j = {}
        for i, v in enumerate(serie):
            if v is None:
                continue
            k = (_dp.date.fromisoformat(_d0) + _dp.timedelta(days=i)).isoformat()
            j[k] = {"publie": v, "atteint": v >= 16}
        f = _pp.Path(_tp.mkdtemp()) / "h.json"
        f.write_text(_jp.dumps({_obp.cle("id", "va"): {"jours": j}}), encoding="utf-8")
        _obp.HISTO_FILE = f
        return _obp.paie_quinzaine("id", "va", jour or _JP)

    _vrai = _obp.HISTO_FILE
    check("paie : la quinzaine de septembre fait bien 15 jours",
          _histo([20])["jours_quinzaine"] == 15)
    check("paie : une journee vaut 75 $ / 15 = 5 $",
          abs(_histo([20])["par_jour"] - 5.0) < 0.001)
    # --- Un doute d Instagram ne se facture pas au VA -------------------------
    try:
        import jb_objectifs as _oD
        import time as _tD_t, datetime as _tD_dt
        _tD = _tD_t.time()
        _vieux = _tD_dt.datetime.fromtimestamp(_tD - 5 * 86400, _tD_dt.timezone.utc).isoformat()
        _cD = [{"username": "doute1"}]
        _sD = {"doute1": {"error": "IG n a pas repondu", "a_verifier": True,
                          "doutes": 2, "last_reel_at": _vieux}}
        _eD = _oD.etat_compte(_cD[0], _sD, _tD, _oD._jour_paris(_tD), 48 * 3600, 3)
        check("doute : un compte « a verifier » n est PAS un oubli",
              not _eD["oublie"] and _eD["non_mesure"] and not _eD["banni"], str(_eD)[:120])
        # Mais s il a poste il y a deux heures, le doute ne l efface pas :
        # le dernier bon releve dit qu il tourne.
        _frais = _tD_dt.datetime.fromtimestamp(_tD - 7200, _tD_dt.timezone.utc).isoformat()
        _sD["doute1"]["last_reel_at"] = _frais
        _eD2 = _oD.etat_compte(_cD[0], _sD, _tD, _oD._jour_paris(_tD), 48 * 3600, 3)
        check("doute : un compte qui a publie recemment reste actif malgre le doute",
              _eD2["actif"] and not _eD2["non_mesure"], str(_eD2)[:120])
        # Et un compte normal, silencieux, reste bien un oubli : la nouvelle
        # regle ne doit pas amnistier tout le monde.
        _sN = {"doute1": {"last_reel_at": _vieux}}
        _eN = _oD.etat_compte(_cD[0], _sN, _tD, _oD._jour_paris(_tD), 48 * 3600, 3)
        check("doute : un silence SANS doute reste un oubli",
              _eN["oublie"] and not _eN["non_mesure"], str(_eN)[:120])
    except Exception as _eDx:
        check("doute : testable", False, repr(_eDx)[:200])

    # LA REGLE DU PROPRIETAIRE, mot pour mot : cinq comptes sur vingt, c'est
    # un quart de la journee.
    _q = _histo([5])
    check("paie : 5 comptes sur 20 = un quart de la journee",
          abs(_q["gagne"] - 1.25) < 0.001, str(_q["gagne"]))
    check("paie : le denominateur est 20, pas l objectif de la fiche",
          _obp.BASE_COMPTES == 20)
    # Le plafond : une fiche de 30 comptes ne doit pas depasser les 75 $.
    check("paie : 25 comptes sur 20 ne rapportent pas plus que la journee",
          abs(_histo([25])["gagne"] - 5.0) < 0.001, str(_histo([25])["gagne"]))
    # Lue le DERNIER jour de la quinzaine : lue avant, elle ne vaut que les
    # journees deja vecues, et c'est voulu.
    check("paie : une quinzaine parfaite rapporte exactement 75 $",
          abs(_histo([20] * 15, "2026-09-15")["gagne"] - 75.0) < 0.01,
          str(_histo([20] * 15, "2026-09-15")["gagne"]))
    # LA JOURNEE VAUT 5 $ PARTOUT. Le calendrier donne des quinzaines de 13 a
    # 16 jours ; la paie n'en tient pas compte - « tous les mois font trente
    # jours ». Une quinzaine de seize jours ne verse donc pas 80 $.
    def _pleine(jour_fin):
        _d0, _d1 = _obp.quinzaine(jour_fin)
        _n = (_dp.date.fromisoformat(_d1) - _dp.date.fromisoformat(_d0)).days + 1
        _j = {}
        for _i in range(_n):
            _k = (_dp.date.fromisoformat(_d0) + _dp.timedelta(days=_i)).isoformat()
            _j[_k] = {"publie": 20, "atteint": True}
        _f = _pp.Path(_tp.mkdtemp()) / "h.json"
        _f.write_text(_jp.dumps({_obp.cle("id", "va"): {"jours": _j}}), encoding="utf-8")
        _obp.HISTO_FILE = _f
        return _obp.paie_quinzaine("id", "va", jour_fin)

    check("paie : la journee vaut 5 $ tout rond", _obp.PAIE_JOUR == 5.0)
    check("paie : une quinzaine de 16 jours ne verse pas 80 $",
          abs(_pleine("2026-10-31")["gagne"] - 75.0) < 0.01,
          str(_pleine("2026-10-31")["gagne"]))
    # Consequence assumee : fevrier n'a que treize jours du 16 au 28.
    check("paie : fevrier 16-28 plafonne a 65 $ (13 jours reels)",
          abs(_pleine("2026-02-28")["gagne"] - 65.0) < 0.01,
          str(_pleine("2026-02-28")["gagne"]))
    check("paie : un seul compte qui publie vaut 25 centimes",
          abs(_histo([1])["gagne"] - 0.25) < 0.001, str(_histo([1])["gagne"]))
    check("paie : zero publication ne rapporte rien",
          _histo([0, 0, 0])["gagne"] == 0.0)
    # Une panne de report n est PAS une journee a zero : elle se compte a part.
    _t = _histo([10, 10, None, 10, 10, 10, 10])
    check("paie : un jour sans releve est compte a part, pas comme un zero",
          _t["jours_non_mesures"] == 1 and _t["jours_mesures"] == 6, str(_t))
    check("paie : et le projete extrapole sur le rythme mesure",
          _t["projete"] > _t["gagne"], str(_t["projete"]))
    check("paie : sans aucun releve, on annonce zero sans planter",
          _histo([None, None])["gagne"] == 0.0)
    # Les jours a venir ne sont pas pre-remplis : on ne reproche a personne de
    # ne pas avoir encore vecu.
    check("paie : la quinzaine s arrete a aujourd hui",
          _histo([20] * 15)["jours_ecoules"] == 7)

    # La veille du premier jour tombe dans la quinzaine PRECEDENTE : c'est
    # comme ca que le portail du VA remonte d'une quinzaine.
    for _j, _attendu in (("2026-09-07", ("2026-08-16", "2026-08-31")),
                         ("2026-09-20", ("2026-09-01", "2026-09-15")),
                         ("2026-03-05", ("2026-02-16", "2026-02-28"))):
        _d0, _ = _obp.quinzaine(_j)
        _av = (_dp.date.fromisoformat(_d0) - _dp.timedelta(days=1)).isoformat()
        check("paie : la quinzaine d avant %s est %s" % (_j, _attendu[0]),
              _obp.quinzaine(_av) == _attendu, str(_obp.quinzaine(_av)))

    # --- Le tarif et le nombre de comptes, fiche par fiche ---------------
    _vraiObj = _obp.OBJECTIFS_FILE
    _obp.OBJECTIFS_FILE = _pp.Path(_tp.mkdtemp()) / "obj.json"
    check("paie : sans reglage, la fiche prend les defauts",
          _obp.reglage_paie("id", "va") == (5.0, 20))
    _obp.fixer_paie("id", "va", paie_jour=8, base_comptes=10)
    check("paie : le tarif et le nombre de comptes se reglent par fiche",
          _obp.reglage_paie("id", "va") == (8.0, 10),
          str(_obp.reglage_paie("id", "va")))
    # LE PIEGE : fixer_objectif ecrasait tout l'enregistrement de la fiche.
    _obp.fixer_objectif("id", "va", 25)
    check("paie : changer l objectif n efface pas le tarif",
          _obp.reglage_paie("id", "va") == (8.0, 10),
          str(_obp.reglage_paie("id", "va")))
    check("paie : et l objectif est bien pose", _obp.objectif_de("id", "va") == 25)
    _obp.fixer_paie("id", "va", paie_jour=0, base_comptes=0)
    check("paie : zero remet au defaut, il ne pose pas zero",
          _obp.reglage_paie("id", "va") == (5.0, 20))
    check("paie : et l objectif survit a la remise a zero du tarif",
          _obp.objectif_de("id", "va") == 25)
    # Un tarif nul paierait tout le monde a rien, un denominateur nul
    # diviserait par zero : les deux doivent retomber sur le defaut.
    _obp.fixer_paie("id", "va", paie_jour="n importe quoi")
    check("paie : un tarif illisible ne casse rien",
          _obp.reglage_paie("id", "va")[0] == 5.0)
    _obp.fixer_paie("id", "va", paie_jour=99999)
    check("paie : un tarif aberrant est plafonne",
          _obp.reglage_paie("id", "va")[0] == 1000.0,
          str(_obp.reglage_paie("id", "va")[0]))
    _obp.OBJECTIFS_FILE = _vraiObj

    _obp.HISTO_FILE = _vrai
except Exception as _epa:
    check("paie : testable", False, repr(_epa)[:200])


print()
print("=" * 70)
print("PERIMETRE DU SCRAPE : ne jamais juger ce qu on ne mesure plus")
print("=" * 70)
try:
    import json as _jsu, time as _tsu
    import jb_objectifs as _obs

    _fsu = _obs.SCRAPE_IDENTS_FILE
    _fsu.parent.mkdir(parents=True, exist_ok=True)
    _sauve = _fsu.read_text(encoding="utf-8") if _fsu.exists() else None

    def _perimetre(actives):
        if actives is None:
            _fsu.unlink(missing_ok=True)
            _fsu.with_suffix(".json.prev").unlink(missing_ok=True)
        else:
            _fsu.write_text(_jsu.dumps({"actives": actives}), encoding="utf-8")

    _cs = [{"username": "z%d" % i, "created_at": _tsu.time() - 40 * 86400}
           for i in range(4)]
    _st = {c["username"]: {"scraped_at": _tsu.time() - 5 * 86400, "reel_days": {}}
           for c in _cs}
    try:
        # SANS REGLAGE, TOUT EST SUIVI : deployer ne doit rien eteindre.
        _perimetre(None)
        check("perimetre : sans fichier, tout est suivi", _obs.suivi_actif("jessye"))
        _e = _obs.etat_fiche("jessye", "VA Z", _cs, _st)
        check("perimetre : suivie, les muets sont des oublis",
              _e["oublies"] == 4 and _e["non_mesures"] == 0, str(_e["oublies"]))

        _perimetre(["autre"])
        check("perimetre : eteinte, suivi_actif est faux",
              not _obs.suivi_actif("jessye"))
        _e2 = _obs.etat_fiche("jessye", "VA Z", _cs, _st)
        check("perimetre : eteinte, plus AUCUN oubli reproche",
              _e2["oublies"] == 0, str(_e2["oublies"]))
        check("perimetre : eteinte, les comptes sont NON MESURES",
              _e2["non_mesures"] == 4, str(_e2["non_mesures"]))
        check("perimetre : la fiche porte son etat de suivi",
              _e2["suivi"] is False)
        # LE POINT QUI COUTE DE L ARGENT : aucune journee a zero ne doit
        # entrer dans le fichier qui sert a payer.
        check("perimetre : aucune journee gravee pour une fiche non suivie",
              _obs.enregistrer_jour([_e2], _obs.aujourdhui()) == 0)
        _perimetre(["jessye"])
        check("perimetre : rallumee, elle redevient mesurable",
              _obs.suivi_actif("jessye")
              and _obs.etat_fiche("jessye", "VA Z", _cs, _st)["non_mesures"] == 0)
    finally:
        if _sauve is None:
            _fsu.unlink(missing_ok=True)
            _fsu.with_suffix(".json.prev").unlink(missing_ok=True)
        else:
            _fsu.write_text(_sauve, encoding="utf-8")

    # Les ecrans doivent le DIRE, pas afficher un zero.
    _srcW = pathlib.Path("web_upload.py").read_text(encoding="utf-8")
    _srcV = pathlib.Path("va_portal.py").read_text(encoding="utf-8")
    check("perimetre : le dashboard dit « non suivie »", "non suivie" in _srcW)
    check("perimetre : le portail dit « suivi en pause »", "suivi en pause" in _srcV)
    check("perimetre : le portail n affiche AUCUN montant sans mesure",
          "ta paie ne" in _srcV.lower())
except Exception as _esu:
    check("perimetre : testable", False, repr(_esu)[:200])

# ==============================================================================
# TRASH TREND ET MENUS PAR FAMILLE (bot, 25/09/2026)
# ==============================================================================
# Chaque vue est CONSTRUITE avec discord.py puis serialisee (to_components) :
# c'est ce que Discord recoit, et c'est la qu'un 26e composant ou un 6e bouton
# sur une rangee fait echouer la vue ENTIERE -- pas seulement le bouton de trop.
# Les registres lus par le bot sont rediriges vers un dossier temporaire.
print()
print("=" * 70)
print("TRASH TREND ET MENUS PAR FAMILLE (bot)")
print("=" * 70)
try:
    import asyncio as _aioTb
    import inspect as _insTb
    import json as _jsTb
    import logging as _lgTb
    import pathlib as _plTb
    import re as _reTb
    import shutil as _shTb
    import tempfile as _tfTb
    import types as _tyTb
    import discord as _dTb
    import guild_features as _gfTb
    import marques_montage as _mmTb
    import cogs.user as _uTb

    _TRASH = tuple(_mmTb.MARQUES["trash"]["actions"])
    _FLASH = tuple(_mmTb.MARQUES["flash"]["actions"])
    _LOGO = _mmTb.MARQUES["trash"]["emoji"]

    def _rowsTb(vue):
        """[[custom_id…] par rangee], tel que Discord le recevra."""
        return [[c.get("custom_id") for c in r["components"]] for r in vue.to_components()]

    def _limitesTb(vue):
        """'' si la vue tient dans les limites de Discord, sinon la raison."""
        rows = vue.to_components()
        comps = [c for r in rows for c in r["components"]]
        ids = [c["custom_id"] for c in comps if c.get("custom_id")]
        libs = [c.get("label") or "" for c in comps]
        pbs = []
        if len(comps) > 25:
            pbs.append("%d composants" % len(comps))
        if len(rows) > 5:
            pbs.append("%d rangees" % len(rows))
        if any(len(r["components"]) > 5 for r in rows):
            pbs.append("rangee > 5 : %s" % [len(r["components"]) for r in rows])
        if any(len(r["components"]) > 1 and any(c["type"] != 2 for c in r["components"])
               for r in rows):
            pbs.append("un menu deroulant partage sa rangee")
        if any(len(i) > 100 for i in ids):
            pbs.append("custom_id > 100 : %s" % max(ids, key=len))
        if len(ids) != len(set(ids)):
            pbs.append("custom_id en double")
        if any(len(l) > 80 for l in libs):
            pbs.append("libelle > 80")
        return " ; ".join(pbs)

    class _RepTb:
        def __init__(self):
            self.envois, self._fait = [], False

        async def send_message(self, *a, **k):
            self.envois.append((a[0] if a else k.get("content"), k))
            self._fait = True

        async def edit_message(self, *a, **k):
            self.envois.append(("<edit>", k))
            self._fait = True

        async def defer(self, *a, **k):
            self._fait = True

        def is_done(self):
            return self._fait

    def _itxTb(guild=None):
        return _tyTb.SimpleNamespace(
            response=_RepTb(), guild=guild, user=_tyTb.SimpleNamespace(id=5),
            client=_tyTb.SimpleNamespace(get_cog=lambda n: None), channel=None)

    _journalTb = []

    class _HTb(_lgTb.Handler):
        def emit(self, r):
            _journalTb.append(r.getMessage())

    _hTb = _HTb()
    _lgTb.getLogger().addHandler(_hTb)

    # -- 1. LES REGISTRES, LUS PAR LE BOT -----------------------------------------
    _TB = _plTb.Path(_tfTb.mkdtemp(prefix="trash_bot_"))
    _savTb = (_uTb.DATA_DIR, _uTb.IDENTITIES_DIR, _uTb.get_user_identity)
    try:
        _uTb.DATA_DIR = _TB
        _uTb.IDENTITIES_DIR = _TB / "identities"
        _tdTb = _uTb.IDENTITIES_DIR / "zzbot" / "templates"
        _tdTb.mkdir(parents=True)
        for _nB in "abcdefg":
            (_tdTb / (_nB + ".mp4")).write_bytes(b"x" + _nB.encode())
            if _nB != "e":        # « e » n'a pas de point de coupe
                (_tdTb / (_nB + ".montage.json")).write_text(
                    '{"segments": "[]", "cut_at": 1.5}', encoding="utf-8")
        _PB = "zzbot|templates|"

        def _regTb(nom, noms):
            (_TB / nom).write_text(_jsTb.dumps([_PB + n + ".mp4" for n in noms]),
                                   encoding="utf-8")

        # b est Flash ET Trash (donnee ancienne) ; d et g sont mis de cote ⊘.
        _regTb("flash_trend.json", "abg")
        _regTb("trash_trend.json", "bcdef")
        _regTb("disabled_reels.json", "dg")
        _regTb("fav_brutes.json", "ac")
        _avantTb = {f.name: f.read_text(encoding="utf-8") for f in _TB.glob("*.json")}
        _ecTb = {}
        _uT, _scT = _uTb.marque_templates_for("trash", "zzbot", ecartes=_ecTb)
        check("trash bot : sert les Trash utilisables (c, f), dans l ordre",
              [p.name for p, _d in _uT] == ["c.mp4", "f.mp4"], str([p.name for p, _d in _uT]))
        check("trash bot : ecarte ET compte le doublon Flash, le ⊘ et le sans-coupe",
              _ecTb.get("conflits") == 1 and _ecTb.get("desactives") == 1
              and _ecTb.get("sans_coupe") == 1 and _scT == 1 and _ecTb.get("erreurs") == [],
              str(_ecTb))
        _uT, _scT = _uTb.marque_templates_for("trash", "zzbot", exiger_banger=True)
        check("trash bot : ⭐ Trash = Trash ET etoile", [p.name for p, _d in _uT] == ["c.mp4"],
              str([p.name for p, _d in _uT]))
        _ecFb = {}
        _uF, _scF = _uTb.flash_templates_for("zzbot", ecartes=_ecFb)
        # Le bug d'avant : aucun selecteur du bot ne lisait le ⊘ du site, un
        # template mis de cote partait quand meme par ⚡ Flash.
        check("flash bot : le template ⊘ n est plus servi, et il est compte",
              [p.name for p, _d in _uF] == ["a.mp4", "b.mp4"] and _ecFb.get("desactives") == 1
              and _ecFb.get("conflits") == 0, str(([p.name for p, _d in _uF], _ecFb)))
        check("flash bot : flash_templates_for reste l enveloppe de marque_templates_for",
              [p.name for p, _d in _uF]
              == [p.name for p, _d in _uTb.marque_templates_for("flash", "zzbot")[0]])
        check("trash bot : le bot LIT les registres, il n y ecrit jamais",
              {f.name: f.read_text(encoding="utf-8") for f in _TB.glob("*.json")} == _avantTb)
        (_TB / "trash_trend.json").unlink()
        _ecTb = {}
        check("trash bot : trash_trend.json absent (pas encore de marque) -> liste vide, sans erreur",
              _uTb.marque_templates_for("trash", "zzbot", ecartes=_ecTb) == ([], 0)
              and _ecTb.get("erreurs") == [], str(_ecTb))
        (_TB / "trash_trend.json").write_text("{pas du json", encoding="utf-8")
        _ecTb = {}
        _rT = _uTb.marque_templates_for("trash", "zzbot", ecartes=_ecTb)
        check("trash bot : un registre Trash illisible est NOMME au lieu de passer pour vide",
              _rT == ([], 0) and any("trash_trend.json illisible" in e for e in _ecTb.get("erreurs", [])),
              str(_ecTb))
        _regTb("trash_trend.json", "bcdef")
        (_TB / "flash_trend.json").write_text("[[[", encoding="utf-8")
        _ecTb = {}
        _rT = _uTb.marque_templates_for("trash", "zzbot", ecartes=_ecTb)
        check("trash bot : un registre Flash illisible ne bloque pas Trash, mais c est dit",
              [p.name for p, _d in _rT[0]] == ["b.mp4", "c.mp4", "f.mp4"]
              and any("flash_trend.json illisible" in e for e in _ecTb.get("erreurs", [])),
              str(_ecTb))
        _regTb("flash_trend.json", "abg")

        # -- 2. CE QUE LE VA LIT QUAND RIEN NE PART ---------------------------------
        # Un admin qui a marque cinq montages et n'en voit aucun arriver doit
        # apprendre POURQUOI : point de coupe, ⊘, double marque.
        _regTb("trash_trend.json", "bde")
        _uTb.get_user_identity = lambda uid: "zzbot"
        _iT = _itxTb()
        class _CogGate:
            # Le serveur autorise le contenu : seule la selection est testee.
            async def _gate_contenu(self, itx, threads_ok=False):
                return False

        _aioTb.run(_uTb.UserCog._send_template_marque(_CogGate(), _iT, "trash"))
        _msgT = str(_iT.response.envois[0][0]) if _iT.response.envois else ""
        check("trash bot : sans Trash utilisable, message EPHEMERE au VA, logo du module",
              _iT.response.envois and _iT.response.envois[0][1].get("ephemeral") is True
              and _msgT.startswith(_LOGO), _msgT[:120])
        check("trash bot : ... qui compte chaque montage ecarte (coupe, ⊘, aussi ⚡ Flash)",
              _msgT.count("écarté(s)") == 3 and "point de coupe" in _msgT and "⊘" in _msgT
              and ("%s %s" % (_mmTb.MARQUES["flash"]["emoji"], _mmTb.MARQUES["flash"]["court"])) in _msgT,
              _msgT[:400])
    finally:
        _uTb.DATA_DIR, _uTb.IDENTITIES_DIR, _uTb.get_user_identity = _savTb
        _shTb.rmtree(_TB, ignore_errors=True)

    # -- 3. QUATRE METHODES, AUCUNE COMMANDE SLASH ----------------------------------
    # Le bot principal est a 100 commandes sur 100 : une de plus fait echouer la
    # synchronisation de TOUT l'arbre, sans un message.
    _slashTb = [c.name for c in getattr(_uTb.UserCog, "__cog_app_commands__", [])]
    check("trash bot : les 4 actions Trash sont des methodes du cog",
          all(_insTb.iscoroutinefunction(getattr(_uTb.UserCog, k, None)) for k in _TRASH),
          str([k for k in _TRASH if not hasattr(_uTb.UserCog, k)]))
    check("trash bot : ... et AUCUNE n est une commande slash",
          all(not hasattr(getattr(_uTb.UserCog, k), "callback") for k in _TRASH)
          and _slashTb and not any("trash" in n for n in _slashTb), str(_slashTb[:5]))
    _appelsTb = []

    class _CogMq:
        async def _send_template_marque(self, itx, cle, **k):
            _appelsTb.append((cle, k.get("exiger_banger", False),
                              k.get("brute_favorite", False), k.get("nombre")))

    for _kT in _TRASH:
        _aioTb.run(getattr(_uTb.UserCog, _kT)(_CogMq(), None, nombre=4))
    check("trash bot : Trash, ⭐ Trash, ⭐ Brut + Trash, ⭐⭐ Trash + Brut -> la bonne exigence",
          _appelsTb == [("trash", False, False, 4), ("trash", True, False, 4),
                        ("trash", False, True, 4), ("trash", True, True, 4)], str(_appelsTb))
    _srcMq = _insTb.getsource(_uTb.UserCog._send_template_marque)
    check("trash bot : famille de reserve et prefixe de fichier suivent la marque",
          'prefixe_fichier=cle' in _srcMq and 'famille=famille' in _srcMq
          and 'f"{cle}_brut"' in _srcMq and 'f"{cle}_vid"' in _srcMq)

    # -- 4. LES TABLES : actions, libelles, icone ----------------------------------
    _clesTb = [a[0] for a in _uTb._JB_ACTIONS_US]
    check("trash bot : les 4 Trash sont declarees, ENTRE les templates et les Flash",
          all(k in _clesTb for k in _TRASH)
          and _clesTb.index("templatebrut") < _clesTb.index(_TRASH[0])
          and _clesTb.index(_TRASH[-1]) < _clesTb.index(_FLASH[0]), str(_clesTb))
    check("trash bot : libelles Trash tires du module, Flash inchanges",
          [a[1] for a in _uTb._JB_ACTIONS_US if a[0] in _TRASH]
          == ["%s Trash" % _LOGO, "⭐ Trash", "⭐ Brut + Trash", "⭐⭐ Trash + Brut"]
          and [a[1] for a in _uTb._JB_ACTIONS_US if a[0] in _FLASH]
          == ["⚡ Flash", "⭐ Flash", "⭐ Brut + Flash", "⭐⭐ Flash + Brut"])
    check("trash bot : chaque action pointe vers un attribut reel du cog",
          all(hasattr(_uTb.UserCog, a[2]) for a in _uTb._JB_ACTIONS_US),
          str([a[0] for a in _uTb._JB_ACTIONS_US if not hasattr(_uTb.UserCog, a[2])]))
    check("trash bot : les variantes Trash du menu VA suivent le reglage « contenu »",
          all(_uTb._MENU_BTN_FEATURE.get("cmenu:" + k) == "contenu"
              for k in (_TRASH[0], _TRASH[1], _TRASH[3])))
    # UNE icone pour les quatre : 50 emplacements d'emoji sans boost, partages
    # avec les PP des models.
    _pngTb = _plTb.Path("emojis") / "vatemplatetrash.png"
    check("trash bot : une seule icone pour les 4 Trash, et le PNG existe",
          {_uTb._ICONES_ACTIONS.get(k) for k in _TRASH} == {"vatemplatetrash"} and _pngTb.exists())

    class _GuildEmTb:
        emojis = []

        def __init__(self):
            self.crees = []

        async def create_custom_emoji(self, name, image, reason=None):
            self.crees.append(name)
            return _dTb.PartialEmoji(name=name, id=len(self.crees))

    _gEm = _GuildEmTb()
    _aioTb.run(_uTb.ensure_action_emojis(_gEm))
    check("trash bot : une icone partagee n est televersee qu UNE fois",
          _gEm.crees.count("vatemplatetrash") == 1 and len(_gEm.crees) == len(set(_gEm.crees)),
          str(_gEm.crees))

    # -- 5. LE PANNEAU US : UN MENU DEROULANT PAR FAMILLE (Components V2) ---------
    # CHANGEMENT VOULU (25/09/2026, maquette /demopanneau validee par le
    # proprietaire : « c'est good, vas-y »). Avant : {0:5, 1:4, 2:3, 3:4}, une
    # rangee de lanceurs « ▸ » qui ouvraient chacun un sous-menu ephemere, et
    # le ⭐⭐⭐ Trends. Maintenant : quantite + identite, publications, puis UN
    # MENU PAR FAMILLE (Brut, Caption, Template, Trash, Flash) directement dans
    # le panneau, sans etape ; Trends retire (« pas encore good »). Un message
    # classique plafonne a cinq rangees et un menu en prend une : le panneau
    # est passe au format « Components V2 » (LayoutView), que les helpers
    # ci-dessous lisent tel que Discord le recoit (to_components).
    def _compsV2Tb(vue):
        """Tous les composants envoyes a Discord, a plat et dans l'ordre
        (conteneur, texte, rangees, boutons, menus)."""
        pile, out = list(vue.to_components()), []
        while pile:
            c = pile.pop(0)
            out.append(c)
            pile[0:0] = list(c.get("components") or [])
        return out

    def _rowsV2Tb(vue):
        """[[custom_id…] par rangee], tel que Discord le recevra."""
        return [[b.get("custom_id") for b in c["components"]]
                for c in _compsV2Tb(vue) if c["type"] == 1]

    def _limitesV2Tb(vue):
        """'' si la vue V2 tient dans les limites de Discord, sinon la raison.
        Depasser ne retire pas l'element fautif : le message est refuse ENTIER."""
        comps = _compsV2Tb(vue)
        rows = [c for c in comps if c["type"] == 1]
        ids = [c["custom_id"] for c in comps if c.get("custom_id")]
        pbs = []
        if len(comps) > 40:
            pbs.append("%d composants" % len(comps))
        if sum(len(c.get("content") or "") for c in comps if c["type"] == 10) > 4000:
            pbs.append("texte > 4000")
        if any(len(r["components"]) > 5 for r in rows):
            pbs.append("rangee > 5 : %s" % [len(r["components"]) for r in rows])
        if any(len(r["components"]) > 1 and any(c["type"] != 2 for c in r["components"])
               for r in rows):
            pbs.append("un menu deroulant partage sa rangee")
        if any(len(i) > 100 for i in ids):
            pbs.append("custom_id > 100 : %s" % max(ids, key=len))
        if len(ids) != len(set(ids)):
            pbs.append("custom_id en double")
        if any(len(c.get("label") or "") > 80 for c in comps if c["type"] == 2):
            pbs.append("libelle > 80")
        for c in comps:
            if c["type"] == 3:
                if not 1 <= len(c.get("options") or []) <= 25:
                    pbs.append("%s : %d options" % (c["custom_id"], len(c.get("options") or [])))
                if any(len(o.get("label") or "") > 100 or len(o.get("description") or "") > 100
                       for o in c.get("options") or []):
                    pbs.append("%s : option > 100" % c["custom_id"])
        return " ; ".join(pbs)

    _GUILD_ICTb = _tyTb.SimpleNamespace(
        id=1, emojis=[_dTb.PartialEmoji(name=n, id=10000 + i)
                      for i, n in enumerate(sorted(set(_uTb._ICONES_ACTIONS.values())))])
    _FAMS_PTb = ("brut", "caption", "template", "trash", "flash")
    for _gT, _nomG in ((None, "sans icones"), (_GUILD_ICTb, "avec icones")):
        _vP = _uTb._jb_panel(None, "emma", 3, "us", _gT)
        _rP = _rowsV2Tb(_vP)
        check("familles : panneau US (%s) dans les limites de Discord" % _nomG,
              not _limitesV2Tb(_vP), _limitesV2Tb(_vP))
        check("familles : panneau US (%s) = quantite+identite, publications, un menu par famille" % _nomG,
              _rP == [["jbus:qb:emma:3"] + ["jbus:a:emma:%s:3" % k for k in ("name", "pseudo", "pp", "bio")],
                      ["jbus:a:emma:%s:3" % k for k in ("story", "storycta", "post")]]
              + [["jbus:s:emma:%s:3" % f] for f in _FAMS_PTb],
              str(_rP))
    check("familles : l ordre des menus suit la table unique (Brut, puis Trash entre Template et Flash)",
          [f.cle for f in _uTb._FAMILLES_MENU] == ["caption", "template", "trash", "flash"]
          and [f.cle for f in _uTb._FAMILLES_PANNEAU] == list(_FAMS_PTb)
          and _uTb._famille_menu("trash").actions == _TRASH
          and _uTb._famille_menu("flash").actions == _FLASH)
    # « trend » est masquee EXPRES (_JB_MASQUEES) : elle n'a pas de place, et
    # ce n'est pas un oubli. Toute autre action sans place serait un oubli.
    check("familles : chaque action du panneau a une place (aucune ecartee en silence)",
          _uTb._jb_disposition()[1] == []
          and all(a[0] in _uTb._JB_RANGEES or a[0] in _uTb._JB_MASQUEES
                  for a in _uTb._JB_ACTIONS_US)
          and _uTb._JB_MASQUEES == {"trend"},
          str(_uTb._jb_disposition()[1]))
    _vL = _uTb._jb_panel(None, "a" * 60, 100, "us", _GUILD_ICTb)
    check("familles : identite de 60 caracteres et quantite 100 -> custom_id <= 100",
          not _limitesV2Tb(_vL) and len(_rowsV2Tb(_vL)) == 7, _limitesV2Tb(_vL))

    # -- 6. LES MENUS DE FAMILLE (JBMenuFamille), ET LES ANCIENS LANCEURS ▸ -------
    # Chaque menu offre les variantes de SA famille, avec la ligne d'aide que
    # le sous-menu ephemere affichait avant (_EXPLICATIONS) en description.
    _vP = _uTb._jb_panel(None, "emma", 7, "us", _GUILD_ICTb)
    _menusTb = {c["custom_id"].split(":")[3]: c for c in _compsV2Tb(_vP) if c["type"] == 3}
    for _fT in _uTb._FAMILLES_PANNEAU:
        _mT = _menusTb.get(_fT.cle) or {}
        _optsT = _mT.get("options") or []
        check("familles : menu %s = ses %d variantes (jbus:s:…), une ligne d aide chacune"
              % (_fT.cle, len(_fT.actions)),
              _mT.get("custom_id") == "jbus:s:emma:%s:7" % _fT.cle
              and [o["value"] for o in _optsT] == list(_fT.actions)
              and all(o.get("description") == _uTb._EXPLICATIONS.get(o["value"])
                      and o.get("description") for o in _optsT)
              and _mT.get("placeholder") == "%s %s…" % (_fT.emoji, _fT.nom),
              str(_mT)[:200])
    _vraiCanTb, _vraiRefTb = _uTb._jb_can_use, _uTb._refus_reserve_jb
    try:
        _uTb._jb_can_use = lambda i: True
        _uTb._refus_reserve_jb = lambda i: ""
        # Un panneau poste entre dc157c3 et les menus directs porte encore ses
        # lanceurs « ▸ ». Plus de sous-menu : un clic RECONSTRUIT son panneau,
        # en V2, a la place (texte et embed vides : c'est ce qui permet a
        # Discord de convertir le message par une edition).
        _iT = _itxTb(_GUILD_ICTb)
        _aioTb.run(_uTb.JBFamilleBouton("emma", "trash", 5).callback(_iT))
        _envT = _iT.response.envois
        _vT = _envT[0][1].get("view") if _envT else None
        check("familles : un ancien lanceur ▸ reconstruit le panneau V2 SUR PLACE (plus de sous-menu)",
              len(_envT) == 1 and _envT[0][0] == "<edit>"
              and _envT[0][1].get("content", 1) is None and _envT[0][1].get("embed", 1) is None
              and isinstance(_vT, _dTb.ui.LayoutView)
              and ["jbus:s:emma:trash:5"] in _rowsV2Tb(_vT), str(_envT)[:200])
        # Depuis un panneau EPHEMERE (le panneau de secours), la vue part
        # ARRETEE : suivie par discord.py, son expiration emportait les motifs
        # enregistres au demarrage et tous les panneaux devenaient muets.
        _iT = _itxTb(_GUILD_ICTb)
        _iT.message = _tyTb.SimpleNamespace(id=9, flags=_tyTb.SimpleNamespace(ephemeral=True))
        _aioTb.run(_uTb.JBFamilleBouton("emma", "trash", 5).callback(_iT))
        _vT = _iT.response.envois[0][1].get("view") if _iT.response.envois else None
        check("familles : ... depuis un panneau EPHEMERE, une vue ARRETEE (non suivie par discord.py)",
              _vT is not None and _vT.is_finished())
        _iT = _itxTb()
        _aioTb.run(_uTb.JBFamilleBouton("emma", "inconnue", 5).callback(_iT))
        check("familles : une famille inconnue est refusee en le disant",
              _iT.response.envois and "inconnue" in str(_iT.response.envois[0][0])
              and _iT.response.envois[0][1].get("ephemeral") is True, str(_iT.response.envois))
        _uTb._refus_reserve_jb = lambda i: "⛔ reserve"
        _iT = _itxTb()
        _aioTb.run(_uTb.JBFamilleBouton("zres", "trash", 5).callback(_iT))
        check("familles : une reserve est refusee au lanceur comme a l action",
              _iT.response.envois and _iT.response.envois[0][0] == "⛔ reserve")
        _uTb._refus_reserve_jb = lambda i: ""
        _uTb._jb_can_use = lambda i: False
        _iT = _itxTb()
        _aioTb.run(_uTb.JBFamilleBouton("emma", "trash", 5).callback(_iT))
        check("familles : le lanceur garde le role Jailbreak",
              _iT.response.envois and "Réservé" in str(_iT.response.envois[0][0]))
    finally:
        _uTb._jb_can_use, _uTb._refus_reserve_jb = _vraiCanTb, _vraiRefTb

    # -- 7. LES ANCIENS MESSAGES DEJA POSTES REPONDENT TOUJOURS ---------------------
    # Les panneaux et les menus VA epingles avant le 25/09/2026 portent les
    # custom_id d'avant. cog_load doit enregistrer de quoi repondre a chacun --
    # par UN element exactement : discord.py lance tous ceux qui correspondent.
    class _BotTb:
        def __init__(self):
            self.vues, self.dyn = [], []

        def add_view(self, v, message_id=None):
            self.vues.append(v)

        def add_dynamic_items(self, *items):
            self.dyn.extend(items)

    _botT = _BotTb()
    del _journalTb[:]
    _aioTb.run(_uTb.UserCog.cog_load(_tyTb.SimpleNamespace(
        bot=_botT, daily_menu=_tyTb.SimpleNamespace(is_running=lambda: True))))
    check("familles : cog_load enregistre tout, sans un echec au journal",
          not [l for l in _journalTb if "cog_load" in l]
          and _uTb.JBFamilleBouton in _botT.dyn and _uTb.JBActionButton in _botT.dyn
          and _uTb.JBMenuFamille in _botT.dyn
          and any(isinstance(v, _uTb.ContentMenuHeritageView) for v in _botT.vues)
          and any(isinstance(v, _uTb.ContentMenuLanceursView) for v in _botT.vues),
          str([l for l in _journalTb if "cog_load" in l])[:200])
    # walk_children : dans une LayoutView (menu VA V2), boutons et menus vivent
    # dans un conteneur, pas au premier niveau.
    _persTb = {it.custom_id for v in _botT.vues for it in v.walk_children()
               if not isinstance(it, _dTb.ui.DynamicItem) and getattr(it, "custom_id", None)}
    _motifsTb = [(c, c.__discord_ui_compiled_template__) for c in _botT.dyn]

    def _qui(cid):
        if cid in _persTb:
            return ["vue"]
        return [c.__name__ for c, p in _motifsTb if p.fullmatch(cid)]

    # Les custom_id d'AVANT (ef00e45) : le panneau US, sa quantite, la grille,
    # et les 25 boutons du menu VA.
    _ANCIENS_US = ("name", "pseudo", "pp", "bio", "story", "storycta", "post", "brute",
                   "brutbanger", "reelcaption", "capbanger", "brutcaption", "montagebanger",
                   "reelmonte", "templatebanger", "bruttemplate", "templatebrut",
                   "templateflash", "templateflashbanger", "brutflash", "templateflashbrut",
                   "trend", "brutchoix")
    _ANCIENS_MENU = ("reel", "story", "post", "storycta", "banger", "reelmonte", "pseudo",
                     "name", "bio", "pp", "lien", "clics", "help", "tuto", "addaccount",
                     "comptes", "pay", "capbanger", "montagebanger", "templateflash",
                     "templateflashbanger", "templateflashbrut", "templatebanger",
                     "templatebrut", "brutbanger")
    _ancTb = (["jbus:a:emma:%s:3" % k for k in _ANCIENS_US]
              + ["jbus:qb:emma:3", "jbus:q:emma:3", "jbus:m:emma"]
              + ["cmenu:" + k for k in _ANCIENS_MENU])
    _sansTb = [(c, _qui(c)) for c in _ancTb if len(_qui(c)) != 1]
    check("familles : les %d custom_id des anciens messages sont pris en charge, chacun par UN element"
          % len(_ancTb), not _sansTb, str(_sansTb)[:200])
    check("familles : ... et chaque ancienne action du panneau vise encore une methode reelle",
          all(_uTb._jb_action(k) and hasattr(_uTb.UserCog, _uTb._jb_action(k)[2])
              for k in _ANCIENS_US))
    # Les lanceurs « ▸ » de dc157c3 (panneau US et menu VA) : plus poses,
    # toujours servis.
    _lancTb = (["jbus:f:emma:%s:3" % f.cle for f in _uTb._FAMILLES_MENU]
               + ["cmenu:fam:" + f.cle for f in _uTb._FAMILLES_MENU])
    _sansLTb = [(c, _qui(c)) for c in _lancTb if len(_qui(c)) != 1]
    check("familles : les 8 lanceurs ▸ deja postes (jbus:f:, cmenu:fam:) sont pris en charge, chacun par UN element",
          not _sansLTb, str(_sansLTb)[:200])
    _neufsTb = ([it.custom_id for it in _uTb._jb_panel(None, "emma", 3).walk_children()
                 if isinstance(it, _dTb.ui.DynamicItem)]
                + [it.custom_id for it in _uTb.ContentMenuView(None).walk_children()
                   if getattr(it, "custom_id", None)])
    _sansNTb = [(c, _qui(c)) for c in _neufsTb if len(_qui(c)) != 1]
    check("familles : chaque NOUVEAU custom_id persistant est pris en charge par UN element",
          _neufsTb and not _sansNTb, str(_sansNTb)[:200])
    _tfTb2 = _uTb.JBFamilleBouton.__discord_ui_compiled_template__
    _idsFTb = ["jbus:f:%s:%s:%d" % (i, f.cle, q) for i in ("emma", "a.b-c_d", "x" * 60)
               for f in _uTb._FAMILLES_MENU for q in (1, 3, 100)]
    check("familles : jbus:f: ne recoupe aucun autre motif, dans les deux sens",
          all(_qui(i) == ["JBFamilleBouton"] for i in _idsFTb)
          and not any(_tfTb2.fullmatch(c) for c in _ancTb + _neufsTb if not c.startswith("jbus:f:")))
    # Le motif des menus du panneau V2 : discord.py lance TOUS les motifs qui
    # correspondent, un recoupement ferait partir deux actions pour un choix.
    _tsTb = _uTb.JBMenuFamille.__discord_ui_compiled_template__
    _idsSTb = ["jbus:s:%s:%s:%d" % (i, f.cle, q) for i in ("emma", "a.b-c_d", "x" * 60)
               for f in _uTb._FAMILLES_PANNEAU for q in (1, 3, 100)]
    check("familles : jbus:s: ne recoupe aucun autre motif, dans les deux sens",
          all(_qui(i) == ["JBMenuFamille"] for i in _idsSTb)
          and not any(_tsTb.fullmatch(c) for c in _ancTb + _lancTb + _neufsTb
                      if not c.startswith("jbus:s:")))

    # -- 8. LE MENU VA : vue V2 persistante, un menu deroulant par famille --------
    # CHANGEMENT VOULU (meme decision) : la rangee de lanceurs « ▸ » et ses
    # sous-menus ephemeres sont remplaces par un menu deroulant par famille,
    # persistant (« cmenu:sel:<famille> »), dans une LayoutView V2.
    _vM = _uTb.ContentMenuView(None)
    _nM = len(_compsV2Tb(_vM))
    check("familles : menu VA V2 dans les limites (%d composants <= 40)" % _nM,
          not _limitesV2Tb(_vM) and _vM.is_persistent() and _vM.has_components_v2(),
          _limitesV2Tb(_vM))
    _rM = _rowsV2Tb(_vM)
    check("familles : menu VA -> un menu par famille (cmenu:sel:), dans l ordre de la table, apres les boutons",
          len(_rM) == 8 and _rM[2:6] == [["cmenu:sel:" + f.cle] for f in _uTb._FAMILLES_MENU],
          str(_rM))
    _vH = _uTb.ContentMenuHeritageView(None)
    _idsH = [it.custom_id for it in _vH.children]
    check("familles : la vue heritee garde les 8 boutons retires, persistante, sans doublon avec le menu",
          sorted(_idsH) == sorted("cmenu:" + k for k in (
              "reelmonte", "templateflash", "templateflashbanger", "templateflashbrut",
              "capbanger", "montagebanger", "templatebanger", "templatebrut"))
          and _vH.is_persistent()
          and not set(_idsH) & {getattr(it, "custom_id", None) for it in _vM.walk_children()},
          str(_idsH))
    _vraiesGf = (_gfTb.get_features, _gfTb.threads_mode)
    try:
        _gfTb.get_features = lambda g: set(_gfTb.ALL_FEATURES)
        _gfTb.threads_mode = lambda g: False
        _vAttTb = {"caption": ["capbanger", "montagebanger"],
                   "template": ["reelmonte", "templatebanger", "templatebrut"],
                   "trash": [_TRASH[0], _TRASH[1], _TRASH[3]],
                   "flash": [_FLASH[0], _FLASH[1], _FLASH[3]]}
        # Le nom dit « sous-menus » (historique) : ce sont les variantes de
        # chaque famille, que les menus deroulants offrent desormais.
        check("familles : sous-menus du menu VA = exactement les variantes du cahier",
              {f.cle: _uTb._variantes_menu_va(f.cle, set(_gfTb.ALL_FEATURES), False)
               for f in _uTb._FAMILLES_MENU} == _vAttTb)
        _vMs = _uTb._menu_va(None, "emma", None)
        _optsM = {c["custom_id"].split(":")[2]: [o["value"] for o in c["options"]]
                  for c in _compsV2Tb(_vMs) if c["type"] == 3}
        check("familles : les menus deroulants du menu VA offrent exactement ces variantes",
              _optsM == _vAttTb, str(_optsM))
        # L'aide qui etait dans l'embed passe dans le texte d'en tete : 4000
        # caracteres pour TOUT le texte, et la derniere ligne est la marque qui
        # fait reconnaitre le menu (_est_menu_va).
        _txM = "\n".join(c.get("content") or "" for c in _compsV2Tb(_vMs) if c["type"] == 10)
        check("familles : le texte d aide du menu VA tient (%d car. <= 4000), marque en derniere ligne"
              % len(_txM),
              len(_txM) <= 4000 and _txM.splitlines()[-1] == _uTb._MENU_VA_MARQUE
              and all(f.nom in _txM for f in _uTb._FAMILLES_MENU), _txM[-200:])
        _gfTb.get_features = lambda g: set(_gfTb.ALL_FEATURES) - {"contenu"}
        _vF = _uTb._filter_menu_view(_uTb.ContentMenuView(None), None)
        check("familles : « contenu » coupe -> plus aucun menu de famille (pas de menu vide)",
              not [c for c in _compsV2Tb(_vF) if c["type"] == 3]
              and not _limitesV2Tb(_vF), _rowsV2Tb(_vF))
    finally:
        _gfTb.get_features, _gfTb.threads_mode = _vraiesGf

    # Les variantes appellent EXACTEMENT ce qu'appelaient les anciens boutons.
    _appelsV = []

    class _CogV:
        def __init__(self):
            async def _cb(cog, itx):
                _appelsV.append(("reelmonte",))
            self.reelmonte = _tyTb.SimpleNamespace(callback=_cb)

        async def _send_caption_bangers(self, itx):
            _appelsV.append(("_send_caption_bangers",))

        async def _send_montage_bangers(self, itx):
            _appelsV.append(("_send_montage_bangers",))

        async def _send_template_plus_brute(self, itx, **k):
            _appelsV.append(("_send_template_plus_brute", tuple(sorted(k.items()))))

        async def _send_template_marque(self, itx, cle, **k):
            _appelsV.append((cle, tuple(sorted(k.items()))))

    _attV = {"reelmonte": ("reelmonte",), "capbanger": ("_send_caption_bangers",),
             "montagebanger": ("_send_montage_bangers",),
             "templatebanger": ("_send_template_plus_brute", (("brute_favorite", False),)),
             "templatebrut": ("_send_template_plus_brute", ())}
    for _mq, _acts in (("flash", _FLASH), ("trash", _TRASH)):
        _attV[_acts[0]] = (_mq, (("brute_favorite", False), ("exiger_banger", False)))
        _attV[_acts[1]] = (_mq, (("brute_favorite", False), ("exiger_banger", True)))
        _attV[_acts[3]] = (_mq, (("brute_favorite", True), ("exiger_banger", True)))
    _ecartsV = []
    _cogV = _CogV()
    for _bT in _uTb.ContentMenuHeritageView(_cogV).children:
        del _appelsV[:]
        _aioTb.run(_bT.callback(_itxTb()))
        if _appelsV != [_attV[_bT.cle]]:
            _ecartsV.append((_bT.custom_id, list(_appelsV)))
    for _cT in (_TRASH[0], _TRASH[1], _TRASH[3]):
        del _appelsV[:]
        _aioTb.run(_uTb._lancer_variante_va(_cogV, _itxTb(), _cT))
        if _appelsV != [_attV[_cT]]:
            _ecartsV.append((_cT, list(_appelsV)))
    check("familles : anciens boutons et variantes Trash lancent l appel attendu",
          not _ecartsV, str(_ecartsV)[:200])

    # -- 9. LE PANNEAU EPHEMERE DES SERVEURS NON-US ----------------------------------
    # Il plantait des sa construction (« item would not fit at row 0 ») :
    # choisir une model dans le menu Jailbreak ne repondait plus. Il suit
    # maintenant la MEME table que le panneau US, en V2 (quantite en menu, sur
    # sa rangee a elle).
    _pbJ = []
    for _icT in ({}, _uTb.icones_actions(_GUILD_ICTb)):
        try:
            _vJ = _uTb.JailbreakActionsView(None, "emma", 3, us=True, icones=_icT)
            if _limitesV2Tb(_vJ):
                _pbJ.append(_limitesV2Tb(_vJ))
        except Exception as _eJ:
            _pbJ.append(repr(_eJ))
    check("familles : JailbreakActionsView se construit en V2 (avec et sans icones), dans les limites",
          not _pbJ, " | ".join(_pbJ)[:200])

    class _CogJ:
        def __init__(self):
            self.appels = []

        async def _run_for_model(self, interaction, model, cmd, count=1, supports_count=True):
            self.appels.append((model, cmd, count))
            await interaction.response.defer()

    for _aJ in _uTb._JB_ACTIONS_US:
        setattr(_CogJ, _aJ[2], _aJ[2])
    _cogJ = _CogJ()
    _vJ = _uTb.JailbreakActionsView(_cogJ, "emma", 4, us=True)
    _vraiCanTb = _uTb._jb_can_use
    try:
        _uTb._jb_can_use = lambda i: True
        _menuJ = [c for c in _vJ.walk_children()
                  if isinstance(c, _uTb._JailbreakFamilleSelect) and c.famille == "trash"]
        check("familles : panneau ephemere -> le menu Trash offre ses 4 variantes",
              _menuJ and [o.value for o in _menuJ[0].options] == list(_TRASH),
              str([o.value for o in _menuJ[0].options]) if _menuJ else "pas de menu Trash")
        _menuJ[0]._values = [_TRASH[1]]
        _iJ = _itxTb()
        _aioTb.run(_menuJ[0].callback(_iJ))
        check("familles : ... et un choix lance l action (model, quantite du panneau)",
              _cogJ.appels == [("emma", _uTb._jb_action(_TRASH[1])[2], 4)], str(_cogJ.appels))
    finally:
        _uTb._jb_can_use = _vraiCanTb

    # -- 10. ✨ GENERAL ET STOCK ---------------------------------------------------------
    # CHANGEMENT VOULU (26/09/2026, partie E, « le menu stp juste pour caption
    # template trash et flash ») : le General est passe en Components V2, un
    # MENU DEROULANT par famille. Trash et ⭐ Trash ne partagent plus la
    # rangee 4 avec Flash : ils sont les deux options du menu 💀 Trash
    # (rangee prevue 4), place AVANT le menu ⚡ Flash (rangee prevue 5). Ce
    # qu'on protege ne change pas : Trash vit entre les templates et Flash,
    # et il pose le contenu sur une brute de la model (_JB_GEN_BRUTE).
    _famsGenTb = [f.cle for f in _uTb._JB_GEN_FAMILLES]
    check("trash bot : ✨ General -> menu Trash (Trash, ⭐ Trash) juste avant le menu Flash (Flash, ⭐ Flash)",
          [k for k, r in _uTb._JB_GENERAL_RANGEES.items() if r == 4] == [_TRASH[0], _TRASH[1]]
          and [k for k, r in _uTb._JB_GENERAL_RANGEES.items() if r == 5] == [_FLASH[0], _FLASH[1]]
          and _famsGenTb.index("trash") + 1 == _famsGenTb.index("flash")
          and _famsGenTb.index("template") + 1 == _famsGenTb.index("trash")
          and _uTb._jb_gen_famille("trash").actions == (_TRASH[0], _TRASH[1])
          and _uTb._jb_gen_famille("flash").actions == (_FLASH[0], _FLASH[1])
          and {_TRASH[0], _TRASH[1]} <= _uTb._JB_GEN_BRUTE,
          str((_famsGenTb, _uTb._JB_GENERAL_RANGEES)))
    # Plus de repli « famille inconnue = Flash » dans le stock : une famille
    # « trash » declaree un jour sans recette aurait ete remplie de Flash.
    import cogs.noctuspool as _npTb
    _fauxNp = _tyTb.SimpleNamespace()
    del _journalTb[:]
    _r1 = _npTb.NoctusPool._recette(_fauxNp, "zzbot", "trash")
    _r2 = _npTb.NoctusPool._recette(_fauxNp, "zzbot", "trash")
    check("trash bot : le stock ne fabrique RIEN pour une famille inconnue, et le journalise une fois",
          _r1 is None and _r2 is None
          and len([l for l in _journalTb if "'trash'" in l and "sans recette" in l]) == 1,
          str(_journalTb)[:200])

    # -- 11. SOUS-MENUS PERIMES DU PANNEAU US -------------------------------------------
    # Un sous-menu de famille est un ephemere ARRETE : il n'expire jamais. Le
    # VA ouvre « 💀 Trash ▸ » sur Lola, passe le panneau sur Julia, puis
    # clique l'ancien sous-menu : sans garde, les montages de LOLA partaient
    # dans le -content pendant que le panneau affichait Julia -- le melange
    # d'identites du 05/09/2026.
    class _MsgPTb:
        def __init__(self, mid=0, ephemere=False):
            self.id = mid
            self.flags = _tyTb.SimpleNamespace(ephemeral=ephemere)
            self.effaces = 0
            self.edits = []

        async def delete(self):
            self.effaces += 1

        async def edit(self, **k):
            self.edits.append(k)

    class _CogPTb:
        def __init__(self):
            self.appels = []

        async def _run_for_model(self, interaction, model, cmd, count=1, supports_count=True):
            self.appels.append((model, count))

    for _nomM in ("templatetrash", "templatetrashbanger", "bruttrash", "templatetrashbrut"):
        setattr(_CogPTb, _nomM, lambda *a, **k: None)
    _cogP = _CogPTb()

    def _itxPTb(chan_id=77, ephemere=True, mid=0, uid=5):
        _i = _itxTb()
        _i.channel = _tyTb.SimpleNamespace(id=chan_id)
        _i.message = _MsgPTb(mid, ephemere)
        _i.user = _tyTb.SimpleNamespace(id=uid)
        _i.client = _tyTb.SimpleNamespace(get_cog=lambda n: _cogP)
        return _i

    _vraisP = (_uTb._jb_can_use, _uTb._refus_reserve_jb, _uTb._JB_PANEL_STORE,
               dict(_uTb._JB_PANNEAU_COURANT), dict(_uTb._JB_SOUS_MENUS))
    _TP = _plTb.Path(_tfTb.mkdtemp(prefix="jb_sousmenus_"))
    try:
        _uTb._jb_can_use = lambda i: True
        _uTb._refus_reserve_jb = lambda i: ""
        _uTb._JB_PANEL_STORE = _TP / "us_panels.json"
        _uTb._JB_PANEL_STORE.write_text('{"77": 1000}', encoding="utf-8")
        _uTb._JB_PANNEAU_COURANT.clear()
        _uTb._JB_SOUS_MENUS.clear()

        # a) Le panneau est passe sur Julia : l'ancien sous-menu de Lola refuse.
        _uTb._JB_PANNEAU_COURANT[77] = ("julia", 3)
        _iP = _itxPTb()
        _aioTb.run(_uTb.JBActionButton("lola", "templatetrash", 3).callback(_iP))
        _repP = str(_iP.response.envois[0][0]) if _iP.response.envois else ""
        check("sous-menus : panneau passe sur une autre model -> l ancien sous-menu REFUSE, en le disant",
              not _cogP.appels and "Lola" in _repP and "Julia" in _repP
              and _iP.response.envois[0][1].get("ephemeral") is True, _repP[:160])
        # b) Meme model, autre quantite : refuse aussi.
        _uTb._JB_PANNEAU_COURANT[77] = ("lola", 5)
        _iP = _itxPTb()
        _aioTb.run(_uTb.JBActionButton("lola", "templatetrash", 3).callback(_iP))
        check("sous-menus : quantite changee sur le panneau -> l ancien sous-menu refuse",
              not _cogP.appels and _iP.response.envois
              and "5" in str(_iP.response.envois[0][0]), str(_iP.response.envois)[:160])
        # c) A jour : le clic part, avec la model et la quantite du bouton.
        _uTb._JB_PANNEAU_COURANT[77] = ("lola", 3)
        _aioTb.run(_uTb.JBActionButton("lola", "templatetrash", 3).callback(_itxPTb()))
        check("sous-menus : sous-menu a jour -> l action part (lola, 3)",
              _cogP.appels == [("lola", 3)], str(_cogP.appels))
        # d) Le panneau EPINGLE (message non ephemere) n'est jamais refuse, et
        #    un etat inconnu (redemarrage) ne refuse rien.
        del _cogP.appels[:]
        _uTb._JB_PANNEAU_COURANT[77] = ("julia", 3)
        _aioTb.run(_uTb.JBActionButton("lola", "templatetrash", 3).callback(
            _itxPTb(ephemere=False, mid=1000)))
        _uTb._JB_PANNEAU_COURANT.clear()
        _aioTb.run(_uTb.JBActionButton("lola", "templatetrash", 3).callback(_itxPTb()))
        check("sous-menus : ni le panneau epingle ni un etat inconnu (redemarrage) ne sont refuses",
              _cogP.appels == [("lola", 3), ("lola", 3)], str(_cogP.appels))

        # e) CHANGEMENT VOULU (menus directs, 25/09/2026) : un ancien lanceur
        #    « ▸ » n'ouvre PLUS de sous-menu -- il redessine le panneau en V2,
        #    sur place, et aucun nouveau sous-menu n'est retenu. Ceux ouverts
        #    AVANT le deploiement restent suivis (_JB_SOUS_MENUS), pour etre
        #    effaces au prochain changement de quantite ou de model (f, g).
        #    Clique depuis l'epingle, le lanceur apprend toujours ce que le
        #    panneau montre.
        _m1, _m2 = _MsgPTb(501, True), _MsgPTb(502, True)
        _uTb._JB_SOUS_MENUS[5] = (77, _m1)
        _iF = _itxPTb(ephemere=False, mid=1000)
        _aioTb.run(_uTb.JBFamilleBouton("lola", "trash", 3).callback(_iF))
        _envF = _iF.response.envois
        check("sous-menus : un ancien lanceur ▸ n ouvre plus de sous-menu, il redessine le panneau en V2",
              len(_envF) == 1 and _envF[0][0] == "<edit>"
              and isinstance(_envF[0][1].get("view"), _dTb.ui.LayoutView)
              and all(_v[1] is _m1 for _v in _uTb._JB_SOUS_MENUS.values()),
              str(_envF)[:160])
        check("sous-menus : ... et le clic depuis le panneau epingle apprend ce qu il montre",
              _uTb._JB_PANNEAU_COURANT.get(77) == ("lola", 3),
              str(_uTb._JB_PANNEAU_COURANT))
        _uTb._JB_SOUS_MENUS.clear()
        _uTb._JB_SOUS_MENUS[5] = (77, _m2)      # un ancien sous-menu encore affiche

        # f) Changer la quantite du panneau epingle : sous-menus effaces, etat
        #    retenu. Depuis un panneau de secours (autre message) : inconnu.
        _aioTb.run(_uTb._jb_panneau_qte_changee(_itxPTb(ephemere=False, mid=1000), "lola", 6))
        check("sous-menus : quantite changee -> sous-menus du salon effaces, nouvel etat retenu",
              _m2.effaces == 1 and not _uTb._JB_SOUS_MENUS
              and _uTb._JB_PANNEAU_COURANT.get(77) == ("lola", 6),
              str((_m2.effaces, _uTb._JB_PANNEAU_COURANT)))
        _aioTb.run(_uTb._jb_panneau_qte_changee(_itxPTb(ephemere=True, mid=999), "lola", 2))
        check("sous-menus : ... depuis un panneau de secours, l etat devient inconnu (rien de faux)",
              77 not in _uTb._JB_PANNEAU_COURANT, str(_uTb._JB_PANNEAU_COURANT))

        # g) Choisir une autre model dans la grille (serveur US) : le panneau
        #    epingle est reecrit, les sous-menus ouverts effaces, l'etat suit.
        import guild_features as _gfP
        _vraisGP = (_gfP.is_us_guild, _uTb.marche_du_membre, _uTb._jb_general_maj)
        try:
            _gfP.is_us_guild = lambda g: True
            _uTb.marche_du_membre = lambda u: "us"

            async def _genP(*a, **k):
                return None
            _uTb._jb_general_maj = _genP
            _epP = _MsgPTb(1000, False)
            _m3 = _MsgPTb(503, True)
            _uTb._JB_SOUS_MENUS[5] = (77, _m3)
            _iM = _itxPTb(ephemere=False, mid=2000)

            async def _fetchP(mid):
                return _epP
            _iM.channel = _tyTb.SimpleNamespace(id=77, fetch_message=_fetchP)
            _aioTb.run(_uTb.JBModelButton("julia").callback(_iM))
            check("sous-menus : autre model choisie -> panneau reecrit, sous-menus effaces, etat = julia",
                  len(_epP.edits) == 1 and _m3.effaces == 1 and not _uTb._JB_SOUS_MENUS
                  and _uTb._JB_PANNEAU_COURANT.get(77) == ("julia", 3),
                  str((len(_epP.edits), _m3.effaces, _uTb._JB_PANNEAU_COURANT)))
        finally:
            _gfP.is_us_guild, _uTb.marche_du_membre, _uTb._jb_general_maj = _vraisGP
    finally:
        _uTb._jb_can_use, _uTb._refus_reserve_jb, _uTb._JB_PANEL_STORE = _vraisP[:3]
        _uTb._JB_PANNEAU_COURANT.clear()
        _uTb._JB_PANNEAU_COURANT.update(_vraisP[3])
        _uTb._JB_SOUS_MENUS.clear()
        _uTb._JB_SOUS_MENUS.update(_vraisP[4])
        import shutil as _shP
        _shP.rmtree(_TP, ignore_errors=True)
except Exception as _eTb:
    import traceback as _tbTb
    check("trash bot : testable", False, repr(_eTb)[:200] + " " + _tbTb.format_exc()[-500:])
finally:
    # Le journal de la section ne doit pas continuer a tout capturer ensuite.
    try:
        _lgTb.getLogger().removeHandler(_hTb)
    except NameError:
        pass


# ==============================================================================
# MENUS DIRECTS (« Components V2 ») : panneau US, panneau ephemere, menu VA,
# ✨ General
# ==============================================================================
# Le 25/09/2026, le proprietaire a valide la maquette /demopanneau (« c'est
# good, vas-y ») : plus de lanceur « ▸ » qui ouvre un sous-menu ephemere, UN
# MENU DEROULANT PAR FAMILLE directement dans le panneau, et « ⭐⭐⭐ Trends »
# retire (« pas encore good »). Un message classique plafonne a cinq rangees
# et un menu en prend une entiere : le panneau US, le panneau ephemere des
# serveurs non-US et le menu VA sont passes au format « Components V2 »
# (LayoutView : 40 composants, 4000 caracteres de texte, plus d'embed).
# Le 26/09/2026, le ✨ General (3e message epingle du salon -menu US) a suivi,
# a la demande du proprietaire (« le menu stp juste pour caption template
# trash et flash ») : PP, Bio, Story, Story CTA et Post restent des boutons,
# Caption, Template, Trash et Flash deviennent un menu chacun (partie E).
#
# Ce qui casse SANS SE VOIR, et que cette section rejoue -- vues CONSTRUITES
# par discord.py, clics SIMULES avec de faux objets Discord (reponse unique
# exigee : une seconde reponse leve, comme chez Discord) et un vrai ViewStore
# pour les redemarrages :
#   - une interaction qui recoit deux reponses, ou aucune (« l'interaction a
#     echoue ») ;
#   - un menu qui ne revient pas a son intitule : re-choisir la meme option ne
#     declenche alors plus rien cote Discord ;
#   - un panneau ou un menu V2 que la recherche dans les epingles ne reconnait
#     pas (un second est poste a cote), ou que _delete_old_menus supprime ;
#   - un message deja poste (embed, lanceur « ▸ », ancien custom_id) qui ne
#     repond plus apres le deploiement ou apres un redemarrage ;
#   - une ecriture dans data/ : les fichiers d'ids sont detournes vers un
#     dossier temporaire, et un crochet d'audit le VERIFIE.
#
# Chaque partie est une FONCTION : ses faux objets (Msg, Salon, Itx…) ne
# fuient pas dans la suite. Ce qu'elle change dans les modules (cogs.user,
# cogs.welcome, guild_features…) est remis en place apres, meme si elle leve.
print()
print("=" * 70)
print("MENUS DIRECTS (Components V2) : panneau US, panneau ephemere, menu VA, General")
print("=" * 70)
_check_v2 = check

def _v2_bloc_panneau():
    'Parties A et B : panneau US epingle, panneau ephemere non-US, reperage, conversion, welcome, maquette.'
    import asyncio
    import json
    import logging
    import os
    import re
    import sys
    import tempfile
    import types
    from pathlib import Path
    import discord
    from discord.components import _component_factory

    RESULTATS = []


    def check(nom, ok, detail=""):
        RESULTATS.append((nom, bool(ok), detail))
        _check_v2("v2 panneau : " + nom, ok, "" if ok else str(detail)[:400])

    class _Journal(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lignes = []

        def emit(self, r):
            self.lignes.append((r.levelname, r.name, r.getMessage()))
            TOUT_JOURNAL.append((r.levelname, r.name, r.getMessage()))


    JOURNAL = _Journal()
    TOUT_JOURNAL = []
    logging.getLogger().addHandler(JOURNAL)
    logging.getLogger().setLevel(logging.DEBUG)

    import cogs.user as U
    import cogs.welcome as W
    import cogs.menutest as MT
    import guild_features as GF

    TMP = Path(tempfile.mkdtemp(prefix="v2_panneau_"))
    U._JB_PANEL_STORE = TMP / "us_panels.json"
    U._JB_GENERAL_STORE = TMP / "us_general_panels.json"
    assert "data" not in str(U._JB_PANEL_STORE)

    IRT = discord.InteractionResponseType
    ui = discord.ui

    # ---------------------------------------------------------------------------
    # Faux objets Discord
    # ---------------------------------------------------------------------------
    _ids = iter(range(10_000, 99_999))


    def http_exc(cls=discord.HTTPException, status=400, texte="refus simule"):
        return cls(types.SimpleNamespace(status=status, reason="x"), texte)


    class Auteur:
        def __init__(self, i):
            self.id = i
            self.bot = True


    MOI = 1


    def comps_de(vue):
        if vue is None:
            return []
        return [_component_factory(d) for d in vue.to_components()]


    class Msg:
        def __init__(self, ch=None, embed=None, view=None, ephemere=False, auteur=MOI, content=None):
            self.id = next(_ids)
            self.ch = ch
            self.embeds = [embed] if embed is not None else []
            self.content = content
            self.view = view
            self.components = comps_de(view)
            self.author = Auteur(auteur)
            self.pinned = False
            v2 = bool(view is not None and view.has_components_v2())
            self.flags = types.SimpleNamespace(ephemeral=ephemere, components_v2=v2)
            self.edits = []
            self.echec_edit = None
            self.supprime = False

        async def edit(self, **k):
            self.edits.append(k)
            if self.echec_edit is not None:
                raise self.echec_edit
            if "view" in k:
                v = k["view"]
                if v is not None and v.has_components_v2():
                    # Discord refuse un V2 qui garderait texte ou embed.
                    if (self.embeds and "embed" not in k and "embeds" not in k) or \
                            (self.content and "content" not in k):
                        raise http_exc(texte="V2 avec embed/texte restant")
                    self.flags.components_v2 = True
                self.view = v
                self.components = comps_de(v)
            if "embed" in k:
                self.embeds = [k["embed"]] if k["embed"] is not None else []
            if "content" in k:
                self.content = k["content"]
            return self

        async def delete(self):
            self.supprime = True
            if self.ch is not None and self in self.ch.msgs:
                self.ch.msgs.remove(self)

        async def pin(self, **k):
            self.pinned = True


    class Salon:
        def __init__(self, cid=4242, name="zz-menu"):
            self.id = cid
            self.name = name
            self.msgs = []
            self.overwrites = {}
            self.guild = types.SimpleNamespace(id=7, emojis=[], text_channels=[self])
            self.echec_send = None

        async def pins(self):
            return [m for m in reversed(self.msgs) if m.pinned]

        async def send(self, content=None, embed=None, view=None, **k):
            if self.echec_send:
                raise self.echec_send
            m = Msg(self, embed=embed, view=view, content=content)
            self.msgs.append(m)
            return m

        async def fetch_message(self, i):
            for m in self.msgs:
                if m.id == int(i):
                    return m
            raise http_exc(discord.NotFound, 404, "absent")

        def get_partial_message(self, i):
            salon = self

            class _P:
                id = int(i)

                async def edit(self, **k):
                    return await (await salon.fetch_message(i)).edit(**k)

                async def delete(self):
                    return await (await salon.fetch_message(i)).delete()
            return _P()

        async def purge(self, limit=200, check=None):
            partis = [m for m in self.msgs if check(m)]
            self.msgs[:] = [m for m in self.msgs if not check(m)]
            return partis

        async def history(self, limit=40):
            for m in list(reversed(self.msgs))[:limit]:
                yield m


    class DeuxReponses(Exception):
        pass


    class Rep:
        def __init__(self, itx):
            self.itx = itx
            self._type = None
            self.faits = []
            self.echec_edit = None
            self.doubles = 0

        def is_done(self):
            return self._type is not None

        @property
        def type(self):
            return self._type

        def _marquer(self, t, quoi, a, k):
            if self._type is not None:
                self.doubles += 1
                raise DeuxReponses(quoi)
            self._type = t
            self.faits.append((quoi, a, k))

        async def send_message(self, *a, **k):
            self._marquer(IRT.channel_message, "send_message", a, k)

        async def edit_message(self, *a, **k):
            if self.echec_edit is not None and self._type is None:
                e, self.echec_edit = self.echec_edit, None
                raise e
            self._marquer(IRT.message_update, "edit_message", a, k)
            m = self.itx.message
            if m is not None and "view" in k:
                await m.edit(**k)

        async def defer(self, ephemeral=False, thinking=False):
            self._marquer(IRT.deferred_channel_message if thinking else IRT.deferred_message_update,
                          "defer", (), dict(ephemeral=ephemeral, thinking=thinking))

        async def send_modal(self, modal):
            self._marquer(IRT.modal, "send_modal", (modal,), {})
            self.modal = modal


    class Suivi:
        def __init__(self, itx):
            self.itx = itx
            self.envois = []
            self.edits = []

        async def send(self, content=None, **k):
            if not self.itx.response.is_done():
                raise AssertionError("followup avant toute reponse")
            self.envois.append((content, k))
            return Msg(ephemere=bool(k.get("ephemeral")))

        async def edit_message(self, mid, **k):
            if not self.itx.response.is_done():
                raise AssertionError("followup.edit avant toute reponse")
            self.edits.append((mid, k))
            m = self.itx.message
            if m is not None and m.id == mid:
                await m.edit(**k)


    class Cog:
        """Faux UserCog : les commandes enregistrent leur appel et repondent
        selon `mode` (defer | defer_eph | send_eph | rien | leve)."""

        def __init__(self):
            self.appels = []
            self.mode = "defer"

        async def _run_for_model(self, interaction, model, cmd, count=None,
                                 supports_count=False, brute_de=None):
            self.appels.append((model, getattr(cmd, "__name__", cmd), count, supports_count))
            mode = self.mode
            if mode == "defer":
                await interaction.response.defer()
                await interaction.followup.send("contenu")
            elif mode == "defer_eph":           # « Choisir ma brute » : defer(ephemeral=True)
                await interaction.response.defer(ephemeral=True)
                await interaction.followup.send("choix", ephemeral=True)
            elif mode == "thinking":
                await interaction.response.defer(thinking=True)
                await interaction.followup.send("fini")
            elif mode == "send_eph":
                await interaction.response.send_message("Aucune brute", ephemeral=True)
            elif mode == "leve":
                raise RuntimeError("panne simulee")


    for _a in U._JB_ACTIONS_US:
        _nom = _a[2]

        def _f(*a, _n=_nom, **k):
            return None
        _f.__name__ = _nom
        setattr(Cog, _nom, staticmethod(_f))
    COG = Cog()


    class Itx:
        def __init__(self, message=None, channel=None, guild=None, uid=5):
            self.message = message
            self.channel = channel
            self.guild = guild or types.SimpleNamespace(id=7, emojis=[])
            self.user = types.SimpleNamespace(id=uid, roles=[])
            self.client = types.SimpleNamespace(
                get_cog=lambda n: COG if n == "UserCog" else None,
                user=types.SimpleNamespace(id=MOI))
            self.response = Rep(self)
            self.followup = Suivi(self)
            self.orig_edits = []
            self.data = {}

        async def edit_original_response(self, **k):
            if self.response.type not in (IRT.deferred_message_update, IRT.message_update):
                raise AssertionError("@original n'est pas le message du clic")
            self.orig_edits.append(k)
            if self.message is not None:
                await self.message.edit(**k)

        async def original_response(self):
            return Msg(ephemere=True)


    def run(coro):
        return asyncio.run(coro)


    async def attendre_fond():
        for _ in range(5):
            await asyncio.sleep(0)
        if U._JB_TACHES:
            await asyncio.gather(*list(U._JB_TACHES), return_exceptions=True)


    def lancer(coro):
        async def _t():
            r = await coro
            await attendre_fond()
            return r
        return asyncio.run(_t())


    def items(vue):
        return list(vue.walk_children())


    def cids(vue):
        return [getattr(i, "custom_id", None) for i in items(vue)
                if getattr(i, "custom_id", None) and not isinstance(i, ui.DynamicItem)] + \
               [i.custom_id for i in items(vue) if isinstance(i, ui.DynamicItem)]


    def rangees(vue):
        """[[custom_id…] par ActionRow], dans l'ordre."""
        out = []
        for i in items(vue):
            if isinstance(i, ui.ActionRow):
                out.append([c.custom_id for c in i.children])
        return out


    def selects(vue):
        return [i for i in items(vue) if isinstance(i, ui.DynamicItem) and isinstance(i.item, ui.Select)]


    def limites(vue):
        pb = []
        if vue.total_children_count > 40:
            pb.append("composants %d > 40" % vue.total_children_count)
        if vue.content_length() > 4000:
            pb.append("texte %d > 4000" % vue.content_length())
        for i in items(vue):
            base = i.item if isinstance(i, ui.DynamicItem) else i
            if isinstance(i, ui.ActionRow) and len(i.children) > 5:
                pb.append("rangee a %d" % len(i.children))
            cid = getattr(base, "custom_id", None)
            if cid and len(cid) > 100:
                pb.append("custom_id %d" % len(cid))
            if isinstance(base, ui.Button) and base.label and U._long_discord(base.label) > 80:
                pb.append("libelle bouton %r" % base.label)
            if isinstance(base, ui.Select):
                if len(base.options) > 25 or not base.options:
                    pb.append("options %d" % len(base.options))
                if base.placeholder and len(base.placeholder) > 150:
                    pb.append("placeholder")
                for o in base.options:
                    if U._long_discord(o.label) > 100:
                        pb.append("option %r" % o.label)
                    if o.description and U._long_discord(o.description) > 100:
                        pb.append("description %r" % o.description)
        # Ce que discord.py envoie doit se serialiser.
        json.dumps(vue.to_components())
        return pb


    def texte(vue):
        return "\n".join(i.content for i in items(vue) if isinstance(i, ui.TextDisplay))


    GUILD_IC = types.SimpleNamespace(
        id=7, emojis=[discord.PartialEmoji(name=n, id=20000 + k)
                      for k, n in enumerate(sorted(set(U._ICONES_ACTIONS.values())))])

    VRAI = dict(can=U._jb_can_use, res=U._refus_reserve_jb, gen=U._jb_general_maj,
                us=GF.is_us_guild, marche=U.marche_du_membre)
    U._jb_can_use = lambda i: True
    U._refus_reserve_jb = lambda i: ""
    U.marche_du_membre = lambda m: "us"

    # ===========================================================================
    # 1. LA TABLE UNIQUE
    # ===========================================================================
    check("table : menus dans l'ordre Brut, Caption, Template, Trash, Flash",
          [f.cle for f in U._FAMILLES_PANNEAU] == ["brut", "caption", "template", "trash", "flash"],
          [f.cle for f in U._FAMILLES_PANNEAU])
    check("table : _FAMILLES_MENU (menu VA) inchangee",
          [f.cle for f in U._FAMILLES_MENU] == ["caption", "template", "trash", "flash"])
    check("table : Brut = brute, brutbanger, brutchoix",
          U._famille_panneau("brut").actions == ("brute", "brutbanger", "brutchoix"))
    check("table : Trash et Flash lus dans marques_montage",
          U._famille_panneau("trash").actions == tuple(U.marques_montage.marque("trash")["actions"])
          and U._famille_panneau("flash").actions == tuple(U.marques_montage.marque("flash")["actions"]))
    check("table : boutons = [qte, name, pseudo, pp, bio], [story, storycta, post]",
          U._JB_BOUTONS_V2 == (("_qte", "name", "pseudo", "pp", "bio"), ("story", "storycta", "post")))
    _disp, _hors = U._jb_disposition()
    check("table : aucune action oubliee (trend masquee expres)",
          _hors == [] and not [a[0] for a in U._JB_ACTIONS_US
                               if a[0] not in U._JB_RANGEES and a[0] not in U._JB_MASQUEES],
          (_hors, [a[0] for a in U._JB_ACTIONS_US if a[0] not in U._JB_RANGEES]))
    check("table : « trend » existe toujours mais n'est nulle part dans la disposition",
          U._jb_action("trend") is not None and all(c != "trend" for _s, c, _r in _disp)
          and not any("trend" in f.actions for f in U._FAMILLES_PANNEAU))
    check("table : chaque action a sa ligne d'explication (brut compris)",
          all(U._EXPLICATIONS.get(k) for f in U._FAMILLES_PANNEAU for k in f.actions),
          [k for f in U._FAMILLES_PANNEAU for k in f.actions if not U._EXPLICATIONS.get(k)])

    # Le filet : une action ajoutee sans place s'affiche quand meme, comptee.
    _sauve = list(U._JB_ACTIONS_US)
    try:
        U._JB_ACTIONS_US.append(("zznouvelle", "🆕 Nouvelle", "story", True))
        del JOURNAL.lignes[:]
        _d2, _h2 = U._jb_disposition()
        _v2 = U._jb_panel(None, "emma", 3)
        check("filet : une action sans place prevue s'affiche sur une rangee a elle, et c'est journalise",
              ("action", "zznouvelle", 2) in _d2 and _h2 == []
              and any("zznouvelle" in l[2] for l in JOURNAL.lignes)
              and "jbus:a:emma:zznouvelle:3" in rangees(_v2)[2], rangees(_v2)[:3])
        for n in range(6):
            U._JB_ACTIONS_US.append(("zzplus%s" % "abcdef"[n], "X", "story", True))
        _d3, _h3 = U._jb_disposition()
        _v3 = U._jb_panel(None, "emma", 3)
        check("filet : au-dela de 5, les actions sont COMPTEES et dites dans le panneau",
              len(_h3) == 2 and "2 action(s) sans place" in texte(_v3) and not limites(_v3),
              (_h3, limites(_v3)))
    finally:
        U._JB_ACTIONS_US[:] = _sauve

    # ===========================================================================
    # 2. LE PANNEAU US V2 : structure, etats, limites
    # ===========================================================================
    for _g, _nomg in ((None, "sans icones"), (GUILD_IC, "avec icones")):
        v = U._jb_panel(None, "emma", 3, "us", _g)
        check("panneau (%s) : LayoutView V2, un seul conteneur rouge fonce" % _nomg,
              isinstance(v, ui.LayoutView) and v.has_components_v2() and len(v.children) == 1
              and isinstance(v.children[0], ui.Container)
              and v.children[0].accent_colour == discord.Colour.dark_red()
              and v.timeout is None)
        check("panneau (%s) : dans les limites de Discord" % _nomg, not limites(v), limites(v))
        r = rangees(v)
        attendu = [["jbus:qb:emma:3"] + ["jbus:a:emma:%s:3" % k for k in ("name", "pseudo", "pp", "bio")],
                   ["jbus:a:emma:%s:3" % k for k in ("story", "storycta", "post")]] + \
                  [["jbus:s:emma:%s:3" % f] for f in ("brut", "caption", "template", "trash", "flash")]
        check("panneau (%s) : rangees = quantite+identite, publications, 5 menus" % _nomg,
              r == attendu, r)
        check("panneau (%s) : le texte vient en tete du conteneur" % _nomg,
              isinstance(v.children[0].children[0], ui.TextDisplay))
        t = texte(v)
        check("panneau (%s) : texte = titre, quantite, -content, marque en derniere ligne" % _nomg,
              "## 🔓 Emma — que veux-tu générer ?" in t and "Quantité : 3 média par action" in t
              and "-content" in t and t.splitlines()[-1] == "-# panneau-actions-us", t)
        check("panneau (%s) : ni « menu » ni « Jailbreak » dans le texte" % _nomg,
              "menu" not in t.lower() and "jailbreak" not in t.lower(), t)
        _js = json.dumps(v.to_components(), ensure_ascii=False)
        check("panneau (%s) : aucune trace de Trends (ni custom_id, ni libelle)" % _nomg,
              ":trend:" not in _js and "Trends" not in _js and "⭐⭐⭐" not in _js)
        sel = selects(v)
        ok_opts, det = True, []
        for s_, f in zip(sel, U._FAMILLES_PANNEAU):
            opts = s_.item.options
            if [o.value for o in opts] != list(f.actions):
                ok_opts = False
                det.append((f.cle, [o.value for o in opts]))
            if s_.item.placeholder != "%s %s…" % (f.emoji, f.nom):
                ok_opts = False
                det.append(s_.item.placeholder)
            for o in opts:
                lib = U._jb_action(o.value)[1]
                icone = U.icones_actions(_g).get(o.value)
                if icone is not None:
                    if o.emoji is None or o.emoji.name != icone.name or o.label != U._libelle_sans_emoji(lib):
                        ok_opts = False
                        det.append(("icone", o.value, o.label, o.emoji))
                else:
                    if o.emoji is not None or o.label != lib:
                        ok_opts = False
                        det.append(("sans icone", o.value, o.label, o.emoji))
                if o.description != U._EXPLICATIONS[o.value]:
                    ok_opts = False
                    det.append(("desc", o.value))
                if o.default:
                    ok_opts = False
                    det.append(("defaut", o.value))
        check("panneau (%s) : options = libelle de production, explication, icone sinon emoji du libelle" % _nomg,
              ok_opts, det)

    v_ic = U._jb_panel(None, "emma", 3, "us", GUILD_IC)
    _bt = [i for i in items(v_ic) if isinstance(i, ui.DynamicItem) and isinstance(i.item, ui.Button)]
    check("panneau : les boutons portent l'icone du serveur quand elle existe",
          all((b.item.emoji is not None) for b in _bt if b.custom_id.startswith("jbus:a:")),
          [(b.custom_id, b.item.emoji) for b in _bt])
    check("panneau : bouton Quantite au libelle de la maquette",
          _bt[0].item.label == "📦 Quantité : 3" and _bt[0].item.style == discord.ButtonStyle.secondary)
    check("panneau : le panneau compte 22 composants",
          U._jb_panel(None, "emma", 3).total_children_count == 22,
          U._jb_panel(None, "emma", 3).total_children_count)

    v0 = U._jb_panel(None, "_", 3)
    check("etat « _ » : texte d'invitation + le seul bouton Quantite, marque presente",
          rangees(v0) == [["jbus:qb:_:3"]] and "Choisis une model" in texte(v0)
          and texte(v0).splitlines()[-1] == "-# panneau-actions-us" and not limites(v0)
          and "menu" not in texte(v0).lower(), (rangees(v0), texte(v0)))
    v0b = U._jb_panel(None, None, 7)
    check("etat « _ » : ident vide -> « _ », quantite gardee", rangees(v0b) == [["jbus:qb:_:7"]])

    vL = U._jb_panel(None, "a" * 60, 100, "us", GUILD_IC)
    check("limites : identite de 60 et quantite 100 -> tout tient (custom_id <= 100)",
          not limites(vL) and len(selects(vL)) == 5, limites(vL))
    del JOURNAL.lignes[:]
    vT = U._jb_panel(None, "b" * 90, 100)
    check("limites : identite de 90 -> panneau SANS boutons qui le dit, journalise",
          not rangees(vT) and "trop long" in texte(vT) and not limites(vT)
          and texte(vT).splitlines()[-1] == "-# panneau-actions-us"
          and any("sans boutons" in l[2] for l in JOURNAL.lignes), texte(vT))
    vX = U._jb_panel(None, "chloé x", 3)
    check("limites : nom hors [a-z0-9_.-] -> panneau sans boutons qui le dit (pas d'exception)",
          not rangees(vX) and "illisible" in texte(vX))
    vQ = U._jb_panel(None, "emma", "abc")
    check("limites : quantite illisible -> 3", "jbus:qb:emma:3" in rangees(vQ)[0])

    # Menu vide (famille sans action connue) : retire ET dit.
    _fam_sauve = U._FAMILLES_PANNEAU
    try:
        U._FAMILLES_PANNEAU = _fam_sauve + (U._Famille("zzvide", "❔", "Vide", ("inexistante",)),)
        del JOURNAL.lignes[:]
        vV = U._jb_panel(None, "emma", 3)
        check("menu vide : pas pose (Discord refuserait tout), dit dans le texte, journalise",
              all("zzvide" not in c for rr in rangees(vV) for c in rr)
              and "inexistante" in texte(vV) and "menu zzvide" in texte(vV)
              and any("inexistante" in l[2] for l in JOURNAL.lignes), texte(vV))
    finally:
        U._FAMILLES_PANNEAU = _fam_sauve

    # ===========================================================================
    # 3. REPERAGE DANS LES EPINGLES : les deux formats
    # ===========================================================================
    _emb_old = discord.Embed(title="🔓 Emma — que veux-tu générer ?")
    _emb_old.set_footer(text="panneau-actions-us")
    m_old = Msg(embed=_emb_old, view=None)
    m_v2 = Msg(view=U._jb_panel(None, "emma", 3))
    m_v2_0 = Msg(view=U._jb_panel(None, "_", 3))
    _eg = discord.Embed(title="✨ General — Lola")
    _eg.set_footer(text="panneau-general-us")
    m_gen = Msg(embed=_eg)
    m_menu = Msg(embed=discord.Embed(title="Menu Jailbreak US — models US"))
    m_autre = Msg(view=U._jb_panel(None, "emma", 3), auteur=999)
    _lv = ui.LayoutView()
    _c = ui.Container()
    _c.add_item(ui.TextDisplay("## Autre chose\n-# pas-le-panneau"))
    _lv.add_item(_c)
    m_v2_autre = Msg(view=_lv)
    check("reperage : ancien panneau (pied d'embed) reconnu", U._est_panneau_actions(m_old, MOI))
    check("reperage : panneau V2 reconnu (message recu, composants Discord)",
          U._est_panneau_actions(m_v2, MOI) and U._est_panneau_actions(m_v2_0, MOI))
    check("reperage : General, menu, autre message V2, autre auteur : NON",
          not U._est_panneau_actions(m_gen, MOI) and not U._est_panneau_actions(m_menu, MOI)
          and not U._est_panneau_actions(m_v2_autre, MOI) and not U._est_panneau_actions(m_autre, MOI))
    check("reperage : General toujours reconnu par son pied (format classique inchange)",
          U._est_general(m_gen, MOI) and not U._est_general(m_v2, MOI))
    check("reperage : ne leve jamais (None, objet quelconque)",
          U._est_panneau_actions(None) is False and U._est_panneau_actions(object()) is False)
    check("conversion : kw = vider texte ET embed pour un ancien, rien pour un V2",
          U._jb_kw_format(m_old) == {"content": None, "embed": None} and U._jb_kw_format(m_v2) == {})

    # ===========================================================================
    # 4. MOTIFS DYNAMIQUES ET REDEMARRAGE
    # ===========================================================================


    class BotF:
        def __init__(self):
            self.vues, self.dyn = [], []

        def add_view(self, v, message_id=None):
            self.vues.append(v)

        def add_dynamic_items(self, *its):
            self.dyn.extend(its)


    _bot = BotF()
    del JOURNAL.lignes[:]
    run(U.UserCog.cog_load(types.SimpleNamespace(
        bot=_bot, daily_menu=types.SimpleNamespace(is_running=lambda: True))))
    check("cog_load : tout enregistre, JBMenuFamille compris, aucun echec au journal",
          U.JBMenuFamille in _bot.dyn and U.JBFamilleBouton in _bot.dyn and U.JBActionButton in _bot.dyn
          and U.JBQtySelect in _bot.dyn and U.JBQtyBouton in _bot.dyn
          and not [l for l in JOURNAL.lignes if "cog_load" in l[2]],
          [l for l in JOURNAL.lignes if "cog_load" in l[2]])
    _motifs = [(c.__name__, c.__discord_ui_compiled_template__) for c in _bot.dyn]
    _persist = {it.custom_id for v in _bot.vues for it in v.walk_children()
                if not isinstance(it, ui.DynamicItem) and getattr(it, "custom_id", None)}


    def qui(cid):
        if cid in _persist:
            return ["vue"]
        return [n for n, p in _motifs if p.fullmatch(cid)]


    _neufs = []
    for ident in ("emma", "a.b-c_d", "x" * 60, "_"):
        for q in (1, 3, 100):
            _neufs += [c for rr in rangees(U._jb_panel(None, ident, q, "us", GUILD_IC)) for c in rr]
    _mauvais = [(c, qui(c)) for c in _neufs if len(qui(c)) != 1]
    check("motifs : chaque custom_id du panneau V2 est servi par UN element exactement",
          not _mauvais and len(_neufs) > 50, _mauvais[:5])
    check("motifs : les menus « jbus:s: » vont a JBMenuFamille et a lui seul",
          all(qui(c) == ["JBMenuFamille"] for c in _neufs if c.startswith("jbus:s:")))
    _anciens = (["jbus:a:emma:%s:3" % a[0] for a in U._JB_ACTIONS_US] + ["jbus:a:emma:trend:3"]
                + ["jbus:qb:emma:3", "jbus:q:emma:3", "jbus:m:emma", "jbus:qb:_:3", "jbus:q:_:3"]
                + ["jbus:f:emma:%s:3" % f.cle for f in U._FAMILLES_MENU]
                + ["jbg:a:lola:blonde:story:3", "jbg:qb:lola:blonde:3", "jbg:r:lola:blonde:3",
                   "genlink:123"])
    _mauv2 = [(c, qui(c)) for c in _anciens if len(qui(c)) != 1]
    check("motifs : tous les ANCIENS custom_id (jbus:a/qb/q/m/f, trend, jbg:, genlink) servis par UN element",
          not _mauv2, _mauv2)
    _tS = U.JBMenuFamille.__discord_ui_compiled_template__
    check("motifs : jbus:s: ne capture aucun ancien custom_id",
          not any(_tS.fullmatch(c) for c in _anciens))


    class EtatF:
        """Etat minimal pour un vrai ViewStore de discord.py."""


    async def _redemarrage(cid, valeur, message):
        """Un clic sur un menu DEJA poste, apres un redemarrage : un ViewStore
        neuf, les motifs de cog_load, et le vrai parcours de discord.py
        (from_message -> from_custom_id -> callback)."""
        from discord.ui.view import ViewStore
        store = ViewStore(EtatF())
        store.add_dynamic_items(*_bot.dyn)
        itx = Itx(message=message, channel=message.ch)
        itx.data = {"custom_id": cid, "component_type": 3, "values": [valeur]}
        store.dispatch_view(3, cid, itx)
        await asyncio.sleep(0)
        for _ in range(20):
            await asyncio.sleep(0)
        await attendre_fond()
        return itx


    _salonR = Salon(5151)
    _vueR = U._jb_panel(None, "emma", 5, "us", GUILD_IC)
    _mR = Msg(_salonR, view=_vueR)
    _mR.pinned = True
    _salonR.msgs.append(_mR)
    U._jb_panel_set(_salonR.id, _mR.id)
    U._JB_PANNEAU_COURANT.clear()
    COG.appels.clear()
    COG.mode = "defer"
    _iR = run(_redemarrage("jbus:s:emma:trash:5", "bruttrash", _mR))
    check("redemarrage : un menu deja poste repond (ViewStore neuf, from_custom_id), l'action part",
          COG.appels == [("emma", "bruttrash", 5, True)], COG.appels)
    check("redemarrage : ... une seule reponse, et le panneau est redessine (menus sur leur intitule)",
          _iR.response.doubles == 0 and len(_iR.response.faits) == 1 and _mR.edits
          and all(not o.default for s_ in selects(_mR.edits[-1]["view"]) for o in s_.item.options),
          (_iR.response.faits, len(_mR.edits)))
    COG.appels.clear()
    _iR2 = run(_redemarrage("jbus:s:emma:trash:5", "templateflash", _mR))
    check("redemarrage : une valeur hors de la famille (forgee) est refusee, rien ne part",
          not COG.appels and _iR2.response.faits and _iR2.response.faits[0][0] == "edit_message"
          and _iR2.followup.envois and "inconnue" in str(_iR2.followup.envois[0][0]),
          (_iR2.response.faits, _iR2.followup.envois))
    COG.appels.clear()
    # Un ANCIEN panneau (vue classique) qui porte encore « ⭐⭐⭐ Trends ».
    _vA = ui.View(timeout=None)
    _vA.add_item(U.JBActionButton("emma", "trend", 5, row=1))
    _vA.add_item(U.JBFamilleBouton("emma", "caption", 5, row=2))
    _mA = Msg(_salonR, view=_vA)
    _salonR.msgs.append(_mA)


    async def _redemarrage_bouton(cid, message):
        from discord.ui.view import ViewStore
        store = ViewStore(EtatF())
        store.add_dynamic_items(*_bot.dyn)
        itx = Itx(message=message, channel=message.ch)
        itx.data = {"custom_id": cid, "component_type": 2}
        store.dispatch_view(2, cid, itx)
        for _ in range(20):
            await asyncio.sleep(0)
        await attendre_fond()
        return itx


    _iR3 = run(_redemarrage_bouton("jbus:a:emma:trend:5", _mA))
    check("redemarrage : un ancien bouton « trend » (vue classique) repond toujours",
          COG.appels == [("emma", "trends", 5, True)], COG.appels)
    _iR4 = run(_redemarrage_bouton("jbus:f:emma:caption:5", _mA))
    check("redemarrage : un ancien lanceur ▸ convertit son panneau en V2 (conversion par edition)",
          _iR4.response.faits and _iR4.response.faits[0][0] == "edit_message"
          and _mA.flags.components_v2 and U._est_panneau_actions(_mA, MOI),
          _iR4.response.faits)

    # ===========================================================================
    # 5. CLIC SUR UN MENU DU PANNEAU US (callbacks simules)
    # ===========================================================================


    def panneau_epingle(ident="emma", qty=3, cid=77):
        ch = Salon(cid)
        m = Msg(ch, view=U._jb_panel(None, ident, qty, "us", GUILD_IC))
        m.pinned = True
        ch.msgs.append(m)
        U._jb_panel_set(ch.id, m.id)
        return ch, m


    def choisir(menu, valeur, message, channel, mode="defer"):
        COG.mode = mode
        menu.item._values = [valeur]
        itx = Itx(message=message, channel=channel, guild=GUILD_IC)
        lancer(menu.callback(itx))
        menu.item._values = []
        return itx


    def remis(vue):
        return vue is not None and all(not o.default for s_ in selects(vue) for o in s_.item.options) \
            and len(selects(vue)) == 5


    U._JB_PANNEAU_COURANT.clear()
    for fam in U._FAMILLES_PANNEAU:
        for cle in fam.actions:
            ch, m = panneau_epingle()
            COG.appels.clear()
            itx = choisir(U.JBMenuFamille("emma", fam.cle, 3), cle, m, ch)
            ent = U._jb_action(cle)
            ok = (COG.appels == [("emma", ent[2], 3, bool(ent[3]))]
                  and itx.response.doubles == 0 and len(itx.response.faits) == 1
                  and len(m.edits) == 1 and remis(m.edits[0]["view"])
                  and U._JB_PANNEAU_COURANT.get(77) == ("emma", 3))
            if not ok:
                check("menu %s / %s : action lancee comme le bouton, menu remis" % (fam.cle, cle), False,
                      (COG.appels, itx.response.faits, len(m.edits)))
                break
        else:
            check("menu %s : chacune de ses %d options lance _run_for_model comme le bouton, et le menu revient"
                  % (fam.cle, len(fam.actions)), True)

    # Choisir ma brute (defer ephemere + fenetre ephemere) depuis le panneau epingle.
    ch, m = panneau_epingle()
    COG.appels.clear()
    itx = choisir(U.JBMenuFamille("emma", "brut", 3), "brutchoix", m, ch, mode="defer_eph")
    check("Choisir ma brute : une reponse (le defer de la commande), sa fenetre en suivi, le menu revient",
          COG.appels == [("emma", "choisirbrute", 3, False)] and itx.response.doubles == 0
          and itx.response.faits[0][0] == "defer" and itx.followup.envois
          and itx.followup.envois[0][1].get("ephemeral") and len(m.edits) == 1 and remis(m.edits[0]["view"]),
          (itx.response.faits, itx.followup.envois, len(m.edits)))
    # Reselectionner la meme option : elle repart.
    COG.appels.clear()
    itx2 = choisir(U.JBMenuFamille("emma", "brut", 3), "brutchoix", m, ch, mode="defer_eph")
    check("meme option choisie deux fois : deux actions", COG.appels == [("emma", "choisirbrute", 3, False)])

    # L'action ne repond pas : on repond EN redessinant.
    ch, m = panneau_epingle()
    itx = choisir(U.JBMenuFamille("emma", "caption", 3), "capbanger", m, ch, mode="rien")
    check("action muette : la reponse est l'edition du panneau (jamais « l'interaction a echoue »)",
          itx.response.faits and itx.response.faits[0][0] == "edit_message" and itx.response.doubles == 0,
          itx.response.faits)

    # L'action leve : panneau remis + erreur dite.
    ch, m = panneau_epingle()
    del JOURNAL.lignes[:]
    itx = choisir(U.JBMenuFamille("emma", "caption", 3), "capbanger", m, ch, mode="leve")
    check("action qui leve : une reponse, erreur DITE en ephemere et journalisee",
          itx.response.doubles == 0 and len(itx.response.faits) == 1
          and itx.followup.envois and "erreur" in itx.followup.envois[-1][0]
          and itx.followup.envois[-1][1].get("ephemeral")
          and any("en echec" in l[2] for l in JOURNAL.lignes),
          (itx.response.faits, itx.followup.envois))

    # Le panneau a change (autre model) pendant le rendu : pas de retour en arriere.
    ch, m = panneau_epingle()
    U._JB_PANNEAU_COURANT[77] = ("julia", 3)
    _vrai_epingle = U._jb_est_panneau_epingle
    U._jb_est_panneau_epingle = lambda i: False
    try:
        itx = choisir(U.JBMenuFamille("emma", "caption", 3), "capbanger", m, ch)
    finally:
        U._jb_est_panneau_epingle = _vrai_epingle
    check("course : panneau deja passe sur une autre model -> aucun redessin avec l'ancienne",
          not m.edits and COG.appels[-1][0] == "emma", len(m.edits))
    U._JB_PANNEAU_COURANT.clear()

    # Course AVEC le redessin de fond en panne (reproduit le 26/09/2026) : le
    # repli de remise a zero (_menu_lancer) passe APRES l'action, avec la vue
    # construite au moment du choix. Le VA ayant clique Julia pendant le rendu
    # de 30 s, il remettait le panneau sur Emma alors que _JB_PANNEAU_COURANT
    # disait Julia. Deux details comptent pour le voir :
    #   - interaction.message est une PHOTO prise au clic (Photo) : ses
    #     drapeaux et son contenu ne suivent pas le salon ;
    #   - interaction.data porte le custom_id du menu choisi, comme chez
    #     Discord -- c'est lui que le correctif cherche dans le message relu.
    class Photo:
        def __init__(self, vrai, echecs=0):
            self.vrai = vrai
            self.id = vrai.id
            self.ch = vrai.ch
            self.embeds = list(vrai.embeds)
            self.content = vrai.content
            self.components = list(vrai.components)
            self.author = vrai.author
            self.pinned = vrai.pinned
            self.flags = types.SimpleNamespace(ephemeral=vrai.flags.ephemeral,
                                               components_v2=vrai.flags.components_v2)
            #: editions refusees (500) avant de passer : le redessin de fond.
            self.echecs = echecs

        async def edit(self, **k):
            if self.echecs:
                self.echecs -= 1
                raise http_exc(status=500, texte="panne simulee")
            return await self.vrai.edit(**k)

        async def delete(self):
            return await self.vrai.delete()


    class CogCourse(Cog):
        """_run_for_model qui joue `pendant()` au milieu du « rendu », une
        fois le redessin de fond passe (et rate)."""

        def __init__(self, pendant):
            super().__init__()
            self.pendant = pendant

        async def _run_for_model(self, interaction, model, cmd, count=None, **k):
            self.appels.append((model, count))
            await interaction.response.defer()
            for _ in range(5):
                await asyncio.sleep(0)
            if self.pendant is not None:
                await self.pendant()
            await interaction.followup.send("contenu")


    def choisir_en_panne(menu, valeur, m, ch, pendant=None):
        menu.item._values = [valeur]
        itx = Itx(message=Photo(m, echecs=1), channel=ch, guild=GUILD_IC)
        itx.data = {"custom_id": menu.item.custom_id, "component_type": 3, "values": [valeur]}
        cog = CogCourse(pendant)
        itx.client = types.SimpleNamespace(get_cog=lambda n: cog if n == "UserCog" else None,
                                           user=types.SimpleNamespace(id=MOI))
        _lire = ch.fetch_message
        ch.lectures = 0

        async def _compter(i):
            ch.lectures += 1
            return await _lire(i)
        ch.fetch_message = _compter
        lancer(menu.callback(itx))
        menu.item._values = []
        return itx, cog


    ch, m = panneau_epingle(cid=70)
    U._JB_PANNEAU_COURANT[70] = ("emma", 3)


    async def _vers_julia():
        U._jb_panneau_noter(70, "julia", 3)
        await m.edit(view=U._jb_panel(None, "julia", 3, "us", GUILD_IC))
    del JOURNAL.lignes[:]
    itx, _cg = choisir_en_panne(U.JBMenuFamille("emma", "caption", 3), "capbanger", m, ch, _vers_julia)
    check("course + redessin de fond en panne : le panneau RESTE sur Julia (pas de retour a Emma), "
          "une seule reponse, rien par @original, journalise",
          _cg.appels == [("emma", 3)] and itx.message.echecs == 0
          and texte(m.view).startswith("## 🔓 Julia") and not itx.orig_edits
          and len(itx.response.faits) == 1 and itx.response.doubles == 0
          and any("deja redessine" in l[2] for l in JOURNAL.lignes),
          (texte(m.view).splitlines()[:1], itx.orig_edits, itx.response.faits))
    # Meme panne, la QUANTITE changee pendant le rendu (3 -> 7) : elle reste a 7.
    ch, m = panneau_epingle(cid=71)
    U._JB_PANNEAU_COURANT[71] = ("emma", 3)


    async def _vers_7():
        U._jb_panneau_noter(71, "emma", 7)
        await m.edit(view=U._jb_panel(None, "emma", 7, "us", GUILD_IC))
    itx, _cg = choisir_en_panne(U.JBMenuFamille("emma", "flash", 3),
                                U._famille_panneau("flash").actions[0], m, ch, _vers_7)
    _ids7 = [c for r_ in rangees(m.view) for c in r_]
    check("course sur la quantite + redessin de fond en panne : le panneau reste a 7",
          "jbus:qb:emma:7" in _ids7 and "jbus:s:emma:flash:7" in _ids7 and not itx.orig_edits,
          _ids7[:2])
    # Meme panne, SANS course : le repli remet bien le panneau (le cas courant).
    ch, m = panneau_epingle(cid=72)
    U._JB_PANNEAU_COURANT[72] = ("emma", 3)
    itx, _cg = choisir_en_panne(U.JBMenuFamille("emma", "caption", 3), "capbanger", m, ch)
    check("redessin de fond en panne, sans course : panneau remis par @original (1 relecture, "
          "1 reponse), menus sur leur intitule",
          len(itx.orig_edits) == 1 and remis(itx.orig_edits[0]["view"]) and ch.lectures == 1
          and len(itx.response.faits) == 1 and itx.response.doubles == 0,
          (itx.orig_edits, ch.lectures, itx.response.faits))
    # Relecture impossible (Discord en panne) : on ne remet pas, a l'aveugle.
    ch, m = panneau_epingle(cid=73)
    U._JB_PANNEAU_COURANT[73] = ("emma", 3)


    async def _lecture_en_panne(i):
        raise http_exc(status=503, texte="panne lecture")
    ch.fetch_message = _lecture_en_panne
    del JOURNAL.lignes[:]
    itx, _cg = choisir_en_panne(U.JBMenuFamille("emma", "caption", 3), "capbanger", m, ch)
    check("relecture en panne : pas de remise a l'aveugle, journalise, une seule reponse",
          not itx.orig_edits and len(itx.response.faits) == 1 and itx.response.doubles == 0
          and any("illisible" in l[2] and "non remis" in l[2] for l in JOURNAL.lignes),
          (itx.orig_edits, itx.response.faits))
    U._JB_PANNEAU_COURANT.clear()

    # Panneau EPHEMERE (secours) : redessin apres coup par l'interaction.
    eph = Msg(view=U._vue_sans_suivi(U._jb_panel(None, "emma", 3)), ephemere=True)
    for mode, attendu in (("defer", "orig"), ("send_eph", "followup"), ("rien", "reponse"),
                          ("thinking", "followup")):
        eph.edits.clear()
        itx = choisir(U.JBMenuFamille("emma", "template", 3), "reelmonte", eph, Salon(78), mode=mode)
        chemin = ("orig" if itx.orig_edits else "followup" if itx.followup.edits
                  else "reponse" if itx.response.faits and itx.response.faits[0][0] == "edit_message" else "?")
        v_ = eph.edits[-1].get("view") if eph.edits else None
        check("ephemere (%s) : menu remis par %s, une seule reponse, vue arretee" % (mode, attendu),
              chemin == attendu and itx.response.doubles == 0 and remis(v_) and v_.is_finished(),
              (chemin, itx.response.faits, len(eph.edits)))

    # Refus : role, reserve, famille inconnue, model « _ », perime, action absente du cog.
    U._JB_PANNEAU_COURANT.clear()
    ch, m = panneau_epingle()


    def refus_avec(nom, preparer, menu, valeur, attendu, message=None, restaurer=None):
        COG.appels.clear()
        preparer()
        try:
            itx = choisir(menu, valeur, message or m, ch)
        finally:
            if restaurer:
                restaurer()
        rep = itx.response.faits
        _vr = rep[0][2]["view"] if rep else None
        # Un menu « _ » ne peut venir que d'un custom_id forge : le panneau
        # redessine est alors celui de l'etat « _ » (sans menus).
        _ok_vue = remis(_vr) if menu.ident != "_" else (_vr is not None and rangees(_vr) == [["jbus:qb:_:3"]])
        check("refus %s : rien ne part, le menu revient, le VA lit pourquoi" % nom,
              not COG.appels and rep and rep[0][0] == "edit_message" and _ok_vue
              and itx.followup.envois and attendu in str(itx.followup.envois[0][0])
              and itx.followup.envois[0][1].get("ephemeral") and itx.response.doubles == 0,
              (COG.appels, rep[:1], itx.followup.envois))


    refus_avec("role", lambda: setattr(U, "_jb_can_use", lambda i: False),
               U.JBMenuFamille("emma", "caption", 3), "capbanger", "Réservé",
               restaurer=lambda: setattr(U, "_jb_can_use", lambda i: True))
    refus_avec("reserve", lambda: setattr(U, "_refus_reserve_jb", lambda i: "⛔ reserve"),
               U.JBMenuFamille("emma", "caption", 3), "capbanger", "⛔ reserve",
               restaurer=lambda: setattr(U, "_refus_reserve_jb", lambda i: ""))
    refus_avec("valeur hors liste blanche", lambda: None,
               U.JBMenuFamille("emma", "caption", 3), "templateflash", "inconnue")
    refus_avec("famille inconnue", lambda: None,
               U.JBMenuFamille("emma", "zzz", 3), "capbanger", "indisponible")
    refus_avec("model « _ »", lambda: None,
               U.JBMenuFamille("_", "caption", 3), "capbanger", "indisponible")
    _attr = U._jb_action("capbanger")[2]
    _sauv_attr = Cog.__dict__.get(_attr)
    refus_avec("action absente du cog", lambda: delattr(Cog, _attr),
               U.JBMenuFamille("emma", "caption", 3), "capbanger", "indisponible",
               restaurer=lambda: setattr(Cog, _attr, _sauv_attr))
    eph2 = Msg(view=U._vue_sans_suivi(U._jb_panel(None, "lola", 3)), ephemere=True)
    refus_avec("panneau ephemere perime (le salon montre Julia)",
               lambda: U._JB_PANNEAU_COURANT.__setitem__(77, ("julia", 3)),
               U.JBMenuFamille("lola", "caption", 3), "capbanger", "Julia", message=eph2,
               restaurer=lambda: U._JB_PANNEAU_COURANT.clear())
    U._JB_PANNEAU_COURANT[77] = ("julia", 3)
    _msgP = U._jb_sous_menu_perime(types.SimpleNamespace(message=eph2, channel=types.SimpleNamespace(id=77)),
                                   "lola", 3, panneau=True)
    _msgS = U._jb_sous_menu_perime(types.SimpleNamespace(message=eph2, channel=types.SimpleNamespace(id=77)),
                                   "lola", 3)
    U._JB_PANNEAU_COURANT.clear()
    check("perime : panneau de secours -> renvoie au panneau epingle ; ancien sous-menu -> phrase d'avant",
          "panneau épinglé" in _msgP and "▸" not in _msgP
          and _msgS == ("⚠️ Ce sous-menu est pour **Lola**, ton panneau est passé sur **Julia** : "
                        "reclique ▸ sur le panneau pour avoir les bons boutons."), (_msgP, _msgS))

    # ===========================================================================
    # 6. CLIC SUR UNE MODEL (JBModelButton, serveur US) : conversion et repli
    # ===========================================================================
    GF.is_us_guild = lambda g: True
    _gen_appels = []


    async def _gen_f(client, chan, model, guild, reposter=False):
        _gen_appels.append((model, reposter))
        return True
    U._jb_general_maj = _gen_f


    def clic_model(ch, ident="julia"):
        itx = Itx(message=Msg(), channel=ch, guild=GUILD_IC)
        lancer(U.JBModelButton(ident).callback(itx))
        return itx


    # a) ancien panneau epingle (embed) : converti PAR EDITION.
    ch = Salon(81)
    _e = discord.Embed(title="🔓 Emma — que veux-tu générer ?")
    _e.set_footer(text="panneau-actions-us")
    old = Msg(ch, embed=_e, view=None)
    old.pinned = True
    ch.msgs.append(old)
    U._jb_panel_set(ch.id, old.id)
    _gen_appels.clear()
    itx = clic_model(ch)
    k = old.edits[-1] if old.edits else {}
    check("model : ancien panneau converti par EDITION (content=None, embed=None, vue V2)",
          k.get("content", "x") is None and k.get("embed", "x") is None
          and isinstance(k.get("view"), ui.LayoutView) and old.flags.components_v2 and not old.embeds
          and U._est_panneau_actions(old, MOI) and len(ch.msgs) == 1, k)
    check("model : ... une reponse (defer), General mis a jour sans repost",
          itx.response.faits == [("defer", (), {"ephemeral": False, "thinking": False})]
          and _gen_appels == [("julia", False)], (itx.response.faits, _gen_appels))
    # b) panneau deja V2 : edition de la vue seule.
    old.edits.clear()
    itx = clic_model(ch, "lola")
    check("model : panneau V2 -> edition de la vue SEULE (rien a vider)",
          list(old.edits[-1].keys()) == ["view"] and "Lola" in texte(old.edits[-1]["view"]))
    # c) conversion refusee : nouveau panneau V2, epingle, l'ancien retire, id memorise, journalise.
    ch = Salon(82)
    old = Msg(ch, embed=_e, view=None)
    old.pinned = True
    old.echec_edit = http_exc(texte="Cannot convert")
    ch.msgs.append(old)
    U._jb_panel_set(ch.id, old.id)
    _gen_appels.clear()
    del JOURNAL.lignes[:]
    itx = clic_model(ch)
    nouv = [x for x in ch.msgs if x is not old]
    check("model : conversion refusee -> nouveau panneau V2 epingle, ancien retire, id memorise",
          old.supprime and len(nouv) == 1 and nouv[0].pinned and U._est_panneau_actions(nouv[0], MOI)
          and U._jb_panel_ids().get(str(ch.id)) == nouv[0].id and not nouv[0].embeds,
          (old.supprime, len(nouv)))
    check("model : ... journalise, une reponse, General REPOSTE sous le nouveau panneau",
          any("edition refusee" in l[2] for l in JOURNAL.lignes) and itx.response.doubles == 0
          and _gen_appels == [("julia", True)], (_gen_appels, itx.response.faits))
    # d) aucun panneau : pose.
    ch = Salon(83)
    _gen_appels.clear()
    itx = clic_model(ch)
    check("model : pas de panneau -> un panneau V2 pose et epingle, General reposte",
          len(ch.msgs) == 1 and ch.msgs[0].pinned and U._est_panneau_actions(ch.msgs[0], MOI)
          and _gen_appels == [("julia", True)])
    # e) id non memorise : retrouve dans les epingles, sous ses deux formats.
    for fmt in ("ancien", "v2"):
        ch = Salon(84 if fmt == "ancien" else 85)
        pm = Msg(ch, embed=_e) if fmt == "ancien" else Msg(ch, view=U._jb_panel(None, "emma", 3))
        pm.pinned = True
        ch.msgs.append(pm)
        itx = clic_model(ch)
        check("model : panneau %s retrouve dans les epingles (pas de doublon)" % fmt,
              len(ch.msgs) == 1 and pm.edits and U._jb_panel_ids().get(str(ch.id)) in (None, pm.id)
              and "Julia" in texte(pm.edits[-1]["view"]))
    # f) tout echoue : ephemere, vue ARRETEE.
    ch = Salon(86)
    ch.echec_send = http_exc(discord.Forbidden, 403, "pas le droit")
    _gen_appels.clear()
    itx = clic_model(ch)
    f = itx.response.faits
    check("model : salon inutilisable -> panneau en ephemere, vue arretee, General non touche",
          f and f[0][0] == "send_message" and f[0][2].get("ephemeral")
          and isinstance(f[0][2].get("view"), ui.LayoutView) and f[0][2]["view"].is_finished()
          and "embed" not in f[0][2] and not _gen_appels, f)

    # ===========================================================================
    # 7. QUANTITE, ANCIEN MENU DE QUANTITE, LANCEURS « ▸ » : conversion
    # ===========================================================================


    async def soumettre(itx_clic, q, message):
        modal = itx_clic.response.modal
        itx_m = Itx(message=message, channel=message.ch, guild=GUILD_IC)
        modal.nombre._value = str(q)
        await modal.on_submit(itx_m)
        await attendre_fond()
        return itx_m


    for fmt in ("ancien", "v2"):
        ch = Salon(91)
        pm = Msg(ch, embed=_e) if fmt == "ancien" else Msg(ch, view=U._jb_panel(None, "emma", 3))
        pm.pinned = True
        ch.msgs.append(pm)
        U._jb_panel_set(ch.id, pm.id)
        itx = Itx(message=pm, channel=ch, guild=GUILD_IC)
        run(U.JBQtyBouton("emma", 3).callback(itx))
        itm = run(soumettre(itx, 7, pm))
        k = itm.response.faits[0][2] if itm.response.faits else {}
        check("quantite (%s) : la fenetre, puis le panneau V2 a 7 par edition%s" % (
            fmt, " (conversion)" if fmt == "ancien" else ""),
              itx.response.faits[0][0] == "send_modal" and itm.response.faits[0][0] == "edit_message"
              and ("jbus:qb:emma:7" in rangees(k["view"])[0])
              and ((k.get("content", "x") is None and k.get("embed", "x") is None) if fmt == "ancien"
                   else set(k) == {"view"}) and U._JB_PANNEAU_COURANT.get(91) == ("emma", 7),
              (itm.response.faits, U._JB_PANNEAU_COURANT.get(91)))
    # Edition refusee depuis la fenetre : repost.
    ch = Salon(92)
    pm = Msg(ch, embed=_e)
    pm.pinned = True
    ch.msgs.append(pm)
    U._jb_panel_set(ch.id, pm.id)
    itx = Itx(message=pm, channel=ch, guild=GUILD_IC)
    run(U.JBQtyBouton("emma", 3).callback(itx))
    modal = itx.response.modal
    itm = Itx(message=pm, channel=ch, guild=GUILD_IC)
    itm.response.echec_edit = http_exc(texte="refus conversion")
    modal.nombre._value = "4"
    _gen_appels.clear()
    lancer(modal.on_submit(itm))
    nouv = [x for x in ch.msgs if x is not pm]
    check("quantite : conversion refusee -> defer, nouveau panneau V2 (4), ancien retire, General reposte",
          itm.response.faits and itm.response.faits[0][0] == "defer" and pm.supprime and len(nouv) == 1
          and "jbus:qb:emma:4" in rangees(nouv[0].view)[0] and nouv[0].pinned
          and U._jb_panel_ids().get("92") == nouv[0].id and _gen_appels == [("emma", True)],
          (itm.response.faits, pm.supprime, len(nouv), _gen_appels))
    # Ancien panneau ephemere : refus -> un nouvel ephemere.
    ephA = Msg(embed=_e, ephemere=True)
    itx = Itx(message=ephA, channel=Salon(93), guild=GUILD_IC)
    itx.response.echec_edit = http_exc(texte="refus")
    lancer(U.JBFamilleBouton("emma", "trash", 5).callback(itx))
    f = itx.response.faits
    check("ancien ephemere : edition refusee -> NOUVEL ephemere V2 (vue arretee)",
          f and f[0][0] == "send_message" and f[0][2].get("ephemeral")
          and f[0][2]["view"].is_finished() and "jbus:s:emma:trash:5" in [c for rr in rangees(f[0][2]["view"]) for c in rr],
          f)

    # Ancien menu de quantite (jbus:q:)
    ch = Salon(94)
    pm = Msg(ch, embed=_e)
    pm.pinned = True
    ch.msgs.append(pm)
    sel = U.JBQtySelect("emma", 3)
    sel.item._values = ["10"]
    itx = Itx(message=pm, channel=ch, guild=GUILD_IC)
    lancer(sel.callback(itx))
    check("ancien menu de quantite (jbus:q:) : repond et convertit le panneau (10)",
          itx.response.faits[0][0] == "edit_message" and pm.flags.components_v2
          and "jbus:qb:emma:10" in rangees(pm.view)[0])
    sel.item._values = [U._JB_QTY_AUTRE]
    itx = Itx(message=pm, channel=ch, guild=GUILD_IC)
    run(sel.callback(itx))
    itm = run(soumettre(itx, 12, pm))
    check("ancien menu de quantite « Autre » : fenetre puis panneau V2 a 12",
          itx.response.faits[0][0] == "send_modal" and "jbus:qb:emma:12" in rangees(pm.view)[0])

    # Anciens lanceurs « ▸ » (dc157c3) : plus de sous-menu, le panneau devient V2.
    ch = Salon(95)
    pm = Msg(ch, embed=_e)
    pm.pinned = True
    ch.msgs.append(pm)
    U._jb_panel_set(ch.id, pm.id)
    U._JB_PANNEAU_COURANT.clear()
    itx = Itx(message=pm, channel=ch, guild=GUILD_IC)
    lancer(U.JBFamilleBouton("emma", "caption", 5).callback(itx))
    f = itx.response.faits
    check("ancien lanceur ▸ : le panneau est RECONSTRUIT en V2 sur place, pas de sous-menu ephemere",
          f and f[0][0] == "edit_message" and not f[0][2].get("ephemeral")
          and f[0][2].get("content", "x") is None and pm.flags.components_v2
          and "jbus:s:emma:caption:5" in [c for rr in rangees(pm.view) for c in rr]
          and not itx.followup.envois and U._JB_PANNEAU_COURANT.get(95) == ("emma", 5), f)
    for nom_r, prep, rest, att in (
            ("role", lambda: setattr(U, "_jb_can_use", lambda i: False),
             lambda: setattr(U, "_jb_can_use", lambda i: True), "Réservé"),
            ("reserve", lambda: setattr(U, "_refus_reserve_jb", lambda i: "⛔ res"),
             lambda: setattr(U, "_refus_reserve_jb", lambda i: ""), "⛔ res")):
        prep()
        try:
            itx = Itx(message=pm, channel=ch)
            lancer(U.JBFamilleBouton("emma", "caption", 5).callback(itx))
        finally:
            rest()
        check("ancien lanceur ▸ : garde « %s »" % nom_r,
              itx.response.faits and itx.response.faits[0][0] == "send_message"
              and att in str(itx.response.faits[0][1]))
    itx = Itx(message=pm, channel=ch)
    lancer(U.JBFamilleBouton("emma", "inconnue", 5).callback(itx))
    check("ancien lanceur ▸ : famille inconnue refusee en le disant",
          "inconnue" in str(itx.response.faits[0][1]) and itx.response.faits[0][2].get("ephemeral"))

    # Anciens boutons d'action (jbus:a:, trend compris) : toujours servis.
    COG.appels.clear()
    COG.mode = "defer"
    for cle in ("trend", "templateflash", "templatetrash", "brutchoix", "reelcaption"):
        itx = Itx(message=pm, channel=ch)
        lancer(U.JBActionButton("emma", cle, 3).callback(itx))
    check("anciens boutons jbus:a: (trend, flash, trash, choisir ma brute, caption) : servis",
          [a[1] for a in COG.appels] == ["trends", "templateflash", "templatetrash", "choisirbrute",
                                          "reelcaption"], COG.appels)

    # ===========================================================================
    # 8. WELCOME : _ensure_us_menu, _ensure_us_panel, reset_us_menu
    # ===========================================================================
    U._jb_general_maj = VRAI["gen"]


    class UCogW:
        def jailbreak_us_menu(self, marche):
            return discord.Embed(title="🔓 Menu Jailbreak US"), None

        async def jailbreak_us_menu_async(self, guild, marche):
            return self.jailbreak_us_menu(marche)


    _botW = types.SimpleNamespace(user=Auteur(MOI), get_cog=lambda n: UCogW() if n == "UserCog" else None)
    _vrai_gen = U._jb_general


    # Depuis le 26/09/2026 (partie E), _jb_general rend lui aussi une
    # LayoutView V2 -- plus de couple (embed, vue) -- reconnue a la derniere
    # ligne de son texte. Ce bouchon suit ce contrat (sans lui, welcome ne
    # posait plus de General ici) ; le vrai General est eprouve dans la
    # partie E (_v2_bloc_general).
    def _gen_simple(cog, model, qty=3, reserve=None, guild=None):
        v = ui.LayoutView(timeout=None)
        c = ui.Container()
        c.add_item(ui.TextDisplay("## ✨ General — %s\n-# panneau-general-us" % model))
        v.add_item(c)
        return v
    U._jb_general = _gen_simple


    def ordre(ch):
        out = ""
        for x in ch.msgs:
            if U._est_panneau_actions(x, MOI):
                out += "P" if x.flags.components_v2 else "p"
            elif U._est_general(x, MOI):
                # Le General, dans l'un ou l'autre format : c'est la fonction
                # du bot qui le dit, comme dans les epingles.
                out += "G"
            elif x.embeds and "Jailbreak" in (x.embeds[0].title or ""):
                out += "M"
            else:
                out += "?"
        return out


    chW = Salon(4343)
    etat = {}
    ok = run(W.reset_us_menu(_botW, chW, etat=etat))
    check("reset_us_menu : menu, panneau V2, General, dans cet ordre",
          ok and ordre(chW) == "MPG" and etat.get("general") is True
          and not chW.msgs[1].embeds and chW.msgs[1].pinned, (ordre(chW), etat))
    # Relance : rien ne se double (le panneau V2 est reconnu).
    etat = {}
    ok = run(W._ensure_us_menu(_botW, chW, etat=etat))
    check("_ensure_us_menu : panneau V2 reconnu, rien de pose en double, General garde",
          ok and ordre(chW) == "MPG" and etat.get("general") is True, (ordre(chW), etat))
    ok = run(W._ensure_us_panel(_botW, chW))
    check("_ensure_us_panel : panneau V2 reconnu, pas de second panneau",
          ok and ordre(chW) == "MPG" and U._jb_panel_ids().get(str(chW.id)) == chW.msgs[1].id)
    # Ancien panneau (embed) : reconnu aussi.
    chA = Salon(4344)
    mA = Msg(chA, embed=discord.Embed(title="🔓 Menu Jailbreak US"))
    mA.pinned = True
    pA = Msg(chA, embed=_e)
    pA.pinned = True
    chA.msgs += [mA, pA]
    etat = {}
    ok = run(W._ensure_us_menu(_botW, chA, etat=etat))
    check("_ensure_us_menu : ANCIEN panneau reconnu, General pose dessous, rien d'autre",
          ok and ordre(chA) == "MpG" and etat.get("general") is True, (ordre(chA), etat))
    ok = run(W._ensure_us_panel(_botW, chA))
    check("_ensure_us_panel : ancien panneau reconnu (pas de doublon avant sa conversion)",
          ok and ordre(chA) == "MpG")
    # Ordre inverse (panneau V2 plus ancien que le menu) : on repart de zero.
    chI = Salon(4345)
    pI = Msg(chI, view=U._jb_panel(None, "emma", 3))
    pI.pinned = True
    mI = Msg(chI, embed=discord.Embed(title="🔓 Menu Jailbreak US"))
    mI.pinned = True
    chI.msgs += [pI, mI]
    ok = run(W._ensure_us_menu(_botW, chI))
    check("_ensure_us_menu : panneau V2 AU-DESSUS du menu -> retire et repose dans l'ordre",
          ok and pI.supprime and ordre(chI) in ("MPG",), ordre(chI))
    # Menu absent, panneau V2 present : le panneau est refait apres le menu.
    chJ = Salon(4346)
    pJ = Msg(chJ, view=U._jb_panel(None, "emma", 3))
    pJ.pinned = True
    chJ.msgs.append(pJ)
    ok = run(W._ensure_us_menu(_botW, chJ))
    check("_ensure_us_menu : menu absent -> le panneau V2 (reconnu) est refait sous le menu",
          ok and pJ.supprime and ordre(chJ) == "MPG", ordre(chJ))
    U._jb_general = _vrai_gen

    # _delete_old_menus (salons VA) : ne touche jamais au panneau ni au General.
    chD = Salon(4400, "va-test")
    pD = Msg(chD, view=U._jb_panel(None, "_", 3))     # texte : « … la grille … », pas de « menu »
    gD = Msg(chD, embed=_eg)
    mD = Msg(chD, embed=discord.Embed(title="☀️ Ton menu"))
    _lv2 = ui.LayoutView()
    _c2 = ui.Container()
    _c2.add_item(ui.TextDisplay("Le menu du jour\n-# panneau-actions-us"))
    _lv2.add_item(_c2)
    pD2 = Msg(chD, view=_lv2)                          # V2 marque, texte avec « menu »
    chD.msgs += [pD, gD, mD, pD2]
    _cogD = types.SimpleNamespace(bot=types.SimpleNamespace(user=Auteur(MOI)))
    run(U.UserCog._delete_old_menus(_cogD, chD))
    check("_delete_old_menus : le vieux menu part, panneau V2 et General restent",
          mD.supprime and not pD.supprime and not gD.supprime and not pD2.supprime)

    # ===========================================================================
    # 9. PANNEAU EPHEMERE NON-US (JailbreakActionsView)
    # ===========================================================================
    pbB = []
    for ic in ({}, U.icones_actions(GUILD_IC)):
        try:
            vB = U.JailbreakActionsView(COG, "emma", 3, us=True, icones=ic)
            if limites(vB):
                pbB.append(limites(vB))
        except Exception as e:
            pbB.append(repr(e))
    check("B : se construit (avec et sans icones), dans les limites", not pbB, pbB)
    vB = U.JailbreakActionsView(COG, "emma", 3, us=True)
    rB = []
    for i in items(vB):
        if isinstance(i, ui.ActionRow):
            rB.append([type(c).__name__ + ":" + (getattr(c, "key", "") or getattr(c, "famille", "") or "")
                       for c in i.children])
    check("B : meme disposition (quantite en menu a part, 4 + 3 boutons, 5 menus)",
          rB == [["_JailbreakQtySelect:"],
                 ["_JailbreakActionButton:name", "_JailbreakActionButton:pseudo",
                  "_JailbreakActionButton:pp", "_JailbreakActionButton:bio"],
                 ["_JailbreakActionButton:story", "_JailbreakActionButton:storycta",
                  "_JailbreakActionButton:post"]]
          + [["_JailbreakFamilleSelect:%s" % f.cle] for f in U._FAMILLES_PANNEAU], rB)
    check("B : texte + V2, timeout 180, aucun element dynamique (il expire)",
          "Emma — que veux-tu générer" in texte(vB) and vB.has_components_v2() and vB.timeout == 180
          and not [i for i in items(vB) if isinstance(i, ui.DynamicItem)])
    check("B : les options suivent la meme table (libelles, explications)",
          [[o.value for o in s_.options] for s_ in items(vB) if isinstance(s_, U._JailbreakFamilleSelect)]
          == [list(f.actions) for f in U._FAMILLES_PANNEAU])


    class MsgHandle:
        def __init__(self):
            self.edits = []
            self.echec = None

        async def edit(self, **k):
            if self.echec:
                raise self.echec
            self.edits.append(k)


    def choisir_B(vue, famille, valeur, mode="defer"):
        s_ = [x for x in items(vue) if isinstance(x, U._JailbreakFamilleSelect) and x.famille == famille][0]
        s_._values = [valeur]
        COG.mode = mode
        itx = Itx(message=Msg(ephemere=True), channel=Salon(96))
        lancer(s_.callback(itx))
        return itx


    vB = U.JailbreakActionsView(COG, "emma", 4, us=True)
    vB.message = MsgHandle()
    COG.appels.clear()
    itx = choisir_B(vB, "trash", "templatetrashbanger")
    check("B : un choix lance l'action (model, quantite du panneau)",
          COG.appels == [("emma", "templatetrashbanger", 4, True)], COG.appels)
    check("B : ... le menu revient tout de suite (jeton du panneau), une seule reponse",
          len(vB.message.edits) == 1 and itx.response.doubles == 0 and len(itx.response.faits) == 1
          and all(not getattr(s_, "values", None) for s_ in items(vB) if isinstance(s_, ui.Select)
                  and not isinstance(s_, U._JailbreakQtySelect)),
          (len(vB.message.edits), itx.response.faits))
    # Jeton perime : redessin par l'interaction du choix.
    vB.message.echec = http_exc(texte="token expire")
    itx = choisir_B(vB, "brut", "brute")
    check("B : jeton du panneau perime -> redessin par l'interaction (@original apres defer)",
          itx.orig_edits and itx.response.doubles == 0, (itx.orig_edits, itx.response.faits))
    vB.message = None
    itx = choisir_B(vB, "caption", "reelcaption", mode="send_eph")
    check("B : sans handle, action repondue par un message -> redessin par followup.edit_message",
          itx.followup.edits and itx.response.doubles == 0, itx.followup.edits)
    _sav = U._jb_can_use
    U._jb_can_use = lambda i: False
    try:
        COG.appels.clear()
        itx = choisir_B(vB, "caption", "reelcaption")
    finally:
        U._jb_can_use = _sav
    check("B : role refuse -> rien ne part, menu remis, raison dite",
          not COG.appels and itx.response.faits[0][0] == "edit_message"
          and "Réservé" in str(itx.followup.envois[0][0]))
    COG.appels.clear()
    itx = choisir_B(vB, "caption", "templateflash")
    check("B : valeur hors de la famille refusee", not COG.appels and "inconnue" in str(itx.followup.envois))
    # Quantite (menu)
    qs = [x for x in items(vB) if isinstance(x, U._JailbreakQtySelect)][0]
    qs._values = ["10"]
    itx = Itx(message=Msg(ephemere=True))
    run(qs.callback(itx))
    check("B : la quantite (menu) reconstruit le panneau a 10",
          vB.quantity == 10 and itx.response.faits[0][0] == "edit_message"
          and "Quantité : 10" in texte(vB))
    # Expiration
    vB.message = MsgHandle()
    run(vB.on_timeout())
    check("B : a l'expiration, le panneau s'eteint (texte seul, aucun bouton, pas d'embed)",
          vB.message.edits and "expiré" in texte(vB) and not [i for i in items(vB) if isinstance(i, (ui.Button, ui.Select))]
          and set(vB.message.edits[-1]) == {"view"})
    # Pose : _poser_panneau_jb envoie la vue, sans embed.
    vB2 = U.JailbreakActionsView(COG, "emma", 3, us=True)
    itx = Itx(message=None)
    run(U._poser_panneau_jb(itx, vB2))
    f = itx.response.faits
    check("B : _poser_panneau_jb envoie la LayoutView en ephemere, sans embed",
          f[0][0] == "send_message" and f[0][2].get("view") is vB2 and f[0][2].get("ephemeral")
          and "embed" not in f[0][2], f)

    # ===========================================================================
    # 10. LA MAQUETTE LIT LA MEME TABLE
    # ===========================================================================
    dm = MT.DemoPanneauDirect("emma")
    _ph = [i.placeholder for i in dm.walk_children() if isinstance(i, ui.Select)]
    _lb = [i.label for i in dm.walk_children() if isinstance(i, ui.Button)]
    check("maquette : memes menus que le vrai panneau, dans le meme ordre",
          _ph == [U._jb_placeholder_famille(f) for f in U._FAMILLES_PANNEAU], _ph)
    check("maquette : memes boutons (sans Trends)",
          _lb == ["📦 Quantité : 3"] + [U._jb_action(k)[1] for rr in U._JB_BOUTONS_V2 for k in rr if k != "_qte"],
          _lb)
    _opts_d = [[o.description for o in i.options] for i in dm.walk_children() if isinstance(i, ui.Select)]
    check("maquette : explications de Brut lues dans _EXPLICATIONS",
          _opts_d[0] == [U._EXPLICATIONS[k] for k in ("brute", "brutbanger", "brutchoix")])

    import shutil
    shutil.rmtree(TMP, ignore_errors=True)


def _v2_bloc_menu_va():
    'Partie C : le menu VA des salons va- (vue V2 persistante).'
    import asyncio
    import json
    import logging
    import os
    import re
    import sys
    import tempfile
    import types
    from pathlib import Path
    import discord
    from discord.components import _component_factory

    RESULTATS = []


    def check(nom, ok, detail=""):
        RESULTATS.append((nom, bool(ok), detail))
        _check_v2("v2 menu VA : " + nom, ok, "" if ok else str(detail)[:400])

    class _Journal(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lignes = []

        def emit(self, r):
            self.lignes.append((r.levelname, r.name, r.getMessage()))
            TOUT_JOURNAL.append((r.levelname, r.name, r.getMessage()))


    JOURNAL = _Journal()
    TOUT_JOURNAL = []
    logging.getLogger().addHandler(JOURNAL)
    logging.getLogger().setLevel(logging.DEBUG)

    import cogs.user as U
    import guild_features as GF
    import marques_montage as MM

    TMP = Path(tempfile.mkdtemp(prefix="v2_menu_va_"))
    U._JB_PANEL_STORE = TMP / "us_panels.json"
    U._JB_GENERAL_STORE = TMP / "us_general_panels.json"
    U.USERS_FILE = TMP / "users.json"
    assert "data" not in str(U.USERS_FILE)

    # L'ANCIEN menu VA (dc157c3 -> 25/09/2026), tel qu'il est encore epingle
    # dans les salons va- : une vue CLASSIQUE (embed a cote), 17 boutons et 4
    # lanceurs « ▸ ». Releve sur le code d'avant le passage au V2 : custom_id,
    # libelle, emoji, style, rangee. Les boutons du menu V2 doivent garder les
    # memes, sinon les menus deja epingles cessent de repondre ou changent de
    # tete sous les yeux du VA.
    _ANCIEN_MENU_VA = (
        ("cmenu:reel", "Reel", "🎬", "primary", 0),
        ("cmenu:banger", "⭐ Reels", None, "primary", 0),
        ("cmenu:story", "Story", "📖", "primary", 0),
        ("cmenu:storycta", "Story CTA", "📲", "primary", 0),
        ("cmenu:post", "Post", "🖼️", "primary", 0),
        ("cmenu:name", "Name", "📝", "secondary", 1),
        ("cmenu:pseudo", "Pseudo", "👤", "secondary", 1),
        ("cmenu:pp", "PP", "🖼", "secondary", 1),
        ("cmenu:bio", "Bio", "💬", "secondary", 1),
        ("cmenu:brutbanger", "⭐ Vidéo brut", None, "primary", 1),
        ("cmenu:clics", "Mes clics", "📊", "success", 3),
        ("cmenu:help", "Assistance", "🆘", "danger", 3),
        ("cmenu:lien", "Demander un lien", "🔗", "success", 3),
        ("cmenu:pay", "Mon paiement", "💸", "secondary", 3),
        ("cmenu:tuto", "Comprends rien ?", "❓", "secondary", 3),
        ("cmenu:addaccount", "Ajouter un compte", "➕", "primary", 4),
        ("cmenu:comptes", "Mes comptes Insta", "📷", "secondary", 4),
        ("cmenu:fam:caption", "Caption ▸", "💬", "primary", 2),
        ("cmenu:fam:template", "Template ▸", "🎞️", "primary", 2),
        ("cmenu:fam:trash", "Trash ▸", "💀", "primary", 2),
        ("cmenu:fam:flash", "Flash ▸", "⚡", "primary", 2),
    )
    #: Les variantes que l'ancien menu savait lancer (ses boutons retires et ses
    #: sous-menus) : le menu V2 ne doit en perdre aucune.
    _ANCIENS_APPELS_VA = {
        "capbanger", "montagebanger", "reelmonte", "templatebanger", "templatebrut",
        "templateflash", "templateflashbanger", "templateflashbrut",
        "templatetrash", "templatetrashbanger", "templatetrashbrut"}


    def _ancien_menu_va():
        """L'ancien menu VA (vue classique), pour simuler un message deja poste."""
        v = discord.ui.View(timeout=None)
        for cid, lib, emo, sty, row in _ANCIEN_MENU_VA:
            v.add_item(discord.ui.Button(label=lib, emoji=emo, custom_id=cid, row=row,
                                         style=getattr(discord.ButtonStyle, sty)))
        return v


    IRT = discord.InteractionResponseType
    ui = discord.ui

    # ---------------------------------------------------------------------------
    # Faux objets Discord (repris de md_verif.py, parties A/B)
    # ---------------------------------------------------------------------------
    _ids = iter(range(10_000, 99_999))


    def http_exc(cls=discord.HTTPException, status=400, texte="refus simule"):
        return cls(types.SimpleNamespace(status=status, reason="x"), texte)


    class Auteur:
        def __init__(self, i):
            self.id = i
            self.bot = True


    MOI = 1


    def comps_de(vue):
        if vue is None:
            return []
        return [_component_factory(d) for d in vue.to_components()]


    class Msg:
        def __init__(self, ch=None, embed=None, view=None, ephemere=False, auteur=MOI, content=None):
            self.id = next(_ids)
            self.ch = ch
            self.embeds = [embed] if embed is not None else []
            self.content = content
            self.view = view
            # Ce que Discord RENVOIE : des composants reconstruits, pas la vue.
            self.components = comps_de(view)
            self.author = Auteur(auteur)
            self.pinned = False
            v2 = bool(view is not None and view.has_components_v2())
            self.flags = types.SimpleNamespace(ephemeral=ephemere, components_v2=v2)
            self.edits = []
            self.echec_edit = None
            self.supprime = False
            self.echec_delete = None

        async def edit(self, **k):
            self.edits.append(k)
            if self.echec_edit is not None:
                raise self.echec_edit
            if "view" in k:
                v = k["view"]
                if v is not None and v.has_components_v2():
                    # Discord refuse un V2 qui garderait texte ou embed.
                    if (self.embeds and "embed" not in k and "embeds" not in k) or \
                            (self.content and "content" not in k):
                        raise http_exc(texte="V2 avec embed/texte restant")
                    self.flags.components_v2 = True
                self.view = v
                self.components = comps_de(v)
            if "embed" in k:
                self.embeds = [k["embed"]] if k["embed"] is not None else []
            if "content" in k:
                self.content = k["content"]
            return self

        async def delete(self):
            if self.echec_delete is not None:
                raise self.echec_delete
            self.supprime = True
            if self.ch is not None and self in self.ch.msgs:
                self.ch.msgs.remove(self)

        async def pin(self, **k):
            self.pinned = True


    class Salon:
        def __init__(self, cid=4242, name="va-test"):
            self.id = cid
            self.name = name
            self.msgs = []
            self.guild = types.SimpleNamespace(id=7, emojis=[], text_channels=[self])
            self.echec_send = None
            self.envois = []

        async def pins(self):
            return [m for m in reversed(self.msgs) if m.pinned]

        async def send(self, content=None, embed=None, view=None, **k):
            self.envois.append(dict(content=content, embed=embed, view=view, **k))
            if self.echec_send:
                raise self.echec_send
            m = Msg(self, embed=embed, view=view, content=content)
            self.msgs.append(m)
            return m

        async def fetch_message(self, i):
            for m in self.msgs:
                if m.id == int(i):
                    return m
            raise http_exc(discord.NotFound, 404, "absent")

        async def history(self, limit=40, oldest_first=False):
            l = list(self.msgs) if oldest_first else list(reversed(self.msgs))
            for m in l[:limit]:
                yield m


    class DeuxReponses(Exception):
        pass


    class Rep:
        def __init__(self, itx):
            self.itx = itx
            self._type = None
            self.faits = []
            self.echec_edit = None
            self.doubles = 0

        def is_done(self):
            return self._type is not None

        @property
        def type(self):
            return self._type

        def _marquer(self, t, quoi, a, k):
            if self._type is not None:
                self.doubles += 1
                raise DeuxReponses(quoi)
            self._type = t
            self.faits.append((quoi, a, k))

        async def send_message(self, *a, **k):
            self._marquer(IRT.channel_message, "send_message", a, k)

        async def edit_message(self, *a, **k):
            if self.echec_edit is not None and self._type is None:
                e, self.echec_edit = self.echec_edit, None
                raise e
            self._marquer(IRT.message_update, "edit_message", a, k)
            m = self.itx.message
            if m is not None and "view" in k:
                await m.edit(**k)

        async def defer(self, ephemeral=False, thinking=False):
            self._marquer(IRT.deferred_channel_message if thinking else IRT.deferred_message_update,
                          "defer", (), dict(ephemeral=ephemeral, thinking=thinking))

        async def send_modal(self, modal):
            self._marquer(IRT.modal, "send_modal", (modal,), {})
            self.modal = modal


    class Suivi:
        def __init__(self, itx):
            self.itx = itx
            self.envois = []
            self.edits = []

        async def send(self, content=None, **k):
            if not self.itx.response.is_done():
                raise AssertionError("followup avant toute reponse")
            self.envois.append((content, k))
            return Msg(ephemere=bool(k.get("ephemeral")))

        async def edit_message(self, mid, **k):
            if not self.itx.response.is_done():
                raise AssertionError("followup.edit avant toute reponse")
            self.edits.append((mid, k))
            m = self.itx.message
            if m is not None and m.id == mid:
                await m.edit(**k)


    def repondre_selon(itx, mode):
        """Ce que fait une action du menu VA, selon `mode`."""
        async def _r():
            if mode == "defer":                  # le cas courant : defer() puis suivi
                await itx.response.defer()
                await itx.followup.send("contenu")
            elif mode == "thinking":
                await itx.response.defer(thinking=True)
                await itx.followup.send("fini")
            elif mode == "send_eph":             # refus de l'action (rien en stock…)
                await itx.response.send_message("Aucun montage", ephemeral=True)
            elif mode == "leve":
                raise RuntimeError("panne simulee")
            # « rien » : l'action ne repond pas
        return _r()


    class CogVA:
        """Faux UserCog : chaque methode appelee par le menu VA est notee, et
        repond selon `mode`."""

        def __init__(self):
            self.appels = []
            self.mode = "defer"
            for nom in ("reel", "story", "storycta", "post", "name", "username",
                        "profilepic", "bio", "reelmonte"):
                setattr(self, nom, types.SimpleNamespace(callback=self._cb(nom)))

        def _cb(self, nom):
            async def _f(cog, itx, *a, **k):
                self.appels.append((nom, a, k))
                await repondre_selon(itx, self.mode)
            return _f

        def _note(self, nom, itx, *a, **k):
            self.appels.append((nom, a, k))
            return repondre_selon(itx, self.mode)

        async def _send_banger_reels(self, itx):
            await self._note("_send_banger_reels", itx)

        async def _send_brutes_bangers(self, itx):
            await self._note("_send_brutes_bangers", itx)

        async def request_link(self, itx):
            await self._note("request_link", itx)

        async def _send_tutoriel(self, itx):
            await self._note("_send_tutoriel", itx)

        async def _send_caption_bangers(self, itx):
            await self._note("_send_caption_bangers", itx)

        async def _send_montage_bangers(self, itx):
            await self._note("_send_montage_bangers", itx)

        async def _send_template_plus_brute(self, itx, **k):
            await self._note("_send_template_plus_brute", itx, **k)

        async def _send_template_marque(self, itx, cle, **k):
            await self._note("_send_template_marque", itx, cle, **k)


    COG = CogVA()


    class Itx:
        def __init__(self, message=None, channel=None, guild=None, uid=55):
            self.message = message
            self.channel = channel
            self.guild = guild or types.SimpleNamespace(id=7, emojis=[])
            self.user = types.SimpleNamespace(id=uid, roles=[], mention=f"<@{uid}>")
            self.client = types.SimpleNamespace(
                get_cog=lambda n: COG if n == "UserCog" else None,
                user=types.SimpleNamespace(id=MOI))
            self.response = Rep(self)
            self.followup = Suivi(self)
            self.orig_edits = []
            self.data = {}

        async def edit_original_response(self, **k):
            if self.response.type not in (IRT.deferred_message_update, IRT.message_update):
                raise AssertionError("@original n'est pas le message du clic")
            self.orig_edits.append(k)
            if self.message is not None:
                await self.message.edit(**k)


    def run(coro):
        return asyncio.run(coro)


    async def attendre_fond():
        for _ in range(5):
            await asyncio.sleep(0)
        if U._JB_TACHES:
            await asyncio.gather(*list(U._JB_TACHES), return_exceptions=True)


    def lancer(coro):
        async def _t():
            r = await coro
            await attendre_fond()
            return r
        return asyncio.run(_t())


    def items(vue):
        return list(vue.walk_children())


    def rangees(vue):
        return [[c.custom_id for c in i.children] for i in items(vue) if isinstance(i, ui.ActionRow)]


    def selects(vue):
        return [i for i in items(vue) if isinstance(i, ui.Select)]


    def boutons(vue):
        return [i for i in items(vue) if isinstance(i, ui.Button)]


    def texte(vue):
        return "\n".join(i.content for i in items(vue) if isinstance(i, ui.TextDisplay))


    def limites(vue):
        pb = []
        if vue.total_children_count > 40:
            pb.append("composants %d > 40" % vue.total_children_count)
        if vue.content_length() > 4000:
            pb.append("texte %d > 4000" % vue.content_length())
        for i in items(vue):
            if isinstance(i, ui.ActionRow) and len(i.children) > 5:
                pb.append("rangee a %d" % len(i.children))
            cid = getattr(i, "custom_id", None)
            if cid and len(cid) > 100:
                pb.append("custom_id %d" % len(cid))
            if isinstance(i, ui.Button) and i.label and U._long_discord(i.label) > 80:
                pb.append("libelle bouton %r" % i.label)
            if isinstance(i, ui.Select):
                if len(i.options) > 25 or not i.options:
                    pb.append("options %d" % len(i.options))
                if i.placeholder and len(i.placeholder) > 150:
                    pb.append("placeholder")
                for o in i.options:
                    if U._long_discord(o.label) > 100:
                        pb.append("option %r" % o.label)
                    if o.description and U._long_discord(o.description) > 100:
                        pb.append("description %r" % o.description)
        json.dumps(vue.to_components())
        return pb


    GUILD_IC = types.SimpleNamespace(
        id=7, emojis=[discord.PartialEmoji(name=n, id=20000 + k)
                      for k, n in enumerate(sorted(set(U._ICONES_ACTIONS.values())))])

    _vrais_gf = (GF.get_features, GF.threads_mode)


    def reglages(feats=None, threads=False):
        """Reglages du serveur simules (None = tout)."""
        GF.get_features = lambda g: set(GF.ALL_FEATURES) if feats is None else set(feats)
        GF.threads_mode = lambda g: threads


    def reglages_vrais():
        GF.get_features, GF.threads_mode = _vrais_gf


    reglages()

    TRASH = tuple(MM.marque("trash")["actions"])
    FLASH = tuple(MM.marque("flash")["actions"])

    # ===========================================================================
    # 1. STRUCTURE DU MENU VA V2
    # ===========================================================================
    v = U.ContentMenuView(None)
    check("structure : LayoutView V2 persistante (timeout None), un seul conteneur",
          isinstance(v, ui.LayoutView) and v.has_components_v2() and v.timeout is None
          and v.is_persistent() and len(v.children) == 1 and isinstance(v.children[0], ui.Container))
    check("structure : le texte vient en tete du conteneur",
          isinstance(v.children[0].children[0], ui.TextDisplay))
    R_ATTENDU = [
        ["cmenu:reel", "cmenu:banger", "cmenu:story", "cmenu:storycta", "cmenu:post"],
        ["cmenu:name", "cmenu:pseudo", "cmenu:pp", "cmenu:bio", "cmenu:brutbanger"],
        ["cmenu:sel:caption"], ["cmenu:sel:template"], ["cmenu:sel:trash"], ["cmenu:sel:flash"],
        ["cmenu:clics", "cmenu:help", "cmenu:lien", "cmenu:pay", "cmenu:tuto"],
        ["cmenu:addaccount", "cmenu:comptes"],
    ]
    check("structure : rangees = cahier (Reel… / Name… / 4 menus / Mes clics… / comptes)",
          rangees(v) == R_ATTENDU, rangees(v))
    check("structure : dans les limites de Discord (%d composants, %d car.)"
          % (v.total_children_count, v.content_length()),
          not limites(v) and v.total_children_count <= 40, limites(v))
    OPTS_ATTENDUES = {
        "caption": ["capbanger", "montagebanger"],
        "template": ["reelmonte", "templatebanger", "templatebrut"],
        "trash": [TRASH[0], TRASH[1], TRASH[3]],
        "flash": [FLASH[0], FLASH[1], FLASH[3]],
    }
    LIB_ATTENDUS = {
        "caption": ["⭐ Caption", "⭐⭐ Caption + Vidéo brut"],
        "template": ["🎞️ Template", "⭐ Template", "⭐⭐ Template + Brut"],
        "trash": ["💀 Trash", "⭐ Trash", "⭐⭐ Trash + Brut"],
        "flash": ["⚡ Flash", "⭐ Flash", "⭐⭐ Flash + Brut"],
    }
    _ok, _det = True, []
    for s_ in selects(v):
        fam = s_.custom_id.split(":")[-1]
        vals = [o.value for o in s_.options]
        libs = [o.label for o in s_.options]
        f = U._famille_menu(fam)
        if vals != OPTS_ATTENDUES[fam] or libs != LIB_ATTENDUS[fam]:
            _ok = False
            _det.append((fam, vals, libs))
        if s_.placeholder != "%s %s…" % (f.emoji, f.nom):
            _ok = False
            _det.append(s_.placeholder)
        for o in s_.options:
            if o.description != U._EXPLICATIONS[o.value] or o.default:
                _ok = False
                _det.append(("desc/defaut", o.value))
        if s_.min_values != 1 or s_.max_values != 1:
            _ok = False
    check("menus : options = variantes du cahier, libelles de production, explication, aucune par defaut",
          _ok, _det)
    check("menus : chaque option est une variante que le menu VA sait lancer (_MENU_VA_APPELS)",
          all(o.value in U._MENU_VA_APPELS for s_ in selects(v) for o in s_.options))

    # Boutons : memes custom_id, libelles, emojis et styles que l'ancien menu.
    _anc = {b.custom_id: b for b in _ancien_menu_va().children if isinstance(b, ui.Button)
            and not b.custom_id.startswith("cmenu:fam:")}
    _diff = []
    for b in boutons(v):
        a = _anc.get(b.custom_id)
        if a is None or (a.label, str(a.emoji), a.style) != (b.label, str(b.emoji), b.style):
            _diff.append((b.custom_id, b.label, str(b.emoji), b.style,
                          a and (a.label, str(a.emoji), a.style)))
    check("boutons : les 17 boutons gardent custom_id, libelle, emoji et style de l'ancien menu",
          not _diff and len(boutons(v)) == 17, _diff)
    check("boutons : chaque bouton de la table a sa methode (_clic_<cle>)",
          all(hasattr(U.ContentMenuView, "_clic_" + b.custom_id.split(":", 1)[1]) for b in boutons(v))
          and not v.inconnues)

    t = texte(v)
    check("texte : titre, aide par rangee, marque en derniere ligne",
          t.startswith("## ☀️ Ton menu\n") and "**Publier**" in t and "**Ton compte**" in t
          and "**Montages**" in t and "**Suivi et aide**" in t and "**Tes comptes**" in t
          and t.splitlines()[-1] == "-# menu-contenu-va", t)
    _jsv = json.dumps(v.to_components(), ensure_ascii=False)
    check("texte : aucune trace de ⭐⭐⭐ Trends (Trash/Flash Trend ne sont pas « Trends »)",
          "⭐⭐⭐" not in _jsv and "Trends" not in _jsv and ":trend" not in _jsv)
    vI = U._menu_va(COG, "julia", None, mention=55)
    tI = texte(vI)
    check("texte : mention en premiere ligne, identite juste au-dessus de la marque",
          tI.splitlines()[0] == "<@55> 👇 **Ton menu du jour est prêt !**"
          and tI.splitlines()[-2] == "-# Identité : `julia`" and tI.splitlines()[-1] == "-# menu-contenu-va", tI)
    check("texte : le mot « identité » n'apparait que sur la ligne d'identite",
          [l for l in tI.splitlines() if "identit" in l.lower()] == ["-# Identité : `julia`"])
    check("texte : le menu VA V2 n'est pas pris pour le panneau US (autre marque)",
          U._est_panneau_actions(Msg(view=vI)) is False)
    check("texte : lecture (identite, mention) d'un menu V2 poste", U._menu_va_lire(Msg(view=vI)) == ("julia", 55),
          U._menu_va_lire(Msg(view=vI)))
    # Le texte trop long est coupe, jamais la marque.
    _t_long = U._menu_va_texte(["x" * 5000], False, True, "julia")
    check("texte : une aide geante est coupee a 4000, la marque et l'identite restent",
          len(_t_long) <= 4000 and _t_long.splitlines()[-1] == "-# menu-contenu-va"
          and _t_long.splitlines()[-2] == "-# Identité : `julia`")

    # Icones du serveur.
    vIc = U._menu_va(COG, "julia", GUILD_IC)
    _bic = {b.custom_id: b.emoji for b in boutons(vIc)}
    _ic = U.icones_actions(GUILD_IC)
    check("icones : les boutons portent l'icone dessinee quand elle existe (Reel, Story, PP…)",
          all(_bic["cmenu:" + k].id is not None for k in ("reel", "story", "storycta", "post",
                                                           "name", "pseudo", "pp", "bio"))
          and _bic["cmenu:clics"].name == "📊", _bic)
    _oic = [(o.value, o.emoji, o.label) for s_ in selects(vIc) for o in s_.options]
    check("icones : chaque option porte l'icone de son action, libelle sans emoji",
          all(e is not None and e.id == _ic[k].id and l == U._libelle_sans_emoji(U._jb_action(k)[1])
              for k, e, l in _oic), _oic)
    check("icones : avec icones, toujours dans les limites", not limites(vIc), limites(vIc))

    # ===========================================================================
    # 2. REGLAGES PAR SERVEUR
    # ===========================================================================
    reglages(set(GF.ALL_FEATURES) - {"contenu"})
    vC = U._menu_va(COG, "julia", None)
    check("reglages : « contenu » coupe -> plus aucun bouton de contenu, plus aucun menu",
          rangees(vC) == [["cmenu:clics", "cmenu:help", "cmenu:lien", "cmenu:pay", "cmenu:tuto"],
                          ["cmenu:addaccount"]] and not selects(vC), rangees(vC))
    check("reglages : ... et le texte ne decrit plus ce qui manque (ni Montages, ni Reel)",
          "Montages" not in texte(vC) and "Reel" not in texte(vC) and "Publier" not in texte(vC)
          and "Clique sur un bouton 👇" in texte(vC), texte(vC))
    reglages(set(GF.ALL_FEATURES) - {"clics", "liens", "onboarding"})
    vD = U._menu_va(COG, "julia", None)
    _idsD = [c for r in rangees(vD) for c in r]
    check("reglages : clics / liens / onboarding coupes -> leurs boutons disparaissent",
          not {"cmenu:clics", "cmenu:lien", "cmenu:addaccount"} & set(_idsD)
          and "cmenu:help" in _idsD and len(selects(vD)) == 4, _idsD)
    reglages(threads=True)
    vT = U._menu_va(COG, "julia", None)
    _idsT = {c for r in rangees(vT) for c in r}
    check("reglages : mode Threads -> seul le jeu reduit, aucun menu",
          _idsT == U._THREADS_MENU and not selects(vT), sorted(_idsT))
    check("reglages : mode Threads -> « Mes comptes Threads », titre Threads, pas d'identite",
          [b.label for b in boutons(vT) if b.custom_id == "cmenu:comptes"] == ["Mes comptes Threads"]
          and texte(vT).startswith("## 🧵 Ton menu Threads") and "Identité" not in texte(vT)
          and "comptes Threads (@pseudo)" in texte(vT), texte(vT))
    # Une option coupee disparait, un menu vide disparait.
    reglages(set(GF.ALL_FEATURES) - {"rappels"})
    _sauve_feat = dict(U._MENU_BTN_FEATURE)
    try:
        U._MENU_BTN_FEATURE["cmenu:capbanger"] = "rappels"
        vO = U._menu_va(COG, "julia", None)
        _cap = [s_ for s_ in selects(vO) if s_.custom_id == "cmenu:sel:caption"]
        check("reglages : une option coupee disparait de son menu (Caption sans ⭐ Caption)",
              _cap and [o.value for o in _cap[0].options] == ["montagebanger"],
              _cap and [o.value for o in _cap[0].options])
        U._MENU_BTN_FEATURE["cmenu:montagebanger"] = "rappels"
        vO2 = U._menu_va(COG, "julia", None)
        check("reglages : un menu vide disparait (plus de menu Caption), les autres restent, le texte suit",
              [s_.custom_id for s_ in selects(vO2)] == ["cmenu:sel:template", "cmenu:sel:trash", "cmenu:sel:flash"]
              and "💬 Caption" not in texte(vO2) and "🎞️ Template" in texte(vO2), texte(vO2))
        U._MENU_BTN_FEATURE["cmenu:banger"] = "rappels"
        vO3 = U._menu_va(COG, "julia", None)
        check("reglages : un bouton coupe disparait de sa rangee (⭐ Reels) et de l'aide",
              rangees(vO3)[0] == ["cmenu:reel", "cmenu:story", "cmenu:storycta", "cmenu:post"]
              and "⭐ Reels" not in texte(vO3), rangees(vO3)[0])
    finally:
        U._MENU_BTN_FEATURE.clear()
        U._MENU_BTN_FEATURE.update(_sauve_feat)


    # Module de reglages en panne : on garde tout (comme avant).
    def _panne(g):
        raise RuntimeError("reglages illisibles")


    GF.get_features = _panne
    vP = U._menu_va(COG, "julia", None)
    check("reglages : module en panne -> menu complet, comme avant",
          rangees(vP) == R_ATTENDU, rangees(vP))
    reglages()
    check("reglages : _filter_menu_view garde son contrat (rend la vue, reconstruite)",
          U._filter_menu_view(U.ContentMenuView(None), None) is not None
          and rangees(U._filter_menu_view(U.ContentMenuView(None), None)) == R_ATTENDU)

    # ===========================================================================
    # 3. ENREGISTREMENT, MOTIFS, REDEMARRAGE
    # ===========================================================================


    class BotF:
        def __init__(self):
            self.vues, self.dyn = [], []

        def add_view(self, v, message_id=None):
            # Meme garde que discord.Client.add_view.
            if not v.is_persistent():
                raise ValueError("View is not persistent")
            self.vues.append(v)

        def add_dynamic_items(self, *its):
            self.dyn.extend(its)


    _bot = BotF()
    del JOURNAL.lignes[:]
    run(U.UserCog.cog_load(types.SimpleNamespace(
        bot=_bot, daily_menu=types.SimpleNamespace(is_running=lambda: True))))
    check("cog_load : menu VA V2, boutons herites et lanceurs herites enregistres, aucun echec au journal",
          any(isinstance(x, U.ContentMenuView) for x in _bot.vues)
          and any(isinstance(x, U.ContentMenuHeritageView) for x in _bot.vues)
          and any(isinstance(x, U.ContentMenuLanceursView) for x in _bot.vues)
          and not [l for l in JOURNAL.lignes if "cog_load" in l[2]],
          [l for l in JOURNAL.lignes if "cog_load" in l[2]])


    async def _cog_load_vrai_bot():
        """cog_load contre un VRAI commands.Bot : ses gardes (vue persistante,
        non terminee) sont celles de discord.py, pas celles d'un faux."""
        from discord.ext import commands as _cmds
        b = _cmds.Bot(command_prefix="!", intents=discord.Intents.none())
        await U.UserCog.cog_load(types.SimpleNamespace(
            bot=b, daily_menu=types.SimpleNamespace(is_running=lambda: True)))
        return b


    del JOURNAL.lignes[:]
    _vb = run(_cog_load_vrai_bot())
    _pv = [type(x).__name__ for x in _vb.persistent_views]
    check("cog_load (vrai commands.Bot) : menu VA V2 + heritages acceptes comme vues persistantes",
          {"ContentMenuView", "ContentMenuHeritageView", "ContentMenuLanceursView"} <= set(_pv)
          and not [l for l in JOURNAL.lignes if "cog_load" in l[2]],
          (_pv, [l for l in JOURNAL.lignes if "cog_load" in l[2]]))
    _persist = [it.custom_id for x in _bot.vues for it in x.walk_children()
                if not isinstance(it, ui.DynamicItem) and getattr(it, "custom_id", None)]
    _motifs = [(c.__name__, c.__discord_ui_compiled_template__) for c in _bot.dyn]


    def qui(cid):
        n = _persist.count(cid)
        return ["vue"] * n + [nm for nm, p in _motifs if p.fullmatch(cid)]


    _neufs = [c for r in rangees(U.ContentMenuView(None)) for c in r]
    _mauv = [(c, qui(c)) for c in _neufs if len(qui(c)) != 1]
    check("motifs : chaque custom_id du menu V2 est servi par UN element exactement",
          not _mauv and len(_neufs) == 21, _mauv)
    _ANCIENS_MENU = ("reel", "story", "post", "storycta", "banger", "reelmonte", "pseudo",
                     "name", "bio", "pp", "lien", "clics", "help", "tuto", "addaccount",
                     "comptes", "pay", "capbanger", "montagebanger", "templateflash",
                     "templateflashbanger", "templateflashbrut", "templatebanger",
                     "templatebrut", "brutbanger")
    _anciens = (["cmenu:" + k for k in _ANCIENS_MENU]
                + ["cmenu:fam:" + f.cle for f in U._FAMILLES_MENU])
    _mauv2 = [(c, qui(c)) for c in _anciens if len(qui(c)) != 1]
    check("motifs : les 25 boutons d'avant dc157c3 et les 4 lanceurs cmenu:fam: servis par UN element",
          not _mauv2, _mauv2)
    _menu_ids = {it.custom_id for it in U.ContentMenuView(None).walk_children() if getattr(it, "custom_id", None)}
    _her_ids = {it.custom_id for it in U.ContentMenuHeritageView(None).children}
    _lan_ids = {it.custom_id for it in U.ContentMenuLanceursView(None).children}
    check("motifs : aucun custom_id partage entre le menu V2 et les vues heritees",
          not (_menu_ids & _her_ids) and not (_menu_ids & _lan_ids) and not (_her_ids & _lan_ids))
    check("motifs : la vue heritee garde EXACTEMENT ses 8 boutons (inchangee), les lanceurs sont a part",
          sorted(_her_ids) == sorted("cmenu:" + k for k in U.ContentMenuHeritageView.ANCIENS)
          and len(_her_ids) == 8
          and _lan_ids == {"cmenu:fam:" + f.cle for f in U._FAMILLES_MENU}
          and U.ContentMenuLanceursView(None).is_persistent())
    check("motifs : aucun motif dynamique ne capture un custom_id « cmenu: »",
          not any(p.fullmatch(c) for _n, p in _motifs for c in _neufs + _anciens))


    class EtatF:
        """Etat minimal pour un vrai ViewStore de discord.py."""


    def store_neuf():
        """Un redemarrage : un ViewStore neuf, rempli comme cog_load le fait
        (add_view sans message_id)."""
        from discord.ui.view import ViewStore
        store = ViewStore(EtatF())
        cog_vrai = COG
        store.add_view(U.ContentMenuView(cog_vrai))
        store.add_view(U.ContentMenuHeritageView(cog_vrai))
        store.add_view(U.ContentMenuLanceursView(cog_vrai))
        store.add_dynamic_items(*_bot.dyn)
        return store


    async def _via_store(store, ctype, cid, itx, valeurs=None):
        # Le ViewStore et ses vues naissent DANS la boucle, comme en production
        # (cog_load) : construite hors boucle, une vue n'a pas de futur « arrete »
        # et discord.py ignore ses clics.
        store = store or store_neuf()
        itx.data = {"custom_id": cid, "component_type": ctype}
        if valeurs is not None:
            itx.data["values"] = valeurs
        store.dispatch_view(ctype, cid, itx)
        for _ in range(30):
            await asyncio.sleep(0)
        await attendre_fond()


    def via_store(ctype, cid, message, valeurs=None, guild=None, mode="defer"):
        COG.mode = mode
        COG.appels.clear()
        itx = Itx(message=message, channel=message.ch if message else None, guild=guild)
        run(_via_store(None, ctype, cid, itx, valeurs))
        return itx


    def menu_poste(ch=None, ident="julia", mention=None, epingle=True, guild=None):
        ch = ch or Salon(900)
        m = Msg(ch, view=U._menu_va(COG, ident, guild, mention))
        m.pinned = epingle
        ch.msgs.append(m)
        return ch, m


    def remis(vue):
        return vue is not None and isinstance(vue, U.ContentMenuView) and len(selects(vue)) == 4 \
            and all(not o.default for s_ in selects(vue) for o in s_.options)


    del JOURNAL.lignes[:]
    ch, m = menu_poste(mention=55)
    itx = via_store(3, "cmenu:sel:trash", m, [TRASH[1]])
    check("redemarrage : un menu V2 deja poste repond (ViewStore neuf), la variante part",
          COG.appels == [("_send_template_marque", ("trash",), {"exiger_banger": True, "brute_favorite": False})],
          COG.appels)
    check("redemarrage : ... une seule reponse, menu redessine sur son intitule, identite et mention gardees",
          itx.response.doubles == 0 and len(itx.response.faits) == 1 and len(m.edits) == 1
          and remis(m.edits[0]["view"]) and U._menu_va_lire(m) == ("julia", 55)
          and not [l for l in JOURNAL.lignes if "Ignoring exception" in l[2]],
          (itx.response.faits, len(m.edits), U._menu_va_lire(m)))
    itx = via_store(2, "cmenu:reel", m)
    check("redemarrage : un bouton du menu V2 repond (Reel -> reel.callback)",
          [a[0] for a in COG.appels] == ["reel"] and len(itx.response.faits) == 1, COG.appels)

    # Ancien menu (embed) avec un ancien bouton et un lanceur.
    ch2 = Salon(901)
    _emb = discord.Embed(title="☀️ Ton menu").set_footer(text="Identité : julia")
    mA = Msg(ch2, embed=_emb, view=_ancien_menu_va(),
             content="<@55> 👇 **Ton menu du jour est prêt !**")
    mA.pinned = True
    ch2.msgs.append(mA)
    itx = via_store(2, "cmenu:post", mA)
    check("ancien menu : un bouton encore present (Post) repond via le menu V2 enregistre",
          [a[0] for a in COG.appels] == ["post"] and len(itx.response.faits) == 1, COG.appels)
    mOld = Msg(ch2, embed=_emb, view=None)
    itx = via_store(2, "cmenu:templateflashbrut", mOld)
    check("ancien menu : un bouton retire avant dc157c3 (templateflashbrut) lance toujours la meme chose",
          COG.appels == [("_send_template_marque", ("flash",), {"exiger_banger": True, "brute_favorite": True})],
          COG.appels)
    del JOURNAL.lignes[:]
    itx = via_store(2, "cmenu:fam:caption", mA)
    check("ancien lanceur ▸ : convertit son menu en V2 SUR PLACE (edition, texte et embed vides)",
          itx.response.faits and itx.response.faits[0][0] == "edit_message"
          and itx.response.faits[0][2].get("content", 1) is None and itx.response.faits[0][2].get("embed", 1) is None
          and mA.flags.components_v2 and not mA.embeds and mA.content is None
          and U._est_menu_va(mA, MOI) and mA.pinned and not COG.appels and itx.response.doubles == 0,
          itx.response.faits)
    check("ancien lanceur ▸ : ... identite (pied d'embed) et mention (contenu) reprises dans le texte",
          U._menu_va_lire(mA) == ("julia", 55) and remis(mA.view), U._menu_va_lire(mA))
    # Refus de l'edition : repli par un nouveau message, epingle, ancien retire.
    ch3 = Salon(902)
    mB = Msg(ch3, embed=_emb, view=_ancien_menu_va())
    mB.pinned = True
    ch3.msgs.append(mB)
    COG.mode = "defer"
    COG.appels.clear()
    itx = Itx(message=mB, channel=ch3)
    itx.response.echec_edit = http_exc(texte="Cannot convert")
    itx.data = {"custom_id": "cmenu:fam:trash", "component_type": 2}
    del JOURNAL.lignes[:]
    run(_via_store(None, 2, "cmenu:fam:trash", itx))
    _nouv = [x for x in ch3.msgs if x is not mB]
    check("conversion refusee : defer, nouveau menu V2 poste ET epingle, ancien retire, journalise",
          itx.response.faits and itx.response.faits[0][0] == "defer" and len(itx.response.faits) == 1
          and mB.supprime and len(_nouv) == 1 and _nouv[0].pinned and U._est_menu_va(_nouv[0], MOI)
          and any("nouveau menu V2" in l[2] for l in JOURNAL.lignes)
          and any("menu VA : edition refusee" in l[2] for l in JOURNAL.lignes),
          (itx.response.faits, [l[2] for l in JOURNAL.lignes]))
    # Ancien menu NON epingle (menu du jour) : le nouveau ne s'epingle pas.
    ch4 = Salon(903)
    mC = Msg(ch4, embed=_emb, view=_ancien_menu_va())
    ch4.msgs.append(mC)
    itx = Itx(message=mC, channel=ch4)
    itx.response.echec_edit = http_exc(texte="Cannot convert")
    itx.data = {"custom_id": "cmenu:fam:flash", "component_type": 2}
    run(_via_store(None, 2, "cmenu:fam:flash", itx))
    _nouv = [x for x in ch4.msgs if x is not mC]
    check("conversion refusee : un menu du jour (non epingle) est remplace sans etre epingle",
          len(_nouv) == 1 and not _nouv[0].pinned and mC.supprime)
    # L'ancien ne peut pas etre retire : dit au journal.
    ch5 = Salon(904)
    mD = Msg(ch5, embed=_emb, view=_ancien_menu_va())
    mD.pinned = True
    mD.echec_delete = http_exc(discord.Forbidden, 403, "pas le droit")
    ch5.msgs.append(mD)
    itx = Itx(message=mD, channel=ch5)
    itx.response.echec_edit = http_exc(texte="Cannot convert")
    del JOURNAL.lignes[:]
    itx.data = {"custom_id": "cmenu:fam:flash", "component_type": 2}
    run(_via_store(None, 2, "cmenu:fam:flash", itx))
    check("conversion refusee : ancien non retire -> « deux menus dans le salon » journalise",
          any("deux menus dans le salon" in l[2] for l in JOURNAL.lignes))
    # Edition refusee ET salon qui refuse le nouveau message : menu en ephemere.
    ch5b = Salon(9045)
    mD2 = Msg(ch5b, embed=_emb, view=_ancien_menu_va())
    mD2.pinned = True
    ch5b.msgs.append(mD2)
    ch5b.echec_send = http_exc(discord.Forbidden, 403, "pas le droit d'ecrire")
    itx = Itx(message=mD2, channel=ch5b)
    itx.response.echec_edit = http_exc(texte="Cannot convert")
    itx.data = {"custom_id": "cmenu:fam:trash", "component_type": 2}
    del JOURNAL.lignes[:]
    run(_via_store(None, 2, "cmenu:fam:trash", itx))
    check("conversion impossible (edition ET envoi refuses) : defer, menu V2 en ephemere (vue arretee), journalise",
          len(itx.response.faits) == 1 and itx.response.faits[0][0] == "defer"
          and itx.followup.envois and itx.followup.envois[0][1].get("ephemeral")
          and isinstance(itx.followup.envois[0][1].get("view"), U.ContentMenuView)
          and itx.followup.envois[0][1]["view"].is_finished() and not mD2.supprime
          and any("conversion impossible" in l[2] for l in JOURNAL.lignes)
          and not [l for l in JOURNAL.lignes if "Ignoring exception" in l[2]],
          (itx.response.faits, itx.followup.envois, [l[2] for l in JOURNAL.lignes][-5:]))
    # Ancien menu ephemere.
    mE = Msg(None, embed=_emb, view=_ancien_menu_va(), ephemere=True)
    itx = Itx(message=mE, channel=Salon(905))
    itx.response.echec_edit = http_exc(texte="refus")
    itx.data = {"custom_id": "cmenu:fam:flash", "component_type": 2}
    run(_via_store(None, 2, "cmenu:fam:flash", itx))
    f = itx.response.faits
    check("conversion refusee en ephemere : nouvel ephemere, vue ARRETEE (non suivie), une reponse",
          len(f) == 1 and f[0][0] == "send_message" and f[0][2].get("ephemeral")
          and isinstance(f[0][2].get("view"), U.ContentMenuView) and f[0][2]["view"].is_finished(), f)
    # Menu vide (tout coupe) : pas de conversion.
    reglages(set(), threads=False)
    _sauve_feat = dict(U._MENU_BTN_FEATURE)
    _sauve_threads = set(U._THREADS_MENU)
    try:
        for k in ("cmenu:help", "cmenu:pay", "cmenu:tuto"):
            U._MENU_BTN_FEATURE[k] = "clics"
        ch6 = Salon(906)
        mF = Msg(ch6, embed=_emb, view=_ancien_menu_va())
        ch6.msgs.append(mF)
        itx = via_store(2, "cmenu:fam:caption", mF)
        check("ancien lanceur, serveur sans aucune fonction : rien de converti, raison dite",
              itx.response.faits and itx.response.faits[0][0] == "send_message"
              and "Aucune fonction" in str(itx.response.faits[0][1]) and not mF.edits)
    finally:
        U._MENU_BTN_FEATURE.clear()
        U._MENU_BTN_FEATURE.update(_sauve_feat)
        reglages()

    # ===========================================================================
    # 4. CHOIX DANS UN MENU : chaque variante, remise a l'intitule, une reponse
    # ===========================================================================
    APPELS_ATTENDUS = {
        "capbanger": ("_send_caption_bangers", (), {}),
        "montagebanger": ("_send_montage_bangers", (), {}),
        "reelmonte": ("reelmonte", (), {}),
        "templatebanger": ("_send_template_plus_brute", (), {"brute_favorite": False}),
        "templatebrut": ("_send_template_plus_brute", (), {}),
    }
    for _m, _acts in (("trash", TRASH), ("flash", FLASH)):
        APPELS_ATTENDUS[_acts[0]] = ("_send_template_marque", (_m,), {"exiger_banger": False, "brute_favorite": False})
        APPELS_ATTENDUS[_acts[1]] = ("_send_template_marque", (_m,), {"exiger_banger": True, "brute_favorite": False})
        APPELS_ATTENDUS[_acts[3]] = ("_send_template_marque", (_m,), {"exiger_banger": True, "brute_favorite": True})


    def choisir(famille, valeur, message, mode="defer", guild=None):
        COG.mode = mode
        COG.appels.clear()
        vue = message.view
        s_ = [x for x in selects(vue) if x.custom_id == U._CMENU_MENU + famille][0]
        itx = Itx(message=message, channel=message.ch, guild=guild)
        itx.data = {"custom_id": s_.custom_id, "component_type": 3, "values": [valeur]}
        lancer(s_.callback(itx))
        return itx


    _tout_ok, _det = True, []
    for fam, vals in OPTS_ATTENDUES.items():
        for val in vals:
            ch, m = menu_poste(mention=55)
            itx = choisir(fam, val, m)
            ok = (COG.appels == [APPELS_ATTENDUS[val]] and itx.response.doubles == 0
                  and len(itx.response.faits) == 1 and len(m.edits) == 1 and remis(m.edits[0]["view"])
                  and U._menu_va_lire(m) == ("julia", 55))
            if not ok:
                _tout_ok = False
                _det.append((fam, val, COG.appels, itx.response.faits, len(m.edits)))
    check("choix : chacune des 11 variantes appelle EXACTEMENT la methode de son ancien bouton, "
          "une reponse, menu remis (identite et mention gardees)", _tout_ok, _det)
    # Parite avec l'ancien : meme table d'appels.
    check("choix : table d'appels identique a celle d'avant la partie C",
          {k: (v.__name__ if hasattr(v, "__name__") else v) for k, v in U._MENU_VA_APPELS.items()}.keys()
          == _ANCIENS_APPELS_VA)

    # Action muette : la reponse est la remise a zero.
    ch, m = menu_poste()
    itx = choisir("caption", "capbanger", m, mode="rien")
    check("action muette : la reponse est l'edition du menu (jamais « l'interaction a echoue »)",
          itx.response.faits and itx.response.faits[0][0] == "edit_message" and itx.response.doubles == 0
          and remis(itx.response.faits[0][2]["view"]), itx.response.faits)
    # Action refusee (send_message ephemere) : menu remis quand meme.
    ch, m = menu_poste()
    itx = choisir("trash", TRASH[0], m, mode="send_eph")
    check("action qui refuse (message ephemere) : une reponse, menu remis par le message",
          len(itx.response.faits) == 1 and itx.response.faits[0][0] == "send_message"
          and len(m.edits) == 1 and remis(m.edits[0]["view"]))
    # Action « thinking ».
    ch, m = menu_poste()
    itx = choisir("template", "reelmonte", m, mode="thinking")
    check("action « thinking » : une reponse, menu remis", len(itx.response.faits) == 1
          and len(m.edits) == 1 and not itx.orig_edits)
    # L'action leve.
    ch, m = menu_poste()
    del JOURNAL.lignes[:]
    itx = choisir("flash", FLASH[0], m, mode="leve")
    check("action qui leve : une reponse, erreur DITE en ephemere et journalisee",
          itx.response.doubles == 0 and len(itx.response.faits) == 1
          and itx.followup.envois and "erreur" in itx.followup.envois[-1][0]
          and itx.followup.envois[-1][1].get("ephemeral")
          and any("menu VA : action" in l[2] and "en echec" in l[2] for l in JOURNAL.lignes),
          (itx.response.faits, itx.followup.envois))
    # Le redessin en fond echoue : on repasse par l'interaction.
    ch, m = menu_poste()
    m.echec_edit = http_exc(texte="Unknown message")
    del JOURNAL.lignes[:]
    itx = choisir("caption", "montagebanger", m, mode="defer")
    check("redessin en fond refuse + action differee : remise par @original, une reponse",
          itx.orig_edits and itx.response.doubles == 0 and len(itx.response.faits) == 1
          and any("remis sur son intitule" in l[2] for l in JOURNAL.lignes), itx.orig_edits)
    ch, m = menu_poste()
    m.echec_edit = http_exc(texte="Unknown message")
    del JOURNAL.lignes[:]
    itx = choisir("caption", "montagebanger", m, mode="send_eph")
    check("redessin impossible partout : pas d'exception, une reponse, echec journalise",
          itx.response.doubles == 0 and len(itx.response.faits) == 1
          and any("non remis sur son intitule" in l[2] for l in JOURNAL.lignes))
    # Refus : valeur forgee.
    ch, m = menu_poste()
    del JOURNAL.lignes[:]
    itx = choisir("caption", "templateflash", m)
    check("refus : une valeur hors de la famille est refusee, rien ne part, menu remis, raison dite",
          not COG.appels and itx.response.faits[0][0] == "edit_message" and remis(itx.response.faits[0][2]["view"])
          and "inconnue" in str(itx.followup.envois[0][0]) and itx.followup.envois[0][1].get("ephemeral")
          and any("choix 'templateflash' refuse" in l[2] for l in JOURNAL.lignes), itx.followup.envois)
    itx = choisir("caption", "brutcaption", m)
    check("refus : ⭐ Brut + Caption (jamais au menu VA) est refusee elle aussi", not COG.appels
          and "inconnue" in str(itx.followup.envois))
    # Refus : option coupee depuis que le menu a ete poste.
    ch, m = menu_poste()
    reglages(set(GF.ALL_FEATURES) - {"contenu"})
    itx = choisir("trash", TRASH[3], m)
    check("refus : variante coupee sur le serveur depuis la pose -> refusee, et le menu redessine n'a plus de menus",
          not COG.appels and "désactivée" in str(itx.followup.envois[0][0])
          and not selects(itx.response.faits[0][2]["view"]), itx.followup.envois)
    reglages()
    # Menu EPHEMERE : pas de message.edit, remise par l'interaction.
    mE = Msg(None, view=U._vue_sans_suivi(U._menu_va(COG, "julia", None)), ephemere=True)
    mE.ch = None
    itx = choisir("template", "templatebrut", mE, mode="defer")
    check("menu ephemere + action differee : remise par @original, vue arretee",
          itx.orig_edits and itx.orig_edits[0]["view"].is_finished() and remis(itx.orig_edits[0]["view"])
          and len(itx.response.faits) == 1, (itx.orig_edits, itx.response.faits))
    itx = choisir("template", "templatebrut", mE, mode="send_eph")
    check("menu ephemere + action repondue par un message : remise par followup.edit_message",
          itx.followup.edits and itx.followup.edits[0][0] == mE.id and len(itx.response.faits) == 1,
          itx.followup.edits)
    itx = choisir("template", "templatebrut", mE, mode="rien")
    check("menu ephemere + action muette : la reponse EST la remise", itx.response.faits[0][0] == "edit_message"
          and len(itx.response.faits) == 1)
    # Les valeurs viennent de l'interaction, pas de l'objet partage.
    ch, m = menu_poste()
    s_ = [x for x in selects(m.view) if x.custom_id == "cmenu:sel:flash"][0]
    s_._values = [FLASH[0]]
    COG.appels.clear()
    itx = Itx(message=m, channel=ch)
    itx.data = {"values": [FLASH[3]]}
    lancer(s_.callback(itx))
    check("choix : la valeur lue est celle de L'INTERACTION (l'element persistant est partage)",
          COG.appels == [APPELS_ATTENDUS[FLASH[3]]], COG.appels)
    s_._values = []

    # ===========================================================================
    # 5. BOUTONS DU MENU V2 (callbacks simules)
    # ===========================================================================
    BOUTONS_APPELS = {
        "reel": "reel", "banger": "_send_banger_reels", "story": "story", "storycta": "storycta",
        "post": "post", "name": "name", "pseudo": "username", "pp": "profilepic", "bio": "bio",
        "brutbanger": "_send_brutes_bangers", "lien": "request_link", "tuto": "_send_tutoriel",
    }
    _ok, _det = True, []
    for b in boutons(U._menu_va(COG, "julia", None)):
        k = b.custom_id.split(":", 1)[1]
        if k not in BOUTONS_APPELS:
            continue
        COG.mode = "defer"
        COG.appels.clear()
        itx = Itx(message=Msg(Salon(910)), channel=Salon(910))
        run(b.callback(itx))
        if [a[0] for a in COG.appels] != [BOUTONS_APPELS[k]] or len(itx.response.faits) != 1:
            _ok = False
            _det.append((k, COG.appels, itx.response.faits))
    check("boutons : chacun appelle la meme methode qu'avant (12 boutons de contenu/aide)", _ok, _det)
    _bmap = {b.custom_id: b for b in boutons(U._menu_va(COG, "julia", None))}
    itx = Itx(message=Msg(Salon(911)))
    run(_bmap["cmenu:help"].callback(itx))
    check("boutons : Assistance ouvre sa fenetre", itx.response.faits[0][0] == "send_modal"
          and isinstance(itx.response.modal, U.AssistanceModal))
    itx = Itx(message=Msg(Salon(911)))
    run(_bmap["cmenu:pay"].callback(itx))
    check("boutons : Mon paiement repond en ephemere avec son choix",
          itx.response.faits[0][0] == "send_message" and itx.response.faits[0][2].get("ephemeral")
          and isinstance(itx.response.faits[0][2].get("view"), U.PaymentMethodView))
    itx = Itx(message=Msg(Salon(911)))
    run(_bmap["cmenu:clics"].callback(itx))
    check("boutons : Mes clics sans le cog ClickRecap -> le dit, en ephemere",
          "indisponibles" in str(itx.response.faits[0][1]))
    itx = Itx(message=Msg(Salon(911)))
    run(_bmap["cmenu:comptes"].callback(itx))
    check("boutons : Mes comptes Insta ouvre sa fenetre", itx.response.faits[0][0] == "send_modal")

    # ===========================================================================
    # 6. REPERAGE DES DEUX FORMATS
    # ===========================================================================
    _mV2 = Msg(view=U._menu_va(COG, "julia", None))
    _mOld = Msg(embed=discord.Embed(title="☀️ Ton menu"))
    _mOldT = Msg(embed=discord.Embed(title="🧵 Ton menu Threads"))
    _mPan = Msg(view=U._jb_panel(None, "emma", 3))
    _mGen = Msg(embed=discord.Embed(title="✨ General").set_footer(text=U._JB_GENERAL_FOOTER))
    _mAutre = Msg(view=U._menu_va(COG, "julia", None), auteur=999)
    _vX = ui.LayoutView()
    _vX.add_item(ui.Container(ui.TextDisplay("## autre chose\n-# pas-la-marque")))
    _mX = Msg(view=_vX)
    check("reperage : menu V2 et ancien menu (deux titres) reconnus",
          U._est_menu_va(_mV2, MOI) and U._est_menu_va(_mOld, MOI) and U._est_menu_va(_mOldT, MOI))
    check("reperage : panneau US, General, autre V2, autre auteur -> pas le menu VA",
          not any(U._est_menu_va(x, MOI) for x in (_mPan, _mGen, _mX, _mAutre, Msg())))
    check("reperage : le menu VA V2 n'est pas pris pour le panneau US ni pour le General",
          not U._est_panneau_actions(_mV2, MOI) and not U._est_general(_mV2, MOI))
    check("reperage : un objet illisible ne fait pas lever",
          U._est_menu_va(types.SimpleNamespace(id=1, author=Auteur(MOI), embeds=5, components=3)) is False
          and U._menu_va_lire(object()) == (None, None))


    # _delete_old_menus : les deux formats partent, rien d'autre.
    class _SelfDel:
        bot = types.SimpleNamespace(user=types.SimpleNamespace(id=MOI))


    def salon_mixte():
        ch = Salon(920)
        intro_v = ui.View()
        intro_v.add_item(ui.Button(label="Commencer", custom_id="va_start_onboarding"))
        msgs = dict(
            v2=Msg(ch, view=U._menu_va(COG, "julia", None)),
            ancien=Msg(ch, embed=discord.Embed(title="☀️ Ton menu"), view=_ancien_menu_va()),
            jour=Msg(ch, embed=discord.Embed(title="🎬 Contenu du jour")),
            panneau=Msg(ch, view=U._jb_panel(None, "emma", 3)),
            general=Msg(ch, embed=discord.Embed(title="✨ General").set_footer(text=U._JB_GENERAL_FOOTER)),
            autre=Msg(ch, view=U._menu_va(COG, "julia", None), auteur=999),
            intro=Msg(ch, view=intro_v, content="Bienvenue"),
            texte=Msg(ch, content="bonjour"),
        )
        ch.msgs.extend(msgs.values())
        return ch, msgs


    ch, ms = salon_mixte()
    run(U.UserCog._delete_old_menus(_SelfDel(), ch))
    check("_delete_old_menus : menu V2, ancien menu et « contenu du jour » supprimes",
          ms["v2"].supprime and ms["ancien"].supprime and ms["jour"].supprime)
    check("_delete_old_menus : panneau US, General, message d'un autre, intro et texte gardes",
          not any(ms[k].supprime for k in ("panneau", "general", "autre", "intro", "texte")))
    ch, ms = salon_mixte()
    run(U.UserCog._delete_old_menus(_SelfDel(), ch, also_onboarding=True))
    check("_delete_old_menus(also_onboarding) : l'intro part aussi, le panneau reste",
          ms["intro"].supprime and not ms["panneau"].supprime and ms["v2"].supprime)

    # ===========================================================================
    # 7. POSE : _post_menu, _pin_menus_for_guild, /menu
    # ===========================================================================


    class _SelfPose:
        def __init__(self, cibles):
            self.bot = types.SimpleNamespace(user=types.SimpleNamespace(id=MOI))
            self._cibles = cibles

        def _va_targets(self, guild=None):
            return self._cibles

        async def _delete_old_menus(self, ch, also_onboarding=False):
            return await U.UserCog._delete_old_menus(self, ch, also_onboarding)


    _sp = _SelfPose([])
    chP = Salon(930)
    ok = run(U.UserCog._post_menu(_sp, chP, "julia", mention_user_id=55))
    _e = chP.envois[-1] if chP.envois else {}
    check("_post_menu : envoie la vue V2 seule (ni contenu ni embed), mention en tete, pings autorises",
          ok is True and _e.get("content") is None and _e.get("embed") is None
          and isinstance(_e.get("view"), U.ContentMenuView)
          and texte(_e["view"]).splitlines()[0] == "<@55> 👇 **Ton menu du jour est prêt !**"
          and _e.get("allowed_mentions") is not None and _e["allowed_mentions"].users is True, _e)
    chP.echec_send = http_exc(discord.Forbidden, 403, "pas le droit")
    del JOURNAL.lignes[:]
    ok = run(U.UserCog._post_menu(_sp, chP, "julia"))
    check("_post_menu : echec d'envoi -> False ET journalise (avant : avale sans trace)",
          ok is False and any("menu VA non poste" in l[2] for l in JOURNAL.lignes))

    # _pin_menus_for_guild : anciens menus (deux formats) remplaces par le V2 epingle.
    _ch1, _ms1 = salon_mixte()
    _ch2 = Salon(931)
    _vieux2 = Msg(_ch2, embed=discord.Embed(title="☀️ Ton menu").set_footer(text="Identité : julia"),
                  view=_ancien_menu_va())
    _vieux2.pinned = True
    _ch2.msgs.append(_vieux2)
    _sp = _SelfPose([(_ch1, "55", "julia"), (_ch2, "56", "julia")])
    _vrai_sleep = asyncio.sleep


    async def _sleep_rapide(t, *a, **k):
        return await _vrai_sleep(0)


    U.asyncio.sleep = _sleep_rapide
    try:
        n = run(U.UserCog._pin_menus_for_guild(_sp, types.SimpleNamespace(id=7)))
    finally:
        U.asyncio.sleep = _vrai_sleep
    _poses1 = [x for x in _ch1.msgs if U._est_menu_va(x, MOI)]
    _poses2 = [x for x in _ch2.msgs if U._est_menu_va(x, MOI)]
    check("_pin_menus_for_guild : un seul menu par salon, V2, epingle ; anciens des deux formats retires",
          n == 2 and len(_poses1) == 1 and len(_poses2) == 1 and _poses1[0].pinned and _poses2[0].pinned
          and _poses1[0].flags.components_v2 and _vieux2.supprime and _ms1["v2"].supprime
          and not _ms1["panneau"].supprime,
          (n, len(_poses1), len(_poses2)))
    check("_pin_menus_for_guild : le menu pose porte l'identite du salon, sans embed",
          U._menu_va_lire(_poses1[0])[0] == "julia" and not _poses1[0].embeds)

    # /menu
    _vrai_gui = U.get_user_identity
    U.get_user_identity = lambda uid: "julia"
    try:
        itx = Itx(message=None, channel=Salon(940))
        run(U.UserCog.menu.callback(types.SimpleNamespace(), itx))
        f = itx.response.faits
        check("/menu : repond par le menu V2 (vue seule, identite du VA)",
              f and f[0][0] == "send_message" and isinstance(f[0][2].get("view"), U.ContentMenuView)
              and "embed" not in f[0][2] and "-# Identité : `julia`" in texte(f[0][2]["view"]), f)
        U.get_user_identity = lambda uid: None
        itx = Itx(message=None, channel=Salon(940))
        run(U.UserCog.menu.callback(types.SimpleNamespace(), itx))
        check("/menu : sans identite -> refus explique, comme avant",
              "identité" in str(itx.response.faits[0][1]) and itx.response.faits[0][2].get("ephemeral"))
    finally:
        U.get_user_identity = _vrai_gui

    # ===========================================================================
    # 8. /setidentite first : l'identite se relit dans un menu V2
    # ===========================================================================
    import safe_json as _sj  # noqa: E402
    _users = TMP / "users.json"
    _sj.write(_users, {"55": {"channel_id": 950, "identity": "autre"}})
    _chI = Salon(950, name="va-bob")
    _chI.msgs.append(Msg(_chI, view=U._menu_va(COG, "julia", None, mention=55)))
    _gI = types.SimpleNamespace(id=7, name="G", text_channels=[_chI])
    _vrai_ssi = GF.set_server_identity
    GF.set_server_identity = lambda g, i: True
    # /setidentite first n'accepte qu'une identite qui EXISTE (list_identities,
    # les dossiers de data/identities). Sans ce bouchon, le test ne passait que
    # sur un poste dont le vrai data/ contient « julia » : lance avec un data/
    # vide (poste neuf, dossier isole), il echouait sans rien dire du menu V2.
    # cogs.welcome est remis en place apres la partie (_V2_MODULES).
    import cogs.welcome as _Wi
    _Wi.list_identities = lambda avec_reserves=False: ["julia", "autre"]
    try:
        itx = Itx(message=None, channel=_chI, guild=_gI, uid=4)
        itx.client.application_info = lambda: _coro_owner()

        async def _coro_owner():
            return types.SimpleNamespace(owner=types.SimpleNamespace(id=4))
        run(U.UserCog.setidentite.callback(types.SimpleNamespace(), itx, identity="first"))
    finally:
        GF.set_server_identity = _vrai_ssi
    _apres = json.loads(_users.read_text(encoding="utf-8"))
    check("/setidentite first : l'identite est relue dans le TEXTE d'un menu V2 (plus d'embed)",
          _apres["55"]["identity"] == "julia", (_apres, itx.followup.envois))

    reglages_vrais()
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)



def _v2_bloc_general():
    'Partie E : le ✨ General (3e message epingle du salon -menu US) en Components V2 -- boutons PP..Post, menus Caption, Template, Trash, Flash ; reperage, conversion, anciens jbg:, welcome.'
    import asyncio
    import json
    import logging
    import os
    import sys
    import tempfile
    import types
    from pathlib import Path
    import discord
    from discord.components import _component_factory

    RESULTATS = []


    def check(nom, ok, detail=""):
        RESULTATS.append((nom, bool(ok), detail))
        _check_v2("v2 General : " + nom, ok, "" if ok else str(detail)[:400])

    class _Journal(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lignes = []

        def emit(self, r):
            self.lignes.append((r.levelname, r.name, r.getMessage()))
            TOUT_JOURNAL.append((r.levelname, r.name, r.getMessage()))


    JOURNAL = _Journal()
    TOUT_JOURNAL = []
    logging.getLogger().addHandler(JOURNAL)
    logging.getLogger().setLevel(logging.DEBUG)

    import cogs.user as U
    import cogs.welcome as W
    import guild_features as GF
    import marques_montage as MM
    import type_identite as TI
    import brutes_off as BO

    TMP = Path(tempfile.mkdtemp(prefix="v2_general_"))
    U._JB_PANEL_STORE = TMP / "us_panels.json"
    U._JB_GENERAL_STORE = TMP / "us_general_panels.json"
    _vrai_data = os.path.realpath("data")
    for _f in (U._JB_PANEL_STORE, U._JB_GENERAL_STORE):
        assert not os.path.realpath(_f).startswith(_vrai_data + os.sep), _f

    IRT = discord.InteractionResponseType
    ui = discord.ui

    # ---------------------------------------------------------------------------
    # Donnees simulees : liens model -> reserves, reserves, brutes
    # ---------------------------------------------------------------------------
    LIENS = {
        "lola": (["blonde"], []),
        "duo": (["blonde", "brune"], []),
        "six": (["r1", "r2", "r3", "r4", "r5", "r6"], []),
        "nue": ([], [("zfr", "reserve du marche FR")]),
        "mixte": (["blonde", "chloé x"], [("zfr", "reserve du marche FR")]),
    }
    RESERVES = {"blonde", "brune", "r1", "r2", "r3", "r4", "r5", "r6", "zfr"}
    BRUTES = {}          # model -> liste ; absente = une brute


    def _liens(m):
        if m == "casse":
            raise RuntimeError("fichier des liens illisible")
        r, e = LIENS.get(m, ([], []))
        return list(r), list(e)


    TI.reserves_liees = _liens
    TI.est_reserve = lambda n: (n or "").lower() in RESERVES
    BO.lister = lambda dossier, extensions=None, **k: list(BRUTES.get(Path(dossier).parent.name, ["b.mp4"]))

    # ---------------------------------------------------------------------------
    # Faux objets Discord (repris de md_verif.py)
    # ---------------------------------------------------------------------------
    _ids = iter(range(10_000, 99_999))


    def http_exc(cls=discord.HTTPException, status=400, texte="refus simule"):
        return cls(types.SimpleNamespace(status=status, reason="x"), texte)


    class Auteur:
        def __init__(self, i):
            self.id = i
            self.bot = True


    MOI = 1


    def comps_de(vue):
        if vue is None:
            return []
        return [_component_factory(d) for d in vue.to_components()]


    class Msg:
        def __init__(self, ch=None, embed=None, view=None, ephemere=False, auteur=MOI, content=None):
            self.id = next(_ids)
            self.ch = ch
            self.embeds = [embed] if embed is not None else []
            self.content = content
            self.view = view
            self.components = comps_de(view)
            self.author = Auteur(auteur)
            self.pinned = False
            v2 = bool(view is not None and view.has_components_v2())
            self.flags = types.SimpleNamespace(ephemeral=ephemere, components_v2=v2)
            self.edits = []
            self.echec_edit = None
            self.supprime = False

        async def edit(self, **k):
            self.edits.append(k)
            if self.echec_edit is not None:
                raise self.echec_edit
            if "view" in k:
                v = k["view"]
                if v is not None and v.has_components_v2():
                    # Discord refuse un V2 qui garderait texte ou embed.
                    if (self.embeds and "embed" not in k and "embeds" not in k) or \
                            (self.content and "content" not in k):
                        raise http_exc(texte="V2 avec embed/texte restant")
                    self.flags.components_v2 = True
                self.view = v
                self.components = comps_de(v)
            if "embed" in k:
                self.embeds = [k["embed"]] if k["embed"] is not None else []
            if "content" in k:
                self.content = k["content"]
            return self

        async def delete(self):
            self.supprime = True
            if self.ch is not None and self in self.ch.msgs:
                self.ch.msgs.remove(self)

        async def pin(self, **k):
            self.pinned = True


    class Salon:
        def __init__(self, cid=4242, name="zz-menu"):
            self.id = cid
            self.name = name
            self.msgs = []
            self.overwrites = {}
            self.guild = types.SimpleNamespace(id=7, emojis=[], text_channels=[self])
            self.echec_send = None
            self.fetchs = 0
            self.lectures_epingles = 0

        async def pins(self):
            self.lectures_epingles += 1
            return [m for m in reversed(self.msgs) if m.pinned]

        async def send(self, content=None, embed=None, view=None, **k):
            if self.echec_send:
                raise self.echec_send
            m = Msg(self, embed=embed, view=view, content=content)
            self.msgs.append(m)
            return m

        async def fetch_message(self, i):
            self.fetchs += 1
            for m in self.msgs:
                if m.id == int(i):
                    return m
            raise http_exc(discord.NotFound, 404, "absent")

        def get_partial_message(self, i):
            salon = self

            class _P:
                id = int(i)

                async def edit(self, **k):
                    for m in salon.msgs:
                        if m.id == int(i):
                            return await m.edit(**k)
                    raise http_exc(discord.NotFound, 404, "absent")

                async def delete(self):
                    for m in salon.msgs:
                        if m.id == int(i):
                            return await m.delete()
                    raise http_exc(discord.NotFound, 404, "absent")
            return _P()

        async def purge(self, limit=200, check=None):
            partis = [m for m in self.msgs if check(m)]
            self.msgs[:] = [m for m in self.msgs if not check(m)]
            return partis

        async def history(self, limit=40):
            for m in list(reversed(self.msgs))[:limit]:
                yield m


    class DeuxReponses(Exception):
        pass


    class Rep:
        def __init__(self, itx):
            self.itx = itx
            self._type = None
            self.faits = []
            self.echec_edit = None
            self.doubles = 0

        def is_done(self):
            return self._type is not None

        @property
        def type(self):
            return self._type

        def _marquer(self, t, quoi, a, k):
            if self._type is not None:
                self.doubles += 1
                raise DeuxReponses(quoi)
            self._type = t
            self.faits.append((quoi, a, k))

        async def send_message(self, *a, **k):
            self._marquer(IRT.channel_message, "send_message", a, k)

        async def edit_message(self, *a, **k):
            if self.echec_edit is not None and self._type is None:
                e, self.echec_edit = self.echec_edit, None
                raise e
            m = self.itx.message
            if m is not None and "view" in k:
                await m.edit(**k)          # Discord refuse AVANT de compter la reponse
            self._marquer(IRT.message_update, "edit_message", a, k)

        async def defer(self, ephemeral=False, thinking=False):
            self._marquer(IRT.deferred_channel_message if thinking else IRT.deferred_message_update,
                          "defer", (), dict(ephemeral=ephemeral, thinking=thinking))

        async def send_modal(self, modal):
            self._marquer(IRT.modal, "send_modal", (modal,), {})
            self.modal = modal


    class Suivi:
        def __init__(self, itx):
            self.itx = itx
            self.envois = []
            self.edits = []

        async def send(self, content=None, **k):
            if not self.itx.response.is_done():
                raise AssertionError("followup avant toute reponse")
            self.envois.append((content, k))
            return Msg(ephemere=bool(k.get("ephemeral")))

        async def edit_message(self, mid, **k):
            if not self.itx.response.is_done():
                raise AssertionError("followup.edit avant toute reponse")
            self.edits.append((mid, k))
            m = self.itx.message
            if m is not None and m.id == mid:
                await m.edit(**k)


    class Cog:
        """Faux UserCog : _run_for_model enregistre l'appel (brute_de compris)
        et repond selon `mode` (defer | defer_eph | thinking | send_eph | rien | leve)."""

        def __init__(self):
            self.appels = []
            self.mode = "defer"

        async def _run_for_model(self, interaction, model, cmd, count=None,
                                 supports_count=False, brute_de=None):
            self.appels.append((model, getattr(cmd, "__name__", cmd), count, supports_count, brute_de))
            mode = self.mode
            if mode == "defer":
                await interaction.response.defer()
                await interaction.followup.send("contenu")
            elif mode == "defer_eph":
                await interaction.response.defer(ephemeral=True)
                await interaction.followup.send("choix", ephemeral=True)
            elif mode == "thinking":
                await interaction.response.defer(thinking=True)
                await interaction.followup.send("fini")
            elif mode == "send_eph":
                await interaction.response.send_message("Aucune brute", ephemeral=True)
            elif mode == "leve":
                raise RuntimeError("panne simulee")


    for _a in U._JB_ACTIONS_US:
        _nom = _a[2]

        def _f(*a, _n=_nom, **k):
            return None
        _f.__name__ = _nom
        setattr(Cog, _nom, staticmethod(_f))
    COG = Cog()


    class Itx:
        def __init__(self, message=None, channel=None, guild=None, uid=5):
            self.message = message
            self.channel = channel
            self.guild = guild or types.SimpleNamespace(id=7, emojis=[])
            self.user = types.SimpleNamespace(id=uid, roles=[])
            self.client = types.SimpleNamespace(
                get_cog=lambda n: COG if n == "UserCog" else None,
                user=types.SimpleNamespace(id=MOI))
            self.response = Rep(self)
            self.followup = Suivi(self)
            self.orig_edits = []
            self.data = {}

        async def edit_original_response(self, **k):
            if self.response.type not in (IRT.deferred_message_update, IRT.message_update):
                raise AssertionError("@original n'est pas le message du clic")
            self.orig_edits.append(k)
            if self.message is not None:
                await self.message.edit(**k)

        async def original_response(self):
            return Msg(ephemere=True)


    def run(coro):
        return asyncio.run(coro)


    async def attendre_fond():
        for _ in range(5):
            await asyncio.sleep(0)
        if U._JB_TACHES:
            await asyncio.gather(*list(U._JB_TACHES), return_exceptions=True)


    def lancer(coro):
        async def _t():
            r = await coro
            await attendre_fond()
            return r
        return asyncio.run(_t())


    def items(vue):
        return list(vue.walk_children())


    def rangees(vue):
        """[[custom_id…] par ActionRow], dans l'ordre."""
        out = []
        for i in items(vue):
            if isinstance(i, ui.ActionRow):
                out.append([c.custom_id for c in i.children])
        return out


    def selects(vue):
        return [i for i in items(vue) if isinstance(i, ui.DynamicItem) and isinstance(i.item, ui.Select)]


    def boutons(vue):
        return [i for i in items(vue) if isinstance(i, ui.DynamicItem) and isinstance(i.item, ui.Button)]


    def limites(vue):
        pb = []
        if vue.total_children_count > 40:
            pb.append("composants %d > 40" % vue.total_children_count)
        if vue.content_length() > 4000:
            pb.append("texte %d > 4000" % vue.content_length())
        for i in items(vue):
            base = i.item if isinstance(i, ui.DynamicItem) else i
            if isinstance(i, ui.ActionRow) and len(i.children) > 5:
                pb.append("rangee a %d" % len(i.children))
            if isinstance(i, ui.TextDisplay) and U._long_discord(i.content) > 4000:
                pb.append("texte (utf-16) %d" % U._long_discord(i.content))
            cid = getattr(base, "custom_id", None)
            if cid and len(cid) > 100:
                pb.append("custom_id %d" % len(cid))
            if isinstance(base, ui.Button) and base.label and U._long_discord(base.label) > 80:
                pb.append("libelle bouton %r" % base.label)
            if isinstance(base, ui.Select):
                if len(base.options) > 25 or not base.options:
                    pb.append("options %d" % len(base.options))
                if base.placeholder and len(base.placeholder) > 150:
                    pb.append("placeholder")
                for o in base.options:
                    if U._long_discord(o.label) > 100:
                        pb.append("option %r" % o.label)
                    if o.description and U._long_discord(o.description) > 100:
                        pb.append("description %r" % o.description)
        json.dumps(vue.to_components())
        return pb


    def texte(vue):
        return "\n".join(i.content for i in items(vue) if isinstance(i, ui.TextDisplay))


    def interactifs(vue):
        return [i for i in items(vue) if isinstance(i, (ui.Button, ui.Select, ui.DynamicItem))]


    GUILD_IC = types.SimpleNamespace(
        id=7, emojis=[discord.PartialEmoji(name=n, id=20000 + k)
                      for k, n in enumerate(sorted(set(U._ICONES_ACTIONS.values())))])

    VRAI = dict(can=U._jb_can_use, res=U._refus_reserve_jb, gen=U._jb_general_maj,
                us=GF.is_us_guild, marche=U.marche_du_membre, general=U._jb_general)
    U._jb_can_use = lambda i: True
    U._refus_reserve_jb = lambda i: ""
    U.marche_du_membre = lambda m: "us"

    _TRASH = MM.marque("trash")["actions"]
    _FLASH = MM.marque("flash")["actions"]
    # La liste blanche d'AVANT (e5a5f53) : les 13 boutons de l'ancien General.
    _ANCIENNES_CLES = {"pp", "bio", "story", "storycta", "post", "reelcaption", "capbanger",
                       "reelmonte", "templatebanger", _TRASH[0], _TRASH[1], _FLASH[0], _FLASH[1]}

    # ===========================================================================
    # 1. LA TABLE DU GENERAL
    # ===========================================================================
    check("table : boutons = PP, Bio, Story, Story CTA, Post",
          U._JB_GEN_BOUTONS == ("pp", "bio", "story", "storycta", "post"), U._JB_GEN_BOUTONS)
    check("table : menus Caption, Template, Trash, Flash, dans cet ordre (celui de _FAMILLES_MENU)",
          [f.cle for f in U._JB_GEN_FAMILLES] == ["caption", "template", "trash", "flash"]
          and [(f.emoji, f.nom) for f in U._JB_GEN_FAMILLES]
          == [(f.emoji, f.nom) for f in U._FAMILLES_MENU], U._JB_GEN_FAMILLES)
    check("table : chaque menu = matiere seule + version etoilee (Caption, ⭐ Caption…)",
          [f.actions for f in U._JB_GEN_FAMILLES]
          == [("reelcaption", "capbanger"), ("reelmonte", "templatebanger"),
              tuple(_TRASH[:2]), tuple(_FLASH[:2])],
          [f.actions for f in U._JB_GEN_FAMILLES])
    check("table : libelles = Caption, ⭐ Caption, Template, ⭐ Template, Trash, ⭐ Trash, Flash, ⭐ Flash",
          [U._jb_action(a)[1] for f in U._JB_GEN_FAMILLES for a in f.actions]
          == ["💬 Caption", "⭐ Caption", "🎞️ Template", "⭐ Template", "💀 Trash", "⭐ Trash",
              "⚡ Flash", "⭐ Flash"],
          [U._jb_action(a)[1] for f in U._JB_GEN_FAMILLES for a in f.actions])
    _brut = {"brute", "brutbanger", "brutchoix", "brutcaption", "montagebanger", "bruttemplate",
             "templatebrut", _TRASH[2], _TRASH[3], _FLASH[2], _FLASH[3]}
    check("table : aucun Brut dans le General (ni menu Brut, ni variante a brute ⭐)",
          not (_brut & set(U._JB_GENERAL_RANGEES)) and "brut" not in [f.cle for f in U._JB_GEN_FAMILLES])
    check("table : liste blanche = les 13 cles d'avant (anciens boutons jbg:a: toujours valides)",
          set(U._JB_GENERAL_RANGEES) == _ANCIENNES_CLES,
          set(U._JB_GENERAL_RANGEES) ^ _ANCIENNES_CLES)
    check("table : rangees prevues deduites (1 = boutons, 2..5 = menus)",
          U._JB_GENERAL_RANGEES == {**{k: 1 for k in U._JB_GEN_BOUTONS},
                                    "reelcaption": 2, "capbanger": 2, "reelmonte": 3,
                                    "templatebanger": 3, _TRASH[0]: 4, _TRASH[1]: 4,
                                    _FLASH[0]: 5, _FLASH[1]: 5}, U._JB_GENERAL_RANGEES)
    check("table : toutes les cles existent dans _JB_ACTIONS_US et ont une explication (menus)",
          set(U._JB_GENERAL_RANGEES) <= {a[0] for a in U._JB_ACTIONS_US}
          and all(U._EXPLICATIONS.get(a) for f in U._JB_GEN_FAMILLES for a in f.actions))
    check("table : _JB_GEN_BRUTE inchange (caption, ⭐ caption, ⭐ template, trash/flash et ⭐)",
          U._JB_GEN_BRUTE == frozenset({"reelcaption", "capbanger", "templatebanger",
                                        _TRASH[0], _TRASH[1], _FLASH[0], _FLASH[1]}))

    # ===========================================================================
    # 2. LA VUE V2 : structure, etats, limites
    # ===========================================================================


    def est_v2_bloc(v):
        return (isinstance(v, ui.LayoutView) and v.has_components_v2() and len(v.children) == 1
                and isinstance(v.children[0], ui.Container)
                and v.children[0].accent_colour == discord.Colour.teal()
                and isinstance(v.children[0].children[0], ui.TextDisplay)
                and v.timeout is None)


    def marque_fin(v):
        return texte(v).splitlines()[-1] == "-# panneau-general-us"


    # Etats SANS actions : texte seul.
    _etats = {
        "attente « _ »": (U._jb_general(None, "_"), "choisis une model au-dessus"),
        "model vide": (U._jb_general(None, None), "choisis une model au-dessus"),
        "model = reserve": (U._jb_general(None, "blonde"), "est une réserve"),
        "liens illisibles": (U._jb_general(None, "casse"), "Liens des réserves illisibles"),
        "aucune reserve": (U._jb_general(None, "nue"), "aucune réserve liée à Nue"),
        "nom illisible": (U._jb_general(None, "chloé x"), "illisible"),
    }
    for nom_e, (v_, attendu) in _etats.items():
        check("etat %s : bloc V2, texte seul (aucun bouton ni menu), marque en derniere ligne" % nom_e,
              est_v2_bloc(v_) and not interactifs(v_) and attendu in texte(v_) and marque_fin(v_)
              and not limites(v_) and texte(v_).startswith("## ✨ General"),
              texte(v_))
    check("etat aucune reserve : liens ecartes et leur raison DITS, chemin du site",
          "`zfr` : reserve du marche FR" in texte(_etats["aucune reserve"][0])
          and "Réserves liées" in texte(_etats["aucune reserve"][0]))
    check("etat « _ » : annonce captions, templates, trash et flash",
          "captions, templates, trash et flash" in texte(_etats["attente « _ »"][0]))

    for _g, _nomg in ((None, "sans icones"), (GUILD_IC, "avec icones")):
        v = U._jb_general(None, "lola", 3, guild=_g)
        check("1 reserve (%s) : bloc V2 turquoise, texte en tete, dans les limites" % _nomg,
              est_v2_bloc(v) and not limites(v), limites(v))
        check("1 reserve (%s) : rangees = [Quantite], [PP, Bio, Story, Story CTA, Post], 4 menus" % _nomg,
              rangees(v) == [["jbg:qb:lola:blonde:3"],
                             ["jbg:a:lola:blonde:%s:3" % k for k in ("pp", "bio", "story", "storycta", "post")],
                             ["jbg:s:lola:blonde:caption:3"], ["jbg:s:lola:blonde:template:3"],
                             ["jbg:s:lola:blonde:trash:3"], ["jbg:s:lola:blonde:flash:3"]], rangees(v))
        _sel = selects(v)
        check("1 reserve (%s) : intitules 💬 Caption…, 🎞️ Template…, 💀 Trash…, ⚡ Flash…" % _nomg,
              [s_.item.placeholder for s_ in _sel] == ["💬 Caption…", "🎞️ Template…", "💀 Trash…", "⚡ Flash…"],
              [s_.item.placeholder for s_ in _sel])
        ok_o, det = True, []
        for s_, f in zip(_sel, U._JB_GEN_FAMILLES):
            if [o.value for o in s_.item.options] != list(f.actions):
                ok_o = False
                det.append((f.cle, [o.value for o in s_.item.options]))
            for o in s_.item.options:
                lib = U._jb_action(o.value)[1]
                icone = U.icones_actions(_g).get(o.value)
                if icone is not None:
                    if o.emoji is None or o.emoji.name != icone.name or o.label != U._libelle_sans_emoji(lib):
                        ok_o = False
                        det.append(("icone", o.value, o.label, o.emoji))
                elif o.emoji is not None or o.label != lib:
                    ok_o = False
                    det.append(("sans icone", o.value, o.label, o.emoji))
                if o.description != U._EXPLICATIONS[o.value] or o.default:
                    ok_o = False
                    det.append(("desc/defaut", o.value))
            if s_.item.min_values != 1 or s_.item.max_values != 1:
                ok_o = False
        check("1 reserve (%s) : options = libelle de production, explication, icone sinon emoji" % _nomg,
              ok_o, det)
        _bt = boutons(v)
        check("1 reserve (%s) : PP, Bio, Story, Story CTA, Post restent des BOUTONS (libelles de production)" % _nomg,
              [b.key for b in _bt if isinstance(b, U.JBGenButton)] == list(U._JB_GEN_BOUTONS)
              and all((b.item.emoji is not None) == (U.icones_actions(_g).get(b.key) is not None)
                      for b in _bt if isinstance(b, U.JBGenButton)))
        _cles_bt = {b.key for b in _bt if isinstance(b, U.JBGenButton)}
        check("1 reserve (%s) : Caption/Template/Trash/Flash ne sont PLUS des boutons" % _nomg,
              not (_cles_bt & {a for f in U._JB_GEN_FAMILLES for a in f.actions}))
        t = texte(v)
        check("1 reserve (%s) : texte = titre, contenu de la reserve, brute de la model, quantite, -content, marque" % _nomg,
              t.splitlines()[0] == "## ✨ General — Blonde pour Lola"
              and "Contenu de la réserve **Blonde**" in t and "brute de **Lola**" in t
              and "Quantité : 3 média par action" in t and "-content" in t and marque_fin(v), t)
        _js = json.dumps(v.to_components(), ensure_ascii=False)
        check("1 reserve (%s) : ni Brut, ni Trends, ni marque du panneau ou du menu VA" % _nomg,
              ":brut" not in _js and "Trends" not in _js and "panneau-actions-us" not in _js
              and "menu-contenu-va" not in _js)

    v1 = U._jb_general(None, "lola", 3)
    check("1 reserve : 18 composants (pas de bouton de reserve)", v1.total_children_count == 18,
          v1.total_children_count)
    v2 = U._jb_general(None, "duo", 5, reserve="brune")
    r2 = rangees(v2)
    check("2 reserves : 1re rangee = boutons de reserve + Quantite, la reserve choisie est active",
          r2[0] == ["jbg:r:duo:blonde:5", "jbg:r:duo:brune:5", "jbg:qb:duo:brune:5"]
          and [b.item.style for b in boutons(v2)[:2]] == [discord.ButtonStyle.secondary,
                                                          discord.ButtonStyle.success]
          and r2[2] == ["jbg:s:duo:brune:caption:5"] and "2 réserves liées" in texte(v2)
          and texte(v2).splitlines()[0] == "## ✨ General — Brune pour Duo", r2)
    v6 = U._jb_general(None, "six", 3, reserve="r6", guild=GUILD_IC)
    check("6 reserves, active = la 6e : 4 boutons (l'active gardee) + Quantite, les autres DITES",
          rangees(v6)[0] == ["jbg:r:six:r1:3", "jbg:r:six:r2:3", "jbg:r:six:r3:3", "jbg:r:six:r6:3",
                             "jbg:qb:six:r6:3"]
          and "+2 autre(s)" in texte(v6) and "r4, r5" in texte(v6) and not limites(v6)
          and v6.total_children_count == 22, (rangees(v6)[0], texte(v6)))
    vr = U._jb_general(None, "duo", 3, reserve="inconnue")
    check("reserve demandee non liee -> retombe sur la premiere liee",
          rangees(vr)[0][-1] == "jbg:qb:duo:blonde:3")
    vm = U._jb_general(None, "mixte", 3)
    check("reserve au nom illisible : ecartee EN LE DISANT, le reste sert",
          "nom illisible dans un bouton Discord" in texte(vm) and "`zfr`" in texte(vm)
          and rangees(vm)[0] == ["jbg:qb:mixte:blonde:3"] and not limites(vm), texte(vm))
    vq = U._jb_general(None, "lola", "abc")
    check("quantite illisible -> 3", rangees(vq)[0] == ["jbg:qb:lola:blonde:3"])

    # Noms longs : ce qui tient, ce qui ne tient pas.
    _m40, _r40 = "m" * 40, "r" * 40
    LIENS[_m40] = ([_r40, "r" * 39 + "b"], [])
    vL = U._jb_general(None, _m40, 100, guild=GUILD_IC)
    check("noms de 40 + quantite 100 : tout tient (custom_id <= 100)",
          not limites(vL) and len(selects(vL)) == 4 and rangees(vL)[0][-1].startswith("jbg:qb:"),
          limites(vL))
    _m60 = "n" * 60
    LIENS[_m60] = (["s" * 40], [])
    del JOURNAL.lignes[:]
    vT = U._jb_general(None, _m60, 100)
    check("noms trop longs : General SANS boutons qui le dit, journalise, marque gardee",
          not interactifs(vT) and "trop longs" in texte(vT) and marque_fin(vT)
          and any("custom_id de" in l[2] for l in JOURNAL.lignes), texte(vT))
    _m40b = "p" * 40
    LIENS[_m40b] = (["a", "y" * 45], [])
    vT2 = U._jb_general(None, _m40b, 100)
    check("noms trop longs pour une reserve VOISINE (pas l'active) : bloque aussi -- son bouton "
          "menerait a un General sans boutons (regle d'avant gardee)",
          not interactifs(vT2) and "trop longs" in texte(vT2), texte(vT2))
    check("_jb_general_ids_poses : couvre reserves, quantite, boutons ET menus",
          sorted(i.split(":")[1] for i in U._jb_general_ids_poses("m", ["a", "b"], "a", 3))
          == sorted(["r", "r", "qb"] + ["a"] * 5 + ["s"] * 4))

    # Texte trop long (liens ecartes innombrables) : coupe, marque gardee.
    LIENS["bavarde"] = (["blonde"], [("x%03d" % i, "raison " + "tres longue " * 30) for i in range(40)])
    LIENS["bavarde2"] = (["blonde"] + ["r%03d" % i for i in range(300)], [])
    for _nb in ("bavarde", "bavarde2"):
        del JOURNAL.lignes[:]
        vB_ = U._jb_general(None, _nb, 3)
        check("texte (%s) : sous 4000, marque en derniere ligne" % _nb,
              not limites(vB_) and marque_fin(vB_) and U._long_discord(texte(vB_)) <= 4000,
              (U._long_discord(texte(vB_)), limites(vB_)))
    LIENS["enorme"] = (["blonde"], [("x", "é" * 5000)])
    del JOURNAL.lignes[:]
    vE = U._jb_general(None, "enorme", 3)
    check("texte enorme : coupe a 4000, journalise, marque gardee",
          U._long_discord(texte(vE)) <= 4000 and marque_fin(vE) and texte(vE).count("…") >= 1
          and any("texte trop long" in l[2] for l in JOURNAL.lignes), U._long_discord(texte(vE)))

    # Titre : jamais « menu » ni « Jailbreak ».
    LIENS["menuxx"] = (["jailbreaky"], [])
    RESERVES.add("jailbreaky")
    vW = U._jb_general(None, "menuxx", 3)
    check("titre : un nom contenant « menu »/« jailbreak » retombe sur « ✨ General »",
          texte(vW).splitlines()[0] == "## ✨ General", texte(vW).splitlines()[0])

    # Menu sans option : retire ET dit.
    _fam_sauve = U._JB_GEN_FAMILLES
    try:
        U._JB_GEN_FAMILLES = _fam_sauve + (U._Famille("zzvide", "❔", "Vide", ("inexistante",)),)
        del JOURNAL.lignes[:]
        vV = U._jb_general(None, "lola", 3)
        check("menu vide : pas pose (Discord refuserait tout), dit dans le texte, journalise",
              all("zzvide" not in c for rr in rangees(vV) for c in rr)
              and "inexistante" in texte(vV) and "menu zzvide" in texte(vV)
              and any("inexistante" in l[2] for l in JOURNAL.lignes) and not limites(vV), texte(vV))
    finally:
        U._JB_GEN_FAMILLES = _fam_sauve

    # ===========================================================================
    # 3. REPERAGE DANS LES EPINGLES : les deux formats
    # ===========================================================================
    _eg = discord.Embed(title="✨ General — Blonde pour Lola")
    _eg.set_footer(text="panneau-general-us")
    m_gen_old = Msg(embed=_eg)
    m_gen_v2 = Msg(view=U._jb_general(None, "lola", 3))
    m_gen_v2_0 = Msg(view=U._jb_general(None, "_"))
    m_pan_v2 = Msg(view=U._jb_panel(None, "emma", 3))
    _ep = discord.Embed(title="🔓 Emma")
    _ep.set_footer(text="panneau-actions-us")
    m_pan_old = Msg(embed=_ep)
    m_menu = Msg(embed=discord.Embed(title="🔓 Menu Jailbreak US"))
    m_autre = Msg(view=U._jb_general(None, "lola", 3), auteur=999)
    check("reperage : ancien General (pied d'embed) reconnu", U._est_general(m_gen_old, MOI))
    check("reperage : General V2 reconnu (message recu, composants Discord), attente et plein",
          U._est_general(m_gen_v2, MOI) and U._est_general(m_gen_v2_0, MOI)
          and U._est_general(m_gen_v2))
    check("reperage : panneau (2 formats), menu, autre auteur : PAS le General",
          not U._est_general(m_pan_v2, MOI) and not U._est_general(m_pan_old, MOI)
          and not U._est_general(m_menu, MOI) and not U._est_general(m_autre, MOI))
    check("reperage : le General V2 n'est ni le panneau d'actions ni le menu VA",
          not U._est_panneau_actions(m_gen_v2, MOI) and not U._est_panneau_actions(m_gen_v2_0, MOI)
          and not U._est_menu_va(m_gen_v2, MOI))
    check("reperage : ne leve jamais (None, objet quelconque)",
          U._est_general(None) is False and U._est_general(object()) is False)
    check("conversion : kw = vider texte ET embed pour l'ancien General, rien pour le V2",
          U._jb_kw_format(m_gen_old) == {"content": None, "embed": None} and U._jb_kw_format(m_gen_v2) == {})

    # ===========================================================================
    # 4. MOTIFS DYNAMIQUES ET REDEMARRAGE
    # ===========================================================================


    class BotF:
        def __init__(self):
            self.vues, self.dyn = [], []

        def add_view(self, v, message_id=None):
            self.vues.append(v)

        def add_dynamic_items(self, *its):
            self.dyn.extend(its)


    _bot = BotF()
    del JOURNAL.lignes[:]
    run(U.UserCog.cog_load(types.SimpleNamespace(
        bot=_bot, daily_menu=types.SimpleNamespace(is_running=lambda: True))))
    check("cog_load : JBGenMenu enregistre avec les boutons du General, aucun echec au journal",
          {U.JBGenMenu, U.JBGenButton, U.JBGenQtyBouton, U.JBGenReserveBouton} <= set(_bot.dyn)
          and not [l for l in JOURNAL.lignes if "cog_load" in l[2]],
          [l for l in JOURNAL.lignes if "cog_load" in l[2]])
    _motifs = [(c.__name__, c.__discord_ui_compiled_template__) for c in _bot.dyn]
    _persist = {it.custom_id for v in _bot.vues for it in v.walk_children()
                if not isinstance(it, ui.DynamicItem) and getattr(it, "custom_id", None)}


    def qui(cid):
        if cid in _persist:
            return ["vue"]
        return [n for n, p in _motifs if p.fullmatch(cid)]


    _neufs = []
    for m_, q_ in (("lola", 1), ("duo", 3), ("six", 100), (_m40, 100)):
        for res_ in (None, "brune", "r6"):
            _neufs += [c for rr in rangees(U._jb_general(None, m_, q_, reserve=res_, guild=GUILD_IC)) for c in rr]
    _mauvais = [(c, qui(c)) for c in _neufs if len(qui(c)) != 1]
    check("motifs : chaque custom_id du General V2 est servi par UN element exactement",
          not _mauvais and len(_neufs) > 100, _mauvais[:5])
    check("motifs : les menus « jbg:s: » vont a JBGenMenu et a lui seul",
          all(qui(c) == ["JBGenMenu"] for c in _neufs if c.startswith("jbg:s:"))
          and any(c.startswith("jbg:s:") for c in _neufs))
    _anciens = (["jbg:a:lola:blonde:%s:3" % k for k in sorted(_ANCIENNES_CLES)]
                + ["jbg:qb:lola:blonde:3", "jbg:r:lola:blonde:3"]
                + ["jbus:a:emma:%s:3" % a[0] for a in U._JB_ACTIONS_US]
                + ["jbus:s:emma:%s:3" % f.cle for f in U._FAMILLES_PANNEAU]
                + ["jbus:qb:emma:3", "jbus:q:emma:3", "jbus:m:emma"]
                + ["jbus:f:emma:%s:3" % f.cle for f in U._FAMILLES_MENU])
    _mauv2 = [(c, qui(c)) for c in _anciens if len(qui(c)) != 1]
    check("motifs : tous les ANCIENS custom_id (jbg:a/qb/r, jbus:*) servis par UN element",
          not _mauv2, _mauv2)
    _tG = U.JBGenMenu.__discord_ui_compiled_template__
    check("motifs : jbg:s: ne capture aucun ancien custom_id",
          not any(_tG.fullmatch(c) for c in _anciens))


    class EtatF:
        """Etat minimal pour un vrai ViewStore de discord.py."""


    async def _redemarrage(cid, valeur, message, ctype=3):
        """Un clic sur un General DEJA poste, apres un redemarrage : un ViewStore
        neuf, les motifs de cog_load, le vrai parcours de discord.py
        (from_message -> from_custom_id -> callback)."""
        from discord.ui.view import ViewStore
        store = ViewStore(EtatF())
        store.add_dynamic_items(*_bot.dyn)
        itx = Itx(message=message, channel=message.ch)
        itx.data = {"custom_id": cid, "component_type": ctype}
        if valeur is not None:
            itx.data["values"] = [valeur]
        store.dispatch_view(ctype, cid, itx)
        for _ in range(20):
            await asyncio.sleep(0)
        await attendre_fond()
        return itx


    def general_epingle(model="lola", qty=3, res=None, cid=5151, guild=None):
        ch = Salon(cid)
        m = Msg(ch, view=U._jb_general(None, model, qty, reserve=res, guild=guild))
        m.pinned = True
        ch.msgs.append(m)
        U._jb_general_set(ch.id, m.id)
        return ch, m


    def remis(vue, n=4):
        return (vue is not None and isinstance(vue, ui.LayoutView)
                and all(not o.default for s_ in selects(vue) for o in s_.item.options)
                and len(selects(vue)) == n)


    U._JB_PANNEAU_COURANT.clear()
    _chR, _mR = general_epingle("lola", 5)
    COG.appels.clear()
    COG.mode = "defer"
    _iR = run(_redemarrage("jbg:s:lola:blonde:trash:5", _TRASH[1], _mR))
    check("redemarrage : un menu du General deja poste repond, l'action part (reserve, brute de la model)",
          COG.appels == [("blonde", U._jb_action(_TRASH[1])[2], 5, True, "lola")], COG.appels)
    check("redemarrage : ... une seule reponse, le General redessine (menus sur leur intitule)",
          _iR.response.doubles == 0 and len(_iR.response.faits) == 1 and _mR.edits
          and remis(_mR.edits[-1]["view"]), (_iR.response.faits, len(_mR.edits)))
    COG.appels.clear()
    _iR2 = run(_redemarrage("jbg:s:lola:blonde:caption:5", "brutcaption", _mR))
    check("redemarrage : une variante Brut forgee dans le menu Caption est REFUSEE",
          not COG.appels and _iR2.response.faits and _iR2.response.faits[0][0] == "edit_message"
          and "inconnue" in str(_iR2.followup.envois), (_iR2.response.faits, _iR2.followup.envois))
    COG.appels.clear()
    _iR3 = run(_redemarrage("jbg:a:lola:blonde:pp:5", None, _mR, ctype=2))
    check("redemarrage : un bouton PP du General V2 repond (jbg:a:)",
          COG.appels == [("blonde", "profilepic", 5, True, "lola")], COG.appels)

    # ===========================================================================
    # 5. CLIC DANS UN MENU DU GENERAL (callbacks simules)
    # ===========================================================================


    def choisir(menu, valeur, message, channel, mode="defer"):
        COG.mode = mode
        menu.item._values = [valeur]
        itx = Itx(message=message, channel=channel, guild=GUILD_IC)
        lancer(menu.callback(itx))
        menu.item._values = []
        return itx


    U._JB_PANNEAU_COURANT.clear()
    for fam in U._JB_GEN_FAMILLES:
        for cle in fam.actions:
            ch, m = general_epingle("duo", 4, res="brune", cid=77)
            COG.appels.clear()
            itx = choisir(U.JBGenMenu("duo", "brune", fam.cle, 4), cle, m, ch)
            ent = U._jb_action(cle)
            _v = m.edits[0]["view"] if m.edits else None
            ok = (COG.appels == [("brune", ent[2], 4, bool(ent[3]), "duo")]
                  and itx.response.doubles == 0 and len(itx.response.faits) == 1
                  and len(m.edits) == 1 and remis(_v)
                  and rangees(_v)[0] == ["jbg:r:duo:blonde:4", "jbg:r:duo:brune:4", "jbg:qb:duo:brune:4"])
            if not ok:
                check("menu %s / %s : action lancee comme le bouton, menu remis" % (fam.cle, cle), False,
                      (COG.appels, itx.response.faits, len(m.edits)))
                break
        else:
            check("menu %s : ses %d options lancent _run_for_model (reserve, brute de la model, quantite), "
                  "une reponse, le General revient sur son intitule, reserve et quantite gardees"
                  % (fam.cle, len(fam.actions)), True)

    # Meme appel qu'un bouton d'avant (jbg:a:) pour la meme cle.
    for cle in (U._JB_GEN_FAMILLES[0].actions + U._JB_GEN_FAMILLES[2].actions):
        ch, m = general_epingle("lola", 3, cid=78)
        COG.appels.clear()
        COG.mode = "defer"
        fam = [f for f in U._JB_GEN_FAMILLES if cle in f.actions][0]
        choisir(U.JBGenMenu("lola", "blonde", fam.cle, 3), cle, m, ch)
        itxB = Itx(message=m, channel=ch)
        lancer(U.JBGenButton("lola", "blonde", cle, 3).callback(itxB))
        if len(COG.appels) != 2 or COG.appels[0] != COG.appels[1]:
            check("menu = bouton d'avant (%s)" % cle, False, COG.appels)
            break
    else:
        check("menu et ancien bouton jbg:a: font EXACTEMENT le meme appel (caption, trash)", True)

    # Reprendre la meme option : elle repart.
    ch, m = general_epingle("lola", 3, cid=79)
    COG.appels.clear()
    _mn = U.JBGenMenu("lola", "blonde", "flash", 3)
    choisir(_mn, _FLASH[0], m, ch)
    choisir(_mn, _FLASH[0], m, ch)
    check("meme option choisie deux fois : deux actions, deux remises", len(COG.appels) == 2
          and len(m.edits) == 2, (COG.appels, len(m.edits)))

    # La quantite du General est la sienne : un panneau a 7 ne bloque pas la remise.
    ch, m = general_epingle("lola", 3, cid=80)
    U._JB_PANNEAU_COURANT[80] = ("lola", 7)
    choisir(U.JBGenMenu("lola", "blonde", "caption", 3), "reelcaption", m, ch)
    check("panneau a une autre QUANTITE (meme model) : le General est bien remis",
          len(m.edits) == 1 and remis(m.edits[0]["view"]), len(m.edits))
    # Course : le panneau (donc le General) est passe sur une autre model.
    ch, m = general_epingle("lola", 3, cid=81)
    U._JB_PANNEAU_COURANT[81] = ("julia", 3)
    COG.appels.clear()
    itx = choisir(U.JBGenMenu("lola", "blonde", "caption", 3), "reelcaption", m, ch)
    check("course : panneau deja passe sur Julia -> aucun redessin du General avec Lola",
          not m.edits and COG.appels and COG.appels[-1][4] == "lola" and itx.response.doubles == 0,
          len(m.edits))
    U._JB_PANNEAU_COURANT.clear()

    # Action muette : on repond EN redessinant.
    ch, m = general_epingle("lola", 3, cid=82)
    itx = choisir(U.JBGenMenu("lola", "blonde", "template", 3), "reelmonte", m, ch, mode="rien")
    check("action muette : la reponse est l'edition du General (jamais « l'interaction a echoue »)",
          itx.response.faits and itx.response.faits[0][0] == "edit_message" and itx.response.doubles == 0,
          itx.response.faits)
    # L'action leve.
    ch, m = general_epingle("lola", 3, cid=83)
    del JOURNAL.lignes[:]
    itx = choisir(U.JBGenMenu("lola", "blonde", "caption", 3), "capbanger", m, ch, mode="leve")
    check("action qui leve : une reponse, erreur DITE en ephemere et journalisee",
          itx.response.doubles == 0 and len(itx.response.faits) == 1
          and itx.followup.envois and "erreur" in itx.followup.envois[-1][0]
          and itx.followup.envois[-1][1].get("ephemeral")
          and any("en echec" in l[2] and "General" in l[2] for l in JOURNAL.lignes),
          (itx.response.faits, itx.followup.envois))
    # Reponses d'action variees (defer ephemere, thinking, message) sur le General du salon.
    for mode in ("defer_eph", "thinking", "send_eph"):
        ch, m = general_epingle("lola", 3, cid=84)
        itx = choisir(U.JBGenMenu("lola", "blonde", "trash", 3), _TRASH[0], m, ch, mode=mode)
        check("reponse de l'action « %s » : une seule reponse, General remis par le salon" % mode,
              itx.response.doubles == 0 and len(itx.response.faits) == 1 and len(m.edits) == 1
              and remis(m.edits[0]["view"]), (itx.response.faits, len(m.edits)))
    # Edition du salon refusee : repli par l'interaction.
    ch, m = general_epingle("lola", 3, cid=85)
    _vraie_edit = m.edit
    _n_ed = {"n": 0}


    async def _edit_une_fois_refusee(**k):
        _n_ed["n"] += 1
        if _n_ed["n"] == 1:
            m.edits.append(k)
            raise http_exc(status=500, texte="panne")
        return await _vraie_edit(**k)
    m.edit = _edit_une_fois_refusee
    itx = choisir(U.JBGenMenu("lola", "blonde", "flash", 3), _FLASH[1], m, ch)
    check("redessin du salon refuse : repli par l'interaction (@original apres defer), une reponse",
          itx.orig_edits and itx.response.doubles == 0 and remis(itx.orig_edits[-1]["view"]),
          (itx.orig_edits, itx.response.faits))

    # Course AVEC le redessin de fond en panne (reproduit le 26/09/2026) : le
    # repli de remise a zero (_menu_lancer) passe APRES l'action, avec la vue
    # construite au choix. Le VA ayant pris la reserve Brune pendant le rendu,
    # il remettait le General sur Blonde. interaction.message est une PHOTO
    # prise au clic (Photo), et interaction.data porte le custom_id du menu,
    # comme chez Discord : c'est lui que le correctif cherche dans le message
    # relu. Photo et CogCourse servent aussi a la partie 6 (conversion).
    class Photo:
        def __init__(self, vrai, echecs=0):
            self.vrai = vrai
            self.id = vrai.id
            self.ch = vrai.ch
            self.embeds = list(vrai.embeds)
            self.content = vrai.content
            self.components = list(vrai.components)
            self.author = vrai.author
            self.pinned = vrai.pinned
            self.flags = types.SimpleNamespace(ephemeral=vrai.flags.ephemeral,
                                               components_v2=vrai.flags.components_v2)
            #: editions refusees (500) avant de passer : le redessin de fond.
            self.echecs = echecs

        async def edit(self, **k):
            if self.echecs:
                self.echecs -= 1
                raise http_exc(status=500, texte="panne simulee")
            return await self.vrai.edit(**k)

        async def delete(self):
            return await self.vrai.delete()


    class CogCourse(Cog):
        """_run_for_model qui joue `pendant()` au milieu du « rendu », une
        fois le redessin de fond passe (et rate)."""

        def __init__(self, pendant):
            super().__init__()
            self.pendant = pendant

        async def _run_for_model(self, interaction, model, cmd, count=None,
                                 supports_count=False, brute_de=None):
            self.appels.append((model, count, brute_de))
            await interaction.response.defer()
            for _ in range(5):
                await asyncio.sleep(0)
            if self.pendant is not None:
                await self.pendant()
            await interaction.followup.send("contenu")


    def itx_course(m, ch, pendant=None, echecs=0):
        itx = Itx(message=Photo(m, echecs=echecs), channel=ch, guild=GUILD_IC)
        cog = CogCourse(pendant)
        itx.client = types.SimpleNamespace(get_cog=lambda n: cog if n == "UserCog" else None,
                                           user=types.SimpleNamespace(id=MOI))
        return itx, cog


    def titre(m):
        return texte(m.view).splitlines()[0] if m.view is not None and not m.embeds else ""


    ch, m = general_epingle("duo", 3, res="blonde", cid=88)
    U._JB_PANNEAU_COURANT[88] = ("duo", 3)


    async def _vers_brune():
        await U.JBGenReserveBouton("duo", "brune", 3).callback(
            Itx(message=Photo(m), channel=ch, guild=GUILD_IC))
    _mnC = U.JBGenMenu("duo", "blonde", "trash", 3)
    _mnC.item._values = [_TRASH[0]]
    itx, _cg = itx_course(m, ch, _vers_brune, echecs=1)
    itx.data = {"custom_id": _mnC.item.custom_id, "component_type": 3, "values": [_TRASH[0]]}
    del JOURNAL.lignes[:]
    lancer(_mnC.callback(itx))
    check("course : reserve passee sur Brune pendant le rendu + redessin de fond en panne -> "
          "le General RESTE sur Brune, rien par @original, une reponse, journalise",
          _cg.appels == [("blonde", 3, "duo")] and itx.message.echecs == 0
          and titre(m) == "## ✨ General — Brune pour Duo" and not itx.orig_edits
          and len(itx.response.faits) == 1 and itx.response.doubles == 0
          and any("deja redessine" in l[2] for l in JOURNAL.lignes),
          (titre(m), itx.orig_edits, itx.response.faits))
    # Meme panne SANS course : le repli remet bien le General (une relecture).
    ch, m = general_epingle("duo", 3, res="blonde", cid=89)
    U._JB_PANNEAU_COURANT[89] = ("duo", 3)
    itx, _cg = itx_course(m, ch, None, echecs=1)
    itx.data = {"custom_id": _mnC.item.custom_id, "component_type": 3, "values": [_TRASH[0]]}
    ch.fetchs = 0
    lancer(_mnC.callback(itx))
    check("redessin de fond en panne, sans course : General remis par @original (1 relecture, 1 reponse)",
          len(itx.orig_edits) == 1 and remis(itx.orig_edits[0]["view"]) and ch.fetchs == 1
          and titre(m) == "## ✨ General — Blonde pour Duo" and len(itx.response.faits) == 1,
          (itx.orig_edits, ch.fetchs, itx.response.faits))
    _mnC.item._values = []
    U._JB_PANNEAU_COURANT.clear()
    # General EPHEMERE (theorique) : vue arretee, redessin par l'interaction.
    eph = Msg(view=U._vue_sans_suivi(U._jb_general(None, "lola", 3)), ephemere=True)
    for mode, attendu in (("defer", "orig"), ("send_eph", "followup"), ("rien", "reponse")):
        eph.edits.clear()
        itx = choisir(U.JBGenMenu("lola", "blonde", "template", 3), "templatebanger", eph, Salon(86), mode=mode)
        chemin = ("orig" if itx.orig_edits else "followup" if itx.followup.edits
                  else "reponse" if itx.response.faits and itx.response.faits[0][0] == "edit_message" else "?")
        v_ = eph.edits[-1].get("view") if eph.edits else None
        check("ephemere (%s) : menu remis par %s, une seule reponse, vue arretee" % (mode, attendu),
              chemin == attendu and itx.response.doubles == 0 and remis(v_) and v_.is_finished(),
              (chemin, itx.response.faits, len(eph.edits)))

    # Refus : rien ne part, le menu revient, la raison est dite.
    ch, m = general_epingle("lola", 3, cid=87)


    def refus_avec(nom, preparer, menu, valeur, attendu, restaurer=None, n_menus=4):
        COG.appels.clear()
        preparer()
        try:
            itx = choisir(menu, valeur, m, ch)
        finally:
            if restaurer:
                restaurer()
        rep = itx.response.faits
        _vr = rep[0][2].get("view") if rep else None
        check("refus %s : rien ne part, le General revient, le VA lit pourquoi" % nom,
              not COG.appels and rep and rep[0][0] == "edit_message" and remis(_vr, n_menus)
              and itx.followup.envois and attendu in str(itx.followup.envois[0][0])
              and itx.followup.envois[0][1].get("ephemeral") and itx.response.doubles == 0,
              (COG.appels, rep[:1], itx.followup.envois))


    refus_avec("role", lambda: setattr(U, "_jb_can_use", lambda i: False),
               U.JBGenMenu("lola", "blonde", "caption", 3), "capbanger", "Réservé",
               restaurer=lambda: setattr(U, "_jb_can_use", lambda i: True))
    del JOURNAL.lignes[:]
    refus_avec("variante Brut (brutcaption) hors liste blanche du General", lambda: None,
               U.JBGenMenu("lola", "blonde", "caption", 3), "brutcaption", "inconnue")
    check("refus hors liste blanche : journalise", any("refuse" in l[2] and "brutcaption" in l[2]
                                                     for l in JOURNAL.lignes))
    refus_avec("valeur d'une autre famille", lambda: None,
               U.JBGenMenu("lola", "blonde", "caption", 3), _FLASH[0], "inconnue")
    refus_avec("Brut du panneau (brutchoix)", lambda: None,
               U.JBGenMenu("lola", "blonde", "template", 3), "brutchoix", "inconnue")
    refus_avec("famille inconnue", lambda: None,
               U.JBGenMenu("lola", "blonde", "brut", 3), "brute", "indisponible")
    refus_avec("model devenue reserve", lambda: setattr(U, "_refus_reserve_jb", lambda i: "⛔ reserve"),
               U.JBGenMenu("lola", "blonde", "caption", 3), "capbanger", "⛔ reserve",
               restaurer=lambda: setattr(U, "_refus_reserve_jb", lambda i: ""))
    refus_avec("reserve deliee depuis", lambda: LIENS.__setitem__("lola", (["brune"], [("blonde", "deliee")])),
               U.JBGenMenu("lola", "blonde", "caption", 3), "capbanger", "n'est plus liée",
               restaurer=lambda: LIENS.__setitem__("lola", (["blonde"], [])))
    refus_avec("liens illisibles", lambda: setattr(TI, "reserves_liees",
                                                   lambda mm: (_ for _ in ()).throw(RuntimeError("x"))),
               U.JBGenMenu("lola", "blonde", "caption", 3), "capbanger", "illisibles",
               restaurer=lambda: setattr(TI, "reserves_liees", _liens), n_menus=0)
    refus_avec("model sans brute (Trash)", lambda: BRUTES.__setitem__("lola", []),
               U.JBGenMenu("lola", "blonde", "trash", 3), _TRASH[1], "aucune vidéo brute",
               restaurer=lambda: BRUTES.pop("lola", None))
    _attr = U._jb_action("capbanger")[2]
    _sauv_attr = Cog.__dict__.get(_attr)
    refus_avec("action absente du cog", lambda: delattr(Cog, _attr),
               U.JBGenMenu("lola", "blonde", "caption", 3), "capbanger", "indisponible",
               restaurer=lambda: setattr(Cog, _attr, _sauv_attr))
    # Template (reelmonte) sans brute : AUTORISE (un brouillon sans coupe n'en a pas besoin).
    BRUTES["lola"] = []
    COG.appels.clear()
    choisir(U.JBGenMenu("lola", "blonde", "template", 3), "reelmonte", m, ch)
    BRUTES.pop("lola", None)
    check("Template sans brute : part quand meme (hors _JB_GEN_BRUTE, comme le bouton)",
          COG.appels and COG.appels[-1][1] == "reelmonte", COG.appels)
    # Le meme refus « sans brute » que le bouton, mot pour mot.
    BRUTES["lola"] = []
    itxb = Itx(message=m, channel=ch)
    lancer(U.JBGenButton("lola", "blonde", _TRASH[0], 3).callback(itxb))
    itxm = choisir(U.JBGenMenu("lola", "blonde", "trash", 3), _TRASH[0], m, ch)
    BRUTES.pop("lola", None)
    check("refus « sans brute » : le menu dit EXACTEMENT ce que dit le bouton",
          itxb.response.faits[0][1][0] == itxm.followup.envois[0][0],
          (itxb.response.faits[0][1], itxm.followup.envois))

    # ===========================================================================
    # 6. ANCIENS BOUTONS (jbg:a/qb/r) ET CONVERSION DE L'ANCIEN GENERAL
    # ===========================================================================


    def ancien_general(model="lola", res="blonde", qty=3, cid=90):
        """Un General tel que e5a5f53 le postait : un embed + une vue classique."""
        ch = Salon(cid)
        e = discord.Embed(title="✨ General — %s pour %s" % (res.capitalize(), model.capitalize()))
        e.set_footer(text="panneau-general-us")
        v = ui.View(timeout=None)
        v.add_item(U.JBGenQtyBouton(model, res, qty))
        # Les rangees d'AVANT (e5a5f53) : boutons, captions, templates, marques.
        _rg = {**{k: 1 for k in U._JB_GEN_BOUTONS}, "reelcaption": 2, "capbanger": 2,
               "reelmonte": 3, "templatebanger": 3, _TRASH[0]: 4, _TRASH[1]: 4,
               _FLASH[0]: 4, _FLASH[1]: 4}
        for k in sorted(_ANCIENNES_CLES):
            v.add_item(U.JBGenButton(model, res, k, qty, row=_rg[k]))
        m = Msg(ch, embed=e, view=v)
        m.pinned = True
        ch.msgs.append(m)
        U._jb_general_set(ch.id, m.id)
        return ch, m


    # a) action d'un ancien bouton (reelcaption) : repond, PUIS convertit le message.
    ch, m = ancien_general(cid=91)
    COG.appels.clear()
    COG.mode = "defer"
    itx = Itx(message=m, channel=ch)
    lancer(U.JBGenButton("lola", "blonde", "reelcaption", 3).callback(itx))
    k = m.edits[-1] if m.edits else {}
    check("ancien bouton jbg:a:reelcaption : l'action part (reserve, brute de la model)",
          COG.appels == [("blonde", "reelcaption", 3, True, "lola")], COG.appels)
    check("... puis l'ancien General est CONVERTI par edition (content=None, embed=None, vue V2), une reponse",
          k.get("content", "x") is None and k.get("embed", "x") is None
          and isinstance(k.get("view"), ui.LayoutView) and m.flags.components_v2 and not m.embeds
          and U._est_general(m, MOI) and len(ch.msgs) == 1 and itx.response.doubles == 0
          and len(selects(m.view)) == 4, k)
    # b) un bouton jbg:a: sur un General deja V2 : pas de nouvelle edition.
    m.edits.clear()
    itx = Itx(message=m, channel=ch)
    lancer(U.JBGenButton("lola", "blonde", "pp", 3).callback(itx))
    check("bouton PP sur un General V2 : l'action part, aucune edition (rien a convertir)",
          COG.appels[-1][1] == "profilepic" and not m.edits, m.edits)
    # c) conversion refusee : nouveau General V2, epingle, memorise, ancien retire.
    ch, m = ancien_general(cid=92)
    m.echec_edit = http_exc(texte="Cannot convert")
    _pan_avant = dict(U._jb_panel_ids())
    del JOURNAL.lignes[:]
    itx = Itx(message=m, channel=ch)
    lancer(U.JBGenButton("lola", "blonde", _FLASH[1], 3).callback(itx))
    nouv = [x for x in ch.msgs if x is not m]
    check("ancien bouton, conversion refusee : nouveau General V2 epingle, ancien retire, id memorise "
          "(fichier du GENERAL, pas celui du panneau), journalise",
          m.supprime and len(nouv) == 1 and nouv[0].pinned and U._est_general(nouv[0], MOI)
          and not nouv[0].embeds and U._jb_general_ids().get("92") == str(nouv[0].id)
          and U._jb_panel_ids() == _pan_avant and COG.appels[-1][1] == U._jb_action(_FLASH[1])[2]
          and any("conversion refusee" in l[2] for l in JOURNAL.lignes) and itx.response.doubles == 0,
          (m.supprime, len(nouv), U._jb_general_ids().get("92")))
    # d) ancien bouton refuse (role) : message ephemere, pas de conversion.
    ch, m = ancien_general(cid=93)
    U._jb_can_use = lambda i: False
    itx = Itx(message=m, channel=ch)
    COG.appels.clear()
    lancer(U.JBGenButton("lola", "blonde", "reelcaption", 3).callback(itx))
    U._jb_can_use = lambda i: True
    check("ancien bouton, role refuse : ephemere « Réservé », rien ne part, message intact",
          itx.response.faits[0][0] == "send_message" and "Réservé" in itx.response.faits[0][1][0]
          and itx.response.faits[0][2].get("ephemeral") and not COG.appels and not m.edits)
    # e) ancienne cle hors liste blanche (forgee) : refusee comme avant.
    itx = Itx(message=m, channel=ch)
    lancer(U.JBGenButton("lola", "blonde", "brute", 3).callback(itx))
    check("bouton jbg:a: a cle forgee (brute) : refuse « absente du ✨ General »",
          "absente du ✨ General" in itx.response.faits[0][1][0] and not m.edits)
    # f) choix de reserve (jbg:r:) sur un ancien General : repond EN convertissant.
    ch = Salon(94)
    e = discord.Embed(title="✨ General — Blonde pour Duo")
    e.set_footer(text="panneau-general-us")
    m = Msg(ch, embed=e, view=None)
    m.pinned = True
    ch.msgs.append(m)
    U._jb_general_set(ch.id, m.id)
    itx = Itx(message=m, channel=ch)
    lancer(U.JBGenReserveBouton("duo", "brune", 3).callback(itx))
    f = itx.response.faits
    check("ancien jbg:r: : une reponse (edition) qui CONVERTIT, la reserve choisie devient active",
          f and f[0][0] == "edit_message" and f[0][2].get("content", "x") is None
          and f[0][2].get("embed", "x") is None and m.flags.components_v2 and not m.embeds
          and rangees(m.view)[0] == ["jbg:r:duo:blonde:3", "jbg:r:duo:brune:3", "jbg:qb:duo:brune:3"]
          and itx.response.doubles == 0, f)
    # g) jbg:r: sur un General V2 : edition de la vue seule.
    itx = Itx(message=m, channel=ch)
    lancer(U.JBGenReserveBouton("duo", "blonde", 3).callback(itx))
    check("jbg:r: sur un General V2 : edition de la vue SEULE (rien a vider)",
          set(itx.response.faits[0][2]) == {"view"} and rangees(m.view)[0][-1] == "jbg:qb:duo:blonde:3")
    # h) jbg:r: conversion refusee : defer, nouveau General, id memorise.
    ch = Salon(95)
    m = Msg(ch, embed=e, view=None)
    m.pinned = True
    ch.msgs.append(m)
    U._jb_general_set(ch.id, m.id)
    itx = Itx(message=m, channel=ch)
    itx.response.echec_edit = http_exc(texte="refus conversion")
    del JOURNAL.lignes[:]
    lancer(U.JBGenReserveBouton("duo", "brune", 3).callback(itx))
    nouv = [x for x in ch.msgs if x is not m]
    check("jbg:r: conversion refusee : defer, nouveau General V2 (brune) epingle, memorise, ancien retire",
          itx.response.faits and itx.response.faits[0][0] == "defer" and m.supprime and len(nouv) == 1
          and nouv[0].pinned and rangees(nouv[0].view)[0][-1] == "jbg:qb:duo:brune:3"
          and U._jb_general_ids().get("95") == str(nouv[0].id)
          and any("General" in l[2] and "edition refusee" in l[2] for l in JOURNAL.lignes),
          (itx.response.faits, m.supprime, len(nouv)))


    async def soumettre(itx_clic, q, message, echec=None):
        modal = itx_clic.response.modal
        itx_m = Itx(message=message, channel=message.ch, guild=GUILD_IC)
        if echec is not None:
            itx_m.response.echec_edit = echec
        modal.nombre._value = str(q)
        await modal.on_submit(itx_m)
        await attendre_fond()
        return itx_m


    # i) quantite (jbg:qb:) sur un ancien General : fenetre, puis conversion a 7.
    ch, m = ancien_general("duo", "brune", 3, cid=96)
    itx = Itx(message=m, channel=ch, guild=GUILD_IC)
    run(U.JBGenQtyBouton("duo", "brune", 3).callback(itx))
    itm = run(soumettre(itx, 7, m))
    k = itm.response.faits[0][2] if itm.response.faits else {}
    check("ancien jbg:qb: : fenetre, puis General V2 a 7 par edition (conversion), reserve gardee",
          itx.response.faits[0][0] == "send_modal" and itm.response.faits[0][0] == "edit_message"
          and k.get("content", "x") is None and k.get("embed", "x") is None
          and rangees(m.view)[0][-1] == "jbg:qb:duo:brune:7"
          and "jbg:s:duo:brune:flash:7" in [c for rr in rangees(m.view) for c in rr], itm.response.faits)
    # j) jbg:qb: conversion refusee : repost.
    ch, m = ancien_general("duo", "brune", 3, cid=97)
    itx = Itx(message=m, channel=ch, guild=GUILD_IC)
    run(U.JBGenQtyBouton("duo", "brune", 3).callback(itx))
    itm = lancer(soumettre(itx, 4, m, echec=http_exc(texte="refus")))
    nouv = [x for x in ch.msgs if x is not m]
    check("jbg:qb: conversion refusee : defer, nouveau General V2 (4) epingle, memorise, ancien retire",
          itm.response.faits[0][0] == "defer" and m.supprime and len(nouv) == 1
          and rangees(nouv[0].view)[0][-1] == "jbg:qb:duo:brune:4"
          and U._jb_general_ids().get("97") == str(nouv[0].id), itm.response.faits)
    # k) quantite / reserve : role refuse.
    U._jb_can_use = lambda i: False
    itx = Itx(message=m, channel=ch)
    run(U.JBGenQtyBouton("duo", "brune", 3).callback(itx))
    itx2 = Itx(message=m, channel=ch)
    run(U.JBGenReserveBouton("duo", "brune", 3).callback(itx2))
    U._jb_can_use = lambda i: True
    check("jbg:qb: et jbg:r: : role refuse -> ephemere, rien d'edite",
          itx.response.faits[0][0] == "send_message" and itx2.response.faits[0][0] == "send_message")

    # l) COURSE PENDANT L'ACTION D'UN ANCIEN BOUTON (reproduit le 26/09/2026).
    # JBGenButton attend tout le rendu (jusqu'a 30 s) PUIS convertit l'ancien
    # General. interaction.message est une PHOTO prise au clic : ses drapeaux
    # disent « ancien format » pour toujours. Pendant le rendu, le VA clique
    # Julia : _jb_general_maj convertit le General pour Julia (Brune). La
    # conversion d'apres la photo le remettait ensuite sur « Blonde pour
    # Lola » -- ses menus servant Blonde sur une brute de Lola pendant que le
    # VA travaille Julia. Les tests d'avant ne le voyaient pas : leur Msg est
    # le message du salon lui-meme, ses drapeaux passent a V2 des la
    # premiere edition.
    LIENS["julia"] = (["brune"], [])
    _cliC = types.SimpleNamespace(get_cog=lambda n: COG if n == "UserCog" else None,
                                  user=types.SimpleNamespace(id=MOI))
    ch, m = ancien_general(cid=9101)
    U._JB_PANNEAU_COURANT[9101] = ("lola", 3)
    _majC = {}


    async def _clic_julia():
        # Ce que fait JBModelButton : noter le panneau, puis suivre le General.
        U._jb_panneau_noter(9101, "julia", 3)
        _majC["ok"] = await U._jb_general_maj(_cliC, ch, "julia", GUILD_IC)
        _majC["titre"] = titre(m)
    itx, _cg = itx_course(m, ch, _clic_julia)
    del JOURNAL.lignes[:]
    lancer(U.JBGenButton("lola", "blonde", "reelcaption", 3).callback(itx))
    _idsC = [c for r_ in rangees(m.view) for c in r_] if m.view is not None else []
    check("course (ancien bouton) : Julia cliquee pendant le rendu -> le General RESTE « Brune pour "
          "Julia » (pas de retour a Lola), un seul General, journalise",
          _cg.appels == [("blonde", 3, "lola")] and _majC.get("ok") is True
          and _majC.get("titre") == "## ✨ General — Brune pour Julia"
          and titre(m) == "## ✨ General — Brune pour Julia"
          and "jbg:s:julia:brune:caption:3" in _idsC and not any(":lola:" in c for c in _idsC)
          and ch.msgs == [m] and itx.response.doubles == 0
          and any("deja converti" in l[2] for l in JOURNAL.lignes),
          (_majC, titre(m), _idsC[:3]))
    # Meme course, c'est la RESERVE que le VA change pendant le rendu.
    ch, m = ancien_general("duo", "blonde", 3, cid=9102)
    U._JB_PANNEAU_COURANT[9102] = ("duo", 3)


    async def _clic_brune():
        await U.JBGenReserveBouton("duo", "brune", 3).callback(
            Itx(message=Photo(m), channel=ch, guild=GUILD_IC))
    itx, _cg = itx_course(m, ch, _clic_brune)
    lancer(U.JBGenButton("duo", "blonde", "capbanger", 3).callback(itx))
    check("course (ancien bouton) : reserve Brune choisie pendant le rendu -> elle reste affichee",
          titre(m) == "## ✨ General — Brune pour Duo" and ch.msgs == [m], titre(m))
    # Sans course, la photo « ancien format » convertit toujours (une relecture).
    ch, m = ancien_general(cid=9103)
    U._JB_PANNEAU_COURANT[9103] = ("lola", 3)
    itx, _cg = itx_course(m, ch)
    ch.fetchs = 0
    lancer(U.JBGenButton("lola", "blonde", "reelcaption", 3).callback(itx))
    check("sans course : l'ancien General est converti (Blonde pour Lola, V2), une seule relecture",
          m.flags.components_v2 and not m.embeds and titre(m) == "## ✨ General — Blonde pour Lola"
          and ch.fetchs == 1 and ch.msgs == [m], (titre(m), ch.fetchs))
    # General deja V2 au clic : aucune relecture (pas d'appel de plus).
    ch.fetchs = 0
    m.edits.clear()
    itx, _cg = itx_course(m, ch)
    lancer(U.JBGenButton("lola", "blonde", "pp", 3).callback(itx))
    check("General deja V2 au clic : aucune relecture, aucune edition",
          ch.fetchs == 0 and not m.edits, (ch.fetchs, m.edits))
    # Panneau deja passe sur Julia, General encore ancien (sa mise a jour est
    # en cours, ou a echoue) : pas de conversion pour Lola, journalise.
    ch, m = ancien_general(cid=9104)
    U._JB_PANNEAU_COURANT[9104] = ("julia", 3)
    itx, _cg = itx_course(m, ch)
    del JOURNAL.lignes[:]
    lancer(U.JBGenButton("lola", "blonde", "reelcaption", 3).callback(itx))
    check("panneau deja sur Julia : l'ancien General de Lola n'est PAS converti, journalise",
          not m.edits and m.embeds and ch.msgs == [m]
          and any("passe sur julia" in l[2] for l in JOURNAL.lignes), (m.edits, ch.msgs))
    # Le General supprime pendant le rendu : rien d'edite, rien de repose, dit.
    ch, m = ancien_general(cid=9105)
    U._JB_PANNEAU_COURANT[9105] = ("lola", 3)


    async def _supprime():
        await m.delete()
    itx, _cg = itx_course(m, ch, _supprime)
    del JOURNAL.lignes[:]
    lancer(U.JBGenButton("lola", "blonde", "reelcaption", 3).callback(itx))
    check("General supprime pendant le rendu : pas de conversion ni de repli, journalise",
          not ch.msgs and not [e for e in m.edits if "view" in e] and itx.response.doubles == 0
          and any("disparu" in l[2] for l in JOURNAL.lignes), (ch.msgs, m.edits))
    LIENS.pop("julia", None)
    U._JB_PANNEAU_COURANT.clear()

    # ===========================================================================
    # 7. _jb_general_maj (clic sur une model) : edition, conversion, repli
    # ===========================================================================
    _cliV = types.SimpleNamespace(get_cog=lambda n: COG if n == "UserCog" else None,
                                  user=types.SimpleNamespace(id=MOI))


    def salon_avec(*msgs, cid):
        ch = Salon(cid)
        for x in msgs:
            x.ch = ch
            x.pinned = True
            ch.msgs.append(x)
        return ch


    def old_gen():
        e = discord.Embed(title="✨ General — Blonde pour Duo")
        e.set_footer(text="panneau-general-us")
        return Msg(embed=e)


    # a) memo -> ancien General : conversion par edition (meme message).
    g = old_gen()
    ch = salon_avec(g, cid=101)
    U._jb_general_set(ch.id, g.id)
    ok = run(U._jb_general_maj(_cliV, ch, "lola", None))
    check("maj, memo = ancien General : CONVERTI par edition (meme message, id garde)",
          ok and len(ch.msgs) == 1 and g.flags.components_v2 and not g.embeds
          and g.edits[-1].get("content", "x") is None and g.edits[-1].get("embed", "x") is None
          and "Blonde pour Lola" in texte(g.view) and U._jb_general_ids().get("101") == str(g.id),
          g.edits)
    # b) memo -> General V2 : une seule edition, vue seule, aucune relecture.
    g.edits.clear()
    ch.fetchs = 0
    ok = run(U._jb_general_maj(_cliV, ch, "duo", None))
    check("maj, memo = General V2 : UNE edition (vue seule), aucune relecture ni epingles",
          ok and len(g.edits) == 1 and set(g.edits[0]) == {"view"} and ch.fetchs == 0
          and ch.lectures_epingles == 0 and "Blonde pour Duo" in texte(g.view), g.edits)
    # c) memo -> General V2, edition refusee (panne) : False, pas de doublon, journalise.
    g.echec_edit = http_exc(status=500, texte="panne")
    del JOURNAL.lignes[:]
    ok = run(U._jb_general_maj(_cliV, ch, "lola", None))
    g.echec_edit = None
    check("maj, General V2 refuse (panne) : False, AUCUN second General, journalise",
          ok is False and len(ch.msgs) == 1 and any("edition refusee" in l[2] for l in JOURNAL.lignes))
    # d) memo -> ancien General, conversion refusee : nouveau General V2.
    g = old_gen()
    g.echec_edit = http_exc(texte="Cannot convert")
    ch = salon_avec(g, cid=102)
    U._jb_general_set(ch.id, g.id)
    del JOURNAL.lignes[:]
    ok = run(U._jb_general_maj(_cliV, ch, "lola", None))
    nouv = [x for x in ch.msgs if x is not g]
    check("maj, conversion refusee (memo) : nouveau General V2 epingle, memorise, ancien retire, journalise",
          ok and g.supprime and len(nouv) == 1 and nouv[0].pinned and U._est_general(nouv[0], MOI)
          and U._jb_general_ids().get("102") == str(nouv[0].id)
          and any("conversion refusee" in l[2] for l in JOURNAL.lignes), (ok, g.supprime, len(nouv)))
    # e) pas de memo, ancien General dans les epingles : converti ; V2 : edite.
    for fmt in ("ancien", "v2"):
        g = old_gen() if fmt == "ancien" else Msg(view=U._jb_general(None, "duo", 3))
        ch = salon_avec(g, cid=103 if fmt == "ancien" else 104)
        ok = run(U._jb_general_maj(_cliV, ch, "lola", None))
        check("maj, sans memo, General %s retrouve dans les epingles : edite%s, pas de doublon, memorise" % (
            fmt, " ET converti" if fmt == "ancien" else " (vue seule)"),
              ok and len(ch.msgs) == 1 and g.flags.components_v2 and "Blonde pour Lola" in texte(g.view)
              and (set(g.edits[-1]) == ({"view", "content", "embed"} if fmt == "ancien" else {"view"}))
              and U._jb_general_ids().get(str(ch.id)) == str(g.id), g.edits)
    # f) pas de memo, ancien General dans les epingles, conversion refusee : repost.
    g = old_gen()
    g.echec_edit = http_exc(texte="Cannot convert")
    ch = salon_avec(g, cid=105)
    ok = run(U._jb_general_maj(_cliV, ch, "lola", None))
    nouv = [x for x in ch.msgs if x is not g]
    check("maj, conversion refusee (epingles) : nouveau General V2, memorise, ancien retire",
          ok and g.supprime and len(nouv) == 1 and U._jb_general_ids().get("105") == str(nouv[0].id))
    # g) aucun General : pose en V2, epingle, memorise.
    ch = Salon(106)
    ok = run(U._jb_general_maj(_cliV, ch, "lola", None))
    check("maj, aucun General : un General V2 pose, epingle, memorise",
          ok and len(ch.msgs) == 1 and ch.msgs[0].pinned and U._est_general(ch.msgs[0], MOI)
          and not ch.msgs[0].embeds and U._jb_general_ids().get("106") == str(ch.msgs[0].id))
    # h) memo sur un AUTRE message : on cherche le General, l'autre n'est pas touche.
    autre = Msg(embed=discord.Embed(title="🔓 Menu Jailbreak US"))
    g = old_gen()
    ch = salon_avec(autre, g, cid=107)
    U._jb_general_set(ch.id, autre.id)
    autre.echec_edit = http_exc(texte="pas a toi")
    ok = run(U._jb_general_maj(_cliV, ch, "lola", None))
    check("maj, memo perime sur un autre message : le General est retrouve et converti, l'autre intact",
          ok and g.flags.components_v2 and autre.embeds and autre.embeds[0].title.startswith("🔓 Menu")
          and U._jb_general_ids().get("107") == str(g.id))
    # i) reposter=True : TOUS les Generals (2 formats) partent, un V2 est pose dessous.
    g1, g2 = old_gen(), Msg(view=U._jb_general(None, "duo", 3))
    ch = salon_avec(g1, g2, cid=108)
    U._jb_general_set(ch.id, g1.id)
    ok = run(U._jb_general_maj(_cliV, ch, "lola", None, reposter=True))
    check("maj reposter : ancien ET V2 retires, un seul General V2 pose et memorise",
          ok and g1.supprime and g2.supprime and len(ch.msgs) == 1 and U._est_general(ch.msgs[0], MOI)
          and U._jb_general_ids().get("108") == str(ch.msgs[0].id))
    # j) etat « aucune reserve » : les boutons de la model precedente disparaissent.
    g = Msg(view=U._jb_general(None, "duo", 3))
    ch = salon_avec(g, cid=109)
    U._jb_general_set(ch.id, g.id)
    ok = run(U._jb_general_maj(_cliV, ch, "nue", None))
    check("maj vers une model sans reserve : texte seul, plus AUCUN bouton de la model precedente",
          ok and not [c for rr in rangees(g.view) for c in rr] and "aucune réserve" in texte(g.view)
          and not g.components[0].children[1:] if g.components else False,
          rangees(g.view))

    # ===========================================================================
    # 8. CLIC SUR UNE MODEL (JBModelButton) : le vrai _jb_general_maj
    # ===========================================================================
    GF.is_us_guild = lambda g: True
    ch = Salon(110)
    pan = Msg(ch, view=U._jb_panel(None, "emma", 3))
    pan.pinned = True
    g = old_gen()
    g.ch = ch
    g.pinned = True
    ch.msgs += [pan, g]
    U._jb_panel_set(ch.id, pan.id)
    U._jb_general_set(ch.id, g.id)
    itx = Itx(message=Msg(), channel=ch, guild=GUILD_IC)
    lancer(U.JBModelButton("duo").callback(itx))
    check("clic sur une model : panneau V2 edite, ANCIEN General converti en V2 pour cette model, "
          "une reponse, ordre panneau puis General garde",
          itx.response.doubles == 0 and itx.response.faits[0][0] == "defer"
          and "Duo" in texte(pan.view) and g.flags.components_v2 and not g.embeds
          and "Blonde pour Duo" in texte(g.view) and ch.msgs == [pan, g], (itx.response.faits, g.view and texte(g.view)))

    # ===========================================================================
    # 9. WELCOME : _ensure_us_menu, _ensure_us_general, reset, _delete_old_menus
    # ===========================================================================


    class UCogW:
        def jailbreak_us_menu(self, marche):
            return discord.Embed(title="🔓 Menu Jailbreak US"), None

        async def jailbreak_us_menu_async(self, guild, marche):
            return self.jailbreak_us_menu(marche)


    _botW = types.SimpleNamespace(user=Auteur(MOI), get_cog=lambda n: UCogW() if n == "UserCog" else None)


    def ordre(ch):
        out = ""
        for x in ch.msgs:
            if U._est_panneau_actions(x, MOI):
                out += "P" if x.flags.components_v2 else "p"
            elif U._est_general(x, MOI):
                out += "G" if x.flags.components_v2 else "g"
            elif x.embeds and "Jailbreak" in (x.embeds[0].title or ""):
                out += "M"
            else:
                out += "?"
        return out


    chW = Salon(4343)
    etat = {}
    ok = run(W.reset_us_menu(_botW, chW, etat=etat))
    check("reset_us_menu (/resetmenus) : menu, panneau V2, General V2 (attente), dans cet ordre",
          ok and ordre(chW) == "MPG" and etat.get("general") is True and not chW.msgs[2].embeds
          and chW.msgs[2].pinned and "choisis une model" in texte(chW.msgs[2].view)
          and not interactifs(chW.msgs[2].view), (ordre(chW), etat))
    etat = {}
    ok = run(W._ensure_us_menu(_botW, chW, etat=etat))
    check("_ensure_us_menu : General V2 reconnu, rien de pose en double",
          ok and ordre(chW) == "MPG" and etat.get("general") is True, (ordre(chW), etat))
    ok = run(W._ensure_us_general(_botW, chW, apres=chW.msgs[1]))
    check("_ensure_us_general : General V2 reconnu (pas de second), id memorise",
          ok is True and ordre(chW) == "MPG" and U._jb_general_ids().get(str(chW.id)) == str(chW.msgs[2].id))
    # Ancien General (embed) : reconnu aussi, garde tel quel (converti au 1er clic).
    chA = Salon(4344)
    mA = Msg(chA, embed=discord.Embed(title="🔓 Menu Jailbreak US"))
    pA = Msg(chA, view=U._jb_panel(None, "_", 3))
    gA = old_gen()
    gA.ch = chA
    for x in (mA, pA, gA):
        x.pinned = True
    chA.msgs += [mA, pA, gA]
    etat = {}
    ok = run(W._ensure_us_menu(_botW, chA, etat=etat))
    check("_ensure_us_menu : ANCIEN General reconnu, garde, rien d'autre pose",
          ok and ordre(chA) == "MPg" and etat.get("general") is True and not gA.supprime, ordre(chA))
    # Doublons (ancien + V2) et General V2 AU-DESSUS du panneau.
    chD = Salon(4345)
    mD = Msg(chD, embed=discord.Embed(title="🔓 Menu Jailbreak US"))
    gHaut = Msg(chD, view=U._jb_general(None, "lola", 3))      # au-dessus du panneau
    pD = Msg(chD, view=U._jb_panel(None, "_", 3))
    gOld = old_gen()
    gOld.ch = chD
    gV2 = Msg(chD, view=U._jb_general(None, "_"))
    for x in (mD, gHaut, pD, gOld, gV2):
        x.pinned = True
    chD.msgs += [mD, gHaut, pD, gOld, gV2]
    ok = run(W._ensure_us_general(_botW, chD, apres=pD))
    check("_ensure_us_general : General V2 au-dessus du panneau et doublon ancien RETIRES, le plus recent garde",
          ok and gHaut.supprime and gOld.supprime and not gV2.supprime and ordre(chD) == "MPG"
          and U._jb_general_ids().get(str(chD.id)) == str(gV2.id), ordre(chD))
    # Menu a reposer : le General V2 existant part avec le reste, un neuf est pose dessous.
    chJ = Salon(4346)
    pJ = Msg(chJ, view=U._jb_panel(None, "emma", 3))
    gJ = Msg(chJ, view=U._jb_general(None, "lola", 3))
    for x in (pJ, gJ):
        x.pinned = True
    chJ.msgs += [pJ, gJ]
    ok = run(W._ensure_us_menu(_botW, chJ))
    check("_ensure_us_menu : menu absent -> panneau et General V2 (reconnus) refaits dans l'ordre",
          ok and pJ.supprime and gJ.supprime and ordre(chJ) == "MPG", ordre(chJ))
    # Pas le serveur US : pas de General.
    GF.is_us_guild = lambda g: False
    chN = Salon(4347)
    ok = run(W._ensure_us_general(_botW, chN))
    check("_ensure_us_general hors serveur US : rien de pose", ok is False and not chN.msgs)
    GF.is_us_guild = lambda g: True
    # _delete_old_menus (salons VA) : ne touche jamais au General, dans aucun format.
    chX = Salon(4400, "va-test")
    gX1 = Msg(chX, view=U._jb_general(None, "menuxx", 3))   # texte avec « menu » (nom de model)
    gX2 = Msg(chX, embed=_eg)
    gX3 = Msg(chX, view=U._jb_general(None, "_"))
    mX = Msg(chX, embed=discord.Embed(title="☀️ Ton menu"))
    chX.msgs += [gX1, gX2, gX3, mX]
    _cogD = types.SimpleNamespace(bot=types.SimpleNamespace(user=Auteur(MOI)))
    run(U.UserCog._delete_old_menus(_cogD, chX))
    check("_delete_old_menus : le vieux menu part, les General (V2, ancien, attente) restent",
          mX.supprime and not gX1.supprime and not gX2.supprime and not gX3.supprime)

    # ===========================================================================
    # 10. LE PANNEAU D'ACTIONS N'A PAS BOUGE (mecanique partagee)
    # ===========================================================================
    vP = U._jb_panel(None, "emma", 3)
    check("panneau d'actions : meme disposition qu'en production (22 composants, 5 menus)",
          vP.total_children_count == 22 and len(selects(vP)) == 5
          and texte(vP).splitlines()[-1] == "-# panneau-actions-us")
    # Remise du panneau : la garde (model, quantite) est intacte.
    chP = Salon(120)
    mP = Msg(chP, view=U._jb_panel(None, "emma", 3))
    mP.pinned = True
    chP.msgs.append(mP)
    U._jb_panel_set(chP.id, mP.id)
    U._JB_PANNEAU_COURANT[120] = ("emma", 7)
    _itxG = Itx(message=mP, channel=chP)
    run(U._jb_remettre_epingle(_itxG, "emma", 3, U._jb_panel(None, "emma", 3)))
    _n_qte = len(mP.edits)
    run(U._jb_remettre_epingle(_itxG, "emma", None, U._jb_panel(None, "emma", 3), quoi="General"))
    _n_none = len(mP.edits)
    U._JB_PANNEAU_COURANT[120] = ("julia", 3)
    run(U._jb_remettre_epingle(_itxG, "emma", None, U._jb_panel(None, "emma", 3), quoi="General"))
    _n_autre = len(mP.edits)
    U._JB_PANNEAU_COURANT.clear()
    run(U._jb_remettre_epingle(_itxG, "emma", 3, U._jb_panel(None, "emma", 3)))
    check("_jb_remettre_epingle : quantite differente -> pas de remise (panneau, garde d'avant) ; "
          "qty=None (General) -> remise ; autre model -> pas de remise ; etat inconnu -> remise",
          (_n_qte, _n_none, _n_autre, len(mP.edits)) == (0, 1, 1, 2),
          (_n_qte, _n_none, _n_autre, len(mP.edits)))
    chP2 = Salon(121)
    mP2 = Msg(chP2, embed=_ep)
    mP2.pinned = True
    mP2.echec_edit = http_exc(texte="Cannot convert")
    chP2.msgs.append(mP2)
    U._jb_panel_set(chP2.id, mP2.id)
    _gen_appels = []


    async def _gen_f(client, chan, model, guild, reposter=False):
        _gen_appels.append((model, reposter))
        return True
    U._jb_general_maj = _gen_f
    del JOURNAL.lignes[:]
    itx = Itx(message=Msg(), channel=chP2, guild=GUILD_IC)
    lancer(U.JBModelButton("julia").callback(itx))
    U._jb_general_maj = VRAI["gen"]
    nouvP = [x for x in chP2.msgs if x is not mP2]
    check("panneau d'actions : repli commun (_jb_message_reposer) -> nouveau panneau memorise dans "
          "us_panels.json, General reposte",
          mP2.supprime and len(nouvP) == 1 and U._jb_panel_ids().get("121") == nouvP[0].id
          and _gen_appels == [("julia", True)]
          and any("panneau US" in l[2] and "edition refusee" in l[2] for l in JOURNAL.lignes),
          (_gen_appels, len(nouvP)))

    import shutil
    shutil.rmtree(TMP, ignore_errors=True)



import importlib as _v2imp
import logging as _v2log
import os as _v2os
import traceback as _v2tb

#: Toute ouverture EN ECRITURE, tout renommage ou effacement sous le VRAI
#: data/ pendant ces trois parties est note. Un crochet d'audit ne se retire
#: pas : il ne fait rien hors de la section.
_V2_AUDIT = {"actif": False, "data": _v2os.path.realpath("data"), "ecrits": []}


def _v2_audit(ev, args):
    if not _V2_AUDIT["actif"]:
        return
    try:
        chemins = []
        if ev == "open":
            mode, flags = args[1], args[2]
            if (mode and any(c in str(mode) for c in "wax+")) or (
                    isinstance(flags, int)
                    and flags & (_v2os.O_WRONLY | _v2os.O_RDWR | _v2os.O_CREAT)):
                chemins = [args[0]]
        elif ev in ("os.rename", "os.replace", "os.remove", "os.unlink",
                    "os.mkdir", "shutil.rmtree"):
            chemins = list(args[:2])
        data = _V2_AUDIT["data"]
        for p in chemins:
            if isinstance(p, (str, bytes, _v2os.PathLike)):
                rp = _v2os.path.realpath(_v2os.fsdecode(p))
                if rp == data or rp.startswith(data + _v2os.sep):
                    _V2_AUDIT["ecrits"].append((ev, rp))
    except Exception:
        pass


sys.addaudithook(_v2_audit)

#: Les modules que les trois parties modifient (fonctions remplacees, chemins
#: detournes) : remis a l'identique apres chacune, meme si elle leve. La
#: partie E remplace aussi la lecture des liens model -> reserves
#: (type_identite) et celle des brutes (brutes_off).
_V2_MODULES = [_v2imp.import_module(n) for n in (
    "cogs.user", "cogs.welcome", "cogs.menutest", "guild_features", "marques_montage",
    "type_identite", "brutes_off")]
_v2_u = _V2_MODULES[0]
for _nomV2, _fV2 in (("panneau", _v2_bloc_panneau), ("menu VA", _v2_bloc_menu_va),
                     ("General", _v2_bloc_general)):
    _savV2 = {m: dict(vars(m)) for m in _V2_MODULES}
    # Etats en memoire modifies SUR PLACE (pas remplaces) par les clics simules.
    _savEtatsV2 = {k: dict(getattr(_v2_u, k)) for k in (
        "_JB_PANNEAU_COURANT", "_JB_SOUS_MENUS", "_DERNIER_PANNEAU_JB", "_MENU_BTN_FEATURE")}
    _savActV2 = list(_v2_u._JB_ACTIONS_US)
    _racineV2 = _v2log.getLogger()
    _savLogV2 = (list(_racineV2.handlers), _racineV2.level)
    _V2_AUDIT["actif"] = True
    try:
        _fV2()
    except Exception as _eV2:
        check("v2 %s : testable" % _nomV2, False,
              repr(_eV2)[:200] + " " + _v2tb.format_exc()[-700:])
    finally:
        _V2_AUDIT["actif"] = False
        for _mV2, _dV2 in _savV2.items():
            for _kV2 in [k for k in vars(_mV2) if k not in _dV2]:
                delattr(_mV2, _kV2)
            for _kV2, _valV2 in _dV2.items():
                if vars(_mV2).get(_kV2, _savV2) is not _valV2:
                    setattr(_mV2, _kV2, _valV2)
        for _kV2, _dV2 in _savEtatsV2.items():
            getattr(_v2_u, _kV2).clear()
            getattr(_v2_u, _kV2).update(_dV2)
        _v2_u._JB_ACTIONS_US[:] = _savActV2
        _racineV2.handlers[:] = _savLogV2[0]
        _racineV2.setLevel(_savLogV2[1])
check("v2 : aucune ecriture dans data/ pendant les trois parties",
      not _V2_AUDIT["ecrits"], str(_V2_AUDIT["ecrits"][:5]))

if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  -", f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
