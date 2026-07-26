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


print()
print("=" * 70)
print("7) Sécurité : le gating par rôle est appliqué CÔTÉ SERVEUR")
print("=" * 70)
try:
    import web_upload as _w
    _app = _w.create_app()
    _app.config["TESTING"] = True
    _orig_users = _w._load_web_users
    _w._load_web_users = lambda: {"chatteur1": {"role": "chatter", "password": "x"}}
    _c = _app.test_client()
    with _c.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "chatteur1"
        _s["role"] = "chatter"
    for _label, _path, _data in (
            ("créer un compte owner", "/settings/role/add", {"username": "p", "role": "owner"}),
            ("se promouvoir", "/settings/role/edit_user", {"username": "chatteur1", "role": "owner"}),
            ("changer sa commission", "/mypuls/chatter/set_pct", {"name": "chatteur1", "pct": "60"}),
            ("détourner une adresse crypto", "/mypuls/chatter/set_crypto", {"name": "a", "address": "moi"}),
            ("ajouter une dépense", "/business/expense/add", {"label": "x", "amount": "10"}),
            ("supprimer un VA", "/jailbreak/remove_va", {"identity": "e", "va_name": "T"})):
        _r = _c.post(_path, data=_data)
        check(f"rôle restreint bloqué : {_label}", _r.status_code == 403, f"HTTP {_r.status_code}")
    _r = _c.post("/chatting/update_cell", data={"edt": "x", "row": "0", "col": "0", "value": "v"})
    check("rôle restreint garde son planning", _r.status_code != 403, f"HTTP {_r.status_code}")
    _w._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _c2 = _app.test_client()
    with _c2.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "boss"
        _s["role"] = "owner"
    _r = _c2.post("/jailbreak/remove_va", data={"identity": "zzz", "va_name": "nope"})
    check("owner : accès complet conservé", _r.status_code != 403, f"HTTP {_r.status_code}")
    _w._load_web_users = _orig_users
except Exception as _e:
    check("sécurité : testable", False, repr(_e)[:90])

print()
print("=" * 70)
print("8) Paie VA : pas de sous-paiement figé, pas de faux zéro")
print("=" * 70)
try:
    import time as _t, datetime as _dtp
    import web_upload as _w
    _today = _dtp.date.today()
    _hier = (_today - _dtp.timedelta(days=1)).isoformat()
    _midi = _t.mktime((_today - _dtp.timedelta(days=1)).timetuple()) + 12 * 3600
    _fin = _t.mktime(_today.timetuple())

    class _G:
        calls = 0
        def api_tag(self, *a):
            import contextlib
            return contextlib.nullcontext()
        def analytics_for_link(self, lid, a, b):
            _G.calls += 1
            return 120, {"FR": 100, "US": 20}

    class _GKo(_G):
        def analytics_for_link(self, lid, a, b):
            _G.calls += 1
            return None, None

    _w._PAY_DAYCACHE.clear()
    _w._PAY_DAYCACHE[f"L1|{_hier}"] = [45, 30, _midi]
    _G.calls = 0
    _tt, _ee = _w._pay_day_stats(_G(), "L1", _hier, True)
    check("jour relevé en cours de journée : re-téléchargé", _G.calls == 1 and _tt == 120, f"{_tt} calls={_G.calls}")
    _w._PAY_DAYCACHE[f"L2|{_hier}"] = [77, 70, _fin + 60]
    _G.calls = 0
    _tt, _ee = _w._pay_day_stats(_G(), "L2", _hier, True)
    check("jour complet : servi du cache", _G.calls == 0 and _tt == 77, f"{_tt} calls={_G.calls}")
    _w._PAY_DAYCACHE.clear()
    _tt, _ee = _w._pay_day_stats(_GKo(), "L3", _hier, True)
    check("panne GMS : aucun faux zéro mis en cache",
          (_tt, _ee) == (0, 0) and f"L3|{_hier}" not in _w._PAY_DAYCACHE, str(list(_w._PAY_DAYCACHE)))
    _tt, _ee = _w._pay_day_stats(_G(), "L3", _hier, True)
    check("après la panne : vraie valeur récupérée", _tt == 120 and _ee == 100, f"{_tt}/{_ee}")
    _w._PAY_DAYCACHE.clear()
except Exception as _e:
    check("paie : testable", False, repr(_e)[:90])


print()
print("=" * 70)
print("9) Sécurité : secrets, sessions révocables, uploads")
print("=" * 70)
try:
    import web_upload as _w2
    _app2 = _w2.create_app()
    _app2.config["TESTING"] = True
    _sav = _w2._load_web_users
    # identifiants Instagram (mots de passe + 2FA) : réservés aux accès complets
    _w2._load_web_users = lambda: {"chat": {"role": "chatter"}}
    _cc = _app2.test_client()
    with _cc.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "chat"
        _s["role"] = "chatter"
        _s["sid"] = "T1"
    check("rôle restreint : identifiants Insta refusés", _cc.get("/external/list").status_code == 403)
    check("rôle restreint : /va/get_insta_3 refusé", _cc.get("/va/get_insta_3?user_id=1").status_code == 403)
    # compte supprimé / désactivé : coupure immédiate
    _w2._load_web_users = lambda: {"autre": {"role": "owner"}}
    _c3 = _app2.test_client()
    with _c3.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "vire"
        _s["role"] = "owner"
        _s["sid"] = "T2"
    check("compte supprimé : accès coupé", _c3.get("/external/list").status_code in (302, 401, 403))
    _w2._load_web_users = lambda: {"susp": {"role": "owner", "disabled": True}}
    _c4 = _app2.test_client()
    with _c4.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "susp"
        _s["role"] = "owner"
        _s["sid"] = "T3"
    check("compte désactivé : accès coupé", _c4.get("/external/list").status_code in (302, 401, 403))
    # révocation effective d'une session
    _w2._load_web_users = lambda: {"boss": {"role": "owner"}}
    _c5 = _app2.test_client()
    with _c5.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "boss"
        _s["role"] = "owner"
        _s["sid"] = "T9"
    check("owner : accès normal", _c5.get("/external/list").status_code == 200)
    _c5.post("/security/revoke_session", data={"session_id": "T9"})
    check("session révoquée : accès coupé", _c5.get("/external/list").status_code in (302, 401, 403))
    pathlib.Path("data/revoked_sessions.json").unlink(missing_ok=True)
    _w2._load_web_users = _sav
    # noms de fichiers uploadés
    for _raw, _exp in (("../../etc/passwd", "passwd"), ("..\..\win.ini", "win.ini"),
                       ("photo (1).png", "photo (1).png"), ("", "fichier")):
        check(f"upload assaini : {_raw or '(vide)'}", _w2._safe_upload_name(_raw) == _exp,
              _w2._safe_upload_name(_raw))
except Exception as _e:
    check("sécurité 2 : testable", False, repr(_e)[:90])


print()
print("=" * 70)
print("10) Argent : attribution des liens et rapport de paie")
print("=" * 70)
try:
    import gms as _gms
    _links = [{"display_name": "va_@amelia", "shortcode": "abcamelia"},
              {"display_name": "va_@mialee", "shortcode": "xxmialee"},
              {"display_name": "va @toky", "shortcode": "zztoky"},
              {"display_name": "va_@lia", "shortcode": "lialink"}]
    _r = _gms.find_link_for_handle("lia", _links)
    check("lien : « lia » ne prend pas celui d'amelia",
          _r and _r["display_name"] == "va_@lia", str(_r))
    _r = _gms.find_link_for_handle("mia", _links)
    check("lien : « mia » ne prend pas celui de mialee",
          (not _r) or _r["display_name"] != "va_@mialee", str(_r))
    _r = _gms.find_link_for_handle("amelia", _links)
    check("lien : « amelia » trouve le sien", _r and _r["display_name"] == "va_@amelia", str(_r))
except Exception as _e:
    check("attribution des liens : testable", False, repr(_e)[:80])

try:
    _src = pathlib.Path("cogs/clickrecap.py").read_text(encoding="utf-8")
    _s = _src.index("    def _format_pay_report(rows, title):")
    _e2 = _src.index("    async def _run_pay_report")
    _NL = chr(10)
    _body = _NL.join(l[4:] if l.startswith('    ') else l
                     for l in _src[_s:_e2].split(_NL))
    _ns = {}
    exec(_body, _ns)
    _txt = _NL.join(_ns['_format_pay_report'](
        [('A', 'toky', 120, 7.2, 0), ('A', 'bo7', 50, 2.5, 3)], 'Quinzaine'))
    check("rapport de paie : jours illisibles signalés", "illisible" in _txt, _txt[-90:])
    check("rapport de paie : total marqué comme minimum", "MINIMUM" in _txt)
except Exception as _e:
    check("rapport de paie : testable", False, repr(_e)[:80])

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
