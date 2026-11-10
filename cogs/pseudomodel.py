# -*- coding: utf-8 -*-
"""Les rôles de model de You FR : le pseudo (« yous1m (AMELIA) ») et le
salon 🗓️・répartition-va. Les événements.

Ce cog ne fait qu'ÉCOUTER : un rôle donné ou retiré, un pseudo changé, et il
demande à pseudo_model.py — qui porte toute la règle et se teste sans bot —
de poser le bon pseudo. Toutes les trente minutes, et au démarrage, il
repasse sur tous les membres : un changement de rôle fait pendant un
redémarrage du bot (un par déploiement) n'arrive jamais comme événement.

La répartition des VA par model (repartition_va.py, 10/11/2026) suit les
mêmes rôles : chaque rôle donné ou retiré, chaque arrivée ou départ, chaque
rôle renommé lui demande une mise à jour, et le passage des trente minutes
la revoit. Un seul cog pour les deux : ils lisent la même reconnaissance des
rôles (pseudo_model.models_du_membre).

Les cartes de model des VA (cartes_va_fr.py, 10/11/2026 : lien GMS et 📷
Ajouter mes comptes dans leur -content) suivent les mêmes rôles, de la même
façon ; leur bouton est enregistré ici (cog_load), pour répondre après un
redémarrage.

AUCUNE COMMANDE SLASH : le bot principal en a 100 sur 100.

SUR LE BOT PRINCIPAL (Ryuk) : c'est lui qui est sur You FR, en administrateur.
Aucun état sur le disque pour le pseudo : le poser deux fois ne change rien.
La répartition garde l'id de son salon et de son message
(data/repartition_va.json), pour ne jamais en poser un second.
"""
from __future__ import annotations

import asyncio
import traceback

from discord.ext import commands, tasks

#: Le passage de rattrapage, en minutes.
PERIODE_MIN = 30
#: Après le démarrage : le bot finit de charger les membres de ses serveurs.
ATTENTE_DEMARRAGE_SEC = 60


class PseudoModel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.boucle.start()

    def cog_unload(self):
        self.boucle.cancel()

    async def cog_load(self):
        try:
            import cartes_va_fr as cv
            self.bot.add_dynamic_items(cv.BoutonComptes)
        except Exception:
            # sans lui, les boutons 📷 des cartes ne répondraient plus : dit
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
            import pseudo_model as pm
            import repartition_va as rv
            guild = getattr(after, "guild", None)
            roles_changes = (list(getattr(before, "roles", []) or [])
                             != list(getattr(after, "roles", []) or []))
            if roles_changes:
                rv.planifier(guild)
                import cartes_va_fr as cv
                cv.planifier(guild)
            if not pm.serveur(guild):
                return
            # Seuls les rôles et le pseudo comptent : l'événement part aussi
            # pour une exclusion temporaire ou un avatar de serveur.
            if not roles_changes and getattr(before, "nick", None) == getattr(after, "nick", None):
                return
            await pm.appliquer(after)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        try:
            import repartition_va as rv
            rv.planifier(getattr(member, "guild", None))
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        try:
            import repartition_va as rv
            rv.planifier(getattr(member, "guild", None))
            # ses cartes partent avec lui
            import cartes_va_fr as cv
            cv.planifier(getattr(member, "guild", None))
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        try:
            # « Amelia » renommé « Amélia 🩷 » reste la model ; renommé
            # « Ancienne », ses VA passent dans « Sans model ».
            if getattr(before, "name", None) != getattr(after, "name", None):
                import repartition_va as rv
                rv.planifier(getattr(after, "guild", None))
            if (getattr(before, "name", None) != getattr(after, "name", None)
                    or getattr(before, "colour", None) != getattr(after, "colour", None)):
                import cartes_va_fr as cv
                cv.planifier(getattr(after, "guild", None))
        except Exception:
            traceback.print_exc()

    @tasks.loop(minutes=PERIODE_MIN)
    async def boucle(self):
        try:
            import pseudo_model as pm
            import repartition_va as rv
            for guild in list(getattr(self.bot, "guilds", []) or []):
                if pm.serveur(guild):
                    await pm.passer(guild)
                if rv.serveur(guild):
                    await rv.assurer(guild, forcer=True)
                import cartes_va_fr as cv
                # éteintes le 10/11 : le passage efface celles encore posées
                if cv.serveur(guild) or cv.cartes_posees(guild):
                    await cv.assurer(guild)
        except Exception:
            # une exception non attrapee tue une tasks.loop sans rien dire
            traceback.print_exc()

    @boucle.before_loop
    async def _avant(self):
        try:
            await self.bot.wait_until_ready()
            await asyncio.sleep(ATTENTE_DEMARRAGE_SEC)
        except Exception:
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(PseudoModel(bot))
