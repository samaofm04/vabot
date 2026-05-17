import os
import random
import discord
from discord import app_commands
from discord.ext import commands

PHOTOS_DIR = os.path.join("assets", "photos")
VIDEOS_DIR = os.path.join("assets", "videos")

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}


def list_files(directory: str, allowed_exts: set[str]) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return [
        f for f in os.listdir(directory)
        if os.path.splitext(f)[1].lower() in allowed_exts
    ]


class Media(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="photo", description="Envoie une photo aléatoire au VA")
    async def photo(self, interaction: discord.Interaction):
        files = list_files(PHOTOS_DIR, PHOTO_EXTS)
        if not files:
            await interaction.response.send_message(
                "Aucune photo disponible dans assets/photos.", ephemeral=True
            )
            return
        choice = random.choice(files)
        path = os.path.join(PHOTOS_DIR, choice)
        await interaction.response.send_message(file=discord.File(path))

    @app_commands.command(name="video", description="Envoie une vidéo aléatoire au VA")
    async def video(self, interaction: discord.Interaction):
        files = list_files(VIDEOS_DIR, VIDEO_EXTS)
        if not files:
            await interaction.response.send_message(
                "Aucune vidéo disponible dans assets/videos.", ephemeral=True
            )
            return
        choice = random.choice(files)
        path = os.path.join(VIDEOS_DIR, choice)
        await interaction.response.defer()
        await interaction.followup.send(file=discord.File(path))

    @app_commands.command(name="list", description="Liste les médias disponibles")
    @app_commands.describe(type="photo ou video")
    async def list_media(self, interaction: discord.Interaction, type: str):
        type = type.lower()
        if type == "photo":
            files = list_files(PHOTOS_DIR, PHOTO_EXTS)
        elif type == "video":
            files = list_files(VIDEOS_DIR, VIDEO_EXTS)
        else:
            await interaction.response.send_message(
                "Type invalide. Utilise `photo` ou `video`.", ephemeral=True
            )
            return

        if not files:
            await interaction.response.send_message(f"Aucun {type} disponible.", ephemeral=True)
            return

        listing = "\n".join(f"- {f}" for f in files[:25])
        await interaction.response.send_message(
            f"**{len(files)} {type}(s):**\n{listing}", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Media(bot))
