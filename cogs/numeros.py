"""Panneau « Numéro & Mail » des salons -numero-mail (serveur US).

Deux boutons persistants :
  📱 Générer un numéro  -> GetAText/SMSBower : le numéro s'affiche, le bot
     attend le code TOUT SEUL et l'édite dans le message dès qu'il arrive.
  📧 Générer un mail    -> SMSBower mail : idem avec l'adresse.

Sur chaque activation : 🔄 Redemander un code (même numéro/mail) et ❌ Annuler.
Tout est ÉPHÉMÈRE (visible du seul demandeur) sauf le panneau lui-même.
"""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import numgen

log = logging.getLogger("vabot.numeros")

POLL_SECONDS = 5
POLL_MAX = 180          # 3 min d'attente auto par code


def _svc_label(code):
    return numgen.SERVICE_LABELS.get(code, code)


class _ServiceSelect(discord.ui.Select):
    """Choix du service (Insta, TikTok…) — commun numéro et mail."""
    def __init__(self, kind, cog):
        self.kind = kind          # "sms" | "mail"
        self.cog = cog
        opts = [discord.SelectOption(label=_svc_label(c), value=c)
                for c in ("ig", "tt", "go", "fb", "tg", "wa", "sc")]
        super().__init__(placeholder="Pour quel service ?",
                         min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        svc = self.values[0]
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.kind == "sms":
            await self.cog.start_sms(interaction, svc)
        else:
            await self.cog.start_mail(interaction, svc)


class _ServiceView(discord.ui.View):
    def __init__(self, kind, cog):
        super().__init__(timeout=120)
        self.add_item(_ServiceSelect(kind, cog))


class _ActivationView(discord.ui.View):
    """🔄 Redemander un code · ❌ Annuler, pour UNE activation."""
    def __init__(self, cog, kind, act_id, value, provider="getatext", stale=""):
        super().__init__(timeout=1800)
        self.cog, self.kind = cog, kind
        self.act_id, self.value = act_id, value
        self.provider, self.stale = provider, stale
        self.owner_id = None

    async def interaction_check(self, itx):
        if self.owner_id and itx.user.id != self.owner_id:
            await itx.response.send_message("Pas pour toi.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Redemander un code", emoji="🔄",
                       style=discord.ButtonStyle.primary)
    async def again(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True, thinking=True)
        if self.kind == "sms":
            ok, msg = await asyncio.to_thread(numgen.retry, self.act_id, self.provider)
            if not ok:
                await itx.followup.send(f"❌ {msg}", ephemeral=True)
                return
        # mail : rien à demander côté API, on relance juste l'écoute
        await itx.followup.send(
            f"🔄 Nouveau code demandé — renvoie le SMS/mail depuis l'app, "
            f"j'écoute **{self.value}** pendant {POLL_MAX // 60} min.", ephemeral=True)
        await self.cog.watch(itx, self, first=False)

    @discord.ui.button(label="Annuler", emoji="❌", style=discord.ButtonStyle.secondary)
    async def stop_it(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True, thinking=True)
        if self.kind == "sms":
            await asyncio.to_thread(numgen.cancel, self.act_id, self.provider)
        else:
            await asyncio.to_thread(numgen.mail_cancel, self.act_id)
        self.stop()
        await itx.followup.send(f"❌ **{self.value}** annulé (remboursé si aucun code reçu).",
                                ephemeral=True)


class NumPanelView(discord.ui.View):
    """Panneau permanent du salon -numero-mail (custom_id stables)."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Générer un numéro", emoji="📱",
                       style=discord.ButtonStyle.success, custom_id="numgen:sms")
    async def sms(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not numgen.status()["sms_ok"]:
            await itx.response.send_message(
                "⚠️ Aucune clé SMS configurée — un admin doit faire `/smskey`.",
                ephemeral=True)
            return
        await itx.response.send_message(
            "📱 **Nouveau numéro** — choisis le service 👇",
            view=_ServiceView("sms", self.cog), ephemeral=True)

    @discord.ui.button(label="Générer un mail", emoji="📧",
                       style=discord.ButtonStyle.primary, custom_id="numgen:mail")
    async def mail(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not numgen.status()["mail_ok"]:
            await itx.response.send_message(
                "⚠️ Aucune clé SMSBower configurée — un admin doit faire `/smskey`.",
                ephemeral=True)
            return
        await itx.response.send_message(
            "📧 **Nouvelle adresse mail** — choisis le service 👇",
            view=_ServiceView("mail", self.cog), ephemeral=True)


class NumerosCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        try:
            self.bot.add_view(NumPanelView(self))
        except Exception:
            pass

    # ------------------------------------------------------------ génération
    async def start_sms(self, interaction, service):
        ok, res = await asyncio.to_thread(numgen.get_number, service)
        if not ok:
            await interaction.followup.send(f"❌ {res}", ephemeral=True)
            return
        view = _ActivationView(self, "sms", res["id"], res["phone"], res["provider"])
        view.owner_id = interaction.user.id
        msg = await interaction.followup.send(
            self._embed_txt("📱", res["phone"], service, waiting=True),
            view=view, ephemeral=True, wait=True)
        view.message = msg
        await self.watch(interaction, view, first=True)

    async def start_mail(self, interaction, service):
        ok, res = await asyncio.to_thread(numgen.get_mail, service)
        if not ok:
            await interaction.followup.send(f"❌ {res}", ephemeral=True)
            return
        view = _ActivationView(self, "mail", res["id"], res["mail"],
                               stale=res.get("stale", ""))
        view.owner_id = interaction.user.id
        msg = await interaction.followup.send(
            self._embed_txt("📧", res["mail"], service, waiting=True),
            view=view, ephemeral=True, wait=True)
        view.message = msg
        await self.watch(interaction, view, first=True)

    def _embed_txt(self, icon, value, service, waiting=True, code=None, err=None):
        head = f"{icon} **`{value}`**  ·  {_svc_label(service)}"
        if code:
            return (f"{head}\n\n🔑 **CODE : `{code}`**\n"
                    "_Besoin d'un autre code ? → 🔄 Redemander un code_")
        if err:
            return f"{head}\n\n⚠️ {err}\n_Tu peux réessayer avec 🔄._"
        return (f"{head}\n\n⏳ **En attente du code…** "
                f"(j'écoute pendant {POLL_MAX // 60} min, le code s'affiche ici tout seul)")

    # --------------------------------------------------------------- polling
    async def watch(self, interaction, view, first=True):
        """Poll le code et ÉDITE le message d'origine dès qu'il arrive."""
        service = "ig"
        for _ in range(POLL_MAX // POLL_SECONDS):
            await asyncio.sleep(POLL_SECONDS)
            if view.is_finished():
                return
            if view.kind == "sms":
                state, val = await asyncio.to_thread(
                    numgen.get_code, view.act_id, view.provider)
            else:
                state, val = await asyncio.to_thread(
                    numgen.get_mail_code, view.act_id, view.stale)
            if state == "code" and val:
                if view.kind == "sms":
                    await asyncio.to_thread(numgen.finish, view.act_id, view.provider)
                else:
                    view.stale = val      # le prochain code doit être DIFFÉRENT
                txt = self._embed_txt("📱" if view.kind == "sms" else "📧",
                                      view.value, service, code=val)
                await self._edit(interaction, view, txt)
                return
            if state in ("cancel", "error"):
                txt = self._embed_txt("📱" if view.kind == "sms" else "📧",
                                      view.value, service,
                                      err=val or "activation annulée")
                await self._edit(interaction, view, txt)
                return
        txt = self._embed_txt("📱" if view.kind == "sms" else "📧", view.value,
                              service, err="Aucun code reçu dans le délai.")
        await self._edit(interaction, view, txt)

    async def _edit(self, interaction, view, content):
        try:
            if getattr(view, "message", None) is not None:
                await view.message.edit(content=content, view=view)
                return
        except Exception:
            pass
        try:
            await interaction.followup.send(content, view=view, ephemeral=True)
        except Exception:
            pass

    # -------------------------------------------------------------- commandes
    @app_commands.command(
        name="panelnumero",
        description="[ADMIN] Poste ICI le panneau Numéro & Mail (boutons)")
    async def panelnumero(self, interaction: discord.Interaction):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            from cogs.user import _is_staff_member
            if not _is_staff_member(interaction.user):
                await interaction.response.send_message("Réservé aux admins.", ephemeral=True)
                return
        await interaction.response.send_message(
            embed=panel_embed(), view=NumPanelView(self))

    @app_commands.command(
        name="smskey",
        description="[OWNER] Clés des générateurs (GetAText SMS / SMSBower mail)")
    @app_commands.describe(
        getatext="Clé API GetAText (numéros)",
        smsbower="Clé API SMSBower (mails + fallback numéros)",
        pays="Code pays par défaut (0 = Russie, 187 = USA…)",
    )
    async def smskey(self, interaction: discord.Interaction,
                     getatext: str = None, smsbower: str = None, pays: str = None):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if getatext is None and smsbower is None and pays is None:
            s = numgen.status()
            await interaction.response.send_message(
                f"🔑 **Générateurs**\n"
                f"• GetAText (numéros) : {s['getatext'] or '❌ absente'}\n"
                f"• SMSBower (mails) : {s['smsbower'] or '❌ absente'}\n"
                f"• Pays par défaut : `{s['country']}`\n\n"
                "_Pose-les : `/smskey getatext:… smsbower:… pays:187`_",
                ephemeral=True)
            return
        s = await asyncio.to_thread(numgen.set_keys, getatext, smsbower, pays)
        await interaction.response.send_message(
            f"✅ Enregistré — GetAText : {s['getatext'] or '❌'} · "
            f"SMSBower : {s['smsbower'] or '❌'} · pays `{s['country']}`",
            ephemeral=True)


def panel_embed():
    return discord.Embed(
        title="📱 Numéro & Mail",
        description=(
            "**📱 Générer un numéro** — un numéro dispo tout de suite. "
            "Le code arrive **ici tout seul** dès que le SMS est reçu.\n"
            "**📧 Générer un mail** — une adresse jetable, même principe.\n\n"
            "Sur chaque demande : **🔄 Redemander un code** (même numéro/mail) "
            "et **❌ Annuler**.\n"
            "_Tout ce que tu génères n'est visible que par toi._"
        ),
        color=discord.Color.blurple(),
    )


async def setup(bot):
    await bot.add_cog(NumerosCog(bot))
