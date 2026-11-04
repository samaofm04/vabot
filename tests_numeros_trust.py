# -*- coding: utf-8 -*-
"""tests_numeros_trust.py — le compte GetAText des serveurs TRUST (04/11/2026).

Propriétaire : « je veux use les propres numéros avec un autre compte GetAText
[...] juste pour les serveurs TRUST », puis « pas TRUST Twitter », « que pour
Instagram et Threads ». Ce fichier prouve, sans réseau ni data/ :
  1. numgen : TRUST INSTAGRAM et THREADS achètent sur le compte TRUST dès que
     sa clé est posée (fournisseur « getatext_trust », sans repli SMSBower) ;
     sans clé, comme avant ; TRUST TWITTER et les autres serveurs jamais ;
  2. un numéro TRUST garde son compte : code, rendu, fin par la même clé ;
  3. la clé : testée chez GetAText avant d'être gardée, refusée si GetAText
     la refuse ou si c'est celle du compte principal, retirée à vide, jamais
     montrée en entier ;
  4. les cartes des tickets (numeros_x_discord) et le salon 📱・numéro
     (cogs/numeros) : le compte de leur serveur, son solde, son alerte ;
  5. le site : la case dans Réglages › Générateurs SMS, admin seulement.

Lancement : python tests_numeros_trust.py
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sys
import tempfile
from types import SimpleNamespace

os.environ["VABOT_BANC_ESSAI"] = "1"
os.environ.pop("GETATEXT_TRUST_API_KEY", None)
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import numgen  # noqa: E402
_GET_REEL = numgen._get

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:400]}]"))


AG, TH, TW = "1488331963575177247", "1498948161039896586", "1445108485090971710"
YOUCHAM, VA_IG = "1565640097146347533", "1505418484052394004"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="numeros_trust_"))
numgen._FILE = TMP / "numgen.json"
import safe_json  # noqa: E402
safe_json.write(numgen._FILE, {"getatext_api_key": "CLE-PRINCIPALE-0000", "smsbower_api_key": "BOWER-1111"})
APPELS = []
REPONSES = {}


def faux_get(url, params, timeout=20):
    APPELS.append((url, dict(params)))
    k = params.get("api_key")
    act = params.get("action")
    return REPONSES.get((k, act), REPONSES.get(act, "NO_NUMBERS"))


numgen._get = faux_get

print("1. Qui achète sur le compte TRUST")
check("sans clé TRUST : personne (tout le monde reste sur le compte principal)",
      all(numgen.compte(g) == "" for g in (AG, TH, TW, YOUCHAM)))
numgen.set_keys(getatext_trust="CLE-TRUST-NOUVELLE-9999")
check("clé posée : TRUST INSTAGRAM et TRUST THREADS", numgen.compte(AG) == "trust" and numgen.compte(TH) == "trust")
check("… pas TRUST TWITTER (« pas TRUST Twitter »), ni YouCham, ni Va IG",
      numgen.compte(TW) == "" and numgen.compte(YOUCHAM) == "" and numgen.compte(VA_IG) == "" and numgen.compte(None) == "")
REPONSES[("CLE-TRUST-NOUVELLE-9999", "getNumber")] = "ACCESS_NUMBER:777:15551234567"
APPELS.clear()
ok, res = numgen.get_number("ig", "187", "trust")
check("achat TRUST : la clé TRUST, le service Instagram de GetAText, fournisseur « getatext_trust »",
      ok and res["provider"] == "getatext_trust" and res["phone"] == "+15551234567"
      and APPELS == [(numgen.GETATEXT_URL, {"api_key": "CLE-TRUST-NOUVELLE-9999", "action": "getNumber",
                                            "service": "instagram/threads", "country": "187"})], (res, APPELS))
REPONSES[("CLE-TRUST-NOUVELLE-9999", "getNumber")] = "NO_BALANCE"
APPELS.clear()
ok, res = numgen.get_number("ig", "187", "trust")
check("compte TRUST à sec : refusé, JAMAIS de repli sur le compte principal ni SMSBower",
      not ok and "GetAText TRUST" in res and all(p["api_key"] == "CLE-TRUST-NOUVELLE-9999" for _u, p in APPELS)
      and numgen.sans_credit(res), (res, APPELS))
REPONSES[("CLE-PRINCIPALE-0000", "getNumber")] = "ACCESS_NUMBER:555:15550000000"
APPELS.clear()
ok, res = numgen.get_number("ig", "187")
check("sans compte (les autres serveurs) : le compte principal, comme avant",
      ok and res["provider"] == "getatext" and APPELS[0][1]["api_key"] == "CLE-PRINCIPALE-0000", (res, APPELS))

print("2. Un numéro TRUST garde son compte")
REPONSES["getStatus"] = "STATUS_OK:123456"
REPONSES["setStatus"] = "ACCESS_CANCEL"
APPELS.clear()
numgen.get_code("777", "getatext_trust")
numgen.cancel("777", "getatext_trust")
numgen.finish("777", "getatext_trust")
check("code, rendu, fin : la clé TRUST", len(APPELS) == 3
      and all(p["api_key"] == "CLE-TRUST-NOUVELLE-9999" and u == numgen.GETATEXT_URL for u, p in APPELS), APPELS)
APPELS.clear()
numgen.get_code("555", "getatext")
check("un numéro du compte principal : la clé principale", APPELS[0][1]["api_key"] == "CLE-PRINCIPALE-0000")
REPONSES[("CLE-TRUST-NOUVELLE-9999", "getBalance")] = "ACCESS_BALANCE:12.50"
REPONSES[("CLE-PRINCIPALE-0000", "getBalance")] = "ACCESS_BALANCE:3.00"
b = numgen.balances()
check("les soldes : le compte TRUST à part (« sms_trust »)", b["sms_trust"] == "12.50 $" and b["sms"] == "3.00 $", b)
st = numgen.status()
check("l'état ne montre que la fin de la clé", st["getatext_trust"] == "CLE-…9999" and st["trust_ok"], st)


print("2 bis. Les cas de la relecture")
import requests as _rq  # noqa: E402
numgen._get = _GET_REEL
_vrai_rget = _rq.get


def _panne(url, params=None, timeout=20):
    raise _rq.exceptions.ConnectionError(
        f"HTTPSConnectionPool: Max retries exceeded with url: /stubs/handler_api.php?api_key={params['api_key']}&action=getBalance")


_rq.get = _panne
t = numgen._get(numgen.GETATEXT_URL, {"api_key": "CLE-TRUST-NOUVELLE-9999", "action": "getBalance"})
check("GetAText injoignable : l'erreur ne porte JAMAIS la clé (ni TRUST ni principale)",
      t.startswith("ERR:ConnectionError") and "CLE-TRUST-NOUVELLE-9999" not in t and "***" in t, t)
t = numgen._get(numgen.GETATEXT_URL, {"api_key": "CLE-PRINCIPALE-0000", "action": "getNumber"})
check("… la clé principale non plus", "CLE-PRINCIPALE-0000" not in t, t)
_rq.get = _vrai_rget
numgen._get = faux_get
# l'ancienne clé : un numéro pris avant un changement reste lu et rendu
REPONSES[("CLE-TRUST-NOUVELLE-9999", "getStatus")] = "STATUS_OK:111111"
REPONSES[("NOUVELLE-CLE-TRUST-4321", "getBalance")] = "ACCESS_BALANCE:20.00"
REPONSES[("NOUVELLE-CLE-TRUST-4321", "getStatus")] = "NO_ACTIVATION"
ok, msg = numgen.enregistrer_cle_trust("NOUVELLE-CLE-TRUST-4321")
APPELS.clear()
etat, val = numgen.get_code("777", "getatext_trust")
check("clé REMPLACÉE pendant qu'un numéro vit : son code se lit sur l'ancienne clé",
      ok and etat == "code" and val == "111111"
      and [p["api_key"] for _u, p in APPELS] == ["NOUVELLE-CLE-TRUST-4321", "CLE-TRUST-NOUVELLE-9999"], (etat, val, APPELS))
REPONSES[("CLE-TRUST-NOUVELLE-9999", "setStatus")] = "ACCESS_CANCEL"
REPONSES[("NOUVELLE-CLE-TRUST-4321", "setStatus")] = "NO_ACTIVATION"
okc, _r = numgen.cancel("777", "getatext_trust")
check("… et il se rend (remboursé) sur l'ancienne clé", okc, _r)
numgen.enregistrer_cle_trust("")
REPONSES[("NOUVELLE-CLE-TRUST-4321", "getStatus")] = "STATUS_OK:222222"
APPELS.clear()
etat, val = numgen.get_code("888", "getatext_trust")
check("clé RETIRÉE pendant qu'un numéro vit : lu sur la dernière clé, pas « NO_KEY »",
      etat == "code" and val == "222222"
      and [p["api_key"] for _u, p in APPELS] == ["NOUVELLE-CLE-TRUST-4321"], (etat, val, APPELS))
check("… sans que les serveurs TRUST n'achètent plus dessus", numgen.compte(AG) == "")
check("l'ancienne clé n'apparaît jamais dans l'état", "NOUVELLE" not in str(numgen.status())
      and "precedente" not in str(numgen.status()))
os.environ["GETATEXT_TRUST_API_KEY"] = "CLE-DU-POINT-ENV-777777"
ok, msg = numgen.enregistrer_cle_trust("")
check("une clé dans .env : « retirer » dit qu'elle est là, pas un faux succès", not ok and ".env" in msg, msg)
REPONSES[("AUTRE-CLE-TRUST-5555", "getBalance")] = "ACCESS_BALANCE:1.00"
ok, msg = numgen.enregistrer_cle_trust("AUTRE-CLE-TRUST-5555")
check("… et une clé du site ne passe pas devant sans le dire",
      ok or (".env" in msg), msg)
os.environ.pop("GETATEXT_TRUST_API_KEY", None)
_w = safe_json.write
safe_json.write = lambda *a, **k: False
numgen._FILE = TMP / "absent" / "x" / "numgen.json"
ok, msg = numgen.enregistrer_cle_trust("AUTRE-CLE-TRUST-5555")
check("écriture impossible : « non enregistrée », l'ancienne reste en service", not ok and "non enregistrée" in msg, msg)
safe_json.write = _w
numgen._FILE = TMP / "numgen.json"
numgen.set_keys(getatext_trust="CLE-TRUST-NOUVELLE-9999")

print("3. La clé")
REPONSES[("MAUVAISE-CLE-0000000", "getBalance")] = "BAD_KEY"
ok, msg = numgen.enregistrer_cle_trust("MAUVAISE-CLE-0000000")
check("GetAText refuse la clé : non gardée, l'ancienne reste",
      not ok and "BAD_KEY" in msg and numgen.getatext_trust_key() == "CLE-TRUST-NOUVELLE-9999", msg)
ok, msg = numgen.enregistrer_cle_trust("CLE-PRINCIPALE-0000")
check("la clé du compte principal : refusée (il faut celle du NOUVEAU compte)",
      not ok and "principal" in msg and numgen.getatext_trust_key() == "CLE-TRUST-NOUVELLE-9999", msg)
ok, msg = numgen.enregistrer_cle_trust("pas une clé")
check("une clé avec des espaces : refusée", not ok)
REPONSES[("NOUVELLE-CLE-TRUST-4321", "getBalance")] = "ACCESS_BALANCE:20.00"
ok, msg = numgen.enregistrer_cle_trust("  NOUVELLE-CLE-TRUST-4321 ")
check("une bonne clé : gardée, le message dit sa fin et le solde, jamais la clé entière",
      ok and numgen.getatext_trust_key() == "NOUVELLE-CLE-TRUST-4321" and "…4321" in msg and "20.00" in msg
      and "NOUVELLE-CLE-TRUST-4321" not in msg, msg)
REPONSES[("INJOIGNABLE-CLE-00000", "getBalance")] = "ERR:timeout"
ok, msg = numgen.enregistrer_cle_trust("INJOIGNABLE-CLE-00000")
check("GetAText injoignable : gardée quand même, et c'est dit", ok and "pas répondu" in msg, msg)
numgen.enregistrer_cle_trust("NOUVELLE-CLE-TRUST-4321")
ok, msg = numgen.enregistrer_cle_trust("")
check("vide : retirée, TRUST INSTAGRAM et THREADS reviennent au compte principal",
      ok and numgen.getatext_trust_key() == "" and numgen.compte(AG) == "", msg)
check("le compte principal n'a jamais bougé", numgen.getatext_key() == "CLE-PRINCIPALE-0000")
numgen.set_keys(getatext_trust="CLE-TRUST-NOUVELLE-9999")

print("4. Les cartes des tickets et le salon 📱・numéro")
import numeros_x_discord as nx  # noqa: E402
check("chaque serveur des cartes connaît son id", all(c.get("gid") == g for g, c in nx.SERVEURS.items()))
check("cartes : Instagram et Threads sur le compte TRUST, Twitter garde HeroSMS",
      nx._compte(nx.SERVEURS[AG]) == "trust" and nx._compte(nx.SERVEURS[TH]) == "trust"
      and nx._compte(nx.SERVEURS[TW]) == "" and nx._fournisseur(nx.SERVEURS[TW]) == "herosms")
ACHATS = []
_gn = numgen.get_number
numgen.get_number = lambda *a: ACHATS.append(a) or (True, {"id": "1", "phone": "+1", "provider": "getatext_trust"})
nx._acheter_chez(nx.SERVEURS[TH])
check("carte Threads : l'achat demande le compte TRUST, dans le pays du panneau",
      ACHATS == [("ig", "187", "trust")], ACHATS)
numgen.get_number = _gn
check("alerte sans crédit : la sienne (« credit:sms_trust »), clé jugée posée",
      nx._cle_credit(nx.SERVEURS[AG]) == "credit:sms_trust" and nx._cle_posee(nx.SERVEURS[AG])
      and nx._cle_credit(nx.SERVEURS[TW]) == "credit:herosms")
DITS = []
numgen.alerter_staff = lambda cle, texte: DITS.append((cle, texte)) or "envoye"
r = nx._souci_achat("GetAText TRUST : NO_BALANCE", nx.SERVEURS[TH])
check("carte à sec : le VA lit « sans crédit », le staff est prévenu du compte TRUST",
      "sans crédit" in r and DITS and DITS[-1][0] == "credit:sms_trust" and "TRUST" in DITS[-1][1], (r, DITS))
check("le nom du fournisseur se lit « GetAText TRUST »", nx.NOMS_FOURNISSEURS["getatext_trust"] == "GetAText TRUST")
from cogs import numeros as cn  # noqa: E402
salon_ag = SimpleNamespace(id=1, name="📱・numéro", guild=SimpleNamespace(id=int(AG)))
salon_tw = SimpleNamespace(id=2, name="x", guild=SimpleNamespace(id=int(TW)))
carte = cn._CartePerso(salon_ag, 42, "bob")
check("salon 📱・numéro de TRUST INSTAGRAM (et la carte du cliqueur) : le compte TRUST",
      cn._compte(salon_ag) == "trust" and cn._compte(carte) == "trust" and cn._compte(salon_tw) == ""
      and cn._compte(None) == "")
check("… son solde est celui du compte TRUST", cn._cle_solde(carte) == "sms_trust" and cn._cle_solde(salon_tw) == "sms")
check("… son alerte aussi ; les mails gardent la leur",
      cn._cle_credit("sms", "trust") == "credit:sms_trust" and cn._cle_credit("sms") == "credit:sms"
      and cn._cle_credit("mail", "trust") == "credit:mail")
DITS.clear()
txt = asyncio.run(cn._souci_fournisseur("sms", "GetAText TRUST : NO_BALANCE", "trust"))
check("salon à sec : « sans crédit » pour le VA, l'alerte TRUST au staff",
      "sans crédit" in txt and DITS and DITS[-1][0] == "credit:sms_trust", (txt, DITS))
SOLDES = {"sms": "3.00 $", "sms_trust": "12.50 $"}
_bal = numgen.balances
numgen.balances = lambda: dict(SOLDES)
check("le solde affiché sur TRUST INSTAGRAM : 12,50 $ (celui du compte TRUST)",
      asyncio.run(cn._solde_sms(carte)) == "12.50 $" and asyncio.run(cn._solde_sms(salon_tw)) == "3.00 $")
numgen.balances = _bal
src = (BOT / "cogs" / "numeros.py").read_text(encoding="utf-8")
check("l'achat du salon passe le compte de son serveur",
      "numgen.get_number, service, _pays(ch), _compte(ch))" in src)
check("/soldes dit le solde du compte TRUST", "GetAText TRUST (Instagram, Threads)" in src)

print("5. Le site : la case de la clé")
import web_upload as w  # noqa: E402
app = w.create_app()
app.config["TESTING"] = True
_users = w._load_web_users
w._load_web_users = lambda: {"admin": {"role": "owner", "password": "x"},
                             "chatteur1": {"role": "chatter", "password": "x"}}
h = w._numgen_trust_html({"sms_trust": "12.50 $"})
check("l'onglet montre l'état (fin de la clé, solde) et un champ masqué, jamais la clé entière",
      "CLE-…9999" in h and "type='password'" in h and "CLE-TRUST-NOUVELLE-9999" not in h
      and "/settings/numgen/cle_trust" in h and "12.50 $" in h, h[:300])
APPELS.clear()
w._numgen_trust_html({"sms_trust": "12.50 $"})
check("… sans relire les soldes chez les fournisseurs (l'onglet vient de le faire)", not APPELS, APPELS)
c = app.test_client()
with c.session_transaction() as s:
    s["auth"], s["username"], s["role"] = True, "chatteur1", "chatter"
r = c.post("/settings/numgen/cle_trust", data={"cle": "NOUVELLE-CLE-TRUST-4321"})
check("un chatteur : refusé, la clé ne bouge pas",
      r.status_code in (302, 403) and numgen.getatext_trust_key() == "CLE-TRUST-NOUVELLE-9999", r.status_code)
c = app.test_client()
with c.session_transaction() as s:
    s["auth"], s["username"], s["role"] = True, "admin", "owner"
r = c.post("/settings/numgen/cle_trust", data={"cle": "NOUVELLE-CLE-TRUST-4321"})
check("l'admin : la clé enregistrée", numgen.getatext_trust_key() == "NOUVELLE-CLE-TRUST-4321", r.status_code)
r = c.post("/settings/numgen/cle_trust", data={"retirer": "1"})
check("… et « Retirer » la retire", numgen.getatext_trust_key() == "", r.status_code)
w._load_web_users = _users

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
