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
import safe_json as _safe_json
from pathlib import Path as _Path

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

    # Boutons DIRECTS en Instagram/Threads : c'est Insta dans 100 % des cas.
    # « Autre service » a ete retire le 30/08/2026 — il n'ajoutait qu'un
    # detour de deux ecrans pour un cas qui ne se presentait pas.
    @discord.ui.button(label="Numéro Instagram / Threads", emoji="📱",
                       style=discord.ButtonStyle.success, custom_id="numgen:sms")
    async def sms(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not numgen.status()["sms_ok"]:
            await itx.response.send_message(
                "⚠️ Aucune clé SMS configurée — un admin doit faire `/smskey`.",
                ephemeral=True)
            return
        await itx.response.defer()
        await self.cog.nouvelle_activation(itx, "sms", "ig")

    @discord.ui.button(label="Mail Instagram", emoji="📧",
                       style=discord.ButtonStyle.primary, custom_id="numgen:mail")
    async def mail(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer()
        await self.cog.nouvelle_activation(itx, "mail", "ig")

    # « Autre service » retire du panneau le 30/08/2026 : c'est Instagram dans
    # tous les cas, et le bouton n'ajoutait qu'un detour de deux ecrans. Les
    # vues ci-dessous restent joignables par les panneaux DEJA POSES, dont les
    # boutons portent encore custom_id="numgen:other" — un message Discord ne
    # se redessine pas, et un bouton sans repondant affiche « n'a pas repondu
    # a temps ». Elles partiront quand plus aucun panneau d'avant ne circulera.


class _PanneauAncienView(discord.ui.View):
    """Sert le bouton « Autre service » des panneaux DEJA POSES.

    Le bouton a ete retire du panneau neuf, mais les messages epingles avant
    ce jour le portent toujours — un message Discord ne se redessine pas. Sans
    repondant, ce bouton-la afficherait « n a pas repondu a temps », qui est
    precisement le symptome qu on vient de passer la soiree a chasser. Cette
    vue disparaitra quand plus aucun ancien panneau ne circulera.
    """
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Autre service", emoji="⚙️", row=1,
                       style=discord.ButtonStyle.secondary,
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
            # Les panneaux d avant portent encore « Autre service » : on
            # continue de le servir tant qu ils circulent.
            self.bot.add_view(_PanneauAncienView(self))
            self.bot.add_view(ActionsView(self))
        except Exception:
            pass

    # ---- Les trois messages : tout se passe DANS le salon -----------------
    async def nouvelle_activation(self, itx, kind="sms", service="ig"):
        """Prend un numero (ou un mail) et le montre dans le message 2.

        Rien d'ephemere : le VA n'a pas a garder un message fantome ouvert, et
        s'il recharge Discord il retrouve exactement le meme ecran.
        """
        ch = getattr(itx, "channel", None)
        if ch is None:
            return
        # Les trois messages doivent EXISTER avant qu'on commande quoi que ce
        # soit. Un salon qui n'a recu que le panneau — pose par l'ancienne
        # route, ou par /panelnumero — n'a ni place pour le numero ni place
        # pour le code : le clic achetait un numero que rien n'affichait, et
        # il etait perdu avec l'argent. On les pose donc d'abord.
        rec0 = _salon(ch.id)
        if not (rec0.get("numero") and rec0.get("code")):
            await poser_trois(self.bot, ch, self)
        await maj_trois(self.bot, ch, actif=None,
                        souci_num="⏳ Recherche d'un numéro…",
                        souci_code="")
        if kind == "sms":
            ok, res = await asyncio.to_thread(numgen.get_number, service)
        else:
            ok, res = await asyncio.to_thread(numgen.get_mail, service)
        if not ok:
            # Un solde vide ou un fournisseur a sec se DIT dans la place du
            # numero, qui reste visible : demande user — le bloc ne disparait
            # jamais, c'est son texte qui change.
            _salon_ecrire(ch.id, actif=None)
            await maj_trois(self.bot, ch, actif=None,
                            souci_num="❌ %s" % str(res)[:400])
            return
        actif = {
            "id": str(res.get("id") or ""),
            "provider": res.get("provider") or "getatext",
            "kind": kind,
            "service": service,
            "valeur": res.get("phone") or res.get("mail") or "?",
            "stale": res.get("stale", ""),
            "pays_nom": dict(numgen.PAYS).get(str(res.get("country") or ""), ""),
            "par": getattr(getattr(itx, "user", None), "id", 0),
        }
        _salon_ecrire(ch.id, actif=actif, code=None)
        try:
            solde = (await asyncio.to_thread(numgen.balances)).get(
                "sms" if kind == "sms" else "mail")
        except Exception:
            solde = None
        await maj_trois(self.bot, ch, actif=actif, solde=solde)
        self.bot.loop.create_task(self.suivre(ch))

    async def suivre(self, channel):
        """Ecoute le code et l'ECRIT dans le message 3 des qu'il arrive.

        Personne n'a a cliquer « Voir le code » : c'etait un clic pour
        apprendre quelque chose que le bot savait deja.
        """
        for _ in range(POLL_MAX // POLL_SECONDS):
            await asyncio.sleep(POLL_SECONDS)
            rec = _salon(channel.id)
            actif = rec.get("actif")
            if not actif:
                return                      # annule entre-temps
            if actif.get("kind") == "sms":
                etat, val = await asyncio.to_thread(
                    numgen.get_code, actif["id"], actif["provider"])
            else:
                etat, val = await asyncio.to_thread(
                    numgen.get_mail_code, actif["id"], actif.get("stale", ""))
            if etat == "code" and val:
                if actif.get("kind") == "sms":
                    await asyncio.to_thread(numgen.finish, actif["id"],
                                            actif["provider"])
                _salon_ecrire(channel.id, code=val)
                rec2 = dict(actif); rec2["code"] = val
                await maj_trois(self.bot, channel, actif=rec2, code=val)
                return
            if etat in ("cancel", "error"):
                await maj_trois(self.bot, channel, actif=actif,
                                souci_code="⚠️ %s" % (val or "activation close"))
                return
        await maj_trois(self.bot, channel,
                        actif=_salon(channel.id).get("actif"),
                        souci_code=("⏳ Aucun code reçu en %d min. "
                                    "« Redemander un code », ou « Annuler » "
                                    "pour être remboursé." % (POLL_MAX // 60)))

    async def action_salon(self, itx, quoi):
        """🔄 Redemander · 🔁 Autre numéro · ❌ Annuler, depuis le message 2."""
        ch = getattr(itx, "channel", None)
        if ch is None:
            return
        rec = _salon(ch.id)
        actif = rec.get("actif")
        if not actif:
            # Les boutons restent visibles sans activation : ils le disent,
            # au lieu de ne rien faire — un bouton muet passe pour casse.
            await maj_trois(self.bot, ch, actif=None,
                            souci_num=("_Aucun numéro en cours._\n"
                                       "Prends-en un avec **📱 Numéro Instagram "
                                       "/ Threads** au-dessus."))
            return
        sms = actif.get("kind") == "sms"
        if quoi == "retry":
            if sms:
                ok, msg = await asyncio.to_thread(
                    numgen.retry, actif["id"], actif["provider"])
                if not ok:
                    await maj_trois(self.bot, ch, actif=actif,
                                    souci_code="⚠️ %s" % str(msg)[:200])
                    return
            else:
                actif["stale"] = rec.get("code") or actif.get("stale", "")
                _salon_ecrire(ch.id, actif=actif)
            _salon_ecrire(ch.id, code=None)
            await maj_trois(self.bot, ch, actif=actif)
            self.bot.loop.create_task(self.suivre(ch))
            return
        # « Autre » et « Annuler » rendent le numero en cours : rembourse tant
        # qu'aucun code n'est arrive.
        try:
            if sms:
                await asyncio.to_thread(numgen.cancel, actif["id"], actif["provider"])
            else:
                await asyncio.to_thread(numgen.mail_cancel, actif["id"])
        except Exception as e:
            log.warning(f"action_salon {quoi} : {e}")
        _salon_ecrire(ch.id, actif=None, code=None)
        if quoi == "autre":
            await self.nouvelle_activation(itx, "sms" if sms else "mail",
                                           actif.get("service", "ig"))
            return
        await maj_trois(self.bot, ch, actif=None)

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
        """Pose le panneau DANS LE SALON COURANT, quel que soit son nom.

        C est la voie sure : les commandes « all » cherchent des salons qui
        finissent par -numero-mail, et cette convention n existe que sur le
        serveur des tickets. Ailleurs le salon s appelle sms-email, ou
        autrement — 156 salons visibles et pas un seul qui matche. Ici, aucun
        filtre : le salon, c est celui ou l on est.

        Elle retire aussi les anciens panneaux EPINGLES de ce salon, de
        n importe quel bot. Le panneau pose avant que le cog ne demenage
        appartient a l autre application et ne repond plus : sans ce
        nettoyage, on se retrouvait avec le neuf a cote du mort, identiques a
        l ecran.
        """
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            from cogs.user import _is_staff_member
            if not _is_staff_member(interaction.user):
                await interaction.response.send_message("Réservé aux admins.", ephemeral=True)
                return
        ch = interaction.channel
        if ch is None:
            await interaction.response.send_message("À utiliser dans un salon.",
                                                    ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        vires = 0
        try:
            for p in await ch.pins():
                t = (p.embeds[0].title or "") if p.embeds else ""
                if getattr(p.author, "bot", False) and (
                        "Numéros & Mails" in t or "Numéro & Mail" in t):
                    try:
                        await p.delete()
                        vires += 1
                    except Exception:
                        try:
                            await p.unpin()
                            vires += 1
                        except Exception:
                            pass
        except Exception as e:
            log.warning(f"panelnumero: nettoyage impossible ({e})")
        _salon_ecrire(ch.id, panneau=None, numero=None, code=None, actif=None)
        pose = await poser_trois(self.bot, ch, self)
        await verrouiller_salon(ch, self.bot)
        mot = ("✅ Les trois messages sont posés et épinglés" if pose else
               "⚠️ Pose incomplète — regarde les droits du bot sur ce salon")
        if vires:
            mot += f" · {vires} ancien(s) panneau(x) retiré(s)"
        await interaction.followup.send(mot + ".", ephemeral=True)

    @app_commands.command(
        name="panelnumeroall",
        description="[ADMIN] Pose le panneau Numéro & Mail dans TOUS les salons -numero-mail")
    @app_commands.describe(
        remplacer="true = supprime l'ancien panneau et repose le nouveau (mise à jour du design)",
        nettoyer="true = vide le salon de tout ce que les bots y ont posté, ne laisse que le panneau")
    async def panelnumeroall(self, interaction: discord.Interaction,
                             remplacer: bool = False, nettoyer: bool = False):
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
                _pourquoi_aucun_salon(guild, self.bot, ("-numero-mail",)),
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok = skipped = vides = 0
        for ch in targets:
            if nettoyer:
                # Le salon ne doit contenir QUE le panneau. On efface ce que
                # les BOTS y ont pose — les deux applications, car l ancien
                # panneau vient de l autre — et on laisse les messages des
                # humains : ils sont irrecuperables, et personne n a demande
                # a les perdre. Le panneau est repose juste apres.
                try:
                    partis = await ch.purge(limit=300,
                                            check=lambda m: m.author.bot)
                    vides += len(partis)
                except Exception as e:
                    log.warning(f"panelnumeroall: nettoyage de #{ch.name} : {e}")
                # Le salon repart a neuf : les TROIS messages, et le verrou.
                _salon_ecrire(ch.id, panneau=None, numero=None, code=None,
                              actif=None)
                if await poser_trois(self.bot, ch, self):
                    ok += 1
                await verrouiller_salon(ch, self.bot)
                await asyncio.sleep(0.6)
                continue
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
            if await poser_trois(self.bot, ch, self):
                ok += 1
            await verrouiller_salon(ch, self.bot)
            await asyncio.sleep(0.6)
        s = numgen.status()
        warn = "" if (s["sms_ok"] and s["mail_ok"]) else (
            "\n⚠️ **Clés manquantes** — fais `/smskey getatext:… smsbower:…` "
            "sinon les boutons refuseront.")
        await interaction.followup.send(
            f"✅ Panneau posé dans **{ok}** salon(s)"
            + (f", {skipped} l'avaient déjà (`remplacer:true` pour les mettre à jour)"
               if skipped else "")
            + (f" · {vides} message(s) de bot effacé(s)" if vides else "")
            + f" (sur {len(targets)} salons `-numero-mail`).{warn}"
            + ("" if nettoyer else
               "\nℹ️ `nettoyer:true` pour ne laisser QUE le panneau dans chaque salon."),
            ephemeral=True)

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
                _pourquoi_aucun_salon(guild, self.bot, ("-menu", "-numero-mail")),
                ephemeral=True)
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


def _pourquoi_aucun_salon(guild, bot, suffixes):
    """Le message quand aucun salon cible n est trouve — avec la RAISON.

    « Aucun salon …-numero-mail sur ce serveur » est un cul-de-sac : les
    salons sont la, sous les yeux, et la commande dit qu ils n existent pas.
    Ce qu elle veut dire, c est « je n en vois aucun » — et la difference est
    entiere, parce que `guild.text_channels` ne contient QUE les salons que
    ce bot a le droit de voir. Le panneau a ete pose par l autre bot, qui a
    ses acces ; celui-ci ne les a pas forcement recus.

    On dit donc combien de salons il voit, et on nomme les plus proches :
    si la liste est courte alors que le serveur en compte des dizaines, la
    cause saute aux yeux.
    """
    from cogs.welcome import _us_norm
    vus = list(getattr(guild, "text_channels", []) or [])
    libelles = " ni ".join("`…%s`" % s for s in suffixes)
    txt = ["❌ Aucun salon %s **visible** ici." % libelles,
           "Je vois **%d** salon(s) texte sur ce serveur." % len(vus)]
    # Les presque-bons d abord : un salon qui contient le mot sans finir par
    # le suffixe (faute de frappe, suffixe tronque) est la piste la plus utile.
    mots = [s.strip("-").split("-")[0] for s in suffixes]
    proches = [c.name for c in vus
               if any(m in _us_norm(c.name) for m in mots)][:6]
    if proches:
        txt.append("Salons qui y ressemblent : " + ", ".join("`%s`" % n for n in proches)
                   + " — le nom doit **finir** par le suffixe.")
    elif vus:
        txt.append("Exemples de ce que je vois : "
                   + ", ".join("`%s`" % c.name for c in vus[:6]))
    if len(vus) < 5:
        txt.append("C'est peu : ce bot n'a probablement pas la permission "
                   "**Voir les salons** sur les catégories des tickets. "
                   "Donne-la-lui (ou ajoute-le au rôle qui l'a), puis relance.")
    else:
        txt.append("Si les salons existent mais n'apparaissent pas, c'est que "
                   "ce bot n'a pas la permission **Voir les salons** dessus — "
                   "un salon privé n'arrive même pas jusqu'à lui.")

    # LA question qu on se pose devant ce message : « ils sont pourtant la,
    # je les vois ». Les deux bots tournent dans le MEME processus : on peut
    # donc demander a l autre ce qu il voit, lui, et trancher au lieu de
    # supposer. Un salon prive n arrive qu aux applications qui y sont
    # invitees — le bot qui a cree les tickets y est, celui qui a herite du
    # module ne l est pas forcement.
    try:
        # PAS `import main` : le programme est lance par `python main.py`, donc
        # ce fichier est enregistre sous « __main__ ». `import main` en cree une
        # SECONDE copie — code de module rejoue, bots neufs et deconnectes — et
        # son main_bot ne connait aucun serveur. La comparaison rendait donc
        # toujours zero, la ligne ne s affichait jamais, et son absence a ete
        # lue comme « les salons sont ailleurs ». Ils ne l etaient pas.
        import sys as _sys
        _mn = _sys.modules.get("__main__")
        if not hasattr(_mn, "main_bot"):
            _mn = _sys.modules.get("main")
        if _mn is None:
            raise LookupError("module principal introuvable")
        for _autre, _nom in ((getattr(_mn, "main_bot", None), "principal"),
                             (getattr(_mn, "admin_bot", None), "admin")):
            if _autre is None or _autre is bot:
                continue
            _g2 = _autre.get_guild(getattr(guild, "id", 0))
            if _g2 is None:
                continue
            _n2 = sum(1 for c in (_g2.text_channels or [])
                      if any(_us_norm(c.name).endswith(s) for s in suffixes))
            if _n2:
                txt.append(
                    "🔎 Le bot **%s**, lui, en voit **%d** sur ce serveur. "
                    "C'est donc bien un accès qui manque à CE bot-ci, pas un "
                    "problème de nom : ajoute-le aux catégories des VA."
                    % (_nom, _n2))
            else:
                # L absence de cette ligne etait deja la reponse, mais une
                # ligne qui ne s affiche pas ne dit rien a personne : on
                # cherchait une permission alors que les deux bots sont
                # d accord — ces salons ne sont pas ICI.
                _dautres = []
                for _g3 in list(getattr(_autre, "guilds", []) or []):
                    if getattr(_g3, "id", 0) == getattr(guild, "id", 0):
                        continue
                    _n3 = sum(1 for c in (_g3.text_channels or [])
                              if any(_us_norm(c.name).endswith(s) for s in suffixes))
                    if _n3:
                        _dautres.append("**%s** (%d)" % (_g3.name, _n3))
                if _dautres:
                    txt.append(
                        "🔎 Le bot **%s** n'en voit aucun ici non plus — mais il "
                        "en voit sur : %s. Ces salons sont sur un AUTRE serveur : "
                        "relance la commande là-bas."
                        % (_nom, ", ".join(_dautres[:3])))
                else:
                    txt.append(
                        "🔎 Le bot **%s** n'en voit aucun ici non plus, ni sur "
                        "aucun autre serveur. Ce n'est donc pas une permission : "
                        "vérifie le nom exact d'un salon (il doit **finir** par "
                        "le suffixe)." % _nom)
            break
    except Exception:
        pass                      # un diagnostic en plus ne doit rien casser
    # Il y a TOUJOURS une issue, et elle marche quelle que soit la cause :
    # /panelnumero ne regarde aucun nom et n a besoin de voir aucun autre
    # salon que celui ou on l appelle. Sans cette ligne, le message
    # diagnostique laissait quand meme l admin sans rien a faire.
    txt.append("➡️ En attendant : va **dans** le salon voulu et lance "
               "**`/panelnumero`** — il pose le panneau là où tu es, sans "
               "regarder le nom, et retire l'ancien.")
    return "\n".join(txt)


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


# ==============================================================================
# LES TROIS MESSAGES PERMANENTS
# ==============================================================================
# Le salon d'un VA porte trois messages, et rien d'autre. Ils ne sont jamais
# supprimes ni reposes : leur CONTENU change.
#
#   1. le panneau  — les deux boutons, toujours cliquables
#   2. le numero   — vide, ou le numero en cours + ses actions
#   3. le code     — vide, ou le code des qu'il arrive
#
# Avant, chaque clic ouvrait un message EPHEMERE : le VA devait cliquer « Voir
# le code », le message disparaissait au moindre rechargement, et le salon ne
# gardait aucune trace de ce qui etait en cours. On veut l'inverse : un ecran
# fixe qui se met a jour tout seul, comme une page web.

SALONS_FILE = _Path("data") / "numgen_salons.json"


def _salons() -> dict:
    d = _safe_json.load(SALONS_FILE, default={})
    return d if isinstance(d, dict) else {}


def _salon(cid) -> dict:
    return _salons().get(str(cid)) or {}


def _salon_ecrire(cid, **champs):
    """Ecrit les champs d'un salon. `actif=None` efface l'activation."""
    d = _salons()
    rec = dict(d.get(str(cid)) or {})
    rec.update(champs)
    d[str(cid)] = rec
    SALONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _safe_json.write(SALONS_FILE, d, indent=2)
    return rec


def _emb_numero(actif=None, solde=None, souci=""):
    """Message 2 : le numero en cours, ou la place vide qui l'attend."""
    if souci:
        e = discord.Embed(title="📱 Numéro", description=souci,
                          color=discord.Color.red())
        return e
    if not actif:
        e = discord.Embed(
            title="📱 Numéro",
            description=("_Aucun numéro en cours._\n"
                         "Clique sur **📱 Numéro Instagram / Threads** au-dessus."),
            color=discord.Color.dark_grey())
        return e
    e = discord.Embed(
        title="📱 Numéro",
        description=("## `%s`\n"
                     "⚠️ Saisis-le **à la main** sur Instagram — ne le colle jamais.\n"
                     "1. Entre le numéro · 2. Demande l'envoi du code\n"
                     "3. Le code apparaît **tout seul** dans le message du dessous."
                     % actif.get("valeur", "?")),
        color=discord.Color.green())
    bas = []
    if actif.get("pays_nom"):
        bas.append(actif["pays_nom"])
    if solde:
        bas.append("solde %s" % solde)
    if bas:
        e.set_footer(text=" · ".join(bas))
    return e


def _emb_code(actif=None, code=None, souci=""):
    """Message 3 : le code, des qu'il arrive. Personne n'a a le demander."""
    if code:
        return discord.Embed(
            title="🔑 Code reçu",
            description="# `%s`" % code,
            color=discord.Color.green())
    if souci:
        return discord.Embed(title="🔑 Code", description=souci,
                             color=discord.Color.orange())
    if not actif:
        return discord.Embed(
            title="🔑 Code",
            description="_Il s'affichera ici dès qu'un numéro sera pris._",
            color=discord.Color.dark_grey())
    return discord.Embed(
        title="🔑 Code",
        description=("⏳ **En attente du SMS…**\n"
                     "Demande l'envoi du code depuis Instagram : il arrive ici seul."),
        color=discord.Color.blurple())


class ActionsView(discord.ui.View):
    """Les actions du message 2. Toujours la, meme sans numero en cours.

    Elles ne sont pas cachees quand il n'y a rien : un bouton qui apparait et
    disparait fait douter de l'endroit ou il etait. Elles repondent alors
    qu'il n'y a pas d'activation, et c'est tout.
    """
    def __init__(self, cog=None):
        super().__init__(timeout=None)
        self.cog = cog

    async def _cog(self, itx):
        return self.cog or itx.client.get_cog("NumerosCog")

    @discord.ui.button(label="Redemander un code", emoji="🔄",
                       style=discord.ButtonStyle.primary,
                       custom_id="numgen:retry")
    async def retry(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        await itx.response.defer()
        await cog.action_salon(itx, "retry")

    @discord.ui.button(label="Autre numéro", emoji="🔁",
                       style=discord.ButtonStyle.secondary,
                       custom_id="numgen:autre")
    async def autre(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        await itx.response.defer()
        await cog.action_salon(itx, "autre")

    @discord.ui.button(label="Annuler", emoji="❌",
                       style=discord.ButtonStyle.danger,
                       custom_id="numgen:annuler")
    async def annuler(self, itx: discord.Interaction, btn: discord.ui.Button):
        cog = await self._cog(itx)
        await itx.response.defer()
        await cog.action_salon(itx, "annuler")


async def poser_trois(bot, channel, cog=None):
    """Garantit les trois messages, dans l'ordre, et retient leurs identifiants.

    Idempotent : si les trois sont deja la, on les MET A JOUR au lieu d'en
    reposer — sinon chaque passage empilerait un jeu de plus.
    """
    if bot is None or channel is None:
        return False
    cog = cog or bot.get_cog("NumerosCog")
    if cog is None:
        log.warning("poser_trois: NumerosCog absent sur ce bot")
        return False
    rec = _salon(channel.id)
    actif = rec.get("actif")
    try:
        solde = (await asyncio.to_thread(numgen.balances)).get("sms")
    except Exception:
        solde = None
    voulus = (
        ("panneau", panel_embed(), NumPanelView(cog)),
        ("numero", _emb_numero(actif, solde), ActionsView(cog)),
        ("code", _emb_code(actif, (actif or {}).get("code")), None),
    )
    ids = {}
    for cle, emb, vue in voulus:
        mid = rec.get(cle)
        msg = None
        if mid:
            try:
                msg = await channel.fetch_message(int(mid))
            except Exception:
                msg = None
        try:
            if msg is not None:
                await msg.edit(embed=emb, view=vue)
            else:
                msg = await channel.send(embed=emb, view=vue)
                try:
                    await msg.pin()
                except Exception:
                    pass
            ids[cle] = msg.id
        except Exception as e:
            log.warning(f"poser_trois #{getattr(channel, 'name', '?')} {cle} : {e}")
        await asyncio.sleep(0.4)
    if ids:
        _salon_ecrire(channel.id, **ids)
    return len(ids) == 3


async def maj_trois(bot, channel, actif=None, code=None, souci_num="",
                    souci_code="", solde=None):
    """Reecrit les messages 2 et 3. Le panneau, lui, ne bouge jamais."""
    rec = _salon(getattr(channel, "id", 0))
    for cle, emb in (("numero", _emb_numero(actif, solde, souci_num)),
                     ("code", _emb_code(actif, code, souci_code))):
        mid = rec.get(cle)
        if not mid:
            continue
        try:
            msg = await channel.fetch_message(int(mid))
            await msg.edit(embed=emb)
        except Exception as e:
            log.warning(f"maj_trois {cle} : {e}")


async def verrouiller_salon(channel, bot):
    """Le salon devient une vitrine : seul le bot y ecrit.

    Le VA garde la LECTURE et les boutons — une interaction n'est pas un
    message. Sans ca, un salon qui ne doit contenir que trois messages se
    remplissait de conversations, et les trois se retrouvaient en haut,
    hors de vue.
    """
    g = getattr(channel, "guild", None)
    if g is None:
        return False
    try:
        await channel.set_permissions(
            g.default_role, send_messages=False,
            reason="Salon numero/mail : seul le bot y ecrit")
        return True
    except Exception as e:
        log.warning(f"verrouiller_salon #{getattr(channel, 'name', '?')} : {e}")
        return False




async def setup(bot):
    await bot.add_cog(NumerosCog(bot))
