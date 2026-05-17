import os
import io
import json
import random
import zipfile
import shutil
import tempfile
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

from video_transform import (
    load_config as load_transform_config,
    save_config as save_transform_config,
    reset_config as reset_transform_config,
    config_summary_text as transform_config_summary,
    is_ffmpeg_available,
)
from image_transform import (
    load_config as load_image_config,
    save_config as save_image_config,
    reset_config as reset_image_config,
    config_summary_text as image_config_summary,
    is_pillow_available,
)

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
PROFILE_PICS_DIR = DATA_DIR / "profile_pics"
WHITELIST_FILE = DATA_DIR / "whitelist.json"
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


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_identities():
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())


def identity_videos_dir(name):
    return IDENTITIES_DIR / name / "videos"


def identity_bios_file(name):
    return IDENTITIES_DIR / name / "bios.txt"


def identity_usernames_file(name):
    return IDENTITIES_DIR / name / "usernames.txt"


SHARED_BIOS_FILE = DATA_DIR / "bios.txt"


def bios_file_for(identity):
    """Per-identity bios path if identity given, else shared path."""
    return identity_bios_file(identity) if identity else SHARED_BIOS_FILE


def read_lines(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    if lines:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")


def read_bios_from(path):
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    return [b.strip() for b in content.split("---") if b.strip()]


def write_bios_to(path, bios):
    path.parent.mkdir(parents=True, exist_ok=True)
    if bios:
        path.write_text("\n---\n".join(bios) + "\n", encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")


def read_bios(identity):
    """Backward-compat: read bios for an identity."""
    return read_bios_from(bios_file_for(identity))


def write_bios(identity, bios):
    write_bios_to(bios_file_for(identity), bios)


def caption_path_for(video_path):
    return video_path.with_suffix(".txt")


def description_path_for(video_path):
    return video_path.with_suffix(".desc.txt")


def example_video_path_for(video_path):
    """Find example video file (same stem + .example + any video ext)."""
    folder = video_path.parent
    for ext in VIDEO_EXTS:
        candidate = folder / f"{video_path.stem}.example{ext}"
        if candidate.exists():
            return candidate
    return None


def example_image_path_for(image_path):
    """Find example image file (same stem + .example + any image ext)."""
    folder = image_path.parent
    for ext in IMAGE_EXTS:
        candidate = folder / f"{image_path.stem}.example{ext}"
        if candidate.exists():
            return candidate
    return None


def is_example_image_filename(filename):
    name_lower = filename.lower()
    stem, ext = os.path.splitext(name_lower)
    return ext in IMAGE_EXTS and stem.endswith(".example")


def identity_posts_dir(name):
    return IDENTITIES_DIR / name / "posts"


def identity_stories_dir(name):
    return IDENTITIES_DIR / name / "stories"


def identity_story_ctas_dir(name):
    return IDENTITIES_DIR / name / "storyctas"


STORY_CTA_CAPTIONS_FILE = DATA_DIR / "story_cta_captions.txt"


def list_image_items(directory):
    """Return list of (filename, caption, description, has_example) for clean images."""
    if not directory.exists():
        return []
    out = []
    for p in sorted(directory.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        if p.stem.lower().endswith(".example"):
            continue
        cap = p.with_suffix(".txt")
        desc = p.with_suffix(".desc.txt")
        caption = cap.read_text(encoding="utf-8").strip() if cap.exists() else None
        description = desc.read_text(encoding="utf-8").strip() if desc.exists() else None
        has_example = example_image_path_for(p) is not None
        out.append((p.name, caption, description, has_example))
    return out


def is_example_video_filename(filename):
    """True if filename looks like 'something.example.<vid_ext>'."""
    name_lower = filename.lower()
    stem, ext = os.path.splitext(name_lower)
    return ext in VIDEO_EXTS and stem.endswith(".example")


def is_clean_video_file(p):
    """True if p is a video and NOT an example video."""
    return (
        p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.lower().endswith(".example")
    )


def list_reels(name):
    """Return list of (filename, caption, description, has_example) tuples."""
    videos_dir = identity_videos_dir(name)
    if not videos_dir.exists():
        return []
    out = []
    for p in sorted(videos_dir.iterdir()):
        if not is_clean_video_file(p):
            continue
        cap_path = caption_path_for(p)
        desc_path = description_path_for(p)
        caption = cap_path.read_text(encoding="utf-8").strip() if cap_path.exists() else None
        description = desc_path.read_text(encoding="utf-8").strip() if desc_path.exists() else None
        has_example = example_video_path_for(p) is not None
        out.append((p.name, caption, description, has_example))
    return out


def sanitize_identity_name(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_-").lower()


def truncate_for_display(s, max_len=80):
    s = (s or "").replace("\n", " ⏎ ")
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def reel_preview_text(identity, current_index, reels):
    """Build the preview text for a reel in the manage view."""
    if not reels:
        return f"Aucun reel pour `{identity}`."
    if current_index >= len(reels):
        current_index = len(reels) - 1
    filename, cap, desc, has_ex = reels[current_index]
    parts = [
        f"**Reel {current_index + 1}/{len(reels)}** — identité `{identity}`",
        f"📁 `{filename}`",
        "",
        f"📝 **Caption :**\n```\n{cap}\n```" if cap else "📝 *(pas de caption)*",
        f"📄 **Description :**\n```\n{desc}\n```" if desc else "📄 *(pas de description)*",
        f"🎥 Vidéo exemple : {'✅' if has_ex else '❌'}",
    ]
    return "\n".join(parts)


def preview_video_for(identity, filename):
    """Return path of example video if exists, else clean video."""
    videos_dir = identity_videos_dir(identity)
    video_path = videos_dir / filename
    ex = example_video_path_for(video_path)
    return ex if ex else video_path


class ReelManagerView(discord.ui.View):
    def __init__(self, identity, current_index=0):
        super().__init__(timeout=600)
        self.identity = identity
        self.current_index = current_index

    async def _refresh(self, interaction):
        reels = list_reels(self.identity)
        if not reels:
            await interaction.response.edit_message(
                content=f"Plus aucun reel pour `{self.identity}`.",
                view=None,
                attachments=[],
            )
            self.stop()
            return
        if self.current_index >= len(reels):
            self.current_index = len(reels) - 1
        if self.current_index < 0:
            self.current_index = 0
        filename = reels[self.current_index][0]
        text = reel_preview_text(self.identity, self.current_index, reels)
        video_path = preview_video_for(self.identity, filename)
        try:
            await interaction.response.edit_message(
                content=text,
                view=self,
                attachments=[discord.File(video_path)],
            )
        except discord.HTTPException:
            # Si la video est trop lourde
            await interaction.response.edit_message(
                content=text + "\n\n⚠️ *(Vidéo trop lourde pour preview)*",
                view=self,
                attachments=[],
            )

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index -= 1
        await self._refresh(interaction)

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index += 1
        await self._refresh(interaction)

    @discord.ui.button(label="🗑️ Supprimer ce reel", style=discord.ButtonStyle.danger)
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        reels = list_reels(self.identity)
        if not reels:
            await interaction.response.send_message("Plus aucun reel.", ephemeral=True)
            return
        if self.current_index >= len(reels):
            self.current_index = len(reels) - 1
        filename = reels[self.current_index][0]
        videos_dir = identity_videos_dir(self.identity)
        video_path = videos_dir / filename
        video_path.unlink(missing_ok=True)
        caption_path_for(video_path).unlink(missing_ok=True)
        description_path_for(video_path).unlink(missing_ok=True)
        ex = example_video_path_for(video_path)
        if ex:
            ex.unlink(missing_ok=True)
        # Refresh: if current index now out of range, decrement
        new_reels = list_reels(self.identity)
        if self.current_index >= len(new_reels):
            self.current_index = max(0, len(new_reels) - 1)
        await self._refresh(interaction)


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None

    async def get_owner_id(self):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return self._owner_id

    async def is_owner(self, user_id):
        return user_id == await self.get_owner_id()

    async def is_admin(self, user_id):
        if await self.is_owner(user_id):
            return True
        return user_id in load_json(WHITELIST_FILE, [])

    async def require_admin(self, interaction):
        if not await self.is_admin(interaction.user.id):
            msg = "Tu n'es pas autorisé."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    async def identity_autocomplete(self, interaction, current):
        return [
            app_commands.Choice(name=n, value=n)
            for n in list_identities()
            if current.lower() in n.lower()
        ][:25]

    # ---------- WHITELIST ----------

    @app_commands.command(name="whitelist", description="[OWNER] Whitelist un utilisateur pour les commandes admin")
    @app_commands.describe(user="L'utilisateur à autoriser")
    async def whitelist(self, interaction: discord.Interaction, user: discord.User):
        if not await self.is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        wl = load_json(WHITELIST_FILE, [])
        if user.id in wl:
            await interaction.response.send_message(f"{user.mention} déjà whitelisté.", ephemeral=True)
            return
        wl.append(user.id)
        save_json(WHITELIST_FILE, wl)
        await interaction.response.send_message(f"✅ {user.mention} ajouté à la whitelist.", ephemeral=True)

    # ---------- IDENTITES ----------

    @app_commands.command(name="addidentite", description="Crée une identité avec un zip (vidéos + captions + descriptions)")
    @app_commands.describe(
        name="Nom de l'identité",
        videos_zip="Zip avec vidéos. Pour pair: video.txt = caption (overlay), video.desc.txt = description (post)"
    )
    async def addidentite(self, interaction: discord.Interaction, name: str, videos_zip: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not videos_zip.filename.lower().endswith(".zip"):
            await interaction.followup.send("Le fichier doit être un .zip", ephemeral=True)
            return
        safe_name = sanitize_identity_name(name)
        if not safe_name:
            await interaction.followup.send("Nom invalide.", ephemeral=True)
            return
        identity_dir = IDENTITIES_DIR / safe_name
        videos_dir = identity_dir / "videos"
        if identity_dir.exists():
            await interaction.followup.send(f"L'identité `{safe_name}` existe déjà.", ephemeral=True)
            return
        videos_dir.mkdir(parents=True, exist_ok=True)
        zip_bytes = await videos_zip.read()
        videos = 0
        examples = 0
        captions = 0
        descriptions = 0
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = tmp.name
        try:
            with zipfile.ZipFile(tmp_path) as zf:
                for member in zf.namelist():
                    base = os.path.basename(member)
                    if not base:
                        continue
                    lower = base.lower()
                    if lower.endswith(".desc.txt"):
                        with zf.open(member) as src:
                            (videos_dir / base).write_bytes(src.read())
                        descriptions += 1
                    elif lower.endswith(".txt"):
                        with zf.open(member) as src:
                            (videos_dir / base).write_bytes(src.read())
                        captions += 1
                    elif is_example_video_filename(base):
                        with zf.open(member) as src, (videos_dir / base).open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        examples += 1
                    else:
                        ext = os.path.splitext(base)[1].lower()
                        if ext in VIDEO_EXTS:
                            with zf.open(member) as src, (videos_dir / base).open("wb") as dst:
                                shutil.copyfileobj(src, dst)
                            videos += 1
        finally:
            os.unlink(tmp_path)
        if videos == 0:
            shutil.rmtree(identity_dir)
            await interaction.followup.send("Aucune vidéo trouvée dans le zip.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Identité `{safe_name}` créée: **{videos}** clean / **{examples}** exemples / **{captions}** caption(s) / **{descriptions}** description(s).",
            ephemeral=True,
        )

    @app_commands.command(name="listidentites", description="Liste les identités + nb de reels et VA assignés")
    async def listidentites(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        identities = list_identities()
        if not identities:
            await interaction.response.send_message("Aucune identité.", ephemeral=True)
            return
        users = load_json(USERS_FILE, {})
        lines = []
        for n in identities:
            reels = list_reels(n)
            n_reels = len(reels)
            n_captions = sum(1 for r in reels if r[1])
            n_descs = sum(1 for r in reels if r[2])
            n_examples = sum(1 for r in reels if r[3])
            assigned = sum(1 for v in users.values() if v == n)
            n_bios = len(read_bios(n))
            n_usernames = len(read_lines(identity_usernames_file(n)))
            lines.append(
                f"• `{n}` — 🎬{n_reels} reels ({n_captions}cap/{n_descs}desc/{n_examples}ex) • 📝{n_bios} bios • 👤{n_usernames} usernames • {assigned} VA"
            )
        await interaction.response.send_message(
            f"**Identités** ({len(identities)})\n" + "\n".join(lines), ephemeral=True
        )

    @app_commands.command(name="deleteidentite", description="Supprime une identité et tout son contenu")
    @app_commands.describe(name="Nom exact de l'identité")
    async def deleteidentite(self, interaction: discord.Interaction, name: str):
        if not await self.require_admin(interaction):
            return
        identity_dir = IDENTITIES_DIR / sanitize_identity_name(name)
        if not identity_dir.exists():
            await interaction.response.send_message(f"Identité introuvable.", ephemeral=True)
            return
        shutil.rmtree(identity_dir)
        users = load_json(USERS_FILE, {})
        detached = [uid for uid, ident in users.items() if ident == sanitize_identity_name(name)]
        for uid in detached:
            del users[uid]
        save_json(USERS_FILE, users)
        await interaction.response.send_message(
            f"✅ Identité supprimée. {len(detached)} VA détaché(s).", ephemeral=True
        )

    # ---------- REELS (vidéo + caption pair) ----------

    @app_commands.command(name="addreel", description="Ajoute un reel à une identité")
    @app_commands.describe(
        identity="Nom de l'identité",
        video="Vidéo CLEAN (à télécharger par le VA)",
        example_video="Vidéo EXEMPLE du rendu final (optionnel)",
        caption="Caption à mettre EN OVERLAY sur la vidéo (optionnel, \\n = retour ligne)",
        description="Description du post Instagram (optionnel, \\n = retour ligne)"
    )
    async def addreel(
        self,
        interaction: discord.Interaction,
        identity: str,
        video: discord.Attachment,
        example_video: discord.Attachment = None,
        caption: str = None,
        description: str = None,
    ):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        safe = sanitize_identity_name(identity)
        if not (IDENTITIES_DIR / safe).exists():
            await interaction.followup.send(f"Identité `{safe}` introuvable. Crée-la avec /addidentite.", ephemeral=True)
            return
        ext = os.path.splitext(video.filename)[1].lower()
        if ext not in VIDEO_EXTS:
            await interaction.followup.send("Format vidéo non supporté.", ephemeral=True)
            return
        videos_dir = identity_videos_dir(safe)
        videos_dir.mkdir(parents=True, exist_ok=True)
        target = videos_dir / video.filename
        if target.exists():
            await interaction.followup.send(f"Fichier `{video.filename}` existe déjà.", ephemeral=True)
            return
        target.write_bytes(await video.read())
        extras = []
        if caption:
            caption_path_for(target).write_text(caption, encoding="utf-8")
            extras.append("caption")
        if description:
            description_path_for(target).write_text(description, encoding="utf-8")
            extras.append("description")
        if example_video:
            ex_ext = os.path.splitext(example_video.filename)[1].lower()
            if ex_ext not in VIDEO_EXTS:
                await interaction.followup.send(
                    f"Vidéo enregistrée mais format de la vidéo exemple ({ex_ext}) non supporté.",
                    ephemeral=True,
                )
                return
            ex_target = videos_dir / f"{target.stem}.example{ex_ext}"
            ex_target.write_bytes(await example_video.read())
            extras.append("exemple")
        suffix = f" + {' + '.join(extras)}" if extras else ""
        await interaction.followup.send(
            f"✅ Reel `{video.filename}` ajouté à `{safe}`{suffix}.", ephemeral=True
        )

    @app_commands.command(name="setreelexample", description="Ajoute/remplace la vidéo exemple d'un reel")
    @app_commands.describe(
        identity="Nom de l'identité",
        video_filename="Nom exact de la vidéo (voir /listreels)",
        example_video="Vidéo EXEMPLE du rendu final"
    )
    async def setreelexample(self, interaction: discord.Interaction, identity: str, video_filename: str, example_video: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        safe = sanitize_identity_name(identity)
        videos_dir = identity_videos_dir(safe)
        video_path = videos_dir / video_filename
        if not video_path.exists():
            await interaction.followup.send("Vidéo introuvable.", ephemeral=True)
            return
        ex_ext = os.path.splitext(example_video.filename)[1].lower()
        if ex_ext not in VIDEO_EXTS:
            await interaction.followup.send("Format de la vidéo exemple non supporté.", ephemeral=True)
            return
        # Supprimer ancienne example si existait (autre extension)
        old_example = example_video_path_for(video_path)
        if old_example:
            old_example.unlink(missing_ok=True)
        ex_target = videos_dir / f"{video_path.stem}.example{ex_ext}"
        ex_target.write_bytes(await example_video.read())
        await interaction.followup.send(
            f"✅ Vidéo exemple mise à jour pour `{video_filename}`.", ephemeral=True
        )

    @app_commands.command(name="setreelcaption", description="Définit la caption (overlay) d'un reel")
    @app_commands.describe(
        identity="Nom de l'identité",
        video_filename="Nom exact du fichier vidéo (voir /listreels)",
        caption="Nouvelle caption (\\n = retour ligne)"
    )
    async def setreelcaption(self, interaction: discord.Interaction, identity: str, video_filename: str, caption: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        video_path = identity_videos_dir(safe) / video_filename
        if not video_path.exists():
            await interaction.response.send_message("Vidéo introuvable.", ephemeral=True)
            return
        caption_path_for(video_path).write_text(caption, encoding="utf-8")
        await interaction.response.send_message(
            f"✅ Caption mise à jour pour `{video_filename}`.", ephemeral=True
        )

    @app_commands.command(name="setreeldescription", description="Définit la description (post) d'un reel")
    @app_commands.describe(
        identity="Nom de l'identité",
        video_filename="Nom exact du fichier vidéo (voir /listreels)",
        description="Nouvelle description (\\n = retour ligne)"
    )
    async def setreeldescription(self, interaction: discord.Interaction, identity: str, video_filename: str, description: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        video_path = identity_videos_dir(safe) / video_filename
        if not video_path.exists():
            await interaction.response.send_message("Vidéo introuvable.", ephemeral=True)
            return
        description_path_for(video_path).write_text(description, encoding="utf-8")
        await interaction.response.send_message(
            f"✅ Description mise à jour pour `{video_filename}`.", ephemeral=True
        )

    @app_commands.command(name="listreels", description="Liste les reels d'une identité")
    @app_commands.describe(identity="Nom de l'identité")
    async def listreels(self, interaction: discord.Interaction, identity: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        reels = list_reels(safe)
        if not reels:
            await interaction.response.send_message(f"Aucun reel pour `{safe}`.", ephemeral=True)
            return
        lines = []
        for i, (filename, cap, desc, has_ex) in enumerate(reels):
            cap_s = truncate_for_display(cap, 40) if cap else "❌"
            desc_s = truncate_for_display(desc, 40) if desc else "❌"
            ex_s = "🎥" if has_ex else "❌"
            lines.append(f"`{i}` **{filename}** • cap: {cap_s} • desc: {desc_s} • ex: {ex_s}")
        text = f"**Reels de `{safe}`** ({len(reels)})\n" + "\n".join(lines)
        if len(text) <= 1900:
            await interaction.response.send_message(text, ephemeral=True)
        else:
            buf = io.BytesIO()
            buf.write(f"Reels de {safe} ({len(reels)})\n\n".encode("utf-8"))
            for i, (filename, cap, desc, has_ex) in enumerate(reels):
                buf.write(f"=== [{i}] {filename} (example: {'oui' if has_ex else 'non'}) ===\n".encode("utf-8"))
                buf.write(f"-- CAPTION --\n{cap or '(aucune)'}\n".encode("utf-8"))
                buf.write(f"-- DESCRIPTION --\n{desc or '(aucune)'}\n\n".encode("utf-8"))
            buf.seek(0)
            await interaction.response.send_message(
                f"**Reels de `{safe}`** ({len(reels)}) — voir fichier",
                file=discord.File(buf, filename=f"reels_{safe}.txt"),
                ephemeral=True,
            )

    @app_commands.command(name="managereels", description="Menu interactif: voir + supprimer les reels page par page")
    @app_commands.describe(identity="Nom de l'identité")
    async def managereels(self, interaction: discord.Interaction, identity: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        reels = list_reels(safe)
        if not reels:
            await interaction.response.send_message(f"Aucun reel pour `{safe}`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        view = ReelManagerView(safe, 0)
        text = reel_preview_text(safe, 0, reels)
        video_path = preview_video_for(safe, reels[0][0])
        try:
            await interaction.followup.send(
                content=text, view=view, file=discord.File(video_path), ephemeral=True
            )
        except discord.HTTPException:
            await interaction.followup.send(
                content=text + "\n\n⚠️ *(Vidéo trop lourde pour preview)*",
                view=view,
                ephemeral=True,
            )

    @app_commands.command(name="clearreels", description="Supprime TOUS les reels d'une identité (irréversible)")
    @app_commands.describe(
        identity="Nom de l'identité",
        confirm="Tape exactement le nom de l'identité pour confirmer"
    )
    async def clearreels(self, interaction: discord.Interaction, identity: str, confirm: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        if confirm != safe:
            await interaction.response.send_message(
                f"⚠️ Pour confirmer la suppression de **TOUS** les reels de `{safe}`, refais la commande avec `confirm:{safe}`.",
                ephemeral=True,
            )
            return
        videos_dir = identity_videos_dir(safe)
        if not videos_dir.exists():
            await interaction.response.send_message(f"Identité `{safe}` introuvable.", ephemeral=True)
            return
        deleted = 0
        for p in list(videos_dir.iterdir()):
            if p.is_file():
                p.unlink(missing_ok=True)
                deleted += 1
        await interaction.response.send_message(
            f"✅ {deleted} fichier(s) supprimé(s) de l'identité `{safe}`.", ephemeral=True
        )

    @app_commands.command(name="clearbios", description="Supprime TOUTES les bios. Sans identité: les partagées.")
    @app_commands.describe(
        confirm="Tape 'shared' (pour partagées) ou le nom de l'identité pour confirmer",
        identity="Optionnel: identité spécifique"
    )
    async def clearbios(self, interaction: discord.Interaction, confirm: str, identity: str = None):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity) if identity else None
        expected = safe if safe else "shared"
        if confirm != expected:
            await interaction.response.send_message(
                f"⚠️ Refais la commande avec `confirm:{expected}` pour confirmer.",
                ephemeral=True,
            )
            return
        n = len(read_bios(safe))
        write_bios(safe, [])
        label = f"`{safe}`" if safe else "partagées"
        await interaction.response.send_message(
            f"✅ {n} bio(s) {label} supprimée(s).", ephemeral=True
        )

    @app_commands.command(name="clearusernames", description="Supprime TOUS les usernames d'une identité")
    @app_commands.describe(
        identity="Nom de l'identité",
        confirm="Tape exactement le nom de l'identité pour confirmer"
    )
    async def clearusernames(self, interaction: discord.Interaction, identity: str, confirm: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        if confirm != safe:
            await interaction.response.send_message(
                f"⚠️ Refais la commande avec `confirm:{safe}` pour confirmer.",
                ephemeral=True,
            )
            return
        path = identity_usernames_file(safe)
        n = len(read_lines(path))
        write_lines(path, [])
        await interaction.response.send_message(
            f"✅ {n} username(s) supprimé(s) de `{safe}`.", ephemeral=True
        )

    @app_commands.command(name="deletereel", description="Supprime un reel (vidéo + caption + description + exemple)")
    @app_commands.describe(identity="Nom de l'identité", index="Index (voir /listreels)")
    async def deletereel(self, interaction: discord.Interaction, identity: str, index: int):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        reels = list_reels(safe)
        if index < 0 or index >= len(reels):
            await interaction.response.send_message(
                f"Index invalide (0-{len(reels)-1}).", ephemeral=True
            )
            return
        filename = reels[index][0]
        videos_dir = identity_videos_dir(safe)
        video_path = videos_dir / filename
        video_path.unlink(missing_ok=True)
        caption_path_for(video_path).unlink(missing_ok=True)
        description_path_for(video_path).unlink(missing_ok=True)
        ex = example_video_path_for(video_path)
        if ex:
            ex.unlink(missing_ok=True)
        await interaction.response.send_message(
            f"✅ Reel `{filename}` supprimé de `{safe}`.", ephemeral=True
        )

    # ---------- BIOS (par identité) ----------

    @app_commands.command(name="addbios", description="Ajoute des bios. Sans identité: partagées. Avec identité: spécifiques.")
    @app_commands.describe(
        file="Fichier .txt avec bios séparées par '---' sur leur propre ligne",
        identity="Optionnel: identité spécifique. Sans, les bios sont partagées entre toutes les identités."
    )
    async def addbios(self, interaction: discord.Interaction, file: discord.Attachment, identity: str = None):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not file.filename.lower().endswith(".txt"):
            await interaction.followup.send("Le fichier doit être un .txt", ephemeral=True)
            return
        safe = None
        target_label = "partagées"
        if identity:
            safe = sanitize_identity_name(identity)
            if not (IDENTITIES_DIR / safe).exists():
                await interaction.followup.send(f"Identité `{safe}` introuvable.", ephemeral=True)
                return
            target_label = f"`{safe}`"
        content = (await file.read()).decode("utf-8", errors="ignore")
        new_bios = [b.strip() for b in content.split("---") if b.strip()]
        existing = read_bios(safe)
        write_bios(safe, existing + new_bios)
        await interaction.followup.send(
            f"✅ {len(new_bios)} bio(s) ajoutée(s) {target_label} (total: {len(existing) + len(new_bios)}).",
            ephemeral=True,
        )

    @app_commands.command(name="listbios", description="Liste les bios. Sans identité: bios partagées.")
    @app_commands.describe(identity="Optionnel: identité spécifique. Sans, montre les bios partagées.")
    async def listbios(self, interaction: discord.Interaction, identity: str = None):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity) if identity else None
        bios = read_bios(safe)
        label = f"de `{safe}`" if safe else "partagées"
        if not bios:
            await interaction.response.send_message(f"Aucune bio {label}.", ephemeral=True)
            return
        lines = [f"`{i}` — {truncate_for_display(b)}" for i, b in enumerate(bios)]
        text = f"**Bios {label}** ({len(bios)})\n" + "\n".join(lines)
        if len(text) <= 1900:
            await interaction.response.send_message(text, ephemeral=True)
        else:
            buf = io.BytesIO()
            buf.write(f"Bios {label}\n\n".encode("utf-8"))
            for i, b in enumerate(bios):
                buf.write(f"=== [{i}] ===\n{b}\n\n".encode("utf-8"))
            buf.seek(0)
            await interaction.response.send_message(
                f"**Bios {label}** ({len(bios)})",
                file=discord.File(buf, filename=f"bios_{safe or 'shared'}.txt"),
                ephemeral=True,
            )

    @app_commands.command(name="deletebio", description="Supprime une bio par son index. Sans identité: bios partagées.")
    @app_commands.describe(index="Index (voir /listbios)", identity="Optionnel: identité spécifique")
    async def deletebio(self, interaction: discord.Interaction, index: int, identity: str = None):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity) if identity else None
        bios = read_bios(safe)
        if index < 0 or index >= len(bios):
            await interaction.response.send_message(
                f"Index invalide (0-{len(bios)-1}).", ephemeral=True
            )
            return
        removed = bios.pop(index)
        write_bios(safe, bios)
        await interaction.response.send_message(
            f"✅ Bio supprimée: `{truncate_for_display(removed, 100)}`", ephemeral=True
        )

    # ---------- USERNAMES (par identité) ----------

    @app_commands.command(name="addusernames", description="Ajoute des usernames à une identité (.txt, 1 par ligne)")
    @app_commands.describe(identity="Nom de l'identité", file="Fichier .txt, 1 username par ligne")
    async def addusernames(self, interaction: discord.Interaction, identity: str, file: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        safe = sanitize_identity_name(identity)
        if not (IDENTITIES_DIR / safe).exists():
            await interaction.followup.send(f"Identité `{safe}` introuvable.", ephemeral=True)
            return
        if not file.filename.lower().endswith(".txt"):
            await interaction.followup.send("Le fichier doit être un .txt", ephemeral=True)
            return
        content = (await file.read()).decode("utf-8", errors="ignore")
        new_usernames = [l.strip() for l in content.splitlines() if l.strip()]
        existing = read_lines(identity_usernames_file(safe))
        write_lines(identity_usernames_file(safe), existing + new_usernames)
        await interaction.followup.send(
            f"✅ {len(new_usernames)} username(s) ajouté(s) à `{safe}` (total: {len(existing) + len(new_usernames)}).",
            ephemeral=True,
        )

    @app_commands.command(name="listusernames", description="Liste les usernames d'une identité")
    @app_commands.describe(identity="Nom de l'identité")
    async def listusernames(self, interaction: discord.Interaction, identity: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        items = read_lines(identity_usernames_file(safe))
        if not items:
            await interaction.response.send_message(f"Aucun username pour `{safe}`.", ephemeral=True)
            return
        lines = [f"`{i}` — {truncate_for_display(x)}" for i, x in enumerate(items)]
        text = f"**Usernames de `{safe}`** ({len(items)})\n" + "\n".join(lines)
        await interaction.response.send_message(text[:1990], ephemeral=True)

    @app_commands.command(name="deleteusername", description="Supprime un username d'une identité par index")
    @app_commands.describe(identity="Nom de l'identité", index="Index (voir /listusernames)")
    async def deleteusername(self, interaction: discord.Interaction, identity: str, index: int):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        items = read_lines(identity_usernames_file(safe))
        if index < 0 or index >= len(items):
            await interaction.response.send_message(
                f"Index invalide (0-{len(items)-1}).", ephemeral=True
            )
            return
        removed = items.pop(index)
        write_lines(identity_usernames_file(safe), items)
        await interaction.response.send_message(
            f"✅ Username supprimé: `{removed}`", ephemeral=True
        )

    # ---------- PROFILE PICS (shared) ----------

    @app_commands.command(name="addprofilepic", description="Ajoute une photo de profil au pool partagé")
    @app_commands.describe(image="Photo de profil (jpg/png/webp)")
    async def addprofilepic(self, interaction: discord.Interaction, image: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        ext = os.path.splitext(image.filename)[1].lower()
        if ext not in IMAGE_EXTS:
            await interaction.followup.send("Format d'image non supporté.", ephemeral=True)
            return
        PROFILE_PICS_DIR.mkdir(parents=True, exist_ok=True)
        existing = list(PROFILE_PICS_DIR.glob("*"))
        target = PROFILE_PICS_DIR / f"pp_{len(existing) + 1}{ext}"
        target.write_bytes(await image.read())
        await interaction.followup.send(f"✅ Photo de profil `{target.name}` ajoutée.", ephemeral=True)

    @app_commands.command(name="listprofilepics", description="Liste les photos de profil")
    async def listprofilepics(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        if not PROFILE_PICS_DIR.exists():
            await interaction.response.send_message("Aucune photo de profil.", ephemeral=True)
            return
        pics = sorted(p.name for p in PROFILE_PICS_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if not pics:
            await interaction.response.send_message("Aucune photo de profil.", ephemeral=True)
            return
        lines = [f"• `{name}`" for name in pics]
        await interaction.response.send_message(
            f"**Photos de profil** ({len(pics)})\n" + "\n".join(lines)[:1900],
            ephemeral=True,
        )

    @app_commands.command(name="deleteprofilepic", description="Supprime une photo de profil par nom de fichier")
    @app_commands.describe(filename="Nom de fichier exact (voir /listprofilepics)")
    async def deleteprofilepic(self, interaction: discord.Interaction, filename: str):
        if not await self.require_admin(interaction):
            return
        target = PROFILE_PICS_DIR / filename
        if not target.exists() or not target.is_file():
            await interaction.response.send_message(f"Fichier `{filename}` introuvable.", ephemeral=True)
            return
        target.unlink()
        await interaction.response.send_message(f"✅ `{filename}` supprimée.", ephemeral=True)

    # ---------- ADDUSER ----------

    @app_commands.command(name="adduser", description="Crée un salon privé pour un VA + onboarding")
    @app_commands.describe(user="Le VA à onboarder")
    async def adduser(self, interaction: discord.Interaction, user: discord.Member):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("À utiliser dans un serveur.", ephemeral=True)
            return
        identities = list_identities()
        if not identities:
            await interaction.followup.send(
                "Aucune identité. Crée-en une avec /addidentite.", ephemeral=True
            )
            return
        identity = random.choice(identities)
        users = load_json(USERS_FILE, {})
        users[str(user.id)] = identity
        save_json(USERS_FILE, users)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True, attach_files=True
            ),
        }
        base_name = f"va-{user.name}".lower().replace(" ", "-")[:90]
        try:
            channel = await guild.create_text_channel(name=base_name, overwrites=overwrites)
        except discord.Forbidden:
            await interaction.followup.send(
                "Le bot n'a pas la permission de créer des salons. Active 'Manage Channels' pour le bot.",
                ephemeral=True,
            )
            return
        from cogs.onboarding import step_embed, OnboardingView
        embed = step_embed(0)
        await channel.send(content=user.mention, embed=embed, view=OnboardingView())
        await interaction.followup.send(
            f"✅ Salon {channel.mention} créé pour {user.mention}. Identité: `{identity}`",
            ephemeral=True,
        )


    # ---------- TRANSFORMATIONS VIDEO ----------

    @app_commands.command(name="transformsettings", description="Affiche la config actuelle des transformations vidéo")
    async def transformsettings(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        cfg = load_transform_config()
        text = transform_config_summary(cfg)
        ffmpeg_ok = "✅ ffmpeg installé" if is_ffmpeg_available() else "❌ ffmpeg MANQUANT (transfos désactivées)"
        await interaction.response.send_message(
            f"⚙️ **Config transformations**\n{ffmpeg_ok}\n\n{text}\n\n*Pour modifier : `/transformset`, `/transformtoggle`, `/transformreset`, `/transformenable`*",
            ephemeral=True,
        )

    @app_commands.command(name="transformenable", description="Active/désactive complètement les transformations")
    @app_commands.describe(enabled="True pour activer, False pour désactiver")
    async def transformenable(self, interaction: discord.Interaction, enabled: bool):
        if not await self.require_admin(interaction):
            return
        cfg = load_transform_config()
        cfg["enabled"] = enabled
        save_transform_config(cfg)
        await interaction.response.send_message(
            f"✅ Transformations globales : {'activées' if enabled else 'désactivées'}", ephemeral=True
        )

    @app_commands.command(name="transformdeletesource", description="Active/désactive la suppression de la vidéo après envoi")
    @app_commands.describe(enabled="True = supprime la source après /reel, False = garde")
    async def transformdeletesource(self, interaction: discord.Interaction, enabled: bool):
        if not await self.require_admin(interaction):
            return
        cfg = load_transform_config()
        cfg["delete_source_after_use"] = enabled
        save_transform_config(cfg)
        await interaction.response.send_message(
            f"✅ Suppression source après /reel : {'activée' if enabled else 'désactivée'}", ephemeral=True
        )

    @app_commands.command(name="transformtoggle", description="Active/désactive une option spécifique de transformation")
    @app_commands.describe(option="Nom de l'option (voir /transformsettings)", enabled="True ou False")
    async def transformtoggle(self, interaction: discord.Interaction, option: str, enabled: bool):
        if not await self.require_admin(interaction):
            return
        cfg = load_transform_config()
        if option not in cfg or not isinstance(cfg[option], dict):
            await interaction.response.send_message(
                f"Option `{option}` inconnue. Voir /transformsettings pour la liste.", ephemeral=True
            )
            return
        cfg[option]["enabled"] = enabled
        save_transform_config(cfg)
        await interaction.response.send_message(
            f"✅ `{option}` : {'activée' if enabled else 'désactivée'}", ephemeral=True
        )

    @app_commands.command(name="transformset", description="Modifie min/max d'une option")
    @app_commands.describe(
        option="Nom de l'option (ex: speed, brightness, framerate)",
        min_value="Valeur minimale",
        max_value="Valeur maximale"
    )
    async def transformset(self, interaction: discord.Interaction, option: str, min_value: float, max_value: float):
        if not await self.require_admin(interaction):
            return
        cfg = load_transform_config()
        if option not in cfg or not isinstance(cfg[option], dict):
            await interaction.response.send_message(f"Option `{option}` inconnue.", ephemeral=True)
            return
        if "min" not in cfg[option]:
            await interaction.response.send_message(f"L'option `{option}` n'a pas de min/max.", ephemeral=True)
            return
        if min_value > max_value:
            await interaction.response.send_message("min ne peut pas être supérieur à max.", ephemeral=True)
            return
        cfg[option]["min"] = min_value
        cfg[option]["max"] = max_value
        save_transform_config(cfg)
        await interaction.response.send_message(
            f"✅ `{option}` : min={min_value} max={max_value}", ephemeral=True
        )

    @app_commands.command(name="transformreset", description="Réinitialise la config transfo aux valeurs par défaut")
    async def transformreset(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        reset_transform_config()
        await interaction.response.send_message("✅ Config transfo réinitialisée aux valeurs par défaut.", ephemeral=True)

    # ---------- TRANSFORMATIONS IMAGE ----------

    @app_commands.command(name="imagetransformsettings", description="Affiche la config des transformations images")
    async def imagetransformsettings(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        cfg = load_image_config()
        text = image_config_summary(cfg)
        pillow_ok = "✅ Pillow installé" if is_pillow_available() else "❌ Pillow MANQUANT"
        await interaction.response.send_message(
            f"⚙️ **Config transformations images**\n{pillow_ok}\n\n{text}",
            ephemeral=True,
        )

    @app_commands.command(name="imagetransformenable", description="Active/désactive les transformations images")
    @app_commands.describe(enabled="True ou False")
    async def imagetransformenable(self, interaction: discord.Interaction, enabled: bool):
        if not await self.require_admin(interaction):
            return
        cfg = load_image_config()
        cfg["enabled"] = enabled
        save_image_config(cfg)
        await interaction.response.send_message(
            f"✅ Transfo images : {'activées' if enabled else 'désactivées'}", ephemeral=True
        )

    @app_commands.command(name="imagetransformtoggle", description="Active/désactive une option de transfo image")
    @app_commands.describe(option="Nom (rotation_degrees, saturation, brightness...)", enabled="True ou False")
    async def imagetransformtoggle(self, interaction: discord.Interaction, option: str, enabled: bool):
        if not await self.require_admin(interaction):
            return
        cfg = load_image_config()
        if option not in cfg or not isinstance(cfg[option], dict):
            await interaction.response.send_message(f"Option `{option}` inconnue.", ephemeral=True)
            return
        cfg[option]["enabled"] = enabled
        save_image_config(cfg)
        await interaction.response.send_message(
            f"✅ `{option}` : {'activée' if enabled else 'désactivée'}", ephemeral=True
        )

    @app_commands.command(name="imagetransformset", description="Modifie min/max d'une option de transfo image")
    @app_commands.describe(option="Nom de l'option", min_value="Min", max_value="Max")
    async def imagetransformset(self, interaction: discord.Interaction, option: str, min_value: float, max_value: float):
        if not await self.require_admin(interaction):
            return
        cfg = load_image_config()
        if option not in cfg or not isinstance(cfg[option], dict):
            await interaction.response.send_message(f"Option `{option}` inconnue.", ephemeral=True)
            return
        if "min" not in cfg[option]:
            await interaction.response.send_message(f"L'option `{option}` n'a pas de min/max.", ephemeral=True)
            return
        if min_value > max_value:
            await interaction.response.send_message("min > max impossible.", ephemeral=True)
            return
        cfg[option]["min"] = min_value
        cfg[option]["max"] = max_value
        save_image_config(cfg)
        await interaction.response.send_message(
            f"✅ `{option}` : min={min_value} max={max_value}", ephemeral=True
        )

    @app_commands.command(name="imagetransformreset", description="Reset config transfo images aux defaults")
    async def imagetransformreset(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        reset_image_config()
        await interaction.response.send_message("✅ Config transfo images réinitialisée.", ephemeral=True)

    # ---------- POSTS (photos pour le feed) ----------

    async def _add_image_content(
        self, interaction, identity, photo, example_photo, caption, description, subdir_name, label
    ):
        await interaction.response.defer(ephemeral=True)
        safe = sanitize_identity_name(identity)
        if not (IDENTITIES_DIR / safe).exists():
            await interaction.followup.send(f"Identité `{safe}` introuvable.", ephemeral=True)
            return
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in IMAGE_EXTS:
            await interaction.followup.send("Format image non supporté.", ephemeral=True)
            return
        target_dir = IDENTITIES_DIR / safe / subdir_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / photo.filename
        if target.exists():
            await interaction.followup.send(f"Fichier `{photo.filename}` existe déjà.", ephemeral=True)
            return
        target.write_bytes(await photo.read())
        extras = []
        if caption:
            target.with_suffix(".txt").write_text(caption, encoding="utf-8")
            extras.append("caption")
        if description:
            target.with_suffix(".desc.txt").write_text(description, encoding="utf-8")
            extras.append("description")
        if example_photo:
            ex_ext = os.path.splitext(example_photo.filename)[1].lower()
            if ex_ext not in IMAGE_EXTS:
                await interaction.followup.send("Format example_photo non supporté.", ephemeral=True)
                return
            ex_target = target_dir / f"{target.stem}.example{ex_ext}"
            ex_target.write_bytes(await example_photo.read())
            extras.append("exemple")
        suffix = f" + {' + '.join(extras)}" if extras else ""
        await interaction.followup.send(
            f"✅ {label} `{photo.filename}` ajouté à `{safe}`{suffix}.", ephemeral=True
        )

    @app_commands.command(name="addpost", description="Ajoute un post photo à une identité")
    @app_commands.describe(
        identity="Nom de l'identité",
        photo="Photo CLEAN (à télécharger par le VA)",
        example_photo="Photo EXEMPLE du rendu final (optionnel)",
        caption="Caption à mettre en overlay (optionnel, \\n = retour ligne)",
        description="Description du post (optionnel, \\n = retour ligne)"
    )
    async def addpost(
        self, interaction: discord.Interaction, identity: str,
        photo: discord.Attachment,
        example_photo: discord.Attachment = None,
        caption: str = None, description: str = None,
    ):
        if not await self.require_admin(interaction):
            return
        await self._add_image_content(interaction, identity, photo, example_photo, caption, description, "posts", "Post")

    async def _bulk_upload_images(self, interaction, identity, photos_zip, subdir, label):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not photos_zip.filename.lower().endswith(".zip"):
            await interaction.followup.send("Le fichier doit être un .zip", ephemeral=True)
            return
        safe = sanitize_identity_name(identity)
        if not (IDENTITIES_DIR / safe).exists():
            await interaction.followup.send(f"Identité `{safe}` introuvable.", ephemeral=True)
            return
        target_dir = IDENTITIES_DIR / safe / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        zip_bytes = await photos_zip.read()
        added = 0
        skipped = 0
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = tmp.name
        try:
            with zipfile.ZipFile(tmp_path) as zf:
                for member in zf.namelist():
                    base = os.path.basename(member)
                    if not base:
                        continue
                    ext = os.path.splitext(base)[1].lower()
                    if ext not in IMAGE_EXTS:
                        continue
                    target = target_dir / base
                    if target.exists():
                        skipped += 1
                        continue
                    with zf.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    added += 1
        finally:
            os.unlink(tmp_path)
        msg = f"✅ {added} {label}(s) ajouté(s) à `{safe}`."
        if skipped:
            msg += f" ({skipped} ignoré(s) car nom déjà pris)"
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="addposts", description="Mass upload de posts via zip")
    @app_commands.describe(identity="Nom de l'identité", photos_zip="Fichier .zip contenant les photos")
    async def addposts(self, interaction: discord.Interaction, identity: str, photos_zip: discord.Attachment):
        await self._bulk_upload_images(interaction, identity, photos_zip, "posts", "post")

    @app_commands.command(name="addstories", description="Mass upload de stories via zip")
    @app_commands.describe(identity="Nom de l'identité", photos_zip="Fichier .zip contenant les photos")
    async def addstories(self, interaction: discord.Interaction, identity: str, photos_zip: discord.Attachment):
        await self._bulk_upload_images(interaction, identity, photos_zip, "stories", "story")

    # ---------- STORY CTAs (photos 1080x1920 + captions partagées) ----------

    @app_commands.command(name="addstorycta", description="Ajoute une story CTA (photo 1080x1920) à une identité")
    @app_commands.describe(identity="Nom de l'identité", photo="Photo CLEAN (sera redimensionnée en 1080x1920)")
    async def addstorycta(self, interaction: discord.Interaction, identity: str, photo: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        safe = sanitize_identity_name(identity)
        if not (IDENTITIES_DIR / safe).exists():
            await interaction.followup.send(f"Identité `{safe}` introuvable.", ephemeral=True)
            return
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in IMAGE_EXTS:
            await interaction.followup.send("Format image non supporté.", ephemeral=True)
            return
        target_dir = identity_story_ctas_dir(safe)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / photo.filename
        if target.exists():
            await interaction.followup.send(f"Fichier `{photo.filename}` existe déjà.", ephemeral=True)
            return
        target.write_bytes(await photo.read())
        await interaction.followup.send(
            f"✅ Story CTA `{photo.filename}` ajoutée à `{safe}`.", ephemeral=True
        )

    @app_commands.command(name="addstoryctas", description="Mass upload de story CTAs via zip")
    @app_commands.describe(identity="Nom de l'identité", photos_zip="Fichier .zip contenant les photos")
    async def addstoryctas(self, interaction: discord.Interaction, identity: str, photos_zip: discord.Attachment):
        await self._bulk_upload_images(interaction, identity, photos_zip, "storyctas", "story CTA")

    @app_commands.command(name="liststoryctas", description="Liste les story CTAs d'une identité")
    @app_commands.describe(identity="Nom de l'identité")
    async def liststoryctas(self, interaction: discord.Interaction, identity: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        d = identity_story_ctas_dir(safe)
        if not d.exists():
            await interaction.response.send_message(f"Aucune story CTA pour `{safe}`.", ephemeral=True)
            return
        items = sorted(p.name for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        if not items:
            await interaction.response.send_message(f"Aucune story CTA pour `{safe}`.", ephemeral=True)
            return
        lines = [f"`{i}` — {name}" for i, name in enumerate(items)]
        text = f"**Story CTAs de `{safe}`** ({len(items)})\n" + "\n".join(lines)
        await interaction.response.send_message(text[:1990], ephemeral=True)

    @app_commands.command(name="deletestorycta", description="Supprime une story CTA par index")
    @app_commands.describe(identity="Nom de l'identité", index="Index (voir /liststoryctas)")
    async def deletestorycta(self, interaction: discord.Interaction, identity: str, index: int):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        d = identity_story_ctas_dir(safe)
        if not d.exists():
            await interaction.response.send_message("Identité ou dossier introuvable.", ephemeral=True)
            return
        items = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        if index < 0 or index >= len(items):
            await interaction.response.send_message(f"Index invalide (0-{len(items)-1}).", ephemeral=True)
            return
        target = items[index]
        target.unlink(missing_ok=True)
        await interaction.response.send_message(
            f"✅ Story CTA `{target.name}` supprimée.", ephemeral=True
        )

    # Captions partagees pour les story CTAs

    @app_commands.command(name="addstoryctacaptions", description="Ajoute des captions partagées pour les story CTAs")
    @app_commands.describe(file="Fichier .txt avec 1 caption par ligne (\\n pour retour ligne dans une caption)")
    async def addstoryctacaptions(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not file.filename.lower().endswith(".txt"):
            await interaction.followup.send("Le fichier doit être un .txt", ephemeral=True)
            return
        content = (await file.read()).decode("utf-8", errors="ignore")
        new_caps = [l.strip() for l in content.splitlines() if l.strip()]
        existing = read_lines(STORY_CTA_CAPTIONS_FILE)
        write_lines(STORY_CTA_CAPTIONS_FILE, existing + new_caps)
        await interaction.followup.send(
            f"✅ {len(new_caps)} caption(s) ajoutée(s) (total: {len(existing) + len(new_caps)}).",
            ephemeral=True,
        )

    @app_commands.command(name="liststoryctacaptions", description="Liste les captions partagées des story CTAs")
    async def liststoryctacaptions(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        items = read_lines(STORY_CTA_CAPTIONS_FILE)
        if not items:
            await interaction.response.send_message("Aucune caption story CTA.", ephemeral=True)
            return
        lines = [f"`{i}` — {truncate_for_display(c)}" for i, c in enumerate(items)]
        text = f"**Captions Story CTA** ({len(items)})\n" + "\n".join(lines)
        if len(text) <= 1900:
            await interaction.response.send_message(text, ephemeral=True)
        else:
            buf = io.BytesIO()
            buf.write(f"Captions Story CTA ({len(items)})\n\n".encode("utf-8"))
            for i, c in enumerate(items):
                buf.write(f"=== [{i}] ===\n{c}\n\n".encode("utf-8"))
            buf.seek(0)
            await interaction.response.send_message(
                f"**Captions Story CTA** ({len(items)})",
                file=discord.File(buf, filename="story_cta_captions.txt"),
                ephemeral=True,
            )

    @app_commands.command(name="deletestoryctacaption", description="Supprime une caption story CTA par index")
    @app_commands.describe(index="Index (voir /liststoryctacaptions)")
    async def deletestoryctacaption(self, interaction: discord.Interaction, index: int):
        if not await self.require_admin(interaction):
            return
        items = read_lines(STORY_CTA_CAPTIONS_FILE)
        if index < 0 or index >= len(items):
            await interaction.response.send_message(f"Index invalide (0-{len(items)-1}).", ephemeral=True)
            return
        removed = items.pop(index)
        write_lines(STORY_CTA_CAPTIONS_FILE, items)
        await interaction.response.send_message(
            f"✅ Caption supprimée: `{truncate_for_display(removed, 100)}`", ephemeral=True
        )

    async def _list_image_items(self, interaction, identity, subdir, label):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        items = list_image_items(IDENTITIES_DIR / safe / subdir)
        if not items:
            await interaction.response.send_message(f"Aucun {label.lower()} pour `{safe}`.", ephemeral=True)
            return
        lines = []
        for i, (filename, cap, desc, has_ex) in enumerate(items):
            cap_s = truncate_for_display(cap, 40) if cap else "❌"
            desc_s = truncate_for_display(desc, 40) if desc else "❌"
            ex_s = "🖼️" if has_ex else "❌"
            lines.append(f"`{i}` **{filename}** • cap: {cap_s} • desc: {desc_s} • ex: {ex_s}")
        text = f"**{label} de `{safe}`** ({len(items)})\n" + "\n".join(lines)
        if len(text) <= 1900:
            await interaction.response.send_message(text, ephemeral=True)
        else:
            buf = io.BytesIO()
            buf.write(f"{label} de {safe}\n\n".encode("utf-8"))
            for i, (filename, cap, desc, has_ex) in enumerate(items):
                buf.write(f"=== [{i}] {filename} ===\nCAPTION: {cap or '(aucune)'}\nDESC: {desc or '(aucune)'}\nEX: {'oui' if has_ex else 'non'}\n\n".encode("utf-8"))
            buf.seek(0)
            await interaction.response.send_message(
                f"**{label} de `{safe}`** ({len(items)})",
                file=discord.File(buf, filename=f"{label.lower()}_{safe}.txt"),
                ephemeral=True,
            )

    @app_commands.command(name="listposts", description="Liste les posts d'une identité")
    @app_commands.describe(identity="Nom de l'identité")
    async def listposts(self, interaction: discord.Interaction, identity: str):
        await self._list_image_items(interaction, identity, "posts", "Posts")

    async def _delete_image_item(self, interaction, identity, subdir, index, label):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        items = list_image_items(IDENTITIES_DIR / safe / subdir)
        if index < 0 or index >= len(items):
            await interaction.response.send_message(
                f"Index invalide (0-{len(items)-1}).", ephemeral=True
            )
            return
        filename = items[index][0]
        target_dir = IDENTITIES_DIR / safe / subdir
        target = target_dir / filename
        target.unlink(missing_ok=True)
        target.with_suffix(".txt").unlink(missing_ok=True)
        target.with_suffix(".desc.txt").unlink(missing_ok=True)
        ex = example_image_path_for(target)
        if ex:
            ex.unlink(missing_ok=True)
        await interaction.response.send_message(
            f"✅ {label} `{filename}` supprimé de `{safe}`.", ephemeral=True
        )

    @app_commands.command(name="deletepost", description="Supprime un post par son index")
    @app_commands.describe(identity="Nom de l'identité", index="Index (voir /listposts)")
    async def deletepost(self, interaction: discord.Interaction, identity: str, index: int):
        await self._delete_image_item(interaction, identity, "posts", index, "Post")

    # ---------- STORIES ----------

    @app_commands.command(name="addstory", description="Ajoute une story photo à une identité")
    @app_commands.describe(
        identity="Nom de l'identité",
        photo="Photo CLEAN",
        example_photo="Photo EXEMPLE du rendu final (optionnel)",
        caption="Caption à mettre en overlay (optionnel, \\n = retour ligne)",
        description="Description (optionnel)"
    )
    async def addstory(
        self, interaction: discord.Interaction, identity: str,
        photo: discord.Attachment,
        example_photo: discord.Attachment = None,
        caption: str = None, description: str = None,
    ):
        if not await self.require_admin(interaction):
            return
        await self._add_image_content(interaction, identity, photo, example_photo, caption, description, "stories", "Story")

    @app_commands.command(name="liststories", description="Liste les stories d'une identité")
    @app_commands.describe(identity="Nom de l'identité")
    async def liststories(self, interaction: discord.Interaction, identity: str):
        await self._list_image_items(interaction, identity, "stories", "Stories")

    @app_commands.command(name="deletestory", description="Supprime une story par son index")
    @app_commands.describe(identity="Nom de l'identité", index="Index (voir /liststories)")
    async def deletestory(self, interaction: discord.Interaction, identity: str, index: int):
        await self._delete_image_item(interaction, identity, "stories", index, "Story")


async def setup(bot):
    await bot.add_cog(Admin(bot))
