# -*- coding: utf-8 -*-
"""cogs/noctuspool.py — remplit la réserve de vidéos, en continu.

CE QU'IL FAIT

Il fabrique des vidéos à l'avance et les range dans `noctus_reserve`, pour
qu'un VA qui clique reçoive un fichier déjà prêt au lieu d'attendre 15 à 30
secondes. Le stock se reconstitue au fil de sa consommation : il n'est donc
jamais vide en fin de journée, ce qu'un remplissage seulement nocturne
n'aurait pas garanti.

IL S'EFFACE, PLUTÔT QUE DE SE CACHER LA NUIT

Avant chaque fabrication il regarde si une génération demandée par un VA est
en cours. Si oui, il rend la main immédiatement. C'est ce qui lui permet de
travailler à toute heure sans jamais ralentir quelqu'un : les deux se
disputeraient ffmpeg, et celui qui regarde son écran attendrait deux fois plus
longtemps — l'inverse exact du but.

À chaque tour il sert la case la plus dégarnie. Si la machine va vite, tout le
monde en profite ; si elle rame, les plus vides sont servis d'abord.

Poser NOCTUS_POOL_DEBUT et NOCTUS_POOL_FIN le restreint à un créneau, si un
jour la machine doit être laissée tranquille en journée.

IL MESURE

Chaque génération est chronométrée et journalisée. Après une nuit, on saura ce
que la machine produit réellement à l'heure, au lieu de le supposer.
"""
import asyncio
import time
from datetime import datetime
from pathlib import Path

from discord.ext import commands, tasks

import noctus_reserve as reserve

import logging
import os

#: LE SILENCE ETAIT LE VRAI DEFAUT. Les deux `except Exception` de ce module
#: sont voulus -- une panne de remplissage ne doit jamais tuer le bot -- mais
#: taire l'erreur a laisse le remplisseur inerte sans que rien ne l'indique.
#: On rend la main, ET on ecrit pourquoi.
log = logging.getLogger("noctuspool")

#: Par DEFAUT il tourne en permanence : le stock se reconstitue au fil de sa
#: consommation, donc il n'est jamais vide au moment ou un VA clique. Un
#: creneau nocturne laisserait la reserve se vider en fin de journee, et
#: l'apres-midi redeviendrait lent.
#:
#: Ce n'est possible que parce qu'il s'efface : voir _quelqu_un_attend. Sans
#: cette politesse, remplir toute la journee volerait le processeur a celui
#: qu'on cherche justement a ne plus faire attendre.
#:
#: Poser les DEUX bornes le restreint a un creneau, si un jour la machine doit
#: etre laissee tranquille en journee.
_DEBUT = os.environ.get("NOCTUS_POOL_DEBUT")
_FIN = os.environ.get("NOCTUS_POOL_FIN")
TOUJOURS = not (_DEBUT and _FIN)
DEBUT_H = int(_DEBUT or "0")
FIN_H = int(_FIN or "5")

#: Repos entre deux fabrications. Court, mais il laisse le processeur souffler
#: et donne a une demande de VA le temps de se declarer avant qu'on reparte.
REPOS_S = 3

#: Les sept familles de boutons qui paient une generation. Les autres servent
#: des fichiers existants et n'ont rien a gagner ici.
#:
#: Chaque nom dit ce que la famille EXIGE, pas ce qu'elle produit — c'est ce
#: qui rend une variante interchangeable avec une generation a la demande du
#: meme bouton.
FAMILLES = ("caption", "montage",           # une brute + une caption incrustee
            "reelmonte",                    # un montage deja approuve
            "template", "template_brut",    # un template assemble a une brute
            "flash", "flash_banger", "flash_brut")

#: Au-delà, on considère que la génération est perdue et on passe à la suite.
#: Le moteur a lui-même un plafond de 300 s sur l'export.
ATTENTE_MAX_S = 330


def _dans_le_creneau(maintenant=None) -> bool:
    """Vrai si l'heure courante est dans le créneau de nuit.

    Gère le passage de minuit : un créneau 22 h → 5 h enjambe la date, et une
    comparaison naïve `DEBUT <= h < FIN` le rendrait toujours faux.
    """
    if TOUJOURS:
        return True
    h = (maintenant or datetime.now()).hour
    if DEBUT_H == FIN_H:
        return False
    if DEBUT_H < FIN_H:
        return DEBUT_H <= h < FIN_H
    return h >= DEBUT_H or h < FIN_H


def _quelqu_un_attend() -> bool:
    """Vrai si une generation demandee par un VA tourne en ce moment.

    C'est ce qui permet de remplir toute la journee sans nuire : on ne lance
    jamais une fabrication d'avance pendant qu'un VA attend la sienne. Les deux
    se disputeraient ffmpeg, et celui qui regarde son ecran attendrait deux
    fois plus longtemps — l'inverse exact du but.

    En cas de doute, on repond OUI : ceder un tour ne coute qu'un retard de
    remplissage, alors que passer outre ralentit quelqu'un.
    """
    try:
        import noctus_web
        return bool(noctus_web.generations_en_cours())
    except Exception:
        return True


class NoctusPool(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._occupe = False
        self.remplir.start()

    def cog_unload(self):
        self.remplir.cancel()

    # ------------------------------------------------------------ recettes --

    def _recette(self, identite: str, famille: str):
        """Ce qu il faut fabriquer pour UNE variante, ou None si c est hors
        d atteinte (vivier vide).

        Rend un dictionnaire : la video source, le brouillon, la brute a
        imposer s il y en a une, la description a joindre, et de quoi calculer
        l empreinte.

        Les ingredients sont tires par les MEMES fonctions que les boutons.
        C est ce qui garantit qu une variante de la reserve est interchangeable
        avec une generation a la demande : deux selections differentes
        produiraient des videos qui ne se ressemblent plus, sans que rien ne le
        signale.
        """
        import random
        from cogs import user as u

        # --- les deux familles a caption incrustee ------------------------
        if famille in ("caption", "montage"):
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
            cap = random.choice(caps)
            brute = random.choice(brutes)
            _c, desc, _e = u._video_meta(brute)
            return {"video": brute, "draft": u.draft_caption(cap, block),
                    "imposees": (), "brute_imposee": None,
                    "desc": desc or "", "caption": cap}

        # --- « Template » : les montages deja approuves --------------------
        if famille == "reelmonte":
            prets = u.va_ready_montages_for(identite, 1)
            if not prets:
                return None
            video, draft, desc = prets[0]
            return {"video": video, "draft": draft, "imposees": (),
                    "brute_imposee": None, "desc": desc or "", "caption": None}

        # --- les templates et les Flash ------------------------------------
        if famille in ("template", "template_brut"):
            templates, _ecartes = u.fav_templates_for(identite)
        else:
            templates, _ecartes = u.flash_templates_for(
                identite, exiger_banger=(famille != "flash"))
        if not templates:
            return None

        # La brute n est IMPOSEE que pour les familles qui l exigent etoilee.
        # Ailleurs le moteur en tire une au hasard — c est le comportement du
        # bouton, et l imposer reduirait le stock sans rien trier de mieux.
        brute_imposee = None
        if famille in ("template_brut", "flash_brut"):
            brutes = u.fav_brutes_for(identite)
            if not brutes:
                return None
            brute_imposee = random.choice(brutes)

        tpl, draft = random.choice(templates)
        _c, desc, _e = u._video_meta(tpl)
        return {"video": tpl, "draft": draft,
                "imposees": (str(brute_imposee),) if brute_imposee else (),
                "brute_imposee": brute_imposee,
                "desc": desc or "", "caption": None}

    async def _fabriquer_une(self, identite: str, famille: str) -> bool:
        """Fabrique UNE variante et la range. Rend True si elle est en stock."""
        import os as _os
        import shutil as _sh
        import tempfile as _tf
        import noctus_web

        r = self._recette(identite, famille)
        if r is None:
            return False

        emp = reserve.empreinte(identite, famille, r["video"],
                                brutes=r.get("imposees") or (),
                                caption=r.get("caption"), draft=r["draft"])
        if reserve.manque(identite, famille, emp) <= 0:
            return False                     # cette recette est deja pourvue

        # Une brute imposee passe par un dossier ne contenant qu elle : sans ce
        # detour, le moteur en tire une au hasard parmi toutes celles de
        # l identite, et l etoile de la brute ne servirait a rien.
        # Le verdict d'assemblage, rempli sur place par le moteur. Il est
        # range dans la fiche : une video servie des semaines plus tard doit
        # pouvoir dire qu'elle est un template nu.
        _rap = {}
        dossier_brutes, tmp = None, None
        if r.get("brute_imposee") is not None:
            tmp = _tf.mkdtemp(prefix="reserve-brute-")
            cible = Path(tmp) / Path(r["brute_imposee"]).name
            try:
                _os.link(str(r["brute_imposee"]), str(cible))
            except Exception:
                _sh.copy2(str(r["brute_imposee"]), str(cible))
            dossier_brutes = tmp

        debut = time.monotonic()
        try:
            try:
                modele = await asyncio.to_thread(
                    noctus_web.gen_from_draft, str(r["video"]), r["draft"],
                    ["V1"], None,
                    Path(dossier_brutes) if dossier_brutes else None,
                    _rap)
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

            pose = reserve.deposer(
                identite, famille, sorties[0], emp, desc=r.get("desc") or "",
                recette={"source": str(r["video"]),
                         "imposees": list(r.get("imposees") or ()),
                         "repli": bool(_rap.get("repli")),
                         "message": str(_rap.get("message") or "")})
            if pose is None:
                return False
        finally:
            # Le dossier temporaire part quoi qu il arrive : le VPS se
            # remplirait sinon d une copie de brute a chaque fabrication.
            if tmp:
                _sh.rmtree(tmp, ignore_errors=True)

        reserve._noter({"acte": "fabrique", "identite": identite,
                        "famille": famille,
                        "secondes": round(time.monotonic() - debut, 1)})
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
            # LES IDENTITES VIENNENT DE web_upload, PAS DE cogs.user.
            #
            # `cogs.user._list_identities` n'a jamais existe : cette ligne
            # levait AttributeError a chaque tour, l'`except` l'avalait, et le
            # remplisseur rendait la main sans rien fabriquer. Il etait
            # inerte, et rien ne le disait. Constate le 05/09/2026, apres
            # l'avoir charge : la reserve restait a zero, moteur allume.
            #
            # `_list_content_identities` et pas `_list_identities` : les
            # identites reservees a Jailbreak et les copies de travail (v2_)
            # ne sont pas servies aux VA. Fabriquer six variantes pour
            # « v2_test » couterait des heures de machine pour personne.
            import web_upload
            identites = sorted(web_upload._list_content_identities())
        except Exception:
            log.exception("[noctuspool] impossible de lister les identites")
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
                    return                   # tout est plein : rien a faire
                if _quelqu_un_attend():
                    return                   # un VA attend : on lui laisse tout
                if not await self._fabriquer_une(*case):
                    # Vivier vide ou moteur en panne : on ecarte la case. Sans
                    # ca elle se represente comme « la plus degarnie » a chaque
                    # tour, et le remplissage s y userait indefiniment.
                    ecartees.add(case)
                await asyncio.sleep(REPOS_S)
        except Exception:
            log.exception("[noctuspool] tour de remplissage interrompu")
        finally:
            self._occupe = False

    @remplir.before_loop
    async def _avant(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(NoctusPool(bot))
