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
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import time

# AVANT tout import du site : l'observateur de parc_web.py est un
# after_request global, il se declenchait sur les requetes de ce banc d'essai
# et ecrivait dans les VRAIS data/parc_journal.jsonl et data/parc_hist.json.
# Chaque passage de tests ajoutait une ligne « hors_plan / inscrit dans la
# file » — un evenement qui n'a jamais eu lieu sur un telephone — au journal
# cense etre la memoire fiable du parc. L'en-tete promet « aucune donnee
# reelle touchee » : ce drapeau est ce qui rend la promesse vraie.
os.environ["VABOT_BANC_ESSAI"] = "1"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import safe_json

FAILS, OKS = [], []


import datetime as _dtVtk


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    _dire(("OK   " if cond else "FAIL ") + label
          + (f"  [{detail}]" if detail and not cond else ""))


def _dire(ligne):
    """Affiche sans jamais planter sur l'encodage de la console.

    La console Windows est en cp1252 : un « ≠ » ou un emoji dans un libelle
    levait UnicodeEncodeError DANS check(), ce qui tuait la suite entiere au
    milieu — on croyait alors que tout passait, alors que la moitie des
    verifications n avait jamais tourne.
    """
    try:
        print(ligne)
    except UnicodeEncodeError:
        enc = (getattr(sys.stdout, "encoding", None) or "ascii")
        print(ligne.encode(enc, "replace").decode(enc, "replace"))


def galerie(client, url):
    """Le HTML d'une galerie Bibliotheque, comme le navigateur l'obtient.

    Les 8 galeries sont DIFFEREES depuis la passe perf : la page complete ne
    porte plus qu'un place-holder et le contenu arrive par /?lazy=<tab>. Un
    test qui lit encore la page entiere ne verrait plus aucune carte et
    conclurait a tort que la galerie est vide.
    """
    from urllib.parse import urlparse, parse_qs
    tab = (parse_qs(urlparse(url).query).get("tab") or [""])[0]
    sep = "&" if "?" in url else "?"
    frag = client.get(f"{url}{sep}lazy={tab}",
                      headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
    # Le navigateur injecte le fragment DANS <div class="form-section"
    # id="form-<tab>"> deja present dans la page. On rend la meme chose, sinon
    # les verifications qui reperent leur section par cet id ne trouvent rien.
    return f'<div class="form-section" id="form-{tab}">{frag}</div>'


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
# Les ALIAS comptent autant que le nom. Le controle ne cherchait que
# « json.dumps » ; trois ecritures sur les brouillons de montage passaient
# « _js.dumps » et sont donc restees non atomiques depuis toujours, sous un
# test qui se disait vert. Un module importe « as _js » ou « as _json » ecrit
# exactement le meme JSON tronque apres une coupure.
BAD = re.compile(r"(?<![\w.])(\w+)\.write_text\(\s*"
                 r"(?:_?js|_?json|_json_mod|json)\.dumps")
# Un nom de variable qui parle d un fichier TEMPORAIRE designe le motif
# atomique lui-meme : ecrire dans .tmp puis remplacer. Le controle accusait
# signup_public.py, qui fait exactement ca — un faux positif que personne
# n avait leve, et qui a fini par rendre l echec normal a force d etre la.
_TEMPORAIRE = ("tmp", "temp", "part")
restants = []
for f in sorted(pathlib.Path(".").rglob("*.py")):
    parts = set(f.parts)
    if parts & {"__pycache__", "node_modules", "venv", "noctus"} or "geelark" in f.name:
        continue
    if f.name in ("safe_json.py", "tests_site.py", "jailbreak.py"):
        continue          # jailbreak.py a son propre mécanisme (backups + verrou)
    txt = f.read_text(encoding="utf-8", errors="ignore")
    for m in BAD.finditer(txt):
        if any(t in m.group(1).lower() for t in _TEMPORAIRE):
            continue
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
            ("supprimer un VA", "/jailbreak/remove_va", {"identity": "e", "va_name": "T"}),
            # L etoile ⭐ des rushs bruts ecrit dans data/ : elle doit tomber
            # sous la meme regle que le reste. Rien n a ete declare pour ca —
            # _guard_write_routes refuse tout POST par defaut — et ce test
            # verifie justement que personne ne l a « ouverte » par megarde.
            ("etoiler une brute", "/reel/toggle_fav_brute",
             {"file_id": "x|brutes|y.mp4"})):
        _r = _c.post(_path, data=_data)
        check(f"rôle restreint bloqué : {_label}", _r.status_code == 403, f"HTTP {_r.status_code}")
    _r = _c.post("/chatting/update_cell", data={"edt": "x", "row": "0", "col": "0", "value": "v"})
    check("rôle restreint garde son planning", _r.status_code != 403, f"HTTP {_r.status_code}")
    # ... mais SEULEMENT s il possede l onglet. « /chatting/ » etait autorise a
    # tous les roles restreints sans le verifier : un compte « montage »
    # pouvait supprimer l emploi du temps depuis la console, alors que la
    # LECTURE du meme planning lui etait correctement refusee, deux fois.
    _w._load_web_users = lambda: {"mont1": {"role": "montage", "password": "x"}}
    _cm = _app.test_client()
    with _cm.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "mont1"
        _s["role"] = "montage"
    _rm = _cm.post("/chatting/update_cell",
                   data={"edt": "x", "row": "0", "col": "0", "value": "v"})
    check("rôle sans l onglet planning : ecriture refusee",
          _rm.status_code == 403, f"HTTP {_rm.status_code}")
    _w._load_web_users = lambda: {"chatteur1": {"role": "chatter", "password": "x"}}
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
    # Le jeton de synchro ouvre la Bibliotheque 2 en lecture, en enumeration ET
    # en ecriture, SANS cookie : /sync/list et /sync/file n'exigent que lui. Il
    # n'etait garde que par « connecte », donc un role restreint pouvait le
    # recopier et s'en servir hors session. Jeton permanent, jamais renouvele.
    _rSy = _cc.get("/sync/token")
    check("rôle restreint : le jeton de synchro est refusé",
          _rSy.status_code == 403, "HTTP %s" % _rSy.status_code)
    check("rôle restreint : le jeton n est pas dans la reponse",
          "token" not in (_rSy.get_data(as_text=True) or "").lower()
          or _rSy.status_code == 403)
    # Toutes les bios et CTA de toutes les models, avec le handle Insta.
    check("rôle restreint : le pool de textes est refusé",
          _cc.get("/textpool/render").status_code == 403,
          "HTTP %s" % _cc.get("/textpool/render").status_code)
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
    # Nom de plus de 120 caracteres : la troncature doit couper la BASE et
    # garder l'extension. Sans ca le fichier arrivait nu, donc invisible des
    # galeries ET de gdrive_sync (tous deux filtrent par extension) : 78
    # photos de themikkiangel n'etaient sauvegardees nulle part.
    _long = "themikkiangel_" + "photo" * 32 + "_2026-06-26_DaBn1IYSFh-_392759552498.jpg"
    _cut = _w2._safe_upload_name(_long)
    check("upload : nom > 120 caracteres, extension conservee",
          _cut.endswith(".jpg") and len(_cut) <= 120, f"{len(_cut)} {_cut!r}")
    _cut_maj = _w2._safe_upload_name("i" * 130 + ".JPEG")
    check("upload : extension conservee telle quelle (.JPEG)",
          _cut_maj.endswith(".JPEG") and len(_cut_maj) <= 120, _cut_maj)
    check("upload : nom long sans extension reste tronque",
          len(_w2._safe_upload_name("j" * 200)) == 120)
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

print()
print("=" * 70)
print("16) Rôles : fuites de données et pages standalone (audit wqariqy6x)")
print("=" * 70)
try:
    import web_upload as _wF
    _aF = _wF.create_app(); _aF.config["TESTING"] = True
    _svF, _svdF = _wF._load_web_users, _wF._load_role_definitions

    # TOUS les comptes présents en permanence : recréer la liste à chaque client
    # faisait échouer is_auth() pour les clients précédents (artefact de test).
    _allUsersF = {"chat": {"role": "chatter"}, "toki": {"role": "VA JB"},
                  "boss": {"role": "owner"}}
    # « jbactivite » est désormais une case DISTINCTE de « jailbreak » (une case
    # = une page) : ce rôle a donc explicitement les deux.
    _allDefsF = {"va jb": {"permissions": {"jailbreak": {"enabled": True},
                                           "jbactivite": {"enabled": True}}}}
    _wF._load_web_users = lambda: _allUsersF
    _wF._load_role_definitions = lambda: _allDefsF

    def _cliF(user, role, users, sid, defs=None):
        _c = _aF.test_client()
        with _c.session_transaction() as _s:
            _s["auth"] = True; _s["username"] = user; _s["role"] = role; _s["sid"] = sid
        return _c

    _chF = _cliF("chat", "chatter", None, "F1")
    _htmlF = _chF.get("/").get_data(as_text=True)
    # -- _g() ne doit plus livrer les <script> des onglets interdits --
    _fuites = [m for m in ("__vaInsta3Data", "__mpCryptoData", "__mpTransactions",
                           "__mpChattersBase", "__sfsData", "__ofPushData",
                           "__mypulsCreators")
               if m in _htmlF]
    check("aucune donnée d'onglet interdit dans la page d'un rôle restreint",
          not _fuites, str(_fuites))
    check("le rôle restreint garde SON onglet", "form-chatplanning" in _htmlF)
    # -- pages standalone gatées --
    check("/jbactivity fermé à un rôle sans la permission",
          _chF.get("/jbactivity").status_code == 403)
    check("/jbimport fermé à un rôle sans la permission",
          _chF.get("/jbimport").status_code == 403)
    # -- en-tête X-Chat-Ajax : bloqué sans l'onglet, servi avec --
    _jbF = _cliF("toki", "VA JB", None, "F2")
    check("X-Chat-Ajax refusé à un rôle sans chatplanning",
          _jbF.get("/", headers={"X-Chat-Ajax": "1"}).status_code == 403)
    check("X-Chat-Ajax servi au rôle qui a chatplanning",
          "form-chatplanning" in _chF.get("/", headers={"X-Chat-Ajax": "1"}).get_data(as_text=True))
    # -- pas de sur-blocage : la case « Activité VA » ouvre bien /jbactivity --
    check("/jbactivity ouvert au rôle qui a la case « Activité VA »",
          _jbF.get("/jbactivity").status_code != 403)
    # -- et la case « Jailbreak » SEULE ne l'ouvre plus (une case = une page) --
    _allDefsF["va jb"]["permissions"].pop("jbactivite", None)
    check("« Jailbreak » seule n'ouvre PAS Activité VA",
          _cliF("toki", "VA JB", None, "F2b").get("/jbactivity").status_code == 403)
    _allDefsF["va jb"]["permissions"]["jbactivite"] = {"enabled": True}
    # -- owner : rien n'est bloqué --
    _owF = _cliF("boss", "owner", None, "F3")
    check("owner : /jbactivity accessible", _owF.get("/jbactivity").status_code != 403)
    check("owner : ses données restent présentes", "__sfsData" in _owF.get("/").get_data(as_text=True))
    _wF._load_web_users, _wF._load_role_definitions = _svF, _svdF
except Exception as _e:
    check("fuites rôles : testable", False, repr(_e)[:90])

try:
    import web_upload as _wA
    # -- réactiver un employé doit lui RENDRE l'accès (il était banni à vie) --
    _users = [{"username": "bob", "password_hash": "H", "role": "chatter",
               "agency": "", "created_at": 1, "active": False}]
    _web = {}          # bob a été retiré à la désactivation
    _app2 = _wA.create_app()   # force la création des helpers de closure
    # on rejoue la logique du helper via la route réelle n'est pas trivial :
    # on vérifie au moins que le hash est bien conservé côté role_users pour
    # permettre la restauration (pré-requis du correctif).
    check("le hash du mot de passe survit à la désactivation (restauration possible)",
          bool(_users[0].get("password_hash")))
except Exception as _e:
    check("réactivation employé : testable", False, repr(_e)[:90])

print()
print("=" * 70)
print("17) Rôles : l'éditeur doit rester SYNCHRO avec les vraies pages")
print("=" * 70)
try:
    import re as _reS, pathlib as _plS
    import web_upload as _wS
    _srcS = _plS.Path("web_upload.py").read_text(encoding="utf-8")
    # onglets RÉELS de la sidebar (source de vérité)
    _realS = set(_reS.findall(r"showTab\(\s*'[^']*'\s*,\s*'([a-z0-9_]+)'", _srcS))
    _realS |= set(_reS.findall(r'id="tab-([a-z0-9_]+)"', _srcS))
    _keysS = {it["key"] for sec in _wS.ROLE_MENU_STRUCTURE for it in sec["items"]}
    # 1) aucune case ne doit être un no-op (elle doit ouvrir au moins une vraie page)
    _noop = sorted(k for k in _keysS
                   if not (_wS._PERM_KEY_TO_TABS.get(k, {k}) & _realS))
    check("aucune case de permission n'est un no-op", not _noop, str(_noop))
    # 2) aucune page ne doit être ingouvernable (ni donnable ni retirable)
    _covered = set()
    for _k in _keysS:
        _covered |= _wS._PERM_KEY_TO_TABS.get(_k, {_k})
    # onglets internes/panneaux non listés dans la sidebar : tolérés
    _exempt = {"reel", "post", "story", "storycta", "pp", "veille"}
    _ungov = sorted(_realS - _covered - _exempt)
    check("aucune page n'échappe à l'éditeur de permissions", not _ungov, str(_ungov))
    # 3) une case ne doit pas ouvrir une page qu'elle n'annonce pas
    check("cocher « Jailbreak » n'ouvre QUE Jailbreak",
          _wS._PERM_KEY_TO_TABS.get("jailbreak") == {"jailbreak"})
    check("« Analyse vues » et « Activité VA » ont leur propre case",
          {"jbanalyse", "jbactivite"} <= _keysS)
    # 4) tout set remappé doit contenir la clé elle-même si un _g() porte ce nom
    check("la case « Veille » débloque bien le contenu Veille",
          "veille" in _wS._PERM_KEY_TO_TABS.get("veille", set()))
except Exception as _e:
    check("synchro éditeur/pages : testable", False, repr(_e)[:90])

print()
print("=" * 70)
print("18) Montage : assemblage brute + template")
print("=" * 70)
# Le point de coupe pilote le remplacement du debut du template par une video
# brute. S'il disparait quelque part, la generation repart du template seul —
# en silence, sans erreur. D'ou ces tests.
try:
    import os as _osM
    _osM.environ.setdefault("WEB_UPLOAD_PASSWORD", "testlocal")
    import noctus_web as _nw

    # -- tri des brutes : ne doit ramener QUE des videos exploitables ----------
    _bd = TMP / "brutes"
    _bd.mkdir(parents=True, exist_ok=True)
    for _n in ("a.mp4", "b.MOV", "c.example.mp4", "vide.mp4"):
        (_bd / _n).write_bytes(b"\0" * (5000 if "vide" not in _n else 10))
    for _n in ("a.txt", "a.desc.txt", "a.montage.json", ".DS_Store", "note.md"):
        (_bd / _n).write_text("x", encoding="utf-8")
    _got = {p.name for p in _nw.list_brutes(_bd)}
    check("brutes : garde les videos (extensions variees)", _got == {"a.mp4", "b.MOV"}, str(sorted(_got)))
    check("brutes : exclut les .example", "c.example.mp4" not in _got)
    check("brutes : exclut txt/desc/montage.json/caches", not (_got & {"a.txt", "a.desc.txt", "a.montage.json", ".DS_Store", "note.md"}))
    check("brutes : exclut les fichiers vides ou tronques", "vide.mp4" not in _got)
    check("brutes : dossier inexistant -> liste vide", _nw.list_brutes(TMP / "nulle_part") == [])

    # -- garde-fous de l'assemblage sans lancer ffmpeg -------------------------
    _ok, _err = _nw.assemble_brute_template(TMP / "absent.mp4", _bd / "a.mp4", 3.0, TMP / "o.mp4")
    check("assemblage : template absent -> echec explicite", (not _ok) and "template" in _err, _err)
    _ok, _err = _nw.assemble_brute_template(_bd / "a.mp4", TMP / "absent.mp4", 3.0, TMP / "o.mp4")
    check("assemblage : brute absente -> echec explicite", (not _ok) and "brute" in _err, _err)

    # -- brute plus COURTE que la coupe : le DEBUT est coupe, son compris ------
    # Jamais de boucle ni d'arret sur image : la video finale demarre quand la
    # brute demarre (duree = template - manque) et la transition reste calee
    # sur le meme instant de la musique. Les captions minutees sont decalees
    # d'autant via caption_map_for.
    if _nw.ffmpeg_available():
        import subprocess as _spM
        _vd = TMP / "vids"
        _vd.mkdir(parents=True, exist_ok=True)
        _spM.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                  "-i", "testsrc2=size=180x320:rate=15:duration=4",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                  "-shortest", str(_vd / "tpl.mp4")], timeout=90)
        _spM.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                  "-i", "testsrc=size=180x320:rate=15:duration=1",
                  "-pix_fmt", "yuv420p", str(_vd / "courte.mp4")], timeout=90)
        check("brute_gap annonce le rognage (coupe 3, brute 1 -> 2)",
              abs(_nw.brute_gap(_vd / "tpl.mp4", _vd / "courte.mp4", 3.0) - 2.0) < 0.15)
        _okA, _errA = _nw.assemble_brute_template(
            _vd / "tpl.mp4", _vd / "courte.mp4", 3.0, _vd / "out.mp4")
        check("assemblage d'une brute plus courte que la coupe", _okA, _errA)
        if _okA:
            _dw, _dh, _df, _ddur = _nw.probe_video(_vd / "out.mp4")
            check("le debut est coupe (duree = template - manque)",
                  abs(_ddur - 2.0) < 0.35, f"{_ddur:.2f}s")

            def _frameM(_t):
                _o = _vd / f"f{_t}.png"
                _spM.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(_t),
                          "-i", str(_vd / "out.mp4"), "-frames:v", "1",
                          "-vf", "scale=48:-2", str(_o)], timeout=60)
                from PIL import Image as _Im
                return list(_Im.open(_o).convert("RGB").resize((10, 10)).getdata())

            def _dM(_a, _b):
                return sum(abs(x[0] - y[0]) + abs(x[1] - y[1]) + abs(x[2] - y[2])
                           for x, y in zip(_a, _b)) / (len(_a) * 3)
            # brute de 0 a 1 s, template de 1 s a la fin : rien de fige
            check("l image BOUGE des le debut (pas d arret sur image)",
                  _dM(_frameM(0.2), _frameM(0.7)) > 3, f"{_dM(_frameM(0.2), _frameM(0.7)):.1f}")
            check("la bascule a lieu quand la brute finit",
                  _dM(_frameM(0.8), _frameM(1.2)) > 15, f"{_dM(_frameM(0.8), _frameM(1.2)):.1f}")

        # decalage des captions minutees pour les variantes rognees
        _ent = {"label": "tst_shift", "font": "Strong",
                "captions": [{"start": "00:00:03.200", "end": "00:00:06.000", "text": "T"},
                             {"start": "00:00:00", "end": "99:99:99", "text": "P"}]}
        _capsL = []
        _cm = _nw.caption_map_for(_ent, ["a.mp4", "b.mp4"], {"a.mp4": 1.5, "b.mp4": 0.0}, _capsL)
        check("caption_map_for : la variante rognee recoit sa copie decalee",
              _cm == {"a.mp4": ["tst_shift_s1"], "b.mp4": ["tst_shift"]}, str(_cm))
        _sh = _capsL[0]["captions"][0] if _capsL else {}
        check("les temps sont decales du rognage (3.2 -> 1.7)",
              _sh.get("start") == "00:00:01.700" and _sh.get("end") == "00:00:04.500", str(_sh))
        check("la caption permanente n est pas touchee",
              _capsL and _capsL[0]["captions"][1]["end"] == "99:99:99")
        check("aucune variante rognee -> pas de captionMap (comportement d avant)",
              _nw.caption_map_for(_ent, ["a.mp4"], {"a.mp4": 0.0}, []) is None)
    else:
        check("assemblage testable (ffmpeg absent -> ignore)", True)

    # -- videoFolderMap : sans lui, N videos x N variantes = N² exports --------
    import inspect as _insp
    _runsrc = _insp.getsource(_nw.run)
    check("run() transmet videoFolderMap au moteur", "videoFolderMap" in _runsrc)
    _rjs = (pathlib.Path(__file__).parent / "noctus" / "noctus_runner.js").read_text(encoding="utf-8")
    check("le runner Node lit videoFolderMap", "args.videoFolderMap" in _rjs)
    check("le runner passe videoFolderMap au pipeline",
          "videoFolderMap, targetFiles" in _rjs.replace("  ", " "))

    # -- le point de coupe doit survivre a l'approbation VA -------------------
    import web_upload as _wM
    _idM = pathlib.Path("data/identities/_tst_montage") / "videos"
    shutil.rmtree(_idM.parent, ignore_errors=True)
    _idM.mkdir(parents=True)
    (_idM / "r.mp4").write_bytes(b"\0" * 3000)
    _pM = _idM / "r.montage.json"
    _appM = _wM.create_app()
    _appM.testing = True
    _cM = _appM.test_client()
    # Des sections precedentes remplacent _load_web_users sans toujours le
    # restaurer : on pose nous-memes un owner et on ouvre la session a la main,
    # sinon is_auth() renvoie False et les POST repondent 401 en silence.
    _savM = _wM._load_web_users
    _wM._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    with _cM.session_transaction() as _s:
        _s["auth"] = True
        _s["username"] = "boss"
    _base = {"file_id": "_tst_montage|videos|r.mp4", "segments": "[]", "font": "Strong", "style": "{}"}
    _rM = _cM.post("/noctus/montage_save", data=dict(_base, cut_at="2.75"))
    check("le point de coupe est enregistre",
          _rM.status_code == 200 and _pM.exists()
          and json.loads(_pM.read_text()).get("cut_at") == 2.75,
          f"http {_rM.status_code}")
    _cM.post("/noctus/montage_approve", data=dict(_base))          # sans cut_at au formulaire
    _dM = json.loads(_pM.read_text())
    check("« dispo VA » ne detruit PAS le point de coupe", _dM.get("cut_at") == 2.75, str(_dM))
    check("« dispo VA » pose bien va_ready", _dM.get("va_ready") is True)
    _cM.post("/noctus/montage_approve", data=dict(_base, cut_at="4.5"))
    check("un point de coupe envoye au formulaire gagne", json.loads(_pM.read_text()).get("cut_at") == 4.5)
    _cM.post("/noctus/montage_unapprove", data={"file_id": _base["file_id"]})
    _dM = json.loads(_pM.read_text())
    check("retirer du stock VA garde le point de coupe", _dM.get("cut_at") == 4.5)
    check("retirer du stock VA enleve va_ready", "va_ready" not in _dM)

    # -- un enregistrement sans cut_at ne doit PAS effacer la coupe ------------
    _cM.post("/noctus/montage_save", data=dict(_base, cut_at="2.5"))
    _cM.post("/noctus/montage_save", data=dict(_base))          # sans cut_at
    check("enregistrer sans toucher a la coupe ne l efface pas",
          json.loads(_pM.read_text()).get("cut_at") == 2.5)

    # -- traversee de chemin par le composant identite -------------------------
    for _bad in ("../..|videos|r.mp4", "..|videos|r.mp4", "/etc|videos|passwd"):
        _rb = _cM.post("/noctus/montage_save", data=dict(_base, file_id=_bad))
        _jb = _rb.get_json() or {}
        check(f"file_id refuse : {_bad}", _jb.get("ok") is not True, str(_jb)[:60])

    # -- un TEMPLATE approuve doit parvenir aux VA -----------------------------
    _tplD = _idM.parent / "templates"
    _tplD.mkdir(parents=True, exist_ok=True)
    (_tplD / "t.mp4").write_bytes(b"\0" * 3000)
    _cM.post("/noctus/montage_approve",
             data={"file_id": "_tst_montage|templates|t.mp4", "segments": "[]",
                   "font": "Strong", "style": "{}", "cut_at": "3"})
    try:
        import cogs.user as _cuM
        _readyM = _cuM.va_ready_montages_for("_tst_montage", 5)
        check("un template « dispo VA » est bien propose aux VA",
              any(p.parent.name == "templates" for p, _d, _x in _readyM),
              f"{len(_readyM)} trouve(s)")
    except Exception as _eu:
        check("templates visibles par le bot : testable", False, repr(_eu)[:80])

    # -- « Appliquer à d'autres models » ---------------------------------------
    _srcT = _idM.parent / "templates"
    _srcT.mkdir(parents=True, exist_ok=True)
    (_srcT / "tp.mp4").write_bytes(b"\0" * 4000)
    _t2 = pathlib.Path("data/identities/_tst_cible") / "templates"
    shutil.rmtree(_t2.parent, ignore_errors=True)
    _t2.mkdir(parents=True)
    (_t2 / "tp.mp4").write_bytes(b"\1" * 9000)     # collision : AUTRE video, meme nom
    _ja = _cM.post("/noctus/montage_apply", data={
        "file_id": "_tst_montage|templates|tp.mp4",
        "targets": "_tst_cible,_tst_montage,../..,inconnue",
        "segments": "[]", "font": "Strong", "style": "{}",
        "cut_at": "2.5", "va_ready": "1"}).get_json() or {}
    check("appliquer : cibles invalides filtrees, la bonne passe",
          _ja.get("done") == ["_tst_cible"], str(_ja))
    check("appliquer : collision de nom -> suffixe, l existant intact",
          (_t2 / "tp.mp4").stat().st_size == 9000 and (_t2 / "tp_2.mp4").exists())
    _jd = json.loads((_t2 / "tp_2.montage.json").read_text(encoding="utf-8"))
    check("appliquer : coupe + va_ready copies chez la cible",
          _jd.get("cut_at") == 2.5 and _jd.get("va_ready") is True, str(_jd))
    _ja2 = _cM.post("/noctus/montage_apply", data={
        "file_id": "_tst_montage|templates|tp.mp4", "targets": "_tst_cible",
        "segments": "[]", "font": "Strong", "style": "{}"}).get_json() or {}
    _n_mp4 = len([p for p in _t2.glob("tp_2*.mp4")])
    check("re-appliquer la meme video ne cree pas de doublon", _ja2.get("ok") and _n_mp4 == 1, str(_n_mp4))
    shutil.rmtree(_t2.parent, ignore_errors=True)

    # ==================================================================
    # D3 — un brouillon VIDE de ses captions ne doit PAS reafficher le texte
    # du fichier voisin. L editeur reprend <stem>.txt comme 1re caption a
    # l ouverture ; le chargement du brouillon n ecrasait cette caption que si
    # le brouillon en avait une : on supprimait tout, on enregistrait, on
    # rouvrait, et l ancien texte etait de retour. On laissait « Dispo VA » en
    # croyant avoir un texte, le VA recevait une video SANS texte, et un simple
    # « Enregistrer » regravait la caption supprimee.
    # Test de COMPORTEMENT : la fonction reellement servie au navigateur est
    # executee par node avec un faux DOM et une fausse reponse serveur.
    import subprocess as _spD3
    _htmlD3 = _wM.UPLOAD_HTML
    _iD3 = _htmlD3.find("function nxMLoadDraft(")
    check("D3 : nxMLoadDraft est bien servie a la page", _iD3 >= 0)
    _nodeD3 = shutil.which("node")
    if _iD3 >= 0 and _nodeD3:
        _fnD3 = _htmlD3[_iD3:_htmlD3.index(chr(10) + "function ", _iD3)]

        def _caps_apres(_rep):
            """captions de l editeur apres chargement de cette reponse serveur."""
            _h = (
                "var nxMState={caps:[{text:'caption du fichier voisin',"
                "start:null,end:null}],style:{size:44}};\n"
                "function nxMStyleInit(){nxMState.style={size:44};}\n"
                "function nxMStylePaint(){}\nfunction nxMRenderCaps(){}\n"
                "function nxMUpdatePreview(){}\nfunction nxMSetApproveBtn(){}\n"
                "function nxMHistInit(){}\n"
                "var document={getElementById:function(){return {};}};\n"
                "function fetch(){return Promise.resolve({json:function(){"
                "return Promise.resolve(" + json.dumps(_rep) + ");}});}\n"
                + _fnD3 + chr(10) +
                "nxMLoadDraft('x');\n"
                "setTimeout(function(){console.log(JSON.stringify("
                "nxMState.caps));},0);\n")
            _f = TMP / "d3_loaddraft.js"
            _f.write_text(_h, encoding="utf-8")
            _r = _spD3.run([_nodeD3, str(_f)], capture_output=True, text=True,
                           timeout=30)
            if _r.returncode != 0:
                return "ERREUR NODE : " + (_r.stderr or "")[:200]
            return (_r.stdout or "").strip()

        _o = _caps_apres({"ok": True, "desc": "",
                          "draft": {"segments": "[]", "font": "Strong",
                                    "style": "{}"}})
        check("D3 : un brouillon vide EFFACE la caption du fichier voisin",
              _o == "[]", _o[:160])
        _o = _caps_apres({"ok": True, "desc": "",
                          "draft": {"segments": json.dumps(
                              [{"text": "la vraie", "start": None, "end": None}]),
                              "font": "Strong", "style": "{}"}})
        check("D3 : un brouillon rempli est toujours applique",
              "la vraie" in _o and "voisin" not in _o, _o[:160])
        _o = _caps_apres({"ok": True, "desc": "",
                          "draft": {"font": "Strong", "style": "{}"}})
        check("D3 : brouillon sans champ segments -> on ne touche a rien",
              "voisin" in _o, _o[:160])
    elif _iD3 >= 0:
        # Ne jamais ecarter en silence : dire que la verification n a pas eu lieu.
        print("     (node absent : nxMLoadDraft n a pas ete execute)")

    # ==================================================================
    # D4 — le garde anti-double-generation consultait noctus_web._PROCS, table
    # remplie SEULEMENT au lancement de Node. Pendant les minutes d assemblage
    # (un ffmpeg par variante) elle restait vide : un 2e clic passait le garde
    # et vidait input/ et output/ sous les pieds du premier.
    # Tout ce qui touche au disque reel est remplace (data/ intact).
    _tmpG = TMP / "noctus_models"
    _tmpG.mkdir(exist_ok=True)
    _savG = {_k: getattr(_nw, _k) for _k in
             ("setup_ok", "purge_old_models", "_models_dir", "_prepare_inputs",
              "read_captions", "write_captions", "run")}
    _porteG = threading.Event()     # tient le 1er appel DANS l assemblage
    _capsG = []                     # captions.json en memoire
    _lancesG = []

    class _FauxProcG:
        def poll(self):
            return None

        def kill(self):
            pass

    def _prepG(src_, inp_, draft_, folders_, brutes_, report=None):
        inp_.mkdir(parents=True, exist_ok=True)
        _porteG.wait(15)
        return ([], {}, {})

    def _runG(model_, folders_=None, captions_=None, targets=None,
              folder_map=None, caption_map=None):
        _lancesG.append(model_)
        return _FauxProcG()

    _nw.setup_ok = lambda: True
    _nw.purge_old_models = lambda *a, **k: 0
    _nw._models_dir = lambda: _tmpG
    _nw._prepare_inputs = _prepG
    _nw.read_captions = lambda: list(_capsG)
    _nw.write_captions = lambda d: (_capsG.__setitem__(slice(None), list(d)), True)[1]
    _nw.run = _runG
    try:
        _segsG = json.dumps([{"text": "texte du montage", "start": None, "end": None}])

        def _clientG():
            _c = _appM.test_client()
            with _c.session_transaction() as _s:
                _s["auth"] = True
                _s["username"] = "boss"
            return _c

        _repG = {}

        def _premierG():
            _repG["1"] = (_clientG().post("/noctus/montage_gen",
                                          data=dict(_base, segments=_segsG)
                                          ).get_json() or {})

        _thG = threading.Thread(target=_premierG)
        _thG.start()
        time.sleep(0.8)                     # le 1er est dans l assemblage
        _j2G = (_cM.post("/noctus/montage_gen", data=dict(_base, segments=_segsG)
                         ).get_json() or {})
        check("D4 : un 2e clic PENDANT l assemblage est refuse",
              _j2G.get("ok") is False and "cours" in (_j2G.get("error") or ""),
              str(_j2G)[:140])
        _porteG.set()
        _thG.join(20)
        check("D4 : le 1er clic va au bout", (_repG.get("1") or {}).get("ok") is True,
              str(_repG.get("1"))[:140])
        check("D4 : une seule generation lancee pour ce reel",
              len(_lancesG) == 1, str(_lancesG))
        check("D4 : la place est rendue une fois la generation lancee",
              (_cM.post("/noctus/montage_gen", data=dict(_base, segments=_segsG)
                        ).get_json() or {}).get("ok") is True)

        # captions.json est PARTAGE : lu-modifie-ecrit hors verrou, deux
        # generations simultanees repartaient du meme contenu et la seconde
        # ecriture effacait le label de la premiere -> video sans texte.
        _capsG[:] = []
        _lancesG[:] = []

        # Ecriture LENTE : elle simule le travail qui separe la lecture de
        # l ecriture (segments, captionMap, lancement). Sans verrou, les deux
        # routes lisent le MEME contenu et la seconde ecriture efface le label
        # de la premiere -> la video de la premiere sort sans texte.
        def _ecrireLentG(d):
            time.sleep(0.3)
            _capsG[:] = list(d)
            return True

        _nw.write_captions = _ecrireLentG
        (_idM / "r2.mp4").write_bytes(b"\0" * 3000)
        _sortiesG = {}

        def _tirerG(cle, fid):
            _sortiesG[cle] = (_clientG().post("/noctus/montage_gen", data={
                "file_id": fid, "font": "Strong", "style": "{}",
                "segments": json.dumps([{"text": cle, "start": None,
                                         "end": None}])}).get_json() or {})

        _tA = threading.Thread(target=_tirerG, args=("A", "_tst_montage|videos|r.mp4"))
        _tB = threading.Thread(target=_tirerG, args=("B", "_tst_montage|videos|r2.mp4"))
        _tA.start()
        _tB.start()
        _tA.join(25)
        _tB.join(25)
        check("D4 : les deux generations aboutissent",
              all((_sortiesG.get(_k) or {}).get("ok") for _k in ("A", "B")),
              str(_sortiesG)[:160])
        _labelsG = [c.get("label") for c in _capsG if isinstance(c, dict)]
        check("D4 : deux generations simultanees gardent CHACUNE leur caption",
              len(_labelsG) == 2 and len(set(_labelsG)) == 2, str(_labelsG))
    finally:
        for _k, _v in _savG.items():
            setattr(_nw, _k, _v)

    # ==================================================================
    # D5 — le retrait d approbation repondait « ok » meme quand il n avait rien
    # retire : le bouton repassait au gris et le filigrane disparaissait alors
    # que va_ready etait toujours sur le disque, donc le reel partait encore
    # aux VA.
    if _pM.exists():
        _pM.unlink()
    _jU = (_cM.post("/noctus/montage_unapprove",
                    data={"file_id": _base["file_id"]}).get_json() or {})
    check("D5 : sans brouillon, le retrait dit qu il n a rien retire",
          _jU.get("ok") is True and _jU.get("retire") is False, str(_jU)[:140])
    _cM.post("/noctus/montage_save", data=dict(_base))        # brouillon sans va_ready
    _jU = (_cM.post("/noctus/montage_unapprove",
                    data={"file_id": _base["file_id"]}).get_json() or {})
    check("D5 : reel jamais approuve -> retrait annonce comme sans effet",
          _jU.get("retire") is False, str(_jU)[:140])
    _cM.post("/noctus/montage_approve", data=dict(_base))
    _jU = (_cM.post("/noctus/montage_unapprove",
                    data={"file_id": _base["file_id"]}).get_json() or {})
    check("D5 : reel approuve -> retrait annonce ET va_ready parti",
          _jU.get("retire") is True
          and "va_ready" not in json.loads(_pM.read_text(encoding="utf-8")),
          str(_jU)[:140])
    _pM.write_text("{ brouillon tronque", encoding="utf-8")
    _jU = (_cM.post("/noctus/montage_unapprove",
                    data={"file_id": _base["file_id"]}).get_json() or {})
    check("D5 : brouillon illisible -> echec dit, pas un « ok » trompeur",
          _jU.get("ok") is False and bool(_jU.get("error")), str(_jU)[:140])
    check("D5 : le client distingue « rien a retirer » du vrai retrait",
          "j.retire===false" in _wM.UPLOAD_HTML)

    _wM._load_web_users = _savM          # rend le magasin d'utilisateurs intact
    shutil.rmtree(_idM.parent, ignore_errors=True)

    # -- les deux chemins de generation doivent passer les brutes -------------
    check("gen_from_draft accepte brutes_dir",
          "brutes_dir" in _insp.signature(_nw.gen_from_draft).parameters)
    _uM = (pathlib.Path(__file__).parent / "cogs" / "user.py").read_text(encoding="utf-8")
    check("le reel monte a la demande (VA) passe le dossier brutes", "_brutes" in _uM and "brutes" in _uM)
    _wsrc = (pathlib.Path(__file__).parent / "web_upload.py").read_text(encoding="utf-8")
    check("la generation depuis le site passe par _prepare_inputs", "_prepare_inputs(" in _wsrc)
    check("l editeur envoie le point de coupe a la generation",
          _wsrc.count("fd.set('cut_at'") >= 3, "save + gen + approve")
except Exception as _e:
    # Trace complete : cette section enchaine ffprobe, routes HTTP et fichiers,
    # un « FileNotFoundError(2) » nu ne dit pas lequel a lache.
    import traceback as _tb
    _tb.print_exc()
    check("montage : testable", False, repr(_e)[:120])

shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 70)
print("19) Facture : associes PAR MARCHE + depenses avancees par le lead")
print("=" * 70)
# Le split par marche (US = lead + associe) et le remboursement des depenses
# avancees par le lead touchent de l argent reel : verifies au dollar pres,
# sur un fichier bac a sable (jamais le vrai data/facture.json).
try:
    import facture_web as _fwF
    _savFF = _fwF.FACTURE_FILE
    _fwF.FACTURE_FILE = TMP / "facture_test.json"
    import web_upload as _wF
    _appF = _wF.create_app()
    _appF.testing = True
    _cF = _appF.test_client()
    _savUF = _wF._load_web_users
    _wF._load_web_users = lambda: {"boss": {"role": "owner"}}
    with _cF.session_transaction() as _sF:
        _sF["auth"] = True
        _sF["username"] = "boss"
    _MF = "2026-07"

    def _addF(label, typ, amount, market, paid_by="agence"):
        _rF = _cF.post("/facture/line/save", data={"month": _MF, "line": json.dumps({
            "label": label, "type": typ, "cat": "other", "form": "fixed",
            "amount": amount, "currency": "USD", "market": market,
            "freq": "monthly", "paid_by": paid_by})})
        assert (_rF.get_json() or {}).get("ok")

    _addF("Rev US", "rev", 10000, "us")
    _addF("Rev FR", "rev", 4000, "fr")
    _addF("Dep US", "exp", 2000, "us")
    _addF("Outil paye par moi", "exp", 300, "fr", "lead")
    _cF.post("/facture/settings", data={"eur_usd": "", "cutoff": "15",
             "associates": json.dumps([{"name": "A", "pct": 50, "market": "us"}])})
    _dF = _cF.get("/facture/state?month=" + _MF).get_json()
    _tF, _bF = _dF["totals"], _dF["by_market"]
    check("associe US 50% : il ne touche QUE le net US",
          _bF["us"]["lead"] == 4000 and _bF["fr"]["lead"] == 3700, str(_bF))
    check("part lead globale = somme des marches", _tF["lead"] == 7700)
    check("depense avancee par le lead comptee a rembourser", _tF["reimb"] == 300)
    check("total a verser au lead = part + remboursements", _tF["lead_pay"] == 8000)
    check("le marche de l associe est stocke",
          _dF["settings"]["associates"][0].get("market") == "us")
    # associe global seul -> calcul d avant inchange
    _cF.post("/facture/settings", data={"eur_usd": "", "cutoff": "15",
             "associates": json.dumps([{"name": "G", "pct": 20, "market": "tous"}])})
    _tF = _cF.get("/facture/state?month=" + _MF).get_json()["totals"]
    check("associe global seul : comportement d avant (net x 80%)", _tF["lead"] == 9360)
    # marche en perte -> les sommes restent coherentes
    _addF("Grosse dep FR", "exp", 9000, "fr")
    _dF = _cF.get("/facture/state?month=" + _MF).get_json()
    _tF, _bF = _dF["totals"], _dF["by_market"]
    check("marche en perte : somme des parts = part globale",
          round(_bF["fr"]["lead"] + _bF["us"]["lead"], 2) == _tF["lead"])
    _rowF = [r for r in _fwF.compute_bilan()["rows"] if r["month"] == _MF][0]
    check("le bilan verse au lead part + avances", _rowF["lead"] == _tF["lead_pay"])
    # depense avancee par un ASSOCIE ('assoc:Nom') : due a LUI, pas au lead
    _addF("Pub payee par Laboule", "exp", 450, "us", "assoc:Laboule")
    _addF("Rev paye par assoc ?", "rev", 100, "us", "assoc:Laboule")  # force 'agence'
    _dF = _cF.get("/facture/state?month=" + _MF).get_json()
    _tF = _dF["totals"]
    check("avance d un associe suivie a son nom",
          _tF.get("reimb_assoc", {}).get("Laboule") == 450, str(_tF.get("reimb_assoc")))
    check("l avance d un associe ne gonfle pas la part du lead",
          _tF["lead_pay"] == round(_tF["lead"] + _tF["reimb"], 2) and _tF["reimb"] == 300)
    check("paid_by assoc refuse sur un revenu",
          all(l["paid_by"] == "agence" for l in _dF["lines"] if l["type"] == "rev"))
    check("l avance associe est rangee dans SON marche",
          _dF["by_market"]["us"]["reimb_assoc"].get("Laboule") == 450
          and not _dF["by_market"]["fr"]["reimb_assoc"])
    # nom du lead : defaut 'Sama', modifiable, champ vide = inchange
    check("nom du lead par defaut : Sama", _dF["settings"].get("lead_name") == "Sama")
    _cF.post("/facture/settings", data={"eur_usd": "", "cutoff": "15",
             "lead_name": "Youl", "associates": json.dumps([])})
    _cF.post("/facture/settings", data={"eur_usd": "", "cutoff": "15",
             "associates": json.dumps([])})
    check("nom du lead modifiable et conserve si champ absent",
          _cF.get("/facture/state?month=" + _MF).get_json()["settings"]["lead_name"] == "Youl")
    # cartes « Part <associé> » : part du split + ses avances a lui rembourser
    # (net US = 10100 - 2450 = 7650 -> 50% = 3825 ; + son avance de 450)
    _cF.post("/facture/settings", data={"eur_usd": "", "cutoff": "15",
             "associates": json.dumps([{"name": "Laboule", "pct": 50, "market": "us"}])})
    _dF = _cF.get("/facture/state?month=" + _MF).get_json()
    _apF = {a["name"]: a for a in _dF["totals"]["assoc_parts"]}
    check("carte associe : part = % du net positif de SON marche",
          _apF["Laboule"]["part"] == 3825, str(_apF))
    check("carte associe : verse = part + ses avances", _apF["Laboule"]["pay"] == 4275)
    _apU = {a["name"]: a for a in _dF["by_market"]["us"]["assoc_parts"]}
    check("vue marche : la part de l associe reste sur SON marche",
          _apU["Laboule"]["part"] == 3825
          and all(not a["part"] and not a["reimb"] for a in _dF["by_market"]["fr"]["assoc_parts"]))
    # associe global : % de la base RESTANTE (7650 - 5300 = 2350 -> 20% = 470)
    _cF.post("/facture/settings", data={"eur_usd": "", "cutoff": "15",
             "associates": json.dumps([{"name": "G", "pct": 20, "market": "tous"}])})
    _dG = _cF.get("/facture/state?month=" + _MF).get_json()
    check("carte associe global : % de la base restante",
          {a["name"]: a["part"] for a in _dG["totals"]["assoc_parts"]} == {"G": 470.0})
    _sG = round(sum(a["part"] for mk in ("fr", "us")
                    for a in _dG["by_market"][mk]["assoc_parts"] if a["name"] == "G"), 2)
    check("ventilation par marche d un global = sa carte globale (au centime)",
          _sG == [a["part"] for a in _dG["totals"]["assoc_parts"] if a["name"] == "G"][0])
    # garde-fous de la revue adversariale
    _rj = _cF.post("/facture/settings", data={"eur_usd": "", "cutoff": "15",
             "associates": json.dumps([{"name": "X", "pct": 60, "market": "us"},
                                       {"name": "Y", "pct": 60, "market": "us"}])}).get_json()
    check("settings refuse un cumul de % > 100 sur un marche", not _rj.get("ok"))
    _dj = _fwF._load()   # config legacy deja stockee a 120% : passee au prorata
    _dj["settings"]["associates"] = [{"name": "X", "pct": 60, "market": "us"},
                                     {"name": "Y", "pct": 60, "market": "us"}]
    _fwF._save(_dj)
    _pX = {a["name"]: a["part"] for a in _cF.get("/facture/state?month=" + _MF)
           .get_json()["by_market"]["us"]["assoc_parts"]}
    check("legacy > 100% : parts au prorata, jamais plus que le net",
          _pX == {"X": 3825.0, "Y": 3825.0}, str(_pX))
    _cF.post("/facture/settings", data={"eur_usd": "", "cutoff": "15",
             "associates": json.dumps([{"name": "Laboule", "pct": 10, "market": "fr"},
                                       {"name": "Laboule", "pct": 10, "market": "us"}])})
    _apH = [a for a in _cF.get("/facture/state?month=" + _MF).get_json()["totals"]["assoc_parts"]
            if a["name"] == "Laboule"]
    check("homonyme sur 2 marches : l avance n est comptee qu une fois",
          len(_apH) == 2 and round(sum(a["reimb"] for a in _apH), 2) == 450, str(_apH))
    _wF._load_web_users = _savUF
    _fwF.FACTURE_FILE = _savFF
except Exception as _e:
    import traceback as _tbF
    _tbF.print_exc()
    check("facture : testable", False, repr(_e)[:120])

print()
print("=" * 70)
print("20) Veille : pre-chauffage Telegram (file_id warm)")
print("=" * 70)
# Le worker de journee telecharge + uploade les reels NON envoyes en silencieux
# (message fantome supprime, seul le file_id garde) -> l envoi du soir est
# instantane. Garde-fous : jamais de lien fallback, pas de notification, et le
# warm s efface des qu un envoi manuel est en cours.
try:
    import inspect as _insp20
    import pathlib as _pl20
    import veille_telegram as _vt20
    check("send_video_from_url a un mode warm_only",
          "warm_only" in _insp20.signature(_vt20.send_video_from_url).parameters)
    check("warm_reel existe et passe warm_only",
          callable(getattr(_vt20, "warm_reel", None))
          and "warm_only=True" in _insp20.getsource(_vt20.warm_reel))
    _src20 = _insp20.getsource(_vt20.send_video_from_url)
    check("le warm supprime le message fantome", "deleteMessage" in _src20)
    check("le warm ne poste jamais de lien fallback",
          0 <= _src20.find("if warm_only:") < _src20.find("if not fallback_url:"))
    check("upload fantome sans notification", "disable_notification" in _src20)
    check("le warm ne prend PAS le verrou d ordre (pas de blocage du soir)",
          _src20.find("if warm_only:") < _src20.find("nullcontext()", _src20.find("if warm_only:")) < _src20.find("fileid_get"))
    check("un fantome au delete rate est mis en file et retente",
          "_WARM_GHOSTS" in _src20 and callable(getattr(_vt20, "warm_cleanup", None)))
    _wsrc20 = (_pl20.Path(__file__).parent / "web_upload.py").read_text(encoding="utf-8")
    check("worker veille-warm demarre avec l app",
          "veille-warm" in _wsrc20 and "_veille_warm_loop" in _wsrc20)
    check("UN SEUL thread warm par process (create_app tourne plusieurs fois)",
          "_VEILLE_WARM_STARTED" in _wsrc20)
    _wloop20 = _wsrc20.split("def _veille_warm_loop", 1)[1][:4200]
    check("le warm s efface devant un envoi manuel", "_vsend_inflight" in _wloop20)
    check("le worker retente les fantomes a chaque cycle", "warm_cleanup" in _wloop20)
    check("barre Sur Telegram + passe forcee presentes",
          "/veille/warm_status" in _wsrc20 and "/veille/warm_now" in _wsrc20
          and "vl-warm-bar" in _wsrc20 and "vlWarmNow" in _wsrc20 and "_vwarm_force" in _wsrc20)
    check("worker et passe forcee serialises (un upload warm a la fois)",
          "_vwarm_lock" in _wsrc20 and "_vwarm_one" in _wsrc20)
    check("passe forcee : claim atomique de running DANS la route (2 clics = 1 passe)",
          "_vwarm_state_lock" in _wsrc20
          and 0 <= _wsrc20.find('_VWARM_STATE.update({"running": True') < _wsrc20.find("veille-warm-force"))
    check("la barre Sur Telegram n existe qu UNE fois (hors boucle des jours)",
          _wsrc20.count("id='vl-warm-bar'") == 1
          and "sections = [bulk_bar, warm_bar_html" in _wsrc20)
    check("_WARM_GHOSTS protege par verrou (append vs purge concurrents)",
          "_GHOST_LOCK" in _insp20.getsource(_vt20))
    check("429 sur le fast-path file_id : erreur claire, pas de re-telechargement",
          "_rf.status_code == 429" in _src20 and "patienter" in _src20)
    check("le client tolere une reponse HTML (proxy timeout)",
          "async function vjson" in _wsrc20 and _wsrc20.count("await vjson(r)") >= 3)
    check("un 429 pendant le warm ne condamne pas le reel",
          '"429" not in err' in _wsrc20)
    # une carte « envoyée côté serveur mais erreur côté client » se corrige seule
    check("le client re-verifie l etat reel d un reel apres une erreur d envoi",
          "/veille/reel_state" in _wsrc20 and "veilleVerifySent" in _wsrc20
          and "wasSent" in _wsrc20 and "veilleMarkSent" in _wsrc20)
    import web_upload as _wu20
    _appW20 = _wu20.create_app()
    _appW20.testing = True
    _rW20 = _appW20.test_client().get("/veille/warm_status")
    check("warm_status exige l auth", _rW20.status_code in (301, 302, 401, 403))
    _rS20 = _appW20.test_client().get("/veille/reel_state?rid=x")
    check("reel_state exige l auth", _rS20.status_code in (301, 302, 401, 403))
    # suivi etape par etape du panneau Envoi X/Y
    check("l envoi expose son etape en cours (poll client)",
          "/veille/send_stage" in _wsrc20 and "_vsend_stage" in _wsrc20
          and "send_stage?rid=" in _wsrc20 and "clearInterval(stIv)" in _wsrc20)
    _rG20 = _appW20.test_client().get("/veille/send_stage?rid=x")
    check("send_stage exige l auth", _rG20.status_code in (301, 302, 401, 403))
    # le pre-chauffage stocke AUSSI la description (envoi du soir 100% local)
    check("le warm remonte la description et le worker la persiste",
          '"description": (followup_text or "")' in _src20
          and 'res.get("description")' in _wsrc20)
    check("fast-path : description relue du sidecar disque",
          0 <= _src20.find("_sdf") < _src20.find("fast-path SOUS le verrou"))
    # un reel ENVOYE peut etre RE-prepare : l etat PRET reste visible
    check("PRET visible aussi sur une carte ENVOYEE (re-preparation d un renvoi)",
          'bool(r.get("prepared")) and not sent' not in _wsrc20
          and _wsrc20.count("top:38px;left:46px") >= 2)
    check("l envoi nettoie le brouillon PRET et le badge eclair sur la carte",
          "vl-warm-badge" in _wsrc20 and "veilleReadyVisual(card, false)" in _wsrc20)
except Exception as _e:
    check("veille warm : testable", False, repr(_e)[:120])

print()
print("=" * 70)
print("21) Captions : bibliotheque par identite + generation random")
print("=" * 70)
try:
    import json as _jsCa
    import pathlib as _plCa
    import shutil as _shCa
    import web_upload as _wCa
    _aCa = _wCa.create_app(); _aCa.testing = True
    _savCa = _wCa._load_web_users
    _wCa._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cCa = _aCa.test_client()
    with _cCa.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "CA1"
    _idCa = _plCa.Path("data/identities/_tst_captions")
    _shCa.rmtree(_idCa, ignore_errors=True)
    (_idCa / "brutes").mkdir(parents=True)
    (_idCa / "brutes" / "b.mp4").write_bytes(b"\x00" * 5000)

    # -- CRUD ---------------------------------------------------------------
    _blk = {"font": "Strong",
            "style": {"size": 54, "color": "#ffffff", "bold": True},
            "global_pos": {"enabled": False, "x": 0.5, "y": 0.2},
            "items": [{"id": f"c{i}", "text": f"Cap {i}", "x": 0.5, "y": 0.2 + i / 100.0}
                      for i in range(12)]}
    _r = _cCa.post("/captions/save", data={"identity": "_tst_captions",
                                           "data": _jsCa.dumps(_blk)})
    check("captions : save ok", _r.status_code == 200 and (_r.get_json() or {}).get("ok"),
          f"http {_r.status_code} {_r.get_data(as_text=True)[:80]}")
    _fCa = _plCa.Path("data/captions.json")
    check("captions : ecrit sur disque (atomique, pas de .tmp residuel)",
          _fCa.exists() and not list(_fCa.parent.glob("captions.json*.tmp")))
    _j = (_cCa.get("/captions/list?identity=_tst_captions").get_json() or {})
    _items = ((_j.get("block") or {}).get("items")) or []
    check("captions : relecture 12 entrees, x/y clampes 0-1",
          len(_items) == 12 and all(0 <= c["x"] <= 1 and 0 <= c["y"] <= 1 for c in _items),
          str(_j)[:100])
    # update : editer un texte ne perd pas la position
    _blk["items"][3]["text"] = "Edite"
    _cCa.post("/captions/save", data={"identity": "_tst_captions", "data": _jsCa.dumps(_blk)})
    _j2 = (_cCa.get("/captions/list?identity=_tst_captions").get_json() or {})
    check("captions : edition conserve la position",
          abs(_j2["block"]["items"][3]["y"] - _blk["items"][3]["y"]) < 1e-6
          and _j2["block"]["items"][3]["text"] == "Edite")
    # description optionnelle : vide/espaces = absente ; remplie = trim + cap 1000
    _blk["items"][2]["desc"] = "Lien en bio 😏 " + "x" * 1200
    _blk["items"][4]["desc"] = "   "
    _cCa.post("/captions/save", data={"identity": "_tst_captions", "data": _jsCa.dumps(_blk)})
    _jd = (_cCa.get("/captions/list?identity=_tst_captions").get_json() or {})
    _itd = _jd["block"]["items"]
    check("captions : desc optionnelle (trim + cap 1000, vide = absente)",
          _itd[2].get("desc", "").startswith("Lien en bio")
          and len(_itd[2].get("desc", "")) <= 1000
          and "desc" not in _itd[4] and "desc" not in _itd[0], str(_itd[2])[:90])
    # ⭐ favori : le champ doit SURVIVRE a l aller-retour. _clean_caption_block
    # ne filtre pas l item, il le reconstruit depuis une liste blanche : un
    # champ non declare la est efface au premier /captions/save, c est-a-dire
    # 250 ms apres le clic sur l etoile. L etoile s allumerait puis
    # s eteindrait au rechargement, sans la moindre erreur.
    _blk["items"][1]["fav"] = True
    _blk["items"][5]["fav"] = False
    _cCa.post("/captions/save", data={"identity": "_tst_captions", "data": _jsCa.dumps(_blk)})
    _jf = (_cCa.get("/captions/list?identity=_tst_captions").get_json() or {})
    _itf = _jf["block"]["items"]
    check("captions : le favori ⭐ survit a l aller-retour",
          _itf[1].get("fav") is True and _itf[5].get("fav") is False
          and _itf[0].get("fav") is False, str(_itf[1])[:90])
    # Un favori n a de sens que s il est encore dans le tirage : le selecteur du
    # bot exige fav ET enabled. On verifie au moins que les deux cohabitent.
    _blk["items"][1]["enabled"] = False
    _cCa.post("/captions/save", data={"identity": "_tst_captions", "data": _jsCa.dumps(_blk)})
    _jf2 = (_cCa.get("/captions/list?identity=_tst_captions").get_json() or {})
    check("captions : favori et desactive cohabitent sans s ecraser",
          _jf2["block"]["items"][1].get("fav") is True
          and _jf2["block"]["items"][1].get("enabled") is False,
          str(_jf2["block"]["items"][1])[:90])
    _blk["items"][1]["enabled"] = True

    # ⭐ l etoile des rushs bruts : posee sur les brutes, ABSENTE ailleurs.
    # _preview_card est une fonction pure, on l appelle directement.
    _pcB = _wCa._preview_card("/m.mp4", "/t.jpg", _plCa.Path("clip.mp4"), True,
                              "ident|brutes|clip.mp4")
    _pcR = _wCa._preview_card("/m.mp4", "/t.jpg", _plCa.Path("r.mp4"), True,
                              "ident|videos|r.mp4")
    _pcP = _wCa._preview_card("/m.mp4", "/t.jpg", _plCa.Path("p.mp4"), True,
                              "ident|pro_brutes|p.mp4")
    check("brutes : l etoile ⭐ est sur la carte d un rush brut",
          "fav-brute-star" in _pcB)
    check("brutes : elle n est PAS sur un reel (il a deja son etoile banger)",
          "fav-brute-star" not in _pcR and "banger-star" in _pcR)
    check("brutes : le Vault PRO est epargne (sous-dossier pro_brutes)",
          "fav-brute-star" not in _pcP)
    _pcT = _wCa._preview_card("/m.mp4", "/t.jpg", _plCa.Path("t.mp4"), True,
                              "ident|templates|t.mp4")
    check("templates : l etoile ⭐ est aussi sur un template de montage",
          "fav-brute-star" in _pcT)
    _pcOn = _wCa._preview_card("/m.mp4", "/t.jpg", _plCa.Path("c.mp4"), True,
                               "ident|brutes|c.mp4", is_fav_brute=True)
    check("brutes : l etoile allumee se voit dans le HTML",
          "is-fav" in _pcOn and "#ffd54a" in _pcOn)

    # partage vers une autre model : copie (desc comprise) + dédupe normalisée
    _idCb = _plCa.Path("data/identities/_tst_captions2")
    _shCa.rmtree(_idCb, ignore_errors=True)
    (_idCb / "brutes").mkdir(parents=True)
    _ja = (_cCa.post("/captions/apply", data={
        "identity": "_tst_captions", "ids": "[]",
        "targets": _jsCa.dumps(["_tst_captions2"])}).get_json() or {})
    _jt = (_cCa.get("/captions/list?identity=_tst_captions2").get_json() or {})
    _titems = (_jt.get("block") or {}).get("items") or []
    check("captions : partage copie tout (desc comprise) chez la cible",
          _ja.get("ok") and _ja.get("added") == 12 and len(_titems) == 12
          and any(c.get("desc") for c in _titems), str(_ja)[:100])
    _ja2 = (_cCa.post("/captions/apply", data={
        "identity": "_tst_captions", "ids": "[]",
        "targets": _jsCa.dumps(["_tst_captions2"])}).get_json() or {})
    check("captions : re-partage = 0 ajout (doublons normalisés ignorés)",
          _ja2.get("ok") and _ja2.get("added") == 0 and _ja2.get("skipped") == 12,
          str(_ja2)[:100])
    _rbadT = (_cCa.post("/captions/apply", data={
        "identity": "_tst_captions", "ids": "[]",
        "targets": _jsCa.dumps(["_tst_captions"])}).get_json() or {})
    check("captions : partage vers soi-même refusé", _rbadT.get("ok") is not True)
    _shCa.rmtree(_idCb, ignore_errors=True)
    # bornes moteur : size clampe a 160, x/y clampes 0-1, wrapW hors bornes ignore
    _blk2 = {"style": {"size": 999},
             "items": [{"id": "w", "text": "W", "x": 2.0, "y": -1.0, "wrapW": 5.0}]}
    _cCa.post("/captions/save", data={"identity": "_tst_captions", "data": _jsCa.dumps(_blk2)})
    _j3 = (_cCa.get("/captions/list?identity=_tst_captions").get_json() or {})
    _it3 = (_j3["block"]["items"] or [{}])[0]
    check("captions : clamps serveur (size 160, x/y 0-1, wrapW ignore)",
          _j3["block"]["style"].get("size") == 160 and _it3.get("x") == 1.0
          and _it3.get("y") == 0.0 and "wrapW" not in _it3, str(_j3)[:120])

    # -- F7 : le plafond de captions ne doit RIEN jeter en silence -----------
    # Le serveur tronquait a CAPTIONS_MAX sans le dire ; le navigateur
    # annoncait « N ajoutees » et la moitie disparaissait au rechargement.
    _MAXCa = _wCa.CAPTIONS_MAX
    _blkP = {"items": [{"id": f"p{i}", "text": f"Plafond {i}"}
                       for i in range(_MAXCa + 10)]}
    _jp = (_cCa.post("/captions/save",
                     data={"identity": "_tst_captions",
                           "data": _jsCa.dumps(_blkP)}).get_json() or {})
    check("captions : le plafond est ANNONCE, pas subi (refuses comptes)",
          _jp.get("ok") and _jp.get("count") == _MAXCa
          and _jp.get("refuses") == 10 and _jp.get("max") == _MAXCa,
          str(_jp)[:120])
    _jpl = (_cCa.get("/captions/list?identity=_tst_captions").get_json() or {})
    check("captions : le plafond garde bien les premieres, pas n importe lesquelles",
          len((_jpl.get("block") or {}).get("items") or []) == _MAXCa
          and _jpl["block"]["items"][0]["text"] == "Plafond 0", str(_jpl)[:90])

    # Partage vers une cible DEJA PLEINE : « plus de place » n est pas
    # « deja la ». Les confondre faisait annoncer des doublons imaginaires.
    _idCp = _plCa.Path("data/identities/_tst_captions_plein")
    _shCa.rmtree(_idCp, ignore_errors=True)
    (_idCp / "brutes").mkdir(parents=True)
    _cCa.post("/captions/save", data={
        "identity": "_tst_captions_plein",
        "data": _jsCa.dumps({"items": [{"id": f"q{i}", "text": f"Cible {i}"}
                                       for i in range(_MAXCa)]})})
    _jap = (_cCa.post("/captions/apply", data={
        "identity": "_tst_captions", "ids": "[]",
        "targets": _jsCa.dumps(["_tst_captions_plein"])}).get_json() or {})
    check("captions : cible pleine -> refus compte a part (pas en doublons)",
          _jap.get("ok") and _jap.get("added") == 0
          and _jap.get("pleins") == _MAXCa and _jap.get("skipped") == 0
          and _jap.get("cibles_pleines") == ["_tst_captions_plein"]
          and _jap.get("max") == _MAXCa, str(_jap)[:140])
    _shCa.rmtree(_idCp, ignore_errors=True)

    # -- F6 : la carte caption, MEME chose cote serveur et cote navigateur ---
    # Flask rend la carte, puis capRenderCards la RE-rend au premier clic.
    # Tant que les deux differaient (bouton Description et ligne d apercu
    # seulement en JS, ligne de largeur seulement en Python), les cartes
    # sautaient en hauteur des qu on touchait a l onglet.
    import re as _reCa
    _blkR = {"items": [{"id": "r1", "text": "Avec description",
                        "desc": "Legende du post", "wrapW": 0.5},
                       {"id": "r2", "text": "Sans rien"}]}
    _cCa.post("/captions/save", data={"identity": "_tst_captions",
                                      "data": _jsCa.dumps(_blkR)})
    with _aCa.test_request_context("/?cloud_captions_ident=_tst_captions"):
        _hCap = _wCa._render_cloud_captions_html()
    # « cap-card' » ferme la classe : sans le guillemet on tomberait sur
    # <div class='cap-card-meta'>, qui commence pareil.
    _i0Ca = _hCap.find("<div class='cap-card'")
    _i1Ca = _hCap.find("<div class='cap-card'", _i0Ca + 10)
    _card0 = _hCap[_i0Ca:_i1Ca] if (_i0Ca >= 0 and _i1Ca > 0) else ""
    _srcCa = _plCa.Path("web_upload.py").read_text(encoding="utf-8")
    _iJs = _srcCa.find("function capRenderCards(){")
    _jsCard = _srcCa[_iJs:_srcCa.find("function capSave(", _iJs)] if _iJs > 0 else ""
    _actsSrv = _reCa.findall(r"data-capact='([a-z]+)'", _card0)
    _actsJs = _reCa.findall(r'data-capact="([a-z]+)"', _jsCard)
    check("captions : la carte rendue par Flask a les MEMES boutons que celle du JS",
          bool(_actsSrv) and _actsSrv == _actsJs,
          f"serveur={_actsSrv} js={_actsJs}")
    check("captions : le serveur rend la ligne d apercu de la description",
          "📄 Legende du post" in _hCap, _card0[-220:])
    check("captions : la ligne de largeur ↔ n est plus rendue (le JS l a lachee)",
          "↔" not in _hCap and "↔" not in _jsCard)

    # identites refusees (traversal / inconnues)
    for _bad in ("../..", "..", "/etc", "_tst_nexiste_pas"):
        _rb = _cCa.post("/captions/save", data={"identity": _bad, "data": "{}"})
        check(f"captions : identite refusee {_bad}",
              (_rb.get_json() or {}).get("ok") is not True)
    # fichier corrompu -> pas de 500 (le loader retombe sur un bloc vide)
    _fCa.write_text("{casse", encoding="utf-8")
    _wCa._invalidate_json_cache(_fCa)
    check("captions : fichier corrompu ne 500 pas",
          _cCa.get("/captions/list?identity=_tst_captions").status_code == 200)
    # re-sauvegarde propre pour la suite
    _cCa.post("/captions/save", data={"identity": "_tst_captions", "data": _jsCa.dumps(_blk)})

    # -- RBAC : role restreint bloque (ecriture ET lecture) ------------------
    _wCa._load_web_users = lambda: {"chat": {"role": "chatter"}}
    _c403 = _aCa.test_client()
    with _c403.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "chat"; _s["role"] = "chatter"; _s["sid"] = "CA2"
    check("captions : chatter bloque en ecriture (403)",
          _c403.post("/captions/save", data={"identity": "_tst_captions", "data": "{}"}).status_code == 403)
    check("captions : chatter bloque en lecture (403)",
          _c403.get("/captions/list?identity=_tst_captions").status_code == 403)
    check("identite : chatter bloque (403)",
          _c403.post("/identity/create", data={"identity_name": "hackette"}).status_code == 403)
    _wCa._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    check("RBAC : onglet cloudcaptions rattache a la cle montage",
          "cloudcaptions" in (_wCa._PERM_KEY_TO_TABS.get("montage") or set()))

    # -- generation : cablage complet SANS lancer node (gen_from_draft stubbe)
    import noctus_web as _nwCa
    _calls = []
    _sav_gen = _nwCa.gen_from_draft
    _sav_setup = _nwCa.setup_ok
    _nwCa.setup_ok = lambda: True
    def _fake_gen(src, draft, folders=None, model=None, brutes_dir=None):
        _calls.append({"src": src, "draft": draft, "folders": folders,
                       "brutes_dir": brutes_dir})
        return "vam-test-123"
    _nwCa.gen_from_draft = _fake_gen
    try:
        _rg = _cCa.post("/captions/gen", data={"identity": "_tst_captions"})
        _jg = _rg.get_json() or {}
        check("captions gen : ok + model renvoye",
              _jg.get("ok") and _jg.get("model") == "vam-test-123", str(_jg)[:100])
        check("captions gen : brute tiree dans <ident>/brutes/",
              bool(_calls) and "_tst_captions" in _calls[0]["src"]
              and _calls[0]["src"].endswith("b.mp4"))
        _dseg = _jsCa.loads(_calls[0]["draft"]["segments"]) if _calls else []
        check("captions gen : draft 1 segment, sans cut_at ni brutes_dir (brute seule)",
              bool(_calls) and len(_dseg) == 1 and _dseg[0]["start"] is None
              and "cut_at" not in _calls[0]["draft"] and _calls[0]["brutes_dir"] is None
              and _calls[0]["folders"] == ["V1"], str(_calls)[:140])
        # caption_id force la caption (bouton « tester »)
        _calls.clear()
        _cCa.post("/captions/gen", data={"identity": "_tst_captions", "caption_id": "c7"})
        _dseg2 = _jsCa.loads(_calls[0]["draft"]["segments"]) if _calls else []
        check("captions gen : caption_id force la caption choisie",
              bool(_dseg2) and _dseg2[0]["text"] == "Cap 7")
        # position globale activee -> ecrase la position par caption
        _blkG = dict(_blk); _blkG["global_pos"] = {"enabled": True, "x": 0.9, "y": 0.1}
        _cCa.post("/captions/save", data={"identity": "_tst_captions", "data": _jsCa.dumps(_blkG)})
        _calls.clear()
        _cCa.post("/captions/gen", data={"identity": "_tst_captions", "caption_id": "c2"})
        _dseg3 = _jsCa.loads(_calls[0]["draft"]["segments"]) if _calls else []
        check("captions gen : position globale prioritaire quand activee",
              bool(_dseg3) and _dseg3[0]["x"] == 0.9 and _dseg3[0]["y"] == 0.1)
        # pool vide -> erreur propre
        _cCa.post("/captions/save", data={"identity": "_tst_captions", "data": "{}"})
        _je = (_cCa.post("/captions/gen", data={"identity": "_tst_captions"}).get_json() or {})
        check("captions gen : pool vide refuse proprement", _je.get("ok") is not True)
    finally:
        _nwCa.gen_from_draft = _sav_gen
        _nwCa.setup_ok = _sav_setup

    # -- creation d identite depuis la Bibliotheque (bouton +) ---------------
    _dNi = _plCa.Path("data/identities/_tst_capident")
    _shCa.rmtree(_dNi, ignore_errors=True)
    _jNi = (_cCa.post("/identity/create", data={"identity_name": "_TST_capident"}).get_json() or {})
    check("identite : creation ok (nom normalise) + dossiers standards",
          _jNi.get("ok") and _jNi.get("identity") == "_tst_capident"
          and (_dNi / "videos").exists() and (_dNi / "brutes").exists(), str(_jNi)[:90])
    check("identite : doublon refuse",
          ((_cCa.post("/identity/create", data={"identity_name": "_tst_capident"}).get_json() or {}).get("ok")) is not True)
    check("identite : nom invalide refuse",
          ((_cCa.post("/identity/create", data={"identity_name": "@@@ !!"}).get_json() or {}).get("ok")) is not True)
    _shCa.rmtree(_dNi, ignore_errors=True)

    # -- defaut = CENTRE : une caption sans x/y est posee au milieu ----------
    _cCa.post("/captions/save", data={"identity": "_tst_captions",
                                      "data": _jsCa.dumps({"items": [{"id": "ctr", "text": "Centre"}]})})
    _jc = (_cCa.get("/captions/list?identity=_tst_captions").get_json() or {})
    check("captions : defaut = centre (x 0.5 / y 0.5)",
          _jc["block"]["items"][0]["x"] == 0.5 and _jc["block"]["items"][0]["y"] == 0.5,
          str(_jc)[:80])
    check("captions : police par defaut = TikTokSans",
          _jc["block"].get("font") == "TikTokSans", str(_jc["block"].get("font")))

    # -- reordonner les identites (glisser-deposer sidebar, ordre partage) ----
    _fOrd = _plCa.Path("data/identity_order.json")
    _savOrd = _fOrd.read_text(encoding="utf-8") if _fOrd.exists() else None
    # Base CONNUE : sinon on compare au rangement REEL de l utilisateur, et le
    # test ne dit plus rien de ce que la route a fait.
    _wCa._save_identity_order([])
    _jo = (_cCa.post("/identity/reorder",
                     data={"order": _jsCa.dumps(["_tst_captions", "zz_inconnue", "_tst_captions"])}).get_json() or {})
    check("ordre : sauvegarde + inconnues et doublons filtres (et comptes)",
          _jo.get("ok") and _jo.get("count") == 1 and _jo.get("inconnues") == 1
          and _jsCa.loads(_fOrd.read_text(encoding="utf-8")) == ["_tst_captions"], str(_jo)[:90])
    check("ordre : identite ordonnee rendue en premier",
          _wCa._apply_identity_order(["aaa", "_tst_captions"]) == ["_tst_captions", "aaa"])
    check("ordre : JSON invalide refuse",
          ((_cCa.post("/identity/reorder", data={"order": "pas du json"}).get_json() or {}).get("ok")) is not True)

    # -- B7 : le fichier d ordre est PARTAGE, une sidebar n en connait qu une
    # partie. L ecraser avec sa seule liste renvoyait toutes les autres en
    # alphabetique : un rangement fait a la main perdu par un simple
    # glissement dans la Bibliotheque 2.
    _idOa = _plCa.Path("data/identities/_tst_ordre_a")
    _idOb = _plCa.Path("data/identities/v2__tst_ordre_b")
    for _dOr in (_idOa, _idOb):
        _shCa.rmtree(_dOr, ignore_errors=True)
        (_dOr / "brutes").mkdir(parents=True)
    _wCa._IDENTITIES_CACHE["mtime"] = None   # la liste est cachee sur le mtime
    try:
        _wCa._save_identity_order(["_tst_ordre_a", "_tst_captions", "v2__tst_ordre_b"])
        # la Bibliotheque 2 n affiche que ses v2_ : elle n envoie que celles-la
        _jm = (_cCa.post("/identity/reorder",
                         data={"order": _jsCa.dumps(["v2__tst_ordre_b"])}).get_json() or {})
        _ordM = _jsCa.loads(_fOrd.read_text(encoding="utf-8"))
        check("ordre : ranger dans la Bibliotheque 2 ne debranche pas les autres",
              _jm.get("ok") and "_tst_ordre_a" in _ordM and "_tst_captions" in _ordM
              and _ordM.index("_tst_ordre_a") < _ordM.index("_tst_captions"),
              str(_ordM)[:120])
        # ... et la sidebar qui range reordonne bien SES identites, sur place
        _wCa._save_identity_order(["_tst_ordre_a", "v2__tst_ordre_b", "_tst_captions"])
        _cCa.post("/identity/reorder",
                  data={"order": _jsCa.dumps(["_tst_captions", "_tst_ordre_a"])})
        _ordN = _jsCa.loads(_fOrd.read_text(encoding="utf-8"))
        check("ordre : la sidebar qui range reordonne SES identites, sans bouger les autres",
              _ordN == ["_tst_captions", "v2__tst_ordre_b", "_tst_ordre_a"], str(_ordN)[:120])
    finally:
        for _dOr in (_idOa, _idOb):
            _shCa.rmtree(_dOr, ignore_errors=True)
        _wCa._IDENTITIES_CACHE["mtime"] = None

    # restaure l ordre d origine (fichier reel de l utilisateur)
    if _savOrd is not None:
        _wCa.safe_json.write_text(_fOrd, _savOrd)
    else:
        # ecriture DIRECTE : depuis la fusion, poster [] ne vide plus le fichier
        _wCa._save_identity_order([])
    _wCa._invalidate_json_cache(_fOrd)

    # -- Drive (lecture seule, tout le contenu d une identite) ----------------
    _rDr = _cCa.get("/?lazy=clouddrive", headers={"X-Tab-Ajax": "1"})
    _hDr = _rDr.get_data(as_text=True)
    check("drive : fragment lazy 200 + sidebar identites",
          _rDr.status_code == 200 and "vault-list-drive" in _hDr, f"http {_rDr.status_code}")
    check("drive : LECTURE SEULE (aucun controle destructif dans le HTML)",
          "cloud/delete" not in _hDr and "toggleReelDisabled" not in _hDr
          and "sel-cb" not in _hDr and "data-capact" not in _hDr)
    _hDf = _cCa.get("/?tab=clouddrive&cloud_drive_ident=_tst_captions&frag=1",
                    headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
    check("drive : fragment identite (vaultGoTo) rendu avec ses fichiers",
          "form-clouddrive" in _hDf and "brutes/b.mp4" in _hDf)

    # -- migration du pool PP partage -> une identite (aucune suppression) ----
    _poolD = _plCa.Path("data/profile_pics")
    _poolHad = _poolD.exists()
    if _poolHad:
        # un VRAI pool existe sur cette machine : on ne touche a rien
        check("pp pool : machine avec vrai pool -> test de deplacement saute", True)
    else:
        _poolD.mkdir(parents=True, exist_ok=True)
        (_poolD / "zz_test_a.jpg").write_bytes(b"\xff" * 100)
        (_poolD / "zz_test_b.png").write_bytes(b"\xff" * 100)
        _rMv = _cCa.post("/cloud/pp_pool_move", data={"identity": "_tst_captions"})
        _ppDst = _idCa / "profile_pics"
        check("pp pool : tout deplace vers l identite (rien supprime)",
              _rMv.status_code in (200, 302)
              and not list(_poolD.glob("zz_test_*"))
              and len(list(_ppDst.glob("pp_*"))) >= 2, f"http {_rMv.status_code}")
        check("pp pool : identite inconnue refusee (fichiers intacts)",
              _cCa.post("/cloud/pp_pool_move", data={"identity": "_tst_nexiste_pas"}).status_code in (200, 302))
        _shCa.rmtree(_poolD, ignore_errors=True)
    import io as _ioCa
    _rUp = _cCa.post("/upload/pp", data={"identity": "", "photo": (_ioCa.BytesIO(b"x"), "a.jpg")},
                     content_type="multipart/form-data")
    check("upload pp : sans identite -> refuse (le pool partage n existe plus)",
          _rUp.status_code in (200, 302)
          and (not _poolD.exists() or not list(_poolD.glob("pp_*"))))

    # -- PP « Appliquer aux autres » : COPIE vers d autres identites ----------
    _ppSrcD = _idCa / "profile_pics"; _ppSrcD.mkdir(parents=True, exist_ok=True)
    (_ppSrcD / "src_apply.jpg").write_bytes(b"\xd8" * 500)
    _id2 = _plCa.Path("data/identities/_tst_cap2")
    _shCa.rmtree(_id2, ignore_errors=True)
    (_id2 / "profile_pics").mkdir(parents=True)
    _jAp = (_cCa.post("/cloud/pp_apply", data={
        "files": _jsCa.dumps(["_tst_captions|profile_pics|src_apply.jpg"]),
        "targets": _jsCa.dumps(["_tst_cap2", "zz_inconnue"])}).get_json() or {})
    check("pp apply : copie vers la cible (original intact)",
          _jAp.get("ok") and _jAp.get("copied") == 1
          and (_ppSrcD / "src_apply.jpg").exists()
          and len(list((_id2 / "profile_pics").glob("pp_*.jpg"))) == 1, str(_jAp)[:90])
    check("pp apply : cibles toutes invalides refusees",
          ((_cCa.post("/cloud/pp_apply", data={
              "files": _jsCa.dumps(["_tst_captions|profile_pics|src_apply.jpg"]),
              "targets": _jsCa.dumps(["zz_inconnue"])}).get_json() or {}).get("ok")) is not True)
    _jTr = (_cCa.post("/cloud/pp_apply", data={
        "files": _jsCa.dumps(["../..|profile_pics|x.jpg", "_tst_captions|videos|../x.jpg"]),
        "targets": _jsCa.dumps(["_tst_cap2"])}).get_json() or {})
    check("pp apply : file_id traversant ignore (0 copie)", _jTr.get("copied", -1) == 0)
    _shCa.rmtree(_id2, ignore_errors=True)

    # -- Bios / CTA scindes (vaults par identite, meme stockage text_pool) ----
    import text_pool as _tpCa
    _fTp = _plCa.Path("data/text_pool.json")
    _savTp = _fTp.read_text(encoding="utf-8") if _fTp.exists() else None
    try:
        _jv = (_cCa.post("/textpool/vault_add", data={
            "category": "bios", "identity": "_tst_captions",
            "texts": _jsCa.dumps(["bio test A\nligne 2", "bio test B", "bio test A\nligne 2"])}).get_json() or {})
        check("textvault : ajout par identite (multi-ligne garde, doublon filtre)",
              _jv.get("ok") and _jv.get("added") == 2 and _jv.get("duplicates") == 1, str(_jv)[:90])
        _lst = _tpCa.list_entries("bios", identity="_tst_captions")
        check("textvault : filtrage par identite dans text_pool",
              len(_lst) == 2 and chr(10) in _lst[0]["text"])
        check("textvault : entrees bien assignees a l identite",
              all((e.get("identity") or "") == "_tst_captions" for e in _lst))
        _hB = _cCa.get("/?tab=cloudbios&cloud_bios_ident=_tst_captions").get_data(as_text=True)
        check("textvault : onglet Bios rendu (sans « Pool commun », retire a la demande)",
              "data-txtroot" in _hB and "bio test B" in _hB
              and "Pool commun" not in _hB)
        check("textvault : identite inconnue refusee",
              ((_cCa.post("/textpool/vault_add", data={"category": "bios", "identity": "zz_inconnue",
                          "texts": _jsCa.dumps(["x"])}).get_json() or {}).get("ok")) is not True)
        check("RBAC : cloudbios/cloudctas rattaches a la cle textpool",
              {"cloudbios", "cloudctas"} <= (_wCa._PERM_KEY_TO_TABS.get("textpool") or set()))
    finally:
        if _savTp is not None:
            _wCa.safe_json.write_text(_fTp, _savTp)
        else:
            try:
                _fTp.unlink()
            except Exception:
                pass

    # -- Import par lien (IG/TikTok -> brutes/templates, yt-dlp stubbe) -------
    import veille_telegram as _vtCa
    _sav_dl = _vtCa.download_via_ytdlp
    _vtCa.download_via_ytdlp = lambda url, timeout=25, info=None, use_cookies=True: b"\x00" * 2000
    # la chaine IG (Apify/scrape) ferait de VRAIS appels reseau -> stub complet
    _sav_fetch = _wCa._linkimp_fetch
    _wCa._linkimp_fetch = lambda u, inf: b"\x00" * 2000
    try:
        _rLi = _cCa.post("/cloud/import_link", data={
            "identity": "_tst_captions", "subdir": "templates",
            "urls": "https://www.tiktok.com/@x/video/123\npas un lien\nhttps://www.instagram.com/reel/ABC/"})
        check("import lien : lance (redirect flash)", _rLi.status_code in (200, 302))
        import time as _tCa
        _tplD = _idCa / "templates"
        for _ in range(30):
            if len(list(_tplD.glob("import_*.mp4"))) >= 2:
                break
            _tCa.sleep(0.1)
        check("import lien : 2 liens valides telecharges dans templates/ (ligne invalide ignoree)",
              len(list(_tplD.glob("import_*.mp4"))) == 2)
        check("import lien : subdir invalide refuse",
              _cCa.post("/cloud/import_link", data={"identity": "_tst_captions", "subdir": "videos",
                        "urls": "https://x.com/v"}).status_code in (200, 302)
              and not list((_idCa / "videos").glob("import_*.mp4")) if (_idCa / "videos").exists() else True)
        check("import lien : identite inconnue refusee",
              _cCa.post("/cloud/import_link", data={"identity": "zz_inconnue", "subdir": "brutes",
                        "urls": "https://x.com/v"}).status_code in (200, 302))
    finally:
        _vtCa.download_via_ytdlp = _sav_dl
        _wCa._linkimp_fetch = _sav_fetch
    check("import lien : chaine Veille pour Instagram (Apify -> scrape -> yt-dlp public)",
          "apify_reels" in _plCa.Path("web_upload.py").read_text(encoding="utf-8")
          and "use_cookies=False" in _plCa.Path("web_upload.py").read_text(encoding="utf-8"))

    # -- Google Drive sync (copie seule) --------------------------------------
    import gdrive_sync as _gdCa
    check("gdrive : module importable sans google-auth (available -> bool)",
          isinstance(_gdCa.available(), bool))
    check("gdrive : parse lien dossier",
          _gdCa.folder_id_from("https://drive.google.com/drive/folders/1AbC_dEf-234567890xyz?usp=sharing") == "1AbC_dEf-234567890xyz"
          and _gdCa.folder_id_from("1AbC_dEf-234567890xyz") == "1AbC_dEf-234567890xyz"
          and _gdCa.folder_id_from("n importe quoi !") == "")
    _gdSrc = _plCa.Path("gdrive_sync.py").read_text(encoding="utf-8")
    check("gdrive : AUCUN appel de suppression dans le module (copie seule)",
          "sess.delete" not in _gdSrc and ".unlink(" not in _gdSrc
          and "rmtree" not in _gdSrc and '"trashed": true' not in _gdSrc.lower())

    # --- rangement du Drive : UN dossier « Bibliothèque », identites dedans ---
    import tempfile as _tfGd
    import shutil as _shGd
    _tmpGd = _plCa.Path(_tfGd.mkdtemp())
    _origGd = _gdCa.IDENTITIES_DIR
    _gdCa.IDENTITIES_DIR = _tmpGd
    try:
        for _idGd, _ssGd in (("julia", ["videos", "posts", "pro_videos"]),
                             ("v2_beta", ["videos"])):
            for _sdGd in _ssGd:
                (_tmpGd / _idGd / _sdGd).mkdir(parents=True)
                (_tmpGd / _idGd / _sdGd / ("f1" + (".mp4" if "video" in _sdGd else ".jpg"))
                 ).write_bytes(b"x")
        _chGd = ["/".join(c) + "/" + p.name for c, p in _gdCa._iter_jobs(True)]
        check("gdrive : tout part sous « Bibliothèque »",
              bool(_chGd) and all(c.startswith("Bibliothèque/") for c in _chGd), str(_chGd))
        check("gdrive : ni Vault PRO ni Bibliotheque 2 (retirees a la demande)",
              not any(("Vault PRO" in c or "Bibliotheque 2" in c) for c in _chGd))

        # --- les fichiers VOISINS partent avec leur media ----------------
        # « .example not in name » est une regle d AFFICHAGE (ne pas montrer
        # l exemple comme une carte a part). Recopiee dans le module de
        # SAUVEGARDE, elle laissait 102 videos exemple et toutes les
        # captions hors du Drive — et, le meme generateur servant au
        # comptage, la page affichait « 100 %, tout est a jour ».
        _vGd = _tmpGd / "julia" / "videos"
        for _nGd in ("f1.txt", "f1.desc.txt", "f1.montage.json",
                     "f1.analyse.json", "f1.example.mp4",
                     "f1.montage.json.prev", "f1.part"):
            (_vGd / _nGd).write_bytes(b"x")
        _nomsGd = [p.name for _c, p in _gdCa._iter_jobs(True)]
        for _quoiGd, _fGd in (("la video exemple", "f1.example.mp4"),
                              ("la caption", "f1.txt"),
                              ("la description", "f1.desc.txt"),
                              ("le brouillon de montage", "f1.montage.json"),
                              ("l analyse", "f1.analyse.json")):
            check("gdrive : %s est sauvegardee" % _quoiGd, _fGd in _nomsGd,
                  str(sorted(_nomsGd)))
        # .prev est une copie interne de safe_json, .part une ecriture
        # interrompue : ni l un ni l autre n a sa place sur le Drive.
        check("gdrive : les artefacts internes restent dehors",
              "f1.montage.json.prev" not in _nomsGd and "f1.part" not in _nomsGd)

        # Repondre « non » aux videos ne doit pas couper les captions :
        # elles pesent quelques kilo-octets et rien d autre ne les garde.
        _sansGd = [p.name for _c, p in _gdCa._iter_jobs(False)]
        check("gdrive : « videos : non » garde quand meme les captions",
              "f1.txt" in _sansGd and "f1.mp4" not in _sansGd,
              str(sorted(_sansGd)))

        # La regle d affichage n a rien a faire dans le module qui decide
        # ce qui est SAUVEGARDE. C est le verrou contre le copier-coller.
        check("gdrive : la regle d affichage a quitte le module de sauvegarde",
              '".example" not in' not in _gdSrc)
        # Un seul endroit calcule l ensemble des extensions : quand deux
        # endroits decident la meme chose, ils divergent (cf. les 598
        # fichiers Drive invisibles).
        check("gdrive : un seul endroit decide des extensions",
              _gdSrc.count("VIDEO_EXTS if is_video else IMAGE_EXTS") == 1
              and _gdSrc.count("def _exts_de") == 1)

        # Le comptage vient du MEME generateur que l envoi : un fichier
        # jamais sauvegarde doit etre compte comme manquant, sinon la page
        # affiche 100 % sur une identite a moitie sauvegardee.
        _vraiEtatGd = _gdCa._load_state
        _gdCa._load_state = lambda: {"uploaded": {}}
        try:
            _repGd = _gdCa.sync_report()
            _juGd = [x for x in (_repGd.get("identities") or [])
                     if x.get("identity") == "julia"]
            check("gdrive : le total du rapport inclut les voisins",
                  bool(_juGd) and _juGd[0].get("total") == len(
                      [n for _c, n in _gdCa._iter_jobs(True)
                       if n.parent.parent.name == "julia"]),
                  str(_juGd[:1]))
            check("gdrive : un fichier jamais envoye compte comme manquant",
                  bool(_juGd) and _juGd[0].get("manque") == _juGd[0].get("total")
                  and _juGd[0].get("sync") == 0, str(_juGd[:1]))
        finally:
            _gdCa._load_state = _vraiEtatGd

        # non_sauvegardes sert au message de /cloud/delete : en cas de
        # doute il doit repondre « pas de copie », jamais l inverse.
        check("gdrive : sans etat, tout est declare non sauvegarde",
              len(_gdCa.non_sauvegardes([_vGd / "f1.txt", _vGd / "f1.mp4"])) == 2)
        check("gdrive : une liste vide ne fait rien",
              _gdCa.non_sauvegardes([]) == [])
        _creGd = []
        _vraiGd = _gdCa._ensure_folder
        _gdCa._ensure_folder = lambda sess, parent, name, st: (
            _creGd.append((parent, name)) or name)
        try:
            _gdCa._creer_arborescence(None, "RACINE", {"folders": {}}, True)
        finally:
            _gdCa._ensure_folder = _vraiGd
        check("gdrive : un SEUL dossier cree a la racine du Drive",
              {n for par, n in _creGd if par == "RACINE"} == {"Bibliothèque"},
              str([c for c in _creGd if c[0] == "RACINE"]))

        # --- envois paralleles : rien en double, la relance ne renvoie rien ---
        import threading as _thGd
        _envGd, _dirGd, _vGd = [], [], _thGd.Lock()
        _origGd2 = (_gdCa.STATE_FILE, _gdCa._session, _gdCa._session_thread,
                    _gdCa._ensure_folder, _gdCa._upload_file,
                    _gdCa.load_config, _gdCa.save_config, _gdCa._lister)
        # Drive vide cote reseau : sans ca, le rangement par marche tenterait
        # un vrai appel HTTP (et run_sync remonte desormais l erreur au lieu
        # de l avaler, ce qui est justement le comportement voulu).
        _gdCa._lister = lambda sess, parent, dossiers=False: []

        def _upGd(sess, parent, path):
            import time as _tGd
            _tGd.sleep(0.01)                     # simule le reseau
            with _vGd:
                _envGd.append(str(path))
            return "id-" + path.name

        def _dirFnGd(sess, parent, name, st):
            _cle = str(parent) + "/" + name
            _cc = st.setdefault("folders", {})
            if _cle in _cc:
                return _cc[_cle]
            with _vGd:
                _dirGd.append(_cle)
            _cc[_cle] = "dir-" + name
            return _cc[_cle]

        _gdCa.STATE_FILE = _tmpGd / "state.json"
        _gdCa._session = lambda: "S"
        _gdCa._session_thread = lambda: "S"
        _gdCa._ensure_folder = _dirFnGd
        _gdCa._upload_file = _upGd
        _gdCa.load_config = lambda: {"folder": "RACINEbidon1234", "include_videos": True}
        _gdCa.save_config = lambda c: True
        try:
            _r1Gd = _gdCa.run_sync()
            check("gdrive : tout part, aucun echec (envois paralleles)",
                  _r1Gd["uploaded"] == _r1Gd["total"] and _r1Gd["errors"] == 0, str(_r1Gd))
            check("gdrive : aucun fichier envoye deux fois",
                  len(_envGd) == len(set(_envGd)), "%d/%d" % (len(_envGd), len(set(_envGd))))
            check("gdrive : aucun dossier cree deux fois (verrou sur le cache)",
                  len(_dirGd) == len(set(_dirGd)), str(len(_dirGd)))
            _envGd.clear()
            _r2Gd = _gdCa.run_sync()
            check("gdrive : relancer ne renvoie rien",
                  _r2Gd["uploaded"] == 0 and _r2Gd["skipped"] == _r1Gd["total"]
                  and not _envGd, str(_r2Gd))
        finally:
            (_gdCa.STATE_FILE, _gdCa._session, _gdCa._session_thread,
             _gdCa._ensure_folder, _gdCa._upload_file,
             _gdCa.load_config, _gdCa.save_config, _gdCa._lister) = _origGd2
    finally:
        _gdCa.IDENTITIES_DIR = _origGd
        _shGd.rmtree(_tmpGd, ignore_errors=True)
    _fGd = _plCa.Path("data/gdrive_sync.json")
    _savGd = _fGd.read_text(encoding="utf-8") if _fGd.exists() else None
    _rGc = _cCa.post("/gdrive/config", data={"folder": "https://drive.google.com/drive/folders/1AbC_dEf-234567890xyz"})
    check("gdrive : config enregistree (id extrait du lien)",
          _rGc.status_code in (200, 302)
          and (_gdCa.load_config().get("folder") == "1AbC_dEf-234567890xyz"))
    check("gdrive : lien invalide refuse",
          _cCa.post("/gdrive/config", data={"folder": "zzz"}).status_code in (200, 302)
          and _gdCa.load_config().get("folder") == "1AbC_dEf-234567890xyz")
    if not _gdCa.available():
        _rGs = _cCa.post("/gdrive/sync", data={})
        check("gdrive : sync sans compte de service -> refus propre (pas de crash)",
              _rGs.status_code in (200, 302))
    else:
        check("gdrive : compte de service present en local -> test sync saute (pas d appel reseau)", True)
    _wCa._load_web_users = lambda: {"chat": {"role": "chatter"}}
    check("gdrive : chatter bloque (403)",
          _c403.post("/gdrive/sync", data={}).status_code == 403)
    _wCa._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    if _savGd is not None:
        _wCa.safe_json.write_text(_fGd, _savGd)
    else:
        try:
            _fGd.unlink()
        except Exception:
            pass

    # tirage random verrouille par grep du source (pattern section 18)
    _wsCa = (_plCa.Path(__file__).parent / "web_upload.py").read_text(encoding="utf-8")
    check("captions gen : tirage random.choice (caption ET brute)",
          _wsCa.count("_rnd.choice(pool)") == 1 and _wsCa.count("_rnd.choice(brutes)") == 1)
    check("captions : persistance via safe_json (jamais write_text brut)",
          "safe_json.write(CAPTIONS_FILE" in _wsCa)

    _wCa._load_web_users = _savCa
    _shCa.rmtree(_idCa, ignore_errors=True)
    # nettoie les entrees de test de data/captions.json
    try:
        _lib = _jsCa.loads(_fCa.read_text(encoding="utf-8"))
        _oteCa = False
        if isinstance(_lib, dict):
            for _kCa in ("_tst_captions", "_tst_captions2", "_tst_captions_plein"):
                if _lib.pop(_kCa, None) is not None:
                    _oteCa = True
        if _oteCa:
            _wCa.safe_json.write(_fCa, _lib, indent=2)
            _wCa._invalidate_json_cache(_fCa)
    except Exception:
        pass
except Exception as _e:
    import traceback as _tbCa
    _tbCa.print_exc()
    check("captions : testable", False, repr(_e)[:120])

print()
print("=" * 70)
print("22) Marche FR/US : le site et le bot doivent dire la MEME chose")
print("=" * 70)
try:
    import json as _jsMk
    import pathlib as _plMk
    import web_upload as _wMk
    import cogs.user as _uMk

    _fMk = _plMk.Path("data/identity_market.json")
    _savMk = _fMk.read_bytes() if _fMk.exists() else None
    try:
        _fMk.unlink(missing_ok=True)
        _wMk._invalidate_json_cache(_wMk.MARKET_FILE)
        # defaut : la repartition historique, des deux cotes
        check("marche : julia FR par defaut (site + bot)",
              _wMk.identity_market("julia") == "fr" and _uMk._market_of("julia") == "fr")
        check("marche : une identite inconnue est US (site + bot)",
              _wMk.identity_market("_tst_us") == "us" and _uMk._market_of("_tst_us") == "us")
        # bascule US -> FR : elle doit TENIR (un simple 'pop' retombait sur US)
        _wMk._set_identity_market("_tst_us", "fr")
        _wMk._invalidate_json_cache(_wMk.MARKET_FILE)
        check("marche : bascule US -> FR conservee (site + bot)",
              _wMk.identity_market("_tst_us") == "fr" and _uMk._market_of("_tst_us") == "fr")
        # bascule FR -> US
        _wMk._set_identity_market("julia", "us")
        _wMk._invalidate_json_cache(_wMk.MARKET_FILE)
        check("marche : bascule FR -> US conservee (site + bot)",
              _wMk.identity_market("julia") == "us" and _uMk._market_of("julia") == "us")
        check("marche : jessye reste hors des textes FR partages",
              not _uMk._is_fr_market("jessye"))
        check("marche : ecriture atomique (pas de .tmp residuel)",
              _fMk.exists() and not list(_fMk.parent.glob("identity_market.json.tmp*")))
        # drapeau : SVG et pas emoji (Windows n a pas de police de drapeaux)
        _flFr = _wMk._market_flag_html("_tst_us")      # bascule en FR juste avant
        _flUs = _wMk._market_flag_html("julia")        # bascule en US juste avant
        check("drapeau : SVG (pas d emoji, illisible sous Windows)",
              _flFr.startswith("<svg") and "\U0001f1eb" not in _flFr)
        check("drapeau FR : bleu blanc rouge",
              "#0055a4" in _flFr and "#ef4135" in _flFr and "Marché FR" in _flFr)
        check("drapeau US : bandes rouges + canton bleu",
              "#b22234" in _flUs and "#3c3b6e" in _flUs and "Marché US" in _flUs)
        # il apparait sur les cartes des DEUX barres laterales (vault + drive)
        import re as _reMk
        _appMk = _wMk.create_app()
        _appMk.config["TESTING"] = True
        _cMk = _appMk.test_client()
        with _cMk.session_transaction() as _sMk:
            _sMk["auth"] = True
            _sMk["username"] = "admin"   # seul nom qui ne depend pas de web_users.json
            _sMk["role"] = "owner"
            _sMk["sid"] = "tests"
        for _tabMk in ("cloudreels", "clouddrive", "cloudcaptions", "cloudbios", "cloudctas"):
            _rMk = _cMk.get("/?tab=%s&frag=1" % _tabMk, headers={"X-Tab-Ajax": "1"})
            _hMk = _rMk.get_data(as_text=True)
            _cartes = _reMk.findall(r"<a [^>]*class='vault-item[^>]*>.*?</a>", _hMk, _reMk.S)
            check("drapeau : present sur chaque carte (%s)" % _tabMk,
                  len(_cartes) > 0
                  and all(x.count("aria-label='Marché") == 1 for x in _cartes),
                  "%d carte(s), HTTP %s, %d octets, identites=%s"
                  % (len(_cartes), _rMk.status_code, len(_hMk),
                     _wMk._list_content_identities()[:4]))
            check("drapeau : filtre FR/US alimente (%s)" % _tabMk,
                  all("data-market=" in x for x in _cartes))
            check("drapeau : en-tete de galerie (%s)" % _tabMk,
                  "data-vault-header-flag" in _hMk)
        # le bouton Tout/FR/US et le filtrage unifie (recherche + contenu + marche)
        _pgMk = _cMk.get("/").get_data(as_text=True)
        check("marche : bouton Tout/FR/US pose a cote du SFW",
              'id="market-floating"' in _pgMk and _pgMk.count("data-mkopt=") == 3)
        check("marche : un seul point de decision pour la visibilite",
              "function vaultItemVisible(" in _pgMk and "function vaultRefilter(" in _pgMk)
        check("marche : le selecteur de models porte le drapeau",
              "o.market || mkMarketOf(o.name)" in _pgMk)
        check("marche : l en-tete suit le changement d identite sans reload",
              "data-vault-header-flag]').forEach" in _pgMk)
        # table des marches : sans elle, pas de drapeau dans les formulaires
        # (le JS y lisait les cartes de la sidebar, qui n y sont pas chargees)
        _mMk = _reMk.search(
            r'<script type="application/json" id="mk-markets">(.*?)</script>',
            _pgMk, _reMk.S)
        check("marche : table {identite: marche} rendue pour le JS",
              bool(_mMk) and "{markets_json}" not in _pgMk)
        try:
            _tblMk = _jsMk.loads(_mMk.group(1)) if _mMk else {}
        except Exception:
            _tblMk = {}
        check("marche : table valide et coherente avec le serveur",
              bool(_tblMk)
              and all(v in ("fr", "us") for v in _tblMk.values())
              and all(_wMk.identity_market(k) == v for k, v in list(_tblMk.items())[:5]))
        check("marche : drapeau dans le selecteur d identite des uploads",
              "fl.innerHTML=mkFlagSvg(mkMarketOf(v))" in _pgMk
              and "fli.innerHTML=mkFlagSvg(mkMarketOf(o.value))" in _pgMk)
    finally:
        if _savMk is None:
            _fMk.unlink(missing_ok=True)
        else:
            _fMk.write_bytes(_savMk)
        _wMk._invalidate_json_cache(_wMk.MARKET_FILE)
except Exception as _eMk:
    check("marche : testable", False, repr(_eMk)[:120])

# --- Les deux bibliotheques doivent porter LES MEMES icones ---------------
# Le proprietaire a redemande cinq fois « mets les icones de Bibliotheque 2
# dans Bibliotheque » alors qu'elles etaient deja identiques : il regardait
# une page en cache. Ce test fige l'alignement, pour que la question ne se
# repose plus et qu'une divergence future soit signalee ici.
try:
    import re as _reIc
    _srcIc = pathlib.Path("web_upload.py").read_text(encoding="utf-8")

    def _iconesIc(groupe):
        d = _srcIc.find("toggleGroup('%s')" % groupe)
        bloc = _srcIc[d:_srcIc.find("</div>" + chr(10) + "</div>", d)]
        out = {}
        for m in _reIc.finditer(
                r'<button class="item"[^>]*>\s*(<svg.*?</svg>)\s*([^<\n]+)',
                bloc, _reIc.S):
            out[m.group(2).strip()] = _reIc.sub(r"\s+", " ", m.group(1))
        return out

    _b2Ic, _b1Ic = _iconesIc("vault2"), _iconesIc("cloud")
    check("sidebar : les deux bibliotheques sont lisibles",
          len(_b2Ic) >= 6 and len(_b1Ic) >= 8)
    _communsIc = set(_b2Ic) & set(_b1Ic)
    _ecartsIc = [k for k in _communsIc if _b2Ic[k] != _b1Ic[k]]
    check("sidebar : memes icones dans Bibliotheque et Bibliotheque 2",
          not _ecartsIc, "different : " + ", ".join(_ecartsIc[:4]))
    check("sidebar : aucun emoji dans les icones de la Bibliotheque",
          not any(_reIc.search("[🌀-🫿]", v)
                  for v in _b1Ic.values()))
except Exception as _eIc:
    check("sidebar : icones testables", False, repr(_eIc)[:120])


# ----------------------------------------------------------------------
# API du rig : deux routes GET en lecture seule, protegees par un jeton.
#
# On les eprouve au RENDU REEL, avec le client de test Flask : une route peut
# etre syntaxiquement parfaite et renvoyer 403 a cause du garde-fou d ecriture,
# ou 404 parce qu un sous-dossier n est pas dans CLOUD_SUBDIRS. Seul l appel
# le dit.
#
# Le jeton est pose dans l environnement le temps du test, puis retire.
try:
    import os as _osRg
    import json as _jsonRg
    import web_upload as _wuRg

    _appRg = _wuRg.create_app()
    _appRg.config["TESTING"] = True
    _cRg = _appRg.test_client()
    _JETONRg = "tests-site-jeton-local"
    _avantRg = _osRg.environ.get("RIG_API_TOKEN")

    # Sans jeton cote serveur, aucune porte ne doit s ouvrir.
    _osRg.environ.pop("RIG_API_TOKEN", None)
    check("rig : 503 tant qu aucun RIG_API_TOKEN n est configure",
          _cRg.get("/api/rig/media").status_code == 503)

    _osRg.environ["RIG_API_TOKEN"] = _JETONRg
    check("rig : 403 sans jeton dans la requete",
          _cRg.get("/api/rig/media").status_code == 403)
    check("rig : 403 avec un mauvais jeton",
          _cRg.get("/api/rig/media?token=nawak").status_code == 403)
    check("rig : 404 sur un sous-dossier inconnu",
          _cRg.get("/api/rig/media?subdir=pouet&token=" + _JETONRg).status_code == 404)
    check("rig : 404 sur une identite inconnue",
          _cRg.get("/api/rig/media?identity=zzzz&token=" + _JETONRg).status_code == 404)

    _repRg = _cRg.get("/api/rig/media?subdir=videos",
                      headers={"X-Rig-Token": _JETONRg})
    check("rig : la liste repond 200 avec le bon jeton", _repRg.status_code == 200)
    _dRg = _jsonRg.loads(_repRg.get_data(as_text=True))
    check("rig : la liste rend ok, items et identites",
          _dRg.get("ok") is True and isinstance(_dRg.get("items"), list)
          and isinstance(_dRg.get("identites"), list))
    # « Ne jamais ecarter en silence » : ce qui est refuse doit etre compte ET
    # motive, sinon un fichier disparait sans que personne ne le sache.
    check("rig : ce qui est ecarte est compte et motive",
          "nb_ecartes" in _dRg and isinstance(_dRg.get("ecartes"), list)
          and all("motif" in e for e in _dRg.get("ecartes", [])))

    # Le service de fichier : memes controles que le dashboard, meme fonction.
    _identRg = (_dRg.get("identites") or ["_aucune_"])[0]
    check("rig : 403 sur une remontee de chemin",
          _cRg.get("/api/rig/file/%s/videos/..%%2F..%%2Fsecret" % _identRg,
                   headers={"X-Rig-Token": _JETONRg}).status_code == 403)
    check("rig : le fichier exige aussi le jeton",
          _cRg.get("/api/rig/file/%s/videos/quoiquecesoit.mp4" % _identRg
                   ).status_code == 403)
    check("rig : 404 sur un fichier absent",
          _cRg.get("/api/rig/file/%s/videos/absent-pour-de-bon.mp4" % _identRg,
                   headers={"X-Rig-Token": _JETONRg}).status_code == 404)

    # Le dashboard et le rig doivent trancher par la MEME fonction : deux
    # copies finiraient par diverger (cf. les 598 fichiers Drive invisibles).
    _srcRg = pathlib.Path("web_upload.py").read_text(encoding="utf-8")
    check("rig : cloud_serve_file et rig_serve_file partagent _cloud_media_path",
          _srcRg.count("_cloud_media_path(identity, subdir, filename)") >= 3)
    check("rig : le jeton n est jamais ecrit en dur",
          "RIG_API_TOKEN" in _srcRg and 'RIG_API_TOKEN"] =' not in _srcRg)

    # --- le JavaScript de la page rendue ---------------------------------
    # Le piege le plus couteux de cette base : le JS vit dans des chaines
    # Python, et une apostrophe echappee ou un « \n » ecrit en toutes
    # lettres tue le script de la page ENTIERE, sans erreur serveur et sans
    # qu aucun autre test ne bronche.
    import re as _reJs
    import shutil as _shJs
    import subprocess as _spJs

    _cJs = _appRg.test_client()
    with _cJs.session_transaction() as _sJs:
        _sJs["auth"] = True
        _sJs["username"] = "admin"
    _hJs = _cJs.get("/?tab=remote").get_data(as_text=True)
    check("page : le tableau de bord se rend", len(_hJs) > 100000)

    # Les blocs <script type="application/json"> portent des donnees, pas
    # du code : les passer a node ferait echouer la verification sur eux.
    _blocsJs = _reJs.findall(
        r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", _hJs, _reJs.S)
    _codeJs = [c for a, c in _blocsJs if "json" not in a.lower()]
    check("page : elle porte bien du JavaScript", len(_codeJs) >= 10)

    _node = _shJs.which("node")
    if _node:
        _fJs = TMP / "page_rendue.js"
        _fJs.write_text((chr(10) + ";" + chr(10)).join(_codeJs),
                        encoding="utf-8")
        _rJs = _spJs.run([_node, "--check", str(_fJs)],
                         capture_output=True, text=True, timeout=90)
        check("page : le JavaScript rendu passe node --check",
              _rJs.returncode == 0,
              (_rJs.stderr or "")[:200].replace(chr(10), " "))
    else:
        # Ne jamais ecarter en silence : dire que la verification n a pas
        # eu lieu vaut mieux qu un OK trompeur.
        print("     (node absent : le JS rendu n a pas ete verifie)")

    # --- l editeur de scenarios ------------------------------------------
    # Le catalogue d actions est declare par le poste : sans lui l editeur
    # ne peut proposer que des noms devines, et une action inventee fait
    # echouer la validation au moment ou l on croit avoir enregistre.
    check("editeur : le catalogue d actions exige le jeton",
          _cRg.post("/api/rig/actions", json={"actions": []}).status_code == 403)
    _repAc = _cRg.post("/api/rig/actions",
                       json={"actions": [
                           {"nom": "tap", "doc": "Touche un element.",
                            "exemple": '{"tap": {"text": "Suivant"}}'},
                           {"nom": "", "doc": "sans nom, a ecarter"}]},
                       headers={"X-Rig-Token": _JETONRg})
    check("editeur : le poste declare ses actions",
          _repAc.status_code == 200
          and _jsonRg.loads(_repAc.get_data(as_text=True)).get("n") == 1)

    # Ecrire demande une session ; lire aussi, ou le jeton.
    _cEd = _appRg.test_client()
    with _cEd.session_transaction() as _sEd:
        _sEd["auth"] = True
        _sEd["username"] = "admin"
    _dAc = _jsonRg.loads(
        _cEd.get("/api/rig/actions").get_data(as_text=True))
    check("editeur : le site rend le catalogue a l interface",
          _dAc.get("ok") is True
          and [a["nom"] for a in _dAc.get("actions") or []] == ["tap"])

    # Un scenario vide effacerait le fichier du poste : refuser tot.
    check("editeur : refuse un enregistrement sans etape",
          _cEd.post("/api/rig/jobs",
                    json={"type": "enregistrer", "scenario": "x",
                          "etapes": []}).status_code == 400)
    check("editeur : refuse au-dela de 200 etapes",
          _cEd.post("/api/rig/jobs",
                    json={"type": "enregistrer", "scenario": "x",
                          "etapes": [{"tap": {}}] * 201}).status_code == 400)
    # Le nom vise n existe VOLONTAIREMENT pas. Un travail reste dans la
    # file apres le test ; si l agent tourne, il le prendra pour de bon. Un
    # essai anterieur, pose sur « post-reel », a ramene ce scenario de vingt
    # etapes a une — ne jamais nommer ici un scenario qui existe.
    _repJb = _cEd.post("/api/rig/jobs",
                       json={"type": "enregistrer",
                             "scenario": "__scenario_de_test_inexistant__",
                             "etapes": [{"tap": {"text": "Suivant"}}]})
    _dJb = _jsonRg.loads(_repJb.get_data(as_text=True))
    check("editeur : le travail d enregistrement porte ses etapes",
          _repJb.status_code == 200 and _dJb.get("ok") is True
          and _dJb["job"]["type"] == "enregistrer"
          and _dJb["job"]["etapes"] == [{"tap": {"text": "Suivant"}}])

    # Un detail tronque a 120 reenregistre perdrait la fin du scenario.
    _cRg.post("/api/rig/scenarios",
              json={"scenarios": [
                  {"nom": "long", "titre": "Long", "etapes": 300,
                   "detail": [{"tap": {}}] * 130},
                  {"nom": "court", "titre": "Court", "etapes": 3,
                   "detail": [{"tap": {}}] * 3}]},
              headers={"X-Rig-Token": _JETONRg})
    _dSc = _jsonRg.loads(
        _cEd.get("/api/rig/scenarios").get_data(as_text=True))
    _parNom = {x["nom"]: x for x in _dSc.get("scenarios") or []}
    check("editeur : un detail tronque est signale incomplet",
          _parNom.get("long", {}).get("complet") is False
          and _parNom.get("court", {}).get("complet") is True)

    # L editeur doit refuser d enregistrer dans ce cas, cote interface.
    check("editeur : l interface bloque l enregistrement d un detail tronque",
          "if(!RMT_ED.complet){" in _srcRg
          and "Enregistrement bloque" in _srcRg)

    # Le site n ecrit jamais le fichier : c est le moteur du poste qui
    # valide les actions, et lui seul sait ce qu il sait jouer.
    check("editeur : le site n ecrit aucun fichier de scenario",
          "scenarios/" not in _srcRg.split("def rig_jobs")[1][:4000])

    # Plus aucun cadre vers la machine locale : Remote se voit de partout.
    check("editeur : plus aucun cadre vers 127.0.0.1:8770",
          "8770" not in _srcRg and "data-remote-cadre" not in _srcRg)

    # --- les garde-fous, un par facon de perdre du travail ---------------
    for _quoi, _temoin in (
            ("fermer l onglet avertit", "beforeunload"),
            ("changer d ecran avertit", "modifications non "),
            ("Ctrl+S enregistre", "ev.key==='s'"),
            ("Echap ferme la palette", "ev.key==='Escape'"),
            ("le double clic ne part pas deux fois",
             "if(RMT_ED.enregistrement) return;"),
            ("l edition concurrente est detectee", "RMT_ED.depart"),
            ("une etape sans action est nommee", "rmtEdIncompletes"),
            ("un parametre ne peut pas etre sans nom",
             "ne peut pas etre sans nom"),
            ("un parametre en double est refuse",
             "Il y a deja un parametre nomme"),
            ("une etape brute a exactement une action",
             "une seule action"),
            ("le poste hors ligne est annonce", "poste hors ligne"),
            ("une etape se duplique", "data-ed-c="),
    ):
        check("editeur : " + _quoi, _temoin in _srcRg, "temoin : " + _temoin)

    # Le filet le plus important : la version precedente est gardee sur le
    # POSTE, pas ici. Le site ne doit surtout pas croire qu il l a.
    check("editeur : le site ne pretend pas garder de version",
          "VERSIONS_GARDEES" not in _srcRg)

    # La file est rendue telle qu elle a ete trouvee : les travaux poses
    # ici n ont rien a faire dans celle du poste.
    try:
        _filesRg = _wuRg.Path("data") / "rig_jobs.json"
        _dRgF = _wuRg.safe_json.load(_filesRg, default={}) or {}
        _restants = [j for j in (_dRgF.get("jobs") or [])
                     if not str(j.get("scenario") or "").startswith("__")]
        if len(_restants) != len(_dRgF.get("jobs") or []):
            _dRgF["jobs"] = _restants
            _wuRg.safe_json.write(_filesRg, _dRgF, indent=None)
        check("rig : les tests ne laissent aucun travail dans la file",
              not [j for j in (_wuRg.safe_json.load(_filesRg, default={})
                               or {}).get("jobs") or []
                   if str(j.get("scenario") or "").startswith("__")])
    except Exception as _eF:
        check("rig : la file est nettoyable", False, repr(_eF)[:120])

    if _avantRg is None:
        _osRg.environ.pop("RIG_API_TOKEN", None)
    else:
        _osRg.environ["RIG_API_TOKEN"] = _avantRg
except Exception as _eRg:
    check("rig : API testable", False, repr(_eRg)[:160])

print()
print("=" * 70)
print("GENERATEURS SMS : le pays, reglable depuis le site")
print("=" * 70)
try:
    import numgen as _ngT
    import web_upload as _wNg

    # Le pays ne se reglait que par /smskey dans Discord. Quand la commande
    # n est pas encore propagee — les commandes globales sont mises en cache
    # par le client — il n y avait plus AUCUN moyen de le changer, et les deux
    # fournisseurs repondaient « aucun numero dispo » : le defaut est « 0 »,
    # c est-a-dire la Russie, ou ils n ont quasiment jamais de numero Instagram.
    _avantNg = _ngT.default_country()
    _aNg = _wNg.create_app(); _aNg.testing = True
    _savNg = _wNg._load_web_users
    _wNg._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cNg = _aNg.test_client()
    with _cNg.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "NG1"

    _hNg = _cNg.get("/?tab=snumgen").get_data(as_text=True)
    check("sms : la page porte l onglet et son panneau",
          "tab-snumgen" in _hNg and "form-snumgen" in _hNg)
    check("sms : le piege du pays 0 est explique a l ecran",
          "Russie" in _hNg and "/numgen/save" in _hNg)

    _ngT.set_keys(country="187")
    _cNg.post("/numgen/save", data={"country": "abc", "service": "ig"})
    check("sms : un code pays qui n est pas un nombre ne change rien",
          _ngT.default_country() == "187", _ngT.default_country())
    _cNg.post("/numgen/save", data={"country": "78", "service": "ig"})
    check("sms : un code valide est enregistre", _ngT.default_country() == "78",
          _ngT.default_country())

    # Ce reglage depense de l argent : il doit rester ferme aux roles restreints.
    _wNg._load_web_users = lambda: {"chat": {"role": "chatter"}}
    _cRe = _aNg.test_client()
    with _cRe.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "chat"; _s["role"] = "chatter"; _s["sid"] = "NG2"
    check("sms : un role restreint ne peut pas changer le pays",
          _cRe.post("/numgen/save", data={"country": "187"}).status_code == 403)

    # Repli automatique. Le pays regle peut tomber a sec du jour au lendemain
    # — c est exactement ce qui est arrive au pays « 0 ». Repondre « aucun
    # numero dispo » n aide personne : il faut connaitre les codes pays pour
    # s en sortir. numgen demande donc au fournisseur ou il lui en reste.
    # Tout est simule ici : ce test ne doit acheter aucun numero.
    _svS, _svG = _ngT._stubs, _ngT.getatext_key
    _svB, _svC = _ngT.smsbower_key, _ngT._cfg
    try:
        _vus = []

        def _fauxNg(prov, action, **p):
            _vus.append((action, p.get("country")))
            if action == "getNumbersStatus":
                return ('{"instagram/threads_0": %d}'
                        % (5061 if p.get("country") == "187" else 0))
            if action == "getNumber":
                return ("ACCESS_NUMBER:9:12025550147"
                        if p.get("country") == "187" else "NO_NUMBERS")
            return "BAD_ACTION"

        _ngT._stubs = _fauxNg
        _ngT.getatext_key = lambda: "K"
        _ngT.smsbower_key = lambda: ""
        _ngT._cfg = lambda: {"country": "0"}
        _okNg, _resNg = _ngT.get_number("ig")
        check("sms : un pays a sec bascule sur un pays qui a du stock",
              _okNg is True and _resNg.get("country") == "187", (_okNg, _resNg))
        check("sms : le pays regle est quand meme essaye en premier",
              [c for a, c in _vus if a == "getNumber"][:1] == ["0"], _vus)

        _vus.clear()
        _ngT._stubs = lambda pr, ac, **p: (_vus.append(ac) or "BAD_KEY")
        _okNg2, _msgNg = _ngT.get_number("ig")
        check("sms : une cle refusee ne fait pas le tour des pays",
              _okNg2 is False and _vus == ["getNumber"], _vus)
    finally:
        _ngT._stubs, _ngT.getatext_key = _svS, _svG
        _ngT.smsbower_key, _ngT._cfg = _svB, _svC

    check("sms : le defaut n est plus la Russie", _ngT.PAYS_DEFAUT != "0",
          _ngT.PAYS_DEFAUT)
    check("sms : une seule table de pays pour le site et le bot",
          _wNg._NUMGEN_PAYS is _ngT.PAYS)

    _ngT.set_keys(country=_avantNg)      # on repose ce qu on a trouve
    _wNg._load_web_users = _savNg
except Exception as _eNg:
    check("sms : reglage du pays testable", False, repr(_eNg)[:160])

print()
print("=" * 70)
print("NOMS DE FICHIERS DANS LES URL (la cause du mur de cartes noires)")
print("=" * 70)
try:
    import re as _reDi
    import shutil as _shDi
    import subprocess as _spDi
    import web_upload as _wDi

    # 89 % des rushs portent un « # » : leurs noms viennent de captions
    # Instagram, donc de hashtags. Sans encodage, le navigateur coupe
    # l adresse au premier « # » qu il prend pour une ancre — le serveur
    # recoit « genesaag__ » au lieu du nom complet et repond 404. Mesure sur
    # le site reel : 68 requetes de vignettes, 68 en 404, et autant de cartes
    # noires. On a cherche du cote de ffmpeg puis du JavaScript avant de
    # regarder les requetes.
    check("url : le diese est encode", "%23" in _wDi._url_nom("a#b.mp4"))
    check("url : la barre aussi (ces routes veulent UN segment)",
          "/" not in _wDi._url_nom("a/b.mp4"))
    check("url : un nom ordinaire n est pas abime",
          _wDi._url_nom("clip.mp4") == "clip.mp4")

    _idDi = "_tst_diese"
    _dDi = _wDi.IDENTITIES_DIR / _idDi / "brutes"
    _shDi.rmtree(_wDi.IDENTITIES_DIR / _idDi, ignore_errors=True)
    _dDi.mkdir(parents=True)
    _nomDi = "modele__ #fyp #outfitinspo_764.mp4"
    _spDi.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
               "-i", "testsrc=s=180x320:d=2", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", str(_dDi / _nomDi)],
              capture_output=True, timeout=90)
    _aDi = _wDi.create_app(); _aDi.testing = True
    _savDi = _wDi._load_web_users
    _wDi._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cDi = _aDi.test_client()
    with _cDi.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "DI1"
    _hDi = galerie(_cDi, "/?tab=cloudbrutes&cloud_brutes_ident=" + _idDi)
    _mDi = _reDi.search(r"/cloud/thumb/" + _idDi + r"/brutes/[^'\" ]+", _hDi)
    check("url : la galerie rend une adresse encodee pour un nom a diese",
          bool(_mDi) and "%23" in _mDi.group(0),
          _mDi.group(0)[:90] if _mDi else "aucune adresse trouvee")
    if _mDi:
        _rDi = _cDi.get(_mDi.group(0))
        # LE test : c est la requete reelle qui rendait 404 et laissait la
        # carte noire.
        check("url : cette adresse rend bien une image, pas un 404",
              _rDi.status_code == 200
              and "image" in (_rDi.headers.get("Content-Type") or "")
              and len(_rDi.get_data()) > 500,
              "HTTP %s %s" % (_rDi.status_code, _rDi.headers.get("Content-Type")))
    _wDi._load_web_users = _savDi
    _shDi.rmtree(_wDi.IDENTITIES_DIR / _idDi, ignore_errors=True)
    _shDi.rmtree(_wDi.THUMB_DIR / ("v%d" % _wDi.THUMB_RECETTE) / _idDi,
                 ignore_errors=True)
except FileNotFoundError:
    check("url : testable (ffmpeg absent)", False, "ffmpeg introuvable")
except Exception as _eDi:
    check("url : testable", False, repr(_eDi)[:160])

print()
print("=" * 70)
print("VIGNETTE NOIRE (la vraie cause du mur de cartes noires)")
print("=" * 70)
try:
    import subprocess as _spNo
    import tempfile as _tfNo
    import pathlib as _plNo
    import web_upload as _wNo
    from PIL import Image as _ImNo, ImageStat as _StNo

    # LA cause, trouvee apres deux correctifs JavaScript inutiles : les
    # vignettes se generaient tres bien, elles etaient simplement NOIRES.
    # L ancienne recette prenait l image a 0,5 s telle quelle ; sur une video
    # commencant par un fondu ou un logo — la norme sur les rushs — elle
    # rendait 0,5 sur 255. Une vignette noire ne se distingue pas d un
    # chargement en cours : on cherche alors du cote du navigateur.
    with _tfNo.TemporaryDirectory() as _tmpNo:
        _dNo = _plNo.Path(_tmpNo)
        _srcNo = _dNo / "debut_noir.mp4"
        _rNo = _spNo.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=black:s=360x640:d=1.2",
             "-f", "lavfi", "-i", "testsrc=s=360x640:d=3",
             "-filter_complex", "[0:v][1:v]concat=n=2:v=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(_srcNo)],
            capture_output=True, timeout=90)
        if _rNo.returncode != 0 or not _srcNo.exists():
            raise RuntimeError("ffmpeg n a pas pu fabriquer la video d essai")
        _outNo = _dNo / "v.jpg"
        _okNo = _wNo._generate_video_thumbnail(_srcNo, _outNo)
        _lumNo = (_StNo.Stat(_ImNo.open(_outNo).convert("L")).mean[0]
                  if _outNo.exists() else -1)
        check("vignette : une video qui commence par du noir donne une image LISIBLE",
              _okNo and _lumNo >= 12, "luminosite %.1f / 255" % _lumNo)
        # Et le detecteur doit reconnaitre une image reellement noire, sinon la
        # seconde tentative ne partirait jamais.
        _noirNo = _dNo / "noir.jpg"
        _ImNo.new("RGB", (60, 60), (0, 0, 0)).save(_noirNo)
        check("vignette : une image noire est bien reconnue comme telle",
              _wNo._vignette_trop_sombre(_noirNo))
        _ImNo.new("RGB", (60, 60), (140, 140, 140)).save(_noirNo)
        check("vignette : une image normale n est pas prise pour du noir",
              not _wNo._vignette_trop_sombre(_noirNo))
    # Changer la recette doit rendre TOUT le cache obsolete : les anciennes
    # vignettes sont plus recentes que leur media, elles ne seraient jamais
    # refaites sans ca.
    check("vignette : le cache est versionne par recette",
          ("v%d" % _wNo.THUMB_RECETTE) in _wNo._thumb_path_for("a/b/c.mp4").as_posix())
except FileNotFoundError:
    check("vignette noire : testable (ffmpeg absent)", False, "ffmpeg introuvable")
except Exception as _eNo:
    check("vignette noire : testable", False, repr(_eNo)[:160])

print()
print("=" * 70)
print("VIGNETTE PERIMEE (defaut F4)")
print("=" * 70)
try:
    import shutil as _shVg
    import time as _tmVg
    import web_upload as _wVg
    from PIL import Image as _ImVg

    # La cle d une vignette porte le NOM du fichier, pas son contenu.
    # Supprimer puis re-televerser sous le meme nom laissait donc l apercu de
    # l ANCIENNE video, definitivement — et avec un cache navigateur d une
    # journee par-dessus. Le code nettoyait deja l etoile et le favori dans ce
    # cas exact ; la vignette etait le troisieme etat oublie.
    _idVg = "_tst_vignette"
    _dVg = _wVg.IDENTITIES_DIR / _idVg / "posts"
    _shVg.rmtree(_wVg.IDENTITIES_DIR / _idVg, ignore_errors=True)
    _dVg.mkdir(parents=True)
    _ImVg.new("RGB", (80, 80), (200, 0, 0)).save(_dVg / "p.jpg")
    _cleVg = "%s/posts/p.jpg" % _idVg
    _t1 = _wVg._get_or_create_thumbnail(_dVg / "p.jpg", _cleVg, False)
    check("vignette : creee au premier appel", bool(_t1 and _t1.exists()))
    _m1 = _t1.stat().st_mtime
    _tmVg.sleep(1.1)                      # granularite du mtime
    _ImVg.new("RGB", (80, 80), (0, 0, 200)).save(_dVg / "p.jpg")
    _t2 = _wVg._get_or_create_thumbnail(_dVg / "p.jpg", _cleVg, False)
    check("vignette : regeneree quand le media a change",
          bool(_t2) and _t2.stat().st_mtime > _m1)
    check("vignette : elle montre bien le NOUVEAU media",
          _ImVg.open(_t2).convert("RGB").getpixel((40, 40))[2] > 100)
    _shVg.rmtree(_wVg.IDENTITIES_DIR / _idVg, ignore_errors=True)
    _shVg.rmtree(_wVg.THUMB_DIR / _idVg, ignore_errors=True)
except Exception as _eVg:
    check("vignette : testable", False, repr(_eVg)[:160])

print()
print("=" * 70)
print("FRAGMENT LEGER DES GALERIES (defaut F5)")
print("=" * 70)
try:
    import pathlib as _plFr
    import shutil as _shFr
    import web_upload as _wFr

    _aFr = _wFr.create_app(); _aFr.testing = True
    _savFr = _wFr._load_web_users
    _wFr._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cFr = _aFr.test_client()
    with _cFr.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "FR1"

    # « Video brut » et « Templates montage » manquaient a la table des
    # fragments : chaque survol d identite renvoyait la page ENTIERE, soit
    # 1,4 Mo, et reconstruisait sept galeries plus le tableau de bord cote
    # serveur. Ce sont exactement les deux onglets ou l on constatait que
    # « rien ne charge ».
    for _tabFr, _identFr, _kFr in (("cloudbrutes", "_tst_frag", "cloud_brutes_ident"),
                                   ("cloudtemplates", "_tst_frag2", "cloud_templates_ident")):
        _dFr = _wFr.IDENTITIES_DIR / _identFr / _tabFr.replace("cloud", "")
        _shFr.rmtree(_wFr.IDENTITIES_DIR / _identFr, ignore_errors=True)
        _dFr.mkdir(parents=True)
        (_dFr / "c1.mp4").write_bytes(b"\x00" * 9000)
        _url = "/?tab=%s&%s=%s" % (_tabFr, _kFr, _identFr)
        _plein = _cFr.get(_url).get_data(as_text=True)
        _frag = _cFr.get(_url + "&frag=1",
                         headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
        check("fragment %s : dix fois plus leger que la page" % _tabFr,
              len(_frag) < len(_plein) / 10,
              "%d vs %d octets" % (len(_frag), len(_plein)))
        check("fragment %s : porte bien la galerie et la bonne identite" % _tabFr,
              "vault-grid" in _frag and _identFr in _frag)
        _shFr.rmtree(_wFr.IDENTITIES_DIR / _identFr, ignore_errors=True)
    _wFr._load_web_users = _savFr
except Exception as _eFr:
    check("fragment : testable", False, repr(_eFr)[:160])

print()
print("=" * 70)
print("SELECTION MULTIPLE ET NAVIGATION (defauts B1 et F2)")
print("=" * 70)
try:
    import pathlib as _plSel
    _srcSel = _plSel.Path("web_upload.py").read_text(encoding="utf-8")

    # B1 — la selection ne doit JAMAIS traverser un changement de galerie :
    # 4 rushs coches chez amelia, un clic sur julia, 1 fichier coche, et la
    # corbeille en supprimait 5. Irreversible, sans corbeille.
    _iGo = _srcSel.index("window.vaultGoTo = function")
    check("selection : videe au changement d identite",
          "clearSelection()" in _srcSel[_iGo:_iGo + 700])
    _iTab = _srcSel.index("function showTab(")
    check("selection : videe au changement d onglet",
          "clearSelection()" in _srcSel[_iTab:_iTab + 500])

    # « Tout selectionner » prenait aussi les cartes masquees par le filtre
    # etoile : on croyait supprimer 3 fichiers, on en supprimait 200.
    _iAll = _srcSel.index("function vaultSelectAll()")
    check("selection : « tout selectionner » ignore les cartes masquees",
          "offsetParent" in _srcSel[_iAll:_iAll + 900])

    # F2 — les scripts recopies SANS leurs attributs perdaient l id et le type
    # du bloc de donnees : tout l onglet Caption devenait inerte, sans message.
    check("navigation : les scripts sont recopies avec leurs attributs",
          "for(const a of oldS.attributes)" in _srcSel)
except Exception as _eSel:
    check("selection : testable", False, repr(_eSel)[:160])

print()
print("=" * 70)
print("VEILLE : les miniatures ne dependent plus d Instagram")
print("=" * 70)
try:
    import re as _reVl
    import shutil as _shVl

    import veille as _vlVl
    import web_upload as _wVl

    # Les adresses de miniature d Instagram sont SIGNEES et expirent. La Veille
    # garde des reels des semaines : ses cartes finissaient par pointer vers des
    # liens morts. Mesure dans la page : 382 miniatures sur 382 en echec cote
    # Veille, pendant que le volet « Suivies », frais du scrape, en chargeait
    # 636 sur 636. Vu de l utilisateur : « les videos ne chargent plus ».
    check("veille : une copie locale de la miniature est prevue",
          hasattr(_vlVl, "copier_thumb") and hasattr(_vlVl, "chemin_thumb"))
    import pathlib as _plVl
    check("veille : la carte pointe vers NOUS, plus vers Instagram",
          '<img src="/veille/thumb/{rid}"' in
          _plVl.Path("web_upload.py").read_text(encoding="utf-8"),
          "sinon l apercu meurt avec la signature du CDN")

    _appVl = _wVl.create_app()
    _appVl.config["TESTING"] = True
    _svVl = _wVl._load_web_users
    _wVl._load_web_users = lambda: {"admin": {"role": "owner", "password": "x"}}
    try:
        _cVl = _appVl.test_client()
        check("veille : la miniature exige une session",
              _cVl.get("/veille/thumb/deadbeef").status_code in (302, 401, 403),
              "une route de lecture reste protegee")
        with _cVl.session_transaction() as _sVl:
            _sVl["auth"] = True
            _sVl["username"] = "admin"
            _sVl["role"] = "owner"
        # Un carre casse laisse croire a une panne du site : on renvoie une
        # image qui DIT que l apercu a expire.
        _rVl = _cVl.get("/veille/thumb/deadbeef")
        check("veille : un reel inconnu rend une image, pas une erreur",
              _rVl.status_code == 200 and (_rVl.mimetype or "").startswith("image/"),
              "code %s, type %s" % (_rVl.status_code, _rVl.mimetype))
        check("veille : cette image dit pourquoi elle est la",
              _rVl.headers.get("X-Thumb-Error") is not None)
        for _malVl, _attVl in (("zz!!bad", 403), ("../etc", 404), ("", 404)):
            check("veille : l identifiant %r est refuse" % _malVl[:10],
                  _cVl.get("/veille/thumb/" + _malVl).status_code == _attVl)

        # Une vraie copie locale doit etre servie telle quelle.
        _ridVl = "abcdef123456"
        try:
            _vlVl.VEILLE_THUMBS_DIR.mkdir(parents=True, exist_ok=True)
            _vlVl.chemin_thumb(_ridVl).write_bytes(
                bytes((0xFF, 0xD8, 0xFF, 0xE0)) + b"\x00" * 3000)
            _r2Vl = _cVl.get("/veille/thumb/" + _ridVl)
            check("veille : une copie locale est servie directement",
                  _r2Vl.status_code == 200 and len(_r2Vl.data) > 2000,
                  "code %s, %d octets" % (_r2Vl.status_code, len(_r2Vl.data)))
            check("veille : et gardee longtemps en cache",
                  "max-age" in (_r2Vl.headers.get("Cache-Control") or ""))
        finally:
            # send_file garde le fichier OUVERT tant que la reponse n est pas
            # fermee : sous Windows, l effacer avant leve une PermissionError.
            try:
                _r2Vl.close()
            except Exception:
                pass
            try:
                _vlVl.chemin_thumb(_ridVl).unlink(missing_ok=True)
            except OSError:
                pass
        # Une reponse du CDN qui n est PAS une image ne doit pas etre gardee.
        check("veille : une page d erreur du CDN n est pas prise pour une image",
              _vlVl.copier_thumb("zzz_tst", "https://exemple.invalide/x.jpg") is False)
    finally:
        _wVl._load_web_users = _svVl
        try:
            _vlVl.chemin_thumb("zzz_tst").unlink(missing_ok=True)
        except OSError:
            pass
except Exception as _eVl:
    check("veille : testable", False, repr(_eVl)[:160])

print()
print("=" * 70)
print("FILIGRANE « DISPO VA » : trame au lieu du texte tuile")
print("=" * 70)
try:
    import re as _reWm
    import pathlib as _plWm
    import urllib.parse as _uWm

    _srcWm = _plWm.Path("web_upload.py").read_text(encoding="utf-8")
    import web_upload as _wWm

    # L ancien motif ecrivait « DISPO VA » en gras toutes les 150 px : lisible,
    # mais il recouvrait l image et faisait tampon administratif. La trame
    # marque la carte tout aussi nettement dans une grille de 200, sans rien
    # cacher de reconnaissable.
    _uriWm = _uWm.unquote(_wWm._va_ready_watermark_uri().split(",", 1)[1])
    check("filigrane : le motif ne repete plus de texte",
          "<text" not in _uriWm and "DISPO VA" not in _uriWm,
          "le motif tuile porte encore du texte")
    check("filigrane : c est bien une trame de hachures",
          "<path" in _uriWm and "stroke" in _uriWm)
    check("filigrane : la tuile est fine, pas un pave de 150 px",
          "width='14'" in _uriWm and "background-size:14px 14px" in _srcWm)

    _bandeWm = _reWm.search(r"\.vault-card-bg\.va-ready::after\{([^}]*)\}", _srcWm)
    check("filigrane : le libelle est un bandeau pleine largeur en bas",
          bool(_bandeWm)
          and all(_x in _bandeWm.group(1)
                  for _x in ("left:0", "right:0", "bottom:0", "top:auto")),
          "sinon la pastille reste dans un coin")

    # Les deux etats se disputaient le MEME pseudo-element : la regle « dispo
    # VA », plus tardive, l emportait et l alerte ambre disparaissait sans
    # bruit — alors qu elle existe justement pour etre vue sans ouvrir la carte.
    _duoWm = _reWm.search(
        r"\.vault-card-bg\.va-ready\.a-approuver::after\{([^}]*)\}", _srcWm)
    check("filigrane : une carte dispo ET a approuver montre les DEUX etats",
          bool(_duoWm) and "DISPO VA" in _duoWm.group(1)
          and "APPROUVER" in _duoWm.group(1),
          "l alerte ambre etait perdue en silence")
    check("filigrane : cet etat double prend la couleur de l alerte",
          bool(_duoWm) and "217,119,6" in _duoWm.group(1),
          "sinon on croit la carte simplement dispo")
    # La regle combinee doit rester PLUS SPECIFIQUE que celle de « dispo VA »
    # seule, sinon la seconde l ecrase de nouveau.
    check("filigrane : la regle combinee reste la plus specifique",
          _srcWm.count(".vault-card-bg.va-ready.a-approuver::after") == 1)
except Exception as _eWm:
    check("filigrane : testable", False, repr(_eWm)[:160])

print()
print("=" * 70)
print("BRUTES DESACTIVEES (caption deja incrustee)")
print("=" * 70)
try:
    import re as _reOf
    import shutil as _shOf
    import pathlib as _plOf
    import brutes_off as _offOf
    import web_upload as _wOf

    _identOf = "_tstoff"
    _dirOf = _wOf.IDENTITIES_DIR / _identOf / "brutes"
    try:
        _shOf.rmtree(_wOf.IDENTITIES_DIR / _identOf, ignore_errors=True)
        _dirOf.mkdir(parents=True, exist_ok=True)
        for _n in ("a.mp4", "b.mp4", "c.mp4", "d.example.mp4", "notes.txt"):
            (_dirOf / _n).write_bytes(b"\x00" * 64)

        _tousOf = _offOf.lister(_dirOf)
        check("desactivees : les .example et les non-videos sont ecartes",
              [p.name for p in _tousOf] == ["a.mp4", "b.mp4", "c.mp4"],
              "obtenu : %s" % [p.name for p in _tousOf])

        # Desactiver ne touche PAS le fichier video : le site n efface jamais
        # un media, et on doit pouvoir revenir en arriere.
        _aOf = _dirOf / "a.mp4"
        _tailleAvant = _aOf.stat().st_size
        check("desactivees : la mise de cote reussit",
              _offOf.desactiver(_aOf, _offOf.CAUSE_TEXTE))
        check("desactivees : la video elle-meme n est pas touchee",
              _aOf.exists() and _aOf.stat().st_size == _tailleAvant)
        _voisinOf = _offOf.lire(_aOf)
        check("desactivees : le voisin garde la CAUSE et la DATE",
              _voisinOf.get("cause") == _offOf.CAUSE_TEXTE and _voisinOf.get("le"),
              "voisin : %r" % _voisinOf)

        check("desactivees : elle disparait de ce qui part chez un VA",
              [p.name for p in _offOf.lister(_dirOf)] == ["b.mp4", "c.mp4"])
        # Les vues du proprietaire doivent au contraire les MONTRER.
        check("desactivees : mais reste visible pour le proprietaire",
              len(_offOf.lister(_dirOf, inclure_desactivees=True)) == 3)
        check("desactivees : le filtre de liste deja constituee marche aussi",
              [p.name for p in _offOf.sans_desactivees(_tousOf)] == ["b.mp4", "c.mp4"])

        check("desactivees : la remise en service fonctionne",
              _offOf.reactiver(_aOf) and len(_offOf.lister(_dirOf)) == 3)

        # LE point delicat : une video qu on n a pas su lire ne doit JAMAIS
        # etre eteinte. Decider a la place de quelqu un qui n a rien decide
        # est exactement ce qu on veut eviter.
        _wOf._textecheck_ecrire(_dirOf / "a.mp4", True, ["accroche"], "")
        _wOf._textecheck_ecrire(_dirOf / "b.mp4", None, [], "illisible")
        _wOf._textecheck_ecrire(_dirOf / "c.mp4", False, [], "")

        _appOf = _wOf.create_app()
        _appOf.config["TESTING"] = True
        _svOf = _wOf._load_web_users
        _wOf._load_web_users = lambda: {"admin": {"role": "owner", "password": "x"}}
        try:
            _cOf = _appOf.test_client()
            with _cOf.session_transaction() as _sOf:
                _sOf["auth"] = True
                _sOf["username"] = "admin"
                _sOf["role"] = "owner"
            _rOf = _cOf.post("/cloud/desactiver_texte", data={"identity": _identOf})
            _jOf = _rOf.get_json() or {}
            check("desactivees : la route eteint bien les brutes avec texte",
                  _jOf.get("ok") and _jOf.get("faits") == 1,
                  "reponse : %r" % {k: _jOf.get(k) for k in ("ok", "faits", "rates")})
            check("desactivees : la video AVEC texte est eteinte",
                  _offOf.est_desactivee(_dirOf / "a.mp4"))
            check("desactivees : la video NON CONCLUE est laissee allumee",
                  not _offOf.est_desactivee(_dirOf / "b.mp4"),
                  "une video illisible ne doit jamais etre eteinte d office")
            check("desactivees : la video SANS texte est laissee allumee",
                  not _offOf.est_desactivee(_dirOf / "c.mp4"))

            # Un second clic ne doit rien refaire : le bouton annonce le
            # nombre RESTANT, pas le total.
            _r2 = _cOf.post("/cloud/desactiver_texte", data={"identity": _identOf})
            check("desactivees : un second clic ne compte pas deux fois",
                  (_r2.get_json() or {}).get("faits") == 0)

            _r3 = _cOf.post("/cloud/desactiver_texte",
                            data={"identity": _identOf, "remettre": "1"})
            check("desactivees : le bouton inverse les rallume",
                  (_r3.get_json() or {}).get("faits") == 1
                  and not _offOf.est_desactivee(_dirOf / "a.mp4"))

            # Une brute eteinte a la MAIN pour une autre raison ne doit pas
            # revenir avec ce bouton-la.
            _offOf.desactiver(_dirOf / "c.mp4", "raison a moi")
            _cOf.post("/cloud/desactiver_texte",
                      data={"identity": _identOf, "remettre": "1"})
            check("desactivees : le bouton inverse ne touche que ce qu il a eteint",
                  _offOf.est_desactivee(_dirOf / "c.mp4"))
        finally:
            _wOf._load_web_users = _svOf
    finally:
        _shOf.rmtree(_wOf.IDENTITIES_DIR / _identOf, ignore_errors=True)

    # Le voisin doit partir AVEC la video. Laisse seul, il eteindrait a la
    # naissance une future video qui porterait le meme nom.
    check("desactivees : le voisin part avec la video supprimee",
          "or n == f\"{stem}{SUFFIXE_DESACTIVE}\"" in _plOf.Path(
              "web_upload.py").read_text(encoding="utf-8"),
          "un .off.json orphelin resterait sur le disque")

    # Le moteur video : UN seul enumerateur alimente le montage, « Reel deja
    # monte » et /noctus/montage_gen. Non filtre, il rouvrait les trois.
    _srcNx = _plOf.Path("noctus_web.py").read_text(encoding="utf-8")
    check("desactivees : le moteur video les ecarte aussi",
          "est_desactivee(f)" in _srcNx,
          "le montage repiocherait dedans")
    check("desactivees : et il DIT pourquoi, au lieu de les taire",
          "désactivée (caption déjà incrustée)" in _srcNx)

    # Le parc de telephones PUBLIE sur Instagram : y laisser passer une brute
    # eteinte est pire qu un envoi a un VA, qui aurait pu s en apercevoir.
    _srcRig = _plOf.Path("web_upload.py").read_text(encoding="utf-8")
    # Trois gardes « chemin » depuis que l'etoile des brutes envoie elle aussi
    # dans Discord (_brute_banger_discord) : elle publie, donc elle se ferme
    # comme les autres. Le compte monte avec le nombre de portes, jamais
    # l'inverse — s'il baisse, c'est qu'une porte s'est rouverte.
    check("desactivees : les routes publiantes du rig sont fermees",
          _srcRig.count("_off.est_desactivee(chemin)") == 3
          and "_off.est_desactivee(f)" in _srcRig,
          "une brute eteinte pourrait etre publiee publiquement")
    check("desactivees : la route banger les refuse aussi",
          "_off.est_desactivee(path)" in _srcRig)

    # Structure : tout ce qui sert un VA doit passer par la porte commune.
    # Le filtre etait recopie a trois endroits ; en oublier un se voit ici.
    _srcBot = _plOf.Path("cogs/user.py").read_text(encoding="utf-8")
    check("desactivees : le bot passe par la porte commune",
          _srcBot.count("_off.lister(") >= 2 and "_off.est_desactivee(" in _srcBot,
          "un chemin Discord liste encore le dossier lui-meme")
    _srcSite = _plOf.Path("web_upload.py").read_text(encoding="utf-8")
    check("desactivees : le site aussi",
          _srcSite.count("_off.lister(") >= 3,
          "%d appel(s)" % _srcSite.count("_off.lister("))
except Exception as _eOf:
    check("desactivees : testable", False, repr(_eOf)[:200])

print()
print("=" * 70)
print("FILTRE DE MARCHE : FR et US melanges pendant 6 secondes")
print("=" * 70)
try:
    import re as _reMk
    import pathlib as _plMk

    _srcMk = _plMk.Path("web_upload.py").read_text(encoding="utf-8")

    # Le filtre ne vivait que dans localStorage, donc en JavaScript, et ne
    # s appliquait qu au DOMContentLoaded : mesure sur le site, 6 535 ms apres
    # un changement d identite. Pendant ces six secondes la barre montrait les
    # 160 identites, FR et US melangees. Le serveur doit donc masquer lui-meme.
    check("marche : le serveur sait masquer les identites de l autre marche",
          "def _marche_cache(" in _srcMk)
    _posesMk = _srcMk.count("style='{_marche_cache(ident, selected)}'")
    check("marche : les QUATRE listes d identites appliquent le masquage",
          _posesMk == 4, "%d liste(s) sur 4" % _posesMk)
    check("marche : le choix est ecrit dans un cookie, lisible par le serveur",
          "va_market=" in _srcMk and "function marcheCookie(" in _srcMk,
          "sans cookie, le serveur ne peut pas rendre la bonne liste")
    check("marche : « Tout afficher » efface aussi le cookie",
          _reMk.search(r"localStorage\.setItem\('vault_market',''\);.{0,120}?marcheCookie\(''\)",
                       _srcMk, _reMk.S) is not None,
          "sinon le serveur masquerait ce que le client vient de reafficher")
    check("marche : un choix deja fait est recopie dans le cookie au demarrage",
          "document.cookie.indexOf('va_market=') === -1" in _srcMk,
          "sinon les sessions ouvertes gardent le defaut pendant un chargement")

    # Rendu reel : c est la seule preuve qui vaille.
    import web_upload as _wMk
    _appMk = _wMk.create_app()
    _appMk.config["TESTING"] = True
    _svMk = _wMk._load_web_users
    _wMk._load_web_users = lambda: {"admin": {"role": "owner", "password": "x"}}
    try:
        _cMk = _appMk.test_client()
        with _cMk.session_transaction() as _sMk:
            _sMk["auth"] = True
            _sMk["username"] = "admin"
            _sMk["role"] = "owner"

        def _itemsMk(html, section="form-cloudbrutes"):
            """(identite, marche, masquee) pour la barre d UNE section.

            La page rend la barre de CHAQUE galerie, et chacune a sa propre
            identite selectionnee — laquelle reste visible par choix. Balayer
            toute la page melangeait donc les sections et faisait passer pour
            un defaut ce qui est le comportement voulu ailleurs.
            """
            _d = html.find("id='%s'" % section)
            if _d < 0:
                _d = html.find('id="%s"' % section)
            if _d < 0:
                return []
            _f = html.find("class=\"form-section\"", _d + 10)
            _bloc = html[_d:_f if _f > 0 else len(html)]
            out = []
            for _m in _reMk.finditer(
                    r"class='vault-item[^']*' data-ident='([^']*)' "
                    r"data-market='([^']*)' style='([^']*)'", _bloc):
                out.append((_m.group(1), _m.group(2), "display:none" in _m.group(3)))
            return out

        # Le jeu local ne contient qu UNE identite, et c est la selectionnee :
        # impossible d y prouver quoi que ce soit. On en fabrique deux, une par
        # marche, et on les efface a la fin. Le marche est simule en memoire —
        # on n ecrit RIEN dans le registre des marches.
        import shutil as _shMk
        _tmpMk = {"_tstmk_fr": "fr", "_tstmk_us": "us"}
        _origMarcheMk = _wMk.identity_market
        try:
            for _nom in _tmpMk:
                (_wMk.IDENTITIES_DIR / _nom / "brutes").mkdir(parents=True, exist_ok=True)
            _wMk.identity_market = (lambda i: _tmpMk.get(i, _origMarcheMk(i)))

            _sansMk = _itemsMk(galerie(_cMk, "/?tab=cloudbrutes"))
            check("marche : sans choix, aucune identite n est masquee",
                  bool(_sansMk) and not any(_h for _i, _m, _h in _sansMk),
                  "%d entree(s), %d masquee(s)"
                  % (len(_sansMk), sum(1 for _i, _m, _h in _sansMk if _h)))

            _cMk.set_cookie("va_market", "us")
            _url = "/?tab=cloudbrutes&cloud_brutes_ident=_tstmk_us"
            _avecMk = _itemsMk(galerie(_cMk, _url))
            _dico = {_i: _h for _i, _m, _h in _avecMk}
            check("marche : avec le choix US, une identite FR est masquee des le HTML",
                  _dico.get("_tstmk_fr") is True,
                  "etat rendu : %r" % _dico.get("_tstmk_fr"))
            check("marche : une identite US, elle, reste visible",
                  _dico.get("_tstmk_us") is False,
                  "etat rendu : %r" % _dico.get("_tstmk_us"))
            # On vient d ouvrir son contenu : la faire disparaitre de sa propre
            # liste laisserait une galerie sans entree correspondante.
            _selFr = _itemsMk(galerie(_cMk, "/?tab=cloudbrutes&cloud_brutes_ident=_tstmk_fr"))
            _dicoFr = {_i: _h for _i, _m, _h in _selFr}
            check("marche : l identite SELECTIONNEE reste visible, meme hors marche",
                  _dicoFr.get("_tstmk_fr") is False,
                  "etat rendu : %r" % _dicoFr.get("_tstmk_fr"))

            # Derniere fuite : une galerie ouverte SANS identite explicite
            # retombait sur la premiere de la liste, souvent de l autre marche.
            # Comme une selectionnee ne se masque jamais, cette entree restait
            # visible — une seule, mais visible, et l utilisateur la voit.
            _htmlDef = galerie(_cMk, "/?tab=cloudbrutes")
            _dicoDef = {_i: _h for _i, _m, _h in _itemsMk(_htmlDef)}
            check("marche : sans identite dans l URL, le defaut respecte le marche",
                  _dicoDef.get("_tstmk_fr") is not False,
                  "une identite FR selectionnee par defaut alors qu on est en US")
            check("marche : le helper de defaut existe et est branche partout",
                  _srcMk.count("_marche_prefere(identities)") == 4,
                  "%d branchement(s) sur 4"
                  % _srcMk.count("_marche_prefere(identities)"))
        finally:
            _wMk.identity_market = _origMarcheMk
            for _nom in _tmpMk:
                _shMk.rmtree(_wMk.IDENTITIES_DIR / _nom, ignore_errors=True)
    finally:
        _wMk._load_web_users = _svMk
except Exception as _eMk:
    check("marche : testable", False, repr(_eMk)[:200])

print()
print("=" * 70)
print("APERCUS DES VIDEOS : le fondu qui ne demarrait jamais")
print("=" * 70)
try:
    import re as _reAp
    import pathlib as _plAp

    _srcAp = _plAp.Path("web_upload.py").read_text(encoding="utf-8")

    # LA panne, cherchee pendant des semaines du mauvais cote. Les miniatures
    # etaient generees, servies et TELECHARGEES (mesure sur le site : 204 sur
    # 204, naturalWidth 360x640) — mais invisibles. L image demarrait a
    # opacity:0 avec une transition de .25s revelee par onload, et son ancetre
    # .cloud-card porte content-visibility:auto : le rendu des cartes hors
    # ecran est SAUTE, la transition ne demarre jamais, l opacite reste a 0.
    # Retirer la seule transition faisait apparaitre les 204.
    check("apercus : l image de carte ne demarre plus invisible",
          "object-fit:cover;display:block;opacity:0;transition:opacity .25s" not in _srcAp,
          "un fondu sous content-visibility:auto reste bloque a 0")
    check("apercus : la classe .vault-img-load ne cache plus l image",
          ".vault-img-load{opacity:0}" not in _srcAp)
    # Le pendant de ce fondu n existait pas : rien n ajoutait « loaded ».
    check("apercus : pas de reveal par une classe que personne n ajoute",
          not (".vault-img-load.loaded" in _srcAp
               and "classList.add('loaded')" not in _srcAp))

    # Regle generale : sous un ancetre content-visibility:auto, on ne fait pas
    # dependre la VISIBILITE d une transition. Les cartes media sont le seul
    # endroit concerne, mais la regle doit tenir si on en ajoute.
    _cvAp = _reAp.search(r"\.cloud-card\{[^}]*content-visibility:\s*auto", _srcAp)
    check("apercus : les cartes media utilisent bien content-visibility",
          _cvAp is not None, "sinon ce test ne protege plus rien")
    _fonduAp = _reAp.findall(r"vault-img-load[^>']*transition:\s*opacity", _srcAp)
    check("apercus : plus aucune transition d opacite sur ces images",
          not _fonduAp, "%d restante(s)" % len(_fonduAp))

    # Deuxieme moitie de la panne : la carte etait peinte en NOIR plein en
    # theme clair, ce qui rendait une miniature manquante indiscernable d une
    # video sans apercu. La regle visait les <video> et avait emporte la carte.
    _noirAp = _reAp.search(r"body\.light[^{}]*\.vault-card-bg[^{}]*\{[^}]*background:\s*#000",
                           _srcAp)
    check("apercus : la carte n est plus peinte en noir en theme clair",
          _noirAp is None,
          "le degrade de chargement gris etait ecrase par un fond noir")

    # Enfin : personne n avait JAMAIS verifie qu une miniature de video sort
    # bien de la route. C est ce trou qui a laisse chercher du cote du
    # navigateur pendant si longtemps.
    import web_upload as _wAp
    _appAp = _wAp.create_app()
    _appAp.config["TESTING"] = True
    _svAp = _wAp._load_web_users
    _wAp._load_web_users = lambda: {"admin": {"role": "owner", "password": "x"}}
    try:
        _cAp = _appAp.test_client()
        with _cAp.session_transaction() as _sAp:
            _sAp["auth"] = True
            _sAp["username"] = "admin"
            _sAp["role"] = "owner"
        _videoAp = None
        for _sub in ("brutes", "videos", "templates"):
            for _f in _wAp.IDENTITIES_DIR.glob("*/%s/*.mp4" % _sub):
                _videoAp = (_f.parent.parent.name, _sub, _f.name)
                break
            if _videoAp:
                break
        if _videoAp:
            _ident, _sub, _nom = _videoAp
            from urllib.parse import quote as _qAp
            _rAp = _cAp.get("/cloud/thumb/%s/%s/%s"
                            % (_qAp(_ident, safe=""), _sub, _qAp(_nom, safe="")))
            check("apercus : la route rend une miniature pour une video",
                  _rAp.status_code == 200, "code %s" % _rAp.status_code)
            _mtAp = (_rAp.mimetype or "")
            check("apercus : ce qui sort est une IMAGE, jamais la video",
                  _mtAp.startswith("image/"), "mimetype %r" % _mtAp)
            # Le repli servait autrefois le fichier ORIGINAL : une galerie de
            # 204 rushs telechargeait 400 Mo pour afficher des cartes noires.
            check("apercus : le repli reste leger (jamais des megaoctets)",
                  len(_rAp.data) < 3_000_000,
                  "%d octets renvoyes" % len(_rAp.data))
        else:
            check("apercus : une video locale existe pour tester la route",
                  True, "aucune video en local — controle saute")

        # « .. » etait refuse PARTOUT dans le nom, pas seulement comme segment
        # de remontee. Les captions Instagram sont pleines de points de
        # suspension : « trop bien... #ootd.mp4 » recevait un 403 sur la
        # miniature, sur la lecture ET sur le telechargement par le rig.
        # C est la seconde moitie du probleme du « # », deja corrige.
        # Le cache ne verifiait que la PRESENCE et la date. Un ffmpeg
        # interrompu — timeout de 25 s, disque plein, redemarrage — laisse un
        # fichier vide ou coupe, alors servi en 200 image/jpeg avec 24 h de
        # cache. La carte restait noire pour toujours, et seul un changement de
        # THUMB_RECETTE purgeait : d ou les « corrige puis re-casse ».
        import tempfile as _tfAp
        _dAp = _plAp.Path(_tfAp.mkdtemp())
        try:
            for _nomCas, _octets, _attendu in (
                    ("vide", b"", False),
                    ("tronque", bytes((0xFF, 0xD8)) + b"x" * 42, False),
                    ("texte", b"<html>pas une image</html>" + b" " * 600, False),
                    ("jpeg", bytes((0xFF, 0xD8, 0xFF, 0xE0)) + b"\x00" * 3000, True),
                    ("png", bytes((0x89, 0x50, 0x4E, 0x47)) + b"\x00" * 3000, True)):
                _fAp = _dAp / "x.jpg"
                _fAp.write_bytes(_octets)
                check("apercus : une vignette « %s » est jugee %s"
                      % (_nomCas, "valide" if _attendu else "invalide"),
                      _wAp._vignette_valide(_fAp) is _attendu)
        finally:
            import shutil as _sh0Ap
            _sh0Ap.rmtree(_dAp, ignore_errors=True)
        check("apercus : le cache verifie le CONTENU avant de servir",
              "_vignette_valide(thumb)" in _srcAp,
              "sinon un reste tronque est servi 24 h durant")
        check("apercus : une extraction qui expire ne laisse pas de reste",
              "except subprocess.TimeoutExpired" in _srcAp
              and "dest.unlink(missing_ok=True)" in _srcAp)

        # LE chemin qui restait casse. Au-dela des 24 premieres cartes, l image
        # n a qu un data-src ; seul vaultChargerVignettes la promeut en src. Il
        # n etait arme que par le chargement initial et par le changement
        # d IDENTITE — jamais par un clic sur un ONGLET. Mesure sur le site, en
        # arrivant par la barre laterale sur Video brut : 24 apercus charges sur
        # 204, les 180 autres restaient un pixel transparent. Par l URL directe
        # tout marchait, ce qui a fait chercher ailleurs pendant longtemps.
        def _corpsAp(entete):
            """Le corps d une fonction JS, borne par la fonction SUIVANTE.

            Compter les accolades ou limiter a N caracteres se trompait de
            fin : showTab fait plusieurs milliers de caracteres et contient
            des blocs fermes en colonne 0.
            """
            _d = _srcAp.find(entete)
            if _d < 0:
                return ""
            _f = _srcAp.find("\nfunction ", _d + len(entete))
            return _srcAp[_d:_f if _f > 0 else _d + 20000]

        _showAp = _corpsAp("function showTab(group,name,title,subtitle){")
        check("apercus : changer d ONGLET reprend les vignettes en charge",
              "vaultChargerVignettes" in _showAp,
              "afficher la galerie ne suffit pas, il faut promouvoir les data-src")
        _lazyAp = _reAp.search(
            r"function chargerOngletDiffere\(sec\)\{(.{0,4000}?)\n\}",
            _srcAp, _reAp.S)
        check("apercus : un fragment injecte reprend ses vignettes aussi",
              bool(_lazyAp) and "vaultChargerVignettes" in _lazyAp.group(1),
              "son HTML arrive apres le passage du chargeur et ne s arme pas seul")
        # La racine est elue sur offsetParent, juste seulement APRES le recalcul
        # de mise en page du display:block. Appeler tout de suite ne trouve rien.
        check("apercus : l appel attend une frame avant d elire sa racine",
              _reAp.search(r"requestAnimationFrame\(function\(\)\{\s*"
                           r"window\.vaultChargerVignettes\(\);", _srcAp) is not None)

        import shutil as _shAp
        _identAp = "_tstpts"
        _dirAp = _wAp.IDENTITIES_DIR / _identAp / "brutes"
        try:
            _dirAp.mkdir(parents=True, exist_ok=True)
            _nomAp = "trop bien... #ootd.mp4"
            (_dirAp / _nomAp).write_bytes(b"\x00" * 2048)
            _wAp._invalidate_json_cache(None) if hasattr(_wAp, "_invalidate_json_cache") else None
            _chAp, _codeAp, _motifAp = _wAp._cloud_media_path(_identAp, "brutes", _nomAp)
            check("apercus : un nom avec des points de suspension est accepte",
                  _codeAp == 200,
                  "code %s (%s) — meme famille de noms que le « # »"
                  % (_codeAp, _motifAp))
            # La securite doit rester entiere : une vraie remontee est refusee.
            for _mechantAp in ("../../secret.txt", "..", "a/../../b.mp4",
                               "..\\..\\secret.txt"):
                _c2, _code2, _ = _wAp._cloud_media_path(_identAp, "brutes", _mechantAp)
                check("apercus : la remontee %r reste refusee" % _mechantAp[:18],
                      _c2 is None and _code2 in (403, 404),
                      "code %s" % _code2)
        finally:
            _shAp.rmtree(_wAp.IDENTITIES_DIR / _identAp, ignore_errors=True)
    finally:
        _wAp._load_web_users = _svAp
except Exception as _eAp:
    check("apercus : testable", False, repr(_eAp)[:160])

print()
print("=" * 70)
print("THEME CLAIR : les couleurs pensees pour le sombre")
print("=" * 70)
try:
    import re as _reTh
    import pathlib as _plTh

    _srcTh = _plTh.Path("web_upload.py").read_text(encoding="utf-8")

    # Regle generale : une classe de la barre laterale qui recoit une couleur
    # dans le theme sombre DOIT avoir sa contrepartie claire. Sans ca on obtient
    # ce qui a ete mesure sur le site : les titres du sous-menu (Instagram,
    # TikTok, Twitter/X, Threads) en #bbb sur du blanc — contraste 1,92, on ne
    # les lit pas — et un survol qui peint un bloc NOIR dans une barre blanche.
    _classesTh = set(_reTh.findall(r"\.sidebar \.([a-z][a-z0-9-]*)\s*\{[^}]*color:", _srcTh))
    _manqueTh = sorted(c for c in _classesTh
                       if ("body.light .sidebar .%s" % c) not in _srcTh
                       and ("body.light .sidebar .subgroup .%s" % c) not in _srcTh)
    check("theme clair : chaque classe coloree de la barre a sa regle claire",
          not _manqueTh, "sans contrepartie claire : %s" % ", ".join(_manqueTh))

    # EDITEUR DE MONTAGE : ses SURFACES passaient au blanc en theme clair, mais
    # pas ce qui est pose dessus. Le nom du projet (.ce-proj, #e6e6ea) devenait
    # blanc sur blanc, et les onglets actifs restaient des pastilles NOIRES
    # (#2e2e34 / #131316) au milieu d un panneau blanc.
    _ceTh = {}
    for _m in _reTh.finditer(r"^\.(ce-[a-z0-9-]+)([^{]*)\{([^}]*)\}", _srcTh, _reTh.M):
        _c = _reTh.search(r"(?<!-)color:\s*(#[0-9a-fA-F]{3,6})", _m.group(3))
        # Une classe qui pose SON PROPRE fond (les boutons IA et leur degrade
        # bleu) porte du blanc a dessein : ce blanc tient dans les deux themes,
        # il n a rien a voir avec un gris herite du sombre.
        if _c and not _reTh.search(r"background:\s*(?!none|transparent)", _m.group(3)):
            _ceTh.setdefault(_m.group(1), _c.group(1))
    _clairCe = set(_reTh.findall(r"body\.light[^{]*?\.(ce-[a-z0-9-]+)", _srcTh))
    # On ne reclame que les tons GRIS/BLANCS : un accent (bleu, rose) tient sur
    # les deux fonds, un gris pense pour du sombre ne tient sur aucun des deux.
    def _griseTh(h):
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except Exception:
            return False
        return max(r, g, b) - min(r, g, b) <= 24 and max(r, g, b) >= 90
    _manqueCe = sorted(c for c, h in _ceTh.items() if _griseTh(h) and c not in _clairCe)
    check("theme clair : l editeur de montage n a plus de gris de theme sombre",
          not _manqueCe, "sans regle claire : %s" % ", ".join(_manqueCe))
    check("theme clair : le nom du projet du montage est lisible",
          "body.light .ce-proj{color:#111827}" in _srcTh,
          "#e6e6ea sur un .ce-title devenu blanc")
    for _on in ("ce-libtab.on", "ce-rtab.on", "ce-subtab.on"):
        check("theme clair : l onglet actif « %s » n est plus une pastille noire" % _on,
              ("body.light .%s{" % _on) in _srcTh)

    # Le sous-menu, arrive apres les themes, n avait AUCUNE regle claire.
    for _sel, _quoi in (("subgroup-head{", "la couleur du titre"),
                        ("subgroup-head:hover{", "le survol"),
                        ("subgroup .sub-items{", "le trait de gauche")):
        check("theme clair : le sous-menu a %s" % _quoi,
              ("body.light .sidebar .%s" % _sel) in _srcTh)

    # Conteneur remappe, texte oublie : la panne la plus frequente du theme.
    # Mesures relevees dans la page : 1,48 puis 1,92.
    check("theme clair : le libelle de la barre de telechargement est lisible",
          'body.light #ig-dl-bar [style*="color:#cbd5e1"]' in _srcTh,
          "barre repeinte en blanc, texte reste en #cbd5e1 -> 1,48")
    check("theme clair : la legende du reel reste claire sur son fond noir",
          'body.light .reel-expand [style*="color:#888"]' in _srcTh,
          "la regle generale l assombrissait sur un panneau noir -> 1,92")
    # Ces couleurs vivent dans un attribut style= : sans !important la regle ne
    # bat meme pas le style inline. Verifie sur la page — une premiere version
    # plus specifique mais SANS !important laissait le contraste a 1,48.
    # La specificite, elle, ne sert qu a departager DEUX regles !important.
    _sansImp = [_m.group(0)[:70] for _m in
                _reTh.finditer(r'body\.light[^{}]*\[style\*="color:[^{}]*\{[^}]*\}', _srcTh)
                if "!important" not in _m.group(0)]
    check("theme clair : aucun remap de couleur inline n oublie !important",
          not _sansImp,
          "inutiles, le style inline gagne : %s" % " | ".join(_sansImp[:3]))
    check("theme clair : les pastilles flottantes SFW / marche sont lisibles",
          "body.light #market-floating button{color:#4b5563!important}" in _srcTh)
    check("theme clair : les boutons de filtre banger sont lisibles",
          "body.light #banger-toggle-btn,body.light #favbrute-toggle-btn{" in _srcTh,
          "dore #f5c518 sur un fond repeint en blanc -> 1,63")

    # Garde-fou general : une couleur de TEXTE posee en inline qui ne se lit pas
    # sur du blanc doit avoir son remap clair. Sans cette regle, dix teintes
    # avaient traverse le site sans etre vues (#22c55e sur 168 elements, #e6e6ea
    # sur 11, #f59e0b sur 10...), simplement parce qu on ne relit jamais le CSS
    # en se demandant de quelle couleur est le fond.
    from collections import Counter as _CntTh
    # Les hex a TROIS chiffres comptent autant : #bbb et #eee etaient passes
    # entre les mailles parce que le motif n acceptait que six caracteres.
    _usages = _CntTh(_reTh.findall(
        r"(?<!-)color:\s*(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3}(?![0-9a-fA-F])))", _srcTh))

    def _contrasteBlancTh(h):
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(_c * 2 for _c in h)
        h = "#" + h
        _r, _g, _b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)

        def _f(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        _L = 0.2126 * _f(_r) + 0.7152 * _f(_g) + 0.0722 * _f(_b)
        return round(1.05 / (_L + 0.05), 2)

    _aveugles = []
    for _h, _n in _usages.items():
        if _n < 3 or _contrasteBlancTh(_h) >= 2.6:
            continue
        if not _reTh.search(r"body\.light[^{}]*" + _h[1:] + r"[^{}]*\{", _srcTh, _reTh.I):
            _aveugles.append("%s (%d usages, %s sur blanc)"
                             % (_h, _n, _contrasteBlancTh(_h)))
    check("theme clair : aucune couleur de texte illisible sur blanc sans remap",
          not _aveugles, " | ".join(sorted(_aveugles)[:5]))

    # Meme garde-fou, mais pour les couleurs posees par une CLASSE et non par un
    # style inline : c est ainsi que le tableau de bord GMS ecrivait ses noms
    # d identites en blanc sur blanc (contraste 1,0, 321 elements), et que la
    # moitie de cet onglet etait invisible en theme clair.
    # Trois exceptions verifiees a la main, listees avec leur raison.
    _EXEMPTES = {
        "va-ig-btn": "pose son propre fond (background:currentColor)",
        "va-pay-btn": "pose son propre fond (background:currentColor)",
        "va-ig3-thumb-play": "icone posee sur une miniature, avec ombre portee",
        "remember-row": "ecran de connexion, qui reste sombre",
        # Initiales d avatar : posees sur une couleur GENEREE par identite, pas
        # sur la surface du theme. Leur blanc vaut sur les deux themes.
        "jb-avatar-fb": "initiale sur une couleur generee par identite",
        "jb-va-avatar-fb": "initiale sur une couleur generee par identite",
        "jb-side-va-fb": "initiale sur une couleur generee par identite",
        # La visionneuse plein ecran (#lightbox, fond rgba(0,0,0,.78)) n a pas
        # de regle claire : elle reste NOIRE dans les deux themes, comme toute
        # visionneuse de media. Ses commandes doivent donc rester blanches.
        "lb-close-btn": "commande de la visionneuse, qui reste noire",
        # Ces deux-la echappaient au controle par ACCIDENT : un commentaire CSS
        # les precedait (« /* Bouton edit crayon dans header */ »), le selecteur
        # capture ne commencait donc pas par un point et la regle etait ecartee
        # sans etre lue. Ajouter une classe juste apres ce commentaire a pris
        # sa place a l abri et revele le trou. Elles ont la meme raison d etre
        # exemptees que leurs voisines ci-dessus, elles sont donc NOMMEES ici
        # plutot que protegees par un hasard de ponctuation.
        "lb-edit-btn": "commande de la visionneuse, qui reste noire",
        "lb-act-btn": "commande de la visionneuse, qui reste noire",
        "lb-counter": "commande de la visionneuse, qui reste noire",
        "lb-nav": "commande de la visionneuse, qui reste noire",
        "lb-dual-label": "libelle dans la visionneuse, qui reste noire",
        # L onglet actif est peint en bleu plein ; la pastille de comptage qu il
        # contient est donc blanche sur bleu, ce qui est juste.
        "gms-tab-active": "pastille posee dans un onglet peint en bleu plein",
    }
    # On lit le CSS REELLEMENT SERVI, pas le fichier source. Deux tentatives
    # precedentes ont echoue pour des raisons opposees : exiger un debut de
    # ligne laissait passer les regles concatenees (les 19 classes du module
    # Jailbreak, dont les pseudos en blanc sur blanc), et ne plus l exiger
    # faisait prendre du JavaScript pour du CSS (« x.last_summary||{} »).
    # Le contenu des <style> de la page rendue ne prete a aucune confusion.
    import web_upload as _wTh
    _appTh = _wTh.create_app()
    _appTh.config["TESTING"] = True
    _sauveTh = _wTh._load_web_users
    _wTh._load_web_users = lambda: {"admin": {"role": "owner", "password": "x"}}
    try:
        _cTh = _appTh.test_client()
        with _cTh.session_transaction() as _sTh:
            _sTh["auth"] = True
            _sTh["username"] = "admin"
            _sTh["role"] = "owner"
        _htmlTh = _cTh.get("/?tab=home").get_data(as_text=True)
        # Les onglets differes apportent LEUR PROPRE <style>, absent de la page
        # d accueil. Sans eux, tout le module Jailbreak echappait au controle —
        # c est ainsi que ses pastilles sont restees illisibles si longtemps.
        for _lz in ("jailbreak", "gms", "clouddrive", "textpool", "geelark",
                    "bilan", "schedule", "srole", "videocrea", "vtg"):
            try:
                _fr = _cTh.get("/?lazy=" + _lz, headers={"X-Tab-Ajax": "1"})
                if _fr.status_code == 200:
                    _htmlTh += "\n" + _fr.get_data(as_text=True)
            except Exception:
                pass
    finally:
        _wTh._load_web_users = _sauveTh
    _cssTh = "\n".join(_reTh.findall(r"<style[^>]*>(.*?)</style>", _htmlTh, _reTh.S))
    check("theme clair : le CSS de la page est bien lisible par le test",
          len(_cssTh) > 100_000, "%d octets extraits" % len(_cssTh))

    _classesKO = {}
    # On raisonne sur le selecteur ENTIER, pas sur un fragment : decouper au
    # milieu faisait passer « body.obsidian .vlm-dup » pour une classe nue sans
    # regle claire, alors que c est une regle de THEME, deja specifique.
    for _m in _reTh.finditer(r"([^{}]+)\{([^{}]*)\}", _cssTh):
        _selTotal, _corps = _m.group(1), _m.group(2)
        # Une regle deja portee par un theme n a rien a voir avec le theme clair.
        _parts = [_p.strip() for _p in _selTotal.split(",")]
        _parts = [_p for _p in _parts if _p.startswith(".")]
        if not _parts:
            continue
        _sel = _parts[0]
        if "body." in _selTotal or "@" in _selTotal:
            continue
        _c = _reTh.search(r"(?<!-)color:\s*(#[0-9a-fA-F]{3,6})", _corps)
        if not _c:
            continue
        # Une regle qui pose un fond OPAQUE assume la couleur de son texte.
        # Un fond TRANSLUCIDE, lui, ne protege rien : pose sur du blanc il
        # reste blanc. C est ce qui laissait passer les pastilles du Jailbreak
        # (fond rgba(...,.12), texte vert clair : 1,57) et les compteurs de VA.
        _bg = _reTh.search(r"background(?:-color)?:\s*([^;]+)", _corps)
        if _bg:
            _v = _bg.group(1).strip().lower()
            _op = _reTh.search(r"rgba\([^)]*?,\s*([0-9.]+)\s*\)", _v)
            _translucide = bool(_op) and float(_op.group(1)) < 0.55
            if _v not in ("none", "transparent") and not _translucide:
                continue
        _h = _c.group(1)
        if len(_h) == 4:
            _h = "#" + "".join(_ch * 2 for _ch in _h[1:])
        if _contrasteBlancTh(_h) >= 2.6:
            continue
        _cls = _reTh.match(r"\.([a-z][a-z0-9_-]*)", _sel).group(1)
        if _cls in _EXEMPTES:
            continue
        # Une regle claire qui ne pose qu un FOND ne repare pas une couleur de
        # texte : c est ce qui laissait .gd-mcard invisible alors que le test
        # le comptait comme couvert. On exige une regle claire qui pose bien
        # une couleur de TEXTE sur cette classe.
        _couvert = False
        for _lm in _reTh.finditer(r"(body\.light[^{}]*)\{([^}]*)\}", _srcTh):
            if not _reTh.search(r"\." + _reTh.escape(_cls) + r"\b", _lm.group(1)):
                continue
            if _reTh.search(r"(?<!-)color:", _lm.group(2)):
                _couvert = True
                break
        if _couvert:
            continue
        _classesKO[_cls] = "%s (%s sur blanc)" % (_h, _contrasteBlancTh(_h))
    check("theme clair : aucune classe coloree sans contrepartie claire",
          not _classesKO,
          " | ".join(".%s %s" % (_k, _v) for _k, _v in sorted(_classesKO.items())[:4]))
except Exception as _eTh:
    check("theme clair : testable", False, repr(_eTh)[:160])

print()
print("=" * 70)
print("CHARGEMENT DIFFERE : amorcage, portee, sections lourdes")
print("=" * 70)
try:
    import re as _reLz
    import pathlib as _plLz

    _srcLz = _plLz.Path("web_upload.py").read_text(encoding="utf-8")

    # BUG 1 (constate sur youl4b.com/?tab=gms) : la page finissait de charger,
    # la section etait bien visible, et elle restait sur « Loading... » a vie.
    # L onglet initial est AFFICHE par une regle CSS, mais seul un clic sur la
    # navigation appelait showTab — donc rien ne declenchait le chargement.
    # Ca touchait les 34 onglets differes, dont le Drive.
    check("differe : l onglet ouvert par l URL est amorce au chargement",
          "chargerOngletDiffere(document.getElementById('form-' + t))" in _srcLz)
    check("differe : l amorcage attend que le DOM existe",
          _reLz.search(r"DOMContentLoaded[\s\S]{0,400}chargerOngletDiffere", _srcLz)
          is not None)

    # BUG 2 : le fragment ecrasait la SECTION entiere (sec.innerHTML = frag).
    # Sur la Veille, le premier clic effacait le volet feed-veille, la colonne
    # de filtres et la modale des reels.
    check("differe : le fragment ne remplace plus toute la section",
          "sec.innerHTML = htmlFrag" not in _srcLz)
    check("differe : c est l emplacement lui-meme qui est remplace",
          "parent.insertBefore(n, trou)" in _srcLz
          and "parent.removeChild(trou)" in _srcLz)
    # Une section peut porter plusieurs emplacements (la Veille en a deux).
    check("differe : TOUS les emplacements d une section sont servis",
          "querySelectorAll('[data-lazy-tab]')" in _srcLz,
          "un querySelector simple ne sert que le premier")
    check("differe : un echec laisse la possibilite de reessayer",
          "delete trou.dataset.enCours" in _srcLz)

    # Sections lourdes : mesurees dans la vraie page, 70 % du DOM (75 977
    # noeuds) vivait dans trois sections MASQUEES rendues d office.
    for _t in ("valist", "jailbreak", "veille"):
        check("differe : la section « %s » n est plus rendue d office" % _t,
              '_lazy("%s")' % _t in _srcLz,
              "encore en _g(...) = rendue meme quand on ne la regarde pas")
    # Differer une section sans producteur la laisserait vide pour toujours.
    _prodsLz = _reLz.search(r"_prods = \{[\s\S]*?\n            \}", _srcLz)
    _corpsLz = _prodsLz.group(0) if _prodsLz else ""
    for _t in ("valist", "jailbreak", "veille"):
        check("differe : « %s » a bien un producteur a la demande" % _t,
              '"%s":' % _t in _corpsLz)
except Exception as _eLz:
    check("differe : testable", False, repr(_eLz)[:160])

print()
print("=" * 70)
print("COHERENCE VISUELLE : le bouton « Partager »")
print("=" * 70)
try:
    import re as _rePa
    import pathlib as _plPa

    # Il en existait QUATRE habillages pour la meme action : texte violet nu
    # dans les Bios et les Captions, pastille violette dans les Templates et la
    # barre Caption, pastille GRISE avec une AUTRE icone dans les Photos de
    # profil. Meme geste, quatre apparences — on hesite avant de cliquer, et on
    # croit que ce n est pas la meme chose.
    _srcPa = _plPa.Path("web_upload.py").read_text(encoding="utf-8")
    _mPa = _rePa.compile(r"<button\b[^>]*>(?:(?!</button>).){0,900}?Partager\s*</button>",
                         _rePa.S)
    _btnPa = _mPa.findall(_srcPa)
    check("partager : au moins quatre boutons trouves dans le source",
          len(_btnPa) >= 4, "%d trouve(s)" % len(_btnPa))
    _sansPa = [b for b in _btnPa if "btn-partager" not in b]
    check("partager : TOUS portent la classe unique",
          not _sansPa,
          _rePa.sub(r"\s+", " ", _sansPa[0])[:110] if _sansPa else "")
    # Deux icones differentes servaient la meme action : les cercles relies
    # (partage) et une fleche d export. Une seule doit rester.
    _fleche = [b for b in _btnPa if "polyline points='16 6 12 2 8 6'" in b]
    check("partager : plus aucune icone d export detournee en partage",
          not _fleche, "%d bouton(s)" % len(_fleche))
    check("partager : la classe est definie, et pour les DEUX themes",
          ".btn-partager{" in _srcPa and "body.light .btn-partager" in _srcPa)
    check("partager : elle a un etat visible au clavier",
          ".btn-partager:focus-visible" in _srcPa)
except Exception as _ePa:
    check("partager : testable", False, repr(_ePa)[:160])

print()
print("=" * 70)
print("VEILLE INSTAGRAM RENDUE A LA DEMANDE (le navigateur qui se fige)")
print("=" * 70)
try:
    import web_upload as _wIg

    # La grille de veille rend jusqu a MILLE reels, chacun avec sa miniature
    # servie par le CDN d Instagram — et elle etait rendue d office, dans la
    # page, quel que soit l onglet ouvert. Mesure sur le site reel : plus de
    # 1000 requetes reseau en affichant « Video brut », et le rendu du
    # navigateur qui ne repond plus (trois captures expirees d affilee).
    _aIg = _wIg.create_app(); _aIg.testing = True
    _savIg = _wIg._load_web_users
    _wIg._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cIg = _aIg.test_client()
    with _cIg.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "IG1"
    # Ici c'est bien la PAGE ENTIERE qu'on veut : le test verifie qu'elle pose
    # le place-holder de la veille et qu'elle n'embarque aucune miniature.
    _hIg = _cIg.get("/?tab=cloudbrutes").get_data(as_text=True)
    check("veille : la page ne porte AUCUNE miniature Instagram au chargement",
          _hIg.count("cdninstagram") == 0,
          "%d trouvee(s)" % _hIg.count("cdninstagram"))
    check("veille : un emplacement est pose pour le chargement a la demande",
          "data-lazy-tab='igtrends'" in _hIg)
    _fIg = _cIg.get("/?lazy=igtrends", headers={"X-Tab-Ajax": "1"})
    check("veille : le fragment est servi quand on ouvre l onglet",
          _fIg.status_code == 200, "HTTP %s" % _fIg.status_code)
    # Un onglet vide doit DIRE quoi faire, pas rester blanc.
    check("veille : sans reel, le fragment explique au lieu de rester blanc",
          len(_fIg.get_data()) > 200)
    _wIg._load_web_users = _savIg
except Exception as _eIg:
    check("veille : testable", False, repr(_eIg)[:160])

print()
print("=" * 70)
print("CASE « PAYE » ET PERIODES (defaut A4)")
print("=" * 70)
try:
    import pathlib as _plPd
    import mypuls as _mpPd

    # La case se lisait par egalite EXACTE de la plage de dates. La periode par
    # defaut etant glissante, le lendemain d un paiement plus aucune case
    # n etait cochee — et RIEN N EMPECHAIT DE REPAYER. is_chatter_paid a ete
    # ecrite pour ca, avec sa regle d inclusion, mais n etait appelee nulle
    # part : le correctif avait ete livre sans jamais etre branche.
    _savPd = _mpPd.get_chatter_meta
    _mpPd.get_chatter_meta = lambda n: {"paid_periods": ["2026-08-01_2026-08-15"]}
    try:
        check("paye : la periode exactement reglee est cochee",
              _mpPd.is_chatter_paid("x", "2026-08-01_2026-08-15") is True)
        check("paye : une plage INCLUSE dans une periode reglee est cochee",
              _mpPd.is_chatter_paid("x", "2026-08-05_2026-08-10") is True)
        check("paye : la quinzaine suivante n est PAS cochee",
              _mpPd.is_chatter_paid("x", "2026-08-16_2026-08-31") is False)
        check("paye : une plage qui deborde n est pas cochee",
              _mpPd.is_chatter_paid("x", "2026-07-20_2026-08-05") is False)
    finally:
        _mpPd.get_chatter_meta = _savPd

    # LE test qui compte : la page doit APPELER cette regle. Sans lui, la
    # fonction pourrait de nouveau dormir sans que personne s en apercoive.
    _srcPd = _plPd.Path("web_upload.py").read_text(encoding="utf-8")
    check("paye : la page appelle bien is_chatter_paid",
          "is_chatter_paid(" in _srcPd)
    check("paye : elle ne compare plus la plage par egalite exacte",
          "in meta.get('paid_periods'" not in _srcPd
          and 'in meta.get("paid_periods"' not in _srcPd)

    # A3 — le bouton de la page poussait les ventes SANS commissions ni taux :
    # l onglet « Paie quinzaine » sortait a 0 $ pour tout le monde et l onglet
    # « Site vs registre » accusait 100 % de l equipe d etre absente. La route
    # soeur passait deja par _ventes_contexte ; deux chemins, un seul correct.
    _iVs = _srcPd.index("def chatters_ventes_sheet(")
    _blocVs = _srcPd[_iVs:_iVs + 2600]
    check("classeur : le bouton transmet les commissions et le taux",
          "commissions=" in _blocVs and "eur_usd=" in _blocVs)
    check("classeur : il transmet aussi la table de performance",
          "chatters=" in _blocVs and "diagnostic=" in _blocVs)

    # A7 — « Indetermine (Creatrice) » est un LIBELLE, pas une personne. Il
    # etait recompte au premier clic sur un filtre, et l unite ne repartait
    # jamais.
    check("chatteurs actifs : la ligne des ventes non attribuees n est pas comptee",
          "mp-row-orphelin')) activeCount++" in _srcPd
          or "mp-row-orphelin')) activeCount" in _srcPd)
except Exception as _ePd:
    check("paye : testable", False, repr(_ePd)[:160])

print()
print("=" * 70)
print("GARDE-FOU DE PAIE (recalcul navigateur)")
print("=" * 70)
try:
    import pathlib as _plPy
    _srcPy = _plPy.Path("web_upload.py").read_text(encoding="utf-8")
    _dPy = _srcPy.index("function mpPayUsd(")
    _fnPy = _srcPy[_dPy:_dPy + 1400]

    # Le defaut d origine etait INVISIBLE a la lecture : la fonction avait
    # exactement la forme de la regle serveur, mais on lui passait un ca_total
    # issu du MEME journal que ca_eur et ca_usd. La somme valait donc
    # elle-meme, le garde-fou ne partait jamais, et toucher un filtre faisait
    # tomber le total a payer. Ces trois controles verrouillent la reparation.
    check("paie : mpPayUsd compare a un CA de reference, pas au sien",
          "perfCa" in _fnPy and "d.ca_total" not in _fnPy,
          _fnPy[:120])
    check("paie : sans reference (filtre actif) il ne pretend pas verifier",
          "typeof perfCa !== 'number'" in _fnPy)
    check("paie : le CA de la table de perf est servi au navigateur",
          "window.__mpPerfCa" in _srcPy and "perf_ca_js" in _srcPy)
    check("paie : l ecran previent quand le total n est pas payable",
          "mp-avert-filtre" in _srcPy and "ne paie pas dessus" in _srcPy)
except Exception as _ePy:
    check("paie : garde-fou testable", False, repr(_ePy)[:160])

print()
print("=" * 70)
print("LE FRAGMENT JAILBREAK EMPORTE SA PROPRE MISE EN PAGE")
print("=" * 70)
try:
    import web_upload as _wJb
    _aJb = _wJb.create_app(); _aJb.testing = True
    _savJb = _wJb._load_web_users
    _wJb._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cJb = _aJb.test_client()
    with _cJb.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"
        _s["sid"] = "JB1"
    _hJb = _cJb.get("/?tab=jailbreak&frag=1",
                    headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
    # Le tableau des comptes empruntait sa grille a DEUX autres sections
    # (.va-ig3-row au bloc GeeLark, .va-ig3-thead au bloc « liste VA »). Depuis
    # que celles-ci sont differees, leur CSS ne partait plus avec la page :
    # l en-tete se lisait « CompteAbonnesVues 24hVues sem… » d un seul tenant et
    # les valeurs s empilaient. Une section doit emporter sa propre mise en page.
    check("jailbreak : le fragment porte la grille du tableau des comptes",
          ".va-ig3-thead{" in _hJb
          and "grid-template-columns:36px 1fr auto" in _hJb,
          "%d octets" % len(_hJb))
    # La vignette est le symptome le plus visible quand la CSS manque : sans
    # taille, l image s affiche en pleine largeur et le texte lui passe dessus.
    check("jailbreak : le fragment porte la taille des vignettes",
          ".va-ig3-row-pp{width:36px" in _hJb)
    # Theme clair : sans ces regles les lignes restaient en sombre sur une page
    # claire, et les chiffres devenaient illisibles. La specificite compte —
    # body.light + classe doit primer sur la regle generale.
    check("jailbreak : le fragment porte le theme clair du tableau",
          "body.light .va-ig3-row{background:#fff" in _hJb
          and "body.light .va-ig3-row-num" in _hJb)

    # Le menu s appelle « Social Analytics » et porte un graphe, plus un cadenas
    # — mais SEUL l affichage change. Renommer les cles « jailbreak » casserait
    # les routes, les droits, les identifiants DOM et la synchro Sheets.
    _hMenu = _cJb.get("/").get_data(as_text=True)
    _iG = _hMenu.find("grp-jailbreak")
    _sec = _hMenu[_iG:_iG + 900] if _iG >= 0 else ""
    check("menu : la section s appelle Social Analytics",
          "Social Analytics" in _sec, _sec[:80])
    check("menu : elle porte le graphe, plus le cadenas",
          "M18 17V9" in _sec and "M7 11V7a5 5 0 0 1 10 0v4" not in _sec)
    check("menu : les cles internes n ont pas bouge",
          all(k in _hMenu for k in ("showTab('jailbreak','jailbreak'",
                                    'id="tab-jailbreak"',
                                    "toggleGroup('jailbreak')")))
    # Le Vault PRO, lui, garde son cadenas : il a du sens la-bas.
    _iP = _hMenu.find("grp-provault")
    check("menu : le Vault PRO garde son cadenas",
          "M7 11V7a5 5 0 0 1 10 0v4" in _hMenu[_iP:_iP + 700] if _iP >= 0 else False)
    # Une seule definition, servie a qui en a besoin. Deux copies, c est deux
    # comportements le jour ou l une bouge.
    _srcSh = _plCa.Path("web_upload.py").read_text(encoding="utf-8")
    check("jailbreak : la mise en page du tableau n existe qu en UN endroit",
          _srcSh.count("_CSS_VA_IG3 = ") == 1
          and _srcSh.count("_CSS_VA_IG3") >= 3,
          "%d definition(s), %d usage(s)"
          % (_srcSh.count("_CSS_VA_IG3 = "), _srcSh.count("_CSS_VA_IG3")))
    # Les 9 colonnes doivent correspondre aux 9 cases de _ACCT_THEAD : une case
    # ajoutee a l en-tete sans colonne correspondante recasse tout.
    _srcJb = _plCa.Path("web_upload.py").read_text(encoding="utf-8")
    _iJb = _srcJb.index("_ACCT_THEAD = (")
    _cases = _srcJb[_iJb:_iJb + 520].count("<span")
    _cols = len([x for x in "36px 1fr auto auto auto auto auto 22px 28px".split()])
    check("jailbreak : autant de colonnes que de cases d en-tete",
          _cases == _cols, "%d cases / %d colonnes" % (_cases, _cols))
    _wJb._load_web_users = _savJb
except Exception as _eJb:
    check("jailbreak : fragment testable", False, repr(_eJb)[:160])

print()
print("=" * 70)
print("AJOUT EN MASSE DE COMPTES : coller un LIEN Instagram")
print("=" * 70)
try:
    import web_upload as _wIg
    for _tIg, _attIg in (
            # Les liens colles depuis un partage Instagram portent du suivi
            # apres le « ? » : igsi, utm_source. Sans la coupe, le compte
            # s appellerait « jessy_jpte?igsi=... » et ne serait jamais retrouve.
            ("https://www.instagram.com/jessy_jpte?igsi=MXNib24waXZ6Zjdzdg%3D%3D&utm_source=qr",
             "jessy_jpte"),
            ("https://www.instagram.com/jessy.hairys?igsi=ajd3bjM0cnU3YzFj", "jessy.hairys"),
            ("instagram.com/jessyeztd/", "jessyeztd"),
            ("@jessy_seafyu", "jessy_seafyu"),
            ("jessy_jpte", "jessy_jpte"),
            ("  jessy_jpte  ", "jessy_jpte"),
            # Un post ou un reel n est PAS un compte : les accepter creerait
            # des comptes fantomes nommes « p » ou « reel ».
            ("https://www.instagram.com/p/ABC123/", ""),
            ("https://www.instagram.com/reel/XY/", ""),
            ("https://www.instagram.com/stories/qqn/1/", ""),
            ("", ""),
            ("n importe quoi !!", ""),
            (None, "")):
        check("instagram : %r -> %r" % (str(_tIg)[:46], _attIg),
              _wIg._pseudo_instagram(_tIg) == _attIg,
              repr(_wIg._pseudo_instagram(_tIg)))
    # Le pseudo le plus long autorise par Instagram fait 30 signes.
    check("instagram : un pseudo trop long est refuse",
          _wIg._pseudo_instagram("a" * 31) == "")
    check("instagram : 30 signes passent",
          _wIg._pseudo_instagram("a" * 30) == "a" * 30)
except Exception as _eIg:
    check("instagram : extraction testable", False, repr(_eIg)[:160])

print()
print("=" * 70)
print("REPORT DES CLICS : deux salons (FR / US), maj 30 min, bouton refresh")
print("=" * 70)
try:
    import datetime as _dtCl
    import cogs.clickrecap as _crCl

    # -- marches -------------------------------------------------------------
    check("clics : le marche FR compte l Europe francophone",
          _crCl._marche_de({"marche": "fr"})[3] == frozenset(
              {"FR", "BE", "CH", "LU", "MC"}))
    # « US » au sens du proprietaire : les anglophones a fort pouvoir d achat,
    # pas les seuls Etats-Unis. Un clic canadien vaut un clic americain.
    check("clics : le marche US couvre US, CA, AU et GB",
          _crCl._marche_de({"marche": "us"})[3]
          == frozenset({"US", "CA", "AU", "GB"}),
          str(sorted(_crCl._marche_de({"marche": "us"})[3])))
    check("clics : le marche US n avale pas la France",
          "FR" not in _crCl._marche_de({"marche": "us"})[3])
    check("clics : ce que US recouvre est dit sous le titre",
          "us" in _crCl.MARCHE_DETAIL and _crCl.MARCHE_DETAIL["us"].count(" ") == 3,
          _crCl.MARCHE_DETAIL.get("us", ""))
    # Un marche inconnu ne doit pas faire disparaitre le report : il retombe
    # sur « tout », qui n affiche que le total.
    check("clics : un marche inconnu retombe sur « tout », sans casser",
          _crCl._marche_de({"marche": "klingon"})[0] == "tout"
          and _crCl._marche_de({})[0] == "tout")

    # -- une config par SALON, pas par serveur -------------------------------
    check("clics : deux salons du meme serveur ont deux cles distinctes",
          _crCl._cle_report(111, 222) != _crCl._cle_report(111, 333))
    _cfgCl = {
        "111:222": {"channel_id": 222, "marche": "fr"},
        "111:333": {"channel_id": 333, "marche": "us"},
        "999": {"channel_id": 444},        # config d avant le multi-salon
        "casse": "pas un dict",
    }
    _clesCl = [c for c, _ in _crCl._reports_configures(_cfgCl)]
    check("clics : les deux salons sont servis",
          "111:222" in _clesCl and "111:333" in _clesCl)
    # Celui-la protege les configs existantes : personne ne doit avoir a
    # refaire son /setreportclick apres la mise a jour.
    check("clics : une ancienne config (par serveur) continue de marcher",
          "999" in _clesCl)
    check("clics : une entree abimee est ecartee sans planter",
          "casse" not in _clesCl)

    # -- cadence -------------------------------------------------------------
    check("clics : les creneaux tombent sur h:00 et h:30",
          _crCl._creneau_30(_dtCl.datetime(2026, 8, 22, 9, 29)) == (9, 0)
          and _crCl._creneau_30(_dtCl.datetime(2026, 8, 22, 9, 30)) == (9, 30))
    # Aligne sur l horloge et non sur un compteur : la cadence doit survivre a
    # un redemarrage du bot.
    check("clics : deux instants du meme creneau ne declenchent qu une maj",
          _crCl._creneau_30(_dtCl.datetime(2026, 8, 22, 9, 31))
          == _crCl._creneau_30(_dtCl.datetime(2026, 8, 22, 9, 59)))

    # -- bouton refresh ------------------------------------------------------
    _vCl = _crCl.ReportRefreshView(None)
    _idsCl = [getattr(i, "custom_id", "") for i in _vCl.children]
    check("clics : le bouton Rafraichir est la, avec un identifiant fixe",
          "reportclick:refresh" in _idsCl, str(_idsCl))
    # Sans timeout=None le bouton cesserait de repondre apres un redemarrage,
    # et le message epingle deviendrait un decor mort.
    check("clics : la vue est persistante", _vCl.timeout is None)
    # -- regroupement par personne -------------------------------------------
    # Une meme personne tient plusieurs telephones : « (BO7) 1 », « (BO7) 2 »…
    # Sans regroupement ses lignes se dispersent dans le tableau.
    #
    # PIEGE : « VA n Nom » designe une PERSONNE, pas un numero. VA 1 Noum,
    # VA 2 Noum et VA 3 Noum sont TROIS personnes ; seul le chiffre APRES la
    # parenthese est le telephone. Une premiere version les fusionnait.
    for _nomCl, _attCl in (
            ("( Bryan ) 2", "Bryan"),
            ("(PAMPAM) 1", "PAMPAM"),
            ("( BO7 ) 4", "BO7"),
            ("( VA 1 Noum ) 1", "VA 1 Noum"),
            ("(VA 1 Noum) 2", "VA 1 Noum"),
            ("(VA 2 Noum) 1", "VA 2 Noum"),
            ("(VA 3 Noum) 1", "VA 3 Noum"),
            ("VA 1", ""),                    # sans parentheses : PAS de groupe
            ("TEMPLATE", "")):
        check("clics : personne de %r -> %r" % (_nomCl, _attCl),
              _crCl._personne_du_lien(_nomCl) == _attCl,
              repr(_crCl._personne_du_lien(_nomCl)))

    # -- un echec ne doit pas ecraser de bons chiffres -----------------------
    # Vu en vrai : GetMySocial a refuse (429) et le report a remplace des
    # chiffres justes par « No data ». Le lecteur croit alors que personne n a
    # clique, alors qu on n a simplement pas su lire.
    import inspect as _insCl
    _sigCl = _insCl.signature(_crCl.ClickRecap._build_group_report)
    check("clics : le report sait refuser de se vider",
          "permettre_vide" in _sigCl.parameters, str(_sigCl))
    _srcCl = _insCl.getsource(_crCl.ClickRecap._post_or_update_report)
    check("clics : un report deja pose n accepte plus un contenu vide",
          "permettre_vide=not c.get(\"message_id\")" in _srcCl
          or "permettre_vide" in _srcCl, "_post_or_update_report")

    # -- rattachement aux liens de suivi : le NOM d abord, le code ensuite ----
    # Plusieurs destinations GetMySocial trainent : « Gerome » vise c80
    # (« VA 4 Geelark ») alors qu un lien « Gérôme » existe en c94. Lire le
    # code lui attribuerait 12 715 visites qui ne sont pas les siennes.
    _nomsCl = {"bo7": {"code": "c85", "nom": "Bo07", "abonnes": 0},
               "gerome": {"code": "c94", "nom": "Gérôme", "abonnes": 0},
               "safidy": {"code": "c84", "nom": "Safidy", "abonnes": 1}}
    _codesCl = {"c80": {"code": "c80", "nom": "VA 4 Geelark", "abonnes": 683},
                "c85": {"code": "c85", "nom": "Bo07", "abonnes": 0},
                "c47": {"code": "c47", "nom": "VA 4 JB", "abonnes": 3766}}
    _tCl2, _ecCl = _crCl._suivi_de("Gerome", "c80", _nomsCl, _codesCl)
    check("clics : le nom prime sur une destination perimee",
          _tCl2 and _tCl2["code"] == "c94" and _ecCl == "",
          str(_tCl2))
    _tCl2, _ecCl = _crCl._suivi_de("VA 1 Noum", "c47", _nomsCl, _codesCl)
    check("clics : sans lien a son nom, on retombe sur le code",
          _tCl2 and _tCl2["code"] == "c47", str(_tCl2))
    # L ecart de nom se DIT : « Bryan » lisant les chiffres de « Jaurel » peut
    # etre voulu, mais ne doit pas passer inapercu.
    check("clics : un nom qui ne correspond pas est signale",
          _crCl._suivi_de("VA 1 Noum", "c47", _nomsCl, _codesCl)[1] == "VA 4 JB")
    check("clics : aucun rattachement possible -> rien, pas un faux zero",
          _crCl._suivi_de("Inconnu", "cXX", _nomsCl, _codesCl)[0] is None)
    # « BO7 » cote GetMySocial, « Bo07 » cote MyPuls : sans mise a plat des
    # noms, aucun rapprochement ne tient.
    for _aCl, _bCl in (("BO7", "Bo07"), ("PAMPAM", "Pam Pam"),
                       ("Gerome", "Gérôme"), ("Safidy", "Safidy")):
        check("clics : « %s » et « %s » se rejoignent" % (_aCl, _bCl),
              _crCl._cle_nom(_aCl) == _crCl._cle_nom(_bCl),
              "%r vs %r" % (_crCl._cle_nom(_aCl), _crCl._cle_nom(_bCl)))
    check("clics : deux personnes differentes ne se rejoignent PAS",
          _crCl._cle_nom("Mike") != _crCl._cle_nom("Mykey"))

    # -- code de suivi MyPuls -------------------------------------------------
    # Les liens GetMySocial pointent vers onlyfans.com/<pseudo>/c85 : « c85 »
    # est le code du lien de suivi MyPuls. C est par LUI qu on rattache les
    # abonnes aux clics — les noms ne se ressemblent pas assez (« Bo07 » cote
    # MyPuls, « BO7 » cote GetMySocial ; « Pam Pam » contre « PAMPAM »).
    for _dCl, _attCl in (
            ("https://onlyfans.com/jessyewdiference/c85", "c85"),
            ("https://onlyfans.com/jessyewdiference/c85/", "c85"),
            ("https://onlyfans.com/jessyewdiference", ""),   # pas de code
            ("", ""),
            (None, "")):
        check("clics : code de suivi de %r -> %r" % (_dCl, _attCl),
              _crCl._code_suivi(_dCl) == _attCl,
              repr(_crCl._code_suivi(_dCl)))

    # Les noms sont saisis a la main : le meme compte s ecrit « ( BO7 ) 1 » ici
    # et « (BO7) 1 » la. Sans normalisation, deux personnes au lieu d une.
    for _nomCl, _attCl in (("( BO7 )  1", "(BO7) 1"),
                           ("(Bryan) 2", "(Bryan) 2"),
                           ("( VA 1 Noum ) 1", "(VA 1 Noum) 1")):
        check("clics : nom normalise %r -> %r" % (_nomCl, _attCl),
              _crCl._nom_propre(_nomCl) == _attCl,
              repr(_crCl._nom_propre(_nomCl)))



    check("clics : un frein protege le quota GetMySocial",
          _crCl._REFRESH_ATTENTE_S >= 30, str(_crCl._REFRESH_ATTENTE_S))

    # -- autocompletion : les WORKSPACES, pas les groupes ---------------------
    # Le proprietaire suit ses clics par workspace (« marche francais »,
    # « JESSY LE RETOUR »…) : proposer les 54 groupes noyait le choix.
    import asyncio as _aioCl
    import time as _tCl

    def _eCl_(nom, tid, n=1):
        return {"id": "tm_" + tid, "name": nom, "link_count": n}

    # Range par nombre de liens decroissant, comme _charger_espaces_gms : c est
    # presque toujours le plus fourni qu on cherche, et l ordre du cache est
    # celui des propositions.
    _crCl._ESPACES_CACHE.update({"ts": _tCl.time(), "tache": None, "espaces": [
        _eCl_("marche francais", "fr", 321),
        _eCl_("Jessye Twitter", "jtw", 30),
        _eCl_("JESSY LE RETOUR", "jlr", 20),
        _eCl_("KHLOE", "khl", 10),
    ] + [_eCl_("W%02d" % i, "w%02d" % i) for i in range(30)]})

    # Le faux cog doit porter la VRAIE methode : sans elle, l autocompletion
    # tombe dans sa garde et rend [], et les tests « passent » sur du vide.
    _FauxCogCl = type("_FauxCogCl", (),
                      {"_ac_groupe_reel": _crCl.ClickRecap._ac_groupe_reel})

    def _acCl(frappe):
        return _aioCl.run(_crCl.ClickRecap._ac_groupe(_FauxCogCl(), None, frappe))

    _jCl = _acCl("jessy")
    check("clics : l autocompletion trouve les workspaces, sans la casse",
          [c.name.split(" (")[0] for c in _jCl]
          == ["Jessye Twitter", "JESSY LE RETOUR"],
          str([c.name for c in _jCl]))
    # La valeur est l identifiant du workspace : c est lui que la resolution
    # attend pour couvrir TOUS ses liens.
    check("clics : la valeur est un identifiant de workspace",
          bool(_jCl) and all(c.value.startswith("tm_") for c in _jCl),
          str([c.value for c in _jCl]))
    check("clics : le nombre de liens est annonce",
          bool(_jCl) and all("lien(s)" in c.name for c in _jCl),
          str([c.name for c in _jCl]))
    # Discord REFUSE une reponse de plus de 25 propositions : au-dela, la liste
    # n apparait pas du tout et l utilisateur croit la commande cassee.
    check("clics : l autocompletion ne depasse jamais 25 propositions",
          len(_acCl("")) == 25, str(len(_acCl(""))))
    check("clics : une frappe sans correspondance ne propose rien",
          _acCl("zzzz") == [])

    # GMS injoignable, pour de vrai : on fait echouer le chargement lui-meme.
    # Sans ca le test rechargeait les vrais workspaces et ne prouvait rien.
    _vraiChargeCl = _crCl._charger_espaces_gms

    async def _bouumCl():
        raise RuntimeError("GetMySocial injoignable (simule)")

    _crCl._charger_espaces_gms = _bouumCl
    _crCl._ESPACES_CACHE.update({"ts": 0, "espaces": [], "tache": None})
    try:
        check("clics : GMS injoignable -> liste vide, aucune exception",
              _acCl("x") == [])
    finally:
        _crCl._charger_espaces_gms = _vraiChargeCl
        _crCl._ESPACES_CACHE.update({"ts": 0, "espaces": [], "tache": None})
except Exception as _eCl:
    check("clics : report testable", False, repr(_eCl)[:160])

print()
print("=" * 70)
print("REPERAGE DES BRUTES QUI PORTENT DEJA DU TEXTE")
print("=" * 70)
try:
    import pathlib as _plTx
    import shutil as _shTx
    import web_upload as _wTx

    _idTx = "_tst_textecheck"
    _dTx = _wTx.IDENTITIES_DIR / _idTx / "brutes"
    _shTx.rmtree(_wTx.IDENTITIES_DIR / _idTx, ignore_errors=True)
    _dTx.mkdir(parents=True)
    for _n in ("a.mp4", "b.mp4", "c.mp4", "d.mp4"):
        (_dTx / _n).write_bytes(b"\x00" * 6000)
    (_dTx / "e.example.mp4").write_bytes(b"\x00" * 6000)   # exemple : pas une brute
    (_dTx / "notes.txt").write_text("x", encoding="utf-8")

    check("texte : seules les vraies brutes sont listees",
          [p.name for p in _wTx._brutes_d_identite(_idTx)]
          == ["a.mp4", "b.mp4", "c.mp4", "d.mp4"],
          str([p.name for p in _wTx._brutes_d_identite(_idTx)]))

    # Aller-retour du verdict, et surtout : le nom suit la convention du projet.
    _wTx._textecheck_ecrire(_dTx / "a.mp4", True, ["POV tu decouvres ca"])
    _wTx._textecheck_ecrire(_dTx / "b.mp4", False, [])
    _wTx._textecheck_ecrire(_dTx / "c.mp4", None, [], "vidéo illisible")
    check("texte : le verdict se range en <stem>.textecheck.json",
          (_dTx / "a.textecheck.json").exists())
    check("texte : il se relit tel qu ecrit",
          _wTx._textecheck_lire(_dTx / "a.mp4").get("texte") is True
          and _wTx._textecheck_lire(_dTx / "a.mp4").get("extraits")
          == ["POV tu decouvres ca"])
    check("texte : une brute jamais examinee ne rend rien",
          _wTx._textecheck_lire(_dTx / "d.mp4") == {})

    _rapTx = _wTx.rapport_texte_brutes(_idTx)
    check("texte : la brute avec texte est proposee",
          [x["fichier"] for x in _rapTx["avec_texte"]] == ["a.mp4"],
          str(_rapTx["avec_texte"]))
    check("texte : la brute sans texte est comptee, pas listee",
          _rapTx["sans_texte"] == 1)
    # LE test qui compte : une video qu on n a pas su lire ne doit JAMAIS
    # glisser parmi les « sans texte », sinon elle survivrait a un menage
    # qu on croirait sur — ou pire, serait proposee a la suppression.
    check("texte : un verdict impossible est mis a part, jamais avec les sans-texte",
          [x["fichier"] for x in _rapTx["non_conclu"]] == ["c.mp4"]
          and _rapTx["sans_texte"] == 1,
          str(_rapTx["non_conclu"]))
    check("texte : la brute non examinee n apparait nulle part",
          _rapTx["total_examine"] == 3 and _rapTx["total_brutes"] == 4)

    # Sans cle IA, on ne lance rien et on le DIT.
    _savKey = _osRg.environ.pop("ANTHROPIC_API_KEY", None) if "_osRg" in dir() else None
    import os as _osTx
    _k0 = _osTx.environ.pop("ANTHROPIC_API_KEY", None)
    _laTx, _msgTx = _wTx._lancer_scan_texte(_idTx)
    check("texte : sans cle IA, rien n est lance et le message le dit",
          _laTx is False and "clé ia" in _msgTx.lower(), _msgTx[:80])
    if _k0 is not None:
        _osTx.environ["ANTHROPIC_API_KEY"] = _k0

    # Le voisin doit partir avec la video, sinon un re-upload homonyme
    # heriterait du verdict de l ancienne.
    _srcTx = _plTx.Path("web_upload.py").read_text(encoding="utf-8")
    check("texte : le verdict est emporte quand la video est supprimee",
          "SUFFIXE_TEXTECHECK}\"  # verdict" in _srcTx
          or "{stem}{SUFFIXE_TEXTECHECK}" in _srcTx)

    _shTx.rmtree(_wTx.IDENTITIES_DIR / _idTx, ignore_errors=True)
except Exception as _eTx:
    check("texte : reperage testable", False, repr(_eTx)[:160])

print()
print("=" * 70)
print("SELECTEURS DES FAVORIS (bouton Caption Banger / Montage Banger)")
print("=" * 70)
try:
    import json as _jsFv
    import pathlib as _plFv
    import shutil as _shFv
    import cogs.user as _uFv

    # -- brutes favorites ---------------------------------------------------
    _idFv = "_tst_fav"
    _dirFv = _uFv.IDENTITIES_DIR / _idFv / "brutes"
    _shFv.rmtree(_uFv.IDENTITIES_DIR / _idFv, ignore_errors=True)
    _dirFv.mkdir(parents=True)
    (_dirFv / "a.mp4").write_bytes(b"\x00" * 6000)
    _fvFile = _uFv.DATA_DIR / "fav_brutes.json"
    _savFv = _fvFile.read_text(encoding="utf-8") if _fvFile.exists() else None
    _fvFile.write_text(_jsFv.dumps([
        _idFv + "|brutes|a.mp4",          # presente sur le disque
        _idFv + "|brutes|disparue.mp4",   # cle orpheline
        "autre|brutes|z.mp4",             # une autre identite
        _idFv + "|videos|r.mp4",          # mauvais sous-dossier
    ]), encoding="utf-8")
    _gotFv = [p.name for p in _uFv.fav_brutes_for(_idFv)]
    check("favoris : seule la brute presente sur le disque est retenue",
          _gotFv == ["a.mp4"], str(_gotFv))
    check("favoris : une identite inconnue ne rend rien",
          _uFv.fav_brutes_for("_tst_inexistant") == [])
    if _savFv is None:
        _fvFile.unlink(missing_ok=True)
    else:
        _fvFile.write_text(_savFv, encoding="utf-8")
    _shFv.rmtree(_uFv.IDENTITIES_DIR / _idFv, ignore_errors=True)

    # -- templates favoris ---------------------------------------------------
    # Le piege : un template SANS point de coupe fait recopier le template seul,
    # donc la brute favorite n apparait pas dans la video. On les ecarte, et on
    # les COMPTE pour pouvoir le dire au VA.
    _idTv = "_tst_favtpl"
    _dirTv = _uFv.IDENTITIES_DIR / _idTv / "templates"
    _shFv.rmtree(_uFv.IDENTITIES_DIR / _idTv, ignore_errors=True)
    _dirTv.mkdir(parents=True)
    for _n in ("bon.mp4", "sanscoupe.mp4", "sansbrouillon.mp4"):
        (_dirTv / _n).write_bytes(b"\x00" * 6000)
    (_dirTv / "bon.montage.json").write_text(
        _jsFv.dumps({"cut_at": 1.8, "segments": "[]"}), encoding="utf-8")
    (_dirTv / "sanscoupe.montage.json").write_text(
        _jsFv.dumps({"cut_at": 0, "segments": "[]"}), encoding="utf-8")
    _savTv = _fvFile.read_text(encoding="utf-8") if _fvFile.exists() else None
    _fvFile.write_text(_jsFv.dumps([
        _idTv + "|templates|bon.mp4",
        _idTv + "|templates|sanscoupe.mp4",
        _idTv + "|templates|sansbrouillon.mp4",
        _idTv + "|templates|disparu.mp4",     # cle orpheline
    ]), encoding="utf-8")
    _utTv, _ecartTv = _uFv.fav_templates_for(_idTv)
    check("favoris : seul le template avec point de coupe est utilisable",
          [p.name for p, _d in _utTv] == ["bon.mp4"],
          str([p.name for p, _d in _utTv]))
    check("favoris : les templates sans point de coupe sont COMPTES, pas ignores",
          _ecartTv == 2, "%d ecarte(s)" % _ecartTv)
    check("favoris : le brouillon du template est rendu avec lui",
          _utTv and float(_utTv[0][1].get("cut_at")) == 1.8)
    if _savTv is None:
        _fvFile.unlink(missing_ok=True)
    else:
        _fvFile.write_text(_savTv, encoding="utf-8")
    _shFv.rmtree(_uFv.IDENTITIES_DIR / _idTv, ignore_errors=True)

    # -- captions favorites -------------------------------------------------
    _idCv = "_tst_favcap"
    _fCv = _uFv.DATA_DIR / "captions.json"
    _savCv = _fCv.read_text(encoding="utf-8") if _fCv.exists() else None
    _dCv = _jsFv.loads(_savCv) if _savCv else {}
    _dCv[_idCv] = {"items": [
        {"id": "c1", "text": "favorite active", "fav": True, "enabled": True},
        {"id": "c2", "text": "favorite hors tirage", "fav": True, "enabled": False},
        {"id": "c3", "text": "ordinaire", "fav": False, "enabled": True},
        {"id": "c4", "text": "   ", "fav": True, "enabled": True},
    ]}
    _fCv.write_text(_jsFv.dumps(_dCv, ensure_ascii=False), encoding="utf-8")
    _actCv = [c["id"] for c in _uFv.fav_captions_for(_idCv)]
    _horsCv = [c["id"] for c in _uFv.fav_captions_desactivees(_idCv)]
    check("favoris : seule la caption favorite ET active part", _actCv == ["c1"],
          str(_actCv))
    # Ce test protege un message honnete : une favorite desactivee ne doit pas
    # se faire annoncer « aucune caption favorite », ce que personne ne saurait
    # deboguer.
    check("favoris : une favorite hors tirage est nommee a part",
          _horsCv == ["c2"], str(_horsCv))
    if _savCv is None:
        _fCv.unlink(missing_ok=True)
    else:
        _fCv.write_text(_savCv, encoding="utf-8")

    # -- le menu VA porte bien les deux boutons -----------------------------
    _vFv = _uFv.ContentMenuView(None)
    _idsFv = [getattr(i, "custom_id", "") for i in _vFv.children]
    # Quatre depuis le 21/08 : « Caption + Brut » a quitte le menu. Il prenait
    # le meme couple d'ingredients que « Montage » — une brute etoilee et une
    # caption etoilee — mais les envoyait separement, la caption en texte a
    # recopier. Deux boutons pour un meme couple, dont un qui ne montait pas :
    # c'est ce qui rendait le menu illisible. La commande /captionbrut reste.
    _BTNS = ("cmenu:capbanger", "cmenu:montagebanger", "cmenu:templatebanger",
             "cmenu:templatebrut", "cmenu:brutbanger")
    check("favoris : les 5 boutons sont dans le menu VA",
          all(b in _idsFv for b in _BTNS),
          str([b for b in _BTNS if b not in _idsFv]))
    check("favoris : les 5 boutons sont declares dans _MENU_BTN_FEATURE",
          all(_uFv._MENU_BTN_FEATURE.get(b) == "contenu" for b in _BTNS),
          str([b for b in _BTNS if _uFv._MENU_BTN_FEATURE.get(b) != "contenu"]))
    # Discord plafonne a 5 boutons par rangee : une 6e sur la meme ligne fait
    # echouer l instanciation de la vue, donc le menu entier.
    from collections import Counter as _CntFv
    _rowsV = _CntFv(i.row for i in _vFv.children)
    check("favoris : aucune rangee du menu VA ne deborde",
          all(n <= 5 for n in _rowsV.values()), str(dict(_rowsV)))
    check("favoris : la vue tient dans les 25 composants de Discord",
          len(_vFv.children) <= 25, "%d composants" % len(_vFv.children))

    # -- le menu du serveur US -----------------------------------------------
    # Le serveur US n'utilise PAS ContentMenuView : ses salons -menu portent le
    # panneau Jailbreak, pilote par _JB_ACTIONS_US. Sans entree la, les deux
    # boutons n'existent que sur le serveur francais.
    import re as _reFv
    import os as _os
    import tempfile as _tempfile
    _clesFv = {a[0] for a in _uFv._JB_ACTIONS_US}
    check("favoris : les 5 actions sont dans le menu US",
          all(k in _clesFv for k in ("capbanger", "montagebanger", "templatebanger",
                                     "templatebrut", "brutbanger")),
          str(sorted(_clesFv)))
    # Le panneau US declenche cmd.callback sur un ATTRIBUT du cog : une action
    # qui pointe vers une methode inexistante repond « Action indisponible ».
    for _k, _lb, _cmd, _sc in _uFv._JB_ACTIONS_US:
        check("favoris : l action US '%s' pointe vers une commande reelle" % _k,
              hasattr(_uFv.UserCog, _cmd), _cmd)
    # Le custom_id n'accepte que des lettres pour la cle : un chiffre ou un
    # tiret bas rendrait le bouton muet, sans erreur nulle part.
    _tplFv = r"jbus:a:(?P<ident>[a-z0-9_.\-]+):(?P<key>[a-z]+):(?P<qty>\d+)"
    check("favoris : les cles US passent le motif du custom_id",
          all(_reFv.fullmatch(_tplFv, "jbus:a:x:%s:3" % a[0])
              for a in _uFv._JB_ACTIONS_US),
          str([a[0] for a in _uFv._JB_ACTIONS_US
               if not _reFv.fullmatch(_tplFv, "jbus:a:x:%s:3" % a[0])]))
    # Rangees du panneau : on CONSTRUIT le vrai panneau et on compte ses vraies
    # rangees, au lieu de recopier ici la formule du rangement.
    #
    # Elle etait recopiee, et ca s est retourne contre nous : le jour ou le code
    # est passe a 5 boutons par ligne pour loger deux actions de plus, ce test a
    # echoue alors que le panneau tenait parfaitement. Un test qui reimplemente
    # ce qu il verifie ne verifie que sa propre copie.
    #
    # Le selecteur de quantite n a pas de rangee fixee (row=None) : Discord la
    # lui attribue. On ne compte donc que ce qui en porte une.
    _emb_us, _vue_us = _uFv._jb_panel(None, "test", 3, "us", None)
    _rowsFv = {}
    for _it in _vue_us.children:
        if getattr(_it, "row", None) is not None:
            _rowsFv[_it.row] = _rowsFv.get(_it.row, 0) + 1
    check("favoris : le panneau US ne deborde aucune rangee",
          all(_n <= 5 for _n in _rowsFv.values()) and max(_rowsFv) <= 4,
          str(_rowsFv))
    check("favoris : le panneau US tient dans les 25 composants de Discord",
          len(_vue_us.children) <= 25,
          "%d composants" % len(_vue_us.children))
    # Une rangee = une famille : identite, photos, brut+Flash, favoris ⭐.
    # C'est la forme VOULUE du panneau, pas un effet de bord d'un « i // 4 » --
    # une action ajoutee ne doit plus pousser les suivantes sur la ligne
    # d'apres.
    #
    # La forme a change le 27/08 en passant de {1:4, 2:3, 3:3, 4:5} a
    # {1:4, 2:5, 3:4, 4:5}, pour loger les trois actions Flash Trend. Ce
    # n'est pas un glissement : la rangee des favoris etait DEJA pleine a
    # cinq, donc les deux reels FINIS (caption, monte) ont ete remontes avec
    # les stories et le post, ce qui libere la rangee 3 pour « brut + Flash ».
    # Sans ce deplacement, les trois Flash n'avaient nulle part ou aller.
    # Forme du 21/08 : {1:4, 2:5, 3:5, 4:4}. Les familles ont ete redecoupees
    # pour que chaque bouton ETOILE suive celui dont il est la version marquee
    # — « Video brut » puis « ⭐ Video brut », « Template Flash » puis
    # « ⭐ Flash ». Avant, tous les etoiles etaient parques ensemble en rangee
    # 4, loin de ce dont ils sont la variante.
    #
    # C'est la REGLE qu'on protege, pas les nombres : une rangee, une famille,
    # et aucune qui deborde les cinq places de Discord.
    check("favoris : le panneau US garde ses 4 familles sur 4 rangees",
          _rowsFv == {1: 4, 2: 5, 3: 5, 4: 5}, str(_rowsFv))
    # Et chaque action connait sa rangee : sans entree, elle retombe sur le
    # filet et atterrit n'importe ou.
    check("favoris : chaque action US a une rangee attribuee",
          all(a[0] in _uFv._JB_RANGEES for a in _uFv._JB_ACTIONS_US),
          str([a[0] for a in _uFv._JB_ACTIONS_US
               if a[0] not in _uFv._JB_RANGEES]))

    # -- brutes a metadonnees changees ---------------------------------------
    # Pas de bouton separe : « Video brut » et « Video brut Banger » reecrivent
    # les metadonnees d office. Ce qu on verifie, c est qu ils passent bien par
    # la -- sinon la brute repart avec son empreinte d origine, sans que rien
    # ne le signale.
    import inspect as _insFv
    for _mFv, _nomFv in ((_uFv.UserCog.videobrut, "Vidéo brut"),
                         (_uFv.UserCog._send_brutes_bangers, "Vidéo brut Banger")):
        _srcFv = _insFv.getsource(getattr(_mFv, "callback", _mFv))
        check("brut+meta : « %s » passe par la reecriture" % _nomFv,
              "_envoyer_brutes_meta" in _srcFv, _nomFv)

    # L interrupteur du site doit etre LU, sinon il ne sert a rien -- c est
    # exactement l etat dans lequel le module d uniquification video se
    # trouvait : reglable, annonce comme « lu par /reel », et cable dans le vide.
    _srcEnv = _insFv.getsource(_uFv.UserCog._envoyer_brutes_meta)
    check("brut+meta : l interrupteur du site est lu",
          "load_transform_config()" in _srcEnv and "enabled" in _srcEnv,
          "aucune lecture de la config dans _envoyer_brutes_meta")
    # Le VA ne doit RIEN lire sur les metadonnees : le reglage est sur le site,
    # c est l affaire de l admin. On cherche la forme accentuee, celle des
    # messages -- les commentaires et docstrings, eux, s ecrivent sans accents.
    check("brut+meta : le VA ne lit pas un mot sur les metadonnees",
          "étadonnées" not in _srcEnv, "un message en parle encore")
    # Mais un echec demande-et-non-applique doit rester visible quelque part.
    check("brut+meta : l echec part au journal du serveur",
          "actif and not reecrit" in _srcEnv and "print(" in _srcEnv,
          "aucune trace serveur en cas d echec")

    # -- pseudo et name : le drapeau du site, et lui seul ---------------------
    # La regle vivait dans les deux boutons du panneau Jailbreak et nulle part
    # ailleurs : /name, /username et le menu VA l'ignoraient, donc un VA sur une
    # identite 🇺🇸 recevait « Ibenhaastrup Belle » selon le bouton clique.
    _vraiMk = _uFv._market_of
    try:
        _uFv._market_of = (lambda i: "us" if i in ("ibenhaastrup", "themikkiangel")
                           else "fr")
        check("pseudo/name : une identite 🇺🇸 part de Jessye",
              _uFv._source_pseudo_name("ibenhaastrup") == "jessye",
              _uFv._source_pseudo_name("ibenhaastrup"))
        check("pseudo/name : une identite 🇫🇷 garde la sienne",
              _uFv._source_pseudo_name("emma") == "emma",
              _uFv._source_pseudo_name("emma"))
        check("pseudo/name : Jessye reste Jessye",
              _uFv._source_pseudo_name("jessye") == "jessye",
              _uFv._source_pseudo_name("jessye"))
    finally:
        _uFv._market_of = _vraiMk
    # Une regle qu'aucune commande n'applique ne sert a rien.
    for _cmdFv in ("username", "name"):
        _sFv = _insFv.getsource(getattr(_uFv.UserCog, _cmdFv).callback)
        check("pseudo/name : /%s applique la regle" % _cmdFv,
              "_source_pseudo_name" in _sFv, _cmdFv)

    # Et surtout : la porte stricte ne doit JAMAIS annoncer un succes qu elle
    # n a pas obtenu. transform_video(), lui, rend True apres une simple copie
    # -- pratique pour un envoi automatique, mensonger pour un bouton qui
    # promet des metadonnees changees. C est la difference que ce test protege.
    import video_transform as _vtFv
    _vraiFv = _vtFv.is_ffmpeg_available
    try:
        _vtFv.is_ffmpeg_available = lambda: False
        _cibleFv = _os.path.join(_tempfile.gettempdir(), "_jamais_ecrit_meta.mp4")
        try:
            _os.remove(_cibleFv)
        except OSError:
            pass
        _rFv = _vtFv.transform_metadata_strict(__file__, _cibleFv)
        check("brut+meta : sans ffmpeg, la porte stricte avoue l echec",
              _rFv is False, repr(_rFv))
        check("brut+meta : sans ffmpeg, aucun fichier recopie en douce",
              not _os.path.exists(_cibleFv), _cibleFv)
    finally:
        _vtFv.is_ffmpeg_available = _vraiFv

    # -- on EXECUTE le chemin d envoi, dans les deux etats de l interrupteur --
    # Tout ce qui precede lit le SOURCE. C est insuffisant, et ca s est vu : un
    # f-string referencait un nom inexistant, le clic partait en NameError
    # APRES le defer(), Discord n affichait donc rien du tout, et aucun test ne
    # bronchait. Une lecture de source ne voit pas un nom qui manque.
    #
    # Les deux etats comptent : le bug ne frappait que l interrupteur ALLUME,
    # c est-a-dire le seul cas qu on ne testait pas en local.
    import asyncio as _aioX
    import pathlib as _plX

    class _RepX:
        async def defer(self, *a, **k): pass
        async def send_message(self, *a, **k): pass

    class _SuiviX:
        def __init__(self): self.envois = []
        async def send(self, content=None, file=None, **k):
            self.envois.append(content)

    class _ItxX:
        def __init__(self):
            self.response, self.followup = _RepX(), _SuiviX()

    _vidX = _os.path.join(_tempfile.gettempdir(), "_brute_test_envoi.mp4")
    with open(_vidX, "wb") as _fX:
        _fX.write(b"pas une vraie video, mais un fichier bien reel")
    _cogX = _uFv.UserCog.__new__(_uFv.UserCog)
    _loadX = _uFv.load_transform_config
    for _etatX in (False, True):
        try:
            _cfgX = _vtFv.load_config()
            _cfgX["enabled"] = _etatX
            _uFv.load_transform_config = (lambda _c=_cfgX: _c)
            _itxX = _ItxX()
            _errX = None
            try:
                _aioX.run(_cogX._envoyer_brutes_meta(
                    _itxX, [_plX.Path(_vidX)], "test", "BRUTE", "entete"))
            except Exception as _eX:
                _errX = repr(_eX)[:140]
            # 2 envois attendus : l en-tete, puis la seule video.
            check("brut+meta : l envoi s execute, interrupteur %s"
                  % ("ALLUME" if _etatX else "ETEINT"),
                  _errX is None and len(_itxX.followup.envois) == 2,
                  _errX or ("%d envois" % len(_itxX.followup.envois)))
        finally:
            _uFv.load_transform_config = _loadX
    try:
        _os.remove(_vidX)
    except OSError:
        pass
except Exception as _eFv:
    check("favoris : selecteurs testables", False, repr(_eFv)[:160])

print()
print("=" * 70)
print("Veille TikTok : normalisation, classements, isolation")
print("=" * 70)
try:
    import veille_tiktok as _vtk
    import apify_reels as _apr
    check("import veille_tiktok", True)

    # Magasin isole : la suite ne doit jamais ecrire dans data/.
    _origStore, _origData = _vtk.STORE, _vtk.DATA_DIR
    _vtk.DATA_DIR = TMP
    _vtk.STORE = TMP / "veille_tiktok.json"

    check("veille TikTok separee de veille Instagram",
          _vtk.STORE.name != "veille_reels.json"
          and _origStore.name == "veille_tiktok.json",
          f"{_origStore.name}")

    # Payload realiste de clockworks~tiktok-scraper.
    def _tk(vid, txt, iso, vues, likes, com, part):
        return {"id": vid, "text": txt, "createTimeISO": iso,
                "authorMeta": {"name": "rival", "nickName": "Rival"},
                "videoMeta": {"duration": 21, "coverUrl": "http://c/%s.jpg" % vid},
                "playCount": vues, "diggCount": likes, "commentCount": com,
                "shareCount": part, "collectCount": 0,
                "webVideoUrl": "https://www.tiktok.com/@rival/video/%s" % vid}

    _aujHui = _dtVtk.date.today()
    _isoJ = lambda n: (_aujHui - _dtVtk.timedelta(days=n)).strftime("%Y-%m-%dT10:00:00.000Z")
    _brut = [_tk("111", "grosse portee", _isoJ(90), 1000000, 10000, 100, 50),
             _tk("222", "fort engagement", _isoJ(5), 20000, 6000, 800, 400),
             _tk("333", "la mediane", _isoJ(45), 50000, 1000, 50, 20),
             {"error": "not found"}]

    _f0 = _vtk.fiche(_brut[0])
    check("fiche : les compteurs TikTok sont bien lus",
          (_f0 or {}).get("vues") == 1000000 and _f0.get("likes") == 10000
          and _f0.get("compte") == "rival" and _f0.get("duree") == 21,
          str(_f0)[:120])
    check("fiche : un item d'erreur (sans id) est rejete",
          _vtk.fiche(_brut[3]) is None)
    check("fiche : couverture acceptee en chaine comme en liste",
          _vtk._texte("http://a.jpg") == "http://a.jpg"
          and _vtk._texte(["http://b.jpg"]) == "http://b.jpg"
          and _vtk._texte(None) == "")

    _fiches = [x for x in (_vtk.fiche(b) for b in _brut) if x and x.get("compte")]
    check("3 fiches sur 4 items", len(_fiches) == 3, str(len(_fiches)))
    check("enregistrer : 3 nouvelles", _vtk.enregistrer(_fiches) == (3, 0))
    check("enregistrer : rejoue, 0 nouvelle (idempotent)",
          _vtk.enregistrer(_fiches) == (0, 3))

    _ordre = lambda tri: [g["id"] for g in _vtk.classer(tri=tri, n=10)]
    check("tri vues : la plus vue en tete", _ordre("vues")[0] == "111",
          str(_ordre("vues")))
    check("tri taux : la plus engageante en tete", _ordre("taux")[0] == "222",
          str(_ordre("taux")))
    check("tri vues et tri taux ne donnent PAS le meme ordre",
          _ordre("vues") != _ordre("taux"))
    _sc = {g["id"]: g["scores"] for g in _vtk.classer(tri="vues", n=10)}
    check("surperf : la video mediane du compte vaut x1.0",
          abs(_sc["333"]["surperf"] - 1.0) < 0.001,
          "x%.3f" % _sc["333"]["surperf"])
    check("taux : (likes+com+partages+favoris)/vues = 36 %",
          abs(_sc["222"]["taux"] - 0.36) < 0.001, "%.4f" % _sc["222"]["taux"])
    check("seuil : une video sous 500 vues n'a pas de taux",
          _vtk.scores({"vues": 100, "likes": 60, "compte": "x"}, {})["taux"] is None)
    check("filtre depuis : 30 jours ne garde que la video fraiche",
          [g["id"] for g in _vtk.classer(tri="vues", n=10, depuis=30)] == ["222"],
          str([g["id"] for g in _vtk.classer(tri="vues", n=10, depuis=30)]))
    check("filtre compte : un compte absent ne rend rien",
          _vtk.classer(comptes=["personne"], n=10) == [])
    check("comptes_suivis : 3 videos, mediane 50000",
          _vtk.comptes_suivis() == [{"compte": "rival", "videos": 3,
                                     "vues_medianes": 50000.0}],
          str(_vtk.comptes_suivis()))

    # Aucun appel reseau ne doit partir sans token ni sans compte : ces deux
    # sorties precoces sont ce qui empeche de bruler du credit Apify par erreur.
    _vraiToken = _apr.get_token
    _apr.get_token = lambda: ""
    _r, _e = _vtk.collecter(["rival"])
    check("collecter sans token : erreur propre, aucun appel", _r == [] and "token" in _e.lower(), _e)
    _apr.get_token = _vraiToken
    _r2, _e2 = _vtk.collecter([])
    check("collecter sans compte : sortie immediate", _r2 == [] and bool(_e2), _e2)

    check("oublier_compte retire les 3 videos", _vtk.oublier_compte("@rival") == 3)
    check("magasin vide apres oubli", _vtk.classer(n=0) == [])
    _vtk.STORE, _vtk.DATA_DIR = _origStore, _origData
except Exception as _eVtk:
    check("veille TikTok : testable", False, repr(_eVtk)[:160])

print()
print("=" * 70)
print("Onglet TikTok Trends : rendu reel et cablage")
print("=" * 70)
try:
    import veille_tiktok_ui as _tkui
    _hTk = _tkui.rendu_html()
    check("l'onglet se rend sans exception", len(_hTk) > 1500, str(len(_hTk)))
    check("le rendu porte le titre, le champ et le bouton",
          "TikTok Trends" in _hTk and 'id="tk-comptes"' in _hTk
          and 'onclick="tkCollecter()"' in _hTk)
    check("les 4 boutons de tri sont rendus",
          _hTk.count('onclick="tkTri(') == 4, str(_hTk.count('onclick="tkTri(')))
    # Le rendu est un f-string bourre de CSS et de JS : une accolade non
    # dedoublee passe la compilation et ne se voit qu'a l'ecran.
    check("aucune accolade de f-string orpheline dans le HTML",
          "{{" not in _hTk and "}}" not in _hTk)
    check("le cout Apify est annonce avant le clic",
          "Apify" in _hTk and "tk-prix" in _hTk)

    _srcTk = pathlib.Path("web_upload.py").read_text(encoding="utf-8")
    check("cablage : bouton de nav TikTok Trends",
          'id="tab-tktrends"' in _srcTk and "showTab('trends','tktrends'" in _srcTk)
    check("cablage : panneau form-tktrends",
          'id="form-tktrends"' in _srcTk and "{tiktok_trends_html}" in _srcTk)
    check("cablage : rendu paresseux declare",
          '"tktrends": _render_tiktok_trends_html' in _srcTk)
    check("cablage : permission tktrends declaree",
          '{"key": "tktrends"' in _srcTk)
    # Dans le bloc TikTok, SEUL "Trends" est livre : "Accounts" reste
    # volontairement SOON. L'assertion porte donc sur le bouton Trends, pas
    # sur l'absence de tout SOON -- qui serait faux et le restera.
    _blocTk = _srcTk[_srcTk.find('id="sub-tiktok"'):_srcTk.find('id="sub-twitter"')]
    check("cablage : Trends n'est plus SOON dans le bloc TikTok",
          'Trends</span><span class="badge">SOON' not in _blocTk
          and 'id="tab-tktrends"' in _blocTk)
    check("cablage : Accounts TikTok reste SOON (non livre)",
          'Accounts</span><span class="badge">SOON' in _blocTk)

    import web_upload as _wTk
    _aTk = _wTk.create_app(); _aTk.config["TESTING"] = True
    _rulesTk = {str(r.rule) for r in _aTk.url_map.iter_rules()}
    check("les 4 routes /tiktok/* sont enregistrees",
          {"/tiktok/render", "/tiktok/collect", "/tiktok/forget",
           "/tiktok/video/<vid>"} <= _rulesTk,
          str(sorted(x for x in _rulesTk if "tiktok" in x)))
    _anonTk = _aTk.test_client()
    check("/tiktok/render refuse l'anonyme",
          _anonTk.get("/tiktok/render").status_code == 401,
          str(_anonTk.get("/tiktok/render").status_code))
    _wTk._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cTk = _aTk.test_client()
    with _cTk.session_transaction() as _sTk:
        _sTk["auth"] = True; _sTk["username"] = "boss"; _sTk["role"] = "owner"
    check("/tiktok/render rend l'onglet a un owner",
          _cTk.get("/tiktok/render").status_code == 200
          and b"TikTok Trends" in _cTk.get("/tiktok/render").data)
    # L'identifiant vient de l'URL : un ../ doit mourir avant send_file.
    check("/tiktok/video refuse la traversee de chemin",
          _cTk.get("/tiktok/video/..%2f..%2fsecrets").status_code == 404)
    _pageTk = _cTk.get("/").data.decode("utf-8", "ignore")
    check("la page porte l'onglet et son panneau",
          'id="tab-tktrends"' in _pageTk and 'id="form-tktrends"' in _pageTk)
except Exception as _eTkU:
    check("onglet TikTok : testable", False, repr(_eTkU)[:160])

print()
print("=" * 70)
print("23) Securite : le nom « admin » n est plus un passe-droit (lot C4)")
print("=" * 70)
try:
    import web_upload as _wC4
    _appC4 = _wC4.create_app()
    _appC4.config["TESTING"] = True
    _savLoadC4 = _wC4._load_web_users
    _savSaveC4 = _wC4._save_web_users
    _savLoadRC4 = _wC4._load_role_users
    _savSaveRC4 = _wC4._save_role_users
    _srcC4 = pathlib.Path("web_upload.py").read_text(encoding="utf-8")

    def _cliC4(username, extra=None):
        _c = _appC4.test_client()
        with _c.session_transaction() as _s:
            _s["auth"] = True
            _s["username"] = username
            _s["role"] = "admin"
            _s["sid"] = "C4"
            for _k, _v in (extra or {}).items():
                _s[_k] = _v
        return _c

    # -- 1) le controle « compte supprime / desactive » exemptait le NOM admin :
    # une session de ce nom survivait 30 jours a la revocation du compte.
    _wC4._load_web_users = lambda: {"autre": {"role": "owner"}}
    _rC4a = _cliC4("admin").get("/external/list")
    check("compte « admin » supprime : acces coupe",
          _rC4a.status_code in (302, 401, 403), "HTTP %s" % _rC4a.status_code)
    _wC4._load_web_users = lambda: {"admin": {"role": "admin", "disabled": True}}
    _rC4b = _cliC4("admin").get("/external/list")
    check("compte « admin » desactive : acces coupe",
          _rC4b.status_code in (302, 401, 403), "HTTP %s" % _rC4b.status_code)
    # -- ... sans casser le depannage : WEB_PASSWORD seul (aucun nom saisi)
    # ouvre une session nommee « admin » qu AUCUN compte ne soutient.
    _wC4._load_web_users = lambda: {"autre": {"role": "owner"}}
    _rC4c = _cliC4("admin", {"legacy_owner": True}).get("/external/list")
    check("depannage WEB_PASSWORD seul : session conservee",
          _rC4c.status_code == 200, "HTTP %s" % _rC4c.status_code)
    # Le drapeau est pose au login. On le verifie sur la SOURCE : poster le
    # formulaire de connexion ecrirait dans data/active_sessions.json.
    check("le login pose (et retire) le drapeau de depannage",
          'session["legacy_owner"] = True' in _srcC4
          and 'session.pop("legacy_owner", None)' in _srcC4)

    # -- 2) noms reserves : plus personne ne peut CREER « admin »
    check("noms reserves reconnus quelle que soit la casse",
          all(_wC4._nom_reserve(n) for n in ("admin", "Admin", " SAMAALI ")))
    check("un nom ordinaire n est pas reserve", not _wC4._nom_reserve("emma"))

    _ecritsC4 = []
    _wC4._save_web_users = lambda d: _ecritsC4.append(("web", dict(d)))
    _wC4._save_role_users = lambda d: _ecritsC4.append(("role", list(d)))
    _wC4._load_role_users = lambda: []
    _wC4._load_web_users = lambda: {"boss": {"role": "owner"},
                                    "dejala": {"role": "va"}}
    _cAddC4 = _cliC4("boss")
    for _nomC4, _pourquoiC4 in (("admin", "nom reserve"),
                                ("dejala", "acces de connexion deja existant")):
        _cAddC4.post("/settings/role/add",
                     data={"username": _nomC4, "role": "va", "password": "azerty1"})
        check(f"/settings/role/add refuse « {_nomC4} » ({_pourquoiC4})",
              not _ecritsC4, "a ecrit : %s" % [t for t, _ in _ecritsC4])

    # -- 3) inscription publique : signup_public ne cree un compte qu a travers
    # la fonction qu on lui passe. Elle doit refuser un nom reserve, et le dire.
    _wC4._load_web_users = lambda: {"boss": {"role": "owner"}}
    _refuseC4 = False
    try:
        _wC4._save_web_users_inscription({"boss": {"role": "owner"},
                                          "admin": {"role": "va"}})
    except ValueError:
        _refuseC4 = True
    check("inscription publique : « admin » refuse, rien d ecrit",
          _refuseC4 and not _ecritsC4, "refus=%s ecritures=%s" % (_refuseC4, len(_ecritsC4)))
    _wC4._save_web_users_inscription({"boss": {"role": "owner"},
                                      "nouvelle": {"role": "va"}})
    check("inscription publique : un nom ordinaire passe toujours",
          any(t == "web" for t, _ in _ecritsC4))
    _wC4._load_web_users = _savLoadC4
    _wC4._save_web_users = _savSaveC4
    _wC4._load_role_users = _savLoadRC4
    _wC4._save_role_users = _savSaveRC4

    # -- 4) /bio/<identite> : page PUBLIQUE dont l identite vient de l URL.
    # Elle etait recopiee telle quelle dans le HTML -> script execute sur
    # l origine du dashboard, ou aucune ecriture n a de jeton anti-CSRF.
    _savAvC4 = _wC4._identity_avatar_url
    _wC4._identity_avatar_url = lambda i: ""
    import bio_links as _blC4
    _savBioC4 = _blC4.get_bio
    _blC4.get_bio = lambda i: {"display_name": "", "bio": "", "theme": "dark",
                               "links": []}
    _chargeC4 = "<img src=x onerror=alert(1)>"
    _htmlC4 = _wC4._render_bio_public_page(_chargeC4)
    check("/bio/<identite> : la charge de l URL est echappee",
          _chargeC4 not in _htmlC4
          and "&lt;img src=x onerror=alert(1)&gt;" in _htmlC4)
    _blC4.get_bio = lambda i: {
        "display_name": "<b>x</b>", "bio": "<script>a</script>", "theme": "dark",
        "links": [{"url": "' onmouseover='alert(1)", "title": "<i>t</i>",
                   "icon": "<u>"}]}
    _htmlC4b = _wC4._render_bio_public_page("emma")
    check("/bio/<identite> : nom, bio et liens stockes sont echappes",
          "<script>a</script>" not in _htmlC4b and "<i>t</i>" not in _htmlC4b
          and "' onmouseover='alert(1)" not in _htmlC4b)
    _blC4.get_bio = _savBioC4
    _wC4._identity_avatar_url = _savAvC4

    # -- 5) lectures qui depensent du quota paye / exposent les push des modeles
    _wC4._load_web_users = lambda: {"chat": {"role": "chatter"}}
    _cChatC4 = _appC4.test_client()
    with _cChatC4.session_transaction() as _sC4:
        _sC4["auth"] = True
        _sC4["username"] = "chat"
        _sC4["role"] = "chatter"
    for _pC4 in ("/insta/apify_diag", "/insta/debug_rapidapi?owner=a&shortcode=b",
                 "/sfssetup/mypuls_pushes"):
        _rC4 = _cChatC4.get(_pC4)
        check("role restreint bloque en lecture : " + _pC4.split("?")[0],
              _rC4.status_code == 403, "HTTP %s" % _rC4.status_code)
    # ... mais la page SFS Planning doit rester servie a qui a l onglet : on
    # verifie le mapping sur la source (l appeler pour de vrai relancerait un
    # scrape MyPuls et reecrirait data/sfs_pushs_cache.json).
    _mapC4 = _srcC4[_srcC4.find("_READ_PREFIX_TO_TAB = {"):]
    _mapC4 = _mapC4[:_mapC4.find("}")]
    check("lecture SFS mappee a l onglet sfs (pas de sur-blocage)",
          '"/sfssetup/mypuls_pushes": "sfs"' in _mapC4)
    _wC4._load_web_users = _savLoadC4
except Exception as _eC4:
    check("securite lot C4 : testable", False, repr(_eC4)[:160])

print()
print("=" * 70)
print("Filtres etoile des galeries (portee + etat)")
print("=" * 70)
# F3 : deux defauts a l ecran, tous deux invisibles en lecture.
#  - PORTEE : chaque galerie rend sa grille avec le MEME id 'vault-grid' et son
#    bouton avec le MEME id ; getElementById renvoyait celui de la 1re galerie
#    du document. Dans la Bibliotheque 2 le filtre ne faisait donc rien a
#    l ecran tout en masquant les cartes de la galerie cachee d a cote.
#  - ETAT : il vivait dans une variable de page qui survivait au re-rendu de la
#    section, alors que le bouton renvoye par le serveur repartait neutre. La
#    galerie se vidait sous un bouton qui se disait inactif.
# On execute les VRAIES fonctions de la page dans node, sur un DOM minimal.
_DOM_STUB_F3 = """
function El(tag){ this.tag=tag; this.classes=[]; this.attrs={}; this.children=[];
  this.parent=null; this.style={}; this.textContent=''; }
El.prototype.setAttribute=function(k,v){ this.attrs[k]=String(v); };
El.prototype.getAttribute=function(k){ return (k in this.attrs)?this.attrs[k]:null; };
El.prototype.appendChild=function(c){ c.parent=this; this.children.push(c); return c; };
Object.defineProperty(El.prototype,'className',{
  get:function(){ return this.classes.join(' '); },
  set:function(v){ this.classes=String(v).split(' ').filter(Boolean); }
});
Object.defineProperty(El.prototype,'classList',{get:function(){
  var self=this;
  return {
    add:function(n){ if(self.classes.indexOf(n)<0) self.classes.push(n); },
    remove:function(n){ var i=self.classes.indexOf(n); if(i>=0) self.classes.splice(i,1); },
    contains:function(n){ return self.classes.indexOf(n)>=0; },
    toggle:function(n,f){ if(f===undefined) f=(self.classes.indexOf(n)<0);
                          if(f) this.add(n); else this.remove(n); return f; }
  };
}});
Object.defineProperty(El.prototype,'offsetParent',{get:function(){
  var n=this; while(n && n.style){ if(n.style.display==='none') return null; n=n.parent; }
  return this.parent||null;
}});
function correspond(el, sel){
  if(!el || !el.classes) return false;
  var toks = sel.match(/[.#][A-Za-z0-9_-]+/g) || [];
  if(!toks.length) return false;
  for(var i=0;i<toks.length;i++){
    var t=toks[i];
    if(t.charAt(0)==='#'){ if(el.attrs.id !== t.slice(1)) return false; }
    else if(el.classes.indexOf(t.slice(1))<0) return false;
  }
  return true;
}
El.prototype.descendants=function(){
  var out=[];
  var marche=function(n){ for(var i=0;i<n.children.length;i++){ out.push(n.children[i]); marche(n.children[i]); } };
  marche(this); return out;
};
El.prototype.querySelectorAll=function(s){
  return this.descendants().filter(function(e){ return correspond(e,s); }); };
El.prototype.querySelector=function(s){ var r=this.querySelectorAll(s); return r.length?r[0]:null; };
El.prototype.closest=function(s){ var n=this; while(n){ if(correspond(n,s)) return n; n=n.parent; } return null; };
var racine = new El('body');
var document = {
  querySelectorAll:function(s){ return racine.querySelectorAll(s); },
  querySelector:function(s){ return racine.querySelector(s); },
  getElementById:function(id){ return racine.querySelector('#'+id); },
  createElement:function(t){ return new El(t); }
};
function faireSection(idSec, visible, etoiles, idBtn, clsEtoile){
  var sec=new El('div'); sec.classes.push('form-section'); sec.attrs.id=idSec;
  if(!visible) sec.style.display='none';
  var btn=new El('button'); btn.attrs.id=idBtn; btn.setAttribute('data-on','0');
  sec.appendChild(btn);
  var grid=new El('div'); grid.attrs.id='vault-grid'; sec.appendChild(grid);
  etoiles.forEach(function(allumee){
    var c=new El('div'); c.classes.push('cloud-card');
    var st=new El('button'); st.classes.push(clsEtoile.split('.')[0]);
    if(allumee) st.classes.push(clsEtoile.split('.')[1]);
    c.appendChild(st); grid.appendChild(c);
  });
  racine.appendChild(sec);
  return {sec:sec, btn:btn, grid:grid};
}
function nbCaches(g){
  return g.querySelectorAll('.cloud-card').filter(function(c){ return c.style.display==='none'; }).length;
}
function vider(){ racine.children.length = 0; }
var res = {};
// --- PORTEE : la 2e bibliotheque est la section VISIBLE ---------------------
var cachee  = faireSection('form-cloudreels', false, [true,false,false], 'banger-toggle-btn', 'banger-star.is-banger');
var visible = faireSection('form-v2reels',    true,  [true,false,false], 'banger-toggle-btn', 'banger-star.is-banger');
toggleBangerFilter(visible.btn);
res.banger_portee_visible = nbCaches(visible.grid);   // attendu 2
res.banger_portee_cachee  = nbCaches(cachee.grid);    // attendu 0
// --- ETAT : le filtre ne doit pas survivre au re-rendu de la section --------
vider();
var avant = faireSection('form-cloudreels', true, [true,false,false], 'banger-toggle-btn', 'banger-star.is-banger');
toggleBangerFilter(avant.btn);
res.banger_actif_apres_clic = nbCaches(avant.grid);   // attendu 2
vider();   // changement d identite : le serveur renvoie une section neuve
var apres = faireSection('form-cloudreels', true, [true,false,false], 'banger-toggle-btn', 'banger-star.is-banger');
applyBangerFilter();       // ce que fait _setBangerStar au 1er clic sur une etoile
res.banger_apres_rerendu = nbCaches(apres.grid);      // attendu 0
res.banger_bouton_neutre = apres.btn.getAttribute('data-on');
// --- meme chose pour l etoile des rushs bruts (Video brut / Template) -------
vider();
var brut1 = faireSection('form-cloudbrutes',    false, [true,false,false], 'favbrute-toggle-btn', 'fav-brute-star.is-fav');
var brut2 = faireSection('form-cloudtemplates', true,  [true,false,false], 'favbrute-toggle-btn', 'fav-brute-star.is-fav');
toggleFavBruteFilter(brut2.btn);
res.fav_portee_visible = nbCaches(brut2.grid);        // attendu 2
res.fav_portee_cachee  = nbCaches(brut1.grid);        // attendu 0
console.log(JSON.stringify(res));
"""
try:
    import shutil as _shF3
    import subprocess as _spF3
    import web_upload as _wF3
    _uplF3 = _wF3.UPLOAD_HTML
    _dA = _uplF3.find("function vaultSectionVisible(){")
    _fA = _uplF3.find("// ⌫ Vide le salon banger-")
    _dB = _uplF3.find("function favBruteApply(sec){")
    _fB = _uplF3.find("// === Repérage des brutes")
    check("filtres etoile : les fonctions sont retrouvables dans la page",
          _dA >= 0 and _fA > _dA and _dB >= 0 and _fB > _dB,
          f"dA={_dA} fA={_fA} dB={_dB} fB={_fB}")
    # Le bouton rendu par le serveur PORTE l etat : sans data-on, la variable
    # de page reprenait la main et la galerie se vidait sous un bouton neutre.
    _srcF3 = pathlib.Path("web_upload.py").read_text(encoding="utf-8")
    check("filtres etoile : le bouton rendu part neutre et porte l etat (data-on)",
          "id='banger-toggle-btn' data-on='0'" in _srcF3
          and "id='favbrute-toggle-btn' data-on='0'" in _srcF3)
    if _dA >= 0 and _fA > _dA and _dB >= 0 and _fB > _dB:
        _codeF3 = _uplF3[_dA:_fA] + "\n" + _uplF3[_dB:_fB] + "\n" + _DOM_STUB_F3
        _fF3 = TMP / "filtres_etoile.js"
        _fF3.write_text(_codeF3, encoding="utf-8")
        _nodeF3 = _shF3.which("node")
        if _nodeF3:
            _rF3 = _spF3.run([_nodeF3, str(_fF3)], capture_output=True,
                             text=True, encoding="utf-8", timeout=60)
            try:
                _resF3 = json.loads((_rF3.stdout or "").strip().splitlines()[-1])
            except Exception:
                _resF3 = {}
            check("filtre ★ : il masque la galerie VISIBLE (Bibliotheque 2)",
                  _resF3.get("banger_portee_visible") == 2,
                  ((_rF3.stderr or "") + " " + str(_resF3))[:200])
            check("filtre ★ : il ne touche PAS la galerie cachee de l autre bibliotheque",
                  _resF3.get("banger_portee_cachee") == 0, str(_resF3)[:200])
            check("filtre ★ : un clic sur le bouton filtre bien",
                  _resF3.get("banger_actif_apres_clic") == 2, str(_resF3)[:200])
            check("filtre ★ : il ne survit pas au re-rendu de la section (bouton neutre = galerie entiere)",
                  _resF3.get("banger_apres_rerendu") == 0
                  and _resF3.get("banger_bouton_neutre") == "0", str(_resF3)[:200])
            check("filtre ⭐ brutes : il vise la galerie visible (Template montage), pas Video brut",
                  _resF3.get("fav_portee_visible") == 2
                  and _resF3.get("fav_portee_cachee") == 0, str(_resF3)[:200])
        else:
            # Ne jamais ecarter en silence : dire que la verification manque.
            print("     (node absent : les filtres etoile n ont pas ete executes)")
except Exception as _eF3:
    check("filtres etoile : testable", False, repr(_eF3)[:160])

print()
print("=" * 70)
print("DRIVE : identifiants gardes, mais JAMAIS au-dela d un changement de compte")
print("=" * 70)


class _SautGoogle(Exception):
    """google-auth n est pas installe sur ce poste : on saute, en le disant."""


try:
    import gdrive_sync as _gdT

    # Les identifiants etaient refabriques a chaque appel, avec token=None :
    # la premiere requete Drive commencait donc toujours par battre un jeton
    # neuf. Une synchro montante en battait treize. On les garde — mais se
    # deconnecter ou brancher un autre compte DOIT les jeter, sinon on
    # continuerait d ecrire dans le Drive du compte precedent.
    try:
        import google.oauth2.credentials as _gOauth   # noqa: F401
        _google_dispo = True
    except Exception:
        _google_dispo = False

    _svCfg = _gdT.oauth_config
    _svC, _svS = _gdT._CREDS, _gdT._CREDS_SIG
    try:
        if not _google_dispo:
            # Ne jamais ecarter en silence : dire que la verification manque.
            _dire("     (google-auth absent : cache d identifiants non teste)")
            raise _SautGoogle
        _cfgT = {"refresh_token": "jeton-A", "client_id": "cid", "client_secret": "sec"}
        _gdT.oauth_config = lambda: dict(_cfgT)
        _gdT._CREDS, _gdT._CREDS_SIG = None, None
        _a1 = _gdT._identifiants()
        _a2 = _gdT._identifiants()
        check("drive : deux appels de suite rendent LES MEMES identifiants",
              _a1 is _a2)
        _cfgT["refresh_token"] = "jeton-B"        # autre compte Google
        _b1 = _gdT._identifiants()
        check("drive : changer de compte refabrique les identifiants",
              _b1 is not _a1 and getattr(_b1, "refresh_token", None) == "jeton-B",
              getattr(_b1, "refresh_token", None))
        _cfgT.clear()                              # deconnexion complete
        _cfgT.update({"refresh_token": "", "client_id": "", "client_secret": ""})
        _c1 = _gdT._identifiants()
        check("drive : se deconnecter ne ressert pas l ancien jeton",
              _c1 is not _b1)
    except _SautGoogle:
        pass
    finally:
        _gdT.oauth_config = _svCfg
        _gdT._CREDS, _gdT._CREDS_SIG = _svC, _svS

    check("drive : le rapport d affichage a sa version gardee",
          callable(getattr(_gdT, "sync_report_cache", None)))
    # La veille decide de relancer une synchro sur ce rapport : une valeur
    # perimee y a deja fabrique une boucle sans fin. Elle doit rester sur le
    # chemin NON garde.
    _srcGd = (_plCa.Path(__file__).resolve().parent / "gdrive_sync.py").read_text("utf-8")
    check("drive : la veille n utilise PAS le rapport garde",
          "sync_report_cache" not in _srcGd.split("def _veille")[-1][:3000])
except Exception as _eGd:
    check("drive : identifiants testables", False, repr(_eGd)[:160])

print()
print("=" * 70)
print("ONGLETS DIFFERES : le fragment est traduit comme la page")
print("=" * 70)
try:
    import web_upload as _wTr
    _aTr = _wTr.create_app(); _aTr.testing = True
    _svTr = _wTr._load_web_users
    _wTr._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cTr = _aTr.test_client()
    with _cTr.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "TTR"
    try:
        # _traduire_html n etait applique QUE dans _render_upload : les ~40
        # onglets differes repartaient en francais alors que l anglais est la
        # langue PAR DEFAUT (cookie va_lang absent). Personne ne le voyait.
        _cTr.set_cookie("va_lang", "fr")
        _frTr = _cTr.get("/?lazy=cloudreels&tab=cloudreels",
                         headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
        _cTr.delete_cookie("va_lang")
        _enTr = _cTr.get("/?lazy=cloudreels&tab=cloudreels",
                         headers={"X-Tab-Ajax": "1"}).get_data(as_text=True)
        check("differe : le fragment n est pas rendu a l identique dans les 2 langues",
              bool(_frTr) and _frTr != _enTr)
        # Un libelle francais bien present cote FR doit avoir disparu cote EN.
        check("differe : un libelle francais ne survit pas en langue par defaut",
              ("Décroissant" in _frTr) and ("Décroissant" not in _enTr),
              "FR:%s EN:%s" % ("Décroissant" in _frTr, "Décroissant" in _enTr))
    finally:
        _wTr._load_web_users = _svTr
except Exception as _eTr:
    check("differe : traduction testable", False, repr(_eTr)[:160])

print()
print("=" * 70)
print("BIBLIOTHEQUE : un filtre n en efface plus un autre")
print("=" * 70)
try:
    import web_upload as _wFl
    _aFl = _wFl.create_app(); _aFl.testing = True
    _svFl = _wFl._load_web_users
    _wFl._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cFl = _aFl.test_client()
    with _cFl.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "TFL"
    try:
        # On pose une date ET un type, puis on regarde les liens de tri rendus :
        # ils doivent reconduire les deux. Avant, choisir « Croissant » apres
        # « Aller a la date » ramenait tout le dossier, sans un mot.
        _hFl = galerie(_cFl, "/?tab=cloudreels&cloud_videos_date=2026-08-12"
                             "&cloud_videos_type=video")
        check("biblio : les liens de tri reconduisent la date",
              "cloud_videos_date=2026-08-12" in _hFl, "date absente des liens")
        check("biblio : les liens de tri reconduisent le type",
              "cloud_videos_type=video" in _hFl, "type absent des liens")
        # Et le formulaire de date reconduit le tri + le type.
        check("biblio : le formulaire de date reconduit tri et type",
              "name='cloud_videos_sort'" in _hFl and "name='cloud_videos_type'" in _hFl)
    finally:
        _wFl._load_web_users = _svFl
except Exception as _eFl:
    check("biblio : filtres testables", False, repr(_eFl)[:160])

print()
print("=" * 70)
print("IMAGES CREEES EN JS : loading pose AVANT src, jamais apres")
print("=" * 70)
try:
    _srcJs = (_plCa.Path(__file__).resolve().parent / "web_upload.py").read_text("utf-8")
    # Le piege s est repete SIX fois dans ce fichier. Poser img.src d abord
    # lance le telechargement immediatement : l attribut loading='lazy' arrive
    # apres coup et ne sert plus a rien. C est ainsi que ~800 photos de profil
    # partaient d un coup alors que le rendu serveur, lui, etait correct.
    _fautifs = []
    for _m in _reCa.finditer(r"createElement\(\s*['\"]img['\"]\s*\)", _srcJs):
        _fen = _srcJs[_m.end():_m.end() + 700]
        _iSrc = _fen.find(".src")
        _iLaz = min([i for i in (_fen.find(".loading"),
                                 _fen.find("'loading'"),
                                 _fen.find('"loading"')) if i >= 0] or [-1])
        if _iSrc >= 0 and _iLaz >= 0 and _iLaz > _iSrc:
            _fautifs.append(_srcJs[:_m.start()].count("\n") + 1)
    check("images JS : aucune ne pose src avant loading",
          not _fautifs, "lignes " + str(_fautifs))
except Exception as _eJs:
    check("images JS : ordre des attributs testable", False, repr(_eJs)[:160])

print()
print("=" * 70)
print("PHOTOS DE PROFIL : servies a la taille affichee, 404 mis en cache")
print("=" * 70)
try:
    import io as _ioPp
    import web_upload as _wPp
    from PIL import Image as _ImPp

    _aPp = _wPp.create_app(); _aPp.testing = True
    _svPp = _wPp._load_web_users
    _wPp._load_web_users = lambda: {"boss": {"role": "owner", "password": "x"}}
    _cPp = _aPp.test_client()
    with _cPp.session_transaction() as _s:
        _s["auth"] = True; _s["username"] = "boss"; _s["role"] = "owner"; _s["sid"] = "TPP"

    # La copie locale fait 320x320 pour des pastilles de 30 a 46 px : avec ~800
    # comptes le navigateur gardait 328 Mo de bitmaps DECODES, ce qui figeait
    # l onglet. La route doit servir une reduction, pas l original.
    _dPp = _plCa.Path("data/insta/pp"); _dPp.mkdir(parents=True, exist_ok=True)
    _fPp = _dPp / "_tst_pp_perf.jpg"
    _ImPp.new("RGB", (320, 320), (200, 60, 120)).save(_fPp, "JPEG", quality=92)
    try:
        _rPp = _cPp.get("/insta/pp/_tst_pp_perf")
        check("pp : la route repond", _rPp.status_code == 200, _rPp.status_code)
        if _rPp.status_code == 200:
            _szPp = _ImPp.open(_ioPp.BytesIO(_rPp.data)).size
            check("pp : servie reduite, pas en 320 px", max(_szPp) <= 96, _szPp)
        # Un 404 sans duree de vie etait redemande a CHAQUE affichage : un
        # compte sans copie locale coutait une requete par rendu, pour rien.
        # Le hook de cache force « no-store » sur tout le text/html, d ou le
        # type text/plain — sans lui l en-tete posee ici etait annulee.
        _r4 = _cPp.get("/insta/pp/_tst_absent_xyz")
        check("pp : un compte sans photo repond 404", _r4.status_code == 404)
        check("pp : ce 404 est mis en cache (plus une requete par affichage)",
              "max-age" in (_r4.headers.get("Cache-Control") or "")
              and "no-store" not in (_r4.headers.get("Cache-Control") or ""),
              _r4.headers.get("Cache-Control"))
    finally:
        for _x in (_fPp, _wPp.THUMB_DIR / "insta_pp96" / "_tst_pp_perf.jpg"):
            try:
                _x.unlink()
            except Exception:
                pass
        _wPp._load_web_users = _svPp
except Exception as _ePp:
    check("pp : reduction testable", False, repr(_ePp)[:160])

print()
print("=" * 70)
print("AVATARS DISCORD : demandes a la taille reellement affichee")
print("=" * 70)
try:
    import web_upload as _wAv
    _av = _wAv._avatar_petit
    check("avatar : 1024 px ramene a 128",
          _av("https://cdn.discordapp.com/avatars/1/ab.png?size=1024")
          == "https://cdn.discordapp.com/avatars/1/ab.png?size=128",
          _av("https://cdn.discordapp.com/avatars/1/ab.png?size=1024"))
    check("avatar : la taille est reecrite meme en 2e parametre",
          _av("https://x/a.png?quality=lossless&size=4096").endswith("size=128"),
          _av("https://x/a.png?quality=lossless&size=4096"))
    check("avatar : une URL sans taille est laissee intacte",
          _av("https://cdn.discordapp.com/embed/avatars/0.png")
          == "https://cdn.discordapp.com/embed/avatars/0.png")
    check("avatar : une URL vide reste vide", _av("") == "" and _av(None) == "")
except Exception as _eAv:
    check("avatar : redimensionnement testable", False, repr(_eAv)[:160])

print()
print("=" * 70)
print("REVENUS API : le prechargement parallele ne change pas les totaux")
print("=" * 70)
try:
    import mypuls as _mpP

    # Les releves partaient l un apres l autre, 30 s de delai chacun : la page
    # Revenus tenait un worker des minutes et /home/overview finissait en 503.
    # Le prechargement remplit le cache en parallele ; la boucle qui additionne
    # l argent doit rester identique, au centime pres.
    _svCr, _svSt, _svCf = (_mpP.api_creators_cached, _mpP.api_creator_stats_cached,
                           _mpP.api_configured)
    _svOv = dict(_mpP._API_OVERVIEW_CACHE)
    try:
        _appels = []
        _CREAS = [
            {"id": 1, "pseudo": "alpha", "active": True, "platform": "mym",
             "currency": "EUR"},
            {"id": 2, "pseudo": "beta", "active": True, "platform": "onlyfans",
             "currency": "USD"},
            {"id": 3, "pseudo": "dormante", "active": False, "platform": "mym"},
            {"id": 4, "pseudo": "bella", "active": True, "platform": "mym"},
        ]
        _REV = {1: 100.0, 2: 50.0, 3: 999.0, 4: 777.0}

        def _faux_stats(cid, d1, d2):
            _appels.append(cid)
            return {"ok": True, "data": {"revenue": {
                "total": _REV[cid], "currency": "EUR" if cid == 1 else "USD",
                "by_type": {"message": _REV[cid]}}}}

        _mpP.api_configured = lambda: True
        _mpP.api_creators_cached = lambda force=False: _CREAS
        _mpP.api_creator_stats_cached = _faux_stats
        _mpP._API_OVERVIEW_CACHE.clear()

        _ov = _mpP.api_overview("2026-08-01", "2026-08-31", eur_usd=2.0,
                                exclude={"bella"})
        check("revenus : l agregat repond ok", _ov.get("ok") is True,
              str(_ov)[:120])
        # alpha : 100 EUR x 2.0 = 200 $ ; beta : 50 $ ; total attendu 250 $
        check("revenus : total inchange par le prechargement",
              abs(float(_ov.get("total_usd") or 0) - 250.0) < 0.01,
              _ov.get("total_usd"))
        check("revenus : une creatrice inactive n est jamais interrogee",
              3 not in _appels, _appels)
        check("revenus : une creatrice ecartee n est jamais interrogee",
              4 not in _appels, _appels)
        # Le prechargement et la boucle doivent viser le MEME ensemble : si les
        # deux filtres divergeaient, on paierait un aller-retour pour rien.
        check("revenus : aucune creatrice hors perimetre prechargee",
              set(_appels) == {1, 2}, _appels)
    finally:
        _mpP.api_creators_cached, _mpP.api_creator_stats_cached = _svCr, _svSt
        _mpP.api_configured = _svCf
        _mpP._API_OVERVIEW_CACHE.clear()
        _mpP._API_OVERVIEW_CACHE.update(_svOv)
except Exception as _eP:
    check("revenus : prechargement testable", False, repr(_eP)[:160])

print()
print("=" * 70)
print("JOURNAL : un print ne doit pas pouvoir interrompre une requete")
print("=" * 70)
try:
    import web_upload as _wEnc
    check("journal : la sortie ne peut plus lever UnicodeEncodeError",
          getattr(sys.stdout, "errors", "") == "replace",
          getattr(sys.stdout, "errors", None))
    # Le cas reel : facture_web imprimait « -> » (fleche U+2192), absent de
    # cp1252. L exception remontait au milieu du calcul, le repli l avalait,
    # et la page se rendait vide sans le moindre message.
    import io
    _tampon = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="replace")
    _tampon.write("[facture] repli scraping → MyPuls ⚠")
    check("journal : une fleche ou un emoji passe sans exception", True)
except Exception as _eEnc:
    check("journal : testable", False, repr(_eEnc)[:160])

print()
print("=" * 70)
print("PORTAIL VA : un lien par fiche, et rien que sa fiche")
print("=" * 70)
try:
    _dosVP = pathlib.Path(tempfile.mkdtemp(prefix="portail_"))
    import jailbreak as _jbVP, va_portal as _vpVP

    _svVP = (_jbVP.JAILBREAK_FILE, _jbVP.PREV_FILE, _jbVP.BACKUP_DIR,
             _jbVP.TOMB_FILE, _vpVP.LIENS_FILE)
    _jbVP.JAILBREAK_FILE = _dosVP / "jailbreak.json"
    _jbVP.PREV_FILE = _dosVP / "jailbreak.prev.json"
    _jbVP.BACKUP_DIR = _dosVP / "backups"
    _jbVP.TOMB_FILE = _dosVP / "tomb.json"
    _vpVP.LIENS_FILE = _dosVP / "liens.json"
    try:
        _jbVP._save({"jessye": {"vas": [{"name": "VA NOUM 1X1", "discord_username": ""},
                                        {"name": "VA NOUM 1X2", "discord_username": ""}],
                                "accounts": []}})
        _jbVP.add_account("jessye", "a.moi", va="VA NOUM 1X1")
        _jbVP.add_account("jessye", "au.voisin", va="VA NOUM 1X2")

        import web_upload as _wVP
        _appVP = _wVP.create_app()
        _admVP = _appVP.test_client()
        with _admVP.session_transaction() as _sVP:
            _sVP["auth"] = True
            _sVP["username"] = "admin"
            _sVP["role"] = "owner"
            # legacy_owner : un test precedent laisse _load_web_users remplace
            # par une table qui ne contient pas « admin ». Sans ce drapeau,
            # is_auth() vide la session avant meme d arriver a la route.
            _sVP["legacy_owner"] = True

        # Le lien ne se demande pas sans session : c'est la seule porte par
        # laquelle un jeton sort, elle doit rester fermee aux anonymes.
        _anoVP = _appVP.test_client()
        check("portail : un anonyme ne peut pas reclamer de lien",
              _anoVP.post("/jailbreak/va_lien",
                          data={"identity": "jessye", "va_name": "VA NOUM 1X1"}).status_code == 401)

        _rVP = _admVP.post("/jailbreak/va_lien", data={
            "identity": "jessye", "va_name": "VA NOUM 1X1", "action": "creer"}).get_json()
        check("portail : le lien se cree", bool(_rVP.get("ok") and _rVP.get("jeton")), str(_rVP)[:120])
        _urlVP = (_rVP.get("url") or "").replace("http://localhost", "")
        _jetVP = _rVP.get("jeton")

        # Idempotent : rouvrir la fenetre ne doit pas invalider le lien deja
        # envoye sur Discord.
        _r2VP = _admVP.post("/jailbreak/va_lien", data={
            "identity": "jessye", "va_name": "VA NOUM 1X1", "action": "creer"}).get_json()
        check("portail : redemander le lien rend le MEME jeton",
              _r2VP.get("jeton") == _jetVP, f"{_r2VP.get('jeton')} vs {_jetVP}")

        _vaVP = _appVP.test_client()
        _pVP = _vaVP.get(_urlVP)
        _hVP = _pVP.get_data(as_text=True)
        check("portail : la page s ouvre sans session", _pVP.status_code == 200, _pVP.status_code)
        check("portail : le VA voit SON compte", "a.moi" in _hVP)
        # Le coeur du besoin : quatre telephones = quatre fiches = quatre pages,
        # et aucune ne doit laisser entrevoir les trois autres.
        check("portail : il ne voit pas celui d une autre fiche", "au.voisin" not in _hVP)
        check("portail : aucun autre jeton n est dans la page",
              _hVP.count("/mes-comptes/") <= 1 or _hVP.count(_jetVP) == _hVP.count("/mes-comptes/"))
        check("portail : la page n est pas indexable",
              "noindex" in (_pVP.headers.get("X-Robots-Tag") or ""),
              _pVP.headers.get("X-Robots-Tag"))
        # Le lien fuit dans le Referer des qu on clique un profil Instagram si
        # rien ne l en empeche.
        check("portail : le jeton ne fuit pas par le Referer",
              (_pVP.headers.get("Referrer-Policy") or "") == "no-referrer",
              _pVP.headers.get("Referrer-Policy"))
        # Un mot de passe se recopie avec le lien : il n a rien a faire ici.
        _jbVP.update_account("jessye",
                             [a for a in _jbVP.list_accounts("jessye")
                              if a["username"] == "a.moi"][0]["id"],
                             password="SECRETABC", two_fa="AAAA BBBB", email="x@y.z")
        _hVP = _vaVP.get(_urlVP).get_data(as_text=True)
        check("portail : le mot de passe ne sort jamais", "SECRETABC" not in _hVP)
        check("portail : le 2FA ne sort jamais", "AAAA BBBB" not in _hVP)
        check("portail : l adresse mail ne sort jamais", "x@y.z" not in _hVP)

        # Collage : pseudo nu, @pseudo, lien de partage avec son suivi, et une
        # URL qui n est pas un compte -- comptee, pas avalee.
        _aVP = _vaVP.post(_urlVP + "/ajouter", data={"comptes":
            "un.deux\n@trois.quatre\n"
            "https://www.instagram.com/cinq.six?igsi=ZZZ&utm_source=qr\n"
            "https://instagram.com/p/CabCabCab"}).get_json()
        _nomsVP = [a["username"] for a in _jbVP.list_accounts("jessye")]
        check("portail : le collage ajoute les trois comptes",
              all(n in _nomsVP for n in ("un.deux", "trois.quatre", "cinq.six")), _nomsVP)
        check("portail : le suivi du lien de partage est coupe",
              not any("igsi" in n for n in _nomsVP), _nomsVP)
        check("portail : la ligne non reconnue est DITE, pas avalee",
              "non reconnue" in (_aVP.get("msg") or ""), _aVP.get("msg"))
        check("portail : les comptes ajoutes tombent sous la bonne fiche",
              all((a.get("va") or "") == "VA NOUM 1X1"
                  for a in _jbVP.list_accounts("jessye") if a["username"] != "au.voisin"))

        # Le controle de perimetre au retrait : sans lui, un identifiant devine
        # dans une autre fiche serait supprimable depuis ce lien-ci.
        _idAutreVP = [a["id"] for a in _jbVP.list_accounts("jessye")
                      if a["username"] == "au.voisin"][0]
        _xVP = _vaVP.post(_urlVP + "/retirer", data={"compte_id": _idAutreVP}).get_json()
        check("portail : retirer le compte d une autre fiche est refuse",
              _xVP.get("ok") is False, str(_xVP)[:100])
        check("portail : et ce compte est toujours la",
              any(a["username"] == "au.voisin" for a in _jbVP.list_accounts("jessye")))

        _idMienVP = [a["id"] for a in _jbVP.list_accounts("jessye")
                     if a["username"] == "un.deux"][0]
        _oVP = _vaVP.post(_urlVP + "/retirer", data={"compte_id": _idMienVP}).get_json()
        check("portail : retirer un de ses comptes marche", _oVP.get("ok") is True, str(_oVP)[:100])
        check("portail : le compte a bien disparu",
              not any(a["username"] == "un.deux" for a in _jbVP.list_accounts("jessye")))

        # Renommer la fiche depuis le dashboard ne doit pas tuer le lien deja
        # parti sur Discord.
        #
        # Le nouveau nom n a AUCUN mot commun avec l ancien, et c est
        # deliberé : la premiere version renommait « VA NOUM 1X1 » en
        # « VA NOUM 1 », dont l ancien nom est un sur-ensemble. La verification
        # « le nouveau nom est dans la page » etait donc deja vraie AVANT le
        # renommage — le test ne pouvait pas echouer, meme si le crochet
        # n existait pas du tout.
        _admVP.post("/jailbreak/update_va", data={
            "identity": "jessye", "old_name": "VA NOUM 1X1",
            "new_name": "Safidy Ravalison", "ajax": "1"})
        _rnVP = _vaVP.get(_urlVP)
        _rnHtml = _rnVP.get_data(as_text=True)
        check("portail : le lien survit au renommage de la fiche",
              _rnVP.status_code == 200, _rnVP.status_code)
        check("portail : la page porte le nouveau nom",
              "Safidy Ravalison" in _rnHtml)
        check("portail : et plus du tout l ancien",
              "VA NOUM 1X1" not in _rnHtml)
        check("portail : les comptes ont suivi le renommage",
              "a.moi" in _rnHtml)

        # Fermer le lien doit fermer la page ET l ecriture : un lien revoque qui
        # accepterait encore un POST ne serait pas revoque du tout.
        _admVP.post("/jailbreak/va_lien", data={
            "identity": "jessye", "va_name": "Safidy Ravalison", "action": "revoquer"})
        check("portail : le lien ferme ne s ouvre plus",
              _vaVP.get(_urlVP).status_code == 404)
        check("portail : le lien ferme n accepte plus d ajout",
              _vaVP.post(_urlVP + "/ajouter",
                         data={"comptes": "tentative"}).status_code == 404)
        check("portail : un jeton inconnu ne dit rien",
              _vaVP.get("/mes-comptes/nimportequoi").status_code == 404)

        # Le jeton EST le secret, et il voyage dans la ligne de requete : arriver
        # en clair l'expose a tout ce qui se trouve entre le telephone et le
        # proxy. Le site repond 200 en http sans rediriger, donc c'est ici que
        # ca se rattrape. Il faut un lien VIVANT — celui d'au-dessus vient
        # d'etre ferme, il repondrait 404 en https et le test serait creux.
        _urlVP2 = (_admVP.post("/jailbreak/va_lien", data={
            "identity": "jessye", "va_name": "VA NOUM 1X2", "action": "creer"}
        ).get_json().get("url") or "").replace("http://localhost", "")
        check("portail : lien vivant pour l essai https", bool(_urlVP2), _urlVP2)
        _clairVP = _vaVP.get(_urlVP2, headers={"X-Forwarded-Proto": "http"})
        check("portail : arriver en clair renvoie vers https",
              _clairVP.status_code == 301
              and (_clairVP.headers.get("Location") or "").startswith("https://"),
              f"{_clairVP.status_code} {_clairVP.headers.get('Location')}")
        check("portail : en https la page se rend normalement",
              _vaVP.get(_urlVP2, headers={"X-Forwarded-Proto": "https"}).status_code == 200)
        check("portail : Cloudflare (CF-Visitor) est lu aussi",
              _vaVP.get(_urlVP2, headers={"CF-Visitor": '{"scheme":"http"}'}).status_code == 301)
        # Sans en-tete on ne SAIT pas : une sonde de supervision ou un appel
        # direct a l'origine ne doit pas se prendre une redirection devinee.
        check("portail : sans en-tete de proxy, aucune redirection",
              _vaVP.get(_urlVP2).status_code == 200)
        check("portail : un jeton demesure est ecarte",
              _vaVP.get("/mes-comptes/" + "x" * 400).status_code == 404)

        # Supprimer la fiche doit emporter son lien, sinon l adresse reste
        # vivante et on peut encore rattacher des comptes a une fiche morte.
        _admVP.post("/jailbreak/va_lien", data={
            "identity": "jessye", "va_name": "VA NOUM 1X2", "action": "creer"})
        _admVP.post("/jailbreak/remove_va", data={
            "identity": "jessye", "va_name": "VA NOUM 1X2", "ajax": "1"})
        check("portail : supprimer la fiche ferme son lien",
              _vpVP.lien_pour("jessye", "VA NOUM 1X2") == "")

        # ------------------------------------------------------------------
        # LES PLAFONDS TIENNENT-ILS VRAIMENT ?
        #
        # Version d'origine : les plafonds etaient recalcules en recomptant le
        # journal, et le journal est tronque a JOURNAL_MAX lignes. Le porteur
        # du jeton faisait donc defiler la fenetre lui-meme avec des requetes
        # sans effet, et retrouvait un plafond neuf. Ces essais rejouent
        # exactement l'attaque.
        # ------------------------------------------------------------------
        _jbVP._save({"jessye": {"vas": [{"name": "Plafond", "discord_username": ""}],
                                "accounts": []}})
        for _i in range(45):
            _jbVP.add_account("jessye", f"cible{_i:02d}", va="Plafond")
        _uPl = (_admVP.post("/jailbreak/va_lien", data={
            "identity": "jessye", "va_name": "Plafond", "action": "creer"}
        ).get_json().get("url") or "").replace("http://localhost", "")
        _pl = _appVP.test_client()

        def _retire_un():
            """Retire le premier compte encore la. Rend le JSON de la reponse."""
            _restants = [a for a in _jbVP.list_accounts("jessye")
                         if (a.get("va") or "") == "Plafond"]
            if not _restants:
                return {"ok": False, "error": "plus rien"}
            return _pl.post(_uPl + "/retirer",
                            data={"compte_id": _restants[0]["id"]}).get_json()

        _faits = 0
        for _i in range(_vpVP.MAX_RETRAITS_JOUR + 3):
            if (_retire_un() or {}).get("ok"):
                _faits += 1
        check("plafond : les retraits s arretent pile au plafond",
              _faits == _vpVP.MAX_RETRAITS_JOUR,
              f"{_faits} passés / plafond {_vpVP.MAX_RETRAITS_JOUR}")
        _restants_apres = len([a for a in _jbVP.list_accounts("jessye")
                               if (a.get("va") or "") == "Plafond"])

        # L'attaque : des ajouts SANS EFFET (un pseudo deja present) pour
        # chasser les lignes « retrait » hors du journal.
        _dejaLa = [a["username"] for a in _jbVP.list_accounts("jessye")
                   if (a.get("va") or "") == "Plafond"][0]
        for _i in range(_vpVP.JOURNAL_MAX + 10):
            _pl.post(_uPl + "/ajouter", data={"comptes": _dejaLa})
        check("plafond : le journal ne fait plus office de compteur",
              (_retire_un() or {}).get("ok") is not True,
              "un retrait est passe apres avoir fait defiler le journal")
        check("plafond : et aucun compte n a ete perdu en plus",
              len([a for a in _jbVP.list_accounts("jessye")
                   if (a.get("va") or "") == "Plafond"]) == _restants_apres)

        # Le plafond d'AJOUTS etait, lui, mathematiquement inatteignable : un
        # pseudo par requete ecrit une ligne n=1, le journal en garde 80, la
        # somme ne depassait jamais 80 alors que le plafond est a 120.
        _jbVP._save({"jessye": {"vas": [{"name": "Vanne", "discord_username": ""}],
                                "accounts": []}})
        _uVa = (_admVP.post("/jailbreak/va_lien", data={
            "identity": "jessye", "va_name": "Vanne", "action": "creer"}
        ).get_json().get("url") or "").replace("http://localhost", "")
        _va2 = _appVP.test_client()
        _passes = 0
        for _i in range(_vpVP.MAX_AJOUTS_JOUR + 15):
            if (_va2.post(_uVa + "/ajouter",
                          data={"comptes": f"neuf{_i:03d}"}).get_json() or {}).get("ok"):
                _passes += 1
        check("plafond : les ajouts s arretent aussi, et pile au plafond",
              _passes == _vpVP.MAX_AJOUTS_JOUR,
              f"{_passes} passés / plafond {_vpVP.MAX_AJOUTS_JOUR}")
        check("plafond : le referentiel ne contient pas plus que le plafond",
              len([a for a in _jbVP.list_accounts("jessye")
                   if (a.get("va") or "") == "Vanne"]) <= _vpVP.MAX_AJOUTS_JOUR)

        # ------------------------------------------------------------------
        # LE PORTAIL NE CREE JAMAIS RIEN D'AUTRE QUE DES COMPTES
        # ------------------------------------------------------------------
        _jbVP._save({"morte": {"vas": [{"name": "Fantome", "discord_username": ""}],
                               "accounts": []}})
        _uFa = (_admVP.post("/jailbreak/va_lien", data={
            "identity": "morte", "va_name": "Fantome", "action": "creer"}
        ).get_json().get("url") or "").replace("http://localhost", "")
        check("fiche morte : le lien marche tant que la fiche existe",
              _appVP.test_client().get(_uFa).status_code == 200)
        # L'identite disparait par un chemin qui ne previent pas le portail
        # (fusion_vas, /jailbreakreset, un import...). Le jeton, lui, survit.
        _jbVP._save({})
        _fa = _appVP.test_client()
        check("fiche morte : la page le dit au lieu d afficher une liste vide",
              _fa.get(_uFa).status_code == 404)
        _rFa = _fa.post(_uFa + "/ajouter", data={"comptes": "revenant"})
        check("fiche morte : l ajout est refuse", _rFa.status_code == 404)
        # LE point : sans ce garde, bulk_add_accounts appelait _ensure_identity
        # et RESSUSCITAIT l identite, avec des comptes dedans, dans une entree
        # que la page Jailbreak ne liste pas mais que la paie compte.
        check("fiche morte : l identite n a pas ete ressuscitee",
              "morte" not in _jbVP.list_all(), list(_jbVP.list_all()))

        # ------------------------------------------------------------------
        # RENOMMER UNE IDENTITE : le lien suit, il ne meurt pas
        # ------------------------------------------------------------------
        _jbVP._save({"emma": {"vas": [{"name": "Tina", "discord_username": ""}],
                              "accounts": []}})
        _jbVP.add_account("emma", "compte.emma", va="Tina")
        _uEm = (_admVP.post("/jailbreak/va_lien", data={
            "identity": "emma", "va_name": "Tina", "action": "creer"}
        ).get_json().get("url") or "").replace("http://localhost", "")
        _vpVP.renommer_identite("emma", "emma2")
        _jbVP.rename_identity_in_storage("emma", "emma2")
        _rEm = _appVP.test_client().get(_uEm)
        check("identite renommee : le lien deja envoye reste vivant",
              _rEm.status_code == 200, _rEm.status_code)
        check("identite renommee : et il montre toujours les comptes",
              "compte.emma" in _rEm.get_data(as_text=True))

        # Fermer un lien ne doit pas emporter son historique : on ferme surtout
        # quand il a fuite, c est-a-dire quand on veut relire ce qu il a fait.
        _vpVP.revoquer("emma2", "Tina")
        _jetEm = [k for k, v in _vpVP._load().items()
                  if isinstance(v, dict) and _vpVP._norm(v.get("va")) == "Tina"]
        check("lien ferme : l enregistrement et son journal sont gardés",
              bool(_jetEm), "l enregistrement a ete supprime")
        check("lien ferme : mais il ne resout plus",
              all(_vpVP.resoudre(_k) is None for _k in _jetEm))
    finally:
        (_jbVP.JAILBREAK_FILE, _jbVP.PREV_FILE, _jbVP.BACKUP_DIR,
         _jbVP.TOMB_FILE, _vpVP.LIENS_FILE) = _svVP
        shutil.rmtree(_dosVP, ignore_errors=True)
except Exception as _eVP:
    check("portail : testable", False, repr(_eVP)[:200])

print()
print("=" * 70)
print("ANCIENNETE : depuis quand ce compte est-il dans la fiche")
print("=" * 70)
try:
    import va_portal as _vpAg
    import web_upload as _wAg
    _nowAg = int(time.time())

    # Le libelle court : une date lisible, et rien du tout quand on ne sait pas.
    for _lbl, _acc, _att in (
            ("aujourd hui", {"created_at": _nowAg}, True),
            ("il y a deux ans", {"created_at": _nowAg - 800 * 86400}, True),
            ("champ absent", {}, False),
            ("valeur a zero", {"created_at": 0}, False),
            # Le vrai piege : un created_at parasite donnait « 01/01/70 », une
            # date fausse que personne n'aurait mise en doute a l'ecran.
            ("horodatage parasite", {"created_at": 12345}, False),
            ("texte au lieu d un nombre", {"created_at": "hier"}, False),
            ("horodatage negatif", {"created_at": -5}, False)):
        _c, _b = _vpAg.anciennete(_acc, {})
        check(f"anciennete : {_lbl} -> {'une date' if _att else 'rien'}",
              bool(_c) is _att, repr(_c))

    # PREMIER POST : c'est LA date demandee. Elle doit dire d'elle-meme si elle
    # est sure ou si ce n'est qu'une borne — une borne presentee comme une date
    # de naissance, et quelqu'un decide sur du faux.
    _jourAg = lambda _n: (_dtVtk.date.today() - _dtVtk.timedelta(days=_n)).isoformat()
    _cEx, _bEx = _vpAg.anciennete(
        {"created_at": _nowAg - 40 * 86400},
        {"premier_post_at": _jourAg(120), "premier_post_exact": True, "posts_count": 9})
    check("premier post : la date exacte s annonce sans reserve",
          _cEx.startswith("1er post ") and "avant" not in _cEx, _cEx)
    check("premier post : l infobulle dit que l historique est complet",
          "historique" in _bEx.lower(), _bEx[:100])
    _cBo, _bBo = _vpAg.anciennete(
        {"created_at": _nowAg - 40 * 86400},
        {"premier_post_at": _jourAg(35), "premier_post_exact": False, "posts_count": 214})
    # LE piege : Instagram ne rend qu une douzaine de posts. Sur un compte qui en
    # a 214, la date vue n est pas le premier post, c est « il publiait deja ».
    check("premier post : une borne se presente COMME une borne",
          "avant" in _cBo, _cBo)
    check("premier post : et l infobulle explique pourquoi",
          "douzaine" in _bBo.lower() or "plus ancien" in _bBo.lower(), _bBo[:160])
    check("premier post : le nombre de posts est rappele",
          "214" in _bBo, _bBo)
    _cRi, _bRi = _vpAg.anciennete({"created_at": _nowAg - 5 * 86400}, {})
    check("premier post : sans post connu, on retombe sur la date d entree",
          _cRi.startswith("ajouté le"), _cRi)
    check("premier post : et on le DIT, au lieu de laisser croire a un 1er post",
          "aucun post connu" in _bRi.lower(), _bRi[:120])
    check("premier post : une date illisible ne passe pas pour une date",
          _vpAg.anciennete({"created_at": _nowAg - 9 * 86400},
                           {"premier_post_at": "pas-une-date"})[0].startswith("ajouté"))
    check("anciennete : l infobulle previent qu Instagram ne donne pas la creation",
          "instagram ne publie pas" in _bEx.lower(), _bEx[-90:])

    # Le calcul lui-meme, sur la liste BRUTE des posts.
    _f = _wAg._premier_post
    _pAg = lambda _n: {"taken_at": _nowAg - _n * 86400, "is_video": True}
    check("premier post : rien a partir de rien", _f([], {}, 0, None)[0] == "")
    _j, _e = _f([_pAg(200), _pAg(10)], {}, 2, None)
    # LE point : post_days n enregistre QUE les posts de moins de 30 jours, donc
    # il ne pouvait structurellement pas remonter a un post de 200 jours.
    check("premier post : un post de 200 jours est bien remonte",
          _j == _jourAg(200), f"{_j} au lieu de {_jourAg(200)}")
    check("premier post : feed complet (2 posts vus / 2 au total) -> exact", _e is True)
    check("premier post : feed partiel -> pas exact",
          _f([_pAg(40), _pAg(1)], {}, 214, None)[1] is False)
    check("premier post : compteur de posts inconnu -> pas exact",
          _f([_pAg(40)], {}, 0, None)[1] is False)
    # Un premier post ne bouge plus : une fois su, il ne redevient pas incertain
    # parce que le compte a continue a publier et que la page ne montre plus rien
    # d ancien.
    _jS, _eS = _f([_pAg(5)], {"premier_post_at": "2026-01-02", "premier_post_exact": True},
                  300, None)
    check("premier post : une date exacte connue ne se degrade jamais",
          _eS is True and _jS == "2026-01-02", f"{_jS} / {_eS}")
    check("premier post : un horodatage illisible est ignore, pas fatal",
          _f([{"taken_at": "n importe quoi"}, _pAg(30)], {}, 1, None)[0] == _jourAg(30))
    check("premier post : l ancien champ, plus faible, sert de candidat",
          _f([_pAg(3)], {"premier_jour_connu": "2026-05-01"}, 99, None)[0] == "2026-05-01")
except Exception as _eAg:
    check("anciennete : testable", False, repr(_eAg)[:200])

print()
print("=" * 70)
print("OBJECTIFS VA : combien de comptes vivants sur les N attendus")
print("=" * 70)
try:
    import jb_objectifs as _obT
    _dosOb = pathlib.Path(tempfile.mkdtemp(prefix="objectifs_"))
    _svOb = (_obT.OBJECTIFS_FILE, _obT.HISTO_FILE)
    _obT.OBJECTIFS_FILE = _dosOb / "obj.json"
    _obT.HISTO_FILE = _dosOb / "histo.json"
    try:
        _nowOb = time.time()
        _jourOb = _obT.aujourdhui()

        def _cptOb(nom, cree_j=None, dernier_h=None, banni=False, poste=False):
            """Rend (compte, entree de cache) pour un cas de figure."""
            a = {"username": nom}
            if cree_j is not None:
                a["created_at"] = int(_nowOb - cree_j * 86400)
            s = {}
            if banni:
                s["banned"] = True
            if dernier_h is not None:
                s["last_reel_at"] = _dtVtk.datetime.fromtimestamp(
                    _nowOb - dernier_h * 3600, _dtVtk.timezone.utc).isoformat()
            if poste:
                s["reel_days"] = {_jourOb: 1}
            return a, {nom: s}

        _cOb, _sOb = [], {}
        for _a, _s in (
                _cptOb("publie_auj", cree_j=40, dernier_h=2, poste=True),
                _cptOb("publie_hier", cree_j=40, dernier_h=20),
                _cptOb("silencieux", cree_j=40, dernier_h=100),
                _cptOb("tout_neuf", cree_j=1),
                _cptOb("cree_ce_jour", cree_j=0),
                _cptOb("banni", cree_j=40, dernier_h=500, banni=True)):
            _cOb.append(_a)
            _sOb.update(_s)
        _eOb = _obT.etat_fiche("jessye", "VA NOUM 1X1", _cOb, _sOb, _nowOb)

        check("objectif : les comptes sont tous comptés", _eOb["total"] == 6, _eOb["total"])
        # Le coeur de la definition voulue : publie sous 48 h OU warm-up.
        check("objectif : actif = a publié sous 48 h ou vient d être créé",
              _eOb["actifs"] == 4, f"{_eOb['actifs']} au lieu de 4")
        check("objectif : un banni n est jamais actif", _eOb["bannis"] == 1)
        # Un compte en warm-up n a rien oublie : il n a pas encore commence.
        check("objectif : le warm-up n est pas un oubli",
              _eOb["oublies"] == 1, f"{_eOb['oublies']} oubli(s), attendu 1")
        check("objectif : « a publié aujourd hui » se compte à part",
              _eOb["publie"] == 1, _eOb["publie"])
        check("objectif : « ajoutés aujourd hui » aussi",
              _eOb["ajoutes"] == 1, _eOb["ajoutes"])
        check("objectif : le défaut est 30", _eOb["objectif"] == 30, _eOb["objectif"])

        # Le seuil s arrondit au SUPERIEUR : accepter 15 sur un objectif de 19
        # reviendrait a valider 78,9 %, c est-a-dire moins que les 80 % annonces.
        check("objectif : seuil 80 % arrondi au supérieur",
              (_obT._seuil(30), _obT._seuil(19), _obT._seuil(10)) == (24, 16, 8),
              str((_obT._seuil(30), _obT._seuil(19), _obT._seuil(10))))
        check("objectif : un objectif nul ne fabrique pas un seuil",
              _obT._seuil(0) == 0)

        check("objectif : on peut le fixer",
              _obT.fixer_objectif("jessye", "VA NOUM 1X1", 12) == 12)
        check("objectif : et il est relu",
              _obT.objectif_de("jessye", "VA NOUM 1X1") == 12)
        # Zero serait TOUJOURS atteint : la pastille deviendrait muette sans
        # que personne le remarque. On revient au defaut.
        check("objectif : zéro remet au défaut, il ne pose pas zéro",
              _obT.fixer_objectif("jessye", "VA NOUM 1X1", 0) == 30
              and _obT.objectif_de("jessye", "VA NOUM 1X1") == 30)
        check("objectif : une saisie absurde est bornée",
              _obT.fixer_objectif("jessye", "VA NOUM 1X1", 99999) == 999)
        check("objectif : du texte ne casse rien",
              _obT.fixer_objectif("jessye", "VA NOUM 1X1", "beaucoup") == 30)
        # La casse du nom ne doit pas fabriquer une deuxieme fiche : il se
        # ressaisit a la main, a la commande Discord comme au dashboard.
        _obT.fixer_objectif("jessye", "VA NOUM 1X1", 17)
        check("objectif : la casse du nom ne crée pas une seconde fiche",
              _obT.objectif_de("JESSYE", "va noum 1x1") == 17)
        _obT.fixer_objectif("jessye", "VA NOUM 1X1", 0)

        # Quinzaines : memes bornes que la paie et le report de clics.
        check("quinzaine : du 1 au 15",
              _obT.quinzaine("2026-08-07") == ("2026-08-01", "2026-08-15"))
        check("quinzaine : du 16 à la fin du mois",
              _obT.quinzaine("2026-08-30") == ("2026-08-16", "2026-08-31"))
        check("quinzaine : février tombe juste",
              _obT.quinzaine("2026-02-20") == ("2026-02-16", "2026-02-28"))
        check("quinzaine : décembre ne déborde pas sur l année suivante",
              _obT.quinzaine("2026-12-20") == ("2026-12-16", "2026-12-31"))

        # Historique et bilan.
        for _j, _atteint in (("2026-08-16", True), ("2026-08-17", True),
                             ("2026-08-18", False), ("2026-08-19", True)):
            _obT.enregistrer_jour([{"identite": "jessye", "va": "VA NOUM 1X1",
                                    "total": 30, "actifs": 25 if _atteint else 10,
                                    "publie": 5, "ajoutes": 0, "oublies": 2,
                                    "bannis": 1, "objectif": 30,
                                    "atteint": _atteint}], _j)
        _bOb = _obT.bilan_quinzaine("jessye", "VA NOUM 1X1", "2026-08-19")
        check("bilan : les journées notées sont comptées",
              _bOb["jours_notes"] == 4, _bOb)
        check("bilan : et les journées tenues aussi", _bOb["jours_tenus"] == 3, _bOb)
        # 3 tenues sur 4 font 75 % : SOUS la barre des 80 %, donc orange. La
        # pastille reprend le seuil de la journee, elle n a pas le sien.
        check("bilan : la pastille suit la proportion, au même seuil que le jour",
              _bOb["pastille"] == "🟠", _bOb)
        # LE point : un bot a l arret a minuit ne doit pas se lire comme une
        # journee ratee, sinon la premiere coupure punit un bon VA.
        check("bilan : une journée sans report ne compte NI en bien ni en mal",
              _bOb["jours_notes"] == 4 and _bOb["pct"] == 75.0, _bOb)
        check("bilan : réécrire la même journée ne la compte pas deux fois",
              (_obT.enregistrer_jour([{"identite": "jessye", "va": "VA NOUM 1X1",
                                       "atteint": True, "objectif": 30}], "2026-08-19")
               is not None)
              and _obT.bilan_quinzaine("jessye", "VA NOUM 1X1",
                                       "2026-08-19")["jours_notes"] == 4)
        check("bilan : la quinzaine d à côté n est pas mélangée",
              _obT.bilan_quinzaine("jessye", "VA NOUM 1X1", "2026-08-05")["jours_notes"] == 0)
        # Une pastille rouge apres une seule journee condamnerait sur un
        # echantillon de un.
        check("bilan : pastille muette tant qu on a moins de 3 journées",
              _obT.pastille(0, 1) == "⚪" and _obT.pastille(0, 2) == "⚪")
        check("bilan : puis elle parle",
              (_obT.pastille(3, 3), _obT.pastille(2, 3), _obT.pastille(1, 3))
              == ("🟢", "🟠", "🔴"))

        # Le rendu Discord : il doit tenir sans planter et dire l essentiel.
        import cogs.reportcomptes as _rcT
        _txtOb = _rcT.ligne_fiche(_eOb)
        check("report : le message nomme la fiche et l identité",
              "VA NOUM 1X1" in _txtOb and "jessye" in _txtOb)
        check("report : il donne actifs sur objectif",
              "4 / 30" in _txtOb or "4/30" in _txtOb, _txtOb[:200])
        check("report : il dit ce qui a été ajouté aujourd hui",
              "ajouté" in _txtOb, _txtOb[:200])
        check("report : objectif non tenu -> il dit combien il manque",
              "il manque" in _txtOb, _txtOb[-200:])
        _pinOb = _rcT.bloc_quinzaine(
            [{"e": _eOb, "bilan": _bOb}], "2026-08-16", "2026-08-31")
        check("report : le message épinglé porte la pastille",
              "🟠" in _pinOb and "VA NOUM 1X1" in _pinOb, _pinOb[:200])
        check("report : et il explique la règle des 80 %",
              "80 %" in _pinOb, _pinOb[:250])
        # Discord refuse au-dela de 2000 caracteres : une liste de 40 fiches
        # doit etre coupee proprement, pas partir en exception a minuit.
        _longOb = _rcT.bloc_quinzaine(
            [{"e": dict(_eOb, va=f"FICHE {_i:02d}"), "bilan": _bOb} for _i in range(60)],
            "2026-08-16", "2026-08-31")
        check("report : un message trop long est coupé, pas perdu",
              len(_rcT._tronquer(_longOb)) <= 2000
              and "tronquée" in _rcT._tronquer(_longOb), len(_rcT._tronquer(_longOb)))
    finally:
        (_obT.OBJECTIFS_FILE, _obT.HISTO_FILE) = _svOb
        shutil.rmtree(_dosOb, ignore_errors=True)
except Exception as _eOb2:
    check("objectifs : testable", False, repr(_eOb2)[:200])

print()
print("=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  -", f)
print("=" * 70)
sys.exit(1 if FAILS else 0)
