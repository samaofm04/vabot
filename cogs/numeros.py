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

Chaque activation est aussi notée dans data/numgen_historique.json (prise,
code, annulation, « Autre »…). Le récap du jour vit dans « 📊・debrief-day » :
UN message par jour (heure du Bénin), créé dès minuit sur un serveur qui a un
panneau numéros et un debrief-day (« Pas de SMS pour le moment. »), ailleurs
au premier numéro ; édité au fil des événements (une édition par minute au
plus), puis figé à minuit en récap final par édition du même message
(`recap_tour`).
"""
import asyncio
import functools
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

import numgen
import safe_json as _safe_json
from pathlib import Path as _Path

log = logging.getLogger("vabot.numeros")

POLL_SECONDS = 5
POLL_MAX = 180          # 3 min au rythme de POLL_SECONDS...
#: ... puis une lecture toutes les POLL_LENT secondes, jusqu'a la fin de vie
#: du numero (DUREE_NUMERO_SEC). L'ecoute s'arretait a 3 min alors que le
#: numero vit 20 min : un VA qui tape le numero a la main demandait le SMS
#: plus tard, le code arrivait et ne s'affichait plus ; il cliquait « Autre »
#: et payait un second numero (relecture du 27/09/2026).
POLL_LENT = 15
#: Erreurs PASSAGERES d'affilee (timeout « ERR:… », page HTML d'un 502)
#: avant d'abandonner l'ecoute. Une seule suffisait : le SMS arrive juste
#: apres n'etait jamais affiche.
ECOUTE_ERREURS_MAX = 5
#: Un numero que le fournisseur refuse de reprendre est retente plus tard :
#: GetAText n'accepte pas d'annulation dans les ~2 premieres minutes
#: (EARLY_CANCEL_DENIED), et c'est justement la qu'un panneau inaffichable
#: le rend.
RENDU_DIFFERE_SEC = 125
RENDU_ESSAIS = 3
#: Essais d'affichage d'un code recu, et leur ecart. Un seul essai (dont le
#: resultat n'etait meme pas lu) : une edition refusee (503, coupure)
#: laissait « En attente du code… » avec le code au registre, jamais montre.
AFFICHAGE_ESSAIS = 3
AFFICHAGE_PAUSE_SEC = 5
#: Fenetre de recherche du panneau dans l'historique, et du menage de ses
#: doubles : le V2 n'est plus epingle, et un salon ou le VA a ecrit plus de
#: 50 messages recevait un second panneau.
FENETRE_PANNEAU = 200


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
        # Heure de prise (la vue nait avec le numero) : au-dela de
        # DUREE_NUMERO_SEC il est mort, un refus de rendu ne bloque plus.
        self.pris_le = time.time()
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

    async def _rendre_ici(self):
        """(on_peut_continuer, message) apres la tentative de rendu.

        Le retour de numgen.cancel / mail_cancel etait jete : un clic dans
        les ~2 premieres minutes recevait EARLY_CANCEL_DENIED, « Autre
        numéro » en achetait un second quand meme, et le premier restait
        actif, paye, connu de personne. Meme regle que le panneau : on ne
        continue que si le fournisseur a repris le numero, s'il n'y a plus
        rien a rendre (code deja recu, numero expire, activation inconnue)."""
        ok, raison = await _rendre({"id": self.act_id, "kind": self.kind,
                                    "provider": self.provider, "valeur": self.value},
                                   "ephemere")
        vivant = time.time() - self.pris_le < DUREE_NUMERO_SEC
        if ok:
            return True, "remboursé"
        if self.code:
            return True, "code déjà reçu : rien à rembourser"
        if not vivant or _rendu_inutile(raison):
            return True, "déjà clos chez le fournisseur"
        log.warning("numgen: %s (vue ephemere) garde : rendu refuse (%s)", self.value, raison)
        return False, raison

    @discord.ui.button(label="Autre numéro", emoji="🔁",
                       style=discord.ButtonStyle.secondary)
    async def other_one(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True, thinking=True)
        # on rend l'actuel (remboursé si aucun code) puis on en reprend un --
        # seulement si le rendu a reussi : sinon le VA garde CE numero.
        continuer, mot = await self._rendre_ici()
        if not continuer:
            await itx.followup.send(f"❌ {mot}", ephemeral=True)
            return
        histo_evenement(self.kind, self.act_id, "remplace")
        self.stop()
        if self.kind == "sms":
            await self.cog.start_sms(itx, self.service)
        else:
            await self.cog.start_mail(itx, self.service)

    @discord.ui.button(label="Annuler", emoji="❌", style=discord.ButtonStyle.danger)
    async def stop_it(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.defer(ephemeral=True, thinking=True)
        continuer, mot = await self._rendre_ici()
        if not continuer:
            # « annulé (remboursé…) » s'affichait alors que le fournisseur
            # refusait : la vue reste active, le VA peut reessayer.
            await itx.followup.send(f"❌ {mot}", ephemeral=True)
            return
        histo_evenement(self.kind, self.act_id, "annule")
        self.stop()
        await itx.followup.send(f"❌ **{self.value}** annulé — {mot}.", ephemeral=True)


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
        # Reprise des ecoutes apres un redemarrage : une seule fois par
        # processus (on_ready revient a chaque reconnexion complete).
        self._repris = False
        # Le recap quotidien (« debrief-day ») : une boucle par processus.
        # _recap_postes garde en memoire ce qui est parti ({(jour, serveur):
        # fiche}) -- si le registre ne peut pas s'ecrire, la boucle ne le
        # reposte pas chaque minute, et le lui redonne des qu'il s'ecrit.
        # _recap_dits : un souci (pas de salon, envoi refuse) se dit UNE fois,
        # pas a chaque tour.
        self._recap_tache = None
        self._recap_arme = False
        self._recap_postes = {}
        self._recap_dits = set()
        # Le message « en direct » du jour. _recap_signes : le texte (sans
        # l'heure) de chaque message tel qu'envoye -- un tour sans nouveau
        # chiffre n'edite rien. _direct_gen : la generation de l'historique a
        # la derniere lecture ; None au demarrage, pour que le premier tour
        # remette le jour a jour (evenements du temps de l'arret).
        # _direct_edite_le : la derniere edition, pour n'en faire qu'une par
        # minute. _direct_expire_le : le prochain numero a expirer, qui change
        # le texte sans aucun evenement. _direct_a_refaire : une edition a
        # echoue, elle repart au tour suivant.
        self._recap_signes = {}
        self._direct_gen = None
        self._direct_edite_le = 0.0
        self._direct_expire_le = None
        self._direct_a_refaire = False
        # _direct_agg : (jour, generation, bilan du jour) de la derniere
        # lecture de l'historique. Un tour reveille seulement parce qu'un
        # serveur n'a pas son message a 0 (envoi refuse, retente chaque minute)
        # le reprend : sans ca, il relisait tout l'historique (plusieurs Mo)
        # chaque minute, toute la journee.
        # _recap_absents : (jour, salon) ou _retrouver a deja lu le salon sans
        # y trouver de recap -- ce processus sait ce qu'il y poste ensuite, le
        # relire a chaque essai refuse etait un appel Discord par minute. Une
        # lecture refusee net (salon prive, 403) y est notee aussi. Un envoi
        # sans reponse nette (connexion coupee, 5xx) l'efface : le message a
        # pu partir quand meme (_refus_net).
        self._direct_agg = None
        self._recap_absents = set()
        # _relire_apres : {salon: (instant, pause)} -- lecture ratee sans refus
        # net : un message a 0 ne relit pas ce salon avant l'instant (pause
        # doublee a chaque echec, RECAP_RELIRE_MAX_SEC au plus).
        # _recap_incertains : (jour, salon) d'un envoi sans reponse nette, pas
        # encore tranche (message retrouve, ou envoi abouti) -- aussi au
        # registre (« incertains ») : un redemarrage juste apres la reponse
        # perdue l'oubliait, et la relecture ratee du tour suivant faisait un
        # second message. _registre_neuf_le : le jour ou ce processus a trouve
        # le registre sans « jours » (perdu, ou premiere mise en route). Dans
        # ces deux cas seulement, un message du jour est peut-etre deja dans
        # le salon sans que rien ne le dise : un message a 0 n'y part pas sur
        # une lecture ratee.
        # _recap_connus : {serveur: du recap ?} vu DISPONIBLE dans ce
        # processus -- un serveur « unavailable » que l'on sait hors du recap
        # n'est pas cherche a minuit (trace « a_chercher » pour un serveur
        # sans debrief-day, et journee tenue ouverte tant qu'il manquait).
        # _figer_aggs : {jour: (generation, bilan)} des journees finies --
        # une journee que seul un essai rate tient ouverte (serveur
        # indisponible, salon illisible) ne relit pas l'historique a chaque
        # tour tant qu'il n'a pas bouge (178 lectures sur une panne de 3 h).
        self._relire_apres = {}
        self._recap_incertains = set()
        self._registre_neuf_le = None
        self._recap_connus = {}
        self._figer_aggs = {}
        self._reveil = None
        self._reveil_boucle = None

    async def cog_unload(self):
        t = self._recap_tache
        if t is not None and hasattr(t, "cancel"):
            t.cancel()
        # Les ecoutes de cette instance s'arretent au tour suivant : un cog
        # recharge reprend les siennes (_reprendre_ecoutes), et deux ecoutes
        # du meme numero ecrivaient deux fois son code.
        for cid in list(self._ecoute):
            self._ecoute[cid] += 1

    @commands.Cog.listener()
    async def on_ready(self):
        """Arme le recap du jour, puis reprend l'ecoute des numeros qui
        attendaient leur code.

        Chaque push sur main redemarre le bot (cron du VPS). L'ecoute d'un
        numero pris juste avant mourait avec l'ancien processus : le code
        arrivait chez le fournisseur et ne s'affichait plus tout seul, il
        fallait penser a cliquer « Redemander ». Le registre sait quels
        numeros attendent encore (vivants, sans code) : on les ecoute de
        nouveau. Un salon que ce bot ne voit pas est DIT au journal."""
        # Le recap ne part que de LA machine de production : un poste de dev
        # qui lance le bot a son propre data/, se croirait en retard et
        # posterait le meme recap une seconde fois (vu avec la quete du jour,
        # 23/09). Son premier tour fige la veille restee « en direct »
        # pendant l'arret, et remet le jour en cours a jour.
        # Un drapeau, pas le retour de create_task : c'est lui qui garantit
        # UNE boucle, quoi que rende la boucle d'evenements.
        if not self._recap_arme and machine_prod():
            self._recap_arme = True
            self._recap_tache = self.bot.loop.create_task(self._boucle_recap())
        await self._reprendre_ecoutes()

    async def _reprendre_ecoutes(self):
        """Relance l'ecoute de chaque numero vivant et sans code du registre.

        Une fois par instance du cog. Appelee par on_ready au demarrage, et
        par cog_load quand le cog est (re)charge sur un bot DEJA pret : il ne
        recevra alors plus de on_ready, et ses numeros en attente restaient
        sur « En attente du code… » sans que rien ne les redessine.
        Ne leve jamais : c'est une tache de fond, et une tache qui meurt ne
        dit rien. Un salon illisible est journalise, les autres repartent."""
        if self._repris:
            return
        self._repris = True
        repris = 0
        try:
            salons = _salons()
        except Exception as e:                               # noqa: BLE001
            log.exception("numgen: registre des salons illisible : aucune ecoute "
                          "reprise (%s: %s)", type(e).__name__, e)
            return
        for cid, rec in salons.items():
            try:
                actif, code = _a_afficher(rec if isinstance(rec, dict) else {})
                if not actif or code:
                    continue
                try:
                    ch = self.bot.get_channel(int(cid))
                except (TypeError, ValueError):
                    ch = None
                if ch is None:
                    log.warning("numgen: ecoute de %s non reprise : salon %s introuvable "
                                "pour ce bot", actif.get("valeur"), cid)
                    continue
                log.info("numgen: ecoute reprise pour #%s (%s)",
                         getattr(ch, "name", "?"), actif.get("id"))
                self._ecouter(ch)
                repris += 1
            except Exception as e:                           # noqa: BLE001
                log.exception("numgen: ecoute du salon %s non reprise (%s: %s)",
                              cid, type(e).__name__, e)
        if repris:
            log.info("numgen: %d ecoute(s) de code reprise(s) apres le redemarrage",
                     repris)

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
        # Cog (re)charge sur un bot DEJA connecte (reload de l'extension) :
        # on_ready ne viendra plus, les ecoutes se reprennent d'ici. Au
        # demarrage normal, le bot n'est pas encore pret : on_ready s'en charge.
        try:
            pret = bool(getattr(self.bot, "is_ready", lambda: False)())
        except Exception:                                    # noqa: BLE001
            pret = False
        if pret:
            self.bot.loop.create_task(self._reprendre_ecoutes())

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

    async def nouvelle_activation(self, itx, kind="sms", service="ig", par=None):
        """Prend un numero (ou un mail) et le montre DANS le panneau.

        Rien d'ephemere : le VA n'a pas a garder un message fantome ouvert, et
        s'il recharge Discord il retrouve exactement le meme ecran.

        `par` : le proprietaire du numero, quand ce n'est pas le cliqueur --
        « Autre » garde celui du numero remplace. Un admin qui aidait un VA
        devenait proprietaire du nouveau numero, et le VA recevait « 🔒 Ce
        numéro a été pris par @admin » sur le numero dont il se servait.
        """
        ch = getattr(itx, "channel", None)
        if ch is None:
            return
        rec0 = _salon(ch.id)
        en_cours = rec0.get("actif")
        if en_cours and not _code_courant(rec0) and _numero_vivant(en_cours):
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
            await self._acheter(itx, ch, kind, service, par=par)
        finally:
            self._achats.discard(ch.id)

    async def _acheter(self, itx, ch, kind, service, par=None):
        # L'activation precedente (code deja recu, ou numero mort) laisse la
        # place : elle ne reviendra pas s'afficher si l'achat echoue.
        # Registre inecrivable DES ICI : on n'achete rien. Le numero ne
        # pourrait pas y etre inscrit, donc ni affiche ni ecoute.
        try:
            _salon_ecrire(ch.id, actif=None, code_valeur=None, code_de=None)
        except Exception as e:                      # noqa: BLE001
            log.error("numgen: registre des salons inecrivable (%s: %s) : rien n'est "
                      "achete dans #%s", type(e).__name__, e, getattr(ch, "name", "?"))
            await _ephemere(itx, "❌ Le registre des numéros ne s'écrit plus : rien n'a "
                                 "été acheté. Préviens un admin.")
            return
        self._ecoute[ch.id] = self._ecoute.get(ch.id, 0) + 1
        # LE PIEGE d'avant : un achat sans place pour l'afficher. Le clic
        # achetait un numero que rien ne montrait, perdu avec l'argent. Le
        # panneau doit donc etre ECRIT avant qu'on commande quoi que ce soit.
        cherche = ("⏳ Recherche d'un numéro…" if kind == "sms"
                   else "⏳ Recherche d'un mail…")
        # Le dernier solde lu, sans relecture ; juste apres un redemarrage il
        # n'y en a pas encore (None) : _vue_salon le lit alors une fois, au
        # lieu d'afficher « 💵 — » le temps de la recherche.
        if not await maj_panneau(self.bot, ch, cog=self, souci=cherche,
                                 solde=_DERNIER_SOLDE["sms"]):
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
            "par": par or getattr(getattr(itx, "user", None), "id", 0),
            # Heure de prise : un numero mort ne bloque plus le salon.
            "pris_le": int(time.time()),
        }
        # Noté AVANT de l'afficher : il est paye, et le recap du soir doit le
        # compter meme si la suite echoue (il sera alors marque rendu).
        histo_prise(actif, ch, _membre_proprietaire(itx, ch, actif["par"]))
        # Le numero est PAYE : a partir d'ici, tout echec -- registre
        # inecrivable, exception au dessin -- doit finir par le rendre. Une
        # exception qui remontait telle quelle sautait le rendu : numero perdu.
        try:
            _salon_ecrire(ch.id, actif=actif, code_valeur=None, code_de=None)
            montre = await maj_panneau(self.bot, ch, cog=self)
            # Autre filet : le panneau se dessine d'apres le registre RELU.
            # S'il n'y porte pas CE numero, ce que le VA voit n'est pas lui --
            # un panneau « vide » bien dessine rendait True.
            if montre and (_salon(ch.id).get("actif") or {}).get("id") != actif["id"]:
                log.error("numgen: numero %s pris, absent du registre relu de #%s",
                          actif.get("valeur"), getattr(ch, "name", "?"))
                montre = False
        except Exception as e:                      # noqa: BLE001
            log.exception("numgen: numero %s pris, affichage en echec (%s: %s)",
                          actif.get("valeur"), type(e).__name__, e)
            montre = False
        if not montre:
            # On n'a pas pu l'ECRIRE : le VA ne le verra jamais. Le garder,
            # c'est le payer pour rien — chaque clic coutait 0,25 $ pendant
            # que le panneau restait sur « Recherche d'un numero… ». On le
            # rend, ce qui rembourse tant qu'aucun code n'est arrive.
            log.error("numgen: numero %s pris mais INAFFICHABLE dans #%s — on le rend",
                      actif.get("valeur"), getattr(ch, "name", "?"))
            ok_rendu, raison = await _rendre(actif, "inaffichable")
            if ok_rendu:
                # Le VA ne l'a jamais vu : le recap ne le lui compte pas en
                # echec, il le montre a part (« rendu par le bot »).
                histo_evenement(kind, actif["id"], "rendu", rendu_auto=True)
                try:
                    _salon_ecrire(ch.id, actif=None, code_valeur=None, code_de=None)
                except Exception as e:              # noqa: BLE001
                    log.error("numgen: registre de #%s non remis a vide (%s: %s)",
                              getattr(ch, "name", "?"), type(e).__name__, e)
                await _ephemere(itx, "❌ Le numéro n'a pas pu s'afficher : il a été "
                                     "rendu (remboursé).")
                # Le panneau restait sur « Recherche d'un numéro… » : on le
                # redessine d'apres le registre (vide), si Discord le permet.
                try:
                    await maj_panneau(self.bot, ch, cog=self)
                except Exception as e:              # noqa: BLE001
                    log.warning("numgen: panneau de #%s non redessine apres le rendu "
                                "(%s: %s)", getattr(ch, "name", "?"), type(e).__name__, e)
                return
            await self._garder_non_rendu(itx, ch, actif, raison)
            return
        self._ecouter(ch)

    async def _garder_non_rendu(self, itx, ch, actif, raison):
        """Le fournisseur REFUSE de reprendre un numero inaffichable.

        Le plus souvent « annulation trop tot » : GetAText ne reprend rien
        dans les ~2 premieres minutes, et c'est justement la que ce cas
        arrive. L'effacer du registre, c'etait le perdre : paye, actif chez
        le fournisseur, et plus rien ne le connaissait -- ni affiche, ni
        annulable, ni ecoute -- pendant que le VA lisait « rendu
        (rembourse) ». On le GARDE, on ecoute son code, on retente le rendu
        dans 2 min (_rendre_plus_tard), et le VA lit la verite."""
        nom = getattr(ch, "name", "?")
        au_registre = True
        try:
            _salon_ecrire(ch.id, actif=actif, code_valeur=None, code_de=None)
        except Exception as e:                               # noqa: BLE001
            # Registre inecrivable : le rendu differe le porte seul, sans
            # condition (personne d'autre ne connait ce numero).
            au_registre = False
            log.error("numgen: %s non rendu ET hors registre dans #%s (%s: %s) -- "
                      "seul le rendu differe le connait", actif.get("valeur"), nom,
                      type(e).__name__, e)
        log.warning("numgen: %s non rendu dans #%s (%s) : garde, nouvel essai dans %d s",
                    actif.get("valeur"), nom, raison, RENDU_DIFFERE_SEC)
        if au_registre:
            self._ecouter(ch)
        try:
            self.bot.loop.create_task(self._rendre_plus_tard(ch, actif, itx, au_registre))
        except Exception as e:                               # noqa: BLE001
            log.error("numgen: rendu differe de %s NON programme (%s: %s) -- a rendre "
                      "a la main chez le fournisseur", actif.get("valeur"),
                      type(e).__name__, e)
        await _ephemere(itx, "⚠️ Le numéro `%s` n'a pas pu s'afficher et n'est pas encore "
                             "rendu (%s) : nouvel essai automatique dans 2 min."
                             % (actif.get("valeur"), _ligne_courte(raison, 120)))
        # Dernier essai d'affichage : sans lui, le panneau restait sur
        # « Recherche d'un numéro… ».
        try:
            await maj_panneau(self.bot, ch, cog=self,
                              souci="❌ Pas encore rendu : nouvel essai dans 2 min")
        except Exception as e:                               # noqa: BLE001
            log.warning("numgen: panneau de #%s toujours inaffichable (%s: %s)",
                        nom, type(e).__name__, e)

    async def _rendre_plus_tard(self, ch, actif, itx=None, au_registre=True):
        """Retente le rendu d'un numero que le fournisseur refusait de
        reprendre, tant qu'il est au panneau SANS code (un code arrive entre-
        temps : le VA s'en sert, on n'y touche plus). Une trace par essai.
        Ne leve jamais : c'est une tache de fond."""
        nom = getattr(ch, "name", "?")
        act_id = str(actif.get("id"))
        valeur = actif.get("valeur")
        try:
            for essai in range(1, RENDU_ESSAIS + 1):
                await asyncio.sleep(RENDU_DIFFERE_SEC)
                if au_registre:
                    rec = _salon(ch.id)
                    if str((rec.get("actif") or {}).get("id")) != act_id:
                        log.info("numgen: rendu differe de %s abandonne : il n'est plus "
                                 "au panneau de #%s (annule ou remplace)", valeur, nom)
                        return
                    if _code_courant(rec):
                        log.info("numgen: rendu differe de %s abandonne : son code est "
                                 "arrive (#%s)", valeur, nom)
                        return
                ok, raison = await _rendre(actif, "rendu differe, essai %d/%d"
                                           % (essai, RENDU_ESSAIS))
                if ok or _rendu_inutile(raison):
                    histo_evenement(actif.get("kind"), act_id, "rendu", rendu_auto=True)
                    if au_registre:
                        # Relu SANS await depuis : l'ecriture ne peut pas
                        # effacer un numero pris entre-temps.
                        rec = _salon(ch.id)
                        if (str((rec.get("actif") or {}).get("id")) == act_id
                                and not _code_courant(rec)):
                            _salon_ecrire(ch.id, actif=None, code_valeur=None, code_de=None)
                            self._ecoute[ch.id] = self._ecoute.get(ch.id, 0) + 1
                            await maj_panneau(self.bot, ch, cog=self)
                    return
            log.error("numgen: %s TOUJOURS PAS RENDU apres %d essais dans #%s -- a rendre "
                      "a la main chez le fournisseur", valeur, RENDU_ESSAIS, nom)
            if itx is not None:
                await _ephemere(itx, "❌ `%s` n'a pas pu être rendu : préviens un admin."
                                % valeur)
        except Exception as e:                               # noqa: BLE001
            log.exception("numgen: rendu differe de %s interrompu (%s: %s) -- a verifier "
                          "chez le fournisseur", valeur, type(e).__name__, e)

    def _ecouter(self, channel):
        """Lance l'ecoute du code de l'activation EN COURS du salon ; une
        ecoute plus ancienne s'arrete au tour suivant."""
        g = self._ecoute.get(channel.id, 0) + 1
        self._ecoute[channel.id] = g
        self.bot.loop.create_task(self.suivre(channel, g))

    def _ecoute_courante(self, channel, gen):
        return gen is None or self._ecoute.get(getattr(channel, "id", 0)) == gen

    async def _montrer_code(self, channel, actif, val):
        """Ecrit le code `val` de `actif` au registre, puis l'AFFICHE. Rend
        True s'il est reellement a l'ecran.

        L'activation n'est PLUS close ici. Le setStatus 6 partait des
        l'affichage, et « 🔄 Nouveau code » (setStatus 3) n'est accepte que
        sur une activation encore ouverte : il ne pouvait finir qu'en
        « ❌ … », et le VA qui avait besoin d'un second SMS payait un autre
        numero. La cloture se fait a « ✅ C'est bon », ou a « Autre » quand
        un code a ete recu (action_salon)."""
        nom = getattr(channel, "name", "?")
        act_id = actif.get("id")
        try:
            # code_affiche=False jusqu'a l'affichage reussi : « Redemander »
            # ne compte comme deja vu qu'un code REELLEMENT montre.
            _salon_ecrire(channel.id, code_valeur=val, code_de=act_id, code_affiche=False)
        except Exception as e:                               # noqa: BLE001
            # Registre inecrivable : le panneau, dessine d'apres lui, ne
            # montrerait pas ce code. On le met dans la ligne de souci plutot
            # que de le perdre (l'activation reste ouverte).
            log.error("numgen: code de %s recu mais registre inecrivable dans #%s (%s: %s) "
                      "-- montre en ligne de souci", act_id, nom, type(e).__name__, e)
            histo_evenement(actif.get("kind"), act_id, "code")
            try:
                return await maj_panneau(
                    self.bot, channel, cog=self,
                    souci="🔑 Code : %s (registre inécrivable, préviens un admin)" % val)
            except Exception as e2:                          # noqa: BLE001
                log.error("numgen: et le code de %s n'a pas pu s'afficher dans #%s (%s: %s)",
                          act_id, nom, type(e2).__name__, e2)
                return False
        histo_evenement(actif.get("kind"), act_id, "code")
        log.info("numgen: code recu pour #%s (%s)", nom, act_id)
        return await self._afficher_code(channel, act_id, val)

    async def _afficher_code(self, channel, act_id, val):
        """Redessine le panneau qui porte le code `val` de `act_id`, en
        AFFICHAGE_ESSAIS essais espaces de AFFICHAGE_PAUSE_SEC ; note
        code_affiche=True au premier succes.

        Le retour de maj_panneau etait ignore : deux editions ratees (503,
        coupure, droits) laissaient « En attente du code… », l'activation
        etait close quand meme et plus rien ne redessinait jusqu'au clic
        suivant -- ou « Redemander » effacait ce code jamais vu."""
        nom = getattr(channel, "name", "?")
        for essai in range(1, AFFICHAGE_ESSAIS + 1):
            rec = _salon(channel.id)
            if (rec.get("actif") or {}).get("id") != act_id or _code_courant(rec) != val:
                log.info("numgen: affichage du code de %s abandonne : le registre de #%s "
                         "a change entre-temps", act_id, nom)
                return False
            try:
                ok = await maj_panneau(self.bot, channel, cog=self)
            except Exception as e:                           # noqa: BLE001
                log.warning("numgen: affichage du code de %s dans #%s en echec (%s: %s)",
                            act_id, nom, type(e).__name__, e)
                ok = False
            if ok:
                # Relu sans await depuis : on ne marque pas le code d'un
                # numero remplace pendant l'edition.
                rec = _salon(channel.id)
                if (rec.get("actif") or {}).get("id") == act_id and _code_courant(rec) == val:
                    try:
                        _salon_ecrire(channel.id, code_affiche=True)
                    except Exception as e:                   # noqa: BLE001
                        # Le code EST a l'ecran ; au pire « Redemander » le
                        # remontrera au lieu d'en demander un autre.
                        log.warning("numgen: code de %s affiche dans #%s, mais non note "
                                    "comme tel (%s: %s)", act_id, nom, type(e).__name__, e)
                return True
            if essai < AFFICHAGE_ESSAIS:
                log.warning("numgen: code de %s pas encore affiche dans #%s (essai %d/%d) : "
                            "nouvel essai dans %d s", act_id, nom, essai, AFFICHAGE_ESSAIS,
                            AFFICHAGE_PAUSE_SEC)
                await asyncio.sleep(AFFICHAGE_PAUSE_SEC)
        log.error("numgen: code de %s JAMAIS affiche dans #%s apres %d essais -- activation "
                  "laissee ouverte, « Redemander » le montrera", act_id, nom, AFFICHAGE_ESSAIS)
        return False

    async def _code_arrive_pendant(self, ch, rec, act_id, deja, pendant):
        """« Redemander » : vrai si le registre RELU (`rec`) porte pour
        `act_id` un code autre que `deja` (le code deja montre) -- ecrit par
        l'ecoute pendant l'appel au fournisseur, ou jamais montre. Il est
        alors affiche, et rien n'est redemande ni efface.

        La relecture ne comparait que l'id de l'activation : un code arrive
        pendant l'appel etait efface juste apres, et le panneau revenait a
        « En attente du code… »."""
        neuf = _code_courant(rec)
        if not neuf or neuf == deja:
            return False
        log.info("numgen: redemander de %s dans #%s : un code est au registre (arrive pendant "
                 "%s, ou pas encore montre) -- il est montre, rien n'est redemande ni efface",
                 act_id, getattr(ch, "name", "?"), pendant)
        await self._afficher_code(ch, act_id, neuf)
        return True

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
        nom = getattr(channel, "name", "?")
        rec0 = _salon(channel.id)
        actif0 = rec0.get("actif") or {}
        act_id = actif0.get("id")
        debut = time.time()
        try:
            pris = float(actif0.get("pris_le") or 0)
        except (TypeError, ValueError):
            pris = 0.0
        # On ecoute tant que le numero VIT (20 min apres sa prise), pas un
        # nombre fixe de tours : l'ecoute s'arretait a 3 min, et le code
        # arrive ensuite ne s'affichait plus. Un numero sans heure (d'avant
        # le 27/09) garde l'ancien delai.
        fin = (pris + DUREE_NUMERO_SEC) if pris else (debut + POLL_MAX)
        reste = max(0.0, fin - debut)
        log.info("numgen: ecoute du code demarree pour #%s (%s), %d s au plus",
                 nom, act_id, reste)
        # `dormi` borne la boucle meme si l'horloge ne bouge pas (bancs a
        # sommeil nul) ; en vrai, l'heure de fin arrive la premiere.
        dormi = 0.0
        erreurs = 0
        while dormi < reste and time.time() < fin:
            age = debut + dormi - (pris or debut)
            pas = POLL_SECONDS if age < POLL_MAX else max(POLL_SECONDS, POLL_LENT)
            await asyncio.sleep(pas)
            dormi += pas
            if not self._ecoute_courante(channel, gen):
                return                      # une ecoute plus recente a pris le relais
            rec = _salon(channel.id)
            actif = rec.get("actif")
            if not actif or actif.get("id") != act_id:
                return                      # annule ou remplace entre-temps
            if _code_courant(rec):
                return                      # deja trouve (« Redemander »)
            if actif.get("kind") == "sms":
                etat, val = await asyncio.to_thread(
                    numgen.get_code, actif["id"], actif["provider"])
            else:
                etat, val = await asyncio.to_thread(
                    numgen.get_mail_code, actif["id"], actif.get("stale", ""))
            if etat == "code" and val:
                # Relu JUSTE avant d'ecrire, sans await entre les deux : pendant
                # get_code (20 s de delai au pire), « Autre » a pu remplacer ce
                # numero -- et son code s'ecrivait sous le numero suivant, dont
                # l'ecoute s'arretait alors (numero paye pour rien).
                rec = _salon(channel.id)
                if (not self._ecoute_courante(channel, gen)
                        or (rec.get("actif") or {}).get("id") != act_id):
                    log.info("numgen: code de %s arrive apres son remplacement dans "
                             "#%s : ignore", act_id, nom)
                    return
                # Ecrit, affiche (essais repetes), et l'activation reste
                # OUVERTE : elle se clot a « C'est bon » (_montrer_code).
                await self._montrer_code(channel, actif, val)
                return
            if etat == "error" and not _erreur_definitive(val):
                # Timeout, coupure, page HTML d'un 502 : le numero vit
                # toujours, son SMS peut arriver au tour suivant. Une seule
                # erreur arretait l'ecoute pour de bon.
                erreurs += 1
                log.warning("numgen: ecoute de #%s : erreur passagere %d/%d (%s)",
                            nom, erreurs, ECOUTE_ERREURS_MAX, _ligne_courte(val, 200))
                if erreurs < ECOUTE_ERREURS_MAX:
                    continue
            if etat in ("cancel", "error"):
                log.warning("numgen: ecoute de #%s close : %s %s", nom, etat, val)
                # Pas une fin : le numero reste au panneau, « Redemander » peut
                # encore trouver son code. Note pour comprendre un « sans code ».
                histo_evenement(actif.get("kind"), actif["id"], "souci",
                                souci=_ligne_courte("%s %s" % (etat, val or ""), 150))
                await maj_panneau(self.bot, channel, cog=self,
                                  souci="❌ %s" % (val or "activation close"))
                return
            erreurs = 0
        if self._ecoute_courante(channel, gen):
            rec = _salon(channel.id)
            if (rec.get("actif") or {}).get("id") != act_id or _code_courant(rec):
                return
            minutes = int(round((fin - (pris or debut)) / 60.0))
            log.info("numgen: aucun code en %d min pour #%s (%s) : ecoute terminee",
                     minutes, nom, act_id)
            await maj_panneau(self.bot, channel, cog=self,
                              souci="❌ Aucun code reçu en %d min" % minutes)

    async def action_salon(self, itx, quoi, attendu=None, code_vu=None):
        """🔄 Redemander · ✅ C'est bon · 🔁 Autre · ❌ Annuler, depuis le panneau.

        `attendu` : l'id de l'activation que nommait la confirmation
        (« Changer `A` pour un autre numéro ? »). Si le numero a change
        depuis, rien n'est fait : deux confirmations ouvertes (double clic
        sur « Autre ») rendaient A et achetaient B, puis rendaient B -- que
        le VA venait peut-etre de saisir -- et achetaient C.

        `code_vu` (avec `attendu`) : le code visible quand la question a ete
        posee. Un code arrive PENDANT la confirmation (le VA attendait
        justement son SMS) etait efface, et « Autre » rachetait un numero :
        A paye et son code perdu, B paye en plus.
        """
        ch = getattr(itx, "channel", None)
        if ch is None:
            return
        nom = getattr(ch, "name", "?")
        rec = _salon(ch.id)
        actif = rec.get("actif")
        if attendu is not None and str((actif or {}).get("id")) != str(attendu):
            log.info("numgen: %s de %s ignore dans #%s : le numero a deja change (%s)",
                     quoi, attendu, nom, (actif or {}).get("id"))
            await _ephemere(itx, "Ce numéro a déjà changé : rien n'a été fait.")
            await maj_panneau(self.bot, ch, cog=self)
            return
        if not actif:
            # Un vieux message ou un double clic : rien en cours. Le panneau
            # est redessine (etat vide) au lieu d'un bouton muet.
            log.info("numgen: %s sans numero en cours dans #%s", quoi, nom)
            await maj_panneau(self.bot, ch, cog=self)
            return
        sms = actif.get("kind") == "sms"
        code = _code_courant(rec)
        # TOUS les boutons d'un numero sont a son proprietaire (ou a un admin).
        # Seuls Autre et Annuler l'etaient : dans un salon partage, un autre
        # membre cliquait « C'est bon » et le code disparaissait avant que le
        # proprietaire l'ait saisi -- deja « fini » chez le fournisseur, il
        # n'etait plus nulle part ; « Nouveau code » l'effacait de meme.
        # « C'est bon » d'un autre reste permis sur un numero MORT (20 min) :
        # un proprietaire parti ne doit pas bloquer le salon.
        gere = _peut_gerer(itx, actif) or (quoi == "fini" and not _numero_vivant(actif))
        if quoi in ("autre", "annuler", "retry", "fini") and not gere:
            log.warning("numgen: %s bloque pour %s dans #%s (numero de %s)", quoi,
                        getattr(getattr(itx, "user", None), "id", "?"), nom,
                        actif.get("par"))
            if quoi in ("autre", "annuler"):
                mot = ("🔒 Ce numéro a été pris par <@%s> : lui seul (ou un admin) peut "
                       "l'annuler ou le changer." % actif.get("par"))
            else:
                mot = ("🔒 Ce numéro a été pris par <@%s> : lui seul (ou un admin) peut "
                       "s'en servir." % actif.get("par"))
            await _ephemere(itx, mot)
            return
        log.info("numgen: %s par %s dans #%s", quoi,
                 getattr(getattr(itx, "user", None), "id", "?"), nom)
        if quoi == "fini":
            if not code and _numero_vivant(actif):
                # « C'est bon » sans code, ce serait abandonner un numero paye
                # sans le rendre. Le bouton n'existe pas dans cet etat, mais un
                # clic croise (deux onglets) peut encore l'envoyer.
                log.warning("numgen: « C'est bon » ignore dans #%s : %s attend "
                            "encore son code", nom, actif.get("valeur"))
                await maj_panneau(self.bot, ch, cog=self)
                return
            _salon_ecrire(ch.id, actif=None, code_valeur=None, code_de=None,
                          code_affiche=None)
            histo_evenement(actif.get("kind"), actif.get("id"), "fini")
            self._ecoute[ch.id] = self._ecoute.get(ch.id, 0) + 1
            await maj_panneau(self.bot, ch, cog=self)
            if code:
                # L'activation se clot ICI, plus a la reception du code : clos
                # des l'affichage, « Nouveau code » etait refuse. APRES
                # l'effacement du registre, pas avant : l'appel HTTP (20 s au
                # pire) ne tombe plus entre la lecture du registre et son
                # ecriture, ou un autre clic pouvait s'intercaler.
                await _finir(actif)
            return
        act_id = actif.get("id")
        if quoi == "retry":
            # Le code DEJA affiche ne compte pas : « Nouveau code » en veut un
            # autre. Un code au registre mais JAMAIS montre (code_affiche
            # False : editions ratees), si : le VA ne l'a pas vu, et
            # redemander un SMS le lui faisait perdre. Un code d'avant ce
            # champ (pas de code_affiche) a ete montre.
            deja = code if (code and rec.get("code_affiche", True) is not False) else None
            # D'ABORD regarder si le code est deja arrive. Il l'etait : visible
            # chez le fournisseur, absent du salon parce que l'ecoute avait
            # lache (un redemarrage du bot suffit). Redemander un SMS dans ce
            # cas fait perdre celui qu'on avait deja.
            if sms:
                etat0, val0 = await asyncio.to_thread(
                    numgen.get_code, actif["id"], actif["provider"])
            else:
                etat0, val0 = await asyncio.to_thread(
                    numgen.get_mail_code, actif["id"], actif.get("stale", ""))
            # Relu apres l'appel : « Autre » a pu remplacer le numero pendant
            # ce temps, et ce qui suit ecrirait sur le suivant.
            rec = _salon(ch.id)
            if (rec.get("actif") or {}).get("id") != act_id:
                log.info("numgen: redemander de %s sans suite dans #%s : numero "
                         "remplace entre-temps", act_id, nom)
                await maj_panneau(self.bot, ch, cog=self)
                return
            if await self._code_arrive_pendant(ch, rec, act_id, deja, "la lecture du code"):
                return
            if etat0 == "code" and val0 and val0 != deja:
                # Le code arrive souvent PAR ici (ecoute perdue a un
                # redemarrage) : _montrer_code le note aussi a l'historique,
                # sans quoi le recap le comptait « sans code » alors que le VA
                # l'avait eu. L'activation reste ouverte (C'est bon la clot).
                await self._montrer_code(ch, actif, val0)
                return
            if sms:
                ok, msg = await asyncio.to_thread(
                    numgen.retry, actif["id"], actif["provider"])
                if not ok:
                    log.warning("numgen: nouveau code refuse pour #%s : %s", nom, msg)
                    await maj_panneau(self.bot, ch, cog=self, souci="❌ %s" % msg)
                    # Le refus du « Redemander » ne tue pas le numero : son
                    # premier SMS peut encore arriver. Sans ecoute relancee
                    # ici, il n'etait jamais affiche (numero repris au
                    # redemarrage, ecoute deja finie).
                    if (not deja and _numero_vivant(actif) and etat0 != "cancel"
                            and not (etat0 == "error" and _erreur_definitive(val0))):
                        log.info("numgen: %s : l'ecoute de son code continue (#%s)",
                                 actif.get("valeur"), nom)
                        self._ecouter(ch)
                    return
                rec = _salon(ch.id)
                if (rec.get("actif") or {}).get("id") != act_id:
                    log.info("numgen: nouveau code de %s demande, mais le numero a ete "
                             "remplace entre-temps (#%s)", act_id, nom)
                    await maj_panneau(self.bot, ch, cog=self)
                    return
                # Le SMS arrive souvent PENDANT setStatus 3 : les VA cliquent
                # justement quand il tarde. L'ecoute l'a ecrit et affiche ;
                # l'effacer ci-dessous le faisait disparaitre du panneau.
                if await self._code_arrive_pendant(ch, rec, act_id, deja,
                                                   "la demande d'un nouveau code"):
                    return
            else:
                # Le prochain code du mail doit etre DIFFERENT de celui-ci. On
                # repart de l'activation RELUE, pas de celle d'avant l'appel.
                frais = dict(rec.get("actif") or {})
                frais["stale"] = deja or frais.get("stale", "")
                _salon_ecrire(ch.id, actif=frais)
            # Aucun await depuis la derniere relecture : rien ne peut ecrire
            # un code entre elle et cet effacement.
            _salon_ecrire(ch.id, code_valeur=None, code_de=None, code_affiche=None)
            await maj_panneau(self.bot, ch, cog=self)
            self._ecouter(ch)
            return
        # La question « Changer `A` … ? » a ete posee sans code, et un code est
        # arrive depuis (l'ecoute l'a ecrit et montre) : on ne touche a rien.
        # Le VA qui clique « Oui » ne l'a pas encore vu.
        if attendu is not None and code and code != code_vu:
            log.info("numgen: %s de %s ignore dans #%s : un code est arrive pendant la "
                     "confirmation", quoi, act_id, nom)
            await maj_panneau(self.bot, ch, cog=self)
            await _ephemere(itx, "🔑 Le code vient d'arriver : rien n'a été changé.")
            return
        # « Autre » et « Annuler » rendent le numero en cours : rembourse tant
        # qu'aucun code n'est arrive. Le RESULTAT compte : un refus (« trop
        # tot », timeout, 5xx) effacait le numero quand meme -- « Autre » en
        # achetait un second pendant que le premier restait actif, paye et
        # inconnu de tous.
        if code:
            # Un code a ete recu : l'annulation serait refusee (SMS livre, rien
            # a rembourser). On TERMINE l'activation, qui ne l'est plus a la
            # reception du code.
            await _finir(actif)
            ok_rendu, raison = False, "code deja recu"
        else:
            ok_rendu, raison = await _rendre(actif, quoi)
        rec = _salon(ch.id)
        if (rec.get("actif") or {}).get("id") != act_id:
            log.info("numgen: %s de %s : le numero a change pendant le rendu (#%s)",
                     quoi, act_id, nom)
            await maj_panneau(self.bot, ch, cog=self)
            return
        code_apres = _code_courant(rec)
        if code_apres and code_apres != code:
            # Le code est arrive PENDANT l'appel au fournisseur. Vider le
            # registre l'effacait avant que le VA l'ait vu (et « Autre »
            # rachetait). Numero et code restent ; si le fournisseur a accepte
            # le rendu, le journal le dit.
            log.warning("numgen: %s de %s dans #%s : un code est arrive pendant l'appel au "
                        "fournisseur (rendu %s) -- numero et code gardes", quoi,
                        actif.get("valeur"), nom, "ACCEPTE" if ok_rendu else "refuse")
            await maj_panneau(self.bot, ch, cog=self)
            await _ephemere(itx, "🔑 Le code vient d'arriver : le numéro est gardé.")
            return
        vivant = _numero_vivant(actif)
        if not (ok_rendu or code or not vivant or _rendu_inutile(raison)):
            # Refuse, vivant, sans code : il reste affiche, avec la raison
            # (« annulation trop tôt — attends ~2 min » le plus souvent).
            log.warning("numgen: %s de %s refuse par le fournisseur dans #%s (%s) : "
                        "numero garde", quoi, actif.get("valeur"), nom, raison)
            await maj_panneau(self.bot, ch, cog=self, souci="❌ %s" % raison)
            return
        if not ok_rendu:
            log.info("numgen: %s de %s sans rendu (%s) : %s", quoi,
                     actif.get("valeur"), raison,
                     "code deja recu, activation terminee" if code else
                     ("numero expire" if not vivant else "deja clos chez le fournisseur"))
        _salon_ecrire(ch.id, actif=None, code_valeur=None, code_de=None, code_affiche=None)
        # Seulement ici : un numero que le fournisseur refuse de reprendre
        # (ci-dessus) reste au panneau, il n'est ni annule ni remplace.
        histo_evenement(actif.get("kind"), actif.get("id"),
                        "remplace" if quoi == "autre" else "annule")
        self._ecoute[ch.id] = self._ecoute.get(ch.id, 0) + 1
        if quoi == "autre":
            # Le nouveau numero reste a CELUI du numero remplace, meme si
            # c'est un admin qui a clique.
            await self.nouvelle_activation(itx, "sms" if sms else "mail",
                                           actif.get("service", "ig"),
                                           par=actif.get("par"))
            return
        await maj_panneau(self.bot, ch, cog=self)

    # ------------------------------------------- récap du jour (debrief-day)
    # UN message par jour et par serveur dans « debrief-day » : cree au premier
    # numero de la journee (heure du Benin), edite a chaque evenement de
    # l'historique (« je peux avoir un recap par jour en live ? », 27/09/2026),
    # puis fige a minuit en recap final PAR EDITION du meme message -- plus de
    # second message a 00:05.
    # Un serveur qui a un panneau numeros ET un « debrief-day » a son message
    # des minuit, meme a 0 SMS (« Pas de SMS pour le moment. ») : le
    # proprietaire ne voyait rien dans le salon et ne savait pas si le recap
    # tournait (« même là, il y a 0 SMS », 27/09/2026). Le premier numero
    # EDITE ce message ; aucun jour vide n'est poste apres coup.
    def _dire_une_fois(self, cle, niveau, msg, *args):
        """Un souci du recap se dit UNE fois par processus : la boucle repasse
        chaque minute, et le meme avertissement noyait le journal."""
        if cle in self._recap_dits:
            return
        self._recap_dits.add(cle)
        niveau(msg, *args)

    def _serveurs_du_recap(self):
        """Les serveurs (ids en chaine, comme les cles de agreger) qui ont leur
        message du jour meme a 0 SMS : voir serveur_du_recap. Un serveur dont
        les salons ne se lisent pas est DIT (une fois), pas ecarte en silence."""
        out = set()
        for g in list(getattr(self.bot, "guilds", None) or []):
            if getattr(g, "unavailable", False):
                # Reconnexion Discord : discord.py garde ses salons en cache
                # (GUILD_DELETE unavailable), mais tout appel echoue en 503 et
                # un envoi sans reponse nette a pu partir -- le message a 0 du
                # jour etait tente chaque minute pendant la panne. Il part a
                # son retour ; _chercher_zeros le traite a part.
                continue
            try:
                du = serveur_du_recap(g)
                self._recap_connus[str(g.id)] = bool(du)
                if du:
                    out.add(str(g.id))
            except Exception as e:                           # noqa: BLE001
                self._dire_une_fois(
                    ("serveur", getattr(g, "id", None)), log.warning,
                    "numgen: recap : salons du serveur %s illisibles (%s: %s) -- pas de "
                    "message a 0 SMS pour lui", getattr(g, "id", "?"), type(e).__name__, e)
        return out

    def _zero_manquant(self, gid, fiche):
        """Le serveur du recap `gid` n'a pas (ou plus) son message a 0 du jour :
        aucune fiche, ou une fiche a 0 dont le salon n'est plus le sien -- un
        « debrief-day » supprime puis recree ne recevait rien jusqu'a minuit,
        puis la veille y etait postee apres coup.

        Une fiche A NUMEROS (postee, ou retenue : salon absent, envoi refuse)
        n'est jamais « manquante » : elle a son propre chemin (evenements,
        rattrapage). La compter relisait l'historique chaque minute, et un
        historique perdu la faisait remplacer par « Pas de SMS »."""
        if not isinstance(fiche, dict) or not fiche:
            return True
        if not _fiche_vide(fiche):
            return False
        if not fiche.get("messages"):
            return True
        guild = self._guilde(gid)
        salon = self._salon_recap(guild, fiche, bavard=False) if guild is not None else None
        return salon is not None and getattr(salon, "id", None) != fiche.get("salon")

    def _salon_perdu(self, guild):
        """Le salon du recap manque-t-il POUR DE BON ? Oui si le serveur est
        visible (disponible, ses salons connus) ou si le bot n'y est plus (il
        en voit d'autres). Non pendant une panne : a une reconnexion complete,
        discord.py remet les serveurs « unavailable », sans aucun salon, le
        temps que Discord les renvoie -- le message a 0 de la veille etait clos
        « en direct » pour toujours au premier tour de minuit tombe la-dessus."""
        if guild is None:
            return bool(list(getattr(self.bot, "guilds", None) or []))
        if getattr(guild, "unavailable", False):
            return False
        return bool(getattr(guild, "text_channels", None))

    def _reveiller(self):
        """Appelee apres chaque evenement de l'historique : reveille la boucle
        du recap, qui sinon attendait son tour suivant (jusqu'a une minute)
        pour creer le message du premier numero."""
        ev, boucle = self._reveil, self._reveil_boucle
        if ev is None or boucle is None:
            return
        try:
            # call_soon_threadsafe : un evenement note depuis un fil
            # (asyncio.to_thread) ne doit pas toucher l'Event directement.
            boucle.call_soon_threadsafe(ev.set)
        except RuntimeError:
            pass                    # boucle fermee : le bot s'arrete

    async def _attendre_reveil(self, delai):
        """Dort `delai` secondes, moins si un evenement arrive entre-temps."""
        ev = self._reveil
        if ev is None:
            await asyncio.sleep(delai)
            return
        try:
            await asyncio.wait_for(ev.wait(), timeout=max(0.0, delai))
        except asyncio.TimeoutError:
            pass
        # Efface APRES le reveil et AVANT le tour : un evenement arrive
        # pendant le tour qui suit remet le drapeau, et la generation de
        # l'historique (_HISTO_GEN) garde la trace de tout evenement.
        ev.clear()

    async def _boucle_recap(self):
        """Tient le recap a jour : un tour a chaque evenement de l'historique,
        et au moins un par minute.

        Un reveil court plutot qu'un long sommeil jusqu'a minuit : le bot
        redemarre a chaque push, et un sommeil de 20 h repartait de zero. Un
        tour sans evenement ne coute qu'une lecture du registre : il ne relit
        pas l'historique (plusieurs Mo a la fin des 90 jours)."""
        attendre = getattr(self.bot, "wait_until_ready", None)
        if attendre is not None:
            try:
                await attendre()
            except Exception:                                # noqa: BLE001
                log.exception("numgen: recap : attente de la connexion en echec")
        self._reveil = asyncio.Event()
        self._reveil_boucle = asyncio.get_running_loop()
        _ECOUTEURS_HISTO.append(self._reveiller)
        log.info("numgen: recap des numeros arme (salon « %s », en direct, fige a minuit "
                 "heure du Benin)", RECAP_SALON)
        try:
            while True:
                bilan = None
                try:
                    bilan = await self.recap_tour()
                except asyncio.CancelledError:
                    raise
                except Exception as e:                       # noqa: BLE001
                    # Une tache de fond qui leve meurt sans un mot : le recap
                    # s'arretait pour de bon. On le dit, et on repasse.
                    log.exception("numgen: tour du recap en echec (%s: %s)",
                                  type(e).__name__, e)
                delai = float(RECAP_PAS_SEC)
                reveil = (bilan or {}).get("reveil")
                if reveil:
                    # Fin du regroupement, ou prochain numero qui expire :
                    # l'edition part a l'heure, pas jusqu'a une minute apres.
                    delai = max(1.0, min(delai, float(reveil) - time.time()))
                await self._attendre_reveil(delai)
        finally:
            try:
                _ECOUTEURS_HISTO.remove(self._reveiller)
            except ValueError:
                pass
            self._reveil = self._reveil_boucle = None

    async def recap_tour(self, maintenant=None):
        """Un tour du recap : fige les journees finies, tient a jour la
        journee en cours. Rend le bilan du tour.

        Journee finie (des minuit, heure du Benin) : son message « en direct »
        est EDITE en recap final. S'il a disparu, ou ne peut pas etre edite,
        le recap final est poste UNE fois (repli). Un jour sans message (bot
        arrete, registre perdu) est poste de la meme facon, dans la limite du
        rattrapage (RECAP_RATTRAPAGE_JOURS) -- sauf un jour a 0 SMS : seul un
        message a 0 deja poste est fige, rien n'est poste apres coup.

        Journee en cours : le message est cree au premier tour du jour sur les
        serveurs du recap (panneau numeros + « debrief-day »), meme a 0 SMS,
        ailleurs au premier numero ; puis edite
        quand son texte change -- au plus une fois par RECAP_DIRECT_PAS_SEC.
        Les evenements d'une rafale partent ensemble a la fin de l'attente, et
        le dernier part toujours : bilan["reveil"] dit quand repasser.

        Un numero pris a 23:58 peut recevoir son code jusqu'a 00:18 : le recap
        fige a minuit est corrige (meme regroupement) tant qu'un numero de la
        journee attend encore, puis « fige » pour de bon."""
        now = float(time.time() if maintenant is None else maintenant)
        # La generation AVANT toute lecture : un evenement note pendant le tour
        # (les envois Discord rendent la main) laisse le recap « a refaire ».
        gen = _HISTO_GEN[0]
        bilan = {"postes": [], "edites": [], "finalises": [], "replis": [], "attente": [],
                 "sans_salon": [], "vides": [], "echecs": [], "retenu": False,
                 "reveil": None}
        reg = _recap_lire()
        if reg is None:
            return bilan
        premiere = "jours" not in reg
        jours_reg = reg.setdefault("jours", {})
        aujourdhui = jour_benin(now)
        fenetre = jours_a_recapituler(now)
        entrees = None
        if premiere:
            # Registre neuf (premiere mise en route, ou perdu) : un PLANCHER
            # durable, « depuis ». Rattraper une semaine sur un registre vide,
            # c'etait reposter des recaps deja partis -- et la garde d'avant
            # (« seulement la veille ») ne tenait qu'UN tour : il enregistrait
            # la cle « jours », le suivant (60 s plus tard) n'etait plus
            # « premier » et reprenait les 7 jours (6 doublons simules).
            entrees = _histo_cloturer(now)
            if entrees is None:
                return bilan
            # Le plancher est la VEILLE, meme quand l'historique nait
            # aujourd'hui : un message a 0 poste hier (registre perdu dans la
            # nuit, historique vide faute de numero) restait « en direct »
            # pour toujours, sans une ligne de journal -- plancher a
            # aujourd'hui, la veille n'etait jamais examinee. L'examiner ne
            # poste rien (aucun jour vide n'est poste apres coup) : une lecture
            # du salon par serveur, et le message a 0 trouve est fige.
            depuis = fenetre[-1]
            if not any(_ts(e.get("pris_le")) < bornes_jour(aujourdhui)[0] for e in entrees):
                # L'historique nait AUJOURD'HUI (deploiement) : la journee en
                # cours est partielle. Son recap aurait fini sous « Journée
                # complète : de 00h00 à 23h59 », sans les numeros d'avant le
                # deploiement, et sans rien qui le signale.
                # Le proprietaire veut le voir EN DIRECT des la mise en route
                # (27/09/2026) : la journee est recapitulee, mais son en-tete
                # dit « depuis HHhMM » au lieu de « depuis 00h00 ».
                # L'heure de depart est celle du premier numero connu : un
                # numero pris avant ce premier tour est compte, l'en-tete ne
                # doit pas dire qu'on a commence apres lui.
                debut = min([now] + [_ts(e.get("pris_le")) for e in entrees
                                     if _ts(e.get("pris_le"))])
                reg.setdefault("partiel", {})[aujourdhui.isoformat()] = int(debut)
                log.info("numgen: recap : l'historique commence aujourd'hui (%s) : journee "
                         "partielle, recapitulee depuis %s", aujourdhui.isoformat(),
                         datetime.fromtimestamp(debut, BENIN).strftime("%Hh%M"))
            reg["depuis"] = depuis.isoformat()
            self._registre_neuf_le = aujourdhui.isoformat()
            # Des maintenant, le registre existe (avec son plancher) : un recap
            # retenu (salon absent) n'est pas oublie au tour suivant.
            self._recap_sauver(reg)
        plancher = str(reg.get("depuis") or "")
        self._redonner_fiches(reg, fenetre[0].isoformat())
        inc = reg.get("incertains")
        if inc is not None:
            # Un envoi incertain ne compte que pour le message a 0 du jour
            # meme : ceux des jours passes n'ont plus d'objet.
            garde = {k: v for k, v in (inc if isinstance(inc, dict) else {}).items()
                     if str(k).split("|")[0] >= aujourdhui.isoformat()}
            if garde != inc:
                if garde:
                    reg["incertains"] = garde
                else:
                    reg.pop("incertains", None)
                self._recap_sauver(reg)

        # Un recap retenu (salon absent, envoi refuse) qui sort de la fenetre
        # de rattrapage ne partira plus : on le DIT, une fois, au lieu de le
        # laisser filer.
        abandon = False
        for cle in sorted(jours_reg):
            if cle >= fenetre[0].isoformat() or not isinstance(jours_reg[cle], dict):
                continue
            for gid, v in jours_reg[cle].items():
                if not isinstance(v, dict) or _finalise(v) or v.get("abandonne"):
                    continue
                if _a_chercher(v):
                    # Salon illisible (ou serveur indisponible) a chaque essai
                    # pendant toute la fenetre : un message a 0 y est peut-etre
                    # reste « en direct ». Rien n'etait en attente -- dit sans
                    # alarme, avec la vraie raison.
                    log.info("numgen: recap du %s (serveur %s) : salon jamais relu, un message "
                             "a 0 eventuel n'a pas pu etre fige, sorti de la fenetre de %d jours "
                             "-- laisse tel quel", cle, gid, RECAP_RATTRAPAGE_JOURS)
                    v.update(finalise=True, fige=True, laisse="hors_fenetre")
                    abandon = True
                elif _fiche_vide(v) and v.get("messages"):
                    # Un message a 0 jamais fige (bot arrete plus longtemps que
                    # la fenetre, salon invisible ou Discord en panne a chaque
                    # essai) : rien n'etait en attente, ce n'est pas un recap
                    # perdu -- dit sans alarme, avec la vraie raison. Sans
                    # message, la fiche est un recap RETENU (jamais poste) : il
                    # est « abandonne », comme avant.
                    log.info("numgen: recap a 0 SMS du %s (serveur %s) jamais fige, sorti de la "
                             "fenetre de %d jours -- laisse tel quel", cle, gid,
                             RECAP_RATTRAPAGE_JOURS)
                    v.update(finalise=True, fige=True, laisse="hors_fenetre")
                    abandon = True
                else:
                    pourquoi = (("envoi toujours refuse (%s)" % v["envoi_refuse"])
                                if v.get("envoi_refuse")
                                else "toujours pas de salon « %s »" % RECAP_SALON)
                    log.warning("numgen: recap du %s (serveur %s, %s numero(s)) abandonne : "
                                "%s apres %d jours", cle, gid, v.get("numeros", "?"),
                                pourquoi, RECAP_RATTRAPAGE_JOURS)
                    v["abandonne"] = True
                    abandon = True
        if abandon:
            self._recap_sauver(reg)

        a_voir = [j for j in fenetre if j.isoformat() >= plancher]
        a_finir = [j for j in a_voir if not _jour_fini(jours_reg.get(j.isoformat()))]
        a_corriger = [j for j in a_voir if _jour_a_corriger(jours_reg.get(j.isoformat()))]
        direct = aujourdhui.isoformat() >= plancher
        # « Sale » : l'historique a bouge depuis la derniere lecture (ou jamais
        # lu dans ce processus : au redemarrage, le jour est remis a jour), une
        # edition a echoue, ou un numero vient d'expirer -- ce dernier change
        # le texte sans aucun evenement.
        sale = (self._direct_gen != gen or self._direct_a_refaire
                or (self._direct_expire_le is not None and now >= self._direct_expire_le))
        # Un serveur du recap sans message du jour : a minuit (le nouveau jour
        # n'a encore AUCUN evenement, « sale » restait faux jusqu'au premier
        # numero), quand un « debrief-day » vient d'etre cree, ou quand celui
        # du message a 0 a ete supprime puis recree (_zero_manquant). Son
        # message a 0 part dans la minute. Un envoi refuse le laisse
        # « manquant » : il est retente au tour suivant (RECAP_PAS_SEC, ou plus
        # tot sur un evenement), dit une fois -- pas de boucle serree, et sans
        # relire l'historique (_direct_agg).
        panneaux = self._serveurs_du_recap() if direct else set()
        jr_auj = jours_reg.get(aujourdhui.isoformat())
        jr_auj = jr_auj if isinstance(jr_auj, dict) else {}
        manquants = sorted(gid for gid in panneaux if self._zero_manquant(gid, jr_auj.get(gid)))
        # « vif_histo » : l'historique a bouge (ou rien n'en est connu) --
        # seul cas ou il faut le relire pour la journee en cours.
        vif_histo = sale and (direct or bool(a_corriger))
        vif = vif_histo or bool(manquants)
        if vif and 0 <= now - self._direct_edite_le < RECAP_DIRECT_PAS_SEC:
            # Regroupement : la derniere edition a moins d'une minute. Rien
            # n'est perdu -- le recap reste « sale », et le tour de la fin de
            # l'attente envoie la derniere valeur.
            bilan["retenu"] = True
            bilan["reveil"] = self._direct_edite_le + RECAP_DIRECT_PAS_SEC
            vif = vif_histo = False
        elif self._direct_expire_le is not None and now < self._direct_expire_le:
            bilan["reveil"] = self._direct_expire_le
        # Rien a figer, rien de neuf : le tour s'arrete la, sans relire
        # l'historique.
        if not a_finir and not vif:
            return bilan
        cle_auj = aujourdhui.isoformat()
        agg = None
        if vif and not vif_histo:
            # Seul un message a 0 manque : l'historique n'a pas bouge depuis
            # sa derniere lecture (meme generation, aucun numero expire), son
            # bilan du jour vaut toujours.
            connu = self._direct_agg
            if connu is not None and connu[0] == cle_auj and connu[1] == self._direct_gen:
                agg = connu[2]
        for k in [k for k in self._figer_aggs if k < fenetre[0].isoformat()]:
            self._figer_aggs.pop(k, None)
        # Une journee finie deja lue dans ce processus, historique inchange :
        # son bilan vaut toujours. Une journee tenue ouverte par un essai rate
        # (serveur indisponible, salon illisible, trace « a_chercher ») relisait
        # tout l'historique a chaque tour -- 178 lectures sur une panne de 3 h,
        # 11 698 sur 8 jours, pour un bilan qui ne bougeait pas.
        a_lire = [j for j in a_finir if self._agg_fini(j, gen) is None]
        if entrees is None and (a_lire or (vif_histo and a_corriger)
                                or (vif and direct and agg is None)):
            entrees = _histo_cloturer(now)
            if entrees is None:
                return bilan
        if vif:
            # Remis a zero AVANT les editions : un echec pendant ce tour le
            # repose, et l'edition repart au tour suivant.
            self._direct_a_refaire = False
        corrige = False
        for jour in a_voir:
            if jour in a_finir or (vif_histo and jour in a_corriger):
                agg_j = self._agg_fini(jour, gen) if entrees is None else None
                if agg_j is None:
                    agg_j = agreger(entrees, jour, now)
                    self._figer_aggs[jour.isoformat()] = (gen, agg_j)
                corrige |= await self._figer_jour(jour, agg_j, reg, bilan, now)
        if not vif:
            return bilan
        self._direct_gen = gen
        edite = corrige
        zero_echec = False
        if direct:
            if agg is None:
                agg = agreger(entrees, aujourdhui, now)
            self._direct_agg = (cle_auj, gen, agg)
            fiches_auj = reg["jours"].get(cle_auj)
            fiches_auj = fiches_auj if isinstance(fiches_auj, dict) else {}
            zeros = set()
            for gid in sorted(panneaux - set(agg)):
                f = fiches_auj.get(gid)
                if isinstance(f, dict) and f and not _fiche_vide(f):
                    # La fiche du jour compte des numeros (ou des mails) que
                    # l'historique n'a plus (perdu ou purge en cours de
                    # journee) -- message poste OU recap retenu (salon absent,
                    # envoi refuse) : « Pas de SMS » par-dessus effacait un vrai
                    # recap, puis minuit le figeait en « Aucun SMS ». Laisse
                    # tel quel, et dit.
                    self._dire_une_fois(
                        ("sans_historique", cle_auj, gid), log.warning,
                        "numgen: recap du %s (serveur %s) : la fiche du jour compte %s "
                        "numero(s), %s mail(s) que l'historique n'a plus -- laisse tel quel, "
                        "pas de « %s » par-dessus", cle_auj, gid, f.get("numeros", "?"),
                        f.get("mails", 0), RECAP_ZERO_DIRECT)
                    continue
                zeros.add(gid)
            cibles = set(agg) | zeros
            if not vif_histo:
                # Tour reveille par les seuls serveurs sans message du jour
                # (envoi a 0 refuse, retente chaque minute) : l'historique n'a
                # pas bouge, les autres n'ont rien de neuf. Les resynchroniser
                # quand meme, c'etait chaque minute les noms de leurs VA
                # (fetch_member pour un VA parti du serveur : un appel Discord
                # par minute toute la journee).
                cibles &= set(manquants)
            for gid in sorted(cibles):
                r = await self._synchroniser(aujourdhui, gid, agg.get(gid) or _agg_zero(), reg,
                                             bilan, now, final=False)
                # Seules les editions d'un recap a numeros comptent dans le
                # regroupement : la creation du message a 0 (minuit, demarrage)
                # retenait jusqu'a une minute le premier numero du jour, ou la
                # correction de la veille.
                edite |= r == "fait" and gid in agg
                zero_echec |= r == "echec" and gid not in agg
        if edite:
            self._direct_edite_le = now
        if entrees is not None:
            attentes = [_ts(e.get("pris_le")) + DUREE_NUMERO_SEC for e in entrees
                        if _issue(e, now) == "attente"]
            self._direct_expire_le = min(attentes) if attentes else None
        if self._direct_a_refaire or zero_echec:
            bilan["reveil"] = now + RECAP_PAS_SEC
        elif self._direct_expire_le is not None:
            bilan["reveil"] = self._direct_expire_le
        return bilan

    def _agg_fini(self, jour, gen):
        """Le bilan deja lu de la journee finie `jour`, s'il vaut toujours :
        meme generation de l'historique, et aucun numero en attente de son
        code (le temps seul change alors son issue). Sinon None."""
        c = self._figer_aggs.get(jour.isoformat())
        if c is None or c[0] != gen or any(g.get("attente") for g in c[1].values()):
            return None
        return c[1]

    async def _figer_jour(self, jour, agg, reg, bilan, now):
        """Fige le recap d'une journee finie (`agg` : son bilan), serveur par
        serveur. Rend True si un recap DEJA fige a ete corrige (edition comptee
        dans le regroupement)."""
        cle = jour.isoformat()
        jours_reg = reg["jours"]
        # Un message a 0 deja poste que le registre ne connait pas (registre
        # perdu ; reponse d'envoi perdue au dernier tour de la journee) est
        # retrouve dans le salon et fige. S'il n'y en a pas, RIEN n'est
        # poste : un registre perdu aurait fait poster sept « Aucun SMS ».
        # `cherches` : un essai par tour -- une edition refusee ici est
        # retentee au tour suivant, pas une seconde fois dans celui-ci.
        cherches = await self._chercher_zeros(jour, agg, reg, bilan, now)
        fiches = jours_reg.get(cle)
        fiches = fiches if isinstance(fiches, dict) else {}
        # Les messages a 0 postes en direct : figes eux aussi (« Aucun SMS ce
        # jour-là. »), y compris un serveur B a 0 le jour ou A a des numeros --
        # agg seul ne les voyait pas, B restait « en direct » pour toujours.
        zeros = sorted(gid for gid, v in fiches.items()
                       if gid not in agg and _fiche_vide(v) and v.get("messages"))
        a_figer_zeros = [gid for gid in zeros if gid not in cherches]
        # Une fiche A NUMEROS dont le serveur n'a plus aucune activation ce
        # jour-la (historique perdu ou purge) : rien ne peut la refaire -- et
        # surtout pas en « Aucun SMS ». Laissee telle quelle, et dit.
        if agg or zeros:
            for gid, v in sorted(fiches.items()):
                if (gid not in agg and isinstance(v, dict) and not _fiche_vide(v)
                        and not _a_chercher(v) and not _finalise(v)
                        and not v.get("abandonne")):
                    log.warning("numgen: recap du %s (serveur %s) : l'historique n'a plus "
                                "aucune activation de ce serveur ce jour-la -- recap laisse "
                                "tel quel", cle, gid)
                    self._poser_fiche(reg, cle, gid, dict(v, finalise=True, fige=True))
        if not agg and not zeros:
            if cle not in jours_reg:
                # Aucun message a 0 n'est poste apres coup (27/09/2026) :
                # seul un message a 0 deja poste en direct est fige. On le
                # dit, et on le retient.
                log.info("numgen: recap du %s : aucun numero pris ce jour-la, "
                         "rien n'est poste", cle)
                jours_reg[cle] = {}
                self._recap_sauver(reg)
            elif isinstance(jours_reg.get(cle), dict) and not _jour_fini(jours_reg[cle]):
                # Des fiches, mais plus aucune activation ce jour-la
                # (historique perdu ou purge) : rien ne peut les completer.
                # Les traces « a_chercher » restent : leur recherche n'a pas
                # abouti, la journee n'est pas close.
                restes = [(gid, v) for gid, v in jours_reg[cle].items()
                          if isinstance(v, dict) and not _a_chercher(v)
                          and not (_finalise(v) and _fige(v))]
                if restes:
                    log.warning("numgen: recap du %s : l'historique n'a plus aucune activation "
                                "de ce jour -- recap laisse tel quel", cle)
                for gid, v in restes:
                    self._poser_fiche(reg, cle, gid, dict(v, finalise=True, fige=True))
            bilan["vides"].append(cle)
            return False
        attente = sum(g["attente"] for g in agg.values())
        if attente:
            self._dire_une_fois(
                ("attente", cle), log.info,
                "numgen: recap du %s fige a minuit : %d numero(s) attendent encore leur "
                "code (au plus %d min), il sera corrige a leur arrivee",
                cle, attente, DUREE_NUMERO_SEC // 60)
            bilan["attente"].append(cle)
        corrige = False
        jr = jours_reg.get(cle)
        for gid in sorted(set(agg) | set(a_figer_zeros)):
            fiche = jr.get(gid) if isinstance(jr, dict) else None
            fiche = fiche if isinstance(fiche, dict) else {}
            if _fige(fiche) or fiche.get("abandonne"):
                continue
            deja = _finalise(fiche)
            r = await self._synchroniser(jour, gid, agg.get(gid) or _agg_zero(), reg, bilan,
                                         now, final=True)
            corrige |= deja and r == "fait"
        return corrige

    async def _chercher_zeros(self, jour, agg, reg, bilan, now):
        """Cherche, sans rien poster, le message a 0 de chaque serveur du recap
        qui n'a pas de fiche pour cette journee finie, et le fige s'il est
        dans le salon. Rend les serveurs cherches dans ce tour.

        Pas seulement quand le JOUR manque au registre : le message a 0 d'un
        serveur B cree au dernier tour de la journee, reponse d'envoi perdue,
        n'a pas de fiche -- et la fiche d'un serveur A faisait exister le
        jour : B n'etait jamais cherche, « en direct » pour toujours.

        Une recherche qui n'aboutit pas (lecture ratee sans refus net, serveur
        « unavailable » pendant une reconnexion) laisse une trace
        « a_chercher » au registre : la journee n'est pas close (_jour_fini),
        la recherche repart au tour suivant. Sans elle, la veille etait close
        a {} (« aucun numero pris ce jour-la ») sur une seule lecture ratee, et
        son message a 0 restait « en direct » pour toujours."""
        cle = jour.isoformat()
        jours_reg = reg["jours"]
        fiches = jours_reg.get(cle)
        fiches = fiches if isinstance(fiches, dict) else {}
        du_recap = self._serveurs_du_recap()
        # Un serveur « unavailable » : ses salons ne se lisent pas, impossible
        # de savoir s'il a un message a 0 -- il est retente, pas ecarte. Sauf
        # s'il a ete vu disponible HORS du recap dans ce processus, sans fiche
        # dans la fenetre : un serveur sans debrief-day, en reconnexion a
        # minuit, recevait une trace « a_chercher » (« un message a 0 deja
        # poste n'a pas pu etre cherche ») et tenait la veille ouverte jusqu'a
        # son retour -- chaque minuit de plus s'il restait absent des jours.
        plancher = jours_a_recapituler(now)[0].isoformat()
        avec_fiche = {gid for k, jr in jours_reg.items() if k >= plancher and isinstance(jr, dict)
                      for gid in jr}
        indispo = {str(getattr(g, "id", "")) for g in list(getattr(self.bot, "guilds", None) or [])
                   if getattr(g, "unavailable", False)}
        indispo = {gid for gid in indispo
                   if self._recap_connus.get(gid) is not False or gid in avec_fiche}
        traces = {gid for gid, v in fiches.items() if _a_chercher(v)}
        cherches = set()
        for gid in sorted((du_recap | indispo | traces) - set(agg)):
            v = fiches.get(gid)
            if isinstance(v, dict) and v and not _a_chercher(v):
                continue                    # fiche connue : son propre chemin
            cherches.add(gid)
            guild = self._guilde(gid)
            pourquoi = "salon illisible"
            if guild is None:
                # Plus sur ce serveur (il en voit d'autres) : rien a y chercher.
                r = "rien" if self._salon_perdu(None) else "illisible"
                pourquoi = "serveur invisible pour ce bot"
            elif getattr(guild, "unavailable", False):
                r, pourquoi = "illisible", (
                    "serveur indisponible (reconnexion)" if gid in self._recap_connus
                    else "serveur indisponible (reconnexion), pas encore vu disponible depuis "
                         "le demarrage")
            elif gid not in du_recap and not _salons_debrief(guild):
                r = "rien"                  # aucun « debrief-day » ou chercher
            else:
                r = await self._synchroniser(jour, gid, _agg_zero(), reg, bilan, now,
                                             final=True, sans_poster=True)
            jr = jours_reg.get(cle)
            v = jr.get(gid) if isinstance(jr, dict) else None
            if r == "illisible":
                if not _a_chercher(v):
                    self._poser_fiche(reg, cle, gid, {"a_chercher": True})
                self._dire_une_fois(
                    ("a_chercher", cle, gid), log.info,
                    "numgen: recap du %s (serveur %s) : %s -- un message a 0 deja poste ce "
                    "jour-la n'a pas pu etre cherche, la journee n'est pas close : nouvel essai "
                    "au prochain tour", cle, gid, pourquoi)
            elif _a_chercher(v):
                # Lu sans rien y trouver (ou plus rien a lire) : la trace n'a
                # plus lieu d'etre ; un jour sans autre fiche redevient
                # « inconnu », et _figer_jour le dit (« rien n'est poste »).
                jr.pop(gid, None)
                if not jr:
                    jours_reg.pop(cle, None)
                self._recap_sauver(reg)
        return cherches

    def _guilde(self, gid):
        try:
            return self.bot.get_guild(int(gid)) if int(gid) else None
        except (TypeError, ValueError):
            return None

    def _salon_recap(self, guild, fiche, bavard=True):
        """Le salon du recap : celui ou vit deja son message (meme renomme),
        sinon le « debrief-day » du serveur. `bavard=False` : sans le journal
        de salon_debrief (« N salons debrief-day ») -- _zero_manquant passe
        chaque minute."""
        if guild is None:
            par_nom = None
        elif bavard:
            par_nom = salon_debrief(guild)
        else:
            par_nom = (_salons_debrief(guild) or [None])[0]
        cid = fiche.get("salon")
        if not cid or (par_nom is not None and getattr(par_nom, "id", None) == cid):
            return par_nom
        try:
            ch = self.bot.get_channel(int(cid))
        except Exception:                                    # noqa: BLE001
            ch = None
        # Ce serveur-la seulement : le recap d'une agence dans le salon d'une
        # autre, c'est montrer ses VA a qui ne doit pas les voir.
        if ch is not None and getattr(getattr(ch, "guild", None), "id", None) == getattr(
                guild, "id", None):
            return ch
        return par_nom

    async def _retrouver(self, salon, jour, now=None, patient=False):
        """Le message d'un recap de ce jour deja poste par ce bot dans le
        salon, ou None. Le registre n'en a pas trace s'il a ete perdu, ou s'il
        n'a pas pu s'ecrire avant un redemarrage : reposter faisait deux
        messages pour le meme jour. Le message entier, pas son id : un recap a
        0 verifie qu'il ne va pas ecraser des lignes de VA.

        _ILLISIBLE : la lecture a echoue sans refus net (5xx, delai depasse,
        connexion coupee) -- ce n'est PAS « rien trouve ». _figer_jour cloturait
        la veille la-dessus (« aucun numero pris ce jour-la ») et son message a
        0 restait « en direct » pour toujours.

        `patient` (message a 0 : rien d'urgent) : apres une lecture ratee, le
        salon n'est relu qu'au bout de la pause (_relire_apres) -- d'ici la,
        _ILLISIBLE sans appel. Un recap a numeros relit toujours, comme avant
        le message a 0."""
        hist = getattr(salon, "history", None)
        moi = getattr(getattr(self.bot, "user", None), "id", None)
        if hist is None or moi is None:
            return None
        titres = {titre_recap(jour, False), titre_recap(jour, True)}
        # Deja lu en entier dans ce processus sans rien y trouver : ce qu'il a
        # poste depuis, il le sait (registre, _recap_postes). Le message a 0
        # d'un serveur a l'envoi refuse est retente chaque minute : relire le
        # salon a chaque essai, c'etait un appel Discord de plus par minute.
        sid = getattr(salon, "id", None)
        vu = (jour.isoformat(), sid)
        if vu in self._recap_absents:
            return None
        pause = self._relire_apres.get(sid)
        if patient and pause is not None and now is not None and now < pause[0]:
            return _ILLISIBLE
        try:
            async for m in hist(limit=RECAP_RETROUVER):
                if getattr(getattr(m, "author", None), "id", None) != moi:
                    continue
                embs = getattr(m, "embeds", None) or []
                if embs and getattr(embs[0], "title", None) in titres:
                    # Une fois : une edition refusee du message retrouve le
                    # faisait redire chaque minute.
                    self._dire_une_fois(
                        ("retrouve", jour.isoformat(), getattr(salon, "id", None), m.id),
                        log.warning, "numgen: recap du %s retrouve dans #%s (message %s) sans "
                        "trace au registre : il est repris, pas reposte", jour.isoformat(),
                        getattr(salon, "name", "?"), m.id)
                    self._relire_apres.pop(sid, None)
                    self._recap_incertains.discard(vu)
                    return m
            self._recap_absents.add(vu)
            self._relire_apres.pop(sid, None)
            # Lu en entier : un envoi incertain d'avant n'a rien cree.
            self._recap_incertains.discard(vu)
        except Exception as e:                               # noqa: BLE001
            net = _refus_net(e)
            if net:
                # Refus net (salon prive : 403 Missing Access ; salon
                # supprime) : le relire ne changera rien dans ce processus.
                # Il etait relu, sans succes, a chaque essai d'envoi du
                # message a 0, chaque minute toute la journee. Un envoi sans
                # reponse nette l'efface quand meme
                # (_synchroniser) : le message a pu partir.
                self._recap_absents.add(vu)
            elif now is not None:
                delai = (min(RECAP_RELIRE_MAX_SEC, 2 * pause[1]) if pause is not None
                         else float(RECAP_PAS_SEC))
                self._relire_apres[sid] = (now + delai, delai)
            # Une fois par (salon, erreur) : le message a 0 d'un serveur dont
            # l'envoi est refuse est retente chaque minute, et un salon
            # illisible aurait repete cet avertissement toute la journee. Pas
            # par jour : au demarrage, la veille est examinee aussi, et le
            # meme salon illisible se disait deux fois.
            self._dire_une_fois(
                ("illisible", getattr(salon, "id", None), type(e).__name__),
                log.warning, "numgen: recap du %s : messages de #%s illisibles (%s: %s) -- "
                "recherche d'un recap deja poste impossible", jour.isoformat(),
                getattr(salon, "name", "?"), type(e).__name__, e)
            if not net:
                return _ILLISIBLE
        return None

    async def _editer_recap(self, salon, mid, emb, cle, gid, fiche, reg, bilan, repli,
                            a_refaire=True):
        """Edite un message du recap : « ok », « disparu » (a poster a neuf),
        ou « echec » (a retenter au prochain tour).

        `repli` : le message DOIT changer (recap « en direct » a figer). S'il
        ne peut pas etre edite (droits, ou RECAP_FINAL_ESSAIS erreurs de
        suite), le recap final est poste a neuf plutot que de laisser « en
        direct » sur une journee finie. Sinon (journee en cours, correction
        d'un recap deja fige), seul un message DISPARU est reposte : un second
        message pour le meme jour ne se justifie que si le premier n'est plus
        la.

        `a_refaire` : hors repli, un echec fait relire l'historique au tour
        suivant (_direct_a_refaire) pour retenter -- pas pour un message a 0
        en direct (voir _synchroniser)."""
        try:
            await salon.get_partial_message(int(mid)).edit(
                embed=emb, allowed_mentions=discord.AllowedMentions.none())
            return "ok"
        except discord.NotFound:
            log.warning("numgen: recap du %s : le message %s a disparu de #%s -- il est "
                        "poste a neuf", cle, mid, getattr(salon, "name", "?"))
            return "disparu"
        except Exception as e:                               # noqa: BLE001
            nom = type(e).__name__
            if repli:
                essais = int(fiche.get("essais_final") or 0) + 1
                fiche["essais_final"] = essais
                if isinstance(e, discord.Forbidden) or essais >= RECAP_FINAL_ESSAIS:
                    log.warning("numgen: recap du %s : le message %s de #%s ne peut pas etre "
                                "fige (%s: %s, essai %d) -- recap final poste a la place",
                                cle, mid, getattr(salon, "name", "?"), nom, e, essais)
                    return "disparu"
                self._poser_fiche(reg, cle, gid, fiche)
            elif a_refaire:
                self._direct_a_refaire = True
            self._dire_une_fois(
                ("edition", cle, gid, nom), log.error,
                "numgen: recap du %s : edition du message %s refusee dans #%s (%s: %s) -- "
                "nouvel essai au prochain tour", cle, mid, getattr(salon, "name", "?"), nom, e)
            bilan["echecs"].append((cle, gid))
            return "echec"

    async def _synchroniser(self, jour, gid, agg, reg, bilan, now, final, sans_poster=False):
        """Amene le message du recap (jour, serveur) au texte voulu : le cree
        s'il n'existe pas, l'edite sinon. `final` : recap fige de la journee
        (sinon « en direct »). Rend « fait » (message cree ou edite),
        « rien » (deja a jour), « echec » ou « sans_salon ».

        `sans_poster` : n'edite qu'un message deja poste (registre ou salon),
        n'en cree jamais -- un jour a 0 SMS sans message ne part pas apres
        coup."""
        cle = jour.isoformat()
        jours_reg = reg.setdefault("jours", {})
        fiche = (jours_reg.get(cle) or {}).get(gid) if isinstance(jours_reg.get(cle), dict) else None
        fiche = dict(fiche) if isinstance(fiche, dict) else {}
        guild = self._guilde(gid)
        vide = _agg_vide(agg)
        if guild is not None and getattr(guild, "unavailable", False):
            # Reconnexion Discord : discord.py garde les salons en cache, mais
            # lecture, edition et envoi echouent (503) -- et un envoi sans
            # reponse nette a pu partir. Une panne a cheval sur minuit
            # faisait retenter le repli chaque minute : un « Aucun SMS » de
            # la veille par essai. Rien n'est tente tant qu'il est indisponible,
            # comme _chercher_zeros et _salon_perdu : le tour suivant reprend.
            self._dire_une_fois(
                ("indispo", cle, gid), log.info,
                "numgen: recap du %s (serveur %s) : serveur indisponible (reconnexion) -- rien "
                "n'est tente, nouvel essai au prochain tour", cle, gid)
            if not final and not vide:
                self._direct_a_refaire = True
            if sans_poster:
                return "illisible"
            bilan["echecs"].append((cle, gid))
            return "echec"
        salon = self._salon_recap(guild, fiche) if guild is not None else None
        if salon is None and vide:
            ou = (("sur le serveur « %s »" % getattr(guild, "name", gid)) if guild is not None
                  else ("serveur %s invisible pour ce bot" % gid))
            # Un recap a 0 n'est jamais « en attente » : pas de fiche
            # « sans_salon » qui finirait « abandonnee » sept jours plus tard.
            if final and fiche.get("messages") and not _finalise(fiche):
                if self._salon_perdu(guild):
                    # Un message a 0 deja poste dont le salon a ete supprime :
                    # plus rien a figer, la journee est close telle quelle.
                    self._dire_une_fois(
                        ("salon", cle, gid), log.info,
                        "numgen: recap a 0 SMS du %s : aucun salon « %s » (%s) -- le message "
                        "est parti avec son salon, rien a figer, journee close", cle,
                        RECAP_SALON, ou)
                    fiche.update(finalise=True, fige=True, laisse="sans_salon")
                    self._poser_fiche(reg, cle, gid, fiche)
                else:
                    # Serveur indisponible (reconnexion, panne Discord) : ses
                    # salons reviennent. La fiche reste a figer, retentee a
                    # chaque tour comme un recap a numeros ; sortie de la
                    # fenetre, elle est dite « jamais figee », sans alarme.
                    self._dire_une_fois(
                        ("salon_invisible", cle, gid), log.info,
                        "numgen: recap a 0 SMS du %s : salon du message invisible (%s, "
                        "serveur indisponible) -- nouvel essai au prochain tour", cle, ou)
            else:
                self._dire_une_fois(
                    ("salon", cle, gid), log.info,
                    "numgen: recap a 0 SMS du %s : aucun salon « %s » (%s) -- rien n'est "
                    "retenu", cle, RECAP_SALON, ou)
            bilan["sans_salon"].append((cle, gid))
            return "sans_salon"
        if salon is None:
            ou = (("sur le serveur « %s »" % getattr(guild, "name", gid)) if guild is not None
                  else ("serveur %s invisible pour ce bot" % gid) if str(gid) != "0"
                  else "numeros sans serveur connu")
            self._dire_une_fois(
                ("salon", cle, gid), log.warning,
                "numgen: recap du %s : aucun salon « %s » (%s) -- %d numero(s) "
                "en attente de recap, il partira des que le salon existera",
                cle, RECAP_SALON, ou, agg["numeros"] + agg["mails"])
            # Retenu AU REGISTRE : le jour reste « a faire » apres un
            # redemarrage, et le rattrapage le reprend quand le salon existe.
            # « rendus » aussi : un recap retenu d'une journee a numeros rendus
            # seulement passait pour une fiche a 0 (_fiche_vide), et son
            # abandon etait dit « message a 0 jamais fige », en simple info.
            if (not fiche.get("sans_salon")
                    or (fiche.get("numeros"), fiche.get("mails"), fiche.get("rendus"))
                    != (agg["numeros"], agg["mails"], agg.get("rendus", 0))):
                fiche.update(finalise=False, sans_salon=True, numeros=agg["numeros"],
                             mails=agg["mails"], rendus=agg.get("rendus", 0))
                self._poser_fiche(reg, cle, gid, fiche)
            bilan["sans_salon"].append((cle, gid))
            return "sans_salon"
        noms = {}
        for uid, v in agg["vas"].items():
            noms[uid] = await _nom_va(self.bot, guild, uid, v.get("nom"))
        partiel = (reg.get("partiel") or {}).get(cle)
        titre, morceaux = texte_recap(jour, agg, noms, en_direct=None if final else now,
                                      depuis_ts=partiel)
        # La signature ne porte PAS l'heure de mise a jour : sans nouveau
        # chiffre, aucune edition. Elle distingue 0 et non 0 : le premier
        # numero doit EDITER le message « Pas de SMS pour le moment. ».
        signature = (bool(final), bool(agg["numeros"]),
                     tuple(texte_recap(jour, agg, noms, depuis_ts=partiel)[1]))
        msgs = [m for m in (fiche.get("messages") or []) if m]
        deja_final = _finalise(fiche)
        salon_remplace = False
        if msgs and fiche.get("salon") not in (None, getattr(salon, "id", None)):
            # Le salon du message n'existe plus (ou n'est plus visible) : ses
            # messages ne s'editent plus, le recap repart dans le salon actuel
            # -- sauf un jour a 0 fini (plus bas) : rien n'est poste apres coup.
            salon_remplace = True
            if not (vide and final):
                # Une fois : un message a 0 dont l'envoi est refuse dans le
                # nouveau salon est retente chaque minute.
                self._dire_une_fois(
                    ("salon_remplace", cle, gid, fiche.get("salon")), log.warning,
                    "numgen: recap du %s : le salon %s du message n'est plus la -- "
                    "recap poste dans #%s", cle, fiche.get("salon"), getattr(salon, "name", "?"))
            msgs = []
        if msgs and deja_final == bool(final) and self._recap_signes.get((cle, gid)) == signature:
            if final and not agg["attente"] and not fiche.get("fige"):
                fiche["fige"] = True
                self._poser_fiche(reg, cle, gid, fiche)
            return "rien"
        illisible = False
        sid = getattr(salon, "id", None)
        doute = ((cle, sid) in self._recap_incertains
                 or _cle_incertain(cle, sid) in (reg.get("incertains") or {})
                 or (self._registre_neuf_le is not None and cle <= self._registre_neuf_le))
        if not msgs:
            trouve = await self._retrouver(salon, jour, now=now,
                                           patient=vide and (sans_poster or (not final and doute)))
            if trouve is _ILLISIBLE:
                # Lecture ratee sans refus net : pour un recap a numeros, rien
                # ne change (le message part, comme avant) ; un message a 0
                # dans le doute attend une lecture reussie (plus bas) ; pour
                # une recherche (sans_poster, _figer_jour), c'est dit plus bas
                # -- la journee ne doit pas etre close sur une lecture ratee.
                trouve, illisible = None, True
            perdu = _perdu_par_l_historique(trouve, agg) if trouve is not None else ""
            if trouve is not None:
                fiche.pop("a_chercher", None)
                self._incertain_tranche(reg, cle, sid)
            if perdu:
                # Registre ET historique perdus (data/ reparti vide) : le
                # message retrouve montre des numeros, des mails ou des numeros
                # rendus que plus rien ne sait refaire. Le reecrire les
                # effacerait (« Pas de SMS », puis « Aucun SMS » a minuit) : il
                # est laisse tel quel, et le registre le retient
                # (« sans_historique ») pour ne pas le relire chaque minute.
                self._dire_une_fois(
                    ("sans_historique", cle, gid), log.warning,
                    "numgen: recap du %s : le message %s de #%s compte %s que "
                    "l'historique n'a plus -- laisse tel quel, pas de « %s » par-dessus",
                    cle, trouve.id, getattr(salon, "name", "?"), perdu,
                    RECAP_ZERO_FINAL if final else RECAP_ZERO_DIRECT)
                fiche.update(salon=getattr(salon, "id", None), messages=[trouve.id],
                             message=trouve.id, sans_historique=True, finalise=bool(final),
                             fige=bool(final))
                self._poser_fiche(reg, cle, gid, fiche)
                return "rien"
            if trouve is not None:
                msgs = [trouve.id]
                # Dans la fiche des maintenant : si l'edition echoue (erreur
                # passagere a minuit), la fiche retenue porte le message et ses
                # chiffres -- sans eux, une fiche retrouvee a 0 passait pour
                # une fiche « a numeros sans historique » au tour suivant.
                fiche.update(salon=getattr(salon, "id", None), messages=[trouve.id],
                             message=trouve.id, numeros=agg["numeros"], mails=agg["mails"],
                             rendus=agg.get("rendus", 0))
                deja = _retrouve_a_jour(trouve, titre, morceaux, final, agg)
                if deja:
                    # Rien a editer : le message dit deja ce qu'il faut (meme
                    # texte), ou c'est un « Aucun SMS » deja fige d'un jour a
                    # 0 -- son en-tete (« Journée partielle ») en sait plus
                    # qu'un registre perdu. L'editer quand meme, c'etait, sur
                    # une edition refusee, un second « Aucun SMS » (repli).
                    for k in ("sans_salon", "envoi_refuse", "essais_final", "sans_historique"):
                        fiche.pop(k, None)
                    fiche.update(parts=1, le=int(now), finalise=bool(final),
                                 fige=bool(final) and not agg["attente"])
                    self._poser_fiche(reg, cle, gid, fiche)
                    if deja == "identique":
                        self._recap_signes[(cle, gid)] = signature
                    return "rien"
                # Au registre AVANT l'edition : si elle est refusee, le serveur
                # n'est plus « manquant » (_zero_manquant) et le salon n'est
                # plus relu. Sans ca, registre perdu et edition refusee :
                # lecture du salon, essai d'edition et « retrouve » au journal
                # chaque minute.
                self._poser_fiche(reg, cle, gid, fiche)
        if not msgs and vide and final and salon_remplace:
            # Le salon du message a 0 a ete remplace (supprime puis recree) et
            # le jour est fini : le message a disparu avec son salon, et un
            # jour a 0 n'est jamais poste apres coup dans un salon qui ne l'a
            # pas eu. Journee close, dite une fois.
            if not deja_final:
                self._dire_une_fois(
                    ("salon_disparu", cle, gid), log.info,
                    "numgen: recap a 0 SMS du %s : le salon %s du message n'est plus la -- "
                    "rien a figer, rien n'est poste apres coup dans #%s", cle,
                    fiche.get("salon"), getattr(salon, "name", "?"))
                fiche.update(finalise=True, fige=True, laisse="salon_disparu")
                self._poser_fiche(reg, cle, gid, fiche)
            return "rien"
        if not msgs and sans_poster:
            return "illisible" if illisible else "rien"
        if not msgs and vide and not final and illisible and doute:
            # Message a 0 dont le salon n'a pas pu etre relu (5xx, delai
            # depasse) alors qu'un message du jour y est peut-etre deja :
            # registre trouve vide par ce processus, ou envoi sans reponse
            # nette. L'envoyer quand meme, c'etait un second « Pas de SMS » et
            # le premier « en direct » pour toujours (lecture en 503 au premier
            # tour apres un registre perdu ; envoi sans reponse puis relecture
            # ratee). Rien n'est urgent a 0 : le serveur reste « manquant »,
            # l'envoi attend une lecture reussie (pause : _relire_apres).
            # Sans ce doute (registre intact, rien envoye), le message part
            # comme avant : attendre, c'etait relire toute la journee un salon
            # en 503 pour un message que rien ne dit deja la.
            # Relecture refusee NET (salon sans « Lire l'historique ») : elle
            # ne reussira jamais dans ce processus, attendre ne tranche rien --
            # le message part, avec le nonce du message du jour (_nonce_recap) :
            # apres une reponse perdue, Discord rend celui deja cree.
            self._dire_une_fois(
                ("zero_attend", cle, gid), log.info,
                "numgen: recap a 0 SMS du %s : #%s pas relu (lecture ratee) -- un message du "
                "jour y est peut-etre deja, rien n'est envoye avant une relecture reussie",
                cle, getattr(salon, "name", "?"))
            bilan["echecs"].append((cle, gid))
            return "echec"
        # Figer un message « en direct » : repli permis s'il ne s'edite pas.
        repli = bool(final) and not deja_final and bool(msgs)
        embeds = [discord.Embed(title=titre if i == 0 else titre + " (suite)",
                                description=texte, colour=_ROSE)
                  for i, texte in enumerate(morceaux)]
        # Des morceaux en trop (texte raccourci) : vides, pas supprimes -- un
        # message du recap ne disparait jamais du fait du bot.
        embeds += [discord.Embed(title=titre + " (suite)", description="—", colour=_ROSE)
                   for _ in range(len(msgs) - len(morceaux))]
        nouveaux = list(msgs)
        poste = reposte = False
        morts = set()
        # Faux si Discord a rendu, pour un nonce deja vu, un message qui ne
        # porte pas ce texte et qu'il n'a pas ete possible d'editer.
        texte_sur = True
        # Message a 0 en direct : son texte ne bouge pas de la journee (pas
        # d'heure de mise a jour), seul un redemarrage le reedite. Une edition
        # refusee (acces au salon retire) posait _direct_a_refaire : chaque
        # tour relisait tout l'historique et retentait jusqu'a minuit (120
        # lectures, 120 editions sur 120 tours simules). Le prochain
        # evenement, ou minuit, retente -- comme pour un envoi a 0 refuse.
        a_refaire = not (vide and not final)
        for i, emb in enumerate(embeds):
            if i < len(nouveaux):
                r = await self._editer_recap(salon, nouveaux[i], emb, cle, gid, fiche, reg,
                                             bilan, repli, a_refaire=a_refaire)
                if r == "ok":
                    continue
                if r == "echec":
                    return "echec"
                if i >= len(morceaux):
                    morts.add(i)    # morceau en trop disparu : rien a remettre
                    continue
            # Nonce du message logique (_nonce_recap) : renvoye apres une
            # reponse perdue, Discord rend le message deja cree au lieu d'en
            # creer un second. discord.py en met un de lui-meme, mais TIRE AU
            # HASARD a chaque envoi : il ne protege que ses propres renvois
            # sur 5xx, pas celui du tour suivant.
            nonce = _nonce_recap(cle, gid, sid, i, final,
                                 nouveaux[i] if i < len(nouveaux) else None)
            try:
                m = await salon.send(embed=emb, allowed_mentions=discord.AllowedMentions.none(),
                                     nonce=nonce)
            except Exception as e:                           # noqa: BLE001
                if not _refus_net(e):
                    # Pas de refus net de Discord (connexion coupee, 5xx) : le
                    # message a pu etre cree quand meme, seule la reponse s'est
                    # perdue. Le « rien dans ce salon » lu juste avant l'envoi
                    # ne vaut plus : le tour suivant relit le salon et reprend
                    # ce message. Sans ca, un second message du meme jour
                    # partait (message a 0 de minuit, premier numero, recap de
                    # rattrapage -- simule avec ServerDisconnectedError et 503).
                    self._recap_absents.discard((cle, getattr(salon, "id", None)))
                    self._recap_incertains.add((cle, sid))
                    inc = reg.setdefault("incertains", {})
                    if _cle_incertain(cle, sid) not in inc:
                        inc[_cle_incertain(cle, sid)] = int(now)
                        self._recap_sauver(reg)
                if vide and final and isinstance(e, (discord.Forbidden, discord.NotFound)):
                    # Le message a 0 ne se fige pas (edition refusee) et le
                    # repli est refuse POUR DE BON (droits, salon supprime) :
                    # un recap a 0 n'est jamais « en attente », la journee est
                    # close telle quelle -- une fiche retenue finissait
                    # « abandonnee » sept jours plus tard.
                    self._dire_une_fois(
                        ("envoi", cle, gid, type(e).__name__), log.warning,
                        "numgen: recap a 0 SMS du %s non poste dans #%s (%s: %s) -- laisse "
                        "tel quel, rien n'est retenu", cle, getattr(salon, "name", "?"),
                        type(e).__name__, e)
                    fiche.update(finalise=True, fige=True, laisse=type(e).__name__)
                    self._poser_fiche(reg, cle, gid, fiche)
                    bilan["echecs"].append((cle, gid))
                    return "echec"
                if vide and final:
                    # Erreur passagere (Discord 5xx, reseau) : clore la journee
                    # laissait le message a 0 « en direct » pour toujours. La
                    # fiche reste a figer (essais_final garde), retentee au tour
                    # suivant ; sortie de la fenetre, dite « jamais figee ».
                    self._dire_une_fois(
                        ("envoi", cle, gid, type(e).__name__), log.warning,
                        "numgen: recap a 0 SMS du %s : ni edite ni poste dans #%s (%s: %s) -- "
                        "nouvel essai au prochain tour", cle, getattr(salon, "name", "?"),
                        type(e).__name__, e)
                    self._poser_fiche(reg, cle, gid, fiche)
                    bilan["echecs"].append((cle, gid))
                    return "echec"
                # Sans refus net, « non poste » etait faux : le message a pu
                # partir (reponse perdue), et le tour suivant le reprend.
                self._dire_une_fois(
                    ("envoi", cle, gid, type(e).__name__), log.error,
                    "numgen: recap du %s non poste dans #%s (%s: %s) -- nouvel "
                    "essai a chaque tour" if _refus_net(e) else
                    "numgen: recap du %s : envoi dans #%s sans reponse nette (%s: %s) -- le "
                    "message a pu partir : le salon est relu au prochain tour, et le message "
                    "repris s'il y est", cle, getattr(salon, "name", "?"),
                    type(e).__name__, e)
                # Retenu AU REGISTRE, comme un salon absent : rien n'y restait,
                # et apres 7 jours de refus le jour sortait de la fenetre sans
                # un mot -- la boucle d'abandon ne parcourt que le registre.
                # Pas pour un recap a 0 : il n'est jamais « en attente » (a
                # minuit, un jour a 0 sans message ne part pas) ; en direct, le
                # serveur reste « manquant » et l'envoi est retente au tour
                # suivant.
                if not vide and (fiche.get("envoi_refuse") != type(e).__name__
                                 or fiche.get("sans_salon")
                                 or (fiche.get("numeros"), fiche.get("mails"),
                                     fiche.get("rendus"))
                                 != (agg["numeros"], agg["mails"], agg.get("rendus", 0))):
                    fiche.pop("sans_salon", None)
                    fiche.update(envoi_refuse=type(e).__name__, numeros=agg["numeros"],
                                 mails=agg["mails"], rendus=agg.get("rendus", 0))
                    fiche.setdefault("finalise", False)
                    self._poser_fiche(reg, cle, gid, fiche)
                # Un message a 0 refuse n'a pas besoin de « _direct_a_refaire » :
                # le serveur reste « manquant » et l'envoi repart au tour
                # suivant -- sans relire l'historique chaque minute.
                if not final and not vide:
                    self._direct_a_refaire = True
                bilan["echecs"].append((cle, gid))
                return "echec"
            # Le salon a desormais un recap de ce jour : une recherche future
            # (_retrouver) doit le relire, pas se fier au « rien trouve ».
            self._recap_absents.discard((cle, getattr(salon, "id", None)))
            self._incertain_tranche(reg, cle, sid)
            rendu = (getattr(m, "embeds", None) or [None])[0]
            if rendu is not None and _texte_embed(rendu) != _texte_embed(emb):
                # Discord a rendu le message deja cree avec ce nonce (reponse
                # perdue au tour d'avant) : il porte le texte d'alors -- « Pas
                # de SMS » quand le premier numero arrive entre-temps. Remis au
                # texte voulu tout de suite ; sinon la signature ne le dit pas
                # a jour, et le tour suivant (ou minuit) retente.
                r = await self._editer_recap(salon, getattr(m, "id", None), emb, cle, gid,
                                             fiche, reg, bilan, False, a_refaire=a_refaire)
                texte_sur = texte_sur and r == "ok"
            if i < len(nouveaux):
                nouveaux[i] = getattr(m, "id", None)
                reposte = True
            else:
                nouveaux.append(getattr(m, "id", None))
                poste = True
            # Retenu TOUT DE SUITE (registre et memoire) : un tour coupe
            # apres cet envoi ne doit pas le reposter.
            fiche.pop("sans_salon", None)
            fiche.update(salon=getattr(salon, "id", None), messages=list(nouveaux),
                         message=nouveaux[0], numeros=agg["numeros"], mails=agg["mails"],
                         rendus=agg.get("rendus", 0))
            fiche.setdefault("finalise", False)
            self._poser_fiche(reg, cle, gid, fiche)
        nouveaux = [x for i, x in enumerate(nouveaux) if i not in morts]
        for k in ("sans_salon", "envoi_refuse", "essais_final", "sans_historique", "a_chercher"):
            fiche.pop(k, None)
        # « rendus » au registre aussi : une fiche a 0 numero mais avec des
        # numeros rendus n'est pas « vide » -- l'historique perdu, elle ne doit
        # pas etre figee en « Aucun SMS » (_fiche_vide).
        fiche.update(salon=getattr(salon, "id", None), messages=nouveaux, message=nouveaux[0],
                     parts=len(morceaux), le=int(now), numeros=agg["numeros"],
                     mails=agg["mails"], rendus=agg.get("rendus", 0),
                     finalise=bool(final) and texte_sur,
                     fige=bool(final) and texte_sur and not agg["attente"])
        if final and reposte and repli:
            fiche["repli"] = True
        self._poser_fiche(reg, cle, gid, fiche)
        if texte_sur:
            self._recap_signes[(cle, gid)] = signature
        else:
            self._recap_signes.pop((cle, gid), None)
        if poste or reposte:
            bilan["postes"].append((cle, gid))
        else:
            bilan["edites"].append((cle, gid))
        if final and texte_sur and not deja_final:
            bilan["finalises"].append((cle, gid))
            if reposte and repli:
                bilan["replis"].append((cle, gid))
        quoi = ("recap final poste (repli)" if final and reposte and repli
                else "recap final poste" if final and not msgs
                else "recap fige a minuit" if final and not deja_final
                else "recap corrige" if final
                else "recap en direct cree" if not msgs
                else "recap en direct reposte" if reposte
                else None)
        if quoi:
            log.info("numgen: %s du %s dans #%s (%d numero(s), %d message(s))", quoi, cle,
                     getattr(salon, "name", "?"), agg["numeros"], len(nouveaux))
        else:
            log.debug("numgen: recap en direct du %s edite (%d numero(s))", cle, agg["numeros"])
        return "fait"

    def _incertain_tranche(self, reg, cle, sid):
        """L'envoi incertain (jour, salon) est tranche : message retrouve, ou
        envoi abouti (le nonce rend le message deja cree)."""
        self._recap_incertains.discard((cle, sid))
        inc = reg.get("incertains")
        if isinstance(inc, dict) and inc.pop(_cle_incertain(cle, sid), None) is not None:
            if not inc:
                reg.pop("incertains", None)
            self._recap_sauver(reg)

    def _poser_fiche(self, reg, cle, gid, fiche):
        """Ecrit la fiche (jour, serveur) au registre, et la garde en memoire
        des qu'elle porte un message : si le registre ne s'ecrit pas, le
        processus sait quand meme ce qui est parti (pas de doublon)."""
        jr = reg.setdefault("jours", {})
        if not isinstance(jr.get(cle), dict):
            jr[cle] = {}
        ancienne = jr[cle].get(gid)
        if isinstance(ancienne, dict) and _sans_le(ancienne) == _sans_le(fiche):
            # Rien de neuf (message reedite a l'identique au redemarrage) :
            # pas d'ecriture. Avec un registre inecrivable, chacune ajoutait
            # une ERROR -- et l'ecart de « le » avec le disque la faisait
            # retenter chaque minute (_redonner_fiches).
            if fiche.get("messages"):
                self._recap_postes[(cle, gid)] = dict(ancienne)
            return
        jr[cle][gid] = dict(fiche)
        if fiche.get("messages"):
            self._recap_postes[(cle, gid)] = dict(fiche)
        self._recap_sauver(reg)

    def _redonner_fiches(self, reg, depuis):
        """Rend au registre relu les fiches que ce processus connait mieux
        (ecriture ratee) : sans ca, le recap du jour etait reposte au tour
        suivant, ou apres un redemarrage."""
        jr = reg.setdefault("jours", {})
        change = False
        for (cle, gid), fiche in list(self._recap_postes.items()):
            if cle < depuis:
                self._recap_postes.pop((cle, gid), None)
                continue
            if not isinstance(jr.get(cle), dict):
                jr[cle] = {}
            # « le » seul ne compte pas : ce n'est pas un fait a restituer.
            if _sans_le(jr[cle].get(gid)) != _sans_le(fiche):
                jr[cle][gid] = dict(fiche)
                change = True
        if change:
            self._recap_sauver(reg)

    def _recap_sauver(self, reg):
        try:
            _recap_ecrire(reg)
        except Exception as e:                               # noqa: BLE001
            # _recap_postes garde en memoire ce qui est parti : pas de doublon
            # dans ce processus. Au prochain redemarrage, si le registre est
            # toujours inecrivable, le message du jour est retrouve dans le
            # salon (_retrouver) -- sauf s'il a deja defile au-dela.
            log.error("numgen: registre du recap non ecrit (%s: %s) -- risque de "
                      "doublon au prochain redemarrage", type(e).__name__, e)

    # ------------------------------------------------------------ génération
    async def start_sms(self, interaction, service):
        ok, res = await asyncio.to_thread(numgen.get_number, service)
        if not ok:
            await interaction.followup.send(f"❌ {res}", ephemeral=True)
            return
        # Ce parcours (« Autre service » des anciens panneaux) achete aussi :
        # hors de l'historique, ses numeros manquaient au recap sans un mot.
        histo_prise(_actif_ephemere("sms", res, service, interaction),
                    getattr(interaction, "channel", None),
                    getattr(interaction, "user", None))
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
        histo_prise(_actif_ephemere("mail", res, service, interaction),
                    getattr(interaction, "channel", None),
                    getattr(interaction, "user", None))
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
        histo_evenement(view.kind, view.act_id, "code")
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
        # Un salon cree avant que ce bot ne soit dans les droits des tickets
        # lui est ferme : « Missing Access », rien de pose (#carter_izac,
        # 27/09). Le bot principal, qui y est, le lui ouvre d'abord.
        try:
            from cogs.welcome import ouvrir_au_bot_admin
            if await ouvrir_au_bot_admin(ch.id) == "ouvert":
                ch = await self.bot.fetch_channel(ch.id)
        except Exception as e:                              # noqa: BLE001
            log.warning(f"panelnumero: ouverture du salon au bot : {type(e).__name__}: {e}")
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
        # Le panneau se pose quel que soit le nom du salon ; seul le refus de
        # vue depend de lui (voir _prive_par_construction).
        await verrouiller_salon(ch, self.bot, prive=_prive_par_construction(ch))
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        # Les salons prives que ce bot n'a jamais recus ne sont meme pas dans
        # guild.text_channels : 26 salons comptes sur 37, #carter_izac oublie.
        # Le bot principal, qui les voit tous, les lui ouvre d'abord (et pose
        # le panneau dans ceux qu'il vient d'ouvrir).
        ids_vus, ouverts, fermes = [], [], []
        try:
            from cogs.welcome import ouvrir_numeros_au_bot_admin, _bot_principal
            principal = _bot_principal()
            if principal is not None and principal is not self.bot:
                b = await ouvrir_numeros_au_bot_admin(principal, guild.id)
                ids_vus, ouverts, fermes = b["salons"], b["ouverts"], b["rates"]
        except Exception as e:                              # noqa: BLE001
            log.warning(f"panelnumeroall: ouverture des salons : {type(e).__name__}: {e}")
        targets = [c for c in guild.text_channels
                   if _us_norm(c.name).endswith("-numero-mail")]
        connus = {c.id for c in targets}
        for i in ids_vus:
            if i in connus:
                continue
            try:
                targets.append(await self.bot.fetch_channel(i))
            except Exception as e:                          # noqa: BLE001
                log.warning(f"panelnumeroall: salon {i} toujours invisible ({type(e).__name__})")
        if not targets:
            await interaction.followup.send(
                _pourquoi_aucun_salon(guild, self.bot, ("-numero-mail",)),
                ephemeral=True)
            return
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
            # Cibles -numero-mail, privees par construction : le refus de vue
            # est remis (l'ancien verrouillage l'effacait, voir la fonction).
            await verrouiller_salon(ch, self.bot, prive=True)
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
            + f" (sur {len(targets)} salons `-numero-mail`)."
            + (f" · {len(ouverts)} salon(s) ouvert(s) au bot" if ouverts else "")
            + (f"\n⚠️ {len(fermes)} salon(s) impossible(s) à ouvrir au bot : "
               + ", ".join(f"`{n}`" for n in fermes[:5]) if fermes else "")
            + warn
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
    """Ecrit les champs d'un salon. `actif=None` efface l'activation.

    LEVE (OSError) si l'ecriture echoue. safe_json.write ne leve jamais : il
    rend False et imprime « echec ecriture ». Ce retour etait jete : un
    numero paye, jamais inscrit, s'affichait « vide » -- le panneau relisait
    l'ancien registre -- et n'etait ni montre, ni rendu, ni ecoute. Les
    try/except des appelants (rendu du numero inaffichable, `au_registre`)
    ne se declenchaient jamais."""
    d = _salons()
    rec = dict(d.get(str(cid)) or {})
    rec.update(champs)
    d[str(cid)] = rec
    SALONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _safe_json.write(SALONS_FILE, d, indent=2):
        raise OSError("%s non ecrit" % _Path(SALONS_FILE).name)
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


def _code_courant(rec):
    """Le code a montrer pour l'activation EN COURS du salon, ou None.

    « code_de » dit a quelle activation le code appartient. Une ecoute qui
    se reveillait apres un « Autre » ecrivait le code de l'ancien numero
    sous le nouveau : le panneau montrait le numero B avec le code de A.
    Un code d'avant ce champ (pas de « code_de ») reste montre."""
    rec = rec or {}
    code = rec.get("code_valeur")
    if not code:
        return None
    de = rec.get("code_de")
    if de is not None and str(de) != str((rec.get("actif") or {}).get("id")):
        return None
    return code


#: Refus DEFINITIFS du fournisseur a la lecture du code : l'activation
#: n'existe plus, ou la cle ne marche plus. Tout le reste -- « ERR:… »
#: (timeout, coupure), une page HTML de 502, une reponse inconnue -- est
#: passager : le numero vit, son SMS peut arriver au tour suivant.
_ERREURS_DEFINITIVES = ("NO_ACTIVATION", "BAD_KEY", "BANNED", "WRONG_SERVICE", "NO_KEY")


def _erreur_definitive(val) -> bool:
    t = str(val or "").strip()
    if not t or t.startswith("ERR:"):
        return False
    return (t in {numgen._MSG.get(k) for k in _ERREURS_DEFINITIVES}
            or t.split(":")[0] in _ERREURS_DEFINITIVES)


def _rendu_ok(kind, rendu) -> bool:
    """Le fournisseur a-t-il REELLEMENT repris l'activation ?

    SMS : numgen.cancel rend (True, …) seulement sur ACCESS_CANCEL. Mail :
    un dict dont le statut n'est ni 0 ni absent. Le resultat n'etait pas
    lu : un refus passait pour un rendu, et le numero -- paye, toujours
    actif -- sortait du registre."""
    if kind == "mail":
        return isinstance(rendu, dict) and rendu.get("status") not in (0, "0", None)
    return isinstance(rendu, tuple) and len(rendu) >= 1 and bool(rendu[0])


def _raison_rendu(rendu) -> str:
    """Pourquoi un rendu a echoue, en une ligne lisible par le VA."""
    if isinstance(rendu, BaseException):
        return "%s: %s" % (type(rendu).__name__, rendu)
    if isinstance(rendu, tuple) and len(rendu) >= 2:
        return str(rendu[1] or "refus du fournisseur")
    if isinstance(rendu, dict):
        return str(rendu.get("error") or rendu.get("message") or "refus du fournisseur")
    return str(rendu or "pas de réponse du fournisseur")


def _rendu_inutile(raison) -> bool:
    """Le fournisseur ne connait plus l'activation (deja close ou annulee) :
    il n'y a plus rien a rendre, le registre peut l'oublier."""
    t = str(raison or "").strip()
    return (t == numgen._MSG.get("NO_ACTIVATION") or t.startswith("NO_ACTIVATION")
            or t.startswith("STATUS_CANCEL"))


async def _rendre(actif, contexte=""):
    """Rend (annule) une activation chez le fournisseur -> (ok, raison).

    Ne leve jamais ; chaque essai laisse une ligne « numgen: rendu de … »
    au journal, accepte ou refuse, avec la reponse brute."""
    actif = actif or {}
    kind = actif.get("kind") or "sms"
    try:
        if kind == "mail":
            rendu = await asyncio.to_thread(numgen.mail_cancel, actif["id"])
        else:
            rendu = await asyncio.to_thread(numgen.cancel, actif["id"],
                                            actif.get("provider") or "getatext")
    except Exception as e:                                   # noqa: BLE001
        rendu = e
    ok = _rendu_ok(kind, rendu)
    raison = "" if ok else _raison_rendu(rendu)
    if ok:
        log.info("numgen: rendu de %s (%s) : accepte %s", actif.get("valeur"),
                 contexte, rendu)
    else:
        log.warning("numgen: rendu de %s (%s) : REFUSE -- %s (reponse : %r)",
                    actif.get("valeur"), contexte, raison, rendu)
    return ok, raison


async def _finir(actif):
    """Clot l'activation SMS chez le fournisseur, une fois le code ECRIT et
    MONTRE. Un echec se journalise : le code est deja au panneau."""
    actif = actif or {}
    if actif.get("kind") == "mail":
        return
    try:
        r = await asyncio.to_thread(numgen.finish, actif["id"],
                                    actif.get("provider") or "getatext")
        log.info("numgen: activation %s terminee chez le fournisseur : %s",
                 actif.get("id"), r)
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: fin de l'activation %s non confirmee (%s: %s)",
                    actif.get("id"), type(e).__name__, e)


def _membre_proprietaire(itx, channel, par):
    """Le membre a noter a l'historique pour un numero de `par` : le
    cliqueur si c'est lui, sinon le membre du serveur (« Autre » clique par
    un admin : le nom du VA, pas celui de l'admin). None si introuvable --
    le recap retombe alors sur l'id."""
    user = getattr(itx, "user", None)
    if not par or getattr(user, "id", None) == par:
        return user
    try:
        g = getattr(channel, "guild", None)
        return g.get_member(int(par)) if g is not None else None
    except Exception:                                        # noqa: BLE001
        return None


# ==============================================================================
# HISTORIQUE DES NUMEROS ET RECAP DU JOUR (« 📊・debrief-day »)
# ==============================================================================
# Le registre des salons ne garde que l'activation EN COURS, ecrasee a chaque
# prise : impossible d'y lire qui a pris quoi la veille. Le proprietaire veut
# le recap qu'une autre agence recoit chaque nuit (27/09/2026) : « qui a pris
# quoi, qui a echoue ». L'historique garde donc UNE entree par activation,
# completee a chaque evenement du parcours du panneau :
#   pris_le · code_le · fini_le · annule_le · remplace_le (« Autre ») ·
#   rendu_le (numero inaffichable, rendu par le bot) · souci_le (ecoute close
#   par le fournisseur) · expire (aucun code en DUREE_NUMERO_SEC).

#: None : a cote du registre des salons. Un banc qui deplace SALONS_FILE vers
#: un dossier temporaire deplace l'historique avec lui -- sans ca, les bancs
#: deja ecrits (qui ne connaissent que SALONS_FILE) ecrivaient dans data/.
HISTO_FILE = None
RECAP_FILE = None
#: Au-dela, une activation sort de l'historique (il grossit de ~150 par jour).
HISTO_JOURS = 90
#: L'heure du Benin, celle des VA : UTC+1 toute l'annee, sans heure d'ete.
BENIN = timezone(timedelta(hours=1), "Bénin")
#: Le salon, nom SANS decor : le proprietaire l'a nomme « 📊・debrief-day ».
RECAP_SALON = "debrief-day"
#: Un bot arrete (ou un salon absent) plusieurs jours : autant de recaps en
#: retard, dans cette limite.
RECAP_RATTRAPAGE_JOURS = 7
#: « 🔎 K sans code » a partir de K = 4, comme le recap de reference (7, 4,
#: 6, 5 affiches ; 3 ou moins, non).
RECAP_SEUIL_LOUPE = 4
#: Un tour de la boucle au moins toutes les RECAP_PAS_SEC (minuit, numeros qui
#: expirent), et a chaque evenement de l'historique.
RECAP_PAS_SEC = 60
#: Le message du jour est edite au plus une fois par RECAP_DIRECT_PAS_SEC :
#: Discord limite les editions, et une rafale de prises (dix VA qui cliquent
#: en meme temps) ne doit pas faire dix editions. Les evenements de l'attente
#: partent ensemble, a sa fin.
RECAP_DIRECT_PAS_SEC = 60
#: Un message « en direct » qui refuse d'etre fige (erreur passagere) est
#: retente a chaque tour ; apres RECAP_FINAL_ESSAIS echecs, le recap final est
#: poste a neuf plutot que de laisser « en direct » sur une journee finie.
RECAP_FINAL_ESSAIS = 3
#: Messages relus dans le salon pour y retrouver le recap du jour quand le
#: registre n'en a pas trace (perdu, ou inecrivable avant un redemarrage) :
#: le reposter faisait deux messages pour le meme jour.
RECAP_RETROUVER = 50
#: La ligne d'un recap sans aucun numero, a la place des VA et du total :
#: « tu peux pas mettre "27 sept, pas de SMS pour le moment" ? » (27/09/2026).
#: En direct, puis une fois la journee figee a minuit.
RECAP_ZERO_DIRECT = "Pas de SMS pour le moment."
RECAP_ZERO_FINAL = "Aucun SMS ce jour-là."
#: Une lecture du salon ratee sans refus net (5xx, delai depasse) n'est
#: retentee, pour un message a 0, qu'apres une pause qui double a chaque echec
#: (RECAP_PAS_SEC, 2 min, 4 min...) jusqu'a ce plafond : sans pause, un salon
#: en 503 toute une apres-midi etait relu chaque minute. 5 min et pas plus : le
#: message a 0 (et le figeage de la veille) attend la relecture, et un plafond
#: de 30 min le retardait d'autant apres le retour de Discord.
RECAP_RELIRE_MAX_SEC = 300
_JOURS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

_ILLISIBLE = object()
_MACHINE_DITE = []
#: Generation de l'historique : +1 a chaque evenement note (prise, code,
#: annulation, « Autre », rendu...). Le recap en direct la compare a celle de
#: sa derniere lecture : sans evenement, il ne relit pas un fichier de
#: plusieurs Mo chaque minute.
_HISTO_GEN = [0]
#: Fonctions sans argument appelees apres chaque evenement : la boucle du
#: recap s'y inscrit pour se reveiller tout de suite, au lieu d'attendre son
#: tour suivant.
_ECOUTEURS_HISTO = []


def _histo_signaler():
    """Un evenement vient d'etre ecrit dans l'historique. Ne leve jamais :
    le parcours du VA passe avant le recap."""
    _HISTO_GEN[0] += 1
    for f in list(_ECOUTEURS_HISTO):
        try:
            f()
        except Exception as e:                               # noqa: BLE001
            log.warning("numgen: reveil du recap en direct en echec (%s: %s) -- il se "
                        "fera au tour suivant", type(e).__name__, e)


def machine_prod() -> bool:
    """Vrai sur LA machine qui a le droit de poster le recap.

    Meme regle que web_upload._machine_proprietaire (la variable n'est posee
    que dans le .env du VPS) ; recopiee ici plutot qu'importee : importer le
    dashboard depuis un cog, c'est charger 49 000 lignes pour un booleen."""
    if os.environ.get("VA_MACHINE_PROD") == "1":
        return True
    if not _MACHINE_DITE:
        _MACHINE_DITE.append(1)
        log.warning("numgen: machine non proprietaire (VA_MACHINE_PROD absent) : "
                    "recap des numeros NON arme ici")
    return False


def _fichier_voisin(explicite, nom):
    return _Path(explicite) if explicite is not None else _Path(SALONS_FILE).with_name(nom)


def _histo_fichier():
    return _fichier_voisin(HISTO_FILE, "numgen_historique.json")


def _recap_fichier():
    return _fichier_voisin(RECAP_FILE, "numgen_recap.json")


def _lire_dict(p):
    """Le contenu (dict) du fichier, {} s'il n'existe pas.

    Un fichier PRESENT mais illisible (sa copie .prev aussi) n'est pas un
    fichier vide : ecrire par-dessus effacerait des semaines d'historique. Il
    est mis de cote sous un autre nom, et le journal le dit. S'il ne peut pas
    l'etre, on leve : mieux vaut ne rien noter que tout effacer."""
    d = _safe_json.load(p, default=_ILLISIBLE)
    if isinstance(d, dict):
        return d
    if d is _ILLISIBLE and (not p.exists() or p.stat().st_size == 0):
        return {}
    dest = p.with_name("%s.illisible-%d" % (p.name, int(time.time())))
    p.rename(dest)
    log.error("numgen: %s illisible : mis de cote sous %s, un neuf repart",
              p.name, dest.name)
    return {}


def _ts(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _histo_lire() -> list:
    d = _lire_dict(_histo_fichier())
    acts = d.get("activations") or []
    if not isinstance(acts, list):
        raise ValueError("historique : « activations » n'est pas une liste")
    bons = [a for a in acts if isinstance(a, dict)]
    if len(bons) != len(acts):
        log.warning("numgen: historique : %d entree(s) malformee(s) ignoree(s)",
                    len(acts) - len(bons))
    return bons


def _histo_ecrire(acts):
    p = _histo_fichier()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Compact (sans indentation) : ~150 activations par jour sur 90 jours,
    # reecrites a chaque evenement.
    if not _safe_json.write(p, {"activations": acts}, indent=None):
        raise OSError("ecriture de %s refusee" % p.name)


def _nom_de(user) -> str:
    return str(getattr(user, "display_name", None) or getattr(user, "global_name", None)
               or getattr(user, "name", None) or "")


def _actif_ephemere(kind, res, service, itx):
    """L'activation du parcours ephemere, au format du registre des salons."""
    return {"id": str((res or {}).get("id") or ""), "kind": kind, "service": service,
            "provider": (res or {}).get("provider") or "getatext",
            "valeur": (res or {}).get("phone") or (res or {}).get("mail") or "?",
            "par": getattr(getattr(itx, "user", None), "id", 0),
            "pris_le": int(time.time())}


def histo_prise(actif, channel=None, user=None, maintenant=None) -> bool:
    """Note une activation (numero ou mail) qui vient d'etre PAYEE.

    Ne leve jamais : un historique inecrivable ne doit pas empecher un VA
    d'avoir son numero. L'echec va au journal, avec le numero."""
    try:
        now = int(time.time() if maintenant is None else maintenant)
        kind = (actif or {}).get("kind") or "sms"
        entree = {
            "id": str(actif.get("id") or ""),
            # Les mails viennent tous de SMSBower ; le registre des salons leur
            # met « getatext » par defaut, qui serait faux ici.
            "fournisseur": ("smsbower" if kind == "mail"
                            else actif.get("provider") or "getatext"),
            "type": kind,
            "service": actif.get("service") or "ig",
            "numero": actif.get("valeur") or "?",
            "par": actif.get("par") or getattr(user, "id", 0) or 0,
            # Le nom du moment : repli du recap si le VA a quitte le serveur.
            "nom": _nom_de(user),
            "salon": getattr(channel, "id", None),
            "serveur": getattr(getattr(channel, "guild", None), "id", None),
            "pris_le": int(actif.get("pris_le") or now),
        }
        acts = _histo_lire()
        limite = now - HISTO_JOURS * 86400
        gardes = [a for a in acts if _ts(a.get("pris_le")) >= limite]
        if len(gardes) != len(acts):
            log.info("numgen: historique : %d activation(s) de plus de %d jours retiree(s)",
                     len(acts) - len(gardes), HISTO_JOURS)
        gardes.append(entree)
        _histo_ecrire(gardes)
        _histo_signaler()
        return True
    except Exception as e:                                   # noqa: BLE001
        log.exception("numgen: historique : prise de %s NON notee (%s: %s) -- "
                      "absente du recap", (actif or {}).get("valeur"), type(e).__name__, e)
        return False


def histo_evenement(kind, act_id, quoi, maintenant=None, **extra) -> bool:
    """Complete l'activation `act_id` : `quoi` in code, fini, annule, remplace,
    rendu, souci -> champ « <quoi>_le » (le PREMIER garde : un « Nouveau
    code » ne decale pas l'heure du premier). Ne leve jamais."""
    try:
        now = int(time.time() if maintenant is None else maintenant)
        acts = _histo_lire()
        k = kind or "sms"
        cible = None
        for a in reversed(acts):
            if str(a.get("id")) == str(act_id) and (a.get("type") or "sms") == k:
                cible = a
                break
        if cible is None:
            # Un numero pris avant l'historique (deploiement du 27/09/2026),
            # ou dont la prise n'a pas pu s'ecrire : on le dit.
            log.warning("numgen: historique : %s de %s %s sans prise notee -- ignore",
                        quoi, k, act_id)
            return False
        cible.setdefault(quoi + "_le", now)
        cible.update(extra)
        _histo_ecrire(acts)
        _histo_signaler()
        return True
    except Exception as e:                                   # noqa: BLE001
        log.exception("numgen: historique : %s de %s NON note (%s: %s)",
                      quoi, act_id, type(e).__name__, e)
        return False


def _issue(e, maintenant) -> str:
    """rendu | code | attente | sans_code.

    « sans code » = annule, remplace (« Autre ») ou expire sans code. Un code
    passe avant tout : un numero annule APRES son code a servi. Un numero
    rendu par le bot n'a jamais ete vu du VA : a part."""
    if e.get("rendu_le"):
        return "rendu"
    if e.get("code_le"):
        return "code"
    if e.get("annule_le") or e.get("remplace_le") or e.get("expire"):
        return "sans_code"
    if maintenant - _ts(e.get("pris_le")) < DUREE_NUMERO_SEC:
        return "attente"
    return "sans_code"


def _histo_cloturer(maintenant):
    """Les activations, les expirees marquees « expire » au passage (aucun
    evenement ne les ferme : elles meurent chez le fournisseur). None si
    l'historique est illisible -- journalise."""
    try:
        acts = _histo_lire()
    except Exception as e:                                   # noqa: BLE001
        log.error("numgen: historique illisible (%s: %s) : pas de recap", type(e).__name__, e)
        return None
    change = False
    for a in acts:
        if (not a.get("expire") and _issue(a, maintenant) == "sans_code"
                and not (a.get("annule_le") or a.get("remplace_le"))):
            a["expire"] = True
            change = True
    if change:
        try:
            _histo_ecrire(acts)
        except Exception as e:                               # noqa: BLE001
            log.warning("numgen: historique : expirations non ecrites (%s: %s)",
                        type(e).__name__, e)
    return acts


def jour_benin(ts):
    """La date (heure du Benin) d'un horodatage."""
    return datetime.fromtimestamp(_ts(ts), BENIN).date()


def bornes_jour(jour):
    """(debut, fin) du jour, heure du Benin : 00:00 inclus, 00:00 du
    lendemain exclu -- « de 00h00 à 23h59 »."""
    debut = datetime(jour.year, jour.month, jour.day, tzinfo=BENIN).timestamp()
    return debut, debut + 86400


def jours_a_recapituler(maintenant):
    """Les journees finies, a figer, de la plus ancienne a la plus recente :
    la veille des minuit (heure du Benin), et les RECAP_RATTRAPAGE_JOURS - 1
    d'avant."""
    dernier = jour_benin(maintenant) - timedelta(days=1)
    return [dernier - timedelta(days=i)
            for i in range(RECAP_RATTRAPAGE_JOURS - 1, -1, -1)]


def _finalise(fiche) -> bool:
    """Le recap de ce serveur a ete fige (edite ou poste en recap final).
    « complet » : le nom d'avant le recap en direct."""
    return isinstance(fiche, dict) and bool(fiche.get("finalise") or fiche.get("complet"))


def _fige(fiche) -> bool:
    """Fige ET plus aucun numero de la journee n'attend son code : plus rien
    ne peut changer son texte."""
    return isinstance(fiche, dict) and bool(fiche.get("fige") or fiche.get("complet"))


def _jour_fini(jour_reg) -> bool:
    """Tous les serveurs de ce jour sont figes (ou abandonnes) ; {} : jour
    vide, rien a poster. None : jamais vu -- l'historique doit etre relu."""
    return isinstance(jour_reg, dict) and all(
        _finalise(v) or (isinstance(v, dict) and v.get("abandonne"))
        for v in jour_reg.values())


def _jour_a_corriger(jour_reg) -> bool:
    """Un recap fige a minuit dont un numero attendait encore son code."""
    return isinstance(jour_reg, dict) and any(
        _finalise(v) and not _fige(v) and not v.get("abandonne")
        for v in jour_reg.values())


def _refus_net(e) -> bool:
    """Discord a REPONDU par un refus (4xx : droits, salon supprime, requete
    invalide) : rien n'a ete cree. Une connexion coupee, un delai depasse ou
    un 5xx ne disent rien -- le message a pu partir quand meme."""
    if isinstance(e, (discord.Forbidden, discord.NotFound)):
        return True
    try:
        return isinstance(e, discord.HTTPException) and 400 <= int(e.status) < 500
    except (TypeError, ValueError, AttributeError):
        return False


def _agg_zero():
    """Le bilan d'un serveur sans aucune activation ce jour-la (message a 0)."""
    return {"vas": {}, "numeros": 0, "mails": 0, "mails_codes": 0, "rendus": 0,
            "attente": 0}


def _agg_vide(agg) -> bool:
    """Rien a montrer : ni numero, ni mail, ni numero rendu. Un tel recap
    n'est jamais « en attente » : le retenir (salon absent, envoi refuse)
    finissait en « abandonne » sept jours plus tard pour un message qui
    n'avait rien a dire."""
    return not (agg.get("numeros") or agg.get("mails") or agg.get("rendus"))


def _fiche_vide(fiche) -> bool:
    """La fiche d'un message a 0 : rien compte a son dernier envoi.

    « numeros » doit y etre ET valoir 0 : une fiche sans chiffres, ou marquee
    « sans_historique » (vrai recap retrouve que l'historique ne sait plus
    refaire), n'est PAS vide -- un vrai recap ne doit jamais devenir « Aucun
    SMS » parce que l'historique a ete perdu ou purge."""
    return (isinstance(fiche, dict) and "numeros" in fiche and fiche.get("numeros") == 0
            and not fiche.get("mails") and not fiche.get("rendus")
            and not fiche.get("sans_historique"))


def _montre_des_numeros(m) -> bool:
    """Le message (un recap deja poste) affiche au moins une ligne de VA."""
    embs = getattr(m, "embeds", None) or []
    desc = str(getattr(embs[0], "description", "") or "") if embs else ""
    return any(ligne.startswith("• ") for ligne in desc.split("\n"))


def _message_a_zero(m) -> bool:
    """Le message (un recap deja poste) est un PUR message a 0 : apres
    l'en-tete et la ligne vide, rien que « Pas de SMS pour le moment. » ou
    « Aucun SMS ce jour-là. » -- ni VA, ni total, ni mails, ni rendus."""
    embs = getattr(m, "embeds", None) or []
    if len(embs) != 1:
        return False
    lignes = str(getattr(embs[0], "description", "") or "").split("\n")
    return lignes[1:] in (["", RECAP_ZERO_DIRECT], ["", RECAP_ZERO_FINAL])


def _retrouve_a_jour(m, titre, morceaux, final, agg) -> str:
    """Le recap A 0 retrouve `m` (registre perdu) n'a pas a etre edite :
    « identique » (meme titre, meme texte), « fige » (un « Aucun SMS » deja
    fige, pour une journee finie qui est toujours a 0), sinon "".

    Un recap a numeros garde le chemin d'avant (toujours edite, repli si
    l'edition est refusee) : le changer est une autre decision."""
    embs = getattr(m, "embeds", None) or []
    if not _agg_vide(agg) or not embs or getattr(embs[0], "title", None) != titre:
        return ""
    if (len(embs) == 1 and len(morceaux) == 1
            and str(getattr(embs[0], "description", "") or "") == morceaux[0]):
        return "identique"
    if final and _message_a_zero(m):
        return "fige"
    return ""


def _nonce_recap(cle, gid, salon_id, i, final, remplace):
    """Le nonce d'un envoi du recap : le meme pour le meme message logique
    (jour, serveur, salon, morceau, en direct ou fige, message remplace). Avec
    un nonce, discord.py demande enforce_nonce : un envoi qui reprend celui
    d'un message cree par le bot dans les minutes d'avant rend ce message au
    lieu d'en creer un second -- apres une reponse perdue, c'est le seul
    moyen de le reprendre quand le salon ne se relit pas (« Lire
    l'historique » retire : 2 messages du jour, le premier « en direct »
    pour toujours). Le repli (message « en direct » remplace) et un
    message disparu reposte portent l'id du message remplace : jamais le
    nonce du message d'origine -- Discord refuse (NotFound) le nonce d'un
    message supprime peu avant, et rendrait sinon le message en direct."""
    brut = "recap|%s|%s|%s|%d|%d|%s" % (cle, gid, salon_id, int(i), int(bool(final)),
                                        remplace or "")
    return int(hashlib.sha1(brut.encode("utf-8")).hexdigest()[:15], 16)


def _texte_embed(emb):
    """(titre, description) d'un embed, sans les blancs de bord que Discord
    peut retirer : un message rendu identique ne doit pas etre reedite."""
    return (str(getattr(emb, "title", None) or "").strip(),
            str(getattr(emb, "description", None) or "").strip())


def _cle_incertain(cle, sid):
    """La cle d'un envoi incertain au registre (« incertains ») : jour|salon."""
    return "%s|%s" % (cle, sid)


def _sans_le(fiche):
    """La fiche sans « le » (heure du dernier passage, jamais relue) : deux
    fiches qui ne different que par elle disent la meme chose. Au redemarrage,
    le message a 0 est reedite a l'identique et seul « le » changeait -- avec
    un registre inecrivable, une ERROR chaque minute jusqu'a minuit."""
    return {k: v for k, v in fiche.items() if k != "le"} if isinstance(fiche, dict) else fiche


def _a_chercher(fiche) -> bool:
    """Trace posee par _figer_jour quand le salon d'un serveur du recap n'a
    pas pu etre lu (5xx, delai depasse, serveur indisponible) : un message a 0
    de ce jour-la y est peut-etre, la journee n'est pas close."""
    return (isinstance(fiche, dict) and bool(fiche.get("a_chercher"))
            and not fiche.get("messages") and not _finalise(fiche))


def _perdu_par_l_historique(m, agg) -> str:
    """Ce que montre le recap retrouve `m` et que le bilan de l'historique
    (`agg`) n'a plus : « des numeros », « des mails », « des numeros
    rendus » -- ou "" si le reecrire ne perd rien.

    Une seule regle pour « ce message a-t-il du contenu », alignee sur
    _fiche_vide : la version d'avant ne voyait que les lignes de VA, et un
    recap « 📧 2 mail(s) » ou « ↩️ 1 numéro(s) rendu(s) » retrouve apres la
    perte de data/ etait ecrase par « Pas de SMS », puis « Aucun SMS »."""
    if _message_a_zero(m):
        return ""
    embs = getattr(m, "embeds", None) or []
    lignes = [ligne for e in embs
              for ligne in str(getattr(e, "description", "") or "").split("\n")]
    perdu = []
    if not agg.get("numeros") and (
            _montre_des_numeros(m)
            or any(ligne.startswith("Total : ") and not ligne.startswith("Total : 0 ")
                   for ligne in lignes)):
        perdu.append("des numeros")
    if not agg.get("mails") and any(ligne.startswith("📧") for ligne in lignes):
        perdu.append("des mails")
    if not agg.get("rendus") and any(ligne.startswith("↩️") for ligne in lignes):
        perdu.append("des numeros rendus")
    if not perdu and _agg_vide(agg):
        # Ni un pur message a 0, ni une ligne reconnue : un texte que ce code
        # ne sait pas relire. « Pas de SMS » par-dessus pourrait effacer un
        # vrai recap -- dans le doute, on n'y touche pas.
        perdu.append("un recap")
    return ", ".join(perdu)


def agreger(entrees, jour, maintenant):
    """{serveur: {vas: {uid: {n, c, sans, attente, nom}}, numeros, mails,
    mails_codes, rendus, attente}} pour les activations PRISES ce jour-la."""
    debut, fin = bornes_jour(jour)
    out = {}
    for e in entrees:
        t = _ts(e.get("pris_le"))
        if not (debut <= t < fin):
            continue
        g = out.setdefault(str(e.get("serveur") or 0), _agg_zero())
        issue = _issue(e, maintenant)
        if issue == "attente":
            g["attente"] += 1
        if issue == "rendu":
            g["rendus"] += 1
            continue
        if (e.get("type") or "sms") == "mail":
            g["mails"] += 1
            g["mails_codes"] += issue == "code"
            continue
        va = g["vas"].setdefault(str(e.get("par") or 0),
                                 {"n": 0, "c": 0, "sans": 0, "attente": 0, "nom": ""})
        va["n"] += 1
        g["numeros"] += 1
        if issue == "code":
            va["c"] += 1
        elif issue == "sans_code":
            va["sans"] += 1
        else:
            va["attente"] += 1
        if e.get("nom"):
            va["nom"] = e["nom"]
    return out


def _decouper(lignes, limite):
    """Des morceaux de `limite` signes au plus, coupes ENTRE deux lignes."""
    morceaux, cur = [], ""
    for ligne in lignes:
        if len(ligne) > limite:
            ligne = ligne[: limite - 1] + "…"
        cand = ligne if not cur else cur + "\n" + ligne
        if len(cand) > limite and cur:
            morceaux.append(cur.strip("\n"))
            cur = ligne
        else:
            cur = cand
    if cur.strip("\n"):
        morceaux.append(cur.strip("\n"))
    return morceaux


def titre_recap(jour, en_direct=False):
    titre = "📊 Récap numéros SMS — %s %s" % (_JOURS_FR[jour.weekday()],
                                              jour.strftime("%d/%m"))
    return titre + " · en direct" if en_direct else titre


def texte_recap(jour, agg, noms, limite=4096, en_direct=None, depuis_ts=None):
    """(titre, [descriptions]) du recap d'un serveur ; plusieurs descriptions
    si le texte depasse `limite` (4096 : la description d'un embed).

    `en_direct` : l'horodatage de la mise a jour, pour le message de la
    journee en cours (titre « · en direct ») ; None pour le recap final. Les
    lignes des VA, le total et les mails sont les memes dans les deux."""
    titre = titre_recap(jour, en_direct is not None)
    # `depuis_ts` : la journee de la mise en route n'est suivie que depuis
    # cette heure-la -- l'annoncer « complete » ou « depuis 00h00 » mentirait.
    debut = (datetime.fromtimestamp(_ts(depuis_ts), BENIN).strftime("%Hh%M")
             if depuis_ts else "00h00")
    if en_direct is None:
        entete = ("Journée complète : de 00h00 à 23h59, heure du Bénin." if not depuis_ts
                  else "Journée partielle : de %s à 23h59, heure du Bénin." % debut)
    elif _agg_vide(agg):
        # A 0 (ni numero, ni mail, ni rendu), pas d'heure de mise a jour : le
        # message n'est edite qu'au premier numero, et « mis à jour à 09h05 »
        # lu a 23h faisait croire que le recap s'etait arrete a 09h05 --
        # l'inquietude meme du proprietaire (27/09/2026). « Pas de SMS pour
        # le moment. » dit deja qu'il suit.
        entete = "En cours : depuis %s, heure du Bénin." % debut
    else:
        # L'heure de la derniere mise a jour : sans elle, un message qui ne
        # bouge pas (aucun numero depuis une heure) ne dit pas s'il suit.
        entete = "En cours : depuis %s, heure du Bénin — mis à jour à %s." % (
            debut, datetime.fromtimestamp(_ts(en_direct), BENIN).strftime("%Hh%M"))
    lignes = [entete, ""]

    def nom(uid):
        return discord.utils.escape_markdown(str(noms.get(uid) or uid))[:80]

    if agg["numeros"]:
        vas = sorted(agg["vas"].items(),
                     key=lambda kv: (-kv[1]["n"], -kv[1]["c"], nom(kv[0]).lower()))
        for uid, v in vas:
            pct = int(v["c"] * 100 / v["n"] + 0.5) if v["n"] else 0
            ligne = "• %s — %d numéro(s) · %d code%s (%d %%)" % (
                nom(uid), v["n"], v["c"], "s" if v["c"] > 1 else "", pct)
            if v["sans"] >= RECAP_SEUIL_LOUPE:
                ligne += " 🔎 %d sans code" % v["sans"]
            lignes.append(ligne)
        lignes += ["", "Total : %d numéro(s)" % agg["numeros"]]
    else:
        # « Même là, il y a 0 SMS : tu peux pas mettre "27 sept, pas de SMS
        # pour le moment" ? » (proprietaire, 27/09/2026). A 0, un blanc puis
        # « Total : 0 numéro(s) » ne disait pas si le recap suivait : une
        # phrase a la place (la date est dans le titre). Mails et rendus
        # restent en dessous, comme apres le total.
        lignes.append(RECAP_ZERO_DIRECT if en_direct is not None else RECAP_ZERO_FINAL)
    if agg.get("mails"):
        lignes.append("📧 %d mail(s)" % agg["mails"])
    if agg.get("rendus"):
        lignes.append("↩️ %d numéro(s) rendu(s) par le bot : impossibles à "
                      "afficher, remboursés" % agg["rendus"])
    return titre, _decouper(lignes, limite)


def _salons_debrief(guild):
    """Les salons « debrief-day » du serveur, quel que soit leur decor, sans
    rien journaliser : serveur_du_recap les compte a CHAQUE tour (chaque
    minute), et le « %d salons » de salon_debrief aurait noye le journal.

    Le tiret de tete est retire aussi : Discord change les espaces d'un salon
    texte en tirets, et « 📊 debrief-day » tape par le proprietaire devient
    « 📊-debrief-day », dont nom_sans_decor garde le tiret (« -debrief-day ») :
    le recap restait bloque sur « aucun salon », puis abandonne."""
    from cogs.welcome import nom_sans_decor
    return [c for c in (getattr(guild, "text_channels", None) or [])
            if nom_sans_decor(getattr(c, "name", "")).lstrip("-_") == RECAP_SALON]


def serveur_du_recap(guild) -> bool:
    """Le serveur recoit son message du jour MEME A 0 SMS : il a un salon
    « debrief-day » ET au moins un panneau numeros (salon -numero-mail, meme
    test que _prive_par_construction).

    « Même là, il y a 0 SMS : tu peux pas mettre "27 sept, pas de SMS pour le
    moment" ? » (27/09/2026). Un serveur sans panneau numeros ne prend aucun
    numero : un « Pas de SMS » chaque jour dans son debrief serait du bruit."""
    if not _salons_debrief(guild):
        return False
    return any(_prive_par_construction(c) for c in (getattr(guild, "text_channels", None) or []))


def salon_debrief(guild):
    """Le salon « debrief-day » du serveur, quel que soit son decor (regle de
    nom : _salons_debrief)."""
    vus = _salons_debrief(guild)
    if len(vus) > 1:
        log.info("numgen: %d salons « %s » sur %s : le premier (#%s) recoit le recap",
                 len(vus), RECAP_SALON, getattr(guild, "name", "?"), vus[0].name)
    return vus[0] if vus else None


async def _nom_va(bot, guild, uid, note=""):
    """Le nom affiche du VA sur le serveur ; repli : son nom d'utilisateur,
    le nom note a la prise (il a quitte le serveur), puis l'identifiant."""
    try:
        i = int(uid)
    except (TypeError, ValueError):
        return str(note or uid)
    m = None
    if guild is not None:
        get_m = getattr(guild, "get_member", None)
        m = get_m(i) if get_m else None
        if m is None and getattr(guild, "fetch_member", None) is not None and i:
            try:
                m = await guild.fetch_member(i)
            except Exception:                                # noqa: BLE001
                m = None
    if m is not None and getattr(m, "display_name", None):
        return m.display_name
    get_u = getattr(bot, "get_user", None)
    u = get_u(i) if (get_u and i) else None
    if u is not None and getattr(u, "name", None):
        return u.name
    return str(note or i)


def _recap_lire():
    """Le registre du recap, ou None s'il est illisible (journalise) : sans
    lui, impossible de savoir ce qui est deja parti."""
    try:
        return _lire_dict(_recap_fichier())
    except Exception as e:                                   # noqa: BLE001
        log.error("numgen: registre du recap illisible (%s: %s) : pas de recap",
                  type(e).__name__, e)
        return None


def _recap_ecrire(reg):
    limite = (datetime.now(BENIN).date() - timedelta(days=HISTO_JOURS)).isoformat()
    jours = reg.get("jours") or {}
    for cle in [c for c in jours if c < limite]:
        jours.pop(cle, None)
    p = _recap_fichier()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not _safe_json.write(p, reg, indent=2):
        raise OSError("ecriture de %s refusee" % p.name)


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

    def __init__(self, cog, quoi, act_id=None, code_vu=None):
        super().__init__(timeout=60)
        self.cog, self.quoi = cog, quoi
        # L'activation que la question NOMME : « Oui » n'agit que sur elle.
        self.act_id = act_id
        # Le code visible quand la question a ete posee (None : aucun). Un
        # code arrive depuis, « Oui » ne change rien (action_salon).
        self.code_vu = code_vu

    @discord.ui.button(label="Oui", emoji="✅", style=discord.ButtonStyle.danger)
    async def oui(self, itx: discord.Interaction, btn: discord.ui.Button):
        self.stop()
        await itx.response.edit_message(content="👌", view=None)
        await self.cog.action_salon(itx, self.quoi, attendu=self.act_id,
                                    code_vu=self.code_vu)

    @discord.ui.button(label="Non", style=discord.ButtonStyle.secondary)
    async def non(self, itx: discord.Interaction, btn: discord.ui.Button):
        self.stop()
        await itx.response.edit_message(content="Rien n'a changé.", view=None)

    async def on_error(self, itx: discord.Interaction, error: Exception, item):
        # Sans ca, une exception apres « 👌 » (registre inecrivable...) ne
        # laissait au VA que ce pouce, et une trace hors du journal numgen.
        log.exception("numgen: erreur a la confirmation « %s » dans #%s", self.quoi,
                      getattr(getattr(itx, "channel", None), "name", "?"), exc_info=error)
        await _ephemere(itx, "❌ Erreur : %s" % (str(error)[:300] or type(error).__name__))


async def _confirmer_ou_refuser(itx, cog, quoi) -> bool:
    """Pour « Autre » et « Annuler » : refus si le numero est a quelqu'un
    d'autre, sinon une confirmation visible du seul cliqueur.

    Rend True quand il n'y a RIEN a confirmer (aucun numero en cours) : le
    clic est alors differe, et l'appelant redessine le panneau."""
    ch = getattr(itx, "channel", None)
    rec = _salon(getattr(ch, "id", 0)) if ch else {}
    actif = rec.get("actif")
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
                                    view=_ConfirmerView(cog, quoi, act_id=actif.get("id"),
                                                        code_vu=_code_courant(rec)),
                                    ephemeral=True)
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
    # Seulement le code de CE numero (code_de) : jamais celui du precedent.
    code = _code_courant(rec)
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


async def _chercher_panneau(channel, moi, sauf=()):
    """Le panneau deja la, quand le registre ne le connait pas (data/ reparti
    de zero) ou vise un message disparu : dans les epingles (l'ancien l'etait)
    puis l'historique. Un panneau V2 passe avant un ancien ; `sauf` : des
    identifiants deja essayes (disparus).

    L'historique est lu sur FENETRE_PANNEAU messages, arret au premier V2 :
    le V2 n'est plus epingle, et avec 50 messages seulement, un salon ou le
    VA avait ecrit davantage recevait un second panneau -- que le menage
    (100 messages) ne retirait pas toujours."""
    exclus = set()
    for x in sauf or ():
        try:
            exclus.add(int(x))
        except (TypeError, ValueError):
            pass
    anciens = []
    try:
        for m in await channel.pins():
            f = est_panneau_numero(m, moi)
            if getattr(m, "id", None) in exclus or not f:
                continue
            if f == "v2":
                return m
            anciens.append(m)
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: epingles de #%s illisibles (%s: %s)",
                    getattr(channel, "name", "?"), type(e).__name__, e)
    try:
        async for m in channel.history(limit=FENETRE_PANNEAU):
            f = est_panneau_numero(m, moi)
            if getattr(m, "id", None) in exclus or not f:
                continue
            if f == "v2":
                return m
            anciens.append(m)
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: historique de #%s illisible (%s: %s)",
                    getattr(channel, "name", "?"), type(e).__name__, e)
    return anciens[0] if anciens else None


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
    cible, fmt, origine = None, None, None
    if format_vu == "v2":
        cible, fmt, origine = vu.id, "v2", "clique"
    elif enregistre:
        cible, fmt, origine = enregistre, ("v2" if rec.get("v2") else "ancien"), "registre"
    elif format_vu == "ancien":
        cible, fmt, origine = vu.id, "ancien", "clique"
    else:
        trouve = await _chercher_panneau(channel, moi)
        if trouve is not None:
            cible, fmt = trouve.id, est_panneau_numero(trouve, moi)
            origine = "retrouve"
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
    essayes = set()
    while cible:
        essayes.add(int(cible))
        try:
            await _appliquer_panneau(channel, cible, fmt, vue, nom, bilan)
            pose = int(cible)
            break
        except discord.NotFound:
            log.info("numgen: panneau %s de #%s introuvable", cible, nom)
            if origine != "registre":
                break
            # Le panneau ENREGISTRE a disparu -- /resetpanels le supprime, et
            # l'ancien _ensure_num_panel en reposait un autre, epingle, hors
            # registre. Poster un neuf laissait cet autre en place (bouton
            # actif : un doublon), et echouait tout court dans un salon
            # verrouille ou le bot ne peut plus poster. On prend donc le
            # panneau clique, sinon celui qu'on retrouve, et on le convertit.
            origine = "repli"
            if format_vu and int(vu.id) not in essayes:
                alt = vu
            else:
                alt = await _chercher_panneau(channel, moi, sauf=essayes)
            if alt is None:
                break
            cible, fmt = alt.id, est_panneau_numero(alt, moi)
            log.info("numgen: panneau enregistre de #%s disparu : le message %s (%s) "
                     "prend sa place", nom, cible, fmt)
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
            break
    if pose is None and essayes:
        log.info("numgen: aucun panneau utilisable dans #%s : un neuf est pose", nom)
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
    if format_vu and int(vu.id) != pose:
        # Le panneau clique n'est pas celui retenu : il part par son
        # identifiant. Sans ca, seul le menage (borne a une fenetre de
        # l'historique) pouvait le retirer, et il gardait ses boutons actifs.
        a_virer.add(int(vu.id))
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
    # Un autre panneau NUMERO (le notre, V2 ou ancien) part TOUJOURS, meme
    # sans `menage`, sur toute la fenetre de recherche : c'etait le doublon
    # qui survivait au-dela des 100 derniers messages.
    vires = 0
    try:
        async for vieux in channel.history(limit=FENETRE_PANNEAU):
            double = est_panneau_numero(vieux, moi) if vieux.id != pose else None
            if not double and not (menage and getattr(vieux.author, "bot", False)
                                   and vieux.id != pose):
                continue
            try:
                await vieux.delete()
                vires += 1
                if double:
                    log.info("numgen: panneau en double %s (%s) retire de #%s",
                             vieux.id, double, nom)
                await asyncio.sleep(0.3)
            except discord.NotFound:
                pass
            except Exception as e:                           # noqa: BLE001
                log.warning("numgen: message %s de #%s non supprime (%s: %s)",
                            getattr(vieux, "id", "?"), nom, type(e).__name__, e)
    except Exception as e:                                   # noqa: BLE001
        log.warning("numgen: menage de #%s : %s", nom, e)
    if vires:
        bilan["vires"] += vires
        log.info("numgen: %d message(s) de bot en trop retire(s) de #%s", vires, nom)
    return True


async def _appliquer_panneau(channel, cible, fmt, vue, nom, bilan):
    """Met la vue sur le message `cible` : edition d'un panneau V2, ou
    CONVERSION d'un ancien (texte et embed retires, l'icone jointe). Leve
    discord.NotFound si le message n'existe plus, et toute autre erreur
    telle quelle : c'est poser_panneau qui decide de la suite."""
    if fmt == "v2":
        try:
            await _editer_v2(channel, cible, vue)
        except discord.NotFound:
            raise
        except Exception as e1:                              # noqa: BLE001
            if not vue.icone:
                raise
            # Une vignette dont la piece jointe manque est refusee : on la
            # renvoie, une fois.
            log.warning("numgen: panneau de #%s refuse (%s: %s) : nouvel essai avec "
                        "l'icone jointe", nom, type(e1).__name__, e1)
            await _editer_v2(channel, cible, vue, joindre=True)
        return
    kw = {"content": None, "embed": None, "view": vue}
    f = _fichier_icone() if vue.icone else None
    if f is not None:
        kw["attachments"] = [f]
    await channel.get_partial_message(int(cible)).edit(**kw)
    bilan["converti"] = True
    log.info("numgen: panneau de #%s converti au format V2 (message %s)", nom, cible)


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
        # Le panneau EST a jour : un drapeau d'icone non note ne doit pas
        # le faire passer pour inaffichable (un achat serait alors rendu).
        try:
            _salon_ecrire(channel.id, icone=True)
        except Exception as e:                               # noqa: BLE001
            log.warning("numgen: icone de #%s jointe mais non notee au registre (%s: %s)",
                        nom, type(e).__name__, e)
    return True


def _prive_par_construction(channel) -> bool:
    """Un salon -numero-mail est cree PRIVE (create_us_tickets : @everyone
    sans la vue) : /panelnumero y remet ce refus de vue, ce qui repare les
    salons que l'ancien verrouillage avait rendus publics. Un salon d'un
    autre nom (sms-email d'un autre serveur) garde sa visibilite."""
    from cogs.welcome import _us_norm
    return _us_norm(getattr(channel, "name", "") or "").endswith("-numero-mail")


async def verrouiller_salon(channel, bot, prive=False):
    """Le salon devient une vitrine : seul le bot y ecrit.

    Le VA garde la LECTURE et les boutons — une interaction n'est pas un
    message. Sans ca, un salon qui ne doit contenir que le panneau se
    remplissait de conversations, et le panneau se retrouvait en haut,
    hors de vue.

    Les overwrites existants sont COMPLETES, jamais remplaces. L'appel
    `set_permissions(@everyone, send_messages=False)` construisait un
    overwrite neuf qui REMPLACAIT celui du salon : le refus de vue pose a la
    creation des tickets disparaissait, et chaque -numero-mail devenait
    visible de tout membre (numeros et codes des autres, « Prendre un
    numéro » dans le salon d'un autre). `prive=True` (salons -numero-mail,
    prives par construction) remet ce refus de vue : il repare les salons
    deja touches.

    Le VA du ticket a un overwrite MEMBRE qui autorise l'envoi, et qui
    l'emporte sur le refus @everyone : « seul le bot ecrit » ne s'appliquait
    pas a la seule personne presente. Chaque overwrite membre (hors bots)
    qui autorise l'envoi est donc passe a « refuse », sa vue et son
    historique gardes. Rend True si @everyone est verrouille ; chaque membre
    non modifie est dit au journal.
    """
    g = getattr(channel, "guild", None)
    nom = getattr(channel, "name", "?")
    if g is None:
        return False
    raison = "Salon numero/mail : seul le bot y ecrit"
    try:
        ow = channel.overwrites_for(g.default_role)
        ow.send_messages = False
        if prive:
            ow.view_channel = False
        await channel.set_permissions(g.default_role, overwrite=ow, reason=raison)
    except Exception as e:                                   # noqa: BLE001
        log.warning("verrouiller_salon #%s : @everyone non verrouille (%s: %s)",
                    nom, type(e).__name__, e)
        return False
    moi = getattr(getattr(bot, "user", None), "id", None)
    bloques, rates = 0, []
    try:
        cibles = list((getattr(channel, "overwrites", None) or {}).items())
    except Exception as e:                                   # noqa: BLE001
        log.warning("verrouiller_salon #%s : overwrites illisibles, membres non bloques "
                    "(%s: %s)", nom, type(e).__name__, e)
        return True
    for cible, ow_m in cibles:
        # Les roles (staff…) ne sont pas touches ; un role hors cache arrive
        # en Object de type Role.
        if (isinstance(cible, discord.Role) or getattr(cible, "type", None) is discord.Role
                or ow_m.send_messages is not True):
            continue
        try:
            membre = cible
            if not isinstance(membre, discord.Member):
                # Membre hors cache : discord.py rend un Object, que
                # set_permissions refuse (ni Member ni Role).
                get_m = getattr(g, "get_member", None)
                membre = get_m(cible.id) if get_m else None
                if membre is None:
                    membre = await g.fetch_member(cible.id)
            # Les bots (celui-ci, le principal) doivent pouvoir poster et
            # redessiner leurs panneaux.
            if getattr(membre, "bot", False) or getattr(membre, "id", None) == moi:
                continue
            ow_m.send_messages = False
            await channel.set_permissions(membre, overwrite=ow_m, reason=raison)
            bloques += 1
        except Exception as e:                               # noqa: BLE001
            rates.append("%s (%s)" % (getattr(cible, "id", "?"), type(e).__name__))
    if rates:
        log.warning("verrouiller_salon #%s : %d membre(s) peuvent encore ecrire : %s",
                    nom, len(rates), ", ".join(rates))
    if bloques:
        log.info("verrouiller_salon #%s : %d membre(s) ne peuvent plus y ecrire", nom, bloques)
    return True


async def setup(bot):
    await bot.add_cog(NumerosCog(bot))
