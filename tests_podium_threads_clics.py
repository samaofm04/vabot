"""Va Threads : le podium de la semaine, aux clics.

Propriétaire, 13/10/2026 : « pour Threads le podium c'est avec des clicks »
(salon « ─│🏆┤-podium » de Threads), primes 10/5/3 $ comme Twitter. Les VA
de Twitter, leurs « VA n », leurs clics GetMySocial au marché US — les
chiffres du récap « -l-clicks » de Threads, pas les trackings MyPuls que
Twitter appelle « subs ».

Vérifié ici, sans réseau ni vrai data/ (GetMySocial, MyPuls, Discord et
l'horloge sont faux ; DATA_DIR est un dossier temporaire) :
  1. le profil livré : podium seul, mesure GetMySocial, mot « clics » ;
     Twitter et Va IG inchangés ;
  2. le relevé : les liens et numéros de Twitter, les clics US de
     GetMySocial, jamais MyPuls ; un seul relevé sert Threads ET Va IG ;
  3. le message vivant : posté par Bowser dans « ─│🏆┤-podium » de Threads,
     « clics » partout, jamais « subs », primes 10/5/3 $ ; Twitter garde
     son message d'avant ;
  4. ni quinzaine, ni bonus du jour sur Threads ;
  5. le lundi : « semaine terminée » sur les chiffres entiers, puis le podium
     figé sur place, mention « Podium clics », primes passées à suivi_va ;
     aucun relevé de plus pour le podium de 9h ;
  6. la boucle du site : sur Threads, le récap des clics et le podium, rien
     d'autre.

Lancer depuis la racine du dépôt : python tests_podium_threads_clics.py
"""
from __future__ import annotations

import ast
import copy
import datetime as dt
import io
import json
import os
import pathlib
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
GMS = {"listes": [], "analytics": []}


def _page(id_, nom, *urls):
    return {"id": id_, "display_name": nom, "type": "landing", "url": None, "status": "active",
            "buttons": [{"url": u} for u in urls]}


LIENS = {EQ_TW1: [_page("l1", "(Roucham) 1", OF + "emy.brw/c42"),
                  _page("l2", "(Roucham) 1SPAM", OF + "emy.brw/c43"),
                  _page("l3", "tsiry 1", OF + "emy.brw/c37"),
                  _page("l4", "(Ricardo) 1", OF + "emy.brw/c44")],
         EQ_TW2: [{"id": "l5", "display_name": "Twitter VA 31 @abdoul_9684", "type": "directlink",
                   "url": OF + "emy.brw/c6", "status": "active", "buttons": []}]}
# les clics US de chaque lien sur la période ; le reste du monde à côté
US = {"l1": 50, "l2": 20, "l3": 35, "l4": 5, "l5": 12}


def _list_links_team(team, force_refresh=False):
    GMS["listes"].append(team)
    return {"ok": True, "links": copy.deepcopy(LIENS.get(team, []))}


def _analytics_for_links(ids, d0, d1):
    GMS["analytics"].append((tuple(ids), d0, d1))
    us = sum(US.get(i, 0) for i in ids)
    return us + 9, {"US": us, "FR": 9}


_faux_gms = types.ModuleType("gms")
_faux_gms.list_links_team = _list_links_team
_faux_gms.analytics_for_links = _analytics_for_links
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
import clics_personnes as cp           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, TH, IG = pd.TWITTER_ID, pd.THREADS_ID, pd.VA_IG_ID
NUMEROS = {"Roucham": 12, "Roucham SPAM": 24, "tsiry 1": 43, "Ricardo": 22, "abdoul_9684": 31}

# ------------------------------------------------------------ faux Discord --
SALONS = {
    TW: [{"id": "tw-podium", "name": "─│🏆┤-podium", "type": 0},
         {"id": "tw-subs", "name": "─│👤┤-subs", "type": 0},
         {"id": "tw-bonus", "name": "─│💸┤-bonus-journalier", "type": 0}],
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

    def guilde_du_salon(self, cid):
        return next((g for g, xs in SALONS.items() if any(x["id"] == cid for x in xs)), "")

    def http(self, bot, methode, chemin, js):
        self.appels.append({"bot": bot["id"], "m": methode, "p": chemin, "json": copy.deepcopy(js)})
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
            self.messages[mid] = {"salon": cid, "auteur": moi,
                                  "embeds": copy.deepcopy(js.get("embeds") or []),
                                  "content": js.get("content", "")}
            return 200, {"id": mid}
        if len(bouts) == 4 and bouts[2] == "messages":
            msg = self.messages.get(bouts[3])
            if not msg or msg["salon"] != cid:
                return 404, {"code": 10008, "message": "Unknown Message"}
            if msg["auteur"] != moi:
                return 403, {"code": 50005}
            if "embeds" in js:
                msg["embeds"] = copy.deepcopy(js["embeds"])
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
_SAUVE_CP = cp.rattachements_identite
_NB = [0]
PAUSE = {"gms": False}


def installer():
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
    GMS["listes"].clear()
    GMS["analytics"].clear()
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


RENDU = {}
try:
    cp.rattachements_identite = lambda: {}

    # ------------------------------------------------------------------ 1
    print("\n— 1. le profil livré")
    check("Threads : dans les serveurs du podium, podium SEUL, repris de Twitter",
          TH in pd.SERVEURS and pd.podium_seulement(TH) and not pd.subs_seulement(TH)
          and pd._repris_de(TH) == TW)
    p_th = pd._profil(TH)
    check("… aux clics GetMySocial (pas les trackings de Twitter), mot « clics »",
          pd._source(TH) == "gms" and pd._source(TW) == "tracking"
          and pd._unite(TH) == "clics" and pd._service(TH) == "GetMySocial")
    check("… marché US et numéros de Twitter, son bot Bowser, sans bonus ni bouton ni thème",
          p_th["marche"] == "US" and p_th["pays"] == ("US",) and p_th["fr"] is False
          and p_th["bot"] == "Bowser" and p_th["bonus"] is False
          and not p_th.get("bouton_maj") and not p_th.get("theme") and not p_th.get("avec_us"))
    check("Twitter et Va IG : profils inchangés, mot « subs », pas « podium seul »",
          pd._unite(TW) == pd._unite(IG) == "subs"
          and not pd.podium_seulement(TW) and not pd.podium_seulement(IG)
          and "reprend" not in pd._profil(TW) and pd._profil(TW) is pd.SERVEURS[TW]
          and pd._profil(IG) is pd.SERVEURS[IG])
    check("mêmes primes que Twitter (10/5/3 $)", pd.PRIMES == [10.0, 5.0, 3.0])
    check("le classement subs d'avant reste écrit à part (PROFIL_THREADS)",
          pd.PROFIL_THREADS.get("subs_seul") is True and "podium_seul" not in pd.PROFIL_THREADS)

    # ------------------------------------------------------------------ 2
    print("\n— 2. le relevé : GetMySocial, numéros de Twitter, un seul pour deux serveurs")
    installer()
    lundi, auj = pd.semaine_en_cours()
    cl = pd.classement(lundi, auj, gid=TH)
    vas = [(x["va"], x["clics"]) for x in cl["lignes"]]
    check("les VA de Twitter, leurs numéros, leurs clics US (pas le reste du monde)",
          vas == [("VA 12", 50), ("VA 43", 35), ("VA 24", 20), ("VA 31", 12), ("VA 22", 5)], vas)
    check("… lus dans GetMySocial (les deux espaces de Twitter), jamais dans MyPuls",
          set(GMS["listes"]) == {EQ_TW1, EQ_TW2} and len(GMS["analytics"]) == 5
          and not MP["appels"], (GMS, MP["appels"]))
    check("… sur la semaine en cours (lundi → aujourd'hui)",
          {a[1:] for a in GMS["analytics"]} == {(lundi.isoformat(), auj.isoformat())})
    n_a = len(GMS["analytics"])
    us = pd._releve_us(lundi, auj)
    check("Va IG reprend CE relevé pour ses VA US : aucun appel de plus",
          us is not None and [x["va"] for x in us["lignes"]] == [v for v, _ in vas]
          and len(GMS["analytics"]) == n_a, len(GMS["analytics"]) - n_a)
    avancer(minutes=30)
    cl2 = pd.classement(lundi, auj, gid=TH)
    check("Threads, une demi-heure après : même relevé, aucun appel",
          [x["va"] for x in cl2["lignes"]] == [v for v, _ in vas]
          and len(GMS["analytics"]) == n_a)
    check("le relevé gardé pour Threads est celui des clics (« gms »), pas les trackings",
          any(k[0] == TW and k[1] == "gms" for k in pd._REPRIS)
          and not any(k[1] == "tracking" for k in pd._REPRIS), list(pd._REPRIS))

    installer()
    us = pd._releve_us(lundi, auj)          # Va IG passe le premier
    n_a = len(GMS["analytics"])
    cl3 = pd.classement(lundi, auj, gid=TH)
    check("dans l'autre sens : Va IG relève, Threads reprend sans appel",
          n_a == 5 and len(GMS["analytics"]) == n_a
          and [x["va"] for x in cl3["lignes"]] == [x["va"] for x in us["lignes"]])
    avancer(hours=2, minutes=1)
    pd.classement(lundi, auj, gid=TH)
    check("deux heures plus tard : relevé neuf (le rythme de Va IG, pas toutes les heures)",
          len(GMS["analytics"]) == n_a + 5, len(GMS["analytics"]) - n_a)

    # le jour du bonus de Twitter et ses trackings ne sont plus gardés pour Threads
    installer()
    pd._garder_repris(TW, auj, auj, {"lignes": [{"va": "VA 1", "clics": 1}]}, "tracking")
    pd._garder_repris(TW, auj, auj, {"lignes": [{"va": "VA 1", "clics": 1}]}, "gms")
    check("rien de gardé hors de ce que Threads montre (trackings, jour non-lundi)",
          not pd._REPRIS, list(pd._REPRIS))
    pd._garder_repris(TW, lundi, auj, {"lignes": [{"va": "VA 1", "clics": 1}]}, "gms")
    check("… la semaine du podium, aux clics : gardée",
          (TW, "gms", lundi.isoformat(), auj.isoformat()) in pd._REPRIS)

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
    check("… jamais dans « paliers-subs », « l-clicks » ni le bonus",
          {x["p"].split("/")[2] for x in ecritures(a)} == {"th-podium"})
    e = p_th[0]["json"]["embeds"][0]
    RENDU["vivant"] = e
    desc = e["description"]
    check("titre « PODIUM CLICS — SEMAINE EN COURS »",
          e["title"] == "🔴 PODIUM CLICS — SEMAINE EN COURS", e["title"])
    check("« clics » partout, jamais « subs » ni « abonnements »",
          "subs" not in json.dumps(e, ensure_ascii=False).lower()
          and "abonnement" not in desc.lower(), desc)
    check("l'en-tête dit ce qui est compté : les clics des liens, marché US",
          "Clics des liens des VA — marché **US**" in desc, desc[:300])
    check("le top 3 avec ses primes 10/5/3 $, aux clics de GetMySocial",
          "🥇 **VA 12** — **50** clics · 💰 **10$**" in desc
          and "🥈 **VA 43** — **35** clics · 💰 **5$**" in desc
          and "🥉 **VA 24** — **20** clics · 💰 **3$**" in desc
          and "4. VA 31 — **12** clics" in desc, desc)
    check("la prime se réclame à Bowser, le bot de Threads",
          "**@Bowser**" in desc and "@Luigi" not in desc)
    check("pied « Marché US », sans bouton 🔄",
          e["footer"]["text"].startswith("YOULAB • Marché US")
          and "components" not in p_th[0]["json"])
    check("aucune lecture MyPuls pour Threads", not MP["appels"])
    check("passage suivant dans deux heures, pas avant",
          not pd.a_rafraichir(TH, CLOCK["now"].timestamp() + 119 * 60)
          and pd.a_rafraichir(TH, CLOCK["now"].timestamp() + 121 * 60))
    PAUSE["gms"] = True
    check("GetMySocial en pause : Threads attend (sa mesure en dépend)",
          pd._pause_pour(TH) and not pd.a_rafraichir(TH, CLOCK["now"].timestamp() + 3 * 3600))
    PAUSE["gms"] = False
    avancer(hours=2, minutes=5)
    US["l4"] = 80                              # Ricardo passe devant
    k1 = len(DISCORD.appels)
    with vd.sur_serveur(TH):
        mid2 = pd.rafraichir(TH)
    a = DISCORD.depuis(k1)
    check("deux heures après : le MÊME message réédité, rien de posté",
          mid2 == mid and not posts(a) and [x["m"] for x in ecritures(a)] == ["PATCH"])
    check("… avec les chiffres neufs",
          "🥇 **VA 22** — **80** clics" in ecritures(a)[0]["json"]["embeds"][0]["description"])
    US["l4"] = 5

    # Twitter, lui, garde exactement son message (« subs », trackings)
    e_tw = pd.embed_podium({"lignes": [{"va": "VA 12", "clics": 7, "numero": 12}],
                            "illisibles": [], "frais": True}, lundi, auj, en_cours=True, gid=TW)
    check("Twitter : « PODIUM SUBS », « subs », « Abonnements via Twitter », comme avant",
          e_tw["title"] == "🔴 PODIUM SUBS — SEMAINE EN COURS"
          and "**7** subs · 💰 **10$**" in e_tw["description"]
          and "Abonnements via Twitter 🐦 — clics **tracking OF**" in e_tw["description"]
          and "@Luigi" in e_tw["description"])
    check("la mention du lundi : « clics » sur Threads, l'ancienne ailleurs",
          pd._mention_podium(TH) == "@everyone 🏆 Podium clics de la semaine !"
          and pd._mention_podium(TW) == pd._mention_podium(IG) == pd.MENTION_PODIUM)

    # ------------------------------------------------------------------ 4
    print("\n— 4. ni quinzaine, ni bonus sur Threads")
    k2 = len(DISCORD.appels)
    n_a = len(GMS["analytics"])
    with vd.sur_serveur(TH):
        check("quinzaine : jamais à faire", not pd.a_rafraichir_subs(TH))
        check("… et refusée si on l'appelle quand même", pd.rafraichir_subs(TH) == "")
        check("bonus du jour : jamais à faire", not pd.a_rafraichir_bonus(TH))
        check("… et refusé si on l'appelle quand même", pd.rafraichir_bonus(TH) == "")
    check("… sans un appel à Discord ni à GetMySocial",
          len(DISCORD.appels) == k2 and len(GMS["analytics"]) == n_a,
          DISCORD.depuis(k2))

    # ------------------------------------------------------------------ 5
    print("\n— 5. le lundi : semaine terminée, puis le podium figé")
    CLOCK["now"] = dt.datetime(2026, 10, 19, 0, 10)       # lundi 00h10
    check("lundi 00h10 : à rafraîchir (dire « terminée »)", pd.a_rafraichir(TH))
    k3 = len(DISCORD.appels)
    n_a = len(GMS["analytics"])
    with vd.sur_serveur(TH):
        pd.rafraichir(TH)
    a = DISCORD.depuis(k3)
    w = ecritures(a)
    check("le message de la semaine passe « terminée », sur place (aucun message neuf)",
          [x["m"] for x in w] == ["PATCH"] and w[0]["p"].endswith(f"/{mid}")
          and w[0]["json"]["embeds"][0]["title"] == "🏁 PODIUM CLICS — SEMAINE TERMINÉE",
          [(x["m"], x["p"]) for x in w])
    check("… sur la semaine entière (12/10 → 18/10), un relevé",
          len(GMS["analytics"]) == n_a + 5
          and {x[1:] for x in GMS["analytics"][n_a:]} == {("2026-10-12", "2026-10-18")})
    check("pas encore de podium (9h)", not pd.a_poster())
    CLOCK["now"] = dt.datetime(2026, 10, 19, 9, 2)
    check("lundi 9h : le podium est dû", pd.a_poster())
    k4 = len(DISCORD.appels)
    n_a = len(GMS["analytics"])
    with vd.sur_serveur(TH):
        fige = pd.poster_podium(TH)
    a = DISCORD.depuis(k4)
    w = ecritures(a)
    check("le podium FIGE le message de la semaine sur place (le même id)",
          fige == mid and w and w[0]["m"] == "PATCH" and w[0]["p"].endswith(f"/{mid}"))
    ef = w[0]["json"]["embeds"][0]
    RENDU["podium"] = ef
    check("… « 🏆 PODIUM CLICS DE LA SEMAINE », classement arrêté",
          ef["title"] == "🏆 PODIUM CLICS DE LA SEMAINE"
          and "il ne bougera plus" in ef["description"]
          and ef["footer"]["text"].endswith("résultat final"))
    ment = [x for x in w if x["m"] == "POST"]
    check("… puis « @everyone 🏆 Podium clics de la semaine ! » en réponse, par Bowser",
          len(ment) == 1 and ment[0]["bot"] == "threads"
          and ment[0]["json"]["content"] == "@everyone 🏆 Podium clics de la semaine !"
          and ment[0]["json"]["message_reference"]["message_id"] == mid,
          [x["json"] for x in ment])
    check("… sans relevé de plus (celui de 00h10 compte déjà la semaine entière)",
          len(GMS["analytics"]) == n_a, len(GMS["analytics"]) - n_a)
    check("les primes passent à suivi_va pour Threads, top 3 aux clics",
          PRIMES_DITES == [(TH, ["VA 12", "VA 43", "VA 24"], dt.date(2026, 10, 12),
                            dt.date(2026, 10, 18))], PRIMES_DITES)
    k5 = len(DISCORD.appels)
    with vd.sur_serveur(TH):
        pd.poster_podium(TH)
    check("un second passage le même lundi : rien (ni message, ni mention, ni prime)",
          not ecritures(DISCORD.depuis(k5)) and len(PRIMES_DITES) == 1)
    k6 = len(DISCORD.appels)
    with vd.sur_serveur(TH):
        neuf = pd.rafraichir(TH)
    p_n = posts(DISCORD.depuis(k6), "th-podium")
    check("la semaine neuve part en message NEUF, en dessous du podium",
          neuf and neuf != mid and len(p_n) == 1
          and p_n[0]["json"]["embeds"][0]["title"] == "🔴 PODIUM CLICS — SEMAINE EN COURS")

    # ------------------------------------------------------------------ 6
    print("\n— 6. la boucle du site (web_upload)")
    src_w = (BOT / "web_upload.py").read_text(encoding="utf-8")
    boucle = None
    for n in ast.walk(ast.parse(src_w)):
        if (isinstance(n, ast.For) and isinstance(n.iter, ast.Attribute)
                and n.iter.attr == "SERVEURS_EXTRA"
                and "a_rafraichir_subs" in (ast.get_source_segment(src_w, n) or "")):
            boucle = n
    check("la boucle du podium est trouvée", boucle is not None)
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
    check("Threads : le récap des clics et le podium de la semaine, RIEN d'autre",
          par(TH) == ["clics", "podium", "semaine"], par(TH))
    check("… avec le bot de Threads (sur_serveur)",
          {s for f, s, a in faits if a == TH and f != "clics"} == {TH})
    check("Twitter et Va IG : tout comme avant",
          par(TW) == par(IG) == ["clics", "podium", "semaine", "subs", "bonus", "liens", "suivi"],
          (par(TW), par(IG)))
finally:
    for k, v in _SAUVE_PD.items():
        setattr(pd, k, v)
    cp.rattachements_identite = _SAUVE_CP
    vd.DATA_DIR, vd._http = _VD_AVANT
    for k, v in _ENV_AVANT.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(TMP, ignore_errors=True)

if RENDU:
    print("\n— rendu : le message vivant de Threads")
    print(json.dumps(RENDU.get("vivant"), ensure_ascii=False, indent=2))
    print("\n— rendu : le podium figé du lundi")
    print(json.dumps(RENDU.get("podium"), ensure_ascii=False, indent=2))

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
if FAILS:
    for f in FAILS:
        print("  - " + f)
sys.exit(1 if FAILS else 0)
