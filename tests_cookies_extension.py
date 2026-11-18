"""Les cookies GetMySocial et MyPuls remis au site par l'extension Chrome.

Propriétaire, 18/11/2026 : « un tools, quand je clique, ça me prend les
cookies dont tu as besoin, soit pour GMS, soit pour MyPuls ». L'extension
(extension_cookies/) fait passer les cookies du navigateur à youl4b.com ; ce
fichier prouve surtout ce qui ne doit PAS arriver.
  1. Le REMEMBERME de MyPuls : son compte (une empreinte) et son échéance.
  2. La remise : le cookie est essayé AVANT d'être enregistré ; celui d'un
     autre compte, un cookie échu ou refusé par MyPuls ne touchent à rien.
  3. Le renouvellement automatique note un refus de MyPuls, pas une panne.
  4. GetMySocial : le compte du jeton, l'échéance inchangée.
  5. Les routes : sans compte 401, rôle restreint 403, le formulaire collé
     de Réglages marche comme avant, aucune valeur ne ressort nulle part.
  6. Réglages : l'état des deux cookies au même endroit, en phrases.
  7. L'extension : permissions strictes, pas de script en ligne, et ses
     décisions jouées dans un faux Chrome (tests_cookies_extension.js).

Sans réseau (MyPuls est simulé) et sans rien écrire dans le vrai data/.
Lancer depuis la racine du dépôt : python tests_cookies_extension.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


VRAIS = [BOT / "data" / n for n in ("mypuls_cookies.json", "gms_config.json")]
AVANT = {str(p): (p.stat().st_mtime if p.exists() else None) for p in VRAIS}

import requests                 # noqa: E402
import gms                      # noqa: E402
import mypuls                   # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="cookies_extension_"))
mypuls.CONFIG_FILE = TMP / "mypuls_cookies.json"
mypuls.DATA_DIR = TMP
gms.CONFIG_FILE = TMP / "gms_config.json"
gms.DATA_DIR = TMP
gms.teams_via_api = lambda *a, **k: []          # la section MyPuls de Réglages l'appelle : pas de réseau

MAINTENANT = int(time.time())
JOUR = 86400


# Des valeurs FABRIQUÉES pour ce test : aucune n'a jamais existé.
def rem(compte, exp, signature="SIGNATUREFABRIQUEE"):
    b64 = base64.b64encode(compte.encode()).decode().replace("=", "~")
    return f"App.Entity.User%3A{b64}%3A{exp}%3A{signature}{compte[:3]}"


def jeton(compte, exp, emis=None):
    def b64(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
    return (b64({"alg": "HS256"}) + "."
            + b64({"id": compte, "sessionId": "s-" + compte, "iat": emis or exp - 30 * JOUR, "exp": exp})
            + ".SIGNATUREFABRIQUEE" + compte)


# le cookie du site : 5 jours devant lui (à 2 jours, Réglages s'inquiète)
EXP_A = MAINTENANT + 5 * JOUR + 3600
REM_A = rem("agence@exemple.fr", EXP_A)
REM_A_NAVIGATEUR = rem("agence@exemple.fr", MAINTENANT + 6 * JOUR, "AUTRESIGNATUREFABRIQUEE")
REM_A_PROLONGE = rem("agence@exemple.fr", MAINTENANT + 7 * JOUR, "SIGNATUREPROLONGEE")
REM_B = rem("chatteur@exemple.fr", MAINTENANT + 6 * JOUR)
PHP_VIEUX, PHP_NEUF = "a" * 32, "b" * 32
GMS_A = jeton("compteA000000000000000000", MAINTENANT + 19 * JOUR + 3600)
GMS_A2 = jeton("compteA000000000000000000", MAINTENANT + 29 * JOUR)
GMS_B = jeton("compteB000000000000000000", MAINTENANT + 25 * JOUR)
SECRETS = [REM_A, REM_A_NAVIGATEUR, REM_A_PROLONGE, REM_B, PHP_VIEUX, PHP_NEUF, GMS_A, GMS_A2, GMS_B,
           "SIGNATUREFABRIQUEE", "agence@exemple.fr", "chatteur@exemple.fr",
           base64.b64encode(b"agence@exemple.fr").decode().rstrip("="), "compteA0000", "compteB0000"]


def sans_secret(texte):
    return [s[:14] + "…" for s in SECRETS if s in texte]


def config_mypuls(**champs):
    mypuls.save_config(dict(champs))


def lue():
    return mypuls.load_config()


# MyPuls simulé : ce que _essai_profil a reçu, et ce qu'il répond.
ESSAIS = []
REPONSE = {"mode": "accepte", "session": PHP_NEUF, "prolonge": REM_A_PROLONGE, "pendant": None}


def faux_essai(cookies, timeout=30):
    ESSAIS.append(dict(cookies))
    if REPONSE["pendant"]:
        REPONSE["pendant"]()
    if REPONSE["mode"] == "refuse":
        return {"ok": False, "refuse": True, "error": "Cookies expirés ou révoqués"}
    if REPONSE["mode"] == "panne":
        return {"ok": False, "refuse": False, "error": "MyPuls a répondu HTTP 503"}
    s = requests.Session()
    for nom, v in cookies.items():
        s.cookies.set(nom, v, domain="mypuls.app", path="/")
    if REPONSE["prolonge"]:
        s.cookies.set("REMEMBERME", REPONSE["prolonge"], domain="mypuls.app", path="/")
    if REPONSE["session"]:
        s.cookies.set("PHPSESSID", REPONSE["session"], domain="mypuls.app", path="/")
    return {"ok": True, "session": s}


def remise(mode="accepte", session=PHP_NEUF, prolonge=REM_A_PROLONGE, pendant=None):
    ESSAIS.clear()
    REPONSE.update(mode=mode, session=session, prolonge=prolonge, pendant=pendant)


_VRAI_ESSAI, _VRAI_PING = mypuls._essai_profil, mypuls.ping
mypuls._essai_profil = faux_essai
mypuls.ping = lambda: {"ok": True, "email": "agence@exemple.fr"}

print("1. Le REMEMBERME : compte et échéance")
check("l'échéance se lit dans le cookie (écrit %3A)", mypuls.echeance_rememberme(REM_A) == EXP_A,
      mypuls.echeance_rememberme(REM_A))
check("écrit avec des deux-points bruts : pareil",
      mypuls.echeance_rememberme(REM_A.replace("%3A", ":")) == EXP_A
      and mypuls.compte_rememberme(REM_A.replace("%3A", ":")) == mypuls.compte_rememberme(REM_A))
check("même compte, autre échéance et autre signature : même empreinte",
      mypuls.compte_rememberme(REM_A) == mypuls.compte_rememberme(REM_A_NAVIGATEUR) != "")
check("autre compte : autre empreinte", mypuls.compte_rememberme(REM_B) not in ("", mypuls.compte_rememberme(REM_A)))
_e = mypuls.compte_rememberme(REM_A)
check("l'empreinte fait 16 caractères et ne contient rien du cookie",
      len(_e) == 16 and all(c in "0123456789abcdef" for c in _e) and not sans_secret(_e), _e)
_sf6 = "YWdlbmNl:%d:SIGNATUREFABRIQUEE" % (MAINTENANT + JOUR)
check("forme sans la classe (Symfony 6) : lue aussi", mypuls.echeance_rememberme(_sf6) == MAINTENANT + JOUR
      and mypuls.compte_rememberme(_sf6) != "")
check("cookie illisible ou vide : ni compte ni échéance, pas d'erreur",
      all(mypuls.compte_rememberme(v) == "" and mypuls.echeance_rememberme(v) is None
          for v in ("", "n-importe-quoi", "a:b:c:d", "App.Entity.User%3Ax%3Apas-une-date%3Ay", None and "")))

print("2. La remise par l'extension")
config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, last_refreshed=MAINTENANT - 9 * 3600,
              cookies_refuses=MAINTENANT - 3600, api_token="jeton-api-garde")
remise()
r = mypuls.remettre_rememberme(REM_A_NAVIGATEUR)
c = lue()
check("même compte : accepté", r.get("ok") is True and r.get("compte_change") is False, r)
check("MyPuls n'a reçu QUE le REMEMBERME du navigateur (sans l'ancienne session)",
      ESSAIS == [{"REMEMBERME": REM_A_NAVIGATEUR}], [sorted(e) for e in ESSAIS])
check("le site garde le REMEMBERME prolongé par MyPuls, pas celui du navigateur",
      c.get("REMEMBERME") == REM_A_PROLONGE, sans_secret(c.get("REMEMBERME", "")))
check("et la session NEUVE que MyPuls lui a ouverte", c.get("PHPSESSID") == PHP_NEUF)
check("la marque « refusé » est levée, le renouvellement daté de maintenant",
      "cookies_refuses" not in c and abs(c.get("last_refreshed", 0) - time.time()) < 5, c.get("last_refreshed"))
check("le reste de la configuration n'a pas bougé (clé API)", c.get("api_token") == "jeton-api-garde")
check("l'échéance rendue est celle du cookie prolongé", r.get("expire") == MAINTENANT + 7 * JOUR, r.get("expire"))
check("la réponse ne porte aucune valeur", not sans_secret(json.dumps(r)), sans_secret(json.dumps(r)))

config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, last_refreshed=MAINTENANT - 9 * 3600)
avant = mypuls.CONFIG_FILE.read_bytes()
remise()
r = mypuls.remettre_rememberme(REM_B)
check("autre compte dans Chrome : refusé, dit « autre compte »", r.get("ok") is False and r.get("autre_compte") is True, r)
check("MyPuls n'a même pas été appelé, le fichier est intact à l'octet", ESSAIS == [] and mypuls.CONFIG_FILE.read_bytes() == avant)
remise(session="", prolonge=None)
r = mypuls.remettre_rememberme(REM_B, forcer=True)
c = lue()
check("forcé : le compte du site est remplacé", r.get("ok") is True and r.get("compte_change") is True
      and c.get("REMEMBERME") == REM_B, r)
check("MyPuls n'a pas rendu de session : l'ancienne (celle de l'ancien compte) est retirée", "PHPSESSID" not in c, sorted(c))

for mode, attendu in (("refuse", "MyPuls refuse ce cookie"), ("panne", "503")):
    config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, last_refreshed=MAINTENANT - 9 * 3600)
    avant = mypuls.CONFIG_FILE.read_bytes()
    remise(mode=mode)
    r = mypuls.remettre_rememberme(REM_A_NAVIGATEUR)
    check(f"MyPuls « {mode} » : rien n'est enregistré, et c'est dit",
          r.get("ok") is False and attendu in r.get("error", "") and mypuls.CONFIG_FILE.read_bytes() == avant
          and bool(r.get("panne")) == (mode == "panne"), r)
remise()
avant = mypuls.CONFIG_FILE.read_bytes()
echu = mypuls.remettre_rememberme(rem("agence@exemple.fr", MAINTENANT - 60))
illisible = mypuls.remettre_rememberme("pas-un-cookie")
vide = mypuls.remettre_rememberme("")
check("cookie échu, illisible ou vide : refusé sans appeler MyPuls ni rien écrire",
      not echu["ok"] and "échu" in echu["error"] and not illisible["ok"] and not vide["ok"]
      and ESSAIS == [] and mypuls.CONFIG_FILE.read_bytes() == avant, (echu, illisible, vide))
config_mypuls(api_token="jeton-api-garde")
remise()
r = mypuls.remettre_rememberme(REM_A_NAVIGATEUR)
check("le site n'avait aucun cookie : accepté sans comparaison de compte", r.get("ok") is True
      and lue().get("REMEMBERME") == REM_A_PROLONGE and lue().get("PHPSESSID") == PHP_NEUF, r)
config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A)
remise(prolonge=None)
r = mypuls.remettre_rememberme(REM_A_NAVIGATEUR)
check("MyPuls ne prolonge pas le cookie : celui du navigateur est gardé tel quel",
      r.get("ok") is True and lue().get("REMEMBERME") == REM_A_NAVIGATEUR)

print("3. Le renouvellement automatique")
config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, last_refreshed=MAINTENANT - 13 * 3600)
remise(mode="refuse")
r = mypuls.auto_refresh()
premier = lue().get("cookies_refuses")
check("MyPuls rend sa page de connexion : le refus est daté", r.get("ok") is False and premier
      and abs(premier - time.time()) < 5 and ESSAIS == [{"REMEMBERME": REM_A}], (r, premier))
c = lue()
c["cookies_refuses"] = MAINTENANT - 5 * 3600
mypuls.save_config(c)
mypuls.auto_refresh()
check("un deuxième refus garde la date du PREMIER", lue().get("cookies_refuses") == MAINTENANT - 5 * 3600)
etat = mypuls.cookies_etat()
check("l'état : présent, refusé depuis, échéance, sans aucune valeur",
      etat["present"] and etat["rememberme"] and etat["refuse_depuis"] == MAINTENANT - 5 * 3600
      and etat["expire"] == EXP_A and not sans_secret(json.dumps(etat)), etat)
remise()
r = mypuls.auto_refresh()
check("un renouvellement réussi lève le refus et garde le cookie prolongé",
      r == {"ok": True, "rotated": True} and "cookies_refuses" not in lue() and lue().get("REMEMBERME") == REM_A_PROLONGE, r)
config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A)
remise(mode="panne")
r = mypuls.auto_refresh()
check("une panne de MyPuls (503) n'est PAS un refus", r.get("ok") is False and "503" in r.get("error", "")
      and "cookies_refuses" not in lue(), (r, sorted(lue())))


def _remis_pendant():
    c2 = lue()
    c2["REMEMBERME"], c2["PHPSESSID"] = REM_B, PHP_NEUF
    mypuls.save_config(c2)


remise(mode="refuse", pendant=_remis_pendant)
r = mypuls.auto_refresh()
check("cookie remis PENDANT le renouvellement : ni marqué refusé, ni écrasé par l'ancien",
      lue().get("REMEMBERME") == REM_B and "cookies_refuses" not in lue() and r.get("ok") is True, (r, sorted(lue())))
remise(pendant=_remis_pendant)
config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A)
mypuls.auto_refresh()
check("… même quand l'ancien venait d'être prolongé", lue().get("REMEMBERME") == REM_B and lue().get("PHPSESSID") == PHP_NEUF)
config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, cookies_refuses=MAINTENANT - 60)
mypuls.save_cookies(PHP_NEUF, REM_A_NAVIGATEUR)
check("des cookies collés à la main lèvent aussi la marque « refusé »",
      "cookies_refuses" not in lue() and lue().get("PHPSESSID") == PHP_NEUF and lue().get("REMEMBERME") == REM_A_NAVIGATEUR)
config_mypuls()
remise()
r = mypuls.auto_refresh()
check("sans REMEMBERME : comme avant, « refresh impossible », MyPuls pas appelé",
      r == {"ok": False, "error": "REMEMBERME non configuré — refresh impossible"} and ESSAIS == [], r)
e = mypuls.cookies_etat()
check("l'état d'un site sans cookie", e == {"present": False, "rememberme": False, "expire": None,
                                           "renouvele": None, "refuse_depuis": None}, e)

print("3 bis. Ce que MyPuls répond : refus, panne ou accord")
# le VRAI _essai_profil, avec un faux réseau : c'est lui qui décide si une
# réponse de MyPuls est un refus (cookie mort) ou une panne (on ne sait pas)


class _Reponse:
    def __init__(self, statut, texte="", url="https://mypuls.app/profil"):
        self.status_code, self.text, self.url = statut, texte, url


VUES, SUITE = [], [None]


def _faux_get(self, url, **kw):
    VUES.append((url, {c.name: c.value for c in self.cookies}, kw.get("timeout"), kw.get("allow_redirects")))
    if isinstance(SUITE[0], Exception):
        raise SUITE[0]
    return SUITE[0]


def essai_reel(reponse, **kw):
    VUES.clear()
    SUITE[0] = reponse
    return _VRAI_ESSAI({"REMEMBERME": REM_A_NAVIGATEUR}, **kw)


_vrai_get = requests.Session.get
requests.Session.get = _faux_get
config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A)
avant = mypuls.CONFIG_FILE.read_bytes()
try:
    r = essai_reel(_Reponse(200, "<html><title>Mon profil</title><body>Tableau de bord</body></html>"), timeout=15)
    check("la page de profil : accord, et la session est rendue", r.get("ok") is True and r.get("session") is not None, r)
    check("MyPuls n'a reçu que les cookies donnés, sur /profil, avec le délai demandé",
          VUES == [("https://mypuls.app/profil", {"REMEMBERME": REM_A_NAVIGATEUR}, 15, True)],
          [(v[0], sorted(v[1]), v[2], v[3]) for v in VUES])
    for libelle, rep in (("la page de connexion", _Reponse(200, "<html><title>Connexion</title></html>")),
                         ("un formulaire de connexion", _Reponse(200, '<form><input name="login"></form>')),
                         ("un 401", _Reponse(401, "non"))):
        r = essai_reel(rep)
        check(f"{libelle} : c'est un REFUS", r.get("ok") is False and r.get("refuse") is True, r)
    for libelle, rep, mot in (("un 503 (maintenance)", _Reponse(503, "indisponible"), "503"),
                              ("un 403 (pare-feu)", _Reponse(403, "bloqué"), "403"),
                              ("le réseau coupé", OSError("coupé"), "Erreur réseau")):
        r = essai_reel(rep)
        check(f"{libelle} : une PANNE, pas un refus", r.get("ok") is False and r.get("refuse") is False
              and mot in r.get("error", ""), r)
    check("un essai n'écrit rien", mypuls.CONFIG_FILE.read_bytes() == avant)
finally:
    requests.Session.get = _vrai_get

print("4. GetMySocial : le compte du jeton")
check("l'échéance se lit comme avant (valeur seule, cookie nommé, en-tête entier)",
      gms.cookie_expiration("authToken=" + GMS_A) == MAINTENANT + 19 * JOUR + 3600
      and gms.cookie_expiration("autre=1; authToken=" + GMS_A + "; x=2") == MAINTENANT + 19 * JOUR + 3600
      and gms.cookie_expiration(gms.normaliser_cookie(GMS_A)) == MAINTENANT + 19 * JOUR + 3600)
check("illisible : None, pas d'erreur", all(gms.cookie_expiration(v) is None for v in
                                           ("", "authToken=abc", "authToken=a.b.c", "x=1", "authToken=a.e30.c")))
check("même compte, autre session : même empreinte ; autre compte : autre empreinte",
      gms.cookie_compte("authToken=" + GMS_A) == gms.cookie_compte("authToken=" + GMS_A2) != ""
      and gms.cookie_compte("authToken=" + GMS_B) not in ("", gms.cookie_compte("authToken=" + GMS_A)))
_e = gms.cookie_compte("authToken=" + GMS_A)
check("l'empreinte fait 16 caractères et ne contient rien du jeton", len(_e) == 16 and not sans_secret(_e), _e)
check("jeton illisible : pas de compte", gms.cookie_compte("authToken=abc") == "" and gms.cookie_compte("") == "")
gms.save_config({"api_key": "cle-gardee"})
check("l'état d'un site sans cookie", gms.cookie_etat() == {"present": False, "expire": None, "emis": None}, gms.cookie_etat())
gms.save_session_cookie("authToken=" + GMS_A)
e = gms.cookie_etat()
check("l'état : présent, échéance, date de connexion, sans valeur",
      e == {"present": True, "expire": MAINTENANT + 19 * JOUR + 3600, "emis": MAINTENANT + 19 * JOUR + 3600 - 30 * JOUR}
      and not sans_secret(json.dumps(e)), e)

print("5. Les routes")
import web_upload as wu         # noqa: E402
app = wu.create_app()
app.config["TESTING"] = True


def client(role=None, nom="admin"):
    cl = app.test_client()
    if role:
        with cl.session_transaction() as s:
            s["auth"], s["username"], s["role"] = True, nom, role
            if role == "owner":
                s["legacy_owner"] = True
    return cl


EXT = {"source": "extension"}
JSON_ = {"Accept": "application/json"}
config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, last_refreshed=MAINTENANT - 6 * 3600)
gms.save_session_cookie("authToken=" + GMS_A)
depart = (mypuls.CONFIG_FILE.read_bytes(), gms.CONFIG_FILE.read_bytes())


def intact():
    return (mypuls.CONFIG_FILE.read_bytes(), gms.CONFIG_FILE.read_bytes()) == depart


remise()
anonyme = client()
r1 = anonyme.get("/settings/cookies_etat")
r2 = anonyme.post("/mypuls/save_cookies", data=dict(EXT, rememberme=REM_A_NAVIGATEUR), headers=JSON_)
r3 = anonyme.post("/gms/set_session_cookie", data=dict(EXT, cookie=GMS_B), headers=JSON_)
check("sans compte : 401 en JSON sur l'état et sur les deux envois, rien d'écrit",
      (r1.status_code, r2.status_code, r3.status_code) == (401, 401, 401)
      and r2.get_json() == {"ok": False, "error": "unauth"} and intact() and ESSAIS == [],
      (r1.status_code, r2.status_code, r3.status_code))
r = anonyme.post("/mypuls/save_cookies", data={"phpsessid": PHP_NEUF})
check("sans compte, le formulaire de Réglages : renvoi à l'accueil comme avant",
      r.status_code in (301, 302) and r.headers.get("Location", "").endswith("/") and intact(), r.status_code)

_users = wu._load_web_users
wu._load_web_users = lambda: {"chat1": {"role": "chatter"}, "admin": {"role": "owner"}, "boss": {"role": "admin"}}
try:
    chatteur = client("chatter", "chat1")
    r1 = chatteur.get("/settings/cookies_etat")
    r2 = chatteur.post("/mypuls/save_cookies", data=dict(EXT, rememberme=REM_A_NAVIGATEUR), headers=JSON_)
    r3 = chatteur.post("/gms/set_session_cookie", data=dict(EXT, cookie=GMS_B, forcer="1"), headers=JSON_)
    check("rôle restreint (chatteur) : 403 partout, rien d'écrit, MyPuls pas appelé",
          (r1.status_code, r2.status_code, r3.status_code) == (403, 403, 403) and intact() and ESSAIS == []
          and "services" not in (r1.get_data(as_text=True)), (r1.status_code, r2.status_code, r3.status_code))

    for role, nom in (("owner", "admin"), ("admin", "boss")):
        r = client(role, nom).get("/settings/cookies_etat")
        j = r.get_json() or {}
        srv = {s["cle"]: s for s in j.get("services", [])}
        check(f"{role} : l'état des deux cookies, en phrases",
              r.status_code == 200 and j.get("ok") is True and list(srv) == ["gms", "mypuls"]
              and srv["gms"]["niveau"] == "ok" and srv["gms"]["jours"] == 19 and "Valide jusqu’au" in srv["gms"]["texte"]
              and "(19 j)" in srv["gms"]["texte"] and "Connexion du" in srv["gms"]["texte"]
              and srv["mypuls"]["niveau"] == "ok" and "renouvelé il y a 6 h" in srv["mypuls"]["texte"]
              and all(s["aide"] and s["nom"] for s in srv.values()), j)
        check(f"{role} : la réponse ne porte aucune valeur et n'est pas gardée en cache",
              not sans_secret(r.get_data(as_text=True)) and "no-store" in r.headers.get("Cache-Control", ""),
              sans_secret(r.get_data(as_text=True)))

    owner = client("owner")
    # --- GetMySocial
    r = owner.post("/gms/set_session_cookie", data=dict(EXT, cookie=GMS_B), headers=JSON_)
    j = r.get_json() or {}
    check("GetMySocial, autre compte dans Chrome : refusé « autre compte », cookie du site intact",
          j.get("ok") is False and j.get("autre_compte") is True and intact(), j)
    r = owner.post("/gms/set_session_cookie", data=dict(EXT, cookie=GMS_A2), headers=JSON_)
    j = r.get_json() or {}
    check("GetMySocial, même compte : enregistré", j.get("ok") is True and gms.get_session_cookie() == "authToken=" + GMS_A2
          and not sans_secret(r.get_data(as_text=True)), j)
    r = owner.post("/gms/set_session_cookie", data=dict(EXT, cookie=jeton("compteA000000000000000000", MAINTENANT - 60)),
                   headers=JSON_)
    check("GetMySocial, jeton échu : refusé, cookie du site intact",
          (r.get_json() or {}).get("ok") is False and gms.get_session_cookie() == "authToken=" + GMS_A2, r.get_json())
    r = owner.post("/gms/set_session_cookie", data=dict(EXT, cookie=GMS_B, forcer="1"), headers=JSON_)
    check("GetMySocial, forcé : le compte du site est remplacé",
          (r.get_json() or {}).get("ok") is True and gms.get_session_cookie() == "authToken=" + GMS_B, r.get_json())
    r = owner.post("/gms/set_session_cookie", data={"cookie": GMS_A, "retour": "settings"})
    check("le formulaire collé de Réglages remplace sans contrôle de compte, comme avant",
          r.status_code in (301, 302) and gms.get_session_cookie() == "authToken=" + GMS_A, r.status_code)
    r = owner.post("/gms/set_session_cookie", data={"cookie": GMS_B})
    check("l'appel du panneau « Clés » (sans source) aussi", (r.get_json() or {}).get("ok") is True
          and gms.get_session_cookie() == "authToken=" + GMS_B, r.get_json())
    check("la clé API GetMySocial n'a pas bougé", gms.load_config().get("api_key") == "cle-gardee")

    # --- MyPuls
    remise()
    r = owner.post("/mypuls/save_cookies", data=dict(EXT, rememberme=REM_A_NAVIGATEUR), headers=JSON_)
    j = r.get_json() or {}
    check("MyPuls par l'extension : remis, réponse réduite à ok et compte_change",
          r.status_code == 200 and j == {"ok": True, "compte_change": False} and lue().get("REMEMBERME") == REM_A_PROLONGE
          and lue().get("PHPSESSID") == PHP_NEUF and ESSAIS == [{"REMEMBERME": REM_A_NAVIGATEUR}], j)
    avant = mypuls.CONFIG_FILE.read_bytes()
    remise()
    r = owner.post("/mypuls/save_cookies", data=dict(EXT, rememberme=REM_B, phpsessid=PHP_VIEUX), headers=JSON_)
    j = r.get_json() or {}
    check("MyPuls, autre compte : refusé « autre compte », rien d'écrit (même avec un PHPSESSID joint)",
          j.get("ok") is False and j.get("autre_compte") is True and mypuls.CONFIG_FILE.read_bytes() == avant
          and ESSAIS == [] and not sans_secret(r.get_data(as_text=True)), j)
    r = owner.post("/mypuls/save_cookies", data=dict(EXT, rememberme=REM_B, forcer="1"), headers=JSON_)
    check("MyPuls, forcé : remplacé", (r.get_json() or {}) == {"ok": True, "compte_change": True}, r.get_json())
    r = owner.post("/mypuls/save_cookies", data=dict(EXT), headers=JSON_)
    check("MyPuls, envoi vide : refusé en JSON", (r.get_json() or {}).get("ok") is False, r.get_json())
    remise()
    r = owner.post("/mypuls/save_cookies", data={"phpsessid": PHP_VIEUX, "rememberme": REM_A})
    check("le formulaire collé de Réglages enregistre les deux cookies tels quels, comme avant",
          r.status_code in (301, 302) and lue().get("PHPSESSID") == PHP_VIEUX and lue().get("REMEMBERME") == REM_A
          and ESSAIS == [], (r.status_code, sorted(lue())))
    r = owner.post("/mypuls/save_cookies", data={"phpsessid": "court"})
    check("… et refuse toujours un PHPSESSID trop court", lue().get("PHPSESSID") == PHP_VIEUX)

    print("6. Réglages : l'état des deux cookies au même endroit")

    def phrases(**mypuls_cfg):
        config_mypuls(**mypuls_cfg)
        return {s["cle"]: s for s in wu._cookies_etat_services()}

    gms.save_session_cookie("authToken=" + jeton("compteA000000000000000000", MAINTENANT + 2 * JOUR + 3600))
    s = phrases(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, cookies_refuses=MAINTENANT - 3600)
    check("GetMySocial à 2 jours : alerte, avec le nombre de jours", s["gms"]["niveau"] == "alerte" and s["gms"]["jours"] == 2
          and "(2 j)" in s["gms"]["texte"], s["gms"])
    check("MyPuls refusé : « MyPuls refuse le cookie du site depuis le … »", s["mypuls"]["niveau"] == "ko"
          and "MyPuls refuse le cookie du site depuis le" in s["mypuls"]["texte"]
          and "Se souvenir de moi" in s["mypuls"]["aide"], s["mypuls"])
    gms.save_session_cookie("authToken=" + jeton("compteA000000000000000000", MAINTENANT - 3600))
    s = phrases(PHPSESSID=PHP_VIEUX)
    check("GetMySocial échu : « Échu depuis le … »", s["gms"]["niveau"] == "ko" and s["gms"]["texte"].startswith("Échu depuis le"), s["gms"])
    check("MyPuls sans « Se souvenir de moi » : alerte", s["mypuls"]["niveau"] == "alerte"
          and "ne se renouvelle pas" in s["mypuls"]["texte"], s["mypuls"])
    gms.save_session_cookie("")
    s = phrases()
    check("aucun cookie : dit pour les deux", s["gms"]["niveau"] == s["mypuls"]["niveau"] == "ko"
          and s["gms"]["texte"] == s["mypuls"]["texte"] == "Aucun cookie sur le site.", s)
    s = phrases(PHPSESSID=PHP_VIEUX, REMEMBERME=rem("agence@exemple.fr", MAINTENANT + 2 * JOUR + 60))
    check("MyPuls à 2 jours : « le renouvellement automatique ne passe plus »", s["mypuls"]["niveau"] == "alerte"
          and "ne passe plus" in s["mypuls"]["texte"], s["mypuls"])
    s = phrases(PHPSESSID=PHP_VIEUX, REMEMBERME=rem("agence@exemple.fr", MAINTENANT - 60))
    check("MyPuls échu", s["mypuls"]["niveau"] == "ko" and s["mypuls"]["texte"].startswith("Échu depuis le"), s["mypuls"])
    gms.save_session_cookie("cookie-colle-de-travers=1")
    s = phrases(PHPSESSID=PHP_VIEUX, REMEMBERME="illisible")
    check("cookies présents mais illisibles : alerte, pas « valide »", s["gms"]["niveau"] == s["mypuls"]["niveau"] == "alerte"
          and "illisible" in s["gms"]["texte"] and "illisible" in s["mypuls"]["texte"], s)
    _lire = mypuls.cookies_etat
    mypuls.cookies_etat = lambda: 1 / 0
    try:
        s = {x["cle"]: x for x in wu._cookies_etat_services()}
    finally:
        mypuls.cookies_etat = _lire
    check("un état qui plante est dit (« État illisible »), l'autre service reste lisible",
          s["mypuls"]["niveau"] == "ko" and "ZeroDivisionError" in s["mypuls"]["texte"] and s["gms"]["niveau"] == "alerte", s)

    gms.save_session_cookie("authToken=" + GMS_A)
    config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, last_refreshed=MAINTENANT - 6 * 3600)
    bloc = wu._render_cookies_etat()
    sg, sm = wu._render_gms_cookie_settings(), wu._render_mypuls_cookies_settings()
    check("le bloc nomme les deux services, leur état et l'extension",
          "État des cookies" in bloc and "GetMySocial" in bloc and "MyPuls" in bloc and bloc.count("✓") == 2
          and "Cookies → youl4b" in bloc and "tu valides l’envoi" in bloc, bloc[:300])
    check("le même bloc ouvre « Cookies GetMySocial » et « Cookies MyPuls », en tête des deux",
          sg.count(bloc) == 1 and sm.count(bloc) == 1 and sg.startswith(bloc) and sm.startswith(bloc))
    check("les deux formulaires à coller sont toujours là", "name='cookie'" in sg and "action='/gms/set_session_cookie'" in sg
          and "name='phpsessid'" in sm and "name='rememberme'" in sm and "/mypuls/clear_cookies" in sm)
    check("aucune valeur de cookie dans Réglages", not sans_secret(sg + sm), sans_secret(sg + sm))
    config_mypuls(PHPSESSID=PHP_VIEUX, REMEMBERME=REM_A, cookies_refuses=MAINTENANT - 3600)
    bloc = wu._render_cookies_etat()
    check("un cookie mort : la consigne paraît sous sa ligne, pas sous l'autre",
          bloc.count("✕") == 1 and bloc.count("Ouvre mypuls.app") == 1 and "Ouvre getmysocial.com" not in bloc, bloc[:400])
    r = owner.get("/gmsdash/keys")
    check("le panneau « Clés » lit toujours l'échéance GetMySocial", ((r.get_json() or {}).get("cookie") or {}).get("jours") == 19, r.get_json())
finally:
    wu._load_web_users = _users

print("7. L'extension")
DOSSIER = BOT / "extension_cookies"
fichiers = sorted(p.name for p in DOSSIER.iterdir())
check("le dossier ne contient que l'extension et sa notice",
      fichiers == ["LISEZMOI.md", "background.js", "manifest.json", "popup.html", "popup.js"], fichiers)
try:
    man = json.loads((DOSSIER / "manifest.json").read_text(encoding="utf-8"))
except Exception as ex:
    man = {}
    check("manifest.json est du JSON valide", False, ex)
check("manifest v3, service worker et popup", man.get("manifest_version") == 3
      and man.get("background") == {"service_worker": "background.js"}
      and (man.get("action") or {}).get("default_popup") == "popup.html", man)
check("permissions : cookies, alarmes, mémoire, rien d'autre", sorted(man.get("permissions") or []) == ["alarms", "cookies", "storage"],
      man.get("permissions"))
check("sites : GetMySocial, MyPuls et youl4b.com, rien d'autre",
      sorted(man.get("host_permissions") or []) == sorted([
          "https://getmysocial.com/*", "https://*.getmysocial.com/*", "https://mypuls.app/*",
          "https://*.mypuls.app/*", "https://youl4b.com/*"]), man.get("host_permissions"))
popup = (DOSSIER / "popup.html").read_text(encoding="utf-8")
fond = (DOSSIER / "background.js").read_text(encoding="utf-8")
pjs = (DOSSIER / "popup.js").read_text(encoding="utf-8")
check("popup.html : un seul script, en fichier (Chrome refuse un script en ligne dans une extension)",
      popup.count("<script") == 1 and '<script src="popup.js"></script>' in popup and "onclick" not in popup.lower())
check("rien de ce qui vient du réseau n'est interprété comme du HTML", "innerHTML" not in pjs and "insertAdjacentHTML" not in pjs
      and "eval(" not in pjs + fond)
check("aucune écriture dans la console", "console." not in fond and "console." not in pjs)
check("une seule adresse de destination : https://youl4b.com",
      fond.count('"https://') == 1 and 'const SITE = "https://youl4b.com";' in fond and "fetch(SITE + chemin" in fond
      and fond.count("fetch(") == 1, fond.count('"https://'))
versions = (man.get("version"), (fond.split('const VERSION = "', 1) + [""])[1].split('"')[0],
            (pjs.split('const ATTENDUE = "', 1) + [""])[1].split('"')[0])
check("une seule version : manifest, fond et popup (sinon le popup recharge l'extension en vain)",
      len(set(versions)) == 1 and versions[0], versions)
check("deux étapes : le popup demande un aperçu, puis envoie les empreintes vues",
      '{ type: "apercu" }' in pjs and '{ type: "envoyer", empreintes: vu.empreintes }' in pjs
      and pjs.count('type: "envoyer"') == 1 and "1 · Prendre les cookies de Chrome" in popup, pjs.count('type: "envoyer"'))
check("les routes appelées par l'extension existent sur le site",
      all(any(str(r.rule) == chemin for r in app.url_map.iter_rules())
          for chemin in ("/gms/set_session_cookie", "/mypuls/save_cookies", "/settings/cookies_etat"))
      and all(('"' + chemin + '"') in fond for chemin in ("/gms/set_session_cookie", "/mypuls/save_cookies", "/settings/cookies_etat")))
node = shutil.which("node")
check("node est là pour vérifier l'extension", bool(node), "node introuvable : l'extension n'est PAS vérifiée")
if node:
    for nom in ("background.js", "popup.js"):
        p = subprocess.run([node, "--check", str(DOSSIER / nom)], capture_output=True, text=True)
        check(f"{nom} : syntaxe valide", p.returncode == 0, p.stderr)
    p = subprocess.run([node, str(BOT / "tests_cookies_extension.js")], capture_output=True, text=True, timeout=120)
    ligne = next((x for x in p.stdout.splitlines() if x.startswith("RESULTAT")), "")
    check("l'extension jouée dans un faux Chrome : tout passe (%s)" % (ligne or "pas de résultat"),
          p.returncode == 0 and " 0 ECHEC" in ligne, (p.stdout[-600:] + p.stderr[-300:]))

print("8. Isolation")
mypuls._essai_profil, mypuls.ping = _VRAI_ESSAI, _VRAI_PING
check("rien écrit dans le vrai data/", {str(p): (p.stat().st_mtime if p.exists() else None) for p in VRAIS} == AVANT)
shutil.rmtree(TMP, ignore_errors=True)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
