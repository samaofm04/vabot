"""cogs/tgperso.py — Démarre le bot Telegram perso (tg_perso).

Aucune commande slash : le bot admin est déjà près du plafond Discord de
100 commandes, et tout se règle sur la page /tgperso du dashboard.
"""
from discord.ext import commands

import tg_perso
import tg_moi


class TGPerso(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Deux bots : Lola (tg_perso) et le bot perso du propriétaire (tg_moi).
        for mod in (tg_perso, tg_moi):
            try:
                mod.start()
            except Exception as e:
                print(f"[{mod.PREFIXE}] start: {e}", flush=True)

    def cog_unload(self):
        for mod in (tg_perso, tg_moi):
            try:
                mod.stop()
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(TGPerso(bot))
