# -*- coding: utf-8 -*-
"""Le rôle d'une model dans le pseudo (« yous1m (AMELIA) ») : les événements.

Ce cog ne fait qu'ÉCOUTER : un rôle donné ou retiré, un pseudo changé, et il
demande à pseudo_model.py — qui porte toute la règle et se teste sans bot —
de poser le bon pseudo. Toutes les trente minutes, et au démarrage, il
repasse sur tous les membres : un changement de rôle fait pendant un
redémarrage du bot (un par déploiement) n'arrive jamais comme événement.

AUCUNE COMMANDE SLASH : le bot principal en a 100 sur 100.

SUR LE BOT PRINCIPAL (Ryuk) : c'est lui qui est sur You FR, en administrateur.
Aucun état sur le disque : poser deux fois le même pseudo ne change rien.
"""
from __future__ import annotations

import asyncio
import traceback

from discord.ext import commands, tasks

#: Le passage de rattrapage, en minutes.
PERIODE_MIN = 30
#: Après le démarrage : le bot finit de charger les membres de ses serveurs.
ATTENTE_DEMARRAGE_SEC = 60


class PseudoModel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.boucle.start()

    def cog_unload(self):
        self.boucle.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
            import pseudo_model as pm
            if not pm.serveur(getattr(after, "guild", None)):
                return
            # Seuls les rôles et le pseudo comptent : l'événement part aussi
            # pour une exclusion temporaire ou un avatar de serveur.
            if (list(getattr(before, "roles", []) or []) == list(getattr(after, "roles", []) or [])
                    and getattr(before, "nick", None) == getattr(after, "nick", None)):
                return
            await pm.appliquer(after)
        except Exception:
            traceback.print_exc()

    @tasks.loop(minutes=PERIODE_MIN)
    async def boucle(self):
        try:
            import pseudo_model as pm
            for guild in list(getattr(self.bot, "guilds", []) or []):
                if pm.serveur(guild):
                    await pm.passer(guild)
        except Exception:
            # une exception non attrapee tue une tasks.loop sans rien dire
            traceback.print_exc()

    @boucle.before_loop
    async def _avant(self):
        try:
            await self.bot.wait_until_ready()
            await asyncio.sleep(ATTENTE_DEMARRAGE_SEC)
        except Exception:
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(PseudoModel(bot))
