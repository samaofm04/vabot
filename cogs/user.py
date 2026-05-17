import json
import random
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
PROFILE_PICS_DIR = DATA_DIR / "profile_pics"
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


def unescape_newlines(text):
    return text.replace("\\n", "\n") if text else text


def read_lines(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def random_username_for(identity):
    items = read_lines(IDENTITIES_DIR / identity / "usernames.txt")
    return unescape_newlines(random.choice(items)) if items else None


def random_bio_for(identity):
    path = IDENTITIES_DIR / identity / "bios.txt"
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8")
    bios = [b.strip() for b in content.split("---") if b.strip()]
    return unescape_newlines(random.choice(bios)) if bios else None


def random_reel_for(identity):
    """Pick a random video + paired caption + description. Returns (Path, caption|None, description|None)."""
    videos_dir = IDENTITIES_DIR / identity / "videos"
    if not videos_dir.exists():
        return None, None, None
    videos = [p for p in videos_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if not videos:
        return None, None, None
    video = random.choice(videos)
    caption_path = video.with_suffix(".txt")
    desc_path = video.with_suffix(".desc.txt")
    caption = None
    description = None
    if caption_path.exists():
        caption = unescape_newlines(caption_path.read_text(encoding="utf-8").strip())
    if desc_path.exists():
        description = unescape_newlines(desc_path.read_text(encoding="utf-8").strip())
    return video, caption, description


def random_profile_pic():
    if not PROFILE_PICS_DIR.exists():
        return None
    pics = [p for p in PROFILE_PICS_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return random.choice(pics) if pics else None


def get_user_identity(user_id):
    users = load_json(USERS_FILE, {})
    return users.get(str(user_id))


class UserCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="username", description="Donne un username Instagram aléatoire de ton identité")
    async def username(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        u = random_username_for(identity)
        if not u:
            await interaction.response.send_message(
                f"Aucun username pour ton identité `{identity}`. Demande à un admin (`/addusernames`).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"📝 **Username (identité `{identity}`) :** `{u}`\n*Copie-colle dans Instagram.*"
        )

    @app_commands.command(name="bio", description="Donne une bio Instagram aléatoire de ton identité")
    async def bio(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        b = random_bio_for(identity)
        if not b:
            await interaction.response.send_message(
                f"Aucune bio pour ton identité `{identity}`. Demande à un admin (`/addbios`).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"📝 **Bio (identité `{identity}`) :**\n```\n{b}\n```\n*Copie-colle dans la bio Instagram.*"
        )

    @app_commands.command(name="profilepic", description="Donne une photo de profil aléatoire")
    async def profilepic(self, interaction: discord.Interaction):
        pic = random_profile_pic()
        if not pic:
            await interaction.response.send_message(
                "Aucune photo de profil disponible. Demande à un admin (`/addprofilepic`).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "📸 **Photo de profil**\n*Télécharge et upload sur Instagram.*",
            file=discord.File(pic),
        )

    @app_commands.command(name="reel", description="Génère un reel: vidéo + caption (overlay) + description (post)")
    async def reel(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        video, caption, description = random_reel_for(identity)
        if not video:
            await interaction.response.send_message(
                f"Aucune vidéo pour ton identité `{identity}`. Demande à un admin.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        parts = [f"🎬 **REEL — identité `{identity}`**\n"]
        if caption:
            parts.append(f"📝 **Caption (À METTRE EN OVERLAY sur la vidéo) :**\n```\n{caption}\n```")
        else:
            parts.append("*(Pas de caption recommandée — choisis-en une toi-même)*")
        if description:
            parts.append(f"📄 **Description (À METTRE COMME TEXTE DU POST) :**\n```\n{description}\n```")
        else:
            parts.append("*(Pas de description recommandée — écris-en une toi-même)*")
        parts.append("\n📥 Télécharge la vidéo, ajoute la caption en overlay, poste avec la description.")
        message = "\n".join(parts)
        try:
            await interaction.followup.send(content=message, file=discord.File(video))
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Impossible d'envoyer la vidéo (probablement trop lourde): {e}",
                ephemeral=True,
            )

    @app_commands.command(name="help", description="Affiche l'aide")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📚 Aide — Commandes du bot",
            color=discord.Color.blurple(),
            description=(
                "**Commandes VA :**\n"
                "`/username` — un username Instagram de ton identité\n"
                "`/bio` — une bio Instagram de ton identité\n"
                "`/profilepic` — une photo de profil (pool partagé)\n"
                "`/reel` — un reel de ton identité + sa caption associée\n"
                "`/help` — cette aide\n\n"
                "**Onboarding :** suis les étapes dans ton salon (boutons →)."
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(UserCog(bot))
