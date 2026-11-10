# -*- coding: utf-8 -*-
"""tests_pseudo_model.py — le rôle d'une model s'écrit dans le pseudo.

Propriétaire, 10/11/2026, devant You FR : « tu peux créer un rôle par model …
y a le rôle Amelia, Lola etc. et … ça change leur name dans le serveur, genre
yous1m (AMELIA) ».

Ce que ce fichier prouve, avec de faux membres (aucun réseau, rien d'écrit) :
  1. Le serveur : You FR seul ; ses models sont celles de ses salons banger.
  2. La règle du pseudo : une model, plusieurs, l'ordre, les 32 signes, le
     rôle décoré ou accentué ; sans rôle, le pseudo est rendu s'il est de
     notre forme et laissé s'il a été choisi à la main.
  3. L'application : posé, rendu, déjà bon ; un bot, un autre serveur, le
     propriétaire (Discord l'interdit) et un rôle trop haut sont passés ET
     dits ; aucune boucle d'événements.
  4. Le cog : il réagit aux rôles et au pseudo, repasse sur tous les
     membres, ne déclare aucune commande, est sur le bot principal.

Lancement : python tests_pseudo_model.py
"""
from __future__ import annotations

import ast
import asyncio
import io
import logging
import os
import pathlib
import sys
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                          # noqa: E402

import bangers as bg                    # noqa: E402
import guild_features as gf             # noqa: E402
import pseudo_model as pm               # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


ns = types.SimpleNamespace
YOU_FR, YOU_US = int(gf.YOU_FR_GUILD_ID), int(gf.YOU_US_GUILD_ID)
YOUCHAM, VA_IG = 1565640097146347533, 1505418484052394004
PROPRIO = 479005370438778891
MODELS = tuple(bg.MODELS_FR)


class Rep:
    status, reason = 403, "Forbidden"


class Membre:
    _n = 100

    def __init__(self, guild, name, roles=(), nick=None, bot=False, uid=None, interdit=False):
        Membre._n += 1
        self.id = uid or Membre._n
        self.guild, self.name, self.nick, self.bot = guild, name, nick, bot
        self.roles = [ns(name=r) for r in roles]
        self.edits = []
        self.interdit = interdit

    async def edit(self, nick=None, reason=None):
        self.edits.append(nick)
        if self.interdit:
            raise discord.Forbidden(Rep(), "Missing Permissions")
        self.nick = nick


def guilde(gid, nom="You FR"):
    g = ns(id=gid, name=nom, owner_id=PROPRIO, members=[])
    return g


def courir(coro):
    return asyncio.run(coro)


class Ecoute(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lignes = []

    def emit(self, rec):
        self.lignes.append(rec.getMessage())


ECOUTE = Ecoute()
pm.log.addHandler(ECOUTE)
pm.log.setLevel(logging.INFO)

# ═══════════════════════════════════════════════════ 1. le serveur ══
print("1. Le serveur")
FR, US = guilde(YOU_FR), guilde(YOU_US, "You US")
check("You FR seul (ni You US, ni YouCham, ni Va IG, ni rien)",
      pm.serveur(FR) and not any(pm.serveur(guilde(g)) for g in (YOU_US, YOUCHAM, VA_IG))
      and not pm.serveur(None) and gf.PSEUDO_MODEL == {gf.YOU_FR_GUILD_ID})
check("ses models : celles de ses salons banger (bangers.MODELS_FR), dans l'ordre",
      pm.models_du_serveur(FR) == MODELS and len(MODELS) == 6)
check("un serveur d'un autre marché n'a aucune model à écrire", pm.models_du_serveur(US) == ())
_src = (BOT / "pseudo_model.py").read_text(encoding="utf-8") + (BOT / "cogs" / "pseudomodel.py").read_text(encoding="utf-8")
check("aucun id de serveur recopié dans le module ni dans le cog",
      str(YOU_FR) not in _src and str(YOU_US) not in _src)

# ═══════════════════════════════════════════════════ 2. la règle ══
print("2. La règle du pseudo")


def voulu(name, roles=(), nick=None):
    return pm.pseudo_voulu(Membre(FR, name, roles, nick), MODELS)


check("une model : « yous1m (AMELIA) »", voulu("yous1m", ["Amelia"]) == (True, "yous1m (AMELIA)"))
check("le nom d'utilisateur, pas un pseudo déjà posé à la main",
      voulu("yous1m", ["Lola"], nick="Le Boss") == (True, "yous1m (LOLA)"))
check("plusieurs models : dans l'ordre des models, pas celui des rôles",
      voulu("bob", ["Lola", "Amelia"]) == (True, "bob (AMELIA/LOLA)"))
check("rôle décoré ou accentué : « 🩷 Amélia », « ・EMMA » sont reconnus",
      voulu("bob", ["🩷 Amélia", "・EMMA"]) == (True, "bob (AMELIA/EMMA)"))
check("les autres rôles ne comptent pas (Jailbreak FR, Manager, Amelia VA)",
      voulu("bob", ["Jailbreak FR", "🛡️ Manager", "Amelia VA", "Emma"]) == (True, "bob (EMMA)"))
check("déjà le bon pseudo : rien à changer",
      voulu("bob", ["Emma"], nick="bob (EMMA)") == (False, "bob (EMMA)"))
long_ = "un_tres_tres_long_pseudo_discord_32"[:32]
ch, v = voulu(long_, ["Amelia"])
check("32 signes au plus : le nom est coupé, la model reste entière",
      ch and len(v) <= 32 and v.endswith(" (AMELIA)") and v.startswith(long_[:10]), v)
ch, v = voulu("yous1m", [m.capitalize() for m in MODELS])
check("toutes les models : les premières, puis « +N », sous 32 signes",
      ch and v == "yous1m (AMELIA/EMMA/SARAH+3)" and len(v) <= 32, v)
ch, v = voulu(long_, [m.capitalize() for m in MODELS])
check("… même avec un nom très long : au moins 8 signes du nom, la model d'abord",
      ch and len(v) <= 32 and v.startswith(long_[:8]) and "(AMELIA" in v and v.endswith(")"), v)
check("sans rôle de model, pseudo de notre forme : rendu",
      voulu("bob", [], nick="bob (AMELIA)") == (True, None)
      and voulu("bob", ["Jailbreak FR"], nick="bob (AMELIA/LOLA)") == (True, None)
      and voulu("bob", [], nick="bob (AMELIA/EMMA+3)") == (True, None))
check("sans rôle de model, pseudo choisi à la main : laissé",
      voulu("bob", [], nick="Bobby") == (False, "Bobby")
      and voulu("bob", [], nick="bob (PARIS)") == (False, "bob (PARIS)")
      and voulu("bob", [], nick="bob (amelia)") == (False, "bob (amelia)")
      and voulu("bob", [], nick=None) == (False, None))
check("un rôle retiré parmi deux : le pseudo suit",
      voulu("bob", ["Lola"], nick="bob (AMELIA/LOLA)") == (True, "bob (LOLA)"))

# ═══════════════════════════════════════════════ 3. l'application ══
print("3. Poser le pseudo")
m = Membre(FR, "bob", ["Amelia"])
check("posé : « bob (AMELIA) », une seule modification",
      courir(pm.appliquer(m)) == "pose" and m.nick == "bob (AMELIA)" and m.edits == ["bob (AMELIA)"])
check("rejoué : déjà bon, aucun appel à Discord",
      courir(pm.appliquer(m)) == "deja" and len(m.edits) == 1)
m.roles = []
check("rôle retiré : le pseudo est rendu",
      courir(pm.appliquer(m)) == "rendu" and m.nick is None and m.edits[-1] is None)
m2 = Membre(FR, "zoe", [], nick="Zoé la boss")
check("sans rôle et pseudo à la main : pas touché", courir(pm.appliquer(m2)) == "deja" and not m2.edits)
b = Membre(FR, "Ryuk.exe", ["Amelia"], bot=True)
check("un bot n'est jamais renommé", courir(pm.appliquer(b)) == "hors" and not b.edits)
for g, nom in ((US, "You US"), (guilde(YOUCHAM, "YouCham"), "YouCham"), (guilde(VA_IG, "Va IG"), "Va IG")):
    x = Membre(g, "bob", ["Amelia"])
    check(f"{nom} : personne n'y est renommé, même avec un rôle « Amelia »",
          courir(pm.appliquer(x)) == "hors" and not x.edits)
ECOUTE.lignes.clear()
p = Membre(FR, "yous1m", ["Amelia"], uid=PROPRIO)
r1, r2 = courir(pm.appliquer(p)), courir(pm.appliquer(p))
check("le propriétaire : Discord l'interdit, AUCUN appel, dit une fois avec le pseudo à poser",
      r1 == r2 == "proprietaire" and not p.edits
      and len([l for l in ECOUTE.lignes if "propriétaire" in l and "yous1m (AMELIA)" in l]) == 1, ECOUTE.lignes)
ECOUTE.lignes.clear()
h = Membre(FR, "chef", ["Emma"], interdit=True)
r1, r2 = courir(pm.appliquer(h)), courir(pm.appliquer(h))
check("rôle au-dessus du bot : refus compté et dit une fois, pseudo laissé",
      r1 == r2 == "refuse" and h.nick is None
      and len([l for l in ECOUTE.lignes if "refuse de renommer" in l]) == 1, ECOUTE.lignes)


class Casse(Membre):
    async def edit(self, nick=None, reason=None):
        raise RuntimeError("Discord injoignable")


check("une panne ne lève pas : « rate »", courir(pm.appliquer(Casse(FR, "bob", ["Lola"]))) == "rate")

# le passage sur tout le serveur
FR.members = [Membre(FR, "a", ["Amelia"]), Membre(FR, "b", ["Lola", "Emma"]), Membre(FR, "c", []),
              Membre(FR, "d", [], nick="d (SARAH)"), Membre(FR, "Rem.exe", ["Emma"], bot=True),
              Membre(FR, "yous1m", ["Julia"], uid=PROPRIO)]
SOMMEILS = []


async def _dormir(s):
    SOMMEILS.append(s)


bilan = courir(pm.passer(FR, dormir=_dormir))
check("passage : chacun traité et COMPTÉ (2 posés, 1 rendu, 1 déjà, 1 bot, le propriétaire)",
      bilan == {"pose": 2, "rendu": 1, "deja": 1, "hors": 1, "proprietaire": 1}, bilan)
check("… les pseudos posés", [m_.nick for m_ in FR.members[:4]] == ["a (AMELIA)", "b (EMMA/LOLA)", None, None])
check("… un répit après chaque modification seulement", SOMMEILS == [0.5, 0.5, 0.5], SOMMEILS)
check("second passage : plus rien à faire",
      courir(pm.passer(FR, dormir=_dormir)) == {"deja": 4, "hors": 1, "proprietaire": 1})
check("passage sur un serveur non concerné : rien", courir(pm.passer(US)) == {})

# ═══════════════════════════════════════════════════════ 4. le cog ══
print("4. Le cog")
import cogs.pseudomodel as cpm  # noqa: E402

check("zéro commande slash", not cpm.PseudoModel.__cog_app_commands__)


async def _evenements():
    cog = cpm.PseudoModel(ns(guilds=[FR]))
    arme = cog.boucle.is_running()
    cog.cog_unload()
    avant = Membre(FR, "eve", [])
    apres = Membre(FR, "eve", ["Alicia"], uid=avant.id)
    await cog.on_member_update(avant, apres)                       # un rôle donné
    n1 = list(apres.edits)
    await cog.on_member_update(apres, apres)                       # l'écho de notre modification
    n2 = list(apres.edits)
    libre = Membre(FR, "eve", ["Alicia"], nick="Eve la star", uid=avant.id)
    await cog.on_member_update(apres, libre)                       # elle change son pseudo
    autre = Membre(US, "eve", ["Alicia"])
    await cog.on_member_update(Membre(US, "eve", []), autre)       # autre serveur
    sans = Membre(FR, "eve", ["Alicia"], nick="eve (ALICIA)")
    meme = Membre(FR, "eve", ["Alicia"], nick="eve (ALICIA)")
    meme.roles = sans.roles
    await cog.on_member_update(sans, meme)                         # ni rôle ni pseudo n'ont bougé
    return arme, n1, n2, libre, autre, meme


arme, n1, n2, libre, autre, meme = courir(_evenements())
check("la boucle de rattrapage est armée au chargement", arme)
check("un rôle donné : le pseudo est posé tout de suite", n1 == ["eve (ALICIA)"])
check("l'écho de notre propre modification ne reboucle pas", n2 == ["eve (ALICIA)"])
check("un pseudo changé à la main revient à celui du rôle",
      libre.edits == ["eve (ALICIA)"] and libre.nick == "eve (ALICIA)")
check("un autre serveur : aucun appel", not autre.edits)
check("ni rôle ni pseudo n'ont bougé : aucun appel", not meme.edits)


async def _boucle():
    FR2 = guilde(YOU_FR)
    FR2.members = [Membre(FR2, "k", ["Sarah"])]
    US2 = guilde(YOU_US, "You US")
    US2.members = [Membre(US2, "k", ["Sarah"])]
    cog = cpm.PseudoModel(ns(guilds=[US2, FR2]))
    cog.cog_unload()
    await cpm.PseudoModel.boucle.coro(cog)
    return FR2.members[0].nick, US2.members[0].nick


check("le passage périodique : You FR rattrapé, You US pas touché",
      courir(_boucle()) == ("k (SARAH)", None))
arbre = ast.parse((BOT / "main.py").read_text(encoding="utf-8"))
listes = {n.targets[0].id: [e.value for e in n.value.elts] for n in arbre.body
          if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
          and n.targets[0].id in ("MAIN_COGS", "ADMIN_COGS")}
check("main.py : sur le bot principal, une seule fois, pas sur le bot admin",
      listes["MAIN_COGS"].count("pseudomodel") == 1 and "pseudomodel" not in listes["ADMIN_COGS"])
_main = (BOT / "main.py").read_text(encoding="utf-8")
_bloc = _main.split('"bangersmiroir",')[1].split('"pseudomodel",')[0]
check("main.py : la fin de la liste reste celle du patch du VPS, le commentaire ne nomme aucune liste",
      listes["MAIN_COGS"][-1] == "bases_identite" and "MAIN_COGS" not in _bloc
      and "ADMIN_COGS" not in _bloc and "]" not in _bloc, _bloc)

print("=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
print("=" * 70)
for x in FAILS:
    print("  - " + x)
sys.exit(1 if FAILS else 0)
