"""Panneau « Numéro Instagram » des salons -numero-mail (serveur US).

UN message Components V2 par salon, l'icône emojis/numero_instagram.png en
vignette (maquette /demonumero, validée par le propriétaire le 27/09/2026 :
« vas-y mets le design avec l'icône »). Son CONTENU suit l'activation :

  vide        « Numéro Instagram » et le solde SMS
              📱 Prendre un numéro · 📧 Mail
  en attente  le numéro, collé (+15550142294), « ⏳ En attente du code… »
              🔄 Redemander un code · 🔁 Autre · ❌ Annuler
  code reçu   le même numéro, « 🔑 Code : 482913 », écrit TOUT SEUL
              ✅ C'est bon · 🔄 Nouveau code · 🔁 Autre

Un souci (pas de numéro, solde vide, écoute interrompue) = une ligne « ❌ … »
dans ce même message. Seuls les refus et les confirmations sont éphémères.
Il remplace les trois messages d'avant (panneau, numéro, code) : un salon à
l'ancien format est converti au premier clic ou à la première pose
(`poser_panneau`), le numéro en cours gardé.
"""
import asyncio
import functools
import logging
import re
import time

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
        # Le clic sur un panneau d'avant le CONVERTIT au passage (27/09/2026) :
        # le salon passe au message unique, et ce bouton disparait avec lui.
        cog = self.cog or itx.client.get_cog("NumerosCog")
        if cog is not None:
            await cog.convertir_si_ancien(itx)


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
        # Salons ou un achat est EN COURS. La commande prend quelques
        # secondes (plusieurs pays essayes) : un second clic pendant ce temps
        # trouvait un salon sans numero enregistre et en achetait un deuxieme.
        self._achats = set()
        # Generation de l'ecoute du code, par salon : seule la plus recente
        # ecrit. « Redemander » en lancait une a cote de la precedente, et
        # « Autre » laissait l'ancienne interroger le nouveau numero puis
        # annoncer son delai depasse avant l'heure.
        self._ecoute = {}

    @commands.Cog.listener()
    async def on_interaction(self, itx: discord.Interaction):
        """Trace chaque clic du panneau numero/mail (27/09/2026).

        Le panneau « ne marchait pas » sans rien laisser dans le journal : on
        ne savait meme pas si le clic arrivait jusqu au bot. Une ligne par clic
        suffit a le dire."""
        try:
            cid = str((getattr(itx, "data", None) or {}).get("custom_id") or "")
        except Exception:                                    # noqa: BLE001
            return
        if cid.startswith("numgen:"):
            log.info("numgen: clic %s par %s (%s) dans #%s", cid,
                     getattr(itx.user, "name", "?"), getattr(itx.user, "id", "?"),
                     getattr(getattr(itx, "channel", None), "name", "?"))

    async def cog_load(self):
        # Vues persistantes : un clic sur un message DEJA poste doit trouver
        # son repondant apres un redemarrage. Une vue porte TOUS les boutons
        # du panneau (chaque etat n'en montre que deux ou trois) ; l'autre sert
        # « Autre service » des panneaux d'avant, pas encore convertis. Les
        # boutons des anciens messages (numgen:sms/mail, numgen:retry/autre/
        # annuler du message « Numero ») ont les MEMES custom_id : ils arrivent
        # donc ici aussi, et leur clic convertit le salon.
        for vue in (PanneauNumero(self, tous=True), _PanneauAncienView(self)):
            try:
                self.bot.add_view(vue)
            except Exception as e:                           # noqa: BLE001
                log.error("numgen: vue persistante %s non enregistree (%s: %s) — "
                          "ses boutons ne repondront plus apres un redemarrage",
                          type(vue).__name__, type(e).__name__, e)

    # ---- Le panneau : un seul message, qui change --------------------------
    async def clic(self, itx, action):
        """Tout clic du panneau passe ici, quel que soit le format du message.

        On REPOND d'abord (Discord laisse trois secondes), puis on convertit
        le salon s'il est encore a l'ancien format, puis on agit. L'etat ne se
        lit jamais dans la vue : il vit dans data/numgen_salons.json, et une
        vue recreee au redemarrage n'en sait rien.
        """
        ch = getattr(itx, "channel", None)
        if ch is None:
            await itx.response.send_message("À utiliser dans un salon.", ephemeral=True)
            return
        if action == "sms" and not numgen.status()["sms_ok"]:
            await itx.response.send_message(
                "⚠️ Aucune clé SMS configurée — un admin doit faire `/smskey`.",
                ephemeral=True)
            await self.convertir_si_ancien(itx)
            return
        immediat = True
        if action in ("autre", "annuler"):
            # Refus ou confirmation, visibles du seul cliqueur : la suite part
            # de « Oui » (_ConfirmerView). Rien a confirmer : clic differe.
            immediat = await _confirmer_ou_refuser(itx, self, action)
        else:
            await itx.response.defer()
        await self.convertir_si_ancien(itx)
        if not immediat:
            return
        if action in ("sms", "mail"):
            await self.nouvelle_activation(itx, action, "ig")
        else:
            await self.action_salon(itx, action)

    async def convertir_si_ancien(self, itx):
        """Le message clique n'est pas le panneau V2 du salon : on convertit.

        C'est un ancien panneau (embed), l'ancien message « Numero », ou un
        panneau V2 que le registre ne connait pas (data/ reparti de zero sur le
        VPS). poser_panneau garde le numero en cours et retire le reste.
        """
        m = getattr(itx, "message", None)
        ch = getattr(itx, "channel", None)
        if m is None or ch is None:
            return False
        rec = _salon(ch.id)
        if rec.get("v2") and _id_message(rec.get("panneau")) == getattr(m, "id", None):
            return False
        moi = getattr(getattr(self.bot, "user", None), "id", None)
        log.info("numgen: clic sur un message %s (%s) de #%s : conversion du salon",
                 getattr(m, "id", "?"), est_panneau_numero(m, moi) or "hors panneau",
                 getattr(ch, "name", "?"))
        try:
            return await poser_panneau(self.bot, ch, self, vu=m)
        except Exception as e:                               # noqa: BLE001
            log.exception("numgen: conversion de #%s impossible (%s: %s)",
                          getattr(ch, "name", "?"), type(e).__name__, e)
            return False

    async def nouvelle_activation(self, itx, kind="sms", service="ig"):
        """Prend un numero (ou un mail) et le montre DANS le panneau.

        Rien d'ephemere : le VA n'a pas a garder un message fantome ouvert, et
        s'il recharge Discord il retrouve exactement le meme ecran.
        """
        ch = getattr(itx, "channel", None)
        if ch is None:
            return
        rec0 = _salon(ch.id)
        en_cours = rec0.get("actif")
        if en_cours and not rec0.get("code_valeur") and _numero_vivant(en_cours):
            # Un numero attend encore son code : en prendre un autre ici
            # l'effacait de l'ecran sans le rendre (paye pour rien), et
            # c'etait peut-etre celui d'un autre membre.
            if _peut_gerer(itx, en_cours):
                mot = ("📱 Tu as déjà `%s` en cours : utilise 🔁 **Autre** "
                       "ou ❌ **Annuler**." % en_cours.get("valeur", "?"))
            else:
                mot = ("🔒 Un numéro est déjà en cours pour <@%s> dans ce salon."
                       % en_cours.get("par"))
            log.info("numgen: %s refuse dans #%s : %s deja en attente de code",
                     kind, getattr(ch, "name", "?"), en_cours.get("valeur"))
            await _ephemere(itx, mot)
            return
        if ch.id in self._achats:
            log.info("numgen: %s refuse dans #%s : un achat y est deja en cours",
                     kind, getattr(ch, "name", "?"))
            await _ephemere(itx, "⏳ Un numéro est déjà en cours de commande ici.")
            return
        self._achats.add(ch.id)
        try:
            await self._acheter(itx, ch, kind, service)
        finally:
            self._achats.discard(ch.id)

    async def _acheter(self, itx, ch, kind, service):
        # L'activation precedente (code deja recu, ou numero mort) laisse la
        # place : elle ne reviendra pas s'afficher si l'achat echoue.
        _salon_ecrire(ch.id, actif=None, code_valeur=None)
        self._ecoute[ch.id] = self._ecoute.get(ch.id, 0) + 1
        # LE PIEGE d'avant : un achat sans place pour l'afficher. Le clic
        # achetait un numero que rien ne montrait, perdu avec l'argent. Le
        # panneau doit donc etre ECRIT avant qu'on commande quoi que ce soit.
        cherche = ("⏳ Recherche d'un numéro…" if kind == "sms"
                   else "⏳ Recherche d'un mail…")
        if not await maj_panneau(self.bot, ch, cog=self, souci=cherche,
                                 solde=_DERNIER_SOLDE["sms"] or "—"):
            log.error("numgen: panneau de #%s impossible a ecrire : rien n'est achete",
                      getattr(ch, "name", "?"))
            await _ephemere(itx, "❌ Le panneau ne peut pas s'afficher dans ce salon : "
                                 "rien n'a été acheté.")
            return
        log.info("numgen: %s demande dans #%s", kind, getattr(ch, "name", "?"))
        if kind == "sms":
            ok, res = await asyncio.to_thread(numgen.get_number, service)
        else:
            ok, res = await asyncio.to_thread(numgen.get_mail, service)
        if not ok:
            log.warning("numgen: %s refuse pour #%s : %s", kind,
                        getattr(ch, "name", "?"), str(res)[:300])
            # Un solde vide ou un fournisseur a sec se DIT dans le panneau,
            # sur une ligne : le reste ne bouge pas.
            await maj_panneau(self.bot, ch, cog=self, souci="❌ %s" % res)
            return
        log.info("numgen: %s obtenu (%s, %s) pour #%s", kind,
                 (res or {}).get("provider"), (res or {}).get("country"),
                 getattr(ch, "name", "?"))
        actif = {
            "id": str(res.get("id") or ""),
            "provider": res.get("provider") or "getatext",
            "kind": kind,
            "service": service,
            "valeur": res.get("phone") or res.get("mail") or "?",
            "stale": res.get("stale", ""),
            "pays_nom": dict(numgen.PAYS).get(str(res.get("country") or ""), ""),
            "par": getattr(getattr(itx, "user", None), "id", 0),
            # Heure de prise : un numero mort ne bloque plus le salon.
            "pris_le": int(time.time()),
        }
        _salon_ecrire(ch.id, actif=actif, code_valeur=None)
        if not await maj_panneau(self.bot, ch, cog=self):
            # On n'a pas pu l'ECRIRE : le VA ne le verra jamais. Le garder,
            # c'est le payer pour rien — chaque clic coutait 0,25 $ pendant
            # que le panneau restait sur « Recherche d'un numero… ». On le
            # rend, ce qui rembourse tant qu'aucun code n'est arrive.
            log.error("numgen: numero %s pris mais INAFFICHABLE dans #%s — on le rend",
                      actif.get("valeur"), getattr(ch, "name", "?"))
            try:
                if kind == "sms":
                    rendu = await asyncio.to_thread(numgen.cancel, actif["id"],
                                                    actif["provider"])
                else:
                    rendu = await asyncio.to_thread(numgen.mail_cancel, actif["id"])
                log.warning("numgen: rendu de %s : %s", actif.get("valeur"), rendu)
            except Exception as e:                  # noqa: BLE001
                log.error("numgen: rendu impossible (%s)", e)
            _salon_ecrire(ch.id, actif=None, code_valeur=None)
            await _ephemere(itx, "❌ Le numéro n'a pas pu s'afficher : il a été rendu "
                                 "(remboursé).")
            return
        self._ecouter(ch)

    def _ecouter(self, channel):
        """Lance l'ecoute du code de l'activation EN COURS du salon ; une
        ecoute plus ancienne s'arrete au tour suivant."""
        g = self._ecoute.get(channel.id, 0) + 1
        self._ecoute[channel.id] = g
        self.bot.loop.create_task(self.suivre(channel, g))

    def _ecoute_courante(self, channel, gen):
        return gen is None or self._ecoute.get(getattr(channel, "id", 0)) == gen

    async def suivre(self, channel, gen=None):
        """Ecoute le code et l'ECRIT dans le panneau des qu'il arrive.

        Personne n'a a cliquer « Voir le code » : c'etait un clic pour
        apprendre quelque chose que le bot savait deja.

        TOUT est rattrape : une tache de fond qui leve meurt sans un mot, et
        c'est arrive — le code etait chez le fournisseur, le bloc restait
        vide, et rien nulle part ne disait pourquoi. Un echec s'ecrit
        desormais DANS le panneau, sur une ligne.
        """
        try:
            await self._suivre(channel, gen)
        except Exception as e:                      # noqa: BLE001
            log.error("numgen: ecoute de #%s interrompue : %r",
                      getattr(channel, "name", "?"), e)
            try:
                if self._ecoute_courante(channel, gen):
                    await maj_panneau(self.bot, channel, cog=self,
                                      souci="❌ Écoute interrompue (%s)"
                                            % type(e).__name__)
            except Exception as e2:                 # noqa: BLE001
                log.error("numgen: et l'incident n'a pas pu s'ecrire dans #%s (%r)",
                          getattr(channel, "name", "?"), e2)

    async def _suivre(self, channel, gen=None):
        rec0 = _salon(channel.id)
        act_id = (rec0.get("actif") or {}).get("id")
        log.info("numgen: ecoute du code demarree pour #%s (%s)",
                 getattr(channel, "name", "?"), act_id)
        for _ in range(POLL_MAX // POLL_SECONDS):
            await asyncio.sleep(POLL_SECONDS)
            if not self._ecoute_courante(channel, gen):
                return                      # une ecoute plus recente a pris le relais
            rec = _salon(channel.id)
            actif = rec.get("actif")
            if not actif or actif.get("id") != act_id:
                return                      # annule ou remplace entre-temps
            if rec.get("code_valeur"):
                return                      # deja trouve (« Redemander »)
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
                _salon_ecrire(channel.id, code_valeur=val)
                log.info("numgen: code recu pour #%s (%s)",
                         getattr(channel, "name", "?"), act_id)
                await maj_panneau(self.bot, channel, cog=self)
                return
            if etat in ("cancel", "error"):
                log.warning("numgen: ecoute de #%s close : %s %s",
                            getattr(channel, "name", "?"), etat, val)
                await maj_panneau(self.bot, channel, cog=self,
                                  souci="❌ %s" % (val or "activation close"))
                return
        if self._ecoute_courante(channel, gen):
            log.info("numgen: aucun code en %d min pour #%s (%s)", POLL_MAX // 60,
                     getattr(channel, "name", "?"), act_id)
            await maj_panneau(self.bot, channel, cog=self,
                              souci="❌ Aucun code reçu en %d min" % (POLL_MAX // 60))

    async def action_salon(self, itx, quoi):
        """🔄 Redemander · ✅ C'est bon · 🔁 Autre · ❌ Annuler, depuis le panneau."""
        ch = getattr(itx, "channel", None)
        if ch is None:
            return
        rec = _salon(ch.id)
        actif = rec.get("actif")
        if not actif:
            # Un vieux message ou un double clic : rien en cours. Le panneau
            # est redessine (etat vide) au lieu d'un bouton muet.
            log.info("numgen: %s sans numero en cours dans #%s", quoi,
                     getattr(ch, "name", "?"))
            await maj_panneau(self.bot, ch, cog=self)
            return
        sms = actif.get("kind") == "sms"
        if quoi in ("autre", "annuler") and not _peut_gerer(itx, actif):
            log.warning("numgen: %s bloque pour %s dans #%s (numero de %s)", quoi,
                        getattr(getattr(itx, "user", None), "id", "?"),
                        getattr(ch, "name", "?"), actif.get("par"))
            await _ephemere(itx, "🔒 Ce numéro a été pris par <@%s> : lui seul (ou un "
                                 "admin) peut l'annuler ou le changer." % actif.get("par"))
            return
        log.info("numgen: %s par %s dans #%s", quoi,
                 getattr(getattr(itx, "user", None), "id", "?"), getattr(ch, "name", "?"))
        if quoi == "fini":
            if not rec.get("code_valeur") and _numero_vivant(actif):
                # « C'est bon » sans code, ce serait abandonner un numero paye
                # sans le rendre. Le bouton n'existe pas dans cet etat, mais un
                # clic croise (deux onglets) peut encore l'envoyer.
                log.warning("numgen: « C'est bon » ignore dans #%s : %s attend "
                            "encore son code", getattr(ch, "name", "?"),
                            actif.get("valeur"))
                await maj_panneau(self.bot, ch, cog=self)
                return
            _salon_ecrire(ch.id, actif=None, code_valeur=None)
            self._ecoute[ch.id] = self._ecoute.get(ch.id, 0) + 1
            await maj_panneau(self.bot, ch, cog=self)
            return
        if quoi == "retry":
            deja = rec.get("code_valeur")
            # D'ABORD regarder si le code est deja arrive. Il l'etait : visible
            # chez le fournisseur, absent du salon parce que l'ecoute avait
            # lache (un redemarrage du bot suffit). Redemander un SMS dans ce
            # cas fait perdre celui qu'on avait deja. Le code DEJA affiche ne
            # compte pas : « Nouveau code » en veut un autre.
            if sms:
                etat0, val0 = await asyncio.to_thread(
                    numgen.get_code, actif["id"], actif["provider"])
            else:
                etat0, val0 = await asyncio.to_thread(
                    numgen.get_mail_code, actif["id"], actif.get("stale", ""))
            if etat0 == "code" and val0 and val0 != deja:
                if sms:
                    await asyncio.to_thread(numgen.finish, actif["id"],
                                            actif["provider"])
                _salon_ecrire(ch.id, code_valeur=val0)
                await maj_panneau(self.bot, ch, cog=self)
                return
            if sms:
                ok, msg = await asyncio.to_thread(
                    numgen.retry, actif["id"], actif["provider"])
                if not ok:
                    log.warning("numgen: nouveau code refuse pour #%s : %s",
                                getattr(ch, "name", "?"), msg)
                    await maj_panneau(self.bot, ch, cog=self, souci="❌ %s" % msg)
                    return
            else:
                # Le prochain code du mail doit etre DIFFERENT de celui-ci.
                actif["stale"] = deja or actif.get("stale", "")
                _salon_ecrire(ch.id, actif=actif)
            _salon_ecrire(ch.id, code_valeur=None)
            await maj_panneau(self.bot, ch, cog=self)
            self._ecouter(ch)
            return
        # « Autre » et « Annuler » rendent le numero en cours : rembourse tant
        # qu'aucun code n'est arrive.
        rendu = None
        try:
            if sms:
                rendu = await asyncio.to_thread(numgen.cancel, actif["id"],
                                                actif["provider"])
            else:
                rendu = await asyncio.to_thread(numgen.mail_cancel, actif["id"])
        except Exception as e:                               # noqa: BLE001
            log.warning("numgen: %s dans #%s : rendu en echec (%s: %s)", quoi,
                        getattr(ch, "name", "?"), type(e).__name__, e)
        log.info("numgen: %s rendu dans #%s : %s", actif.get("valeur"),
                 getattr(ch, "name", "?"), rendu)
        trop_tot = numgen._MSG.get("EARLY_CANCEL_DENIED")
        if (sms and isinstance(rendu, tuple) and len(rendu) == 2 and not rendu[0]
                and rendu[1] == trop_tot and _numero_vivant(actif)):
            # Le fournisseur REFUSE de le reprendre si tot : l'effacer d'ici
            # laissait croire qu'il etait rendu, et « Autre » en payait un
            # second. Il reste affiche, avec la raison.
            await maj_panneau(self.bot, ch, cog=self, souci="❌ %s" % trop_tot)
            return
        _salon_ecrire(ch.id, actif=None, code_valeur=None)
        self._ecoute[ch.id] = self._ecoute.get(ch.id, 0) + 1
        if quoi == "autre":
            await self.nouvelle_activation(itx, "sms" if sms else "mail",
                                           actif.get("service", "ig"))
            return
        await maj_panneau(self.bot, ch, cog=self)

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
        description="[ADMIN] Poste ICI le panneau Numéro Instagram (ou le met à jour)")
    async def panelnumero(self, interaction: discord.Interaction):
        """Pose le panneau DANS LE SALON COURANT, quel que soit son nom.

        C est la voie sure : les commandes « all » cherchent des salons qui
        finissent par -numero-mail, et cette convention n existe que sur le
        serveur des tickets. Ailleurs le salon s appelle sms-email, ou
        autrement — 156 salons visibles et pas un seul qui matche. Ici, aucun
        filtre : le salon, c est celui ou l on est.

        Elle retire aussi les anciens panneaux EPINGLES d une AUTRE
        application. Le panneau pose avant que le cog ne demenage appartient a
        l autre bot et ne repond plus : sans ce nettoyage, on se retrouvait
        avec le neuf a cote du mort, identiques a l ecran. Les notres, eux,
        sont CONVERTIS sur place (poser_panneau) : le numero en cours y reste.
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
        moi = getattr(self.bot.user, "id", 0)
        orphelins = 0
        try:
            for p in await ch.pins():
                t = (p.embeds[0].title or "") if p.embeds else ""
                if (getattr(p.author, "bot", False) and p.author.id != moi
                        and any(k in t for k in TITRES_PANNEAU_ANCIEN)):
                    try:
                        await p.delete()
                        orphelins += 1
                    except Exception:
                        try:
                            await p.unpin()
                            orphelins += 1
                        except Exception as e:
                            log.warning(f"panelnumero: panneau orphelin {p.id} "
                                        f"de #{ch.name} ni supprime ni desepingle ({e})")
        except Exception as e:
            log.warning(f"panelnumero: nettoyage impossible ({e})")
        bilan = {}
        pose = await poser_panneau(self.bot, ch, self, menage=False, bilan=bilan)
        # Le salon ne garde QUE le panneau : tout autre message de bot part,
        # APRES la pose -- le panneau est converti sur place, pas repose, et
        # une purge d'abord l'emportait avec le numero qu'il affichait.
        vires = bilan.get("vires", 0)
        if pose:
            garde = _id_message(_salon(ch.id).get("panneau"))
            try:
                partis = await ch.purge(limit=300,
                                        check=lambda m: m.author.bot and m.id != garde)
                vires += len(partis)
            except Exception as e:
                log.warning(f"panelnumero: nettoyage de #{ch.name} : {e}")
        await verrouiller_salon(ch, self.bot)
        mot = ("✅ Panneau en place" if pose else
               "⚠️ Pose incomplète — regarde les droits du bot sur ce salon")
        if bilan.get("converti"):
            mot += " (converti au nouveau format)"
        if vires:
            mot += f" · {vires} ancien(s) message(s) de bot retiré(s)"
        if orphelins:
            mot += f" · {orphelins} ancien(s) panneau(x) retiré(s)"
        await interaction.followup.send(mot + ".", ephemeral=True)

    @app_commands.command(
        name="panelnumeroall",
        description="[ADMIN] Pose le panneau Numéro Instagram dans TOUS les salons -numero-mail")
    @app_commands.describe(
        remplacer="true = remet aussi à jour les panneaux déjà au nouveau format",
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
        from cogs.welcome import _us_norm
        targets = [c for c in guild.text_channels
                   if _us_norm(c.name).endswith("-numero-mail")]
        if not targets:
            await interaction.response.send_message(
                _pourquoi_aucun_salon(guild, self.bot, ("-numero-mail",)),
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        # Un seul releve du solde pour tous les salons : quarante releves,
        # c etait quatre-vingts appels au fournisseur pour la meme valeur.
        solde = await _solde_sms()
        ok = skipped = vides = convertis = 0
        for ch in targets:
            rec = _salon(ch.id)
            if (rec.get("v2") and _id_message(rec.get("panneau"))
                    and not (remplacer or nettoyer)):
                skipped += 1
                continue
            bilan = {}
            # Un salon a l ancien format est CONVERTI (le numero en cours
            # garde) ; un panneau deja au nouveau format est redessine.
            pose = await poser_panneau(self.bot, ch, self, solde=solde,
                                       menage=not nettoyer, bilan=bilan)
            if pose:
                ok += 1
                convertis += 1 if bilan.get("converti") else 0
            if nettoyer and pose:
                # Le salon ne doit contenir QUE le panneau. On efface ce que
                # les BOTS y ont pose — les deux applications, car l ancien
                # panneau vient de l autre — et on laisse les messages des
                # humains : ils sont irrecuperables, et personne n a demande
                # a les perdre. Le panneau, pose juste avant, est epargne.
                garde = _id_message(_salon(ch.id).get("panneau"))
                try:
                    partis = await ch.purge(limit=300,
                                            check=lambda m, g=garde: m.author.bot and m.id != g)
                    vides += len(partis)
                except Exception as e:
                    log.warning(f"panelnumeroall: nettoyage de #{ch.name} : {e}")
            await verrouiller_salon(ch, self.bot)
            await asyncio.sleep(0.6)
        s = numgen.status()
        warn = "" if (s["sms_ok"] and s["mail_ok"]) else (
            "\n⚠️ **Clés manquantes** — fais `/smskey getatext:… smsbower:…` "
            "sinon les boutons refuseront.")
        await interaction.followup.send(
            f"✅ Panneau posé dans **{ok}** salon(s)"
            + (f" dont {convertis} converti(s) au nouveau format" if convertis else "")
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

        async def _wipe(ch, titles, est=None):
            """Supprime les anciens panneaux epingles de ce salon.

            De N IMPORTE QUEL bot, pas seulement du notre. Le panneau pose
            avant que le cog ne demenage appartient a l AUTRE application :
            ses boutons ne trouvent plus personne et Discord repond « n a pas
            repondu a temps ». En ne nettoyant que nos propres messages, le
            reset laissait le cadavre epingle a cote du neuf — deux panneaux
            identiques a l ecran, dont un mort, et rien pour les distinguer.

            Le filet reste etroit : un message EPINGLE, d un BOT, dont le
            titre d embed est l un des notres -- ou que `est(message)`
            reconnait : le menu des models en « menus de 10 » (format V2)
            n a plus d embed ni de texte, seulement ses menus « jbus:ms: »
            (ou la ligne-marque de ceux deja postes). Une conversation ne
            peut pas tomber dedans.
            """
            try:
                for p in await ch.pins():
                    t = (p.embeds[0].title or "") if p.embeds else ""
                    if getattr(p.author, "bot", False) and (
                            any(k in t for k in titles)
                            or (est is not None and est(p))):
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
        # Le menu des models n est repose que par le bot qui a UserCog (le
        # principal) : _ensure_us_menu rend False partout ailleurs. Ce cog
        # vit sur le bot ADMIN -- effacer le menu ici, c etait laisser chaque
        # -menu sans menu (« 0/N » au bilan), et ses VA sans rien a cliquer.
        # On n efface donc que ce qu on peut reposer, et on le dit.
        menu_gere = self.bot.get_cog("UserCog") is not None
        if menu_gere:
            from cogs.user import _est_menu_models
            for ch in menus:
                # TOUS les formats : l ancien (titre d embed) et le V2 (ses
                # custom_id « jbus:ms: », ou « -# menu-models-… » pour ceux
                # deja postes), de n importe quel bot. Le panneau d actions
                # et le ✨ General n en sont jamais (_est_menu_models).
                await _wipe(ch, ("Jailbreak US", "Menu Jailbreak"),
                            est=_est_menu_models)
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
        ligne_menu = (
            f"• 🔓 Menu Jailbreak US : **{n_menu}**/{len(menus)} salon(s) `-menu`\n"
            if menu_gere else
            f"• 🔓 Menu Jailbreak US : **non touché** dans {len(menus)} salon(s) "
            "`-menu` — ce bot ne sait pas le reposer ; `/resetmenus` sur le bot "
            "principal le remet à neuf\n")
        await interaction.followup.send(
            f"♻️ **Reset des panneaux terminé**\n"
            + ligne_menu +
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
        description="Solde des générateurs (GetAText, SMSBower, SMSPool)")
    async def soldes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        b = await asyncio.to_thread(numgen.balances)
        await interaction.followup.send(
            "💰 **Soldes**\n"
            f"• 📱 Numéros (GetAText) : **{b['sms']}**\n"
            f"• 📧 Mails (SMSBower) : **{b['mail']}**\n"
            f"• 🏊 SMSPool : **{b.get('smspool', '—')}**", ephemeral=True)


class _KeysModal(discord.ui.Modal, title="🔑 Clés des générateurs"):
    getatext = discord.ui.TextInput(
        label="Clé GetAText (numéros)", required=False, max_length=120,
        placeholder="laisse vide pour ne pas changer")
    smsbower = discord.ui.TextInput(
        label="Clé SMSBower (mails)", required=False, max_length=120,
        placeholder="laisse vide pour ne pas changer")
    smspool = discord.ui.TextInput(
        label="Clé SMSPool (solde seul)", required=False, max_length=120,
        placeholder="laisse vide pour ne pas changer")
    pays = discord.ui.TextInput(
        label="Pays par défaut (0 = RU, 187 = USA)", required=False, max_length=6,
        placeholder="187")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        s = await asyncio.to_thread(
            functools.partial(
                numgen.set_keys,
                str(self.getatext.value).strip() or None,
                str(self.smsbower.value).strip() or None,
                str(self.pays.value).strip() or None,
                smspool=str(self.smspool.value).strip() or None))
        b = await asyncio.to_thread(numgen.balances)
        await interaction.followup.send(
            f"✅ **Enregistré**\n"
            f"• 📱 GetAText : {s['getatext'] or '❌ absente'} — solde **{b['sms']}**\n"
            f"• 📧 SMSBower : {s['smsbower'] or '❌ absente'} — solde **{b['mail']}**\n"
            f"• 🏊 SMSPool : {s.get('smspool') or '❌ absente'} — solde **{b.get('smspool', '—')}**\n"
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


# ==============================================================================
# LE PANNEAU : un seul message par salon
# ==============================================================================
# Le salon d'un VA porte UN message, et rien d'autre. Il n'est jamais
# supprime ni repose : son CONTENU change (vide, en attente, code recu).
#
# Avant le 27/09/2026, c'etait TROIS messages epingles (panneau, numero,
# code) ; avant encore, chaque clic ouvrait un message EPHEMERE qu'un
# rechargement faisait disparaitre. On garde ce qui a marche -- un ecran fixe
# qui se met a jour tout seul, comme une page web -- en un seul message, sans
# epingle : le proprietaire deteste la notice « a epingle un message ».

SALONS_FILE = _Path("data") / "numgen_salons.json"


def _salons() -> dict:
    d = _safe_json.load(SALONS_FILE, default={})
    return d if isinstance(d, dict) else {}


def _salon(cid) -> dict:
    return _salons().get(str(cid)) or {}


def _id_message(v):
    """L'identifiant d'un message Discord, ou None.

    Le champ « code » d'un salon a longtemps servi a DEUX choses : l'id du
    message « Code » ET le code recu (« 546451 »). Des qu'un numero etait
    pris, l'id etait efface ; a l'arrivee du SMS, le code prenait sa place et
    le bot editait un message inexistant — le code n'apparaissait JAMAIS dans
    le salon (27/09/2026). Le code vit maintenant dans « code_valeur » ; un
    ancien « code » qui n'a pas la taille d'un identifiant Discord est ignore.
    """
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 10 ** 15 else None


def _salon_ecrire(cid, **champs):
    """Ecrit les champs d'un salon. `actif=None` efface l'activation."""
    d = _salons()
    rec = dict(d.get(str(cid)) or {})
    rec.update(champs)
    d[str(cid)] = rec
    SALONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _safe_json.write(SALONS_FILE, d, indent=2)
    return rec


#: Duree de vie d'un numero chez le fournisseur : au-dela, il ne recevra
#: plus de code et ne doit plus bloquer le salon.
DUREE_NUMERO_SEC = 20 * 60


def _numero_vivant(actif) -> bool:
    """Un numero qui peut encore recevoir son code. Ceux d'avant le
    27/09/2026 n'ont pas d'heure : ils sont vieux de plusieurs jours (douze
    salons en gardaient un du 22/09), donc morts."""
    import time as _t
    try:
        return _t.time() - float((actif or {}).get("pris_le") or 0) < DUREE_NUMERO_SEC
    except (TypeError, ValueError):
        return False


def _peut_gerer(itx, actif) -> bool:
    """Seul celui qui a pris le numero -- ou un admin -- peut l'annuler ou
    le remplacer. Le 27/09/2026, dans un salon partage, un autre membre a
    annule deux numeros en quelques secondes : « ca l'efface cash »."""
    par = (actif or {}).get("par")
    uid = getattr(getattr(itx, "user", None), "id", None)
    if not par or uid == par:
        return True
    try:
        from cogs.user import _is_staff_member
        return bool(_is_staff_member(itx.user))
    except Exception:                                        # noqa: BLE001
        return False


class _ConfirmerView(discord.ui.View):
    """« Oui, annuler » : un clic de travers ne rend plus un numero."""

    def __init__(self, cog, quoi):
        super().__init__(timeout=60)
        self.cog, self.quoi = cog, quoi

    @discord.ui.button(label="Oui", emoji="✅", style=discord.ButtonStyle.danger)
    async def oui(self, itx: discord.Interaction, btn: discord.ui.Button):
        self.stop()
        await itx.response.edit_message(content="👌", view=None)
        await self.cog.action_salon(itx, self.quoi)

    @discord.ui.button(label="Non", style=discord.ButtonStyle.secondary)
    async def non(self, itx: discord.Interaction, btn: discord.ui.Button):
        self.stop()
        await itx.response.edit_message(content="Rien n'a changé.", view=None)


async def _confirmer_ou_refuser(itx, cog, quoi) -> bool:
    """Pour « Autre » et « Annuler » : refus si le numero est a quelqu'un
    d'autre, sinon une confirmation visible du seul cliqueur.

    Rend True quand il n'y a RIEN a confirmer (aucun numero en cours) : le
    clic est alors differe, et l'appelant redessine le panneau."""
    ch = getattr(itx, "channel", None)
    actif = _salon(getattr(ch, "id", 0)).get("actif") if ch else None
    if not actif:
        await itx.response.defer()
        return True
    if not _peut_gerer(itx, actif):
        log.info("numgen: %s refuse a %s (numero de %s) dans #%s", quoi,
                 getattr(itx.user, "id", "?"), actif.get("par"), getattr(ch, "name", "?"))
        await itx.response.send_message(
            "🔒 Ce numéro a été pris par <@%s> : lui seul (ou un admin) peut "
            "l'annuler ou le changer." % actif.get("par"),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return False
    autre = "numéro" if actif.get("kind") != "mail" else "mail"
    question = ("Annuler `%s` ?" if quoi == "annuler"
                else "Changer `%s` pour un autre " + autre + " ?")
    await itx.response.send_message(question % actif.get("valeur", "?"),
                                    view=_ConfirmerView(cog, quoi), ephemeral=True)
    return False


async def _ephemere(itx, texte):
    """Un mot au seul cliqueur, que le clic ait deja recu sa reponse ou non.
    Un mot qui ne part pas va au journal : jamais de refus muet."""
    try:
        if itx.response.is_done():
            await itx.followup.send(texte, ephemeral=True,
                                    allowed_mentions=discord.AllowedMentions.none())
        else:
            await itx.response.send_message(
                texte, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: message ephemere non remis (%s: %s) : %s",
                    type(e).__name__, e, str(texte)[:160])


# ---- Le message V2 -----------------------------------------------------------

_ICONE = _Path(__file__).resolve().parent.parent / "emojis" / "numero_instagram.png"
_ICONE_NOM = "numero_instagram.png"
#: Le rose Instagram de la maquette validee.
_ROSE = 0xE1306C

#: Les boutons que portent les panneaux d'AVANT (embed « Numéros & Mails »).
#: Un message Discord ne se redessine pas : ceux-la restent cliquables tant
#: que le salon n'est pas converti, et le filet du bot principal
#: (cogs/general.py, PanneauPerime) doit tous les couvrir.
IDS_PANNEAU_ANCIEN = ("numgen:sms", "numgen:mail", "numgen:other")

#: Les titres d'embed du panneau d'avant : le libelle a change en cours de
#: route, et chercher le seul ancien laissait passer le nouveau.
TITRES_PANNEAU_ANCIEN = ("Numéros & Mails", "Numéro & Mail")

#: Le dernier solde SMS lu. « Recherche d'un numero… » s'affiche AVANT
#: l'achat : relire le solde a ce moment-la retardait l'achat d'autant.
_DERNIER_SOLDE = {"sms": None}


def _fichier_icone():
    """L'icone a joindre, neuve a chaque envoi (un discord.File ne se lit
    qu'une fois), ou None si le fichier manque -- le panneau part alors sans
    vignette plutot que pas du tout, et le journal le dit."""
    if not _ICONE.exists():
        log.warning("numgen: icone absente (%s) : panneau sans vignette", _ICONE)
        return None
    return discord.File(str(_ICONE), filename=_ICONE_NOM)


async def _solde_sms():
    """Le solde SMS a afficher ; en cas d'echec, le dernier connu."""
    try:
        v = (await asyncio.to_thread(numgen.balances)).get("sms")
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: solde illisible (%s: %s)", type(e).__name__, e)
        return _DERNIER_SOLDE["sms"]
    _DERNIER_SOLDE["sms"] = v
    return v


def _solde_affiche(solde) -> str:
    """« 99.94 $ » -> « 99,94 $ », comme la maquette ; « — » si inconnu."""
    s = " ".join(str(solde or "").split())
    if not s:
        return "—"
    m = re.fullmatch(r"(\d+)\.(\d+)( ?\$)", s)
    return ("%s,%s%s" % m.groups()) if m else _ligne_courte(s, 60)


def _ligne_courte(texte, n=150) -> str:
    """UNE ligne courte : un souci ne doit pas repousser le reste du panneau."""
    t = " ".join(str(texte or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _drapeau(actif) -> str:
    """🇺🇸 (le drapeau du pays du numero), ou 📧 pour un mail."""
    if (actif or {}).get("kind") == "mail":
        return "📧"
    tete = str((actif or {}).get("pays_nom") or "").split(" ", 1)[0]
    if tete and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in tete):
        return tete
    return "📱"


def _a_afficher(rec):
    """(actif, code) a montrer. Un numero MORT (plus de 20 min sans code) ne
    s'affiche plus : il ne recevra plus rien, et il cachait « Prendre un
    numero » -- douze salons gardaient un numero du 22/09."""
    actif = (rec or {}).get("actif")
    code = (rec or {}).get("code_valeur")
    if not actif:
        return None, None
    if code:
        return actif, code
    return (actif, None) if _numero_vivant(actif) else (None, None)


def _boutons_etat(etat):
    """(action, libelle, emoji, style) de chaque bouton d'un etat, dans
    l'ordre de la maquette. Le custom_id est « numgen:<action> » : ceux qui
    existaient deja sont gardes (retry, autre, annuler, sms, mail), pour que
    les messages d'avant repondent encore."""
    B = discord.ButtonStyle
    if etat == "vide":
        return (("sms", "Prendre un numéro", "📱", B.success),
                ("mail", "Mail", "📧", B.secondary))
    if etat == "attente":
        return (("retry", "Redemander un code", "🔄", B.primary),
                ("autre", "Autre", "🔁", B.secondary),
                ("annuler", "Annuler", "❌", B.danger))
    return (("fini", "C'est bon", "✅", B.success),
            ("retry", "Nouveau code", "🔄", B.primary),
            ("autre", "Autre", "🔁", B.secondary))


class _BoutonNum(discord.ui.Button):
    """Un bouton du panneau. Le clic ne lit RIEN dans la vue : l'etat vit
    dans data/numgen_salons.json. Apres un redemarrage, c'est la vue neuve
    de cog_load qui recoit le clic, et elle n'a rien a savoir du salon."""

    def __init__(self, cog, action, label, emoji, style):
        super().__init__(label=label, emoji=emoji, style=style,
                         custom_id="numgen:" + action)
        self.cog, self.action = cog, action

    async def callback(self, itx: discord.Interaction):
        cog = self.cog or itx.client.get_cog("NumerosCog")
        if cog is None:
            raise RuntimeError("NumerosCog absent de ce bot")
        await cog.clic(itx, self.action)


class PanneauNumero(discord.ui.LayoutView):
    """Le panneau « Numéro Instagram » : UN message Components V2.

    Conteneur rose, une section (texte + l'icone en vignette), une rangee
    de boutons. `tous=True` : la vue d'enregistrement de cog_load, qui porte
    les six boutons pour qu'un clic sur n'importe quel etat trouve son
    repondant apres un redemarrage ; elle n'est jamais envoyee.
    """

    def __init__(self, cog=None, actif=None, code=None, solde=None, souci="",
                 icone=None, tous=False):
        super().__init__(timeout=None)
        self.cog = cog
        self.icone = _ICONE.exists() if icone is None else bool(icone)
        ui = discord.ui
        if tous:
            boutons, vus = [], set()
            for etat in ("vide", "attente", "code"):
                for b in _boutons_etat(etat):
                    if b[0] not in vus:
                        vus.add(b[0])
                        boutons.append(_BoutonNum(cog, *b))
            self.etat = "tous"
            self.add_item(ui.Container(ui.ActionRow(*boutons[:5]),
                                       ui.ActionRow(*boutons[5:]),
                                       accent_colour=_ROSE))
            return
        etat = "vide" if not actif else ("code" if code else "attente")
        self.etat = etat
        if etat == "vide":
            lignes = ["## Numéro Instagram", "-# 💵 " + _solde_affiche(solde)]
        else:
            # Le numero COLLE, sans espaces : demande expresse du proprietaire.
            valeur = "".join(str(actif.get("valeur") or "?").split())
            ligne = ("⏳ En attente du code…" if etat == "attente"
                     else "🔑 **Code : `%s`**" % code)
            lignes = ["## `%s`" % valeur, _drapeau(actif) + " " + ligne]
        if souci:
            lignes.append(_ligne_courte(souci))
        textes = [ui.TextDisplay(t) for t in lignes]
        rangee = ui.ActionRow(*[_BoutonNum(cog, *b) for b in _boutons_etat(etat)])
        if self.icone:
            tete = ui.Section(*textes,
                              accessory=ui.Thumbnail("attachment://" + _ICONE_NOM))
            self.add_item(ui.Container(tete, rangee, accent_colour=_ROSE))
        else:
            self.add_item(ui.Container(*textes, rangee, accent_colour=_ROSE))

    async def on_error(self, itx: discord.Interaction, error: Exception, item):
        # 27/09/2026 : « ca ne marche pas » sans une ligne dans le journal. Une
        # exception dans un bouton restait invisible des deux cotes : on la
        # journalise, et le VA la lit au lieu d un bouton muet.
        log.exception("numgen: erreur au clic %s dans #%s",
                      getattr(item, "custom_id", "?"),
                      getattr(getattr(itx, "channel", None), "name", "?"),
                      exc_info=error)
        await _ephemere(itx, "❌ Erreur : %s" % (str(error)[:300] or type(error).__name__))


def est_panneau_numero(m, moi=None):
    """« v2 », « ancien » ou None : ce message est-il le panneau numero ?

      - v2 : un message Components V2 qui porte un bouton « numgen: » ;
      - ancien : l'embed « Numéros & Mails » (ou son premier libelle).
    L'ancien message « Numero » (embed « 📱 Numéro », boutons numgen:retry…)
    n'en est PAS un : il part a la conversion. Toute recherche du panneau
    (welcome, /panelnumero, la conversion au clic) passe par ici : deux
    reperages finiraient par ne plus reconnaitre la meme chose.

    `moi` : l'id du bot ; donne, un message d'un autre auteur ne compte
    jamais (on ne peut pas modifier le message d'une autre application).
    Ne leve jamais."""
    try:
        if m is None:
            return None
        auteur = getattr(m, "author", None)
        if moi is not None and getattr(auteur, "id", None) != moi:
            return None
        if not getattr(auteur, "bot", False):
            return None
        # Un message ephemere (la maquette /demonumero, une confirmation) n'est
        # pas dans le salon : l'adopter comme panneau le perdrait au rechargement.
        if getattr(getattr(m, "flags", None), "ephemeral", False):
            return None
        if getattr(getattr(m, "flags", None), "components_v2", False):
            from cogs.user import _ids_composants
            if any(str(c).startswith("numgen:") for c in _ids_composants(m)):
                return "v2"
            return None
        emb = getattr(m, "embeds", None) or []
        titre = (getattr(emb[0], "title", None) or "") if emb else ""
        if any(k in titre for k in TITRES_PANNEAU_ANCIEN):
            return "ancien"
        return None
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: message %s illisible (%s: %s)",
                    getattr(m, "id", "?"), type(e).__name__, e)
        return None


async def _chercher_panneau(channel, moi):
    """Le panneau deja la, quand le registre ne le connait pas (data/ reparti
    de zero) : dans les epingles (l'ancien l'etait) puis l'historique. Un
    panneau V2 passe avant un ancien."""
    vus = []
    try:
        vus.extend(await channel.pins())
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: epingles de #%s illisibles (%s: %s)",
                    getattr(channel, "name", "?"), type(e).__name__, e)
    try:
        async for m in channel.history(limit=50):
            vus.append(m)
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: historique de #%s illisible (%s: %s)",
                    getattr(channel, "name", "?"), type(e).__name__, e)
    for voulu in ("v2", "ancien"):
        for m in vus:
            if est_panneau_numero(m, moi) == voulu:
                return m
    return None


async def _vue_salon(cog, rec, souci="", solde=None):
    actif, code = _a_afficher(rec)
    if not actif and solde is None:
        solde = await _solde_sms()
    return PanneauNumero(cog, actif=actif, code=code, solde=solde, souci=souci)


async def _editer_v2(channel, mid, vue, joindre=False):
    """Edite le panneau V2 SANS le relire : un fetch qui echoue une seconde
    -- une limite d'API suffit -- faisait croire le message disparu, et un
    second etait poste. La piece jointe deja la est gardee (la vignette la
    vise par son nom) ; `joindre` la renvoie."""
    kw = {"view": vue}
    if joindre:
        f = _fichier_icone()
        if f is not None:
            kw["attachments"] = [f]
    await channel.get_partial_message(int(mid)).edit(**kw)


async def poser_panneau(bot, channel, cog=None, vu=None, souci="", solde=None,
                        menage=True, bilan=None):
    """Garantit LE panneau du salon, au format V2, et retient son identifiant.

    Idempotent : le panneau deja la est MIS A JOUR, jamais double. Il est
    pris, dans l'ordre : le message clique s'il est un panneau V2 (`vu`), le
    message enregistre, le message clique s'il est un ancien panneau, sinon
    celui que _chercher_panneau retrouve ; a defaut, un neuf est poste.

    Un ancien panneau (embed) est CONVERTI par edition : texte et embed
    retires, la vue V2 et l'icone jointe. Si Discord refuse, un nouveau
    message est poste et l'ancien supprime. Les anciens messages « Numero »
    et « Code » du bot sont supprimes ; le numero en cours, qui vit dans le
    registre, s'affiche dans le panneau. `menage` : tout autre message de
    bot du salon part aussi (jamais un message d'humain).

    `bilan` (dict, facultatif) recoit converti / poste / vires.
    """
    bilan = {} if bilan is None else bilan
    bilan.setdefault("vires", 0)
    if bot is None or channel is None:
        return False
    nom = getattr(channel, "name", "?")
    cog = cog or bot.get_cog("NumerosCog")
    if cog is None:
        log.warning("numgen: panneau de #%s non pose : NumerosCog absent de ce bot", nom)
        return False
    moi = getattr(getattr(bot, "user", None), "id", None)
    rec = _salon(channel.id)
    enregistre = _id_message(rec.get("panneau"))
    format_vu = est_panneau_numero(vu, moi) if vu is not None else None
    cible, fmt = None, None
    if format_vu == "v2":
        cible, fmt = vu.id, "v2"
    elif enregistre:
        cible, fmt = enregistre, ("v2" if rec.get("v2") else "ancien")
    elif format_vu == "ancien":
        cible, fmt = vu.id, "ancien"
    else:
        trouve = await _chercher_panneau(channel, moi)
        if trouve is not None:
            cible, fmt = trouve.id, est_panneau_numero(trouve, moi)
            log.info("numgen: panneau %s (%s) retrouve dans #%s hors registre",
                     cible, fmt, nom)
    a_virer = set()
    if enregistre and enregistre != cible:
        a_virer.add(enregistre)          # un panneau en double : le clique l'emporte
    for cle in ("numero", "code"):
        x = _id_message(rec.get(cle))
        if x:
            a_virer.add(x)
    vue = await _vue_salon(cog, rec, souci, solde)
    pose = None
    if cible:
        try:
            if fmt == "v2":
                try:
                    await _editer_v2(channel, cible, vue)
                except discord.NotFound:
                    raise
                except Exception as e1:                      # noqa: BLE001
                    if not vue.icone:
                        raise
                    # Une vignette dont la piece jointe manque est refusee :
                    # on la renvoie, une fois.
                    log.warning("numgen: panneau de #%s refuse (%s: %s) : nouvel "
                                "essai avec l'icone jointe", nom, type(e1).__name__, e1)
                    await _editer_v2(channel, cible, vue, joindre=True)
            else:
                kw = {"content": None, "embed": None, "view": vue}
                f = _fichier_icone() if vue.icone else None
                if f is not None:
                    kw["attachments"] = [f]
                await channel.get_partial_message(int(cible)).edit(**kw)
                bilan["converti"] = True
                log.info("numgen: panneau de #%s converti au format V2 (message %s)",
                         nom, cible)
            pose = int(cible)
        except discord.NotFound:
            log.info("numgen: panneau %s de #%s introuvable : un neuf est pose",
                     cible, nom)
        except Exception as e:                               # noqa: BLE001
            if fmt == "v2":
                # Reseau, limite d'API... : le panneau est la, et en poster un
                # second, c'est le doublon constate avant. On reessaiera.
                log.warning("numgen: panneau %s de #%s non modifiable (%s: %s) — "
                            "rien n'est reposte", cible, nom, type(e).__name__, e)
                return False
            log.warning("numgen: conversion refusee dans #%s (%s: %s) : nouveau "
                        "message, l'ancien supprime", nom, type(e).__name__, e)
            a_virer.add(int(cible))
    if pose is None:
        kw = {"view": vue}
        f = _fichier_icone() if vue.icone else None
        if f is not None:
            kw["file"] = f
        try:
            nouveau = await channel.send(**kw)
        except Exception as e:                               # noqa: BLE001
            log.warning("numgen: panneau impossible a poser dans #%s (%s: %s)",
                        nom, type(e).__name__, e)
            return False
        pose = nouveau.id
        bilan["poste"] = True
        log.info("numgen: panneau pose dans #%s (message %s)", nom, pose)
    a_virer.discard(pose)
    restants = set()
    for mid in sorted(a_virer):
        try:
            await channel.get_partial_message(mid).delete()
            bilan["vires"] += 1
            await asyncio.sleep(0.3)
        except discord.NotFound:
            pass
        except Exception as e:                               # noqa: BLE001
            log.warning("numgen: ancien message %s de #%s non supprime (%s: %s)",
                        mid, nom, type(e).__name__, e)
            restants.add(mid)
    champs = {"panneau": pose, "v2": True, "icone": vue.icone}
    for cle in ("numero", "code"):
        # Un ancien message qu'on n'a pas pu supprimer reste au registre : la
        # prochaine pose reessaiera. « code » a longtemps porte une VALEUR de
        # code (« 546451 ») : elle n'est l'id de rien, elle part.
        x = _id_message(rec.get(cle))
        champs[cle] = x if x in restants else None
    _salon_ecrire(channel.id, **champs)

    # UN message, jamais deux. Tout message de bot qui n'est pas le panneau
    # est supprime -- les anciens « Numero »/« Code » qu'aucun registre ne
    # connait plus, le panneau mort de l'autre application, les notices
    # d'epinglage. Les messages des humains ne sont pas touches.
    if menage:
        vires = 0
        try:
            async for vieux in channel.history(limit=100):
                if getattr(vieux.author, "bot", False) and vieux.id != pose:
                    try:
                        await vieux.delete()
                        vires += 1
                        await asyncio.sleep(0.3)
                    except Exception as e:                   # noqa: BLE001
                        log.warning("numgen: message %s de #%s non supprime (%s: %s)",
                                    getattr(vieux, "id", "?"), nom,
                                    type(e).__name__, e)
        except Exception as e:                               # noqa: BLE001
            log.warning("numgen: menage de #%s : %s", nom, e)
        if vires:
            bilan["vires"] += vires
            log.info("numgen: %d message(s) de bot en trop retire(s) de #%s",
                     vires, nom)
    return True


async def maj_panneau(bot, channel, souci="", solde=None, cog=None) -> bool:
    """Redessine le panneau d'apres le registre (numero, code) ; `souci` :
    une ligne « ❌ … » en plus, le reste inchange.

    Rend True si le panneau est REELLEMENT a jour : un numero achete et
    jamais montre, c'est de l'argent perdu en silence. Un salon sans panneau
    V2 (ancien format, message disparu) passe par poser_panneau.
    """
    if bot is None or channel is None:
        return False
    cog = cog or bot.get_cog("NumerosCog")
    nom = getattr(channel, "name", "?")
    rec = _salon(channel.id)
    mid = _id_message(rec.get("panneau"))
    if not mid or not rec.get("v2"):
        return await poser_panneau(bot, channel, cog, souci=souci, solde=solde)
    vue = await _vue_salon(cog, rec, souci, solde)
    joindre = bool(vue.icone and not rec.get("icone", True))
    try:
        await _editer_v2(channel, mid, vue, joindre)
    except discord.NotFound:
        log.warning("numgen: panneau %s de #%s disparu : on le repose", mid, nom)
        _salon_ecrire(channel.id, panneau=None, v2=None)
        return await poser_panneau(bot, channel, cog, souci=souci, solde=solde)
    except Exception as e:                                   # noqa: BLE001
        if joindre or not vue.icone:
            log.warning("numgen: panneau de #%s non mis a jour (%s: %s)",
                        nom, type(e).__name__, e)
            return False
        # La piece jointe a pu partir (retiree a la main) : une vignette qui
        # vise un fichier absent est refusee. On la renvoie, une fois.
        try:
            await _editer_v2(channel, mid, vue, joindre=True)
            joindre = True
        except Exception as e2:                              # noqa: BLE001
            log.warning("numgen: panneau de #%s non mis a jour (%s: %s, puis %s: %s)",
                        nom, type(e).__name__, e, type(e2).__name__, e2)
            return False
    if joindre:
        _salon_ecrire(channel.id, icone=True)
    return True


async def verrouiller_salon(channel, bot):
    """Le salon devient une vitrine : seul le bot y ecrit.

    Le VA garde la LECTURE et les boutons — une interaction n'est pas un
    message. Sans ca, un salon qui ne doit contenir que le panneau se
    remplissait de conversations, et le panneau se retrouvait en haut,
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
