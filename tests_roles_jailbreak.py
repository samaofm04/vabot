"""Va IG : plus aucun rôle Jailbreak.

Propriétaire, 13/10/2026 : « remove le menu jb à tout le monde », « y a des
mecs avec un rôle jailbreak, faut leur remove ». Relevé le même jour : 150
membres de Va IG avaient « Jailbreak FR » (posé à chaque ticket par
appliquer_roles_marche), un avait « Jailbreak ».

Vérifié ici, sans Discord (membres et rôles faux) :
  1. retirer_roles_jailbreak : Va IG, tous les rôles Jailbreak partent, les
     autres restent ; bots épargnés ; un échec compté ; ailleurs, rien ;
  2. appliquer_roles_marche ne pose ni ne crée plus rien sur Va IG ;
  3. marche_du_membre : sur Va IG, « fr » sans rôle (avant : « us », menu US) ;
     ailleurs, les rôles décident comme avant ;
  4. la boucle des 10 minutes l'appelle, serveur par serveur.

Lancer depuis la racine du dépôt : python tests_roles_jailbreak.py
"""
from __future__ import annotations

import ast
import asyncio
import io
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

import cogs.welcome as w                # noqa: E402
import cogs.user as u                   # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


IG, YOUL = 1505418484052394004, 1535758943324999711


class Role:
    def __init__(self, nom):
        self.name = nom

    def __repr__(self):
        return self.name


JB, JBFR, JBUS, AMELIA, VERIF = (Role("Jailbreak"), Role("Jailbreak FR"), Role("Jailbreak US"),
                                 Role("Amelia"), Role("✅ Vérifié"))


class Membre:
    def __init__(self, i, roles, bot=False, guilde=None, casse=False):
        self.id, self.roles, self.bot, self.guild, self.casse = i, list(roles), bot, guilde, casse
        self.retraits = []

    async def remove_roles(self, *roles, reason=None):
        if self.casse:
            raise RuntimeError("403")
        self.retraits.append(roles)
        self.roles = [r for r in self.roles if r not in roles]

    async def add_roles(self, *roles, reason=None):
        raise AssertionError("aucun rôle ne doit être posé ici")


def guilde(gid, membres):
    g = types.SimpleNamespace(id=gid, members=membres, roles=[JB, JBFR, JBUS, AMELIA])

    async def create_role(**kw):
        raise AssertionError("aucun rôle ne doit être créé ici")
    g.create_role = create_role
    for m in membres:
        m.guild = g
    return g


_dormir = w.asyncio.sleep
w.asyncio.sleep = lambda *_a, **_k: _dormir(0)
try:
    # ------------------------------------------------------------------ 1
    print("\n— 1. le retrait")
    a = Membre(1, [JBFR, AMELIA, VERIF])
    b = Membre(2, [JB, JBFR])
    c = Membre(3, [AMELIA])
    robot = Membre(4, [JBFR], bot=True)
    casse = Membre(5, [JBUS], casse=True)
    g = guilde(IG, [a, b, c, robot, casse])
    bil = asyncio.run(w.retirer_roles_jailbreak(g))
    check("Va IG : Jailbreak, Jailbreak FR, Jailbreak US partent ; la model et ✅ restent",
          a.roles == [AMELIA, VERIF] and b.roles == [] and c.roles == [AMELIA], (a.roles, b.roles))
    check("un membre sans rôle Jailbreak : aucun appel ; un bot : épargné",
          not c.retraits and robot.roles == [JBFR] and not robot.retraits)
    check("un refus de Discord est compté, les autres passent",
          bil["retires"] == 2 and len(bil["rates"]) == 1, bil)
    check("second passage : plus rien à faire",
          asyncio.run(w.retirer_roles_jailbreak(guilde(IG, [a, b, c])))["retires"] == 0)
    y = Membre(6, [JBUS])
    check("Youl4b (rôle de marché utile là-bas) : rien",
          asyncio.run(w.retirer_roles_jailbreak(guilde(YOUL, [y])))["retires"] == 0 and y.roles == [JBUS])

    # ------------------------------------------------------------------ 2
    print("\n— 2. plus de pose")
    _users = w.load_users
    try:
        w.load_users = lambda: {"7": {"identity": "amelia"}}
        n = Membre(7, [AMELIA])
        r = asyncio.run(w.appliquer_roles_marche(guilde(IG, [n]), n))
    finally:
        w.load_users = _users
    check("appliquer_roles_marche sur Va IG : rien posé, aucun rôle créé", r == (0, 0, 0) and n.roles == [AMELIA])

    # ------------------------------------------------------------------ 3
    print("\n— 3. le marché du VA")
    check("Va IG sans rôle : « fr » (avant : « us », le panneau passait en US)",
          u.marche_du_membre(Membre(8, [AMELIA], guilde=types.SimpleNamespace(id=IG))) == "fr")
    check("Va IG même avec un rôle US resté : « fr »",
          u.marche_du_membre(Membre(9, [JBUS], guilde=types.SimpleNamespace(id=IG))) == "fr")
    check("ailleurs, les rôles décident comme avant (FR, US, et « us » par défaut)",
          u.marche_du_membre(Membre(10, [JBFR], guilde=types.SimpleNamespace(id=YOUL))) == "fr"
          and u.marche_du_membre(Membre(11, [JBUS], guilde=types.SimpleNamespace(id=YOUL))) == "us"
          and u.marche_du_membre(Membre(12, [], guilde=types.SimpleNamespace(id=YOUL))) == "us")
finally:
    w.asyncio.sleep = _dormir

# ------------------------------------------------------------------ 4
print("\n— 4. la boucle")
src = (BOT / "cogs" / "welcome.py").read_text(encoding="utf-8")
arbre = ast.parse(src)
f = next(n for n in ast.walk(arbre) if isinstance(n, ast.AsyncFunctionDef)
         and n.name == "auto_secure_general_channels")
corps = ast.get_source_segment(src, f)
check("la boucle des 10 minutes retire les rôles, serveur par serveur, dans son propre try",
      "await retirer_roles_jailbreak(guild)" in corps
      and corps.rindex("for guild in self.bot.guilds:") < corps.index("await verrouiller_bangers(guild)")
      < corps.index("await retirer_roles_jailbreak(guild)"))

print(f"\nRESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
