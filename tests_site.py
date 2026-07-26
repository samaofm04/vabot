"""tests_site.py — banc d'essai du stockage de données du site (hors GeeLark).

Lancer :  python tests_site.py        (depuis le dossier bot/)

Vérifie, sur des fichiers TEMPORAIRES (aucune donnée réelle touchée) :
  1. safe_json : atomicité, concurrence, récupération après corruption ;
  2. chaque module de données : aller-retour save/load, résistance à un
     fichier tronqué, absence de .tmp résiduel ;
  3. qu'aucune écriture non atomique ne subsiste dans le code.
"""
import importlib
import json
import pathlib
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import safe_json

FAILS, OKS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{detail}]" if detail and not cond else ""))


TMP = pathlib.Path(tempfile.mkdtemp(prefix="vabot_tests_"))
print(f"bac à sable : {TMP}\n")

print("=" * 70)
print("1) safe_json : socle d'écriture")
print("=" * 70)
p = TMP / "t1.json"
safe_json.write(p, {"a": 1, "é": "ü"})
check("écriture + relecture", safe_json.load(p) == {"a": 1, "é": "ü"})
check("accents conservés (pas d'échappement)", "é" in p.read_text(encoding="utf-8"))
safe_json.write(p, {"a": 2})
check("copie .prev créée", (TMP / "t1.json.prev").exists())
check("nouvelle valeur écrite", safe_json.load(p)["a"] == 2)
p.write_text("{tronqué", encoding="utf-8")
check("corruption -> repli sur .prev", safe_json.load(p, default={}) == {"a": 1, "é": "ü"})
check("fichier principal réparé", json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "é": "ü"})
missing = TMP / "jamais_ecrit.json"
check("fichier absent -> défaut", safe_json.load(missing, default={"d": 1}) == {"d": 1})
cache_p = TMP / "gros_cache.json"
safe_json.write(cache_p, {"x": 1})
safe_json.write(cache_p, {"x": 2})
check("fichier de cache : pas de .prev (économie)", not (TMP / "gros_cache.json.prev").exists())
check("aucun .tmp résiduel", not list(TMP.glob("*.tmp")))

print()
print("=" * 70)
print("2) safe_json : 10 threads × 30 écritures simultanées")
print("=" * 70)
conc = TMP / "conc.json"
safe_json.write(conc, {"n": 0})
errors = []


def hammer(k):
    for i in range(30):
        try:
            safe_json.write(conc, {"who": k, "i": i})
            d = safe_json.load(conc)
            if not isinstance(d, dict) or "who" not in d:
                errors.append(f"lecture incohérente: {d}")
        except Exception as e:
            errors.append(repr(e))


ths = [threading.Thread(target=hammer, args=(k,)) for k in range(10)]
t0 = time.time()
for t in ths:
    t.start()
for t in ths:
    t.join()
check("300 écritures concurrentes sans erreur", not errors, errors[:2])
check("fichier final valide", isinstance(safe_json.load(conc), dict))
check("jamais de JSON tronqué observé", not any("Expecting" in e for e in errors))
print(f"     ({time.time() - t0:.1f}s)")

print()
print("=" * 70)
print("3) Modules de données : aller-retour + corruption")
print("=" * 70)

# (module, attribut du chemin, fonction save, fonction load, donnée d'exemple)
CASES = [
    ("bio_links", "BIO_FILE", "_save_all", "_load_all", {"amelia": {"links": []}}),
    ("guild_features", "_FILE", "_save", "_load", {"123": {"jailbreak": True}}),
    ("tg_router", "CFG_FILE", "_save", "_load", {"dest": {"1": "2"}}),
    ("sfs_setup", "SETUP_FILE", "_save", "_load", {"mym": {"amelia": {"user": "x"}}}),
    ("apify_reels", "CONFIG_FILE", "_save", "_load", {"token": "abc"}),
]

for mod_name, path_attr, save_fn, load_fn, sample in CASES:
    try:
        mod = importlib.import_module(mod_name)
        original = getattr(mod, path_attr)
        tmp_path = TMP / f"{mod_name}.json"
        setattr(mod, path_attr, tmp_path)
        try:
            getattr(mod, save_fn)(sample)
            back = getattr(mod, load_fn)()
            inclus = all(back.get(k) == v for k, v in sample.items()) if isinstance(back, dict) else False
            check(f"{mod_name} : aller-retour", inclus, f"{back}")
            check(f"{mod_name} : écriture atomique", not list(TMP.glob(f"{mod_name}.json.tmp")))
            tmp_path.write_text("{cassé", encoding="utf-8")
            rec = getattr(mod, load_fn)()
            check(f"{mod_name} : fichier cassé ne fait pas planter", isinstance(rec, (dict, list)),
                  f"{type(rec).__name__}")
        finally:
            setattr(mod, path_attr, original)
    except Exception as e:
        check(f"{mod_name} : testable", False, repr(e)[:90])

# business.py : listes (revenus/dépenses)
try:
    import business
    tmp_b = TMP / "biz.json"
    business._save(tmp_b, [{"montant": 10}])
    check("business : aller-retour", business._load(tmp_b) == [{"montant": 10}])
    tmp_b.write_text("[[[", encoding="utf-8")
    check("business : fichier cassé -> liste vide", business._load(tmp_b) == [])
except Exception as e:
    check("business : testable", False, repr(e)[:90])

# jb_activity
try:
    import jb_activity
    tmp_a = TMP / "act.json"
    jb_activity._save(tmp_a, {"u": {"last_post_ts": 1}})
    check("jb_activity : aller-retour", jb_activity._load(tmp_a) == {"u": {"last_post_ts": 1}})
except Exception as e:
    check("jb_activity : testable", False, repr(e)[:90])

# facture (module web) : sauvegarde du mois
try:
    import facture_web
    orig = facture_web.FACTURE_FILE
    facture_web.FACTURE_FILE = TMP / "facture.json"
    facture_web._save({"months": {"2026-07": {"lignes": []}}})
    _fb = facture_web._load()
    check("facture : aller-retour", _fb.get("months", {}).get("2026-07") == {"lignes": []}, f"{_fb}")
    facture_web.FACTURE_FILE = orig
except Exception as e:
    check("facture : testable", False, repr(e)[:90])

print()
print("=" * 70)
print("4) Aucune écriture JSON non atomique ne subsiste")
print("=" * 70)
import re
BAD = re.compile(r"\.write_text\(\s*json\.dumps")
restants = []
for f in sorted(pathlib.Path(".").rglob("*.py")):
    parts = set(f.parts)
    if parts & {"__pycache__", "node_modules", "venv", "noctus"} or "geelark" in f.name:
        continue
    if f.name in ("safe_json.py", "tests_site.py", "jailbreak.py"):
        continue          # jailbreak.py a son propre mécanisme (backups + verrou)
    txt = f.read_text(encoding="utf-8", errors="ignore")
    for m in BAD.finditer(txt):
        restants.append(f"{f.as_posix()}:{txt[:m.start()].count(chr(10)) + 1}")
check("plus aucune écriture non atomique", not restants, ", ".join(restants[:4]))
print(f"     (GeeLark exclu à ta demande)")

print()
print("=" * 70)
print("5) Modules critiques : import + fonctions de données appelables")
print("=" * 70)
for m in ("web_upload", "jailbreak", "sheets_sync", "gms", "mypuls", "business",
          "facture_web", "insta_scraper", "guild_features", "safe_json"):
    try:
        importlib.import_module(m)
        check(f"import {m}", True)
    except Exception as e:
        check(f"import {m}", False, repr(e)[:80])


print()
print("=" * 70)
print("6) Sync Sheet : scénarios destructeurs (bugs trouvés par l'audit)")
print("=" * 70)
import json as _json
import sheets_sync as _ss
import jailbreak as _jb


def _mk():
    return {"lola": {"vas": [{"name": "Andry", "discord_username": ""},
                             {"name": "Bo7", "discord_username": ""}],
            "accounts": [
                {"id": 1, "username": "u1", "va": "Andry", "password": "SECRET1",
                 "email": "a@x.io", "two_fa": "KEY1", "notes": "n1"},
                {"id": 2, "username": "u2", "va": "Andry", "password": "SECRET2",
                 "email": "b@x.io", "two_fa": "KEY2", "notes": "n2"}]}}


def _merge(sheet, state):
    _jb._load = lambda: _json.loads(_json.dumps(state))
    _jb._save = lambda d: (state.clear(), state.update(_json.loads(_json.dumps(d))))
    _jb.tombstones = lambda: {"vas": {}, "accounts": {}}
    _jb.tomb_clear = lambda *a: None
    _ss.pull_all = lambda: sheet
    _ss.is_paused = lambda: False
    return _ss.pull_and_merge()


C_FULL = ["username", "password", "email", "two_fa", "va", "notes"]
st = _mk()
_merge({"lola": [{"username": "u1", "password": "SECRET1", "2fa": "KEY1", "va": "Andry",
                  "notes": "n1", "__cols__": ["username", "password", "2fa", "va", "notes"]},
                 {"username": "u2", "password": "SECRET2", "2fa": "KEY2", "va": "Andry",
                  "notes": "n2", "__cols__": ["username", "password", "2fa", "va", "notes"]}]}, st)
_a = {x["username"]: x for x in st["lola"]["accounts"]}
check("colonne 2FA renommée : secret conservé", _a["u1"]["two_fa"] == "KEY1", _a["u1"]["two_fa"])
check("colonne email supprimée : email conservé", _a["u1"]["email"] == "a@x.io", _a["u1"]["email"])

st = _mk()
_merge({"lola Andry": [{"username": "u2", "__cols__": ["username"]}],
        "lola Bo7": [{"username": "u1", "__cols__": ["username"]}]}, st)
_a = {x["username"]: x for x in st["lola"]["accounts"]}
check("ligne déplacée entre onglets VA : compte gardé", "u1" in _a, list(_a))
check("ligne déplacée : VA réassigné", _a.get("u1", {}).get("va") == "Bo7", _a.get("u1", {}).get("va"))
check("ligne déplacée : mot de passe intact", _a.get("u1", {}).get("password") == "SECRET1")

st = _mk()
_merge({"lola": [{"username": "u1", "password": "NOUVEAU", "email": "a@x.io", "two_fa": "KEY1",
                  "va": "Andry", "notes": "n1", "__cols__": C_FULL},
                 {"username": "u2", "password": "SECRET2", "email": "b@x.io", "two_fa": "KEY2",
                  "va": "Andry", "notes": "n2", "__cols__": C_FULL}],
        "lola Andry": [{"username": "u1", "password": "SECRET1", "email": "a@x.io",
                        "two_fa": "KEY1", "notes": "n1",
                        "__cols__": ["username", "password", "email", "two_fa", "notes"]},
                       {"username": "u2", "password": "SECRET2", "email": "b@x.io",
                        "two_fa": "KEY2", "notes": "n2",
                        "__cols__": ["username", "password", "email", "two_fa", "notes"]}]}, st)
_a = {x["username"]: x for x in st["lola"]["accounts"]}
check("modif de l'onglet identité non annulée", _a["u1"]["password"] == "NOUVEAU", _a["u1"]["password"])

st = _mk()
_merge({"lola": [{"username": "u1", "password": "SECRET1", "email": "a@x.io", "two_fa": "KEY1",
                  "va": "Andry", "notes": "n1", "__cols__": C_FULL}]}, st)
check("suppression volontaire toujours appliquée",
      [x["username"] for x in st["lola"]["accounts"]] == ["u1"],
      [x["username"] for x in st["lola"]["accounts"]])

# import : identité fantôme refusée
try:
    import jb_import as _ji
    check("import : « VA JB — lola » normalisé", _ji._ident_from_filename("VA JB — lola") == "lola")
    _st2 = {"lola": {"vas": [], "accounts": []}}
    _jb._load = lambda: _json.loads(_json.dumps(_st2))
    _jb._save = lambda d: (_st2.clear(), _st2.update(_json.loads(_json.dumps(d))))
    _ji._list_identities = lambda: ["lola"]
    _ji.restore({"lola": [{"username": "a1", "va": "A"}], "inconnue": [{"username": "x9"}]})
    check("import : identité inconnue refusée", sorted(_st2) == ["lola"], sorted(_st2))
except Exception as e:
    check("import : testable", False, repr(e)[:80])

# update_account : doublon de username refusé
try:
    import tempfile as _tf
    _tmpd = pathlib.Path(_tf.mkdtemp())
    _orig_file, _orig_dir = _jb.JAILBREAK_FILE, _jb.DATA_DIR
    _jb.JAILBREAK_FILE = _tmpd / "jb.json"
    _jb.DATA_DIR = _tmpd
    import importlib as _il
    _il.reload(_jb)
    _jb.JAILBREAK_FILE = _tmpd / "jb.json"
    _jb.DATA_DIR = _tmpd
    _jb.BACKUP_DIR = _tmpd / "bk"
    _jb.PREV_FILE = _tmpd / "jb.prev.json"
    a1 = _jb.add_account("zz", "aaa")
    a2 = _jb.add_account("zz", "bbb")
    check("update_account : doublon refusé", _jb.update_account("zz", a2["id"], username="aaa") is False)
    _jb.JAILBREAK_FILE, _jb.DATA_DIR = _orig_file, _orig_dir
    shutil.rmtree(_tmpd, ignore_errors=True)
except Exception as e:
    check("update_account : testable", False, repr(e)[:80])

shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  -", f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
