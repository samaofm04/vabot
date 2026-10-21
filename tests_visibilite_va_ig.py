"""Visibilité des salons de Va IG : staff caché aux VA, ressources pour tous.

Audit du 20/10/2026 : la boucle d'entretien (cogs/outils.py) mettait TOUS les
salons de 🏠 ACCUEIL dans la liste blanche de l'isolation, salons staff
compris (arrivées, départs, annonces d'entretiens) : chaque arrivant y
recevait un accès à son nom. À l'inverse, heure-de-post, modele-a-suivre et
les deux vocaux, hors de ces catégories, étaient cachés aux 13 derniers
arrivés. Et vectorofm, 🛡️ Manager, était isolé comme un VA.

Lancer depuis la racine du dépôt : python tests_visibilite_va_ig.py
"""
from __future__ import annotations

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

import discord                          # noqa: E402

import cogs.outils as o                 # noqa: E402
import cogs.welcome as w                # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


IG = 1505418484052394004
VERIFIE = 1555740262767001710


class Role:
    def __init__(self, i, nom):
        self.id, self.name = i, nom


class Membre(discord.Member):
    """Un vrai discord.Member pour isinstance, sans état Discord."""
    def __init__(self, uid, nom, roles=(), bot=False, admin=False, guilde=None):
        self._f = dict(id=uid, name=nom, roles=list(roles), bot=bot, guild=guilde,
                       guild_permissions=discord.Permissions(administrator=admin))

    id = property(lambda s: s._f["id"])
    name = property(lambda s: s._f["name"])
    roles = property(lambda s: s._f["roles"])
    bot = property(lambda s: s._f["bot"])
    guild = property(lambda s: s._f["guild"])
    guild_permissions = property(lambda s: s._f["guild_permissions"])
    __hash__ = object.__hash__
    __eq__ = object.__eq__


class Salon:
    """Voit = ce que voit un membre qui n'a que ✅ Vérifié."""
    def __init__(self, cid, nom, voit, overwrites=None, categorie="🏠 ACCUEIL"):
        self.id, self.name, self._voit = cid, nom, voit
        self.category = types.SimpleNamespace(name=categorie)
        self._ow = dict(overwrites or {})
        self.appels = []

    def permissions_for(self, role):
        return discord.Permissions(view_channel=self._voit)

    @property
    def overwrites(self):
        return {k: discord.PermissionOverwrite(**{n: v for n, v in ow if v is not None})
                for k, ow in self._ow.items()}

    async def set_permissions(self, cible, *, overwrite=..., reason=None, **perms):
        if overwrite is ...:
            overwrite = discord.PermissionOverwrite(**perms)
        self.appels.append((cible, overwrite))
        if overwrite is None:
            self._ow.pop(cible, None)
        else:
            self._ow[cible] = overwrite


class Categorie(discord.CategoryChannel):
    def __init__(self, cid):
        self._fid = cid
    id = property(lambda s: s._fid)
    __hash__ = object.__hash__


class Guilde:
    def __init__(self, salons, roles, owner_id=1):
        self.id, self.name, self.owner_id = IG, "Va IG", owner_id
        self.channels = list(salons)
        self._roles = {r.id: r for r in roles}
        self.default_role = Role(IG, "@everyone")

    def get_role(self, rid):
        return self._roles.get(int(rid))

    def get_channel(self, cid):
        return next((c for c in self.channels if c.id == cid), None)


verifie = Role(VERIFIE, "✅ Vérifié")
manager = Role(1555968604032213102, "🛡️ Manager")
boss = Role(1505821464375328798, "BOSS")
alicia = Role(9, "Alicia")

cfg = {}
w.load_welcome_config = lambda: dict(cfg)
w.save_welcome_config = lambda c: (cfg.clear(), cfg.update(c))


def run(coro):
    return asyncio.run(coro)


# 1. salons_info : par le rôle ✅, toutes catégories, sauf /hidesalon
staff = Salon(10, "🚪・arrivées-sur-le-serveur", voit=False)
accueil = Salon(11, "👋・accueil", voit=True)
heure = Salon(12, "🕒・heure-de-post", voit=True)
cache = Salon(13, "💬・discussions", voit=True)
cat = Categorie(14)
g = Guilde([staff, accueil, heure, cache, cat], [verifie, manager, boss, alicia])
cfg.update({"extra_visible_channel_ids": [], "hidden_from_va_channel_ids": [13]})
ids = [c.id for c in o.salons_info(g)]
check("salons_info garde les salons que ✅ Vérifié voit, hors catégories d'accueil", ids == [11, 12], ids)
check("salons_info écarte le salon staff (BOSS seul)", 10 not in ids, ids)
check("salons_info ne reprend pas un salon caché par /hidesalon", 13 not in ids, ids)
check("le rôle des VA est ✅ Vérifié même porte fermée", o._role_des_va(g) is verifie)

# 2. est_encadrant
va = Membre(100, "dioplucky", [verifie, alicia], guilde=g)
vecto = Membre(101, "vectorofm", [verifie, alicia, manager], guilde=g)
proprio = Membre(1, "yous1m", [verifie], guilde=g)
luigi = Membre(102, "Luigi", bot=True, guilde=g)
chef = Membre(103, "chef", [boss], guilde=g)
admin = Membre(104, "admin", admin=True, guilde=g)
check("un VA n'est pas encadrant", not w.est_encadrant(va))
check("🛡️ Manager, BOSS, admin, propriétaire et bot sont encadrants",
      all(w.est_encadrant(m) for m in (vecto, chef, admin, proprio, luigi)))

# 3. l'isolation ne cache rien à un 🛡️ Manager, mais lui donne les salons d'aide
cfg.update({"hide_all_channels_from_va": True, "extra_visible_channel_ids": [11]})
for s in (staff, accueil, heure):
    s.appels.clear()
w.find_identity_channels = lambda guild, ident: []
run(w._isolate_va_and_grant(g, vecto, "alicia", 999))
refus = [(s.name, c) for s in (staff, accueil, heure) for c, ow in s.appels
         if ow is not None and ow.view_channel is False]
check("aucun refus de vue posé au 🛡️ Manager", not refus, refus)
check("le 🛡️ Manager reçoit les salons d'aide", any(c is vecto for c, _ in accueil.appels))
run(w._isolate_va_and_grant(g, va, "alicia", 999))
check("un VA reste isolé des salons publics hors liste", any(
    c is va and ow.view_channel is False for c, ow in heure.appels))

# 4. nettoyage : liste blanche purgée, accès des VA retirés, staff gardé
staff2 = Salon(20, "📢・annonces-entretiens", voit=False, overwrites={
    va: [("view_channel", True)], proprio: [("view_channel", True)],
    luigi: [("view_channel", True)], vecto: [("view_channel", True), ("send_messages", True)]})
verif = Salon(21, "🔐・vérification", voit=False, overwrites={va: [("view_channel", True)]})
spoofer = Salon(22, "spoofer", voit=False, overwrites={va: [("view_channel", True)]},
                categorie="🧰 Outils")
g2 = Guilde([staff2, verif, spoofer, accueil], [verifie, manager, boss, alicia])
cfg.clear()
cfg.update({"extra_visible_channel_ids": [11, 20, 21, 22, 777]})
orig_sleep = asyncio.sleep


async def _sans_attente(*a, **k):
    return None
o.asyncio.sleep = _sans_attente
try:
    bilan = run(o.nettoyer_salons_staff(g2))
finally:
    o.asyncio.sleep = orig_sleep
check("les salons staff sortent de la liste blanche, le reste y reste",
      cfg["extra_visible_channel_ids"] == [11, 22, 777], cfg)
check("un salon d'outils fermé à @everyone reste ouvert aux VA (liste blanche voulue)",
      va in spoofer._ow and not spoofer.appels, spoofer._ow)
check("l'accès du VA est retiré des deux salons staff",
      va not in staff2._ow and va not in verif._ow, bilan)
check("propriétaire et bot gardent leur accès", proprio in staff2._ow and luigi in staff2._ow)
check("le 🛡️ Manager garde son entrée", vecto in staff2._ow, staff2._ow)
check("bilan compté", bilan["acces_retires"] == 2 and sorted(bilan["retires"]) ==
      sorted(["📢・annonces-entretiens", "🔐・vérification"]), bilan)
bilan2 = run(o.nettoyer_salons_staff(g2))
check("le nettoyage est sans effet la 2e fois", not bilan2["retires"] and not bilan2["acces_retires"], bilan2)

# 5. déblocage d'un salon qui entre dans la liste (comme /showsalon)
heure3 = Salon(30, "🕒・heure-de-post", voit=True, overwrites={
    va: [("view_channel", False)], vecto: [("view_channel", False)]})
n = run(w.debloquer_pour_les_va(heure3, "test"))
check("les refus des VA isolés sont levés", n == 2 and all(
    ow.view_channel is True for ow in heure3.overwrites.values()), heure3._ow)

# 6. /hidesalon et /showsalon tiennent la liste des salons cachés
cog = w.Welcome.__new__(w.Welcome)


async def _admin(self, inter):
    return True
w.Welcome.require_admin = _admin


class Reponse:
    async def defer(self, **k):
        pass


class Suite:
    async def send(self, *a, **k):
        pass


def interaction():
    return types.SimpleNamespace(guild=types.SimpleNamespace(get_member=lambda i: None),
                                 response=Reponse(), followup=Suite())


cfg.clear()
cfg.update({"extra_visible_channel_ids": [12]})
w.load_users = lambda: {}
salon = types.SimpleNamespace(id=12, mention="#heure", overwrites={})
run(w.Welcome.hidesalon.callback(cog, interaction(), salon))
check("/hidesalon retire de la liste et mémorise", cfg["extra_visible_channel_ids"] == []
      and cfg["hidden_from_va_channel_ids"] == [12], cfg)
run(w.Welcome.showsalon.callback(cog, interaction(), salon))
check("/showsalon remet dans la liste et oublie le cache", cfg["extra_visible_channel_ids"] == [12]
      and cfg["hidden_from_va_channel_ids"] == [], cfg)

print(f"\n{len(OKS)} OK, {len(FAILS)} échec(s)")
sys.exit(1 if FAILS else 0)
