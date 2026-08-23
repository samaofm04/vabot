"""cogs/sheetssync.py — Poller Sheet->site + commande /sheetsync (config/test).

Le push site->Sheet est declenche par jailbreak._save (voir sheets_sync.push_all_async).
Ici : un poller lit le Sheet toutes les 2 min et applique les changements dans
jailbreak.json (pull_and_merge), + une commande OWNER pour configurer/tester.
"""
import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import sheets_sync


class SheetsSync(commands.Cog):
    # Anti-noyade du journal : le poller tourne toutes les 2 min, donc un état
    # QUI DURE (pause, Sheet illisible, état local illisible) écrirait 720
    # lignes par jour et noierait tout le reste — un journal illisible cache
    # aussi bien que le silence. Un message identique n'est réécrit qu'au bout
    # de 30 min ; un cycle qui CHANGE quelque chose est toujours écrit.
    _RELOG_S = 1800

    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self._dernier_log = ("", 0.0)   # (message, horodatage) — cf. _RELOG_S
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
    def _journal(self, res, toujours: bool = False) -> None:
        """Écrit au journal le résultat d'un cycle de pull.

        Avant, le journal ne recevait QUE les cycles qui avaient modifié
        quelque chose (`if changed`). Or la protection anti-écrasement agit
        exactement dans les cycles où rien n'est écrit : une valeur du Sheet
        ignorée, un compte protégé, un pull ANNULÉ ne laissaient donc AUCUNE
        trace nulle part. `toujours` = pull demandé à la main : une action
        volontaire mérite sa ligne, même répétée."""
        changed, summary = res[0], res[1]
        outcome = getattr(res, "outcome", "") or "?"
        if not (changed or toujours or getattr(res, "signale", False)):
            return
        ligne = f"[sheetssync] pull ({outcome}): {summary}"
        maintenant = time.time()
        if (not (changed or toujours) and ligne == self._dernier_log[0]
                and maintenant - self._dernier_log[1] < self._RELOG_S):
            return
        self._dernier_log = (ligne, maintenant)
        print(ligne, flush=True)

    @tasks.loop(minutes=2)
    async def poll(self):
        if not sheets_sync.is_configured():
            return
        try:
            res = await asyncio.to_thread(sheets_sync.pull_and_merge)
            self._journal(res)
        except Exception as e:
            print(f"[sheetssync] poll: {e}", flush=True)

    @poll.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()
        # PUSH INITIAL avant le 1er pull : si le bot a redémarré pile pendant un
        # ajout côté site, le push async a pu être perdu -> sans ça, le pull
        # supprimerait le compte du site (absent du Sheet). Push d'abord = safe.
        try:
            import jailbreak as jb
            await asyncio.to_thread(sheets_sync.push_all, jb._load(), False)
            print("[sheetssync] push initial au démarrage OK", flush=True)
        except Exception as e:
            print(f"[sheetssync] push initial: {e}", flush=True)

    # ---------- Commande ----------
    @app_commands.command(
        name="sheetsync",
        description="[OWNER] Sync Google Sheet des comptes Jailbreak (setup/test/push/pull/status)",
    )
    @app_commands.describe(
        action="setup · folder · test · push · pull · status",
        sheet_id="(setup) l'ID du Google Sheet — la longue chaîne dans son URL",
        cle="(setup) le fichier JSON du compte de service Google",
        folder="(folder) le lien du dossier Drive partagé au compte de service (1 classeur/identité)",
        force="(pull) appliquer AUSSI les suppressions massives (> 25 %) — grand ménage volontaire",
    )
    async def sheetsync(self, interaction: discord.Interaction, action: str,
                        sheet_id: str = None, cle: discord.Attachment = None,
                        folder: str = None, force: bool = False):
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

        if action == "folder":
            await interaction.response.defer(ephemeral=True, thinking=True)
            link = (folder or sheet_id or "").strip()
            email = sheets_sync.service_account_email()
            email_disp = email or "(charge d'abord la clé via /sheetsync setup)"
            if not link:
                await interaction.followup.send(
                    "📁 **Mode « 1 classeur par identité »**\n"
                    "1. Crée un dossier dans Google Drive (ex : `VA JB`)\n"
                    f"2. Partage-le en **Éditeur** avec : `{email_disp}`\n"
                    "3. Refais : `/sheetsync folder folder:<lien_du_dossier>`\n\n"
                    "Je créerai automatiquement **1 classeur par identité** dedans, et je les synchroniserai "
                    "dans les 2 sens. ⚠️ L'**API Google Drive** doit être activée sur le projet du compte de service.",
                    ephemeral=True)
                return
            fid = sheets_sync.set_folder(link)
            import jailbreak as jb
            ok = await asyncio.to_thread(sheets_sync.push_all, jb._load(), True)
            if not self.poll.is_running():
                self.poll.start()
            cfg = sheets_sync.load_config()
            n = len(cfg.get("sheets") or {})
            created = sheets_sync._LAST_FOLDER.get("ok", 0)
            err = sheets_sync._LAST_FOLDER.get("err", "")
            proj = email.split("@")[-1].split(".")[0] if email and "@" in email else "ton-projet"
            if ok and created > 0:
                await interaction.followup.send(
                    f"✅ **Mode 1 classeur/identité activé.** Dossier `{fid}`.\n"
                    f"📗 **{created}** classeur(s) synchronisé(s) (1 par identité), rangés dans ton dossier.\n"
                    f"🔁 Poller Sheet→site : ON. Tu peux renommer/éditer chaque classeur, ça se resync.",
                    ephemeral=True)
            elif err:
                low = err.lower()
                hint = ""
                if "storage quota" in low or "quota has been exceeded" in low:
                    names = sheets_sync.identity_names()
                    liste = "\n".join(f"• `{n}`" for n in names[:25]) or "(aucune identité)"
                    if len(names) > 25:
                        liste += f"\n… +{len(names) - 25} autre(s)"
                    hint = ("\n\n👉 **Limite Google connue** : un compte de service ne peut PAS *créer* de fichiers "
                            "(pas de quota de stockage). Mais il peut ÉCRIRE dans des classeurs qui existent déjà.\n"
                            "**À faire une seule fois :** dans ton dossier, crée un Google Sheets **vide** par identité, "
                            "nommé EXACTEMENT comme ça :\n"
                            f"{liste}\n"
                            "Puis relance `/sheetsync folder folder:<lien>` — je les remplirai et synchroniserai tout seul ensuite.")
                elif "drive" in low and ("disabled" in low or "not been used" in low or "not enabled" in low or "accessnotconfigured" in low.replace(" ", "")):
                    hint = (f"\n\n👉 **API Google Drive pas activée.** Active-la ici (attends 1-2 min) :\n"
                            f"https://console.cloud.google.com/apis/library/drive.googleapis.com?project={proj}")
                elif "permission" in low or "not found" in low or "404" in low:
                    hint = (f"\n\n👉 **Problème d'accès au dossier.** Partage-le en **Éditeur** avec `{email}`.")
                await interaction.followup.send(
                    (f"⚠️ **0 classeur créé.** Erreur : `{err}`{hint}")[:1990],
                    ephemeral=True)
            else:
                await interaction.followup.send(
                    "ℹ️ Dossier enregistré, mais **aucune identité jailbreak à synchroniser** "
                    "(la base de comptes JB est vide ?). Ajoute des comptes puis `/sheetsync push`.",
                    ephemeral=True)
            return

        if action in ("pause", "resume"):
            await interaction.response.defer(ephemeral=True, thinking=True)
            p = sheets_sync.set_paused(action == "pause")
            await interaction.followup.send(
                ("⏸️ **Sync GELÉE.** Plus aucun push ni pull — rien ne peut être écrasé.\n"
                 "Reprends avec `/sheetsync resume`." if p else
                 "▶️ **Sync réactivée.**"), ephemeral=True)
            return

        if action == "restore":
            await interaction.response.defer(ephemeral=True, thinking=True)
            ok, msg = await asyncio.to_thread(sheets_sync.restore_from_single_sheet)
            await interaction.followup.send(
                ("✅ " if ok else "❌ ") + msg +
                ("\n\n(100 % additif : rien n'a été supprimé.)" if ok else ""),
                ephemeral=True)
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
            err = ""
            try:
                err = (getattr(sheets_sync, "_LAST_FOLDER", None) or {}).get("err") or ""
            except Exception:
                pass
            if ok and err:
                msg = f"✅ Poussé, mais un classeur a échoué : `{err[:170]}` — relance `/sheetsync push`."
            elif ok:
                msg = "✅ Comptes poussés vers le Sheet."
            elif err:
                msg = f"❌ Push échoué : `{err[:180]}`"
            else:
                msg = "❌ Push échoué (config/gspread ?). Fais `/sheetsync status`."
            await interaction.followup.send(msg, ephemeral=True)
            return

        if action == "pull":
            await interaction.response.defer(ephemeral=True, thinking=True)
            res = await asyncio.to_thread(sheets_sync.pull_and_merge, force)
            # La formulation vit dans sheets_sync.pull_message : elle se
            # décidait ici en relisant le TEXTE du résumé (« RETENUES » dedans ?
            # « pause » dedans ?), et tout ce que ce décodage ne prévoyait pas —
            # à commencer par un pull ANNULÉ — retombait sur « rien de nouveau ».
            self._journal(res, toujours=True)   # l'écran ET le journal, jamais l'un sans l'autre
            await interaction.followup.send(sheets_sync.pull_message(res)[:1990],
                                            ephemeral=True)
            return

        if action == "check":
            await interaction.response.defer(ephemeral=True, thinking=True)
            report = await asyncio.to_thread(sheets_sync.check_sync)
            await interaction.followup.send(report[:1990], ephemeral=True)
            return

        await interaction.response.send_message(
            "Actions : `setup` (sheet_id + clé), `test`, `check`, `push`, `pull`, `status`.",
            ephemeral=True)

    @app_commands.command(
        name="jailbreakreset",
        description="[OWNER] DANGER: supprime TOUS les comptes JB sauf ceux d'un VA (backup auto)",
    )
    @app_commands.describe(
        garder_va="Le VA dont on GARDE les comptes (ex: Toky). Tout le reste est supprimé.",
        confirmer="Laisse vide = APERÇU (rien supprimé). Mets True = SUPPRIME pour de vrai.",
    )
    async def jailbreakreset(self, interaction: discord.Interaction,
                             garder_va: str, confirmer: bool = False):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        keep = (garder_va or "").strip()
        if not keep:
            await interaction.response.send_message("Précise le VA à garder (ex: Toky).", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        import jailbreak as jb
        kl = keep.lower()

        def _counts(data):
            total = kept = 0
            for e in data.values():
                if not isinstance(e, dict):
                    continue
                accts = e.get("accounts") or []
                total += len(accts)
                kept += sum(1 for a in accts if (a.get("va") or "").strip().lower() == kl)
            return total, kept

        if not confirmer:
            total, kept = _counts(await asyncio.to_thread(jb._load))
            await interaction.followup.send(
                f"⚠️ **APERÇU — rien n'est supprimé.**\nGarder le VA « **{keep}** » :\n"
                f"• Total actuel : **{total}** comptes\n"
                f"• Gardés («{keep}») : **{kept}**\n"
                f"• Seraient **SUPPRIMÉS** : **{total - kept}**\n\n"
                f"Si c'est bon, relance avec :\n"
                f"`/jailbreakreset garder_va:{keep} confirmer:True`\n"
                f"_(un backup du fichier est fait avant toute suppression)._",
                ephemeral=True)
            return

        # Exécution : pause le poller pendant l'opé (anti ré-import), backup, filtre, save + push synchrone
        was = self.poll.is_running()
        if was:
            self.poll.cancel()

        def _do():
            import json as _j, time as _t
            with jb.transaction():
                return _do_locked(_j, _t)

        def _do_locked(_j, _t):
            data = jb._load()
            total_before, _ = _counts(data)
            backup = jb.DATA_DIR / f"jailbreak.backup.{int(_t.time())}.json"
            try:
                jb.DATA_DIR.mkdir(parents=True, exist_ok=True)
                backup.write_text(_j.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            # Tombstones AVANT filtrage : sans elles le poller (2 min) ré-importait
            # depuis le Sheet tout ce que le reset venait de supprimer.
            for identity, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                gone_u = [(a.get("username") or "") for a in (entry.get("accounts") or [])
                          if (a.get("va") or "").strip().lower() != kl]
                gone_v = [(v.get("name") if isinstance(v, dict) else v or "")
                          for v in (entry.get("vas") or [])
                          if (v.get("name") if isinstance(v, dict) else v or "").strip().lower() != kl]
                try:
                    if gone_u:
                        jb.tomb_add("accounts", identity, *gone_u)
                    if gone_v:
                        jb.tomb_add("vas", identity, *gone_v)
                except Exception:
                    pass
                entry["accounts"] = [a for a in (entry.get("accounts") or [])
                                     if (a.get("va") or "").strip().lower() == kl]
                entry["vas"] = [v for v in (entry.get("vas") or [])
                                if (v.get("name") if isinstance(v, dict) else v or "").strip().lower() == kl]
            _, kept = _counts(data)
            jb._save(data)
            try:
                sheets_sync.push_all(data, force=True)  # maj le Sheet MAINTENANT (anti-race)
            except Exception:
                pass
            return total_before, kept, total_before - kept, str(backup)

        try:
            total_before, kept, removed, backup = await asyncio.to_thread(_do)
        finally:
            if was and not self.poll.is_running():
                self.poll.start()
        await interaction.followup.send(
            f"✅ **Reset effectué** — gardé le VA « {keep} ».\n"
            f"• Avant : **{total_before}** comptes\n"
            f"• Gardés : **{kept}**\n"
            f"• Supprimés : **{removed}**\n"
            f"🗂 Backup sauvegardé : `{backup}` (sur le VPS, au cas où).\n"
            f"Le Sheet a été mis à jour.",
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(SheetsSync(bot))
