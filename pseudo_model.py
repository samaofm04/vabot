# -*- coding: utf-8 -*-
"""Le rôle d'une model s'écrit dans le pseudo : « yous1m (AMELIA) ».

POURQUOI (propriétaire, 10/11/2026, devant You FR)
    « Tu peux créer un rôle par model … y a le rôle Amelia, Lola etc. et … ça
    change leur name dans le serveur, genre yous1m (AMELIA). » Sur You FR
    tout le monde a les mêmes outils et les mêmes salons : rien ne disait
    sur quelle model travaille qui. Le rôle le dit, et le pseudo le montre
    partout — liste des membres, messages, salons vocaux.

LA RÈGLE
    Le pseudo du serveur = le NOM D'UTILISATEUR Discord (celui du salon perso,
    « <pseudo>-content ») suivi de ses models en majuscules :

        une model          yous1m (AMELIA)
        plusieurs          yous1m (AMELIA/LOLA)     dans l'ordre des models
        trop pour 32       yous1m (AMELIA/EMMA+3)   Discord coupe à 32 signes

    Plus aucun rôle de model : le pseudo est rendu (remis à zéro) s'il est de
    cette forme ; un pseudo choisi à la main, d'une autre forme, n'est pas
    touché. Un membre qui a un rôle de model et change son pseudo le retrouve
    aussitôt : c'est le rôle qui nomme.

LES RÔLES
    Un rôle est celui d'une model quand son nom, sans décor ni accent, est le
    sien (« Amelia », « 🩷 Amélia »). Les models sont celles du marché du
    serveur (bangers.MODELS_FR pour un serveur FR) : la liste de ses salons
    banger, pas une copie. Les rôles ont été créés une fois, à la main (REST,
    10/11/2026) ; ce module n'en crée ni n'en supprime aucun — un rôle retiré
    par le propriétaire ne revient pas.

CE QUE DISCORD REFUSE
    Personne ne peut renommer le PROPRIÉTAIRE du serveur, ni un membre dont
    le plus haut rôle est au-dessus de celui du bot. Ces membres sont passés,
    et c'est dit une fois au journal — jamais en silence.

Le rôle n'est qu'une étiquette : il n'ouvre ni ne ferme rien.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import List, Optional, Tuple

log = logging.getLogger("vabot.pseudo_model")

#: La longueur maximale d'un pseudo de serveur, chez Discord.
PLAFOND = 32
#: Ce qu'on garde au moins du nom quand les models ne tiennent pas toutes.
BASE_MIN = 8

#: Un pseudo de NOTRE forme : « … (AMELIA) », « … (AMELIA/LOLA) », « … (AMELIA+2) ».
_RE_NOTRE = re.compile(r"^(.*) \(([A-Z]+(?:/[A-Z]+)*)(?:\+\d+)?\)$")

#: Ce qui a déjà été dit (propriétaire, rôle trop haut) : une fois par membre.
_DITS: set = set()


def _dire_une_fois(cle: str, message: str) -> None:
    if cle not in _DITS:
        _DITS.add(cle)
        log.warning(message)


def cle(nom) -> str:
    """Le nom d'un rôle sans décor ni accent, en minuscules : « 🩷 Amélia » →
    « amelia »."""
    t = unicodedata.normalize("NFKD", str(nom or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def serveur(guild) -> bool:
    """Ce serveur écrit-il la model dans le pseudo ? (guild_features.PSEUDO_MODEL)"""
    try:
        import guild_features as gf
        return bool(gf.pseudo_model(guild))
    except Exception:                                        # noqa: BLE001
        return False


def models_du_serveur(guild) -> Tuple[str, ...]:
    """Les models du serveur, dans l'ordre : celles de son marché. Un serveur
    FR a celles de Va IG (bangers.MODELS_FR). Aucune liste pour un autre
    marché : personne n'y est renommé."""
    try:
        import guild_features as gf
        if gf.marche_serveur(guild) == "fr":
            import bangers
            return tuple(bangers.MODELS_FR)
    except Exception as e:                                   # noqa: BLE001
        _dire_une_fois(f"models:{getattr(guild, 'id', '')}:{type(e).__name__}",
                       f"[pseudo-model] models du serveur illisibles ({type(e).__name__}: {e}) : "
                       f"personne n'est renommé")
    return ()


def models_du_membre(membre, models) -> List[str]:
    """Les models dont le membre porte le rôle, dans l'ordre de `models`."""
    portes = {cle(getattr(r, "name", "")) for r in (getattr(membre, "roles", None) or [])}
    return [m for m in models if m in portes]


def _suffixe(models: List[str], base: str) -> str:
    """« (AMELIA/LOLA) », ou « (AMELIA+1) » si tout ne tient pas à côté d'au
    moins BASE_MIN signes du nom."""
    place = PLAFOND - min(len(base), BASE_MIN) - 1
    noms = [m.upper() for m in models]
    for n in range(len(noms), 0, -1):
        s = "(" + "/".join(noms[:n]) + (f"+{len(noms) - n}" if n < len(noms) else "") + ")"
        if len(s) <= place or n == 1:
            return s
    return ""


def est_le_notre(pseudo, models) -> bool:
    """Ce pseudo a-t-il la forme que ce module donne, avec de vraies models ?"""
    m = _RE_NOTRE.match(str(pseudo or ""))
    if not m:
        return False
    connues = {x.upper() for x in models}
    return all(p in connues for p in m.group(2).split("/"))


def pseudo_voulu(membre, models) -> Tuple[bool, Optional[str]]:
    """(à changer ?, le pseudo à poser — None = le rendre).

    Avec un rôle de model : « <nom d'utilisateur> (<MODELS>) », coupé à 32
    signes côté nom. Sans : rendu seulement si le pseudo actuel est de notre
    forme ; un pseudo choisi à la main reste."""
    actuel = getattr(membre, "nick", None)
    siennes = models_du_membre(membre, models)
    if not siennes:
        return (True, None) if est_le_notre(actuel, models) else (False, actuel)
    base = str(getattr(membre, "name", "") or "").strip() or "membre"
    suffixe = _suffixe(siennes, base)
    base = base[: max(1, PLAFOND - len(suffixe) - 1)].rstrip()
    voulu = f"{base} {suffixe}"[:PLAFOND]
    return (voulu != actuel), voulu


async def appliquer(membre) -> str:
    """Pose (ou rend) le pseudo d'UN membre. Rend ce qui a été fait :
    « pose », « rendu », « deja », « hors » (serveur ou membre non concerné),
    « proprietaire », « refuse », « rate ». Ne lève pas."""
    import discord
    guild = getattr(membre, "guild", None)
    if guild is None or getattr(membre, "bot", False) or not serveur(guild):
        return "hors"
    models = models_du_serveur(guild)
    if not models:
        return "hors"
    changer, voulu = pseudo_voulu(membre, models)
    if not changer:
        return "deja"
    qui = f"{getattr(membre, 'name', '?')} ({getattr(membre, 'id', '?')})"
    if getattr(guild, "owner_id", None) == getattr(membre, "id", object()):
        # Discord ne laisse renommer le propriétaire par personne d'autre que lui.
        _dire_une_fois(f"proprio:{guild.id}:{membre.id}:{voulu}",
                       f"[pseudo-model] {getattr(guild, 'name', '?')} : {qui} est le propriétaire "
                       f"du serveur, Discord interdit de le renommer — « {voulu} » à poser par lui")
        return "proprietaire"
    try:
        await membre.edit(nick=voulu, reason="Le rôle de la model s'écrit dans le pseudo")
    except discord.Forbidden:
        _dire_une_fois(f"refuse:{guild.id}:{membre.id}",
                       f"[pseudo-model] {getattr(guild, 'name', '?')} : Discord refuse de renommer "
                       f"{qui} (son rôle est au-dessus de celui du bot ?) — pseudo laissé")
        return "refuse"
    except Exception as e:                                   # noqa: BLE001
        log.warning(f"[pseudo-model] {getattr(guild, 'name', '?')} : {qui} non renommé "
                    f"({type(e).__name__}: {e})")
        return "rate"
    _DITS.discard(f"refuse:{guild.id}:{membre.id}")
    log.info(f"[pseudo-model] {getattr(guild, 'name', '?')} : {qui} → "
             + (f"« {voulu} »" if voulu else "pseudo rendu (plus de rôle de model)"))
    return "pose" if voulu else "rendu"


async def passer(guild, dormir=None) -> dict:
    """Tous les membres d'un serveur : rattrape un changement de rôle manqué
    (le bot redémarre à chaque déploiement). Rend le bilan, chaque cas compté."""
    import asyncio
    bilan: dict = {}
    if not serveur(guild):
        return bilan
    dormir = dormir or asyncio.sleep
    for m in list(getattr(guild, "members", None) or []):
        r = await appliquer(m)
        bilan[r] = bilan.get(r, 0) + 1
        if r in ("pose", "rendu"):
            await dormir(0.5)                 # on ménage l'API
    return bilan
