"""Le thème Mario hors du podium : le menu du VA et le warm-up.

Le propriétaire a renommé les bots en personnages Mario le 03/10/2026 (Yoshi,
Peach, Luigi, Bowser, Wario) puis a demandé le serveur assorti. Le podium et le
classement des subs ont déjà le leur (podium_discord.THEMES) ; ce module
habille ce qui restait : la ligne de menu épinglée dans le ticket, le menu
complet, et les couleurs du warm-up.

QUI DÉCIDE QU'UN SERVEUR EST MARIO : podium_discord.SERVEURS[gid]["theme"],
et personne d'autre. Cette clé existait avant ce module ; en tenir une seconde
liste ici aurait fini par donner un podium Mario et un menu qui ne l'est pas —
c'est exactement ce que le Drive a déjà coûté, avec ses deux tables de noms de
dossiers et ses 598 fichiers invisibles. Retirer la clé éteint donc TOUT le
thème, podium compris.

Va Twitter et YouL4b US ne changent pas d'un pixel : chaque fonction reçoit le
serveur ET LA VALEUR D'AVANT, et rend cette valeur telle quelle hors thème. Un
appel sans serveur (la vue persistante enregistrée au démarrage, qui ne sert
qu'à déclarer les custom_id et n'est jamais affichée) retombe donc sur l'ancien
rendu : c'est voulu.

CE QUE CE THÈME NE TOUCHE PAS, et pourquoi :
- les custom_id des boutons : ils sont gravés dans les messages déjà publiés,
  les changer rend muets tous les menus en place ;
- la marque « -# menu-contenu-va », la ligne « <@id> 👇 » et « Identité : `x` » :
  le bot les RELIT pour retrouver ses propres menus ;
- les noms de salons : podium_discord._salon les cherche par égalité exacte, et
  le propriétaire les décore lui-même ;
- le panneau d'actions (rouge sombre) et le ✨ General (turquoise) : ils sont
  partagés mot pour mot avec le serveur US, et leurs deux couleurs sont
  différentes exprès, pour qu'on ne confonde pas les deux messages.
"""

import logging
from typing import Any, Optional

log = logging.getLogger("vabot.theme")

#: Le nom du thème, tel que podium_discord.THEMES le porte.
NOM = "mario"

#: Le repli si podium_discord devient illisible : Va IG. Il ne sert que dans ce
#: cas-là, et l'ennui est écrit dans le journal — un thème qui se trompe de
#: serveur en silence est pire qu'un thème absent.
GUILDS = {"1505418484052394004"}

#: Le salon 🚀・warm-up de Va IG. onboarding_discord ne connaît que son salon
#: (data/onboarding_discord.json n'a pas de clé serveur) : c'est donc par le
#: salon qu'on reconnaît Va IG là-bas.
SALONS_WARMUP = {"1511674589627813959"}

# --- La palette, la MÊME que celle du podium (podium_discord.THEMES) --------
ROUGE = 0xE52521    # la casquette : l'accueil, ce qui est en cours
OR = 0xF8C51C       # la pièce : le résultat, la récompense
BLEU = 0x049CD8     # la salopette : ce qui vit encore
VERT = 0x43B047     # Luigi
PIERRE = 0x6B6B6B   # le bloc gris : ce qui est fini et ne bougera plus

#: Les rôles de couleur, et la valeur Mario de chacun. La clé dit à quoi sert
#: la couleur, pas de quelle couleur il s'agit : c'est ce qui permet de
#: repeindre le serveur sans relire les modules de rendu.
COULEURS = {
    "menu": ROUGE,      # le cadre du menu VA, épinglé dans son ticket
}

#: L'emoji de chaque bouton du menu VA. Les absents gardent le leur : un bouton
#: se clique, il ne se décore pas. ⬇️ Download, 🆘 Assistance, 🔗 le lien,
#: 📷 Mes comptes et 📖 Tuto (demandé le 03/10) disent déjà ce qu'ils font —
#: les déguiser ferait chercher le VA.
EMOJIS = {
    "menu": "🍄",       # le champignon : on appuie, ça s'ouvre
    "spoofer": "🔥",    # la fleur de feu
    "clics": "🪙",      # un clic ramené, une pièce — comme au podium
    "pay": "⭐",        # l'étoile : ce qu'on gagne
}

#: Le titre du menu VA. « ☀️ Ton menu » reste celui des autres serveurs.
TITRE_MENU = "🍄 Ton menu"

#: Les neuf couleurs du warm-up, une par jour, en mondes de Mario : pièce,
#: ciel, désert, plaine, eau, château, Peach, lave, Luigi.
COULEURS_WARMUP = [OR,         # accueil
                   BLEU,       # jour 0
                   0xE39D3B,   # attente — le désert
                   VERT,       # jour 1
                   0x2BB3A3,   # jour 2 — l'eau
                   0x7B4AA8,   # jour 3 — le château
                   0xF083B8,   # jour 4 — Peach
                   ROUGE,      # jour 5 — la lave
                   0x3FA34D]   # jour 6+ — la routine installée

_repli_dit = False


def _id(guild_or_id: Any) -> str:
    """L'id du serveur, qu'on reçoive un objet Discord, un entier ou une chaîne.

    Ne lève jamais : un thème qui fait tomber un menu n'est plus un thème.
    """
    if guild_or_id is None:
        return ""
    for attr in ("id", "guild_id"):
        v = getattr(guild_or_id, attr, None)
        if v is not None:
            return str(v)
    g = getattr(guild_or_id, "guild", None)
    if g is not None and g is not guild_or_id:
        return _id(g)
    try:
        return str(int(str(guild_or_id).strip()))
    except (TypeError, ValueError):
        return ""


def actif(guild_or_id: Any) -> bool:
    """Ce serveur porte-t-il le thème Mario ?

    La réponse vient de podium_discord.SERVEURS[gid]["theme"] : une seule clé
    pour tout le serveur. L'import est fait ici et pas en tête de fichier —
    podium_discord tire verif_discord et le reste, et cogs/user.py n'a pas à
    payer ça au démarrage du bot.
    """
    global _repli_dit
    gid = _id(guild_or_id)
    if not gid:
        return False
    try:
        import podium_discord
        profil = podium_discord.SERVEURS.get(gid) or {}
        return str(profil.get("theme") or "") == NOM
    except Exception as e:                                   # noqa: BLE001
        if not _repli_dit:
            _repli_dit = True
            log.warning("theme : podium_discord illisible (%s: %s) — on retombe "
                        "sur la liste de secours %s", type(e).__name__, e, GUILDS)
        return gid in GUILDS


def couleur(role: str, guild_or_id: Any, defaut: int) -> int:
    """La couleur du rôle demandé sous le thème, `defaut` partout ailleurs.

    `defaut` est la couleur d'avant : un rôle inconnu, ou un serveur sans
    thème, rend exactement ce que le code rendait hier.
    """
    if not actif(guild_or_id):
        return defaut
    return COULEURS.get(role, defaut)


def emoji(cle: str, guild_or_id: Any, defaut: str) -> str:
    """L'emoji du bouton `cle` sous le thème, celui d'avant ailleurs."""
    if not actif(guild_or_id):
        return defaut
    return EMOJIS.get(cle, defaut)


def titre_menu(guild_or_id: Any, defaut: str) -> str:
    """Le titre du menu VA : le champignon sous le thème, sinon `defaut`.

    En mode Threads le titre porte déjà sa propre marque (🧵) et aucun serveur
    à thème n'est en mode Threads : l'appelant passe simplement son titre.
    """
    if not actif(guild_or_id):
        return defaut
    return TITRE_MENU


def warmup_ici(salon_id: Optional[Any]) -> bool:
    """Ce salon de warm-up est-il celui du serveur à thème ?

    Si un second serveur reçoit un jour le warm-up, il gardera la palette
    d'origine tant que son salon n'est pas inscrit ci-dessus — c'est le but.
    """
    try:
        return str(int(str(salon_id).strip())) in SALONS_WARMUP
    except (TypeError, ValueError):
        return False
