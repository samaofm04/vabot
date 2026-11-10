# -*- coding: utf-8 -*-
"""tests_liens_you_fr.py — le lien GMS d'une model suit les rôles de Va IG ET de You FR.

10/11/2026 : à la demande du propriétaire, quatre liens FR ont été créés pour
des VA de You FR (fenoainir Amelia, priscah0017_30005 Emma, eniassy_83352
Lola, dioplucky Alicia). Sur Va IG, ces quatre n'ont que le rôle Alicia : les
liens Amelia, Emma et Lola ont été coupés dans la minute (« role amelia
retire »), car seul Va IG était lu (cogs/welcome._liens_suivent).

Ce que ce fichier prouve, sans réseau et sans rien écrire dans le vrai data/ :
  1. models_tous_serveurs : les rôles de Va IG, puis ceux de You FR ; un VA
     absent de You FR garde la règle d'avant ; une erreur aussi.
  2. aligner, avec ces models : le lien Amelia coupé « par rôle » revient en
     service ; un lien d'une model portée nulle part reste coupé ; un lien
     coupé à la main n'est pas rallumé.
  3. Le cog des pseudos : un rôle changé sur You FR relance tout de suite le
     suivi des liens sur Va IG, pour ce VA seul.

Lancement : python tests_liens_you_fr.py
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

VRAI = BOT / "data" / "liens_va_fr.json"
AVANT = VRAI.stat().st_mtime if VRAI.exists() else None

import guild_features as gf             # noqa: E402
import liens_fr                         # noqa: E402
from cogs import welcome as W           # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


ns = types.SimpleNamespace
VA_IG, YOU_FR, YOU_US = 1505418484052394004, int(gf.YOU_FR_GUILD_ID), int(gf.YOU_US_GUILD_ID)
FENO, AUTRE = 1561628437938970677, 4242
MODELS = ("amelia", "emma", "sarah", "julia", "lola", "alicia")


class Guilde:
    def __init__(self, gid, membres=(), categories=()):
        self.id, self.name = gid, str(gid)
        self.members = list(membres)
        self.categories = [ns(name=c) for c in categories]
        for m in self.members:
            m.guild = self

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)


def membre(uid, name, roles):
    return ns(id=uid, name=name, bot=False, guild=None,
              roles=[ns(name=r, position=10 - i) for i, r in enumerate(roles)])


def serveurs(feno_va_ig=("Alicia",), feno_you_fr=("Amelia",), autre_you_fr=True):
    va_ig = Guilde(VA_IG, [membre(FENO, "fenoainir", feno_va_ig), membre(AUTRE, "autre", ("Lola",))],
                   categories=MODELS)
    you = Guilde(YOU_FR, [membre(FENO, "fenoainir", feno_you_fr)]
                 + ([membre(AUTRE, "autre", ("Lola",))] if autre_you_fr else []))
    us = Guilde(YOU_US, [membre(FENO, "fenoainir", ("Amelia", "Emma"))])
    return ns(guilds=[va_ig, you, us]), va_ig, you


# ── 1. models_tous_serveurs ───────────────────────────────────────────────
print("\n── 1. models_tous_serveurs")
bot, va_ig, you = serveurs()
feno = va_ig.get_member(FENO)
check("fenoainir : Alicia (Va IG) puis Amelia (You FR)",
      W.models_tous_serveurs(bot, feno) == ["alicia", "amelia"], W.models_tous_serveurs(bot, feno))
check("Va IG seul (models_du_membre) ne donnait qu'Alicia", W.models_du_membre(feno) == ["alicia"])
check("You US (pas de rôle de model dans le pseudo) n'ajoute rien",
      "emma" not in W.models_tous_serveurs(bot, feno))
bot2, va_ig2, _y = serveurs(feno_you_fr=("Amelia", "Alicia"))
check("même model sur les deux serveurs : une fois",
      W.models_tous_serveurs(bot2, va_ig2.get_member(FENO)) == ["alicia", "amelia"])
bot3, va_ig3, you3 = serveurs()
you3.members = [m for m in you3.members if m.id != FENO]
check("absent de You FR : la règle d'avant (Va IG seul)",
      W.models_tous_serveurs(bot3, va_ig3.get_member(FENO)) == ["alicia"])
import pseudo_model as pm               # noqa: E402
_vrai = pm.models_du_serveur
pm.models_du_serveur = lambda g: (_ for _ in ()).throw(RuntimeError("panne"))
check("You FR illisible : la règle d'avant, sans planter",
      W.models_tous_serveurs(bot, feno) == ["alicia"])
pm.models_du_serveur = _vrai

# ── 2. aligner avec ces models ─────────────────────────────────────────────
print("\n── 2. aligner")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="tst_liens_you_fr_"))
liens_fr.ETAT = TMP / "liens_va_fr.json"
import safe_json                        # noqa: E402
safe_json.write(liens_fr.ETAT, {
    "liens": {f"{FENO}:amelia": {"link_id": "lnk_am", "pseudo": "fenoainir", "model": "amelia"},
              f"{FENO}:alicia": {"link_id": "lnk_al", "pseudo": "fenoainir", "model": "alicia"},
              f"{FENO}:lola": {"link_id": "lnk_lo", "pseudo": "fenoainir", "model": "lola"},
              f"{FENO}:emma": {"link_id": "lnk_em", "pseudo": "fenoainir", "model": "emma"}},
    "coupes_role": {"lnk_am": {"nom": "Amelia VA 49 @fenoainir"},
                    "lnk_lo": {"nom": "Lola VA 1 @fenoainir"}}})
EQUIPE = [{"id": "lnk_am", "display_name": "Amelia VA 49 @fenoainir", "status": "inactive"},
          {"id": "lnk_al", "display_name": "Alicia VA 9 @fenoainir", "status": "active"},
          {"id": "lnk_lo", "display_name": "Lola VA 1 @fenoainir", "status": "inactive"},
          {"id": "lnk_em", "display_name": "Emma VA 2 @fenoainir", "status": "inactive"}]
liens_fr._liens_equipe = lambda force=False, strict=False: EQUIPE
import gms                              # noqa: E402
APPELS = []
gms.enable_link = lambda lid: APPELS.append(("on", lid)) or {"ok": True}
gms.disable_link = lambda lid: APPELS.append(("off", lid)) or {"ok": True}
faits = liens_fr.aligner([(FENO, "fenoainir", W.models_tous_serveurs(bot, feno))])
check("le lien Amelia coupé par rôle revient en service (rôle sur You FR)",
      ("on", "lnk_am") in APPELS, APPELS)
check("Lola (coupé par rôle, rôle porté nulle part) reste coupé", ("on", "lnk_lo") not in APPELS)
check("Emma coupé à la main (pas dans coupes_role) n'est pas rallumé", ("on", "lnk_em") not in APPELS)
check("Alicia, en service et voulu, n'est pas touché", ("off", "lnk_al") not in APPELS)
check("une seule bascule", len(APPELS) == 1 and len(faits) == 1 and faits[0]["ok"], (APPELS, faits))
APPELS.clear()
EQUIPE[0]["status"] = "active"
liens_fr.aligner([(FENO, "fenoainir", W.models_du_membre(feno))])
check("pour mémoire : avec Va IG seul, Amelia aurait été recoupé", ("off", "lnk_am") in APPELS, APPELS)

# ── 3. Le cog des pseudos relance le suivi sur Va IG ─────────────────────
print("\n── 3. Le cog")
from cogs import pseudomodel as cpm     # noqa: E402

APPELS_W = []


class FauxWelcome:
    async def _liens_suivent(self, guild, uids=None):
        APPELS_W.append((guild.id, list(uids or [])))


async def _scenario():
    bot, va_ig, you = serveurs()
    bot.get_cog = lambda nom: FauxWelcome() if nom == "Welcome" else None
    cog = cpm.PseudoModel.__new__(cpm.PseudoModel)
    cog.bot, cog._taches = bot, set()
    cog._liens_va_ig(you, you.get_member(FENO))
    us = bot.guilds[2]
    cog._liens_va_ig(us, us.get_member(FENO))
    seul = membre(999, "pas_sur_va_ig", ("Emma",))
    you.members.append(seul)
    cog._liens_va_ig(you, seul)
    await asyncio.sleep(0.05)


asyncio.new_event_loop().run_until_complete(_scenario())
check("rôle changé sur You FR : suivi relancé sur Va IG pour ce VA seul",
      APPELS_W == [(VA_IG, [FENO])], APPELS_W)
src = (BOT / "cogs" / "pseudomodel.py").read_text(encoding="utf-8")
check("le cog appelle ce relais quand les rôles changent",
      "self._liens_va_ig(guild, after)" in src)
wsrc = (BOT / "cogs" / "welcome.py").read_text(encoding="utf-8")
check("welcome._liens_suivent passe models_tous_serveurs à aligner",
      "models_tous_serveurs(self.bot, m)" in wsrc)

check("vrai data/liens_va_fr.json intact",
      (VRAI.stat().st_mtime if VRAI.exists() else None) == AVANT)

print(f"\n{len(OKS)} OK, {len(FAILS)} FAIL")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  - " + f)
sys.exit(1 if FAILS else 0)
