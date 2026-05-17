import json
import random
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
PROFILE_PICS_DIR = DATA_DIR / "profile_pics"
CAPTIONS_FILE = DATA_DIR / "captions.txt"
BIOS_FILE = DATA_DIR / "bios.txt"
USERNAMES_FILE = DATA_DIR / "usernames.txt"
USERS_FILE = DATA_DIR / "users.json"

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_lines(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def unescape_newlines(text: str) -> str:
    return text.replace("\\n", "\n") if text else text


def random_line(path):
    lines = read_lines(path)
    return unescape_newlines(random.choice(lines)) if lines else None


def random_bio():
    if not BIOS_FILE.exists():
        return None
    content = BIOS_FILE.read_text(encoding="utf-8")
    bios = [b.strip() for b in content.split("---") if b.strip()]
    return unescape_newlines(random.choice(bios)) if bios else None


def random_file(directory: Path, exts):
    if not directory.exists():
        return None
    files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in exts]
    return random.choice(files) if files else None


def get_user_identity(user_id: int):
    users = load_json(USERS_FILE, {})
    return users.get(str(user_id))


class UserCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="username", description="Donne un username Instagram aléatoire")
    async def username(self, interaction: discord.Interaction):
        u = random_line(USERNAMES_FILE)
        if not u:
            await interaction.response.send_message(
                "Aucun username disponible. Demande à un admin d'en ajouter avec `/addusernames`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"📝 **Username :** `{u}`\n*Copie-colle dans Instagram.*"
        )

    @app_commands.command(name="bio", description="Donne une bio Instagram aléatoire")
    async def bio(self, interaction: discord.Interaction):
        b = random_bio()
        if not b:
            await interaction.response.send_message(
                "Aucune bio disponible. Demande à un admin d'en ajouter avec `/addbios`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"📝 **Bio :**\n```\n{b}\n```\n*Copie-colle dans la bio Instagram.*"
        )

    @app_commands.command(name="profilepic", description="Donne une photo de profil aléatoire")
    async def profilepic(self, interaction: discord.Interaction):
        pic = random_file(PROFILE_PICS_DIR, IMAGE_EXTS)
        if not pic:
            await interaction.response.send_message(
                "Aucune photo de profil disponible. Demande à un admin d'en ajouter avec `/addprofilepic`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "📸 **Photo de profil**\n*Télécharge et upload sur Instagram.*",
            file=discord.File(pic),
        )

    @app_commands.command(name="reel", description="Génère un reel: vidéo de ton identité + caption")
    async def reel(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        videos_dir = IDENTITIES_DIR / identity / "videos"
        video = random_file(videos_dir, VIDEO_EXTS)
        if not video:
            await interaction.response.send_message(
                f"Aucune vidéo dans ton identité `{identity}`. Demande à un admin.",
                ephemeral=True,
            )
            return
        caption = random_line(CAPTIONS_FILE) or "(aucune caption disponible)"
        await interaction.response.defer()
        message = (
            f"🎬 **REEL — identité `{identity}`**\n\n"
            f"📝 **Caption (à mettre en overlay sur la vidéo) :**\n```\n{caption}\n```\n"
            "📥 Télécharge la vidéo, ajoute la caption par-dessus, poste sur Instagram."
        )
        try:
            await interaction.followup.send(content=message, file=discord.File(video))
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Impossible d'envoyer la vidéo (probablement trop lourde pour ce serveur): {e}",
                ephemeral=True,
            )

    @app_commands.command(name="help", description="Affiche l'aide")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📚 Aide — Commandes du bot",
            color=discord.Color.blurple(),
            description=(
                "**Commandes VA :**\n"
                "`/username` — un username Instagram aléatoire\n"
                "`/bio` — une bio Instagram aléatoire\n"
                "`/profilepic` — une photo de profil\n"
                "`/reel` — génère un reel (vidéo de ton identité + caption)\n"
                "`/help` — cette aide\n\n"
                "**Onboarding :** suis les étapes dans ton salon (boutons **→** sous les messages)."
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(UserCog(bot))
