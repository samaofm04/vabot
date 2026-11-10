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
# You FR et You US (10/11/2026) prennent le compte TRUST sans être des serveurs TRUST.
import guild_features as _gf_you  # noqa: E402
YOU_US, YOU_FR = _gf_you.YOU_US_GUILD_ID, _gf_you.YOU_FR_GUILD_ID
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
      all(numgen.compte(g) == "" for g in (AG, TH, TW, YOUCHAM, YOU_US, YOU_FR)))
numgen.set_keys(getatext_trust="CLE-TRUST-NOUVELLE-9999")
check("clé posée : TRUST INSTAGRAM et TRUST THREADS", numgen.compte(AG) == "trust" and numgen.compte(TH) == "trust")
check("… pas TRUST TWITTER (« pas TRUST Twitter »), ni YouCham, ni Va IG",
      numgen.compte(TW) == "" and numgen.compte(YOUCHAM) == "" and numgen.compte(VA_IG) == "" and numgen.compte(None) == "")
# Propriétaire, 10/11/2026 : « je veux use des num avec API du serv trust
# instagram », « change juste API du fournisseur … pour les SMS sur You FR »,
# puis « oui, You US aussi ».
check("You FR et You US achètent sur le compte TRUST (id texte ou entier)",
      numgen.compte(YOU_FR) == "trust" and numgen.compte(int(YOU_FR)) == "trust"
      and numgen.compte(YOU_US) == "trust" and numgen.compte(int(YOU_US)) == "trust")
check("la liste du compte : les deux serveurs TRUST, You FR et You US, lue dans guild_features",
      numgen.serveurs_compte_trust() == {AG: "TRUST INSTAGRAM", TH: "TRUST THREADS",
                                         YOU_FR: "You FR", YOU_US: "You US"}
      and _gf_you.NUMEROS_COMPTE_TRUST == {YOU_FR: "You FR", YOU_US: "You US"},
      numgen.serveurs_compte_trust())
check("ni l'un ni l'autre n'est un serveur TRUST (TRUST_SERVEURS inchangée) ; leurs ids ne sont pas "
      "recopiés dans numgen",
      set(numgen.TRUST_SERVEURS) == {AG, TH}
      and not any(g in (BOT / "numgen.py").read_text(encoding="utf-8") for g in (YOU_FR, YOU_US)))
_sauve_table = dict(_gf_you.NUMEROS_COMPTE_TRUST)
_gf_you.NUMEROS_COMPTE_TRUST.clear()
check("table vidée : You FR et You US reviennent sur le compte principal, les serveurs TRUST ne bougent pas",
      numgen.compte(YOU_FR) == "" and numgen.compte(YOU_US) == "" and numgen.compte(AG) == "trust")
_gf_you.NUMEROS_COMPTE_TRUST.update(_sauve_table)
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
# You FR et You US : le salon commun 📱・numéro et la carte du cliqueur prennent
# le compte TRUST ; la vignette GetAText reste aux serveurs TRUST (« seulement
# TRUST »). YouCham, le troisième serveur aux outils communs, ne bouge pas.
salon_us = SimpleNamespace(id=3, name="📱・numéro", guild=SimpleNamespace(id=int(YOU_US)))
salon_fr = SimpleNamespace(id=4, name="📱・numéro", guild=SimpleNamespace(id=int(YOU_FR)))
salon_yc = SimpleNamespace(id=5, name="📱・numéro", guild=SimpleNamespace(id=int(YOUCHAM)))
for _nom_s, _salon_s in (("You FR", salon_fr), ("You US", salon_us)):
    _carte_s = cn._CartePerso(_salon_s, 43, "zoe")
    check(f"{_nom_s} : salon et carte sur le compte TRUST, son solde et son alerte",
          cn._compte(_salon_s) == "trust" and cn._compte(_carte_s) == "trust"
          and cn._cle_solde(_carte_s) == "sms_trust"
          and cn._cle_credit("sms", cn._compte(_carte_s)) == "credit:sms_trust")
    check(f"{_nom_s} garde la vignette du téléphone (la puce GetAText est celle des serveurs TRUST)",
          cn._icone_de(_salon_s) == (cn._ICONE, cn._ICONE_NOM))
    check(f"{_nom_s} : seul le compte change — ni limite par jour, ni paliers, ni numéros +33 "
          "(propres à TRUST INSTAGRAM et à Va IG)",
          not cn._numero_seul(_salon_s) and not cn._serveur_fr(_salon_s)
          and cn._pays(_salon_s) is None)
check("YouCham reste sur le compte principal ; TRUST INSTAGRAM garde sa puce",
      cn._compte(salon_yc) == "" and cn._cle_solde(salon_yc) == "sms"
      and cn._icone_de(salon_ag) == (cn._ICONE_TRUST, cn._ICONE_TRUST_NOM))
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
check("l'onglet nomme TOUS les serveurs qui achètent sur ce compte, You FR et You US compris",
      "TRUST INSTAGRAM, TRUST THREADS, You FR et You US achètent sur ce compte" in h, h[:400])
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

print("6. La clé SMSBower depuis le site (05/11/2026)")
REPONSES[("BOWER-NOUVELLE-22222222", "getBalance")] = "ACCESS_BALANCE:7.25"
REPONSES[("BOWER-MAUVAISE-33333333", "getBalance")] = "BAD_KEY"
ok, msg = numgen.enregistrer_cle_smsbower("BOWER-MAUVAISE-33333333")
check("SMSBower refuse la clé : refusée, l'ancienne reste", not ok and "BAD_KEY" in msg
      and numgen.smsbower_key() == "BOWER-1111", (ok, msg))
ok, msg = numgen.enregistrer_cle_smsbower("trop courte")
check("clé mal copiée : refusée", not ok and numgen.smsbower_key() == "BOWER-1111", (ok, msg))
APPELS.clear()
ok, msg = numgen.enregistrer_cle_smsbower("  BOWER-NOUVELLE-22222222 ")
check("bonne clé : testée chez SMSBower puis enregistrée, solde dit, clé jamais en entier",
      ok and numgen.smsbower_key() == "BOWER-NOUVELLE-22222222" and "7.25" in msg
      and "BOWER-NOUVELLE-22222222" not in msg
      and any(u == numgen.SMSBOWER_STUBS_URL and pr.get("action") == "getBalance" for u, pr in APPELS),
      (ok, msg, APPELS))
check("… la clé GetAText principale et la TRUST ne bougent pas",
      numgen.getatext_key() == "CLE-PRINCIPALE-0000")
h = w._numgen_smsbower_html({"mail": "7.25 $"})
check("la case : fin de la clé, solde, champ masqué, jamais la clé entière",
      "type='password'" in h and "/settings/numgen/cle_smsbower" in h and "7.25 $" in h
      and "BOWER-NOUVELLE-22222222" not in h and "2222" in h, h[:300])
check("… dans l'onglet Générateurs SMS", "_numgen_smsbower_html(soldes)" in (BOT / "web_upload.py").read_text(encoding="utf-8"))
c = app.test_client()
with c.session_transaction() as s:
    s["auth"], s["username"], s["role"] = True, "chatteur1", "chatter"
r = c.post("/settings/numgen/cle_smsbower", data={"cle": "BOWER-MAUVAISE-33333333"})
check("un chatteur : refusé, la clé ne bouge pas",
      r.status_code in (302, 403) and numgen.smsbower_key() == "BOWER-NOUVELLE-22222222", r.status_code)
REPONSES[("BOWER-AUTRE-44444444", "getBalance")] = "ACCESS_BALANCE:1.00"
c = app.test_client()
with c.session_transaction() as s:
    s["auth"], s["username"], s["role"] = True, "admin", "owner"
r = c.post("/settings/numgen/cle_smsbower", data={"cle": "BOWER-AUTRE-44444444"})
check("l'admin : enregistrée, retour sur l'onglet Générateurs SMS",
      numgen.smsbower_key() == "BOWER-AUTRE-44444444" and r.status_code == 302
      and "tab=snumgen" in (r.headers.get("Location") or ""), (r.status_code, r.headers.get("Location")))
w._load_web_users = _users

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
