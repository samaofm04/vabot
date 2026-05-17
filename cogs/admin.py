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
CAPTIONS_FILE = DATA_DIR / "captions.txt"
BIOS_FILE = DATA_DIR / "bios.txt"
USERNAMES_FILE = DATA_DIR / "usernames.txt"
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
            msg = "Tu n'es pas autorisé à utiliser cette commande."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    @app_commands.command(name="whitelist", description="[OWNER] Whitelist un utilisateur pour les commandes admin")
    @app_commands.describe(user="L'utilisateur à autoriser")
    async def whitelist(self, interaction: discord.Interaction, user: discord.User):
        if not await self.is_owner(interaction.user.id):
            await interaction.response.send_message(
                "Seul le propriétaire du bot peut whitelist des utilisateurs.", ephemeral=True
            )
            return
        wl = load_json(WHITELIST_FILE, [])
        if user.id in wl:
            await interaction.response.send_message(f"{user.mention} est déjà whitelisté.", ephemeral=True)
            return
        wl.append(user.id)
        save_json(WHITELIST_FILE, wl)
        await interaction.response.send_message(f"✅ {user.mention} ajouté à la whitelist.", ephemeral=True)

    async def _append_lines_from_attachment(self, attachment: discord.Attachment, target: Path) -> int:
        content = (await attachment.read()).decode("utf-8", errors="ignore")
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        return len(lines)

    @app_commands.command(name="addcaptions", description="Ajoute des captions (fichier .txt, 1 par ligne)")
    @app_commands.describe(file="Fichier .txt avec une caption par ligne")
    async def addcaptions(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not file.filename.lower().endswith(".txt"):
            await interaction.followup.send("Le fichier doit être un .txt", ephemeral=True)
            return
        n = await self._append_lines_from_attachment(file, CAPTIONS_FILE)
        await interaction.followup.send(f"✅ {n} caption(s) ajoutée(s).", ephemeral=True)

    @app_commands.command(name="addusernames", description="Ajoute des usernames (fichier .txt, 1 par ligne)")
    @app_commands.describe(file="Fichier .txt avec un username par ligne")
    async def addusernames(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not file.filename.lower().endswith(".txt"):
            await interaction.followup.send("Le fichier doit être un .txt", ephemeral=True)
            return
        n = await self._append_lines_from_attachment(file, USERNAMES_FILE)
        await interaction.followup.send(f"✅ {n} username(s) ajouté(s).", ephemeral=True)

    @app_commands.command(name="addbios", description="Ajoute des bios (fichier .txt, séparées par '---' sur une ligne)")
    @app_commands.describe(file="Fichier .txt avec les bios séparées par '---'")
    async def addbios(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not file.filename.lower().endswith(".txt"):
            await interaction.followup.send("Le fichier doit être un .txt", ephemeral=True)
            return
        content = (await file.read()).decode("utf-8", errors="ignore")
        bios = [b.strip() for b in content.split("---") if b.strip()]
        BIOS_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = BIOS_FILE.read_text(encoding="utf-8") if BIOS_FILE.exists() else ""
        with BIOS_FILE.open("w", encoding="utf-8") as f:
            if existing.strip():
                f.write(existing.rstrip() + "\n---\n")
            f.write("\n---\n".join(bios) + "\n")
        await interaction.followup.send(f"✅ {len(bios)} bio(s) ajoutée(s).", ephemeral=True)

    @app_commands.command(name="addprofilepic", description="Ajoute une photo de profil au pool")
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
        await interaction.followup.send(f"✅ Photo de profil ajoutée ({target.name}).", ephemeral=True)

    @app_commands.command(name="addidentite", description="Crée une identité avec un zip de vidéos")
    @app_commands.describe(name="Nom de l'identité (sera nettoyé)", videos_zip="Fichier .zip contenant les vidéos")
    async def addidentite(self, interaction: discord.Interaction, name: str, videos_zip: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not videos_zip.filename.lower().endswith(".zip"):
            await interaction.followup.send("Le fichier doit être un .zip", ephemeral=True)
            return
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_-").lower()
        if not safe_name:
            await interaction.followup.send("Nom d'identité invalide.", ephemeral=True)
            return
        identity_dir = IDENTITIES_DIR / safe_name
        videos_dir = identity_dir / "videos"
        if identity_dir.exists():
            await interaction.followup.send(f"L'identité `{safe_name}` existe déjà.", ephemeral=True)
            return
        videos_dir.mkdir(parents=True, exist_ok=True)
        zip_bytes = await videos_zip.read()
        count = 0
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = tmp.name
        try:
            with zipfile.ZipFile(tmp_path) as zf:
                for member in zf.namelist():
                    base = os.path.basename(member)
                    if not base:
                        continue
                    if os.path.splitext(base)[1].lower() not in VIDEO_EXTS:
                        continue
                    with zf.open(member) as src, (videos_dir / base).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1
        finally:
            os.unlink(tmp_path)
        if count == 0:
            shutil.rmtree(identity_dir)
            await interaction.followup.send("Aucune vidéo trouvée dans le zip.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Identité `{safe_name}` créée avec {count} vidéo(s).", ephemeral=True
        )

    @app_commands.command(name="adduser", description="Crée un salon privé pour un VA + onboarding")
    @app_commands.describe(user="Le VA à onboarder")
    async def adduser(self, interaction: discord.Interaction, user: discord.Member):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Cette commande s'utilise dans un serveur.", ephemeral=True)
            return

        identities = list_identities()
        if not identities:
            await interaction.followup.send(
                "Aucune identité disponible. Crée-en une avec `/addidentite` d'abord.", ephemeral=True
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
                "Le bot n'a pas la permission de créer des salons. Donne-lui le rôle `Manage Channels`.",
                ephemeral=True,
            )
            return

        from cogs.onboarding import step_embed, OnboardingView
        embed = step_embed(0)
        await channel.send(content=user.mention, embed=embed, view=OnboardingView())

        await interaction.followup.send(
            f"✅ Salon {channel.mention} créé pour {user.mention}. Identité assignée: `{identity}`",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Admin(bot))
