"""cogs/tgperso.py — Démarre le bot Telegram perso (tg_perso).

Aucune commande slash : le bot admin est déjà près du plafond Discord de
100 commandes, et tout se règle sur la page /tgperso du dashboard.
"""
from discord.ext import commands

import tg_perso


class TGPerso(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            tg_perso.start()
        except Exception as e:
            print(f"[tgperso] start: {e}", flush=True)

    def cog_unload(self):
        try:
            tg_perso.stop()
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(TGPerso(bot))
