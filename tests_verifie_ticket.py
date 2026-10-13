"""Un ✅ Vérifié posé à la main ouvre le ticket du VA.

Propriétaire, 13/10/2026 : « quand je mets quelqu'un en vérifié ça doit lui
ouvrir un ticket automatiquement », « pour Twitter ça envoie à un des
managers et pour IG ça envoie à une des models aléatoire ».

Ici, le côté Va IG (cogs/welcome.py, _apres_verification) : porte de
vérification fermée, l'arrivée crée déjà le ticket et pose ✅ d'office ; un ✅
posé à la main plus tard sur un membre SANS ticket lance le parcours
d'arrivée (ticket dans la model qui a le moins de VA). Le côté Twitter et
Threads (tickets_discord.ouvrir_tickets_verifies) est dans
tests_managers_auto.py, section 16.

Lancer depuis la racine du dépôt : python tests_verifie_ticket.py
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import cogs.welcome as w                # noqa: E402
import tickets_discord as tk            # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:300]}]" if detail and not cond else ""))


IG, TH = "1505418484052394004", "1498948161039896586"
ROLE = "555"


class Role:
    def __init__(self, i):
        self.id = int(i)


class Guilde:
    def __init__(self, gid, salons=()):
        self.id = int(gid)
        self.name = "test"
        self._salons = set(salons)

    def get_channel(self, cid):
        return object() if cid in self._salons else None


def membre(gid, roles, il_y_a, uid=42, salons=()):
    return types.SimpleNamespace(id=uid, bot=False, guild=Guilde(gid, salons),
                                 roles=[Role(r) for r in roles],
                                 joined_at=datetime.now(timezone.utc) - il_y_a)


appels = []


class FauxCog:
    async def _accueillir(self, member, cfg):
        appels.append(member.id)


_sauve = (w._verif_porte, w._verif_config, w.load_users)
try:
    w._verif_porte = lambda g: None                       # Va IG : porte fermée
    w._verif_config = lambda g: {"role_verifie": ROLE} if str(g.id) in (IG, TH) else None
    fiches = {}
    w.load_users = lambda: fiches
    import cogs.user as _u
    _staff = _u._is_staff_member
    _u._is_staff_member = lambda m: False

    def lancer(before, after):
        appels.clear()
        asyncio.run(w.Welcome._apres_verification(FauxCog(), before, after))
        return list(appels)

    vieux = timedelta(hours=3)
    check("Va IG : ✅ posé à la main sur un membre sans ticket -> parcours d'arrivée (ticket)",
          lancer(membre(IG, [], vieux), membre(IG, [ROLE], vieux)) == [42])
    check("… pas dans les dix minutes qui suivent l'arrivée (pose d'office : _accueillir "
          "crée déjà le ticket, pas deux)",
          lancer(membre(IG, [], timedelta(minutes=2)),
                 membre(IG, [ROLE], timedelta(minutes=2))) == [])
    fiches["42"] = {"channel_id": 777}
    check("… pas s'il a déjà son ticket",
          lancer(membre(IG, [], vieux, salons=(777,)), membre(IG, [ROLE], vieux, salons=(777,))) == [])
    fiches.clear()
    check("… ni si le rôle était déjà là (pas un ajout)",
          lancer(membre(IG, [ROLE], vieux), membre(IG, [ROLE], vieux)) == [])
    _u._is_staff_member = lambda m: True
    check("… ni pour le staff", lancer(membre(IG, [], vieux), membre(IG, [ROLE], vieux)) == [])
    _u._is_staff_member = lambda m: False
    check("Threads (tickets_discord) : welcome n'ouvre rien, le tour des tickets s'en charge",
          TH in tk.SERVEURS_TICKETS
          and lancer(membre(TH, [], vieux), membre(TH, [ROLE], vieux)) == [])
    w._verif_config = lambda g: None
    check("un serveur sans vérification : rien",
          lancer(membre(IG, [], vieux), membre(IG, [ROLE], vieux)) == [])
finally:
    w._verif_porte, w._verif_config, w.load_users = _sauve
    try:
        _u._is_staff_member = _staff
    except NameError:
        pass

print(f"\nRESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
sys.exit(1 if FAILS else 0)
