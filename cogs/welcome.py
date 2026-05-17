"""Welcome flow: auto-message on member join with 'Continuer' button.
Click → creates VA channel + assigns random identity + sends intro with payment info + 'Commencer' button.
Click → posts step 1 of onboarding.
"""
import json
import logging
import random
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("vabot.welcome")

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
USERS_FILE = DATA_DIR / "users.json"
WHITELIST_FILE = DATA_DIR / "whitelist.json"
WELCOME_CONFIG_FILE = DATA_DIR / "welcome_config.json"

DEFAULT_WELCOME_CONFIG = {
    "welcome_channel_id": None,
    "welcome_public_message": (
        "👋 **Bienvenue dans l'agence {mention} !**\n\n"
        "Tu es là parce que tu vas bosser avec nous comme VA. "
        "Pour démarrer, clique sur **Continuer** ci-dessous : ton salon perso sera créé "
        "automatiquement et on commencera l'onboarding ensemble.\n\n"
        "↓"
    ),
    "ticket_intro_message": (
        "🎫 **Voilà ton salon perso {mention} !**\n\n"
        "Ici tu auras toutes les infos dont tu as besoin pour bosser :\n"
        "💰 **Paiement** : 50% par reel posté (à définir avec le boss)\n"
        "📅 **Rythme** : 1 reel + 1 post + 1 story par jour minimum\n"
        "📩 **Questions** : DM le boss directement\n\n"
        "Quand tu es prêt, clique sur **Commencer l'onboarding** pour démarrer le tutoriel "
        "étape par étape (création du compte, bio, photo de profil, etc.).\n\n"
        "↓"
    ),
}


def load_welcome_config():
    if not WELCOME_CONFIG_FILE.exists():
        save_welcome_config(DEFAULT_WELCOME_CONFIG)
        return dict(DEFAULT_WELCOME_CONFIG)
    try:
        cfg = json.loads(WELCOME_CONFIG_FILE.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_WELCOME_CONFIG)
        merged.update(cfg)
        return merged
    except Exception:
        return dict(DEFAULT_WELCOME_CONFIG)


def save_welcome_config(cfg):
    WELCOME_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    WELCOME_CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def list_identities():
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())


async def create_va_channel(guild, member, identity):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_messages=True, attach_files=True
        ),
    }
    base_name = f"va-{member.name}".lower().replace(" ", "-")[:90]
    try:
        return await guild.create_text_channel(name=base_name, overwrites=overwrites)
    except discord.Forbidden:
        return None


class StartOnboardingView(discord.ui.View):
    """2e bouton : dans le salon perso du VA, démarre l'onboarding."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎬 Commencer l'onboarding",
        style=discord.ButtonStyle.success,
        custom_id="va_start_onboarding",
    )
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verifier que c'est bien le VA proprietaire du salon qui clique
        from cogs.onboarding import step_embed, OnboardingView
        embed = step_embed(0)
        await interaction.response.send_message(
            content=interaction.user.mention, embed=embed, view=OnboardingView()
        )


class WelcomeContinueView(discord.ui.View):
    """1er bouton : dans le salon welcome public, clic pour creer le ticket."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ Continuer",
        style=discord.ButtonStyle.primary,
        custom_id="welcome_continue",
    )
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Doit etre utilise dans un serveur.", ephemeral=True)
            return

        users = load_users()
        existing = users.get(str(interaction.user.id))

        # Si user a deja un salon, l'envoyer là
        if isinstance(existing, dict) and existing.get("channel_id"):
            existing_channel = guild.get_channel(existing["channel_id"])
            if existing_channel:
                await interaction.followup.send(
                    f"Tu as deja un salon : {existing_channel.mention}. Rends-toi la-bas pour commencer.",
                    ephemeral=True,
                )
                return

        # Determiner l'identite : garder existante OU random
        if isinstance(existing, dict) and existing.get("identity"):
            identity = existing["identity"]
        elif isinstance(existing, str):
            identity = existing
        else:
            identities = list_identities()
            if not identities:
                await interaction.followup.send(
                    "❌ Aucune identité disponible. Préviens un admin.", ephemeral=True
                )
                return
            identity = random.choice(identities)

        # Creer le salon
        channel = await create_va_channel(guild, interaction.user, identity)
        if not channel:
            await interaction.followup.send(
                "❌ Le bot n'a pas la permission de créer un salon. Préviens un admin.",
                ephemeral=True,
            )
            return

        # Sauvegarder
        users[str(interaction.user.id)] = {
            "identity": identity,
            "channel_id": channel.id,
            "auto_post": True,
        }
        save_users(users)

        # Envoyer le message intro dans le salon
        cfg = load_welcome_config()
        intro_text = cfg["ticket_intro_message"].format(mention=interaction.user.mention)
        await channel.send(content=intro_text, view=StartOnboardingView())

        # Confirmer au VA
        await interaction.followup.send(
            f"✅ Ton salon a été créé : {channel.mention}\nRends-toi là-bas pour commencer.",
            ephemeral=True,
        )


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None

    async def cog_load(self):
        # Persistent views (survivent au restart)
        self.bot.add_view(WelcomeContinueView())
        self.bot.add_view(StartOnboardingView())

    async def get_owner_id(self):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return self._owner_id

    async def is_admin(self, user_id):
        if user_id == await self.get_owner_id():
            return True
        if WHITELIST_FILE.exists():
            try:
                wl = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
                return user_id in wl
            except Exception:
                pass
        return False

    async def require_admin(self, interaction):
        if not await self.is_admin(interaction.user.id):
            msg = "Tu n'es pas autorisé."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Quand un nouveau membre rejoint, envoyer le message de bienvenue avec bouton."""
        if member.bot:
            return
        cfg = load_welcome_config()
        channel_id = cfg.get("welcome_channel_id")
        if not channel_id:
            log.warning(f"on_member_join: aucun welcome_channel_id configuré, member={member.id}")
            return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            log.warning(f"on_member_join: welcome_channel_id={channel_id} introuvable")
            return
        try:
            text = cfg["welcome_public_message"].format(mention=member.mention)
            await channel.send(content=text, view=WelcomeContinueView())
        except Exception as e:
            log.error(f"on_member_join: erreur envoi welcome: {e}")

    @app_commands.command(name="setwelcomechannel", description="[ADMIN] Définit le salon où arrivera le welcome auto")
    @app_commands.describe(channel="Le salon (laisse vide pour utiliser le salon courant)")
    async def setwelcomechannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not await self.require_admin(interaction):
            return
        target = channel or interaction.channel
        cfg = load_welcome_config()
        cfg["welcome_channel_id"] = target.id
        save_welcome_config(cfg)
        await interaction.response.send_message(
            f"✅ Salon welcome auto : {target.mention}", ephemeral=True
        )

    @app_commands.command(name="welcomesettings", description="[ADMIN] Voir la config du welcome")
    async def welcomesettings(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        cfg = load_welcome_config()
        channel_id = cfg.get("welcome_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        text = (
            "⚙️ **Config welcome**\n"
            f"Salon welcome : {channel.mention if channel else '❌ Non configuré'}\n\n"
            "**Message public :**\n"
            f"```\n{cfg.get('welcome_public_message', '')[:500]}\n```\n"
            "**Message ticket (privé) :**\n"
            f"```\n{cfg.get('ticket_intro_message', '')[:500]}\n```"
        )
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="welcometest", description="[ADMIN] Simule l'arrivée d'un membre")
    @app_commands.describe(user="Sur quel user simuler (défaut: toi)")
    async def welcometest(self, interaction: discord.Interaction, user: discord.Member = None):
        if not await self.require_admin(interaction):
            return
        target = user or interaction.user
        await self.on_member_join(target)
        await interaction.response.send_message(
            f"✅ Welcome simulé pour {target.mention}", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Welcome(bot))
