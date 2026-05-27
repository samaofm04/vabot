"""Auto-post quotidien : à une heure fixe, le bot poste reel + post + story + storycta
dans le salon de chaque VA actif. Quand le VA se reveille, tout est deja la.
"""
import asyncio
import io
import json
import logging
import random
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks

from video_transform import load_config as load_video_config
from image_transform import transform_image, load_config as load_image_config

log = logging.getLogger("vabot.autopost")

DATA_DIR = Path("data")
USERS_FILE = DATA_DIR / "users.json"
IDENTITIES_DIR = DATA_DIR / "identities"
AUTOPOST_CONFIG = DATA_DIR / "autopost_config.json"
STORY_CTA_CAPTIONS_FILE = DATA_DIR / "story_cta_captions.txt"

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

DEFAULT_AUTOPOST_CONFIG = {
    "enabled": False,
    "hour_utc": 7,       # 8h Paris hiver, 9h Paris ete
    "minute_utc": 0,
    "post_reel": True,
    "post_post": True,
    "post_story": True,
    "post_storycta": True,
    "last_run_date": None,
}


def load_autopost_config():
    if not AUTOPOST_CONFIG.exists():
        save_autopost_config(DEFAULT_AUTOPOST_CONFIG)
        return dict(DEFAULT_AUTOPOST_CONFIG)
    try:
        cfg = json.loads(AUTOPOST_CONFIG.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_AUTOPOST_CONFIG)
        merged.update(cfg)
        return merged
    except Exception:
        return dict(DEFAULT_AUTOPOST_CONFIG)


def save_autopost_config(cfg):
    AUTOPOST_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    AUTOPOST_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


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


def get_user_data(user_id):
    """Returns dict {identity, channel_id, auto_post} or None."""
    users = load_users()
    data = users.get(str(user_id))
    if data is None:
        return None
    if isinstance(data, str):
        return {"identity": data, "channel_id": None, "auto_post": True}
    return {
        "identity": data.get("identity"),
        "channel_id": data.get("channel_id"),
        "auto_post": data.get("auto_post", True),
    }


def unescape_newlines(text):
    return text.replace("\\n", "\n") if text else text


def random_reel_data(identity):
    videos_dir = IDENTITIES_DIR / identity / "videos"
    if not videos_dir.exists():
        return None, None, None, None
    videos = [
        p for p in videos_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not videos:
        return None, None, None, None
    video = random.choice(videos)
    cap_p = video.with_suffix(".txt")
    desc_p = video.with_suffix(".desc.txt")
    caption = unescape_newlines(cap_p.read_text(encoding="utf-8").strip()) if cap_p.exists() else None
    description = unescape_newlines(desc_p.read_text(encoding="utf-8").strip()) if desc_p.exists() else None
    example = None
    for ext in VIDEO_EXTS:
        c = videos_dir / f"{video.stem}.example{ext}"
        if c.exists():
            example = c
            break
    return video, caption, description, example


def random_image_with_pair(directory):
    if not directory.exists():
        return None, None, None, None
    images = [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not images:
        return None, None, None, None
    img = random.choice(images)
    cap_p = img.with_suffix(".txt")
    desc_p = img.with_suffix(".desc.txt")
    caption = unescape_newlines(cap_p.read_text(encoding="utf-8").strip()) if cap_p.exists() else None
    description = unescape_newlines(desc_p.read_text(encoding="utf-8").strip()) if desc_p.exists() else None
    example = None
    for ext in IMAGE_EXTS:
        c = directory / f"{img.stem}.example{ext}"
        if c.exists():
            example = c
            break
    return img, caption, description, example


def random_storycta_data(identity):
    d = IDENTITIES_DIR / identity / "storyctas"
    if not d.exists():
        return None, None
    images = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    if not images:
        return None, None
    img = random.choice(images)
    caption = None
    if STORY_CTA_CAPTIONS_FILE.exists():
        lines = [l.strip() for l in STORY_CTA_CAPTIONS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            caption = unescape_newlines(random.choice(lines))
    return img, caption


async def send_reel(channel, identity):
    video, caption, description, example = random_reel_data(identity)
    if not video:
        return False
    intro = f"🎬 **REEL — identité `{identity}`**\n📥 Télécharge la vidéo CLEAN."
    if example:
        intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE — NE PAS la télécharger."
    files = [discord.File(video, filename=video.name)]
    if example:
        files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
    try:
        await channel.send(content=intro, files=files)
    except discord.HTTPException:
        try:
            await channel.send(content=intro, file=discord.File(video, filename=video.name))
        except discord.HTTPException:
            return False
    if caption:
        await channel.send("📝 **CAPTION** (à mettre **PAR-DESSUS la vidéo** dans l'éditeur Insta) :")
        await channel.send(caption)
    if description:
        await channel.send("📄 **DESCRIPTION** (à coller dans le **champ légende** du post) :")
        await channel.send(description)
    return True


async def _send_image(channel, identity, kind_label, kind_target, random_fn, transform_cfg):
    image, caption, description, example = random_fn(identity)
    if not image:
        return False
    tmp_dir = None
    send_path = image
    try:
        if transform_cfg.get("enabled", True):
            tmp_dir = tempfile.mkdtemp(prefix=f"{kind_target}_")
            tmp_path = Path(tmp_dir) / image.name
            if await asyncio.to_thread(transform_image, image, tmp_path, transform_cfg, kind_target):
                send_path = tmp_path
        intro = f"🖼️ **{kind_label.upper()} — identité `{identity}`**\n📥 Télécharge la photo CLEAN."
        if example:
            intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE — NE PAS la télécharger."
        files = [discord.File(send_path, filename=image.name)]
        if example:
            files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
        try:
            await channel.send(content=intro, files=files)
        except discord.HTTPException:
            return False
        if caption:
            await channel.send(f"📝 **CAPTION {kind_label.upper()}** (à mettre **PAR-DESSUS la photo** dans l'éditeur Insta) :")
            await channel.send(caption)
        if description:
            await channel.send(f"📄 **DESCRIPTION {kind_label.upper()}** (à coller dans le **champ légende** du post) :")
            await channel.send(description)
        return True
    finally:
        if tmp_dir:
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


async def send_post(channel, identity):
    return await _send_image(channel, identity, "post", "post",
                             lambda i: random_image_with_pair(IDENTITIES_DIR / i / "posts"),
                             load_image_config())


async def send_story(channel, identity):
    return await _send_image(channel, identity, "story", "story",
                             lambda i: random_image_with_pair(IDENTITIES_DIR / i / "stories"),
                             load_image_config())


async def send_storycta(channel, identity):
    image, caption = random_storycta_data(identity)
    if not image or not caption:
        return False
    tmp_dir = None
    send_path = image
    try:
        cfg = load_image_config()
        if cfg.get("enabled", True):
            tmp_dir = tempfile.mkdtemp(prefix="storycta_")
            tmp_path = Path(tmp_dir) / image.name
            if await asyncio.to_thread(transform_image, image, tmp_path, cfg, "storycta"):
                send_path = tmp_path
        intro = (
            f"📲 **STORY CTA — identité `{identity}`**\n"
            f"📥 Télécharge la photo + écris la caption dessus.\n\n"
            f"🕖 **À POSTER LE SOIR ENTRE 19H ET 23H** — c'est le créneau "
            f"où tes clics convertissent le mieux 💰"
        )
        try:
            await channel.send(content=intro, file=discord.File(send_path))
        except discord.HTTPException:
            return False
        await channel.send(caption)
        return True
    finally:
        if tmp_dir:
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


async def run_autopost_for_all(bot):
    """Iterate all VAs and post content for each."""
    cfg = load_autopost_config()
    users = load_users()
    count = 0
    errors = 0
    for user_id_str, raw_data in users.items():
        if isinstance(raw_data, str):
            identity = raw_data
            channel_id = None
            auto_enabled = True
        else:
            identity = raw_data.get("identity")
            channel_id = raw_data.get("channel_id")
            auto_enabled = raw_data.get("auto_post", True)
        if not auto_enabled or not channel_id or not identity:
            continue
        channel = bot.get_channel(channel_id)
        if not channel:
            log.warning(f"Autopost: channel {channel_id} introuvable pour user {user_id_str}")
            continue
        try:
            if cfg.get("post_reel", True):
                await send_reel(channel, identity)
            if cfg.get("post_post", True):
                await send_post(channel, identity)
            if cfg.get("post_story", True):
                await send_story(channel, identity)
            if cfg.get("post_storycta", True):
                await send_storycta(channel, identity)
            count += 1
        except Exception as e:
            log.error(f"Autopost erreur pour user {user_id_str}: {e}")
            errors += 1
    return count, errors


async def run_broadcast(
    bot,
    identity_filter: str = None,
    n_reels: int = 0,
    n_posts: int = 0,
    n_stories: int = 0,
    n_storyctas: int = 0,
):
    """Envoie N de chaque type a chaque VA correspondant (ou tous si filter=None).

    Retourne (nb_vas_touches, nb_erreurs).
    """
    users = load_users()
    count = 0
    errors = 0
    for user_id_str, raw_data in users.items():
        if isinstance(raw_data, str):
            identity = raw_data
            channel_id = None
            auto_enabled = True
        else:
            identity = raw_data.get("identity")
            channel_id = raw_data.get("channel_id")
            auto_enabled = raw_data.get("auto_post", True)
        if not auto_enabled or not channel_id or not identity:
            continue
        # Filtre par identite si specifie (comparaison case-insensitive)
        if identity_filter and identity.lower() != identity_filter.lower():
            continue
        channel = bot.get_channel(channel_id)
        if not channel:
            log.warning(f"Broadcast: channel {channel_id} introuvable pour {user_id_str}")
            continue
        try:
            for _ in range(n_reels):
                await send_reel(channel, identity)
            for _ in range(n_posts):
                await send_post(channel, identity)
            for _ in range(n_stories):
                await send_story(channel, identity)
            for _ in range(n_storyctas):
                await send_storycta(channel, identity)
            count += 1
        except Exception as e:
            log.error(f"Broadcast erreur pour user {user_id_str}: {e}")
            errors += 1
    return count, errors


class AutoPost(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self.check_autopost.start()

    def cog_unload(self):
        self.check_autopost.cancel()

    async def get_owner_id(self):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return self._owner_id

    async def is_admin(self, user_id):
        if user_id == await self.get_owner_id():
            return True
        wl_path = DATA_DIR / "whitelist.json"
        if wl_path.exists():
            try:
                wl = json.loads(wl_path.read_text(encoding="utf-8"))
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

    @tasks.loop(minutes=1)
    async def check_autopost(self):
        cfg = load_autopost_config()
        if not cfg.get("enabled", False):
            return
        now = datetime.now(timezone.utc)
        target_h = cfg.get("hour_utc", 7)
        target_m = cfg.get("minute_utc", 0)
        if now.hour != target_h or now.minute != target_m:
            return
        today = now.date().isoformat()
        if cfg.get("last_run_date") == today:
            return
        log.info("Autopost: démarrage du run quotidien")
        count, errors = await run_autopost_for_all(self.bot)
        cfg["last_run_date"] = today
        save_autopost_config(cfg)
        log.info(f"Autopost: {count} VAs traités, {errors} erreurs")

    @check_autopost.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="autopostsettings", description="Affiche la config de l'auto-post quotidien")
    async def autopostsettings(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        cfg = load_autopost_config()
        msg = (
            f"⚙️ **Auto-post quotidien**\n"
            f"État: {'✅ Activé' if cfg.get('enabled') else '❌ Désactivé'}\n"
            f"Heure: **{cfg.get('hour_utc'):02d}:{cfg.get('minute_utc'):02d} UTC** "
            f"({(cfg.get('hour_utc') + 2) % 24:02d}h Paris été, {(cfg.get('hour_utc') + 1) % 24:02d}h Paris hiver)\n"
            f"Dernier run: {cfg.get('last_run_date') or 'jamais'}\n\n"
            f"📦 Contenu posté:\n"
            f"  • Reel: {'✅' if cfg.get('post_reel') else '❌'}\n"
            f"  • Post: {'✅' if cfg.get('post_post') else '❌'}\n"
            f"  • Story: {'✅' if cfg.get('post_story') else '❌'}\n"
            f"  • Story CTA: {'✅' if cfg.get('post_storycta') else '❌'}\n"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="autopostenable", description="Active/désactive l'auto-post quotidien")
    @app_commands.describe(enabled="True ou False")
    async def autopostenable(self, interaction: discord.Interaction, enabled: bool):
        if not await self.require_admin(interaction):
            return
        cfg = load_autopost_config()
        cfg["enabled"] = enabled
        save_autopost_config(cfg)
        await interaction.response.send_message(
            f"✅ Auto-post : {'activé' if enabled else 'désactivé'}", ephemeral=True
        )

    @app_commands.command(name="autoposttime", description="Change l'heure du run quotidien (UTC)")
    @app_commands.describe(hour="Heure UTC (0-23)", minute="Minute (0-59)")
    async def autoposttime(self, interaction: discord.Interaction, hour: int, minute: int = 0):
        if not await self.require_admin(interaction):
            return
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            await interaction.response.send_message("Heure invalide.", ephemeral=True)
            return
        cfg = load_autopost_config()
        cfg["hour_utc"] = hour
        cfg["minute_utc"] = minute
        save_autopost_config(cfg)
        await interaction.response.send_message(
            f"✅ Heure de l'auto-post : **{hour:02d}:{minute:02d} UTC**", ephemeral=True
        )

    @app_commands.command(name="autoposttoggle", description="Active/désactive un type de contenu pour l'auto-post")
    @app_commands.describe(content_type="reel, post, story ou storycta", enabled="True ou False")
    async def autoposttoggle(self, interaction: discord.Interaction, content_type: str, enabled: bool):
        if not await self.require_admin(interaction):
            return
        key = f"post_{content_type.lower()}"
        if key not in ("post_reel", "post_post", "post_story", "post_storycta"):
            await interaction.response.send_message(
                "Type invalide. Utilise: reel, post, story, storycta", ephemeral=True
            )
            return
        cfg = load_autopost_config()
        cfg[key] = enabled
        save_autopost_config(cfg)
        await interaction.response.send_message(
            f"✅ Auto-post `{content_type}` : {'activé' if enabled else 'désactivé'}", ephemeral=True
        )

    @app_commands.command(
        name="broadcast",
        description="[ADMIN] Envoie N reels/posts/stories/storyctas a tous les VAs (filtre par identite)",
    )
    @app_commands.describe(
        identite="Si specifie, envoie SEULEMENT aux VAs de cette identite (ex: julia). Vide = tous.",
        reels="Nombre de reels a envoyer a chaque VA (defaut 0)",
        posts="Nombre de posts photo a envoyer a chaque VA (defaut 0)",
        stories="Nombre de stories a envoyer a chaque VA (defaut 0)",
        storyctas="Nombre de story CTAs a envoyer a chaque VA (defaut 0)",
    )
    async def broadcast(
        self,
        interaction: discord.Interaction,
        identite: str = None,
        reels: app_commands.Range[int, 0, 20] = 0,
        posts: app_commands.Range[int, 0, 20] = 0,
        stories: app_commands.Range[int, 0, 20] = 0,
        storyctas: app_commands.Range[int, 0, 20] = 0,
    ):
        if not await self.require_admin(interaction):
            return
        total = reels + posts + stories + storyctas
        if total == 0:
            await interaction.response.send_message(
                "Tu dois specifier au moins un type de contenu (reels / posts / stories / storyctas > 0).\n"
                "Exemple: `/broadcast identite:julia reels:3 stories:3 storyctas:1`",
                ephemeral=True,
            )
            return
        if total > 30:
            await interaction.response.send_message(
                f"Trop d'items demandes ({total}). Limite: 30 par VA pour eviter le spam.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        filtre_msg = f"identite **{identite}**" if identite else "**tous les VAs**"
        await interaction.followup.send(
            f"🚀 Broadcast en cours sur {filtre_msg} : "
            f"{reels} reels + {posts} posts + {stories} stories + {storyctas} CTAs par VA...",
            ephemeral=True,
        )
        count, errors = await run_broadcast(
            self.bot,
            identity_filter=identite,
            n_reels=reels,
            n_posts=posts,
            n_stories=stories,
            n_storyctas=storyctas,
        )
        await interaction.followup.send(
            f"✅ Broadcast termine : **{count}** VAs touches, **{errors}** erreur(s).\n"
            f"Total envois : ~{count * total} items.",
            ephemeral=True,
        )

    @app_commands.command(name="setvachannel", description="[ADMIN] Définit le salon d'auto-post pour un VA")
    @app_commands.describe(user="Le VA", channel="Le salon (laisse vide pour utiliser le salon courant)")
    async def setvachannel(self, interaction: discord.Interaction, user: discord.Member, channel: discord.TextChannel = None):
        if not await self.require_admin(interaction):
            return
        target_channel = channel or interaction.channel
        users = load_users()
        data = users.get(str(user.id))
        if data is None:
            await interaction.response.send_message(
                f"{user.mention} n'a pas d'identité. Fais /adduser d'abord.", ephemeral=True
            )
            return
        if isinstance(data, str):
            users[str(user.id)] = {"identity": data, "channel_id": target_channel.id, "auto_post": True}
        else:
            data["channel_id"] = target_channel.id
            users[str(user.id)] = data
        save_users(users)
        await interaction.response.send_message(
            f"✅ Salon auto-post de {user.mention} : {target_channel.mention}", ephemeral=True
        )

    @app_commands.command(name="togglevaautopost", description="[ADMIN] Active/désactive l'auto-post pour UN VA spécifique")
    @app_commands.describe(user="Le VA", enabled="True ou False")
    async def togglevaautopost(self, interaction: discord.Interaction, user: discord.Member, enabled: bool):
        if not await self.require_admin(interaction):
            return
        users = load_users()
        data = users.get(str(user.id))
        if data is None:
            await interaction.response.send_message(f"{user.mention} n'a pas d'identité.", ephemeral=True)
            return
        if isinstance(data, str):
            users[str(user.id)] = {"identity": data, "channel_id": None, "auto_post": enabled}
        else:
            data["auto_post"] = enabled
            users[str(user.id)] = data
        save_users(users)
        await interaction.response.send_message(
            f"✅ Auto-post pour {user.mention} : {'activé' if enabled else 'désactivé'}", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(AutoPost(bot))
