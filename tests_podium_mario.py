# -*- coding: utf-8 -*-
"""tests_podium_mario.py — le thème Mario du podium et du classement subs de Va IG.

Demande du propriétaire (03/10/2026) : « tu penses y'a moyen de faire un theme
Mario pour tout ca », puis « vas-y » à la proposition : Grand Prix des subs
pour la semaine, Championnat des subs pour la quinzaine, les têtes de Mario,
Luigi et Peach au top 3, 🪙 pour les primes, une vignette, « Relancer la
course » sur le bouton. Les bots s'appellent déjà Mario, Luigi, Peach…

Ce qui est vérifié :
  - la clé « theme » : sur Va IG seulement, commentée, et le seul interrupteur ;
  - chaque état du message de la semaine (vivant, « terminée », final) et de
    la quinzaine (vivante, figée) : titre, couleur, vignette, marqueurs du top
    3 (têtes si le serveur les a, 👑 ⭐ 🍄 sinon, jamais un mélange), 🪙 aux
    primés selon la même règle qu'avant (au moins un sub), 🟢 aux suivants, le
    bloc des primes ; et tout le reste MOT POUR MOT comme sans thème
    (réclamation, numéro de VA, avertissements, pied) ;
  - le bouton « Relancer la course » (🔄, podium:maj) sous les messages vivants ;
  - les têtes : trouvées dans la liste du serveur, créées si absentes (les PNG
    du dépôt en data URI), refaites si supprimées à la main ; 403 (« Gérer les
    expressions » manquante) : repli, UNE ligne au journal, un essai par jour
    — pas de rafale ; liste illisible : rien de créé (pas de doublon) ; une
    exception ne casse jamais un podium ;
  - elles sont posées par les passages qui parlent déjà à Discord (rafraichir,
    rafraichir_subs, poster_podium), jamais par un rendu : les rendus ne font
    aucun appel réseau et n'écrivent rien ;
  - un message FIGÉ (podium de 9h, semaine figée sans podium, podium corrigé,
    quinzaine figée) relit la liste juste avant son rendu : une tête
    supprimée à la main depuis la vérification du jour n'y reste jamais pour
    toujours ; liste illisible à ce moment-là : 👑 ⭐ 🍄 sur ce message ;
  - la longueur : des têtes, puis le 🟢, qui feraient couper le podium cèdent
    la place ; jamais coupé là où le message sans thème tient ; la quinzaine
    compte leur vraie longueur pour paginer ;
  - la vignette porte la version de son fichier (?v=) : un 404 gardé par le
    cache de Cloudflare avant la mise en ligne ne la masque pas ;
  - FORMAT_AFFICHAGE changé : les messages vivants sont refaits tout de suite ;
  - Twitter, et Va IG sans la clé : chaque appel à Discord est celui du code
    d'avant le thème (REF, lu dans git), à l'octet près.

Faux Discord (emojis compris), faux GetMySocial (le VRAI classement tourne
dessus), horloge simulée, dossier temporaire : aucun appel réseau, rien n'est
écrit dans data/. Lancement : python tests_podium_mario.py

REF est le commit d'avant le thème. Un autre changement du podium d'ici là
déplace REF sur le commit qui le précède (comme tests_podium_us.py).
"""
from __future__ import annotations

import base64
import contextlib
import copy
import datetime as dt
import hashlib
import importlib.util
import inspect
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252 : jamais d'UnicodeEncodeError
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

REF = "028652a"                        # le code d'avant le thème
CLOCK = {"now": dt.datetime(2026, 9, 22, 12, 0)}
J = dt.timedelta(days=1)

# ------------------------------------------------ faux suivi_va (la paie) --
_PRIMES = []
_faux_suivi = types.ModuleType("suivi_va")
_faux_suivi.annoncer_primes = lambda gid, cl, debut, fin: (
    _PRIMES.append((str(gid), debut.isoformat())) or {"dits": [], "sans_adresse": [], "inconnus": []})
sys.modules["suivi_va"] = _faux_suivi

# ------------------------------------------------- faux GetMySocial --------
# Les mêmes liens que tests_podium_maj.py : deux espaces Twitter, un espace FR.
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

GMS = []
FR_MUET, TW_MUET = set(), set()
LIEN_MUET = set()
PAUSE = {"on": False}


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
    GMS.append({"ids": tuple(ids), "d0": d0, "d1": d1, "quand": CLOCK["now"], "marche": marche})
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
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:500]}]" if detail and not cond else ""))


TW, IG = pd.TWITTER_ID, pd.VA_IG_ID
GIDS = (TW, IG)
NOMS = ["kart_mario", "kart_luigi", "kart_peach"]
REPLI = ["👑", "⭐", "🍄"]
IDS = {"kart_mario": "1424242424242424101", "kart_luigi": "1424242424242424102",
       "kart_peach": "1424242424242424103"}
TETES = [f"<:{n}:{IDS[n]}>" for n in NOMS]
T_EN_COURS = "🏁 GRAND PRIX DES SUBS — COURSE EN COURS 🍄"
T_TERMINE = "🏁 GRAND PRIX DES SUBS — COURSE TERMINÉE"
T_FINAL = "🏆 GRAND PRIX DES SUBS — PODIUM DE LA SEMAINE"
L_EN_COURS = "🔴 _La course continue… rien n'est joué !_"
L_TERMINE = "🏁 _Ligne d'arrivée franchie ! Le podium officiel arrive ce lundi à 9h, sur ce message._"
L_FINAL = "🔒 _Course terminée : le podium ne bougera plus._"
BLOC_PRIMES = "🏆 **Le podium de la course gagne des pièces :**"
FIN_PODIUM = "🔢 _Ton numéro de VA ne change jamais : c'est le même chaque semaine._"


def _version(rel):
    """Les 8 premiers caractères du md5 de static/<rel> : la version que
    l'adresse de la vignette doit porter."""
    return hashlib.md5((BOT / "static" / rel).read_bytes()).hexdigest()[:8]


# Versionnées : sans « ?v= », un 404 servi avant la mise en ligne restait
# sept jours dans le cache de Cloudflare (relu en revue, voir section 1)
VIGNETTE_PODIUM = f"https://youl4b.com/static/podium/grand_prix.png?v={_version('podium/grand_prix.png')}"
VIGNETTE_SUBS = f"https://youl4b.com/static/podium/championnat.png?v={_version('podium/championnat.png')}"
ROUGE, OR, BLEU = 0xE52521, 0xF8C51C, 0x049CD8
BOUTON = [{"type": 1, "components": [{"type": 2, "style": 2, "label": "Relancer la course",
                                      "emoji": {"name": "🔄"}, "custom_id": "podium:maj"}]}]


# ------------------------------------------------------- le faux Discord --
class FauxDiscord:
    """Comme celui de tests_podium_maj.py (une édition ne remplace que ce
    qu'elle envoie), plus les emojis du serveur : la liste, la création, et
    les refus qu'on veut lui faire dire."""

    def __init__(self):
        self.salons, self.appels, self.n = {}, [], {}
        self.emojis = {}                 # gid -> [{id, name, available}]
        self.refus_liste = None          # (code, corps) rendu par GET …/emojis
        self.refus_creation = None       # (code, corps) rendu par POST …/emojis
        self.exception = False           # l'appel lève (réseau tombé)
        self.n_emoji = 1424242424242424200

    def api(self, methode, chemin, **kw):
        js = copy.deepcopy(kw.get("json"))
        self.appels.append({"m": methode, "p": chemin, "json": js, "quand": CLOCK["now"]})
        parts = chemin.strip("/").split("/")
        if parts[0] == "guilds" and len(parts) == 3 and parts[2] == "emojis":
            if self.exception:
                raise ConnectionError("réseau tombé")
            gid = parts[1]
            if methode == "GET":
                return self.refus_liste or (200, copy.deepcopy(self.emojis.get(gid, [])))
            if methode == "POST":
                if self.refus_creation:
                    return self.refus_creation
                self.n_emoji += 1
                e = {"id": str(self.n_emoji), "name": js["name"], "available": True}
                self.emojis.setdefault(gid, []).append(e)
                return 201, dict(e, roles=[], require_colons=True, managed=False, animated=False)
            return 405, {}
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
TMP = pathlib.Path(tempfile.mkdtemp(prefix="podium_mario_test_"))
_ATTRS = ("DATA_DIR", "ETAT_FICHIER", "CONFIG_FICHIER", "NUMEROS_FICHIER", "LIENS_CACHE",
          "ALLTIME_FICHIER", "_maintenant", "_aujourdhui", "_api", "_salon", "_pause_gms", "time")
_SAUVE = {k: getattr(pd, k) for k in _ATTRS}
_SAUVE_IG = copy.deepcopy(pd.SERVEURS[IG])
_SAUVE_VD = vd._EN_FOND
_NB_BAC = [0]
TACHES = []


def installer(mod=None):
    """Un bac neuf : dossier, horloge, Discord, pause, mémoire."""
    global DISCORD
    mod = mod or pd
    _NB_BAC[0] += 1
    d = TMP / f"bac{_NB_BAC[0]}"
    d.mkdir()
    safe_json.write_text(d / "podium_numeros.json", json.dumps(NUMEROS_TW))
    mod.DATA_DIR = d
    mod.ETAT_FICHIER = d / "podium.json"
    mod.CONFIG_FICHIER = d / "podium_config.json"
    mod.NUMEROS_FICHIER = d / "podium_numeros.json"
    mod.LIENS_CACHE = d / "gmsdash_links.json"
    mod.ALLTIME_FICHIER = d / "podium_alltime.json"
    mod._maintenant = lambda: CLOCK["now"]
    mod._aujourdhui = lambda: CLOCK["now"].date()
    mod.time = types.SimpleNamespace(time=lambda: CLOCK["now"].timestamp(), sleep=lambda s: None)
    mod._pause_gms = lambda: PAUSE["on"]
    mod._salon = lambda gid, voulu="": (f"{gid}-subs" if "subs" in (voulu or "")
                                        else f"{gid}-bonus" if "bonus" in (voulu or "")
                                        else f"{gid}-podium")
    DISCORD = FauxDiscord()
    mod._api = lambda methode, chemin, **kw: DISCORD.api(methode, chemin, **kw)
    mod._RELEVES.clear()
    mod._DERNIER_CLIC.clear()
    GMS.clear()
    _PRIMES.clear()
    FR_MUET.clear()
    TW_MUET.clear()
    LIEN_MUET.clear()
    PAUSE["on"] = False
    TACHES.clear()
    vd._EN_FOND = TACHES.append
    return d


def a(moment, gids=GIDS, mod=None):
    """Un tour de la vraie boucle (web_upload._start_podium_semaine_daemon)."""
    mod = mod or pd
    CLOCK["now"] = moment
    for gid in gids:
        with vd.sur_serveur(gid):
            if mod.a_poster():
                mod.poster_podium(gid)
            if mod.a_rafraichir(gid):
                mod.rafraichir(gid)
            if mod.a_rafraichir_subs(gid):
                mod.rafraichir_subs(gid)
            if mod.a_rafraichir_bonus(gid):
                mod.rafraichir_bonus(gid)


def derouler(calendrier, mod=None):
    installer(mod)
    for moment, action in calendrier:
        if action:
            action()
        a(moment, mod=mod)
    return [(x["m"], x["p"], x["json"]) for x in DISCORD.appels]


def m(*x):
    return dt.datetime(*x)


def journal(f):
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        r = f()
    return r, tampon.getvalue()


def emb(js):
    if isinstance(js, dict) and "description" in js and "embeds" not in js:
        return js
    return ((js or {}).get("embeds") or [{}])[0]


def titre(js):
    return emb(js).get("title", "")


def desc(js):
    return emb(js).get("description", "")


def pied(js):
    return (emb(js).get("footer") or {}).get("text", "")


def appels_emojis(gid=None, depuis=0):
    return [x for x in DISCORD.appels[depuis:] if "/emojis" in x["p"]
            and (gid is None or x["p"].startswith(f"/guilds/{gid}/"))]


def lignes_emoji(log):
    return [l for l in log.splitlines() if "têtes" in l]


def poser_cache(ids=None, gid=IG):
    safe_json.write_text(pd._fichier_emojis(), json.dumps({gid: dict(ids if ids is not None else IDS)}))


def lire_cache():
    return safe_json.load(pd._fichier_emojis(), default={}) or {}


def effacer_cache():
    """Le cache ET sa copie .prev : safe_json relit la copie quand le fichier
    manque ou est illisible (c'est voulu : un cache tronqué ne perd pas les
    têtes), un test « sans têtes » doit donc retirer les deux."""
    f = pd._fichier_emojis()
    for x in (f, f.with_suffix(f.suffix + ".prev")):
        x.unlink(missing_ok=True)


def L(va, clics, numero=1, model=""):
    return {"va": va, "numero": numero, "clics": clics, "liens": 1, "spam": False, "model": model}


def sans_theme(f):
    """f() rendu avec Va IG SANS la clé « theme », la clé remise ensuite."""
    th = pd.SERVEURS[IG].pop("theme", None)
    try:
        return f()
    finally:
        if th is not None:
            pd.SERVEURS[IG]["theme"] = th


def vers_avant(texte, marqueurs):
    """Un texte du thème ramené aux mots d'avant : ce qui reste différent du
    rendu sans thème n'est PAS de l'habillage."""
    for ancien, neuf in ((L_EN_COURS, "🔴 _Mis à jour tout seul, plusieurs fois par jour. Rien n'est joué._"),
                         (L_TERMINE, "🏁 _Semaine terminée. Le podium officiel arrive ce lundi à 9h, sur ce message._"),
                         (L_FINAL, "🔒 _Semaine terminée : classement arrêté, il ne bougera plus._"),
                         (BLOC_PRIMES, "🎁 **Les 3 meilleurs de la semaine touchent une prime :**"),
                         ("🪙", "💰")):
        texte = texte.replace(ancien, neuf)
    for mq, med in zip(marqueurs, ["🥇", "🥈", "🥉"]):
        texte = texte.replace(mq, med)
    return re.sub(r"^(\d+)\. 🟢 ", r"\1. ", texte, flags=re.M)


def charger_ancien():
    r = subprocess.run(["git", "-C", str(BOT), "show", f"{REF}:podium_discord.py"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0 or "def classement(" not in r.stdout or "THEMES" in r.stdout:
        return None
    f = TMP / "podium_avant_theme.py"
    f.write_text(r.stdout, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("podium_avant_theme", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# les données réalistes : Jessye VA 8 (US) devant, une VA FR 2e, des VA des
# deux côtés ensuite, une VA FR à zéro (jamais primée)
LUN_W, DIM_W = dt.date(2026, 9, 21), dt.date(2026, 9, 27)
CL_FR = {"lignes": [L("Amelia VA 3", 212, 3, "amelia"), L("Lola VA 2", 151, 2, "lola"),
                    L("Amelia VA 1", 0, 1, "amelia")],
         "illisibles": [], "frais": True, "sans_numero": []}
US = {"lignes": [L("VA 8", 241, 8), L("VA 12", 193, 12), L("VA 3", 120, 3), L("VA 5", 33, 5)],
      "illisibles": [], "frais": True}
TOP = [("Jessye VA 8", 241, 10), ("Amelia VA 3", 212, 5), ("Jessye VA 12", 193, 3)]
SUITE = ["4. 🟢 Lola VA 2 — **151** subs", "5. 🟢 Jessye VA 3 — **120** subs",
         "6. 🟢 Jessye VA 5 — **33** subs", "7. 🟢 Amelia VA 1 — **0** subs"]

CAL_NORMAL = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 22, 14, 10), None),
              (m(2026, 9, 27, 20, 0), None), (m(2026, 9, 28, 0, 10), None),
              (m(2026, 9, 28, 9, 0), None), (m(2026, 9, 28, 9, 10), None),
              (m(2026, 9, 29, 10, 0), None), (m(2026, 9, 30, 23, 50), None),
              (m(2026, 10, 1, 0, 10), None), (m(2026, 10, 1, 12, 0), None)]


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
    for salon, ms in DISCORD.salons.items():
        if salon == f"{IG}-podium":
            ms.pop(sorted(ms, key=lambda k: ms[k]["rang"])[-1], None)


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
CAL_PRIMES = [(m(2026, 9, 22, 12, 0), None), (m(2026, 9, 28, 0, 10), va2_muet),
              (m(2026, 9, 28, 9, 0), None), (m(2026, 9, 28, 10, 0), va2_revenu),
              (m(2026, 9, 28, 11, 10), None)]
CALS = (("vie normale", CAL_NORMAL), ("relevé FR raté le lundi", CAL_FR_MUET),
        ("pause GetMySocial", CAL_PAUSE), ("message supprimé, podium reposté", CAL_REPOSTE),
        ("VA US sans relevé, podium corrigé", CAL_PRIMES))

try:
    ancien = charger_ancien()
    check(f"le code d'avant le thème ({REF}) se lit dans git", ancien is not None)

    # ================================================================ 1. --
    print("=" * 70)
    print("1. La clé, les images, le format")
    print("=" * 70)
    src = (BOT / "podium_discord.py").read_text(encoding="utf-8")
    check("Va IG porte « theme »: « mario », Twitter non",
          pd.SERVEURS[IG].get("theme") == "mario" and "theme" not in pd.SERVEURS[TW])
    _i = src.find('"theme": "mario"')
    check("la clé cite le propriétaire et dit comment la retirer",
          _i > 0 and "theme Mario pour tout ca" in src[_i - 900:_i] and "vas-y" in src[_i - 900:_i]
          and "POUR LE RETIRER" in src[_i - 900:_i])
    check("la clé n'est lue qu'à un seul endroit (_theme)",
          src.count('.get("theme")') == 1 and "def _theme(" in src)
    for n in NOMS:
        f = BOT / "emojis" / f"{n}.png"
        octets = f.read_bytes() if f.exists() else b""
        check(f"emojis/{n}.png : un PNG de moins de 256 Ko (limite Discord)",
              octets[:8] == b"\x89PNG\r\n\x1a\n" and 0 < len(octets) <= 256 * 1024, len(octets))
    for n in ("grand_prix", "championnat"):
        f = BOT / "static" / "podium" / f"{n}.png"
        check(f"static/podium/{n}.png : un PNG", f.exists() and f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n")
    ign = subprocess.run(["git", "-C", str(BOT), "check-ignore", "emojis/kart_mario.png",
                          "static/podium/grand_prix.png", "static/podium/championnat.png"],
                         capture_output=True, text=True)
    check("les images ne sont pas ignorées par git (le VPS les reçoit au déploiement)",
          ign.returncode == 1 and not ign.stdout.strip(), ign.stdout)
    # Flask sert le dossier static/ du dépôt à /static/ : c'est là que Discord
    # va chercher la vignette (youl4b.com/static/podium/…)
    import flask
    _src_w = (BOT / "web_upload.py").read_text(encoding="utf-8")
    check("web_upload : l'application Flask garde son dossier static/ par défaut",
          "app = Flask(__name__)" in _src_w and "static_folder" not in _src_w)
    with flask.Flask("web_upload", root_path=str(BOT)).test_client() as _cli:
        for n in ("grand_prix", "championnat"):
            _r = _cli.get(f"/static/podium/{n}.png")
            check(f"/static/podium/{n}.png est servi tel quel (200, image/png)",
                  _r.status_code == 200 and _r.mimetype == "image/png"
                  and _r.data == (BOT / "static" / "podium" / f"{n}.png").read_bytes(), _r.status_code)
            _r.close()
    check("la vignette est bâtie sur verif_discord.SITE",
          vd.SITE == "https://youl4b.com"
          and pd._vignette(pd.THEMES["mario"], "podium")["url"].startswith(
              "https://youl4b.com/static/podium/grand_prix.png")
          and pd._vignette(pd.THEMES["mario"], "subs")["url"].startswith(
              "https://youl4b.com/static/podium/championnat.png"))
    # Le site marque toute réponse sous /static/, 404 compris, « public,
    # max-age=604800, immutable » (web_upload._perf_after_request), et
    # Cloudflare l'applique : une adresse demandée AVANT la mise en ligne
    # garde son 404 sept jours (vu le 03/10 : HIT sur grand_prix.png). La
    # version du fichier dans l'adresse en fait une autre adresse — la clé de
    # cache de Cloudflare comprend la requête (vérifié : ?v= neuf → MISS) —
    # et une image changée plus tard sous le même nom se voit aussitôt.
    check("vignettes versionnées : « ?v= » + 8 caractères du md5 du fichier servi",
          pd._vignette(pd.THEMES["mario"], "podium") == {"url": VIGNETTE_PODIUM}
          and pd._vignette(pd.THEMES["mario"], "subs") == {"url": VIGNETTE_SUBS}
          and re.fullmatch(r".+\.png\?v=[0-9a-f]{8}", VIGNETTE_PODIUM),
          (pd._vignette(pd.THEMES["mario"], "podium"), VIGNETTE_PODIUM))
    with flask.Flask("web_upload", root_path=str(BOT)).test_client() as _cli:
        for _u in (VIGNETTE_PODIUM, VIGNETTE_SUBS):
            _chemin = _u.split("youl4b.com", 1)[1]
            _r = _cli.get(_chemin)
            check(f"{_chemin} : Flask sert l'image malgré « ?v= » (200, même contenu)",
                  _r.status_code == 200 and _r.mimetype == "image/png"
                  and _r.data == (BOT / _chemin.split("?")[0].lstrip("/")).read_bytes(), _r.status_code)
            _r.close()
    # une image absente du dépôt : pas de version (rien à versionner), et le
    # journal le dit UNE fois, pas à chaque rendu
    _th_abs = dict(pd.THEMES["mario"], vignettes={"podium": "podium/absente.png", "subs": "podium/absente.png"})
    _v_abs, _log_abs = journal(lambda: [pd._vignette(_th_abs, "podium") for _ in range(5)])
    check("vignette absente du dépôt : adresse sans version, UNE ligne au journal pour cinq rendus",
          _v_abs[0] == {"url": "https://youl4b.com/static/podium/absente.png"}
          and len([l for l in _log_abs.splitlines() if "absente.png" in l]) == 1, _log_abs)
    if ancien is not None:
        check("FORMAT_AFFICHAGE a changé (les messages vivants sont refaits dès la mise en ligne)",
              pd.FORMAT_AFFICHAGE != ancien.FORMAT_AFFICHAGE, pd.FORMAT_AFFICHAGE)

    # ================================================================ 2. --
    print()
    print("=" * 70)
    print("2. Le message de la semaine, dans chaque état (rendu direct)")
    print("=" * 70)
    installer()
    CLOCK["now"] = m(2026, 9, 28, 8, 0)               # avant 9h : « ce lundi à 9h »
    _appels_rendu = []

    def _boom(methode, chemin, **kw):
        _appels_rendu.append((methode, chemin))
        raise AssertionError("appel réseau pendant un rendu")

    ETATS = (("vivant", {"en_cours": True}, T_EN_COURS, ROUGE, L_EN_COURS),
             ("terminée", {"termine": True}, T_TERMINE, OR, L_TERMINE),
             ("final", {}, T_FINAL, OR, L_FINAL))
    for cache, marqueurs in (("têtes posées", TETES), ("sans têtes", REPLI)):
        if cache == "têtes posées":
            poser_cache()
        else:
            effacer_cache()
        avant_cache = pd._fichier_emojis().read_bytes() if pd._fichier_emojis().exists() else None
        pd._api = _boom
        for nom, kw, t_, coul, ligne in ETATS:
            fin = dt.date(2026, 9, 24) if kw.get("en_cours") else DIM_W
            e_ = pd.embed_podium(CL_FR, LUN_W, fin, gid=IG, us=US, **kw)
            d_ = desc(e_)
            et = f"{nom}, {cache}"
            check(f"{et} : titre « {t_} », couleur {coul:#08x}, vignette du Grand Prix",
                  titre(e_) == t_ and e_["color"] == coul and e_["thumbnail"] == {"url": VIGNETTE_PODIUM},
                  (titre(e_), hex(e_.get("color", 0)), e_.get("thumbnail")))
            check(f"{et} : la ligne d'état de la course", d_.split("\n")[2] == ligne, d_.split("\n")[:4])
            top = [f"{marqueurs[i]} **{va}** — **{c}** subs · 🪙 **{p}$**" for i, (va, c, p) in enumerate(TOP)]
            check(f"{et} : le top 3 avec ses marqueurs et ses pièces (Jessye VA 8 1er, la VA FR 2e)",
                  "\n".join(top + SUITE) in d_, d_[:700])
            check(f"{et} : bloc des primes « Le podium de la course gagne des pièces », places et montants exacts",
                  "\n".join([BLOC_PRIMES, f"{marqueurs[0]} 1er → **10$**", f"{marqueurs[1]} 2e → **5$**",
                             f"{marqueurs[2]} 3e → **3$**"]) in d_, d_[-700:])
            check(f"{et} : réclamation, « un seul prix », numéro de VA : mot pour mot",
                  "💸 **Pour recevoir ta prime :** envoie un message à **@Luigi** dans **ton espace perso** "
                  "avec **ton rang de la semaine** et **ton adresse USDC (réseau Solana)**." in d_
                  and "Un seul prix par personne · payé à la main après vérification" in d_
                  and "🔢 _Ton numéro de VA ne change jamais : c'est le même chaque semaine._" in d_)
            check(f"{et} : ni 💰 ni médaille d'avant", not re.search("💰|🥇|🥈|🥉", d_))
            if cache == "têtes posées":
                check(f"{et} : les têtes ou rien — aucun emoji de repli à côté",
                      not re.search("👑|⭐", d_) and d_.count("<:kart_") == 6)
            sans = sans_theme(lambda: pd.embed_podium(CL_FR, LUN_W, fin, gid=IG, us=US, **kw))
            check(f"{et} : à l'habillage près, le message sans thème (chiffres, rangs, avertissements, pied)",
                  vers_avant(d_, marqueurs) == desc(sans) and pied(e_) == pied(sans), vers_avant(d_, marqueurs)[:300])
        check(f"{cache} : aucun appel réseau pendant les rendus, et le cache n'est pas réécrit",
              not _appels_rendu and (pd._fichier_emojis().read_bytes() if pd._fichier_emojis().exists()
                                     else None) == avant_cache, _appels_rendu)
        pd._api = lambda methode, chemin, **kw: DISCORD.api(methode, chemin, **kw)

    # deux têtes sur trois : le repli pour les trois (un Mario à côté d'un ⭐
    # ferait croire à un message cassé)
    poser_cache({k: v for k, v in IDS.items() if k != "kart_peach"})
    check("deux têtes sur trois dans le cache : les trois marqueurs de repli",
          pd._marqueurs(IG) == REPLI)
    poser_cache()
    check("les trois têtes : leurs balises Discord, 1er Mario, 2e Luigi, 3e Peach",
          pd._marqueurs(IG) == TETES)
    _prev = pd._fichier_emojis().with_suffix(".json.prev")
    safe_json.write_text(pd._fichier_emojis(), "pas du json")
    check("cache illisible : safe_json reprend la copie précédente (les têtes restent)",
          _prev.exists() and pd._marqueurs(IG) == TETES)
    _prev.unlink()
    safe_json.write_text(pd._fichier_emojis(), "pas du json", backup=False)
    check("cache illisible sans copie : repli, sans exception", pd._marqueurs(IG) == REPLI)
    poser_cache()
    check("Twitter et sans serveur : les médailles d'avant",
          pd._marqueurs(TW) == ["🥇", "🥈", "🥉"] and pd._marqueurs(None) == ["🥇", "🥈", "🥉"])

    # les avertissements, inchangés eux aussi
    us_t = dict(US, illisibles=["VA 2"], frais=False)
    cl_t = dict(CL_FR, illisibles=["Lola VA 4"])
    for kw in ({"en_cours": True}, {"termine": True}, {}):
        avec = pd.embed_podium(cl_t, LUN_W, DIM_W, gid=IG, us=us_t, **kw)
        sans = sans_theme(lambda: pd.embed_podium(cl_t, LUN_W, DIM_W, gid=IG, us=us_t, **kw))
        check(f"avertissements ({kw or 'final'}) : relevé incomplet, VA sans relevé, liste périmée — mot pour mot",
              vers_avant(desc(avec), TETES) == desc(sans) and "⚠️ **Classement incomplet** : Lola VA 4" in desc(avec)
              and "⚠️ **Sans relevé** : Jessye VA 2" in desc(avec), desc(avec)[-500:])
    # sans VA US (clé « avec_us » coupée, ou relevé indisponible) : même habillage,
    # même règle d'avant (le 3e touche son 3$ même à zéro, défaut laissé au propriétaire)
    seul = pd.embed_podium(CL_FR, LUN_W, DIM_W, gid=IG)
    check("VA FR seuls : têtes, 🪙 et 🟢 aussi, règle de prime d'avant",
          f"{TETES[0]} **Amelia VA 3** — **212** subs · 🪙 **10$**" in desc(seul)
          and f"{TETES[2]} **Amelia VA 1** — **0** subs · 🪙 **3$**" in desc(seul)
          and vers_avant(desc(seul), TETES) == desc(sans_theme(lambda: pd.embed_podium(CL_FR, LUN_W, DIM_W, gid=IG))),
          desc(seul)[:500])
    vide = pd.embed_podium({"lignes": [], "illisibles": ["Amelia VA 3"], "frais": True}, LUN_W, DIM_W,
                           gid=IG, en_cours=True)
    check("aucun relevé : titre de la course, « Aucun relevé cette semaine. »",
          titre(vide) == T_EN_COURS and "_Aucun relevé cette semaine._" in desc(vide))
    CLOCK["now"] = m(2026, 9, 28, 10, 30)
    check("« terminée » écrit après 9h : « dans la journée », comme sans thème",
          "Le podium officiel arrive dans la journée, sur ce message." in
          desc(pd.embed_podium(CL_FR, LUN_W, DIM_W, gid=IG, us=US, termine=True)))

    # ================================================================ 3. --
    print()
    print("=" * 70)
    print("3. La quinzaine : Championnat des subs")
    print("=" * 70)
    CLOCK["now"] = m(2026, 9, 24, 12, 0)
    S_OLD, S_OLD_FIN = dt.date(2026, 9, 16), dt.date(2026, 9, 30)
    tot = {"Amelia VA 3": 900, "Lola VA 2": 400, "Amelia VA 1": 30}
    tot_us = {"VA 8": 5000, "VA 12": 4100, "VA 3": 800, "VA 5": 90}
    for cache, marqueurs in (("têtes posées", TETES), ("sans têtes", REPLI)):
        if cache == "têtes posées":
            poser_cache()
        else:
            effacer_cache()
        pd._api = _boom
        for final, t_, coul in ((False, "🏎️ Championnat des subs — la quinzaine", BLEU),
                                (True, "🏎️ Championnat des subs — quinzaine du 16/09 au 30/09 (terminée)", OR)):
            pgs = pd.pages_subs(CL_FR, S_OLD, S_OLD_FIN, tot, gid=IG, final=final, us=US, totaux_us=tot_us)
            e_ = pgs[0]
            et = f"quinzaine {'figée' if final else 'vivante'}, {cache}"
            check(f"{et} : titre, couleur {coul:#08x}, vignette du Championnat",
                  len(pgs) == 1 and titre(e_) == t_ and e_["color"] == coul
                  and e_["thumbnail"] == {"url": VIGNETTE_SUBS}, (titre(e_), hex(e_.get("color", 0))))
            d_ = desc(e_)
            check(f"{et} : têtes au top 3, 🟢 ensuite, all-time de chacun",
                  "\n".join([f"{marqueurs[0]} **Jessye VA 8** — **241** subs · 🌐 5000 all-time",
                             f"{marqueurs[1]} **Amelia VA 3** — **212** subs · 🌐 900 all-time",
                             f"{marqueurs[2]} **Jessye VA 12** — **193** subs · 🌐 4100 all-time",
                             "4. 🟢 Lola VA 2 — 151 subs · 🌐 400 all-time",
                             "5. 🟢 Jessye VA 3 — 120 subs · 🌐 800 all-time"]) in d_, d_[:600])
            check(f"{et} : la quinzaine ne paie rien — ni 🪙 ni 💰", "🪙" not in d_ and "💰" not in d_)
            sans = sans_theme(lambda: pd.pages_subs(CL_FR, S_OLD, S_OLD_FIN, tot, gid=IG, final=final,
                                                    us=US, totaux_us=tot_us))
            check(f"{et} : à l'habillage près, la page sans thème (total, en-tête, pied)",
                  vers_avant(d_, marqueurs) == desc(sans[0]) and pied(e_) == pied(sans[0]))
        check(f"quinzaine, {cache} : aucun appel réseau pendant le rendu", not _appels_rendu, _appels_rendu)
        pd._api = lambda methode, chemin, **kw: DISCORD.api(methode, chemin, **kw)

    # ================================================================ 4. --
    print()
    print("=" * 70)
    print("4. Le bouton « Relancer la course »")
    print("=" * 70)
    check("vivant : « Relancer la course », gris, 🔄, custom_id podium:maj",
          pd._boutons(IG, True) == {"components": BOUTON})
    check("figé : « components » vide, comme avant", pd._boutons(IG, False) == {"components": []})
    check("Twitter : rien", pd._boutons(TW, True) == {} and pd._boutons(TW, False) == {})
    check("le custom_id n'a pas changé : les boutons déjà posés marchent encore",
          pd.BOUTON_MAJ == "podium:maj" and (ancien is None or ancien.BOUTON_MAJ == pd.BOUTON_MAJ))
    installer()
    CLOCK["now"] = m(2026, 9, 22, 12, 0)
    r = pd.traiter({"type": 3, "guild_id": IG, "channel_id": f"{IG}-podium", "application_id": "777",
                    "data": {"custom_id": "podium:maj", "component_type": 2},
                    "member": {"user": {"id": "42"}, "roles": [vd.SERVEURS_EXTRA[IG]["role_manager"]],
                               "permissions": "0"},
                    "message": {"id": "x", "channel_id": f"{IG}-podium"}, "token": "t"})
    check("un clic du staff sur le bouton renommé lance la mise à jour",
          ((r or {}).get("data") or {}).get("content", "").startswith("🔄 Mise à jour lancée") and len(TACHES) == 1, r)
    if TACHES:
        journal(TACHES.pop())

    # ================================================================ 5. --
    print()
    print("=" * 70)
    print("5. Les têtes sur le serveur : trouvées, créées, refusées — un essai par jour")
    print("=" * 70)
    # a. déjà là (posées à la main, ou par un autre déploiement)
    installer()
    CLOCK["now"] = m(2026, 9, 22, 12, 0)
    DISCORD.emojis[IG] = [{"id": "111111111111111111", "name": "vabio", "available": True}] + [
        {"id": IDS[n], "name": n, "available": True} for n in NOMS]
    r, log = journal(lambda: pd._assurer_emojis(IG))
    check("déjà sur le serveur : trouvées par la liste, AUCUNE création",
          r == IDS and [x["m"] for x in appels_emojis()] == ["GET"]
          and appels_emojis()[0]["p"] == f"/guilds/{IG}/emojis", appels_emojis())
    check("… le cache les garde ({serveur: {nom: id}}) et le dit une fois au journal",
          lire_cache().get(IG) == IDS and len(lignes_emoji(log)) == 1 and "trouvées" in log, log)
    check("… le rendu les prend", pd._marqueurs(IG) == TETES)
    n0 = len(DISCORD.appels)
    r, log = journal(lambda: [pd._assurer_emojis(IG) for _ in range(20)])
    check("le même jour : plus aucun appel, plus rien au journal", len(DISCORD.appels) == n0 and not log)
    CLOCK["now"] = m(2026, 9, 23, 0, 10)
    r, log = journal(lambda: pd._assurer_emojis(IG))
    check("le lendemain : UNE vérification (la liste), rien de créé, rien au journal",
          [x["m"] for x in appels_emojis(depuis=n0)] == ["GET"] and not lignes_emoji(log), log)

    # b. absentes : créées depuis les PNG du dépôt
    installer()
    CLOCK["now"] = m(2026, 9, 22, 12, 0)
    r, log = journal(lambda: pd._assurer_emojis(IG))
    posts = [x for x in appels_emojis() if x["m"] == "POST"]
    check("absentes : la liste d'abord, puis une création par tête, dans l'ordre",
          [x["m"] for x in appels_emojis()] == ["GET", "POST", "POST", "POST"]
          and [x["json"]["name"] for x in posts] == NOMS
          and all(x["p"] == f"/guilds/{IG}/emojis" for x in posts), appels_emojis())
    _png_ok = all(
        x["json"]["image"].startswith("data:image/png;base64,") and x["json"].get("roles") == []
        and base64.b64decode(x["json"]["image"].split(",", 1)[1])
        == (BOT / "emojis" / f'{x["json"]["name"]}.png').read_bytes() for x in posts)
    check("… chaque image est le PNG du dépôt, en data URI base64", _png_ok)
    check("… les identifiants rendus par Discord vont au cache, et au rendu",
          r == {e["name"]: e["id"] for e in DISCORD.emojis[IG]} and lire_cache().get(IG) == r
          and pd._marqueurs(IG) == [f"<:{n}:{r[n]}>" for n in NOMS])
    check("… une ligne au journal : créées", len(lignes_emoji(log)) == 1
          and "créées : kart_mario, kart_luigi, kart_peach" in log, log)

    # c. une tête supprimée à la main : vue le lendemain, refaite
    DISCORD.emojis[IG] = [e for e in DISCORD.emojis[IG] if e["name"] != "kart_luigi"]
    CLOCK["now"] = m(2026, 9, 23, 0, 10)
    n0 = len(DISCORD.appels)
    r, log = journal(lambda: pd._assurer_emojis(IG))
    check("supprimée à la main : vue à la vérification du lendemain, refaite (elle seule)",
          [(x["m"], (x["json"] or {}).get("name")) for x in appels_emojis(depuis=n0)]
          == [("GET", None), ("POST", "kart_luigi")]
          and "supprimées à la main, refaites : kart_luigi" in log
          and lire_cache()[IG]["kart_luigi"] == DISCORD.emojis[IG][-1]["id"], log)
    # d. une tête « indisponible » (boosts perdus) ne compte pas
    DISCORD.emojis[IG] = [dict(e, available=(e["name"] != "kart_peach")) for e in DISCORD.emojis[IG]]
    CLOCK["now"] = m(2026, 9, 24, 0, 10)
    n0 = len(DISCORD.appels)
    journal(lambda: pd._assurer_emojis(IG))
    check("une tête marquée indisponible par Discord est refaite (une indisponible ne s'affiche pas)",
          [(x["m"], (x["json"] or {}).get("name")) for x in appels_emojis(depuis=n0)]
          == [("GET", None), ("POST", "kart_peach")])

    # e. permission manquante : repli, une ligne, un essai par jour
    installer()
    DISCORD.refus_creation = (403, {"message": "Missing Permissions", "code": 50013})
    t = m(2026, 9, 22, 0, 10)
    _, log = journal(lambda: a(t))
    em = appels_emojis(IG)
    check("403 / 50013 : la liste, UNE tentative de création, puis on s'arrête (pas les trois)",
          [x["m"] for x in em] == ["GET", "POST"], [x["m"] for x in em])
    check("… UNE ligne au journal, qui nomme la permission et le repli",
          len(lignes_emoji(log)) == 1 and "Gérer les expressions" in log and "👑 ⭐ 🍄" in log
          and "nouvel essai demain" in log, lignes_emoji(log))
    js = DISCORD.salons[f"{IG}-podium"][pd._etat()["vivants"][IG]["message"]]["json"]
    check("… le podium part quand même, avec 👑 ⭐ 🍄 (rien de bloqué, rien de cassé)",
          titre(js) == T_EN_COURS and desc(js).count("👑") == 2 and "<:kart_" not in desc(js)
          and js.get("components") == BOUTON, desc(js)[:300])
    pages = pd._etat()["subs"][IG]["messages"]
    check("… la quinzaine aussi",
          pages and "👑" in desc(DISCORD.salons[f"{IG}-subs"][pages[0]]["json"]))
    _, log = journal(lambda: [a(t + dt.timedelta(minutes=10 * k)) for k in range(1, 143)])
    check("toute la journée (142 tours de boucle, rafraîchissements compris) : AUCUN nouvel essai, rien au journal",
          len(appels_emojis(IG)) == 2 and not lignes_emoji(log), (len(appels_emojis(IG)), lignes_emoji(log)[:2]))
    check("… et l'échec est gardé dans le cache, avec son jour",
          lire_cache()["_essais"][IG]["jour"] == "2026-09-22" and "50013" in lire_cache()["_essais"][IG]["echec"])
    DISCORD.refus_creation = None              # le propriétaire a donné la permission
    _, log = journal(lambda: a(m(2026, 9, 23, 0, 10)))
    em = appels_emojis(IG)
    check("le lendemain : UN nouvel essai, qui réussit (liste puis trois créations)",
          [x["m"] for x in em][2:] == ["GET", "POST", "POST", "POST"] and len(lignes_emoji(log)) == 1, em[2:])
    CLOCK["now"] = m(2026, 9, 23, 14, 0)
    a(CLOCK["now"])
    js = DISCORD.salons[f"{IG}-podium"][pd._etat()["vivants"][IG]["message"]]["json"]
    check("… et le passage suivant met les têtes sur le podium vivant",
          desc(js).count("<:kart_") == 6 and "👑" not in desc(js), desc(js)[:300])

    # f. liste illisible : rien de créé (Discord accepte deux emojis du même nom)
    installer()
    DISCORD.refus_liste = (500, {"message": "panne"})
    CLOCK["now"] = m(2026, 9, 22, 12, 0)
    r, log = journal(lambda: pd._assurer_emojis(IG))
    check("liste illisible (500) : AUCUNE création (pas de doublon), une ligne, repli",
          [x["m"] for x in appels_emojis()] == ["GET"] and len(lignes_emoji(log)) == 1
          and pd._marqueurs(IG) == REPLI, log)
    poser_cache()
    CLOCK["now"] = m(2026, 9, 23, 12, 0)
    r, log = journal(lambda: pd._assurer_emojis(IG))
    check("… avec des têtes déjà connues : le cache est gardé (une liste ratée ne prouve rien)",
          pd._marqueurs(IG) == TETES and "gardées" in log, log)

    # g. une exception (réseau tombé) : jamais un podium cassé, pas de rafale
    installer()
    DISCORD.exception = True
    t = m(2026, 9, 22, 12, 0)
    _, log = journal(lambda: a(t))
    check("exception pendant la pose : le podium et la quinzaine partent quand même, en repli",
          pd._etat().get("vivants", {}).get(IG, {}).get("message")
          and pd._etat().get("subs", {}).get(IG, {}).get("messages")
          and "👑" in desc(DISCORD.salons[f"{IG}-podium"][pd._etat()["vivants"][IG]["message"]]["json"]))
    check("… une ligne au journal", len(lignes_emoji(log)) == 1 and "ConnectionError" in log, lignes_emoji(log))
    n_em = len(appels_emojis(IG))
    _, log = journal(lambda: [a(t + dt.timedelta(minutes=10 * k)) for k in range(1, 30)])
    check("… et pas d'autre essai de la journée", len(appels_emojis(IG)) == n_em and not lignes_emoji(log))

    # h. Twitter, et Va IG sans la clé : jamais rien
    installer()
    derouler(CAL_NORMAL)
    check("Twitter : aucun appel aux emojis de tout le calendrier",
          not appels_emojis(TW) and pd._assurer_emojis(TW) == {} and not appels_emojis(TW))
    # une liste par jour (la pose), plus une lecture juste avant chaque
    # message figé (section 10) : ici le podium du 28/09 et la quinzaine du
    # 16/09, figée le 01/10
    _etat_n = pd._etat()
    _n_gels = (len([k for k in _etat_n.get("postes", {}) if k.startswith(f"{IG}:")])
               + len([v for v in ((_etat_n.get("figes") or {}).get(IG) or {}).values()
                      if v.get("mode") == "sans_podium"])
               + len((_etat_n.get("subs_figes") or {}).get(IG) or {}))
    _gets = [x for x in appels_emojis(IG) if x["m"] == "GET"]
    check("Va IG (avec le thème) : une liste par jour, plus une avant chaque gel ; trois créations en tout",
          _n_gels == 2 and len(_gets) == len({x["quand"].date() for x in _gets}) + _n_gels
          and len([x for x in appels_emojis(IG) if x["m"] == "POST"]) == 3,
          (_n_gels, [(str(x["quand"]), x["m"]) for x in appels_emojis(IG)]))
    installer()
    sans_theme(lambda: derouler(CAL_NORMAL))
    check("Va IG sans la clé : aucun appel aux emojis, aucun fichier de cache",
          not appels_emojis() and not pd._fichier_emojis().exists())

    # ================================================================ 6. --
    print()
    print("=" * 70)
    print("6. Posées par les passages qui parlent à Discord, jamais par un rendu")
    print("=" * 70)
    corps = {}
    for f in ("rafraichir", "rafraichir_subs", "poster_podium", "embed_podium", "pages_subs",
              "_lignes_podium_mix", "_marqueurs", "_vignette", "_figer_quinzaine", "_semaine_terminee",
              "_figer_semaine", "_primes_retenues"):
        corps[f] = inspect.getsource(getattr(pd, f))
    check("rafraichir, rafraichir_subs et poster_podium posent les têtes (avant tout rendu)",
          all("_assurer_emojis(gid)" in corps[f] for f in ("rafraichir", "rafraichir_subs", "poster_podium"))
          and corps["rafraichir"].find("_assurer_emojis(gid)") < corps["rafraichir"].find("embed_podium(")
          and corps["rafraichir_subs"].find("_assurer_emojis(gid)") < corps["rafraichir_subs"].find("_figer_quinzaines(")
          and corps["poster_podium"].find("_assurer_emojis(gid)") < corps["poster_podium"].find("_primes_retenues("))
    check("aucun rendu n'appelle Discord ni ne pose de tête",
          not [f for f in ("embed_podium", "pages_subs", "_lignes_podium_mix", "_marqueurs", "_vignette")
               if "_api(" in corps[f] or "_assurer_emojis" in corps[f]])
    check("les gels ne créent rien eux-mêmes : la pose passe par les trois fonctions ci-dessus",
          not [f for f in ("_figer_quinzaine", "_semaine_terminee", "_figer_semaine", "_primes_retenues")
               if "_assurer_emojis" in corps[f]])
    # … mais un message figé l'est pour toujours : juste avant son rendu, la
    # liste du serveur est relue (section 10). Le « terminée » du lundi, lui,
    # est refait par le podium de 9h : pas de lecture pour lui
    check("chaque rendu figé (podium de 9h, semaine figée, podium corrigé, quinzaine figée) relit la liste avant",
          all("_tetes_sures(gid)" in corps[f]
              and corps[f].find("_tetes_sures(gid)") < corps[f].find(
                  "pages_subs(" if f == "_figer_quinzaine" else "embed_podium(")
              for f in ("poster_podium", "_figer_semaine", "_primes_retenues", "_figer_quinzaine"))
          and "_tetes_sures" not in corps["_semaine_terminee"])
    # dans la vraie boucle : la pose passe AVANT le premier message
    installer()
    a(m(2026, 9, 22, 12, 0))
    ig = [x for x in DISCORD.appels if x["p"].startswith(f"/guilds/{IG}/") or x["p"].startswith(f"/channels/{IG}-")]
    i_post = next(i for i, x in enumerate(ig) if x["p"] == f"/channels/{IG}-podium/messages")
    check("premier passage : liste et créations AVANT le premier message, qui porte déjà les têtes",
          [x["m"] for x in ig[:4]] == ["GET", "POST", "POST", "POST"] and i_post == 4
          and desc(ig[i_post]["json"]).count("<:kart_") == 6, [(x["m"], x["p"]) for x in ig[:6]])
    pages = pd._etat()["subs"][IG]["messages"]
    check("… la quinzaine vivante aussi (même passage, aucun appel de plus)",
          desc(DISCORD.salons[f"{IG}-subs"][pages[0]]["json"]).count("<:kart_") == 3
          and len(appels_emojis(IG)) == 4)
    for t_ in (m(2026, 9, 27, 20, 0), m(2026, 9, 28, 0, 10), m(2026, 9, 28, 9, 0), m(2026, 9, 30, 23, 50),
               m(2026, 10, 1, 0, 10)):
        a(t_)
    etat = pd._etat()
    fin_w = DISCORD.salons[f"{IG}-podium"][etat["postes"][f"{IG}:{LUN_W}"]]["json"]
    fg_q = etat["subs_figes"][IG]["2026-09-16"]["messages"][0]
    q_js = DISCORD.salons[f"{IG}-subs"][fg_q]["json"]
    check("podium de 9h : figé avec les têtes, le titre final, l'or, sans bouton",
          titre(fin_w) == T_FINAL and fin_w["embeds"][0]["color"] == OR
          and desc(fin_w).count("<:kart_") == 6 and fin_w.get("components") == [], desc(fin_w)[:300])
    check("quinzaine figée le 01/10 : têtes, titre daté, or, vignette, sans bouton",
          titre(q_js) == "🏎️ Championnat des subs — quinzaine du 16/09 au 30/09 (terminée)"
          and q_js["embeds"][0]["color"] == OR and q_js["embeds"][0]["thumbnail"] == {"url": VIGNETTE_SUBS}
          and desc(q_js).count("<:kart_") == 3 and q_js.get("components") == [], titre(q_js))
    _gets = [x["quand"] for x in appels_emojis(IG) if x["m"] == "GET"]
    _jours = sorted({q.date() for q in _gets})
    check("sur ces cinq jours : une liste par jour, plus une juste avant chacun des deux gels, trois créations",
          len([x for x in appels_emojis(IG) if x["m"] == "POST"]) == 3
          and sorted(_gets) == sorted([min(q for q in _gets if q.date() == j) for j in _jours]
                                      + [m(2026, 9, 28, 9, 0), m(2026, 10, 1, 0, 10)]),
          [str(q) for q in _gets])

    # ================================================================ 7. --
    print()
    print("=" * 70)
    print("7. La longueur : jamais coupé à cause des têtes")
    print("=" * 70)
    installer()
    CLOCK["now"] = m(2026, 9, 28, 9, 30)
    us_long = {"lignes": [L(f"VA {i}", 900 - i, i) for i in range(1, 16)], "illisibles": [], "frais": True}

    def cl_fr_n(n):
        return {"lignes": [L(f"Amelia VA {i}", 0, i, "amelia") for i in range(1, n + 1)],
                "illisibles": [], "frais": True}

    effacer_cache()
    n_fr, long_repli = None, None
    for n in range(10, 200):
        d_ = desc(pd.embed_podium(cl_fr_n(n), LUN_W, DIM_W, gid=IG, us=us_long))
        if 4096 - 150 < len(d_) <= 4096:
            n_fr, long_repli = n, d_
            break
    check("cas construit : un podium qui tient en 4096 avec 👑 ⭐ 🍄, pas avec les têtes",
          n_fr is not None and len(long_repli) + 6 * (len(TETES[0]) - 1) > 4096, n_fr)
    if n_fr:
        poser_cache()
        e_, log = journal(lambda: pd.embed_podium(cl_fr_n(n_fr), LUN_W, DIM_W, gid=IG, us=us_long))
        check("… avec les têtes posées : il repart en 👑 ⭐ 🍄, entier (rien de coupé), et le dit",
              desc(e_) == long_repli and desc(e_).endswith("c'est le même chaque semaine._")
              and "trop long" in log and "les têtes" in log
              and "🟢" not in log, (len(desc(e_)), log))      # les têtes suffisaient : le 🟢 reste
        e_, log = journal(lambda: pd.embed_podium(cl_fr_n(n_fr + 60), LUN_W, DIM_W, gid=IG, us=us_long))
        check("trop long même en repli : coupé à 4096 (limite de Discord), mais dit au journal",
              len(desc(e_)) == 4096 and "coupé à 4096" in log, log)
    # Le 🟢 des places 4 et plus pèse deux caractères par ligne : une
    # centaine de VA FR, et c'est lui qui faisait couper (relu en revue) un
    # podium qui tient SANS thème — la coupe tombait sur la réclamation des
    # primes. Le thème ne doit jamais faire couper ce qui tiendrait sans lui.
    _mots = {"en_cours": ("🔴 _Mis à jour tout seul, plusieurs fois par jour. Rien n'est joué._", L_EN_COURS),
             "termine": ("🏁 _Semaine terminée. Le podium officiel arrive dans la journée, sur ce message._",
                         L_TERMINE.replace("ce lundi à 9h", "dans la journée")),
             "final": ("🔒 _Semaine terminée : classement arrêté, il ne bougera plus._", L_FINAL)}

    def vers_theme(texte, etat):
        """Le rendu sans thème habillé en Mario, avec 👑 ⭐ 🍄 et 🟢, SANS
        rien retirer : ce que le thème écrirait s'il ne cédait rien."""
        texte = texte.replace(_mots[etat][0], _mots[etat][1]).replace(
            "🎁 **Les 3 meilleurs de la semaine touchent une prime :**", BLOC_PRIMES).replace("💰", "🪙")
        for med, mq in zip(["🥇", "🥈", "🥉"], REPLI):
            texte = texte.replace(med, mq)
        return re.sub(r"^(\d+)\. ", r"\1. 🟢 ", texte, flags=re.M)

    for etat_, kw in (("final", {}), ("termine", {"termine": True}), ("en_cours", {"en_cours": True})):
        for cache in ("sans têtes", "têtes posées"):
            effacer_cache() if cache == "sans têtes" else poser_cache()
            n_bord, sans_d = None, ""
            for n in range(40, 300):
                # coupé, un rendu fait exactement 4096 : c'est sa fin qui dit
                # s'il tient (ici, sans avertissement, la ligne du numéro de VA)
                d_, _ = journal(lambda: desc(sans_theme(
                    lambda: pd.embed_podium(cl_fr_n(n), LUN_W, DIM_W, gid=IG, us=us_long, **kw))))
                if not d_.endswith(FIN_PODIUM):
                    break
                n_bord, sans_d = n, d_
            et = f"podium {etat_}, {cache}, {n_bord} VA FR"
            check(f"{et} : cas construit — sans thème il tient, habillé (🟢 compris) il ne tiendrait pas",
                  n_bord and len(sans_d) <= 4096 and len(vers_theme(sans_d, etat_)) > 4096,
                  (n_bord, len(sans_d), len(vers_theme(sans_d, etat_))))
            e_, log = journal(lambda: pd.embed_podium(cl_fr_n(n_bord), LUN_W, DIM_W, gid=IG, us=us_long, **kw))
            check(f"{et} : avec le thème non plus, rien de coupé — réclamation, « un seul prix », numéro de VA entiers",
                  len(desc(e_)) <= 4096 and "coupé" not in log
                  and "**ton adresse USDC (réseau Solana)**.\nUn seul prix par personne · payé à la main après "
                      "vérification\n\n🔢 _Ton numéro de VA ne change jamais : c'est le même chaque semaine._"
                  in desc(e_), (len(desc(e_)), log, desc(e_)[-200:]))
            check(f"{et} : le même message que sans thème, mot pour mot, aux marqueurs près (🟢 retirés, 👑 ⭐ 🍄)",
                  vers_avant(desc(e_).replace(_mots[etat_][1], _mots[etat_][0]), REPLI) == sans_d
                  and "🟢" not in desc(e_) and "<:kart_" not in desc(e_)
                  and desc(e_).count("👑") == 2 and titre(e_) == {"final": T_FINAL, "termine": T_TERMINE,
                                                                 "en_cours": T_EN_COURS}[etat_])
            check(f"{et} : dit au journal (une ligne), et seulement ce qu'il a fallu retirer",
                  len([l for l in log.splitlines() if "trop long" in l]) == 1
                  and "🟢" in log and (("têtes" in log) == (cache == "têtes posées")), log)
    # juste sous le bord : le 🟢 reste (rien n'est retiré sans nécessité)
    effacer_cache()
    for n in range(40, 300):
        d_, _ = journal(lambda: desc(pd.embed_podium(cl_fr_n(n + 1), LUN_W, DIM_W, gid=IG, us=us_long)))
        if "🟢" not in d_ or not d_.endswith(FIN_PODIUM):
            break
    _e, _log = journal(lambda: pd.embed_podium(cl_fr_n(n), LUN_W, DIM_W, gid=IG, us=us_long))
    check(f"{n} VA FR, habillé il tient encore : le 🟢 reste, rien au journal",
          "🟢" in desc(_e) and desc(_e).endswith(FIN_PODIUM) and len(desc(_e)) <= 4096 and not _log
          and desc(_e).count("🟢") == len(re.findall(r"^\d+\. ", desc(_e), flags=re.M)), _log)
    # la quinzaine : ses pages comptent la vraie longueur des lignes
    poser_cache()
    cl_q = {"lignes": [L(f"Amelia VA {i}", 500 - i, i, "amelia") for i in range(1, 121)],
            "illisibles": [], "frais": True}
    pgs = pd.pages_subs(cl_q, dt.date(2026, 9, 16), dt.date(2026, 9, 30), {}, gid=IG)
    toutes = "\n".join(desc(x) for x in pgs)
    check("quinzaine de 120 VA avec les têtes : plusieurs pages, aucune au-delà de 4096, chaque VA une fois",
          len(pgs) > 1 and all(len(desc(x)) <= 4096 for x in pgs)
          and sorted(int(x) for x in re.findall(r"Amelia VA (\d+)(?:\*\*)? — ", toutes)) == list(range(1, 121))
          and toutes.count("<:kart_") == 3, [len(desc(x)) for x in pgs])
    check("… titres « (1/N) » du Championnat, le total sur la dernière page",
          [titre(x) for x in pgs] == [f"🏎️ Championnat des subs — la quinzaine ({k}/{len(pgs)})"
                                      for k in range(1, len(pgs) + 1)]
          and "👥 **Total période**" in desc(pgs[-1]) and all(x["thumbnail"] == {"url": VIGNETTE_SUBS} for x in pgs))

    # ================================================================ 8. --
    print()
    print("=" * 70)
    print("8. Le format d'affichage : les messages vivants refaits dès la mise en ligne")
    print("=" * 70)
    installer()
    a(m(2026, 9, 22, 12, 0))
    etat = pd._etat()
    for cle in ("vivants", "subs"):
        etat[cle][IG]["format"] = "2026-10-03-bouton"     # écrits par le code d'avant
    pd._ecrire(etat)
    CLOCK["now"] = m(2026, 9, 22, 12, 10)
    check("message vivant écrit avant le thème : refait au tour suivant, sans attendre deux heures",
          pd.a_rafraichir(IG) and pd.a_rafraichir_subs(IG))
    a(CLOCK["now"])
    etat = pd._etat()
    check("… et refait au format du thème",
          etat["vivants"][IG]["format"] == pd.FORMAT_AFFICHAGE == etat["subs"][IG]["format"]
          and not pd.a_rafraichir(IG) and not pd.a_rafraichir_subs(IG))

    # ================================================================ 9. --
    print()
    print("=" * 70)
    print(f"9. Twitter, et Va IG sans la clé : le code d'avant le thème ({REF}), octet pour octet")
    print("=" * 70)
    if ancien is not None:
        for nom, cal in CALS:
            ref = derouler(cal, mod=ancien)
            avec = derouler(cal)
            tw_ref = [x for x in ref if x[1].startswith(f"/channels/{TW}-")]
            tw_avec = [x for x in avec if x[1].startswith(f"/channels/{TW}-")]
            check(f"{nom} : AVEC le thème, chaque appel de Twitter est celui d'avant ({len(tw_ref)} appels)",
                  tw_ref == tw_avec and len(tw_ref) > 3)
            ig_ref = [(x[0], x[1]) for x in ref if x[1].startswith(f"/channels/{IG}-")]
            ig_avec = [(x[0], x[1]) for x in avec if x[1].startswith(f"/channels/{IG}-")]
            check(f"{nom} : AVEC le thème, Va IG fait les mêmes gestes, seul le contenu change",
                  ig_ref == ig_avec and [x for x in ref if x[1].startswith(f"/channels/{IG}-")]
                  != [x for x in avec if x[1].startswith(f"/channels/{IG}-")])
            sans = sans_theme(lambda: derouler(cal))
            diff = next((i for i, (x, y) in enumerate(zip(ref, sans)) if x != y), None)
            check(f"{nom} : SANS la clé, Twitter ET Va IG identiques au code d'avant ({len(ref)} appels)",
                  ref == sans and len(ref) > 5,
                  (diff, ref[diff] if diff is not None else len(ref), sans[diff] if diff is not None else len(sans)))
        installer(ancien)
        installer()
        CLOCK["now"] = m(2026, 9, 28, 8, 0)
        cl_ill = dict(CL_FR, illisibles=["Lola VA 4"], frais=False)
        us_ill = dict(US, illisibles=["VA 2"])
        for g in (TW, IG, None):
            for us_ in (None, US, us_ill):
                for kw in ({"en_cours": True}, {"termine": True}, {}):
                    r_n = sans_theme(lambda: pd.embed_podium(cl_ill, LUN_W, DIM_W, gid=g, us=us_, **kw))
                    r_a = ancien.embed_podium(cl_ill, LUN_W, DIM_W, gid=g, us=us_, **kw)
                    check(f"embed_podium {g or 'sans serveur'} {kw or 'final'} us={'oui' if us_ else 'non'} "
                          "sans la clé : rendu d'avant", r_n == r_a)
                for fin_ in (False, True):
                    r_n = sans_theme(lambda: pd.pages_subs(cl_ill, dt.date(2026, 9, 16), dt.date(2026, 9, 30),
                                                           {"Amelia VA 3": 7}, gid=g, final=fin_, us=us_,
                                                           totaux_us={"VA 8": 3}))
                    r_a = ancien.pages_subs(cl_ill, dt.date(2026, 9, 16), dt.date(2026, 9, 30),
                                            {"Amelia VA 3": 7}, gid=g, final=fin_, us=us_, totaux_us={"VA 8": 3})
                    check(f"pages_subs {g or 'sans serveur'} final={fin_} us={'oui' if us_ else 'non'} "
                          "sans la clé : rendu d'avant", r_n == r_a)
            check(f"_boutons {g or 'sans serveur'} sans la clé : ceux d'avant",
                  all(sans_theme(lambda: pd._boutons(g, v)) == ancien._boutons(g, v) for v in (True, False)))
        check("Twitter AVEC le thème de Va IG : rendus d'avant (le thème ne déborde pas)",
              pd.embed_podium(cl_ill, LUN_W, DIM_W, gid=TW, en_cours=True)
              == ancien.embed_podium(cl_ill, LUN_W, DIM_W, gid=TW, en_cours=True)
              and pd.pages_subs(cl_ill, dt.date(2026, 9, 16), dt.date(2026, 9, 30), {}, gid=TW)
              == ancien.pages_subs(cl_ill, dt.date(2026, 9, 16), dt.date(2026, 9, 30), {}, gid=TW)
              and pd.embed_bonus(cl_ill, LUN_W)["description"] == ancien.embed_bonus(cl_ill, LUN_W)["description"])

    # =============================================================== 10. --
    print()
    print("=" * 70)
    print("10. Un message figé relit ses têtes : jamais une tête morte pour toujours")
    print("=" * 70)
    # Relu en revue : la liste n'est vérifiée qu'une fois par jour. Une tête
    # supprimée à la main APRÈS cette vérification gardait son identifiant
    # dans le cache, et le podium de 9h, figé pour toujours, l'affichait en
    # « :kart_luigi: » ; la correction du lendemain ne touchait plus un
    # message figé.

    def lire_message(salon, mid):
        return DISCORD.salons[salon][mid]["json"]

    def vif_ig():
        return lire_message(f"{IG}-podium", pd._etat()["vivants"][IG]["message"])

    def oter(nom):
        DISCORD.emojis[IG] = [e for e in DISCORD.emojis[IG] if e["name"] != nom]

    # a. le podium de 9h
    installer()
    for t_ in (m(2026, 9, 22, 12, 0), m(2026, 9, 27, 20, 0), m(2026, 9, 28, 0, 10)):
        a(t_)
    luigi = lire_cache()[IG]["kart_luigi"]
    check("(départ) têtes posées, vérification du jour faite le lundi à 00h10",
          lire_cache()["_essais"][IG]["jour"] == "2026-09-28" and len(lire_cache()[IG]) == 3)
    oter("kart_luigi")                               # supprimée à la main à 8h
    n0 = len(DISCORD.appels)
    _, log = journal(lambda: a(m(2026, 9, 28, 9, 0)))
    etat = pd._etat()
    mid_p = etat["postes"][f"{IG}:{LUN_W}"]
    js = lire_message(f"{IG}-podium", mid_p)
    check("podium de 9h : la liste relue juste avant le gel — une lecture, aucune création",
          [x["m"] for x in appels_emojis(IG, depuis=n0)] == ["GET"], appels_emojis(IG, depuis=n0))
    check("… figé SANS la tête disparue : 👑 ⭐ 🍄 aux trois places et au bloc des primes",
          titre(js) == T_FINAL and "<:kart_" not in desc(js) and desc(js).count("👑") == 2
          and desc(js).count("⭐") == 2 and js.get("components") == [], desc(js)[:400])
    check("… le cache l'oublie, une ligne au journal qui la nomme",
          "kart_luigi" not in lire_cache()[IG] and len(lignes_emoji(log)) == 1
          and "kart_luigi" in log, lignes_emoji(log))
    check("… le message vivant de la semaine neuve non plus n'a pas l'identifiant mort",
          f"<:kart_luigi:{luigi}>" not in desc(vif_ig()) and "👑" in desc(vif_ig()))
    n0 = len(DISCORD.appels)
    _, log = journal(lambda: a(m(2026, 9, 29, 0, 10)))
    check("le lendemain : la pose refait kart_luigi (elle seule), les têtes reviennent sur le vivant",
          [(x["m"], (x["json"] or {}).get("name")) for x in appels_emojis(IG, depuis=n0)]
          == [("GET", None), ("POST", "kart_luigi")] and desc(vif_ig()).count("<:kart_") == 6)
    check("… le podium figé, lui, garde ses 👑 ⭐ 🍄 — justes, et jamais retouchés",
          "<:kart_" not in desc(lire_message(f"{IG}-podium", mid_p)))

    # b. têtes intactes : le gel les garde (la lecture ne coûte qu'un appel)
    installer()
    for t_ in (m(2026, 9, 22, 12, 0), m(2026, 9, 28, 0, 10)):
        a(t_)
    n0 = len(DISCORD.appels)
    _, log = journal(lambda: a(m(2026, 9, 28, 9, 0)))
    js = lire_message(f"{IG}-podium", pd._etat()["postes"][f"{IG}:{LUN_W}"])
    check("têtes intactes : une lecture, et le podium figé porte les têtes ; rien au journal",
          [x["m"] for x in appels_emojis(IG, depuis=n0)] == ["GET"] and desc(js).count("<:kart_") == 6
          and not lignes_emoji(log), lignes_emoji(log))
    n0 = len(DISCORD.appels)
    _, log = journal(lambda: [a(m(2026, 9, 28, 9, 10 + 10 * k)) for k in range(5)])
    check("… les tours suivants du lundi (podium déjà figé) : plus aucune lecture",
          not appels_emojis(IG, depuis=n0))

    # c. liste illisible au moment du gel : 👑 ⭐ 🍄 sur CE message, cache gardé
    installer()
    for t_ in (m(2026, 9, 22, 12, 0), m(2026, 9, 28, 0, 10)):
        a(t_)
    DISCORD.refus_liste = (503, {"message": "upstream"})
    n0 = len(DISCORD.appels)
    _, log = journal(lambda: a(m(2026, 9, 28, 9, 0)))
    js = lire_message(f"{IG}-podium", pd._etat()["postes"][f"{IG}:{LUN_W}"])
    check("liste illisible au gel : une lecture, le podium figé en 👑 ⭐ 🍄 (rien d'invérifié pour toujours)",
          [x["m"] for x in appels_emojis(IG, depuis=n0)] == ["GET"] and "<:kart_" not in desc(js)
          and desc(js).count("👑") == 2 and titre(js) == T_FINAL, desc(js)[:300])
    check("… une ligne au journal ; le cache est gardé, le vivant garde ses têtes",
          len(lignes_emoji(log)) == 1 and "503" in log and len(lire_cache()[IG]) == 3
          and desc(vif_ig()).count("<:kart_") == 6, lignes_emoji(log))
    DISCORD.refus_liste = None
    installer()
    for t_ in (m(2026, 9, 22, 12, 0), m(2026, 9, 28, 0, 10)):
        a(t_)
    DISCORD.exception = True
    _, log = journal(lambda: a(m(2026, 9, 28, 9, 0)))
    js = lire_message(f"{IG}-podium", pd._etat()["postes"][f"{IG}:{LUN_W}"])
    check("exception pendant la lecture : le podium est figé quand même, en 👑 ⭐ 🍄, et le journal le dit",
          titre(js) == T_FINAL and "<:kart_" not in desc(js) and "ConnectionError" in log, lignes_emoji(log))
    DISCORD.exception = False

    # d. la quinzaine figée : kart_peach supprimée entre la vérification du
    # jour et le gel de 00h10
    installer()
    for t_ in (m(2026, 9, 22, 12, 0), m(2026, 9, 30, 23, 50)):
        a(t_)
    CLOCK["now"] = m(2026, 10, 1, 0, 5)
    journal(lambda: pd._assurer_emojis(IG))          # la vérification du 01/10
    oter("kart_peach")
    n0 = len(DISCORD.appels)
    _, log = journal(lambda: a(m(2026, 10, 1, 0, 10)))
    fg_q = pd._etat()["subs_figes"][IG]["2026-09-16"]["messages"][0]
    q_js = lire_message(f"{IG}-subs", fg_q)
    check("quinzaine figée : la liste relue avant le gel, sans création, la page en 👑 ⭐ 🍄",
          [x["m"] for x in appels_emojis(IG, depuis=n0)] == ["GET"]
          and titre(q_js) == "🏎️ Championnat des subs — quinzaine du 16/09 au 30/09 (terminée)"
          and "<:kart_" not in desc(q_js) and "👑" in desc(q_js) and "🍄" in desc(q_js), desc(q_js)[:300])

    # e. la semaine figée sans podium (relevé FR raté tout le lundi)
    installer()
    for t_, act in ((m(2026, 9, 22, 12, 0), None), (m(2026, 9, 28, 0, 10), muet_fr_semaine),
                    (m(2026, 9, 28, 9, 0), None), (m(2026, 9, 28, 23, 50), None)):
        if act:
            act()
        a(t_)
    CLOCK["now"] = m(2026, 9, 29, 0, 5)
    journal(lambda: pd._assurer_emojis(IG))          # la vérification du 29/09
    oter("kart_mario")
    fr_revenu()
    n0 = len(DISCORD.appels)
    _, log = journal(lambda: a(m(2026, 9, 29, 0, 10)))
    fg = pd._etat()["figes"][IG][LUN_W.isoformat()]
    js = lire_message(f"{IG}-podium", fg["message"])
    check("semaine figée sans podium : la liste relue avant le gel, le message en 👑 ⭐ 🍄",
          fg.get("mode") == "sans_podium" and [x["m"] for x in appels_emojis(IG, depuis=n0)] == ["GET"]
          and titre(js) == T_FINAL and "<:kart_" not in desc(js) and "👑" in desc(js),
          (fg, appels_emojis(IG, depuis=n0), desc(js)[:300]))

    # f. le podium corrigé (VA US relu le lundi) : réécrit, donc relu lui aussi
    installer()
    for t_, act in ((m(2026, 9, 22, 12, 0), None), (m(2026, 9, 28, 0, 10), va2_muet),
                    (m(2026, 9, 28, 9, 0), None)):
        if act:
            act()
        a(t_)
    mid_p = pd._etat()["postes"][f"{IG}:{LUN_W}"]
    check("(départ) podium de 9h figé avec les têtes, primes retenues (un VA US sans relevé)",
          desc(lire_message(f"{IG}-podium", mid_p)).count("<:kart_") == 6
          and pd._etat()["figes"][IG][LUN_W.isoformat()].get("primes_attente"))
    oter("kart_peach")
    va2_revenu()
    n0 = len(DISCORD.appels)
    _, log = journal(lambda: [a(m(2026, 9, 28, 10, 0)), a(m(2026, 9, 28, 11, 10))])
    fg = pd._etat()["figes"][IG][LUN_W.isoformat()]
    js = lire_message(f"{IG}-podium", mid_p)
    check("podium corrigé sur place : la liste relue avant la réécriture, plus de tête morte",
          fg.get("corrige") and not fg.get("primes_attente")
          and [x["m"] for x in appels_emojis(IG, depuis=n0)] == ["GET"]
          and "<:kart_" not in desc(js) and "👑" in desc(js), (fg, appels_emojis(IG, depuis=n0)))

    # g. Twitter et Va IG sans la clé : aucune lecture (déjà prouvé octet pour
    # octet en section 9) ; et sans têtes dans le cache, rien à relire
    installer()
    DISCORD.refus_creation = (403, {"message": "Missing Permissions", "code": 50013})
    for t_ in (m(2026, 9, 22, 12, 0), m(2026, 9, 28, 0, 10)):
        a(t_)
    n0 = len(DISCORD.appels)
    a(m(2026, 9, 28, 9, 0))
    check("sans têtes posées (permission manquante) : le gel ne relit rien, il est déjà en 👑 ⭐ 🍄",
          not appels_emojis(IG, depuis=n0)
          and "👑" in desc(lire_message(f"{IG}-podium", pd._etat()["postes"][f"{IG}:{LUN_W}"])))

except Exception as _e:
    import traceback
    check("thème Mario : testable", False, repr(_e)[:200] + " " + traceback.format_exc()[-1500:])
finally:
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
