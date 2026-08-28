# -*- coding: utf-8 -*-
"""cogs/noctuspool.py — remplit la réserve de vidéos, la nuit.

CE QU'IL FAIT

Entre minuit et 5 h, il fabrique des vidéos à l'avance et les range dans
`noctus_reserve`. Le matin, un VA qui clique reçoit un fichier déjà prêt au
lieu d'attendre 15 à 30 secondes par vidéo.

BORNÉ PAR L'HEURE, PAS PAR UN COMPTE

Il s'arrête à l'heure dite, quoi qu'il arrive. C'est délibéré : la durée réelle
d'une génération n'est pas connue — les « 15-30 s » du dépôt sont un
commentaire, jamais une mesure. Un objectif chiffré déborderait sur la journée
le jour où une vidéo prend 40 secondes ; une borne horaire remplit simplement
un peu moins et rend la main à l'heure.

À chaque tour il sert la case la plus dégarnie. Si la machine va vite, tout le
monde en profite ; si elle rame, les plus vides sont servis d'abord.

IL NE TOURNE JAMAIS EN JOURNÉE

Hors du créneau, il ne fait rien. Il ne peut donc pas voler le processeur à un
VA qui clique à midi — c'est justement l'attente qu'on cherche à supprimer.

IL MESURE

Chaque génération est chronométrée et journalisée. Après une nuit, on saura ce
que la machine produit réellement à l'heure, au lieu de le supposer.
"""
import asyncio
import time
from datetime import datetime

from discord.ext import commands, tasks

import noctus_reserve as reserve

#: Créneau de travail, en heures locales. Bornes réglables sans toucher au code.
import os

DEBUT_H = int(os.environ.get("NOCTUS_POOL_DEBUT") or "0")
FIN_H = int(os.environ.get("NOCTUS_POOL_FIN") or "5")

#: Familles que ce cog sait fabriquer aujourd'hui. Les familles template et
#: flash passent par un autre chemin d'assemblage : elles viendront ensuite,
#: et d'ici là leurs boutons gardent leur comportement actuel.
FAMILLES = ("caption", "montage")

#: Au-delà, on considère que la génération est perdue et on passe à la suite.
#: Le moteur a lui-même un plafond de 300 s sur l'export.
ATTENTE_MAX_S = 330


def _dans_le_creneau(maintenant=None) -> bool:
    """Vrai si l'heure courante est dans le créneau de nuit.

    Gère le passage de minuit : un créneau 22 h → 5 h enjambe la date, et une
    comparaison naïve `DEBUT <= h < FIN` le rendrait toujours faux.
    """
    h = (maintenant or datetime.now()).hour
    if DEBUT_H == FIN_H:
        return False
    if DEBUT_H < FIN_H:
        return DEBUT_H <= h < FIN_H
    return h >= DEBUT_H or h < FIN_H


class NoctusPool(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._occupe = False
        self.remplir.start()

    def cog_unload(self):
        self.remplir.cancel()

    # ------------------------------------------------------------ recettes --

    def _recette(self, identite: str, famille: str):
        """Rend (brute, caption, block) pour UNE variante, ou None.

        Les ingrédients sont tirés exactement comme le bouton les tirerait —
        mêmes fonctions, même vivier. C'est ce qui garantit qu'une variante de
        la réserve est interchangeable avec une génération à la demande.
        """
        import random
        from cogs import user as u

        block = u._captions_block(identite)
        caps = [c for c in u.fav_captions_for(identite)
                if str(c.get("text") or "").strip()]
        if not caps:
            return None

        if famille == "montage":
            brutes = u.fav_brutes_for(identite)
        else:
            import brutes_off as _off
            brutes = _off.lister(u.IDENTITIES_DIR / identite / "brutes",
                                 extensions=u.VIDEO_EXTS)
        if not brutes:
            return None
        return random.choice(brutes), random.choice(caps), block

    async def _fabriquer_une(self, identite: str, famille: str) -> bool:
        """Fabrique UNE variante et la range. Rend True si elle est en stock."""
        import noctus_web
        from cogs import user as u

        ingredients = self._recette(identite, famille)
        if ingredients is None:
            return False
        brute, cap, block = ingredients
        draft = u.draft_caption(cap, block)
        emp = reserve.empreinte(identite, famille, brute, caption=cap,
                                draft=draft)

        # Rien à faire si la case est déjà pleine POUR CETTE RECETTE.
        if reserve.manque(identite, famille, emp) <= 0:
            return False

        debut = time.monotonic()
        try:
            modele = await asyncio.to_thread(
                noctus_web.gen_from_draft, str(brute), draft, ["V1"], None, None)
        except Exception:
            modele = None
        if not modele:
            return False

        etat = "running"
        limite = time.monotonic() + ATTENTE_MAX_S
        while time.monotonic() < limite:
            await asyncio.sleep(2)
            try:
                etat = noctus_web.status(modele).get("state", "running")
            except Exception:
                etat = "running"
            if etat in ("done", "error", "stopped"):
                break
        if etat != "done":
            return False

        try:
            sorties = noctus_web.output_paths(modele)
        except Exception:
            sorties = []
        if not sorties:
            return False

        _cap, desc, _ex = u._video_meta(brute)
        pose = reserve.deposer(
            identite, famille, sorties[0], emp, desc=desc or "",
            recette={"brute": str(brute), "caption_id": cap.get("id")})
        if pose is None:
            return False

        reserve._noter({"acte": "fabrique", "identite": identite,
                        "famille": famille, "secondes": round(
                            time.monotonic() - debut, 1)})
        return True

    # -------------------------------------------------------------- boucle --

    def _case_la_plus_vide(self, identites, ecartees=()):
        """(identite, famille) qui manque le plus, ou None si tout est plein.

        Servir d'abord le plus dégarni évite qu'une identité bien fournie
        accapare la nuit pendant qu'une autre reste à zéro.
        """
        pire, manque_max = None, 0
        for ident in identites:
            for famille in FAMILLES:
                if (ident, famille) in ecartees:
                    continue
                n = reserve.compter(ident, famille)
                if reserve.PROFONDEUR - n > manque_max:
                    manque_max = reserve.PROFONDEUR - n
                    pire = (ident, famille)
        return pire

    @tasks.loop(minutes=2)
    async def remplir(self):
        if self._occupe or not _dans_le_creneau():
            return
        try:
            import noctus_web
            if not noctus_web.setup_ok():
                return                       # ni Node ni ffmpeg : rien à faire
            from cogs import user as u
            identites = sorted(u._list_identities())
        except Exception:
            return
        if not identites:
            return

        self._occupe = True
        try:
            # On fabrique tant qu'il reste du temps ET des cases à remplir. La
            # boucle se relance toutes les deux minutes ; ce tour-ci s'arrête
            # net a la fin du creneau.
            ecartees = set()
            while _dans_le_creneau():
                case = self._case_la_plus_vide(identites, ecartees)
                if case is None:
                    return                   # plus rien a faire : bonne nuit
                if not await self._fabriquer_une(*case):
                    # Vivier vide ou moteur en panne : on ecarte la case. Sans
                    # ca elle se represente comme « la plus degarnie » a chaque
                    # tour, et la nuit entiere s y use.
                    ecartees.add(case)
                    await asyncio.sleep(1)
        except Exception:
            pass
        finally:
            self._occupe = False

    @remplir.before_loop
    async def _avant(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(NoctusPool(bot))
