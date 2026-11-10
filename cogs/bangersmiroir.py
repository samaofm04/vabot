# -*- coding: utf-8 -*-
"""Les bangers recopiés sur You US et You FR : la boucle.

Ce cog ne fait que TOURNER : toutes les dix minutes, un passage de
bangers_miroir.tour, qui porte toute la règle (quels salons, quelles cartes,
le journal) et se teste sans bot.

AUCUNE COMMANDE SLASH : le bot principal en a 100 sur 100.

SUR LE BOT PRINCIPAL (Ryuk) : c'est lui qui est sur You US et You FR, et lui
qui poste les bangers de Youl4b et de Va IG.

SEULEMENT SUR LA MACHINE DE PRODUCTION, comme cogs/alertes : chaque machine a
son propre data/. Armée aussi sur le Mac, la boucle aurait cru n'avoir rien
recopié et tout reposté une seconde fois.
"""
from __future__ import annotations

import asyncio
import os
import traceback

from discord.ext import commands, tasks

#: Le passage, en minutes. La publication du matin part à 9 h : la copie suit
#: dans les dix minutes.
PERIODE_MIN = 10
#: Après le démarrage : le bot principal finit de charger ses serveurs.
ATTENTE_DEMARRAGE_SEC = 120


def _machine_prod() -> bool:
    try:
        from web_upload import _machine_proprietaire
    except Exception:
        # site absent : la regle reste la meme, dite ici
        return os.environ.get("VA_MACHINE_PROD") == "1"
    return _machine_proprietaire("bangers-miroir")


class BangersMiroir(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if _machine_prod():
            self.boucle.start()

    def cog_unload(self):
        self.boucle.cancel()

    @tasks.loop(minutes=PERIODE_MIN)
    async def boucle(self):
        try:
            import bangers_miroir as bm
            await bm.tour(self.bot)
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
    await bot.add_cog(BangersMiroir(bot))
