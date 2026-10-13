"""Va Twitter et Va Threads : le récap des subs et le récap des clics.

Propriétaire, 13/10/2026 : « ici tu peux envoyer les récap des subs et les
récap de clicks pour le Threads et aussi pour Twitter, et tu mets aussi celui
des subs », les liens « tout le lien comme d'hab ».

Ce qui est vérifié ici, sans réseau ni vrai data/ (GetMySocial, MyPuls,
Discord et l'horloge sont faux ; chaque DATA_DIR est un dossier temporaire) :
  1. le classement subs de Twitter trouve « ─│👤┤-subs » — jamais
     « ─│🏆┤-paliers-subs », ni une catégorie, ni un salon au hasard ;
  2. Threads poste le classement de la quinzaine avec les chiffres de Twitter
     (le même embed, à l'octet), par SON bot, sans relire MyPuls ni
     GetMySocial quand Twitter vient de relever ; il ne relève lui-même (avec
     les sources de Twitter) que si Twitter n'a rien ; ni podium, ni bonus, ni
     paliers sur Threads ;
  3. la boucle du site (web_upload) ne fait que la quinzaine sur Threads, et
     tout ce qu'elle faisait ailleurs ;
  4. le récap des clics : le report de JESSY LE RETOUR (marché US) posté puis
     édité sur place dans « ─│📊┤-l-clicks » des deux serveurs, par REST, avec
     le bot de chaque serveur ; retrouvé après un redémarrage ou un état
     perdu, jamais en double ; aucun appel GetMySocial de plus ; rien sur les
     autres serveurs ; seul le report PUBLIÉ est repris (ni la page publique
     des clics, ni l'essai du rig) ; un salon changé dans le réglage reçoit
     le récap au relevé suivant.

Lancer depuis la racine du dépôt : python tests_recaps_twitter_threads.py
"""
from __future__ import annotations

import ast
import asyncio
import copy
import datetime as dt
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import textwrap
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

CLOCK = {"now": dt.datetime(2026, 10, 13, 10, 0)}      # un mardi, quinzaine du 01/10

# ------------------------------------------------ faux suivi_va (la paie) --
_PRIMES = []
_faux_suivi = types.ModuleType("suivi_va")
_faux_suivi.annoncer_primes = lambda gid, cl, debut, fin: (
    _PRIMES.append(str(gid)) or {"dits": [], "sans_adresse": [], "inconnus": []})
sys.modules["suivi_va"] = _faux_suivi

# ------------------------------------------------- faux GetMySocial --------
EQ_TW1, EQ_TW2 = "tm_6a0e4739bfa0c238f20a8bf5", "tm_6ab46ebb11a0232c11211b1a"
OF = "https://onlyfans.com/"
GMS = {"listes": [], "analytics": [], "report": [], "muet": False}


def _page(id_, nom, *urls):
    return {"id": id_, "display_name": nom, "type": "landing", "url": None, "status": "active",
            "buttons": [{"url": u} for u in urls]}


LIENS = {EQ_TW1: [_page("l1", "(Roucham) 1", OF + "emy.brw/c42"),
                  _page("l2", "(Roucham) 1SPAM", OF + "emy.brw/c43"),
                  _page("l3", "tsiry 1", OF + "emy.brw/c37"),
                  _page("l4", "(Ricardo) 1", OF + "emy.brw/c44")],
         EQ_TW2: [{"id": "l5", "display_name": "Twitter VA 31 @abdoul_9684", "type": "directlink",
                   "url": OF + "emy.brw/c6", "status": "active", "buttons": []}]}


def _list_links_team(team, force_refresh=False):
    GMS["listes"].append(team)
    return {"ok": True, "links": copy.deepcopy(LIENS.get(team, []))}


def _analytics_for_links(ids, d0, d1):
    GMS["analytics"].append((tuple(ids), d0, d1))
    return 10, {"US": 7, "FR": 3}


# le report des clics (cogs/clickrecap._build_group_report)
META = [{"id": "g1", "display_name": "(Roucham) 1", "shortcode": "a",
         "destination": OF + "jessyewdiference/c101"},
        {"id": "g2", "display_name": "(Roucham) 1SP", "shortcode": "b", "destination": ""},
        {"id": "g3", "display_name": "(VA 4 Noum) 1", "shortcode": "c",
         "destination": OF + "jessyewdiference/c103"}]
CLICS = {"facteur": 1}


def _report_links_meta(*a):
    GMS["report"].append(("meta",) + tuple(a))
    return None if GMS["muet"] else copy.deepcopy(META)


def _clicks_for_ids(ids, s, e):
    GMS["report"].append(("total", s, e))
    return 100 * CLICS["facteur"]


def _analytics_for_link(lid, a, b):
    GMS["report"].append(("lien", lid, a, b))
    f = CLICS["facteur"]
    return ({"g1": 619, "g2": 1318, "g3": 11205}[lid] * f,
            {"US": {"g1": 346, "g2": 329, "g3": 4218}[lid] * f})


_faux_gms = types.ModuleType("gms")
_faux_gms.list_links_team = _list_links_team
_faux_gms.analytics_for_links = _analytics_for_links
_faux_gms.analytics_for_link = _analytics_for_link
_faux_gms.report_links_meta = _report_links_meta
_faux_gms.clicks_for_ids = _clicks_for_ids
_faux_gms.sante_cles = lambda: []
_faux_gms.etat_quota = lambda: {}
_faux_gms.pause_restante = lambda: 0
sys.modules["gms"] = _faux_gms

# ------------------------------------------------------- faux MyPuls -------
NOMS_MP = {"emy.brw/c42": "Roucham - ( normal )", "emy.brw/c43": "Roucham - ( spam )",
           "emy.brw/c37": "Tsiry - ( normal )", "emy.brw/c44": "Ricrado  - ( normal )",
           "emy.brw/c6": "Twitter VA 31 @abdoul_9684"}
VISITES = {}
MP = {"appels": [], "suivi": []}


def _mp_api_get(path, params=None, _essai=0):
    params = dict(params or {})
    MP["appels"].append((path, params.get("from"), params.get("to")))
    du, au = params["from"], params["to"]
    items = []
    for t, nom in NOMS_MP.items():
        pseudo, code = t.split("/")
        jours = VISITES.get(t, {})
        items.append({"code": code, "name": nom, "url": f"https://onlyfans.com/{pseudo}/{code}",
                      "visits_period": sum(v for j, v in jours.items() if du <= j <= au),
                      "visits_total": sum(v for j, v in jours.items() if j <= au)})
    return {"ok": True, "data": {"period": {"from": du + "T00:00:00+02:00",
                                            "to": au + "T23:59:59+02:00"},
                                 "count": len(items), "data": items}}


def _mp_tracking_links(_f, debut, fin):
    MP["suivi"].append((debut, fin))
    return [{"url": OF + "jessyewdiference/c101", "abonnes_periode": 104, "revenu": 1500.5},
            {"url": OF + "jessyewdiference/c103", "abonnes_periode": 443, "revenu": 5227.4}]


_faux_mypuls = types.ModuleType("mypuls")
_faux_mypuls.api_get = _mp_api_get
_faux_mypuls.api_tracking_links = _mp_tracking_links
sys.modules["mypuls"] = _faux_mypuls

import safe_json                       # noqa: E402
import verif_discord as vd             # noqa: E402
import podium_discord as pd            # noqa: E402
import recap_clics_rest as rcr         # noqa: E402
import cogs.clickrecap as cr           # noqa: E402
import clics_personnes as cp           # noqa: E402
import clics_arrivees as ca            # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, TH, IG = pd.TWITTER_ID, pd.THREADS_ID, pd.VA_IG_ID

# Le 13/10/2026, le propriétaire a retiré la quinzaine de Threads et le récap
# des clics de Twitter (« pas besoin »), puis donné à Threads le podium de la
# semaine aux clics (tests_podium_threads_clics.py). Les réglages livrés le
# disent ; les mécanismes de la quinzaine reprise, eux, restent testés en
# remettant les deux le temps de ce fichier.
check("livré : Threads n'a plus de classement subs (profil gardé dans PROFIL_THREADS), "
      "il a le podium aux clics",
      not pd.subs_seulement(TH) and pd.podium_seulement(TH)
      and pd.PROFIL_THREADS.get("subs_seul") is True)
check("livré : le récap des clics part sur Threads seulement (Twitter retiré)",
      set(rcr.CIBLES_DEFAUT) == {TH})
pd.SERVEURS[TH] = dict(pd.PROFIL_THREADS)
rcr.CIBLES_DEFAUT[TW] = dict(rcr._REPORT_US, salon=rcr.SALON_CLICS)
AUTRE = "1535758943324999711"          # Youl4b : le serveur du report d'origine
NUMEROS = {"Roucham": 12, "Roucham SPAM": 24, "tsiry 1": 43, "Ricardo": 22, "abdoul_9684": 31}

# ------------------------------------------------------------ faux Discord --
SALONS = {
    TW: [{"id": "tw-cat", "name": "<<<🔔NOTIFICATION >>>", "type": 4},
         {"id": "tw-podium", "name": "─│🏆┤-podium", "type": 0},
         {"id": "1552385975806726154", "name": "─│👤┤-subs", "type": 0},
         {"id": "1559405794586525726", "name": "─│📊┤-l-clicks", "type": 0},
         {"id": "tw-paliers", "name": "─│🏆┤-paliers-subs", "type": 0},
         {"id": "tw-bonus", "name": "─│💸┤-bonus-journalier", "type": 0}],
    TH: [{"id": "th-cat", "name": "<<<🔔NOTIFICATION >>>", "type": 4},
         {"id": "th-podium", "name": "─│🏆┤-podium", "type": 0},
         {"id": "1552665019752120485", "name": "─│👤┤-subs", "type": 0},
         {"id": "1559405318327242842", "name": "─│📊┤-l-clicks", "type": 0},
         {"id": "th-paliers", "name": "─│🏆┤-paliers-subs", "type": 0},
         {"id": "th-bonus", "name": "─│💸┤-bonus-journalier", "type": 0}],
    IG: [{"id": "ig-subs", "name": "─│🪙┤-subs", "type": 0},
         {"id": "ig-podium", "name": "─│🏁┤-podium", "type": 0}],
}
SUBS_TW, SUBS_TH = "1552385975806726154", "1552665019752120485"
CLICS_TW, CLICS_TH = "1559405794586525726", "1559405318327242842"
UTILISATEUR = {"siri": "1552153790701117480", "threads": "1552789379574145126"}
# le bot qui a le droit d'agir sur chaque serveur (le mur est physique : 403 ailleurs)
SERT = {"siri": {TW, IG, AUTRE}, "threads": {TH}}


class FauxDiscord:
    """Discord vu par verif_discord._http : chaque appel note LE BOT qui l'a fait."""

    def __init__(self):
        self.appels, self.n = [], 0
        self.messages = {}             # id -> {salon, auteur, embeds, content, epingle}
        self.pannes = []               # [(methode, debut du chemin, code, réponse)] une fois chacune

    def guilde_du_salon(self, cid):
        return next((g for g, xs in SALONS.items() if any(x["id"] == cid for x in xs)), "")

    def http(self, bot, methode, chemin, js):
        self.appels.append({"bot": bot["id"], "m": methode, "p": chemin, "json": copy.deepcopy(js)})
        for i, (m, debut, code, rep) in enumerate(self.pannes):
            if m == methode and chemin.startswith(debut):
                self.pannes.pop(i)
                return code, rep
        bouts = chemin.split("?")[0].strip("/").split("/")
        if chemin == "/users/@me":
            return 200, {"id": UTILISATEUR[bot["id"]]}
        if bouts[0] == "guilds":
            if bouts[1] not in SERT[bot["id"]]:
                return 403, {"code": 50001, "message": "Missing Access"}
            return 200, copy.deepcopy(SALONS.get(bouts[1], []))
        if bouts[0] != "channels":
            return 404, {"code": 0}
        cid = bouts[1]
        if self.guilde_du_salon(cid) not in SERT[bot["id"]]:
            return 403, {"code": 50001, "message": "Missing Access"}
        moi = UTILISATEUR[bot["id"]]
        if len(bouts) == 3 and bouts[2] == "messages" and methode == "POST":
            self.n += 1
            mid = f"M{self.n}"
            self.messages[mid] = {"salon": cid, "auteur": moi, "embeds": copy.deepcopy(js["embeds"]),
                                  "content": js.get("content", ""), "epingle": False}
            return 200, {"id": mid}
        if len(bouts) == 3 and bouts[2] == "messages" and methode == "GET":
            out = [{"id": k, "author": {"id": v["auteur"]}, "embeds": v["embeds"]}
                   for k, v in self.messages.items() if v["salon"] == cid]
            return 200, list(reversed(out))
        if len(bouts) == 3 and bouts[2] == "pins" and methode == "GET":
            return 200, [{"id": k, "author": {"id": v["auteur"]}, "embeds": v["embeds"]}
                         for k, v in self.messages.items() if v["salon"] == cid and v["epingle"]]
        if len(bouts) == 4 and bouts[2] == "pins" and methode == "PUT":
            if bouts[3] in self.messages:
                self.messages[bouts[3]]["epingle"] = True
                return 204, {}
            return 404, {"code": 10008}
        if len(bouts) == 4 and bouts[2] == "messages":
            mid = bouts[3]
            msg = self.messages.get(mid)
            if not msg or msg["salon"] != cid:
                return 404, {"code": 10008, "message": "Unknown Message"}
            if methode == "DELETE":
                self.messages.pop(mid)
                return 204, {}
            if msg["auteur"] != moi:
                return 403, {"code": 50005, "message": "Cannot edit a message authored by another user"}
            if "embeds" in js:
                msg["embeds"] = copy.deepcopy(js["embeds"])
            if "content" in js:
                msg["content"] = js["content"]
            return 200, {"id": mid}
        return 404, {"code": 0}

    def depuis(self, k):
        return self.appels[k:]


DISCORD = FauxDiscord()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="recaps_tw_th_test_"))

# les deux bots prêts, chacun son jeton : Luigi (siri) et Bowser (threads)
_ENV_AVANT = {k: os.environ.get(k) for k in ("SEVEN_BOT_TOKEN", "THREADS_BOT_TOKEN",
                                             "VA_MACHINE_PROD")}
os.environ["SEVEN_BOT_TOKEN"] = "jeton-luigi"
os.environ["THREADS_BOT_TOKEN"] = "jeton-bowser"
os.environ.pop("VA_MACHINE_PROD", None)
_VD_AVANT = (vd.DATA_DIR, vd._http)
vd.DATA_DIR = TMP / "vd"
vd.DATA_DIR.mkdir()
safe_json.write(vd.DATA_DIR / "bots_config.json",
                {"threads_app_id": "1552789379574145126", "threads_cle_publique": "b" * 64})
vd._http = lambda bot, methode, chemin, _sans_jeton=False, **kw: DISCORD.http(
    bot, methode, chemin, kw.get("json"))

_NB = [0]


def installer():
    """Un bac neuf : dossier, horloge, Discord, faux services remis à zéro."""
    global DISCORD
    _NB[0] += 1
    d = TMP / f"bac{_NB[0]}"
    d.mkdir()
    safe_json.write_text(d / "podium_numeros.json", json.dumps(NUMEROS))
    pd.DATA_DIR = d
    pd.ETAT_FICHIER = d / "podium.json"
    pd.CONFIG_FICHIER = d / "podium_config.json"
    pd.NUMEROS_FICHIER = d / "podium_numeros.json"
    pd.LIENS_CACHE = d / "gmsdash_links.json"
    pd.ALLTIME_FICHIER = d / "podium_alltime.json"
    rcr.DATA_DIR = d
    cr._REPORT_CFG_FILE = d / "report_click.json"
    cr._PREC_FILE = d / "clickrecap_prec.json"
    CLOCK["now"] = dt.datetime(2026, 10, 13, 10, 0)
    pd._maintenant = lambda: CLOCK["now"]
    pd._aujourdhui = lambda: CLOCK["now"].date()
    horloge = types.SimpleNamespace(time=lambda: CLOCK["now"].timestamp(), sleep=lambda s: None)
    pd.time = horloge
    rcr.time = horloge
    cr._paris_now = lambda: CLOCK["now"]
    pd._pause_gms = lambda: False
    DISCORD = FauxDiscord()
    pd._RELEVES.clear()
    pd._RELEVES_LUS = False
    pd._REPRIS.clear()
    pd._REPRIS_LUS = False
    pd._MP_LUS.clear()
    rcr._MOI.clear()
    GMS["listes"].clear()
    GMS["analytics"].clear()
    GMS["report"].clear()
    GMS["muet"] = False
    MP["appels"].clear()
    MP["suivi"].clear()
    VISITES.clear()
    VISITES.update({"emy.brw/c42": {"2026-10-01": 30, "2026-10-13": 12},
                    "emy.brw/c43": {"2026-10-12": 4},
                    "emy.brw/c37": {"2026-10-13": 5},
                    "emy.brw/c44": {"2026-10-05": 9},
                    "emy.brw/c6": {"2026-10-13": 3}})
    CLICS["facteur"] = 1
    return d


def posts(appels, salon=None):
    return [a for a in appels if a["m"] == "POST" and a["p"].endswith("/messages")
            and (salon is None or a["p"] == f"/channels/{salon}/messages")]


def patchs(appels, salon=None):
    return [a for a in appels if a["m"] == "PATCH"
            and (salon is None or a["p"].startswith(f"/channels/{salon}/messages/"))]


def salons_touches(appels):
    return {a["p"].split("/")[2] for a in appels
            if a["p"].startswith("/channels/") and a["m"] in ("POST", "PATCH", "PUT", "DELETE")}


RENDU = {}
_SAUVE_CR = (cr._REPORT_CFG_FILE, cr._PREC_FILE, cr._paris_now)
_SAUVE_CP = (cp.annuaire_va, ca.toutes, ca.enregistrer_liens)
_SAUVE_RCR = (rcr.DATA_DIR, rcr.time, rcr._poste_ici)
_SAUVE_PD = {k: getattr(pd, k) for k in (
    "DATA_DIR", "ETAT_FICHIER", "CONFIG_FICHIER", "NUMEROS_FICHIER", "LIENS_CACHE",
    "ALLTIME_FICHIER", "_maintenant", "_aujourdhui", "_pause_gms", "time")}

try:
    # les fiches VA de Jessye : un pseudo inventé, pas ceux du vrai data/
    cp.annuaire_va = lambda identite="": {"roucham": "roucham_tw"} if identite else {}
    ca.toutes = lambda: {}
    ca.enregistrer_liens = lambda *a, **k: None

    # ------------------------------------------------------------------ 1
    print("\n— 1. le salon du classement subs")
    installer()
    with vd.sur_serveur(TW):
        k0 = len(DISCORD.appels)
        s_tw = pd._salon_subs(TW)
    check("Twitter : « ─│👤┤-subs » trouvé à son nom exact (profil), du premier coup",
          s_tw == SUBS_TW and len(DISCORD.depuis(k0)) == 1, (s_tw, DISCORD.depuis(k0)))
    check("le nom voulu vient du profil de Twitter (podium_config garde la main)",
          pd._nom_salon_subs(TW) == "─│👤┤-subs" and pd._nom_salon_subs(TH) == "─│👤┤-subs")
    check("Va IG garde son nom d'origine (retrouvé au nom nu, comme avant)",
          pd._nom_salon_subs(IG) == pd.SALON_SUBS == "─│📊┤-subs")
    with vd.sur_serveur(IG):
        check("… et le trouve toujours (« ─│🪙┤-subs »)", pd._salon_subs(IG) == "ig-subs")
    safe_json.write(pd.CONFIG_FICHIER, {"salon_subs": "─│📊┤-subs"})
    with vd.sur_serveur(TW):
        check("podium_config « salon_subs » à l'ancien nom : retrouvé au nom nu, jamais les paliers",
              pd._salon_subs(TW) == SUBS_TW)
    pd.CONFIG_FICHIER.unlink()
    _avant_salons = copy.deepcopy(SALONS[TW])
    try:
        SALONS[TW][2]["name"] = "👥・team-subs"
        SALONS[TW].append({"id": "tw-cat-subs", "name": "SUBS", "type": 4})
        with vd.sur_serveur(TW):
            check("renommé « 👥・team-subs » : le seul salon texte en « -subs », hors paliers "
                  "et hors catégorie", pd._salon_subs(TW) == SUBS_TW)
        SALONS[TW][2]["name"] = "─│👥┤-va-subs"
        SALONS[TW].append({"id": "tw-autre", "name": "─│🔥┤-top-subs", "type": 0})
        with vd.sur_serveur(TW):
            check("deux salons en « -subs » : aucun choisi (dit au journal)",
                  pd._salon_subs(TW) == "")
        SALONS[TW][:] = [x for x in _avant_salons if x["id"] != SUBS_TW]
        with vd.sur_serveur(TW):
            check("plus de salon subs : JAMAIS « ─│🏆┤-paliers-subs » à la place",
                  pd._salon_subs(TW) == "")
    finally:
        SALONS[TW][:] = _avant_salons

    # ------------------------------------------------------------------ 2
    print("\n— 2. Threads : le classement subs de Twitter, et rien d'autre")
    check("Threads est dans les serveurs du podium, en « subs seulement », repris de Twitter",
          TH in pd.SERVEURS and pd.subs_seulement(TH) and pd._repris_de(TH) == TW
          and not pd.subs_seulement(TW) and not pd.subs_seulement(IG))
    p_th = pd._profil(TH)
    check("son profil : celui de Twitter (marché US, clics tracking), son bot, sans bonus",
          p_th["marche"] == "US" and p_th.get("mesure") == pd.SERVEURS[TW].get("mesure")
          and p_th["bot"] == "Bowser" and p_th["bonus"] is False
          and not p_th.get("bouton_maj") and not p_th.get("theme") and not p_th.get("avec_us"))
    check("Twitter et Va IG : profils inchangés (pas de clé de Threads)",
          "reprend" not in pd._profil(TW) and "subs_seul" not in pd._profil(IG)
          and pd._profil(TW) is pd.SERVEURS[TW] and pd._profil(IG) is pd.SERVEURS[IG])

    installer()
    with vd.sur_serveur(TW):
        check("Twitter : classement à poster", pd.a_rafraichir_subs(TW))
        k_tw = len(DISCORD.appels)
        mp0, gl0 = len(MP["appels"]), len(GMS["listes"])
        mid_tw = pd.rafraichir_subs(TW)
    app_tw = DISCORD.depuis(k_tw)
    mp_tw, gl_tw = len(MP["appels"]) - mp0, len(GMS["listes"]) - gl0
    check("Twitter poste dans « ─│👤┤-subs », avec Luigi",
          mid_tw and len(posts(app_tw, SUBS_TW)) == 1
          and {a["bot"] for a in app_tw} == {"siri"}, app_tw[-3:])
    check("Twitter a lu MyPuls et les listes GetMySocial (sa lecture à lui)",
          mp_tw >= 1 and gl_tw >= 2, (MP["appels"], GMS["listes"]))
    check("son relevé est gardé pour Threads (mémoire ET disque)",
          any(k[0] == TW for k in pd._REPRIS) and pd._fichier_repris().exists())

    with vd.sur_serveur(TH):
        check("Threads : classement à poster", pd.a_rafraichir_subs(TH))
        k_th = len(DISCORD.appels)
        mp1, gl1, an1 = len(MP["appels"]), len(GMS["listes"]), len(GMS["analytics"])
        mid_th = pd.rafraichir_subs(TH)
    app_th = DISCORD.depuis(k_th)
    check("Threads poste dans SON « ─│👤┤-subs », avec SON bot (Bowser), rien d'autre",
          mid_th and len(posts(app_th, SUBS_TH)) == 1 and {a["bot"] for a in app_th} == {"threads"}
          and salons_touches(app_th) == {SUBS_TH}, app_th)
    check("AUCUNE lecture de plus : ni MyPuls, ni liste GetMySocial, ni analytics",
          len(MP["appels"]) == mp1 and len(GMS["listes"]) == gl1
          and len(GMS["analytics"]) == an1, (MP["appels"][mp1:], GMS["listes"][gl1:]))
    e_tw = posts(app_tw, SUBS_TW)[0]["json"]
    e_th = posts(app_th, SUBS_TH)[0]["json"]
    check("le MÊME message que Twitter, à l'octet (chiffres, « VA n », en-tête, pied)",
          e_th == e_tw, (e_tw, e_th))
    d_th = e_th["embeds"][0]
    check("le pied dit « Marché US », comme Twitter ; les libellés sont les « VA n » de Twitter",
          "Marché US" in d_th["footer"]["text"] and "**VA 12**" in d_th["description"]
          and "Clics **tracking OF**" in d_th["description"])
    check("aucun bouton (Threads n'en a pas, Twitter non plus)",
          "components" not in e_th)
    RENDU["subs_threads"] = e_th

    with vd.sur_serveur(TW):
        tw_du = pd.a_rafraichir_subs(TW)
    with vd.sur_serveur(TH):
        th_du = pd.a_rafraichir_subs(TH)
    check("juste après : ni l'un ni l'autre à refaire", not tw_du and not th_du)
    CLOCK["now"] += dt.timedelta(minutes=30)
    check("trente minutes plus tard : toujours rien",
          not pd.a_rafraichir_subs(TW) and not pd.a_rafraichir_subs(TH))

    # une heure plus tard : Twitter relève, Threads suit au même passage
    CLOCK["now"] += dt.timedelta(minutes=31)
    VISITES["emy.brw/c42"]["2026-10-13"] = 40
    pd._MP_LUS.clear()
    with vd.sur_serveur(TW):
        k2 = len(DISCORD.appels)
        if pd.a_rafraichir_subs(TW):
            pd.rafraichir_subs(TW)
    check("Twitter se refait à son rythme (édité sur place)",
          len(patchs(DISCORD.depuis(k2), SUBS_TW)) == 1 and not posts(DISCORD.depuis(k2)))
    mp2, gl2 = len(MP["appels"]), len(GMS["listes"])
    with vd.sur_serveur(TH):
        th_suit = pd.a_rafraichir_subs(TH)
        k3 = len(DISCORD.appels)
        if th_suit:
            pd.rafraichir_subs(TH)
    a3 = DISCORD.depuis(k3)
    check("Threads suit aussitôt (relevé de Twitter plus récent que son message)", th_suit)
    check("… édité sur place, avec les chiffres neufs de Twitter, sans aucune lecture",
          len(patchs(a3, SUBS_TH)) == 1 and not posts(a3)
          and "**70** subs" in patchs(a3, SUBS_TH)[0]["json"]["embeds"][0]["description"]
          and len(MP["appels"]) == mp2 and len(GMS["listes"]) == gl2,
          [x["json"]["embeds"][0]["description"][:300] for x in patchs(a3)])
    check("… et le même texte que Twitter",
          patchs(a3, SUBS_TH)[0]["json"] == patchs(DISCORD.depuis(k2), SUBS_TW)[0]["json"])

    # redémarrage : le relevé est relu du disque
    pd._REPRIS.clear()
    pd._REPRIS_LUS = False
    pd._MP_LUS.clear()
    CLOCK["now"] += dt.timedelta(minutes=5)
    mp4, gl4 = len(MP["appels"]), len(GMS["listes"])
    with vd.sur_serveur(TH):
        k4 = len(DISCORD.appels)
        pd.rafraichir_subs(TH, forcer=True)
    check("après un redémarrage : le relevé de Twitter repris du disque, aucune lecture",
          len(MP["appels"]) == mp4 and len(GMS["listes"]) == gl4
          and len(patchs(DISCORD.depuis(k4), SUBS_TH)) == 1)

    # Twitter muet depuis deux heures : Threads relève, avec les sources de Twitter
    CLOCK["now"] += dt.timedelta(hours=2)
    pd._MP_LUS.clear()
    mp5, gl5 = len(MP["appels"]), len(GMS["listes"])
    with vd.sur_serveur(TH):
        th_du2 = pd.a_rafraichir_subs(TH)
        k5 = len(DISCORD.appels)
        pd.rafraichir_subs(TH)
    nouv_listes = GMS["listes"][gl5:]
    check("Twitter muet : Threads relève lui-même, UNE fois, avec les sources de Twitter",
          th_du2 and len(MP["appels"]) - mp5 == 1 and sorted(nouv_listes) == sorted([EQ_TW1, EQ_TW2]),
          (MP["appels"][mp5:], nouv_listes))
    check("… gardé sous le nom de Twitter (Threads ne relit pas au tour suivant)",
          pd._repris_t(TH) > 0 and not pd.a_rafraichir_subs(TH))
    check("… et posté par Bowser dans le salon de Threads",
          {a["bot"] for a in DISCORD.depuis(k5)} == {"threads"}
          and salons_touches(DISCORD.depuis(k5)) == {SUBS_TH})

    # ni podium, ni bonus, ni paliers
    k6 = len(DISCORD.appels)
    mp6, gl6 = len(MP["appels"]), len(GMS["listes"])
    with vd.sur_serveur(TH):
        r_pod = pd.poster_podium(TH)
        r_sem = pd.rafraichir(TH)
        r_bon = pd.rafraichir_bonus(TH)
        du_sem, du_bon = pd.a_rafraichir(TH), pd.a_rafraichir_bonus(TH)
    check("Threads : ni podium de la semaine, ni message de la semaine, ni bonus du jour",
          r_pod == r_sem == r_bon == "" and not du_sem and not du_bon)
    check("… sans un appel à Discord ni une lecture",
          DISCORD.depuis(k6) == [] and len(MP["appels"]) == mp6 and len(GMS["listes"]) == gl6)
    tous_th = [a for a in DISCORD.appels if a["bot"] == "threads"]
    check("de tout ce test, Bowser n'a écrit QUE dans « ─│👤┤-subs » (pas podium, bonus, paliers)",
          salons_touches(tous_th) == {SUBS_TH}, salons_touches(tous_th))
    check("aucune prime annoncée pour Threads", TH not in _PRIMES)

    # la quinzaine finie se fige sur Threads aussi, sur le relevé entier de Twitter
    CLOCK["now"] = dt.datetime(2026, 10, 16, 12, 30)
    pd._MP_LUS.clear()
    VISITES["emy.brw/c6"]["2026-10-15"] = 8
    with vd.sur_serveur(TW):
        k7 = len(DISCORD.appels)
        pd.rafraichir_subs(TW)
    fige_tw = [a for a in patchs(DISCORD.depuis(k7), SUBS_TW)
               if "(terminée)" in a["json"]["embeds"][0]["title"]]
    mp7, gl7 = len(MP["appels"]), len(GMS["listes"])
    with vd.sur_serveur(TH):
        k8 = len(DISCORD.appels)
        pd.rafraichir_subs(TH)
    a8 = DISCORD.depuis(k8)
    fige_th = [a for a in patchs(a8, SUBS_TH) if "(terminée)" in a["json"]["embeds"][0]["title"]]
    def sans_alltime(js):
        e = copy.deepcopy(js["embeds"][0])
        e["description"] = re.sub(r" · 🌐 \d+ all-time", "", e["description"])
        return e
    at_tw = pd._alltime_lu(TW)
    check("quinzaine finie : Threads fige sa page sur le relevé entier de Twitter (mêmes subs, "
          "même titre, même pied « résultat final »)",
          len(fige_tw) == 1 and len(fige_th) == 1
          and sans_alltime(fige_th[0]["json"]) == sans_alltime(fige_tw[0]["json"])
          and "résultat final" in fige_th[0]["json"]["embeds"][0]["footer"]["text"],
          (fige_tw and sans_alltime(fige_tw[0]["json"]), fige_th and sans_alltime(fige_th[0]["json"])))
    # Twitter fige AVANT de relire son « depuis toujours » du jour (pour sa
    # quinzaine neuve) ; Threads passe après : il montre ce total-là, celui du
    # fichier de Twitter, sans l'avoir relu lui-même
    check("… le total « depuis toujours » est celui du fichier de Twitter, lu sans appel",
          "🌐 %d all-time" % at_tw["VA 12"] in fige_th[0]["json"]["embeds"][0]["description"])
    check("… puis la quinzaine neuve repart en message neuf, toujours sans lecture à lui",
          len(posts(a8, SUBS_TH)) == 1 and len(MP["appels"]) == mp7
          and len(GMS["listes"]) == gl7, (MP["appels"][mp7:], GMS["listes"][gl7:]))

    # ------------------------------------------------------------------ 3
    print("\n— 3. la boucle du site (web_upload)")
    src_w = (BOT / "web_upload.py").read_text(encoding="utf-8")
    arbre = ast.parse(src_w)
    boucle = None
    aide = None
    for n in ast.walk(arbre):
        if isinstance(n, ast.FunctionDef) and n.name == "_recap_clics_rest":
            aide = n
        if (isinstance(n, ast.For) and isinstance(n.iter, ast.Attribute)
                and n.iter.attr == "SERVEURS_EXTRA"
                and "a_rafraichir_subs" in (ast.get_source_segment(src_w, n) or "")):
            boucle = n
    check("la boucle du podium et l'aide du récap des clics sont trouvées", boucle and aide)
    faits = []

    def note(nom):
        return lambda *a, **k: faits.append((nom, vd.serveur_courant(), a[0] if a else None))
    faux_p = types.SimpleNamespace(
        SERVEURS=pd.SERVEURS, subs_seulement=pd.subs_seulement,
        podium_seulement=pd.podium_seulement,
        a_poster=lambda: True, poster_podium=note("podium"),
        a_rafraichir=lambda g: True, rafraichir=note("semaine"),
        a_rafraichir_subs=lambda g: True, rafraichir_subs=note("subs"),
        a_rafraichir_bonus=lambda g: True, rafraichir_bonus=note("bonus"))
    ns = {"_p": faux_p, "_vd_p": vd, "_sync_liens_va": note("liens"), "_suivi_va": note("suivi"),
          "_recap_clics_rest": note("clics")}
    exec(compile(textwrap.dedent(ast.get_source_segment(src_w, boucle)), "boucle", "exec"), ns)

    def par(g):
        return [f for f, s, a in faits if a == g]
    check("Threads : le récap des clics et le classement de la quinzaine, RIEN d'autre",
          par(TH) == ["clics", "subs"], par(TH))
    check("… le classement fait avec le bot de Threads (sur_serveur)",
          [s for f, s, a in faits if a == TH and f == "subs"] == [TH])
    check("Twitter : tout comme avant (podium, semaine, quinzaine, bonus, liens, suivi) + le récap",
          par(TW) == ["clics", "podium", "semaine", "subs", "bonus", "liens", "suivi"], par(TW))
    check("Va IG : tout comme avant (son récap des clics n'existe pas, l'aide le saute)",
          par(IG) == ["clics", "podium", "semaine", "subs", "bonus", "liens", "suivi"]
          and IG not in rcr.cibles(), par(IG))
    ns_a = {}
    exec(compile(ast.get_source_segment(src_w, aide), "aide", "exec"), ns_a)
    vus = []
    _pub = rcr.publier
    try:
        rcr.publier = lambda g: vus.append((g, vd.serveur_courant())) or "M"
        for g in (TW, TH, IG, AUTRE):
            ns_a["_recap_clics_rest"](g)
        rcr.publier = lambda g: (_ for _ in ()).throw(RuntimeError("panne simulée"))
        ns_a["_recap_clics_rest"](TW)          # ne doit rien lever
        panne_avalee = True
    except Exception:
        panne_avalee = False
    finally:
        rcr.publier = _pub
    check("l'aide ne publie que pour Twitter et Threads, chacun dans le contexte de son serveur",
          vus == [(TW, TW), (TH, TH)], vus)
    check("une panne du récap n'arrête pas la boucle (dite au journal)", panne_avalee)

    # ------------------------------------------------------------------ 4
    print("\n— 4. le récap des clics dans « ─│📊┤-l-clicks »")
    installer()
    rcr._poste_ici = lambda: True
    SOURCE = {"channel_id": 1541139559729864704, "team_id": EQ_TW1, "group_id": None,
              "identity": None, "group_name": "JESSY LE RETOUR", "marche": "us", "tout": True,
              "message_id": 1541178887621316659, "image_message_id": 1554401283245473853}
    safe_json.write(cr._REPORT_CFG_FILE, {f"{AUTRE}:1541139559729864704": SOURCE})
    check("deux serveurs, et seulement eux : Twitter et Threads, au salon « ─│📊┤-l-clicks »",
          set(rcr.cibles()) == {TW, TH}
          and all(c["salon"] == "─│📊┤-l-clicks" for c in rcr.cibles().values()))
    check("… le même report que le salon click-us de Youl4b (JESSY LE RETOUR, US, tout l'espace)",
          rcr.signature(rcr.cibles()[TW]) == rcr.signature(rcr.cibles()[TH]) == rcr.signature(SOURCE)
          and rcr._source_configuree(rcr.signature(SOURCE)) == f"{AUTRE}:1541139559729864704")

    # le réglage se change sans redéployer : null retire un serveur, une
    # entrée illisible est écartée (et dite), le reste garde le défaut
    safe_json.write(rcr._fichier_config(), {"cibles": {TH: None, TW: {"salon": "─│📊┤-clics"},
                                                       IG: "n'importe quoi"}})
    _c_sur = rcr.cibles()
    check("data/recap_clics_rest.json : null retire Threads, un salon se renomme, "
          "une entrée illisible est ignorée",
          set(_c_sur) == {TW} and _c_sur[TW]["salon"] == "─│📊┤-clics"
          and _c_sur[TW]["team_id"] == EQ_TW1, _c_sur)
    rcr._fichier_config().unlink()

    class _Faux:
        pass

    CLE_SOURCE = f"{AUTRE}:1541139559729864704"
    EDITES = []

    class _FauxMsgYoshi:
        """Le message épinglé du salon click-us, que Yoshi édite (discord.py)."""
        id = SOURCE["message_id"]
        flags = None

        async def edit(self, **kw):
            EDITES.append(kw.get("embed"))

    class _FauxSalonYoshi:
        guild = None                   # pas de « me » : la vérification des droits passe

        async def fetch_message(self, mid):
            return _FauxMsgYoshi()

    _yoshi = types.SimpleNamespace(bot=types.SimpleNamespace(
        get_channel=lambda cid: _FauxSalonYoshi()))
    _yoshi._build_group_report = (
        lambda c, **kw: cr.ClickRecap._build_group_report(_yoshi, c, **kw))

    async def _sans_image(*a, **k):
        return None                    # les images du report ne sont pas l'objet ici

    def report_source():
        """Le report horaire de Youl4b, PUBLIÉ par le vrai _post_or_update_report
        (faux GetMySocial, faux salon) : rend l'embed édité dans click-us."""
        _img = cr._classement_en_image
        cr._classement_en_image = _sans_image
        try:
            n = len(EDITES)
            raison = asyncio.run(cr.ClickRecap._post_or_update_report(_yoshi, CLE_SOURCE))
        finally:
            cr._classement_en_image = _img
        return EDITES[-1] if raison == "" and len(EDITES) == n + 1 else None

    emb = report_source()
    rel = safe_json.load(rcr._fichier_releves(), default={})
    sig = rcr.signature(SOURCE)
    check("le report de Youl4b dépose son embed COMPLET au passage (aucun appel de plus)",
          emb is not None and sig in rel and rel[sig]["embed"] == json.loads(json.dumps(emb.to_dict())),
          list(rel))
    check("… et le marqueur « publié » ne survit pas à la publication hors de sa tâche",
          cr._REPORT_PUBLIE.get() == "")

    # LES AUTRES CONSTRUCTIONS DU MÊME ESPACE NE TOUCHENT À RIEN : la page
    # publique des clics (un lien « Jessy US » créé dans Settings, ou une portée
    # sans nom -> « Groupe ») et l'essai du rig (« Rien n'est écrit »)
    # construisent le même report, sans être publiés
    avant_rel = rcr._fichier_releves().read_bytes()
    portail = {"team_id": EQ_TW1, "group_id": None, "identity": None,
               "group_name": "Jessy US", "marche": "us", "tout": True}
    check("(la page publique a bien la même signature que la source)",
          rcr.signature(portail) == sig)
    gardes = []
    _vrai_retenir = rcr.retenir

    def _espion(*a, **k):
        r = _vrai_retenir(*a, **k)
        gardes.append(r)
        return r
    rcr.retenir = _espion
    try:
        # chaque construction contrôlée seule : l'horloge est figée, et l'essai
        # du rig (le report d'origine) réécrirait à l'octet ce que la page
        # publique aurait changé
        e_portail = asyncio.run(cr.ClickRecap._build_group_report(_Faux(), dict(portail)))
        check("page publique « Jessy US » : construite, mais RIEN de gardé",
              e_portail is not None and e_portail.title == "🇺🇸 Clicks — Jessy US"
              and not any(gardes) and rcr._fichier_releves().read_bytes() == avant_rel, gardes)
        e_essai = asyncio.run(cr.ClickRecap._build_group_report(_Faux(), dict(SOURCE)))
        check("essai du rig (« Rien n'est écrit ») : construit, mais RIEN de gardé",
              e_essai is not None and not any(gardes)
              and rcr._fichier_releves().read_bytes() == avant_rel, gardes)
    finally:
        rcr.retenir = _vrai_retenir
    # un second report PUBLIÉ du même espace, sous un autre nom : un seul fait foi
    safe_json.write(cr._REPORT_CFG_FILE, {CLE_SOURCE: SOURCE,
                                          f"{AUTRE}:999": dict(SOURCE, channel_id=999,
                                                               group_name="Jessy bis")})
    jeton = cr._REPORT_PUBLIE.set(f"{AUTRE}:999")
    try:
        asyncio.run(cr.ClickRecap._build_group_report(
            _Faux(), dict(SOURCE, channel_id=999, group_name="Jessy bis")))
    finally:
        cr._REPORT_PUBLIE.reset(jeton)
    check("un second report publié du même espace (« Jessy bis ») n'est pas repris : "
          "seul celui que l'on attend fait foi",
          rcr._fichier_releves().read_bytes() == avant_rel)
    safe_json.write(cr._REPORT_CFG_FILE, {CLE_SOURCE: SOURCE})
    _sauve_env = os.environ.get("VA_MACHINE_PROD")
    rcr._poste_ici = _SAUVE_RCR[2]
    os.environ.pop("VA_MACHINE_PROD", None)
    rcr._fichier_releves().unlink()
    report_source()
    check("hors de la machine qui poste (tests, Mac) : rien n'est gardé",
          not rcr._fichier_releves().exists())
    rcr._poste_ici = lambda: True
    emb = report_source()
    n_gms = len(GMS["report"])
    k0 = len(DISCORD.appels)
    with vd.sur_serveur(TW):
        m_tw = rcr.publier(TW)
    a_tw = DISCORD.depuis(k0)
    check("Twitter : récap posté dans « ─│📊┤-l-clicks », par Luigi, et épinglé",
          m_tw and len(posts(a_tw, CLICS_TW)) == 1 and {a["bot"] for a in a_tw} == {"siri"}
          and DISCORD.messages[m_tw]["epingle"], a_tw)
    corps = posts(a_tw, CLICS_TW)[0]["json"]
    check("… le contenu et l'embed du report d'origine (minuteur, titre, champs, pied)",
          corps["embeds"] == [json.loads(json.dumps(emb.to_dict()))]
          and corps["content"].startswith("⏱️ **Prochaine mise à jour** <t:")
          and corps["embeds"][0]["title"] == "🇺🇸 Clicks — JESSY LE RETOUR")
    check("… sans bouton, sans mention", "components" not in corps
          and corps.get("allowed_mentions") == {"parse": []})
    RENDU["clics"] = corps
    k1 = len(DISCORD.appels)
    with vd.sur_serveur(TH):
        m_th = rcr.publier(TH)
    a_th = DISCORD.depuis(k1)
    check("Threads : le même récap dans SON « ─│📊┤-l-clicks », par Bowser",
          m_th and len(posts(a_th, CLICS_TH)) == 1 and {a["bot"] for a in a_th} == {"threads"}
          and posts(a_th, CLICS_TH)[0]["json"]["embeds"] == corps["embeds"], a_th)
    check("… aucun appel GetMySocial ni MyPuls pour les deux",
          len(GMS["report"]) == n_gms)
    k2 = len(DISCORD.appels)
    rcr.publier(TW)
    rcr.publier(TH)
    check("rien de neuf : aucun appel à Discord", DISCORD.depuis(k2) == [])

    # l'heure suivante : le report change, les deux récaps sont édités sur place
    CLOCK["now"] += dt.timedelta(hours=1)
    CLICS["facteur"] = 2
    emb2 = report_source()
    k3 = len(DISCORD.appels)
    with vd.sur_serveur(TW):
        rcr.publier(TW)
    with vd.sur_serveur(TH):
        rcr.publier(TH)
    a3 = DISCORD.depuis(k3)
    check("relevé neuf : chaque récap ÉDITÉ sur place, aucun message de plus",
          [a["p"] for a in patchs(a3)] == [f"/channels/{CLICS_TW}/messages/{m_tw}",
                                            f"/channels/{CLICS_TH}/messages/{m_th}"]
          and not posts(a3)
          and patchs(a3)[0]["json"]["embeds"] == [json.loads(json.dumps(emb2.to_dict()))], a3)
    check("… chacun par le bot de son serveur",
          [a["bot"] for a in patchs(a3)] == ["siri", "threads"])

    # redémarrage : l'état est sur disque
    rcr._MOI.clear()
    CLOCK["now"] += dt.timedelta(hours=1)
    report_source()
    k4 = len(DISCORD.appels)
    with vd.sur_serveur(TW):
        rcr.publier(TW)
    a4 = DISCORD.depuis(k4)
    check("après un redémarrage : le même message, édité (un seul appel)",
          len(a4) == 1 and a4[0]["m"] == "PATCH" and a4[0]["p"].endswith(m_tw), a4)

    # état perdu : le récap est retrouvé dans le salon, pas reposté
    rcr._fichier_etat().unlink()
    prev = rcr._fichier_etat().with_name(rcr._fichier_etat().name + ".prev")
    if prev.exists():
        prev.unlink()                  # sinon safe_json le restaure : pas un état perdu
    rcr._MOI.clear()
    CLOCK["now"] += dt.timedelta(hours=1)
    report_source()
    k5 = len(DISCORD.appels)
    with vd.sur_serveur(TW):
        m5 = rcr.publier(TW)
    a5 = DISCORD.depuis(k5)
    check("état perdu : retrouvé à son auteur et à son titre, édité — jamais en double",
          m5 == m_tw and not posts(a5) and len(patchs(a5, CLICS_TW)) == 1
          and any(a["m"] == "GET" and a["p"] == f"/channels/{CLICS_TW}/pins" for a in a5)
          and sum(1 for v in DISCORD.messages.values() if v["salon"] == CLICS_TW) == 1, a5)

    # Discord en panne passagère : rien de reposté, nouvel essai au passage suivant
    CLOCK["now"] += dt.timedelta(hours=1)
    report_source()
    DISCORD.pannes.append(("PATCH", f"/channels/{CLICS_TW}/messages/", 503, {"message": "down"}))
    k6 = len(DISCORD.appels)
    with vd.sur_serveur(TW):
        rcr.publier(TW)
    a6 = DISCORD.depuis(k6)
    with vd.sur_serveur(TW):
        rcr.publier(TW)
    a6b = DISCORD.depuis(k6 + len(a6))
    check("Discord en panne : message gardé, rien reposté ; repris au passage suivant",
          not posts(a6) and len(patchs(a6)) == 1 and len(patchs(a6b)) == 1 and not posts(a6b),
          (a6, a6b))

    # supprimé à la main : un neuf, un seul
    DISCORD.messages.pop(m_tw)
    CLOCK["now"] += dt.timedelta(hours=1)
    report_source()
    k7 = len(DISCORD.appels)
    with vd.sur_serveur(TW):
        m7 = rcr.publier(TW)
    a7 = DISCORD.depuis(k7)
    check("supprimé à la main : un récap neuf, un seul, épinglé",
          m7 and m7 != m_tw and len(posts(a7, CLICS_TW)) == 1
          and sum(1 for v in DISCORD.messages.values() if v["salon"] == CLICS_TW) == 1
          and DISCORD.messages[m7]["epingle"], a7)

    # LE SALON RÉGLÉ CHANGE (data/recap_clics_rest.json) : le récap y part au
    # relevé suivant, l'ancien message reste tel quel
    CLICS_TW2 = "tw-clics2"
    SALONS[TW].append({"id": CLICS_TW2, "name": "─│📊┤-clics", "type": 0})
    try:
        with vd.sur_serveur(TH):
            rcr.publier(TH)            # Threads à jour avant le changement de Twitter
        safe_json.write(rcr._fichier_config(), {"cibles": {TW: {"salon": "─│📊┤-clics"}}})
        avant_m7 = copy.deepcopy(DISCORD.messages[m7])
        CLOCK["now"] += dt.timedelta(hours=1)
        report_source()
        k_s = len(DISCORD.appels)
        with vd.sur_serveur(TW):
            m_s = rcr.publier(TW)
        with vd.sur_serveur(TH):
            m_s_th = rcr.publier(TH)
        a_s = DISCORD.depuis(k_s)
        check("salon de Twitter changé dans le réglage : le récap part dans le nouveau, "
              "par Luigi, épinglé ; l'ancien n'est ni édité ni effacé",
              m_s and m_s != m7 and DISCORD.messages[m_s]["salon"] == CLICS_TW2
              and DISCORD.messages[m_s]["epingle"]
              and len(posts(a_s, CLICS_TW2)) == 1 and not patchs(a_s, CLICS_TW)
              and DISCORD.messages.get(m7) == avant_m7
              and all(a["bot"] == "siri" for a in a_s if CLICS_TW2 in a["p"]), a_s)
        check("… Threads, lui, garde son salon et son message (édité sur place)",
              m_s_th == m_th and [a["p"] for a in patchs(a_s, CLICS_TH)]
              == [f"/channels/{CLICS_TH}/messages/{m_th}"] and not posts(a_s, CLICS_TH))
        CLOCK["now"] += dt.timedelta(hours=1)
        report_source()
        k_s2 = len(DISCORD.appels)
        with vd.sur_serveur(TW):
            rcr.publier(TW)
        a_s2 = DISCORD.depuis(k_s2)
        check("… l'heure suivante : édité sur place dans le nouveau salon, un seul appel",
              len(a_s2) == 1 and a_s2[0]["m"] == "PATCH"
              and a_s2[0]["p"] == f"/channels/{CLICS_TW2}/messages/{m_s}", a_s2)
        # retour au réglage d'origine, mais la liste des salons illisible ce
        # tour-là (Discord en panne) : le récap reste où il est, rien de perdu
        rcr._fichier_config().unlink()
        CLOCK["now"] += dt.timedelta(hours=1)
        report_source()
        DISCORD.pannes.append(("GET", f"/guilds/{TW}/channels", 503, {"message": "down"}))
        k_s3 = len(DISCORD.appels)
        with vd.sur_serveur(TW):
            rcr.publier(TW)
        a_s3 = DISCORD.depuis(k_s3)
        check("salon réglé introuvable (liste des salons en panne) : le récap reste édité "
              "dans son salon, rien posté",
              [a["m"] for a in a_s3] == ["GET", "PATCH"]
              and a_s3[1]["p"] == f"/channels/{CLICS_TW2}/messages/{m_s}"
              and not posts(a_s3), a_s3)
        # le relevé suivant retente : l'ancien récap est retrouvé dans le salon
        # d'origine et édité, pas reposté
        CLOCK["now"] += dt.timedelta(hours=1)
        report_source()
        k_s4 = len(DISCORD.appels)
        with vd.sur_serveur(TW):
            m_s4 = rcr.publier(TW)
        a_s4 = DISCORD.depuis(k_s4)
        check("… retenté au relevé suivant : l'ancien récap du salon d'origine retrouvé et "
              "édité, pas reposté",
              m_s4 == m7 and not posts(a_s4)
              and [a["p"] for a in patchs(a_s4)] == [f"/channels/{CLICS_TW}/messages/{m7}"], a_s4)
        k_s5 = len(DISCORD.appels)
        CLOCK["now"] += dt.timedelta(hours=1)
        report_source()
        with vd.sur_serveur(TW):
            rcr.publier(TW)
        a_s5 = DISCORD.depuis(k_s5)
        check("… puis de nouveau un seul appel par relevé (le nom réglé est noté)",
              len(a_s5) == 1 and a_s5[0]["m"] == "PATCH", a_s5)
    finally:
        SALONS[TW] = [x for x in SALONS[TW] if x["id"] != CLICS_TW2]
        if rcr._fichier_config().exists():
            rcr._fichier_config().unlink()

    # le report d'origine RENOMMÉ et l'état perdu au même moment : le récap
    # est retrouvé à son genre de titre (« 🇺🇸 Clicks — »), jamais doublé
    safe_json.write(cr._REPORT_CFG_FILE, {CLE_SOURCE: dict(SOURCE, group_name="JESSY US")})
    rcr._fichier_etat().unlink()
    prev = rcr._fichier_etat().with_name(rcr._fichier_etat().name + ".prev")
    if prev.exists():
        prev.unlink()
    rcr._MOI.clear()
    CLOCK["now"] += dt.timedelta(hours=1)
    emb_r = report_source()
    k_r = len(DISCORD.appels)
    with vd.sur_serveur(TW):
        m_r = rcr.publier(TW)
    a_r = DISCORD.depuis(k_r)
    check("report d'origine renommé + état perdu : l'ancien récap repris sous son nouveau "
          "titre, pas de second message",
          emb_r is not None and emb_r.title == "🇺🇸 Clicks — JESSY US"
          and m_r == m7 and not posts(a_r)
          and DISCORD.messages[m7]["embeds"][0]["title"] == "🇺🇸 Clicks — JESSY US"
          and sum(1 for v in DISCORD.messages.values() if v["salon"] == CLICS_TW) == 1, a_r)
    safe_json.write(cr._REPORT_CFG_FILE, {CLE_SOURCE: SOURCE})

    # rien ailleurs
    k8 = len(DISCORD.appels)
    check("aucun récap sur Va IG ni sur un autre serveur",
          rcr.publier(IG) == "" and rcr.publier(AUTRE) == "" and DISCORD.depuis(k8) == [])
    check("un report d'un autre espace n'est pas gardé (FR, ou un groupe), même publié",
          not rcr.retenir(dict(SOURCE, marche="fr"), {"title": "x"}, CLE_SOURCE)
          and not rcr.retenir(dict(SOURCE, group_id="gr_1"), {"title": "x"}, CLE_SOURCE))
    check("… et le report attendu, sans marque « publié », ne l'est pas non plus",
          not rcr.retenir(dict(SOURCE), {"title": "x"})
          and rcr.retenir(dict(SOURCE), emb.to_dict(), CLE_SOURCE))
    check("… de tout ce test, aucun message ailleurs que dans les « -l-clicks » "
          "(et le salon réglé à la place, le temps du changement)",
          salons_touches([a for a in DISCORD.appels if "/pins/" not in a["p"]])
          <= {CLICS_TW, CLICS_TH, CLICS_TW2})

    # le report d'origine muet : on l'attend, puis on le construit ici, une fois
    installer()
    rcr._poste_ici = lambda: True
    safe_json.write(cr._REPORT_CFG_FILE, {f"{AUTRE}:1541139559729864704": SOURCE})
    construits = []
    _vrai_construire = rcr._construire
    rcr._construire = lambda cib: construits.append(rcr.signature(cib)) or _vrai_construire(cib)
    try:
        k9 = len(DISCORD.appels)
        r9 = rcr.publier(TW)
        check("aucun relevé, le report de Youl4b configuré : on l'attend (rien posté, rien relevé)",
              r9 == "" and construits == [] and DISCORD.depuis(k9) == [] and GMS["report"] == [])
        CLOCK["now"] += dt.timedelta(hours=2, minutes=1)
        with vd.sur_serveur(TW):
            r10 = rcr.publier(TW)
        with vd.sur_serveur(TH):
            r11 = rcr.publier(TH)
        check("muet depuis deux heures : construit ICI, une seule fois pour les deux serveurs",
              r10 and r11 and construits == [sig]
              and len(posts(DISCORD.appels, CLICS_TW)) == 1
              and len(posts(DISCORD.appels, CLICS_TH)) == 1, construits)
        # sans report configuré : construit tout de suite, puis au plus une fois par heure
        installer()
        rcr._poste_ici = lambda: True
        construits.clear()
        GMS["muet"] = True
        rcr.publier(TW)
        rcr.publier(TH)
        check("aucun report de cet espace configuré : construit ici tout de suite, une fois "
              "(GetMySocial muet : rien posté, jamais un « No data »)",
              construits == [sig] and not posts(DISCORD.appels))
        CLOCK["now"] += dt.timedelta(minutes=30)
        rcr.publier(TW)
        check("… et pas de nouvel essai avant une heure", construits == [sig])
    finally:
        rcr._construire = _vrai_construire

    # le report horaire de Yoshi déclenche la reprise, sur la seule machine qui poste
    src_cr = (BOT / "cogs" / "clickrecap.py").read_text(encoding="utf-8")
    fin_boucle = src_cr.index("async def _poser_ranking_auto")
    bloc = src_cr[src_cr.index("async def hourly_report"):fin_boucle]
    check("le report horaire relance la reprise juste après lui (VA_MACHINE_PROD seulement)",
          "_rcr.publier_tous" in bloc and 'VA_MACHINE_PROD") == "1"' in bloc)
    check("l'appel du report et son édition sont inchangés (patchs du VPS)",
          'c, permettre_vide=not c.get("message_id"))' in src_cr
          and "await msg.edit(content=content, embed=emb," in src_cr)

finally:
    for k, v in _SAUVE_PD.items():
        setattr(pd, k, v)
    cr._REPORT_CFG_FILE, cr._PREC_FILE, cr._paris_now = _SAUVE_CR
    cp.annuaire_va, ca.toutes, ca.enregistrer_liens = _SAUVE_CP
    rcr.DATA_DIR, rcr.time, rcr._poste_ici = _SAUVE_RCR
    vd.DATA_DIR, vd._http = _VD_AVANT
    for k, v in _ENV_AVANT.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)

# ---- l'avis « … a épinglé un message » du récap est retiré, et rien d'autre
_appels_avis = []
def _faux_api(m, chemin, gid, **kw):
    _appels_avis.append((m, chemin))
    if m == "GET":
        return 200, [{"id": "900", "type": 6, "message_reference": {"message_id": "555"}},
                     {"id": "901", "type": 6, "message_reference": {"message_id": "777"}},
                     {"id": "902", "type": 0, "message_reference": {"message_id": "555"}},
                     {"id": "555", "type": 0}]
    return 204, None
_vrai_api = rcr._api
rcr._api = _faux_api
try:
    _ok = rcr._retirer_avis("1445108485090971710", "42", "555")
finally:
    rcr._api = _vrai_api
check("avis d'épinglage : seul l'avis (type 6) qui pointe le récap est supprimé",
      _ok and [c for c in _appels_avis if c[0] == "DELETE"] == [("DELETE", "/channels/42/messages/900")],
      _appels_avis)

if RENDU:
    print("\n— rendu : le classement subs de Threads (premier envoi)")
    print(json.dumps(RENDU.get("subs_threads"), ensure_ascii=False, indent=2))
    print("\n— rendu : le récap des clics (Twitter et Threads)")
    print(json.dumps(RENDU.get("clics"), ensure_ascii=False, indent=2))

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
if FAILS:
    for f in FAILS:
        print("  - " + f)
sys.exit(1 if FAILS else 0)
