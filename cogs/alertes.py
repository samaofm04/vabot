# -*- coding: utf-8 -*-
"""Alertes au staff avant qu'une limite casse quelque chose (Telegram).

Ce cog ne fait que REGARDER Discord : combien de salons sur le serveur Spam,
combien dans chaque categorie de Va IG. Tout le reste — seuils, textes, « deja
envoyee » — vit dans alertes_echeances.py, qui se teste sans bot.

AUCUNE COMMANDE SLASH, comme spoofer et presenceshift : rien a declarer, et
rien qui puisse faire echouer la synchronisation de l'arbre.

SEULEMENT SUR LA MACHINE DE PRODUCTION. Chaque machine a son propre data/ :
armee aussi sur le Mac, la boucle aurait cru n'avoir rien envoye et renvoye
chaque alerte une seconde fois (la quete du jour est partie deux fois le 23/09
pour cette raison). D'ou _machine_proprietaire(), la porte des demons du site.

POURQUOI SUR LE BOT ADMIN ET POURTANT TOUS LES BOTS : le serveur Spam n'est vu
que par le principal, Va IG par les deux. Le cog cherche donc chaque serveur
chez le bot qui y est, parmi ceux du processus.
"""
from __future__ import annotations

import asyncio
import os
import traceback

from discord.ext import commands, tasks

import alertes_echeances as ae


def _machine_prod() -> bool:
    try:
        from web_upload import _machine_proprietaire
    except Exception:
        # site absent : la regle reste la meme, dite ici
        return os.environ.get("VA_MACHINE_PROD") == "1"
    return _machine_proprietaire("alertes-echeances")


class Alertes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._dits = set()
        if _machine_prod():
            self.boucle.start()

    def cog_unload(self):
        self.boucle.cancel()

    def _bots(self):
        bots = [self.bot]
        try:
            import web_upload as w
            bots += [w._BOT_REF, w._BOT_ADMIN_REF]
        except Exception:
            pass
        vus, rendu = set(), []
        for b in bots:
            if b is not None and id(b) not in vus:
                vus.add(id(b))
                rendu.append(b)
        return rendu

    def _guilde(self, gid: str):
        for b in self._bots():
            g = b.get_guild(int(gid))
            if g is not None and not g.unavailable:
                return g
        return None

    def mesurer(self):
        """({id: {"nom", "salons", "categories"}}, avertissements)."""
        serveurs, avert = {}, []
        for gid in sorted(set(ae.SERVEURS_SALONS) | set(ae.SERVEURS_CATEGORIES)):
            g = self._guilde(gid)
            if g is None:
                # « je ne vois pas ce serveur » n'est PAS « il est vide » : aucun
                # bot du processus n'y est (ou panne Discord). Dit, pas ecarte.
                avert.append(f"serveur {gid} vu par aucun bot")
                continue
            serveurs[gid] = {
                "nom": g.name,
                # guild.channels = tous les salons et categories, meme ceux que
                # le bot ne peut pas ouvrir : c'est ce que compte la limite des 500
                "salons": len(g.channels),
                "categories": [{"id": str(c.id), "nom": c.name, "salons": len(c.channels)}
                               for c in g.categories],
            }
        return serveurs, avert

    @tasks.loop(minutes=15)
    async def boucle(self):
        try:
            serveurs, avert = self.mesurer()
            for a in avert:
                if a not in self._dits:            # une fois par processus
                    self._dits.add(a)
                    print(f"[alertes] {a}", flush=True)
            # Telegram et data/ : hors de la boucle Discord
            await asyncio.to_thread(ae.tour, serveurs, avert)
        except Exception:
            # une exception non attrapee tue une tasks.loop sans rien dire
            traceback.print_exc()

    @boucle.before_loop
    async def _avant(self):
        try:
            await self.bot.wait_until_ready()
            # le principal peut se connecter apres le bot admin : sans lui, le
            # serveur Spam serait « vu par aucun bot » au premier tour
            await asyncio.sleep(90)
        except Exception:
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(Alertes(bot))
