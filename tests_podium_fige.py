# -*- coding: utf-8 -*-
"""tests_podium_fige.py — une période finie reste dans le salon, figée.

Demande du propriétaire (03/10/2026), pour le podium de la semaine : « faut
que le message il reste chaque semaine … il reste fixe et un autre se
lance » ; et pour le classement subs de la quinzaine : « que ça reste là la
période après la période … le truc bouge plus ».

Ce qui est vérifié, sur Twitter ET Va IG :
  - un message par période, jamais effacé ;
  - le lundi avant 9h, le message de la semaine finie dit « terminée » (une
    fois, chiffres de la semaine entière) et AUCUN appel GetMySocial ne suit
    jusqu'au podium ; la semaine neuve attend le podium ;
  - à 9h, ce message est figé sur place (une seule édition finale), la
    mention @everyone part en réponse, le message neuf part après ;
  - message supprimé à la main : podium posté à neuf, comme avant ;
  - podium impossible tout le lundi : figé le mardi, sans mention ni primes ;
  - quinzaine finie : pages figées sur la période entière avant les neuves,
    nouvel essai si le relevé rate, abandon à 48 h avec ce qu'on a ;
  - aucun « EN COURS » ni « remonteront au prochain passage » dans un message
    figé.

Tout se joue dans un dossier temporaire : faux Discord en mémoire, faux
classement GetMySocial déterministe, horloge simulée (heure de Paris). Aucun
appel réseau, rien n'est écrit dans data/. Lancement : python tests_podium_fige.py
"""
from __future__ import annotations

import copy
import datetime as dt
import io
import pathlib
import re
import shutil
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# les primes sont annoncées par suivi_va : remplacé AVANT tout import, pour
# qu'aucune requête ne parte vers Discord
_PRIMES = []
_faux_suivi = types.ModuleType("suivi_va")
_faux_suivi.annoncer_primes = lambda gid, cl, debut, fin: (
    _PRIMES.append((str(gid), debut.isoformat())) or {"dits": [], "sans_adresse": [], "inconnus": []})
sys.modules["suivi_va"] = _faux_suivi

import podium_discord as pd            # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


TW, IG = pd.TWITTER_ID, pd.VA_IG_ID
GIDS = (TW, IG)
J = dt.timedelta(days=1)

# Va IG porte le thème Mario (clé « theme » de podium_discord.SERVEURS, vérifié
# en détail par tests_podium_mario.py) : ses titres et la ligne de son podium
# figé sont ceux de la course. Twitter garde les siens. .get : ce fichier tourne
# aussi sur un code sans thème (tests_podium_us.py, section H), où Va IG
# reprend les mots de Twitter.
_MARIO = bool(pd.SERVEURS.get(IG, {}).get("theme"))


def _mots(twitter, mario):
    return {TW: twitter, IG: mario if _MARIO else twitter}


T_EN_COURS = _mots("🔴 PODIUM SUBS — SEMAINE EN COURS", "🏁 GRAND PRIX DES SUBS — COURSE EN COURS 🍄")
T_TERMINE = _mots("🏁 PODIUM SUBS — SEMAINE TERMINÉE", "🏁 GRAND PRIX DES SUBS — COURSE TERMINÉE")
T_FINAL = _mots("🏆 PODIUM SUBS DE LA SEMAINE", "🏆 GRAND PRIX DES SUBS — PODIUM DE LA SEMAINE")
T_QUINZAINE = _mots("📊 Classement subs", "🏎️ Championnat des subs")
FIN_PODIUM = _mots("Semaine terminée : classement arrêté, il ne bougera plus.",
                   "Course terminée : le podium ne bougera plus.")

# ---------------------------------------------------------------- bac à sable --
TMP = pathlib.Path(tempfile.mkdtemp(prefix="podium_fige_test_"))
_SAUVE = {k: getattr(pd, k) for k in (
    "DATA_DIR", "ETAT_FICHIER", "CONFIG_FICHIER", "NUMEROS_FICHIER", "LIENS_CACHE",
    "ALLTIME_FICHIER", "_maintenant", "_aujourdhui", "_api", "_salon", "_pause_gms",
    "classement", "alltime", "time")}
pd.DATA_DIR = TMP
pd.ETAT_FICHIER = TMP / "podium.json"
pd.CONFIG_FICHIER = TMP / "podium_config.json"
pd.NUMEROS_FICHIER = TMP / "podium_numeros.json"
pd.LIENS_CACHE = TMP / "gmsdash_links.json"
pd.ALLTIME_FICHIER = TMP / "podium_alltime.json"

# --- l'horloge : heure de Paris simulée, et time.time() qui la suit
CLOCK = {"now": dt.datetime(2026, 9, 22, 12, 0)}
pd._maintenant = lambda: CLOCK["now"]
pd._aujourdhui = lambda: CLOCK["now"].date()
pd.time = types.SimpleNamespace(time=lambda: CLOCK["now"].timestamp(), sleep=lambda s: None)

PAUSE = {"on": False}
pd._pause_gms = lambda: PAUSE["on"]
pd._salon = lambda gid, voulu="": (f"{gid}-subs" if "subs" in (voulu or "")
                                   else f"{gid}-bonus" if "bonus" in (voulu or "")
                                   else f"{gid}-podium")
pd.alltime = lambda gid=None: {}


# --- le faux Discord : un salon = {id: message}, chaque appel noté
class FauxDiscord:
    def __init__(self):
        self.salons = {}
        self.appels = []
        self.n = 1000
        self.echec_ping = False
        self.panne_patch = {}          # id -> codes (ou (code, corps)) à rendre, un par appel
        self.panne_ping = {}           # salon -> (code, corps) pour les réponses, un par appel
        self.panne_post = []           # [condition(json), code, corps, combien de fois]
        self.coupes = set()            # salons dont l'accès est retiré (403, Discord 50001)

    def api(self, methode, chemin, **kw):
        js = copy.deepcopy(kw.get("json"))
        appel = {"m": methode, "p": chemin, "json": js, "quand": CLOCK["now"]}
        self.appels.append(appel)
        code, rep = self._repondre(methode, chemin, js)
        appel["code"] = code                   # un appel refusé n'a rien écrit
        return code, rep

    def _repondre(self, methode, chemin, js):
        parts = chemin.strip("/").split("/")
        if parts[0] != "channels":
            return 200, []
        msgs = self.salons.setdefault(parts[1], {})
        if parts[1] in self.coupes:
            return 403, {"message": "Missing Access", "code": 50001}
        if methode == "POST" and len(parts) == 3:
            if self.echec_ping and (js or {}).get("message_reference"):
                return 500, {"message": "panne"}
            if (js or {}).get("message_reference") and self.panne_ping.get(parts[1]):
                return self.panne_ping[parts[1]].pop(0)
            for p in self.panne_post:
                if p[3] > 0 and p[0](js or {}):
                    p[3] -= 1
                    return p[1], p[2]
            self.n += 1
            mid = f"m{self.n}"
            msgs[mid] = {"json": js, "rang": self.n, "versions": [js]}
            return 200, {"id": mid}
        mid = parts[3]
        if methode == "PATCH":
            if self.panne_patch.get(mid):
                v = self.panne_patch[mid].pop(0)
                return v if isinstance(v, tuple) else (v, {"message": "panne"})
            if mid not in msgs:
                return 404, {"message": "Unknown Message", "code": 10008}
            # une édition ne remplace que ce qu'elle envoie, comme le vrai
            # Discord : celle qui retire le seul bouton 🔄 de Va IG (« components »
            # seul) laisse l'embed en place
            msgs[mid]["json"] = dict(msgs[mid]["json"] or {}, **(js or {}))
            msgs[mid]["versions"].append(js)
            return 200, {"id": mid}
        if methode == "DELETE":
            return (204, {}) if msgs.pop(mid, None) else (404, {})
        return 404, {}


DISCORD = FauxDiscord()
pd._api = lambda methode, chemin, **kw: DISCORD.api(methode, chemin, **kw)

# --- le faux GetMySocial : des clics par heure, par VA, par serveur
BASES = {TW: {"VA 1": 10, "VA 2": 7, "VA 3": 5, "VA 4": 2},
         IG: {"Amelia VA 3": 9, "Amelia VA 1": 6, "Lola VA 2": 4}}
PANNES = set()                         # (gid, debut iso) : GetMySocial ne rend rien
ILLISIBLES = {}                        # (gid, debut iso) : VA illisibles
GMS = []                               # (gid, debut, fin, moment, fonction appelante)
# les relevés qui comptent une SEMAINE du podium. Le bonus du jour relève
# (lundi, lundi) comme le message vivant d'un lundi : seule la fonction
# appelante les distingue.
RELEVES_SEMAINE = ("rafraichir", "_semaine_terminee", "_figer_semaine", "poster_podium")


def faux_classement(debut, fin, pause=0.3, gid=None):
    gid = str(gid)
    GMS.append((gid, debut, fin, CLOCK["now"], sys._getframe(1).f_code.co_name))
    cle = (gid, debut.isoformat())
    if cle in PANNES:
        return {"lignes": [], "illisibles": [], "frais": True, "entites": 4, "liens": 4,
                "sans_numero": []}
    now = CLOCK["now"]
    lignes, ill = [], []
    for i, (va, base) in enumerate(BASES[gid].items()):
        if va in ILLISIBLES.get(cle, ()):
            ill.append(va)
            continue
        total, j = 0, debut
        while j <= fin:
            total += base * 24 if j < now.date() else base * now.hour if j == now.date() else 0
            j += J
        lignes.append({"va": va, "numero": i + 1, "clics": total, "liens": 1, "spam": False,
                       "model": ""})
    lignes.sort(key=lambda x: (-x["clics"], x["numero"]))
    out = {"lignes": lignes, "illisibles": sorted(ill), "frais": True,
           "entites": len(BASES[gid]), "liens": len(BASES[gid]), "sans_numero": []}
    # comme le vrai classement : un relevé de Twitter est gardé pour Va IG,
    # qui le reprend au lieu d'en refaire un (clé « avec_us »). getattr : ce
    # fichier doit encore tourner le jour où ce code temporaire sera retiré
    getattr(pd, "_retenir", lambda *x: None)(gid, debut, fin, out)
    return out


pd.classement = faux_classement


def complet(gid, va, debut, fin):
    """Les clics d'une période ENTIÈRE (tous ses jours révolus)."""
    return BASES[gid][va] * 24 * ((fin - debut).days + 1)


def premier(gid):
    return next(iter(BASES[gid]))


# --- outils de lecture
def remise_a_zero():
    global DISCORD
    DISCORD = FauxDiscord()
    for f in TMP.iterdir():
        if f.is_file():
            f.unlink()
    PANNES.clear()
    ILLISIBLES.clear()
    GMS.clear()
    _PRIMES.clear()
    getattr(pd, "_RELEVES", {}).clear()   # les relevés gardés en mémoire pour Va IG
    PAUSE["on"] = False


def a(moment):
    """Un tour de la vraie boucle (web_upload._start_podium_semaine_daemon),
    dans le même ordre, bonus du jour compris, pour chaque serveur. L'ordre
    est vérifié contre le source de web_upload.py (section 16)."""
    CLOCK["now"] = moment
    for gid in GIDS:
        if pd.a_poster():
            pd.poster_podium(gid)
        if pd.a_rafraichir(gid):
            pd.rafraichir(gid)
        if pd.a_rafraichir_subs(gid):
            pd.rafraichir_subs(gid)
        if pd.a_rafraichir_bonus(gid):
            pd.rafraichir_bonus(gid)


def boucle(de, a_, pas=10):
    t = de
    while t <= a_:
        a(t)
        t += dt.timedelta(minutes=pas)


def P(gid):
    return f"{gid}-podium"


def S(gid):
    return f"{gid}-subs"


def titre(js):
    return ((js or {}).get("embeds") or [{}])[0].get("title", "")


def texte(js):
    js = js or {}
    morceaux = [js.get("content") or ""]
    for e in js.get("embeds") or []:
        morceaux += [e.get("title", ""), e.get("description", ""), (e.get("footer") or {}).get("text", "")]
    return "\n".join(morceaux)


def msgs(salon):
    return DISCORD.salons.get(salon, {})


def appels_sur(mid):
    return [x for x in DISCORD.appels if x["p"].endswith("/" + mid)]


def posts(salon, apres=None, avant=None):
    return [x for x in DISCORD.appels if x["m"] == "POST" and x["p"] == f"/channels/{salon}/messages"
            and (apres is None or x["quand"] > apres) and (avant is None or x["quand"] < avant)]


def gms_semaine(gid, apres, avant):
    """Les relevés GetMySocial d'une SEMAINE du podium dans un créneau (le
    bonus du jour, qui relève la journée, n'en est pas un)."""
    return [x for x in GMS if x[0] == gid and x[4] in RELEVES_SEMAINE and apres < x[3] < avant]


def semaine_du(js):
    m = re.search(r"(?:Semaine du|depuis le) \*\*(\d\d/\d\d)\*\*", (((js or {}).get("embeds") or [{}])[0]
                                                                  .get("description", "")))
    return m.group(1) if m else None


def periode_du(js):
    m = re.search(r"Période \*\*(\d\d/\d\d) →", (((js or {}).get("embeds") or [{}])[0]
                                                .get("description", "")))
    return m.group(1) if m else None


MOTS_VIVANTS = ("EN COURS", "REMONTERONT AU PROCHAIN PASSAGE", "REMONTERA AU PROCHAIN PASSAGE",
                "RIEN N'EST JOUÉ", "MIS À JOUR")


def vivant_dans(js):
    t = texte(js).upper()
    return [m for m in MOTS_VIVANTS if m in t]


def fige(js):
    t = titre(js)
    return t in T_FINAL.values() or "(terminée)" in t


def controle_figes(etiquette):
    """Aucun message figé ne parle encore comme un message vivant."""
    fautes = []
    for salon, ms in DISCORD.salons.items():
        for mid, m in ms.items():
            if fige(m["json"]) and vivant_dans(m["json"]):
                fautes.append((salon, mid, vivant_dans(m["json"])))
    check(f"{etiquette} : aucun message figé ne dit « en cours » ni « prochain passage »",
          not fautes, fautes)


def controle_orphelins(etiquette, attente_ok=False):
    """Aucun message d'un salon du podium ou des subs ne parle comme un message
    vivant s'il n'est pas LE message vivant de la période en cours : un
    « SEMAINE EN COURS » ou un « la quinzaine · mis à jour » oublié ne serait
    plus jamais figé."""
    etat = pd._etat()
    fautes = []
    for g in GIDS:
        vif = ((etat.get("vivants") or {}).get(g) or {}).get("message")
        for mid, m in msgs(P(g)).items():
            t = titre(m["json"])
            if t and not fige(m["json"]) and mid != vif:
                fautes.append((P(g), mid, t))
        pages = ((etat.get("subs") or {}).get(g) or {}).get("messages") or []
        attente = [x for r in ((etat.get("subs_a_figer") or {}).get(g) or {}).values()
                   for x in r.get("messages") or []] if attente_ok else []
        for mid, m in msgs(S(g)).items():
            t = titre(m["json"])
            if t and not fige(m["json"]) and mid not in pages and mid not in attente:
                fautes.append((S(g), mid, t))
    check(f"{etiquette} : aucun message vivant oublié (seul celui de la période en cours parle au présent)",
          not fautes, fautes)


def par_semaine(g):
    out = {}
    for mid, m in msgs(P(g)).items():
        if (m["json"] or {}).get("embeds"):
            out.setdefault(semaine_du(m["json"]), []).append(mid)
    return out


def par_quinzaine(g):
    out = {}
    for mid, m in msgs(S(g)).items():
        out.setdefault(periode_du(m["json"]), []).append(mid)
    return out


def mentions(salon):
    """Les messages @everyone PRÉSENTS dans le salon (pas les essais refusés)."""
    return [(mid, m["json"]) for mid, m in msgs(salon).items()
            if "@everyone" in str((m["json"] or {}).get("content"))]


LUN_W, DIM_W = dt.date(2026, 9, 21), dt.date(2026, 9, 27)
LUN_W1, DIM_W1 = dt.date(2026, 9, 28), dt.date(2026, 10, 4)
LUN_W2 = dt.date(2026, 10, 5)
S_OLD, S_OLD_FIN, S_NEW = dt.date(2026, 9, 16), dt.date(2026, 9, 30), dt.date(2026, 10, 1)

try:
    # ================================================================ 1. --
    print()
    print("=" * 70)
    print("1. Le calendrier complet : semaine 21/09, podium du 28/09, quinzaine du 16/09")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    a(dt.datetime(2026, 9, 24, 12, 0))
    a(dt.datetime(2026, 9, 27, 20, 0))                       # dimanche soir
    etat = pd._etat()
    vivant_w = {g: etat["vivants"][g]["message"] for g in GIDS}
    page_old = {g: etat["subs"][g]["messages"][0] for g in GIDS}
    for g in GIDS:
        js = msgs(P(g))[vivant_w[g]]["json"]
        check(f"{g} dimanche soir : le message de la semaine est vivant",
              titre(js) == T_EN_COURS[g])
        check(f"{g} dimanche soir : le dernier relevé est gardé pour figer sans GetMySocial",
              (etat["vivants"][g].get("dernier") or {}).get("lignes")
              and etat["vivants"][g]["dernier"]["le"] == "27/09 à 20h00")

    lundi0010 = dt.datetime(2026, 9, 28, 0, 10)
    a(lundi0010)
    etat = pd._etat()
    for g in GIDS:
        js = msgs(P(g))[vivant_w[g]]["json"]
        d0 = texte(js)
        check(f"{g} lundi 00h10 : le message dit « semaine terminée »",
              titre(js) == T_TERMINE[g], titre(js))
        check(f"{g} lundi 00h10 : le podium officiel est annoncé pour 9h, sur ce message",
              "Le podium officiel arrive ce lundi à 9h, sur ce message" in d0)
        va1 = premier(g)
        check(f"{g} lundi 00h10 : chiffres de la semaine ENTIÈRE (lundi → dimanche)",
              f'**{va1}** — **{complet(g, va1, LUN_W, DIM_W)}** subs' in d0, d0[:300])
        check(f"{g} lundi 00h10 : drapeau « terminée » posé dans l'état",
              etat["vivants"][g].get("termine") is True)
        check(f"{g} lundi 00h10 : la semaine neuve n'est PAS lancée avant le podium",
              not posts(P(g), apres=dt.datetime(2026, 9, 27, 21, 0)))
        check(f"{g} lundi 00h10 : « terminée » ne parle plus d'un prochain passage",
              not vivant_dans(js), vivant_dans(js))

    for h, m in ((3, 0), (8, 50)):
        a(dt.datetime(2026, 9, 28, h, m))
    for g in GIDS:
        check(f"{g} lundi 00h10 → 08h50 : AUCUN relevé GetMySocial de semaine (porte fermée)",
              not gms_semaine(g, lundi0010, dt.datetime(2026, 9, 28, 9, 0)),
              gms_semaine(g, lundi0010, dt.datetime(2026, 9, 28, 9, 0)))
        check(f"{g} lundi 08h50 : rien à rafraîchir (a_rafraichir faux)",
              pd.a_rafraichir(g) is False)
        check(f"{g} lundi 08h50 : « terminée » n'a été écrit qu'une fois",
              sum(1 for x in appels_sur(vivant_w[g]) if x["m"] == "PATCH"
                  and titre(x["json"]) == T_TERMINE[g]) == 1)
        check(f"{g} lundi 08h50 : toujours aucun message neuf dans le salon du podium",
              not posts(P(g), apres=dt.datetime(2026, 9, 27, 21, 0)))

    neuf = dt.datetime(2026, 9, 28, 9, 0)
    a(neuf)
    etat = pd._etat()
    for g in GIDS:
        mid = vivant_w[g]
        js = msgs(P(g))[mid]["json"]
        d9 = texte(js)
        check(f"{g} 09h : le podium est le MÊME message, figé sur place",
              etat["postes"].get(f"{g}:{LUN_W}") == mid)
        check(f"{g} 09h : titre du podium final", titre(js) == T_FINAL[g])
        check(f"{g} 09h : le message dit qu'il ne bougera plus", FIN_PODIUM[g] in d9)
        check(f"{g} 09h : pied « résultat final »",
              js["embeds"][0]["footer"]["text"].endswith("· résultat final"))
        va1 = premier(g)
        check(f"{g} 09h : chiffres de la semaine entière",
              f'**{va1}** — **{complet(g, va1, LUN_W, DIM_W)}** subs' in d9)
        ping = [x for x in posts(P(g), apres=neuf - dt.timedelta(minutes=1))
                if (x["json"] or {}).get("content")]
        check(f"{g} 09h : une seule mention @everyone, en RÉPONSE au message figé",
              len(ping) == 1
              and ping[0]["json"]["content"] == "@everyone 🏆 Podium subs de la semaine !"
              and ping[0]["json"].get("allowed_mentions") == {"parse": ["everyone"]}
              and ping[0]["json"].get("message_reference") == {"message_id": mid,
                                                               "fail_if_not_exists": False}
              and not ping[0]["json"].get("embeds"), ping)
        check(f"{g} 09h : la mention est notée dans l'historique des semaines figées",
              (etat["figes"][g][LUN_W.isoformat()].get("ping") or "").startswith("m")
              and etat["figes"][g][LUN_W.isoformat()]["mode"] == "podium")
        check(f"{g} 09h : les primes sont annoncées, une fois", _PRIMES.count((g, LUN_W.isoformat())) == 1)
        neufs = [x for x in posts(P(g), apres=neuf - dt.timedelta(minutes=1))
                 if (x["json"] or {}).get("embeds")]
        check(f"{g} 09h : le message de la semaine neuve part APRÈS (même tour)",
              len(neufs) == 1 and titre(neufs[0]["json"]) == T_EN_COURS[g]
              and DISCORD.appels.index(neufs[0]) > DISCORD.appels.index(ping[0]))
        check(f"{g} 09h : le message neuf est sous le podium dans le salon",
              msgs(P(g))[etat["vivants"][g]["message"]]["rang"] > msgs(P(g))[mid]["rang"])
        check(f"{g} 09h : le message vivant n'est plus celui de la semaine finie",
              etat["vivants"][g]["semaine"] == LUN_W1.isoformat())

    a(dt.datetime(2026, 9, 28, 9, 10))
    a(dt.datetime(2026, 9, 29, 10, 0))
    a(dt.datetime(2026, 9, 30, 23, 50))                      # dernier passage de la quinzaine
    for g in GIDS:
        check(f"{g} 09h10 : le podium n'est pas refait", _PRIMES.count((g, LUN_W.isoformat())) == 1
              and len([x for x in posts(P(g)) if (x["json"] or {}).get("content")]) == 1)
        js = msgs(S(g))[page_old[g]]["json"]
        check(f"{g} 30/09 23h50 : la quinzaine est encore vivante",
              titre(js) == f"{T_QUINZAINE[g]} — la quinzaine")

    jeudi = dt.datetime(2026, 10, 1, 0, 10)
    a(jeudi)
    etat = pd._etat()
    for g in GIDS:
        js = msgs(S(g))[page_old[g]]["json"]
        ds = texte(js)
        check(f"{g} 01/10 : l'ancienne page est figée, ses dates dans le titre",
              titre(js) == f"{T_QUINZAINE[g]} — quinzaine du 16/09 au 30/09 (terminée)", titre(js))
        check(f"{g} 01/10 : elle dit que la période est finie et ne bougera plus",
              "Période terminée : classement arrêté, il ne bougera plus." in ds
              and js["embeds"][0]["footer"]["text"].endswith("· résultat final"))
        va1 = premier(g)
        # Va IG avec la clé « avec_us » (temporaire) : la page montre aussi les
        # VA de Twitter, et son total unique est celui de toute l'agence. .get :
        # sans la clé (ou sans le code), le total redevient celui de ses VA seuls
        mele = g == IG and pd.SERVEURS.get(IG, {}).get("avec_us")
        total = sum(complet(x, v, S_OLD, S_OLD_FIN) for x in ((g, TW) if mele else (g,))
                    for v in BASES[x])
        check(f"{g} 01/10 : chiffres de la quinzaine ENTIÈRE (16 → 30/09)",
              f'**{va1}** — **{complet(g, va1, S_OLD, S_OLD_FIN)}** subs' in ds
              and f'👥 **Total période**\n**{total}** subs' in ds, ds[:400])
        nouv = etat["subs"][g]
        check(f"{g} 01/10 : la quinzaine neuve a SA page, postée après la figée",
              nouv["saison"] == S_NEW.isoformat() and nouv["messages"][0] != page_old[g]
              and msgs(S(g))[nouv["messages"][0]]["rang"] > msgs(S(g))[page_old[g]]["rang"]
              and titre(msgs(S(g))[nouv["messages"][0]]["json"]) == f"{T_QUINZAINE[g]} — la quinzaine")
        fig_patch = [x for x in appels_sur(page_old[g]) if x["m"] == "PATCH" and fige(x["json"])]
        neuve_post = [x for x in posts(S(g), apres=jeudi - dt.timedelta(minutes=1))]
        check(f"{g} 01/10 : figée AVANT que la neuve parte",
              len(fig_patch) == 1 and neuve_post
              and DISCORD.appels.index(fig_patch[0]) < DISCORD.appels.index(neuve_post[0]))
        check(f"{g} 01/10 : historique des quinzaines figées, rien en attente",
              etat["subs_figes"][g][S_OLD.isoformat()]["complet"] is True
              and not (etat.get("subs_a_figer") or {}).get(g))
        check(f"{g} 01/10 : un seul relevé de la période entière pour figer",
              len([x for x in GMS if x[0] == g and x[1] == S_OLD and x[2] == S_OLD_FIN
                   and x[3] >= jeudi]) == 1)

    a(dt.datetime(2026, 10, 1, 12, 0))
    a(dt.datetime(2026, 10, 4, 22, 0))
    a(dt.datetime(2026, 10, 5, 0, 10))
    a(dt.datetime(2026, 10, 5, 3, 0))
    a(dt.datetime(2026, 10, 5, 9, 0))
    a(dt.datetime(2026, 10, 5, 9, 10))
    a(dt.datetime(2026, 10, 6, 12, 0))
    etat = pd._etat()
    for g in GIDS:
        mid_w1 = etat["postes"].get(f"{g}:{LUN_W1}")
        js1 = msgs(P(g))[mid_w1]["json"] if mid_w1 in msgs(P(g)) else {}
        va1 = premier(g)
        check(f"{g} lundi 05/10 : la semaine du 28/09 est figée à son tour, sur place",
              titre(js1) == T_FINAL[g]
              and f'**{va1}** — **{complet(g, va1, LUN_W1, DIM_W1)}** subs' in texte(js1))
        apres_final = [x for x in appels_sur(vivant_w[g])
                       if x["quand"] > neuf]
        check(f"{g} : le message du 21/09 n'est plus jamais touché après son podium",
              not apres_final, apres_final[:2])
        finals = [x for x in appels_sur(vivant_w[g]) if x["m"] == "PATCH" and fige(x["json"])]
        check(f"{g} : le message du 21/09 n'a reçu qu'UNE édition finale", len(finals) == 1)
        apres_q = [x for x in appels_sur(page_old[g]) if x["quand"] > jeudi]
        check(f"{g} : la page de la quinzaine du 16/09 n'est plus touchée après le 01/10",
              not apres_q, apres_q[:2])
        semaines = {}
        for mid, m in msgs(P(g)).items():
            if (m["json"] or {}).get("embeds"):
                semaines.setdefault(semaine_du(m["json"]), []).append(mid)
        check(f"{g} : UN message par semaine dans le salon du podium (21/09, 28/09, 05/10)",
              sorted(semaines) == ["05/10", "21/09", "28/09"]
              and all(len(v) == 1 for v in semaines.values()), semaines)
        ordre = sorted(msgs(P(g)).items(), key=lambda kv: kv[1]["rang"])
        sem_ordre = [semaine_du(m["json"]) for _mid, m in ordre if (m["json"] or {}).get("embeds")]
        check(f"{g} : les semaines se lisent dans l'ordre", sem_ordre == ["21/09", "28/09", "05/10"],
              sem_ordre)
        check(f"{g} : seul le message de la semaine en cours est vivant",
              [titre(m["json"]) for _mid, m in ordre if (m["json"] or {}).get("embeds")]
              == [T_FINAL[g], T_FINAL[g], T_EN_COURS[g]])
        periodes = {}
        for mid, m in msgs(S(g)).items():
            periodes.setdefault(periode_du(m["json"]), []).append(mid)
        check(f"{g} : UN message par quinzaine dans le salon des subs",
              sorted(periodes) == ["01/10", "16/09"]
              and all(len(v) == 1 for v in periodes.values()), periodes)
        check(f"{g} : les deux semaines figées sont dans l'historique",
              sorted(etat["figes"][g]) == [LUN_W.isoformat(), LUN_W1.isoformat()])
        check(f"{g} : jamais une seule suppression dans le salon du podium",
              not [x for x in DISCORD.appels if x["m"] == "DELETE" and x["p"].startswith(f"/channels/{P(g)}")])
    controle_figes("calendrier complet")

    # forcer : refait le podium sur le MÊME message
    CLOCK["now"] = dt.datetime(2026, 10, 6, 13, 0)
    n_av = len(DISCORD.appels)
    mid_w1 = pd._etat()["postes"][f"{TW}:{LUN_W1}"]
    r = pd.poster_podium(TW, jour=dt.date(2026, 10, 5), mentionner=False, forcer=True)
    nouveaux = DISCORD.appels[n_av:]
    check("forcer : le podium est réédité sur place, rien de posté",
          r == mid_w1 and [x["m"] for x in nouveaux] == ["PATCH"]
          and nouveaux[0]["p"].endswith("/" + mid_w1))

    # ================================================================ 2. --
    print()
    print("=" * 70)
    print("2. Message supprimé à la main : le podium est posté à neuf, comme avant")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    a(dt.datetime(2026, 9, 27, 20, 0))
    a(dt.datetime(2026, 9, 28, 0, 10))
    vivant_w = {g: pd._etat()["vivants"][g]["message"] for g in GIDS}
    del DISCORD.salons[P(TW)][vivant_w[TW]]                 # supprimé à la main
    neuf = dt.datetime(2026, 9, 28, 9, 0)
    a(neuf)
    etat = pd._etat()
    p9 = posts(P(TW), apres=neuf - dt.timedelta(minutes=1))
    check("supprimé : l'édition échoue (404), le podium part en message neuf avec @everyone",
          len(p9) == 2 and titre(p9[0]["json"]) == "🏆 PODIUM SUBS DE LA SEMAINE"
          and p9[0]["json"].get("content") == "@everyone 🏆 Podium subs de la semaine !"
          and p9[0]["json"].get("allowed_mentions") == {"parse": ["everyone"]}
          and not p9[0]["json"].get("message_reference"), [titre(x["json"]) for x in p9])
    check("supprimé : le podium posté est noté, mode « reposte »",
          etat["postes"][f"{TW}:{LUN_W}"] not in ("", vivant_w[TW])
          and etat["figes"][TW][LUN_W.isoformat()]["mode"] == "reposte")
    check("supprimé : puis la semaine neuve, après le podium",
          "SEMAINE EN COURS" in titre(p9[1]["json"]))
    check("supprimé : les primes sont annoncées quand même", (TW, LUN_W.isoformat()) in _PRIMES)
    check("Va IG intact à côté : figé sur place", etat["postes"][f"{IG}:{LUN_W}"] == vivant_w[IG])

    # la mention ratée ne défait pas le podium, et elle est réessayée seule
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    a(dt.datetime(2026, 9, 28, 0, 10))
    DISCORD.echec_ping = True
    a(dt.datetime(2026, 9, 28, 9, 0))
    etat = pd._etat()
    check("mention refusée (500) : le podium compte comme posté, la mention est à refaire",
          all(etat["postes"].get(f"{g}:{LUN_W}") for g in GIDS)
          and all(etat["figes"][g][LUN_W.isoformat()]["ping"] == "" for g in GIDS)
          and all(etat["figes"][g][LUN_W.isoformat()].get("ping_a_refaire") for g in GIDS))
    n_av, n_gms = len(DISCORD.appels), len(GMS)
    a(dt.datetime(2026, 9, 28, 9, 10))
    sur_tw = [x for x in DISCORD.appels[n_av:] if x["p"].startswith(f"/channels/{P(TW)}")]
    check("mention refusée : à 09h10, seule la mention est retentée (en réponse), rien d'autre",
          [x["m"] for x in sur_tw] == ["POST"] and sur_tw[0]["json"].get("message_reference")
          and not [x for x in GMS[n_gms:] if x[4] == "poster_podium"]
          and _PRIMES.count((TW, LUN_W.isoformat())) == 1, [(x["m"], x["json"]) for x in sur_tw])

    # ================================================================ 3. --
    print()
    print("=" * 70)
    print("3. Podium impossible tout le lundi : figé le mardi, sans mention ni primes")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    a(dt.datetime(2026, 9, 27, 20, 0))
    vivant_w = {g: pd._etat()["vivants"][g]["message"] for g in GIDS}
    for g in GIDS:
        PANNES.add((g, LUN_W.isoformat()))                  # GetMySocial muet sur la semaine
    lundi = dt.datetime(2026, 9, 28, 0, 10)
    a(lundi)
    for g in GIDS:
        js = msgs(P(g))[vivant_w[g]]["json"]
        check(f"{g} relevé vide à 00h10 : « terminée » avec le dernier relevé, et il le dit",
              titre(js) == T_TERMINE[g]
              and "Chiffres du dernier relevé (27/09 à 20h00)" in texte(js), texte(js)[-300:])
    t = dt.datetime(2026, 9, 28, 9, 0)
    while t <= dt.datetime(2026, 9, 28, 23, 50):
        a(t)
        t += dt.timedelta(minutes=10)
    etat = pd._etat()
    for g in GIDS:
        check(f"{g} tout le lundi : pas de podium noté (il réessaie)",
              not etat.get("postes", {}).get(f"{g}:{LUN_W}"))
        check(f"{g} tout le lundi : la semaine neuve attend, aucun message posté",
              not posts(P(g), apres=lundi - dt.timedelta(minutes=1)))
        check(f"{g} tout le lundi : aucun relevé de la semaine NEUVE (porte fermée)",
              not [x for x in GMS if x[0] == g and x[1] == LUN_W1 and x[4] in RELEVES_SEMAINE])
    mardi = dt.datetime(2026, 9, 29, 0, 10)
    PANNES.discard((TW, LUN_W.isoformat()))                # Twitter : GetMySocial revient
    a(mardi)                                               # Va IG : toujours muet
    etat = pd._etat()
    for g in GIDS:
        mid = vivant_w[g]
        js = msgs(P(g))[mid]["json"]
        check(f"{g} mardi : la semaine finie est FIGÉE (podium final, il ne bougera plus)",
              titre(js) == T_FINAL[g]
              and FIN_PODIUM[g] in texte(js))
        check(f"{g} mardi : aucune mention @everyone",
              not [x for x in posts(P(g)) if "@everyone" in str((x["json"] or {}).get("content"))])
        check(f"{g} mardi : aucune prime annoncée", (g, LUN_W.isoformat()) not in _PRIMES)
        check(f"{g} mardi : noté « sans podium » dans l'historique, pas dans les postes",
              etat["figes"][g][LUN_W.isoformat()]["mode"] == "sans_podium"
              and not etat.get("postes", {}).get(f"{g}:{LUN_W}"))
        neufs = posts(P(g), apres=mardi - dt.timedelta(minutes=1))
        fin_patch = [x for x in appels_sur(mid) if x["m"] == "PATCH" and fige(x["json"])]
        check(f"{g} mardi : la semaine neuve part APRÈS le gel",
              len(neufs) == 1 and len(fin_patch) == 1
              and DISCORD.appels.index(fin_patch[0]) < DISCORD.appels.index(neufs[0])
              and titre(neufs[0]["json"]) == T_EN_COURS[g])
        check(f"{g} : depuis lundi, deux éditions (« terminée » puis finale), pas une de plus",
              len([x for x in appels_sur(mid) if x["m"] == "PATCH" and x["quand"] >= lundi]) == 2)
    va1 = premier(TW)
    check("Twitter mardi : GetMySocial revenu, chiffres de la semaine entière",
          f'**{va1}** — **{complet(TW, va1, LUN_W, DIM_W)}** subs' in texte(msgs(P(TW))[vivant_w[TW]]["json"])
          and pd._etat()["figes"][TW][LUN_W.isoformat()]["complet"] is True)
    check("Va IG mardi : toujours muet, figé sur le dernier relevé, et il le dit",
          "Chiffres du dernier relevé (27/09 à 20h00)" in texte(msgs(P(IG))[vivant_w[IG]]["json"])
          and pd._etat()["figes"][IG][LUN_W.isoformat()]["complet"] is False)
    a(dt.datetime(2026, 9, 29, 12, 0))
    check("mardi midi : les messages figés ne sont plus touchés",
          not [x for g in GIDS for x in appels_sur(vivant_w[g]) if x["quand"] > mardi])
    controle_figes("podium impossible")

    # Discord en panne au moment de figer : réessai sans redemander les chiffres
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    vivant_w = {g: pd._etat()["vivants"][g]["message"] for g in GIDS}
    for g in GIDS:
        PANNES.add((g, LUN_W.isoformat()))
    a(dt.datetime(2026, 9, 28, 9, 0))
    for g in GIDS:
        PANNES.discard((g, LUN_W.isoformat()))
    DISCORD.panne_patch[vivant_w[TW]] = [503]
    m1 = dt.datetime(2026, 9, 29, 0, 10)
    a(m1)
    etat = pd._etat()
    check("Discord 503 au gel : le message reste vivant dans l'état, la semaine neuve attend",
          etat["vivants"][TW]["semaine"] == LUN_W.isoformat() and etat["vivants"][TW].get("embed_final")
          and not posts(P(TW), apres=m1 - dt.timedelta(minutes=1)))
    n_gms = len([x for x in GMS if x[0] == TW and x[1] == LUN_W])
    a(dt.datetime(2026, 9, 29, 0, 20))
    etat = pd._etat()
    check("Discord revenu : figé au tour suivant, sans nouveau relevé de la semaine",
          titre(msgs(P(TW))[vivant_w[TW]]["json"]) == "🏆 PODIUM SUBS DE LA SEMAINE"
          and len([x for x in GMS if x[0] == TW and x[1] == LUN_W]) == n_gms
          and etat["vivants"][TW]["semaine"] == LUN_W1.isoformat())

    # ================================================================ 4. --
    print()
    print("=" * 70)
    print("4. Quinzaine : relevé raté -> nouvel essai, abandon à 48 h")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 29, 12, 0))
    a(dt.datetime(2026, 9, 30, 23, 50))
    page_old = {g: pd._etat()["subs"][g]["messages"][0] for g in GIDS}
    ILLISIBLES[(TW, S_OLD.isoformat())] = ["VA 2"]          # Twitter : un VA illisible
    PANNES.add((IG, S_OLD.isoformat()))                     # Va IG : rien du tout
    jeudi = dt.datetime(2026, 10, 1, 0, 10)
    a(jeudi)
    etat = pd._etat()
    for g in GIDS:
        check(f"{g} 01/10 relevé raté : la quinzaine neuve part quand même",
              etat["subs"][g]["saison"] == S_NEW.isoformat()
              and etat["subs"][g]["messages"][0] != page_old[g])
        rec = (etat.get("subs_a_figer") or {}).get(g, {}).get(S_OLD.isoformat())
        check(f"{g} 01/10 relevé raté : la quinzaine finie reste à figer, notée dans l'état",
              rec and rec["messages"] == [page_old[g]] and rec["essais"] == 1, rec)
        # Va IG : seul son bouton 🔄 s'en va dès maintenant (« components » seul,
        # vérifié dans tests_podium_maj.py) ; l'embed, lui, attend le gel
        check(f"{g} 01/10 relevé raté : l'ancienne page n'est pas encore touchée",
              not [x for x in appels_sur(page_old[g]) if x["quand"] >= jeudi
                   and set(x["json"] or {}) != {"components"}])

    a(dt.datetime(2026, 10, 1, 1, 10))
    check("01h10 : pas de nouvel essai avant 2 h (quota)",
          len([x for x in GMS if x[1] == S_OLD and x[2] == S_OLD_FIN and x[3] >= jeudi]) == 2)
    a(dt.datetime(2026, 10, 1, 2, 20))
    etat = pd._etat()
    check("02h20 : nouvel essai pour chaque serveur, toujours raté",
          len([x for x in GMS if x[1] == S_OLD and x[2] == S_OLD_FIN and x[3] >= jeudi]) == 4
          and all(etat["subs_a_figer"][g][S_OLD.isoformat()]["essais"] == 2 for g in GIDS))
    del ILLISIBLES[(TW, S_OLD.isoformat())]                 # Twitter : le relevé revient
    retour = dt.datetime(2026, 10, 1, 4, 30)
    a(retour)
    etat = pd._etat()
    js = msgs(S(TW))[page_old[TW]]["json"]
    check("Twitter 04h30 : figée au nouvel essai, chiffres complets",
          titre(js) == "📊 Classement subs — quinzaine du 16/09 au 30/09 (terminée)"
          and f'**VA 1** — **{complet(TW, "VA 1", S_OLD, S_OLD_FIN)}** subs' in texte(js)
          and etat["subs_figes"][TW][S_OLD.isoformat()]["complet"] is True
          and etat["subs_figes"][TW][S_OLD.isoformat()]["essais"] == 3
          and TW not in (etat.get("subs_a_figer") or {}))
    check("Twitter 04h30 : la page figée est restée AU-DESSUS de la neuve",
          msgs(S(TW))[page_old[TW]]["rang"] < msgs(S(TW))[etat["subs"][TW]["messages"][0]]["rang"])
    t = dt.datetime(2026, 10, 1, 5, 0)
    while t < dt.datetime(2026, 10, 3, 0, 0):
        a(t)
        t += dt.timedelta(hours=1)
    etat = pd._etat()
    check("Twitter : une fois figée, plus aucun relevé de la quinzaine finie",
          not [x for x in GMS if x[0] == TW and x[1] == S_OLD and x[3] > retour])
    check("Twitter : la page figée n'est plus touchée",
          not [x for x in appels_sur(page_old[TW]) if x["quand"] > retour])
    essais_ig = etat["subs_a_figer"][IG][S_OLD.isoformat()]["essais"]
    check("Va IG avant 48 h : toujours en attente, essais espacés d'au moins 2 h",
          2 < essais_ig <= 1 + 48 // 2, essais_ig)
    check("Va IG avant 48 h : l'ancienne page est encore dans son état vivant",
          titre(msgs(S(IG))[page_old[IG]]["json"]) == f"{T_QUINZAINE[IG]} — la quinzaine")
    abandon = dt.datetime(2026, 10, 3, 0, 20)
    a(abandon)
    etat = pd._etat()
    js = msgs(S(IG))[page_old[IG]]["json"]
    check("Va IG à 48 h : figée avec le dernier relevé, et le message le dit",
          titre(js) == f"{T_QUINZAINE[IG]} — quinzaine du 16/09 au 30/09 (terminée)"
          and "Chiffres du dernier relevé (30/09 à 23h50)" in texte(js)
          and "il ne bougera plus" in texte(js), texte(js)[-300:])
    check("Va IG à 48 h : historique « incomplet », plus rien en attente",
          etat["subs_figes"][IG][S_OLD.isoformat()]["complet"] is False
          and not (etat.get("subs_a_figer") or {}).get(IG))
    a(dt.datetime(2026, 10, 3, 4, 0))
    check("Va IG après l'abandon : plus aucun relevé ni édition de la quinzaine finie",
          not [x for x in GMS if x[0] == IG and x[1] == S_OLD and x[3] > abandon]
          and not [x for x in appels_sur(page_old[IG]) if x["quand"] > abandon])
    controle_figes("quinzaine ratée")

    # un VA illisible jusqu'au bout : figée avec, sans « prochain passage »
    remise_a_zero()
    a(dt.datetime(2026, 9, 30, 23, 50))
    page_old = {g: pd._etat()["subs"][g]["messages"][0] for g in GIDS}
    ILLISIBLES[(TW, S_OLD.isoformat())] = ["VA 2"]
    a(dt.datetime(2026, 10, 1, 0, 10))
    a(dt.datetime(2026, 10, 3, 0, 20))
    js = msgs(S(TW))[page_old[TW]]["json"]
    check("illisible à 48 h : figée avec ce qu'on a, le VA manquant « à confirmer »",
          "(terminée)" in titre(js)
          and "⚠️ Relevé indisponible : VA 2 — à confirmer." in texte(js)
          and "remonteront" not in texte(js), texte(js)[-300:])

    # Discord refuse d'écrire au moment d'abandonner : pas de boucle toutes les 10 min
    remise_a_zero()
    a(dt.datetime(2026, 9, 30, 23, 50))
    page_old = {g: pd._etat()["subs"][g]["messages"][0] for g in GIDS}
    PANNES.add((TW, S_OLD.isoformat()))
    a(dt.datetime(2026, 10, 1, 0, 10))
    DISCORD.panne_patch[page_old[TW]] = [503]
    a48 = dt.datetime(2026, 10, 3, 0, 20)
    CLOCK["now"] = a48
    check("48 h passées : un passage est déclenché tout de suite", pd.a_rafraichir_subs(TW) is True)
    pd.rafraichir_subs(TW)
    rec = (pd._etat().get("subs_a_figer") or {}).get(TW, {}).get(S_OLD.isoformat()) or {}
    check("Discord 503 à l'abandon : la quinzaine reste à figer, marquée « abandon »",
          rec.get("abandon") is True)
    check("Discord 503 à l'abandon : les pages calculées attendent dans l'état",
          bool(rec.get("pages")))
    n_gms = len(GMS)
    a(a48 + dt.timedelta(minutes=10))
    js = msgs(S(TW))[page_old[TW]]["json"]
    check("Discord revenu 10 min après : figée sur les pages gardées, sur le dernier relevé",
          "(terminée)" in titre(js) and "Chiffres du dernier relevé (30/09 à 23h50)" in texte(js)
          and not (pd._etat().get("subs_a_figer") or {}).get(TW))
    check("Discord revenu : AUCUN relevé GetMySocial pour réécrire (ni la quinzaine finie, ni la neuve)",
          not [x for x in GMS[n_gms:] if x[0] == TW and x[4] in ("rafraichir_subs", "_figer_quinzaine")],
          GMS[n_gms:])

    # ================================================================ 5. --
    print()
    print("=" * 70)
    print("5. GetMySocial en pause à 48 h : figée sans lui")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 30, 23, 50))
    page_old = {g: pd._etat()["subs"][g]["messages"][0] for g in GIDS}
    PANNES.add((TW, S_OLD.isoformat()))
    a(dt.datetime(2026, 10, 1, 0, 10))
    nouvelle = pd._etat()["subs"][TW]["messages"][0]
    PAUSE["on"] = True
    debut_pause = dt.datetime(2026, 10, 1, 0, 30)
    a(dt.datetime(2026, 10, 2, 12, 0))
    check("pause, avant 48 h : rien ne bouge", pd.a_rafraichir_subs(TW) is False
          and not [x for x in DISCORD.appels if x["quand"] > debut_pause])
    a(dt.datetime(2026, 10, 3, 0, 30))
    js = msgs(S(TW))[page_old[TW]]["json"]
    check("pause, 48 h passées : la quinzaine finie est figée sur le dernier relevé",
          "(terminée)" in titre(js) and "Chiffres du dernier relevé (30/09 à 23h50)" in texte(js))
    check("pause : AUCUN appel GetMySocial pendant la pause",
          not [x for x in GMS if x[3] > debut_pause])
    check("pause : la page de la quinzaine neuve n'est pas rafraîchie (pas de relevé)",
          not [x for x in appels_sur(nouvelle) if x["quand"] > debut_pause])
    check("pause : plus rien à faire ensuite", pd.a_rafraichir_subs(TW) is False)

    # ================================================================ 6. --
    print()
    print("=" * 70)
    print("6. Quinzaine figée sur plus (ou moins) de pages qu'en direct")
    print("=" * 70)
    remise_a_zero()
    _bases_tw = dict(BASES[TW])
    try:
        a(dt.datetime(2026, 9, 30, 23, 50))
        page_old = pd._etat()["subs"][TW]["messages"]
        check("en direct : une seule page", len(page_old) == 1)
        BASES[TW] = {f"VA {i}": 1 + i % 7 for i in range(1, 181)}   # la liste complète s'allonge
        jeudi = dt.datetime(2026, 10, 1, 0, 10)
        a(jeudi)
        fige_ = pd._etat()["subs_figes"][TW][S_OLD.isoformat()]["messages"]
        nouv = pd._etat()["subs"][TW]["messages"]
        check("plus de pages : la première est rééditée, les autres postées",
              len(fige_) >= 2 and fige_[0] == page_old[0])
        check("plus de pages : toutes figées, numérotées",
              all("(terminée)" in titre(msgs(S(TW))[m]["json"]) for m in fige_)
              and all(f"page {i}/{len(fige_)}" in msgs(S(TW))[m]["json"]["embeds"][0]["footer"]["text"]
                      for i, m in enumerate(fige_, start=1)))
        check("plus de pages : les pages figées passent AVANT celles de la quinzaine neuve",
              max(msgs(S(TW))[m]["rang"] for m in fige_) < min(msgs(S(TW))[m]["rang"] for m in nouv))
        txt = "\n".join(texte(msgs(S(TW))[m]["json"]) for m in fige_)
        check("plus de pages : aucun VA perdu", all(re.search(rf"VA {i}(?!\d)", txt) for i in range(1, 181)))

        # et l'inverse : la liste raccourcit, la page en trop est retirée
        remise_a_zero()
        a(dt.datetime(2026, 9, 30, 23, 50))
        page_old = pd._etat()["subs"][TW]["messages"]
        BASES[TW] = dict(_bases_tw)
        a(dt.datetime(2026, 10, 1, 0, 10))
        fige_ = pd._etat()["subs_figes"][TW][S_OLD.isoformat()]["messages"]
        check("moins de pages : la page en trop est retirée, la première figée",
              len(page_old) >= 2 and fige_ == page_old[:1]
              and all(m not in msgs(S(TW)) for m in page_old[1:])
              and "(terminée)" in titre(msgs(S(TW))[page_old[0]]["json"]))
    finally:
        BASES[TW] = _bases_tw

    # ================================================================ 7. --
    print()
    print("=" * 70)
    print("7. Serveur tout neuf, et rattrapage à la main")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 28, 3, 0))
    check("serveur sans historique, lundi 03h : le message vivant part tout de suite",
          all(pd._etat()["vivants"][g]["semaine"] == LUN_W1.isoformat() for g in GIDS))
    CLOCK["now"] = dt.datetime(2026, 9, 28, 3, 10)
    st = pd._etat()
    check("date passée à la main : aucune attente du podium",
          pd._attente_podium(st, TW, dt.date(2026, 10, 5)) is False)
    check("le lundi, la porte ne vaut que pour un serveur qui a déjà un podium",
          pd._attente_podium(st, TW) is True and pd._attente_podium({}, TW) is False)
    CLOCK["now"] = dt.datetime(2026, 9, 29, 3, 10)
    check("le mardi, la porte est ouverte quoi qu'il arrive", pd._attente_podium(st, TW) is False)

    # ================================================================ 8. --
    print()
    print("=" * 70)
    print("8. Discord passager sur l'édition de chaque heure : jamais de message en double")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    etat = pd._etat()
    w = {g: etat["vivants"][g]["message"] for g in GIDS}
    sp = {g: etat["subs"][g]["messages"][0] for g in GIDS}
    DISCORD.panne_patch[w[TW]] = [503]
    DISCORD.panne_patch[sp[TW]] = [0]                       # délai dépassé (requests) : code 0
    DISCORD.panne_patch[w[IG]] = [(403, {"code": 50001, "message": "Missing Access"})]
    DISCORD.panne_patch[sp[IG]] = [429]
    t1 = dt.datetime(2026, 9, 22, 13, 10)
    a(t1)
    etat = pd._etat()
    check("Twitter 503 / délai dépassé : rien de reposté, les mêmes messages restent les vivants",
          etat["vivants"][TW]["message"] == w[TW] and etat["subs"][TW]["messages"] == [sp[TW]]
          and not posts(P(TW), apres=t1 - dt.timedelta(minutes=1))
          and not posts(S(TW), apres=t1 - dt.timedelta(minutes=1)),
          (etat["vivants"][TW]["message"], etat["subs"][TW]["messages"]))
    check("Twitter : le tour raté compte comme un passage (pas un relevé toutes les 10 min)",
          pd.a_rafraichir(TW) is False and pd.a_rafraichir_subs(TW) is False)
    t2 = dt.datetime(2026, 9, 22, 14, 10)
    a(t2)
    etat = pd._etat()
    check("Va IG accès retiré (403 50001) / 429 : rien de reposté",
          etat["vivants"][IG]["message"] == w[IG] and etat["subs"][IG]["messages"] == [sp[IG]]
          and not posts(P(IG), apres=t1) and not posts(S(IG), apres=t1))
    check("Twitter : l'heure suivante, l'édition repasse sur le MÊME message",
          [x for x in appels_sur(w[TW]) if x["quand"] == t2 and x["m"] == "PATCH"]
          and "22/09 à 14h10" in msgs(P(TW))[w[TW]]["json"]["embeds"][0]["footer"]["text"])
    del DISCORD.salons[P(TW)][w[TW]]                         # supprimé à la main
    a(dt.datetime(2026, 9, 22, 15, 20))
    nv = pd._etat()["vivants"][TW]["message"]
    check("supprimé à la main en cours de semaine : là, un message neuf le remplace",
          nv != w[TW] and nv in msgs(P(TW)))
    for t in (dt.datetime(2026, 9, 27, 20, 0), dt.datetime(2026, 9, 28, 0, 10), dt.datetime(2026, 9, 28, 9, 0),
              dt.datetime(2026, 9, 28, 9, 10), dt.datetime(2026, 9, 30, 23, 50), dt.datetime(2026, 10, 1, 0, 10),
              dt.datetime(2026, 10, 1, 12, 0), dt.datetime(2026, 10, 6, 12, 0)):
        a(t)
    for g in GIDS:
        sem, qz = par_semaine(g), par_quinzaine(g)
        check(f"{g} après les pannes : UN message par semaine et UN par quinzaine",
              sorted(sem) == ["05/10", "21/09", "28/09"] and all(len(v) == 1 for v in sem.values())
              and sorted(qz) == ["01/10", "16/09"] and all(len(v) == 1 for v in qz.values()), (sem, qz))
    controle_orphelins("pannes passagères")
    controle_figes("pannes passagères")

    # ================================================================ 9. --
    print()
    print("=" * 70)
    print("9. Quinzaine figée : une page qui ne part pas n'est jamais perdue")
    print("=" * 70)
    remise_a_zero()
    _bases_tw = dict(BASES[TW])
    try:
        a(dt.datetime(2026, 9, 30, 23, 50))
        page_old = pd._etat()["subs"][TW]["messages"]
        BASES[TW] = {f"VA {i}": 1 + i % 7 for i in range(1, 181)}   # la version figée tient sur 2 pages
        DISCORD.panne_post.append([lambda js: "(terminée) (2/" in titre(js), 503, {"message": "panne"}, 1])
        jeudi = dt.datetime(2026, 10, 1, 0, 10)
        a(jeudi)
        etat = pd._etat()
        rec = ((etat.get("subs_a_figer") or {}).get(TW) or {}).get(S_OLD.isoformat())
        check("POST d'une page figée refusé (503) : la quinzaine reste à figer, rien n'est noté figé",
              bool(rec) and not ((etat.get("subs_figes") or {}).get(TW) or {}).get(S_OLD.isoformat()),
              ((etat.get("subs_figes") or {}).get(TW), rec and rec.get("messages")))
        boucle(jeudi + dt.timedelta(minutes=10), dt.datetime(2026, 10, 1, 4, 0))
        etat = pd._etat()
        fg = ((etat.get("subs_figes") or {}).get(TW) or {}).get(S_OLD.isoformat()) or {}
        txt = "\n".join(texte(msgs(S(TW))[m]["json"]) for m in fg.get("messages") or [] if m in msgs(S(TW)))
        manquants = [i for i in range(1, 181) if not re.search(rf"VA {i}(?!\d)", txt)]
        check("au tour suivant : la page manquante est postée, aucun VA ni total perdu, « complet »",
              fg.get("complet") is True and len(fg.get("messages") or []) == 2 and not manquants
              and "Total période" in txt and not (etat.get("subs_a_figer") or {}).get(TW),
              (fg, len(manquants)))
        check("les pages figées sont numérotées 1/2 et 2/2",
              [msgs(S(TW))[m]["json"]["embeds"][0]["footer"]["text"][:8] for m in fg.get("messages") or []]
              == ["page 1/2", "page 2/2"])
        nouv = etat["subs"][TW]["messages"]
        check("les pages figées restent AU-DESSUS de celles de la quinzaine neuve",
              nouv and max(msgs(S(TW))[m]["rang"] for m in fg["messages"])
              < min(msgs(S(TW))[m]["rang"] for m in nouv))
        check("un seul relevé de la période entière, même avec la page à refaire",
              len([x for x in GMS if x[0] == TW and x[1] == S_OLD and x[2] == S_OLD_FIN
                   and x[3] >= jeudi]) == 1)
        controle_orphelins("page figée refusée")
        controle_figes("page figée refusée")

        # ============================================================ 10. --
        print()
        print("=" * 70)
        print("10. Page supprimée à la main + Discord en panne : jamais deux fois la même page")
        print("=" * 70)
        remise_a_zero()
        BASES[TW] = {f"VA {i}": 1 + i % 7 for i in range(1, 181)}
        a(dt.datetime(2026, 9, 30, 23, 50))
        old = pd._etat()["subs"][TW]["messages"]
        check("en direct : deux pages", len(old) == 2)
        del DISCORD.salons[S(TW)][old[0]]                   # page 1 supprimée à la main
        DISCORD.panne_patch[old[1]] = [503]                 # page 2 : Discord en panne une fois
        jeudi = dt.datetime(2026, 10, 1, 0, 10)
        boucle(jeudi, dt.datetime(2026, 10, 1, 2, 30))
        etat = pd._etat()
        fg = ((etat.get("subs_figes") or {}).get(TW) or {}).get(S_OLD.isoformat()) or {}
        figees = [mid for mid, m in msgs(S(TW)).items() if "(terminée)" in titre(m["json"])]
        p1 = [mid for mid in figees if msgs(S(TW))[mid]["json"]["embeds"][0]["footer"]["text"].startswith("page 1/")]
        check("une seule page « 1/2 » figée dans le salon", len(p1) == 1, p1)
        check("toute page figée du salon est dans l'historique (aucune orpheline)",
              sorted(figees) == sorted(fg.get("messages") or []) and fg.get("complet") is True,
              (figees, fg))
        check("un seul relevé de la période entière",
              len([x for x in GMS if x[0] == TW and x[1] == S_OLD and x[2] == S_OLD_FIN
                   and x[3] >= jeudi]) == 1)
        controle_orphelins("page supprimée + panne")

        # ============================================================ 12. --
        print()
        print("=" * 70)
        print("12. Quinzaine figée en retard sur plus de pages : pas mêlée à la neuve")
        print("=" * 70)
        remise_a_zero()
        BASES[TW] = dict(_bases_tw)
        a(dt.datetime(2026, 9, 30, 23, 50))
        page_old = pd._etat()["subs"][TW]["messages"]
        ILLISIBLES[(TW, S_OLD.isoformat())] = ["VA 2"]       # premier essai raté
        a(dt.datetime(2026, 10, 1, 0, 10))
        del ILLISIBLES[(TW, S_OLD.isoformat())]
        BASES[TW] = {f"VA {i}": 1 + i % 7 for i in range(1, 181)}   # la version figée tient sur 2 pages
        a(dt.datetime(2026, 10, 1, 2, 20))
        etat = pd._etat()
        fg = ((etat.get("subs_figes") or {}).get(TW) or {}).get(S_OLD.isoformat()) or {}
        nouv = etat["subs"][TW]["messages"]
        ordre = [(periode_du(m["json"]), mid) for mid, m in sorted(msgs(S(TW)).items(),
                                                                  key=lambda kv: kv[1]["rang"])]
        check("figée en retard sur 2 pages : toutes au-dessus de la quinzaine neuve",
              len(fg.get("messages") or []) == 2 and nouv
              and [p for p, _m in ordre] == ["16/09"] * 2 + ["01/10"] * len(nouv), ordre)
        check("figée en retard : la page de la quinzaine neuve reprise est bien remplacée",
              all("(terminée)" not in titre(msgs(S(TW))[m]["json"]) for m in nouv)
              and all(m in msgs(S(TW)) for m in nouv))
        controle_orphelins("figée en retard")
        controle_figes("figée en retard")
    finally:
        BASES[TW] = _bases_tw

    # ================================================================ 11. --
    print()
    print("=" * 70)
    print("11. Discord en panne au moment de figer la quinzaine : pas de second relevé")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 30, 23, 50))
    page_old = {g: pd._etat()["subs"][g]["messages"][0] for g in GIDS}
    DISCORD.panne_patch[page_old[IG]] = [503]
    jeudi = dt.datetime(2026, 10, 1, 0, 10)
    boucle(jeudi, dt.datetime(2026, 10, 1, 4, 30))
    pleins = [x for x in GMS if x[0] == IG and x[1] == S_OLD and x[2] == S_OLD_FIN and x[3] >= jeudi]
    fige_le = next((x["quand"] for x in appels_sur(page_old[IG])
                    if x["m"] == "PATCH" and fige(x["json"]) and x["code"] == 200), None)
    check("Va IG : un seul relevé de la période entière malgré la panne Discord",
          len(pleins) == 1, [x[3].strftime("%H:%M") for x in pleins])
    check("Va IG : la page est figée au tour suivant (10 min), pas deux heures après",
          fige_le == jeudi + dt.timedelta(minutes=10), fige_le)
    controle_orphelins("panne au gel de la quinzaine")

    # ================================================================ 13. --
    print()
    print("=" * 70)
    print("13. La mention @everyone du podium n'est jamais perdue")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    a(dt.datetime(2026, 9, 28, 0, 10))
    w = {g: pd._etat()["vivants"][g]["message"] for g in GIDS}
    DISCORD.panne_ping[P(TW)] = [(503, {"message": "panne"})]
    a(dt.datetime(2026, 9, 28, 9, 0))
    check("réponse refusée (503) : le podium est figé, la mention est à refaire",
          pd._etat()["postes"].get(f"{TW}:{LUN_W}") == w[TW] and not mentions(P(TW))
          and pd._etat()["figes"][TW][LUN_W.isoformat()].get("ping_a_refaire"))
    n_gms = len(GMS)
    a(dt.datetime(2026, 9, 28, 9, 10))
    a(dt.datetime(2026, 9, 28, 9, 20))
    fg = pd._etat()["figes"][TW][LUN_W.isoformat()]
    mt = mentions(P(TW))
    check("503 : la mention part au tour suivant, en réponse au podium, UNE fois",
          len(mt) == 1 and mt[0][1].get("message_reference", {}).get("message_id") == w[TW]
          and fg.get("ping") == mt[0][0] and not fg.get("ping_a_refaire"), (mt, fg))
    check("503 : le nouvel essai ne relève rien chez GetMySocial",
          not [x for x in GMS[n_gms:] if x[0] == TW and x[4] == "poster_podium"])
    check("Va IG à côté : une mention, en réponse", len(mentions(P(IG))) == 1)

    for code, corps in ((400, {"code": 160002, "message": "Cannot reply without permission to read message history"}),
                        (403, {"code": 50013, "message": "Missing Permissions"})):
        remise_a_zero()
        a(dt.datetime(2026, 9, 22, 12, 0))
        a(dt.datetime(2026, 9, 28, 0, 10))
        w = {g: pd._etat()["vivants"][g]["message"] for g in GIDS}
        DISCORD.panne_ping[P(TW)] = [(code, corps)] * 20
        a(dt.datetime(2026, 9, 28, 9, 0))
        a(dt.datetime(2026, 9, 28, 9, 10))
        mt = mentions(P(TW))
        lien = f"https://discord.com/channels/{TW}/{P(TW)}/{w[TW]}"
        check(f"réponse refusée ({code} {corps['code']}) : mention simple tout de suite, avec le lien du podium",
              len(mt) == 1 and not mt[0][1].get("message_reference")
              and mt[0][1].get("allowed_mentions") == {"parse": ["everyone"]}
              and lien in mt[0][1].get("content", "")
              and pd._etat()["figes"][TW][LUN_W.isoformat()].get("ping") == mt[0][0], mt)
        check(f"réponse refusée ({code}) : une seule réponse tentée, pas de boucle",
              len([x for x in posts(P(TW)) if (x["json"] or {}).get("message_reference")]) == 1)

    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    a(dt.datetime(2026, 9, 28, 0, 10))
    DISCORD.panne_ping[P(TW)] = [(0, {"message": "Read timed out"})]
    a(dt.datetime(2026, 9, 28, 9, 0))
    a(dt.datetime(2026, 9, 28, 9, 10))
    check("délai dépassé (code 0) : la mention a pu partir, pas de second @everyone",
          len([x for x in posts(P(TW)) if "@everyone" in str((x["json"] or {}).get("content"))]) == 1
          and not pd._etat()["figes"][TW][LUN_W.isoformat()].get("ping_a_refaire"))

    # ================================================================ 14. --
    print()
    print("=" * 70)
    print("14. Accès au salon retiré (403 50001) : la semaine attend, elle n'est pas oubliée")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    w = pd._etat()["vivants"][TW]["message"]
    DISCORD.coupes.add(P(TW))
    boucle(dt.datetime(2026, 9, 27, 22, 0), dt.datetime(2026, 9, 29, 0, 30))
    etat = pd._etat()
    check("accès retiré : la semaine n'est pas notée figée tant que le message est injoignable",
          not ((etat.get("figes") or {}).get(TW) or {}).get(LUN_W.isoformat())
          and etat["vivants"][TW]["semaine"] == LUN_W.isoformat() and etat["vivants"][TW]["message"] == w,
          ((etat.get("figes") or {}).get(TW), etat["vivants"].get(TW, {}).get("semaine")))
    DISCORD.coupes.clear()                                 # le propriétaire rend l'accès
    retour = dt.datetime(2026, 9, 29, 9, 0)
    boucle(retour, dt.datetime(2026, 9, 29, 10, 0))
    etat = pd._etat()
    js = msgs(P(TW))[w]["json"]
    fg = ((etat.get("figes") or {}).get(TW) or {}).get(LUN_W.isoformat()) or {}
    check("accès rendu : la semaine est figée sur place (podium final), notée sans podium",
          titre(js) == "🏆 PODIUM SUBS DE LA SEMAINE" and "il ne bougera plus" in texte(js)
          and fg.get("mode") == "sans_podium" and fg.get("edite") is True, fg)
    neufs = posts(P(TW), apres=retour - dt.timedelta(minutes=1))
    vif = ((etat.get("vivants") or {}).get(TW) or {}).get("message")
    check("accès rendu : la semaine neuve part après, en dessous",
          len([x for x in neufs if (x["json"] or {}).get("embeds") and x["code"] == 200]) == 1
          and vif in msgs(P(TW)) and msgs(P(TW))[vif]["rang"] > msgs(P(TW))[w]["rang"])
    controle_orphelins("accès retiré")

    # ================================================================ 15. --
    print()
    print("=" * 70)
    print("15. GetMySocial en pause du lundi au mardi : la semaine se fige sur ses chiffres gardés")
    print("=" * 70)
    remise_a_zero()
    a(dt.datetime(2026, 9, 22, 12, 0))
    a(dt.datetime(2026, 9, 28, 0, 10))                     # « terminée » : la semaine ENTIÈRE est relevée
    w = {g: pd._etat()["vivants"][g]["message"] for g in GIDS}
    for g in GIDS:
        PANNES.add((g, LUN_W.isoformat()))                  # le podium rate tout le lundi
    PAUSE["on"] = True                                     # quota épuisé de lundi 09h à mardi 18h
    boucle(dt.datetime(2026, 9, 28, 9, 0), dt.datetime(2026, 9, 28, 23, 50))
    n_gms = len(GMS)
    mardi = dt.datetime(2026, 9, 29, 0, 0)
    boucle(mardi, dt.datetime(2026, 9, 29, 17, 50))
    etat = pd._etat()
    for g in GIDS:
        js = msgs(P(g))[w[g]]["json"]
        va1 = premier(g)
        check(f"{g} pause, mardi : figée sur les chiffres de la semaine entière, sans promesse périmée",
              titre(js) == T_FINAL[g] and "podium officiel arrive" not in texte(js)
              and "dernier relevé" not in texte(js)
              and f'**{va1}** — **{complet(g, va1, LUN_W, DIM_W)}** subs' in texte(js), texte(js)[:300])
        check(f"{g} pause, mardi : figée dès le premier tour du mardi",
              [x["quand"] for x in appels_sur(w[g]) if x["m"] == "PATCH" and fige(x["json"])] == [mardi])
        fg = ((etat.get("figes") or {}).get(g) or {}).get(LUN_W.isoformat()) or {}
        check(f"{g} pause, mardi : noté sans podium, chiffres complets",
              fg.get("mode") == "sans_podium" and fg.get("complet") is True, fg)
        check(f"{g} pause, mardi : la semaine neuve attend la fin de la pause (il faut ses chiffres)",
              not posts(P(g), apres=mardi - dt.timedelta(minutes=1)))
    check("pause, mardi : AUCUN appel GetMySocial", not GMS[n_gms:], GMS[n_gms:][:3])
    PAUSE["on"] = False
    fin_pause = dt.datetime(2026, 9, 29, 18, 0)
    a(fin_pause)
    for g in GIDS:
        neufs = posts(P(g), apres=fin_pause - dt.timedelta(minutes=1))
        check(f"{g} fin de la pause : la semaine neuve part, sous la semaine figée",
              len(neufs) == 1 and titre(neufs[0]["json"]) == T_EN_COURS[g])
    controle_orphelins("pause lundi-mardi")

    # ================================================================ 16. --
    print()
    print("=" * 70)
    print("16. La boucle simulée est celle de web_upload.py")
    print("=" * 70)
    _src_w = (BOT / "web_upload.py").read_text(encoding="utf-8")
    _i = _src_w.find("def _start_podium_semaine_daemon")
    _corps = _src_w[_i:_src_w.find("\ndef ", _i + 10)]
    _pas = ["_p.a_poster()", "_p.poster_podium(gid)", "_p.a_rafraichir(gid)", "_p.rafraichir(gid)",
            "_p.a_rafraichir_subs(gid)", "_p.rafraichir_subs(gid)", "_p.a_rafraichir_bonus(gid)",
            "_p.rafraichir_bonus(gid)"]
    _pos = [_corps.find(x) for x in _pas]
    check("web_upload : podium, puis message vivant, puis quinzaine, puis bonus (l'ordre de a())",
          _i >= 0 and all(p >= 0 for p in _pos) and _pos == sorted(_pos), list(zip(_pas, _pos)))

    # ---------------------------------------------- les textes, hors boucle --
    cl = {"lignes": [{"va": "VA 1", "numero": 1, "clics": 5, "liens": 1, "spam": False}],
          "illisibles": ["VA 9"], "frais": True}
    e_vif = pd.embed_podium(cl, LUN_W, DIM_W, en_cours=True)
    e_ter = pd.embed_podium(cl, LUN_W, DIM_W, termine=True)
    e_fin = pd.embed_podium(cl, LUN_W, DIM_W)
    check("vivant : « il remontera au prochain passage » (inchangé)",
          "il remontera au prochain passage" in e_vif["description"])
    check("terminée : le relevé manquant sera relu pour le podium",
          "il sera relu pour le podium officiel" in e_ter["description"]
          and "prochain passage" not in e_ter["description"])
    check("final : à confirmer avant de payer, rien n'est promis pour plus tard",
          "à confirmer avant de payer" in e_fin["description"]
          and "prochain passage" not in e_fin["description"])
    CLOCK["now"] = dt.datetime(2026, 9, 28, 10, 30)
    check("terminée écrit après 9h (podium en échec) : plus de « à 9h » périmé",
          "Le podium officiel arrive dans la journée, sur ce message."
          in pd.embed_podium(cl, LUN_W, DIM_W, termine=True)["description"])
    p_fin = pd.pages_subs(cl, S_OLD, S_OLD_FIN, {}, final=True)
    check("quinzaine figée : « remonteront au prochain passage » remplacé",
          "remonteront" not in p_fin[0]["description"]
          and "⚠️ Relevé indisponible : VA 9 — à confirmer." in p_fin[0]["description"])
    check("quinzaine vivante : texte inchangé",
          "ils remonteront au prochain passage" in pd.pages_subs(cl, S_OLD, S_OLD_FIN, {})[0]["description"])
    src = (BOT / "podium_discord.py").read_text(encoding="utf-8")
    check("aucune date naïve dans le module (heure de Paris partout)", "dt.date.today()" not in src)
    check("l'état s'écrit de façon atomique (safe_json), jamais write_text direct",
          "ETAT_FICHIER.write_text" not in src and "safe_json.write_text(ETAT_FICHIER" in src)
except Exception as _e:
    import traceback
    check("podium figé : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-900:])
finally:
    for _k, _v in _SAUVE.items():
        setattr(pd, _k, _v)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
