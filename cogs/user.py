import asyncio
import json
import os
import random
import tempfile
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

from video_transform import transform_video, load_config as load_transform_config
from image_transform import transform_image, load_config as load_image_config

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


SHARED_BIOS_FILE = DATA_DIR / "bios.txt"


def _read_bios_at(path):
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    return [b.strip() for b in content.split("---") if b.strip()]


def random_bio_for(identity):
    """Try identity-specific bios first, fallback to shared bios."""
    if identity:
        bios = _read_bios_at(IDENTITIES_DIR / identity / "bios.txt")
        if bios:
            return unescape_newlines(random.choice(bios))
    bios = _read_bios_at(SHARED_BIOS_FILE)
    if bios:
        return unescape_newlines(random.choice(bios))
    return None


def random_reel_for(identity):
    """Pick random clean video + caption + description + example_path|None.
    Returns (Path, caption|None, description|None, example_Path|None).
    """
    videos_dir = IDENTITIES_DIR / identity / "videos"
    if not videos_dir.exists():
        return None, None, None, None
    # Filtrer les videos clean (pas les .example.*)
    videos = [
        p for p in videos_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not videos:
        return None, None, None, None
    video = random.choice(videos)
    caption_path = video.with_suffix(".txt")
    desc_path = video.with_suffix(".desc.txt")
    caption = None
    description = None
    if caption_path.exists():
        caption = unescape_newlines(caption_path.read_text(encoding="utf-8").strip())
    if desc_path.exists():
        description = unescape_newlines(desc_path.read_text(encoding="utf-8").strip())
    # Chercher la video exemple
    example = None
    for ext in VIDEO_EXTS:
        candidate = videos_dir / f"{video.stem}.example{ext}"
        if candidate.exists():
            example = candidate
            break
    return video, caption, description, example


def random_profile_pic():
    if not PROFILE_PICS_DIR.exists():
        return None
    pics = [p for p in PROFILE_PICS_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return random.choice(pics) if pics else None


def random_image_with_pair(directory):
    """Pick a random clean image + caption + description + example. Skips .example.* files."""
    if not directory.exists():
        return None, None, None, None
    images = [
        p for p in directory.iterdir()
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not images:
        return None, None, None, None
    image = random.choice(images)
    cap_path = image.with_suffix(".txt")
    desc_path = image.with_suffix(".desc.txt")
    caption = unescape_newlines(cap_path.read_text(encoding="utf-8").strip()) if cap_path.exists() else None
    description = unescape_newlines(desc_path.read_text(encoding="utf-8").strip()) if desc_path.exists() else None
    example = None
    for ext in IMAGE_EXTS:
        candidate = directory / f"{image.stem}.example{ext}"
        if candidate.exists():
            example = candidate
            break
    return image, caption, description, example


def random_post_for(identity):
    return random_image_with_pair(IDENTITIES_DIR / identity / "posts")


def random_story_for(identity):
    return random_image_with_pair(IDENTITIES_DIR / identity / "stories")


STORY_CTA_CAPTIONS_FILE = DATA_DIR / "story_cta_captions.txt"


def random_story_cta_caption():
    if not STORY_CTA_CAPTIONS_FILE.exists():
        return None
    lines = [l.strip() for l in STORY_CTA_CAPTIONS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    return unescape_newlines(random.choice(lines)) if lines else None


def random_story_cta_image_for(identity):
    d = IDENTITIES_DIR / identity / "storyctas"
    if not d.exists():
        return None
    images = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return random.choice(images) if images else None


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
            f"📝 **Username** (identité `{identity}`) — utilise le bouton copy du bloc ⬇️"
        )
        await interaction.followup.send(f"```\n{u}\n```")

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
            f"📝 **Bio** (identité `{identity}`) — utilise le bouton copy du bloc ⬇️"
        )
        await interaction.followup.send(f"```\n{b}\n```")

    @app_commands.command(name="profilepic", description="Donne une photo de profil aléatoire (transformée)")
    async def profilepic(self, interaction: discord.Interaction):
        pic = random_profile_pic()
        if not pic:
            await interaction.response.send_message(
                "Aucune photo de profil disponible. Demande à un admin (`/addprofilepic`).",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        # Transformer
        cfg = load_image_config()
        tmp_dir = None
        send_path = pic
        try:
            if cfg.get("enabled", True):
                tmp_dir = tempfile.mkdtemp(prefix="pp_")
                tmp_path = Path(tmp_dir) / pic.name
                if await asyncio.to_thread(transform_image, pic, tmp_path, cfg, "profile"):
                    send_path = tmp_path
            await interaction.followup.send(
                "📸 **Photo de profil**\n*Télécharge et upload sur Instagram.*",
                file=discord.File(send_path),
            )
        finally:
            if tmp_dir:
                try:
                    import shutil
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

    async def _send_image_content(self, interaction, kind_label, kind_target, random_fn, transform_cfg):
        """Generic handler for /post and /story commands."""
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        image, caption, description, example = random_fn(identity)
        if not image:
            await interaction.response.send_message(
                f"Aucun {kind_label} pour ton identité `{identity}`. Demande à un admin.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        tmp_dir = None
        send_path = image
        try:
            if transform_cfg.get("enabled", True):
                tmp_dir = tempfile.mkdtemp(prefix=f"{kind_target}_")
                tmp_path = Path(tmp_dir) / image.name
                if await asyncio.to_thread(transform_image, image, tmp_path, transform_cfg, kind_target):
                    send_path = tmp_path
            intro = (
                f"🖼️ **{kind_label.upper()} — identité `{identity}`**\n"
                f"📥 Télécharge la photo CLEAN (1ère pièce jointe), ajoute la caption en overlay, poste avec la description."
            )
            if example:
                intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE du rendu final — NE PAS la télécharger pour poster."
            if caption:
                intro += "\n\n📝 **Caption** ⬇️ (long-press pour copier)"
            if description:
                intro += "\n📄 **Description** ⬇️ (long-press pour copier)"
            files = [discord.File(send_path, filename=image.name)]
            if example:
                files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
            try:
                await interaction.followup.send(content=intro, files=files)
            except discord.HTTPException as e:
                await interaction.followup.send(f"Erreur d'envoi : {e}", ephemeral=True)
                return
            if caption:
                await interaction.followup.send(f"```\n{caption}\n```")
            if description:
                await interaction.followup.send(f"```\n{description}\n```")
        finally:
            if tmp_dir:
                try:
                    import shutil
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

    @app_commands.command(name="post", description="Génère un post photo (photo + caption + description)")
    async def post(self, interaction: discord.Interaction):
        cfg = load_image_config()
        await self._send_image_content(interaction, "post", "post", random_post_for, cfg)

    @app_commands.command(name="story", description="Génère une story (photo + caption + description)")
    async def story(self, interaction: discord.Interaction):
        cfg = load_image_config()
        await self._send_image_content(interaction, "story", "story", random_story_for, cfg)

    @app_commands.command(name="storycta", description="Génère une story CTA: photo 1080x1920 + caption à écrire dessus")
    async def storycta(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True
            )
            return
        image = random_story_cta_image_for(identity)
        if not image:
            await interaction.response.send_message(
                f"Aucune story CTA pour ton identité `{identity}`. Demande à un admin (`/addstorycta`).",
                ephemeral=True,
            )
            return
        caption = random_story_cta_caption()
        if not caption:
            await interaction.response.send_message(
                "Aucune caption disponible. Demande à un admin (`/addstoryctacaptions`).",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        cfg = load_image_config()
        tmp_dir = None
        send_path = image
        try:
            if cfg.get("enabled", True):
                tmp_dir = tempfile.mkdtemp(prefix="storycta_")
                tmp_path = Path(tmp_dir) / image.name
                if await asyncio.to_thread(transform_image, image, tmp_path, cfg, "storycta"):
                    send_path = tmp_path
            intro = (
                f"📲 **STORY CTA — identité `{identity}`**\n"
                "📥 Télécharge la photo, écris la caption dessus avec l'éditeur Instagram, poste en story.\n\n"
                "📝 **Caption** ⬇️ (long-press pour la copier)"
            )
            try:
                await interaction.followup.send(content=intro, file=discord.File(send_path))
            except discord.HTTPException as e:
                await interaction.followup.send(f"Erreur d'envoi : {e}", ephemeral=True)
                return
            await interaction.followup.send(f"```\n{caption}\n```")
        finally:
            if tmp_dir:
                try:
                    import shutil
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

    @app_commands.command(name="reel", description="Génère un reel: vidéo clean (transformée) + caption + description + exemple")
    async def reel(self, interaction: discord.Interaction):
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        video, caption, description, example = random_reel_for(identity)
        if not video:
            await interaction.response.send_message(
                f"Aucune vidéo pour ton identité `{identity}`. Demande à un admin.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()

        # Transformation video DESACTIVEE - envoi de la video originale telle quelle
        transform_cfg = load_transform_config()
        transformed_path = None
        tmp_dir = None
        try:
            video_to_send = video  # toujours envoyer l'original

            intro = (
                f"🎬 **REEL — identité `{identity}`**\n"
                "📥 Télécharge la vidéo CLEAN (1ère pièce jointe), ajoute la caption en overlay, poste avec la description."
            )
            if example:
                intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE du rendu final — NE PAS la télécharger pour poster."
            if caption:
                intro += "\n\n📝 **Caption** ⬇️ (long-press le message pour la copier)"
            if description:
                intro += "\n📄 **Description** ⬇️ (long-press l'autre message pour la copier)"

            files = [discord.File(video_to_send, filename=video.name)]
            if example:
                files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
            try:
                await interaction.followup.send(content=intro, files=files)
            except discord.HTTPException as e:
                # Retry sans l'exemple si c'est trop lourd
                if example and len(files) == 2:
                    try:
                        await interaction.followup.send(
                            content=intro + "\n\n⚠️ *(Vidéo exemple omise car trop lourde)*",
                            file=discord.File(video_to_send, filename=video.name),
                        )
                    except discord.HTTPException:
                        await interaction.followup.send(
                            f"Impossible d'envoyer la vidéo (probablement trop lourde): {e}",
                            ephemeral=True,
                        )
                        return
                else:
                    await interaction.followup.send(
                        f"Impossible d'envoyer la vidéo (probablement trop lourde): {e}",
                        ephemeral=True,
                    )
                    return
            # Messages séparés pour copier facilement sur mobile
            if caption:
                await interaction.followup.send(f"```\n{caption}\n```")
            if description:
                await interaction.followup.send(f"```\n{description}\n```")

            # Suppression de la source si configuré
            if transform_cfg.get("delete_source_after_use", False):
                try:
                    video.unlink(missing_ok=True)
                    # Supprimer aussi caption/description associées
                    cap_p = video.with_suffix(".txt")
                    desc_p = video.with_suffix(".desc.txt")
                    cap_p.unlink(missing_ok=True)
                    desc_p.unlink(missing_ok=True)
                    # Supprimer l'exemple paire si existe
                    if example:
                        example.unlink(missing_ok=True)
                except Exception:
                    pass
        finally:
            # Nettoyage du fichier transformé temporaire
            if tmp_dir:
                try:
                    import shutil
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

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
