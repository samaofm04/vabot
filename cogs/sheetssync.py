"""cogs/sheetssync.py — Poller Sheet->site + commande /sheetsync (config/test).

Le push site->Sheet est declenche par jailbreak._save (voir sheets_sync.push_all_async).
Ici : un poller lit le Sheet toutes les 2 min et applique les changements dans
jailbreak.json (pull_and_merge), + une commande OWNER pour configurer/tester.
"""
import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

import sheets_sync


class SheetsSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        if sheets_sync.is_configured():
            self.poll.start()

    def cog_unload(self):
        if self.poll.is_running():
            self.poll.cancel()

    async def _is_owner(self, uid):
        if self._owner_id is None:
            try:
                app = await self.bot.application_info()
                self._owner_id = app.owner.id
            except Exception:
                return False
        return uid == self._owner_id

    # ---------- Poller Sheet -> site ----------
    @tasks.loop(minutes=2)
    async def poll(self):
        if not sheets_sync.is_configured():
            return
        try:
            changed, summary = await asyncio.to_thread(sheets_sync.pull_and_merge)
            if changed:
                print(f"[sheetssync] pull: {summary}", flush=True)
        except Exception as e:
            print(f"[sheetssync] poll: {e}", flush=True)

    @poll.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ---------- Commande ----------
    @app_commands.command(
        name="sheetsync",
        description="[OWNER] Sync Google Sheet des comptes Jailbreak (setup/test/push/pull/status)",
    )
    @app_commands.describe(
        action="setup · test · push · pull · status",
        sheet_id="(setup) l'ID du Google Sheet — la longue chaîne dans son URL",
        cle="(setup) le fichier JSON du compte de service Google",
    )
    async def sheetsync(self, interaction: discord.Interaction, action: str,
                        sheet_id: str = None, cle: discord.Attachment = None):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        action = (action or "").strip().lower()

        if action == "setup":
            await interaction.response.defer(ephemeral=True, thinking=True)
            msg = []
            if cle is not None:
                try:
                    sheets_sync.DATA_DIR.mkdir(parents=True, exist_ok=True)
                    await cle.save(str(sheets_sync.SA_FILE))
                    msg.append("✅ Clé de service enregistrée.")
                except Exception as e:
                    await interaction.followup.send(f"❌ Erreur clé : {e}", ephemeral=True)
                    return
            if sheet_id:
                cfg = sheets_sync.load_config()
                cfg["sheet_id"] = sheet_id.strip()
                sheets_sync.save_config(cfg)
                msg.append("✅ Sheet ID enregistré.")
            email = sheets_sync.service_account_email()
            if email:
                msg.append(f"📧 **Partage ton Sheet (Éditeur) avec :** `{email}`")
            ok, tmsg = await asyncio.to_thread(sheets_sync.test_connection)
            msg.append(("🔗 " if ok else "⚠️ ") + tmsg)
            if ok:
                if not self.poll.is_running():
                    self.poll.start()
                # 1er push complet pour remplir le Sheet
                try:
                    import jailbreak as jb
                    await asyncio.to_thread(sheets_sync.push_all, jb._load(), True)
                    msg.append("📤 Comptes actuels poussés dans le Sheet.")
                except Exception:
                    pass
            await interaction.followup.send("\n".join(msg), ephemeral=True)
            return

        if action in ("test", "status"):
            await interaction.response.defer(ephemeral=True, thinking=True)
            ok, tmsg = await asyncio.to_thread(sheets_sync.test_connection)
            email = sheets_sync.service_account_email()
            extra = f"\n📧 Compte de service : `{email}`" if email else ""
            extra += f"\n🔁 Poller (Sheet→site) : {'ON' if self.poll.is_running() else 'OFF'}"
            extra += "\n📦 gspread installé : " + ("oui" if sheets_sync.gspread_available() else "**NON** (`pip install gspread`)")
            await interaction.followup.send(("✅ " if ok else "❌ ") + tmsg + extra, ephemeral=True)
            return

        if action == "push":
            await interaction.response.defer(ephemeral=True, thinking=True)
            import jailbreak as jb
            ok = await asyncio.to_thread(sheets_sync.push_all, jb._load(), True)
            await interaction.followup.send(
                "✅ Comptes poussés vers le Sheet." if ok else
                "❌ Push échoué (config/gspread ?). Fais `/sheetsync status`.", ephemeral=True)
            return

        if action == "pull":
            await interaction.response.defer(ephemeral=True, thinking=True)
            changed, summary = await asyncio.to_thread(sheets_sync.pull_and_merge)
            await interaction.followup.send(
                f"✅ Importé du Sheet : {summary}" if changed else
                "Rien de nouveau côté Sheet (ou Sheet indispo).", ephemeral=True)
            return

        await interaction.response.send_message(
            "Actions : `setup` (sheet_id + clé), `test`, `push`, `pull`, `status`.",
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(SheetsSync(bot))
