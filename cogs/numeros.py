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
    """Boutons d'UNE activation : Voir le code · Redemander · Autre · Annuler
    (mêmes boutons/couleurs que le serveur de référence de l'user)."""
    def __init__(self, cog, kind, act_id, value, provider="getatext", stale=""):
        super().__init__(timeout=1800)
        self.cog, self.kind = cog, kind
        self.act_id, self.value = act_id, value
        self.provider, self.stale = provider, stale
        self.owner_id = None
        self.service = "ig"
        self.code = None            # rempli par le poll dès qu'il arrive
        lbl = "Voir le code SMS" if kind == "sms" else "Voir le code mail"
        self.children[0].label = lbl
        self.children[2].label = "Autre numéro" if kind == "sms" else "Autre mail"

    async def interaction_check(self, itx):
        if self.owner_id and itx.user.id != self.owner_id:
            await itx.response.send_message("Pas pour toi.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Voir le code", emoji="📨",
                       style=discord.ButtonStyle.success)
    async def see(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True, thinking=True)
        if self.code:
            await itx.followup.send(f"🔑 **CODE : `{self.code}`**", ephemeral=True)
            return
        # pas encore vu par le poll : on redemande tout de suite au fournisseur
        if self.kind == "sms":
            state, val = await asyncio.to_thread(
                numgen.get_code, self.act_id, self.provider)
        else:
            state, val = await asyncio.to_thread(
                numgen.get_mail_code, self.act_id, self.stale)
        if state == "code" and val:
            self.code = val
            await itx.followup.send(f"🔑 **CODE : `{val}`**", ephemeral=True)
            await self.cog.show_code(itx, self, val)
            return
        await itx.followup.send(
            "⏳ **Pas encore reçu.** Demande l'envoi du code depuis l'app — "
            "il s'affichera **tout seul** dans le message au-dessus.", ephemeral=True)

    @discord.ui.button(label="Redemander un code", emoji="🔄",
                       style=discord.ButtonStyle.primary)
    async def again(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True, thinking=True)
        if self.kind == "sms":
            ok, msg = await asyncio.to_thread(numgen.retry, self.act_id, self.provider)
            if not ok:
                await itx.followup.send(f"❌ {msg}", ephemeral=True)
                return
        else:
            self.stale = self.code or self.stale   # le prochain doit être DIFFÉRENT
        self.code = None
        await itx.followup.send(
            f"🔄 Nouveau code demandé — relance l'envoi depuis l'app, "
            f"j'écoute **{self.value}** pendant {POLL_MAX // 60} min.", ephemeral=True)
        await self.cog.watch(itx, self, first=False)

    @discord.ui.button(label="Autre numéro", emoji="🔁",
                       style=discord.ButtonStyle.secondary)
    async def other_one(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True, thinking=True)
        # on rend l'actuel (remboursé si aucun code) puis on en reprend un
        if self.kind == "sms":
            await asyncio.to_thread(numgen.cancel, self.act_id, self.provider)
        else:
            await asyncio.to_thread(numgen.mail_cancel, self.act_id)
        self.stop()
        if self.kind == "sms":
            await self.cog.start_sms(itx, self.service)
        else:
            await self.cog.start_mail(itx, self.service)

    @discord.ui.button(label="Annuler", emoji="❌", style=discord.ButtonStyle.danger)
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

    # Boutons DIRECTS en Instagram/Threads (demande user : pas de menu de
    # service, c'est Insta dans 100 % des cas). Le select reste dispo via
    # « Autre service » pour les cas rares.
    @discord.ui.button(label="Numéro Instagram / Threads", emoji="📱",
                       style=discord.ButtonStyle.success, custom_id="numgen:sms")
    async def sms(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not numgen.status()["sms_ok"]:
            await itx.response.send_message(
                "⚠️ Aucune clé SMS configurée — un admin doit faire `/smskey`.",
                ephemeral=True)
            return
        await itx.response.defer(ephemeral=True, thinking=True)
        await self.cog.start_sms(itx, "ig")

    @discord.ui.button(label="Mail Instagram", emoji="📧",
                       style=discord.ButtonStyle.primary, custom_id="numgen:mail")
    async def mail(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not numgen.status()["mail_ok"]:
            await itx.response.send_message(
                "⚠️ Aucune clé SMSBower configurée — un admin doit faire `/smskey`.",
                ephemeral=True)
            return
        await itx.response.defer(ephemeral=True, thinking=True)
        await self.cog.start_mail(itx, "ig")

    @discord.ui.button(label="Autre service", emoji="⚙️",
                       style=discord.ButtonStyle.secondary, row=1,
                       custom_id="numgen:other")
    async def other(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.send_message(
            "⚙️ **Autre service** — numéro OU mail, choisis 👇",
            view=_OtherView(self.cog), ephemeral=True)


class _OtherView(discord.ui.View):
    """Numéro/mail pour un service autre qu'Instagram."""
    def __init__(self, cog):
        super().__init__(timeout=120)
        self.cog = cog

    @discord.ui.button(label="📱 Numéro", style=discord.ButtonStyle.success)
    async def n(self, itx: discord.Interaction, b: discord.ui.Button):
        await itx.response.send_message("Service 👇", view=_ServiceView("sms", self.cog),
                                        ephemeral=True)

    @discord.ui.button(label="📧 Mail", style=discord.ButtonStyle.primary)
    async def m(self, itx: discord.Interaction, b: discord.ui.Button):
        await itx.response.send_message("Service 👇", view=_ServiceView("mail", self.cog),
                                        ephemeral=True)


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
        view.service = service
        solde = (await asyncio.to_thread(numgen.balances)).get("sms")
        # Le pays réglé peut être à sec : numgen bascule alors seul sur un
        # pays qui a du stock. Le dire, sinon on reçoit un numéro étranger
        # sans comprendre pourquoi — et le réglage a l'air cassé.
        note, pris = None, res.get("country")
        if pris and pris != numgen.default_country():
            note = (f"ℹ️ Plus de numéro dans le pays réglé — pris en "
                    f"**{dict(numgen.PAYS).get(pris, pris)}**.")
        msg = await interaction.followup.send(
            content=note, embed=self._embed_txt("📱", res["phone"], service,
                                                user=interaction.user.id, solde=solde),
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
        view.service = service
        solde = (await asyncio.to_thread(numgen.balances)).get("mail")
        msg = await interaction.followup.send(
            embed=self._embed_txt("📧", res["mail"], service,
                                  user=interaction.user.id, solde=solde),
            view=view, ephemeral=True, wait=True)
        view.message = msg
        await self.watch(interaction, view, first=True)

    def _embed_txt(self, icon, value, service, waiting=True, code=None, err=None,
                   user=None, solde=None):
        """EMBED d'activation, calqué sur le serveur de référence de l'user :
        barre verte, valeur en gros, ⚠️ anti-ban, mode d'emploi, solde en pied."""
        kind_lbl = "numéro" if icon == "📱" else "mail"
        app = _svc_label(service)
        emb = discord.Embed(
            title=f"{icon} Ton {kind_lbl} {app}",
            color=(discord.Color.green() if not err else discord.Color.orange()),
        )
        emb.description = f"{'📞' if icon == '📱' else '✉️'} `{value}`"
        if code:
            emb.add_field(name="🔑 Code reçu", value=f"# {code}", inline=False)
            emb.add_field(
                name="​",
                value="_Besoin d'un autre code ? → **🔄 Redemander un code**_",
                inline=False)
        elif err:
            emb.add_field(name="⚠️ Souci", value=str(err)[:900], inline=False)
        else:
            emb.add_field(
                name="⚠️ À lire absolument",
                value=(f"Entre ce {kind_lbl} **à la main** sur {app} — "
                       "**ne le copie-colle JAMAIS** (risque de ban de la plateforme)."),
                inline=False)
            emb.add_field(
                name="Comment faire",
                value=(f"**1.** Saisis le {kind_lbl} à la main sur **{app}**\n"
                       f"**2.** Demande l'envoi du code\n"
                       f"**3.** ⏳ Le code arrive **automatiquement ici** "
                       f"(j'écoute {POLL_MAX // 60} min)"),
                inline=False)
        if user is not None:
            emb.add_field(name="Lié à toi", value=f"<@{user}>", inline=False)
        if solde:
            emb.set_footer(text=f"Youl4b · solde : {solde}")
        return emb

    # --------------------------------------------------------------- polling
    async def watch(self, interaction, view, first=True):
        """Poll le code et ÉDITE le message d'origine dès qu'il arrive."""
        service = getattr(view, "service", "ig")
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
                await self.show_code(interaction, view, val)
                return
            if state in ("cancel", "error"):
                emb = self._embed_txt("📱" if view.kind == "sms" else "📧",
                                      view.value, service,
                                      err=val or "activation annulée",
                                      user=view.owner_id)
                await self._edit(interaction, view, emb)
                return
        emb = self._embed_txt("📱" if view.kind == "sms" else "📧", view.value,
                              service, err="Aucun code reçu dans le délai.",
                              user=view.owner_id)
        await self._edit(interaction, view, emb)

    async def show_code(self, interaction, view, code):
        """Code reçu : on clôture l'activation et on l'affiche dans l'embed."""
        view.code = code
        if view.kind == "sms":
            await asyncio.to_thread(numgen.finish, view.act_id, view.provider)
        else:
            view.stale = code          # le prochain code doit être DIFFÉRENT
        emb = self._embed_txt("📱" if view.kind == "sms" else "📧", view.value,
                              getattr(view, "service", "ig"), code=code,
                              user=view.owner_id)
        await self._edit(interaction, view, emb)

    async def _edit(self, interaction, view, embed):
        try:
            if getattr(view, "message", None) is not None:
                await view.message.edit(embed=embed, view=view)
                return
        except Exception:
            pass
        try:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
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
        name="panelnumeroall",
        description="[ADMIN] Pose le panneau Numéro & Mail dans TOUS les salons -numero-mail")
    @app_commands.describe(
        remplacer="true = supprime l'ancien panneau et repose le nouveau (mise à jour du design)")
    async def panelnumeroall(self, interaction: discord.Interaction,
                             remplacer: bool = False):
        from cogs.user import _is_staff_member
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux admins.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        from cogs.welcome import _ensure_num_panel, _us_norm
        targets = [c for c in guild.text_channels
                   if _us_norm(c.name).endswith("-numero-mail")]
        if not targets:
            await interaction.response.send_message(
                "Aucun salon `…-numero-mail` sur ce serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok = skipped = 0
        for ch in targets:
            olds = []
            try:
                for p in await ch.pins():
                    t = (p.embeds[0].title or "") if p.embeds else ""
                    if p.author.id == getattr(self.bot.user, "id", 0) and (
                            "Numéro & Mail" in t or "Numéros & Mails" in t):
                        olds.append(p)
            except Exception:
                pass
            if olds and not remplacer:
                skipped += 1
                continue
            for p in olds:                    # remplacer : on vire l'ancien
                try:
                    await p.delete()
                except Exception:
                    try:
                        await p.unpin()
                    except Exception:
                        pass
            if await _ensure_num_panel(self.bot, ch):
                ok += 1
            await asyncio.sleep(0.6)
        s = numgen.status()
        warn = "" if (s["sms_ok"] and s["mail_ok"]) else (
            "\n⚠️ **Clés manquantes** — fais `/smskey getatext:… smsbower:…` "
            "sinon les boutons refuseront.")
        await interaction.followup.send(
            f"✅ Panneau posé dans **{ok}** salon(s)"
            + (f", {skipped} l'avaient déjà (`remplacer:true` pour les mettre à jour)"
               if skipped else "")
            + f" (sur {len(targets)} salons `-numero-mail`).{warn}", ephemeral=True)

    @app_commands.command(
        name="resetpanels",
        description="[ADMIN] RESET : repose les panneaux (menu Jailbreak + numéro/mail) dans TOUS les salons")
    async def resetpanels(self, interaction: discord.Interaction):
        from cogs.user import _is_staff_member
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux admins.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        from cogs.welcome import _ensure_num_panel, _ensure_us_menu, _us_norm
        menus = [c for c in guild.text_channels if _us_norm(c.name).endswith("-menu")]
        nums = [c for c in guild.text_channels if _us_norm(c.name).endswith("-numero-mail")]
        if not menus and not nums:
            await interaction.response.send_message(
                "Aucun salon `…-menu` ni `…-numero-mail` ici.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        me = getattr(self.bot.user, "id", 0)

        async def _wipe(ch, titles):
            """Supprime les anciens panneaux epingles de ce salon.

            De N IMPORTE QUEL bot, pas seulement du notre. Le panneau pose
            avant que le cog ne demenage appartient a l AUTRE application :
            ses boutons ne trouvent plus personne et Discord repond « n a pas
            repondu a temps ». En ne nettoyant que nos propres messages, le
            reset laissait le cadavre epingle a cote du neuf — deux panneaux
            identiques a l ecran, dont un mort, et rien pour les distinguer.

            Le filet reste etroit : un message EPINGLE, d un BOT, dont le
            titre d embed est l un des notres. Une conversation ne peut pas
            tomber dedans.
            """
            try:
                for p in await ch.pins():
                    t = (p.embeds[0].title or "") if p.embeds else ""
                    if getattr(p.author, "bot", False) and any(k in t for k in titles):
                        try:
                            await p.delete()
                        except Exception:
                            try:
                                await p.unpin()
                            except Exception:
                                pass
            except Exception:
                pass

        n_menu = n_num = 0
        for ch in menus:
            await _wipe(ch, ("Jailbreak US", "Menu Jailbreak"))
            if await _ensure_us_menu(self.bot, ch):
                n_menu += 1
            await asyncio.sleep(0.6)
        for ch in nums:
            await _wipe(ch, ("Numéro & Mail", "Numéros & Mails"))
            if await _ensure_num_panel(self.bot, ch):
                n_num += 1
            await asyncio.sleep(0.6)
        s = numgen.status()
        warn = "" if (s["sms_ok"] and s["mail_ok"]) else (
            "\n⚠️ Clé "
            + ("SMSBower (mails) " if not s["mail_ok"] else "")
            + ("GetAText (numéros) " if not s["sms_ok"] else "")
            + "manquante — fais `/smskey`.")
        await interaction.followup.send(
            f"♻️ **Reset des panneaux terminé**\n"
            f"• 🔓 Menu Jailbreak US : **{n_menu}**/{len(menus)} salon(s) `-menu`\n"
            f"• 📱 Numéro & Mail : **{n_num}**/{len(nums)} salon(s) `-numero-mail`{warn}",
            ephemeral=True)

    @app_commands.command(
        name="smskey",
        description="[OWNER] Clés des générateurs (formulaire privé) + soldes")
    async def smskey(self, interaction: discord.Interaction):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        # FORMULAIRE (modal) et pas des options de slash : une option se voit
        # dans la zone de saisie et peut partir en clair dans le salon.
        await interaction.response.send_modal(_KeysModal())

    @app_commands.command(
        name="soldes",
        description="Solde des générateurs (numéros GetAText + mails SMSBower)")
    async def soldes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        b = await asyncio.to_thread(numgen.balances)
        await interaction.followup.send(
            "💰 **Soldes**\n"
            f"• 📱 Numéros (GetAText) : **{b['sms']}**\n"
            f"• 📧 Mails (SMSBower) : **{b['mail']}**", ephemeral=True)


class _KeysModal(discord.ui.Modal, title="🔑 Clés des générateurs"):
    getatext = discord.ui.TextInput(
        label="Clé GetAText (numéros)", required=False, max_length=120,
        placeholder="laisse vide pour ne pas changer")
    smsbower = discord.ui.TextInput(
        label="Clé SMSBower (mails)", required=False, max_length=120,
        placeholder="laisse vide pour ne pas changer")
    pays = discord.ui.TextInput(
        label="Pays par défaut (0 = RU, 187 = USA)", required=False, max_length=6,
        placeholder="187")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        s = await asyncio.to_thread(
            numgen.set_keys,
            str(self.getatext.value).strip() or None,
            str(self.smsbower.value).strip() or None,
            str(self.pays.value).strip() or None)
        b = await asyncio.to_thread(numgen.balances)
        await interaction.followup.send(
            f"✅ **Enregistré**\n"
            f"• 📱 GetAText : {s['getatext'] or '❌ absente'} — solde **{b['sms']}**\n"
            f"• 📧 SMSBower : {s['smsbower'] or '❌ absente'} — solde **{b['mail']}**\n"
            f"• 🌍 Pays par défaut : `{s['country']}`", ephemeral=True)


def panel_embed():
    """Panneau calqué sur celui de l'autre serveur de l'user (avertissement
    coût + confidentialité), avec les soldes des DEUX fournisseurs."""
    try:
        b = numgen.balances()
    except Exception:
        b = {"sms": "—", "mail": "—"}
    return discord.Embed(
        title="📱 Numéros & Mails Instagram",
        description=(
            "Clique sur un bouton pour obtenir un **numéro** ou un **mail** "
            "et vérifier un compte Instagram.\n\n"
            "Le numéro/mail **et le code** ne sont visibles que **par toi** "
            "(message éphémère). Le code arrive **tout seul** ici.\n\n"
            "⚠️ Chaque numéro/mail **coûte de l'argent** — n'en prends que si "
            "tu en as vraiment besoin."
        ),
        color=discord.Color.blurple(),
    ).set_footer(text=f"Solde · 📱 numéros : {b['sms']}   |   📧 mails : {b['mail']}")


async def setup(bot):
    await bot.add_cog(NumerosCog(bot))
