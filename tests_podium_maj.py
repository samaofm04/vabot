# -*- coding: utf-8 -*-
"""tests_podium_maj.py — le bouton « 🔄 Mettre à jour » du podium de Va IG.

Demande du propriétaire (03/10/2026) : « mets un truc pour reload a la
main », « le bouton refresh ». Deux heures entre deux relevés sur Va IG :
le staff veut voir le podium et le classement subs bouger tout de suite.

Ce qui est vérifié :
  - le bouton (gris, « Mettre à jour », 🔄, custom_id « podium:maj ») est
    sous le message VIVANT de la semaine et sous chaque page VIVANTE de la
    quinzaine de Va IG, à l'envoi comme à chaque réédition ; jamais sur
    Twitter (aucun « components » envoyé, ses messages restent ceux d'avant) ;
  - chaque message figé s'en débarrasse : « terminée » du lundi, podium de
    9h, podium reposté, podium corrigé (primes retenues), semaine figée le
    mardi (relevé raté, pause GetMySocial), quinzaine figée — « components »
    vide envoyé exprès, parce qu'une édition muette les GARDE (le faux
    Discord ci-dessous fait comme le vrai) ; une quinzaine finie qui attend
    son gel (VA illisible à minuit) perd le bouton dès 00h10, une fois, et
    au passage suivant si Discord était en panne ;
  - le clic : un autre bouton passe son chemin (None), un VA se voit
    répondre « réservé au staff », un serveur sans bouton une réponse
    neutre, deux minutes entre deux clics, la pause GetMySocial, une mise à
    jour déjà en cours ; sinon réponse éphémère tout de suite, et en fond
    rafraichir puis rafraichir_subs, une fois chacun, sur le serveur du clic ;
  - le clic passe outre le rythme (deux heures), pas les règles de gel : le
    lundi à 3h, la semaine neuve attend toujours le podium ;
  - un seul passage à la fois : la boucle saute son tour (au journal) pendant
    le travail d'un clic, le clic répond « déjà en cours » pendant celui de la
    boucle, et rien n'est jamais posté deux fois — y compris avec de vrais
    fils qui se croisent ;
  - la route /discord/interactions de web_upload passe le clic au module.

Faux Discord, faux GetMySocial (le VRAI classement tourne dessus), horloge
simulée, dossier temporaire : aucun appel réseau, rien n'est écrit dans data/.
Lancement : python tests_podium_maj.py
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
import json
import pathlib
import re
import shutil
import sys
import tempfile
import textwrap
import threading
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

CLOCK = {"now": dt.datetime(2026, 9, 22, 12, 0)}
J = dt.timedelta(days=1)

# ------------------------------------------------ faux suivi_va (la paie) --
_PRIMES = []
_faux_suivi = types.ModuleType("suivi_va")
_faux_suivi.annoncer_primes = lambda gid, cl, debut, fin: (
    _PRIMES.append((str(gid), debut.isoformat())) or {"dits": [], "sans_adresse": [], "inconnus": []})
sys.modules["suivi_va"] = _faux_suivi

# ------------------------------------------------- faux GetMySocial --------
# Les mêmes liens que tests_podium_us.py : deux espaces Twitter, un espace FR.
EQ_TW1, EQ_TW2 = "tm_6a0e4739bfa0c238f20a8bf5", "tm_6ab46ebb11a0232c11211b1a"
EQ_FR = "tm_6ac06401e06eabe3b9ef45f6"
LIENS = {
    EQ_TW1: {"t1": ("Twitter VA 1 @abdoul", {"US": 10, "FR": 1}),
             "t2": ("Twitter VA 2 @bryan", {"US": 7}),
             "t3": ("Twitter VA 3 @carl", {"US": 5, "BE": 2}),
             "t4": ("Twitter VA 4 @dino", {"US": 2})},
    EQ_TW2: {"t5": ("Twitter VA 5 @emy", {"US": 1})},
    EQ_FR: {"f3": ("Amelia VA 3 @seven", {"FR": 6, "BE": 2, "CH": 1, "US": 3}),
            "f1": ("Amelia VA 1 @prisca", {"FR": 5, "LU": 1}),
            "f2": ("Lola VA 2 @lea", {"FR": 3, "MC": 1, "US": 4}),
            "fb": ("Amelia 1", {"FR": 50})},
}
TAUX = {i: t for eq in LIENS.values() for i, (_n, t) in eq.items()}
IDS_TW = set(LIENS[EQ_TW1]) | set(LIENS[EQ_TW2])
NUMEROS_TW = {"abdoul": 1, "bryan": 2, "carl": 3, "dino": 4, "emy": 5}

GMS = []                               # chaque appel d'analytics
FR_MUET, TW_MUET = set(), set()        # (d0, d1) : GetMySocial ne rend rien
LIEN_MUET = set()                      # (id, d0, d1) : ce lien seul ne répond pas
PAUSE = {"on": False}
# un fil qui n'est pas le fil principal reste bloqué dans son premier relevé
# tant que « libre » n'est pas posé : de quoi croiser deux passages pour de vrai
BLOCAGE = {"actif": False, "entre": threading.Event(), "libre": threading.Event()}


def heures(d0, d1):
    a_, b = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)
    auj = CLOCK["now"].date()
    h = 0
    plein = min(b, auj - J)
    if plein >= a_:
        h += 24 * ((plein - a_).days + 1)
    if a_ <= auj <= b:
        h += CLOCK["now"].hour
    return h


def _analytics(ids, d0, d1):
    ids = [str(i) for i in ids]
    marche = "US" if ids[0] in IDS_TW else "FR"
    fil = threading.current_thread()
    if BLOCAGE["actif"] and fil is not threading.main_thread():
        BLOCAGE["entre"].set()
        BLOCAGE["libre"].wait(10)
    GMS.append({"ids": tuple(ids), "d0": d0, "d1": d1, "quand": CLOCK["now"], "marche": marche,
                "fil": fil.name})
    if (d0, d1) in (TW_MUET if marche == "US" else FR_MUET):
        return None, None
    if any((i, d0, d1) in LIEN_MUET for i in ids):
        return None, None
    pays = {}
    for i in ids:
        for p, r in TAUX[i].items():
            pays[p] = pays.get(p, 0) + r * heures(d0, d1)
    return sum(pays.values()), pays


_faux_gms = types.ModuleType("gms")
_faux_gms.analytics_for_links = _analytics
_faux_gms.list_links_team = lambda team, force_refresh=False: {
    "ok": True, "links": [{"id": i, "display_name": n} for i, (n, _t) in LIENS.get(team, {}).items()]}
_faux_gms.pause_restante = lambda: 0
sys.modules["gms"] = _faux_gms

import podium_discord as pd            # noqa: E402
import safe_json                       # noqa: E402
import verif_discord as vd             # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


TW, IG = pd.TWITTER_ID, pd.VA_IG_ID
GIDS = (TW, IG)
BOUTON = [{"type": 1, "components": [{"type": 2, "style": 2, "label": "Mettre à jour",
                                      "emoji": {"name": "🔄"}, "custom_id": "podium:maj"}]}]
ROLE_MANAGER_IG = vd.SERVEURS_EXTRA[IG]["role_manager"]
ROLE_MANAGER_TW = vd.SERVEURS_EXTRA[TW]["role_manager"]
VIVANTS = ("🔴 PODIUM SUBS — SEMAINE EN COURS", "📊 Classement subs — la quinzaine")


# ------------------------------------------------------- le faux Discord --
class FauxDiscord:
    """Une édition ne remplace que ce qu'elle envoie, comme le vrai Discord :
    sans « components », les boutons d'un message restent. C'est ce qui rend
    le « components » vide des messages figés indispensable."""

    def __init__(self):
        self.salons, self.appels, self.n = {}, [], {}
        self.verrou = threading.Lock()

    def api(self, methode, chemin, **kw):
        with self.verrou:
            js = copy.deepcopy(kw.get("json"))
            self.appels.append({"m": methode, "p": chemin, "json": js, "quand": CLOCK["now"],
                                "fil": threading.current_thread().name,
                                "srv": vd.serveur_courant()})
            parts = chemin.strip("/").split("/")
            if parts[0] != "channels":
                return 200, []
            msgs = self.salons.setdefault(parts[1], {})
            if methode == "POST" and len(parts) == 3:
                self.n[parts[1]] = self.n.get(parts[1], 0) + 1
                mid = f"{parts[1]}:{self.n[parts[1]]}"
                msgs[mid] = {"json": js, "rang": self.n[parts[1]]}
                return 200, {"id": mid}
            mid = parts[3]
            if methode == "PATCH":
                if mid not in msgs:
                    return 404, {"message": "Unknown Message", "code": 10008}
                msgs[mid]["json"] = dict(msgs[mid]["json"] or {}, **(js or {}))
                return 200, {"id": mid}
            if methode == "DELETE":
                return (204, {}) if msgs.pop(mid, None) else (404, {})
            return 404, {}


DISCORD = FauxDiscord()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="podium_maj_test_"))
_SAUVE = {k: getattr(pd, k) for k in (
    "DATA_DIR", "ETAT_FICHIER", "CONFIG_FICHIER", "NUMEROS_FICHIER", "LIENS_CACHE",
    "ALLTIME_FICHIER", "_maintenant", "_aujourdhui", "_api", "_salon", "_pause_gms", "time",
    "rafraichir", "rafraichir_subs")}
_SAUVE_IG = copy.deepcopy(pd.SERVEURS[IG])
_SAUVE_VD = vd._EN_FOND
_NB_BAC = [0]
TACHES = []                            # le travail « en fond » d'un clic, lancé à la main


def installer():
    """Un bac neuf : dossier, horloge, Discord, pause, clics, verrou libre."""
    global DISCORD
    _NB_BAC[0] += 1
    d = TMP / f"bac{_NB_BAC[0]}"
    d.mkdir()
    safe_json.write_text(d / "podium_numeros.json", json.dumps(NUMEROS_TW))
    pd.DATA_DIR = d
    pd.ETAT_FICHIER = d / "podium.json"
    pd.CONFIG_FICHIER = d / "podium_config.json"
    pd.NUMEROS_FICHIER = d / "podium_numeros.json"
    pd.LIENS_CACHE = d / "gmsdash_links.json"
    pd.ALLTIME_FICHIER = d / "podium_alltime.json"
    pd._maintenant = lambda: CLOCK["now"]
    pd._aujourdhui = lambda: CLOCK["now"].date()
    pd.time = types.SimpleNamespace(time=lambda: CLOCK["now"].timestamp(), sleep=lambda s: None)
    pd._pause_gms = lambda: PAUSE["on"]
    pd._salon = lambda gid, voulu="": (f"{gid}-subs" if "subs" in (voulu or "")
                                       else f"{gid}-bonus" if "bonus" in (voulu or "")
                                       else f"{gid}-podium")
    DISCORD = FauxDiscord()
    pd._api = lambda methode, chemin, **kw: DISCORD.api(methode, chemin, **kw)
    pd._RELEVES.clear()
    pd._DERNIER_CLIC.clear()
    GMS.clear()
    _PRIMES.clear()
    FR_MUET.clear()
    TW_MUET.clear()
    LIEN_MUET.clear()
    PAUSE["on"] = False
    TACHES.clear()
    vd._EN_FOND = TACHES.append
    BLOCAGE["actif"] = False
    BLOCAGE["entre"].clear()
    BLOCAGE["libre"].clear()


def a(moment, gids=GIDS):
    """Un tour de la vraie boucle (web_upload._start_podium_semaine_daemon)."""
    CLOCK["now"] = moment
    for gid in gids:
        with vd.sur_serveur(gid):
            if pd.a_poster():
                pd.poster_podium(gid)
            if pd.a_rafraichir(gid):
                pd.rafraichir(gid)
            if pd.a_rafraichir_subs(gid):
                pd.rafraichir_subs(gid)
            if pd.a_rafraichir_bonus(gid):
                pd.rafraichir_bonus(gid)


def derouler(calendrier):
    installer()
    for moment, action in calendrier:
        if action:
            action()
        a(moment)


def m(*x):
    return dt.datetime(*x)


def titre(js):
    return (((js or {}).get("embeds") or [{}])[0]).get("title", "")


def pied(js):
    return ((((js or {}).get("embeds") or [{}])[0]).get("footer") or {}).get("text", "")


def vivant(js):
    return any(titre(js).startswith(t) for t in VIVANTS)


def appels_messages(gid):
    """Les envois et éditions de messages À EMBED sur les salons d'un serveur."""
    return [x for x in DISCORD.appels if x["m"] in ("POST", "PATCH")
            and x["p"].startswith(f"/channels/{gid}-") and (x["json"] or {}).get("embeds")]


def controle_appels(etiquette):
    """Chaque appel de Va IG : bouton si vivant, « components » vide si figé.
    Twitter : jamais de « components »."""
    ig = appels_messages(IG)
    fautes = [(x["m"], titre(x["json"]), x["json"].get("components", "ABSENT")) for x in ig
              if x["json"].get("components", "ABSENT") != (BOUTON if vivant(x["json"]) else [])]
    check(f"{etiquette} : Va IG — bouton sur chaque envoi/édition vivant, « components » vide sur "
          f"chaque message figé ({len(ig)} appels)", not fautes and len(ig) > 2, fautes[:4])
    tw = [x for x in DISCORD.appels if x["p"].startswith(f"/channels/{TW}-")]
    check(f"{etiquette} : Twitter — aucun « components » envoyé ({len(tw)} appels)",
          tw and not [x for x in tw if "components" in (x["json"] or {})])


def controle_salons(etiquette):
    """L'état des salons après coup : seul le message vivant porte le bouton."""
    etat = pd._etat()
    vifs = {str((etat.get("vivants") or {}).get(IG, {}).get("message") or "")}
    vifs |= {str(x) for x in ((etat.get("subs") or {}).get(IG, {}).get("messages") or [])}
    vifs.discard("")
    fautes = []
    n_fig = 0
    for salon in (f"{IG}-podium", f"{IG}-subs"):
        for mid, msg in DISCORD.salons.get(salon, {}).items():
            js = msg["json"] or {}
            if not js.get("embeds"):
                continue                      # la mention @everyone, sans bouton
            if mid in vifs:
                if js.get("components") != BOUTON or not vivant(js):
                    fautes.append(("vivant sans bouton", mid, titre(js), js.get("components")))
            else:
                n_fig += 1
                if js.get("components") or vivant(js):
                    fautes.append(("figé avec bouton", mid, titre(js), js.get("components")))
    check(f"{etiquette} : dans les salons de Va IG, le bouton n'est QUE sous les messages vivants "
          f"({len(vifs)} vivant(s), {n_fig} figé(s))", not fautes, fautes[:4])
    for salon in (f"{TW}-podium", f"{TW}-subs"):
        avec = [mid for mid, msg in DISCORD.salons.get(salon, {}).items()
                if "components" in (msg["json"] or {})]
        check(f"{etiquette} : {salon} sans aucun bouton", not avec, avec)


def clic(gid=IG, cid="podium:maj", roles=(), perms="0", typ=3, uid="42"):
    return {"type": typ, "guild_id": gid, "channel_id": f"{gid}-podium", "application_id": "777",
            "data": {"custom_id": cid, "component_type": 2},
            "member": {"user": {"id": uid}, "roles": list(roles), "permissions": perms},
            "message": {"id": "x", "channel_id": f"{gid}-podium"}, "token": "jeton-interaction"}


def staff(gid=IG):
    return clic(gid, roles=[ROLE_MANAGER_IG if gid == IG else ROLE_MANAGER_TW])


def contenu(rep):
    return ((rep or {}).get("data") or {}).get("content")


def ephemere(rep):
    return (rep or {}).get("type") == 4 and ((rep or {}).get("data") or {}).get("flags") == 64


def journal(f):
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        r = f()
    return r, tampon.getvalue()


LANCEE = "🔄 Mise à jour lancée : le podium et le classement changent dans une minute."
STAFF_SEUL = "🔒 Réservé au staff."
EN_COURS = "⏳ Mise à jour déjà en cours."
TROP_TOT = "⏳ Déjà mis à jour il y a moins de 2 minutes."

# la vie normale : semaine, lundi « terminée », podium de 9h, quinzaine figée
CAL_NORMAL = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 22, 14, 10), None),
              (m(2026, 9, 27, 20, 0), None), (m(2026, 9, 28, 0, 10), None),
              (m(2026, 9, 28, 9, 0), None), (m(2026, 9, 28, 9, 10), None),
              (m(2026, 9, 29, 10, 0), None), (m(2026, 9, 30, 23, 50), None),
              (m(2026, 10, 1, 0, 10), None), (m(2026, 10, 1, 12, 0), None)]
LUN_W, DIM_W = dt.date(2026, 9, 21), dt.date(2026, 9, 27)


def muet_fr_semaine():
    FR_MUET.add((LUN_W.isoformat(), DIM_W.isoformat()))


def fr_revenu():
    FR_MUET.clear()


def pause_on():
    PAUSE["on"] = True
    FR_MUET.add((LUN_W.isoformat(), DIM_W.isoformat()))
    TW_MUET.add((LUN_W.isoformat(), DIM_W.isoformat()))


def pause_off():
    PAUSE["on"] = False


def supprimer_vivant_ig():
    mid = pd._etat()["vivants"][IG]["message"]
    DISCORD.salons[f"{IG}-podium"].pop(mid)


def va2_muet():
    LIEN_MUET.add(("t2", LUN_W.isoformat(), DIM_W.isoformat()))


def va2_revenu():
    LIEN_MUET.clear()


CAL_FR_MUET = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 27, 20, 0), None),
               (m(2026, 9, 28, 0, 10), muet_fr_semaine), (m(2026, 9, 28, 9, 0), None),
               (m(2026, 9, 28, 23, 50), None), (m(2026, 9, 29, 0, 10), fr_revenu),
               (m(2026, 9, 29, 12, 0), None)]
CAL_PAUSE = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 28, 0, 10), None),
             (m(2026, 9, 28, 9, 0), pause_on), (m(2026, 9, 29, 0, 0), None),
             (m(2026, 9, 29, 12, 0), None), (m(2026, 9, 29, 18, 0), pause_off)]
CAL_REPOSTE = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 28, 0, 10), None),
               (m(2026, 9, 28, 9, 0), supprimer_vivant_ig), (m(2026, 9, 28, 9, 10), None)]
# un VA de Twitter sans relevé de tout le lundi matin : le podium mêlé de Va IG
# part, ses primes retenues, puis il est corrigé sur place une fois le VA relu
CAL_PRIMES = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 28, 0, 10), va2_muet),
              (m(2026, 9, 28, 9, 0), None), (m(2026, 9, 28, 10, 0), va2_revenu),
              (m(2026, 9, 28, 11, 10), None)]

try:
    # ================================================================ 1. --
    print("=" * 70)
    print("1. Le bouton sous les messages vivants de Va IG, jamais sur Twitter")
    print("=" * 70)
    check("Va IG porte la clé « bouton_maj », Twitter non",
          pd.SERVEURS[IG].get("bouton_maj") is True and "bouton_maj" not in pd.SERVEURS[TW])
    installer()
    a(m(2026, 9, 22, 12, 0))
    etat = pd._etat()
    mid_w = etat["vivants"][IG]["message"]
    pages = etat["subs"][IG]["messages"]
    post_w = [x for x in DISCORD.appels if x["m"] == "POST" and x["p"] == f"/channels/{IG}-podium/messages"]
    check("message vivant de la semaine (Va IG) : posté AVEC le bouton gris « Mettre à jour » 🔄 "
          "(custom_id « podium:maj »)",
          len(post_w) == 1 and post_w[0]["json"].get("components") == BOUTON
          and DISCORD.salons[f"{IG}-podium"][mid_w]["json"]["components"] == BOUTON,
          post_w[0]["json"].get("components") if post_w else None)
    check("pages vivantes de la quinzaine (Va IG) : chacune avec le bouton",
          pages and all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == BOUTON for p in pages))
    check("le bouton est bien celui voulu : une rangée, un bouton gris (style 2)",
          BOUTON[0]["components"][0]["style"] == 2 and len(BOUTON[0]["components"]) == 1
          and pd._boutons(IG, True) == {"components": BOUTON})
    tw_w = DISCORD.salons[f"{TW}-podium"][etat["vivants"][TW]["message"]]["json"]
    check("Twitter : message vivant sans « components » (rien de changé chez lui)",
          "components" not in tw_w and titre(tw_w) == "🔴 PODIUM SUBS — SEMAINE EN COURS")
    n0 = len(DISCORD.appels)
    a(m(2026, 9, 22, 14, 10))
    patchs = [x for x in DISCORD.appels[n0:] if x["m"] == "PATCH" and x["p"].startswith(f"/channels/{IG}-")]
    check("réédition deux heures plus tard : le bouton est renvoyé avec l'embed (semaine ET quinzaine)",
          len(patchs) == 1 + len(pages) and all(x["json"].get("components") == BOUTON for x in patchs),
          [(x["p"], x["json"].get("components")) for x in patchs])

    # ================================================================ 2. --
    print()
    print("=" * 70)
    print("2. Chaque message figé perd le bouton")
    print("=" * 70)
    derouler(CAL_NORMAL[:4])
    etat = pd._etat()
    mid_old = etat["vivants"][IG]["message"]
    js = DISCORD.salons[f"{IG}-podium"][mid_old]["json"]
    check("lundi 00h10, « semaine terminée » : le bouton s'en va",
          titre(js) == "🏁 PODIUM SUBS — SEMAINE TERMINÉE" and js.get("components") == [],
          (titre(js), js.get("components")))
    a(m(2026, 9, 28, 9, 0))
    etat = pd._etat()
    js = DISCORD.salons[f"{IG}-podium"][mid_old]["json"]
    check("lundi 9h, podium figé sur place : sans bouton",
          etat["postes"][f"{IG}:{LUN_W}"] == mid_old and titre(js) == "🏆 PODIUM SUBS DE LA SEMAINE"
          and js.get("components") == [], (titre(js), js.get("components")))
    neuf = etat["vivants"][IG]["message"]
    check("… et la semaine neuve repart avec le bouton, sous le podium",
          neuf != mid_old and DISCORD.salons[f"{IG}-podium"][neuf]["json"].get("components") == BOUTON)
    for moment, _x in CAL_NORMAL[5:]:
        a(moment)
    etat = pd._etat()
    figee = (etat.get("subs_figes") or {}).get(IG, {}).get("2026-09-16") or {}
    check("quinzaine finie : ses pages figées sans bouton, les neuves avec",
          figee.get("messages")
          and all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == [] for p in figee["messages"])
          and all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == BOUTON
                  for p in etat["subs"][IG]["messages"])
          and etat["subs"][IG]["saison"] == "2026-10-01", figee)
    controle_appels("vie normale")
    controle_salons("vie normale")

    for nom, cal in (("relevé FR raté le lundi, figée le mardi", CAL_FR_MUET),
                     ("pause GetMySocial, figée sans elle", CAL_PAUSE),
                     ("message supprimé à la main, podium reposté", CAL_REPOSTE),
                     ("VA US sans relevé, podium corrigé sur place", CAL_PRIMES)):
        derouler(cal)
        etat = pd._etat()
        if cal is CAL_FR_MUET or cal is CAL_PAUSE:
            fg = (etat.get("figes") or {}).get(IG, {}).get(LUN_W.isoformat()) or {}
            js = DISCORD.salons[f"{IG}-podium"].get(fg.get("message"), {}).get("json") or {}
            check(f"{nom} : semaine figée sans podium, et sans bouton",
                  fg.get("mode") == "sans_podium" and js.get("components") == []
                  and titre(js) == "🏆 PODIUM SUBS DE LA SEMAINE", (fg, js.get("components")))
        if cal is CAL_REPOSTE:
            rep = [x for x in DISCORD.appels if x["m"] == "POST" and x["p"] == f"/channels/{IG}-podium/messages"
                   and titre(x["json"]) == "🏆 PODIUM SUBS DE LA SEMAINE"]
            check(f"{nom} : le podium reposté n'a pas de bouton",
                  len(rep) == 1 and rep[0]["json"].get("components") == []
                  and rep[0]["json"].get("content", "").startswith("@everyone"), rep)
        if cal is CAL_PRIMES:
            mid_p = etat["postes"][f"{IG}:{LUN_W}"]
            corr = [x for x in DISCORD.appels if x["m"] == "PATCH" and x["p"].endswith("/" + mid_p)
                    and x["quand"] == m(2026, 9, 28, 11, 10)]
            check(f"{nom} : la correction de 11h10 a bien eu lieu, sans bouton",
                  len(corr) == 1 and corr[0]["json"].get("components") == []
                  and not (etat["figes"][IG][LUN_W.isoformat()].get("primes_attente")), corr)
        controle_appels(nom)
        controle_salons(nom)

    # La quinzaine finie qui ne se fige pas tout de suite (un VA illisible à
    # 00h10, pause GetMySocial, Discord qui refuse) : ses pages attendaient
    # jusqu'à 48 h AVEC le bouton, et un clic répondait « mise à jour
    # lancée » sans jamais les toucher. Le bouton doit partir dès la fin de
    # la quinzaine, comme celui de la semaine part avec « terminée ».
    def strips(gid, depuis=0):
        """Les éditions qui n'envoient QUE « components » (le bouton retiré)."""
        return [x for x in DISCORD.appels[depuis:] if x["m"] == "PATCH"
                and x["p"].startswith(f"/channels/{gid}-") and set(x["json"] or {}) == {"components"}]

    derouler(CAL_NORMAL)
    check("quinzaine figée tout de suite : aucune édition de plus pour retirer le bouton",
          not strips(IG) and not strips(TW), strips(IG)[:2])

    installer()
    a(m(2026, 9, 22, 12, 0))
    vieilles_ig = list(pd._etat()["subs"][IG]["messages"])
    vieilles_tw = list(pd._etat()["subs"][TW]["messages"])
    js_avant = {p: copy.deepcopy(DISCORD.salons[f"{IG}-subs"][p]["json"]) for p in vieilles_ig}
    # un VA FR (Va IG) et un VA de Twitter (donc aussi les VA US de Va IG)
    # sans relevé pour toute la quinzaine finie
    LIEN_MUET.add(("f1", "2026-09-16", "2026-09-30"))
    LIEN_MUET.add(("t1", "2026-09-16", "2026-09-30"))
    n0 = len(DISCORD.appels)
    journal(lambda: a(m(2026, 10, 1, 0, 10)))
    etat = pd._etat()
    attente = (etat.get("subs_a_figer") or {})
    check("quinzaine finie, VA illisible : elle attend son gel (Va IG ET Twitter)",
          "2026-09-16" in (attente.get(IG) or {}) and "2026-09-16" in (attente.get(TW) or {}), attente)
    check("… ses pages perdent le bouton tout de suite (00h10), embed intact",
          all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == []
              and DISCORD.salons[f"{IG}-subs"][p]["json"].get("embeds") == js_avant[p]["embeds"]
              for p in vieilles_ig),
          [(p, DISCORD.salons[f"{IG}-subs"][p]["json"].get("components")) for p in vieilles_ig])
    check("… par une édition qui n'envoie QUE « components » vide, une par page",
          sorted(x["p"].rsplit("/", 1)[-1] for x in strips(IG, n0)) == sorted(vieilles_ig)
          and all(x["json"] == {"components": []} for x in strips(IG, n0)), strips(IG, n0))
    neuves = etat["subs"][IG]["messages"]
    check("… et les pages neuves de la quinzaine du 1er ont le bouton",
          etat["subs"][IG]["saison"] == "2026-10-01" and neuves
          and all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == BOUTON for p in neuves))
    check("… Twitter : ses pages en attente ne reçoivent aucun « components »",
          not strips(TW) and all("components" not in DISCORD.salons[f"{TW}-subs"][p]["json"]
                                 for p in vieilles_tw))
    n1 = len(DISCORD.appels)
    t = m(2026, 10, 1, 0, 20)
    while t < m(2026, 10, 1, 6, 0):
        journal(lambda: a(t))
        t += dt.timedelta(minutes=10)
    check("… une seule fois : les tours suivants ne renvoient rien (la quinzaine attend toujours)",
          not strips(IG, n1) and "2026-09-16" in ((pd._etat().get("subs_a_figer") or {}).get(IG) or {}),
          strips(IG, n1)[:2])
    LIEN_MUET.clear()
    journal(lambda: a(m(2026, 10, 1, 6, 20)))
    etat = pd._etat()
    fg = ((etat.get("subs_figes") or {}).get(IG) or {}).get("2026-09-16") or {}
    check("… VA revenu : la quinzaine se fige complète, sans bouton, titre « terminée »",
          fg.get("complet") and all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == []
                                    and "(terminée)" in titre(DISCORD.salons[f"{IG}-subs"][p]["json"])
                                    for p in fg.get("messages") or ["?"]), fg)
    controle_appels("quinzaine figée en retard")
    controle_salons("quinzaine figée en retard")

    # Discord en panne au moment de retirer le bouton : réessayé au passage
    # suivant de la quinzaine, pas oublié
    installer()
    a(m(2026, 9, 22, 12, 0))
    vieilles_ig = list(pd._etat()["subs"][IG]["messages"])
    LIEN_MUET.add(("f1", "2026-09-16", "2026-09-30"))
    _vrai_api = pd._api
    pd._api = lambda methode, chemin, **kw: (
        (503, {"message": "panne"}) if methode == "PATCH" and set(kw.get("json") or {}) == {"components"}
        else _vrai_api(methode, chemin, **kw))
    journal(lambda: a(m(2026, 10, 1, 0, 10)))
    pd._api = _vrai_api
    check("Discord en panne à 00h10 : le bouton est encore là…",
          all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == BOUTON for p in vieilles_ig))
    n2 = len(DISCORD.appels)
    journal(lambda: a(m(2026, 10, 1, 2, 20)))
    check("… et retiré au passage suivant de la quinzaine",
          all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == [] for p in vieilles_ig)
          and len(strips(IG, n2)) == len(vieilles_ig), strips(IG, n2))
    # un manager clique entre-temps sur une page neuve : la quinzaine finie
    # garde son bouton retiré, la neuve est relevée
    CLOCK["now"] = m(2026, 10, 1, 2, 30)
    n3 = len(DISCORD.appels)
    r = pd.traiter(staff())
    journal(TACHES.pop())
    check("… un clic ensuite ne remet pas le bouton sur la quinzaine finie",
          contenu(r) == LANCEE
          and all(DISCORD.salons[f"{IG}-subs"][p]["json"].get("components") == [] for p in vieilles_ig)
          and not [x for x in DISCORD.appels[n3:] if x["p"].rsplit("/", 1)[-1] in vieilles_ig
                   and (x["json"] or {}).get("components")], contenu(r))

    # ================================================================ 3. --
    print()
    print("=" * 70)
    print("3. Le clic : qui, quand, et la réponse tout de suite")
    print("=" * 70)
    installer()
    a(m(2026, 9, 22, 12, 0))
    for nom, p in (("un autre bouton", clic(cid="quete:go:1")), ("le bouton Copier", clic(cid="copie")),
                   ("un PING", {"type": 1}), ("une commande", {"type": 2, "data": {"name": "podium:maj"}}),
                   ("une fenêtre de saisie", clic(typ=5)), ("rien du tout", None)):
        check(f"{nom} : None, le module suivant s'en occupe", pd.traiter(p) is None)
    r = pd.traiter(clic())
    check("un VA (ni rôle manager, ni permission) : « 🔒 Réservé au staff. », éphémère, rien lancé",
          ephemere(r) and contenu(r) == STAFF_SEUL and not TACHES and not pd._VERROU.locked(), r)
    r = pd.traiter(clic(roles=["123"], perms="1024"))
    check("un VA avec d'autres rôles : refusé aussi", contenu(r) == STAFF_SEUL and not TACHES)
    r = pd.traiter(clic(gid=TW, roles=[ROLE_MANAGER_TW]))
    check("Twitter (pas de bouton) : réponse neutre, rien lancé",
          ephemere(r) and contenu(r) == "ℹ️ Ce classement se met à jour tout seul, plusieurs fois par jour."
          and not TACHES and not pd._VERROU.locked(), r)
    r = pd.traiter(clic(gid="999", perms="8"))
    check("serveur inconnu, administrateur : réponse neutre", contenu(r) and "tout seul" in contenu(r)
          and not TACHES)

    vus = []

    def faux_rafraichir(gid, *a_, **kw):
        vus.append(("rafraichir", gid, kw, vd.serveur_courant(), pd._VERROU.locked(), pd._TIENT.get()))
        return "x"

    def faux_rafraichir_subs(gid, *a_, **kw):
        vus.append(("rafraichir_subs", gid, kw, vd.serveur_courant(), pd._VERROU.locked(), pd._TIENT.get()))
        return "x"

    pd.rafraichir, pd.rafraichir_subs = faux_rafraichir, faux_rafraichir_subs
    CLOCK["now"] = m(2026, 9, 22, 12, 30)
    r, log = journal(lambda: pd.traiter(staff()))
    check("staff (rôle manager de Va IG) : réponse éphémère immédiate, mot pour mot",
          ephemere(r) and contenu(r) == LANCEE and r["data"].get("allowed_mentions") == {"parse": []}, r)
    check("… le travail part en fond (rien n'est fait avant la réponse), verrou pris",
          len(TACHES) == 1 and not vus and pd._VERROU.locked())
    check("… et le journal dit qui a cliqué", "bouton 🔄 par 42" in log, log)
    TACHES.pop()()
    check("en fond : rafraichir PUIS rafraichir_subs, une fois chacun, sur Va IG",
          [(x[0], x[1]) for x in vus] == [("rafraichir", IG), ("rafraichir_subs", IG)], vus)
    check("… la quinzaine relevée hors rythme (forcer=True), la semaine sans rien de plus",
          vus and vus[0][2] == {} and vus[1][2] == {"forcer": True}, vus)
    check("… avec le serveur du clic (le bot de Va IG), même hors de toute requête",
          [x[3] for x in vus] == [IG, IG] and vd.serveur_courant() is None, vus)
    check("… sous le verrou, puis le verrou est rendu",
          all(x[4] and x[5] for x in vus) and not pd._VERROU.locked() and pd._TIENT.get() is False, vus)

    CLOCK["now"] = m(2026, 9, 22, 12, 31)
    r = pd.traiter(staff())
    check("second clic une minute plus tard : « ⏳ Déjà mis à jour il y a moins de 2 minutes. »",
          ephemere(r) and contenu(r) == TROP_TOT and not TACHES and not pd._VERROU.locked(), r)
    CLOCK["now"] = m(2026, 9, 22, 12, 31, 59)
    check("… encore à 1 min 59", contenu(pd.traiter(staff())) == TROP_TOT and not TACHES)
    CLOCK["now"] = m(2026, 9, 22, 12, 32)
    vus.clear()
    r = pd.traiter(clic(perms="8"))
    check("à 2 min pile, un administrateur (sans le rôle) : relancé", contenu(r) == LANCEE and len(TACHES) == 1)
    TACHES.pop()()
    check("… une fois de plus chacun", [x[0] for x in vus] == ["rafraichir", "rafraichir_subs"])
    CLOCK["now"] = m(2026, 9, 22, 12, 40)
    vus.clear()
    r = pd.traiter(clic(perms=str(0x10000000)))
    check("gestion des rôles (sans admin) : staff aussi", contenu(r) == LANCEE and len(TACHES) == 1)
    TACHES.pop()()

    CLOCK["now"] = m(2026, 9, 22, 13, 0)
    PAUSE["on"] = True
    r = pd.traiter(staff())
    check("pause GetMySocial : la mise à jour se fera au prochain passage, rien lancé",
          ephemere(r) and contenu(r) == "⏸️ GetMySocial est en pause : le podium et le classement se "
          "mettront à jour au prochain passage." and not TACHES and not pd._VERROU.locked(), r)
    PAUSE["on"] = False
    r = pd.traiter(staff())
    check("… la pause finie, un clic tout de suite passe (la pause n'a pas compté comme un clic)",
          contenu(r) == LANCEE and len(TACHES) == 1)
    TACHES.pop()()

    CLOCK["now"] = m(2026, 9, 22, 14, 0)
    pd._VERROU.acquire()
    try:
        r = pd.traiter(staff())
        check("un passage de la boucle en cours : « ⏳ Mise à jour déjà en cours. », rien lancé",
              ephemere(r) and contenu(r) == EN_COURS and not TACHES, r)
    finally:
        pd._VERROU.release()
    r = pd.traiter(staff())
    check("… le passage fini, le clic passe (« en cours » n'a pas compté comme un clic)",
          contenu(r) == LANCEE and len(TACHES) == 1)
    TACHES.pop()()

    CLOCK["now"] = m(2026, 9, 22, 15, 0)
    vd._EN_FOND = lambda f: (_ for _ in ()).throw(RuntimeError("can't start new thread"))
    r, log = journal(lambda: pd.traiter(staff()))
    check("le fil ne part pas : on le dit, le verrou est rendu, le clic suivant n'attend pas 2 min",
          contenu(r) and contenu(r).startswith("❌") and not pd._VERROU.locked()
          and IG not in pd._DERNIER_CLIC and "lancement impossible" in log, (r, log))
    vd._EN_FOND = TACHES.append
    pd.rafraichir, pd.rafraichir_subs = _SAUVE["rafraichir"], _SAUVE["rafraichir_subs"]

    # ================================================================ 4. --
    print()
    print("=" * 70)
    print("4. Le travail du clic, pour de vrai : hors rythme, mais dans les règles de gel")
    print("=" * 70)
    installer()
    a(m(2026, 9, 22, 12, 0))
    etat = pd._etat()
    mid_w, pages = etat["vivants"][IG]["message"], list(etat["subs"][IG]["messages"])
    CLOCK["now"] = m(2026, 9, 22, 12, 30)
    check("12h30 : la boucle n'aurait rien fait (Va IG relève toutes les deux heures)",
          not pd.a_rafraichir(IG) and not pd.a_rafraichir_subs(IG))
    n0, g0 = len(DISCORD.appels), len(GMS)
    r = pd.traiter(staff())
    TACHES.pop()()
    nouv = DISCORD.appels[n0:]
    check("le clic de 12h30 relève et réédite la semaine ET la quinzaine sur place, sans rien poster",
          [x["m"] for x in nouv] == ["PATCH"] * (1 + len(pages))
          and nouv[0]["p"].endswith("/" + mid_w)
          and "mis à jour 22/09 à 12h30" in pied(DISCORD.salons[f"{IG}-podium"][mid_w]["json"])
          and all("mis à jour 22/09 à 12h30" in pied(DISCORD.salons[f"{IG}-subs"][p]["json"]) for p in pages),
          [(x["m"], x["p"]) for x in nouv])
    fr = [x for x in GMS[g0:] if x["marche"] == "FR"]
    check("… avec un relevé FR neuf de la semaine et de la quinzaine (3 VA chacun)",
          sorted({(x["d0"], x["d1"]) for x in fr}) == [("2026-09-16", "2026-09-22"), ("2026-09-21", "2026-09-22")]
          and len(fr) == 6, [(x["d0"], x["d1"]) for x in fr])
    check("… le bouton toujours là, sur chaque message", all(
        x["json"].get("components") == BOUTON for x in nouv))
    etat = pd._etat()
    check("… et le rythme repart de là (vu = 12h30 : la boucle attend jusqu'à 14h30)",
          etat["vivants"][IG]["vu"] == m(2026, 9, 22, 12, 30).timestamp()
          and etat["subs"][IG]["vu"] == m(2026, 9, 22, 12, 30).timestamp())
    check("… Twitter n'a pas bougé", not [x for x in nouv if f"/{TW}-" in x["p"]])

    # le lundi à 3h : la semaine neuve attend le podium, clic ou pas
    derouler(CAL_NORMAL[:4])
    etat = pd._etat()
    mid_old = etat["vivants"][IG]["message"]
    CLOCK["now"] = m(2026, 9, 28, 3, 0)
    n0, g0 = len(DISCORD.appels), len(GMS)
    r = pd.traiter(staff())
    check("lundi 3h : le clic est accepté (la quinzaine, elle, est vivante)", contenu(r) == LANCEE)
    TACHES.pop()()
    etat = pd._etat()
    nouv_p = [x for x in DISCORD.appels[n0:] if x["p"].startswith(f"/channels/{IG}-podium")]
    check("… mais rien sur le salon du podium : ni semaine neuve, ni podium avant l'heure",
          not nouv_p and f"{IG}:{LUN_W}" not in (etat.get("postes") or {})
          and etat["vivants"][IG]["semaine"] == LUN_W.isoformat()
          and etat["vivants"][IG]["message"] == mid_old, nouv_p)
    js = DISCORD.salons[f"{IG}-podium"][mid_old]["json"]
    check("… le message de la semaine finie reste « terminée », sans bouton",
          titre(js) == "🏁 PODIUM SUBS — SEMAINE TERMINÉE" and js.get("components") == [])
    check("… aucun relevé de semaine (ni la finie, ni la neuve) : la porte du lundi tient",
          not [x for x in GMS[g0:] if x["marche"] == "FR" and x["d0"] in ("2026-09-21", "2026-09-28")],
          [(x["d0"], x["d1"]) for x in GMS[g0:]])
    a(m(2026, 9, 28, 9, 0))
    etat = pd._etat()
    check("… et à 9h, tout se passe comme sans clic : podium figé sur place, semaine neuve en dessous",
          etat["postes"][f"{IG}:{LUN_W}"] == mid_old and etat["vivants"][IG]["semaine"] == "2026-09-28"
          and len([x for x in DISCORD.appels if x["m"] == "POST" and x["p"] == f"/channels/{IG}-podium/messages"
                   and (x["json"] or {}).get("embeds")]) == 2)
    controle_appels("clic du lundi 3h")
    controle_salons("clic du lundi 3h")

    # ================================================================ 5. --
    print()
    print("=" * 70)
    print("5. Un seul passage à la fois : rien n'est jamais posté deux fois")
    print("=" * 70)
    installer()
    CLOCK["now"] = m(2026, 9, 22, 12, 0)
    pd._VERROU.acquire()
    try:
        _r, log = journal(lambda: a(m(2026, 9, 22, 12, 0)))
    finally:
        pd._VERROU.release()
    check("la boucle pendant le travail d'un clic : chaque appel saute son tour, au journal",
          not DISCORD.appels and not GMS
          and all(f"{f} {g} : une mise à jour tourne déjà" in log
                  for f in ("rafraichir", "rafraichir_subs") for g in GIDS)
          and "rafraichir_bonus " + TW in log and "passage sauté, repris au prochain tour" in log, log[-600:])
    CLOCK["now"] = m(2026, 9, 28, 9, 0)
    pd._VERROU.acquire()
    try:
        _r, log = journal(lambda: pd.poster_podium(IG))
    finally:
        pd._VERROU.release()
    check("… le podium du lundi aussi (poster_podium)", _r == "" and not DISCORD.appels
          and f"poster_podium {IG} : une mise à jour tourne déjà" in log, log)
    a(m(2026, 9, 22, 12, 10))
    check("… et le tour suivant fait ce qui avait été sauté",
          pd._etat().get("vivants", {}).get(IG, {}).get("message")
          and pd._etat().get("subs", {}).get(IG, {}).get("messages"))

    # de vrais fils : le clic tient le verrou, la boucle passe au même moment
    installer()
    vd._EN_FOND = _SAUVE_VD                 # le vrai _en_fond : un fil, le contexte emporté
    CLOCK["now"] = m(2026, 9, 22, 12, 0)
    BLOCAGE["actif"] = True
    with vd.sur_serveur(IG):                 # comme la route /discord/interactions
        r1 = pd.traiter(staff())
    entre = BLOCAGE["entre"].wait(10)
    check("vrai fil : le clic répond tout de suite, son travail est en cours (dans son premier relevé)",
          contenu(r1) == LANCEE and entre and pd._VERROU.locked())
    _r, log = journal(lambda: a(m(2026, 9, 22, 12, 0), gids=(IG,)))
    principal = [x for x in DISCORD.appels if x["fil"] == threading.main_thread().name]
    check("… la boucle, au même instant, ne touche à rien (ni Discord, ni GetMySocial) et le dit",
          not principal and not [x for x in GMS if x["fil"] == threading.main_thread().name]
          and "passage sauté" in log, (principal, log[-300:]))
    r2 = pd.traiter(clic(perms="8", uid="43"))
    check("… un second clic : « ⏳ Mise à jour déjà en cours. »", contenu(r2) == EN_COURS, r2)
    BLOCAGE["libre"].set()
    fini = pd._VERROU.acquire(timeout=10)
    if fini:
        pd._VERROU.release()
    BLOCAGE["actif"] = False
    etat = pd._etat()
    posts_w = [x for x in DISCORD.appels if x["m"] == "POST" and x["p"] == f"/channels/{IG}-podium/messages"]
    posts_s = [x for x in DISCORD.appels if x["m"] == "POST" and x["p"] == f"/channels/{IG}-subs/messages"]
    check("… le travail fini : UN message de la semaine, UNE série de pages, gardés dans l'état",
          fini and len(posts_w) == 1 and len(posts_s) == len(etat["subs"][IG]["messages"]) >= 1
          and etat["vivants"][IG]["message"] == f"{IG}-podium:1", (len(posts_w), len(posts_s)))
    check("… posté depuis le fil du clic, avec le serveur du clic (le bot de Va IG)",
          all(x["fil"] != threading.main_thread().name and x["srv"] == IG for x in posts_w + posts_s),
          [(x["fil"], x["srv"]) for x in posts_w + posts_s])
    a(m(2026, 9, 22, 12, 10), gids=(IG,))
    posts_w2 = [x for x in DISCORD.appels if x["m"] == "POST" and x["p"] == f"/channels/{IG}-podium/messages"]
    check("… et la boucle suivante ne reposte rien (le clic a déjà tout fait)", len(posts_w2) == 1)

    # l'inverse : la boucle dans un vrai fil, le clic au milieu
    installer()
    vd._EN_FOND = _SAUVE_VD
    CLOCK["now"] = m(2026, 9, 22, 12, 0)
    BLOCAGE["actif"] = True
    boucle = threading.Thread(target=lambda: a(m(2026, 9, 22, 12, 0), gids=(IG,)), name="boucle-podium")
    boucle.start()
    BLOCAGE["entre"].wait(10)
    r = pd.traiter(staff())
    check("vrai fil : la boucle tourne, le clic répond « déjà en cours » et ne lance rien",
          contenu(r) == EN_COURS and IG not in pd._DERNIER_CLIC, r)
    BLOCAGE["libre"].set()
    boucle.join(10)
    BLOCAGE["actif"] = False
    posts_w = [x for x in DISCORD.appels if x["m"] == "POST" and x["p"] == f"/channels/{IG}-podium/messages"]
    check("… la boucle finie : un seul message de la semaine, le verrou rendu",
          not boucle.is_alive() and len(posts_w) == 1 and not pd._VERROU.locked())
    vd._EN_FOND = TACHES.append

    # ================================================================ 6. --
    print()
    print("=" * 70)
    print("6. Retirer le bouton, la clé, et la route du site")
    print("=" * 70)
    try:
        pd.SERVEURS[IG]["bouton_maj"] = False
        check("« bouton_maj » à False : « components » vide partout (le bouton déjà posé s'en va)",
              pd._boutons(IG, True) == {"components": []} and pd._boutons(IG, False) == {"components": []})
        installer()
        r = pd.traiter(staff())
        check("… et le clic sur un bouton resté : réponse neutre, rien lancé",
              contenu(r) and "tout seul" in contenu(r) and not TACHES)
        pd.SERVEURS[IG].pop("bouton_maj")
        check("clé retirée : rien n'est envoyé (comme Twitter)",
              pd._boutons(IG, True) == {} and pd._boutons(IG, False) == {}
              and pd._boutons(TW, True) == {} and pd._boutons(None, True) == {})
    finally:
        pd.SERVEURS[IG].clear()
        pd.SERVEURS[IG].update(copy.deepcopy(_SAUVE_IG))
    src = (BOT / "podium_discord.py").read_text(encoding="utf-8")
    check("la clé n'est lue qu'à deux endroits (_boutons, traiter)",
          src.count('pf["bouton_maj"]') == 1 and src.count('.get("bouton_maj")') == 1
          and src.count('"bouton_maj" not in pf') == 1)
    _i = src.find('"bouton_maj": True')
    check("la clé dit pourquoi, et comment la retirer",
          _i > 0 and "reload a la main" in src[_i - 900:_i] and "POUR LE" in src[_i - 900:_i])

    # la route : le vrai _discord_repondre de web_upload, tiré du source et
    # exécuté tel quel (quêtes, tickets, copie, annonces, podium, vérification)
    _src_w = (BOT / "web_upload.py").read_text(encoding="utf-8")
    _i = _src_w.find("    def _discord_repondre(charge):")
    _j = _src_w.find("\n    @app.route", _i)
    corps_route = _src_w[_i:_j]
    check("web_upload : la route passe le clic à podium_discord.traiter, sous try/except, avec jsonify, "
          "après /annonce et avant la vérification",
          _i > 0 and "import podium_discord as _pdm" in corps_route
          and "_rep_pdm = _pdm.traiter(charge)" in corps_route
          and "return jsonify(_rep_pdm)" in corps_route
          and corps_route.find("_an.traiter(charge)") < corps_route.find("_pdm.traiter(charge)")
          < corps_route.find("return jsonify(_vd.traiter_interaction(charge))")
          and re.search(r"try:\n\s+import podium_discord as _pdm\n\s+_rep_pdm = _pdm\.traiter\(charge\)\n"
                        r"\s+if _rep_pdm is not None:\n\s+return jsonify\(_rep_pdm\)\n"
                        r"\s+except Exception as _e_pdm:", corps_route), corps_route[-900:])
    import flask
    espace = {}
    exec(textwrap.dedent(corps_route), espace)
    repondre = espace["_discord_repondre"]
    installer()
    sauve_ti = vd.traiter_interaction
    vd.traiter_interaction = lambda p: {"type": 4, "data": {"content": "verif"}}
    try:
        with flask.Flask("essai").app_context():
            rr = repondre(staff()).get_json()
            r_va = repondre(clic()).get_json()
            r_autre = repondre(clic(cid="rien:du:tout")).get_json()
    finally:
        vd.traiter_interaction = sauve_ti
    check("route : le clic du staff arrive au podium (réponse éphémère, travail en fond)",
          contenu(rr) == LANCEE and ephemere(rr) and len(TACHES) == 1, rr)
    TACHES.pop()()
    check("route : un VA reçoit « réservé au staff »", contenu(r_va) == STAFF_SEUL, r_va)
    check("route : un autre bouton passe à la vérification, comme avant", contenu(r_autre) == "verif", r_autre)
    _src_d = _src_w[_src_w.find("def _start_podium_semaine_daemon"):]
    _src_d = _src_d[:_src_d.find("\ndef ", 10)]
    check("la boucle n'a pas changé d'ordre ni de gestes (le verrou est dans podium_discord)",
          all(x in _src_d for x in ("_p.poster_podium(gid)", "_p.rafraichir(gid)", "_p.rafraichir_subs(gid)"))
          and "_VERROU" not in _src_d)
    check("le verrou entoure les fonctions qui écrivent podium.json",
          all(re.search(r"@_exclusif[^\n]*\ndef " + f + r"\(", src)
              for f in ("poster_podium", "rafraichir", "rafraichir_subs", "rafraichir_bonus")))
    check("aucun verrou laissé pris, aucun contexte de clic qui traîne",
          not pd._VERROU.locked() and pd._TIENT.get() is False)

    # ---- format d'affichage : un message dans l'ancien format est refait tout de suite
    print("\nFormat d'affichage (FORMAT_AFFICHAGE)")
    _etat_vrai, _pause_vrai, _maint = pd._etat, pd._pause_gms, pd.time.time
    try:
        _lundi = pd.semaine_en_cours()[0].isoformat()
        _saison = pd.saison_en_cours()[0].isoformat()
        _t = 10_000_000.0
        def _etat_avec(fmt_v, fmt_s):
            return {"vivants": {IG: {"semaine": _lundi, "message": "1", "vu": _t, **({"format": fmt_v} if fmt_v else {})}},
                    "subs": {IG: {"saison": _saison, "messages": ["2"], "vu": _t, **({"format": fmt_s} if fmt_s else {})}}}
        pd._pause_gms = lambda: False
        pd.time.time = lambda: _t + 60
        pd._etat = lambda: _etat_avec(None, None)
        check("message vivant sans format (ecrit avant ce changement) : refait au passage suivant",
              pd.a_rafraichir(IG, _t + 60) and pd.a_rafraichir_subs(IG, _t + 60))
        pd._etat = lambda: _etat_avec("ancien", "ancien")
        check("format different : refait tout de suite, sans attendre les deux heures",
              pd.a_rafraichir(IG, _t + 60) and pd.a_rafraichir_subs(IG, _t + 60))
        pd._etat = lambda: _etat_avec(pd.FORMAT_AFFICHAGE, pd.FORMAT_AFFICHAGE)
        check("format a jour, une minute apres : rien (la cadence reprend)",
              not pd.a_rafraichir(IG, _t + 60) and not pd.a_rafraichir_subs(IG, _t + 60))
        check("chaque ecriture du message vivant note le format (POST, PATCH, quinzaine)",
              src.count('"format": FORMAT_AFFICHAGE') >= 2 and 'garde["format"] = FORMAT_AFFICHAGE' in src)
    finally:
        pd._etat, pd._pause_gms, pd.time.time = _etat_vrai, _pause_vrai, _maint

except Exception as _e:
    import traceback
    check("bouton 🔄 : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-1500:])
finally:
    BLOCAGE["libre"].set()
    for _k, _v in _SAUVE.items():
        setattr(pd, _k, _v)
    pd.SERVEURS[IG].clear()
    pd.SERVEURS[IG].update(_SAUVE_IG)
    pd._RELEVES.clear()
    pd._DERNIER_CLIC.clear()
    vd._EN_FOND = _SAUVE_VD
    if pd._VERROU.locked():
        try:
            pd._VERROU.release()
        except RuntimeError:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for _l in FAILS:
        print("  - " + _l)
sys.exit(1 if FAILS else 0)
