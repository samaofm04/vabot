"""cogs/tgrouter.py — Démarre le routeur Telegram (tg_router) + /tgrouter status.

Le routeur écoute les chats Telegram : quand une modèle RÉPOND à une vidéo
de veille avec sa vidéo brute, il copie les deux dans le groupe de destination,
dans le sujet de la modèle. Config côté Telegram : /setdestination, /setmodel.
"""
import discord
from discord import app_commands
from discord.ext import commands

import tg_router


class TGRouter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            tg_router.start()
        except Exception as e:
            print(f"[tgrouter] start: {e}", flush=True)

    def cog_unload(self):
        try:
            tg_router.stop()
        except Exception:
            pass

    @app_commands.command(
        name="tgrouter",
        description="Statut du routeur Telegram (vidéos modèles → sujets du groupe)",
    )
    @app_commands.describe(
        token="(optionnel) Token d'un bot Telegram DÉDIÉ au routeur (via @BotFather) — évite le conflit avec le downloader",
    )
    async def tgrouter(self, interaction: discord.Interaction, token: str = None):
        perms = getattr(interaction.user, "guild_permissions", None)
        if not (perms and perms.manage_channels):
            await interaction.response.send_message("Réservé au staff.", ephemeral=True)
            return
        if token:
            tg_router.set_router_token(token)
            await interaction.response.send_message(
                "✅ Token du bot routeur enregistré — il est utilisé immédiatement.\n"
                "⚠️ Ajoute CE nouveau bot (admin) dans VEILLE ID + les groupes des modèles, "
                "puis refais `/setdestination` et `/setmodel` avec lui si besoin "
                "(la config des sujets/chats existante est conservée).",
                ephemeral=True)
            return
        cfg = tg_router._load()
        st = tg_router.STATUS
        import veille_telegram
        has_token = bool((veille_telegram.load_config() or {}).get("bot_token"))
        dedicated = bool(cfg.get("router_token"))
        txt = (
            "📡 **Routeur Telegram — reels modèles**\n"
            f"• Bot : {'✅ bot DÉDIÉ routeur' if dedicated else ('✅ token Veille partagé' if has_token else '❌ aucun token — Settings → Veille Telegram, ou /tgrouter token:...')}\n"
            f"• Poller : {'🟢 actif' if st.get('running') else '🔴 arrêté'}"
            + (f" — dernière activité <t:{st['last_update']}:R>" if st.get("last_update") else "") + "\n"
            f"• Groupe destination : {'✅ ' + str(cfg.get('dest_chat_id')) if cfg.get('dest_chat_id') else '❌ tape /setdestination dans ton groupe à sujets'}\n"
            f"• Chats de modèles branchés : **{len(cfg.get('sources') or {})}** "
            f"({', '.join(sorted(set((cfg.get('sources') or {}).values()))) or '—'})\n"
            f"• Sujets créés : {len(cfg.get('topics') or {})}\n"
            f"• Vidéos rangées : **{st.get('routed', 0)}**\n"
            + (f"• ⚠️ Dernière erreur : `{st.get('error')}`\n" if st.get("error") else "")
            + "\n**Setup :**\n"
            "1. Crée un groupe Telegram → active les **Sujets** (Paramètres du groupe)\n"
            "2. Ajoute ton bot Veille en **admin** (avec « Gérer les sujets »)\n"
            "3. Dans ce groupe : `/setdestination`\n"
            "4. Dans chaque chat de travail d'une modèle (bot admin) : `/setmodel amelia`\n"
            "5. La modèle répond à la vidéo de veille avec sa vidéo → rangé automatiquement 🔥"
        )
        await interaction.response.send_message(txt, ephemeral=True)


async def setup(bot):
    await bot.add_cog(TGRouter(bot))
