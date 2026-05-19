import os
import logging
import traceback
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("PREFIX", "!")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("vabot")

intents = discord.Intents.default()
intents.members = True  # necessaire pour on_member_join (welcome auto)


class VABot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=PREFIX, intents=intents)

    async def setup_hook(self):
        for filename in sorted(os.listdir("./cogs")):
            if filename.endswith(".py") and not filename.startswith("_"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    log.info(f"Cog charge: {filename}")
                except Exception as e:
                    log.error(f"Erreur chargement {filename}: {e}")
                    log.error(traceback.format_exc())
        try:
            synced = await self.tree.sync()
            log.info(f"{len(synced)} slash commands synchronisees")
        except Exception as e:
            log.warning(f"Sync au demarrage echoue (rate-limit ?): {e}")


bot = VABot()


@bot.event
async def on_ready():
    log.info(f"Bot connecte en tant que {bot.user} (id: {bot.user.id})")


@bot.tree.command(name="sync", description="[OWNER] Resync les slash commands")
async def sync_slash(interaction: discord.Interaction):
    app = await bot.application_info()
    if interaction.user.id != app.owner.id:
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        await interaction.followup.send(f"OK {len(synced)} commandes synchronisees.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Erreur: {e}", ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN manquant dans .env")
    log.info("=== Demarrage du bot (force-resync v3) ===")
    # Lancer le mini site web d'upload dans un thread separe
    try:
        from web_upload import start_in_thread
        start_in_thread()
        log.info("Mini site web demarre sur le port 8080")
    except Exception as e:
        log.warning(f"Impossible de demarrer le mini site web : {e}")
    bot.run(TOKEN, log_handler=None)
