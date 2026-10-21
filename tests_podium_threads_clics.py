"""Va Threads : SES VA, à leurs liens Threads, clics uniques US + UK.

Propriétaire, 14/10/2026 : « pour le podium et les clics, garde que ceux du
même groupe », « genre le truc simple de base », « pour les 3 groupes ».
Threads compte ses propres liens (EMY THREADS, « Threads VA 61 @pseudo »),
numérotés comme leurs tickets (section 1 bis). Le mode d'avant (les liens de
Twitter sous les numéros du registre, sections 2 à 6) reste dans le code,
coupé : il est rallumé ici pour rester testé.

Historique :

Propriétaire, 13/10/2026 : « pour Threads le podium c'est avec des clicks »
(primes 10/5/3 $ comme Twitter), puis, devant le récap -l-clicks : « pour
Threads tu écris Threads, pour Twitter Twitter, anonyme toujours, et pour le
click uniquement les clicks USA UK, et ça unique ». Choisi ensuite : les
clics vers OnlyFans dédoublonnés (« button_clicks »), « Threads 12 » partout
sur Threads (podium compris), et dans -l-clicks le classement de la
quinzaine avec l'all-time, à la place du report JESSY LE RETOUR.

Vérifié ici, sans réseau ni vrai data/ (GetMySocial, MyPuls, Discord et
l'horloge sont faux ; DATA_DIR est un dossier temporaire) :
  1. le profil livré : vitrine (ni bonus, ni synchro, ni suivi), mesure
     « gms_bouton », pays US + GB, « Threads n » ; Twitter et Va IG inchangés ;
  2. les numéros : ceux du registre des trackings (comme Twitter), pour
     Threads ET pour les VA US de Va IG — un lien renommé façon Infloww garde
     son VA, deux téléphones sur un tracking font une ligne, un lien sans
     tracking garde le numéro de son nom, un lien sur deux trackings est mis
     de côté et dit ;
  3. la mesure : clics uniques US + UK pour Threads (jamais les vues, jamais
     MyPuls) ; Va IG garde les vues US ;
  4. le podium de la semaine : Bowser, « ─│🏆┤-podium », « Threads n »,
     « clics », primes ; le lundi, figé et mentionné ;
  5. la quinzaine dans « ─│📊┤-l-clicks », avec l'all-time « Threads n » ; une
     page d'avant dans un salon disparu est reposée ;
  6. l'ancien récap JESSY de -l-clicks est vidé sur place, une fois, jamais
     supprimé ;
  7. la boucle du site : sur Threads, podium et quinzaine, rien d'autre.

Lancer depuis la racine du dépôt : python tests_podium_threads_clics.py
"""
from __future__ import annotations

import ast
import contextlib
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

CLOCK = {"now": dt.datetime(2026, 10, 13, 10, 0)}      # un mardi

# ------------------------------------------------ faux suivi_va (la paie) --
PRIMES_DITES = []
_faux_suivi = types.ModuleType("suivi_va")
_faux_suivi.annoncer_primes = lambda gid, cl, debut, fin: (
    PRIMES_DITES.append((str(gid), [x["va"] for x in cl.get("lignes") or []][:3],
                         debut, fin))
    or {"dits": [], "sans_adresse": [], "inconnus": []})
sys.modules["suivi_va"] = _faux_suivi

# ------------------------------------------------- faux GetMySocial --------
EQ_TW1, EQ_TW2 = "tm_6a0e4739bfa0c238f20a8bf5", "tm_6ab46ebb11a0232c11211b1a"
OF = "https://onlyfans.com/"
GMS = {"listes": [], "vues": [], "boutons": [], "muet": False, "tag": None, "repli": False}


def _page(id_, nom, *urls):
    return {"id": id_, "display_name": nom, "type": "landing", "url": None, "status": "active",
            "buttons": [{"url": u} for u in urls]}


# ce que GetMySocial portait le 13/10/2026, en petit
LIENS = {EQ_TW1: [_page("l1", "VA 3 - Roucham 1 ( normal )", OF + "emy.brw/c42"),
                  _page("l2", "VA 3 - Roucham 2 ( normal )", OF + "emy.brw/c42"),
                  _page("l3", "tsiry 1", OF + "emy.brw/c37"),
                  _page("l4", "eddy 2", OF + "Emy.Brw/c035/"),
                  _page("l5", "test emy", OF + "emy.brw"),
                  _page("l6", "Nouveau sans rien")],
         EQ_TW2: [{"id": "l8", "display_name": "Twitter VA 31 @abdoul_9684", "type": "directlink",
                   "url": OF + "emy.brw/c6", "status": "active", "buttons": []}]}
# EMY THREADS le 14/10/2026, en petit : des liens directs nommés par liens_va,
# un ancien coupé (angelyy, même VA 61), et les liens de base de l'espace


def _direct(id_, nom, statut="active"):
    return {"id": id_, "display_name": nom, "type": "directlink", "status": statut,
            "url": OF + "seren.vale/c193", "buttons": None}


EQ_TH = "tm_6ab51e03b299b7e3ba6ff7bf"
LIENS[EQ_TH] = [_direct("t1", "Threads VA 61 @momobtn"), _direct("t1b", "Threads VA 61 @momobtn", "inactive"),
                _direct("t2", "Threads VA 62 @steave0454"), _direct("t3", "Threads VA 31 @abdoul_9684"),
                _direct("t9", "Emy Threads A/B"), _direct("t8", "TEST duplicata Threads (a supprimer)",
                                                          "inactive")]
# clics vers OnlyFans, dédoublonnés, par pays (button_clicks)
BOUTONS = {"l1": {"US": 40, "GB": 5, "FR": 9}, "l2": {"US": 2, "IN": 3},
           "l3": {"US": 30, "GB": 1, "IN": 50}, "l4": {"US": 10, "GB": 10, "CA": 4},
           "l5": {"US": 3}, "l6": {"US": 99}, "l7": {"US": 77}, "l8": {}}
# vues de la page, par pays (ce que Va IG compte) : dix fois plus, US seul ;
# le lien direct (l8) n'a que des visites : c'est elles qui comptent pour lui
VUES = {k: {p: 10 * n for p, n in v.items()} for k, v in BOUTONS.items()}
VUES["l8"] = {"US": 6, "GB": 1, "FR": 4}
# les liens Threads sont directs : leurs visites par pays
VUES.update({"t1": {"US": 20, "GB": 3, "FR": 9}, "t1b": {"US": 4}, "t2": {"US": 7, "IN": 30},
             "t3": {"GB": 1, "IN": 5}, "t9": {"US": 500}, "t8": {"US": 50}})


def _list_links_team(team, force_refresh=False):
    GMS["listes"].append(team)
    if GMS["repli"]:
        return {"ok": False, "error": "panne"}
    return {"ok": True, "links": copy.deepcopy(LIENS.get(team, []))}


def _somme(table, ids):
    out = {}
    for i in ids:
        for p, n in table.get(i, {}).items():
            out[p] = out.get(p, 0) + n
    return sum(out.values()), out


def _analytics_for_links(ids, d0, d1):
    GMS["vues"].append((tuple(ids), d0, d1))
    return (None, None) if GMS["muet"] else _somme(VUES, ids)


def _boutons_par_pays(ids, d0, d1, directs=()):
    GMS["boutons"].append((tuple(ids), d0, d1))
    GMS.setdefault("tags", []).append(GMS["tag"])
    GMS.setdefault("directs", []).append(tuple(directs))
    if GMS["muet"]:
        return None, None
    tp, pp = _somme(BOUTONS, [i for i in ids if i not in directs])
    td, pdir = _somme(VUES, [i for i in ids if i in directs])
    return tp + td, {k: pp.get(k, 0) + pdir.get(k, 0) for k in set(pp) | set(pdir)}


@contextlib.contextmanager
def _api_tag(nom):
    avant, GMS["tag"] = GMS["tag"], nom
    try:
        yield
    finally:
        GMS["tag"] = avant


_faux_gms = types.ModuleType("gms")
_faux_gms.list_links_team = _list_links_team
_faux_gms.analytics_for_links = _analytics_for_links
_faux_gms.boutons_par_pays = _boutons_par_pays
_faux_gms.api_tag = _api_tag
_faux_gms.sante_cles = lambda: []
_faux_gms.etat_quota = lambda: {}
_faux_gms.pause_restante = lambda: 0
sys.modules["gms"] = _faux_gms

# ------------------------------------------------------- faux MyPuls -------
MP = {"appels": []}


def _mp_api_get(path, params=None, _essai=0):
    MP["appels"].append((path, dict(params or {})))
    return {"ok": True, "data": {"count": 0, "data": []}}


_faux_mypuls = types.ModuleType("mypuls")
_faux_mypuls.api_get = _mp_api_get
_faux_mypuls.api_tracking_links = lambda *a, **k: []
sys.modules["mypuls"] = _faux_mypuls

import safe_json                       # noqa: E402
import verif_discord as vd             # noqa: E402
import podium_discord as pd            # noqa: E402
import recap_clics_rest as rcr         # noqa: E402
import clics_personnes as cp           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, TH, IG = pd.TWITTER_ID, pd.THREADS_ID, pd.VA_IG_ID
# la table au NOM des liens : les liens renommés façon Infloww n'y sont plus
NUMEROS = {"tsiry 1": 43, "eddy 2": 42, "test emy": 30, "abdoul_9684": 31}


def _trk(numero, nom, ids=(), spam=False):
    return {"numero": numero, "cle": nom, "spam": spam, "nom": nom, "liens": [nom],
            "ids": list(ids), "mp": True, "premier": "2026-10-06", "vu": "2026-10-13",
            "actif": True}


# « ids » : les liens que le registre a vus derrière chaque tracking (tenu par
# le relevé de Twitter sur les listes fraîches)
REGISTRE = {"trackings": {"emy.brw/c42": _trk(12, "Roucham", ["l1", "l2"]),
                          "emy.brw/c43": _trk(24, "Roucham SPAM", [], spam=True),
                          "emy.brw/c37": _trk(43, "tsiry", ["l3"]),
                          "emy.brw/c35": _trk(41, "eddy", ["l4"]),
                          "emy.brw/c6": _trk(31, "abdoul_9684", ["l8"])},
            "attente": {}, "frais": "2026-10-13"}

# ------------------------------------------------------------ faux Discord --
SALONS = {
    TW: [{"id": "tw-podium", "name": "─│🏆┤-podium", "type": 0},
         {"id": "tw-subs", "name": "─│👤┤-subs", "type": 0},
         {"id": "tw-clics", "name": "─│📊┤-l-clicks", "type": 0}],
    # le vrai Threads du 13/10/2026 : plus de salon « -subs », un « paliers-subs »
    TH: [{"id": "th-cat", "name": "<<<🔔NOTIFICATION >>>", "type": 4},
         {"id": "th-podium", "name": "─│🏆┤-podium", "type": 0},
         {"id": "th-clics", "name": "─│📊┤-l-clicks", "type": 0},
         {"id": "th-paliers", "name": "─│🏆┤-paliers-subs", "type": 0},
         {"id": "th-bonus", "name": "─│💸┤-bonus-journalier", "type": 0}],
    IG: [{"id": "ig-subs", "name": "─│🪙┤-subs", "type": 0},
         {"id": "ig-podium", "name": "─│🏁┤-podium", "type": 0}],
}
UTILISATEUR = {"siri": "1552153790701117480", "threads": "1552789379574145126"}
SERT = {"siri": {TW, IG}, "threads": {TH}}


class FauxDiscord:
    """Discord vu par verif_discord._http : chaque appel note LE BOT qui l'a fait."""

    def __init__(self):
        self.appels, self.n = [], 0
        self.messages = {}
        self.pannes = []               # [(méthode, début du chemin, code)] une fois chacune

    def guilde_du_salon(self, cid):
        return next((g for g, xs in SALONS.items() if any(x["id"] == cid for x in xs)), "")

    def http(self, bot, methode, chemin, js):
        self.appels.append({"bot": bot["id"], "m": methode, "p": chemin, "json": copy.deepcopy(js)})
        for i, (m, debut, code) in enumerate(self.pannes):
            if m == methode and chemin.startswith(debut):
                self.pannes.pop(i)
                return code, {"message": "panne"}
        bouts = chemin.split("?")[0].strip("/").split("/")
        if chemin == "/users/@me":
            return 200, {"id": UTILISATEUR[bot["id"]]}
        if bouts[0] == "guilds":
            if bouts[1] not in SERT[bot["id"]]:
                return 403, {"code": 50001, "message": "Missing Access"}
            if len(bouts) > 2 and bouts[2] == "emojis":
                return 200, []
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
            self.messages[mid] = {"salon": cid, "auteur": moi, "epingle": False,
                                  "embeds": copy.deepcopy(js.get("embeds") or []),
                                  "content": js.get("content", "")}
            return 200, {"id": mid}
        if len(bouts) == 4 and bouts[2] == "pins" and methode == "DELETE":
            msg = self.messages.get(bouts[3])
            if not msg:
                return 404, {"code": 10008}
            msg["epingle"] = False
            return 204, {}
        if len(bouts) == 4 and bouts[2] == "messages":
            msg = self.messages.get(bouts[3])
            if not msg or msg["salon"] != cid:
                return 404, {"code": 10008, "message": "Unknown Message"}
            if msg["auteur"] != moi:
                return 403, {"code": 50005}
            if "embeds" in js:
                msg["embeds"] = copy.deepcopy(js["embeds"])
            if "content" in js:
                msg["content"] = js["content"]
            return 200, {"id": bouts[3]}
        return 404, {"code": 0}

    def depuis(self, k):
        return self.appels[k:]


DISCORD = FauxDiscord()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="podium_threads_clics_"))
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
_SAUVE_PD = {k: getattr(pd, k) for k in (
    "DATA_DIR", "ETAT_FICHIER", "CONFIG_FICHIER", "NUMEROS_FICHIER", "LIENS_CACHE",
    "ALLTIME_FICHIER", "_maintenant", "_aujourdhui", "_pause_gms", "time")}
_SAUVE_RCR = (rcr.DATA_DIR,)
_SAUVE_CP = cp.rattachements_identite
_NB = [0]
PAUSE = {"gms": False}


def installer():
    global DISCORD
    _NB[0] += 1
    d = TMP / f"bac{_NB[0]}"
    d.mkdir()
    safe_json.write_text(d / "podium_numeros.json", json.dumps(NUMEROS))
    safe_json.write(d / "podium_trackings.json", REGISTRE)
    pd.DATA_DIR = d
    pd.ETAT_FICHIER = d / "podium.json"
    pd.CONFIG_FICHIER = d / "podium_config.json"
    pd.NUMEROS_FICHIER = d / "podium_numeros.json"
    pd.LIENS_CACHE = d / "gmsdash_links.json"
    pd.ALLTIME_FICHIER = d / "podium_alltime.json"
    rcr.DATA_DIR = d
    CLOCK["now"] = dt.datetime(2026, 10, 13, 10, 0)
    pd._maintenant = lambda: CLOCK["now"]
    pd._aujourdhui = lambda: CLOCK["now"].date()
    pd.time = types.SimpleNamespace(time=lambda: CLOCK["now"].timestamp(), sleep=lambda s: None)
    PAUSE["gms"] = False
    pd._pause_gms = lambda: PAUSE["gms"]
    DISCORD = FauxDiscord()
    pd._RELEVES.clear()
    pd._RELEVES_LUS = False
    pd._REPRIS.clear()
    pd._REPRIS_LUS = False
    for k in ("listes", "vues", "boutons", "tags", "directs"):
        GMS.setdefault(k, []).clear()
    GMS["muet"] = GMS["repli"] = False
    GMS["tag"] = None
    MP["appels"].clear()
    PRIMES_DITES.clear()
    return d


def posts(appels, salon=None):
    return [a for a in appels if a["m"] == "POST" and a["p"].endswith("/messages")
            and (salon is None or a["p"] == f"/channels/{salon}/messages")]


def ecritures(appels):
    return [a for a in appels if a["m"] in ("POST", "PATCH", "PUT", "DELETE")]


def avancer(**kw):
    CLOCK["now"] += dt.timedelta(**kw)


ATTENDU = [("Threads 12", 47), ("Threads 43", 31), ("Threads 41", 20), ("Threads 31", 7),
           ("Threads 30", 3)]
RENDU = {}
try:
    cp.rattachements_identite = lambda: {}

    # ------------------------------------------------------------------ 1
    print("\n— 1. le profil livré")
    p_th = pd._profil(TH)
    check("Threads : son profil à lui (il ne reprend plus Twitter), vitrine",
          TH in pd.SERVEURS and not pd._repris_de(TH) and pd.vitrine(TH)
          and not pd.subs_seulement(TH) and not pd.podium_seulement(TH))
    check("… clics uniques vers OnlyFans (« gms_bouton »), US + UK seulement",
          pd._source(TH) == "gms_bouton" and tuple(p_th["pays"]) == ("US", "GB")
          and p_th["marche"] == "US + UK" and pd._service(TH) == "GetMySocial")
    check("… « Threads n », « clics », Bowser, sans bonus ni bouton ni thème",
          p_th["libelle"] == "Threads" and pd._unite(TH) == "clics" and p_th["bot"] == "Bowser"
          and p_th["bonus"] is False and p_th["fr"] is False
          and not p_th.get("bouton_maj") and not p_th.get("theme") and not p_th.get("avec_us"))
    check("… SES liens (EMY THREADS), numérotés par leur nom, la quinzaine dans -l-clicks, "
          "un all-time neuf (l'ancien range les totaux des liens de Twitter)",
          p_th.get("equipes") == [EQ_TH] and p_th.get("numeros_liens")
          and not p_th.get("numeros_registre") and not p_th.get("clics_seuls")
          and p_th["salon_subs"] == "─│📊┤-l-clicks"
          and p_th["alltime"] == "podium_alltime_threads_liens.json", p_th)
    check("Va IG : ses VA seulement (plus de VA US mêlés)", not pd._profil(IG).get("avec_us")
          and not pd._mele(IG))
    check("Twitter et Va IG : profils inchangés (« subs », pas vitrine, pas de libellé)",
          pd._unite(TW) == pd._unite(IG) == "subs" and not pd.vitrine(TW) and not pd.vitrine(IG)
          and "libelle" not in pd._profil(TW) and pd._source(TW) == "tracking"
          and pd._profil(TW) is pd.SERVEURS[TW] and pd._profil(IG) is pd.SERVEURS[IG])
    check("mêmes primes que Twitter (10/5/3 $), et plus aucun récap JESSY à poster",
          pd.PRIMES == [10.0, 5.0, 3.0] and rcr.CIBLES_DEFAUT == {})

    # ------------------------------------------------------------------ 1 bis
    print("\n— 1 bis. le profil livré : ses liens à lui, ses numéros de ticket")
    installer()
    lundi, auj = pd.semaine_en_cours()
    cl = pd.classement(lundi, auj, gid=TH)
    vas = [(x["va"], x["clics"]) for x in cl["lignes"]]
    check("Threads 61 (lien actif + l'ancien coupé), 62, 31 : visites US + UK de leurs liens",
          vas == [("Threads 61", 27), ("Threads 62", 7), ("Threads 31", 1)], vas)
    check("seul l'espace EMY THREADS est lu : aucun lien de Twitter", GMS["listes"] == [EQ_TH],
          GMS["listes"])
    check("les liens de base (Emy Threads A/B, le test) ne comptent pour personne, sans appel",
          not any(set(a[0]) & {"t8", "t9"} for a in GMS["boutons"]) and cl["entites"] == 3,
          GMS["boutons"])
    check("liens directs : comptés à leurs visites", all(set(d) == set(i) for i, d in
                                                          zip([a[0] for a in GMS["boutons"]],
                                                              GMS["directs"])), GMS["directs"])
    tot = pd.alltime(TH)
    check("l'all-time sous les mêmes noms, dans son fichier neuf",
          tot.get("Threads 61") == 27 and (pd.DATA_DIR / "podium_alltime_threads_liens.json").exists()
          and not (pd.DATA_DIR / "podium_alltime_threads.json").exists(), tot)

    # Le mode d'avant (liens de Twitter, numéros du registre) reste un
    # interrupteur : rallumé pour la suite de ce test
    _LIVRE = copy.deepcopy(pd.SERVEURS[TH])
    pd.SERVEURS[TH].update(equipes=None, numeros_registre=True, clics_seuls=True,
                           alltime="podium_alltime_threads.json")
    pd.SERVEURS[TH].pop("numeros_liens", None)

    # ------------------------------------------------------------------ 2
    print("\n— 2. (mode d'avant) les numéros : le registre des trackings")
    installer()
    lundi, auj = pd.semaine_en_cours()
    cl = pd.classement(lundi, auj, gid=TH)
    vas = [(x["va"], x["clics"]) for x in cl["lignes"]]
    check("Threads : les VA au numéro de leur tracking, « Threads n », clics uniques US + UK",
          vas == ATTENDU, vas)
    check("lien renommé façon Infloww (« VA 3 - Roucham 1 ( normal ) ») : son VA 12, par "
          "son tracking", vas[0] == ("Threads 12", 47))
    check("deux téléphones sur le même tracking (Roucham 1 et 2) : UNE ligne, un appel pour "
          "les deux liens", ("l1", "l2") in [a[0] for a in GMS["boutons"]]
          and sum(1 for v, _ in vas if v == "Threads 12") == 1)
    check("le registre l'emporte sur le nom (« eddy 2 » : VA 41 comme sur Twitter, pas 42)",
          ("Threads 41", 20) in vas and not any(v == "Threads 42" for v, _ in vas))
    check("lien direct sans page (VA 31) : compté à ses visites US + UK (pas de bouton)",
          ("Threads 31", 7) in vas and ("l8",) in GMS["directs"]
          and all(d == () for i, d in zip([a[0] for a in GMS["boutons"]], GMS["directs"])
                  if i != ("l8",)), (vas, GMS["directs"]))
    check("sans tracking connu : le numéro de son nom (« test emy », 30)", ("Threads 30", 3) in vas)
    check("sans tracking ni numéro : mis de côté ET dit, sans appel",
          cl["sans_numero"] == ["Nouveau sans rien"]
          and not any(a[0] == ("l6",) for a in GMS["boutons"]), cl["sans_numero"])
    check("le podium relève sous l'étiquette qui paie (« podium »)",
          set(GMS["tags"]) == {"podium"}, GMS["tags"])
    check("aucun numéro attribué ici (la table au nom des liens n'a pas bougé)",
          json.loads(pd.NUMEROS_FICHIER.read_text()) == NUMEROS)
    check("un appel par VA, sur la semaine, jamais les vues ni MyPuls",
          len(GMS["boutons"]) == 5 and not GMS["vues"] and not MP["appels"]
          and {a[1:] for a in GMS["boutons"]} == {(lundi.isoformat(), auj.isoformat())})

    # Va IG : « ne touche pas [Va IG], on ne parle que de Threads » — ses VA US
    # gardent leurs numéros au nom du lien et leurs vues US, comme avant
    us = pd._releve_us(lundi, auj)
    vus_ig = [(x["va"], x["clics"]) for x in (us or {}).get("lignes") or []]
    check("Va IG inchangé : ses VA US au numéro du NOM de leur lien (pas le registre), "
          "à leurs vues US",
          vus_ig == [("VA 43", 300), ("VA 42", 100), ("VA 30", 30), ("VA 31", 6)], vus_ig)
    check("… Va IG ne relit pas les clics uniques de Threads (mesures séparées) : un "
          "appel par VA numéroté au nom (4)",
          len(GMS["boutons"]) == 5 and len(GMS["vues"]) == 4, (len(GMS["boutons"]), len(GMS["vues"])))

    # ------------------------------------------------------------------ 2 bis
    print("\n— 2 bis. pages à deux boutons, doutes du registre, liste de repli")
    reg0 = pd._lire_registre()

    def regroupe(liens, ents, table=None, reg=None):
        if reg is not None:
            safe_json.write(pd.DATA_DIR / "podium_trackings.json", reg)
        try:
            return pd._par_tracking(liens, ents, table or {}, "2026-10-12", "2026-10-13")
        finally:
            safe_json.write(pd.DATA_DIR / "podium_trackings.json", REGISTRE)

    double = _page("d1", "(Roucham) 1", OF + "emy.brw/c42", OF + "emy.brw/c43")
    double_s = _page("d2", "(Roucham) SPAM", OF + "emy.brw/c42", OF + "emy.brw/c43")
    o, t, dte, _c = regroupe([double, double_s],
                             {"Roucham": {"nom": "Roucham", "spam": False, "ids": ["d1"]},
                              "Roucham SPAM": {"nom": "Roucham", "spam": True, "ids": ["d2"]}})
    check("une page aux deux boutons, normal et spam : au VA de son genre (12, et 24 pour "
          "la page spam), rien mis de côté",
          t == {"#12": 12, "#24": 24} and o["#12"]["ids"] == ["d1"] and o["#24"]["ids"] == ["d2"]
          and not dte, (o, t, dte))
    deux = _page("d3", "Conflit", OF + "emy.brw/c42", OF + "emy.brw/c37")
    o, t, dte, en_c = regroupe([deux], {"Conflit": {"nom": "Conflit", "spam": False,
                                                    "ids": ["d3"]}})
    check("une page sur les trackings de deux personnes : mise de côté, ses deux VA sans "
          "relevé (comme Twitter), les trackings en cause dits",
          not t and list(o) == ["Conflit (trackings de VA 12, 43)"] and dte == {12, 43}
          and en_c == ["emy.brw/c37", "emy.brw/c42"], (o, t, dte, en_c))
    o, t, dte, _c = regroupe([deux], {"Conflit": {"nom": "Conflit", "spam": False,
                                                  "ids": ["d3"]}}, {"Conflit": 43})
    check("… sauf si son nom désigne l'un des deux : le sien", t == {"#43": 43} and not dte)
    reg_d = json.loads(json.dumps(REGISTRE))
    reg_d["trackings"]["emy.brw/c42"]["doute"] = [12, 47]
    o, t, dte, en_c = regroupe(LIENS[EQ_TW1], pd.entites(LIENS[EQ_TW1], {}), NUMEROS, reg_d)
    check("tracking en doute au registre : ses VA (12, 47) sont à mettre sans relevé",
          dte == {12, 47} and en_c == ["emy.brw/c42"], (dte, en_c))
    safe_json.write(pd.DATA_DIR / "podium_trackings.json", reg_d)
    cl_d = pd.classement(lundi, auj, gid=TH)
    safe_json.write(pd.DATA_DIR / "podium_trackings.json", REGISTRE)
    # « y a pas de tracking pour Threads », « c'est un lien dupliqué », « c'est au
    # click pour Threads » : le doute du registre ne retire personne ici
    check("… mais sur Threads, au clic : « Threads 12 » compte ses clics, personne « sans "
          "relevé », aucune note de tracking",
          ("Threads 12", 47) in [(x["va"], x["clics"]) for x in cl_d["lignes"]]
          and not cl_d["illisibles"] and not cl_d["conflits"]
          and not pd._notes_tracking(cl_d), (cl_d["illisibles"], cl_d.get("conflits")))
    import contextlib as _ctx
    _sortie = io.StringIO()
    cl_x = dict(cl_d, illisibles=["Threads 99"], frais=False)
    with _ctx.redirect_stdout(_sortie):
        e_d = pd.embed_podium(cl_x, lundi, auj, en_cours=True, gid=TH)
        e_t = pd.embed_podium(dict(cl_x, illisibles=["VA 99"]), lundi, auj, en_cours=True, gid=TW)
    check("un avertissement de Threads (un relevé raté) : pas dans le message, au journal ; "
          "Twitter, lui, garde les siens",
          "⚠️" not in e_d["description"] and "Threads 99" not in e_d["description"]
          and "non affiché dans le podium" in _sortie.getvalue()
          and "Threads 99" in _sortie.getvalue() and "⚠️" in e_t["description"],
          (_sortie.getvalue()[-300:], e_d["description"][-200:]))
    check("le format d'affichage : Threads à part, Twitter et Va IG inchangés",
          pd._format_affiche(TW) == pd._format_affiche(IG) == pd.FORMAT_AFFICHAGE
          != pd._format_affiche(TH))
    reg_a = json.loads(json.dumps(REGISTRE))
    reg_a["attente"]["emy.brw/c99"] = {"premier": "2026-10-12", "conflit": True,
                                       "numeros": [43], "liens": ["x"], "ids": []}
    o, t, dte, en_c = regroupe([], {}, {}, reg_a)
    check("tracking neuf en conflit (« attente ») : son VA aussi sans relevé, comme Twitter",
          dte == {43} and en_c == ["emy.brw/c99"], (dte, en_c))
    # la liste de repli (gmsdash_links.json) n'a ni boutons ni url
    safe_json.write(pd.LIENS_CACHE, {EQ_TW1: [{"id": l["id"], "display_name": l["display_name"]}
                                              for l in LIENS[EQ_TW1]],
                                     EQ_TW2: [{"id": "l8", "display_name": LIENS[EQ_TW2][0]
                                               ["display_name"], "type": "directlink"}]})
    GMS["repli"] = True
    cl_r = pd.classement(lundi, auj, gid=TH)
    GMS["repli"] = False
    check("liste de repli sans boutons : les mêmes VA, par les liens que le registre a vus "
          "(pas de « Threads 42 », Roucham reste 12), et le message dit la liste non fraîche",
          [(x["va"], x["clics"]) for x in cl_r["lignes"]] == ATTENDU and not cl_r["frais"],
          [(x["va"], x["clics"]) for x in cl_r["lignes"]])
    check("le registre relu n'a pas été réécrit par ces lectures",
          pd._lire_registre() == reg0)

    # Va IG : un relevé US pris avant le changement de format n'est pas repris
    installer()
    pd._charger_releves()
    pd._RELEVES[(TW, lundi.isoformat(), auj.isoformat())] = {
        "t": CLOCK["now"].timestamp() - 60, "essai": CLOCK["now"].timestamp() - 60,
        "jour": auj.isoformat(), "format": "2026-10-06-clics-tracking",
        "cl": {"lignes": [{"va": "VA 42", "numero": 42, "clics": 1}], "illisibles": [],
               "frais": True}}
    us2 = pd._releve_us(lundi, auj)
    check("Va IG : le relevé US d'avant le changement (autre format) est refait, pas repris",
          len(GMS["vues"]) == 4 and [x["va"] for x in us2["lignes"]][0] == "VA 43"
          and pd._RELEVES[(TW, lundi.isoformat(), auj.isoformat())]["format"]
          == pd.FORMAT_AFFICHAGE, us2 and us2["lignes"][:2])
    n_v = len(GMS["vues"])
    pd._releve_us(lundi, auj)
    check("… puis repris tel quel au passage suivant (même format, moins de deux heures)",
          len(GMS["vues"]) == n_v)
    safe_json.write_text(pd.ALLTIME_FICHIER, json.dumps(
        {"jour": auj.isoformat(), "totaux": {"VA 42": 5}}))
    at_tw = pd.alltime(TW, mesure="gms")
    check("… et son all-time US du jour, écrit dans l'ancien format, est refait",
          at_tw.get("VA 43") == 300 and "VA 12" not in at_tw
          and json.loads(pd.ALLTIME_FICHIER.read_text())["format"]
          == pd.FORMAT_AFFICHAGE, at_tw)

    # ------------------------------------------------------------------ 3
    print("\n— 3. le message vivant de la semaine")
    installer()
    check("à poster (aucun message encore)", pd.a_rafraichir(TH))
    k0 = len(DISCORD.appels)
    with vd.sur_serveur(TH):
        mid = pd.rafraichir(TH)
    a = DISCORD.depuis(k0)
    p_th = posts(a, "th-podium")
    check("posté dans « ─│🏆┤-podium » de Threads, par Bowser, un seul message",
          mid and len(p_th) == 1 and p_th[0]["bot"] == "threads" and len(posts(a)) == 1,
          [(x["bot"], x["p"]) for x in ecritures(a)])
    e = p_th[0]["json"]["embeds"][0]
    RENDU["vivant"] = e
    desc = e["description"]
    check("titre « PODIUM CLICS — SEMAINE EN COURS »",
          e["title"] == "🔴 PODIUM CLICS — SEMAINE EN COURS", e["title"])
    check("en-tête : clics uniques US + UK vers OnlyFans",
          "Clics **uniques US + UK** vers OnlyFans" in desc, desc[:300])
    check("« Threads n » et « clics » partout, jamais « VA 12 », « subs » ni un nom de lien",
          "subs" not in json.dumps(e, ensure_ascii=False).lower()
          and "**VA " not in desc and "Roucham" not in desc and "tsiry" not in desc, desc)
    check("le top 3 avec ses primes 10/5/3 $",
          "🥇 **Threads 12** — **47** clics · 💰 **10$**" in desc
          and "🥈 **Threads 43** — **31** clics · 💰 **5$**" in desc
          and "🥉 **Threads 41** — **20** clics · 💰 **3$**" in desc
          and "4. Threads 31 — **7** clics" in desc and "5. Threads 30 — **3** clics" in desc,
          desc)
    # Bowser ne lit aucun message : « envoie un message à @Bowser » n'avait
    # enregistré aucune adresse (audit du 20/10/2026)
    check("l'adresse de la prime se donne au bouton 💳 du ticket, plus à Bowser",
          "**💳 Mon adresse USDC**" in desc and "@Bowser" not in desc, desc[-400:])
    # « je veux pas les trucs là » : aucun ⚠️ ni ℹ️ dans les messages de Threads
    check("aucun avertissement affiché sur Threads (ni ⚠️ ni ℹ️)",
          "⚠️" not in desc and "ℹ️" not in desc, desc[-300:])
    check("pied « Marché US + UK », sans bouton 🔄",
          e["footer"]["text"].startswith("YOULAB • Marché US + UK")
          and "components" not in p_th[0]["json"])
    check("passage suivant dans deux heures, pas avant",
          not pd.a_rafraichir(TH, CLOCK["now"].timestamp() + 119 * 60)
          and pd.a_rafraichir(TH, CLOCK["now"].timestamp() + 121 * 60))
    PAUSE["gms"] = True
    check("GetMySocial en pause : Threads attend (sa mesure en dépend)",
          pd._pause_pour(TH) and not pd.a_rafraichir(TH, CLOCK["now"].timestamp() + 3 * 3600))
    PAUSE["gms"] = False
    e_tw = pd.embed_podium({"lignes": [{"va": "VA 12", "clics": 7, "numero": 12}],
                            "illisibles": [], "frais": True}, lundi, auj, en_cours=True, gid=TW)
    check("Twitter : « PODIUM SUBS », « VA 12 », « Abonnements via Twitter », comme avant",
          e_tw["title"] == "🔴 PODIUM SUBS — SEMAINE EN COURS"
          and "🥇 **VA 12** — **7** subs · 💰 **10$**" in e_tw["description"]
          and "Abonnements via Twitter 🐦 — clics **tracking OF**" in e_tw["description"])
    # Luigi et Bowser ne lisent aucun message (audit du 20/10/2026) : la
    # consigne renvoie au bouton 💳 du ticket, sur le podium comme au bonus
    bouton = ("enregistre **ton adresse USDC (réseau Solana)** avec le bouton "
              "**💳 Mon adresse USDC** du message épinglé de **ton espace perso**")
    e_b = pd.embed_bonus({"lignes": [{"va": "VA 12", "clics": 7}], "illisibles": [], "frais": True},
                         auj, TW)
    check("primes de Threads et de Twitter, bonus de Twitter : l'adresse au bouton 💳, plus "
          "« envoie un message à @Bowser / @Luigi »",
          all(bouton in d and "envoie un message" not in d
              for d in (e_d["description"], e_tw["description"], e_b["description"]))
          and "puis écris-y **ton rang de la semaine**." in e_d["description"]
          and "puis écris-y **ton rang du jour (top 1, 2 ou 3)**." in e_b["description"],
          (e_d["description"][-400:], e_b["description"][-300:]))
    # le 🌐 all-time est relevé une fois par jour, la période en direct : il
    # se lisait plus petit qu'elle (audit du 20/10/2026). Va IG le garde
    # (Threads ne l'affiche plus depuis le 21/10/2026, section 4)
    cl_at = {"lignes": [{"va": "VA 12", "numero": 12, "clics": 47},
                        {"va": "VA 43", "numero": 43, "clics": 31}],
             "illisibles": [], "frais": True}
    d_at = pd.pages_subs(cl_at, lundi, auj, {"VA 12": 41, "VA 43": 900},
                         gid=IG)[0]["description"]
    check("🌐 all-time jamais plus petit que la période (47 et non 41), le plus grand gardé (900)",
          "**VA 12** — **47** subs · 🌐 47 all-time" in d_at
          and "**VA 43** — **31** subs · 🌐 900 all-time" in d_at, d_at[:500])
    check("Va IG (pas de bouton 💳 sur ses tickets) : la consigne d'avant, mot pour mot",
          pd._reclamer_prime(pd._profil(IG), "💸 **Pour recevoir ta prime :**", "ton rang de la semaine")
          == "💸 **Pour recevoir ta prime :** envoie un message à **@Luigi** dans **ton espace perso** "
             "avec **ton rang de la semaine** et **ton adresse USDC (réseau Solana)**.")
    check("la mention du lundi : « clics » sur Threads, l'ancienne ailleurs",
          pd._mention_podium(TH) == "@everyone 🏆 Podium clics de la semaine !"
          and pd._mention_podium(TW) == pd._mention_podium(IG) == pd.MENTION_PODIUM)

    # ------------------------------------------------------------------ 4
    print("\n— 4. la quinzaine dans « ─│📊┤-l-clicks » : VA de Threads et de Va IG, US / GBL")
    # Propriétaire, 21/10/2026 : les VA de Va IG à leurs clics, « US + UK +
    # Canada pour tous », « us : » et « gbl : », plus d'all-time. Deux VA de
    # Va IG (fiches liens_fr), un troisième au lien coupé, pas compté.
    import liens_fr as _lfr
    _etat_fr = _lfr.ETAT
    _lfr.ETAT = pd.DATA_DIR / "liens_va_fr.json"
    safe_json.write(_lfr.ETAT, {"liens": {
        "u7:amelia": {"numero": 3, "pseudo": "seven", "link_id": "i1",
                      "trackings": {"OF": "https://onlyfans.com/amelia.mrn/c3"}},
        "u8:lola": {"numero": 2, "pseudo": "lolafan", "link_id": "i2"},
        "u9:emma": {"numero": 4, "pseudo": "parti", "link_id": "i3", "actif": False}}})
    BOUTONS.update({"i1": {"US": 2, "FR": 30, "CA": 1}, "i2": {"GB": 4, "BE": 6},
                    "i3": {"US": 99}})
    # les abonnés (propriétaire, 21/10/2026 : « mets les subs à côté », « 🌐
    # all-time sub et 🌐 all-time click ») : Threads 12 (roucham) a son
    # tracking Emy, Threads VA 001 (seven) le sien ; Threads VA 002 n'en a pas.
    # amelia.mrn/c3 : 1 abonné « depuis toujours » au compteur, 2 sur la
    # période — l'all-time affiché ne descend jamais sous la période
    import liens_va as _lv4
    _etat_lv4, _mp4 = _lv4._etat, pd._lire_mypuls
    _lv4._etat = lambda: {"liens": {f"{TH}:u12": {"numero": 12, "pseudo": "roucham",
                                                  "tracking": "https://onlyfans.com/emy.brw/c42"}}}
    pd._lire_mypuls = lambda d0, d1, forcer=False: ({
        "emy.brw/c42": {"nom": "Threads VA 12 @roucham", "subs": 5, "subs_total": 40},
        "amelia.mrn/c3": {"nom": "Amelia VA 3 @seven", "subs": 2, "subs_total": 1}}, "")
    # ce matin, Threads avait une page dans son salon -subs, supprimé depuis
    d0 = json.loads(pd.ETAT_FICHIER.read_text())
    d0.setdefault("subs", {})[TH] = {"saison": "2026-10-01", "messages": ["1559432858823823432"],
                                     "vu": 1, "format": "2026-10-06-clics-tracking"}
    safe_json.write(pd.ETAT_FICHIER, d0)
    check("la quinzaine est à faire (format d'affichage changé)", pd.a_rafraichir_subs(TH))
    k1 = len(DISCORD.appels)
    n_b = len(GMS["boutons"])
    with vd.sur_serveur(TH):
        q = pd.rafraichir_subs(TH)
    a = DISCORD.depuis(k1)
    pq = posts(a, "th-clics")
    check("posée dans « ─│📊┤-l-clicks » par Bowser (l'ancienne page, introuvable, reposée)",
          q and len(pq) == 1 and pq[0]["bot"] == "threads"
          and not posts(a, "th-paliers") and not posts(a, "th-podium"),
          [(x["m"], x["p"]) for x in ecritures(a)])
    eq = pq[0]["json"]["embeds"][0]
    RENDU["quinzaine"] = eq
    dq = eq["description"]
    _lv4._etat, pd._lire_mypuls = _etat_lv4, _mp4
    check("l'all-time des clics sur chaque ligne, sur la même ligne : « · 🌐 n all-time click », "
          "tous pays depuis la création du lien ; jamais l'ancien fichier all-time",
          "🥇 **Threads 12** — US : **47** · GBL : **59** · 🌐 — all-time click\n" in dq
          and "4. Threads 31 — US : 7 · GBL : 11 · 🌐 11 all-time click\n" in dq
          and "Threads VA 001 — US : 3 · GBL : 33 · 🌐 33 all-time click\n" in dq
          and "Threads VA 002 — US : 4 · GBL : 10 · 🌐 10 all-time click\n" in dq
          and not (pd.DATA_DIR / "podium_alltime_threads.json").exists(), dq)
    # propriétaire, 21/10/2026 : « mets pas les subs, uniquement dans leur ticket
    # perso quand il tape Mes stats »
    check("… et aucun abonné dans le classement public : ni « Subs », ni « all-time sub »",
          "Subs" not in dq and "all-time sub" not in dq and "abonnés" not in dq, dq)
    check("la quinzaine non plus : ni ⚠️ ni ℹ️", "⚠️" not in dq and "ℹ️" not in dq, dq[-300:])
    n_lignes = len(re.findall(r" — US : ", dq))
    check("titre « Classement clics », en-tête « uniques US + UK + CA » et sa légende, total US / "
          "GBL, comptes classés Threads + Va IG, anonyme",
          eq["title"] == "📊 Classement clics — la quinzaine"
          and "Clics **uniques US + UK + CA** · **" + str(n_lignes) + "** comptes classés" in dq
          and "_US : clics uniques US + UK + Canada · GBL : clics de tous les pays_" in dq
          and dq.rstrip().endswith("\nUS : **119** · GBL : **221**")
          and "Roucham" not in dq and "roucham" not in dq, (eq["title"], dq))
    check("… sur la quinzaine (01/10 → aujourd'hui) et depuis toujours (une fois par jour), clics "
          "uniques, un relevé par VA dont les deux de Va IG",
          {a[1:] for a in GMS["boutons"][n_b:]} == {("2026-10-01", "2026-10-13"),
                                                     (pd.ALLTIME_DEPUIS, "2026-10-13")}
          and ("i1",) in [a[0] for a in GMS["boutons"][n_b:]]
          and ("i3",) not in [a[0] for a in GMS["boutons"][n_b:]]
          and not GMS["vues"])
    check("… sous l'étiquette « quinzaine » (elle ne paie rien : elle cède la réserve)",
          set(GMS["tags"][n_b:]) == {pd.ETIQUETTE_QUINZAINE} != "podium", GMS["tags"][n_b:])
    check("prochain passage de la quinzaine : dans une heure",
          not pd.a_rafraichir_subs(TH, CLOCK["now"].timestamp() + 59 * 60)
          and pd.a_rafraichir_subs(TH, CLOCK["now"].timestamp() + 61 * 60))
    check("ni bonus du jour sur Threads", not pd.a_rafraichir_bonus(TH))
    # « aussi threads refais » (19/10/2026) : « 👀 Pseudos », comme Twitter
    comp = pq[0]["json"].get("components") or []
    check("sous la quinzaine : « 👀 Pseudos » seul ; rien sous le podium",
          [c["custom_id"] for r in comp for c in r["components"]] == [pd.BOUTON_PSEUDOS]
          and pd._boutons(TH, True) == {}, comp)
    import liens_va as _lv
    _etat_lv = _lv._etat
    _lv._etat = lambda: {"liens": {f"{TH}:1": {"numero": 12, "pseudo": "momobtn"},
                                   f"{TH}:2": {"numero": 43, "pseudo": "steave0454"},
                                   f"{pd.TWITTER_ID}:3": {"numero": 31, "pseudo": "pas_threads"}}}
    _nl = pd.SERVEURS[TH].get("numeros_liens")
    try:
        # ici, le mode d'avant (numéros du registre) : le nom du registre
        txt_reg = pd.texte_pseudos(TH)
        # livré : le numéro du ticket, dans le nom du lien (« numeros_liens »)
        pd.SERVEURS[TH]["numeros_liens"] = True
        txt_th = pd.texte_pseudos(TH)
    finally:
        _lv._etat = _etat_lv
        pd.SERVEURS[TH].pop("numeros_liens", None)
        if _nl is not None:
            pd.SERVEURS[TH]["numeros_liens"] = _nl
    check("« 👀 Pseudos » de Threads, livré : « Threads n » → le pseudo de sa fiche liens_va, "
          "jamais celle d'un autre serveur",
          "🥇 Threads 12 · **momobtn** · 47 clics" in txt_th
          and "🥈 Threads 43 · **steave0454** · 31 clics" in txt_th
          and "Threads 31 · **?**" in txt_th and "pas_threads" not in txt_th, txt_th)
    check("… numéros du registre (mode d'avant) : le nom du registre",
          "🥇 Threads 12 · **Roucham** · 47 clics" in txt_reg, txt_reg)
    check("… et les VA de Va IG : « Threads VA 001 » → pseudo (model VA n · Va IG)",
          "Threads VA 001 · **seven (Amelia VA 3 · Va IG)** · 3 clics" in txt_th
          and "Threads VA 002 · **lolafan (Lola VA 2 · Va IG)** · 4 clics" in txt_th, txt_th)
    check("« Threads VA » sur trois chiffres : l'Instagram VA 23 est « Threads VA 023 », jamais "
          "le « Threads 23 » d'un VA de Threads",
          pd._libelle_va_ig(23) == "Threads VA 023" and pd._libelle_va_ig(1) == "Threads VA 001"
          and [m[0] for m in pd._ligne_affichee("Threads").findall(
              "🥇 **Threads VA 023** — US : **9** · GBL : **9**\n2. Threads 23 — US : 1 · GBL : 1")]
          == ["Threads VA 023", "Threads 23"])
    _lfr.ETAT = _etat_fr

    # ------------------------------------------------------------------ 4 bis
    print("\n— 4 bis. « 📈 Mes stats » : les subs ET les clics du lien")
    # Propriétaire, 21/10/2026 : « pour mes sub change et mets mes stats, ça
    # montre les sub et click ». Le VA 61 (momobtn) : ses liens t1 et t1b
    # (coupé), directs, comptés à leurs visites
    import subs_va as _sva
    import tickets_discord as _tkd
    _sv_ms = (_lv._etat, pd.liens_bruts, _sva.subs_du_va, _tkd._boutons_va_avant_stats)
    try:
        _lv._etat = lambda: {"liens": {f"{TH}:u61": {"numero": 61, "pseudo": "momobtn",
                                                     "link_id": "t1"}}}
        pd.liens_bruts = lambda gid=None, etiquette="podium": (copy.deepcopy(LIENS[EQ_TH]), True)
        _sva.subs_du_va = lambda gid, uid, jour=None: {
            "trackings": 2, "communs": [],
            "aujourdhui": {"du": "2026-10-13", "au": "2026-10-13", "n": 1},
            "periode": {"du": "2026-10-01", "au": "2026-10-13", "n": 4},
            "precedente": {"du": "2026-09-16", "au": "2026-09-30", "n": None}}
        n_b = len(GMS["boutons"])
        c61 = pd.clics_du_va(TH, "u61", [(dt.date(2026, 10, 13), dt.date(2026, 10, 13))])
        # t1 : US 20, GB 3, FR 9 ; t1b (coupé) : US 4 -> US+UK+CA 27, tous pays 36
        check("ses clics : ses deux liens (le coupé compris), US + UK + CA et tous pays",
              c61 == [(27, 36)] and GMS["boutons"][n_b][0] == ("t1", "t1b"), (c61, GMS["boutons"][n_b:]))
        txt_ms = _sva.texte(TH, "u61")
        check("le texte : « Tes stats », les subs (une période illisible le dit), puis les clics "
              "« US : n · GBL : n » sur les mêmes périodes, aucun montant",
              txt_ms.startswith("📈 **Tes stats**\n**Subs**\nAujourd'hui : **1**\n")
              and "Cette période (du 01/10 au 13/10) : **4**" in txt_ms
              and "Période précédente (du 16/09 au 30/09) : pas lisible pour l'instant" in txt_ms
              and "**Clics de ton lien** (US = US + UK + Canada · GBL = tous pays)" in txt_ms
              and "Cette période (du 01/10 au 13/10) : US : **27** · GBL : **36**" in txt_ms
              and "$" not in txt_ms, txt_ms)
        check("un VA sans lien : ses subs, et « pas encore de lien » pour les clics",
              "Pas encore de lien" in _sva.texte(TH, "u_sans_lien"))
        _tkd._boutons_va_avant_stats = lambda uid, **k: [{"type": 1, "components": [
            {"type": 2, "label": "Mes subs", "custom_id": f"subs:total:{uid}"},
            {"type": 2, "label": "Mon adresse USDC", "custom_id": f"usdc:set:{uid}"}]}]
        lab = lambda g: [b["label"] for r in _tkd.boutons_va("u61", gid=g) for b in r["components"]]
        check("le bouton (posé par le patch du VPS) : « Mes stats » sur Threads, « Mes subs » "
              "ailleurs tant que le propriétaire ne l'a pas demandé",
              lab(TH) == ["Mes stats", "Mon adresse USDC"]
              and lab(TW) == ["Mes subs", "Mon adresse USDC"], (lab(TH), lab(TW)))
        check("… et les accueils déjà postés sont redessinés une fois (BOUTONS_VERSION 4)",
              _tkd.BOUTONS_VERSION == 4)
    finally:
        _lv._etat, pd.liens_bruts, _sva.subs_du_va, _tkd._boutons_va_avant_stats = _sv_ms

    # ------------------------------------------------------------------ 5
    print("\n— 5. le lundi : semaine terminée, puis le podium figé")
    CLOCK["now"] = dt.datetime(2026, 10, 19, 0, 10)
    k3 = len(DISCORD.appels)
    with vd.sur_serveur(TH):
        pd.rafraichir(TH)
    w = ecritures(DISCORD.depuis(k3))
    check("lundi 00h10 : « terminée », sur place",
          [x["m"] for x in w] == ["PATCH"] and w[0]["p"].endswith(f"/{mid}")
          and w[0]["json"]["embeds"][0]["title"] == "🏁 PODIUM CLICS — SEMAINE TERMINÉE",
          [(x["m"], x["p"]) for x in w])
    CLOCK["now"] = dt.datetime(2026, 10, 19, 9, 2)
    k4 = len(DISCORD.appels)
    n_b = len(GMS["boutons"])
    with vd.sur_serveur(TH):
        fige = pd.poster_podium(TH)
    w = ecritures(DISCORD.depuis(k4))
    ef = w[0]["json"]["embeds"][0] if w else {}
    RENDU["podium"] = ef
    check("9h : le podium FIGE le message de la semaine, « 🏆 PODIUM CLICS DE LA SEMAINE »",
          fige == mid and w[0]["m"] == "PATCH" and ef.get("title") == "🏆 PODIUM CLICS DE LA SEMAINE"
          and "🥇 **Threads 12**" in ef.get("description", ""))
    ment = [x for x in w if x["m"] == "POST"]
    check("… « @everyone 🏆 Podium clics de la semaine ! » en réponse, par Bowser",
          len(ment) == 1 and ment[0]["bot"] == "threads"
          and ment[0]["json"]["content"] == "@everyone 🏆 Podium clics de la semaine !")
    # comme Twitter et Va IG : le podium de 9h relit la semaine entière, lundi
    # → dimanche (un appel par VA), en clics uniques
    check("… sur la semaine entière (12/10 → 18/10), clics uniques, un appel par VA",
          len(GMS["boutons"]) == n_b + 5
          and {a[1:] for a in GMS["boutons"][n_b:]} == {("2026-10-12", "2026-10-18")}
          and not GMS["vues"], GMS["boutons"][n_b:])
    check("les primes passent à suivi_va : top 3 « Threads n »",
          PRIMES_DITES == [(TH, ["Threads 12", "Threads 43", "Threads 41"],
                            dt.date(2026, 10, 12), dt.date(2026, 10, 18))], PRIMES_DITES)

    # ------------------------------------------------------------------ 6
    print("\n— 6. l'ancien récap JESSY de -l-clicks : vidé sur place, jamais supprimé")
    installer()
    DISCORD.messages["R1"] = {"salon": "th-clics", "auteur": UTILISATEUR["threads"],
                              "epingle": True, "content": "⏱️ Prochaine mise à jour",
                              "embeds": [{"title": "🇺🇸 Clicks — JESSY LE RETOUR",
                                          "description": "🥇 **Roucham** `@roucham_79944`"}]}
    safe_json.write(rcr._fichier_etat(), {TH: {"salon": "th-clics", "nom": "─│📊┤-l-clicks",
                                               "message": "R1", "t_releve": 1, "vu": 1}})
    DISCORD.pannes.append(("PATCH", "/channels/th-clics/messages/R1", 503))
    with vd.sur_serveur(TH):
        r0 = rcr.retirer(TH)
    check("Discord en panne : rien noté, le tour suivant réessaie",
          r0 is False and not rcr._etat()[TH].get("retire")
          and DISCORD.messages["R1"]["embeds"])
    k5 = len(DISCORD.appels)
    with vd.sur_serveur(TH):
        r1 = rcr.retirer(TH)
    m = DISCORD.messages.get("R1") or {}
    check("vidé sur place par Bowser : plus de noms ni de pseudos, un renvoi au classement",
          r1 is True and m.get("embeds") == [] and "classement juste en dessous" in m["content"]
          and all(x["bot"] == "threads" for x in ecritures(DISCORD.depuis(k5))), m)
    check("… désépinglé, jamais supprimé",
          "R1" in DISCORD.messages and not m.get("epingle")
          and not [x for x in ecritures(DISCORD.depuis(k5))
                   if x["m"] == "DELETE" and "/messages/" in x["p"]])
    k6 = len(DISCORD.appels)
    with vd.sur_serveur(TH):
        r2 = rcr.retirer(TH)
    check("une fois : le passage suivant ne touche plus à rien",
          r2 is False and not ecritures(DISCORD.depuis(k6)))
    safe_json.write(rcr._fichier_etat(), {TW: {"salon": "tw-clics", "message": "R404"}})
    with vd.sur_serveur(TW):
        r3 = rcr.retirer(TW)
    check("Twitter : son ancien récap supprimé à la main entre-temps (404) : noté, rien d'autre",
          r3 is False and rcr._etat()[TW].get("retire"))
    with vd.sur_serveur(IG):
        check("un serveur sans ancien récap (Va IG) : rien", rcr.retirer(IG) is False)

    # ------------------------------------------------------------------ 7
    print("\n— 7. la boucle du site (web_upload)")
    src_w = (BOT / "web_upload.py").read_text(encoding="utf-8")
    boucle = aide = None
    for n in ast.walk(ast.parse(src_w)):
        if isinstance(n, ast.FunctionDef) and n.name == "_recap_clics_rest":
            aide = n
        if (isinstance(n, ast.For) and isinstance(n.iter, ast.Attribute)
                and n.iter.attr == "SERVEURS_EXTRA"
                and "a_rafraichir_subs" in (ast.get_source_segment(src_w, n) or "")):
            boucle = n
    check("la boucle du podium et l'aide du récap sont trouvées", boucle and aide)
    faits = []

    def note(nom):
        return lambda *a, **k: faits.append((nom, vd.serveur_courant(), a[0] if a else None))
    faux_p = types.SimpleNamespace(
        SERVEURS=pd.SERVEURS, subs_seulement=pd.subs_seulement,
        podium_seulement=pd.podium_seulement, vitrine=pd.vitrine,
        a_poster=lambda: True, poster_podium=note("podium"),
        a_rafraichir=lambda g: True, rafraichir=note("semaine"),
        a_rafraichir_subs=lambda g: True, rafraichir_subs=note("subs"),
        # le vrai pour Threads (son profil n'a pas de bonus), « à faire » ailleurs
        a_rafraichir_bonus=lambda g: pd.a_rafraichir_bonus(g) if g == TH else True,
        rafraichir_bonus=note("bonus"))
    ns = {"_p": faux_p, "_vd_p": vd, "_sync_liens_va": note("liens"), "_suivi_va": note("suivi"),
          "_recap_clics_rest": note("clics")}
    exec(compile(textwrap.dedent(ast.get_source_segment(src_w, boucle)), "boucle", "exec"), ns)

    def par(g):
        return [f for f, s, a in faits if a == g]
    check("Threads : podium et quinzaine, ni bonus, ni synchro des liens, ni suivi des VA",
          par(TH) == ["clics", "podium", "semaine", "subs"], par(TH))
    check("… avec le bot de Threads (sur_serveur)",
          {s for f, s, a in faits if a == TH and f != "clics"} == {TH})
    check("Twitter et Va IG : tout comme avant",
          par(TW) == par(IG) == ["clics", "podium", "semaine", "subs", "bonus", "liens", "suivi"],
          (par(TW), par(IG)))
    ns_a = {}
    exec(compile(ast.get_source_segment(src_w, aide), "aide", "exec"), ns_a)
    vus = []
    _pub, _ret = rcr.publier, rcr.retirer
    try:
        rcr.publier = lambda g: vus.append(("publier", g)) or "M"
        rcr.retirer = lambda g: vus.append(("retirer", g, vd.serveur_courant())) or False
        for g in (TW, TH, IG):
            ns_a["_recap_clics_rest"](g)
    finally:
        rcr.publier, rcr.retirer = _pub, _ret
    check("l'aide ne publie plus rien ; elle vide l'ancien récap, chacun avec son bot",
          vus == [("retirer", TW, TW), ("retirer", TH, TH), ("retirer", IG, IG)], vus)
finally:
    if "_LIVRE" in globals():
        pd.SERVEURS[TH] = _LIVRE
    for k, v in _SAUVE_PD.items():
        setattr(pd, k, v)
    rcr.DATA_DIR, = _SAUVE_RCR
    cp.rattachements_identite = _SAUVE_CP
    vd.DATA_DIR, vd._http = _VD_AVANT
    for k, v in _ENV_AVANT.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)

for k in ("vivant", "quinzaine", "podium"):
    if RENDU.get(k):
        print(f"\n— rendu : {k}")
        print(json.dumps(RENDU[k], ensure_ascii=False, indent=2))

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
if FAILS:
    for f in FAILS:
        print("  - " + f)
sys.exit(1 if FAILS else 0)
