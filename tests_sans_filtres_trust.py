"""Liens des VA des trois TRUST : plus de filtres pays ni de safe page (11/11/2026).

Propriétaire : « maintenant bloque plus les clics ni rien de bizarre du coup
pour Twitter, Threads et IG, laisse les liens comme ça aussi, mets le truc de
base en général ». Le compte OnlyFans de Lia bloque lui-même 210 pays sur 227.

Vérifie le DÉFAUT (rien dans la config) :
  - aucune liste de pays : ni à la création (poser_pays), ni à la reprise
    (reprendre_pays, liste changée), ni sur les pages — et aucun appel
    GetMySocial pour ça ;
  - une fiche « pays » : false reste telle quelle (reprise si la règle revient),
    sans alerte à chaque passage ;
  - la clé « pays » {"cibles": [...]} remet la règle, {} la coupe ;
  - la safe page des pages est éteinte (pages_va.SAFE_PAGE ; la création et la
    reprise sont vérifiées dans tests_pages_va, section 9).

Aucun réseau : GetMySocial est doublé, toute connexion fait échouer la suite.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import socket
import sys
import tempfile

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import gms                     # noqa: E402
import liens_va as lv          # noqa: E402
import pages_va as pv          # noqa: E402

OK, KO = [], []
SORTIES = []
_VRAIS_SOCKET = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)


def _reseau_interdit(*a, **k):
    SORTIES.append(str(a[1:2])[:80])
    raise OSError("réseau interdit dans tests_sans_filtres_trust")


socket.socket.connect = socket.socket.connect_ex = _reseau_interdit
socket.getaddrinfo = _reseau_interdit


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:400]}]"))


TW, TH, AG = lv.TWITTER_ID, lv.THREADS_ID, lv.AGENCY_IG_ID
TMP = pathlib.Path(tempfile.mkdtemp(prefix="sans_filtres_"))
SAV = (lv.ETAT_FICHIER, lv.config, gms.get_link, gms.update_link, lv.PAUSE_PAYS_S, pv.FICHIER,
       gms.disable_link, gms.list_links_team)
lv.ETAT_FICHIER = TMP / "liens_va.json"
pv.FICHIER = TMP / "pages_va.json"
CONFIG = {}
lv.config = lambda: dict(CONFIG)
lv.PAUSE_PAYS_S = 0

LIENS, APPELS = {}, []


def f_get(lid, team_id=None):
    APPELS.append(("get", lid))
    l = LIENS.get(lid)
    return {"ok": True, "link": json.loads(json.dumps(l))} if l else {"ok": False, "error": "404"}


def f_update(lid, champs, team_id=None):
    APPELS.append(("update", lid, sorted(champs)))
    LIENS[lid].update(json.loads(json.dumps(champs)))
    return {"ok": True}


def _gms_interdit(*a, **k):
    raise AssertionError("appel GetMySocial non prévu dans tests_sans_filtres_trust")


gms.get_link, gms.update_link = f_get, f_update
gms.disable_link = gms.list_links_team = _gms_interdit


def direct(lid, tracking="https://onlyfans.com/liasxcret/c76"):
    LIENS[lid] = {"id": lid, "type": "direct", "url": tracking, "geofilters": [], "buttons": []}


def landing(lid, tracking="https://onlyfans.com/liasxcret/c76"):
    LIENS[lid] = {"id": lid, "type": "landing", "url": "", "buttons": [
        {"label": "MY FREE 0F", "url": tracking, "geofilters": []},
        {"label": "MY TELEGRAM", "url": "https://t.me/m/x"}]}


try:
    EQ = {g: lv.espace(g)["equipe"] for g in (TW, TH, AG)}

    # ── 1. le défaut ──────────────────────────────────────────────────────
    print("1. Par défaut : plus de filtres pays, plus de safe page")
    check("interrupteurs du code éteints (FILTRE_PAYS, SAFE_PAGE)",
          lv.FILTRE_PAYS is False and pv.SAFE_PAGE is False)
    check("aucun pays cible, sur les trois TRUST comme sans équipe",
          lv.cibles_pays() is None and all(lv.cibles_pays(EQ[g]) is None for g in (TW, TH, AG)),
          [lv.cibles_pays(EQ[g]) for g in (TW, TH, AG)])
    check("aucune règle à poser, signature vide",
          lv.regles_pays("https://onlyfans.com/liasxcret") == []
          and all(lv.signature_pays(g) == "" for g in (TW, TH, AG)) and lv.signature_pays_avant() == "")

    # ── 2. création : rien posé, rien lu ─────────────────────────────────
    print("2. poser_pays (création, rallumage, pages)")
    direct("d_tw")
    landing("p_ig")
    APPELS.clear()
    rd, rl = lv.poser_pays("d_tw", EQ[TW]), lv.poser_pays("p_ig", EQ[AG])
    check("lien direct et landing : « ok, coupé », aucun appel à GetMySocial",
          rd.get("ok") and rd.get("coupe") and rl.get("ok") and rl.get("coupe") and not APPELS, (rd, rl, APPELS))
    check("… et rien n'a changé sur les liens (ni pays, ni boutons)",
          LIENS["d_tw"]["geofilters"] == [] and [b.get("geofilters") for b in LIENS["p_ig"]["buttons"]] == [[], None])

    # ── 3. reprise : un « pays » : false n'est pas reposé, sans alerte ─────
    print("3. Reprise des pays")
    lv._ecrire({"liens": {
        f"{TW}:1": {"link_id": "d_tw", "actif": True, "pays": False, "pays_essais": 1, "shortcode": "a",
                    "pays_a_verifier": True, "pays_liste_due": "AD,AT"},
        f"{TW}:2": {"link_id": "d_tw2", "actif": True, "pays": True, "pays_cibles": "AD,AT,AU", "shortcode": "b"},
        f"{TH}:3": {"link_id": "d_th", "actif": True, "pays": False, "shortcode": "c"}}})
    avant = json.loads(json.dumps(lv._etat()))
    APPELS.clear()
    journal = io.StringIO()
    _sortie, sys.stdout = sys.stdout, journal
    try:
        bilans = [lv.reprendre_pays(g) for g in (TW, TH, AG)]
    finally:
        sys.stdout = _sortie
    check("reprendre_pays : rien posé, rien raté, aucun appel",
          all(b == {"poses": [], "rates": []} for b in bilans) and not APPELS, (bilans, APPELS))
    check("… les fiches restent telles quelles (le « false » serait repris si la règle revenait)",
          lv._etat() == avant, lv._etat())
    check("… et pas d'alerte « encore sur l'ancienne liste » à chaque passage",
          "ancienne liste" not in journal.getvalue(), journal.getvalue()[:200])
    check("liste comparée : aucun lien ni aucune page marqués à refaire",
          lv._marquer_liste_pays(TW) == [] and pv._marquer_liste_pays(TW) == [] and lv._etat() == avant)

    # ── 4. la clé de la config : remettre, couper ────────────────────────
    print("4. Clé « pays » de la config")
    CONFIG["pays"] = {"cibles": ["US", "CA"]}
    ct = lv.cibles_pays(EQ[TW])
    check("{\"cibles\": [...]} remet la règle (l'Europe en plus sur Twitter, comme avant)",
          lv.cibles_pays() == {"US", "CA"} and {"US", "CA", "FR"} <= ct and "ES" not in ct, ct)
    APPELS.clear()
    r = lv.poser_pays("d_tw", EQ[TW])
    base = {x["country_code"] for x in LIENS["d_tw"]["geofilters"]}
    check("… et poser_pays pose de nouveau la liste (les autres pays vers le compte de base)",
          r.get("ok") and not r.get("coupe") and "ES" in base and not ({"US", "CA", "FR"} & base)
          and ("update", "d_tw", ["geofilters"]) in APPELS, (r, sorted(base)[:5]))
    CONFIG["pays"] = {}
    check("{} coupe la règle", lv.cibles_pays() is None and lv.regles_pays("https://onlyfans.com/x") == [])
    CONFIG.pop("pays")
    _v = lv.FILTRE_PAYS
    lv.FILTRE_PAYS = True
    check("FILTRE_PAYS remis à vrai : la liste d'avant (8 pays, Europe sur Twitter)",
          lv.cibles_pays() == set(lv.PAYS_CIBLES) and set(lv.PAYS_EUROPE) <= lv.cibles_pays(EQ[TW]))
    lv.FILTRE_PAYS = _v
    CONFIG["pays"] = {"cibles": "US"}
    try:
        lv.cibles_pays()
        lu = False
    except ValueError:
        lu = True
    check("une clé mal écrite lève toujours une erreur (pas de règle devinée)", lu)
    CONFIG.pop("pays")

    # ── 5. safe page ──────────────────────────────────────────────────────
    print("5. Safe page")
    check("la copie de la branche 30 % (si elle revenait) ne demande plus de safe page",
          pv._lien_ab("lnk_x", "https://onlyfans.com/liasxcret/c1", "sc")["safe_page"] is False)
finally:
    (lv.ETAT_FICHIER, lv.config, gms.get_link, gms.update_link, lv.PAUSE_PAYS_S, pv.FICHIER,
     gms.disable_link, gms.list_links_team) = SAV
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = _VRAIS_SOCKET

check("aucune connexion réseau tentée", not SORTIES, SORTIES[:3])
print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
sys.exit(1 if KO else 0)
