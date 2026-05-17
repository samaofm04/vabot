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


def read_bios(name):
    path = identity_bios_file(name)
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    return [b.strip() for b in content.split("---") if b.strip()]


def write_bios(name, bios):
    path = identity_bios_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if bios:
        path.write_text("\n---\n".join(bios) + "\n", encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")


def list_reels(name):
    """Return list of (video_filename, caption_or_None) tuples."""
    videos_dir = identity_videos_dir(name)
    if not videos_dir.exists():
        return []
    out = []
    for p in sorted(videos_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        caption_path = p.with_suffix(".txt")
        caption = caption_path.read_text(encoding="utf-8").strip() if caption_path.exists() else None
        out.append((p.name, caption))
    return out


def sanitize_identity_name(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_-").lower()


def truncate_for_display(s, max_len=80):
    s = (s or "").replace("\n", " ⏎ ")
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


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

    @app_commands.command(name="addidentite", description="Crée une identité avec un zip (vidéos + captions paires)")
    @app_commands.describe(
        name="Nom de l'identité",
        videos_zip="Fichier .zip avec vidéos. Pour les captions: mettre un .txt du même nom que la vidéo dans le zip."
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
        captions = 0
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
                    if ext in VIDEO_EXTS:
                        with zf.open(member) as src, (videos_dir / base).open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        videos += 1
                    elif ext == ".txt":
                        with zf.open(member) as src:
                            (videos_dir / base).write_bytes(src.read())
                        captions += 1
        finally:
            os.unlink(tmp_path)
        if videos == 0:
            shutil.rmtree(identity_dir)
            await interaction.followup.send("Aucune vidéo trouvée dans le zip.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Identité `{safe_name}` créée: **{videos}** vidéo(s), **{captions}** caption(s) paire(s).",
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
            n_captions = sum(1 for _, c in reels if c)
            assigned = sum(1 for v in users.values() if v == n)
            n_bios = len(read_bios(n))
            n_usernames = len(read_lines(identity_usernames_file(n)))
            lines.append(
                f"• `{n}` — 🎬{n_reels} reels ({n_captions} cap) • 📝{n_bios} bios • 👤{n_usernames} usernames • {assigned} VA"
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

    @app_commands.command(name="addreel", description="Ajoute une vidéo + caption à une identité")
    @app_commands.describe(
        identity="Nom de l'identité",
        video="Fichier vidéo (mp4/mov/webm)",
        caption="Caption recommandée (utilise \\n pour retour à la ligne, optionnel)"
    )
    async def addreel(
        self,
        interaction: discord.Interaction,
        identity: str,
        video: discord.Attachment,
        caption: str = None,
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
            await interaction.followup.send(f"Fichier `{video.filename}` existe déjà dans cette identité.", ephemeral=True)
            return
        target.write_bytes(await video.read())
        caption_msg = ""
        if caption:
            (videos_dir / (target.stem + ".txt")).write_text(caption, encoding="utf-8")
            caption_msg = " + caption"
        await interaction.followup.send(
            f"✅ Reel `{video.filename}` ajouté à `{safe}`{caption_msg}.", ephemeral=True
        )

    @app_commands.command(name="setreelcaption", description="Définit/modifie la caption d'un reel existant")
    @app_commands.describe(
        identity="Nom de l'identité",
        video_filename="Nom exact du fichier vidéo (voir /listreels)",
        caption="Nouvelle caption (\\n pour retour à la ligne)"
    )
    async def setreelcaption(
        self,
        interaction: discord.Interaction,
        identity: str,
        video_filename: str,
        caption: str,
    ):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        videos_dir = identity_videos_dir(safe)
        video_path = videos_dir / video_filename
        if not video_path.exists():
            await interaction.response.send_message(f"Vidéo introuvable.", ephemeral=True)
            return
        (videos_dir / (video_path.stem + ".txt")).write_text(caption, encoding="utf-8")
        await interaction.response.send_message(
            f"✅ Caption mise à jour pour `{video_filename}`.", ephemeral=True
        )

    @app_commands.command(name="listreels", description="Liste les reels d'une identité avec leur caption")
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
        for i, (filename, cap) in enumerate(reels):
            cap_str = truncate_for_display(cap, 60) if cap else "*(pas de caption)*"
            lines.append(f"`{i}` — **{filename}** — {cap_str}")
        text = f"**Reels de `{safe}`** ({len(reels)})\n" + "\n".join(lines)
        if len(text) <= 1900:
            await interaction.response.send_message(text, ephemeral=True)
        else:
            buf = io.BytesIO()
            buf.write(f"Reels de {safe} ({len(reels)})\n\n".encode("utf-8"))
            for i, (filename, cap) in enumerate(reels):
                buf.write(f"=== [{i}] {filename} ===\n{cap or '(pas de caption)'}\n\n".encode("utf-8"))
            buf.seek(0)
            await interaction.response.send_message(
                f"**Reels de `{safe}`** ({len(reels)}) — voir fichier",
                file=discord.File(buf, filename=f"reels_{safe}.txt"),
                ephemeral=True,
            )

    @app_commands.command(name="deletereel", description="Supprime un reel (vidéo + sa caption) d'une identité")
    @app_commands.describe(identity="Nom de l'identité", index="Index du reel (voir /listreels)")
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
        filename, _ = reels[index]
        videos_dir = identity_videos_dir(safe)
        (videos_dir / filename).unlink(missing_ok=True)
        (videos_dir / (Path(filename).stem + ".txt")).unlink(missing_ok=True)
        await interaction.response.send_message(
            f"✅ Reel `{filename}` supprimé de `{safe}`.", ephemeral=True
        )

    # ---------- BIOS (par identité) ----------

    @app_commands.command(name="addbios", description="Ajoute des bios à une identité (.txt, séparées par '---')")
    @app_commands.describe(
        identity="Nom de l'identité",
        file="Fichier .txt avec bios séparées par '---' sur leur propre ligne"
    )
    async def addbios(self, interaction: discord.Interaction, identity: str, file: discord.Attachment):
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
        new_bios = [b.strip() for b in content.split("---") if b.strip()]
        existing = read_bios(safe)
        write_bios(safe, existing + new_bios)
        await interaction.followup.send(
            f"✅ {len(new_bios)} bio(s) ajoutée(s) à `{safe}` (total: {len(existing) + len(new_bios)}).",
            ephemeral=True,
        )

    @app_commands.command(name="listbios", description="Liste les bios d'une identité")
    @app_commands.describe(identity="Nom de l'identité")
    async def listbios(self, interaction: discord.Interaction, identity: str):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
        bios = read_bios(safe)
        if not bios:
            await interaction.response.send_message(f"Aucune bio pour `{safe}`.", ephemeral=True)
            return
        lines = [f"`{i}` — {truncate_for_display(b)}" for i, b in enumerate(bios)]
        text = f"**Bios de `{safe}`** ({len(bios)})\n" + "\n".join(lines)
        if len(text) <= 1900:
            await interaction.response.send_message(text, ephemeral=True)
        else:
            buf = io.BytesIO()
            buf.write(f"Bios de {safe}\n\n".encode("utf-8"))
            for i, b in enumerate(bios):
                buf.write(f"=== [{i}] ===\n{b}\n\n".encode("utf-8"))
            buf.seek(0)
            await interaction.response.send_message(
                f"**Bios de `{safe}`** ({len(bios)})",
                file=discord.File(buf, filename=f"bios_{safe}.txt"),
                ephemeral=True,
            )

    @app_commands.command(name="deletebio", description="Supprime une bio d'une identité par son index")
    @app_commands.describe(identity="Nom de l'identité", index="Index (voir /listbios)")
    async def deletebio(self, interaction: discord.Interaction, identity: str, index: int):
        if not await self.require_admin(interaction):
            return
        safe = sanitize_identity_name(identity)
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


async def setup(bot):
    await bot.add_cog(Admin(bot))
