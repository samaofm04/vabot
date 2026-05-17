import os
import sys
import faulthandler
import logging
import traceback
import discord
from discord.ext import commands
from dotenv import load_dotenv

faulthandler.enable(file=open("crash.log", "a", encoding="utf-8"))

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("PREFIX", "!")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", mode="a", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("vabot")

intents = discord.Intents.default()


class VABot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=PREFIX, intents=intents)

    async def setup_hook(self):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and not filename.startswith("_"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    log.info(f"Cog chargé: {filename}")
                except Exception as e:
                    log.error(f"Erreur chargement {filename}: {e}")
                    log.error(traceback.format_exc())


bot = VABot()


@bot.event
async def on_ready():
    log.info(f"Bot connecté en tant que {bot.user} (id: {bot.user.id})")
    log.info("Bot prêt - en attente de commandes")


@bot.event
async def on_disconnect():
    log.warning("Bot déconnecté du gateway")


@bot.event
async def on_resumed():
    log.info("Bot reconnecté au gateway")


@bot.command(name="sync")
@commands.is_owner()
async def sync_cmd(ctx):
    """Resynchronise les slash commands (à utiliser après avoir ajouté de nouvelles commandes)."""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"{len(synced)} commandes synchronisées.")
    except Exception as e:
        await ctx.send(f"Erreur: {e}")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN manquant dans .env")
    log.info("=== Démarrage du bot ===")
    try:
        bot.run(TOKEN, log_handler=None)
    except Exception:
        log.error("CRASH:")
        log.error(traceback.format_exc())
    log.info("=== Bot arrêté ===")
