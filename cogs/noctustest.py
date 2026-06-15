"""Commande /reeltest : génère un reel (variation) depuis la Bibliothèque et le poste ici."""
import asyncio
import random
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

BOT_DIR = Path(__file__).resolve().parent.parent          # .../bot
IDENTITIES_DIR = BOT_DIR / "data" / "identities"
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _pick_clean_reel(identite=None):
    """Retourne (identity, video_path) d'un reel CLEAN aléatoire (hors .example)."""
    if not IDENTITIES_DIR.exists():
        return None, None
    idents = [d.name for d in IDENTITIES_DIR.iterdir() if d.is_dir() and (d / "videos").exists()]
    if identite:
        wanted = [i for i in idents if i.lower() == identite.lower().strip()]
        idents = wanted or idents
    random.shuffle(idents)
    for ident in idents:
        vids = [
            v for v in (IDENTITIES_DIR / ident / "videos").glob("*")
            if v.is_file() and v.suffix.lower() in VIDEO_EXTS and ".example" not in v.name.lower()
        ]
        if vids:
            return ident, random.choice(vids)
    return None, None


class NoctusTest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None

    async def _is_owner(self, uid):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return uid == self._owner_id

    @app_commands.command(
        name="reeltest",
        description="Génère un reel de test (variation) depuis la Bibliothèque et l'envoie ici",
    )
    @app_commands.describe(
        identite="Identité à utiliser (optionnel — sinon au hasard)",
        texte="Caption à incruster (optionnel — sinon celle du reel, ou sans texte)",
    )
    async def reeltest(self, interaction: discord.Interaction, identite: str = None, texte: str = None):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            import noctus_web
        except Exception as e:
            await interaction.followup.send(f"Module vidéo indispo : {e}")
            return
        if not noctus_web.setup_ok():
            await interaction.followup.send(
                "⚠️ Setup vidéo incomplet sur le serveur (Node/ffmpeg/canvas). "
                "Va sur le dashboard → Création de vidéos pour l'installer."
            )
            return

        ident, src = _pick_clean_reel(identite)
        if not src:
            await interaction.followup.send(
                "Aucune vidéo clean trouvée dans la Bibliothèque" + (f" pour `{identite}`" if identite else "") + "."
            )
            return

        # Caption : param fourni > caption stockée du reel > sans texte
        caption = (texte or "").strip()
        if not caption:
            cap_f = src.with_suffix(".txt")
            if cap_f.exists():
                try:
                    caption = cap_f.read_text(encoding="utf-8").strip()
                except Exception:
                    caption = ""

        await interaction.followup.send(
            f"🎬 Génération d'un reel test — identité `{ident}` "
            f"({'avec caption' if caption else 'sans texte'})… ça prend ~10-30s ⏳"
        )

        model = await asyncio.to_thread(
            noctus_web.gen_from_path, str(src), caption, "TikTokSans", ["V1"]
        )
        if not model:
            await interaction.followup.send("❌ Lancement de la génération impossible.")
            return

        # Poll le statut (max ~3 min)
        state = "running"
        for _ in range(90):
            await asyncio.sleep(2)
            state = noctus_web.status(model).get("state", "running")
            if state in ("done", "error", "stopped"):
                break
        if state != "done":
            err = noctus_web.status(model).get("error", "")
            await interaction.followup.send(f"❌ Génération non terminée ({state}) {err}".strip())
            return

        outs = noctus_web.output_paths(model)
        if not outs:
            await interaction.followup.send("❌ Aucun reel généré.")
            return
        out = outs[0]
        size = out.stat().st_size
        limit = getattr(interaction.guild, "filesize_limit", 26214400) if interaction.guild else 26214400
        if size > (limit or 26214400):
            await interaction.followup.send(
                f"Reel généré ({size // (1024 * 1024)} Mo) mais trop lourd pour Discord (limite {limit // (1024 * 1024)} Mo)."
            )
            return
        try:
            await interaction.followup.send(
                content=f"✅ **Reel test** — identité `{ident}` · variation V1 · {'caption incrustée' if caption else 'sans texte'}",
                file=discord.File(str(out), filename="reeltest.mp4"),
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"Erreur d'envoi : {e}")


async def setup(bot):
    await bot.add_cog(NoctusTest(bot))
