# -*- coding: utf-8 -*-
"""Qui est en vocal pendant son shift de chatting.

CE COG NE FAIT QUE REGARDER ET DIRE. Tout le raisonnement — a quel shift
cette minute appartient, a partir de quand on est « a l heure », qui n est
pas jugeable — vit dans presence_shift.py, qui se teste sans bot et sans
reseau. Ici il n y a que la lecture de Discord.

AUCUNE COMMANDE SLASH, ET C EST OBLIGATOIRE

Le bot principal declare 101 commandes pour un plafond Discord de 100. Un
cog qui en declare une seule echoue ENTIEREMENT, en silence : quatre cogs
de ce depot sont deja morts ainsi (vaactivity, vasort, tgrouter, numeros).
On suit le modele de reportcomptes et sessionsvoc : zero commande, et le
declenchement se lit depuis le tableau de bord.

POURQUOI UNE HORLOGE A SOI, ET PAS CELLE DE sessionsvoc

Parce que ses fenetres ne sont pas les notres. Les sessions VA courent de
10 h a 17 h, 17 h a 23 h, 23 h a 2 h et 2 h a 5 h, avec une zone morte
VOLONTAIRE de 5 h a 10 h. Les creneaux chatteurs, eux, sont 02h-08h,
08h-14h, 14h-20h et 20h-02h. Le debut du creneau 08h-14h — neuf lignes du
planning — tombe pile dans cette zone morte : branche sur l horloge des VA,
il n aurait JAMAIS ete observe, et personne ne l aurait su.

POURQUOI ON SONDE AU LIEU D ECOUTER LES ENTREES ET SORTIES

on_voice_state_update ne survit pas a un redemarrage : ceux qui etaient
deja connectes n existent plus pour le bot, et un evenement perdu laisse
quelqu un « present » indefiniment. Or le VPS redemarre le service des
qu un commit arrive sur main, c est-a-dire n importe quand. Relever la
liste chaque minute mesure du temps reellement passe et se repare tout seul
au tour suivant.

IL N ECRIT RIEN TANT QU ON NE LUI DIT PAS

presence_shift.config()["ecrire"] vaut False par defaut. Le cog releve donc
— et construit la couverture qui permettra de juger — sans toucher au
planning. C est voulu : un pointage qui se mettrait a ecrire le jour du
deploiement ecrirait sur des donnees que personne n a eu le temps de
regarder.
"""
from __future__ import annotations

import traceback
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import chatting
import presence_shift as ps
import safe_json


class PresenceShift(commands.Cog):
    """Releve chaque minute qui est en vocal, et juge les shifts termines."""

    def __init__(self, bot):
        self.bot = bot
        self._tours = 0
        self._dernier_jugement = 0.0
        self.boucle.start()

    def cog_unload(self):
        self.boucle.cancel()

    # -- le rattachement se decide a UN seul endroit du depot ---------------
    def _resoudre(self, handle: str):
        """handle -> identifiant Discord, via la MEME fonction que le site.

        Surtout pas une deuxieme implementation : le panneau afficherait
        « rattache » en vert pendant que le pointage ignorerait la ligne.
        C est le piege « deux mappings valent deux comportements », qui a
        deja coute 598 fichiers invisibles cote Drive.
        """
        try:
            from web_upload import _resolve_discord_user_by_handle, GUILDE_CHATTEURS
            info = _resolve_discord_user_by_handle(handle, GUILDE_CHATTEURS)
            return info.get("id") if info else None
        except Exception:
            return None

    @tasks.loop(minutes=1)
    async def boucle(self):
        try:
            cfg = ps.config()
            guilde = discord.utils.get(self.bot.guilds, name=cfg["guilde"])
            if guilde is None:
                # Guilde absente = « je ne peux pas regarder », PAS
                # « personne n est la ». On n enregistre donc aucun tour :
                # la couverture baisse, et le verdict se suspend tout seul.
                safe_json.write(str(ps.FICHIER_ETAT), {
                    "quand": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "avertissement": "guilde « %s » introuvable" % cfg["guilde"]})
                return

            maintenant = datetime.now(timezone.utc)
            shift = chatting.shift_a(maintenant)
            if not shift:
                return

            vus = {}
            for salon in guilde.voice_channels:
                for m in salon.members:
                    if m.bot:
                        continue
                    etat = m.voice
                    vus[str(m.id)] = {
                        "nom": m.display_name or m.name,
                        # self_stream = « Go Live », le partage d ecran.
                        # Il vient de l intent voice_states, actif par
                        # defaut : rien a activer, rien a installer.
                        "partage": bool(etat and (etat.self_stream or etat.self_video)),
                        "salon": salon.name,
                    }
            # Un dictionnaire VIDE est une observation valide : « j ai
            # regarde, il n y avait personne ». C est ce qui distingue
            # « absent » de « pas observe ».
            ps.enregistrer_tour(shift["jour"], shift["creneau"], vus,
                                quand=maintenant.timestamp())
            self._tours += 1

            # Le jugement des shifts termines, toutes les cinq minutes : le
            # relever coute une lecture, le juger coute tout le planning.
            if maintenant.timestamp() - self._dernier_jugement >= 300:
                self._dernier_jugement = maintenant.timestamp()
                bilan = ps.appliquer(resoudre=self._resoudre, maintenant=maintenant)
                bilan["tours_depuis_demarrage"] = self._tours
                bilan["salon_suivis"] = len(guilde.voice_channels)
                safe_json.write(str(ps.FICHIER_ETAT), dict(
                    bilan, quand=maintenant.isoformat(timespec="seconds")))
        except Exception:
            # Une exception non attrapee dans une tasks.loop passe par
            # Loop._error, qui se contente d un _log.error : la boucle meurt
            # et RIEN ne le dit sur aucun ecran. On la rattrape donc ici, et
            # on la publie la ou le proprietaire regarde.
            traceback.print_exc()
            try:
                safe_json.write(str(ps.FICHIER_ETAT), {
                    "quand": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "erreur": traceback.format_exc(limit=2)[-400:]})
            except Exception:
                pass

    @boucle.before_loop
    async def _avant(self):
        # Sous try/except : dans sessionsvoc, l equivalent ne l est pas, et
        # une exception ici tue la boucle avant son premier tour — sans
        # trace ailleurs que dans les journaux.
        try:
            await self.bot.wait_until_ready()
        except Exception:
            traceback.print_exc()


async def setup(bot):
    await bot.add_cog(PresenceShift(bot))
