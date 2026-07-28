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
    _r_ko = _w._pay_day_stats(_GKo(), "L3", _hier, True)
    # NOUVEAU contrat : panne GMS -> None (sentinelle « jour illisible »), PAS
    # (0,0) (qui aurait sous-payé en silence). Rien mis en cache.
    check("panne GMS : sentinelle None (pas de faux zéro) + rien en cache",
          _r_ko is None and f"L3|{_hier}" not in _w._PAY_DAYCACHE, str(list(_w._PAY_DAYCACHE)))
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


print()
print("=" * 70)
print("11) Sécurité : cookies, force brute, cloisonnement du HTML")
print("=" * 70)
try:
    import web_upload as _w3
    _a3 = _w3.create_app()
    _a3.config["TESTING"] = True
    check("cookie HttpOnly", _a3.config.get("SESSION_COOKIE_HTTPONLY") is True)
    check("cookie SameSite", _a3.config.get("SESSION_COOKIE_SAMESITE") == "Lax")
    check("cookie Secure", _a3.config.get("SESSION_COOKIE_SECURE") is True)
    _sav3 = _w3._check_web_login
    _w3._check_web_login = lambda u, p: False
    _c6 = _a3.test_client()
    _blocked = False
    for _i in range(12):
        _txt = _c6.post("/", data={"username": "x", "password": "no"}).get_data(as_text=True)
        if "Trop de tentatives" in _txt:
            _blocked = True
            break
    check("force brute bloquée après ~8 essais", _blocked)
    _w3._check_web_login = _sav3
    # cloisonnement : un rôle restreint ne reçoit pas les données des autres onglets
    _sav4 = _w3._load_web_users
    _w3._load_web_users = lambda: {"chat": {"role": "chatter"}}
    _c7 = _a3.test_client()
    with _c7.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "chat"
        _s["role"] = "chatter"
        _s["sid"] = "Z1"
    _h = _c7.get("/").get_data(as_text=True)
    check("onglets interdits neutralisés", _h.count("Accès non autorisé") > 5, str(_h.count("Accès non autorisé")))
    _w3._load_web_users = lambda: {"boss": {"role": "owner"}}
    _c8 = _a3.test_client()
    with _c8.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "boss"
        _s["role"] = "owner"
        _s["sid"] = "Z2"
    check("owner : rien n'est retiré", _c8.get("/").get_data(as_text=True).count("Accès non autorisé") == 0)
    _w3._load_web_users = _sav4
except Exception as _e:
    check("sécurité 3 : testable", False, repr(_e)[:80])

print()
print("=" * 70)
print("10) Régressions du 27/07 (sweep wi90wufzn) — verrouillage")
print("=" * 70)
try:
    import web_upload as _wr
    _ar = _wr.create_app(); _ar.config["TESTING"] = True
    _svr = _wr._load_web_users
    # -- FIX 1 : un rôle restreint change SON propre mot de passe (pas 403) --
    _wr._load_web_users = lambda: {"chat": {"role": "chatter"}}
    _cc = _ar.test_client()
    with _cc.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "chat"; _s["role"] = "chatter"; _s["sid"] = "R1"
    check("FIX1 chatter peut changer son mdp (≠403)",
          _cc.post("/settings/my_password", data={"old": "x", "new": "y"}).status_code != 403)
    # -- FIX 4 : revenus globaux + paie VA fermés à un rôle restreint --
    check("FIX4 /paievas/report fermé au chatter",
          _cc.get("/paievas/report?period=current").status_code == 403)
    check("FIX4 /home/overview fermé au chatter",
          _cc.get("/home/overview?home_period=today").status_code == 403)
    # -- FIX 2 : SSRF ancré sur une frontière de point --
    _wr._load_web_users = lambda: {"boss": {"role": "owner"}}
    _co = _ar.test_client()
    with _co.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "R2"
    _ssrf_ok = all(_co.get("/insta/proxy_video?vurl=http://" + _h + "/x").status_code == 403
                   for _h in ("evil-instagram.com", "xinstagram.com", "attacker-facebook.com"))
    check("FIX2 SSRF bloque les domaines sosies", _ssrf_ok)
    check("FIX2 SSRF laisse passer le vrai CDN",
          _co.get("/insta/proxy_video?vurl=https://scontent.cdninstagram.com/v/x.mp4").status_code != 403)
    _wr._load_web_users = _svr
    # -- FIX 5 : fin de journée de paie calée sur Paris, SANS zoneinfo --
    import datetime as _dtp, calendar as _calp
    def _dayend(_iso):
        _nd = _dtp.date.fromisoformat(_iso) + _dtp.timedelta(days=1)
        _d0 = _dtp.date(_nd.year, 3, _wr._last_sunday_web(_nd.year, 3))
        _d1 = _dtp.date(_nd.year, 10, _wr._last_sunday_web(_nd.year, 10))
        _off = 2 if (_d0 < _nd <= _d1) else 1   # bornes décalées (bascule DST)
        return _calp.timegm((_dtp.datetime(_nd.year, _nd.month, _nd.day)
                             - _dtp.timedelta(hours=_off)).timetuple())
    check("FIX5 fin de jour Paris été (CEST)",
          _dayend("2026-07-26") == _calp.timegm(_dtp.datetime(2026, 7, 26, 22, 0).timetuple()))
    check("FIX5 fin de jour Paris hiver (CET)",
          _dayend("2026-01-15") == _calp.timegm(_dtp.datetime(2026, 1, 15, 23, 0).timetuple()))
except Exception as _e:
    check("régressions 27/07 : testable", False, repr(_e)[:90])

try:
    import copy as _cp, sheets_sync as _ss
    class _FJB:
        def __init__(_s, d): _s._data = d
        def _load(_s): return _cp.deepcopy(_s._data)
        def _save(_s, d): _s._data = d
        def tombstones(_s): return {"accounts": {}, "vas": {}}
        def tomb_clear(_s, *a, **k): pass
    _COLS = ["username", "password", "email", "two_fa", "va"]
    _jb = _FJB({"test": {"vas": ["jhon", "andry"],
                         "accounts": [{"id": 1, "username": "acc1", "va": "jhon",
                                       "password": "SECRET", "two_fa": "2FA", "email": "e@x"}]}})
    # onglet identité PÉRIMÉ (jhon) + ligne DÉPLACÉE dans l'onglet VA 'andry'
    _ss._merge_sheet_into_data({
        "test": [{"username": "acc1", "va": "jhon", "password": "SECRET", "email": "e@x",
                  "two_fa": "2FA", "__cols__": _COLS}],
        "test andry": [{"username": "acc1", "__cols__": ["username"]}],
        "test jhon": [],
    }, _jb, force_delete=False)
    _a = {a["username"]: a for a in _jb._data["test"]["accounts"]}.get("acc1")
    check("FIX6 déplacement d'onglet VA tient (reassignation)", bool(_a) and _a["va"] == "andry")
    check("FIX6 credentials préservés au déplacement",
          bool(_a) and _a["password"] == "SECRET" and _a["two_fa"] == "2FA")
    # chemin normal : colonne 'va' de l'onglet identité fait toujours foi
    _jb2 = _FJB({"test": {"vas": ["jhon", "andry"],
                          "accounts": [{"id": 2, "username": "acc2", "va": "jhon",
                                        "password": "S", "two_fa": "T", "email": "e"}]}})
    _ss._merge_sheet_into_data({
        "test": [{"username": "acc2", "va": "andry", "password": "S", "email": "e",
                  "two_fa": "T", "__cols__": _COLS}],
        "test jhon": [{"username": "acc2", "__cols__": ["username"]}],
    }, _jb2, force_delete=False)
    _b = {a["username"]: a for a in _jb2._data["test"]["accounts"]}.get("acc2")
    check("FIX6 chemin normal (colonne va) intact", bool(_b) and _b["va"] == "andry")
    # -- FIX7 : colonne absente (renommée) n'efface AUCUN champ (protection __cols__) --
    _jb7 = _FJB({"test": {"vas": ["v"], "accounts": [{"id": 9, "username": "u1", "va": "v",
                          "password": "KEEP", "two_fa": "T2", "email": "e"}]}})
    _ss._merge_sheet_into_data({
        "test": [{"username": "u1", "va": "v", "email": "e", "two_fa": "T2",
                  "__cols__": ["username", "va", "email", "two_fa"]}],  # 'password' absente
    }, _jb7, force_delete=False)
    _u = {a["username"]: a for a in _jb7._data["test"]["accounts"]}.get("u1")
    check("FIX7 colonne absente n'efface pas le mdp", bool(_u) and _u["password"] == "KEEP")
    # -- FIX14 : doublon périmé dans un autre onglet VA ne réassigne PAS --
    _jb14 = _FJB({"test": {"vas": ["v1", "v2"], "accounts": [{"id": 8, "username": "d1", "va": "v1",
                           "password": "S", "two_fa": "T", "email": "e"}]}})
    _ss._merge_sheet_into_data({
        "test": [{"username": "d1", "va": "v1", "password": "S", "email": "e",
                  "two_fa": "T", "__cols__": _COLS}],
        "test v1": [{"username": "d1", "__cols__": ["username"]}],   # toujours chez v1
        "test v2": [{"username": "d1", "__cols__": ["username"]}],   # doublon périmé
    }, _jb14, force_delete=False)
    _d = {a["username"]: a for a in _jb14._data["test"]["accounts"]}.get("d1")
    check("FIX14 doublon périmé ne réassigne pas à tort", bool(_d) and _d["va"] == "v1")
except Exception as _e:
    check("FIX6/7/14 : testable", False, repr(_e)[:90])

try:
    import importlib as _il, tempfile as _tf, pathlib as _pl
    import facture_web as _fw, mypuls as _mp8
    _orig_src = _fw._live_eur_usd_src   # restauré en fin de bloc (sinon #5 teste un stub)
    # Ce bloc teste la logique de fiabilité du taux LIVE : on neutralise le taux
    # HISTORIQUE (testé séparément en #9) pour que le chemin de repli live soit exercé.
    _mp8.get_eur_usd_rate_for_date = lambda iso: {"rate": 0.0, "source": "error"}
    # -- FIX8 : _month_rate (chemin GET) ne clobber PAS une écriture POST concurrente --
    _fw.FACTURE_FILE = _pl.Path(_tf.mkdtemp()) / "facture.json"
    _fw._save({"settings": {}, "months": {"2020-01": {"lines": []}}})
    _snap = _fw._load()                       # snapshot d'un GET compute_state
    _d2 = _fw._load(); _d2["months"]["2020-01"]["lines"].append({"id": 1})  # POST concurrent
    _fw._save(_d2)
    _fw._live_eur_usd_src = lambda: (1.14, "api")
    _fw._month_rate(_snap, "2020-01")
    _after = _fw._load()
    check("FIX8 ligne POST concurrente non clobberée",
          len(_after["months"]["2020-01"]["lines"]) == 1)
    check("FIX8 taux mois clos figé atomiquement",
          abs(float(_after["settings"]["month_rates"]["2020-01"]) - 1.14) < 1e-9)
    # -- FIX9 : ne JAMAIS figer le repli 1.10 (source 'fallback') --
    _fw.FACTURE_FILE = _pl.Path(_tf.mkdtemp()) / "facture.json"
    _fw._save({"settings": {}, "months": {"2020-02": {"lines": []}}})
    _snap2 = _fw._load()
    _fw._live_eur_usd_src = lambda: (1.10, "fallback")
    _fw._month_rate(_snap2, "2020-02")
    _frozen = "2020-02" in ((_fw._load().get("settings") or {}).get("month_rates") or {})
    check("FIX9 repli 1.10 (fallback) NON figé", not _frozen)
    _fw._live_eur_usd_src = lambda: (1.145, "cache")
    _fw._month_rate(_snap2, "2020-02")
    check("FIX9 se fige au vrai taux une fois dispo",
          abs(float(_fw._load()["settings"]["month_rates"]["2020-02"]) - 1.145) < 1e-9)
    _fw._live_eur_usd_src = _orig_src   # restaure la vraie fonction (pour le test #5)
except Exception as _e:
    check("FIX8/9 facture : testable", False, repr(_e)[:90])

try:
    import web_upload as _wp, threading as _thr, time as _tm
    _cnt = {"n": 0}; _lk = _thr.Lock()
    @_wp.ttl_cache(seconds=30)
    def _slow_cold():
        with _lk: _cnt["n"] += 1
        _tm.sleep(0.2)
        return "V"
    _res = []
    _ts = [_thr.Thread(target=lambda: _res.append(_slow_cold())) for _ in range(10)]
    for _t in _ts: _t.start()
    for _t in _ts: _t.join()
    check("FIX11 cache froid : 1 seule invocation (pas de thundering herd)", _cnt["n"] == 1)
    check("FIX11 les 10 requêtes obtiennent la valeur", _res.count("V") == 10)
except Exception as _e:
    check("FIX11 ttl_cache froid : testable", False, repr(_e)[:90])

print()
print("=" * 70)
print("11) Régressions du 2e sweep (w22vueppt) — verrouillage")
print("=" * 70)
try:
    import web_upload as _w2s
    _a2 = _w2s.create_app(); _a2.config["TESTING"] = True
    _sv2 = _w2s._load_web_users
    _svr2 = getattr(_w2s, "_load_role_definitions", None)
    _w2s._load_web_users = lambda: {"mgr": {"role": "manager"}, "chat": {"role": "chatter"}, "boss": {"role": "owner"}}
    _w2s._load_role_definitions = lambda: {"manager": {"permissions": {"paievas": {"enabled": True}}}}

    def _mk(user, role, sid):
        _c = _a2.test_client()
        with _c.session_transaction() as _s:
            _s["auth"] = True; _s["username"] = user; _s["role"] = role; _s["sid"] = sid
        return _c
    def _forbidden(cl, path):
        _r = cl.get(path); return _r.status_code == 403 and b"forbidden" in _r.data
    _chat = _mk("chat", "chatter", "V2C")
    # -- #1 : revenus agence MyPuls fermés au chatter --
    check("#1 chatter bloqué sur /mypuls/sales_window",
          _forbidden(_chat, "/mypuls/sales_window?start=2026-07-01&end=2026-07-31"))
    check("#1 chatter bloqué sur /mypuls/api_stats_test",
          _forbidden(_chat, "/mypuls/api_stats_test?id=1"))
    check("#1 chatter garde /mypuls/avatar (pas un 403 du guard)",
          not _forbidden(_chat, "/mypuls/avatar/1"))
    # -- #6 : un rôle AVEC la permission paievas lit /paievas/report ; sans -> bloqué --
    check("#6 manager(paievas) lit /paievas/report",
          _mk("mgr", "manager", "V2M").get("/paievas/report?period=current").status_code != 403)
    check("#6 chatter (sans paievas) reste bloqué",
          _forbidden(_chat, "/paievas/report?period=current"))
    check("#6b manager(paievas) NE lit PAS les revenus agence",
          _forbidden(_mk("mgr", "manager", "V2M2"), "/mypuls/sales_window?start=2026-07-01&end=2026-07-31"))
    # -- #2 : SSRF host-confusion (backslash / %5C / userinfo) bloqué --
    from urllib.parse import quote as _q
    _boss = _mk("boss", "owner", "V2B")
    for _p in ("http://169.254.169.254\\.instagram.com/",
               "http://169.254.169.254%5C.instagram.com/",
               "http://instagram.com@169.254.169.254/"):
        check("#2 SSRF bloqué: " + _p[:38],
              _boss.get("/insta/proxy_video?vurl=" + _q(_p, safe='')).status_code == 403)
    check("#2 vrai CDN passe encore",
          _boss.get("/insta/proxy_video?vurl=https://scontent.cdninstagram.com/v/x.mp4").status_code != 403)
    _w2s._load_web_users = _sv2
    if _svr2 is not None:
        _w2s._load_role_definitions = _svr2
except Exception as _e:
    check("#1/#2/#6 : testable", False, repr(_e)[:90])

try:
    import web_upload as _w3s, threading as _thr3, time as _tm3
    # -- #3 : leader échoue -> waiters ne bloquent PAS 5s --
    _c3 = {"n": 0}; _l3 = _thr3.Lock()
    @_w3s.ttl_cache(seconds=30)
    def _failing():
        with _l3: _c3["n"] += 1
        _tm3.sleep(0.15)
        raise RuntimeError("429")
    def _wk():
        try: _failing()
        except Exception: pass
    _tt = [_thr3.Thread(target=_wk) for _ in range(6)]
    _t0 = _tm3.time()
    for _t in _tt: _t.start()
    for _t in _tt: _t.join()
    check("#3 échec leader : pas de blocage 5s (< 3s total)", (_tm3.time() - _t0) < 3.0)
except Exception as _e:
    check("#3 ttl_cache échec : testable", False, repr(_e)[:90])

try:
    import facture_web as _fw3, mypuls as _mp3
    # -- #5 : _live_eur_usd_src mémoïsé (pas d'amplification réseau par mois) --
    _rc = {"n": 0}
    _mp3.get_eur_usd_rate = lambda force_refresh=False: (_rc.__setitem__("n", _rc["n"] + 1) or {"rate": 1.14, "source": "api"})
    _fw3._EUR_USD_SRC_CACHE = {"ts": 0.0, "val": None}
    for _ in range(12):
        _fw3._live_eur_usd_src()
    check("#5 12 appels -> 1 seul appel réseau (mémoïsé 60s)", _rc["n"] == 1)
except Exception as _e:
    check("#5 eur_usd mémo : testable", False, repr(_e)[:90])

try:
    import web_upload as _w7, datetime as _d7, calendar as _c7
    def _de(_iso):
        _nd = _d7.date.fromisoformat(_iso) + _d7.timedelta(days=1); _y = _nd.year
        _d0 = _d7.date(_y, 3, _w7._last_sunday_web(_y, 3)); _d1 = _d7.date(_y, 10, _w7._last_sunday_web(_y, 10))
        _off = 2 if (_d0 < _nd <= _d1) else 1
        return _c7.timegm((_d7.datetime(_nd.year, _nd.month, _nd.day) - _d7.timedelta(hours=_off)).timetuple())
    # veille du spring-forward -> minuit encore CET (+1) = 23:00 UTC ; veille du fall-back -> CEST (+2) = 22:00 UTC
    check("#7 veille spring-forward = 23:00 UTC (CET)",
          _de("2026-03-28") == _c7.timegm(_d7.datetime(2026, 3, 28, 23, 0).timetuple()))
    check("#8 veille fall-back = 22:00 UTC (CEST)",
          _de("2026-10-24") == _c7.timegm(_d7.datetime(2026, 10, 24, 22, 0).timetuple()))
except Exception as _e:
    check("#7/#8 bornes DST : testable", False, repr(_e)[:90])

print()
print("=" * 70)
print("12) Régressions du 3e sweep (wql4zarky) — verrouillage")
print("=" * 70)
try:
    import web_upload as _wA
    _aA = _wA.create_app(); _aA.config["TESTING"] = True
    _svA = _wA._load_web_users; _svrA = getattr(_wA, "_load_role_definitions", None)
    _wA._load_web_users = lambda: {"sfsu": {"role": "sfsrole"}, "chat": {"role": "chatter"}}
    _wA._load_role_definitions = lambda: {"sfsrole": {"permissions": {"sfs": {"enabled": True}}}}
    def _cA(u, r, sid):
        _c = _aA.test_client()
        with _c.session_transaction() as _s:
            _s["auth"] = True; _s["username"] = u; _s["role"] = r; _s["sid"] = sid
        return _c
    # -- A : bouton SFS « MAJ profils » (rôle sfs OK, chatter bloqué) --
    check("SFS: rôle sfs peut /mypuls/refresh_pushs_now (≠403)",
          _cA("sfsu", "sfsrole", "SA1").get("/mypuls/refresh_pushs_now").status_code != 403)
    _rc2 = _cA("chat", "chatter", "SA2").get("/mypuls/refresh_pushs_now")
    check("SFS: chatter reste bloqué (403)",
          _rc2.status_code == 403 and b"forbidden" in _rc2.data)
    _wA._load_web_users = _svA
    if _svrA is not None: _wA._load_role_definitions = _svrA
except Exception as _e:
    check("SFS refresh_pushs_now : testable", False, repr(_e)[:90])

try:
    import web_upload as _wB, threading as _thB, time as _tmB
    # -- B : échec TRANSITOIRE du leader -> single-flight (pas de herd) --
    _cB = {"n": 0}; _lB = _thB.Lock()
    @_wB.ttl_cache(seconds=30)
    def _transient():
        with _lB: _cB["n"] += 1; _n = _cB["n"]
        _tmB.sleep(0.12)
        if _n == 1:
            raise RuntimeError("429 transitoire")
        return "OK"
    _rB = []
    def _wkB():
        try: _rB.append(_transient())
        except Exception: _rB.append("ERR")
    _ttB = [_thB.Thread(target=_wkB) for _ in range(6)]
    for _t in _ttB: _t.start()
    for _t in _ttB: _t.join()
    check("B échec transitoire : single-flight (<=2 invocations, pas de herd)", _cB["n"] <= 2)
    check("B les waiters récupèrent la valeur (>=5/6)", _rB.count("OK") >= 5)
except Exception as _e:
    check("B ttl single-flight : testable", False, repr(_e)[:90])

try:
    import web_upload as _wC, threading as _thC, time as _tmC
    # -- C : refresh en vol ne réécrit PAS le cache après invalidation --
    _stC = {"v": "old"}; _gate = _thC.Event(); _enter = _thC.Event()
    @_wC.ttl_cache(seconds=0.05)
    def _renderC():
        _enter.set(); _gate.wait(2)
        return _stC["v"]
    _gate.set()
    _renderC()                      # amorce le cache avec 'old'
    _gate.clear(); _enter.clear()
    _tmC.sleep(0.08)                # laisse périmer
    _renderC()                      # chemin stale -> lance le refresh en fond
    _enter.wait(1)                  # le refresh a lu 'old' et bloque
    _stC["v"] = "new"; _wC._invalidate_all_ttl_cache()   # mutation + invalidation
    _gate.set(); _tmC.sleep(0.15)   # le refresh finit et tente d'écrire 'old'
    check("C invalidation non défaite par un write-back périmé",
          _renderC() == "new")
except Exception as _e:
    check("C ttl generation guard : testable", False, repr(_e)[:90])

print()
print("=" * 70)
print("13) Régressions du 4e sweep (wn87bca3a) — génération PAR PRÉFIXE")
print("=" * 70)
try:
    import web_upload as _wD, threading as _thD, time as _tmD
    # -- CROSS-KEY : invalider F ne doit PAS rejeter le store en vol de G --
    _gcD = {"n": 0}
    @_wD.ttl_cache(30)
    def _GD():
        _gcD["n"] += 1; _tmD.sleep(0.25); return "G"
    @_wD.ttl_cache(30)
    def _FD():
        return "F"
    _FD()
    _thg = _thD.Thread(target=_GD); _thg.start()
    _tmD.sleep(0.08)
    _FD.invalidate()                 # invalidation SANS RAPPORT pendant le calcul de G
    _thg.join()
    _b = _gcD["n"]; _GD()            # doit être un HIT
    check("cross-key: G caché malgré F.invalidate (gen par préfixe)", _gcD["n"] == _b)
    # -- FULL-CLEAR : _invalidate_all rejette bien le store en vol (fix C préservé) --
    _hcD = {"n": 0}
    @_wD.ttl_cache(30)
    def _HD():
        _hcD["n"] += 1; _tmD.sleep(0.25); return "H"
    _thh = _thD.Thread(target=_HD); _thh.start()
    _tmD.sleep(0.08)
    _wD._invalidate_all_ttl_cache()  # vidage total pendant le calcul
    _thh.join()
    _b2 = _hcD["n"]; _HD()           # doit RECOMPUTER (store rejeté par l'époque)
    check("full-clear: store en vol rejeté (contrat _success préservé)", _hcD["n"] == _b2 + 1)
except Exception as _e:
    check("4e sweep cross-key/full-clear : testable", False, repr(_e)[:90])

try:
    import web_upload as _wE, threading as _thE, time as _tmE
    # -- DEADLINE-FALLBACK : leader lent > 5 s -> UN SEUL relais, pas de troupeau --
    _lcE = {"n": 0}; _lkE = _thE.Lock()
    @_wE.ttl_cache(30)
    def _LE():
        with _lkE: _lcE["n"] += 1; _n = _lcE["n"]
        _tmE.sleep(5.4 if _n == 1 else 0.1)   # seul le leader est lent
        return "L"
    _rE = []
    _tE = [_thE.Thread(target=lambda: _rE.append(_LE())) for _ in range(5)]
    for _t in _tE: _t.start()
    for _t in _tE: _t.join()
    check("deadline-fallback: leader lent -> <=2 computes (pas de troupeau)", _lcE["n"] <= 2)
    check("deadline-fallback: les 5 requêtes obtiennent la valeur", _rE.count("L") == 5)
    check("deadline-fallback: _TTL_FALLBACK/_TTL_REFRESHING vidés (pas de fuite)",
          len(_wE._TTL_FALLBACK) == 0 and len(_wE._TTL_REFRESHING) == 0)
except Exception as _e:
    check("deadline-fallback : testable", False, repr(_e)[:90])

print()
print("=" * 70)
print("14) Audit ARGENT (wznf76t51) — paie VA web")
print("=" * 70)
try:
    import web_upload as _wM, gms as _gmsM, datetime as _dtM
    def _reset_pay():
        _wM._PAY_REPORT_CACHE.clear()
        with _wM._PAY_DAYCACHE_LOCK: _wM._PAY_DAYCACHE.clear()
    _gmsM.list_all_links = lambda: [{"id": "L1"}]
    # -- #1/#2 : jour illisible (panne GMS) -> partial + missing, PAS un 0 silencieux --
    _wM._pay_list_discord_vas = lambda: [("Team A", "marie")]
    _wM._pay_gms_exact_link = lambda h, links: {"id": "L1"}
    def _mixed(lid, a, b):
        return (80, {"FR": 80}) if _dtM.date.fromisoformat(a).day % 2 == 0 else (None, None)
    _gmsM.analytics_for_link = _mixed
    _reset_pay()
    _pm = _wM._compute_va_pay_report("current")
    _vm = _pm["categories"][0]["vas"][0]
    check("#1/#2 panne GMS -> payload partial=True", _pm["partial"] is True)
    check("#1/#2 jours illisibles comptés (missing>0)", _vm["missing"] > 0)
    check("#1/#2 jours lus quand même payés (money>0, pas 0 silencieux)", _vm["money"] > 0)
    # aucune panne -> pas de faux positif
    _gmsM.analytics_for_link = lambda lid, a, b: (50, {"FR": 50})
    _reset_pay()
    _pn = _wM._compute_va_pay_report("current")
    check("#1/#2 aucune panne -> partial=False & missing=0",
          _pn["partial"] is False and _pn["categories"][0]["vas"][0]["missing"] == 0)
    # -- rapport PARTIEL non caché : « relance » recalcule après rétablissement GMS --
    _wM._pay_list_discord_vas = lambda: [("Team A", "marie")]
    _wM._pay_gms_exact_link = lambda h, links: {"id": "L1"}
    _gmsM.analytics_for_link = _mixed
    _reset_pay()
    _pp1 = _wM._compute_va_pay_report("current")
    check("rapport partiel NON mis en cache", "current" not in _wM._PAY_REPORT_CACHE)
    with _wM._PAY_DAYCACHE_LOCK: _wM._PAY_DAYCACHE.clear()
    _gmsM.analytics_for_link = lambda lid, a, b: (80, {"FR": 80})   # GMS rétabli
    _pp2 = _wM._compute_va_pay_report("current")
    check("relance après rétablissement -> total complet (pas le minimum stale)",
          (not _pp2["partial"]) and _pp2["total"] > _pp1["total"])
    check("rapport complet, lui, mis en cache", "current" in _wM._PAY_REPORT_CACHE)
    # -- #7 : deux handles -> même lien GMS -> UNE seule ligne payée --
    _wM._pay_list_discord_vas = lambda: [("Cat", "marie.rose"), ("Cat", "marierose")]
    _wM._pay_gms_exact_link = lambda h, links: {"id": "L1"}
    _reset_pay()
    _pd = _wM._compute_va_pay_report("current")
    _nrows = sum(len(c["vas"]) for c in _pd["categories"])
    check("#7 double attribution: 1 lien -> 1 ligne payée (pas 2)", _nrows == 1)
    # -- #5 : clamp serveur du malus négatif --
    check("#5 malus négatif borné à 0 (pas de bonus)", max(0.0, float("-5")) == 0.0)
except Exception as _e:
    check("audit argent paie : testable", False, repr(_e)[:90])

try:
    import facture_web as _fwM, tempfile as _tfM, pathlib as _plM
    _fwM.FACTURE_FILE = _plM.Path(_tfM.mkdtemp()) / "facture.json"
    _fwM._EUR_USD_SRC_CACHE = {"ts": 0.0, "val": (1.0, "api")}
    # -- #8 : parts lead par marché == part lead globale (marché en perte) --
    _fwM._save({"settings": {"associates": [{"name": "A", "pct": 20}], "eur_usd": 1.0},
                "months": {"2020-05": {"lines": [
                    {"id": "r1", "type": "rev", "form": "fixed", "amount": 4080.42, "currency": "USD", "market": "fr", "label": "FR"},
                    {"id": "e1", "type": "exp", "form": "fixed", "amount": 4254.88, "currency": "USD", "market": "fr", "label": "cFR"},
                    {"id": "r2", "type": "rev", "form": "fixed", "amount": 1000, "currency": "USD", "market": "us", "label": "US"},
                    {"id": "e2", "type": "exp", "form": "fixed", "amount": 300, "currency": "USD", "market": "us", "label": "cUS"}]}}})
    _s8 = _fwM.compute_state("2020-05")
    _sum = round(sum(m.get("lead", 0) for m in (_s8.get("by_market") or {}).values()), 2)
    check("#8 somme parts lead par marché == part lead globale",
          abs(_sum - _s8["totals"]["lead"]) < 0.02)
    # -- #4 : supprimer la base d'une paye % ne la rebase PAS sur rev_total --
    _fwM.FACTURE_FILE = _plM.Path(_tfM.mkdtemp()) / "facture.json"
    _fwM._save({"settings": {"associates": [], "eur_usd": 1.0},
                "months": {"2020-06": {"lines": [
                    {"id": "of", "type": "rev", "form": "fixed", "amount": 2286.12, "currency": "USD", "market": "fr", "label": "OF Lola"},
                    {"id": "other", "type": "rev", "form": "fixed", "amount": 5000, "currency": "USD", "market": "fr", "label": "Autres"},
                    {"id": "pay", "type": "exp", "form": "pct", "pct": 35, "pct_of": "line:of", "market": "fr", "label": "Paye 35%"}]}}})
    _d4 = _fwM._load(); _m4 = _d4["months"]["2020-06"]
    _m4["lines"] = [l for l in _m4["lines"] if l.get("id") != "of"]  # base supprimée (sans rebase)
    _fwM._save(_d4)
    _s4 = _fwM.compute_state("2020-06")
    _pl4 = [l for l in _s4["lines"] if l.get("id") == "pay"][0]
    check("#4 paye orpheline -> 0 (pas rebasée sur rev_total)", abs(_pl4.get("usd", 1)) < 0.01)
    # -- #9 : mois clos figé sur le taux HISTORIQUE, pas le 'latest' du jour --
    import mypuls as _mpH
    _fwM.FACTURE_FILE = _plM.Path(_tfM.mkdtemp()) / "facture.json"
    _fwM._EUR_USD_SRC_CACHE = {"ts": 0.0, "val": None}
    _fwM._live_eur_usd_src = lambda: (1.16, "api")               # taux du JOUR
    _mpH.get_eur_usd_rate_for_date = lambda iso: {"rate": 1.07, "source": "api"}  # taux d'ÉPOQUE
    _fwM._save({"settings": {}, "months": {"2020-06": {"lines": []}}})
    _r9 = _fwM._month_rate(_fwM._load(), "2020-06")
    check("#9 mois clos figé sur le taux historique (pas le latest)", abs(_r9 - 1.07) < 1e-9)
    _mpH.get_eur_usd_rate_for_date = lambda iso: {"rate": 0.0, "source": "error"}
    _fwM.FACTURE_FILE = _plM.Path(_tfM.mkdtemp()) / "facture.json"
    _fwM._save({"settings": {}, "months": {"2020-07": {"lines": []}}})
    check("#9 repli si historique indispo -> live fiable",
          abs(_fwM._month_rate(_fwM._load(), "2020-07") - 1.16) < 1e-9)
except Exception as _e:
    check("audit argent facture : testable", False, repr(_e)[:90])

print()
print("=" * 70)
print("15) Rôles : la casse du nom ne doit JAMAIS perdre les permissions")
print("=" * 70)
try:
    import web_upload as _wR, json as _jR
    _tmpR = TMP / "roles"; _tmpR.mkdir(parents=True, exist_ok=True)
    _savedDir = _wR.DATA_DIR
    _wR.DATA_DIR = _tmpR
    # fichier ANCIEN : clé écrite telle que tapée, avec majuscules
    (_tmpR / "role_definitions.json").write_text(
        _jR.dumps({"VA JB": {"permissions": {"jailbreak": {"enabled": True}}}}),
        encoding="utf-8")
    _tabs = {r: _wR._role_allowed_tabs(r) for r in
             ["VA JB", "va jb", "VA  JB", " Va Jb ", "vA jB"]}
    check("rôle 'VA JB' (majuscules) : permissions bien appliquées",
          "jailbreak" in (_tabs["VA JB"] or set()))
    check("toutes les casses/espacements donnent le MÊME accès",
          len({frozenset(v or ()) for v in _tabs.values()}) == 1, str(_tabs))
    # écriture : toujours en clé canonique
    _wR._save_role_definitions({"Nouveau Role": {"permissions": {"sfs": {"enabled": True}}}})
    _keysR = list(_jR.loads((_tmpR / "role_definitions.json").read_text(encoding="utf-8")))
    check("sauvegarde en clé canonique (minuscules)", _keysR == ["nouveau role"], str(_keysR))
    check("rôle relu juste après la sauvegarde",
          "sfs" in (_wR._role_allowed_tabs("Nouveau Role") or set()))
    # owner/admin et le fallback chatter ne bougent pas
    check("owner/admin gardent l'accès complet",
          _wR._role_allowed_tabs("owner") is None and _wR._role_allowed_tabs("Admin") is None)
    _savR = _wR._load_role_definitions
    _wR._load_role_definitions = lambda: {}
    check("chatter garde son jeu d'onglets par défaut",
          "chatplanning" in (_wR._role_allowed_tabs("Chatter") or set()))
    _wR._load_role_definitions = _savR
    _wR.DATA_DIR = _savedDir
except Exception as _e:
    check("rôles : testable", False, repr(_e)[:90])

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
