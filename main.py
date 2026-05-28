import os
import logging
import traceback
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_TOKEN = os.getenv("DISCORD_ADMIN_TOKEN")
PREFIX = os.getenv("PREFIX", "!")

# Repartition des cogs entre les 2 bots
MAIN_COGS = ["welcome", "onboarding", "autopost", "general", "user"]
ADMIN_COGS = ["admin", "geelark"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("vabot")


def make_intents():
    intents = discord.Intents.default()
    intents.members = True  # necessaire pour on_member_join
    return intents


class VABot(commands.Bot):
    def __init__(self, label: str, cogs_to_load: list):
        super().__init__(command_prefix=PREFIX, intents=make_intents())
        self._label = label
        self._cogs_to_load = cogs_to_load

    async def setup_hook(self):
        for cog_name in self._cogs_to_load:
            path = f"./cogs/{cog_name}.py"
            if not os.path.exists(path):
                log.warning(f"[{self._label}] cog {cog_name} introuvable, skip")
                continue
            try:
                await self.load_extension(f"cogs.{cog_name}")
                log.info(f"[{self._label}] Cog charge: {cog_name}")
            except Exception as e:
                log.error(f"[{self._label}] Erreur chargement {cog_name}: {e}")
                log.error(traceback.format_exc())
        try:
            synced = await self.tree.sync()
            log.info(f"[{self._label}] {len(synced)} slash commands synchronisees")
        except Exception as e:
            log.warning(f"[{self._label}] Sync echoue (rate-limit?): {e}")


def register_sync_command(bot: commands.Bot, label: str):
    """Enregistre /sync sur ce bot."""
    @bot.tree.command(name="sync", description="[OWNER] Resync les slash commands")
    async def sync_slash(interaction: discord.Interaction):
        app = await bot.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            synced = await bot.tree.sync()
            await interaction.followup.send(
                f"OK {len(synced)} commandes synchronisees ({label}).", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Erreur: {e}", ephemeral=True)


# Bot principal (VAs + onboarding + welcome + autopost)
main_bot = VABot("main", MAIN_COGS)
register_sync_command(main_bot, "main")


async def _dm_owner(bot, message: str):
    """Envoie un DM au owner du bot (pour debug). Silencieux si echec."""
    try:
        app = await bot.application_info()
        owner = app.owner
        if owner:
            await owner.send(message)
    except Exception as e:
        log.warning(f"DM owner echoue: {e}")


@main_bot.event
async def on_ready():
    log.info(f"[main] Bot connecte: {main_bot.user} (id: {main_bot.user.id})")
    await _dm_owner(
        main_bot,
        f"✅ **[MAIN]** Bot principal connecté : `{main_bot.user}`\n"
        f"ADMIN_TOKEN dans .env : {'✅ présent' if ADMIN_TOKEN else '❌ absent'}",
    )


# Bot admin (cree dynamiquement si ADMIN_TOKEN dispo)
admin_bot = None
if ADMIN_TOKEN:
    admin_bot = VABot("admin", ADMIN_COGS)
    register_sync_command(admin_bot, "admin")

    @admin_bot.event
    async def on_admin_ready():
        log.info(f"[admin] Bot connecte: {admin_bot.user} (id: {admin_bot.user.id})")
        await _dm_owner(
            admin_bot,
            f"✅ **[ADMIN]** Bot admin connecté : `{admin_bot.user}`",
        )

    admin_bot.add_listener(on_admin_ready, "on_ready")


async def main_async():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN manquant dans .env")

    log.info("=== Demarrage du bot ===")
    if ADMIN_TOKEN:
        log.info("ADMIN_TOKEN detecte -> les 2 bots seront lances")
    else:
        log.info("ADMIN_TOKEN absent -> seul le bot principal sera lance")

    # Mini site web d'upload (lancer une seule fois, dans un thread separe)
    try:
        from web_upload import start_in_thread, set_bot_ref
        set_bot_ref(main_bot)
        start_in_thread()
        log.info("Mini site web demarre sur le port 8080")
    except Exception as e:
        log.warning(f"Impossible de demarrer le mini site web : {e}")

    async def _run_safe(bot, token, label):
        """Wrap bot.start dans un try/except pour qu'un bot qui crashe ne tue pas l'autre.

        Si l'admin bot crashe, on essaie de notifier l'owner via le main bot.
        """
        err_msg = None
        try:
            await bot.start(token)
        except discord.LoginFailure as e:
            err_msg = f"❌ **[{label.upper()}]** Token invalide. Refais `/setadmintoken` avec le bon token. ({e})"
            log.error(f"[{label}] Token invalide: {e}")
        except discord.PrivilegedIntentsRequired as e:
            err_msg = (
                f"❌ **[{label.upper()}]** Privileged Intents requis. "
                f"Va sur https://discord.com/developers/applications → ton bot → Bot → "
                f"active **SERVER MEMBERS INTENT** → Save Changes. Puis fais `/restartbot`."
            )
            log.error(f"[{label}] PRIVILEGED INTENTS: {e}")
        except Exception as e:
            err_msg = f"❌ **[{label.upper()}]** Crash: {type(e).__name__}: {e}"
            log.error(f"[{label}] Bot crashe: {type(e).__name__}: {e}")
        # Notifier le owner via le main bot si c'est l'admin qui crashe
        if err_msg and label == "admin":
            # Attendre que main_bot soit connecte pour pouvoir DM
            for _ in range(30):
                if main_bot.is_ready():
                    await _dm_owner(main_bot, err_msg)
                    break
                await asyncio.sleep(1)

    tasks = [asyncio.create_task(_run_safe(main_bot, TOKEN, "main"), name="main_bot")]
    if admin_bot is not None:
        tasks.append(
            asyncio.create_task(_run_safe(admin_bot, ADMIN_TOKEN, "admin"), name="admin_bot")
        )

    # Les deux bots tournent independamment. Si l'un crashe, l'autre continue.
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main_async())
