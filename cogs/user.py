import asyncio
import collections as _collections
import datetime as _dt
import json
import logging
import os
import random
import re
import tempfile
import time
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks

import marques_montage
import safe_json
from video_transform import (transform_video, transform_metadata_strict,
                             transform_full_strict,
                             load_config as load_transform_config)
from image_transform import transform_image, load_config as load_image_config

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
PROFILE_PICS_DIR = DATA_DIR / "profile_pics"

# Le fichier appelait deja log.warning (emojis d'actions et de PP) sans
# jamais definir `log` : le moindre echec d'emoji levait NameError dans son
# propre except. Le menu General journalise aussi ses echecs ici.
log = logging.getLogger("vabot.user")

# Fuseau France pour le post quotidien à minuit (heure locale FR)
try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = _dt.timezone(_dt.timedelta(hours=1))  # fallback UTC+1


# Quelle fonction (guild_features) commande chaque bouton/champ du menu.
_MENU_BTN_FEATURE = {
    "cmenu:reel": "contenu", "cmenu:story": "contenu", "cmenu:post": "contenu",
    "cmenu:storycta": "contenu", "cmenu:pseudo": "contenu", "cmenu:name": "contenu",
    "cmenu:bio": "contenu", "cmenu:pp": "contenu", "cmenu:comptes": "contenu",
    "cmenu:banger": "contenu", "cmenu:reelmonte": "contenu",
    # La fonction DOIT etre « contenu » : ALL_FEATURES filtre les cles
    # inconnues, donc une fonction inventee ferait disparaitre le bouton en
    # permanence sur tout serveur bride, sans erreur nulle part.
    "cmenu:capbanger": "contenu", "cmenu:montagebanger": "contenu",
    "cmenu:templatebrut": "contenu",
    "cmenu:brutbanger": "contenu", "cmenu:captionbrut": "contenu",
    "cmenu:templatebanger": "contenu", "cmenu:brutchoix": "contenu",
    # Les trois Flash. « contenu » comme leurs voisins : ALL_FEATURES filtre
    # les cles inconnues, donc une fonction inventee ferait disparaitre le
    # bouton en permanence sur tout serveur bride, sans erreur nulle part.
    "cmenu:templateflash": "contenu",
    "cmenu:templateflashbanger": "contenu",
    "cmenu:templateflashbrut": "contenu",
    # Les trois Trash du menu VA, meme regle. Ils ne sont pas des boutons
    # postes mais des options du menu deroulant Trash : c'est ici que le menu
    # lit si le serveur les autorise (_variantes_menu_va).
    "cmenu:templatetrash": "contenu",
    "cmenu:templatetrashbanger": "contenu",
    "cmenu:templatetrashbrut": "contenu",
    "cmenu:addaccount": "onboarding",
    "cmenu:lien": "liens", "cmenu:clics": "clics",
}

# Mode Threads : menu réduit à ces boutons (PP, Name, Pseudo, Mes clics,
# Demander un lien, Mes comptes). Les comptes pointent vers threads.net.
_THREADS_MENU = {"cmenu:pp", "cmenu:name", "cmenu:pseudo", "cmenu:clics", "cmenu:lien", "cmenu:comptes", "cmenu:help", "cmenu:pay", "cmenu:tuto"}


# ---------------------------------------------------------------------------
# LES FAMILLES DE CONTENU -- UNE SEULE TABLE POUR TOUS LES MENUS.
#
# Chaque famille a variantes devient UN MENU DEROULANT (« 💬 Caption… »), pose
# directement dans le message, sans etape : le VA choisit la variante.
# Decisions du proprietaire du 25/09/2026, validees sur maquette : sans ca,
# Trash ne tenait nulle part -- le menu VA etait a 25 composants sur 25, son
# embed a 25 champs sur 25, le panneau US a 24 sur 25. Un premier passage en
# faisait un bouton « ▸ » qui ouvrait les variantes en ephemere (dc157c3) ;
# /demopanneau a montre les menus directs, retenus (format « Components V2 »).
#
# Le panneau US, le panneau ephemere des serveurs non-US, le menu VA et son
# texte d'aide lisent TOUS cette table. Deux tables, deux comportements : le
# Drive en a perdu 598 fichiers (CLAUDE.md).
#
# Dans une famille, les actions vont de la plus simple a la plus exigeante :
# la matiere seule, + etoile, brute etoilee + matiere, matiere etoilee +
# brute etoilee. Les marques (Trash, Flash) viennent de marques_montage, dans
# SON ordre : Trash vit « entre » les templates et Flash.
_Famille = _collections.namedtuple("_Famille", "cle emoji nom actions")

_FAMILLES_MENU = (
    _Famille("caption", "💬", "Caption",
             ("reelcaption", "capbanger", "brutcaption", "montagebanger")),
    _Famille("template", "🎞️", "Template",
             ("reelmonte", "templatebanger", "bruttemplate", "templatebrut")),
) + tuple(
    _Famille(_m, marques_montage.marque(_m)["emoji"],
             marques_montage.marque(_m)["court"],
             tuple(marques_montage.marque(_m)["actions"]))
    for _m in marques_montage.ORDRE)

#: Ce qu'exige chaque action d'une marque, dans l'ordre de ses « actions »
#: (marques_montage) : (template etoile ?, brute etoilee ?).
_MARQUE_VARIANTES = ((False, False), (True, False), (False, True), (True, True))


def _famille_menu(cle):
    """La famille `cle` de _FAMILLES_MENU, ou None."""
    for f in _FAMILLES_MENU:
        if f.cle == cle:
            return f
    return None


def _libelles_marque(cle) -> tuple:
    """Les quatre libelles d'une marque, dans l'ordre de ses actions.

    Tires de marques_montage et de lui seul : changer le logo la-bas change
    ces boutons, sans qu'aucun logo soit recopie ici.
    """
    m = marques_montage.marque(cle)
    e, c = m["emoji"], m["court"]
    return (f"{e} {c}", f"⭐ {c}", f"⭐ Brut + {c}", f"⭐⭐ {c} + Brut")


def _explications_actions() -> dict:
    """{cle d'action: ce qu'elle envoie}, en une ligne.

    Le menu d'une famille met CETTE ligne sous chaque variante : quatre
    boutons qui ne different que par leurs etoiles ne s'expliquent pas tout
    seuls, et c'etait deja le role de l'embed du menu VA.
    """
    out = {
        # Le menu 🎥 Brut du panneau US : ses options portent AUSSI une ligne
        # d'explication, comme toutes les autres. Elles vivaient dans la
        # maquette (/demopanneau) seulement ; ici, la maquette et le vrai
        # panneau lisent la meme ligne.
        "brute": "une vidéo brute, sans rien dessus",
        "brutbanger": "une de tes brutes ⭐",
        "brutchoix": "tu choisis toi-même la brute à utiliser",
        "reelcaption": "une vidéo brute, une caption au hasard incrustée",
        "capbanger": "tes captions ⭐, incrustées sur une vidéo",
        "brutcaption": "une brute ⭐, une caption au hasard incrustée",
        "montagebanger": "une brute ⭐ + une caption ⭐, montées pour toi",
        "reelmonte": "les reels montés (texte déjà incrusté), à poster tels quels",
        "templatebanger": "ton template ⭐, monté avec une de tes brutes",
        "bruttemplate": "une brute ⭐, un template au hasard",
        "templatebrut": "un template ⭐ assemblé avec une brute ⭐",
    }
    for m in marques_montage.ORDRE:
        fiche = marques_montage.marque(m)
        e, nom = fiche["emoji"], fiche["nom"]
        a = fiche["actions"]
        out[a[0]] = f"un montage {e} {nom}, monté avec une brute au hasard"
        out[a[1]] = f"un montage {e} ET ⭐, monté avec une brute au hasard"
        out[a[2]] = f"une brute ⭐, un montage {e} au hasard"
        out[a[3]] = f"un montage {e} ET ⭐, monté avec ta brute ⭐"
    return out


_EXPLICATIONS = _explications_actions()


def _libelle_action(cle) -> str:
    """Le libelle d'une action, tel que le panneau US l'affiche. Une seule
    source (_JB_ACTIONS_US) pour le panneau, les menus et l'aide."""
    e = _jb_action(cle)
    return e[1] if e else cle


def _ch_handle_va(name) -> str:
    """Renvoie le handle si `name` est un salon va-<handle> (tolère un rond en
    préfixe), sinon ''. Sert à repérer les salons VA (ex: pour /cleanva)."""
    m = re.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (name or "").lower())
    return m.group(1) if m else ""


# Marqueur "a un lien GMS" : un 🔗 ajoute APRES le rond d'activite (🟢/🟠/🔴, gere
# par le cog vaactivity). INDEPENDANT de l'activite -> un VA 🔴 (peu actif) peut tres
# bien avoir un 🔗 (un lien). Absence de lien = pas de 🔗 (le rond reste, lui).
LINK_MARK = "🔗"
_ACTIVITY_DOTS = ("🟢", "🟠", "🔴")
_VS = "️"  # sélecteur de variante (VS16) : parfois normalisé par Discord


def _va_channel_target_name(name, has_link):
    """Nom cible d'un salon va- : PRESERVE le rond d'activite existant (🟢/🟠/🔴) et
    ajoute/retire seulement le 🔗 selon la presence d'un lien.
    Ex: '🔴🔗-va-handle' (peu actif MAIS a un lien). None si pas un salon va-."""
    handle = _ch_handle_va(name)
    if not handle:
        return None
    n = name or ""
    dot = n[0] if n[:1] in _ACTIVITY_DOTS else ""
    gear = "⚙️" if "⚙" in n else ""  # préserve le marqueur "0 clic 3j" (géré par clickrecap)
    return f"{dot}{LINK_MARK if has_link else ''}{gear}-va-{handle}"


async def _apply_va_link_mark(channel, has_link, reason="marqueur lien VA"):
    """Renomme un salon va- pour refleter la presence d'un lien. No-op (False) si
    deja correct ou si echec ; True si renomme. Best-effort (ignore les erreurs)."""
    cur = getattr(channel, "name", "") or ""
    target = _va_channel_target_name(cur, has_link)
    # Comparaison insensible au sélecteur de variante (_VS) : évite une boucle de
    # renommage si Discord normalise le ⚙️.
    if not target or target.replace(_VS, "") == cur.replace(_VS, ""):
        return False
    try:
        await channel.edit(name=target, reason=reason)
        return True
    except Exception:
        return False


def _link_message(url, guild=None) -> str:
    """Message d'envoi du lien GMS au VA. En mode Threads : juste « Voici ton lien »
    (pas la consigne 'story' qui est spécifique Instagram)."""
    try:
        import guild_features as gf
        if gf.threads_mode(guild):
            return f"🔗 **Voici ton lien :**\n{url}"
    except Exception:
        pass
    return (f"🔗 **Voici ton lien :**\n{url}\n\n"
            "📲 Voilà ton lien à mettre dans tes **story** (mets-le en story) !")


def _link_identity(guild, uid):
    """Identité à utiliser pour le LIEN GMS d'un VA : si le serveur a une identité
    dédiée (ex: hybride pour Threads US), on l'utilise — peu importe l'identité
    stockée du VA. Sinon, l'identité du VA. Évite de devoir réassigner chaque VA."""
    try:
        import guild_features as gf
        si = gf.get_server_identity(guild)
        if si:
            return si
    except Exception:
        pass
    return get_user_identity(uid)


def _link_is_for_server_identity(url, guild) -> bool:
    """Sur un serveur à identité dédiée (ex: hybride), True seulement si le lien
    correspond à CETTE identité. Un ancien lien d'une autre identité (julia/emma)
    est considéré périmé -> on le régénère. Sans identité dédiée : toujours True."""
    try:
        import guild_features as gf
        si = gf.get_server_identity(guild)
        if not si:
            return True
        import gms
        suffix = (gms._SHORTCODE_SUFFIX.get(si, si) or si).lower()
        sc = (url or "").rstrip("/").rsplit("/", 1)[-1].lower()
        return bool(sc) and sc.endswith(suffix)
    except Exception:
        return True


def _menu_feature_check(interaction, feature: str) -> bool:
    """True si la fonction est active sur le serveur de l'interaction."""
    try:
        import guild_features as gf
        return gf.enabled(getattr(interaction, "guild", None), feature)
    except Exception:
        return True


# Correspondance suffixe de custom_id -> icone. Couvre « cmenu: » comme
# « cmenu2: » : on coupe au premier deux-points.
#
# Les trois Flash n'y sont plus : ils pointaient vers l'icone « Template +
# Brut », qui ecrasait leur ⚡ des que les icones etaient televersees. Ils
# vivent desormais dans le menu deroulant ⚡, qui pose l'icone de CHAQUE
# action (icones_actions) -- vatemplateflash compris, qui n'etait jamais
# montree. Depuis les menus directs, « capbanger », « montagebanger » et
# « templatebrut » sont des OPTIONS de menu (icone posee par
# _jb_option_action) : leurs lignes ici ne servent plus aucun bouton poste.
# « reelmonte » sert encore le menu central (cmenu2:reelmonte).
_ICONE_PAR_ACTION_MENU = {
    "reel": "reelcaption",
    "reelmonte": "reelmonte",
    "story": "story",
    "post": "post",
    "storycta": "storycta",
    "pseudo": "pseudo",
    "name": "name",
    "bio": "bio",
    "pp": "pp",
    "capbanger": "capbanger",
    "montagebanger": "montagebanger",
    "templatebrut": "templatebrut",
}
# Les lanceurs de famille (« cmenu:fam: ») n'y sont plus : ils ne sont plus
# poses. Les variantes des menus deroulants prennent l'icone de CHAQUE action
# (_jb_option_action) ; cette table sert les boutons.


def _poser_icones_menu(view, guild):
    """Remplace l emoji standard des boutons par l icone du serveur.

    Ces boutons declarent leur emoji dans le DECORATEUR, donc a la
    definition de la classe : on ne peut pas y mettre une icone qui depend
    du serveur. On la pose ici, au moment ou la vue part reellement.

    Contrairement au panneau jailbreak, le libelle est deja separe de
    l emoji sur ces boutons : il n y a rien a couper.
    """
    try:
        ic = icones_actions(guild)
    except Exception:
        return
    if not ic:
        return
    for item in getattr(view, "children", []):
        cid = getattr(item, "custom_id", "") or ""
        suffixe = cid.split(":", 1)[1] if ":" in cid else ""
        cle = _ICONE_PAR_ACTION_MENU.get(suffixe)
        emo = ic.get(cle) if cle else None
        if emo is not None:
            try:
                item.emoji = emo
            except Exception:
                pass


def _reglages_menu(guild):
    """(fonctions actives, mode Threads) du serveur, avec le repli d'avant :
    un module de reglages qui ne repond pas ne doit pas vider le menu."""
    try:
        import guild_features as gf
        return gf.get_features(guild), gf.threads_mode(guild)
    except Exception:
        return None, False


def _variantes_menu_va(famille, feats, threads) -> list:
    """Les variantes du menu VA d'une famille que CE serveur autorise.

    `feats` None = reglages illisibles : on garde tout, comme avant. Une
    variante suit la fonction de son ancien bouton (_MENU_BTN_FEATURE) : le
    menu deroulant applique donc les memes reglages que le menu d'avant.
    """
    fam = _famille_menu(famille)
    if fam is None:
        return []
    out = []
    for cle in fam.actions:
        if cle not in _MENU_VA_APPELS:
            continue
        cid = "cmenu:" + cle
        if threads and cid not in _THREADS_MENU:
            continue
        need = _MENU_BTN_FEATURE.get(cid, "contenu")
        if feats is not None and need and need not in feats:
            continue
        out.append(cle)
    return out


def _bouton_va_permis(cid, feats, threads) -> bool:
    """Ce serveur montre-t-il le bouton `cid` du menu VA ?

    `feats` None = reglages illisibles : on garde tout, comme avant. Memes
    regles que les variantes (_variantes_menu_va) : _MENU_BTN_FEATURE, puis le
    jeu reduit du mode Threads."""
    if feats is None:
        return True
    need = _MENU_BTN_FEATURE.get(cid)
    if need and need not in feats:
        return False
    if threads and cid not in _THREADS_MENU:
        return False
    return True


def _filter_menu_view(view, guild):
    """Applique a `view` (un ContentMenuView) les reglages de ce serveur :
    fonctions coupees, mode Threads (jeu reduit, « Mes comptes Threads »),
    icones dessinees.

    Le menu est RECONSTRUIT avec les reglages, plus rien n'est retire apres
    coup : un bouton coupe disparait, une option coupee disparait de son menu,
    un menu sans option disparait -- et le texte d'en tete, deduit de ce qui a
    ete pose, ne decrit plus un bouton absent. Avant, l'embed d'aide etait
    ecrit a part, avec sa propre liste : deux listes, deux comportements."""
    view.construire(guild)
    return view


#: Prefixe des lanceurs de famille des menus VA postes entre dc157c3 et le
#: passage aux menus directs (« 💬 Caption ▸ »…). Plus poses : un clic
#: convertit le menu qui les porte (ContentMenuLanceursView).
_CMENU_FAMILLE = "cmenu:fam:"
#: Prefixe des menus deroulants de famille du menu VA (« 💬 Caption… »).
#: Distinct de tout custom_id « cmenu:<cle> » : aucune cle d'action ne
#: s'appelle « sel ».
_CMENU_MENU = "cmenu:sel:"

#: La derniere ligne du texte du menu VA, en petit gris. Un message
#: « Components V2 » n'a pas d'embed : c'est CETTE ligne qui le designe
#: (_est_menu_va), pour _delete_old_menus et consorts. Le titre ne suffit
#: pas : il change en mode Threads.
_MENU_VA_PIED = "menu-contenu-va"
_MENU_VA_MARQUE = "-# " + _MENU_VA_PIED
#: Titres de l'ancien menu (embed) : ce sont eux qui le designent.
_MENU_VA_TITRES = ("☀️ Ton menu", "🧵 Ton menu Threads")


def _est_menu_va(m, moi=None) -> bool:
    """Ce message est-il le menu VA, dans l'un ou l'autre format ?

    Ancien : un embed titre « ☀️ Ton menu » / « 🧵 Ton menu Threads ».
    V2 : la ligne _MENU_VA_MARQUE dans son texte. `moi` : l'id du bot ; donne,
    un message d'un autre auteur n'est jamais le menu. Ne leve jamais."""
    try:
        if m is None:
            return False
        if moi is not None and getattr(getattr(m, "author", None), "id", None) != moi:
            return False
        emb = getattr(m, "embeds", None) or []
        if emb and (getattr(emb[0], "title", None) or "") in _MENU_VA_TITRES:
            return True
        return any(ligne.strip() == _MENU_VA_MARQUE
                   for t in _textes_v2(m) for ligne in t.splitlines())
    except Exception as e:                                   # noqa: BLE001
        log.warning("menu VA : message %s illisible (%s: %s)",
                    getattr(m, "id", "?"), type(e).__name__, e)
        return False


_RE_MENU_VA_IDENT = re.compile(r"^(?:-# )?Identité : `?([^`\n]+?)`?\s*$")
_RE_MENU_VA_MENTION = re.compile(r"^<@!?(\d+)> 👇")


def _menu_va_lire(m):
    """(identite, id du VA mentionne) d'un menu VA deja poste, dans l'un ou
    l'autre format -- pour le redessiner SANS rien perdre de ce qu'il
    affichait. (None, None) si rien n'est lisible. Ne leve jamais."""
    ident = mention = None
    try:
        lignes = [l for t in _textes_v2(m) for l in t.splitlines()]
        emb = getattr(m, "embeds", None) or []
        if emb:
            pied = getattr(getattr(emb[0], "footer", None), "text", None) or ""
            lignes.append(pied)
        lignes += (getattr(m, "content", None) or "").splitlines()
        for l in lignes:
            l = l.strip()
            mi = _RE_MENU_VA_IDENT.match(l)
            if mi and ident is None:
                ident = mi.group(1).strip() or None
            mm = _RE_MENU_VA_MENTION.match(l)
            if mm and mention is None:
                mention = int(mm.group(1))
    except Exception as e:                                   # noqa: BLE001
        log.warning("menu VA : message %s illisible (%s: %s)",
                    getattr(m, "id", "?"), type(e).__name__, e)
    return ident, mention


def _menu_va_texte(aide, threads, avec_menus, identite=None, mention=None,
                   inconnues=()) -> str:
    """Le texte en tete du menu VA (TextDisplay), qui remplace l'embed.

    `aide` : une ligne par rangee REELLEMENT posee (ContentMenuView). Sa
    DERNIERE ligne est la marque qui le designe (_MENU_VA_MARQUE) ; juste
    au-dessus, l'identite, comme l'ancien pied d'embed -- /setidentite
    « first » la relit dans l'historique du salon."""
    haut = []
    if mention:
        haut.append(f"<@{int(mention)}> 👇 **Ton menu du jour est prêt !**")
    haut.append("## 🧵 Ton menu Threads" if threads else "## ☀️ Ton menu")
    haut.append("Clique sur un bouton, ou choisis directement dans un menu 👇"
                if avec_menus else "Clique sur un bouton 👇")
    haut += list(aide)
    if inconnues:
        haut.append(f"⚠️ {len(inconnues)} élément(s) introuvable(s), absent(s) "
                    "du menu : " + ", ".join(inconnues) + " (à signaler à un admin).")
    bas = []
    if identite and not threads:
        bas.append(f"-# Identité : `{identite}`")
    bas.append(_MENU_VA_MARQUE)
    corps, fin = "\n".join(haut), "\n".join(bas)
    # 4000 caracteres pour TOUT le texte d'un message V2. On coupe l'aide,
    # jamais la marque : sans elle, le menu ne serait plus reconnu.
    place = 4000 - len(fin) - 1
    if len(corps) > place:
        log.warning("menu VA : texte trop long (%d > %d), aide coupee",
                    len(corps), place)
        corps = corps[:max(0, place - 1)] + "…"
    return corps + "\n" + fin


USERS_FILE = DATA_DIR / "users.json"
TUTO_VIDEO_FILE = DATA_DIR / "tutoriel.mp4"  # vidéo explicative (bouton "Comprends rien ?")
WHITELIST_FILE = DATA_DIR / "whitelist.json"
# Config demandes de lien. Nouveau format PAR SERVEUR : {"<guild_id>": {channel_id, role_id}}.
# Rétro-compat : ancien format global {channel_id, role_id} encore lu en fallback.
LINK_REQ_CONFIG = DATA_DIR / "link_request_config.json"


def _lr_cfg_for_guild(gid):
    """(channel_id, role_id) du salon de demande de lien pour CE serveur.
    Cherche d'abord la config du serveur, sinon retombe sur l'ancien format global."""
    def _load():
        try:
            d = json.loads(LINK_REQ_CONFIG.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    cfg = _load()
    g = cfg.get(str(gid)) if gid else None
    if isinstance(g, dict):
        return g.get("channel_id"), g.get("role_id")
    return cfg.get("channel_id"), cfg.get("role_id")  # legacy global


def _lr_cfg_set_guild(gid, channel_id=None, role_id=None, set_role=False):
    """Écrit la config demande-de-lien PAR SERVEUR (sans toucher aux autres serveurs)."""
    try:
        cfg = json.loads(LINK_REQ_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}
    g = cfg.get(str(gid))
    if not isinstance(g, dict):
        g = {}
    if channel_id is not None:
        g["channel_id"] = channel_id
    if set_role:
        g["role_id"] = role_id
    cfg[str(gid)] = g
    save_json(LINK_REQ_CONFIG, cfg)

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    # Écriture atomique : on écrit dans un fichier temporaire puis os.replace.
    # Évite qu'un kill/crash en plein flush laisse un JSON tronqué (ce qui
    # réinitialiserait silencieusement l'état, ex. les blocs anti-doublon).
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
        return True
    except Exception:
        return False


# Mots-clés de rôles considérés comme staff (en plus des permissions Discord) :
# un VA avec le rôle "boss" ou "manager" peut gérer (ex: accepter les demandes de lien)
# même sans la permission "gérer le serveur".
_STAFF_ROLE_KEYWORDS = ("boss", "manager", "manageur", "manageuse", "admin", "staff")


def _is_staff_member(member):
    """True si le membre est staff : permissions Discord (admin / gérer serveur /
    gérer salons) OU porteur d'un rôle 'boss' / 'manager' / 'admin' / 'staff'."""
    p = getattr(member, "guild_permissions", None)
    if p and (p.administrator or p.manage_guild or p.manage_channels):
        return True
    for r in (getattr(member, "roles", None) or []):
        nm = (getattr(r, "name", "") or "").lower()
        if any(k in nm for k in _STAFF_ROLE_KEYWORDS):
            return True
    return False


# Roles a notifier pour une demande d'aide VA (managers/boss).
_HELP_PING_KEYWORDS = ("boss", "manager", "manageur", "manageuse")


def _find_help_channel(guild):
    """Salon d'aide (ex: 🆘・help) : 1er salon texte dont le nom contient 'help'
    (prioritaire), sinon 'aide'/'sos'/🆘. None si introuvable."""
    best = None
    for ch in getattr(guild, "text_channels", []):
        n = (getattr(ch, "name", "") or "").lower()
        if "help" in n:
            return ch
        if best is None and ("aide" in n or "sos" in n or "🆘" in n):
            best = ch
    return best


def _staff_ping(guild):
    """Mentions des roles managers/boss du serveur (pour notifier une demande
    d'aide), dedupliquees ; '@here' en dernier recours."""
    seen, out = set(), []
    for r in getattr(guild, "roles", []):
        nm = (getattr(r, "name", "") or "").lower()
        if nm == "@everyone":
            continue
        if any(k in nm for k in _HELP_PING_KEYWORDS):
            m = r.mention
            if m not in seen:
                seen.add(m)
                out.append(m)
    return " ".join(out) if out else "@here"


# Reseaux TapTap (mobile money) proposes : code -> libelle (pays).
_PAY_NETWORKS = [
    ("Airtel", "Airtel — Madagascar 🇲🇬"),
    ("Orange", "Orange — Madagascar 🇲🇬"),
    ("Mvola", "Mvola — Madagascar 🇲🇬"),
    ("Moov", "Moov — Bénin 🇧🇯"),
    ("MTN", "MTN — Bénin 🇧🇯"),
]


def _payment_summary(pay):
    """Resume lisible d'un moyen de paiement stocke, ou None si absent/invalide."""
    if not isinstance(pay, dict) or not pay.get("method"):
        return None
    if pay.get("method") == "TapTap":
        return f"📱 TapTap · {pay.get('network', '?')} · `{pay.get('number', '?')}`"
    chain = pay.get("chain")
    head = pay.get("method", "?") + (f" ({chain})" if chain else "")
    shot = " · 📸" if pay.get("screenshot") else ""
    return f"💰 {head} · `{pay.get('address', '?')}`{shot}"


def _find_payment_channel(guild):
    """Salon de paiement (si l'user en a cree un), sinon None. Nom contenant
    'paiement'/'payment'/'paye'/💸."""
    for ch in getattr(guild, "text_channels", []):
        n = (getattr(ch, "name", "") or "").lower()
        if "paiement" in n or "payment" in n or "paye" in n or "💸" in n:
            return ch
    return None


# ---- Demandes de lien : anti-spam (1 demande en attente) + anti-doublon (1 SEUL lien / VA) ----
# Bloc DUR : dès qu'un VA a un lien, on refuse d'en regénérer un (sauf future commande dédiée).
LINK_STATE_FILE = DATA_DIR / "link_request_state.json"  # {uid: {"p": ts_demande, "g": ts_genere, "url": ..., "name": ...}}
_REQ_PENDING_TTL = 24 * 3600   # une demande en attente expire après 24h

# Verrou en mémoire : empêche un double-clic / 2 managers de générer 2 liens
# pendant que la 1re génération (lente, réseau) est encore en cours.
_LINK_GEN_INFLIGHT = set()


def _gms_exact_link(handle: str, links) -> "dict | None":
    """Match STRICT pour le bloc dur : display_name normalisé == 'va' + handle.
    Volontairement PAS de substring (gms.find_link_for_handle bloquerait à tort
    un VA différent dont le pseudo est inclus dans un autre, ex: @mia vs @mialee)."""
    h = re.sub(r"[^a-z0-9]", "", (handle or "").lower())
    if len(h) < 3 or not links:
        return None
    target = "va" + h
    for l in links:
        if re.sub(r"[^a-z0-9]", "", (l.get("display_name") or "").lower()) == target:
            return l
    return None


def _lr_load():
    d = load_json(LINK_STATE_FILE, {})
    return d if isinstance(d, dict) else {}


def _lr_is_pending(uid) -> bool:
    e = _lr_load().get(str(uid)) or {}
    p = e.get("p")
    return bool(p and (time.time() - p) < _REQ_PENDING_TTL)


def _lr_mark_pending(uid):
    d = _lr_load()
    d.setdefault(str(uid), {})["p"] = time.time()
    save_json(LINK_STATE_FILE, d)


def _lr_existing(uid):
    """Renvoie l'entrée {g, url, name} si un lien a DÉJÀ été généré pour ce VA, sinon None.
    Sert de bloc dur : une fois qu'un VA a un lien, plus de génération auto."""
    e = _lr_load().get(str(uid)) or {}
    return e if e.get("g") else None


def _lr_mark_generated(uid, url: str = "", name: str = ""):
    d = _lr_load()
    e = d.setdefault(str(uid), {})
    e["g"] = time.time()
    if url:
        e["url"] = url
    if name:
        e["name"] = name
    e.pop("p", None)  # la demande est traitée
    save_json(LINK_STATE_FILE, d)


async def _lr_send_blocked(interaction, uid, url: str = "", source: str = ""):
    """Réponse standard quand un VA a déjà un lien : éphémère + on retire le bouton."""
    where = " (trouvé sur GetMySocial)" if source == "gms" else ""
    try:
        await interaction.followup.send(
            f"🔒 **Ce VA a déjà un lien**{where} — génération bloquée pour éviter les doublons."
            + (f"\n🔗 Lien existant : {url}" if url else "")
            + "\n\n_Pour en recréer un, il faudra une commande dédiée (pas encore dispo)._",
            ephemeral=True,
        )
    except Exception:
        pass
    msg = getattr(interaction, "message", None)
    if msg is not None:
        try:
            await msg.edit(
                content=f"🔒 {interaction.user.mention} — ce VA a déjà un lien"
                + (f" : {url}" if url else "")
                + " (génération bloquée, anti-doublon).",
                view=None,
            )
        except Exception:
            pass


def unescape_newlines(text):
    return text.replace("\\n", "\n") if text else text


def read_lines(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def random_username_for(identity):
    """usernames.txt de l'identité + bibliothèque « Usernames » du site."""
    items = read_lines(IDENTITIES_DIR / identity / "usernames.txt")
    items = items + [x for x in _vault_texts("usernames", identity) if x not in items]
    return unescape_newlines(random.choice(items)) if items else None


# === USERNAME GENERATOR + INSTAGRAM AVAILABILITY CHECK ===

# Mots calques sur les VRAIS comptes de la niche (releve de la Veille) :
# @elsafraise, @jadelapinee, @mila.tacrush, @lolabloomy_, @julie.tatoueuse,
# @anais.cutiee, @jade.minili. Ce sont des mots FR mignons/concrets, jamais du
# jargon marketing anglais (l'ancien « lolavibes » sonnait faux).
# AUCUN ALIMENT (demande user) : « alicesucre » ne ressemble pas a un pseudo.
# Retires : fraise, praline, caramel, vanille, noisette, pomme, miel, sucre,
# peche. On garde animaux / tendresse / ciel, qui se lisent comme un surnom.
_CUTE_WORDS = [
    "lapine", "jolie", "cherie", "bloomy", "cutie", "crush", "biche",
    "minou", "bisou", "coeur", "ange", "reve", "chatonne", "douce",
    "lune", "etoile", "mimi", "bella", "belle", "chou", "poupee",
    "rose", "soleil", "nuit", "fee", "sirene", "papillon", "cygne",
]
# Prefixes/suffixes reellement observes : @itsncyoff, @lolabloomy_, @_jade.vibess
_REAL_PREFIXES = ("its", "real", "iam")
_REAL_SUFFIXES = ("off", "ofc")


def _ascii_name(s: str) -> str:
    """Prenom -> minuscules SANS ACCENT ni espace, lettres ASCII uniquement.

    Indispensable : Instagram REFUSE les caracteres accentues. Une identite
    nommee « Amélia » produisait « amélia_fntn », un pseudo impossible a creer
    (str.isalnum() accepte les lettres accentuees, d'ou le trou).
    """
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "").lower().strip())
    s = s.encode("ascii", "ignore").decode("ascii")
    return "".join(c for c in s if c.isalpha())


def _consonant_tag(word: str) -> str:
    """Nom de famille -> son abreviation SANS VOYELLES, facon initiales.

    C'est LE motif dominant de la niche (releve Veille) : @anna_vnbs,
    @ludivine_dstr, @lorenastms, @lousmtr, @ninicsti. Ce n'est PAS du hasard :
    ca se lit comme les initiales d'un vrai nom, d'ou le rendu credible.
    Ex : Dubois -> dbs, Martin -> mrtn, Mercier -> mrcr, Rousseau -> rss.
    """
    w = "".join(c for c in (word or "").lower() if c.isalpha())
    tag = "".join(c for c in w if c not in "aeiouy")
    return tag[:4]                       # 2-4 lettres comme les vrais comptes


def generate_username_candidates(base: str, count: int = 40) -> list:
    """Pseudos LISIBLES batis UNIQUEMENT sur le prenom (+ ses diminutifs) et de
    VRAIS mots. Plus jamais de consonnes au hasard.

    Exemples pour « amelia » : amelia, amy, ame, amelia.rose, amyxo, itsamelia

    La liste est ORDONNEE du plus proche du vrai prenom au plus decore : le
    checker de dispo prend les premiers libres, donc on propose toujours le
    plus credible en premier.
    """
    base = _ascii_name(base)
    if not base:
        return []

    seen = set()
    out = []

    def add(u):
        u = (u or "").lower()
        core = u.replace("_", "").replace(".", "")
        # Regles Instagram reelles : lettres/chiffres/point/underscore, 30 max,
        # le POINT interdit en bord — mais l'UNDERSCORE est autorise en bord
        # (@lolabloomy_, @_jade.vibess). Mon filtre precedent le refusait a tort.
        # Minimum 3 : il faut garder les formes courtes (ame, amy) que l'ancien
        # filtre 4+ jetait.
        if not u or not (3 <= len(u) <= 30) or u in seen:
            return
        # isalnum() seul ne suffit PAS : il accepte « é ». Instagram, non.
        if not u.isascii() or not core.isalnum() or core.isdigit():
            return                              # doit contenir des lettres ASCII
        if u[0] == "." or u[-1] == "." or ".." in u or "__" in u:
            return
        seen.add(u)
        out.append(u)

    # Toutes les formes du prenom, de la plus reconnaissable a la moins
    names = [base] + _get_diminutives(base)
    names = list(dict.fromkeys(names))

    # --- Niveau 1 : le prenom complet NU, et LUI SEUL ---
    # Les surnoms courts nus (« ali », « ame », « amy », « mel ») sont pris depuis
    # 15 ans sur Instagram : les proposer, c'est gaspiller une ligne sur 10 et un
    # appel de verification. Ils restent utilises comme BASE des combinaisons
    # (ali_grnr, alice.biche) — c'est la qu'ils servent vraiment.
    add(base)

    # --- Niveau 2 : pseudos COMPLETS, calques sur les vrais comptes de la niche ---
    # Les formes nues ci-dessus sont quasi toujours prises : c'est ICI que sortent
    # les pseudos reellement posables. Interdits : chiffres (demande user), nom de
    # famille invente (« lola.blanc »), consonnes au hasard (« amelia_xqks »).
    # Modeles observes : @elsafraise, @jadelapinee, @alice.moreee, @lolabloomy_,
    # @mila.tacrush, @anais.cutiee, @_jade.vibess, @itsncyoff.
    fam_tag, fam_double, fam_word, fam_under, fam_pre = [], [], [], [], []
    # 0) LE motif dominant de la niche : prenom + initiales de nom sans voyelles
    #    (@anna_vnbs, @ludivine_dstr, @lorenastms, @lousmtr). En premier car c'est
    #    ce que l'user a designe comme la reference.
    # 3-4 lettres comme les vrais comptes (vnbs, dstr, stms, smtr, csti) : a 2
    # lettres (« amy_fr ») ca ne ressemble plus a des initiales.
    tags = [t for t in (_consonant_tag(l) for l in _LAST_NAMES) if 3 <= len(t) <= 4]
    tags = list(dict.fromkeys(tags))
    random.shuffle(tags)
    for t in tags:
        for n in names[:3]:
            for sep in ("_", ""):
                fam_tag.append(f"{n}{sep}{t}")
    random.shuffle(fam_tag)
    # a) voyelle finale allongee : ameliaa, ameliaaa  (@alice.moreee, @jadelioraaa)
    for n in names[:4]:
        if n and n[-1] in "aeiouy":
            # Resultat >= 6 caracteres : « amee »/« amyy »/« alii » sont aussi
            # courts que les surnoms nus, donc pris depuis longtemps. On garde
            # « ameliaa », « aliciaa », « jessyee ».
            for v in (n + n[-1], n + n[-1] * 2):
                if len(v) >= 6:
                    fam_double.append(v)
    # b) prenom + mot FR mignon : amelia.fraise, ameliajolie, amy.cherie
    words = list(_CUTE_WORDS)
    random.shuffle(words)
    for w in words:
        for n in names[:3]:
            # Separateur OBLIGATOIRE : « alice.biche » se lit, « alicesucre » non.
            for sep in (".", "_"):
                fam_word.append(f"{n}{sep}{w}")
    # melange : sinon on sortait 3x le meme mot a la suite
    random.shuffle(fam_word)
    # c) underscore decoratif : amelia_, _amelia, _amelia_  (@lolabloomy_)
    for n in names[:4]:
        fam_under += [f"{n}_", f"_{n}", f"_{n}_"]
    # d) prefixes/suffixes de vrais comptes : itsamelia, amelia.off
    for pre in _REAL_PREFIXES:
        for n in names[:3]:
            fam_pre.append(f"{pre}{n}")
    for suf in _REAL_SUFFIXES:
        for n in names[:3]:
            fam_pre += [f"{n}.{suf}", f"{n}{suf}"]

    # Alternance PONDEREE : a chaque tour on sert 2 pseudos du motif de reference
    # (prenom + initiales, facon @anna_vnbs) et 1 de chaque autre famille. Sinon
    # les 10 premiers seraient 10 variantes du meme motif.
    # NB : on avance un CURSEUR par famille — repeter la meme liste dans `fams`
    # ne marcherait pas (on re-ajouterait l'element deja vu, donc ignore).
    plan = [(fam_tag, 2), (fam_word, 1), (fam_double, 1),
            (fam_under, 1), (fam_pre, 1)]
    pos = [0] * len(plan)
    while len(out) < count:
        progressed = False
        for j, (fam, weight) in enumerate(plan):
            for _ in range(weight):
                if pos[j] < len(fam):
                    add(fam[pos[j]])
                    pos[j] += 1
                    progressed = True
            if len(out) >= count:
                break
        if not progressed:
            break                        # toutes les familles sont epuisees

    return out[:count]


async def check_instagram_username_available(username: str) -> bool:
    """Check si un username Instagram est dispo via RapidAPI Instagram Scraper.
    Plus fiable que le HTTP direct (IG redirect login pour les non-authentifies).

    Retourne True si dispo (= profile pas trouve), False si pris.
    """
    if not username:
        return False
    import aiohttp
    try:
        from insta_scraper import load_auth
        auth = load_auth()
        api_key = (auth.get("rapidapi_key") or "").strip()
        host = (auth.get("rapidapi_host") or "instagram-scraper-stable-api.p.rapidapi.com").strip()
        if not api_key:
            return False  # Pas de cle = on peut pas check, on retourne False (safe)
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": host,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://{host}/ig_get_fb_profile_v3.php",
                headers=headers,
                data=f"username_or_url={username}",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status == 404:
                    return True
                if r.status != 200:
                    return False
                try:
                    body = await r.json(content_type=None)
                except Exception:
                    return False
                if not isinstance(body, dict):
                    # body non-dict suggere reponse vide / erreur
                    return True
                # Unwrap "data"/"user"
                user = body
                if "user" in body and isinstance(body["user"], dict):
                    user = body["user"]
                elif "data" in body and isinstance(body["data"], dict):
                    user = body["data"]
                if not isinstance(user, dict):
                    return True
                # Un profil valide a soit username, pk, ou id, ou follower_count
                has_id = bool(user.get("username") or user.get("pk") or user.get("id"))
                # Si erreur explicite, dispo
                err = (user.get("error") or user.get("message") or "")
                if err and ("not found" in str(err).lower() or "introuvable" in str(err).lower()):
                    return True
                if not has_id:
                    return True  # rien dans la reponse = pas trouve = dispo
                return False  # has_id = profil existe = pris
    except Exception:
        return False


async def find_available_usernames(base: str, max_check: int = 30, want: int = 5) -> list:
    """Genere des candidats et check leur dispo Instagram en parallele.
    Retourne les premiers `want` qui sont dispo."""
    candidates = generate_username_candidates(base, count=max_check)
    if not candidates:
        return []
    # Check en parallele (8 en simultane max pour eviter rate-limit)
    semaphore = asyncio.Semaphore(8)
    available = []          # (rang du candidat, pseudo)
    async def check_one(i, u):
        async with semaphore:
            if len(available) >= want:
                return
            ok = await check_instagram_username_available(u)
            if ok:
                available.append((i, u))
    tasks = [asyncio.create_task(check_one(i, c)) for i, c in enumerate(candidates)]
    # Attend jusqu'a ce qu'on en ait assez OU qu'on ait tout teste
    done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED, timeout=20)
    for t in pending:
        t.cancel()
    # Rend les dispos dans l'ORDRE de generation (= du plus proche du vrai
    # prenom au plus decore), et non dans l'ordre d'arrivee des reponses API.
    available.sort(key=lambda x: x[0])
    return [u for _, u in available[:want]]


def random_name_for(identity):
    """names.txt de l'identité + bibliothèque « Names » du site."""
    items = read_lines(IDENTITIES_DIR / identity / "names.txt")
    items = items + [x for x in _vault_texts("names", identity) if x not in items]
    return unescape_newlines(random.choice(items)) if items else None


# === DISPLAY NAME GENERATOR (Instagram-style) ===

# Noms de famille FR / international qui passent bien sur IG
_LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Durand", "Robert", "Petit", "Richard",
    "Moreau", "Laurent", "Lefebvre", "Roux", "Fournier", "Mercier", "Bonnet",
    "Lambert", "Rousseau", "Vincent", "Muller", "Lefevre", "Garnier", "Faure",
    "Andre", "Mercier", "Blanc", "Henry", "Roussel", "Garcia", "David", "Bertrand",
    "Charpentier", "Renard", "Marchand", "Carpentier", "Vidal", "Caron", "Hubert",
    "Aubert", "Rey", "Lemoine", "Riviere", "Fontaine", "Olivier", "Lopez",
    "Gauthier", "Lacroix", "Gerard", "Renaud", "Dumont", "Roger", "Schmitt",
    "Colin", "Mathieu", "Roy", "Picard", "Roche", "Boyer", "Aubry", "Dupuis",
    "Lemoine", "Brun", "Adam", "Joly", "Roussel", "Carre", "Camus", "Renard",
    # International qui marche bien sur IG
    "Rose", "Stone", "Wilde", "Storm", "Lane", "Reed", "Knox", "Wood",
    "Cole", "Quinn", "Ray", "Page", "Lee", "May", "Belle", "Fox",
]
_NAME_EMOJIS = [
    "🌹", "🤍", "💕", "✨", "🌸", "🦋", "🌟", "💫", "🌺", "🍒",
    "💋", "🔥", "❤️", "🌷", "💞", "👼", "🌙", "💎", "🦄", "🐝",
    "",  # Vide aussi pour avoir des noms sans emoji parfois
    "", "", "",
]
_SEPARATORS = [" ", " | ", " • ", " · ", " "]


def _capitalize_smart(s: str) -> str:
    """amelia -> Amélia (avec accent si pertinent)."""
    s = s.strip().lower()
    if not s:
        return ""
    # Petit accent automatique sur prenoms FR courants
    accents_map = {
        "amelia": "Amélia", "celia": "Célia", "emelia": "Émelia",
        "agathe": "Agathe", "agnes": "Agnès", "anais": "Anaïs",
        "andrea": "Andréa", "charlene": "Charlène", "chloe": "Chloé",
        "clemence": "Clémence", "elea": "Éléa", "eleonore": "Éléonore",
        "elise": "Élise", "eloise": "Éloïse", "elodie": "Élodie",
        "emilie": "Émilie", "ines": "Inès", "lea": "Léa",
        "noemie": "Noémie", "phebe": "Phébé", "renee": "Renée",
        "salome": "Salomé", "valerie": "Valérie", "zoe": "Zoé",
    }
    if s in accents_map:
        return accents_map[s]
    return s[0].upper() + s[1:]


# Diminutifs CURES par prenom. REGLE : chaque forme doit se lire comme un vrai
# surnom/prenom qu'une fille utiliserait vraiment. On n'accepte AUCUN bout de mot
# decoupe qui ne veut rien dire (« lia », « licia », « alic », « emm », « jes »).
_KNOWN_DIM = {
    "amelia": ["ame", "amy", "mel", "ameli", "melie"],
    "emma": ["emy", "emmy", "emmi", "emmie", "em"],
    "julia": ["jul", "juju", "juli", "julie"],
    "lola": ["lolo", "lou", "loula", "lolie", "lolou"],
    "alicia": ["ali", "alice", "lili", "alissa", "alicya"],
    "jessye": ["jess", "jessy", "jessie", "jessica", "jessa"],
    "jessy": ["jess", "jessi", "jessie", "jessica"],
    "sarah": ["sara", "sasa", "sarra"],
    "sophia": ["soph", "sofy", "sophie"],
    "chloe": ["chlo", "cloe", "kloe"],
    "lea": ["leya", "leia"],
    "ines": ["inez", "inou"],
    "manon": ["mano", "manou"],
    "lucie": ["lulu", "luce", "lucy"],
    "camille": ["cam", "cami", "milie"],
    "marie": ["mary", "mimi", "marion"],
}


def _get_diminutives(base: str) -> list:
    """Surnoms PROCHES du vrai prenom, ORDONNES du plus reconnaissable au moins.

    UNIQUEMENT la liste CUREE (_KNOWN_DIM). On ne decoupe plus le prenom
    automatiquement : toutes les regles de troncature finissaient par sortir des
    bouts de mots qui ne veulent rien dire (« lia », « licia », « alic », « emm »,
    « jes », « lol ») ou des doublages ratés (« jeje », « mama »). Un prenom
    inconnu n'a donc pas de surnom — il recevra des pseudos « prenom + nom de
    famille », qui se lisent toujours comme une vraie personne.

    Ex: amelia -> ['ame', 'amy', 'mel', 'ameli', 'melie']
        julia  -> ['jul', 'juju', 'juli', 'julie']
        lola   -> ['lolo', 'lou', 'loula']
    """
    base = _ascii_name(base)          # « Amélia » -> « amelia » (sinon aucun surnom)
    if len(base) < 3:
        return []
    out = []
    for d in _KNOWN_DIM.get(base, []):
        d = (d or "").strip().lower()
        if 2 <= len(d) <= 7 and d.isalpha() and d != base and d not in out:
            out.append(d)
    return out


# Petites decorations de vrais mots ajoutees au prenom (jamais de consonnes au
# hasard) : le pseudo doit rester lisible comme un vrai compte.
# NB : nom distinct de _SEPARATORS (ligne ~678, pour les NOMS affiches) — deux
# globales homonymes, la derniere ecrasait l'autre.
# Le point et l'underscore d'abord : « amelia.rose » se lit mieux que « ameliarose ».
_USERNAME_SEPS = [".", "_", ""]


def generate_display_names(base: str, count: int = 5) -> list:
    """Genere `count` display names varies. Focus sur 'Prenom Nom' avec
    diminutifs + parfois emojis discrets."""
    first = _capitalize_smart(base)
    if not first:
        return []
    # Cree aussi des variants avec diminutifs (Amy Rose, Mel Stone, etc.)
    diminutives = _get_diminutives(base)
    first_variants = [first] + [_capitalize_smart(d) for d in diminutives]
    out = set()
    attempts = 0
    while len(out) < count and attempts < 60:
        attempts += 1
        # Choisit le prenom (de base ou diminutif)
        fv = random.choice(first_variants)
        last = random.choice(_LAST_NAMES)
        # Patterns (focus sur Prenom Nom)
        pattern = random.choices(
            ["first_last", "first_last", "first_last",  # 3x pour favoriser ce format
             "first_last_emoji", "first_only_emoji"],
            weights=[3, 3, 3, 1, 0.5],
        )[0]
        if pattern == "first_last":
            name = f"{fv} {last}"
        elif pattern == "first_last_emoji":
            emoji = random.choice([e for e in _NAME_EMOJIS if e])
            name = f"{fv} {last} {emoji}"
        else:  # first_only_emoji
            emoji = random.choice([e for e in _NAME_EMOJIS if e])
            name = f"{fv} {emoji}"
        out.add(name.strip())
    return list(out)[:count]


SHARED_BIOS_FILE = DATA_DIR / "bios.txt"


def _read_bios_at(path):
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    return [b.strip() for b in content.split("---") if b.strip()]


def _vault_texts(category, identity):
    """Textes de la BIBLIOTHÈQUE du site (data/text_pool.json) pour cette
    identité. Le site écrit là ; le bot lisait seulement les .txt -> les bios
    posées sur le site étaient invisibles pour les VA.

    ⚠️ Les identités du MARCHÉ FR sont volontairement EXCLUES : leur contenu
    ne doit pas bouger tant que l'user ne l'a pas demandé (elles continuent de
    ne servir que leurs .txt, exactement comme avant).

    SAUF UNE RESERVE (25/09/2026) : elle est nee sur le site, son contenu
    n'existe QUE dans la bibliotheque. L'exclusion FR rendait invisibles les
    bios saisies pour une reserve FR, et le menu General repondait « aucune
    bio » alors qu'on venait d'en poser."""
    if _is_fr_market(identity) and not _est_reserve_sure(identity):
        return []
    try:
        import text_pool as _tp
        return [str(e.get("text") or "").strip()
                for e in _tp.list_entries(category, identity=(identity or "").lower())
                if str(e.get("text") or "").strip()]
    except Exception:
        return []


def random_bio_for(identity):
    """Bios de l'identité : fichier bios.txt ET bibliothèque Bios du site.

    ⚠️ Le repli sur les bios PARTAGÉES (data/bios.txt) est réservé au marché
    FR : sans ça, une identité US sans bio recevait des bios françaises."""
    idl = (identity or "").lower().strip()
    if identity:
        bios = _read_bios_at(IDENTITIES_DIR / identity / "bios.txt")
        bios = bios + [b for b in _vault_texts("bios", identity) if b not in bios]
        if bios:
            return unescape_newlines(random.choice(bios))
        if idl and not _is_fr_market(idl):
            return None            # US : pas de repli FR, on dit qu'il n'y en a pas
    # Menu ✨ General : la bio doit venir de la RESERVE. Retomber sur les
    # bios partagees servirait un texte qui n'est ni a elle ni a la model,
    # sans que rien ne le signale ; « aucune bio » dit le vrai manque.
    if _MODEL_REELLE.get():
        return None
    bios = _read_bios_at(SHARED_BIOS_FILE)
    if bios:
        return unescape_newlines(random.choice(bios))
    return None


def _list_clean_videos(identity):
    """Liste les videos clean (hors .example) d'une identite."""
    videos_dir = IDENTITIES_DIR / identity / "videos"
    if not videos_dir.exists():
        return []
    return [
        p for p in videos_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.lower().endswith(".example")
    ]


def _morceaux_discord(texte, taille=1900):
    """Decoupe un texte pour Discord, qui refuse au-dela de 2000 caracteres.

    Ces textes partaient BRUTS : « await _envoyer_texte(interaction, description) ».
    Or l editeur de la Bibliotheque laisse ecrire jusqu a 2200 caracteres, et
    une legende reprise d un post Instagram en fait souvent autant. Discord
    levait alors HTTPException : le VA recevait la video, puis plus rien —
    pas meme un message d erreur, puisque l exception remontait au-dessus de
    la boucle et emportait les envois suivants.

    On coupe aux sauts de ligne quand c est possible : une legende coupee au
    milieu d un mot se recolle mal a la main.
    """
    texte = str(texte or "")
    if not texte.strip():
        return []
    out = []
    while len(texte) > taille:
        coupe = texte.rfind("\n", 0, taille)
        if coupe < taille // 2:          # pas de saut de ligne exploitable
            coupe = texte.rfind(" ", 0, taille)
        if coupe < taille // 2:
            coupe = taille
        out.append(texte[:coupe])
        texte = texte[coupe:].lstrip("\n")
    if texte.strip():
        out.append(texte)
    return out


class _Progression:
    """La barre bleue qui avance pendant que les reels se fabriquent.

    POURQUOI. Entre « je les genere pour toi » et le premier fichier, il se
    passe une minute pendant laquelle le salon ne dit RIEN. Le VA ne sait pas
    si ca travaille, si c est bloque, ni combien de temps il lui reste : il
    relance la commande, ce qui refabrique tout et allonge encore l attente.

    CE QU ELLE MESURE, ELLE NE L INVENTE PAS. Le moteur ecrit deja son
    avancement (`pct`) dans son fichier d etat ; on le lit. La part globale,
    c est « reels finis + avancement de celui en cours », divisee par le
    total. Une barre qui avancerait a l horloge serait une barre qui ment le
    jour ou le rendu se bloque — exactement le jour ou on la regarde.

    UN MESSAGE, EDITE. Pas une pluie de messages : la barre remplace son
    propre contenu. Discord limite les editions, d ou le delai minimum entre
    deux — sans lui, une generation de trois reels declenche une centaine
    d editions et le bot se fait taire par Discord.
    """

    #: Discord tolere mal plus d une edition toutes les quelques secondes.
    DELAI_MINI = 4.0

    def __init__(self, interaction, total, titre="Génération des reels",
                 mot="Reel"):
        self.interaction = interaction
        self.total = max(1, int(total or 1))
        self.titre = titre
        # LE MOT DE L ELEMENT. Le corps disait « Reel N/total » en dur :
        # au-dessus d un TEMPLATE ou d un FLASH, il annoncait le mauvais
        # objet. Le titre ne coiffe que l en-tete, pas les lignes.
        self.mot = str(mot or "Reel")
        self.message = None
        self.faits = 0
        self._dernier = 0.0
        self._fini = False

    @staticmethod
    def _barre(part):
        """Douze cases. Bleu pour ce qui est fait, gris pour le reste."""
        part = max(0.0, min(1.0, float(part or 0.0)))
        pleines = int(round(part * 12))
        return "🟦" * pleines + "⬜" * (12 - pleines)

    def _corps(self, part, detail=""):
        lignes = [self._barre(part) + f"  **{int(round(part * 100))} %**",
                  f"{self.mot} **{min(self.faits + 1, self.total)}/{self.total}**"
                  if not self._fini else f"**{self.total}/{self.total}** — terminé"]
        if detail:
            lignes.append(detail)
        return "\n".join(lignes)

    async def demarrer(self):
        try:
            import discord as _d
            emb = _d.Embed(title="⏳ " + self.titre,
                           description=self._corps(0.0, "démarrage…"),
                           color=_d.Color.blurple())
            self.message = await self.interaction.followup.send(embed=emb, wait=True)
        except Exception:
            self.message = None            # jamais bloquant : c est un confort

    async def poser(self, part, detail="", force=False):
        """Met la barre a `part` (0..1). Silencieux si trop tot, sauf `force`."""
        import time as _t
        if self.message is None:
            return
        if not force and (_t.time() - self._dernier) < self.DELAI_MINI:
            return
        self._dernier = _t.time()
        try:
            import discord as _d
            emb = _d.Embed(
                title=("✅ " if self._fini else "⏳ ") + self.titre,
                description=self._corps(part, detail),
                color=(_d.Color.green() if self._fini else _d.Color.blurple()))
            await self.message.edit(embed=emb)
        except Exception:
            pass

    async def un_de_plus(self):
        """Un reel est parti : on avance d un cran, tout de suite."""
        self.faits += 1
        self._fini = self.faits >= self.total
        await self.poser(self.faits / float(self.total),
                         "" if self._fini else "reel suivant…", force=True)

    def part_courante(self, pct_en_cours):
        """La part globale : les reels finis, plus l avancement du courant."""
        try:
            p = max(0.0, min(100.0, float(pct_en_cours or 0)))
        except Exception:
            p = 0.0
        return (self.faits + p / 100.0) / float(self.total)


async def _envoyer_texte(interaction, texte, copiable=True):
    """Envoie un texte au VA, en autant de messages que Discord l exige.

    EN BLOC DE CODE, et pour deux raisons.

    La premiere est confort : Discord pose un bouton « copier » sur les blocs
    de code. Le VA n a plus a selectionner la legende au doigt sur telephone,
    ce qui rate une ligne sur deux.

    La seconde est une CORRECTION. Un texte nu est interprete en Markdown par
    Discord : « @mon_compte_perso » perd ses underscores et s affiche en
    italique, « 3*5 » mange ses etoiles, et c est CE texte deforme que le VA
    copiait pour le coller en legende Instagram. Le bloc de code n interprete
    rien : ce qu il lit est ce qui a ete ecrit.

    Une legende qui contient elle-meme trois accents graves fermerait le bloc
    par le milieu et le reste sortirait deforme. Ce cas-la repart en texte nu :
    mieux vaut perdre le bouton que livrer une legende fausse.
    """
    t = str(texte or "")
    if copiable and "```" not in t:
        # -12 : la cloture du bloc compte dans les 2000 signes de Discord.
        for bout in _morceaux_discord(t, taille=1880):
            await interaction.followup.send("```\n" + bout + "\n```")
        return
    for bout in _morceaux_discord(t):
        await interaction.followup.send(bout)


_ETRANGER = re.compile(r"(?:^|[^\w@])@[A-Za-z0-9._]{3,}|https?://|\bwww\.")


def desc_retenue(video):
    """La description est-elle une legende REPRISE d un autre compte ?

    Quand un template ou une brute est importe par lien sans description
    saisie, le site recopie la LEGENDE DU POST D ORIGINE dans <stem>.desc.txt
    et pose a cote <stem>.acheck.txt — « reprise du post, a relire ». Ce
    marqueur n avait jamais ete lu ailleurs que par le site : la legende
    partait telle quelle au VA, sous « a coller dans le champ legende », avec
    le @ et les liens d une AUTRE creatrice. C est ce que le proprietaire
    voyait arriver sous ses flash : « des id rien a voir ».

    On ne retient QUE le cas nuisible : marqueur present ET identifiant
    etranger dedans (@compte ou lien). Une accroche relue, ou une accroche
    sans @ ni lien, continue de partir — retenir toutes les descriptions non
    relues assecherait les legendes sans rapport avec le probleme.
    """
    try:
        if not video.with_suffix(".acheck.txt").exists():
            return False
        d = video.with_suffix(".desc.txt")
        if not d.exists():
            return False
        return bool(_ETRANGER.search(d.read_text(encoding="utf-8")))
    except Exception:
        return False


def _video_meta(video):
    """Retourne (caption, description, example_path) pour une video donnee."""
    caption_path = video.with_suffix(".txt")
    desc_path = video.with_suffix(".desc.txt")
    caption = None
    description = None
    if caption_path.exists():
        try:
            caption = caption_path.read_text(encoding="utf-8").strip().replace("\\n", "\n")
        except Exception:
            pass
    if desc_path.exists() and not desc_retenue(video):
        try:
            description = desc_path.read_text(encoding="utf-8").strip().replace("\\n", "\n")
        except Exception:
            pass
    example = None
    for ext in VIDEO_EXTS:
        candidate = video.parent / f"{video.stem}.example{ext}"
        if candidate.exists():
            example = candidate
            break
    return caption, description, example


def random_n_reels_for(identity, n: int):
    """Pioche n reels uniques (sans remise). Retourne une liste de tuples
    (video, caption, description, example). Liste peut etre plus courte si pas assez.
    """
    videos = _list_clean_videos(identity)
    if not videos:
        return []
    n = min(n, len(videos))
    picked = random.sample(videos, n)
    return [(v, *_video_meta(v)) for v in picked]


def va_ready_montages_for(identity, n: int, ecartes=None):
    """Reels APPROUVES « Dispo pour les VA » d'une identite : ceux dont le brouillon de
    montage (<stem>.montage.json a cote de la video) a va_ready=true. La variante MONTEE
    est generee A LA DEMANDE (pas de fichier pre-genere) -> chaque VA une variante unique.
    Retourne n au hasard sans remise : [(video_path, draft_dict, description)]."""
    import json as _json
    ready = []
    sans_montage = 0
    # videos/ ET templates/ : un template approuve est le cas NORMAL depuis
    # l'assemblage brute+template — ne scanner que videos/ le rendait
    # silencieusement invisible pour les VA.
    sources = list(_list_clean_videos(identity))
    _tpl = IDENTITIES_DIR / identity / "templates"
    if _tpl.exists():
        sources += [p for p in _tpl.iterdir()
                    if p.is_file() and p.suffix.lower() in VIDEO_EXTS
                    and not p.stem.lower().endswith(".example")]
    for v in sources:
        mj = v.parent / f"{v.stem}.montage.json"
        if not mj.exists():
            continue
        try:
            draft = _json.loads(mj.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not (isinstance(draft, dict) and draft.get("va_ready")):
            continue
        # NI COUPE, NI SEGMENTS : le moteur ne fait alors RIEN -- il recopie
        # la source telle quelle. Et les sources scannees ici incluent
        # videos/, c'est-a-dire le stock de reels DEJA FINIS : le VA recevait
        # un reel fini sous l'etiquette « REEL MONTE ».
        #
        # Le point de coupe SEUL ne suffit pas comme critere : la commande
        # annonce « Reels DEJA MONTES (texte incruste) », et un brouillon sans
        # coupe mais AVEC des segments produit exactement cela. L'ecarter
        # supprimerait un cas legitime -- c'est l'erreur de mon premier jet.
        try:
            _cut = float((draft or {}).get("cut_at") or 0)
        except (TypeError, ValueError):
            _cut = 0.0
        _segs = (draft or {}).get("segments")
        if _cut <= 0.05 and not (isinstance(_segs, list) and _segs):
            sans_montage += 1
            continue
        _cap, desc, _ex = _video_meta(v)
        ready.append((v, draft, desc))
    # Le compte remonte a l'appelant : « approuve mais vide » et « aucun reel
    # approuve » demandent deux gestes tres differents, et un print dans le
    # journal du VPS n'est lu par personne. Dictionnaire FACULTATIF : les
    # quatre appelants existants ne changent pas.
    if isinstance(ecartes, dict):
        ecartes["sans_montage"] = sans_montage
    if not ready:
        return []
    n = min(n, len(ready))
    return random.sample(ready, n)


def banger_reels_for(identity, limit=15):
    """Reels marques ⭐ banger d'une identite -> [(video, caption, desc, example)].
    Lit data/banger_marks.json (cle file_id = 'identity|videos|filename', cf
    web_upload). Ne garde que les fichiers video encore presents. Plafonne a `limit`."""
    import json as _json
    marks_file = DATA_DIR / "banger_marks.json"
    try:
        raw = _json.loads(marks_file.read_text(encoding="utf-8"))
        keys = list(raw.keys()) if isinstance(raw, dict) else list(raw or [])
    except Exception:
        keys = []
    prefix = f"{identity}|videos|"
    names = []
    for k in keys:
        if isinstance(k, str) and k.startswith(prefix):
            fn = k[len(prefix):]
            if fn and fn not in names:
                names.append(fn)
    vids_dir = IDENTITIES_DIR / identity / "videos"
    out = []
    for fn in names:
        p = vids_dir / fn
        if p.exists() and p.is_file():
            out.append((p, *_video_meta(p)))
            if limit and len(out) >= limit:
                break
    return out


def fav_brutes_for(identity, limit=15):
    """Rushs bruts marques ⭐ favoris d'une identite -> [Path].

    Lit data/fav_brutes.json (cle file_id = 'identity|brutes|filename', ecrite
    par le site). ATTENTION : ce n'est PAS banger_marks.json, qui porte le meme
    symbole mais garde les ACCUSES d'envoi Discord.

    Ne pas se fier a l'ancienne formule « simple favori local » : depuis que
    l'envoi a ete branche, etoiler une brute sur le site la poste AUSSI dans
    banger-{identite}. Ce registre-ci reste malgre tout la seule source pour
    « Video brut Banger » -- la marque est conservee meme quand l'envoi
    echoue.

    Ne garde que les fichiers encore presents sur le disque : une brute
    supprimee laisserait sinon une cle orpheline, et le VA s'entendrait
    annoncer des brutes qui n'existent plus.
    """
    import json as _json
    fav_file = DATA_DIR / "fav_brutes.json"
    try:
        raw = _json.loads(fav_file.read_text(encoding="utf-8"))
        keys = list(raw.keys()) if isinstance(raw, dict) else list(raw or [])
    except Exception:
        keys = []
    prefix = f"{identity}|brutes|"
    names = []
    for k in keys:
        if isinstance(k, str) and k.startswith(prefix):
            fn = k[len(prefix):]
            if fn and fn not in names:
                names.append(fn)
    # Ce chemin lit un REGISTRE, pas le dossier : il ne passe donc pas par
    # brutes_off.lister et doit ecarter les desactivees lui-meme. Une brute
    # marquee favorite AVANT d etre eteinte serait sinon la seule a passer au
    # travers — et c est justement celle qu on envoie le plus souvent.
    import brutes_off as _off
    brutes_dir = IDENTITIES_DIR / identity / "brutes"
    out = []
    for fn in names:
        p = brutes_dir / fn
        if p.exists() and p.is_file() and not _off.est_desactivee(p):
            out.append(p)
            if limit and len(out) >= limit:
                break
    return out


def trends_for(identity, limit=3):
    """Les videos FINIES d une identite -> [Path].

    Rangees dans data/identities/<identite>/trends par le site (onglet
    « Trends »). Ce ne sont PAS des brutes : elles sont pretes a poster telles
    quelles, et c est exactement pour ca qu elles vivent dans leur propre
    dossier — melanger le produit fini a la matiere premiere ferait envoyer
    l un en croyant l autre, dans les deux sens.

    Le stock est volontairement petit (les meilleures). On tire au hasard
    plutot que de servir toujours les memes en tete de liste : deux VA qui
    cliquent a la minute recevraient sinon la meme video.
    """
    # TROIS dossiers, pas un : « trends » recoit les depots a la main, et
    # « trends_caption » / « trends_template » ce qui sort des editeurs Perfect.
    # N en lire qu un laissait le VA sans rien alors que le stock etait plein —
    # rangé dans les deux autres.
    base = IDENTITIES_DIR / identity
    fichiers = []
    for nom in ("trends", "trends_caption", "trends_template"):
        d = base / nom
        if d.is_dir():
            fichiers.extend(p for p in sorted(d.iterdir())
                            if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    if not fichiers:
        return []
    if limit and len(fichiers) > limit:
        return random.sample(fichiers, limit)
    random.shuffle(fichiers)
    return fichiers


def fav_templates_for(identity, limit=15):
    """Templates marques ⭐ favoris -> (utilisables, sans_point_de_coupe).

    `utilisables` = [(Path, draft)] : les templates dont le brouillon
    <stem>.montage.json porte un cut_at exploitable. `sans_point_de_coupe` = le
    NOMBRE de templates etoiles qu'on a du ecarter.

    Pourquoi ce second nombre. Le moteur prend le template comme SOURCE et
    n'insere une brute que s'il trouve un point de coupe (_prepare_inputs :
    « brutes = list_brutes(...) if (brutes_dir and cut > 0.05) »). Sans cut_at
    il recopie le template seul : le VA recevrait une video ou sa brute
    favorite n'apparait PAS, et personne ne saurait pourquoi. On les ecarte
    donc, et on les compte pour pouvoir le dire — plutot que de les ignorer en
    silence.
    """
    import json as _json
    fav_file = DATA_DIR / "fav_brutes.json"      # meme registre, cle par sous-dossier
    try:
        raw = _json.loads(fav_file.read_text(encoding="utf-8"))
        keys = list(raw.keys()) if isinstance(raw, dict) else list(raw or [])
    except Exception:
        keys = []
    prefix = f"{identity}|templates|"
    names = []
    for k in keys:
        if isinstance(k, str) and k.startswith(prefix):
            fn = k[len(prefix):]
            if fn and fn not in names:
                names.append(fn)
    tdir = IDENTITIES_DIR / identity / "templates"
    utilisables, sans_coupe = [], 0
    for fn in names:
        p = tdir / fn
        if not (p.exists() and p.is_file()):
            continue
        mj = p.parent / f"{p.stem}.montage.json"
        if not mj.exists():
            sans_coupe += 1
            continue
        try:
            draft = _json.loads(mj.read_text(encoding="utf-8"))
        except Exception:
            sans_coupe += 1
            continue
        try:
            cut = float((draft or {}).get("cut_at") or 0)
        except (TypeError, ValueError):
            cut = 0.0
        if cut <= 0.05:
            sans_coupe += 1
            continue
        utilisables.append((p, draft))
        if limit and len(utilisables) >= limit:
            break
    return utilisables, sans_coupe


def tous_templates_for(identity, limit=15):
    """TOUS les templates exploitables d'une identite -> ([(Path, draft)], nb).

    Meme contrat et MEME validation que fav_templates_for : un template sans
    point de coupe est ecarte et compte, parce que le moteur le recopierait tel
    quel et que la brute n'apparaitrait pas dans la video.

    LA SEULE DIFFERENCE EST LE VIVIER. fav_templates_for part des noms etoiles
    lus dans fav_brutes.json ; celle-ci part du DOSSIER. Elle sert la famille
    « template_vid » (bouton ⭐ Brut + Template), ou c'est la brute qui porte
    l'etoile et ou la matiere est prise au hasard.

    Pourquoi elle n'existait pas : jusqu'ici aucune recette n'avait besoin d'un
    template non etoile. L'etoile de la brute ne pouvait se combiner qu'avec
    une matiere elle aussi etoilee -- voir le commentaire de FAMILLES dans
    noctus_reserve.py.
    """
    import json as _json
    tdir = IDENTITIES_DIR / (identity or "").lower().strip() / "templates"
    if not tdir.is_dir():
        return [], 0
    utilisables, sans_coupe = [], 0
    for p in sorted(tdir.iterdir()):
        if not (p.is_file() and p.suffix.lower() in VIDEO_EXTS):
            continue
        mj = p.parent / f"{p.stem}.montage.json"
        if not mj.exists():
            sans_coupe += 1
            continue
        try:
            draft = _json.loads(mj.read_text(encoding="utf-8"))
        except Exception:
            sans_coupe += 1
            continue
        try:
            cut = float((draft or {}).get("cut_at") or 0)
        except (TypeError, ValueError):
            cut = 0.0
        if cut <= 0.05:
            sans_coupe += 1
            continue
        utilisables.append((p, draft))
        if limit and len(utilisables) >= limit:
            break
    return utilisables, sans_coupe


def _cles_registre(fichier):
    """Les cles « identite|dossier|fichier » d'un registre du site, toleres
    en liste comme en dict. Absent ou illisible : ensemble vide -- ces
    registres-la (etoiles, ⊘) n'ont jamais bloque un bouton, on ne commence
    pas ici."""
    try:
        raw = json.loads((DATA_DIR / fichier).read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(raw, dict):
        return {k for k in raw if isinstance(k, str)}
    if isinstance(raw, list):
        return {k for k in raw if isinstance(k, str)}
    return set()


def marque_templates_for(cle, identity, limit=15, exiger_banger=False,
                         ecartes=None):
    """Templates portant la marque `cle` (« flash », « trash ») ->
    ([(Path, draft)], nb_sans_coupe).

    Meme contrat que fav_templates_for, meme validation : un template sans
    point de coupe est ECARTE et COMPTE, parce que le moteur le recopierait
    tel quel et que le VA recevrait une video ou aucune brute n'apparait.

    `exiger_banger` demande en plus l'etoile. L'etoile vit dans un autre
    fichier et se cumule avec la marque (⭐ + ⚡ = « Flash Banger »).

    CE QUI EST ENCORE ECARTE, ET COMPTE dans `ecartes` (dict facultatif :
    les appelants a deux valeurs, dont le stock, ne changent pas) :

      desactives  le ⊘ du site (disabled_reels.json). Aucun selecteur du bot
                  ne le lisait : un template mis de cote partait quand meme
                  par ⚡ Flash. Corrige ICI pour les deux marques, sinon
                  « desactive » ne voudrait rien dire pour Trash non plus.
      conflits    un montage marque aussi d'une marque PRIORITAIRE
                  (marques_montage.PRIORITE : Flash l'emporte). Le site rend
                  les marques exclusives a l'ecriture ; une donnee ancienne
                  peut encore porter les deux, et le meme template partirait
                  alors par deux familles de boutons -- publie deux fois.
      erreurs     un registre de marque qui existe mais ne se lit pas. Le
                  dire, sinon « aucun montage » envoie chercher une panne
                  qui n'existe pas.

    Le bot ne fait que LIRE ces registres : aucune ecriture ici.
    """
    import json as _json
    fiche = marques_montage.marque(cle)
    cles, err = marques_montage.lire_cles_ou_erreur(DATA_DIR / fiche["fichier"])
    erreurs = [err] if err else []
    p = f"{identity}|templates|"
    noms = {k[len(p):] for k in cles if k.startswith(p) and k[len(p):]}
    if exiger_banger:
        noms &= {k[len(p):] for k in _cles_registre("fav_brutes.json")
                 if k.startswith(p)}

    # Flash l'emporte sur Trash : on retire ce qu'une marque PLUS prioritaire
    # porte deja. Un registre prioritaire illisible ne bloque pas le bouton
    # (on ne peut plus trier les doubles) : on le dit.
    conflits = 0
    for autre in marques_montage.PRIORITE[:marques_montage.PRIORITE.index(cle)]:
        a_cles, a_err = marques_montage.lire_cles_ou_erreur(
            DATA_DIR / marques_montage.marque(autre)["fichier"])
        if a_err:
            erreurs.append(a_err + " : doubles marques non verifiees")
            continue
        doubles = {n for n in noms if p + n in a_cles}
        conflits += len(doubles)
        noms -= doubles

    eteints = _cles_registre("disabled_reels.json")
    desactives = {n for n in noms if p + n in eteints}
    noms -= desactives

    tdir = IDENTITIES_DIR / identity / "templates"
    utilisables, sans_coupe = [], 0
    for fn in sorted(noms):
        chemin = tdir / fn
        if not (chemin.exists() and chemin.is_file()):
            continue
        mj = chemin.parent / f"{chemin.stem}.montage.json"
        if not mj.exists():
            sans_coupe += 1
            continue
        try:
            draft = _json.loads(mj.read_text(encoding="utf-8"))
            cut = float((draft or {}).get("cut_at") or 0)
        except Exception:
            sans_coupe += 1
            continue
        if cut <= 0.05:
            sans_coupe += 1
            continue
        utilisables.append((chemin, draft))
        if limit and len(utilisables) >= limit:
            break
    if isinstance(ecartes, dict):
        ecartes.update(sans_coupe=sans_coupe, desactives=len(desactives),
                       conflits=conflits, erreurs=erreurs)
    return utilisables, sans_coupe


def flash_templates_for(identity, limit=15, exiger_banger=False, ecartes=None):
    """Templates marques Flash Trend -> ([(Path, draft)], nb_sans_coupe).

    Garde son nom : cogs/noctuspool.py et le diagnostic du site l'appellent.
    Tout le travail est dans marque_templates_for.
    """
    return marque_templates_for("flash", identity, limit=limit,
                                exiger_banger=exiger_banger, ecartes=ecartes)


def _reserve_ouverte_aux_va() -> bool:
    """La reserve sert-elle encore de cache aux boutons Discord ?

    Elle a d'abord ete cela : une variante deja fabriquee partait tout de
    suite au lieu des 15 a 30 s de generation. Depuis que le parc y puise
    aussi, les deux se disputaient le meme stock -- et un VA qui trouve la
    case vide genere et obtient sa video, quand le parc, lui, ne publie rien.

    Decision du proprietaire, 13/09/2026 : le stock est au parc. On lit le
    drapeau A CHAQUE APPEL et non a l'import, pour que le rallumer ne demande
    pas de redemarrer le bot.

    Jamais pendant un clic du menu ✨ General : le stock est indexe par la
    seule identite (ici la reserve), il ne sait pas sur la brute de QUELLE
    model une variante a ete montee. Le jour ou POUR_LES_VA repasse a True,
    Lola recevrait sinon une video montee sur la brute de Julia.
    """
    if _MODEL_REELLE.get():
        return False
    try:
        import noctus_reserve as _res
        return bool(getattr(_res, "POUR_LES_VA", True))
    except Exception:
        return False


def fav_captions_for(identity):
    """Captions marquees ⭐ favorites ET encore dans le tirage -> [dict].

    Les deux conditions comptent. Une caption etoilee puis DESACTIVEE ne doit
    pas partir — mais repondre « aucune caption favorite » serait un mensonge
    que personne ne saurait deboguer. L'appelant distingue les deux cas grace
    a fav_captions_desactivees().
    """
    items = _captions_block(identity).get("items") or []
    return [c for c in items
            if c.get("fav") is True and c.get("enabled", True)
            and str(c.get("text") or "").strip()]


def fav_captions_desactivees(identity):
    """Captions favorites mises HORS TIRAGE. Sert a nommer le vrai probleme."""
    items = _captions_block(identity).get("items") or []
    return [c for c in items
            if c.get("fav") is True and not c.get("enabled", True)
            and str(c.get("text") or "").strip()]


def random_reel_for(identity):
    """Pick random clean video + caption + description + example_path|None.
    Returns (Path, caption|None, description|None, example_Path|None).
    Conserve pour la compatibilite (autopost.send_reel etc.).
    """
    videos_dir = IDENTITIES_DIR / identity / "videos"
    if not videos_dir.exists():
        return None, None, None, None
    # Filtrer les videos clean (pas les .example.*)
    videos = [
        p for p in videos_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not videos:
        return None, None, None, None
    video = random.choice(videos)
    caption_path = video.with_suffix(".txt")
    desc_path = video.with_suffix(".desc.txt")
    caption = None
    description = None
    if caption_path.exists():
        caption = unescape_newlines(caption_path.read_text(encoding="utf-8").strip())
    if desc_path.exists():
        description = unescape_newlines(desc_path.read_text(encoding="utf-8").strip())
    # Chercher la video exemple
    example = None
    for ext in VIDEO_EXTS:
        candidate = videos_dir / f"{video.stem}.example{ext}"
        if candidate.exists():
            example = candidate
            break
    return video, caption, description, example


def _identity_pp_dir(identity):
    """Dossier des PP propres à une identité (ex: jessye marché US)."""
    return IDENTITIES_DIR / (identity or "").strip().lower() / "profile_pics"


def random_profile_pic(identity=None):
    """PP au hasard : si l'identité a ses PROPRES PP (data/identities/<id>/profile_pics/)
    on pioche dedans ; sinon on retombe sur le pool partagé (marché FR)."""
    if identity:
        d = _identity_pp_dir(identity)
        if d.exists():
            own = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
            if own:
                return random.choice(own)
    # Menu ✨ General : une reserve sans PP repond « aucune PP ». Le pool
    # partage donnerait une photo qui n'est pas la sienne, et le VA la
    # posterait comme si elle l'etait.
    if _MODEL_REELLE.get():
        return None
    if not PROFILE_PICS_DIR.exists():
        return None
    pics = [p for p in PROFILE_PICS_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return random.choice(pics) if pics else None


def random_image_with_pair(directory):
    """Pick a random clean image + caption + description + example. Skips .example.* files."""
    if not directory.exists():
        return None, None, None, None
    images = [
        p for p in directory.iterdir()
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not images:
        return None, None, None, None
    image = random.choice(images)
    cap_path = image.with_suffix(".txt")
    desc_path = image.with_suffix(".desc.txt")
    caption = unescape_newlines(cap_path.read_text(encoding="utf-8").strip()) if cap_path.exists() else None
    description = unescape_newlines(desc_path.read_text(encoding="utf-8").strip()) if desc_path.exists() else None
    example = None
    for ext in IMAGE_EXTS:
        candidate = directory / f"{image.stem}.example{ext}"
        if candidate.exists():
            example = candidate
            break
    return image, caption, description, example


def random_post_for(identity):
    return random_image_with_pair(IDENTITIES_DIR / identity / "posts")


def random_story_for(identity):
    return random_image_with_pair(IDENTITIES_DIR / identity / "stories")


STORY_CTA_CAPTIONS_FILE = DATA_DIR / "story_cta_captions.txt"


def random_story_cta_caption():
    if not STORY_CTA_CAPTIONS_FILE.exists():
        return None
    lines = [l.strip() for l in STORY_CTA_CAPTIONS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    return unescape_newlines(random.choice(lines)) if lines else None


def random_story_cta_image_for(identity):
    d = IDENTITIES_DIR / identity / "storyctas"
    if not d.exists():
        return None
    images = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return random.choice(images) if images else None


import contextvars
# Override d'identite (menu Jailbreak) : quand il est pose, get_user_identity
# renvoie CETTE identite a la place de celle stockee pour le VA. Local a la task
# asyncio (contextvars) -> aucune interference entre interactions concurrentes.
# Par defaut None = comportement STRICTEMENT identique pour tous les VAs normaux.
_IDENTITY_OVERRIDE = contextvars.ContextVar("identity_override", default=None)

# Menu « ✨ General » : _IDENTITY_OVERRIDE y vaut la RESERVE (tout le contenu
# vient d'elle, sans toucher aux fonctions de tirage), et celui-ci la MODEL
# cliquee, dont on prend la VIDEO BRUTE. Pas « reserve » dans le nom : ce
# mot designe deja ici le stock noctus (_reserve_ouverte_aux_va).
# None hors General = chemins d'avant, a l'identique.
_MODEL_REELLE = contextvars.ContextVar("model_reelle", default=None)


def _identite_en_pause(identity) -> bool:
    """identite_pause.en_pause, sans jamais planter un envoi : repli OUVERT
    (pas en pause) et journalise."""
    try:
        import identite_pause as _ip
        return _ip.en_pause(identity)
    except Exception as e:
        log.warning("controle « pause » indisponible pour %r (%s: %s)",
                    identity, type(e).__name__, e)
        return False


def _dossier_brutes(identity):
    """LE seul endroit qui dit d'ou vient la brute : la model reelle pendant
    un clic General, sinon l'identite elle-meme. Les quatre chemins qui
    montent une brute l'appellent ; recalcule a chacun, un seul oubli aurait
    monte le contenu de Blonde sur un dossier vide (template nu)."""
    return IDENTITIES_DIR / ((_MODEL_REELLE.get() or identity or "").strip().lower()) / "brutes"


def _est_reserve_sure(identity) -> bool:
    """type_identite.est_reserve, sans jamais faire planter un tirage : si le
    module ne repond pas, on garde le comportement d'avant (pas une reserve)
    et on le journalise."""
    try:
        import type_identite as _ti
        return _ti.est_reserve(identity)
    except Exception as e:
        log.warning("controle « reserve » indisponible pour %r (%s: %s)",
                    identity, type(e).__name__, e)
        return False


def get_user_identity(user_id):
    _ov = _IDENTITY_OVERRIDE.get()
    if _ov:
        return _ov
    users = load_json(USERS_FILE, {})
    data = users.get(str(user_id))
    if data is None:
        return None
    if isinstance(data, str):
        return data  # legacy format
    if isinstance(data, dict):
        return data.get("identity")
    return None


def _has_jailbreak_role(member):
    """True si le membre a le role 'Jailbreak' (ou est staff/admin, pour tester)."""
    try:
        if any((getattr(r, "name", "") or "").strip().lower() == "jailbreak"
               for r in getattr(member, "roles", [])):
            return True
    except Exception:
        pass
    try:
        return _is_staff_member(member)
    except Exception:
        return False


def _jb_can_use(interaction):
    """Accès aux menus Jailbreak : rôle « Jailbreak » — OU serveur US, où le menu
    est ouvert à TOUT LE MONDE (demande explicite : pas de rôle à gérer là-bas)."""
    try:
        import guild_features as gf
        if gf.is_us_guild(getattr(interaction, "guild", None)):
            return True
    except Exception:
        pass
    return _has_jailbreak_role(interaction.user)


def _us_content_channel_for(guild, member):
    """Salon @pseudo-content du membre sur le serveur US, ou None."""
    try:
        from cogs.welcome import _us_ticket_name, _us_norm
        name = _us_ticket_name(member, "content")
        return discord.utils.find(
            lambda c, n=name: _us_norm(c.name) == n, guild.text_channels)
    except Exception:
        return None


def _us_content_target(interaction):
    """Le salon -content correspondant au salon COURANT.

    Avant, on cherchait le -content du CLIQUEUR : un admin qui teste dans le
    -menu de quelqu'un d'autre n'en a pas, la redirection ne se faisait pas,
    et le contenu se deversait dans le -menu. On suit donc le salon, pas la
    personne : meme categorie (le dossier de la personne), sinon meme prefixe,
    et en dernier recours le -content du cliqueur."""
    ch = getattr(interaction, "channel", None)
    guild = getattr(interaction, "guild", None)
    if ch is None or guild is None:
        return None
    try:
        from cogs.welcome import _us_norm
    except Exception:
        return None
    try:
        cat = getattr(ch, "category", None)
        if cat is not None:
            for c in getattr(cat, "text_channels", []):
                if _us_norm(c.name).endswith("-content"):
                    return c
        nom = _us_norm(getattr(ch, "name", ""))
        if nom.endswith("-menu"):
            cible = nom[: -len("-menu")] + "-content"
            c = discord.utils.find(
                lambda x, t=cible: _us_norm(x.name) == t, guild.text_channels)
            if c is not None:
                return c
    except Exception:
        pass
    return _us_content_channel_for(guild, getattr(interaction, "user", None))


def _est_salon_menu(ch) -> bool:
    try:
        from cogs.welcome import _us_norm
        return _us_norm(getattr(ch, "name", "")).endswith("-menu")
    except Exception:
        return False


class _RedirectFollowup:
    """followup.send qui route les messages NON-éphémères vers un autre salon.

    Les éphémères, eux, ne s'EMPILENT plus : le premier devient LE message,
    les suivants l'éditent. Le salon -menu restait sinon jonché de « Aucun
    story… » et « Direction #content » a chaque clic."""
    def __init__(self, real_followup, target_channel, interaction=None):
        self._real = real_followup
        self._target = target_channel
        self._itx = interaction
        self._pose = False

    async def send(self, content=None, **kw):
        if kw.get("ephemeral"):
            if self._itx is not None and self._pose:
                # deja un message prive affiche -> on le remplace
                garde = {k: v for k, v in kw.items()
                         if k in ("embed", "embeds", "view", "attachments")}
                try:
                    return await self._itx.edit_original_response(
                        content=content, **garde)
                except Exception:
                    pass
            self._pose = True
            return await self._real.send(content, **kw)
        if self._target is None:
            # Aucun -content trouve : plutot que de polluer le salon -menu
            # (qui ne doit contenir QUE les deux menus), on repond en prive.
            kw["ephemeral"] = True
            return await self._real.send(content, **kw)
        kw.pop("ephemeral", None)
        kw.pop("wait", None)  # kwarg webhook, inconnu de TextChannel.send
        if content is None:
            return await self._target.send(**kw)
        return await self._target.send(content, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _RedirectResponse:
    """`interaction.response.send_message` qui route le NON-éphémère vers le
    salon -content.

    Le proxy ne couvrait que `followup` : les commandes qui repondent
    directement (77 appels dans ce fichier, dont les bios) deversaient leur
    contenu dans le salon -menu. On accuse reception de l'interaction par un
    defer ephemere, puis on ecrit dans le bon salon."""
    def __init__(self, real_response, target_channel, interaction):
        self._real = real_response
        self._target = target_channel
        self._itx = interaction

    async def send_message(self, content=None, **kw):
        if kw.get("ephemeral"):
            return await self._real.send_message(content, **kw)
        kw.pop("ephemeral", None)
        try:
            if not self._real.is_done():
                await self._real.defer(ephemeral=True)
        except Exception:
            pass
        if self._target is None:      # pas de -content : surtout pas ici
            return await self._itx.followup.send(content, ephemeral=True, **kw)
        kw.pop("wait", None)
        if content is None:
            return await self._target.send(**kw)
        return await self._target.send(content, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _JBRedirect:
    """Proxy d'interaction pour le menu Jailbreak du serveur US : le contenu
    généré part dans le salon -content du membre (le salon -menu reste vierge).
    Tout le reste (response.defer, user, guild…) est délégué tel quel."""
    def __init__(self, interaction, target_channel):
        object.__setattr__(self, "_itx", interaction)
        object.__setattr__(self, "followup", _RedirectFollowup(
            interaction.followup, target_channel, interaction))
        object.__setattr__(self, "response", _RedirectResponse(
            interaction.response, target_channel, interaction))

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_itx"), name)


class GenLinkButton(discord.ui.DynamicItem[discord.ui.Button], template=r"genlink:(?P<uid>\d+)"):
    """Bouton « Générer le lien » sur une demande de lien. L'ID du VA est dans le
    custom_id -> persistant (marche même après un redémarrage du bot). Réservé staff.
    Au clic : génère le lien GMS et l'envoie dans le salon perso du VA."""

    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        super().__init__(
            discord.ui.Button(
                label="Générer le lien", emoji="🔗",
                style=discord.ButtonStyle.success,
                custom_id=f"genlink:{int(user_id)}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if not _menu_feature_check(interaction, "liens"):
            await interaction.response.send_message("⚠️ Génération de lien désactivée sur ce serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        uid = self.user_id
        # Bloc DUR anti-doublon (couche 1, locale) : ce VA a déjà eu un lien -> on refuse.
        _ex = _lr_existing(uid)
        if _ex:
            await _lr_send_blocked(interaction, uid, _ex.get("url", ""))
            return
        # Verrou anti double-clic : la génération est lente (réseau) ; on empêche
        # une 2e génération concurrente pour le même VA tant que celle-ci tourne.
        # (check + add sans await entre les deux -> atomique côté asyncio)
        if uid in _LINK_GEN_INFLIGHT:
            try:
                await interaction.followup.send(
                    "⏳ Une génération est déjà en cours pour ce VA — patiente quelques secondes.",
                    ephemeral=True,
                )
            except Exception:
                pass
            return
        _LINK_GEN_INFLIGHT.add(uid)
        try:
            # Identité du LIEN = identité dédiée du serveur (ex: hybride) si définie.
            identity = _link_identity(interaction.guild, uid)
            if not identity:
                await interaction.followup.send("⚠️ Ce VA n'a pas d'identité assignée (`/adduser`).", ephemeral=True)
                return
            # Salon perso + handle du VA
            users = load_json(USERS_FILE, {})
            data = users.get(str(uid), {})
            ch_id = data.get("channel_id") if isinstance(data, dict) else None
            va_ch = interaction.client.get_channel(ch_id) if ch_id else None
            handle = ""
            if va_ch:
                m = re.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (va_ch.name or "").lower())
                handle = m.group(1) if m else ""
            if not handle:
                member = interaction.guild.get_member(uid) if interaction.guild else None
                handle = (getattr(member, "name", "") or "").lower()
            try:
                import gms
            except Exception as e:
                await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
                return
            # Bloc DUR anti-doublon (couche 2, GMS) : un lien va_@<handle> existe déjà
            # côté GetMySocial (ex: créé via le site). On utilise un match STRICT
            # (pas de substring) pour ne jamais bloquer un VA différent par erreur.
            if handle:
                try:
                    _all = await asyncio.to_thread(gms.list_all_links)
                except Exception:
                    _all = {"ok": False}
                # Fail-closed : si on ne peut pas vérifier, on n'invente pas un lien.
                if not _all.get("ok"):
                    await interaction.followup.send(
                        "⚠️ Impossible de vérifier sur GetMySocial pour l'instant (API indispo). "
                        "Génération annulée par sécurité (anti-doublon) — réessaie dans un instant.",
                        ephemeral=True,
                    )
                    return
                _hit = _gms_exact_link(handle, _all.get("links") or [])
                if _hit:
                    _sc = _hit.get("shortcode", "")
                    _u = f"{gms.PUBLIC_LINK_DOMAIN}/{_sc}" if _sc else ""
                    _lr_mark_generated(uid, _u, _hit.get("display_name", ""))
                    await _lr_send_blocked(interaction, uid, _u, source="gms")
                    return
            try:
                res = await asyncio.to_thread(gms.quick_generate_for_identity, identity, handle)
            except Exception as e:
                await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
                return
            if not res.get("ok"):
                await interaction.followup.send(f"❌ {res.get('error', 'Génération échouée')}", ephemeral=True)
                return
            url = res.get("public_url", "")
            _lr_mark_generated(uid, url, res.get("va_name", ""))  # bloc dur + clôt la demande
            if va_ch:
                try:
                    await va_ch.send(_link_message(url, getattr(va_ch, "guild", None)))
                except Exception:
                    pass
                try:
                    await _apply_va_link_mark(va_ch, True, reason="lien généré")
                except Exception:
                    pass
            # Marque la demande comme traitée (retire le bouton)
            try:
                await interaction.message.edit(
                    content=f"✅ Lien généré par {interaction.user.mention} : {url}", view=None
                )
            except Exception:
                pass
            try:
                await interaction.followup.send(
                    f"✅ Lien généré pour <@{uid}> (`{identity}`) : {url}"
                    + (f"\n→ envoyé dans {va_ch.mention}" if va_ch else " (⚠️ salon VA introuvable — copie-le manuellement)"),
                    ephemeral=True,
                )
            except Exception:
                pass
        finally:
            _LINK_GEN_INFLIGHT.discard(uid)


class _SendProxy:
    """Imite interaction.response ET interaction.followup mais envoie dans un salon cible.
    Permet de réutiliser les commandes telles quelles en redirigeant leur sortie."""
    _OK = ("embed", "embeds", "file", "files", "view", "allowed_mentions", "tts")

    def __init__(self, channel):
        self._ch = channel

    def _clean(self, kw):
        return {k: v for k, v in kw.items() if k in self._OK}

    async def send(self, content=None, **kw):
        return await self._ch.send(content=content, **self._clean(kw))

    async def send_message(self, content=None, **kw):
        return await self._ch.send(content=content, **self._clean(kw))

    async def defer(self, *a, **k):
        return None

    def is_done(self):
        return True


class _ChannelProxy:
    """Faux 'interaction' qui route les sends d'une commande vers `channel`."""
    def __init__(self, real_interaction, channel):
        self._real = real_interaction
        self.channel = channel
        self.channel_id = channel.id
        self.user = real_interaction.user
        self.guild = getattr(real_interaction, "guild", None)
        self.client = getattr(real_interaction, "client", None)
        self.response = _SendProxy(channel)
        self.followup = _SendProxy(channel)

    def __getattr__(self, name):
        return getattr(self._real, name)


class ConfirmCleanVA(discord.ui.View):
    """Confirmation avant suppression en masse des salons va- d'un serveur.
    Éphémère, à usage unique, réservée à l'auteur de la commande."""

    def __init__(self, channels, author_id):
        super().__init__(timeout=120)
        self.channels = channels
        self.author_id = author_id

    @discord.ui.button(label="Supprimer", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Réservé à la personne qui a lancé la commande.", ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"🗑️ Suppression de **{len(self.channels)}** salons `va-…` en cours…", view=None)
        deleted = failed = 0
        for ch in self.channels:
            try:
                await ch.delete(reason="cleanva (purge des salons va-)")
                deleted += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.7)  # rate-limit friendly
        try:
            await interaction.edit_original_response(
                content=f"✅ Terminé : **{deleted}** salon(s) `va-` supprimé(s)"
                + (f" · ⚠️ {failed} échec(s) (permissions ?)." if failed else "."))
        except Exception:
            pass

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Réservé à la personne qui a lancé la commande.", ephemeral=True)
            return
        await interaction.response.edit_message(content="❌ Annulé — rien n'a été supprimé.", view=None)


class UserCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _va_channel(self, user_id):
        """Salon va- d'un VA depuis users.json (None si pas configuré)."""
        users = load_json(USERS_FILE, {})
        data = users.get(str(user_id))
        ch_id = data.get("channel_id") if isinstance(data, dict) else None
        return self.bot.get_channel(ch_id) if ch_id else None

    async def _gate_contenu(self, interaction, threads_ok=False) -> bool:
        """True si la commande de contenu est désactivée sur ce serveur (et a déjà
        répondu en éphémère). Bloque si 'contenu' est off, OU si le serveur est en
        mode Threads et que la commande n'en fait pas partie (threads_ok=False)."""
        blocked = False
        msg = "⚠️ Cette fonction est désactivée sur ce serveur."
        # IDENTITE EN PAUSE (identite_pause) : plus rien n'est servi pour
        # elle, ni au VA qui l'a, ni via Jailbreak ou le ✨ General (la
        # reserve ET la model cliquee). Un seul point de passage pour toutes
        # les commandes de contenu. Repli OUVERT et journalise : un module
        # qui ne repond pas ne coupe pas le contenu de tout le monde.
        try:
            import identite_pause as _ip
            for _cand in (_MODEL_REELLE.get(), get_user_identity(interaction.user.id)):
                if _cand and _ip.en_pause(_cand):
                    blocked, msg = True, _ip.refus(_cand)
                    break
        except Exception as e:
            log.warning("controle « pause » indisponible (%s: %s)", type(e).__name__, e)
        if blocked:
            pass
        elif not _menu_feature_check(interaction, "contenu"):
            blocked = True
        else:
            try:
                import guild_features as gf
                if gf.threads_mode(getattr(interaction, "guild", None)) and not threads_ok:
                    blocked = True
                    msg = "⚠️ Pas dispo en mode Threads (garde PP / Name / Pseudo)."
            except Exception:
                pass
        if not blocked:
            return False
        try:
            resp = getattr(interaction, "response", None)
            if resp is not None and hasattr(resp, "is_done") and resp.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
        return True

    async def _central_run(self, interaction, cmd):
        """Bouton du menu CENTRAL : exécute la commande mais la sortie va dans le salon du VA."""
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        target = self._va_channel(interaction.user.id)
        if not identity or target is None:
            await interaction.response.send_message(
                "⚠️ Tu n'as pas de salon perso configuré. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        # Accuse réception du clic SANS message visible : pour un composant,
        # defer(thinking=False) = DeferredMessageUpdate -> rien ne s'affiche au
        # VA, le contenu part directement dans son salon perso.
        try:
            await interaction.response.defer()
        except Exception:
            pass
        proxy = _ChannelProxy(interaction, target)
        try:
            await cmd.callback(self, proxy)
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            except Exception:
                pass

    @app_commands.command(
        name="icones",
        description="[ADMIN] Envoie sur le serveur les icones des boutons (style du site)")
    async def icones(self, interaction: discord.Interaction):
        """Televerse les icones du menu, et DIT ce qui s est passe.

        Sans cette commande, l envoi n avait lieu qu en postant le menu
        jailbreak : le panneau epingle, lui, gardait ses vieux emojis sans
        que rien ne l explique. Un echec silencieux ressemble a un bug du
        code, alors que c est souvent un serveur plein ou une permission
        manquante — deux choses que seul l admin peut regler.
        """
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "À utiliser dans un serveur.", ephemeral=True)
            return
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is None or not perms.manage_guild:
            await interaction.response.send_message(
                "🔒 Réservé aux admins du serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        attendus = dict(_ICONES_ACTIONS)
        avant = {e.name for e in guild.emojis}
        try:
            await ensure_action_emojis(guild)
        except Exception as e:
            await interaction.followup.send(f"❌ Envoi impossible : `{e}`", ephemeral=True)
            return

        apres = {e.name for e in guild.emojis}
        crees = sorted((apres - avant) & set(attendus.values()))
        presents = sorted(set(attendus.values()) & apres)
        manquants = sorted(set(attendus.values()) - apres)

        # On compte des NOMS d'emoji, pas des actions : les quatre Trash
        # partagent une icone, et « 18/24 » aurait annonce six manquantes.
        lignes = [f"**{len(presents)}/{len(set(attendus.values()))} icônes "
                  "disponibles** sur ce serveur."]
        if crees:
            lignes.append(f"➕ {len(crees)} envoyée(s) à l'instant.")
        elif presents:
            lignes.append("Elles y étaient déjà.")
        if manquants:
            # On NOMME la cause probable : « ça n a pas marché » n aide personne.
            dossier = Path(__file__).resolve().parent.parent / "emojis"
            absents = [n for n in manquants if not (dossier / f"{n}.png").exists()]
            libre = getattr(guild, "emoji_limit", 50) - len(guild.emojis)
            cause = []
            if absents:
                cause.append(f"fichier absent du serveur : {', '.join(absents[:4])}")
            if libre <= 0:
                cause.append("plus aucun emplacement d'emoji libre")
            if not perms.manage_emojis_and_stickers:
                cause.append("le bot n'a pas la permission « Gérer les emojis »")
            detail = ("\n_Cause probable : " + " ; ".join(cause) + "_") if cause else ""
            lignes.append("⚠️ Manquantes : " + ", ".join(manquants[:6]) + detail)
            lignes.append("_Les boutons concernés gardent leur emoji standard._")
        else:
            lignes.append("Repose un menu pour les voir : `/menujailbreakus`, "
                          "ou re-sélectionne une model dans le panneau épinglé.")
        await interaction.followup.send("\n".join(lignes), ephemeral=True)

    @app_commands.command(name="username", description="Génère des pseudos Instagram VRAIMENT dispo basés sur ton identité")
    async def username(self, interaction: discord.Interaction):
        if await self._gate_contenu(interaction, threads_ok=True):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        # Drapeau 🇺🇸 posé sur le site -> les pseudos partent de Jessye. Ici et
        # pas dans le bouton : /username, le menu VA et les deux panneaux
        # Jailbreak passent tous par cette commande.
        identity = _source_pseudo_name(identity)
        # Defer car on va check ~20 URLs Instagram = quelques secondes
        await interaction.response.defer()
        try:
            available = await find_available_usernames(identity, max_check=30, want=5)
        except Exception as e:
            # Repli : on RE-GENERE avec les regles actuelles au lieu de servir le
            # vieux fichier usernames.txt (lot fige, jamais reverifie). On previent
            # clairement que la dispo n'a PAS pu etre controlee.
            props = generate_username_candidates(identity, count=5)
            if not props:
                props = [u for u in [random_username_for(identity)] if u]
            txt = "\n".join(f"`{u}`" for u in props) or "_(rien à proposer)_"
            await interaction.followup.send(
                f"⚠️ Instagram n'a pas répondu ({e}) — **dispo NON vérifiée**, "
                f"teste-les à la création :\n{txt}"
            )
            return
        if not available:
            # Tous pris : on propose quand meme des pseudos du MEME style (non
            # verifies) plutot que de renvoyer l'utilisateur vers une liste figee.
            props = [u for u in generate_username_candidates(identity, count=8)][:3]
            extra = random_username_for(identity)
            if extra and extra not in props:
                props.append(extra)
            txt = "\n".join(f"`{u}`" for u in props)
            await interaction.followup.send(
                f"😬 Les pseudos testés pour `{identity}` sont tous pris. "
                + (f"À tenter (dispo non vérifiée) :\n{txt}" if props
                   else "Demande à un admin (`/addusernames`).")
            )
            return
        # Affichage des dispo
        lines = [
            f"✅ **{len(available)} pseudo(s) dispo sur Instagram** pour `{identity}` :",
            "",
        ]
        for u in available:
            lines.append(f"• `{u}`")
        lines.append("")
        lines.append("👉 Copie celui que tu veux et inscris-le sur Instagram.")
        lines.append("⚠️ Les pseudos sont checkés en temps réel — ils peuvent être pris à tout moment, prends rapidement.")
        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="name", description="Donne 5 noms (display Instagram) variés avec nom de famille")
    async def name(self, interaction: discord.Interaction):
        if await self._gate_contenu(interaction, threads_ok=True):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True
            )
            return
        # Drapeau 🇺🇸 posé sur le site -> les noms partent de Jessye. Voir
        # _source_pseudo_name : la règle est écrite une seule fois.
        identity = _source_pseudo_name(identity)
        # Genere 5 noms varies via le generateur
        names = generate_display_names(identity, count=5)
        if not names:
            # Fallback ancien systeme
            n = random_name_for(identity)
            if n:
                await interaction.response.send_message(n)
            else:
                await interaction.response.send_message(
                    f"Aucun nom pour ton identité `{identity}`.", ephemeral=True,
                )
            return
        lines = [f"✨ **5 noms pour `{identity}` :**", ""]
        for n in names:
            lines.append(f"• `{n}`")
        lines.append("")
        lines.append("👉 Copie celui qui te plait pour le display name Instagram.")
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="insta", description="Enregistre tes 3 comptes Instagram (handles séparés par espace)")
    @app_commands.describe(
        handle1="@handle du 1er compte Insta",
        handle2="@handle du 2e compte Insta (optionnel)",
        handle3="@handle du 3e compte Insta (optionnel)",
    )
    async def insta(
        self,
        interaction: discord.Interaction,
        handle1: str,
        handle2: str = "",
        handle3: str = "",
    ):
        if await self._gate_contenu(interaction):
            return
        import re as _re_ig, json as _json_ig
        uid = str(interaction.user.id)

        def _norm(raw):
            if not raw:
                return ""
            h = raw.strip().lstrip("@").strip()
            h = _re_ig.sub(r"[^a-zA-Z0-9_.]", "", h).lower()
            return h if (h and len(h) <= 30) else ""

        handles = []
        seen = set()
        for raw in (handle1, handle2, handle3):
            n = _norm(raw)
            if n and n not in seen:
                seen.add(n)
                handles.append(n)
        if not handles:
            await interaction.response.send_message(
                "❌ Aucun handle valide. Format attendu : `@username` (lettres/chiffres/_./).",
                ephemeral=True,
            )
            return

        VA_INSTA_FILE_C = DATA_DIR / "va_insta_accounts.json"
        existing = safe_json.load(VA_INSTA_FILE_C, {}) or {}
        if not isinstance(existing, dict):
            existing = {}
        # Le SITE ecrit ce fichier au format riche
        # ({handle, email, password, totp_seed}). Ecrire ici une simple liste de
        # chaines effacait le mot de passe et le TOTP saisis sur le site pour ce
        # VA : on repart donc des entrees existantes, appariees par handle.
        anciens = {}
        for it in (existing.get(uid) or []):
            if isinstance(it, dict):
                h = str(it.get("handle") or "").strip().lower()
                if h:
                    anciens[h] = it
            elif isinstance(it, str) and it.strip():
                anciens[it.strip().lower()] = None
        nouveaux = []
        for h in handles:
            vieux = anciens.get(h)
            if isinstance(vieux, dict):
                entree = dict(vieux)
                entree["handle"] = h
            else:
                entree = {"handle": h, "email": "", "password": "", "totp_seed": ""}
            nouveaux.append(entree)
        existing[uid] = nouveaux
        # Ecriture ATOMIQUE : write_text tronquait le fichier avant de le
        # remplir, une coupure emportait les comptes de TOUS les VAs.
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not safe_json.write_text(
                VA_INSTA_FILE_C,
                _json_ig.dumps(existing, indent=2, ensure_ascii=False)):
            await interaction.response.send_message(
                "❌ Erreur de sauvegarde — tes comptes n'ont PAS été enregistrés. "
                "Préviens un admin.", ephemeral=True)
            return

        lines = [f"• @{h}" for h in handles]
        await interaction.response.send_message(
            "✅ Comptes Instagram enregistrés :\n" + "\n".join(lines),
            ephemeral=True,
        )

    @app_commands.command(name="bio", description="Donne des bios Instagram de ton identité")
    @app_commands.describe(nombre="Combien de bios (1-10, défaut 3)")
    async def bio(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        bios, seen = [], set()
        for _ in range(nombre * 5):
            if len(bios) >= nombre:
                break
            b = random_bio_for(identity)
            if not b:
                break
            if b in seen:
                continue
            seen.add(b)
            bios.append(b)
        if not bios:
            await interaction.response.send_message(
                f"Aucune bio pour ton identité `{identity}`. Demande à un admin (`/addbios`).",
                ephemeral=True,
            )
            return
        if len(bios) == 1:
            await interaction.response.send_message(bios[0])
        else:
            msg = "💬 **Bios pour ton identité** (mets-en une différente par compte) :\n\n" + "\n\n".join(
                f"**Compte {i}.** {b}" for i, b in enumerate(bios, 1)
            )
            await interaction.response.send_message(msg[:2000])

    @app_commands.command(name="profilepic", description="Donne des photos de profil (transformées)")
    @app_commands.describe(nombre="Combien de photos (1-10, défaut 3)")
    async def profilepic(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        if await self._gate_contenu(interaction, threads_ok=True):
            return
        identity = get_user_identity(interaction.user.id)  # PP propres si dispo, sinon pool partagé
        pics, seen = [], set()
        for _ in range(nombre * 5):
            if len(pics) >= nombre:
                break
            p = random_profile_pic(identity)
            if not p:
                break
            if str(p) in seen:
                continue
            seen.add(str(p))
            pics.append(p)
        if not pics:
            await interaction.response.send_message(
                "Aucune photo de profil disponible. Demande à un admin (`/addprofilepic`).",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        cfg = load_image_config()
        n = len(pics)
        for i, pic in enumerate(pics, 1):
            tmp_dir = None
            send_path = pic
            try:
                if cfg.get("enabled", True):
                    tmp_dir = tempfile.mkdtemp(prefix="pp_")
                    tmp_path = Path(tmp_dir) / pic.name
                    if await asyncio.to_thread(transform_image, pic, tmp_path, cfg, "profile"):
                        send_path = tmp_path
                head = (
                    f"📸 **Photo de profil {i}/{n}** → une différente sur ton **compte n°{i}**"
                    if n > 1
                    else "📸 **Photo de profil**"
                )
                try:
                    await interaction.followup.send(
                        f"{head}\n*Télécharge et upload sur Instagram.*",
                        file=discord.File(send_path),
                    )
                except FileNotFoundError:
                    # rangee entre le tirage et l'envoi (doublons_vault)
                    await interaction.followup.send(f"⚠️ Photo de profil {i}/{n} : introuvable (déplacée entre-temps), passe à la suivante.")
                    continue
            finally:
                if tmp_dir:
                    try:
                        import shutil
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

    async def _send_image_content(self, interaction, kind_label, kind_target, random_fn, transform_cfg, count=3):
        """Generic handler pour /post et /story. Envoie `count` items DISTINCTS."""
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        # Recupere jusqu'a `count` images distinctes (best-effort)
        picks, seen = [], set()
        for _ in range(count * 5):
            if len(picks) >= count:
                break
            image, caption, description, example = random_fn(identity)
            if not image:
                break
            key = str(image)
            if key in seen:
                continue
            seen.add(key)
            picks.append((image, caption, description, example))
        if not picks:
            await interaction.response.send_message(
                f"Aucun {kind_label} pour ton identité `{identity}`. Demande à un admin.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        n = len(picks)
        for i, (image, caption, description, example) in enumerate(picks, 1):
            tmp_dir = None
            send_path = image
            try:
                if transform_cfg.get("enabled", True):
                    tmp_dir = tempfile.mkdtemp(prefix=f"{kind_target}_")
                    tmp_path = Path(tmp_dir) / image.name
                    if await asyncio.to_thread(transform_image, image, tmp_path, transform_cfg, kind_target):
                        send_path = tmp_path
                num = f" {i}/{n}" if n > 1 else ""
                if n > 1:
                    intro = (
                        f"🖼️ **{kind_label.upper()} {i}/{n}** → à poster sur ton **compte n°{i}** (`{identity}`)\n"
                        f"📥 Télécharge la photo CLEAN."
                    )
                else:
                    intro = f"🖼️ **{kind_label.upper()} — identité `{identity}`**\n📥 Télécharge la photo CLEAN."
                if example:
                    intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE — NE PAS la télécharger."
                try:
                    files = [discord.File(send_path, filename=image.name)]
                    if example:
                        files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
                except FileNotFoundError:
                    # rangee entre le tirage et l'envoi (doublons_vault)
                    await interaction.followup.send(f"⚠️ {kind_label.upper()}{num} : introuvable (déplacée entre-temps), passe à la suivante.")
                    continue
                try:
                    await interaction.followup.send(content=intro, files=files)
                except discord.HTTPException as e:
                    await interaction.followup.send(f"Erreur d'envoi : {e}", ephemeral=True)
                    continue
                if caption:
                    await interaction.followup.send(
                        f"📝 **CAPTION {kind_label.upper()}{num}** (à écrire **PAR-DESSUS la photo**) :"
                    )
                    await _envoyer_texte(interaction, caption)
                if description:
                    await interaction.followup.send(
                        f"📄 **DESCRIPTION {kind_label.upper()}{num}** (à coller dans le **champ légende**) :"
                    )
                    await _envoyer_texte(interaction, description)
            finally:
                if tmp_dir:
                    try:
                        import shutil
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

    @app_commands.command(name="post", description="Génère 3 posts photo (photo + caption + description)")
    @app_commands.describe(nombre="Combien de posts (1-10, défaut 3)")
    async def post(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        cfg = load_image_config()
        await self._send_image_content(interaction, "post", "post", random_post_for, cfg, count=nombre)

    @app_commands.command(name="story", description="Génère 3 stories (photo + caption + description)")
    @app_commands.describe(nombre="Combien de stories (1-10, défaut 3)")
    async def story(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        cfg = load_image_config()
        await self._send_image_content(interaction, "story", "story", random_story_for, cfg, count=nombre)

    @app_commands.command(name="storycta", description="Génère des stories CTA: photo 1080x1920 + caption à écrire dessus")
    @app_commands.describe(nombre="Combien de stories CTA (1-10, défaut 3)")
    async def storycta(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True
            )
            return
        images, seen = [], set()
        for _ in range(nombre * 5):
            if len(images) >= nombre:
                break
            im = random_story_cta_image_for(identity)
            if not im:
                break
            if str(im) in seen:
                continue
            seen.add(str(im))
            images.append(im)
        if not images:
            await interaction.response.send_message(
                f"Aucune story CTA pour ton identité `{identity}`. Demande à un admin (`/addstorycta`).",
                ephemeral=True,
            )
            return
        if not random_story_cta_caption():
            await interaction.response.send_message(
                "Aucune caption disponible. Demande à un admin (`/addstoryctacaptions`).",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        cfg = load_image_config()
        n = len(images)
        for i, image in enumerate(images, 1):
            caption = random_story_cta_caption() or ""
            tmp_dir = None
            send_path = image
            try:
                if cfg.get("enabled", True):
                    tmp_dir = tempfile.mkdtemp(prefix="storycta_")
                    tmp_path = Path(tmp_dir) / image.name
                    if await asyncio.to_thread(transform_image, image, tmp_path, cfg, "storycta"):
                        send_path = tmp_path
                head = (
                    f"📲 **STORY CTA {i}/{n}** → pour ton **compte n°{i}** (`{identity}`)"
                    if n > 1
                    else f"📲 **STORY CTA — identité `{identity}`**"
                )
                intro = (
                    f"{head}\n"
                    f"📥 Télécharge la photo, écris la caption dessus en story.\n\n"
                    f"🕖 **À POSTER LE SOIR ENTRE 19H ET 23H** — c'est le créneau "
                    f"où tes clics convertissent le mieux 💰"
                )
                try:
                    await interaction.followup.send(content=intro, file=discord.File(send_path))
                except FileNotFoundError:
                    await interaction.followup.send(f"⚠️ STORY CTA {i}/{n} : introuvable (déplacée entre-temps), passe à la suivante.")
                    continue
                except discord.HTTPException as e:
                    await interaction.followup.send(f"Erreur d'envoi : {e}", ephemeral=True)
                    continue
                if caption:
                    await _envoyer_texte(interaction, caption)
            finally:
                if tmp_dir:
                    try:
                        import shutil
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

    async def _deliver_reels_loop(self, interaction, reels, identity, label="REEL", delete_after=False):
        """Envoie chaque reel [(video, caption, desc, example)] : video (+exemple) avec
        fallback fichier trop lourd, puis CAPTION et DESCRIPTION. `label` = REEL/BANGER.
        `delete_after` supprime la source (JAMAIS pour les bangers). Interaction deja defer()."""
        total = len(reels)
        for idx, (video, caption, description, example) in enumerate(reels, start=1):
            intro = (
                f"🎬 **{label} {idx}/{total}** → à poster sur ton **compte n°{idx}** (`{identity}`)\n"
                f"📥 Télécharge la vidéo CLEAN."
            )
            if example:
                intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE — NE PAS la télécharger."
            video_to_send = video
            try:
                files = [discord.File(video_to_send, filename=video.name)]
                if example:
                    files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
            except FileNotFoundError:
                # Rangee entre le tirage et l'envoi (doublons_vault range les
                # copies exactes) : on le dit et on passe a la suivante, au
                # lieu d'arreter tout le lot.
                await interaction.followup.send(
                    f"⚠️ {label} {idx}: vidéo introuvable (déplacée entre-temps), passe à la suivante.")
                continue
            try:
                await interaction.followup.send(content=intro, files=files)
            except discord.HTTPException as e:
                if example and len(files) == 2:
                    try:
                        await interaction.followup.send(
                            content=intro + "\n\n⚠️ *(Vidéo exemple omise car trop lourde)*",
                            file=discord.File(video_to_send, filename=video.name),
                        )
                    except (discord.HTTPException, FileNotFoundError):
                        await interaction.followup.send(
                            f"⚠️ {label} {idx}: impossible d'envoyer (trop lourd): {e}")
                        continue
                else:
                    await interaction.followup.send(
                        f"⚠️ {label} {idx}: impossible d'envoyer (trop lourd): {e}")
                    continue
            if caption:
                await interaction.followup.send(
                    f"📝 **CAPTION {label} {idx}** (à mettre **PAR-DESSUS la vidéo** dans l'éditeur Insta) :")
                await _envoyer_texte(interaction, caption)
            if description:
                await interaction.followup.send(
                    f"📄 **DESCRIPTION {label} {idx}** (à coller dans le **champ légende** du post) :")
                await _envoyer_texte(interaction, description)
            if delete_after:
                try:
                    video.unlink(missing_ok=True)
                    video.with_suffix(".txt").unlink(missing_ok=True)
                    video.with_suffix(".desc.txt").unlink(missing_ok=True)
                    if example:
                        example.unlink(missing_ok=True)
                except Exception:
                    pass

    async def _gen_and_send_montaged(self, interaction, video, draft, description, idx,
                                     total, identity, label="REEL MONTÉ", emoji="🎞️",
                                     prefixe_fichier="reel_monte", brutes_dir=None,
                                     famille="", suivi=None):
        """Génère À LA DEMANDE une variante MONTÉE (texte incrusté) du reel `video` via le
        pipeline Noctus (draft = son .montage.json), puis l'envoie à poster telle quelle +
        la description. Chaque appel = une variante UNIQUE (uniquification iPhone). Lent
        (~15-30s) -> interaction déjà defer()."""
        import asyncio
        import noctus_web

        # LA RESERVE D'ABORD, comme pour les captions. Une variante deja
        # fabriquee pour cette recette exacte part tout de suite.
        #
        # La brute n'entre dans l'empreinte que si elle est IMPOSEE (brutes_dir
        # ne contenant qu'elle). Quand le moteur tire au hasard, la recette est
        # « ce template avec n'importe quelle brute » : toute variante deja
        # produite pour ce template convient.
        fichier, de_la_reserve = None, None
        # Pose AVANT la reserve : une video sortie du stock apporte son propre
        # verdict, et il doit survivre a la suite. Le poser plus bas
        # l'ecraserait juste apres l'avoir rempli.
        _rapport = {}
        # LA RESERVE EST AU PARC, PAS AUX VA. Voir POUR_LES_VA dans
        # noctus_reserve.py : un VA qui trouve la case vide genere et
        # obtient sa video ; le parc, lui, n'a aucun repli. Partager le
        # stock penalisait le seul des deux qui ne peut pas s'en passer.
        if famille and _reserve_ouverte_aux_va():
            try:
                import noctus_reserve as _res
                _imposees = ()
                if brutes_dir:
                    _lst = [x for x in Path(brutes_dir).iterdir() if x.is_file()]
                    if len(_lst) == 1:
                        _imposees = (str(_lst[0]),)
                emp = _res.empreinte(identity, famille, video,
                                     brutes=_imposees, draft=draft)
                _fiche = {}
                pris, _d = _res.prendre(
                    identity, famille, emp,
                    demandeur=str(getattr(interaction.user, "id", "")),
                    fiche_out=_fiche)
                if pris is not None:
                    fichier, de_la_reserve = pris, pris
                    # Le remplisseur fabrique des templates NUS pour
                    # reelmonte / flash / flash_banger (brutes_dir=None) : sans
                    # cette reprise, le stock rendait muet l'avertissement.
                    _rec = _fiche.get("recette") or {}
                    if _rec.get("repli"):
                        _rapport = {"repli": True,
                                    "message": str(_rec.get("message") or "")}
            except Exception:
                fichier = None                # reserve illisible : on genere

        try:
            if fichier is not None:
                raise _DejaPret                # saute la generation
            # brutes_dir : si le brouillon a un point de coupe et que l'identité a
            # des vidéos brutes, le début du template est remplacé par l'une d'elles.
            # brutes_dir impose : le bouton « Template + Brut » passe un dossier
            # ne contenant QUE la brute etoilee choisie. Sans ca, le moteur en
            # tire une au hasard parmi toutes celles de l'identite et l'etoile
            # de la brute ne servirait a rien.
            # Hors brutes_dir impose, _dossier_brutes : la model reelle
            # pendant un clic ✨ General (le template vient de la reserve).
            _brutes = (Path(brutes_dir) if brutes_dir else
                       _dossier_brutes(identity))
            model = await asyncio.to_thread(
                noctus_web.gen_from_draft, str(video), draft, ["V1"], None, _brutes,
                _rapport)
        except _DejaPret:
            model = "reserve"
        except Exception:
            model = None
        if not model:
            await interaction.followup.send(f"⚠️ {label} {idx}/{total} : génération impossible.")
            # La barre avance QUAND MEME : plantee a 33 % alors que la commande
            # est finie, elle laisse croire que ca travaille encore.
            if suivi is not None:
                await suivi.un_de_plus()
            return
        # SERVI PAR LE STOCK : il n y a AUCUN rendu a suivre, la boucle
        # d attente ci-dessous ne tourne pas une seule fois. Sans ce mot, la
        # barre semblait figee alors que tout allait bien -- et c est
        # precisement ce que le proprietaire regarde.
        if suivi is not None and fichier is not None:
            await suivi.poser(suivi.part_courante(100), "servi depuis la réserve",
                              force=True)
        state = "done" if fichier is not None else "running"
        for _ in range(0 if fichier is not None else 90):   # ~3 min max
            await asyncio.sleep(2)
            try:
                _st = noctus_web.status(model)
                state = _st.get("state", "running")
            except Exception:
                _st, state = {}, "running"
            # LA BARRE AVANCE SUR LE CHIFFRE DU MOTEUR, pas sur l'horloge. Le
            # pipeline ecrit deja son « pct » (et son « eta ») dans son fichier
            # d'etat : une barre calquee sur le temps ecoule continuerait de
            # grimper pendant un rendu bloque -- justement le moment ou on la
            # regarde. On l'edite au plus une fois toutes les quelques
            # secondes, sinon Discord fait taire le bot.
            if suivi is not None and state == "running":
                _eta = _st.get("eta")
                _det = "rendu en cours"
                try:
                    if _eta:
                        _det += f" · ~{int(float(_eta))} s"
                except Exception:
                    pass
                await suivi.poser(suivi.part_courante(_st.get("pct")), _det)
            if state in ("done", "error", "stopped"):
                break
        if state != "done":
            err = ""
            try:
                err = str(noctus_web.status(model).get("error", ""))[:180]
            except Exception:
                pass
            await interaction.followup.send(
                f"⚠️ {label} {idx}/{total} : génération échouée ({state}) {err}".strip())
            if suivi is not None:
                await suivi.un_de_plus()
            return
        if fichier is None:
            outs = noctus_web.output_paths(model)
            if not outs:
                await interaction.followup.send(f"⚠️ {label} {idx}/{total} : aucun fichier produit.")
                if suivi is not None:
                    await suivi.un_de_plus()
                return
            fichier = outs[0]
        out = fichier
        # LE REPLI SE DIT. Une variante livree sans brute, c'est le template
        # ENTIER : l'accroche appartient a une AUTRE creatrice, et « poste-la
        # telle quelle » serait alors un mauvais conseil. Le moteur le sait
        # depuis toujours et l'ecrit dans son rapport ; c'est la premiere fois
        # qu'on l'ecoute.
        _tete = (f"{emoji} **{label} {idx}/{total}** → à poster sur ton "
                 f"**compte n°{idx}** (`{identity}`)")
        if _rapport.get("repli"):
            intro = (
                _tete + "\n"
                "⚠️ **NE POSTE PAS cette vidéo telle quelle.** Le montage n'a pas pu se faire : "
                + (_rapport.get("message") or "aucune vidéo brute utilisable") + ".\n"
                "Ce n'est pas la vidéo de la model — signale-le avant de publier."
            )
        else:
            intro = (
                _tete + "\n"
                "📥 Poste cette vidéo **telle quelle** — le texte est **déjà incrusté** dessus."
            )
        try:
            await interaction.followup.send(
                content=intro, file=discord.File(str(out), filename=f"{prefixe_fichier}_{idx}.mp4"))
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"⚠️ {label} {idx}/{total} : envoi impossible (trop lourd) : {e}")
            if suivi is not None:
                await suivi.un_de_plus()
            return
        finally:
            # Sortie de la reserve = effacee, quoi qu il arrive. Elle n y
            # retourne jamais : un echec d envoi ne prouve pas que Discord n a
            # rien recu, et la re-servir serait le doublon qu on interdit.
            if de_la_reserve is not None:
                try:
                    import noctus_reserve as _res2
                    _res2.solder(de_la_reserve)
                except Exception:
                    pass
        if suivi is not None:
            await suivi.un_de_plus()
        # Pas de legende derriere un « ne poste pas ». Le message precedent
        # vient d'interdire la publication ; enchainer sur « a coller dans le
        # champ legende » decrit la marche a suivre de ce qu'on interdit, et
        # c'est la consigne la plus recente qui est suivie.
        if description and not _rapport.get("repli"):
            await interaction.followup.send(
                f"📄 **DESCRIPTION {label} {idx}/{total}** (à coller dans le **champ légende**) :")
            await _envoyer_texte(interaction, description)
        elif desc_retenue(video) and not _rapport.get("repli"):
            # RETENUE, PAS PERDUE. Se taire ferait croire que ce montage n a
            # pas de legende ; le VA en inventerait une. On dit qu elle
            # existe, pourquoi elle ne part pas, et qui peut la debloquer.
            await interaction.followup.send(
                f"ℹ️ _Pas de description pour ce {label.lower()} : "
                "celle du template est la **légende du post d'origine** et "
                "porte le **@ d'un autre compte**. Un admin la relit sur le "
                "site (**À relire**) et elle repartira._")

    async def _send_banger_reels(self, interaction):
        """Bouton '💥 Reels Banger' : envoie au VA ses reels marques ⭐ banger (dans la
        Bibliotheque) pour SON identite. Ne supprime JAMAIS la source."""
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return
        reels = banger_reels_for(identity)
        if not reels:
            await interaction.response.send_message(
                "💥 Aucun **reel banger** pour ton identité pour l'instant.\n"
                "_(Les meilleurs reels sont marqués avec l'étoile ⭐ dans la Bibliothèque.)_",
                ephemeral=True)
            return
        await interaction.response.defer()
        total = len(reels)
        await interaction.followup.send(
            f"💥 **{total} REEL(S) BANGER pour `{identity}`** — tes meilleurs, à reposter ! 🔥\n\n"
            f"🚨 **1 reel différent par compte.**\n"
            f"📝 **CAPTION** = par-dessus la vidéo · **DESCRIPTION** = dans la légende du post.")
        await self._deliver_reels_loop(interaction, reels, identity, label="BANGER", delete_after=False)

    @staticmethod
    def _note_plafond(demande, total, quoi):
        """La phrase a ajouter quand le stock a rogne la quantite demandee.

        Sans elle, demander sept et recevoir trois est indistinguable d'un
        selecteur casse -- c'est exactement la plainte qui a mene ici. Le
        plafond, lui, doit rester : au-dela des combinaisons reelles,
        _pick_fresh recycle et le VA republie deux fois la meme video.
        """
        if not demande or total >= demande:
            return ""
        return (f"\n\u26a0\ufe0f Tu en as demande **{demande}**, il en part "
                f"**{total}** : c'est tout ce que permet le stock ({quoi}). "
                f"Au-dela, la meme video repartirait deux fois.")

    async def _send_caption_bangers(self, interaction, nombre=3):
        """Bouton '⭐ Caption Banger' : les captions marquees favorites sur le site.

        Il rendait le TEXTE des captions, a copier-coller. Le VA devait alors
        rouvrir l'editeur Instagram et le recopier a la main, alors que tous
        les autres boutons lui livrent la video prete.

        Sa place parmi ses voisins tient au stock qu'il exige :

            Reel caption   brute quelconque + caption quelconque
            Caption (*)    brute quelconque + caption ETOILEE
            Montage (*)    brute ETOILEE    + caption ETOILEE

        D'ou son interet propre : il marche encore quand AUCUNE brute n'est
        etoilee, cas ou « Montage » ne rend rien.
        """
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return
        caps = fav_captions_for(identity)
        if not caps:
            # Distinguer « aucune favorite » de « toutes hors tirage ». Sans ca,
            # un admin qui a bien etoile ses captions chercherait au mauvais
            # endroit pendant une heure.
            hors = fav_captions_desactivees(identity)
            if hors:
                await interaction.response.send_message(
                    f"⭐ Tes **{len(hors)} caption(s) favorite(s)** pour `{identity}` "
                    f"sont **désactivées** (hors tirage).\n"
                    "_(Un admin les réactive sur le site, onglet **Caption**, bouton ⊘.)_",
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"⭐ Aucune **caption favorite** pour `{identity}`.\n"
                    "_(Un admin les marque avec l'étoile ⭐ sur le site, onglet **Caption**.)_",
                    ephemeral=True)
            return
        await interaction.response.defer()
        # Une favorite au texte VIDE etait sautee dans la boucle : le VA lisait
        # « 5 CAPTIONS » et n'en recevait que 4, sans un mot. On les ecarte
        # AVANT de compter, et on dit combien.
        utiles = [c for c in caps if str(c.get("text") or "").strip()]
        vides = len(caps) - len(utiles)
        if not utiles:
            await interaction.followup.send(
                f"⭐ Tes **{vides} caption(s) favorite(s)** pour `{identity}` sont **vides** "
                "(aucun texte). _(Un admin les corrige sur le site, onglet **Caption**.)_")
            return
        # Des VIDEOS, pas une liste a copier-coller. Le texte seul obligeait le
        # VA a rouvrir l'editeur Instagram et a recopier la caption a la main,
        # alors que tous les autres boutons lui livrent la video prete.
        #
        # La brute est prise dans TOUT le stock, pas seulement les etoilees.
        # C'est ce qui distingue ce bouton de « Montage », qui exige les DEUX
        # etoiles et ne rend donc rien tant qu'aucune brute n'est marquee :
        #
        #     Reel caption   brute quelconque + caption quelconque
        #     Caption (*)    brute quelconque + caption ETOILEE     <- ici
        #     Montage (*)    brute ETOILEE    + caption ETOILEE
        import brutes_off as _off
        brutes = _off.lister(_dossier_brutes(identity),
                             extensions=VIDEO_EXTS)
        if not brutes:
            await interaction.followup.send(
                f"Aucune **vidéo brute** pour `{identity}` : tes "
                f"{len(utiles)} caption(s) étoilée(s) n'ont rien sur quoi "
                "s'incruster.\n_(Un admin en ajoute sur le site, onglet "
                "**Vidéo brut**.)_")
            return
        try:
            import noctus_web
        except Exception as e:
            await interaction.followup.send(f"⚠️ Module vidéo indisponible : {e}")
            return
        if not noctus_web.setup_ok():
            await interaction.followup.send(
                "⚠️ La génération vidéo n'est pas prête sur le serveur "
                "(Node/ffmpeg). Préviens un admin.")
            return

        block = _captions_block(identity)
        # LA QUANTITE DU PANNEAU, PAS UN 3 EN DUR : le selecteur n'avait
        # aucun effet ici, on demandait sept et on recevait trois sans un mot.
        # Le plafond par les combinaisons REELLES reste -- au-dela, _pick_fresh
        # recycle et le VA republie la meme video.
        # ET CE PLAFOND EST LE PRODUIT, PAS LE PLUS PETIT DES DEUX TAS.
        # min(len(utiles), len(brutes)) bornait a TROIS avec quatre captions
        # et trois brutes, alors que douze paires existent -- et que
        # _send_montage_bangers, qui assemble exactement de la meme facon,
        # autorisait deja le produit. Une brute reservie sous une autre
        # caption ne redonne pas la meme video : c'est le texte incruste qui
        # change. Ce qu'il faut eviter, c'est la meme PAIRE deux fois.
        total = min(nombre, len(utiles) * len(brutes))
        entete = (f"⭐ **{total} VIDÉO(S) À CAPTION BANGER pour `{identity}`** — "
                  f"tes meilleures captions, déjà incrustées.\n"
                  f"⏳ Je les génère (≈15-30s chacune). Poste **tel quel**.")
        if vides:
            entete += f"\n{vides} caption(s) favorite(s) écartée(s) : texte vide."
        entete += self._note_plafond(
            nombre, total, f"{len(utiles)} caption(s) ⭐, {len(brutes)} brute(s) ⭐")
        await interaction.followup.send(entete)

        used_b, used_c = set(), set()
        suivi = _Progression(interaction, total, "Captions incrustées",
                             mot="Caption")
        await suivi.demarrer()
        for idx in range(1, total + 1):
            cap = _pick_fresh(utiles, used_c, key=lambda c: c.get("id"))
            vid = _pick_fresh(brutes, used_b, key=lambda p: str(p))
            await self._gen_and_send_caption(
                interaction, vid, cap, block, idx, total, identity,
                label="CAPTION BANGER", emoji="⭐",
                prefixe_fichier="caption_banger", famille="caption",
                suivi=suivi)

    async def brutcaption(self, interaction, nombre=3):
        """⭐ Brut + Caption : une brute ETOILEE, une caption au hasard.

        Le symetrique de « ⭐ Caption », qui etoile le texte et tire la video au
        hasard. Ici l'etoile est sur la VIDEO -- celle qui performe -- et le
        texte vient du vivier complet. Mesure du 13/09/2026 : lillaroseconlon
        avait 17 captions actives dont 4 etoilees ; les treize autres ne
        servaient a aucun bouton.
        """
        await self._send_montage_bangers(interaction, caption_favorite=False,
                                         nombre=nombre)

    async def bruttemplate(self, interaction, nombre=3):
        """⭐ Brut + Template : une brute ETOILEE, un template au hasard."""
        await self._send_template_plus_brute(interaction, brute_favorite=True,
                                             template_favori=False, nombre=nombre)

    async def brutflash(self, interaction, nombre=3):
        """⭐ Brut + Flash : une brute ETOILEE, un flash au hasard.

        Cette combinaison etait DEJA possible dans _send_template_flash --
        exiger_banger=False avec brute_favorite=True -- mais aucun bouton ne
        l'appelait.
        """
        await self._send_template_flash(interaction, exiger_banger=False,
                                        brute_favorite=True, nombre=nombre)

    # LES QUATRE TRASH : des METHODES, jamais des commandes slash. Le bot
    # principal est a 100 commandes sur 100, et une de plus fait echouer la
    # synchronisation de TOUT l'arbre, sans un message. Le panneau US, le
    # ✨ General et le menu VA savent appeler une methode ordinaire
    # (_run_for_model). Ordre et forme calques sur les quatre Flash.
    async def templatetrash(self, interaction, nombre=3):
        """Trash : un montage Trash Trend, une brute au hasard."""
        await self._send_template_marque(interaction, "trash", nombre=nombre)

    async def templatetrashbanger(self, interaction, nombre=3):
        """⭐ Trash : un montage Trash Trend ET etoile, une brute au hasard."""
        await self._send_template_marque(interaction, "trash",
                                         exiger_banger=True, nombre=nombre)

    async def bruttrash(self, interaction, nombre=3):
        """⭐ Brut + Trash : une brute ETOILEE, un Trash au hasard."""
        await self._send_template_marque(interaction, "trash",
                                         brute_favorite=True, nombre=nombre)

    async def templatetrashbrut(self, interaction, nombre=3):
        """⭐⭐ Trash + Brut : un Trash etoile, monte avec ta brute etoilee."""
        await self._send_template_marque(interaction, "trash",
                                         exiger_banger=True,
                                         brute_favorite=True, nombre=nombre)

    async def _send_montage_bangers(self, interaction, caption_favorite=True,
                                    nombre=3):
        """Bouton '🎬 Montage Banger' : une BRUTE favorite + une CAPTION favorite.

        Meme recette que /reelcaption, restreinte aux favoris. PAS de template :
        la brute EST la source et la caption s'incruste dessus. Un template
        aurait ete un piege — dans le modele d'assemblage c'est le TEMPLATE qui
        est la source et la brute est tiree au hasard par le moteur, si bien
        qu'un template sans point de coupe produit une video ou la brute
        favorite n'apparait pas du tout, et sans un mot.
        """
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return
        brutes = fav_brutes_for(identity)
        # caption_favorite decide du VIVIER DE TEXTES, et rien d'autre :
        #   True   les captions etoilees   -> « ⭐⭐ Caption + Vidéo brut »
        #   False  toutes les captions     -> « ⭐ Brut + Caption »
        # Dans le second cas l'etoile est sur la VIDEO, pas sur le texte.
        caps = (fav_captions_for(identity) if caption_favorite else
                [c for c in (_captions_block(identity).get("items") or [])
                 if c.get("enabled", True) and str(c.get("text") or "").strip()])
        if not brutes or not caps:
            # Toujours nommer le nombre de l'AUTRE cote : c'est ca qui apprend
            # au VA — et au manager — ce qui manque reellement.
            if not brutes and not caps:
                manque = ("Il manque **les deux** : aucune vidéo brute étoilée "
                          "(onglet **Vidéo brut**) et aucune caption étoilée "
                          "(onglet **Caption**).")
            elif not brutes:
                manque = (f"Tu as **{len(caps)} caption(s) favorite(s)**, mais "
                          f"**aucune vidéo brute étoilée** (onglet **Vidéo brut**).")
            else:
                hors = fav_captions_desactivees(identity)
                extra = (f" _(Tes {len(hors)} caption(s) favorite(s) sont désactivées.)_"
                         if hors else "")
                manque = (f"Tu as **{len(brutes)} brute(s) favorite(s)**, mais "
                          f"**aucune caption étoilée** (onglet **Caption**).{extra}")
            await interaction.response.send_message(
                f"🎬 Impossible de monter pour `{identity}`.\n{manque}\n"
                "_(Un admin pose les étoiles ⭐ sur le site.)_", ephemeral=True)
            return
        try:
            import noctus_web
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ Module vidéo indisponible : {e}", ephemeral=True)
            return
        if not noctus_web.setup_ok():
            await interaction.response.send_message(
                "⚠️ La génération vidéo n'est pas prête sur le serveur (Node/ffmpeg). "
                "Préviens un admin.", ephemeral=True)
            return
        await interaction.response.defer()
        block = _captions_block(identity)
        # LA QUANTITE DU PANNEAU, PAS UN 3 EN DUR : le selecteur n'avait
        # aucun effet ici, on demandait sept et on recevait trois sans un mot.
        # Le plafond par les combinaisons REELLES reste : sans lui, 1 brute +
        # 1 caption sortiraient sept fois la meme video.
        total = min(nombre, len(brutes) * len(caps))
        await interaction.followup.send(
            f"🎬 **{total} MONTAGE(S) BANGER pour `{identity}`** — tes meilleures "
            f"brutes avec tes meilleures captions.\n"
            f"⏳ Je les génère (≈15-30s chacun). Le texte est **incrusté** : "
            f"poste **tel quel**."
            + self._note_plafond(
                nombre, total,
                f"{len(brutes)} brute(s) × {len(caps)} caption(s)"))
        used_b, used_c = set(), set()
        suivi = _Progression(interaction, total, "Montages caption + brut",
                             mot="Montage")
        await suivi.demarrer()
        for idx in range(1, total + 1):
            cap = _pick_fresh(caps, used_c, key=lambda c: c.get("id"))
            vid = _pick_fresh(brutes, used_b, key=lambda p: str(p))
            await self._gen_and_send_caption(
                interaction, vid, cap, block, idx, total, identity,
                label="MONTAGE BANGER", emoji="🎬",
                prefixe_fichier="montage_banger",
                famille=("montage" if caption_favorite else "caption_vid"),
                suivi=suivi)

    async def _send_template_plus_brute(self, interaction, brute_favorite=True,
                                        template_favori=True, nombre=3):
        """Bouton 'Template + Brut' : un template ⭐ ASSEMBLE avec une brute.

        `brute_favorite` decide du STOCK de brutes, et rien d'autre :

            True   la brute doit etre etoilee   -> « ⭐⭐ Template + Brut »
            False  n'importe quelle brute       -> « ⭐ Template »

        La seconde existe pour la meme raison que « ⭐ Caption » : elle marche
        encore quand aucune brute n'est etoilee, cas ou la premiere ne rend
        rien du tout.

        La difference avec « Montage Banger » tient en une phrase : ici le
        TEMPLATE est la source et la brute vient s'y inserer au point de coupe ;
        la-bas la brute est la source et une caption s'incruste dessus.

        La brute etoilee est imposee au moteur par un dossier temporaire ne
        contenant qu'elle. Sans ce detour, _prepare_inputs en tire une au
        hasard parmi TOUTES les brutes de l'identite, et l'etoile de la brute
        ne servirait a rien.
        """
        import shutil as _sh
        import tempfile as _tf
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return
        # template_favori decide du VIVIER DE TEMPLATES, comme brute_favorite
        # decide de celui des brutes. Les deux a False n'aurait aucun sens --
        # ce serait « n'importe quoi sur n'importe quoi » -- et aucun bouton ne
        # le propose.
        templates, sans_coupe = (fav_templates_for(identity) if template_favori
                                 else tous_templates_for(identity))
        if brute_favorite:
            brutes = fav_brutes_for(identity)
        else:
            # Tout le stock, moins les desactivees : une brute dont la caption
            # est deja incrustee ne doit pas servir de support.
            import brutes_off as _off_t
            brutes = _off_t.lister(_dossier_brutes(identity),
                                   extensions=VIDEO_EXTS)
        if not templates or not brutes:
            # Le nombre ecarte se dit TOUJOURS : un admin qui a etoile cinq
            # templates et n'en voit aucun arriver doit apprendre qu'il leur
            # manque un point de coupe, pas chercher une panne ailleurs.
            note = ""
            if sans_coupe:
                note = (f"\n⚠️ {sans_coupe} template(s) étoilé(s) ont été **écartés** : "
                        f"ils n'ont pas de **point de coupe**, donc ta brute n'y "
                        f"apparaîtrait pas. _(À définir dans l'éditeur Montage du site.)_")
            if not templates and not brutes:
                manque = ("Il manque **les deux** : aucun template étoilé "
                          "(onglet **Templates montage**) et aucune vidéo brute "
                          "étoilée (onglet **Vidéo brut**).")
            elif not templates:
                manque = (f"Tu as **{len(brutes)} brute(s) favorite(s)**, mais "
                          f"**aucun template utilisable** (onglet **Templates montage**).")
            else:
                manque = (f"Tu as **{len(templates)} template(s) utilisable(s)**, mais "
                          f"**aucune vidéo brute étoilée** (onglet **Vidéo brut**)."
                          if brute_favorite else
                          "**aucune vidéo brute** (onglet **Vidéo brut**).")
            await interaction.response.send_message(
                f"🎵 Impossible d'assembler pour `{identity}`.\n{manque}{note}\n"
                "_(Un admin pose les étoiles ⭐ sur le site.)_", ephemeral=True)
            return
        try:
            import noctus_web
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ Module vidéo indisponible : {e}", ephemeral=True)
            return
        if not noctus_web.setup_ok():
            await interaction.response.send_message(
                "⚠️ La génération vidéo n'est pas prête sur le serveur (Node/ffmpeg). "
                "Préviens un admin.", ephemeral=True)
            return
        await interaction.response.defer()
        # LA QUANTITE DU PANNEAU, PAS UN 3 EN DUR. Le selecteur n'avait
        # aucun effet sur ce bouton : on demandait sept, on recevait
        # trois, sans un mot. Le plafond par les combinaisons reelles
        # reste : au-dela, _pick_fresh recycle et on republie le meme.
        total = min(nombre, len(templates) * len(brutes))
        intro = (f"🎵 **{total} TEMPLATE pour `{identity}`** — ton template "
                 + ("étoilé, monté avec ta brute étoilée." if brute_favorite else "étoilé, monté avec une de tes brutes.") + "\n"
                 f"⏳ Je les génère (≈15-30s chacun).")
        if sans_coupe:
            intro += (f"\nℹ️ {sans_coupe} template(s) étoilé(s) écarté(s) : "
                      f"pas de point de coupe.")
        intro += self._note_plafond(
            nombre, total, f"{len(templates)} template(s) × {len(brutes)} brute(s)")
        await interaction.followup.send(intro)
        used_t, used_b = set(), set()
        suivi = _Progression(interaction, total, "Assemblage template + brut",
                             mot="Template")
        await suivi.demarrer()
        for idx in range(1, total + 1):
            tpl, draft = _pick_fresh(templates, used_t, key=lambda t: str(t[0]))
            vid = _pick_fresh(brutes, used_b, key=lambda p: str(p))
            # Un dossier par generation, supprime quoi qu'il arrive : le VPS
            # se remplirait sinon d'une copie de brute a chaque clic.
            tmp = _tf.mkdtemp(prefix="favbrute-")
            try:
                cible = Path(tmp) / vid.name
                try:
                    os.link(str(vid), str(cible))   # pas de copie : lien dur
                except Exception:
                    _sh.copy2(str(vid), str(cible))
                _cap, desc, _ex = _video_meta(tpl)
                await self._gen_and_send_montaged(
                    interaction, tpl, draft, desc, idx, total, identity,
                    label="TEMPLATE + BRUT", emoji="🎵",
                    prefixe_fichier="template_brut", brutes_dir=tmp,
                    famille=("template_vid" if not template_favori else
                             "template_brut" if brute_favorite else "template"),
                    suivi=suivi)
            finally:
                _sh.rmtree(tmp, ignore_errors=True)

    async def _send_template_flash(self, interaction, exiger_banger=False,
                                   brute_favorite=False, nombre=3):
        """Les boutons Flash. Garde son nom : le menu VA et les commandes
        /templateflash* l'appellent. Tout le travail est dans
        _send_template_marque, partage avec Trash."""
        await self._send_template_marque(interaction, "flash",
                                         exiger_banger=exiger_banger,
                                         brute_favorite=brute_favorite,
                                         nombre=nombre)

    async def _send_template_marque(self, interaction, cle, exiger_banger=False,
                                    brute_favorite=False, nombre=3):
        """Les quatre boutons d'une marque (Flash, Trash), qui ne different
        que par ce qu'ils exigent :

            Flash / Trash          template MARQUE           brute au hasard
            ⭐ Flash / ⭐ Trash    template MARQUE + ETOILE  brute au hasard
            ⭐ Brut + …            template MARQUE           brute ETOILEE
            ⭐⭐ … + Brut           template MARQUE + ETOILE  brute ETOILEE

        « brute au hasard » n est pas un pis-aller : sans brutes_dir, le moteur
        pioche lui-meme parmi toutes les brutes de l identite. C est le
        comportement voulu quand seul le TEMPLATE est trie -- imposer en plus
        une brute etoilee reduirait le stock sans rien trier de mieux.

        UNE fonction pour les deux marques, pilotee par marques_montage : une
        copie par marque aurait diverge a la premiere retouche (CLAUDE.md,
        « deux mappings valent deux comportements »).
        """
        import shutil as _sh
        import tempfile as _tf
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return

        fiche = marques_montage.marque(cle)
        logo, court = fiche["emoji"], fiche["court"]
        quoi = (f"montage {logo} **et** ⭐" if exiger_banger
                else f"montage {logo}")
        ecartes = {}
        templates, sans_coupe = marque_templates_for(
            cle, identity, exiger_banger=exiger_banger, ecartes=ecartes)
        brutes = fav_brutes_for(identity) if brute_favorite else []

        # CE QUI A ETE ECARTE SE DIT TOUJOURS, dans les deux messages : un
        # admin qui a tague cinq montages et n'en voit aucun arriver doit
        # apprendre pourquoi (point de coupe, ⊘, double marque, registre
        # illisible), pas chercher une panne ailleurs.
        notes = []
        if sans_coupe:
            notes.append(f"ℹ️ {sans_coupe} montage(s) {logo} écarté(s) : pas de "
                         "**point de coupe**, donc aucune brute n'y apparaîtrait. "
                         "_(À définir dans l'éditeur Montage du site.)_")
        if ecartes.get("desactives"):
            notes.append(f"ℹ️ {ecartes['desactives']} montage(s) {logo} écarté(s) : "
                         "mis de côté ⊘ sur le site.")
        if ecartes.get("conflits"):
            autres = " / ".join(
                marques_montage.marque(m)["emoji"] + " " + marques_montage.marque(m)["court"]
                for m in marques_montage.PRIORITE[:marques_montage.PRIORITE.index(cle)])
            notes.append(f"ℹ️ {ecartes['conflits']} montage(s) {logo} écarté(s) : "
                         f"aussi marqué(s) {autres} — c'est le bouton {autres} "
                         "qui les envoie.")
        for err in ecartes.get("erreurs") or []:
            notes.append(f"⚠️ {err} — préviens un admin.")

        if not templates or (brute_favorite and not brutes):
            if not templates:
                manque = ("Aucun " + quoi + " utilisable "
                          "(onglet **Templates montage**).")
            else:
                manque = (f"Tu as **{len(templates)} montage(s) {logo} "
                          "utilisable(s)**, mais **aucune vidéo brute étoilée** "
                          "(onglet **Vidéo brut**).")
            await interaction.response.send_message(
                f"{logo} Impossible d'assembler pour `{identity}`.\n"
                + manque + "".join("\n" + n for n in notes) + "\n"
                + f"_(Un admin pose le {logo} sur le site, page Templates montage.)_",
                ephemeral=True)
            return

        try:
            import noctus_web
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ Module vidéo indisponible : {e}", ephemeral=True)
            return
        if not noctus_web.setup_ok():
            await interaction.response.send_message(
                "⚠️ La génération vidéo n'est pas prête sur le serveur "
                "(Node/ffmpeg). Préviens un admin.", ephemeral=True)
            return

        await interaction.response.defer()
        # LA QUANTITE DU PANNEAU, PAS UN 3 EN DUR. Le selecteur n'avait
        # aucun effet sur ce bouton : on demandait sept, on recevait
        # trois, sans un mot. Le plafond par les combinaisons reelles
        # reste : au-dela, _pick_fresh recycle et on republie le meme.
        total = min(nombre, len(templates) * (len(brutes) if brute_favorite else 1))
        # Le libelle nomme ce que le VA a demande. « ⭐ Brut + Flash » se
        # disait « FLASH BANGER + BRUT », comme la double etoile, alors que
        # son template n'est pas etoile.
        haut = court.upper()
        libelle = (f"{haut} BANGER + BRUT" if exiger_banger and brute_favorite
                   else f"BRUT BANGER + {haut}" if brute_favorite
                   else f"TEMPLATE {haut} BANGER" if exiger_banger
                   else f"TEMPLATE {haut}")
        avec = " avec ta brute ⭐" if brute_favorite else ""
        intro = (f"{logo} **{total} {libelle} pour `{identity}`** — ton {quoi}, "
                 f"monté{avec}.\n⏳ Je les génère (~15-30s chacun).")
        intro += "".join("\n" + n for n in notes)
        intro += self._note_plafond(
            nombre, total,
            f"{len(templates)} montage(s) {logo}"
            + (f" × {len(brutes)} brute(s)" if brute_favorite else ""))
        await interaction.followup.send(intro)

        # La famille de reserve : la meme regle que noctus_reserve.
        # FAMILLE_PAR_ACTION (templateflashbrut -> flash_brut, brutflash ->
        # flash_vid). « ⭐ Brut + Flash » passait « flash_brut » : sans effet
        # tant que la reserve est au parc (POUR_LES_VA), faux le jour ou elle
        # rouvre aux VA. Trash n'a pas de famille de stock : la reserve ne
        # trouve rien et on genere, comme pour une case vide.
        famille = (f"{cle}_brut" if exiger_banger and brute_favorite
                   else f"{cle}_vid" if brute_favorite
                   else f"{cle}_banger" if exiger_banger
                   else cle)
        used_t, used_b = set(), set()
        suivi = _Progression(interaction, total, f"Montages {court}", mot=court)
        await suivi.demarrer()
        for idx in range(1, total + 1):
            tpl, draft = _pick_fresh(templates, used_t, key=lambda t: str(t[0]))
            _cap, desc, _ex = _video_meta(tpl)
            tmp = None
            try:
                if brute_favorite:
                    # Un dossier par generation, supprime quoi qu il arrive : le
                    # VPS se remplirait sinon d une copie de brute a chaque clic.
                    vid = _pick_fresh(brutes, used_b, key=lambda p: str(p))
                    tmp = _tf.mkdtemp(prefix=f"{cle}brute-")
                    cible = Path(tmp) / vid.name
                    try:
                        os.link(str(vid), str(cible))   # pas de copie : lien dur
                    except Exception:
                        _sh.copy2(str(vid), str(cible))
                await self._gen_and_send_montaged(
                    interaction, tpl, draft, desc, idx, total, identity,
                    label=libelle, emoji=logo,
                    prefixe_fichier=cle, brutes_dir=tmp,
                    famille=famille, suivi=suivi)
            finally:
                if tmp:
                    _sh.rmtree(tmp, ignore_errors=True)

    # Les trois entrees ⭐⭐⭐ du menu. Volontairement des METHODES et non des
    # commandes slash : le bot principal est deja a 101 commandes pour un
    # plafond de 100, et chaque commande en trop en fait disparaitre une autre
    # sans le moindre message. Le panneau sait desormais appeler l une ou
    # l autre.
    async def trends(self, interaction: discord.Interaction, count=None):
        """Le bouton ⭐⭐⭐ du menu : les videos deja finies de cette model."""
        # `count` arrivait ici et n'allait pas plus loin : le bouton demandait
        # sept trends, il en recevait trois.
        await self._send_trends(interaction, nombre=count)

    async def _send_trends(self, interaction, famille="", nombre=None):
        """Boutons ⭐⭐⭐ : les videos deja FINIES, a poster telles quelles.

        Elles viennent de l onglet « Trends » du site, pas des brutes. Rien
        n est monte ni incruste ici : le travail est deja fait, le VA n a plus
        qu a publier.

        Elles passent quand meme par brute_a_envoyer, et c est le point
        important : ce sont justement les videos que le VA poste SANS RIEN
        RETOUCHER, donc celles qui ont le plus besoin d une empreinte propre a
        chaque envoi. Trois VA qui cliquent le meme bouton ne doivent pas
        publier trois fichiers identiques.

        Le texte voisin part avec : pour une trend, c est la consigne qui
        compte — le son impose.
        """
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.",
                ephemeral=True)
            return
        videos = trends_for(identity, limit=(nombre or _TRENDS_PAR_ENVOI))
        if not videos:
            await interaction.response.send_message(
                f"⭐⭐⭐ Aucune **trend prête** pour `{identity}`.\n"
                "_(Un admin en dépose sur le site, onglet **Trends** — ce sont "
                "les vidéos finies, à poster telles quelles.)_",
                ephemeral=True)
            return
        await interaction.response.defer()
        n = len(videos)
        suffixe = f" — {famille}" if famille else ""
        entete = (f"⭐⭐⭐ **{n} TREND{'S' if n > 1 else ''} PRÊTE{'S' if n > 1 else ''} "
                  f"pour `{identity}`**{suffixe}\n"
                  f"🔥 Le travail est **déjà fait** : poste-la telle quelle, "
                  f"ne la remonte pas, ne réécris pas le texte.")
        await self._envoyer_brutes_meta(interaction, videos, identity,
                                        "TREND", entete, avec_texte=True)

    async def _send_brutes_bangers(self, interaction):
        """Bouton '🎥 Vidéo brut Banger' : les brutes ⭐, sans montage.

        Rien d'incruste, rien de genere. C'est quasi instantane, contrairement
        au Montage Banger qui fabrique une video (15-30 s piece).

        Ces brutes-la servent aussi a « Template + Brut » et « Montage Banger »,
        qui les ASSEMBLENT. Ici elles partent nues -- meme contenu, sans
        template. L image n est pas touchee ; seules les metadonnees sont
        reecrites, comme pour « Video brut ».
        """
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return
        brutes = fav_brutes_for(identity)
        if not brutes:
            await interaction.response.send_message(
                f"⭐ Aucune **vidéo brute favorite** pour `{identity}`.\n"
                "_(Un admin les marque avec l'étoile ⭐ sur le site, onglet "
                "**Vidéo brut**.)_", ephemeral=True)
            return
        await interaction.response.defer()
        entete = (f"⭐ **{len(brutes)} VIDÉO(S) BRUTE(S) BANGER pour "
                  f"`{identity}`** — les meilleures, sans texte ni montage : à "
                  f"toi de les monter. 🔥")
        await self._envoyer_brutes_meta(interaction, brutes, identity,
                                        "BRUTE BANGER", entete)

    async def _send_choix_brutes(self, interaction):
        """Bouton « 🎛️ Choisir ma brute » : il voit, puis il choisit.

        La difference avec « ⭐ Video brut » tient en un mot : celui-la en
        envoie trois au hasard, celui-ci le laisse decider. Quand une seule
        brute l interesse, les deux autres etaient du bruit.
        """
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.",
                ephemeral=True)
            return
        brutes = fav_brutes_for(identity, limit=0)
        if not brutes:
            await interaction.response.send_message(
                f"⭐ Aucune **vidéo brute favorite** pour `{identity}`.\n"
                "_(Un admin les marque avec l'étoile ⭐ sur le site, onglet "
                "**Vidéo brut**.)_", ephemeral=True)
            return

        # Le menu precedent part AVANT qu on ouvre celui-ci : deux menus
        # empiles proposent deux identites differentes, et rien ne dit lequel
        # est le bon.
        await _fermer_menu_brutes(interaction.user.id)

        # La premiere ouverture fabrique les vignettes manquantes : quelques
        # dixiemes de seconde par brute. Les suivantes les relisent.
        await interaction.response.defer(ephemeral=True)
        vue = ChoixBrutesView(self, identity, brutes)
        texte, fichier = vue._planche_et_texte()
        if fichier is not None:
            vue.message = await interaction.followup.send(
                content=texte, file=fichier, view=vue, ephemeral=True,
                wait=True)
        else:
            vue.message = await interaction.followup.send(
                content=texte, view=vue, ephemeral=True, wait=True)
        _DERNIER_MENU_BRUTES[int(interaction.user.id)] = vue.message

    async def _send_caption_plus_brute(self, interaction):
        """Bouton '📝 Caption + Brut Banger' : une brute ⭐ ET une caption ⭐,
        envoyees SEPAREMENT.

        La difference avec « Montage Banger » tient a un mot : ici la caption
        arrive en TEXTE, a coller par le VA dans l'editeur Instagram ; la-bas
        elle est incrustee dans la video par le moteur. D'ou deux couts tres
        differents — instantane ici, 15-30 s par video la-bas.
        """
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return
        brutes = fav_brutes_for(identity)
        caps = fav_captions_for(identity)
        if not brutes or not caps:
            # Nommer le nombre de l'AUTRE cote : c'est ce qui apprend au VA —
            # et au manager — ce qui manque reellement.
            if not brutes and not caps:
                manque = ("Il manque **les deux** : aucune vidéo brute étoilée "
                          "(onglet **Vidéo brut**) et aucune caption étoilée "
                          "(onglet **Caption**).")
            elif not brutes:
                manque = (f"Tu as **{len(caps)} caption(s) favorite(s)**, mais "
                          f"**aucune vidéo brute étoilée**.")
            else:
                hors = fav_captions_desactivees(identity)
                extra = (f" _(Tes {len(hors)} caption(s) favorite(s) sont "
                         f"désactivées.)_" if hors else "")
                manque = (f"Tu as **{len(brutes)} brute(s) favorite(s)**, mais "
                          f"**aucune caption étoilée**.{extra}")
            await interaction.response.send_message(
                f"📝 Impossible pour `{identity}`.\n{manque}\n"
                "_(Un admin pose les étoiles ⭐ sur le site.)_", ephemeral=True)
            return
        await interaction.response.defer()
        total = min(len(brutes), 5)
        await interaction.followup.send(
            f"📝 **{total} BRUTE(S) + CAPTION BANGER pour `{identity}`**\n"
            f"🎥 La vidéo est **nue** · 📝 la caption est à **écrire par-dessus** "
            f"dans l'éditeur Instagram.")
        used_c = set()
        for idx, v in enumerate(brutes[:total], start=1):
            cap = _pick_fresh(caps, used_c, key=lambda c: c.get("id"))
            try:
                await interaction.followup.send(
                    content=f"🎥 **BRUTE {idx}/{total}** (`{identity}`)",
                    file=discord.File(str(v), filename=v.name))
            except FileNotFoundError:
                await interaction.followup.send(f"⚠️ BRUTE {idx}/{total} : introuvable (déplacée entre-temps), passe à la suivante.")
                continue
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"⚠️ BRUTE {idx}/{total} : envoi impossible (trop lourde) : {e}")
                continue
            txt = str((cap or {}).get("text") or "").strip()
            if txt:
                await interaction.followup.send(
                    f"📝 **CAPTION {idx}/{total}** (à mettre **par-dessus la "
                    f"vidéo**) :\n```\n{txt[:1800]}\n```")
            desc = str((cap or {}).get("desc") or "").strip()
            if desc:
                await interaction.followup.send(
                    f"📄 **DESCRIPTION {idx}/{total}** (champ légende) :\n"
                    f"```\n{desc[:1800]}\n```")

    # Les deux actions existent AUSSI en commandes, pour une raison precise :
    # le panneau du serveur US ne sait declencher que des app_commands — il
    # appelle cmd.callback sur un attribut du cog (_run_for_model). Sans ces
    # deux commandes, les boutons n'auraient pu vivre que dans le menu FR.
    #
    # Le bouton, lui, marche des le redemarrage : il n'a pas besoin que Discord
    # connaisse la commande. Seule la frappe de « /captionbanger » exige une
    # resynchronisation de l'arbre.
    @app_commands.command(
        name="captionbanger",
        description="Tes meilleures captions (marquees ⭐ sur le site)")
    async def captionbanger(self, interaction: discord.Interaction,
                            nombre: app_commands.Range[int, 1, 10] = 3):
        await self._send_caption_bangers(interaction, nombre=nombre)

    @app_commands.command(
        name="montagebanger",
        description="Une video brute ⭐ + une caption ⭐, montees pour toi")
    async def montagebanger(self, interaction: discord.Interaction,
                            nombre: app_commands.Range[int, 1, 10] = 3):
        await self._send_montage_bangers(interaction, nombre=nombre)

    @app_commands.command(
        name="templatebrut",
        description="Un template ⭐ assemble avec une video brute ⭐")
    async def templatebrut(self, interaction: discord.Interaction,
                           nombre: app_commands.Range[int, 1, 10] = 3):
        await self._send_template_plus_brute(interaction, nombre=nombre)

    @app_commands.command(
        name="choisirbrute",
        description="Voir tes vidéos brutes ⭐ et choisir toi-même laquelle")
    async def choisirbrute(self, interaction: discord.Interaction):
        await self._send_choix_brutes(interaction)

    @app_commands.command(
        name="templatebanger",
        description="Un template ⭐ assemble avec une de tes brutes")
    async def templatebanger(self, interaction: discord.Interaction,
                             nombre: app_commands.Range[int, 1, 10] = 3):
        # La brute n'a pas a etre etoilee : c'est ce qui distingue ce bouton
        # de /templatebrut, et ce qui le rend utilisable quand aucune brute
        # n'est marquee.
        await self._send_template_plus_brute(interaction, brute_favorite=False,
                                             nombre=nombre)

    @app_commands.command(
        name="templateflash",
        description="Un montage Flash Trend, assemble avec une brute au hasard")
    async def templateflash(self, interaction: discord.Interaction,
                            nombre: app_commands.Range[int, 1, 10] = 3):
        await self._send_template_flash(interaction, nombre=nombre)

    @app_commands.command(
        name="templateflashbanger",
        description="Un montage Flash Trend ET etoile, avec une brute au hasard")
    async def templateflashbanger(self, interaction: discord.Interaction,
                                  nombre: app_commands.Range[int, 1, 10] = 3):
        await self._send_template_flash(interaction, exiger_banger=True,
                                        nombre=nombre)

    @app_commands.command(
        name="templateflashbrut",
        description="Un montage Flash Trend ET etoile, avec ta brute etoilee")
    async def templateflashbrut(self, interaction: discord.Interaction,
                                nombre: app_commands.Range[int, 1, 10] = 3):
        await self._send_template_flash(interaction, exiger_banger=True,
                                        brute_favorite=True, nombre=nombre)

    @app_commands.command(
        name="brutbanger",
        description="Tes meilleures videos brutes (marquees ⭐), sans montage")
    async def brutbanger(self, interaction: discord.Interaction):
        await self._send_brutes_bangers(interaction)

    @app_commands.command(
        name="captionbrut",
        description="Une brute ⭐ + sa caption ⭐ en texte, a coller toi-meme")
    async def captionbrut(self, interaction: discord.Interaction):
        await self._send_caption_plus_brute(interaction)

    @app_commands.command(name="reel", description="Genere 3 reels (par defaut) : video clean + caption + description + exemple")
    @app_commands.describe(nombre="Combien de reels envoyer (1-10, defaut 3)")
    async def reel(
        self,
        interaction: discord.Interaction,
        nombre: app_commands.Range[int, 1, 10] = 3,
    ):
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        reels = random_n_reels_for(identity, nombre)
        if not reels:
            await interaction.response.send_message(
                f"Aucune vidéo pour ton identité `{identity}`. Demande à un admin.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()

        transform_cfg = load_transform_config()
        total = len(reels)

        # Message d'intro CLAIR : 1 reel different par compte + explication caption/description
        intro_global = (
            f"🎬 **{total} reels pour `{identity}` — {total} comptes**\n\n"
            f"🚨 **RÈGLE : 1 reel différent par compte.**\n"
            f"Poste **REEL 1** sur ton **compte 1**, **REEL 2** sur le **compte 2**, "
            f"**REEL 3** sur le **compte 3**.\n"
            f"⚠️ NE POSTE JAMAIS le même reel sur 2 comptes → duplicate content = shadowban.\n\n"
            f"📝 **Pour chaque reel je vais t'envoyer 2 textes :**\n"
            f"• **CAPTION** = le texte à écrire **PAR-DESSUS la vidéo** "
            f"(dans l'éditeur Insta, outil texte, en overlay sur le reel)\n"
            f"• **DESCRIPTION** = le texte à coller dans **le champ légende** du post "
            f"(en bas, là où Instagram demande 'Écrire une légende...')"
        )
        await interaction.followup.send(intro_global)

        if total < nombre:
            await interaction.followup.send(
                f"ℹ️ Seulement **{total}** reels disponibles pour `{identity}` "
                f"(tu en as demande {nombre})."
            )

        _del = transform_cfg.get("delete_source_after_use", False)
        await self._deliver_reels_loop(interaction, reels, identity, label="REEL", delete_after=_del)

    @app_commands.command(name="reelmonte", description="Reels DÉJÀ MONTÉS (texte incrusté), générés à la demande : à poster tels quels + description")
    @app_commands.describe(nombre="Combien de reels montés (1-10, defaut 3)")
    async def reelmonte(self, interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 10] = 3):
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin de faire `/adduser` sur toi.",
                ephemeral=True,
            )
            return
        _ecartes = {}
        ready = va_ready_montages_for(identity, nombre, _ecartes)
        if not ready:
            # Deux causes, deux gestes differents. Les confondre envoyait
            # refaire un geste deja fait.
            _vides = _ecartes.get("sans_montage") or 0
            if _vides:
                _detail = (
                    f"_({_vides} reel(s) sont bien marqués « 📥 Dispo pour les VA », mais leur "
                    "montage est **vide** : ni point de coupe, ni texte. Servis tels quels, ce "
                    "serait la vidéo d'origine. Un admin doit les rouvrir dans l'éditeur Montage "
                    "et poser un texte ou une coupe.)_"
                )
            else:
                _detail = ("_(Un admin doit ouvrir un reel dans l'éditeur Montage du site "
                           "et cliquer « 📥 Dispo pour les VA ».)_")
            await interaction.response.send_message(
                f"Aucun **reel monté** dispo pour ton identité `{identity}` pour l'instant.\n"
                + _detail,
                ephemeral=True,
            )
            return
        try:
            import noctus_web
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Module vidéo indisponible : {e}", ephemeral=True)
            return
        if not noctus_web.setup_ok():
            await interaction.response.send_message(
                "⚠️ La génération vidéo n'est pas prête sur le serveur (Node/ffmpeg). Préviens un admin.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        total = len(ready)
        await interaction.followup.send(
            f"🎞️ **{total} reel(s) déjà monté(s) pour `{identity}`** — je les **génère pour toi** "
            f"(≈15-30s chacun ⏳). Chaque reel est **unique** — jamais le même sur 2 comptes.\n"
            f"✅ Texte **déjà incrusté** : poste **tel quel** + la **DESCRIPTION** en légende."
        )
        if total < nombre:
            await interaction.followup.send(
                f"ℹ️ Seulement **{total}** reel(s) monté(s) approuvé(s) pour `{identity}` "
                f"(tu en as demandé {nombre})."
            )
        # LA BARRE. Entre ce message et le premier fichier il se passe une
        # minute pendant laquelle le salon ne disait RIEN : le VA relancait la
        # commande, ce qui refabriquait tout et allongeait encore l attente.
        suivi = _Progression(interaction, total, "Génération des reels")
        await suivi.demarrer()
        for idx, (video, draft, description) in enumerate(ready, start=1):
            await self._gen_and_send_montaged(
                interaction, video, draft, description, idx, total, identity,
                famille="reelmonte", suivi=suivi)

    @app_commands.command(
        name="videobrut",
        description="Envoie des vidéos BRUTES (rushs) de ton identité, sans montage")
    @app_commands.describe(nombre="Combien de vidéos (1-10, défaut 3)")
    async def videobrut(self, interaction: discord.Interaction,
                        nombre: app_commands.Range[int, 1, 10] = 3):
        """Rushs nus du dossier « brutes » : aucun texte, aucun montage.

        L IMAGE reste celle qui a ete uploadee sur le site, au bit pres. Seules
        les metadonnees sont reecrites, a chaque envoi : modele d iPhone, iOS,
        date de prise de vue, GPS d une vraie ville. C est systematique et sans
        bouton separe -- une brute ne part jamais avec l empreinte d origine.
        """
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return
        # brutes_off.lister ecarte aussi les brutes DESACTIVEES (celles qui
        # portent deja une caption incrustee). Le filtre etait recopie ici et
        # a deux autres endroits : une seule porte d entree, desormais.
        import brutes_off as _off
        bdir = IDENTITIES_DIR / identity / "brutes"
        vids = _off.lister(bdir, extensions=VIDEO_EXTS)
        if not vids:
            await interaction.response.send_message(
                f"Aucune **vidéo brute** pour `{identity}`.\n"
                "_(Un admin en ajoute sur le site, onglet **Vidéo brut**.)_",
                ephemeral=True)
            return
        await interaction.response.defer()
        picked = random.sample(vids, min(nombre, len(vids)))
        total = len(picked)
        entete = (f"🎥 **{total} vidéo(s) brute(s) pour `{identity}`** — sans "
                  f"texte ni montage, à toi de les monter.")
        if total < nombre:
            entete += (f"\nℹ️ Seulement **{total}** vidéo(s) brute(s) dispo "
                       f"(tu en as demandé {nombre}).")
        await self._envoyer_brutes_meta(interaction, picked, identity,
                                        "VIDÉO BRUTE", entete)

    async def _envoyer_brutes_meta(self, interaction, videos, identity,
                                   label, entete, avec_texte=False):
        """Envoie des brutes dont les metadonnees ont ete reecrites.

        C EST LE SITE QUI DECIDE. Reglages > Uniquification video, le gros
        interrupteur ON/OFF. Eteint, les brutes repartent exactement comme
        avant, sans un mot de plus. Allume, chaque fichier ressort avec une
        autre identite d appareil.

        Cet interrupteur existait deja et se disait « lu par /reel ». Il n etait
        lu NULLE PART : le module d uniquification video etait entierement
        cable dans le vide. C est ici qu il sert enfin.

        L IMAGE N EST JAMAIS TOUCHEE. Remux seul, aucun re-encodage : les pixels
        sortent identiques au bit pres. Ce qui change, c est ce que Meta lit --
        modele d iPhone, version d iOS, date de prise de vue, GPS d une vraie
        ville -- donc une empreinte differente a chaque envoi.

        LE VA N EN LIT RIEN. Pas un mot sur les metadonnees dans le salon :
        le reglage vit sur le site, c est l affaire de l admin. Le VA recoit sa
        video, point -- exactement le message qu il avait avant.

        MAIS L ECHEC NE DISPARAIT PAS. Si l uniquification est demandee et que
        ffmpeg manque ou refuse, la video part quand meme et la ligne va au
        JOURNAL du serveur. Muet pour le VA, visible pour qui administre : sans
        ca, une uniquification allumee qui n uniquifie rien ne se verrait nulle
        part.

        Et on ne croit pas le booleen sur parole : le fichier de sortie doit
        exister ET peser quelque chose. Un ffmpeg qui rend 0 en laissant un
        fichier vide, c est arrive.
        """
        import tempfile as _tmp
        total = len(videos)
        await interaction.followup.send(entete)
        with _tmp.TemporaryDirectory(prefix="brutmeta_") as _d:
            for idx, v in enumerate(videos, start=1):
                fichier, _reecrit, _raison = await brute_a_envoyer(v, _d, identity)
                tete = f"🎥 **{label} {idx}/{total}** (`{identity}`)"
                # En temps normal le VA ne lit RIEN sur l uniquification : le
                # reglage vit sur le site, c est l affaire de l admin. Mais
                # quand elle est demandee et qu elle ECHOUE, il doit le savoir :
                # il poste la brute telle quelle, donc il publierait un doublon
                # sans s en douter. Se taire ici lui coute un compte.
                if _raison:
                    tete += ("\n⚠️ _Celle-ci n a **pas** pu etre rendue unique — "
                             "ne la poste pas telle quelle, previens un admin._")
                try:
                    await interaction.followup.send(
                        content=tete,
                        file=discord.File(str(fichier), filename=v.name))
                except FileNotFoundError:
                    await interaction.followup.send(f"⚠️ {label} {idx}/{total} : introuvable (déplacée entre-temps), passe à la suivante.")
                    continue
                except discord.HTTPException as e:
                    await interaction.followup.send(
                        f"⚠️ {label} {idx}/{total} : envoi impossible "
                        f"(trop lourde pour Discord) : {e}")
                    continue
                # Le texte voisin de la video, quand elle en a un. Pour une
                # TREND c est la consigne qui compte — le son a utiliser — et
                # l envoyer separement la rend copiable d un doigt sur mobile.
                if avec_texte:
                    _cap, _desc, _ = _video_meta(v)
                    if _cap:
                        await interaction.followup.send(
                            "🎵 **SON / CONSIGNE** :\n```\n"
                            + str(_cap)[:1800] + "\n```")
                    if _desc:
                        await interaction.followup.send(
                            "📄 **DESCRIPTION** (champ légende) :\n```\n"
                            + str(_desc)[:1800] + "\n```")
                    elif desc_retenue(v):
                        # RETENUE, PAS ABSENTE. Se taire ferait croire que
                        # ce fichier n a pas de legende.
                        await interaction.followup.send(
                            "ℹ️ _Pas de description ici : celle du fichier est "
                            "la **legende du post d'origine** et porte le **@ "
                            "d'un autre compte**. Un admin la relit sur le site "
                            "(**A relire**)._")

    @app_commands.command(
        name="reelcaption",
        description="Vidéo brute + caption incrustée (bibliothèque Caption du site)")
    @app_commands.describe(nombre="Combien de vidéos (1-10, défaut 3)")
    async def reelcaption(self, interaction: discord.Interaction,
                          nombre: app_commands.Range[int, 1, 10] = 3):
        """Une brute de l'identité + UNE caption au hasard, incrustée par le
        moteur montage — même recette que le bouton 🎲 du site (/captions/gen)."""
        if await self._gate_contenu(interaction):
            return
        identity = get_user_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Demande à un admin.", ephemeral=True)
            return
        block = _captions_block(identity)
        pool = [c for c in (block.get("items") or [])
                if c.get("enabled", True) and str(c.get("text") or "").strip()]
        if not pool:
            await interaction.response.send_message(
                f"Aucune **caption** active pour `{identity}`.\n"
                "_(Un admin les ajoute sur le site, onglet **Caption**.)_", ephemeral=True)
            return
        # Meme porte d entree que la commande « Video brut » : les brutes
        # desactivees ne doivent pas non plus servir de support a une caption.
        import brutes_off as _off
        bdir = _dossier_brutes(identity)
        brutes = _off.lister(bdir, extensions=VIDEO_EXTS)
        if not brutes:
            await interaction.response.send_message(
                f"Aucune **vidéo brute** pour `{identity}`.\n"
                "_(Un admin en ajoute sur le site, onglet **Vidéo brut**.)_", ephemeral=True)
            return
        try:
            import noctus_web
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ Module vidéo indisponible : {e}", ephemeral=True)
            return
        if not noctus_web.setup_ok():
            await interaction.response.send_message(
                "⚠️ La génération vidéo n'est pas prête sur le serveur (Node/ffmpeg).",
                ephemeral=True)
            return
        await interaction.response.defer()
        total = min(nombre, len(brutes) * 3)
        await interaction.followup.send(
            f"💬 **{total} reel(s) caption pour `{identity}`** — je les génère "
            f"(≈15-30s chacun ⏳). Le texte est **incrusté** : poste **tel quel**.")
        used_b, used_c = set(), set()
        suivi = _Progression(interaction, total, "Captions incrustées",
                             mot="Caption")
        await suivi.demarrer()
        for idx in range(1, total + 1):
            cap = _pick_fresh(pool, used_c, key=lambda c: c.get("id"))
            vid = _pick_fresh(brutes, used_b, key=lambda p: str(p))
            await self._gen_and_send_caption(interaction, vid, cap, block, idx,
                                             total, identity, suivi=suivi)

    async def _gen_and_send_caption(self, interaction, video, cap, block, idx, total,
                                    identity, label="REEL CAPTION", emoji="💬",
                                    prefixe_fichier="reel_caption", famille="",
                                    suivi=None):
        """Génère UNE vidéo brute + caption incrustée puis l'envoie (+ description).

        `label` sert au bouton « Montage Banger », qui emprunte exactement cette
        recette : sans lui, le VA lirait « REEL CAPTION » sur un contenu qu'on
        vient de lui annoncer comme un montage banger. Le défaut laisse
        /reelcaption strictement inchangé.
        """
        import asyncio
        import noctus_web
        draft = draft_caption(cap, block)

        # LA RESERVE D'ABORD. Une variante deja fabriquee pour cette recette
        # exacte part tout de suite, au lieu des 15 a 30 s de generation. Si
        # elle est vide, on genere comme avant : la reserve accelere, elle ne
        # conditionne rien.
        fichier, de_la_reserve = None, None
        # LA RESERVE EST AU PARC, PAS AUX VA. Voir POUR_LES_VA dans
        # noctus_reserve.py : un VA qui trouve la case vide genere et
        # obtient sa video ; le parc, lui, n'a aucun repli. Partager le
        # stock penalisait le seul des deux qui ne peut pas s'en passer.
        if famille and _reserve_ouverte_aux_va():
            try:
                import noctus_reserve as _res
                emp = _res.empreinte(identity, famille, video, caption=cap,
                                     draft=draft)
                pris, _desc = _res.prendre(
                    identity, famille, emp,
                    demandeur=str(getattr(interaction.user, "id", "")))
                if pris is not None:
                    fichier, de_la_reserve = pris, pris
            except Exception:
                fichier = None                # reserve illisible : on genere

        if fichier is None:
            try:
                model = await asyncio.to_thread(
                    noctus_web.gen_from_draft, str(video), draft, ["V1"], None, None)
            except Exception:
                model = None
            if not model:
                await interaction.followup.send(f"⚠️ {label} {idx}/{total} : génération impossible.")
                if suivi is not None:
                    await suivi.un_de_plus()
                return
            state = "running"
            for _ in range(90):                       # ~3 min max
                await asyncio.sleep(2)
                try:
                    _st = noctus_web.status(model)
                    state = _st.get("state", "running")
                except Exception:
                    _st, state = {}, "running"
                # LE CHIFFRE DU MOTEUR, pas l horloge. Sans cette lecture, une
                # barre branchee ici n avancerait que d un cran par element :
                # exactement la barre-a-l-horloge qu on refuse ailleurs.
                if suivi is not None and state == "running":
                    _eta = _st.get("eta")
                    _det = "rendu en cours"
                    try:
                        if _eta:
                            _det += f" · ~{int(float(_eta))} s"
                    except Exception:
                        pass
                    await suivi.poser(suivi.part_courante(_st.get("pct")), _det)
                if state in ("done", "error", "stopped"):
                    break
            if state != "done":
                # LE RETOUR APPARTIENT A L'ECHEC, PAS AU SUIVI.
                #
                # Il etait indente d'un cran de trop : sorti du « if state !=
                # done », il s'executait des que `suivi` existait -- c'est-a-dire
                # a CHAQUE appel des boutons par lot, reussite comprise. La
                # fonction avancait donc la barre puis sortait, juste avant
                # d'envoyer la video.
                #
                # Symptome, le 13/09/2026 a 23:55 sur montagebanger : « 3/3 —
                # termine », aucun avertissement, et aucune video nulle part.
                # Le bug dormait depuis longtemps : tant que la reserve servait
                # les VA, le fichier venait du stock, _DejaPret sautait tout ce
                # bloc, et ce retour n'etait jamais atteint. Fermer la reserve
                # aux VA l'a reveille.
                #
                # La forme correcte est celle du « aucun fichier produit » juste
                # en dessous : avertir, avancer le suivi, PUIS sortir.
                await interaction.followup.send(
                    f"⚠️ {label} {idx}/{total} : génération échouée ({state}).")
                if suivi is not None:
                    await suivi.un_de_plus()
                return
            outs = noctus_web.output_paths(model)
            if not outs:
                await interaction.followup.send(f"⚠️ {label} {idx}/{total} : aucun fichier produit.")
                if suivi is not None:
                    await suivi.un_de_plus()
                return
            fichier = outs[0]
        if suivi is not None and de_la_reserve is not None:
            await suivi.poser(suivi.part_courante(100), "servi depuis la réserve",
                              force=True)
        intro = (f"{emoji} **{label} {idx}/{total}** → à poster sur ton **compte n°{idx}** "
                 f"(`{identity}`)\n📥 Poste cette vidéo **telle quelle** — la caption est "
                 f"**déjà écrite** dessus.")
        try:
            await interaction.followup.send(
                content=intro,
                file=discord.File(str(fichier), filename=f"{prefixe_fichier}_{idx}.mp4"))
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"⚠️ {label} {idx}/{total} : envoi impossible (trop lourd) : {e}")
            if suivi is not None:
                await suivi.un_de_plus()
            return
        finally:
            # Une variante sortie de la reserve est effacee QUOI QU IL ARRIVE.
            # Elle n y retourne jamais : un echec d envoi ne prouve pas que
            # Discord n a rien recu, et la re-servir serait le doublon qu on
            # interdit. Perdre une variante coute 25 s de calcul ; un doublon
            # coute un shadowban.
            if de_la_reserve is not None:
                try:
                    import noctus_reserve as _res2
                    _res2.solder(de_la_reserve)
                except Exception:
                    pass
        if suivi is not None:
            await suivi.un_de_plus()
        desc = str(cap.get("desc") or "").strip()
        if desc:
            await interaction.followup.send(
                f"📄 **DESCRIPTION {label} {idx}/{total}** (à coller dans le **champ légende**) :")
            await _envoyer_texte(interaction, desc)

    async def cog_load(self):
        # Vues persistantes : les boutons des menus marchent meme apres un
        # redemarrage du bot.
        #
        # CHAQUE ENREGISTREMENT DANS SON PROPRE ESSAI, ET JOURNALISE. Ils
        # partageaient un seul « try ... except: pass » : une vue qui deborde
        # (un 26e composant, un 6e bouton sur une rangee) leve a la
        # construction, et TOUS les enregistrements suivants sautaient en
        # silence -- au redemarrage, le panneau US entier devenait muet sans
        # une ligne dans le journal.
        def _enregistrer(quoi, faire):
            try:
                faire()
            except Exception as e:
                log.warning("cog_load : %s non enregistre(s) (%s: %s) -- "
                            "ses boutons ne repondront pas.",
                            quoi, type(e).__name__, e)

        # Le menu VA en V2 : construit SANS reglage, il porte tous ses
        # custom_id (boutons « cmenu:<cle> », menus « cmenu:sel:<famille> »).
        _enregistrer("menu VA", lambda: self.bot.add_view(ContentMenuView(self)))
        # Ce que les menus VA deja epingles portent encore et que le V2 n'a
        # plus : les boutons retires le 25/09/2026, puis les lanceurs « ▸ »
        # (cmenu:fam:…), qui convertissent leur menu en V2 au clic. Sans ces
        # vues, ils resteraient a l'ecran sans rien faire.
        _enregistrer("anciens boutons du menu VA",
                     lambda: self.bot.add_view(ContentMenuHeritageView(self)))
        _enregistrer("anciens lanceurs du menu VA",
                     lambda: self.bot.add_view(ContentMenuLanceursView(self)))
        _enregistrer("menu central", lambda: self.bot.add_view(CentralMenuView(self)))
        # L'ancien menu Jailbreak a UN menu deroulant (« jbmenu:model »,
        # « jbmenuus:model ») : il n'est plus pose, mais les messages deja
        # postes le portent -- sans ce motif, leur menu ne repondrait plus.
        # Un clic le convertit en « menus de 10 ».
        _enregistrer("ancien menu Jailbreak (un seul menu)",
                     lambda: self.bot.add_dynamic_items(JBMenuModelsAncien))
        _enregistrer("panneau des liens", lambda: self.bot.add_view(LinkPanelView()))
        _enregistrer("bouton Generer le lien",
                     lambda: self.bot.add_dynamic_items(GenLinkButton))
        # Les boutons-photos de l'ancienne grille (« jbus:m:<ident> ») : les
        # menus deja epingles les portent jusqu'a leur conversion.
        _enregistrer("boutons des models US",
                     lambda: self.bot.add_dynamic_items(JBModelButton))
        # Le menu des models en « menus de 10 » (« jbus:ms:<marche>:<n> ») :
        # la model choisie arrive avec le clic, rien d'autre a retenir -- il
        # repond apres un redemarrage.
        _enregistrer("menus des models",
                     lambda: self.bot.add_dynamic_items(JBModelsMenu))
        # Panneau d'actions permanent : l'etat vit dans le custom_id, donc
        # les boutons repondent encore apres un redemarrage.
        _enregistrer("quantite du panneau US",
                     lambda: self.bot.add_dynamic_items(JBQtyBouton))
        # JBQtySelect reste enregistree pour les panneaux DEJA postes : ils
        # portent son custom_id, et sans elle leurs boutons deviendraient
        # muets sans un mot. JBActionButton sert le panneau, les sous-menus de
        # famille ET les anciens panneaux (jbus:a:…:templateflash:…).
        _enregistrer("actions du panneau US",
                     lambda: self.bot.add_dynamic_items(JBQtySelect, JBActionButton))
        # Les lanceurs de famille (💬 Caption ▸ …) des panneaux US deja
        # postes : ils ne sont plus poses, mais un clic doit encore
        # reconstruire le panneau en V2.
        _enregistrer("familles du panneau US",
                     lambda: self.bot.add_dynamic_items(JBFamilleBouton))
        # Les menus deroulants du panneau US V2 (« jbus:s: ») : tout leur
        # etat est dans le custom_id, ils repondent apres un redemarrage.
        _enregistrer("menus du panneau US",
                     lambda: self.bot.add_dynamic_items(JBMenuFamille))
        # Le menu ✨ General, a part et JOURNALISE : un enregistrement rate y
        # laisserait les boutons du General muets sans une ligne nulle part.
        # JBGenMenu : ses menus deroulants V2 (« jbg:s: »), tout l'etat dans
        # le custom_id -- ils repondent apres un redemarrage.
        try:
            self.bot.add_dynamic_items(JBGenButton, JBGenQtyBouton,
                                       JBGenReserveBouton, JBGenMenu)
        except Exception as e:
            log.warning("cog_load : boutons du menu General non enregistres "
                        "(%s: %s) -- ils ne repondront pas.",
                        type(e).__name__, e)
        if not self.daily_menu.is_running():
            self.daily_menu.start()

    def cog_unload(self):
        try:
            self.daily_menu.cancel()
        except Exception:
            pass

    async def _delete_old_menus(self, channel, also_onboarding=False):
        """Supprime les anciens messages de menu postés par le bot dans `channel`
        (épinglés ou non), pour qu'un nouveau menu remplace proprement l'ancien.
        also_onboarding=True supprime AUSSI le message d'intro onboarding
        (bouton « Commencer l'onboarding » + images de bonus) — pour le mode Threads."""
        me = getattr(self.bot, "user", None)
        if me is None:
            return
        try:
            async for m in channel.history(limit=40):
                if not (m.author and m.author.id == me.id):
                    continue
                # Le panneau d'actions US et le ✨ General ne sont JAMAIS des
                # menus a remplacer, dans aucun de leurs formats : le panneau
                # V2 n'a plus d'embed, et un reperage elargi a son texte
                # (« … le menu … ») l'aurait emporte.
                # Le menu des MODELS non plus, qui les precede : ce n'est pas
                # un menu VA, rien ici ne le repose, et l'ancien titre (« Menu
                # Jailbreak … ») tombait sous le test « menu » plus bas -- le
                # trio menu / panneau / General aurait perdu sa tete.
                if (_est_panneau_actions(m) or _est_general(m, me.id)
                        or _est_menu_models(m, me.id)):
                    continue
                # Le menu VA, dans ses DEUX formats : le V2 n'a plus d'embed,
                # il se reconnait a la marque de son texte (_est_menu_va).
                rm = _est_menu_va(m)
                if not rm and m.embeds:
                    t = (m.embeds[0].title or "").lower()
                    if "menu" in t or "contenu du jour" in t:
                        rm = True
                if also_onboarding and not rm:
                    # message d'intro onboarding = contient le bouton va_start_onboarding
                    try:
                        for row in (m.components or []):
                            for comp in getattr(row, "children", []):
                                if getattr(comp, "custom_id", "") == "va_start_onboarding":
                                    rm = True
                    except Exception:
                        pass
                if rm:
                    try:
                        await m.delete()
                    except Exception:
                        pass
        except Exception:
            pass

    async def jailbreak_us_menu_async(self, guild, marche="us"):
        """(None, vue) : le menu des models en « menus de 10 », avec la PP de
        chaque model en emoji. `marche` : les models proposees suivent le role
        de la personne.

        L'embed vaut None depuis le passage au format V2 (26/09/2026) : le
        texte est DANS la vue. Le couple est garde parce que ses appelants
        (welcome, /menujailbreakus, les bancs d'essai) le deballent.

        C'est au moment de POSTER qu'on cree les emojis manquants
        (ensure_identity_emojis) : au clic, il n'y a pas le temps d'appels API."""
        models = _jb_models_marche(marche)
        emojis = {}
        try:
            emojis = await ensure_identity_emojis(guild, models)
        except Exception as e:                               # noqa: BLE001
            # Sans PP le menu marche : le libelle suffit. On le dit quand meme.
            log.warning("menu des models : PP non posees (%s: %s)",
                        type(e).__name__, e)
            emojis = _jb_emojis_presents(guild, models)
        # Les icones des ACTIONS, au meme moment : c est le seul endroit ou
        # l on a le droit de prendre le temps d appels API.
        try:
            await ensure_action_emojis(guild)
        except Exception:
            pass
        return None, JailbreakModelsView(models, emojis=emojis, marche=marche,
                                         guild=guild)

    def jailbreak_us_menu(self, marche="us", guild=None):
        """(None, vue) du menu des models, SANS creer d'emoji : le repli quand
        la version async echoue. Les PP deja presentes sur le serveur sont
        reprises (lecture seule). Meme disposition, meme texte : c'est la
        meme vue (JailbreakModelsView)."""
        return None, _jb_menu_models_vue(marche, guild)

    async def _post_menu(self, channel, identity, mention_user_id=None):
        """Poste le menu (V2 : texte + boutons + menus) dans `channel`. @ping
        le VA si fourni. Filtre boutons, menus et aide selon les fonctions
        activées sur le serveur.

        Un message V2 n'a pas de `content` : la ligne qui pinge le VA est la
        premiere de son texte (_menu_va_texte), et allowed_mentions s'y
        applique comme au contenu d'avant."""
        guild = getattr(channel, "guild", None)
        view = _menu_va(self, identity, guild, mention=mention_user_id)
        if not view.a_des_elements():
            return False  # aucune fonction de menu activée sur ce serveur
        try:
            await channel.send(
                view=view,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            return True
        except Exception as e:
            # Jusqu'ici un echec d'envoi disparaissait : le menu du jour
            # manquait dans le salon sans une ligne nulle part.
            log.warning("menu VA non poste dans %s (%s: %s)",
                        getattr(channel, "name", "?"), type(e).__name__, e)
            return False

    def _va_targets(self, guild=None):
        """Salons VA à qui pousser le menu, sous forme (channel, uid, identity).
        - guild=None  -> TOUS les VAs de users.json (utilisé par le cron quotidien,
          chaque salon reçoit le menu adapté à SON serveur).
        - guild fourni -> UNIQUEMENT les salons va- de CE serveur (commandes
          manuelles : on ne pousse pas vers les autres serveurs)."""
        users = load_json(USERS_FILE, {})
        info = {}  # channel_id -> (uid, identity)
        for uid, data in users.items():
            if isinstance(data, dict):
                cid, ident = data.get("channel_id"), data.get("identity")
            elif isinstance(data, str):
                cid, ident = None, data
            else:
                continue
            if cid:
                info[cid] = (uid, ident)
        out = []
        if guild is not None:
            for ch in guild.text_channels:
                if not _ch_handle_va(ch.name):
                    continue
                uid, ident = info.get(ch.id, (None, None))
                out.append((ch, uid, ident))
        else:
            for cid, (uid, ident) in info.items():
                ch = self.bot.get_channel(cid)
                if ch is not None:
                    out.append((ch, uid, ident))
        return out

    async def _push_menu_to_all_vas(self, guild=None):
        """Poste le menu (avec @ping) dans le salon de chaque VA. Retourne le nb d'envois.
        Si `guild` est fourni, ne pousse QUE dans les salons va- de ce serveur."""
        sent = sautes = 0
        for ch, uid, ident in self._va_targets(guild):
            # Identite en pause : pas de menu (ses boutons refuseraient tous).
            if _identite_en_pause(ident):
                sautes += 1
                continue
            try:
                uid_int = int(uid) if uid is not None else None
            except (TypeError, ValueError):
                uid_int = None
            if await self._post_menu(ch, ident, mention_user_id=uid_int):
                sent += 1
        if sautes:
            log.info("menu VA : %d salon(s) saute(s), identite en pause", sautes)
        return sent

    @tasks.loop(time=_dt.time(hour=0, minute=0, tzinfo=_PARIS_TZ))
    async def daily_menu(self):
        """Chaque jour à MINUIT (heure FR) : poste le menu contenu (boutons)
        dans le salon de chaque VA, en le @pingant."""
        await self._push_menu_to_all_vas()

    @daily_menu.before_loop
    async def _before_daily_menu(self):
        await self.bot.wait_until_ready()

    # ===== Demande de lien : notification des managers =====

    async def _admin_ids(self):
        """IDs des managers à prévenir en DM : owner du bot + whitelist."""
        ids = set()
        try:
            app = await self.bot.application_info()
            if app and app.owner:
                ids.add(app.owner.id)
        except Exception:
            pass
        wl = load_json(WHITELIST_FILE, [])
        if isinstance(wl, list):
            for x in wl:
                try:
                    ids.add(int(x))
                except (TypeError, ValueError):
                    pass
        return ids

    async def _notify_managers_link_request(self, member, identity, guild):
        """Prévient les managers (salon + @rôle + DM) qu'un VA demande son lien.
        Posté DANS le serveur du VA (par serveur) + ping du rôle boss/manager."""
        gid = getattr(guild, "id", None)
        ch_id, role_id = _lr_cfg_for_guild(gid)
        name = getattr(member, "display_name", str(member))
        emb = discord.Embed(
            title="🔗 Demande de lien",
            description=f"{member.mention} (**{name}**) demande son lien.",
            color=discord.Color.orange(),
        )
        emb.add_field(name="Identité", value=f"`{identity}`", inline=True)
        emb.add_field(name="VA", value=member.mention, inline=True)
        emb.set_footer(text="Envoie-lui son lien GetMySocial.")

        # 1) Salon manager DU MÊME SERVEUR (config par serveur, sinon auto-détection)
        posted = None  # le salon où la demande a été postée (None = échec/non trouvé)
        ch = guild.get_channel(ch_id) if (guild and ch_id) else None
        if ch is None and guild:
            # Fallback : trouve un salon "demande-...-lien" DANS ce serveur
            ch = discord.utils.find(
                lambda c: "demande" in (c.name or "").lower() and "lien" in (c.name or "").lower(),
                guild.text_channels,
            )
        if ch is not None:
            # Ping : rôle configuré, sinon on ping les rôles boss/manager du serveur
            if role_id:
                ping = f"<@&{role_id}> "
            else:
                boss_roles = [r for r in getattr(guild, "roles", [])
                              if any(k in (r.name or "").lower() for k in ("boss", "manager", "manageu"))]
                ping = " ".join(r.mention for r in boss_roles[:3]) + (" " if boss_roles else "")
            view = discord.ui.View(timeout=None)
            try:
                view.add_item(GenLinkButton(member.id))
            except Exception:
                view = None
            try:
                await ch.send(
                    content=(ping + "nouvelle demande de lien").strip(),
                    embed=emb,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
                posted = ch  # succès : on a bien posté dans le salon
            except Exception as e:
                print(f"[lien] post #{getattr(ch,'name','?')} échoué : {e}")

        # 2) DM aux managers (owner + whitelist)
        for aid in await self._admin_ids():
            try:
                u = self.bot.get_user(aid) or await self.bot.fetch_user(aid)
                if u:
                    await u.send(embed=emb)
            except Exception:
                pass
        return posted

    async def request_link(self, interaction: discord.Interaction):
        """Bouton "Demander un lien" du menu VA.
        - Si le VA a DÉJÀ un lien -> on lui affiche directement son lien.
        - Sinon -> demande envoyée aux managers."""
        if not _menu_feature_check(interaction, "liens"):
            await interaction.response.send_message("⚠️ Fonction désactivée sur ce serveur.", ephemeral=True)
            return
        uid = interaction.user.id
        # Identité dédiée du serveur (ex: hybride pour Threads) si définie, sinon celle du VA.
        identity = _link_identity(interaction.guild, uid)
        if not identity:
            await interaction.response.send_message(
                "⚠️ Tu n'as pas d'identité assignée — demande à un admin.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        # 1) Lien déjà connu en local -> on l'affiche (sauf s'il est d'une autre
        #    identité que celle dédiée au serveur : alors on le considère périmé).
        _ex = _lr_existing(uid)
        if _ex and _ex.get("url") and _link_is_for_server_identity(_ex["url"], interaction.guild):
            await interaction.followup.send(
                _link_message(_ex["url"], interaction.guild), ephemeral=True,
            )
            return

        # 2) Demande déjà en attente -> on évite de re-spammer (et d'interroger GMS).
        if _lr_is_pending(uid):
            await interaction.followup.send(
                "⏳ **Ta demande est déjà en attente** — un manager va t'envoyer ton lien. "
                "Pas besoin de re-cliquer 🙂",
                ephemeral=True,
            )
            return

        # 3) Sinon, le lien existe peut-être sur GMS (ex: créé via le site) -> on le cherche.
        url = ""
        users = load_json(USERS_FILE, {})
        data = users.get(str(uid), {})
        ch_id = data.get("channel_id") if isinstance(data, dict) else None
        va_ch = interaction.client.get_channel(ch_id) if ch_id else None
        handle = ""
        if va_ch:
            m = re.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (va_ch.name or "").lower())
            handle = m.group(1) if m else ""
        if not handle:
            handle = (getattr(interaction.user, "name", "") or "").lower()
        if handle:
            try:
                import gms
                _all = await asyncio.to_thread(gms.list_all_links)
                if _all.get("ok"):
                    _hit = _gms_exact_link(handle, _all.get("links") or [])
                    if _hit:
                        _sc = _hit.get("shortcode", "")
                        _u = f"{gms.PUBLIC_LINK_DOMAIN}/{_sc}" if _sc else ""
                        # On ignore un lien d'une autre identité (serveur hybride).
                        if _u and _link_is_for_server_identity(_u, interaction.guild):
                            url = _u
                            _lr_mark_generated(uid, url, _hit.get("display_name", ""))
            except Exception:
                pass  # GMS indispo -> on retombe sur la demande normale

        if url:
            await interaction.followup.send(
                _link_message(url, interaction.guild), ephemeral=True,
            )
            return

        # 4) Vraiment pas de lien -> demande aux managers.
        posted = None
        try:
            posted = await self._notify_managers_link_request(
                interaction.user, identity, interaction.guild
            )
        except Exception:
            posted = None
        if posted is not None:
            # On marque "en attente" UNIQUEMENT si la notif est bien partie dans un
            # salon (sinon le VA resterait bloqué "déjà en attente" sans rien reçu).
            _lr_mark_pending(uid)
            await interaction.followup.send(
                f"✅ **Demande envoyée aux managers !** (dans {posted.mention}) Tu vas recevoir ton lien bientôt 🔗",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "⚠️ **Aucun salon `demande-de-lien` joignable** sur ce serveur "
                "(salon introuvable ou le bot ne peut pas y écrire). Recliquera plus tard, "
                "ou un admin doit faire `/setliensalon` + **donner au bot l'accès au salon**.",
                ephemeral=True,
            )

    @app_commands.command(name="lien", description="Demande ton lien aux managers")
    async def lien(self, interaction: discord.Interaction):
        await self.request_link(interaction)

    @app_commands.command(
        name="menuall",
        description="[ADMIN] Pousse le menu aux VAs de CE serveur maintenant (avec @ping)",
    )
    async def menuall(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message(
                "Réservé aux managers/admins.", ephemeral=True
            )
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        # Scopé au serveur courant : on ne pousse PAS vers les autres serveurs.
        sent = await self._push_menu_to_all_vas(guild=interaction.guild)
        await interaction.followup.send(
            f"✅ Menu poussé à **{sent}** VA(s) de **{interaction.guild.name}** (chacun @pingé dans son salon).",
            ephemeral=True,
        )

    async def _run_for_model(self, interaction, model, cmd, count=None, supports_count=False,
                             brute_de=None):
        """Execute une action de contenu (reel/story/...) pour la MODEL choisie en
        surchargeant temporairement l'identite via le contextvar (menu Jailbreak).
        `count` = quantite demandee (multiplicateur) ; envoyee a la commande SEULEMENT
        si elle accepte un parametre `nombre` (reel/story/post/storycta/bio/pp). Le
        plafond Range[1,10] du slash n'est PAS applique ici (appel direct du callback)
        -> on peut demander beaucoup ; les generateurs plafonnent au stock dispo. Local
        a la task -> pas d'interference entre clics simultanes.

        `brute_de` (menu ✨ General) : `model` est alors la RESERVE, d'ou vient
        tout le contenu, et `brute_de` la model cliquee, dont on prend la video
        brute (_dossier_brutes). Nomme et en dernier : JBActionButton et le
        menu FR ne le passent pas, rien ne change pour eux."""
        # Serveur US : le contenu part dans le salon @pseudo-content du cliqueur
        # (le salon -menu est en lecture seule), via un proxy d'interaction.
        itx, target = interaction, None
        try:
            import guild_features as gf
            if gf.is_us_guild(getattr(interaction, "guild", None)):
                target = _us_content_target(interaction)
                if target is not None and target.id != getattr(interaction.channel, "id", None):
                    itx = _JBRedirect(interaction, target)
                elif _est_salon_menu(getattr(interaction, "channel", None)):
                    # salon -menu sans -content identifiable : on n'y publie
                    # rien, tout repart en ephemere
                    itx = _JBRedirect(interaction, None)
                    target = None
                else:
                    target = None
        except Exception:
            itx, target = interaction, None
        token = _IDENTITY_OVERRIDE.set((model or "").strip().lower())
        token_m = _MODEL_REELLE.set((brute_de or "").strip().lower() or None)
        try:
            _rappel = getattr(cmd, "callback", None)
            if _rappel is None:
                # Methode ordinaire, deja liee au cog : pas de `self` a passer.
                if supports_count and count and count > 0:
                    await cmd(itx, count)
                else:
                    await cmd(itx)
            elif supports_count and count and count > 0:
                await _rappel(self, itx, count)
            else:
                await _rappel(self, itx)
        finally:
            # Dans le finally, comme l'identite : une commande qui leve ne
            # doit pas laisser la model reelle posee pour la suite de la tache.
            _MODEL_REELLE.reset(token_m)
            _IDENTITY_OVERRIDE.reset(token)
        # (Plus de note « Direction #salon » : le panneau permanent l'annonce
        # deja, et elle doublait le nombre de messages dans le salon -menu.)

    async def _handle_assistance(self, interaction, probleme):
        """Bouton 🆘 Assistance : transmet le probleme du VA au salon d'aide
        (🆘・help) avec ping managers/boss, puis confirme au VA."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("À utiliser dans un serveur.", ephemeral=True)
            return
        probleme = (probleme or "").strip()
        if not probleme:
            await interaction.followup.send(
                "Tu n'as rien écrit — reclique sur 🆘 Assistance et explique ton souci.",
                ephemeral=True)
            return
        help_ch = _find_help_channel(guild)
        if help_ch is None:
            await interaction.followup.send(
                "⚠️ Je ne trouve pas le salon d'aide (🆘・help). Préviens un admin.",
                ephemeral=True)
            return
        identity = get_user_identity(interaction.user.id) or "—"
        # Salon perso du VA (via users.json), fallback sur le salon courant si va-
        va_ch = None
        try:
            users = load_json(USERS_FILE, {})
            data = users.get(str(interaction.user.id))
            if isinstance(data, dict) and data.get("channel_id"):
                va_ch = guild.get_channel(data["channel_id"])
        except Exception:
            va_ch = None
        if va_ch is None and _ch_handle_va(getattr(interaction.channel, "name", "")):
            va_ch = interaction.channel
        emb = discord.Embed(
            title="🆘 Un VA a besoin d'aide",
            description=f"**Problème :**\n{probleme[:1500]}",
            color=discord.Color.red(),
        )
        emb.add_field(name="👤 VA", value=interaction.user.mention, inline=True)
        emb.add_field(name="🎭 Identité", value=str(identity), inline=True)
        if va_ch is not None:
            emb.add_field(name="📍 Son salon", value=va_ch.mention, inline=True)
        emb.set_footer(text=f"{interaction.user} · ID {interaction.user.id}")
        # Bouton-lien pour sauter DIRECT dans le salon du VA (1 clic).
        _view = None
        if va_ch is not None:
            _view = discord.ui.View(timeout=None)
            _view.add_item(discord.ui.Button(
                label="💬 Aller dans son salon",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{guild.id}/{va_ch.id}",
            ))
        try:
            await help_ch.send(
                content=f"{_staff_ping(guild)} — un VA demande de l'aide 👇",
                embed=emb,
                view=_view,
                allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=True),
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Je n'ai pas la permission d'écrire dans le salon d'aide. Préviens un admin.",
                ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"⚠️ Erreur d'envoi : {e}", ephemeral=True)
            return
        await interaction.followup.send(
            "✅ **C'est transmis !** Un **manager** ou un **boss** va venir t'aider très vite. "
            "Reste dans ton salon, on te répond ici. 🙌",
            ephemeral=True)

    def _store_payment(self, uid, info):
        """Ecrit users.json[uid]['payment'] = info (cree l'entree dict si besoin).
        Retourne True SI l'ecriture a reussi : l'appelant annonce « enregistré »,
        il ne doit pas le faire quand rien n'a ete ecrit (c'est le moyen d'etre
        paye, un VA ne doit pas croire l'avoir declare pour rien)."""
        import time as _t
        info["updated_at"] = int(_t.time())
        users = load_json(USERS_FILE, {})
        data = users.get(uid)
        if not isinstance(data, dict):
            data = {"identity": data} if isinstance(data, str) and data else {}
            users[uid] = data
        data["payment"] = info
        return bool(save_json(USERS_FILE, users))

    async def _notify_payment(self, interaction, info, screenshot_att=None):
        """Poste le moyen de paiement dans le SALON PERSO du VA (privé : seul le VA +
        le staff le voient), PAS dans un salon public. Joint la capture si fournie."""
        guild = interaction.guild
        ch = None
        try:
            _u = load_json(USERS_FILE, {}).get(str(interaction.user.id))
            if isinstance(_u, dict) and _u.get("channel_id"):
                ch = guild.get_channel(_u["channel_id"])
        except Exception:
            ch = None
        if ch is None and _ch_handle_va(getattr(interaction.channel, "name", "")):
            ch = interaction.channel  # fallback : le salon courant si c'est un va-
        if ch is None:
            return
        emb = discord.Embed(title="💸 Moyen de paiement (VA)", color=discord.Color.gold())
        emb.add_field(name="👤 VA", value=interaction.user.mention, inline=True)
        idt = get_user_identity(interaction.user.id)
        if idt:
            emb.add_field(name="🎭 Identité", value=str(idt), inline=True)
        emb.add_field(name="💰 Moyen", value=_payment_summary(info) or "—", inline=False)
        emb.set_footer(text=f"{interaction.user} · ID {interaction.user.id}")
        try:
            if screenshot_att is not None:
                f = await screenshot_att.to_file()
                await ch.send(embed=emb, file=f)
            else:
                await ch.send(embed=emb)
        except Exception:
            try:
                await ch.send(embed=emb)
            except Exception:
                pass

    async def _save_payment(self, interaction, info):
        """Enregistre le moyen de paiement (TapTap) + confirme + notifie."""
        ok = self._store_payment(str(interaction.user.id), info)
        summary = _payment_summary(info) or "—"
        if not ok:
            await interaction.response.send_message(
                f"❌ **Échec de l'enregistrement** de ton moyen de paiement.\n{summary}\n\n"
                "Rien n'a été sauvegardé — réessaie, et préviens un manager si ça persiste.",
                ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ **Moyen de paiement enregistré !**\n{summary}\n\n"
            "Le boss le verra pour te payer. Tu peux le changer quand tu veux "
            "avec le même bouton. 💸",
            ephemeral=True)
        await self._notify_payment(interaction, info, None)

    async def _save_crypto_and_ask_screenshot(self, interaction, info):
        """Enregistre l'adresse USDC puis demande au VA de DEPOSER une capture d'ecran
        dans le salon (les modals Discord n'acceptent pas d'image) ; l'attache ensuite
        au moyen de paiement + notif."""
        import asyncio as _a
        uid = str(interaction.user.id)
        if not self._store_payment(uid, info):
            await interaction.response.send_message(
                "❌ **Échec de l'enregistrement** de ton adresse — rien n'a été "
                "sauvegardé. Réessaie, et préviens un manager si ça persiste.",
                ephemeral=True)
            return
        chain = info.get("chain", "")
        await interaction.response.send_message(
            f"✅ Adresse enregistrée : **USDC · {chain}**\n`{info.get('address', '')}`\n\n"
            "📸 **Dernière étape : envoie une CAPTURE D'ÉCRAN de ton wallet dans ce salon** "
            "(glisse l'image ici). Tu as 5 min. _(ou tape `skip` pour passer)_",
            ephemeral=True)

        def _check(m):
            return (m.author.id == interaction.user.id
                    and getattr(m.channel, "id", None) == getattr(interaction.channel, "id", None)
                    and (bool(m.attachments) or (m.content or "").strip().lower() == "skip"))

        try:
            msg = await interaction.client.wait_for("message", check=_check, timeout=300)
        except _a.TimeoutError:
            try:
                await interaction.followup.send(
                    "⏳ Pas de capture reçue — ton adresse est **enregistrée** quand même. "
                    "Tu pourras rajouter la capture plus tard via 💸 Mon paiement.",
                    ephemeral=True)
            except Exception:
                pass
            await self._notify_payment(interaction, info, None)
            return
        if msg.attachments:
            att = msg.attachments[0]
            info["screenshot"] = att.url
            self._store_payment(uid, info)  # re-ecrit avec le lien de la capture
            try:
                await interaction.followup.send(
                    "✅ Capture reçue, merci ! Ton moyen de paiement est **complet**. 💸",
                    ephemeral=True)
            except Exception:
                pass
            await self._notify_payment(interaction, info, screenshot_att=att)
        else:
            try:
                await interaction.followup.send(
                    "Ok, sans capture. Ton adresse est **enregistrée**. 💸", ephemeral=True)
            except Exception:
                pass
            await self._notify_payment(interaction, info, None)

    @app_commands.command(
        name="moyenspaiement",
        description="[ADMIN] Liste les moyens de paiement déclarés par les VA",
    )
    async def moyenspaiement(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        users = load_json(USERS_FILE, {})
        guild = interaction.guild
        lines = []
        for uid, data in users.items():
            if not isinstance(data, dict):
                continue
            summary = _payment_summary(data.get("payment"))
            if not summary:
                continue
            mem = None
            try:
                mem = guild.get_member(int(uid)) if guild else None
            except Exception:
                mem = None
            who = mem.mention if mem else f"`{uid}`"
            lines.append(f"• {who} — {summary}")
        if not lines:
            await interaction.response.send_message(
                "Aucun VA n'a encore déclaré de moyen de paiement.", ephemeral=True)
            return
        header = f"💸 **Moyens de paiement des VA** ({len(lines)})\n"
        out, total = [], len(header)
        for ln in lines:
            if total + len(ln) + 1 > 1950:
                break
            out.append(ln)
            total += len(ln) + 1
        body = header + "\n".join(out)
        if len(out) < len(lines):
            body += f"\n… +{len(lines) - len(out)} autre(s) (trop pour un message)"
        await interaction.response.send_message(body, ephemeral=True)

    async def _send_tutoriel(self, interaction):
        """Bouton 'Comprends rien ?' : envoie la vidéo explicative (data/tutoriel.mp4)
        en privé au VA (ré-upload natif -> lecture inline)."""
        if not TUTO_VIDEO_FILE.exists():
            await interaction.response.send_message(
                "📹 La vidéo explicative n'est pas encore disponible — un admin doit la "
                "définir avec `/settutoriel`. Reviens bientôt !", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await interaction.followup.send(
                content="🎬 **Comment ça marche — la vidéo qui explique tout :**\n"
                        "Regarde ça tranquillement, tu vas tout comprendre ! 👇",
                file=discord.File(str(TUTO_VIDEO_FILE), filename="tutoriel.mp4"),
                ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                f"⚠️ Impossible d'envoyer la vidéo ({e}). Préviens un admin.", ephemeral=True)

    @app_commands.command(
        name="settutoriel",
        description="[ADMIN] Définit la vidéo explicative montrée par le bouton « Comprends rien ? »",
    )
    @app_commands.describe(video="La vidéo explicative (mp4/mov). Elle remplace l'ancienne.")
    async def settutoriel(self, interaction: discord.Interaction, video: discord.Attachment):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        ct = (video.content_type or "").lower()
        if "video" not in ct and not video.filename.lower().endswith((".mp4", ".mov", ".webm", ".m4v")):
            await interaction.response.send_message(
                "❌ Envoie un fichier **vidéo** (.mp4, .mov…).", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            TUTO_VIDEO_FILE.parent.mkdir(parents=True, exist_ok=True)
            await video.save(str(TUTO_VIDEO_FILE))
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur de sauvegarde : {e}", ephemeral=True)
            return
        _mo = video.size / (1024 * 1024)
        await interaction.followup.send(
            f"✅ Vidéo explicative enregistrée (**{_mo:.1f} Mo**). "
            "Le bouton **« Comprends rien ? »** la montrera aux VA.\n"
            "⚠️ Si elle est trop lourde pour Discord (~25 Mo sans boost), l'envoi aux VA "
            "peut échouer — garde-la légère.",
            ephemeral=True)

    @app_commands.command(
        name="marquerliens",
        description="[ADMIN] Ajoute/retire le 🔗 (a un lien) sur les salons VA, sans toucher au rond d'activite",
    )
    async def marquerliens(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
            links = await asyncio.to_thread(gms.list_all_links)
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        if not isinstance(links, dict) or not links.get("ok"):
            await interaction.followup.send(
                "⚠️ GetMySocial ne répond pas — réessaie dans un instant.", ephemeral=True)
            return
        link_list = links.get("links") or []
        targets = []
        for ch in guild.text_channels:
            h = _ch_handle_va(ch.name)
            if not h:
                continue
            has = bool(_gms_exact_link(h, link_list))
            targets.append((ch, has))
        if not targets:
            await interaction.followup.send("Aucun salon `va-…` trouvé sur ce serveur.", ephemeral=True)
            return
        n_link = sum(1 for _, h in targets if h)
        await interaction.followup.send(
            f"🔄 Marquage 🔗 lancé sur **{len(targets)}** salon(s) VA "
            f"({n_link} avec lien 🔗, {len(targets) - n_link} sans) — en arrière-plan "
            f"(Discord limite les renommages, ~quelques minutes). Le rond d'activité (🟢/🟠/🔴) "
            f"n'est PAS touché. Je préviens ici à la fin.",
            ephemeral=True)
        _chan = interaction.channel
        _uid = interaction.user.id

        async def _run():
            renamed = already = failed = 0
            for ch, has in targets:
                try:
                    target = _va_channel_target_name(ch.name, has)
                    if not target or target.replace(_VS, "") == (ch.name or "").replace(_VS, ""):
                        already += 1
                        continue
                    await ch.edit(name=target, reason="marquage lien VA")
                    renamed += 1
                except Exception:
                    failed += 1
            try:
                await _chan.send(
                    f"✅ <@{_uid}> Marquage 🔗 terminé : **{renamed}** mis à jour, "
                    f"{already} déjà ok" + (f", {failed} échec(s)" if failed else "") + ".\n"
                    f"🔗 = a un lien (ajouté à côté du rond d'activité 🟢/🟠/🔴, qui ne bouge pas)")
            except Exception:
                pass
        interaction.client.loop.create_task(_run())

    @app_commands.command(
        name="menujailbreak",
        description="[ADMIN] Poste ICI le menu Jailbreak (toutes les models) pour les VA avec le role Jailbreak",
    )
    async def menujailbreak(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        # Serveur FR : seulement les models du marche FR — les US n'ont
        # rien a faire ici (elles ont /menujailbreakus sur Youl4b).
        # LA LISTE DU MENU, PAS UNE COPIE : ce comptage lisait
        # list_active_identities() filtree au marche pendant que le menu
        # lui-meme listait TOUTES les identites actives -- deux listes pour
        # une decision. C'est desormais celle que le menu affiche.
        models = _jb_models_marche("fr")
        if not models:
            await interaction.response.send_message(
                "⚠️ Aucune model FR à afficher.\n" + _jb_diagnostic_marche("fr"),
                ephemeral=True)
            return
        # Creer les PP en emoji et le role prend plus que les 3 s de Discord.
        await interaction.response.defer(ephemeral=True, thinking=True)
        # S'assurer que le role 'Jailbreak' existe (auto-creation best-effort)
        role = discord.utils.find(
            lambda r: (getattr(r, "name", "") or "").strip().lower() == "jailbreak", guild.roles)
        created = False
        if role is None:
            try:
                role = await guild.create_role(
                    name="Jailbreak", colour=discord.Color.dark_red(),
                    reason="Menu Jailbreak — accès à toutes les models")
                created = True
            except Exception:
                role = None
        # Le menu en « menus de 10 », la meme vue que partout ailleurs. Poste
        # dans le salon, PAS en suivi de l'interaction : un suivi apres un
        # defer « thinking » EDITE le message d'attente, et le passer au
        # format V2 par cette voie n'a jamais ete eprouve -- le salon, si
        # (_ensure_us_menu le fait depuis le debut).
        _e, vue = await self.jailbreak_us_menu_async(guild, "fr")
        try:
            await interaction.channel.send(view=vue)
        except Exception as e:                               # noqa: BLE001
            log.warning("/menujailbreak %s : menu non poste (%s: %s)",
                        getattr(interaction.channel, "name", "?"),
                        type(e).__name__, e)
            await interaction.followup.send(
                f"❌ Menu non posté ici ({type(e).__name__}) — le bot a-t-il le "
                "droit d'écrire dans ce salon ?", ephemeral=True)
            return
        note = ""
        if created:
            note = f"\n✅ Rôle **{role.name}** créé — donne-le aux VA jailbreak."
        elif role is None:
            note = ("\n⚠️ Je n'ai pas pu créer le rôle « Jailbreak » (permissions manquantes) "
                    "— crée-le à la main et donne-le aux VA concernés.")
        try:
            await interaction.followup.send(f"✅ Menu Jailbreak posté ici.{note}", ephemeral=True)
        except Exception:
            pass

    @app_commands.command(
        name="menujailbreakus",
        description="[ADMIN] Poste ICI le menu Jailbreak US (toutes les models SAUF le marché FR)",
    )
    async def menujailbreakus(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        import guild_features as gf
        if not gf.is_us_guild(guild):
            await interaction.response.send_message(
                "🔒 Réservé au serveur US (Youl4b) — rien ne change sur ce serveur.", ephemeral=True)
            return
        models = _jb_us_models()
        if not models:
            # ON DIT CE QUI MANQUE, PAS « ca n'a pas marche ». Un menu vide
            # laisse chercher pendant une heure ; les compteurs par filtre
            # designent la case a corriger sur le site.
            await interaction.response.send_message(
                "⚠️ Aucune model US à afficher.\n" + _jb_diagnostic_marche("us"),
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        _e, view = await self.jailbreak_us_menu_async(guild)
        # Dans le salon, pas en suivi : voir /menujailbreak.
        try:
            await interaction.channel.send(view=view)
        except Exception as e:                               # noqa: BLE001
            log.warning("/menujailbreakus %s : menu non poste (%s: %s)",
                        getattr(interaction.channel, "name", "?"),
                        type(e).__name__, e)
            await interaction.followup.send(
                f"❌ Menu non posté ici ({type(e).__name__}) — le bot a-t-il le "
                "droit d'écrire dans ce salon ?", ephemeral=True)
            return
        try:
            await interaction.followup.send(
                "✅ Menu Jailbreak US posté ici — ouvert à tout le monde sur ce serveur "
                "(pas de rôle à donner).", ephemeral=True)
        except Exception:
            pass

    @app_commands.command(
        name="panellien",
        description="[ADMIN] Poste ICI un panneau pour générer un lien GetMySocial en 1 clic",
    )
    async def panellien(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if not _menu_feature_check(interaction, "liens"):
            await interaction.response.send_message("⚠️ Génération de lien désactivée sur ce serveur.", ephemeral=True)
            return
        emb = discord.Embed(
            title="🔗 Générateur de lien GetMySocial",
            description=(
                "Clique sur le bouton, entre l'**identité** (le modèle) et le **pseudo du VA**, "
                "et le lien est généré en 1 clic.\n"
                "Le lien est nommé `va_@pseudo`, et s'il existe un salon `va-pseudo`, il y est aussi envoyé."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=emb, view=LinkPanelView())

    @app_commands.command(
        name="menucentral",
        description="[ADMIN] Poste ICI un menu central : chaque VA clique, le contenu arrive dans SON salon",
    )
    @app_commands.describe(
        nettoyer="true = vide d'abord le salon pour ne laisser QUE le menu (épinglé)",
    )
    async def menucentral(self, interaction: discord.Interaction, nettoyer: bool = False):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if not _menu_feature_check(interaction, "contenu"):
            await interaction.response.send_message("⚠️ Le menu contenu est désactivé sur ce serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ch = interaction.channel
        cleaned = 0
        if nettoyer and ch is not None:
            try:
                deleted = await ch.purge(limit=1000)
                cleaned = len(deleted)
            except discord.Forbidden:
                await interaction.followup.send(
                    "⚠️ Il me manque la permission **Gérer les messages** pour nettoyer ce salon.",
                    ephemeral=True)
                return
            except Exception as e:
                # Nettoyage partiel (ex: messages > 14 j non supprimables en masse) :
                # on continue quand même à poser le menu.
                print(f"[menucentral] purge partielle : {e}")
        emb = discord.Embed(
            title="🎛️ Menu contenu — clique, ça arrive dans TON salon",
            description=(
                "Clique un bouton ci-dessous : ton contenu est envoyé **dans ton salon perso `va-…`** "
                "(pas ici). Tu peux cliquer **autant de fois que tu veux**.\n\n"
                "🎬 **Reel** · 📖 **Story** · 🖼️ **Post** · 📲 **Story CTA**\n"
                "👤 **Pseudo** · 📝 **Name** · 💬 **Bio** · 🖼 **PP** · 🔗 **Demander un lien**\n\n"
                "⚠️ **Règles :** 1 reel différent par compte (jamais le même sur 2 comptes) · "
                "Story CTA **entre 19h et 23h** · suis ton onboarding (jour 0 → 6+)."
            ),
            color=discord.Color.blurple(),
        )
        try:
            _vue_c = CentralMenuView(self)
            # interaction.guild, PAS guild : cette fonction n a pas de
            # variable « guild ». Un NameError serait tombe dans le except
            # ci-dessous et le menu aurait cesse de se poster, sans un mot.
            _poser_icones_menu(_vue_c, interaction.guild)
            msg = await ch.send(embed=emb, view=_vue_c)
        except Exception as e:
            await interaction.followup.send(f"❌ Impossible de poster le menu : {e}", ephemeral=True)
            return
        try:
            await msg.pin(reason="Menu central permanent")
            # Supprime la notif système « X a épinglé un message » pour rester
            # 100% menu-only (ne touche jamais le message du menu lui-même).
            if nettoyer:
                await asyncio.sleep(0.4)
                await ch.purge(limit=5, check=lambda m: m.id != msg.id)
        except Exception:
            pass
        note = f" · 🗑️ **{cleaned}** message(s) supprimé(s)" if nettoyer else ""
        await interaction.followup.send(
            f"✅ Menu central posté et épinglé ici{note}.\n"
            "Les VAs cliquent → leur contenu arrive dans **leur** salon perso (pas ici).",
            ephemeral=True)

    async def _pin_menus_for_guild(self, guild, clean_onboarding=False) -> int:
        """Remplace/épingle le menu (adapté au serveur) dans chaque salon va- du
        serveur. clean_onboarding=True supprime aussi l'intro d'onboarding (mode
        Threads). Retourne le nombre de salons traités."""
        pinned = 0
        for ch, uid, ident in self._va_targets(guild):
            try:
                await self._delete_old_menus(ch, also_onboarding=clean_onboarding)
                _view = _menu_va(self, ident, guild)
                if not _view.a_des_elements():
                    continue
                msg = await ch.send(view=_view)
                await msg.pin(reason="Menu permanent VA (h24)")
                pinned += 1
                await asyncio.sleep(1.2)
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"[menupin] salon {getattr(ch, 'id', '?')} : {e}")
        return pinned

    @app_commands.command(
        name="menupin",
        description="[ADMIN] Épingle un menu PERMANENT (h24) dans le salon de chaque VA",
    )
    async def menupin(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        pinned = await self._pin_menus_for_guild(interaction.guild)
        await interaction.followup.send(
            f"📌 Menu permanent épinglé dans **{pinned}** salon(s) VA de **{interaction.guild.name}**.\n"
            "→ Chaque VA a le menu en **message épinglé** en haut de son salon.\n"
            "⚠️ Le bot a besoin de **Gérer les messages** pour épingler.",
            ephemeral=True,
        )

    @app_commands.command(
        name="menuthreads",
        description="[ADMIN] Active le mode Threads + pose le menu réduit sur CE serveur",
    )
    async def menuthreads(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            import guild_features as gf
            gf.set_threads(interaction.guild, True)  # 1) bascule le serveur en mode Threads
        except Exception as e:
            await interaction.followup.send(f"❌ Impossible d'activer le mode Threads : {e}", ephemeral=True)
            return
        # Réponse IMMÉDIATE (sinon "réfléchit…" tant que tous les salons ne sont pas faits)
        n_targets = len(self._va_targets(interaction.guild))
        await interaction.followup.send(
            f"🧵 **Mode Threads activé** sur **{interaction.guild.name}**.\n"
            f"📌 Je (re)pose le menu Threads dans **{n_targets}** salon(s) VA… "
            "(ça tourne en arrière-plan, ~1-2 min s'il y en a beaucoup).",
            ephemeral=True,
        )
        # 2) (re)pose le menu Threads + supprime les anciennes intros onboarding
        pinned = await self._pin_menus_for_guild(interaction.guild, clean_onboarding=True)
        try:
            await interaction.followup.send(
                f"✅ Menu Threads posé dans **{pinned}** salon(s) "
                "(👤 Pseudo · 📝 Name · 🖼 PP · 📊 Mes clics · 🔗 Demander un lien · 📷 Mes comptes Threads).",
                ephemeral=True,
            )
        except Exception:
            pass

    @app_commands.command(
        name="setliensalon",
        description="[ADMIN] Définit le salon où arrivent les demandes de lien",
    )
    @app_commands.describe(salon="Le salon manager qui reçoit les demandes de lien")
    async def setliensalon(self, interaction: discord.Interaction, salon: discord.TextChannel):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        _lr_cfg_set_guild(interaction.guild.id, channel_id=salon.id)
        await interaction.response.send_message(
            f"✅ Les demandes de lien de **{interaction.guild.name}** arriveront dans {salon.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="setlienrole",
        description="[ADMIN] Définit le rôle à ping pour les demandes de lien",
    )
    @app_commands.describe(role="Le rôle manager à @ping (laisse vide pour enlever le ping)")
    async def setlienrole(self, interaction: discord.Interaction, role: discord.Role = None):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        _lr_cfg_set_guild(interaction.guild.id, role_id=(role.id if role else None), set_role=True)
        if role:
            await interaction.response.send_message(
                f"✅ Le rôle {role.mention} sera ping à chaque demande de lien.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.response.send_message("✅ Ping de rôle désactivé.", ephemeral=True)

    @app_commands.command(
        name="resetlien",
        description="[OWNER] Réinitialise l'anti-doublon de lien d'un VA (pour re-tester)",
    )
    @app_commands.describe(
        membre="Le VA à débloquer (sinon : le VA du salon où tu lances la commande)",
        supprimer_gms="true = supprime aussi son lien sur GetMySocial (reset complet)",
        regenerer="true = génère DIRECT un nouveau lien avec le bon template/identité",
    )
    async def resetlien(
        self, interaction: discord.Interaction,
        membre: discord.Member = None, supprimer_gms: bool = False,
        regenerer: bool = False,
    ):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ch = interaction.channel
        # Résout le VA : membre fourni, sinon via le salon courant (users.json), + le handle
        uid = membre.id if membre else None
        if uid is None:
            users = load_json(USERS_FILE, {})
            for k, data in users.items():
                if isinstance(data, dict) and data.get("channel_id") == getattr(ch, "id", None):
                    try:
                        uid = int(k)
                    except Exception:
                        uid = None
                    break
        handle = _ch_handle_va(getattr(ch, "name", "")) or (getattr(membre, "name", "") or "").lower()
        if uid is None and not handle:
            await interaction.followup.send(
                "⚠️ Lance la commande **dans le salon `va-` du VA**, ou précise `membre:`.",
                ephemeral=True)
            return
        # 1) Reset de l'état local (pending + bloc dur)
        cleared = False
        if uid is not None:
            d = _lr_load()
            cleared = str(uid) in d
            d.pop(str(uid), None)
            save_json(LINK_STATE_FILE, d)
        who = f"<@{uid}>" if uid is not None else f"`{handle}`"
        msg = f"✅ Anti-doublon réinitialisé pour {who}" + ("" if cleared or uid is None else " (rien en local)") + "."
        # 2) Optionnel : supprimer TOUS les liens va_@<handle> sur GMS (sinon la
        #    couche 2 rebloque ou affiche un ancien lien d'une autre identité).
        # regenerer implique de supprimer l'ancien lien d'abord (sinon doublon)
        if (supprimer_gms or regenerer) and handle:
            try:
                import gms
                # Scan le workspace par défaut ET tous les teams connus (Threads US…)
                # sinon un lien hybride dans Threads US ne serait pas supprimé.
                pool = []
                allr = await asyncio.to_thread(gms.list_all_links)
                if allr.get("ok"):
                    pool += (allr.get("links") or [])
                for tid in getattr(gms, "KNOWN_TEAMS", ()):
                    try:
                        tr = await asyncio.to_thread(gms.list_links_team, tid)
                        if tr.get("ok"):
                            pool += (tr.get("links") or [])
                    except Exception:
                        pass
                seen_ids, links = set(), []
                for l in pool:
                    lid = l.get("id")
                    if lid and lid not in seen_ids:
                        seen_ids.add(lid)
                        links.append(l)
                targets = [l for l in links if l.get("id") and _gms_exact_link(handle, [l])]
                deleted = 0
                for l in targets:
                    r = await asyncio.to_thread(gms.delete_link, l["id"])
                    if r.get("ok"):
                        deleted += 1
                if deleted:
                    msg += f"\n🗑️ **{deleted}** lien(s) GetMySocial `va_@{handle}` supprimé(s)."
                else:
                    msg += "\n(aucun lien `va_@` trouvé sur GMS)"
            except Exception as e:
                msg += f"\n⚠️ GMS indispo : {e}"
        elif not regenerer:
            msg += "\n⚠️ S'il a déjà un lien `va_@<pseudo>` sur GMS, la vérif le rebloquera — relance avec `supprimer_gms:true` pour un reset complet."
        # 3) Optionnel : régénère DIRECT un nouveau lien (bon template + identité serveur)
        if regenerer and handle:
            try:
                import gms
                ident = (_link_identity(interaction.guild, uid) or "").strip().lower()
                if not ident:
                    msg += "\n⚠️ Régénération impossible : aucune identité (ni serveur, ni VA)."
                else:
                    gen = await asyncio.to_thread(gms.quick_generate_for_identity, ident, handle)
                    if gen.get("ok"):
                        grp = f" · groupe **{gen['group']}**" if gen.get("group") else ""
                        msg += (f"\n🔗 **Nouveau lien {ident}** : {gen.get('public_url')}{grp}\n"
                                f"_(« Demander un lien » affichera celui-ci.)_")
                    else:
                        msg += f"\n⚠️ Régénération échouée : {gen.get('error')}"
            except Exception as e:
                msg += f"\n⚠️ Régénération : {e}"
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(
        name="menu",
        description="Menu contenu : reel / story / story CTA / pseudo / name en 1 clic",
    )
    async def menu(self, interaction: discord.Interaction):
        guild = interaction.guild
        identity = get_user_identity(interaction.user.id)
        view = _menu_va(self, identity, guild)
        if not view.a_des_elements():
            await interaction.response.send_message(
                "⚠️ Aucune fonction de menu activée sur ce serveur.", ephemeral=True)
            return
        # L'identité n'est requise que si le menu contient du contenu (reel/story…).
        if _menu_feature_check(interaction, "contenu") and not identity:
            await interaction.response.send_message(
                "⚠️ Tu n'as pas d'identité assignée — demande à un admin.", ephemeral=True
            )
            return
        await interaction.response.send_message(view=view)

    @app_commands.command(
        name="serverfeatures",
        description="[OWNER] Active/désactive les fonctions du bot sur CE serveur (multi-serveurs)",
    )
    @app_commands.describe(
        contenu="Menu contenu (Reel/Story/Post/Pseudo/Name/Bio/PP)",
        onboarding="Parcours d'onboarding + bouton Ajouter un compte",
        clics="Bouton Mes clics + récap quotidien des clics",
        liens="Demander un lien + Générer le lien",
        tickets="Création automatique de ticket à l'arrivée",
        statut="Ronds 🟢/🟠/🔴 d'activité sur les salons va-",
        rappels="Rappels quotidiens (Story/Reel/CTA) + suivi des comptes",
        threads="Mode Threads : menu réduit (PP/Name/Pseudo/Clics/Lien/Comptes) + comptes threads.net",
        reset="true = enlève le bridage (ce serveur récupère TOUTES les fonctions)",
    )
    async def serverfeatures(
        self, interaction: discord.Interaction,
        contenu: bool = None, onboarding: bool = None, clics: bool = None,
        liens: bool = None, tickets: bool = None, statut: bool = None,
        rappels: bool = None, threads: bool = None, reset: bool = False,
    ):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        import guild_features as gf

        def _recap(feats, restricted):
            lines = "\n".join(f"{'✅' if f in feats else '❌'} {f}" for f in gf.ALL_FEATURES)
            head = "🔒 **Serveur bridé**" if restricted else "🌐 **Serveur non bridé** (toutes les fonctions)"
            tline = f"\n🧵 mode Threads : {'✅ ON' if gf.threads_mode(interaction.guild) else '❌ off'}"
            return f"{head} — **{interaction.guild.name}**\n{lines}{tline}"

        if reset:
            gf.clear_guild(interaction.guild)
            gf.set_threads(interaction.guild, False)
            await interaction.response.send_message(
                "✅ Bridage retiré.\n" + _recap(gf.get_features(interaction.guild), False),
                ephemeral=True)
            return
        if threads is not None:
            gf.set_threads(interaction.guild, threads)
        provided = {k: v for k, v in {
            "contenu": contenu, "onboarding": onboarding, "clics": clics,
            "liens": liens, "tickets": tickets, "statut": statut, "rappels": rappels,
        }.items() if v is not None}
        if not provided and threads is None:
            await interaction.response.send_message(
                _recap(gf.get_features(interaction.guild), gf.is_restricted(interaction.guild))
                + "\n\n_Règle avec `contenu:false`, `clics:true`, `threads:true`… ou `reset:true` pour tout réactiver._",
                ephemeral=True)
            return
        new = set(gf.get_features(interaction.guild))
        for f, v in provided.items():
            new.add(f) if v else new.discard(f)
        final = gf.set_features(interaction.guild, list(new)) if provided else gf.get_features(interaction.guild)
        await interaction.response.send_message(
            "✅ Mis à jour.\n" + _recap(final, gf.is_restricted(interaction.guild)), ephemeral=True)

    @app_commands.command(
        name="cleanva",
        description="[OWNER] Supprime TOUS les salons va- de CE serveur (avec confirmation)",
    )
    async def cleanva(self, interaction: discord.Interaction):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        chans = [ch for ch in interaction.guild.text_channels if _ch_handle_va(ch.name)]
        if not chans:
            await interaction.response.send_message(
                "Aucun salon `va-…` trouvé sur ce serveur.", ephemeral=True)
            return
        sample = ", ".join(f"`{ch.name}`" for ch in chans[:6])
        more = f" … (+{len(chans) - 6})" if len(chans) > 6 else ""
        await interaction.response.send_message(
            "⚠️ **Action irréversible.**\n"
            f"Serveur : **{interaction.guild.name}**\n"
            f"Ça va **supprimer {len(chans)} salon(s)** `va-…` : {sample}{more}\n"
            "Les **catégories** et tous les autres salons (général-, boss-, équipes…) sont **conservés**.\n\n"
            "Vérifie bien le **nom du serveur** ci-dessus, puis clique **Supprimer**.",
            view=ConfirmCleanVA(chans, interaction.user.id),
            ephemeral=True,
        )

    @app_commands.command(
        name="setvacategory",
        description="[OWNER] Catégorie d'accueil des nouveaux VAs sur CE serveur (ex: Equipe 1)",
    )
    @app_commands.describe(
        categorie="La catégorie où placer les nouveaux salons va- (ex: Equipe 1)",
        deplacer_existants="true = déplace aussi les salons va- déjà présents dans cette catégorie",
        reset="true = enlève la catégorie d'accueil (retour au classement par identité)",
    )
    async def setvacategory(
        self, interaction: discord.Interaction,
        categorie: discord.CategoryChannel = None,
        deplacer_existants: bool = False, reset: bool = False,
    ):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        import guild_features as gf
        if reset:
            gf.set_va_category(interaction.guild, None)
            await interaction.response.send_message(
                "✅ Catégorie d'accueil retirée — les nouveaux VAs sont à nouveau classés par identité.",
                ephemeral=True)
            return
        if categorie is None:
            cid = gf.get_va_category_id(interaction.guild)
            cur = interaction.guild.get_channel(cid) if cid else None
            await interaction.response.send_message(
                (f"📂 Catégorie d'accueil actuelle : **{cur.name}**" if cur
                 else "📂 Aucune catégorie d'accueil définie (classement par identité).")
                + "\n_Choisis-en une avec `categorie:` (option `deplacer_existants:true` pour ranger les VAs déjà là), ou `reset:true`._",
                ephemeral=True)
            return
        gf.set_va_category(interaction.guild, categorie.id)
        if not deplacer_existants:
            await interaction.response.send_message(
                f"✅ Les nouveaux VAs de **{interaction.guild.name}** iront dans **{categorie.name}**.",
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        moved = failed = 0
        for ch in interaction.guild.text_channels:
            if _ch_handle_va(ch.name) and ch.category_id != categorie.id:
                try:
                    await ch.edit(category=categorie, reason="setvacategory")
                    moved += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.5)
        await interaction.followup.send(
            f"✅ Nouveaux VAs → **{categorie.name}**. **{moved}** salon(s) existant(s) déplacé(s)"
            + (f" · ⚠️ {failed} échec(s) (catégorie pleine ? 50 max)." if failed else "."),
            ephemeral=True)

    @app_commands.command(
        name="setidentite",
        description="[OWNER] Identité par défaut des VAs de CE serveur (ex: jessye)",
    )
    @app_commands.describe(
        identity="Nom · 'first' = 1ère identité (historique) · 'category' · 'random' · 'none'",
        reassigner="true = met aussi cette identité aux VAs déjà présents sur le serveur",
    )
    async def setidentite(
        self, interaction: discord.Interaction,
        identity: str = None, reassigner: bool = False,
    ):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        import guild_features as gf
        if identity is None:
            cur = gf.get_server_identity(interaction.guild)
            await interaction.response.send_message(
                (f"🪪 Identité dédiée de ce serveur : **{cur}**" if cur
                 else "🪪 Aucune identité dédiée (rotation normale du marché français).")
                + "\n_Définis-en une : `identity:jessye` (+ `reassigner:true` pour les VAs déjà là). `identity:none` pour enlever._",
                ephemeral=True)
            return
        ident = identity.strip().lower()
        if ident in ("random", "aleatoire", "aléatoire", "hasard", "rotation"):
            # Mode ALÉATOIRE : aucune identité fixe (les nouveaux VAs reçoivent une
            # identité au hasard via la rotation). reassigner:true = redistribue aussi
            # les VAs DÉJÀ présents au hasard, de façon équilibrée.
            gf.set_server_identity(interaction.guild, None)
            if not reassigner:
                await interaction.response.send_message(
                    "✅ **{}** en **assignation aléatoire** : les nouveaux VAs reçoivent une "
                    "identité au hasard.\n_(`reassigner:true` pour redistribuer aussi les VAs "
                    "déjà présents.)_".format(interaction.guild.name), ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            import random as _rnd
            try:
                from cogs.welcome import list_active_identities
                idents = list_active_identities()  # exclut désactivées + jailbreak-only
            except Exception:
                idents = []
            if not idents:
                await interaction.followup.send(
                    "⚠️ Aucune identité active à distribuer. Active-en (`/toggleidentity`) "
                    "et désactive celles à exclure (ex: `alicia`).", ephemeral=True)
                return
            users = load_json(USERS_FILE, {})
            chan_ids = {ch.id for ch in interaction.guild.text_channels if _ch_handle_va(ch.name)}
            pool, changed = [], 0
            for k, data in users.items():
                if isinstance(data, dict) and data.get("channel_id") in chan_ids:
                    if not pool:  # recharge un cycle mélangé -> distribution équilibrée
                        pool = list(idents)
                        _rnd.shuffle(pool)
                    data["identity"] = pool.pop()
                    changed += 1
            save_json(USERS_FILE, users)
            await interaction.followup.send(
                f"✅ **{interaction.guild.name}** en mode **aléatoire** + **{changed}** VA(s) "
                f"redistribué(s) au hasard sur : {', '.join(sorted(idents))}.", ephemeral=True)
            return
        if ident in ("category", "categorie", "catégorie", "auto", "dossier", "categories"):
            # Assigne chaque VA selon la CATEGORIE Discord de son salon : les salons
            # sont DEJA ranges par identite (VAs sous 'Lola' -> lola, sous 'Alicia' ->
            # alicia, etc.). C'est le vrai "remettre comme avant".
            await interaction.response.defer(ephemeral=True, thinking=True)
            import re as _re_cat
            def _norm(s):
                return _re_cat.sub(r'[^a-z]', '', (s or '').lower())
            try:
                from cogs.welcome import list_identities
                valid = list_identities()
            except Exception:
                valid = []
            valid_norm = [(_norm(v), v) for v in valid]
            gf.set_server_identity(interaction.guild, None)  # enleve le "serveur = X" force
            users = load_json(USERS_FILE, {})
            chan_ident = {}
            for ch in interaction.guild.text_channels:
                if not _ch_handle_va(ch.name) or not ch.category:
                    continue
                cn = _norm(ch.category.name)
                if not cn:
                    continue
                for vn, vv in valid_norm:
                    if vn and (vn == cn or cn.startswith(vn)):
                        chan_ident[ch.id] = vv
                        break
            changed, counts = 0, {}
            for k, data in users.items():
                if isinstance(data, dict) and data.get("channel_id") in chan_ident:
                    newid = chan_ident[data["channel_id"]]
                    if data.get("identity") != newid:
                        data["identity"] = newid
                        changed += 1
                    counts[newid] = counts.get(newid, 0) + 1
            save_json(USERS_FILE, users)
            summary = ', '.join(f"{v} ×{c}" for v, c in sorted(counts.items()))
            if not summary:
                summary = "— (aucun salon VA rangé dans une catégorie identité)"
            await interaction.followup.send(
                f"✅ **{changed}** VA(s) réassigné(s) selon leur **catégorie Discord**.\n"
                f"📊 Répartition : {summary}",
                ephemeral=True)
            return
        if ident in ("first", "premiere", "première", "conv", "historique", "history", "origine", "original"):
            # Remet la PREMIERE identite de chaque VA, lue dans l'HISTORIQUE du salon :
            # le tout 1er menu du bot a un embed footer "Identité : X". Plus fiable que
            # la categorie (qui a pu bouger). Long (lit l'historique de chaque salon).
            await interaction.response.defer(ephemeral=True, thinking=True)
            import re as _re_h
            try:
                from cogs.welcome import list_identities
                valid = {n.lower() for n in list_identities()}
            except Exception:
                valid = set()
            users = load_json(USERS_FILE, {})
            chan_to_key = {}
            for k, data in users.items():
                if isinstance(data, dict) and data.get("channel_id"):
                    chan_to_key[data["channel_id"]] = k
            changed, notfound, counts = 0, 0, {}
            for ch in interaction.guild.text_channels:
                if not _ch_handle_va(ch.name):
                    continue
                key = chan_to_key.get(ch.id)
                if not key:
                    continue
                first_ident = None
                try:
                    async for msg in ch.history(limit=80, oldest_first=True):
                        texts = [msg.content or ""]
                        for emb in (msg.embeds or []):
                            if emb.footer and emb.footer.text:
                                texts.append(emb.footer.text)
                            if emb.title:
                                texts.append(emb.title)
                            if emb.description:
                                texts.append(emb.description)
                        # Le menu V2 n'a plus d'embed : son identite est une
                        # ligne de son texte (« -# Identité : `x` »). Ligne par
                        # ligne : la regex ne lit que le PREMIER « identité »
                        # d'un texte, et l'aide du menu pourrait en contenir un.
                        texts += [l for t in _textes_v2(msg) for l in t.splitlines()]
                        for t in texts:
                            # "Identité : X" OU "identité X" OU "identité `X`" (footer ou texte)
                            mm = _re_h.search(r'identit[ée]\s*[:\-—]*\s*[`*_]*([a-zA-Z]{2,})', t or "", _re_h.IGNORECASE)
                            if mm and mm.group(1).strip().lower() in valid:
                                first_ident = mm.group(1).strip().lower()
                                break
                        if first_ident:
                            break
                except Exception:
                    pass
                if first_ident:
                    if users[key].get("identity") != first_ident:
                        users[key]["identity"] = first_ident
                        changed += 1
                    counts[first_ident] = counts.get(first_ident, 0) + 1
                else:
                    notfound += 1
            save_json(USERS_FILE, users)
            gf.set_server_identity(interaction.guild, None)
            summary = ', '.join(f"{v} ×{c}" for v, c in sorted(counts.items())) or "—"
            await interaction.followup.send(
                f"✅ **{changed}** VA(s) remis à leur **1ʳᵉ identité** (lue dans l'historique du salon).\n"
                f"📊 {summary}" + (f"\n⚠️ {notfound} salon(s) sans 1er menu trouvé (gardent l'actuelle)." if notfound else ""),
                ephemeral=True)
            return
        if ident in ("sync", "syncacces", "acces", "accès", "permissions", "perms"):
            # Donne a CHAQUE VA l'acces aux salons par-identite (general-/banger-/
            # exemple-compte-X) de SA CATEGORIE Discord, et retire ceux des autres
            # identites. La CATEGORIE du salon du VA est la source de verite (ce que
            # tu vois/ranges) ; on retombe sur l'etiquette stockee si la categorie
            # n'est pas une identite reconnue. Tourne en arriere-plan (Discord
            # limite fort les modifs de permissions).
            guild = interaction.guild
            import re as _re_sync
            def _norm(s):
                return _re_sync.sub(r'[^a-z]', '', (s or '').lower())
            try:
                from cogs.welcome import list_identities
                _valid = list_identities()
            except Exception:
                _valid = []
            _valid_norm = [(_norm(v), v) for v in _valid]
            def _ident_from_category(_ch):
                if not _ch or not getattr(_ch, "category", None):
                    return None
                cn = _norm(_ch.category.name)
                if not cn:
                    return None
                for vn, vv in _valid_norm:
                    if vn and (vn == cn or cn.startswith(vn)):
                        return vv
                return None
            users = load_json(USERS_FILE, {})
            chan_ids = {ch.id for ch in guild.text_channels if _ch_handle_va(ch.name)}
            targets = []  # (member, identite_cible, source)
            for k, data in users.items():
                if not isinstance(data, dict) or data.get("channel_id") not in chan_ids:
                    continue
                try:
                    mem = guild.get_member(int(k))
                except Exception:
                    mem = None
                if not mem:
                    continue
                vch = guild.get_channel(data.get("channel_id"))
                cat_ident = _ident_from_category(vch)
                idt = cat_ident or (data.get("identity") or "").strip().lower()
                if not idt:
                    continue
                targets.append((mem, idt, "catégorie" if cat_ident else "étiquette"))
            if not targets:
                await interaction.response.send_message(
                    "Aucun VA (membre présent) à synchroniser.", ephemeral=True)
                return
            _n_cat = sum(1 for _, _, s in targets if s == "catégorie")
            await interaction.response.send_message(
                f"🔄 Sync des accès lancé pour **{len(targets)}** VA(s) "
                f"({_n_cat} via leur catégorie Discord) — en arrière-plan "
                f"(~quelques minutes, Discord limite les permissions). Je préviens ici à la fin.",
                ephemeral=True)
            _chan = interaction.channel
            _uid = interaction.user.id

            async def _sync_run():
                try:
                    from cogs.welcome import sync_general_channel_access
                except Exception:
                    return
                ok = 0
                fixed = 0          # VAs dont au moins 1 acces a change
                tot_granted = 0    # acces a la BONNE identite ajoutes
                tot_revoked = 0    # acces a une MAUVAISE identite retires
                for mem, idt, _src in targets:
                    try:
                        res = await sync_general_channel_access(guild, mem, idt)
                        ok += 1
                        if isinstance(res, tuple):
                            g, r = res
                            tot_granted += g
                            tot_revoked += r
                            if g or r:
                                fixed += 1
                    except Exception:
                        pass
                try:
                    await _chan.send(
                        f"✅ <@{_uid}> Accès aux salons d'identité **synchronisés** "
                        f"(basé sur la **catégorie** de chaque VA).\n"
                        f"• {ok}/{len(targets)} VA(s) vérifié(s)\n"
                        f"• **{fixed}** VA(s) dont l'accès a été mis à jour\n"
                        f"• {tot_granted} accès **ajouté(s)** (salons de leur catégorie), "
                        f"{tot_revoked} accès **retiré(s)** (salons d'une autre identité)")
                except Exception:
                    pass
            interaction.client.loop.create_task(_sync_run())
            return
        if ident in ("none", "aucune", "reset", ""):
            gf.set_server_identity(interaction.guild, None)
            await interaction.response.send_message(
                "✅ Identité dédiée retirée — retour à la rotation normale.", ephemeral=True)
            return
        # Une RESERVE (contenu partage) ne devient pas l'identite d'un
        # serveur : avec reassigner:true, la boucle du dessous l'ecrivait sur
        # chaque VA du serveur, et _link_identity leur generait des liens GMS
        # a son nom. Sans reassigner, le ticket l'ignore : « les nouveaux VAs
        # auront blonde » serait faux. Repli ouvert et journalise, comme
        # cogs/admin._refus_reserve.
        try:
            import type_identite as _ti
            _refus = _ti.refus_assignation(ident)
        except Exception as e:
            _refus = ""
            log.warning("setidentite : controle « reserve » indisponible pour "
                        "%r (%s: %s)", ident, type(e).__name__, e)
        if _refus:
            await interaction.response.send_message(f"❌ {_refus}", ephemeral=True)
            return
        gf.set_server_identity(interaction.guild, ident)
        if not reassigner:
            await interaction.response.send_message(
                f"✅ Les nouveaux VAs de **{interaction.guild.name}** auront l'identité **{ident}**.\n"
                "_(`reassigner:true` pour l'appliquer aussi aux VAs déjà présents.)_",
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        users = load_json(USERS_FILE, {})
        chan_ids = {ch.id for ch in interaction.guild.text_channels if _ch_handle_va(ch.name)}
        changed = 0
        for k, data in users.items():
            if isinstance(data, dict) and data.get("channel_id") in chan_ids and data.get("identity") != ident:
                data["identity"] = ident
                changed += 1
        save_json(USERS_FILE, users)
        await interaction.followup.send(
            f"✅ Identité **{ident}** pour les nouveaux VAs de **{interaction.guild.name}** "
            f"+ **{changed}** VA(s) existant(s) réassigné(s).",
            ephemeral=True)

    @app_commands.command(
        name="testidentite",
        description="[OWNER] T'assigne une identité à TOI pour la tester (réversible)",
    )
    @app_commands.describe(
        identity="Identité à t'assigner pour tester (ex: alicia). 'none' = enlever/remettre l'ancienne.",
    )
    async def testidentite(self, interaction: discord.Interaction, identity: str):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        users = load_json(USERS_FILE, {})
        entry = users.get(uid) if isinstance(users.get(uid), dict) else {}
        ident = identity.strip().lower()
        if ident in ("none", "aucune", "reset", ""):
            # Restaure l'identité d'origine si on l'avait sauvegardée, sinon enlève.
            prev = entry.pop("_test_prev_identity", None)
            if prev:
                entry["identity"] = prev
                msg = f"✅ Identité de test retirée — tu es de nouveau **{prev}**."
            else:
                entry.pop("identity", None)
                msg = "✅ Identité de test retirée."
            if entry:
                users[uid] = entry
            else:
                users.pop(uid, None)
            save_json(USERS_FILE, users)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        # Vérifie que l'identité existe (active ou non — on teste exprès une désactivée)
        try:
            from cogs.welcome import list_identities
            if ident not in [x.lower() for x in list_identities()]:
                await interaction.response.send_message(
                    f"❌ Identité `{ident}` introuvable. Crée-la d'abord (`/add`).", ephemeral=True)
                return
        except Exception:
            pass
        # Sauvegarde l'identité d'origine UNE fois (pour pouvoir revenir).
        if entry.get("identity") and "_test_prev_identity" not in entry:
            entry["_test_prev_identity"] = entry["identity"]
        entry["identity"] = ident
        users[uid] = entry
        save_json(USERS_FILE, users)
        await interaction.response.send_message(
            f"✅ Tu as maintenant l'identité **{ident}** (mode test).\n"
            f"Utilise `/menu`, `/reel`, `/username`, « Demander un lien »… → ça te sert le contenu de **{ident}** "
            f"(même si elle est désactivée).\n"
            f"_Pour revenir en arrière : `/testidentite identity:none`._",
            ephemeral=True)

    @app_commands.command(
        name="gmsdebug",
        description="[OWNER] Diagnostic GMS : outils API + team_id + recherche template",
    )
    @app_commands.describe(shortcode="Template à chercher (ex: templatethreads)")
    async def gmsdebug(self, interaction: discord.Interaction, shortcode: str = ""):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ GMS indispo : {e}", ephemeral=True)
            return
        lines = []
        # 1) Outils MCP exposés (pour voir s'il existe un list_teams/workspaces)
        t = await asyncio.to_thread(gms.list_tools)
        if t.get("ok"):
            lines.append("**Outils GMS** : " + ", ".join(x["name"] for x in t["tools"])[:600])
        else:
            lines.append(f"⚠️ list_tools : {t.get('error')}")
        # 2) Liens du workspace par défaut : team_id vus + recherche du template
        allr = await asyncio.to_thread(gms.list_all_links)
        if allr.get("ok"):
            links = allr.get("links") or []
            lines.append(f"**{len(links)} liens** (workspace par défaut).")
            tids = sorted({str(l.get("team_id") or l.get("teamId") or "") for l in links if (l.get("team_id") or l.get("teamId"))})
            if tids:
                lines.append("**team_id vus** : " + ", ".join(f"`{x}`" for x in tids))
            sc = (shortcode or "templatethread").lower()
            hits = [l for l in links if sc in (str(l.get("shortcode") or "") + " " + str(l.get("display_name") or "")).lower()]
            if hits:
                for h in hits[:4]:
                    lines.append(f"🔎 `{h.get('shortcode')}` · id=`{h.get('id')}` · team=`{h.get('team_id') or h.get('teamId') or '(perso)'}`")
            else:
                lines.append(f"❌ aucun lien `{sc}` dans le workspace par défaut (sûrement dans Threads US).")
        else:
            lines.append(f"⚠️ list_links : {allr.get('error')}")
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    @app_commands.command(
        name="settemplate",
        description="[OWNER] Définit le template GMS à dupliquer pour une identité",
    )
    @app_commands.describe(
        identity="Identité (ex: hybride)",
        shortcode="Shortcode du template (ex: templatethreads)",
    )
    async def settemplate(self, interaction: discord.Interaction, identity: str, shortcode: str):
        app = await interaction.client.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ident = identity.strip().lower()
        sc = shortcode.strip().lstrip("/").lower()
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ GMS indispo : {e}", ephemeral=True)
            return
        # Cherche le lien template dans tous les workspaces connus + le workspace par défaut
        sources = [("défaut", lambda: gms.list_all_links())]
        for tid in getattr(gms, "KNOWN_TEAMS", ()):
            sources.append((tid, (lambda t=tid: gms.list_links_team(t))))
        # Collecte tous les liens (avec leur workspace) en une passe
        all_pairs = []  # (workspace_label, link)
        for label, fn in sources:
            try:
                r = await asyncio.to_thread(fn)
            except Exception:
                continue
            if not r.get("ok"):
                continue
            for l in (r.get("links") or []):
                all_pairs.append((label, l))

        def _norm(s):
            # Tolérant aux inversions de lettres (threads/therads) et espaces
            return "".join(sorted((s or "").lower().replace(" ", "").replace("_", "")))
        sc_norm = _norm(sc)
        link = None
        seen_ws = ""
        # Tier 1 : sous-chaîne dans le shortcode | Tier 2 : dans le display_name
        # Tier 3 : fuzzy (mêmes lettres, ordre ignoré -> tolère les fautes de frappe)
        for matcher in (
            lambda l: sc in str(l.get("shortcode") or "").lower(),
            lambda l: sc in str(l.get("display_name") or "").lower(),
            lambda l: sc_norm and sc_norm == _norm(str(l.get("shortcode") or "")),
            lambda l: sc_norm and sc_norm == _norm(str(l.get("display_name") or "")),
        ):
            for label, l in all_pairs:
                if matcher(l):
                    link, seen_ws = l, label
                    break
            if link:
                break
        if not link or not link.get("id"):
            # Diagnostic : montre les vrais shortcodes pour qu'on voie l'orthographe exacte
            listing = []
            for label, l in all_pairs[:25]:
                listing.append(f"• `{l.get('shortcode')}` ({l.get('display_name') or '?'}) — {label}")
            body = "\n".join(listing) if listing else "(aucun lien trouvé dans les workspaces)"
            await interaction.followup.send(
                f"❌ Template `{sc}` introuvable.\n**Voici les vrais shortcodes existants** "
                f"(copie l'orthographe exacte) :\n{body}"[:1900],
                ephemeral=True)
            return
        try:
            gms.set_template_for_model(ident, link["id"])
        except Exception as e:
            await interaction.followup.send(f"❌ Échec config : {e}", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Template de **{ident}** = `{link.get('shortcode')}` (id `{link['id']}`, workspace `{seen_ws}`).\n"
            f"→ Les liens générés pour {ident} dupliqueront ce template.",
            ephemeral=True)

    @app_commands.command(name="help", description="Affiche l'aide")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📚 Aide — Commandes du bot",
            color=discord.Color.blurple(),
            description=(
                "**Commandes VA :**\n"
                "`/username` — un username Instagram de ton identité\n"
                "`/bio` — une bio Instagram de ton identité\n"
                "`/profilepic` — une photo de profil (pool partagé)\n"
                "`/reel` — un reel de ton identité + sa caption associée\n"
                "`/help` — cette aide\n\n"
                "**Onboarding :** suis les étapes dans ton salon (boutons →)."
            ),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _insta_handle_check(raw: str):
    """Normalise un pseudo/lien Instagram + VERIFIE qu'il existe (via RapidAPI).
    Retourne (username, status) ; status: 'ok'|'notfound'|'invalid'|'unknown'|'empty'."""
    import re as _re_i
    s = (raw or "").strip()
    if not s:
        return ("", "empty")
    m = _re_i.search(r'(?:instagram\.com|instagr\.am|threads\.net)/@?([A-Za-z0-9_.]+)', s, _re_i.IGNORECASE)
    if m:
        u = m.group(1)
    else:
        u = s.lstrip("@").strip().rstrip("/").split("/")[-1].split("?")[0]
    u = _re_i.sub(r'[^A-Za-z0-9_.]', '', u)
    if not u:
        return (s[:40], "invalid")
    try:
        from insta_scraper import load_auth
        auth = load_auth()
        key = (auth.get("rapidapi_key") or "").strip()
        if not key:
            return (u, "unknown")  # pas de cle -> on accepte sans pouvoir verifier
        host = (auth.get("rapidapi_host") or "instagram-scraper-stable-api.p.rapidapi.com").strip()
        import requests
        r = requests.post(
            f"https://{host}/ig_get_fb_profile_v3.php",
            headers={"x-rapidapi-key": key, "x-rapidapi-host": host,
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"username_or_url": u}, timeout=12,
        )
        body = r.text.lower()
        if "does not exist" in body or "invalid or missing" in body:
            return (u, "notfound")
        try:
            d = r.json()
        except Exception:
            return (u, "unknown")

        def _has_pk(o, dep=0):
            if dep > 6:
                return False
            if isinstance(o, dict):
                if o.get("pk") or o.get("id") or o.get("username"):
                    return True
                return any(_has_pk(v, dep + 1) for v in o.values())
            if isinstance(o, list):
                return any(_has_pk(x, dep + 1) for x in o)
            return False
        return (u, "ok" if _has_pk(d) else "notfound")
    except Exception:
        return (u, "unknown")


class MesComptesInstaModal(discord.ui.Modal, title="📷 Mes comptes Instagram"):
    """Saisie des 3 comptes Insta du VA, avec validation d'existence en direct."""
    insta1 = discord.ui.TextInput(label="Insta 1", placeholder="@pseudo ou lien insta", required=False, max_length=150)
    insta2 = discord.ui.TextInput(label="Insta 2", placeholder="@pseudo ou lien insta", required=False, max_length=150)
    insta3 = discord.ui.TextInput(label="Insta 3", placeholder="@pseudo ou lien insta", required=False, max_length=150)

    def __init__(self, prefill=None):
        super().__init__()
        pf = [x for x in (prefill or []) if isinstance(x, str)]
        if len(pf) > 0:
            self.insta1.default = pf[0]
        if len(pf) > 1:
            self.insta2.default = pf[1]
        if len(pf) > 2:
            self.insta3.default = pf[2]

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        raws = [(1, self.insta1.value), (2, self.insta2.value), (3, self.insta3.value)]
        lines, valid = [], []
        for i, raw in raws:
            if not (raw or "").strip():
                continue
            u, status = _insta_handle_check(raw)
            if status == "ok":
                lines.append(f"✅ **Insta {i}** — [@{u}](https://instagram.com/{u}) : compte trouvé")
                valid.append(u)
            elif status == "notfound":
                lines.append(f"❌ **Insta {i}** — @{u} : **compte introuvable** (vérifie le @ / le lien)")
            elif status == "invalid":
                lines.append(f"❌ **Insta {i}** — `{(raw or '')[:40]}` : **@ ou lien invalide**")
            else:  # unknown : pas pu vérifier (clé API absente / souci réseau)
                lines.append(f"➕ **Insta {i}** — @{u} : ajouté (pas pu vérifier l'existence)")
                valid.append(u)
        if not lines:
            await interaction.followup.send("⚠️ Tu n'as rempli aucun champ.", ephemeral=True)
            return
        enregistre = False
        if valid:
            try:
                users = load_json(USERS_FILE, {})
                k = str(interaction.user.id)
                entry = users.get(k)
                if not isinstance(entry, dict):
                    # Fiche au format ANCIEN (users.json[uid] = "julia") : la
                    # remplacer par {} effacait l'identite du VA, qui se
                    # retrouvait sans contenu apres un simple clic sur
                    # « Mes comptes Insta ». On la conserve (meme reprise que
                    # _store_payment).
                    entry = {"identity": entry} if isinstance(entry, str) and entry else {}
                    users[k] = entry
                existing = [x for x in (entry.get("insta_accounts") or []) if isinstance(x, str)]
                low = [e.lower() for e in existing]
                for u in valid:
                    if u.lower() not in low:
                        existing.append(u)
                        low.append(u.lower())
                entry["insta_accounts"] = existing
                enregistre = bool(save_json(USERS_FILE, users))
            except Exception as e:
                print(f"[user] enregistrement comptes insta échoué : {e}", flush=True)
                enregistre = False
        # Ne JAMAIS annoncer « enregistré » sans l'avoir ecrit : le VA repartait
        # en croyant ses comptes connus alors que rien n'etait sauvegarde.
        if valid and enregistre:
            fin = "\n\n_Comptes valides enregistrés ✅ (visibles dans « Mes comptes Insta »)_"
        elif valid:
            fin = ("\n\n⚠️ **Impossible d'enregistrer** tes comptes pour l'instant "
                   "(erreur d'écriture). Réessaie, et préviens un admin si ça persiste.")
        else:
            fin = ""
        await interaction.followup.send(
            "📷 **Validation de tes comptes Instagram :**\n\n" + "\n".join(lines) + fin,
            ephemeral=True)


#: Le dernier menu de brutes ouvert par chaque personne.
#:
#: Un message ephemere ne disparait pas quand on en ouvre un autre : le
#: proprietaire se retrouvait avec le menu de « ibenhaastrup » et celui de
#: « themikkiangel » empiles dans le meme salon, tous deux cliquables. On
#: efface donc le precedent a l ouverture du suivant.
#:
#: Un dictionnaire suffit : une entree par personne, remplacee a chaque
#: ouverture. Il ne grossit pas avec le temps.
_DERNIER_MENU_BRUTES = {}


async def _fermer_menu_brutes(user_id):
    """Efface le menu de brutes encore ouvert par cette personne, s il y en a.

    Ne leve jamais : le message a peut-etre deja ete rejete a la main, ou son
    jeton d interaction a expire. Dans les deux cas il n y a plus rien a
    fermer, et echouer ici empecherait d ouvrir le nouveau.
    """
    ancien = _DERNIER_MENU_BRUTES.pop(int(user_id or 0), None)
    if ancien is None:
        return
    try:
        await ancien.delete()
    except Exception:
        pass


#: Le dernier panneau Jailbreak ouvert par chaque personne.
#:
#: MEME DEFAUT QUE LE MENU DES BRUTES, ET IL AVAIT ETE CORRIGE LA SEULEMENT.
#: Choisir une model POSTE un nouveau panneau ephemere ; un ephemere ne
#: disparait pas quand on en ouvre un autre. Les panneaux s'empilaient donc
#: dans le salon, tous cliquables, chacun gardant SA model et SA quantite --
#: et un clic sur un ancien servait l'ancienne identite. C'est le melange
#: d'identites constate le 05/09/2026.
_DERNIER_PANNEAU_JB = {}


async def _fermer_panneau_jb(user_id):
    """Efface le panneau Jailbreak encore ouvert par cette personne.

    Ne leve jamais : le message a peut-etre deja ete rejete a la main, ou son
    jeton d'interaction a expire. Dans les deux cas il n'y a plus rien a
    fermer, et echouer ici empecherait d'ouvrir le nouveau.
    """
    ancien = _DERNIER_PANNEAU_JB.pop(int(user_id or 0), None)
    if ancien is None:
        return
    try:
        await ancien.delete()
    except Exception:
        pass


#: Ce que montre le panneau EPINGLE de chaque salon US : {salon: (model, qte)}.
#:
#: Les sous-menus de famille (« 💬 Caption ▸ »…) sont des ephemeres ARRETES
#: (_vue_sans_suivi) : ils n'expirent jamais et restent cliquables. Quand le
#: VA passe le panneau de Lola a Julia, l'ancien sous-menu garde
#: « jbus:a:lola:… » dans ses boutons, et un clic servait Lola dans le
#: -content pendant que le panneau affichait Julia -- le melange d'identites
#: du 05/09/2026, reintroduit par le chemin US. Avant les sous-menus, toutes
#: les variantes etaient sur le panneau epingle, qui suit toujours la model.
#: En memoire seulement : apres un redemarrage l'etat est inconnu, et on ne
#: refuse RIEN (un refus sans savoir bloquerait un VA pour rien).
_JB_PANNEAU_COURANT = {}

#: Le dernier sous-menu de famille ouvert par chaque personne :
#: {user_id: (salon_id, message)}. Pour l'effacer quand un autre s'ouvre ou
#: quand le panneau change de model ou de quantite -- tant que le jeton de
#: l'interaction (15 min) le permet ; au-dela, le refus de JBActionButton
#: prend le relais.
_JB_SOUS_MENUS = {}


def _jb_panneau_noter(chan_id, ident, qty):
    """Retient ce que montre desormais le panneau epingle du salon.

    `ident` None : l'etat devient INCONNU (on l'oublie) plutot que faux --
    par exemple quand c'est le panneau de secours, envoye en ephemere, qui a
    change, et non celui que le salon voit.
    """
    cid = int(chan_id or 0)
    if not cid:
        return
    if ident is None:
        _JB_PANNEAU_COURANT.pop(cid, None)
    else:
        _JB_PANNEAU_COURANT[cid] = ((ident or "").lower(), int(qty))


def _jb_est_panneau_epingle(interaction) -> bool:
    """Le message de ce clic est-il le panneau ENREGISTRE du salon ?"""
    cid = int(getattr(getattr(interaction, "channel", None), "id", 0) or 0)
    mid = int(getattr(getattr(interaction, "message", None), "id", 0) or 0)
    epingle = _jb_panel_ids().get(str(cid)) if cid else None
    return bool(cid and mid and epingle and int(epingle) == mid)


async def _jb_sous_menus_fermer(user_id=None, channel_id=None):
    """Efface les sous-menus de famille d'une personne ou d'un salon.

    Ne leve jamais : un ephemere deja rejete, ou dont le jeton a expire, n'a
    plus rien a effacer -- et echouer ici empecherait d'ouvrir le suivant.
    Rend le nombre de messages effaces.
    """
    if user_id is None and channel_id is None:
        return 0
    n = 0
    for uid, (cid, msg) in list(_JB_SOUS_MENUS.items()):
        if user_id is not None and uid != int(user_id):
            continue
        if channel_id is not None and cid != int(channel_id):
            continue
        _JB_SOUS_MENUS.pop(uid, None)
        try:
            await msg.delete()
            n += 1
        except Exception:
            pass
    return n


def _jb_sous_menu_perime(interaction, ident, qty, panneau=False) -> str:
    """Le refus a opposer au clic d'un sous-menu PERIME, "" sinon.

    Seulement pour un message ephemere (le panneau epingle, lui, est
    toujours a jour) et seulement si l'etat du panneau est connu.

    `panneau=True` : le clic vient d'un panneau de SECOURS (ephemere, V2),
    pas d'un ancien sous-menu -- il n'y a pas de « ▸ » a recliquer, la
    phrase renvoie au panneau epingle.
    """
    msg = getattr(interaction, "message", None)
    if not getattr(getattr(msg, "flags", None), "ephemeral", False):
        return ""
    cid = int(getattr(getattr(interaction, "channel", None), "id", 0) or 0)
    etat = _JB_PANNEAU_COURANT.get(cid)
    if not etat:
        return ""
    m, q = etat
    quoi = "Ce panneau" if panneau else "Ce sous-menu"
    suite = ("sers-toi du panneau épinglé du salon." if panneau else
             "reclique ▸ sur le panneau pour avoir les bons boutons.")
    if m != (ident or "").lower():
        return (f"⚠️ {quoi} est pour **{(ident or '?').capitalize()}**, ton "
                f"panneau est passé sur **{m.capitalize()}** : {suite}")
    if int(q) != int(qty):
        return (f"⚠️ {quoi} est réglé sur **{qty}** média(s), ton panneau "
                f"sur **{q}** : "
                + ("sers-toi du panneau épinglé du salon." if panneau
                   else "reclique ▸ sur le panneau."))
    return ""


async def _poser_panneau_jb(interaction, view):
    """Ouvre un panneau Jailbreak en fermant le precedent.

    Le handle du message est garde pour pouvoir l'eteindre : un ephemere
    envoye par send_message ne rend rien, il faut le redemander par
    original_response().
    """
    await _fermer_panneau_jb(interaction.user.id)
    # Un panneau « Components V2 » (LayoutView) : pas d'embed, tout le texte
    # est dans la vue. discord.py pose lui-meme le drapeau du format.
    await interaction.response.send_message(view=view, ephemeral=True)
    try:
        view.message = await interaction.original_response()
        _DERNIER_PANNEAU_JB[int(interaction.user.id)] = view.message
    except Exception:
        # Sans handle on ne pourra pas l'eteindre, mais le panneau fonctionne.
        # Mieux vaut un panneau non eteignable qu'une commande qui echoue.
        view.message = None


def _vers_content(interaction):
    """Rend une interaction dont les envois partent dans le salon -content.

    Les boutons du panneau Jailbreak passent par _run_for_model, qui fait deja
    ce travail. Un clic dans une VUE, lui, produit une interaction neuve :
    sans ce passage, la video se deverse dans le salon -menu, qui est cense
    rester vierge.

    Hors serveur US, ou si aucun -content n est identifiable, on rend
    l interaction telle quelle : mieux vaut publier dans le salon courant que
    ne rien publier du tout.
    """
    try:
        import guild_features as gf
        if not gf.is_us_guild(getattr(interaction, "guild", None)):
            return interaction
        cible = _us_content_target(interaction)
        if cible is None:
            return interaction
        if cible.id == getattr(interaction.channel, "id", None):
            return interaction
        return _JBRedirect(interaction, cible)
    except Exception:
        return interaction


class CaptionLibreModal(discord.ui.Modal, title="Ta caption"):
    """La fenetre ou le VA ecrit son propre texte.

    Elle existe parce que la bibliotheque de captions ne couvre pas tout : un
    rush precis appelle parfois une phrase qui n y est pas, et obliger le VA a
    demander a un admin de l ajouter pour un seul post revient a ne pas la lui
    donner.
    """

    texte = discord.ui.TextInput(
        label="Le texte à incruster sur la vidéo",
        style=discord.TextStyle.paragraph,
        placeholder="ex : POV : tu découvres mon compte…",
        required=True, max_length=300)

    description = discord.ui.TextInput(
        label="Description (champ légende) — facultatif",
        style=discord.TextStyle.paragraph,
        required=False, max_length=1500)

    def __init__(self, cog, identity, video):
        super().__init__()
        self.cog = cog
        self.identity = identity
        self.video = video

    async def on_submit(self, interaction: discord.Interaction):
        cap = {"id": "libre", "text": str(self.texte.value or "").strip(),
               "desc": str(self.description.value or "").strip(),
               "x": 0.5, "y": 0.3}
        if not cap["text"]:
            await interaction.response.send_message(
                "Texte vide : rien à incruster.", ephemeral=True)
            return
        await interaction.response.defer()
        # La caption ecrite a la main N EST PAS mise en reserve : elle ne
        # servira qu une fois, et une recette a usage unique encombrerait le
        # stock sans jamais etre reprise. D ou l absence de « famille ».
        await self.cog._gen_and_send_caption(
            _vers_content(interaction), self.video, cap,
            _captions_block(self.identity),
            1, 1, self.identity, label="BRUTE + TA CAPTION", emoji="✍️",
            prefixe_fichier="brute_caption")


class ChoixCaptionView(discord.ui.View):
    """Une fois la brute choisie : avec quelle caption ?

    Trois voies, et c est voulu :
      - telle quelle, sans rien incruster — le comportement d avant ;
      - une caption de la bibliotheque, incrustee par le moteur ;
      - la sienne, tapee sur le moment.

    Le VA revient toujours au menu des brutes : il peut donc prendre la meme
    brute deux fois avec deux captions differentes, ce que « ⭐ Video brut » ne
    permettait pas.
    """

    def __init__(self, cog, identity, video):
        super().__init__(timeout=600)
        self.cog = cog
        self.identity = identity
        self.video = video

        block = _captions_block(identity)
        items = [c for c in (block.get("items") or [])
                 if c.get("enabled", True) and str(c.get("text") or "").strip()]
        self.captions = items[:25]          # Discord plafonne un menu a 25
        if self.captions:
            options = []
            for i, c in enumerate(self.captions):
                apercu = str(c.get("text") or "").strip().replace("\n", " ")
                options.append(discord.SelectOption(
                    label=apercu[:95] or "(vide)", value=str(i)))
            select = discord.ui.Select(
                placeholder="Choisir une caption de la bibliothèque",
                options=options, row=0)
            select.callback = self._caption_choisie
            self.add_item(select)

        brut = discord.ui.Button(label="Telle quelle", emoji="🎥",
                                 style=discord.ButtonStyle.secondary, row=1)
        brut.callback = self._sans_caption
        self.add_item(brut)

        libre = discord.ui.Button(label="Écrire la mienne", emoji="✍️",
                                  style=discord.ButtonStyle.primary, row=1)
        libre.callback = self._ecrire
        self.add_item(libre)

    async def _sans_caption(self, interaction):
        await interaction.response.defer()
        interaction = _vers_content(interaction)
        _c, desc, _e = _video_meta(self.video)
        # Meme traitement que « Video brut » : cette brute part NUE, elle doit
        # donc sortir avec la meme empreinte reecrite. Elle partait telle
        # quelle depuis le disque -- l uniquification etait allumee et ne
        # s appliquait pas ici, sans un mot.
        import tempfile as _tmp
        try:
            with _tmp.TemporaryDirectory(prefix="brutmeta_") as _d:
                fichier, _reecrit, _raison = await brute_a_envoyer(
                    self.video, _d, self.identity)
                _av = ("\n⚠️ _Elle n a **pas** pu etre rendue unique — ne la "
                       "poste pas telle quelle, previens un admin._"
                       if _raison else "")
                await interaction.followup.send(
                    content=("🎥 **BRUTE CHOISIE** (`%s`) — sans montage.%s"
                             % (self.identity, _av)),
                    file=discord.File(str(fichier),
                                      filename=self.video.name),
                    ephemeral=False)
        except discord.HTTPException as e:
            await interaction.followup.send(
                "⚠️ Envoi impossible (trop lourde) : %s" % e, ephemeral=True)
            return
        if desc:
            await interaction.followup.send(
                "📄 **DESCRIPTION** (champ légende) :\n```\n%s\n```"
                % str(desc)[:1800], ephemeral=False)

    async def _ecrire(self, interaction):
        await interaction.response.send_modal(
            CaptionLibreModal(self.cog, self.identity, self.video))

    async def _caption_choisie(self, interaction):
        try:
            rang = int(interaction.data["values"][0])
            cap = self.captions[rang]
        except Exception:
            await interaction.response.send_message("Choix illisible.",
                                                    ephemeral=True)
            return
        await interaction.response.defer()
        # Pas de « famille » : ce couple brute+caption est choisi a la main,
        # il ne correspond a aucune recette que la reserve prepare d avance.
        await self.cog._gen_and_send_caption(
            _vers_content(interaction), self.video, cap,
            _captions_block(self.identity),
            1, 1, self.identity, label="BRUTE + CAPTION", emoji="💬",
            prefixe_fichier="brute_caption")


#: Les 20 derniers passages de brute_a_envoyer. En MEMOIRE seulement : ca sert
#: a repondre a « qu est-ce qui s est passe au dernier envoi ? », pas a tenir un
#: historique. Sans ca, un envoi non reecrit ne laissait qu une ligne sur la
#: sortie standard du serveur — que personne ne lit — et la seule facon de le
#: savoir etait de recuperer le fichier sur Discord et de lire ses proprietes.
_JOURNAL_BRUTES = __import__("collections").deque(maxlen=20)


#: Reprises en mode complet. Le re-encodage echoue par intermittence (mesure :
#: 1 fois sur 8), et il echoue vite — reessayer coute une seconde, laisser
#: partir la brute inchangee coute un doublon publie.
_BRUTE_ESSAIS = 3

#: Plafond vise pour une brute re-encodee. Discord refuse au-dela de 10 Mo sur
#: un serveur non boosté ; on garde de la marge pour le son et le conteneur.
_PLAFOND_DISCORD_MO = 8.5

#: Combien de trends part un clic. Le stock est petit par definition —
#: ce sont LES meilleures — et en envoyer dix reviendrait a les banaliser.
_TRENDS_PAR_ENVOI = 3


def _noter_brute(fichier, identity, actif, reecrit, raison, mode=""):
    try:
        _JOURNAL_BRUTES.append({
            "t": int(__import__("time").time()),
            "fichier": str(fichier)[:80],
            "identite": str(identity or "")[:40],
            "actif": bool(actif),
            "reecrit": bool(reecrit),
            "mode": str(mode or "")[:14],
            "raison": str(raison or "")[:140],
        })
    except Exception:
        pass          # un journal perdu ne doit jamais rater un envoi


def journal_brutes():
    """Le journal, du plus recent au plus ancien."""
    return list(_JOURNAL_BRUTES)[::-1]


async def brute_a_envoyer(video, dossier, identity=""):
    """(fichier a envoyer, metadonnees reecrites ?) pour UNE brute.

    Un seul endroit decide, parce qu il y a PLUSIEURS boutons qui envoient une
    brute nue : « Video brut », « Video brut Banger », et « Telle quelle » au
    bout de « Choisir ma brute ». Ce dernier envoyait le fichier tel qu il est
    sur le disque -- l uniquification etait allumee et ne s appliquait pas la,
    sans un mot. C est exactement ce qui se voyait : la video partait
    instantanement, comme un simple envoi de fichier.

    L interrupteur « Uniquification video » du site est lu ICI. Eteint, on rend
    le fichier d origine et rien ne se passe.

    On ne croit pas le booleen sur parole : le fichier de sortie doit exister
    ET peser quelque chose. Un ffmpeg qui rend 0 en laissant un fichier vide,
    c est arrive.

    Demandee mais pas appliquee (ffmpeg absent ou en echec) : la video part
    quand meme -- un envoi ne doit pas s arreter pour ca -- et la ligne va au
    JOURNAL du serveur. Muet pour le VA, visible pour qui administre.
    """
    import asyncio as _aio
    video = Path(video)
    cfg = load_transform_config()
    if not bool(cfg.get("enabled", False)):
        _noter_brute(video.name, identity, False, False, "interrupteur coupe", "")
        return video, False, ""

    # Le MODE vient de la page (menu « Mode »), pas d une constante ici.
    # - metadonnees seules : l image ne bouge pas. Suffit si le VA MONTE la
    #   brute derriere, puisque le montage deplacera l empreinte visuelle.
    # - complet : les filtres bougent l image. Indispensable si le VA POSTE la
    #   brute telle quelle — Instagram compare ce qu on voit, et des
    #   metadonnees ne changent rien a ce qu on voit.
    complet = not bool(cfg.get("metadata_only", True))
    moteur = transform_full_strict if complet else transform_metadata_strict
    mode = "complet" if complet else "metadonnees"

    # Le re-encodage echoue par intermittence (mesure : 1 fois sur 8, et il
    # echoue vite). Une seule tentative laissait donc partir une brute sur huit
    # sans rien changer — et comme le VA la poste telle quelle, c est un
    # doublon publie. On reessaie ; chaque tentative retire ses propres des.
    essais = _BRUTE_ESSAIS if complet else 1
    sortie = Path(dossier) / video.name
    detail = ""
    # Le re-encodage gonfle le fichier (debit configure a 5000-6000 kbps) : une
    # brute de 40 s sortirait a 27 Mo, au-dela de ce que Discord accepte, et le
    # VA ne recevrait RIEN. On borne le debit pour que la sortie tienne.
    kw = {"plafond_mo": _PLAFOND_DISCORD_MO} if complet else {}
    for tour in range(essais):
        # ffmpeg segfaute par intermittence sur la chaine de filtres (~1 fois
        # sur 8, en une seconde). « -filter_threads 1 » l en empeche mais rend
        # 2,6x plus lentement : on garde la vitesse pour les deux premieres
        # tentatives, et on ne paie le mode sur que si elles ont echoue.
        if complet:
            kw["mono_thread"] = (tour >= essais - 1)
        try:
            if sortie.exists():
                sortie.unlink()
        except OSError:
            pass
        try:
            ok = await _aio.to_thread(lambda: moteur(video, sortie, **kw))
        except Exception as e:                  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"[:120]
        if ok and sortie.exists() and sortie.stat().st_size > 0:
            _noter_brute(video.name, identity, True, True, "", mode)
            return sortie, True, ""

    raison = detail or (f"ffmpeg a echoue {essais} fois de suite" if essais > 1
                        else "ffmpeg a echoue")
    print(f"[brutes] {identity or '?'} / {video.name} : uniquification "
          f"demandee ({mode}), NON appliquee ({raison})")
    _noter_brute(video.name, identity, True, False, raison, mode)
    return video, False, raison


class ChoixBrutesView(discord.ui.View):
    """Le VA regarde ses brutes etoilees et prend celles qu il veut.

    POURQUOI CE BOUTON EXISTE
        « Video brut » lui en envoie trois au hasard. Quand une seule
        l interesse vraiment, il recoit deux videos qu il ne postera pas et il
        doit recliquer en esperant tomber sur la bonne. Ici il VOIT, puis il
        choisit.

    COMMENT IL VOIT
        Discord ne sait pas montrer une video qu il n a pas recue, et
        televerser douze rushs pour qu il en regarde douze couterait plus de
        temps qu il n en gagne. On lui envoie donc UNE planche-contact : une
        image ou chaque brute occupe une case numerotee. Les vignettes sont
        fabriquees une fois puis gardees a cote des videos, donc la deuxieme
        ouverture est instantanee.

    EPHEMERE, ET IL PEUT EN PRENDRE PLUSIEURS
        Le menu n est visible que par lui et disparait quand il quitte. La
        video choisie, elle, est postee normalement : c est ce qu il vient
        chercher, elle doit rester. Le menu reste ouvert pour qu il en prenne
        une autre sans tout recommencer.
    """

    #: Aligne sur vignettes.PAR_PLANCHE : la page du menu et la planche
    #: doivent montrer EXACTEMENT les memes brutes, sinon le numero lu sur
    #: l image ne designe pas la ligne choisie dans le menu.
    PAR_PAGE = 20

    #: Court, volontairement. Un menu laisse ouvert apres un changement de
    #: model continue de proposer les brutes de l ANCIENNE identite : le
    #: proprietaire l a constate. On le laisse donc mourir vite, et on le dit.
    DUREE_S = 180

    def __init__(self, cog, identity, brutes, page=0):
        super().__init__(timeout=self.DUREE_S)
        self.message = None
        self.cog = cog
        self.identity = identity
        self.brutes = list(brutes)
        self.page = page
        self._poser()

    # -- construction ------------------------------------------------------

    async def on_timeout(self):
        """Eteint le menu au lieu de le laisser mentir.

        Un menu ephemere ne disparait pas tout seul : sans ca, celui d une
        identite abandonnee reste cliquable dans la conversation et sert les
        brutes d une autre.
        """
        for item in self.children:
            item.disabled = True
        # Il ne doit plus etre ferme deux fois : le registre ne garde que les
        # menus encore vivants.
        for cle, msg in list(_DERNIER_MENU_BRUTES.items()):
            if msg is self.message:
                _DERNIER_MENU_BRUTES.pop(cle, None)
        try:
            if self.message is not None:
                await self.message.edit(
                    content=("⏳ Menu expiré (identité `%s`). Relance "
                             "**🎛️ Choisir ma brute**." % self.identity),
                    attachments=[], view=self)
        except Exception:
            pass

    def _tranche(self):
        debut = self.page * self.PAR_PAGE
        return self.brutes[debut:debut + self.PAR_PAGE]

    def _pages(self):
        return max(1, (len(self.brutes) + self.PAR_PAGE - 1) // self.PAR_PAGE)

    def _poser(self):
        self.clear_items()
        tranche = self._tranche()
        options = []
        depart = self.page * self.PAR_PAGE
        for i, b in enumerate(tranche, start=1):
            # Le libelle porte le NUMERO de la planche : c est par lui que le
            # VA fait le lien entre ce qu il voit et ce qu il choisit. Le nom
            # de fichier ne lui dit rien, mais il aide a distinguer deux rushs
            # qui se ressemblent.
            nom = b.name
            if len(nom) > 60:
                nom = nom[:57] + "..."
            options.append(discord.SelectOption(
                label="%d — %s" % (depart + i, nom[:90]), value=str(i - 1)))
        if options:
            select = discord.ui.Select(
                placeholder="Laquelle veux-tu ?", options=options, row=0)
            select.callback = self._choisir
            self.add_item(select)

        if self._pages() > 1:
            prec = discord.ui.Button(label="◀", row=1,
                                     disabled=(self.page == 0))
            prec.callback = self._precedente
            self.add_item(prec)
            suiv = discord.ui.Button(
                label="▶", row=1,
                disabled=(self.page >= self._pages() - 1))
            suiv.callback = self._suivante
            self.add_item(suiv)

    def _planche_et_texte(self):
        import vignettes
        tranche = self._tranche()
        vignettes.prechauffer(tranche)
        image = vignettes.planche(tranche, depart=self.page * self.PAR_PAGE)
        texte = ("⭐ **%d brute(s) étoilée(s)** pour `%s`"
                 % (len(self.brutes), self.identity))
        if self._pages() > 1:
            texte += "  ·  page %d/%d" % (self.page + 1, self._pages())
        texte += "\nRegarde les numéros, puis choisis dans le menu. "
        texte += "Tu peux en prendre plusieurs."
        fichier = None
        if image:
            import io
            fichier = discord.File(io.BytesIO(image), filename="brutes.jpg")
        return texte, fichier

    # -- reactions ---------------------------------------------------------

    async def _rafraichir(self, interaction):
        self._poser()
        texte, fichier = self._planche_et_texte()
        try:
            if fichier is not None:
                await interaction.response.edit_message(
                    content=texte, attachments=[fichier], view=self)
            else:
                await interaction.response.edit_message(content=texte, view=self)
        except Exception:
            pass

    async def _precedente(self, interaction):
        self.page = max(0, self.page - 1)
        await self._rafraichir(interaction)

    async def _suivante(self, interaction):
        self.page = min(self._pages() - 1, self.page + 1)
        await self._rafraichir(interaction)

    async def _choisir(self, interaction):
        try:
            rang = int(interaction.data["values"][0])
        except Exception:
            await interaction.response.send_message("Choix illisible.",
                                                    ephemeral=True)
            return
        tranche = self._tranche()
        if not (0 <= rang < len(tranche)):
            await interaction.response.send_message(
                "Cette vidéo n'est plus dans la liste.", ephemeral=True)
            return
        video = tranche[rang]

        # On ne l envoie pas encore : il peut vouloir une caption dessus. Le
        # menu des brutes reste ouvert derriere, donc il pourra revenir en
        # prendre une autre — ou la meme avec un autre texte.
        await interaction.response.send_message(
            content=("🎥 Brute **%d** retenue.\nAvec quelle caption ?"
                     % (self.page * self.PAR_PAGE + rang + 1)),
            view=ChoixCaptionView(self.cog, self.identity, video),
            ephemeral=True)


def _appel_marque(cle, exiger_banger, brute_favorite):
    """L'appel d'une variante de marque, tel que le faisaient ses boutons."""
    async def _appel(cog, itx):
        await cog._send_template_marque(itx, cle, exiger_banger=exiger_banger,
                                        brute_favorite=brute_favorite)
    return _appel


async def _appel_reelmonte(cog, itx):
    await cog.reelmonte.callback(cog, itx)


async def _appel_capbanger(cog, itx):
    await cog._send_caption_bangers(itx)


async def _appel_montagebanger(cog, itx):
    await cog._send_montage_bangers(itx)


async def _appel_templatebanger(cog, itx):
    await cog._send_template_plus_brute(itx, brute_favorite=False)


async def _appel_templatebrut(cog, itx):
    await cog._send_template_plus_brute(itx)


#: Les variantes que le MENU VA sait lancer, et COMMENT. Ce sont exactement
#: les appels des anciens boutons (cmenu:capbanger, cmenu:templateflash…) :
#: les ranger dans un menu deroulant ne devait rien changer a ce qu'ils
#: envoient.
#:
#: Le menu VA n'a jamais eu les « ⭐ Brut + … », ni « 💬 Caption » (c'est
#: « Reel », rangee 0) : la table ne les invente pas. Les marques suivent
#: marques_montage (la marque seule, + etoile, + etoile + brute etoilee).
_MENU_VA_APPELS = {
    "capbanger": _appel_capbanger,
    "montagebanger": _appel_montagebanger,
    "reelmonte": _appel_reelmonte,
    "templatebanger": _appel_templatebanger,
    "templatebrut": _appel_templatebrut,
}
for _m in marques_montage.ORDRE:
    for _i in (0, 1, 3):
        _MENU_VA_APPELS[marques_montage.marque(_m)["actions"][_i]] = _appel_marque(
            _m, *_MARQUE_VARIANTES[_i])
del _m, _i


async def _lancer_variante_va(cog, interaction, cle):
    """Lance une variante du menu VA par sa cle d'action."""
    appel = _MENU_VA_APPELS.get(cle)
    if appel is None:
        await interaction.response.send_message(
            f"Action indisponible (`{cle}`).", ephemeral=True)
        return
    await appel(cog, interaction)


# ---------------------------------------------------------------------------
# LE MENU VA, EN « COMPONENTS V2 » (menus directs, 25/09/2026)
#
# Meme principe que le panneau US (maquette /demopanneau validee par le
# proprietaire) : plus de lanceur « ▸ » qui ouvre un sous-menu ephemere, UN
# MENU DEROULANT PAR FAMILLE, directement dans le menu. Un message classique
# plafonne a cinq rangees et chaque menu en prend une : quatre rangees de
# boutons + quatre menus n'y tiennent pas. Le V2 compte les composants (40
# au plus ; le menu en a 31) et n'a pas d'embed : l'aide passe dans le texte
# d'en tete.
#
# Vue PERSISTANTE : timeout None, custom_id fixes (« cmenu:<cle> » pour les
# boutons, « cmenu:sel:<famille> » pour les menus), enregistree dans
# cog_load. Les menus deja epingles, dans l'ancien format, repondent encore :
# leurs boutons gardent les memes custom_id, les boutons retires avant eux
# sont servis par ContentMenuHeritageView, leurs lanceurs « ▸ » par
# ContentMenuLanceursView.

#: Un bouton du menu VA : sa cle (custom_id « cmenu:<cle> »), son libelle,
#: son emoji standard (remplace par l'icone dessinee du serveur quand elle
#: existe), son style, et sa ligne dans le texte d'aide.
_BoutonVA = _collections.namedtuple("_BoutonVA", "cle libelle emoji style aide")

#: La place des menus deroulants de famille dans la disposition.
_MENU_VA_FAMILLES = "_familles"

_BS = discord.ButtonStyle

#: LE MENU VA, EN UNE SEULE TABLE : rangees dans l'ordre, chaque bouton, et
#: sa ligne d'aide. Les menus viennent de _FAMILLES_MENU (variantes :
#: _variantes_menu_va, appels : _MENU_VA_APPELS). Le texte d'en tete est
#: DEDUIT de ce qui a ete reellement pose apres les reglages du serveur :
#: l'ancien embed avait sa propre liste, et pouvait decrire un bouton absent.
_MENU_VA_DISPOSITION = (
    ("Publier", (
        _BoutonVA("reel", "Reel", "🎬", _BS.primary, "vidéos + captions (1 par compte)"),
        _BoutonVA("banger", "⭐ Reels", None, _BS.primary, "tes meilleurs reels ⭐"),
        _BoutonVA("story", "Story", "📖", _BS.primary, "photo + texte pour ta story"),
        _BoutonVA("storycta", "Story CTA", "📲", _BS.primary, "photo CTA, à poster le soir"),
        _BoutonVA("post", "Post", "🖼️", _BS.primary, "photo + légende pour le feed"),
    )),
    ("Ton compte", (
        _BoutonVA("name", "Name", "📝", _BS.secondary, "des noms d'affichage"),
        _BoutonVA("pseudo", "Pseudo", "👤", _BS.secondary, "des pseudos dispo"),
        _BoutonVA("pp", "PP", "🖼", _BS.secondary, "des photos de profil prêtes"),
        _BoutonVA("bio", "Bio", "💬", _BS.secondary, "des bios prêtes à coller"),
        _BoutonVA("brutbanger", "⭐ Vidéo brut", None, _BS.primary,
                  "tes meilleures brutes ⭐, sans montage"),
    )),
    ("Montages", _MENU_VA_FAMILLES),
    ("Suivi et aide", (
        _BoutonVA("clics", "Mes clics", "📊", _BS.success,
                  "tes clics en direct (jour, hier, semaine, quinzaine)"),
        _BoutonVA("help", "Assistance", "🆘", _BS.danger,
                  "un souci ? un manager ou le boss vient t'aider"),
        _BoutonVA("lien", "Demander un lien", "🔗", _BS.success,
                  "ton lien si tu en as un, sinon les managers sont prévenus"),
        _BoutonVA("pay", "Mon paiement", "💸", _BS.secondary,
                  "comment tu reçois ton argent (crypto ou TapTap)"),
        _BoutonVA("tuto", "Comprends rien ?", "❓", _BS.secondary,
                  "une vidéo qui explique comment tout marche"),
    )),
    ("Tes comptes", (
        _BoutonVA("addaccount", "Ajouter un compte", "➕", _BS.primary,
                  "relance l'onboarding pour un nouveau compte"),
        _BoutonVA("comptes", "Mes comptes Insta", "📷", _BS.secondary,
                  "la liste de tes comptes Instagram (@pseudo)"),
    )),
)

#: Mode Threads : (libelle, aide) qui remplacent ceux de la table.
_MENU_VA_THREADS = {
    "comptes": ("Mes comptes Threads", "la liste de tes comptes Threads (@pseudo)"),
}


class _BoutonMenuVA(discord.ui.Button):
    """Un bouton du menu VA. Il garde son menu en reference directe : dans
    un LayoutView, il vit dans une rangee, elle-meme dans un conteneur."""

    def __init__(self, menu, spec, libelle, emoji):
        super().__init__(label=libelle, emoji=emoji, style=spec.style,
                         custom_id="cmenu:" + spec.cle)
        self.menu = menu
        self.cle = spec.cle

    async def callback(self, interaction: discord.Interaction):
        await getattr(self.menu, "_clic_" + self.cle)(interaction)


class _MenuFamilleVA(discord.ui.Select):
    """Le menu deroulant d'une famille du menu VA (« 💬 Caption… »).

    Options : les variantes que CE serveur autorise (_variantes_menu_va),
    avec le libelle de production, la ligne d'explication et l'icone du
    serveur (_jb_option_action, la brique du panneau US). custom_id fixe
    « cmenu:sel:<famille> » : il repond apres un redemarrage."""

    def __init__(self, menu, fam, cles, icones=None):
        opts, self.inconnues = [], []
        for cle in cles:
            o = _jb_option_action(cle, icones)
            if o is None:
                self.inconnues.append(cle)
            else:
                opts.append(o)
        if self.inconnues:
            log.warning("menu VA, famille %s : variante(s) sans libelle "
                        "(absente(s) de _JB_ACTIONS_US) : %s",
                        fam.cle, ", ".join(self.inconnues))
        #: Aucune option : ContentMenuView ne pose pas ce menu (Discord
        #: refuserait le message ENTIER) et le dit dans le texte.
        self.vide = not opts
        super().__init__(
            custom_id=_CMENU_MENU + fam.cle,
            placeholder=_jb_placeholder_famille(fam), min_values=1, max_values=1,
            options=opts or [discord.SelectOption(label="(aucune variante)", value="_")])
        self.menu = menu
        self.famille = fam.cle

    async def callback(self, interaction: discord.Interaction):
        # Les valeurs de L'INTERACTION, pas celles de l'objet : l'element
        # enregistre au demarrage est partage par tous les salons va-.
        valeurs = ((getattr(interaction, "data", None) or {}).get("values")
                   or list(self.values or []))
        await _menu_va_choisir(self.menu.cog, interaction, self.famille,
                               (valeurs or [""])[0])


def _menu_va(cog, identite=None, guild=None, mention=None):
    """Le menu VA pret a partir : reglages de `guild` appliques, texte
    compris. `mention` : l'id du VA a pinger en tete (menu du jour)."""
    vue = ContentMenuView(cog, identite=identite, mention=mention)
    return _filter_menu_view(vue, guild)


def _menu_va_frais(cog, interaction):
    """Le menu VA d'ou vient le clic, redessine : ses menus sur leur
    intitule, les reglages ACTUELS du serveur, et ce qu'il affichait
    (identite, mention) relu dans le message. En ephemere, une vue ARRETEE
    (_vue_sans_suivi) : ses clics sont servis par la vue persistante."""
    msg = getattr(interaction, "message", None)
    ident, mention = _menu_va_lire(msg) if msg is not None else (None, None)
    vue = _menu_va(cog, ident, getattr(interaction, "guild", None), mention)
    if getattr(getattr(msg, "flags", None), "ephemeral", False):
        _vue_sans_suivi(vue)
    return vue


async def _menu_va_choisir(cog, interaction, famille, choix):
    """Un choix dans un menu de famille du menu VA.

    La valeur est VALIDEE (liste blanche de la famille, variantes que le
    serveur autorise AUJOURD'HUI -- un menu poste avant un changement de
    reglage porte encore l'option), puis la variante part par
    _MENU_VA_APPELS, EXACTEMENT comme son ancien bouton. Le menu reprend son
    intitule, sans quoi re-choisir la meme variante ne declencherait rien.
    Une interaction = une reponse, dans tous les cas (_menu_lancer)."""
    msg = getattr(interaction, "message", None)
    ephemere = bool(getattr(getattr(msg, "flags", None), "ephemeral", False))
    frais = _menu_va_frais(cog, interaction)
    fam = _famille_menu(famille)
    feats, threads = _reglages_menu(getattr(interaction, "guild", None))
    refus = ""
    if fam is None or choix not in fam.actions or choix not in _MENU_VA_APPELS:
        # Hors de la liste blanche : ce choix ne vient pas d'un menu que le
        # bot a pose. Refuse, et trace.
        log.warning("menu VA : choix %r refuse (famille %r)", choix, famille)
        refus = f"Option inconnue (`{choix}`) : tape `/menu` pour un menu à jour."
    elif choix not in _variantes_menu_va(famille, feats, threads):
        refus = "⚠️ Cette fonction est désactivée sur ce serveur."
    if refus:
        await _jb_menu_refuser(interaction, refus, frais)
        return
    # Le message du SALON se redessine tout de suite, sans attendre la fin
    # d'un rendu de 30 s : c'est un message du bot, il s'edite sans passer
    # par l'interaction. Un ephemere est redessine apres coup, par elle.
    tache = None
    if not ephemere and msg is not None:
        tache = _jb_en_fond(msg.edit(view=frais, **_jb_kw_format(msg)),
                            "menu VA : menu remis sur son intitule")
    appel = _MENU_VA_APPELS[choix]
    await _menu_lancer(interaction, lambda: appel(cog, interaction), choix,
                       frais, tache, "menu VA")


async def _menu_va_reposer(chan, ancien, vue, raison):
    """Le REPLI quand Discord refuse de convertir un ancien menu par
    edition : un NOUVEAU menu V2 est poste (epingle si l'ancien l'etait),
    puis l'ancien est retire. Tout est journalise. Leve si le nouveau n'a
    pas pu etre poste : _jb_panneau_en_reponse le laisse remonter."""
    nom = getattr(chan, "name", "?")
    nouveau = await chan.send(view=vue)
    log.warning("menu VA %s : %s -- nouveau menu V2 %s a la place de %s",
                nom, raison, nouveau.id, getattr(ancien, "id", None))
    if getattr(ancien, "pinned", False):
        try:
            await nouveau.pin(reason="Menu permanent VA (h24)")
        except Exception as e:                               # noqa: BLE001
            log.warning("menu VA %s : nouveau menu non epingle (%s: %s)",
                        nom, type(e).__name__, e)
    if ancien is not None:
        try:
            await ancien.delete()
        except Exception as e:                               # noqa: BLE001
            log.warning("menu VA %s : ancien menu %s non retire (%s: %s) -- "
                        "deux menus dans le salon", nom,
                        getattr(ancien, "id", "?"), type(e).__name__, e)
    return nouveau


async def _menu_va_convertir(cog, interaction):
    """Le clic sur un ancien lanceur « ▸ » : le menu qui le porte devient le
    menu V2, SUR PLACE (meme message, meme epingle), au lieu d'ouvrir un
    sous-menu ephemere. Le VA choisit ensuite sa variante dans le menu de la
    famille. Conversion par edition, repli par un nouveau message : la
    brique du panneau US (_jb_panneau_en_reponse)."""
    vue = _menu_va_frais(cog, interaction)
    if not vue.a_des_elements():
        await interaction.response.send_message(
            "⚠️ Aucune fonction de menu activée sur ce serveur.", ephemeral=True)
        return
    try:
        await _jb_panneau_en_reponse(interaction, vue, None, quoi="menu VA",
                                     reposer=_menu_va_reposer)
        return
    except Exception as e:                                   # noqa: BLE001
        # Edition refusee ET nouveau message impossible (droits du salon…) :
        # sans ce repli, le clic finissait sur un accuse de reception muet.
        log.warning("menu VA %s : conversion impossible (%s: %s) -- menu "
                    "envoye en ephemere", getattr(interaction.channel, "name", "?"),
                    type(e).__name__, e)
    secours = _vue_sans_suivi(_menu_va_frais(cog, interaction))
    try:
        if interaction.response.is_done():
            await interaction.followup.send(view=secours, ephemeral=True)
        else:
            await interaction.response.send_message(view=secours, ephemeral=True)
    except Exception as e:                                   # noqa: BLE001
        log.warning("menu VA : menu de secours non envoye (%s: %s)",
                    type(e).__name__, e)


class ContentMenuView(discord.ui.LayoutView):
    """Menu de contenu cliquable. Chaque bouton sert le contenu correspondant
    pour l'identité du VA qui clique (réutilise les commandes existantes).
    Vue persistante (custom_id fixes, timeout None) : marche après un
    redémarrage du bot.

    « Components V2 » depuis le 25/09/2026 (menus directs) : un bloc, le
    texte d'aide en tete, puis les rangees de _MENU_VA_DISPOSITION --
      Reel, ⭐ Reels, Story, Story CTA, Post
      Name, Pseudo, PP, Bio, ⭐ Vidéo brut
      un menu deroulant par famille de _FAMILLES_MENU (Caption, Template,
      Trash, Flash), sans etape
      Mes clics, Assistance, Demander un lien, Mon paiement, Comprends rien ?
      Ajouter un compte, Mes comptes Insta
    Construite sans reglages (enregistrement au demarrage, tests) elle porte
    TOUT ; _filter_menu_view / _menu_va la reconstruisent pour un serveur.
    """

    def __init__(self, cog, identite=None, mention=None):
        super().__init__(timeout=None)
        self.cog = cog
        self.identite = identite
        self.mention = mention
        self.construire(None, filtrer=False)

    def a_des_elements(self) -> bool:
        """Au moins un bouton ou un menu : sinon, rien a poster."""
        return self.nb_elements > 0

    def construire(self, guild=None, filtrer=True):
        """(Re)construit le menu avec les reglages de `guild` : un bouton coupe
        disparait, une option coupee disparait de son menu, un menu sans
        option disparait. `filtrer=False` : tout, sans reglage (la vue
        enregistree au demarrage doit porter TOUS les custom_id)."""
        ui = discord.ui
        feats, threads = _reglages_menu(guild) if filtrer else (None, False)
        try:
            icones = icones_actions(guild)   # lecture seule : rien sur le reseau
        except Exception as e:                               # noqa: BLE001
            log.warning("menu VA : icones illisibles (%s: %s)", type(e).__name__, e)
            icones = {}
        self.clear_items()
        self.threads = threads
        self.inconnues = []
        self.nb_elements = 0
        boite = ui.Container(accent_colour=discord.Colour.blurple())
        texte = ui.TextDisplay(_MENU_VA_MARQUE)      # ecrit a la fin
        boite.add_item(texte)
        aide, avec_menus = [], False
        for titre, boutons in _MENU_VA_DISPOSITION:
            if boutons is _MENU_VA_FAMILLES:
                noms = []
                for fam in _FAMILLES_MENU:
                    cles = _variantes_menu_va(fam.cle, feats, threads)
                    if not cles:
                        continue                 # aucune variante permise ici
                    menu = _MenuFamilleVA(self, fam, cles, icones)
                    self.inconnues += menu.inconnues
                    if menu.vide:
                        self.inconnues.append(f"menu {fam.nom}")
                        continue
                    rangee = ui.ActionRow()
                    rangee.add_item(menu)
                    boite.add_item(rangee)
                    self.nb_elements += 1
                    noms.append(f"{fam.emoji} {fam.nom}")
                if noms:
                    avec_menus = True
                    aide.append(f"**{titre}** — un menu par famille ("
                                + " · ".join(noms) + ") : choisis ta variante, "
                                "chaque option dit ce qu'elle envoie.")
                continue
            rangee, morceaux = ui.ActionRow(), []
            for b in boutons:
                if not _bouton_va_permis("cmenu:" + b.cle, feats, threads):
                    continue
                if not hasattr(self, "_clic_" + b.cle):
                    # Une ligne de table sans methode : le bouton ne ferait
                    # rien. Absent du menu, mais COMPTE et dit.
                    log.warning("menu VA : bouton %r sans methode _clic_%s",
                                b.cle, b.cle)
                    self.inconnues.append(b.cle)
                    continue
                libelle, expli = b.libelle, b.aide
                if threads and b.cle in _MENU_VA_THREADS:
                    libelle, expli = _MENU_VA_THREADS[b.cle]
                cle_ic = _ICONE_PAR_ACTION_MENU.get(b.cle)
                icone = icones.get(cle_ic) if cle_ic else None
                rangee.add_item(_BoutonMenuVA(
                    self, b, libelle, icone if icone is not None else b.emoji))
                self.nb_elements += 1
                morceaux.append(f"{b.emoji + ' ' if b.emoji else ''}**{libelle}** : {expli}")
            if morceaux:
                boite.add_item(rangee)
                aide.append(f"**{titre}** — " + " · ".join(morceaux))
        texte.content = _menu_va_texte(aide, threads, avec_menus, self.identite,
                                       self.mention, self.inconnues)
        self.add_item(boite)

    # -- ce que fait chaque bouton (cle de _MENU_VA_DISPOSITION) -------------

    async def _clic_reel(self, interaction: discord.Interaction):
        await self.cog.reel.callback(self.cog, interaction)

    async def _clic_banger(self, interaction: discord.Interaction):
        await self.cog._send_banger_reels(interaction)

    async def _clic_story(self, interaction: discord.Interaction):
        await self.cog.story.callback(self.cog, interaction)

    async def _clic_storycta(self, interaction: discord.Interaction):
        await self.cog.storycta.callback(self.cog, interaction)

    async def _clic_post(self, interaction: discord.Interaction):
        await self.cog.post.callback(self.cog, interaction)

    async def _clic_name(self, interaction: discord.Interaction):
        await self.cog.name.callback(self.cog, interaction)

    async def _clic_pseudo(self, interaction: discord.Interaction):
        await self.cog.username.callback(self.cog, interaction)

    async def _clic_pp(self, interaction: discord.Interaction):
        await self.cog.profilepic.callback(self.cog, interaction)

    async def _clic_bio(self, interaction: discord.Interaction):
        await self.cog.bio.callback(self.cog, interaction)

    async def _clic_brutbanger(self, interaction: discord.Interaction):
        await self.cog._send_brutes_bangers(interaction)

    async def _clic_clics(self, interaction: discord.Interaction):
        # Délègue au cog clickrecap (logique des clics centralisée là-bas)
        cog = interaction.client.get_cog("ClickRecap")
        if cog is None or not hasattr(cog, "_handle_myclicks"):
            await interaction.response.send_message(
                "⚠️ Stats de clics indisponibles pour l'instant.", ephemeral=True)
            return
        await cog._handle_myclicks(interaction)

    async def _clic_help(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AssistanceModal(self.cog))

    async def _clic_lien(self, interaction: discord.Interaction):
        await self.cog.request_link(interaction)

    async def _clic_pay(self, interaction: discord.Interaction):
        emb = discord.Embed(
            title="💸 Ton moyen de paiement",
            description="Choisis **comment tu veux recevoir ton argent** 👇",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=emb, view=PaymentMethodView(self.cog), ephemeral=True)

    async def _clic_tuto(self, interaction: discord.Interaction):
        await self.cog._send_tutoriel(interaction)

    async def _clic_addaccount(self, interaction: discord.Interaction):
        if not _menu_feature_check(interaction, "onboarding"):
            await interaction.response.send_message("⚠️ Désactivé sur ce serveur.", ephemeral=True)
            return
        # Relance l'onboarding depuis l'étape 0 (mêmes vues que le 1er onboarding)
        try:
            from cogs.onboarding import step_embed, OnboardingView, send_step_media
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Onboarding indispo : {e}", ephemeral=True)
            return
        await interaction.response.send_message(
            content=f"{interaction.user.mention} — on repart de zéro pour ajouter un compte 👇",
            embed=step_embed(0), view=OnboardingView(),
        )
        try:
            await send_step_media(interaction.channel, 0, bot=interaction.client)
        except Exception:
            pass

    async def _clic_comptes(self, interaction: discord.Interaction):
        if not _menu_feature_check(interaction, "contenu"):
            await interaction.response.send_message("⚠️ Désactivé sur ce serveur.", ephemeral=True)
            return
        # Ouvre le modal de saisie des 3 comptes Insta (Insta 1/2/3) : pseudo OU lien,
        # avec validation d'existence. Pre-rempli avec ce que le VA a deja mis.
        prefill = []
        try:
            _u = load_json(USERS_FILE, {}).get(str(interaction.user.id))
            if isinstance(_u, dict):
                prefill = [x for x in (_u.get("insta_accounts") or []) if isinstance(x, str)][:3]
        except Exception:
            pass
        await interaction.response.send_modal(MesComptesInstaModal(prefill=prefill))


class _BoutonHeritageVA(discord.ui.Button):
    """Un bouton RETIRE du menu VA, encore porte par les menus deja postes."""

    def __init__(self, cle):
        super().__init__(label=cle, custom_id=f"cmenu:{cle}")
        self.cle = cle

    async def callback(self, interaction: discord.Interaction):
        await _lancer_variante_va(self.view.cog, interaction, self.cle)


class _LanceurFamilleVA(discord.ui.Button):
    """« 💬 Caption ▸ », « 🎞️ Template ▸ »… des menus VA postes entre
    dc157c3 et le passage aux menus directs. PLUS POSE : il ouvrait les
    variantes dans un sous-menu ephemere. Au clic, il convertit le menu qui
    le porte en menu V2, sur place (_menu_va_convertir). Servi par
    ContentMenuLanceursView."""

    def __init__(self, fam):
        super().__init__(label=f"{fam.nom} ▸", emoji=fam.emoji,
                         style=discord.ButtonStyle.primary,
                         custom_id=_CMENU_FAMILLE + fam.cle)
        self.famille = fam.cle

    async def callback(self, interaction: discord.Interaction):
        await _menu_va_convertir(self.view.cog, interaction)


class ContentMenuHeritageView(discord.ui.View):
    """Les custom_id que le menu VA a quittes le 25/09/2026 (passes dans les
    familles), TOUJOURS GERES.

    Jamais postee : enregistree au demarrage (cog_load) pour repondre aux
    menus deja epingles dans les salons va-, jusqu'a ce qu'un nouveau menu
    les remplace. Sans elle, ces boutons resteraient a l'ecran et ne feraient
    plus rien -- sans un mot, pour le VA comme pour le journal.

    Chaque bouton lance EXACTEMENT ce qu'il lancait (_MENU_VA_APPELS). Les
    Trash n'y sont pas : ils n'ont jamais ete postes hors d'un sous-menu.
    """

    #: Les anciens boutons, dans l'ordre de l'ancien menu.
    ANCIENS = ("reelmonte", "templateflash", "templateflashbanger",
               "templateflashbrut", "capbanger", "montagebanger",
               "templatebanger", "templatebrut")

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        for cle in self.ANCIENS:
            self.add_item(_BoutonHeritageVA(cle))


class ContentMenuLanceursView(discord.ui.View):
    """Les lanceurs « ▸ » (cmenu:fam:<famille>) des menus VA postes entre
    dc157c3 et le passage aux menus directs, TOUJOURS GERES : un clic
    convertit leur menu en V2, sur place (_menu_va_convertir).

    Jamais postee, enregistree au demarrage comme ContentMenuHeritageView.
    A part d'elle : ses boutons ne lancent pas une variante, ils changent le
    message qui les porte."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        for fam in _FAMILLES_MENU:
            self.add_item(_LanceurFamilleVA(fam))


class CentralMenuView(discord.ui.View):
    """Menu CENTRAL (salon partagé type #commande-va) : chaque bouton envoie le
    contenu dans le SALON PERSO du VA qui clique (via _central_run). Persistant."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Reel", emoji="🎬", style=discord.ButtonStyle.primary, custom_id="cmenu2:reel", row=0)
    async def b_reel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.reel)

    @discord.ui.button(label="Template", emoji="🎞️", style=discord.ButtonStyle.primary, custom_id="cmenu2:reelmonte", row=0)
    async def b_reelmonte(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.reelmonte)

    @discord.ui.button(label="Story", emoji="📖", style=discord.ButtonStyle.primary, custom_id="cmenu2:story", row=0)
    async def b_story(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.story)

    @discord.ui.button(label="Post", emoji="🖼️", style=discord.ButtonStyle.primary, custom_id="cmenu2:post", row=0)
    async def b_post(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.post)

    @discord.ui.button(label="Story CTA", emoji="📲", style=discord.ButtonStyle.primary, custom_id="cmenu2:storycta", row=0)
    async def b_storycta(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.storycta)

    @discord.ui.button(label="Pseudo", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="cmenu2:pseudo", row=1)
    async def b_pseudo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.username)

    @discord.ui.button(label="Name", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="cmenu2:name", row=1)
    async def b_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.name)

    @discord.ui.button(label="Bio", emoji="💬", style=discord.ButtonStyle.secondary, custom_id="cmenu2:bio", row=1)
    async def b_bio(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.bio)

    @discord.ui.button(label="PP", emoji="🖼", style=discord.ButtonStyle.secondary, custom_id="cmenu2:pp", row=1)
    async def b_pp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._central_run(interaction, self.cog.profilepic)

    @discord.ui.button(label="Demander un lien", emoji="🔗", style=discord.ButtonStyle.success, custom_id="cmenu2:lien", row=2)
    async def b_lien(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.request_link(interaction)

    @discord.ui.button(label="Assistance", emoji="🆘", style=discord.ButtonStyle.danger, custom_id="cmenu2:help", row=2)
    async def b_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AssistanceModal(self.cog))

    @discord.ui.button(label="Mon paiement", emoji="💸", style=discord.ButtonStyle.secondary, custom_id="cmenu2:pay", row=2)
    async def b_pay(self, interaction: discord.Interaction, button: discord.ui.Button):
        emb = discord.Embed(
            title="💸 Ton moyen de paiement",
            description="Choisis **comment tu veux recevoir ton argent** 👇",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=emb, view=PaymentMethodView(self.cog), ephemeral=True)

    @discord.ui.button(label="Comprends rien ?", emoji="❓", style=discord.ButtonStyle.secondary, custom_id="cmenu2:tuto", row=2)
    async def b_tuto(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._send_tutoriel(interaction)


class AssistanceModal(discord.ui.Modal, title="🆘 Demande d'aide"):
    """Le VA explique son probleme -> transmis au salon 🆘・help."""
    probleme = discord.ui.TextInput(
        label="C'est quoi ton problème ?",
        placeholder="Explique ton souci en quelques mots, un manager va venir t'aider…",
        style=discord.TextStyle.paragraph,
        required=True, min_length=3, max_length=1000,
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._handle_assistance(interaction, str(self.probleme.value or ""))


# ============ Moyen de paiement du VA ============
# Le VA declare comment il veut etre paye : crypto (USDC/ETH/SOL -> adresse) ou
# TapTap mobile money (reseau + numero). Stocke dans users.json[uid]["payment"].
# Flux : bouton -> select methode -> (crypto: modal adresse) / (taptap: select
# reseau -> modal numero) -> _save_payment.
# Reseaux (chaines) sur lesquels le VA peut recevoir de l'USDC.
_USDC_CHAINS = [
    ("Solana", "USDC sur Solana", "🟣"),
    ("ETH", "USDC sur Ethereum", "💎"),
]


class _PaymentMethodSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        opts = [
            discord.SelectOption(label="USDC (crypto)", value="USDC", emoji="💵",
                                 description="Reçu en USDC sur Solana ou Ethereum"),
            discord.SelectOption(label="TapTap (Mobile Money)", value="TAPTAP", emoji="📱",
                                 description="Airtel / Orange / Mvola / Moov / MTN"),
        ]
        super().__init__(placeholder="Choisis ton moyen de paiement…",
                         min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "USDC":
            await interaction.response.edit_message(
                content="💵 **USDC** — sur quel réseau veux-tu le recevoir ?",
                embed=None, view=_UsdcChainView(self.cog))
        else:
            await interaction.response.edit_message(
                content="📱 **TapTap** — choisis ton réseau :",
                embed=None, view=_PaymentNetworkView(self.cog))


class PaymentMethodView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.add_item(_PaymentMethodSelect(cog))


class _UsdcChainSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        opts = [discord.SelectOption(label=code, value=code, description=desc, emoji=emo)
                for code, desc, emo in _USDC_CHAINS]
        super().__init__(placeholder="Solana ou Ethereum…",
                         min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(_CryptoAddressModal(self.cog, self.values[0]))


class _UsdcChainView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.add_item(_UsdcChainSelect(cog))


class _PaymentNetworkSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        opts = [discord.SelectOption(label=code, value=code, description=desc)
                for code, desc in _PAY_NETWORKS]
        super().__init__(placeholder="Choisis ton réseau…",
                         min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(_MobileNumberModal(self.cog, self.values[0]))


class _PaymentNetworkView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.add_item(_PaymentNetworkSelect(cog))


class _CryptoAddressModal(discord.ui.Modal):
    def __init__(self, cog, chain):
        super().__init__(title=f"💵 USDC — {chain}")
        self.cog = cog
        self.chain = chain
        self.addr = discord.ui.TextInput(
            label=f"Ton adresse USDC ({chain})",
            placeholder="Colle ici ton adresse de wallet",
            required=True, max_length=200)
        self.add_item(self.addr)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._save_crypto_and_ask_screenshot(interaction, {
            "method": "USDC", "chain": self.chain,
            "address": str(self.addr.value or "").strip()})


class _MobileNumberModal(discord.ui.Modal):
    def __init__(self, cog, network):
        super().__init__(title=f"📱 TapTap — {network}")
        self.cog = cog
        self.network = network
        self.number = discord.ui.TextInput(
            label="Ton numéro",
            placeholder="ex : +261 34 12 345 67",
            required=True, max_length=40)
        self.add_item(self.number)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._save_payment(interaction, {
            "method": "TapTap", "network": self.network,
            "number": str(self.number.value or "").strip()})


# ============ Menu JAILBREAK (toutes les models) ============
# Reserve aux VA avec le role 'Jailbreak'. Un select des models -> un menu
# ephemere : choix de la QUANTITE (multiplicateur) + 8 actions (reel/story/post/
# storycta/pseudo/name/bio/pp) qui generent le contenu de la MODEL choisie (via
# cog._run_for_model + override d'identite).
# (cle action, label bouton, attribut commande cog, accepte une quantite ?)
_JB_ACTIONS = [
    ("reel", "🎬 Reel", "reel", True),
    ("reelmonte", "🎞️ Template", "reelmonte", True),
    ("story", "📖 Story", "story", True),
    ("post", "🖼️ Post", "post", True),
    ("storycta", "📲 Story CTA", "storycta", True),
    ("pseudo", "👤 Pseudo", "username", False),
    ("name", "📝 Name", "name", False),
    ("bio", "💬 Bio", "bio", True),
    ("pp", "🖼️ PP", "profilepic", True),
    ("brute", "🎥 Vidéo brut", "videobrut", True),
]

# Liste AFFICHEE dans les menus Jailbreak (les 2 marches) : c'est « Reel
# caption » partout, jamais le Reel brut avec exemple (demande user).
# _JB_ACTIONS reste definie au-dessus : elle sert de table de compatibilite
# pour les panneaux DEJA postes dont les boutons portent la cle « reel ».
# Serveur US : PAS de « Reel » brut (les VA US ne postent pas de reel avec
# exemple) — à la place « Reel caption » (brute + caption incrustée, biblio
# Caption du site) et « Reel monté » (montage template).
def _actions_marque(cle) -> list:
    """Les quatre actions d'une marque, au format de _JB_ACTIONS_US.

    Cle d'action = attribut du cog : templateflash* sont des commandes
    slash, brutflash et les quatre Trash des methodes ordinaires, et
    _run_for_model sait appeler les deux.
    """
    return [(k, lib, k, True) for k, lib in
            zip(marques_montage.marque(cle)["actions"], _libelles_marque(cle))]


_JB_ACTIONS_US = [
    # IDENTITE.
    ('name', '📝 Name', 'name', False),
    ('pseudo', '👤 Pseudo', 'username', False),
    ('pp', '🖼️ PP', 'profilepic', True),
    ('bio', '💬 Bio', 'bio', True),

    # PUBLICATIONS, puis le brut nu et sa version marquee.
    ('story', '📖 Story', 'story', True),
    ('storycta', '📲 Story CTA', 'storycta', True),
    ('post', '🖼️ Post', 'post', True),
    ('brute', '🎥 Vidéo brut', 'videobrut', True),
    ('brutbanger', '⭐ Vidéo brut', 'brutbanger', False),

    # Les FAMILLES, dans l'ordre de _FAMILLES_MENU. Chacune va de la matiere
    # seule a la double etoile. LA BRUTE ETOILEE, LA MATIERE AU HASARD
    # (« ⭐ Brut + … ») suit l'etoile simple dont elle est la variante : on
    # lit la progression d'une meme matiere, pas un compte d'etoiles.
    ('reelcaption', '💬 Caption', 'reelcaption', True),
    ('capbanger', '⭐ Caption', 'captionbanger', True),
    ('brutcaption', '⭐ Brut + Caption', 'brutcaption', True),
    ('montagebanger', '⭐⭐ Caption + Vidéo brut', 'montagebanger', True),
    ('reelmonte', '🎞️ Template', 'reelmonte', True),
    ('templatebanger', '⭐ Template', 'templatebanger', True),
    ('bruttemplate', '⭐ Brut + Template', 'bruttemplate', True),
    ('templatebrut', '⭐⭐ Template + Brut', 'templatebrut', True),
    # Les MARQUES (Trash, puis Flash) : cles, libelles et ordre viennent de
    # marques_montage -- changer le logo la-bas change ces boutons.
    *[_e for _mq in marques_montage.ORDRE for _e in _actions_marque(_mq)],

    # Les TRENDS : des videos deja FINIES, a poster telles quelles.
    ('trend', '⭐⭐⭐ Trends', 'trends', True),
    ('brutchoix', '🎛️ Choisir ma brute', 'choisirbrute', False),

    # CETTE LISTE N'EST PAS L'ORDRE D'AFFICHAGE : c'est _JB_BOUTONS_V2 et
    # _FAMILLES_PANNEAU. Elle fait foi pour ce qui EXISTE (panneau, ✨ General,
    # parc, menutest) -- « trend » compris, masque mais toujours servi
    # (_JB_MASQUEES).
    # Trends et « Choisir ma brute » restent en queue : le menu de test
    # (cogs/menutest.py) coupe au-dela de 25 entrees en le disant, et ce sont
    # les deux seules qui n'ont de toute facon pas de reserve a y essayer.
]

#: Les actions servies par le stock « Trends » : elles se distinguent a
#: l oeil, en vert, du reste du panneau. Aucune cle Trash ne commence par
#: « trend » : « Trash Trend » n'est pas « ⭐⭐⭐ Trends ».
_JB_CLES_TREND = frozenset({"trend", "trendcaption", "trendtemplate", "trendflash"})

#: LE PANNEAU D'ACTIONS, EN UNE SEULE TABLE (maquette /demopanneau validee
#: par le proprietaire le 25/09/2026 : « c'est good, vas-y »).
#:
#: Le panneau US epingle, le panneau ephemere des serveurs non-US et la
#: maquette lisent TOUS cette table : _JB_BOUTONS_V2 (les boutons) et
#: _FAMILLES_PANNEAU (les menus) ; _JB_MASQUEES dit ce qui est retire expres.
#: Deux dispositions recopiees, c'est deux comportements.
#:
#: POURQUOI LE FORMAT « COMPONENTS V2 » (LayoutView)
#:     Un message classique plafonne a CINQ rangees, et un menu deroulant en
#:     occupe une entiere : deux rangees de boutons + cinq menus = sept. Le V2
#:     compte les COMPOSANTS (40 au plus, conteneur et rangees compris) et le
#:     texte (4000 au plus) ; il n'a pas d'embed, le texte passe dans un
#:     TextDisplay. Le panneau US en compte 22.
#:
#: Rangees de BOUTONS, dans l'ordre ; « _qte » est la place de la quantite
#: (bouton sur le panneau US, menu deroulant sur sa rangee a lui dans le
#: panneau ephemere). Puis UN MENU DEROULANT PAR FAMILLE, sans etape : le VA
#: choisit directement la variante. Les lanceurs « ▸ » qui ouvraient un
#: sous-menu ephemere (dc157c3) ne sont plus poses ; ceux deja postes
#: reconstruisent le panneau a la place (JBFamilleBouton).
_JB_QTE = "_qte"
_JB_BOUTONS_V2 = (
    (_JB_QTE, "name", "pseudo", "pp", "bio"),
    ("story", "storycta", "post"),
)

#: Le menu 🎥 Brut : le brut nu, la brute etoilee, et l'outil qui la choisit.
#: A part de _FAMILLES_MENU : cette table-la sert aussi le menu VA, qui garde
#: « ⭐ Vidéo brut » en bouton et n'a pas de famille Brut.
_FAMILLE_BRUT = _Famille("brut", "🎥", "Brut", ("brute", "brutbanger", "brutchoix"))

#: Les menus du panneau, dans l'ordre voulu par le proprietaire : Brut AVANT
#: les familles de _FAMILLES_MENU (Caption, Template, Trash, Flash).
_FAMILLES_PANNEAU = (_FAMILLE_BRUT,) + _FAMILLES_MENU

#: Actions qui EXISTENT encore mais ne s'affichent plus. « ⭐⭐⭐ Trends » a ete
#: retire par le proprietaire le 25/09/2026 (« pas encore good ») : sa cle
#: reste dans _JB_ACTIONS_US, parce que les panneaux deja postes portent
#: encore « jbus:a:…:trend:… » et doivent continuer de repondre. Etre ici,
#: c'est etre masquee EXPRES : le filet de _jb_disposition ne la compte pas
#: comme oubliee.
_JB_MASQUEES = frozenset({"trend"})


def _famille_panneau(cle):
    """La famille `cle` des menus du panneau (Brut compris), ou None."""
    for f in _FAMILLES_PANNEAU:
        if f.cle == cle:
            return f
    return None


#: La rangee PREVUE de chaque action : boutons d'abord (0, 1), puis le menu
#: de sa famille (2 = Brut, 3 = Caption…). Deduite de la table, rien a tenir
#: a jour a la main ; elle sert au filet (une action absente d'ici n'a pas
#: de place prevue).
_JB_RANGEES = {_k: _r for _r, _ks in enumerate(_JB_BOUTONS_V2)
               for _k in _ks if _k != _JB_QTE}
_JB_RANGEES.update({_k: len(_JB_BOUTONS_V2) + _i
                    for _i, _f in enumerate(_FAMILLES_PANNEAU) for _k in _f.actions})


def _jb_disposition():
    """([(sorte, cle, rangee)], hors) -- le panneau, dans l'ordre d'affichage.

    `sorte` vaut « qte » (la quantite), « action » (un bouton) ou « menu »
    (le menu deroulant d'une famille de _FAMILLES_PANNEAU). `rangee` est le
    rang de la rangee, de haut en bas.

    LE FILET. Une action de _JB_ACTIONS_US que ni les boutons ni un menu ne
    placent, et qui n'est pas masquee expres (_JB_MASQUEES), s'affiche quand
    meme : sur une rangee de boutons a elle, entre les boutons et les menus,
    cinq au plus. Au-dela, elle est COMPTEE, journalisee et dite dans le
    panneau -- jamais ecartee en silence.
    """
    out = []
    for r, ks in enumerate(_JB_BOUTONS_V2):
        for k in ks:
            out.append(("qte" if k == _JB_QTE else "action", k, r))
    rangee = len(_JB_BOUTONS_V2)
    orphelines = [a[0] for a in _JB_ACTIONS_US
                  if a[0] not in _JB_RANGEES and a[0] not in _JB_MASQUEES]
    if orphelines:
        out += [("action", k, rangee) for k in orphelines[:5]]
        rangee += 1
    hors = orphelines[5:]
    out += [("menu", f.cle, rangee + i) for i, f in enumerate(_FAMILLES_PANNEAU)]
    if orphelines:
        log.warning("panneau US : %d action(s) sans place prevue (%s)%s",
                    len(orphelines), ", ".join(orphelines),
                    (" -- %d non affichee(s) : %s" % (len(hors), ", ".join(hors)))
                    if hors else "")
    return out, hors


def _jb_note_hors(hors) -> str:
    """La ligne du panneau qui dit ce qu'il n'a pas pu afficher."""
    if not hors:
        return ""
    return (f"⚠️ {len(hors)} action(s) sans place dans ce panneau : "
            + ", ".join(hors) + " (à signaler à un admin).")


def _jb_option_action(cle, icones=None):
    """La SelectOption d'une action : libelle de production (_jb_action),
    la ligne d'explication (_EXPLICATIONS) en description, et l'icone
    dessinee du serveur si elle existe -- sinon l'emoji du libelle, tel
    quel, comme sur les boutons. None si l'action est inconnue."""
    entree = _jb_action(cle)
    if entree is None:
        return None
    lib = entree[1]
    icone = (icones or {}).get(cle)
    expli = _EXPLICATIONS.get(cle) or None
    return discord.SelectOption(
        label=_couper_discord(_libelle_sans_emoji(lib) if icone is not None else lib, 100),
        value=cle,
        description=_couper_discord(expli, 100) if expli else None,
        emoji=icone)


def _jb_options_famille(fam, icones=None):
    """(options, inconnues) du menu d'une famille. Une cle de famille sans
    action n'aurait pas d'option, et personne ne saurait pourquoi : elle est
    rendue a part, pour etre journalisee et dite."""
    opts, inconnues = [], []
    for cle in fam.actions:
        o = _jb_option_action(cle, icones)
        if o is None:
            inconnues.append(cle)
        else:
            opts.append(o)
    if inconnues:
        log.warning("famille %s : action(s) absente(s) de _JB_ACTIONS_US : %s",
                    fam.cle, ", ".join(inconnues))
    return opts, inconnues


def _jb_placeholder_famille(fam) -> str:
    """L'intitule d'un menu -- celui qu'il REPREND apres chaque choix."""
    return f"{fam.emoji} {fam.nom}…"


# Quantites proposees (multiplicateur). Plafonnees au stock reel de la model.
_JB_QTY_OPTIONS = [1, 3, 5, 10, 15, 20, 30, 50, 60]

# Discord ne sait pas faire un menu deroulant ou l on TAPE : une liste est une
# liste fermee. Pour un nombre libre il faut une fenetre de saisie (Modal). On
# ajoute donc une entree qui l ouvre, plutot que d allonger indefiniment la
# liste des valeurs proposees.
_JB_QTY_AUTRE = "__autre__"
_JB_QTY_MAX = 100          # garde-fou de saisie ; le stock de la model plafonne ensuite


def _jb_qty_options(courante: int) -> list:
    """Les quantites proposees, plus la valeur libre en cours, plus « Autre ».

    La valeur en cours est REINJECTEE si elle ne fait pas partie des choix
    predefinis : sans ca, apres avoir tape 7, le menu n avait plus aucune
    ligne cochee et on ne savait plus ce qui etait selectionne.
    """
    valeurs = sorted(set(_JB_QTY_OPTIONS) | {int(courante)})
    opts = [discord.SelectOption(label=f"{q} média par action", value=str(q),
                                 default=(q == int(courante)))
            for q in valeurs]
    opts.append(discord.SelectOption(
        label="Autre nombre…", value=_JB_QTY_AUTRE, emoji="✏️",
        description="Tape le nombre que tu veux"))
    return opts


class _JBQtyModal(discord.ui.Modal, title="Quantité par action"):
    """La petite fenetre ou le VA tape son nombre."""

    nombre = discord.ui.TextInput(
        label="Combien de médias par action ?",
        placeholder="ex : 7", required=True, min_length=1, max_length=3)

    def __init__(self, suite):
        super().__init__()
        self._suite = suite          # coroutine(interaction, quantite)

    async def on_submit(self, interaction: discord.Interaction):
        brut = str(self.nombre.value or "").strip()
        try:
            q = int(brut)
        except ValueError:
            # On repete ce qui a ete tape : « nombre invalide » tout court
            # laisse chercher ce qui n allait pas.
            await interaction.response.send_message(
                f"« {brut} » n'est pas un nombre.", ephemeral=True)
            return
        if not 1 <= q <= _JB_QTY_MAX:
            await interaction.response.send_message(
                f"Choisis un nombre entre 1 et {_JB_QTY_MAX}.", ephemeral=True)
            return
        await self._suite(interaction, q)

# Marché FR — exclu du menu Jailbreak US (/menujailbreakus). Le menu US montre
# toutes les identités actives SAUF celles-ci (jessye/jailbreak-only INCLUSES,
# contrairement au menu classique qui les exclut).
# Marché FR : rien de leur comportement ne doit changer sans demande explicite
# de l'user (leurs textes viennent UNIQUEMENT des .txt, comme avant).
# Repartition historique, utilisee tant que le marche n'a pas ete choisi sur
# le site (Bibliotheque -> Modifier -> Marche 🇫🇷/🇺🇸).
_FR_MARKET_IDENTITIES = {"julia", "emma", "lola", "sarah", "amelia", "alicia"}
# + jessye : elle non plus n'est pas une model du menu US (elle en est la SOURCE)
_JB_FR_IDENTITIES = _FR_MARKET_IDENTITIES | {"jessye"}

_MARKET_FILE = Path("data") / "identity_market.json"
_MARKET_CACHE = {"ts": 0.0, "sig": None, "data": {}}


def _markets() -> dict:
    """{identite: 'fr'|'us'} choisi depuis le site. Relu quand le fichier
    bouge (le site ecrit, le bot lit — deux processus distincts)."""
    try:
        sig = _MARKET_FILE.stat().st_mtime_ns
    except OSError:
        _MARKET_CACHE.update(sig=None, data={})
        return {}
    if _MARKET_CACHE["sig"] != sig:
        try:
            d = json.loads(_MARKET_FILE.read_text(encoding="utf-8"))
            d = {str(k).lower(): str(v).lower() for k, v in d.items()} if isinstance(d, dict) else {}
        except Exception:
            d = {}
        _MARKET_CACHE.update(sig=sig, data=d)
    return _MARKET_CACHE["data"]


def _market_of(identity: str) -> str:
    """« fr » (Discord YouL4b Agency) ou « us » (serveur Youl4b).
    La regle vit dans marche.py, partagee avec le site et la synchro Drive."""
    try:
        import marche as _mk
        return _mk.de(identity)
    except Exception:                      # module absent -> ancien comportement
        idl = (identity or "").strip().lower()
        v = _markets().get(idl)
        if v in ("fr", "us"):
            return v
        return "fr" if idl in _JB_FR_IDENTITIES else "us"


def _is_fr_market(identity: str) -> bool:
    """Marche FR au sens « textes et bios partages du serveur historique ».
    Jessye en est exclue : elle est la SOURCE du menu US, pas une model FR
    (c'etait deja le cas avant le selecteur, on ne change rien pour elle)."""
    idl = (identity or "").strip().lower()
    return idl != _US_SOURCE_IDENTITY and _market_of(idl) == "fr"

# Serveur US : pseudo et name sont GÉNÉRÉS à partir d'une identité « source »
# commune (Jessye), quelle que soit la model cliquée. Tout le reste — reel,
# story, post, PP et les BIOS — vient bien de la model : chaque model US a SA
# propre liste de bios sur le site.
#
# POURQUOI JESSYE, ET PAS LA MODEL
#     Les deux générateurs partent d'un PRÉNOM (generate_username_candidates,
#     generate_display_names). Or les identités US sont des pseudos de compte,
#     pas des prénoms : « themikkiangel » sort « themikkiangelstn » et
#     « Themikkiangel Belle ». « jessye » est un vrai prénom, donc
#     « jess_crush » et « Jessica Aubry ».
#
#     C'est acceptable parce qu'un pseudo n'a qu'un seul travail : être LIBRE
#     et plausible. Il n'a pas à rappeler la model — c'est un compte neuf.
#
#     Retirer cette redirection sans rien changer d'autre DÉGRADE le résultat.
#     Ce qui la rendrait inutile, c'est un vrai prénom stocké par identité sur
#     le site ; le générateur partirait de là, et chaque model aurait les siens.
#
# (Un commentaire affirmait ici que c'étaient « des exemples posés à la main,
# aucune génération IA ». C'était faux : rien n'est posé à la main.)
_US_SOURCE_IDENTITY = "jessye"
# (_US_SOURCED_ACTIONS a disparu : la liste des actions concernees etait la
#  pour que les BOUTONS sachent quand rediriger. Ce sont desormais les deux
#  commandes elles-memes qui appellent _source_pseudo_name, donc la reponse
#  est dans le code qui s en sert, plus dans un ensemble a tenir a jour.)


def _source_pseudo_name(identity: str) -> str:
    """Identité qui SERT à fabriquer pseudo et name. Souvent elle-même.

    LE DRAPEAU DU SITE TRANCHE, ET LUI SEUL
        Bibliothèque → ✏️ Modifier → Marché. Une identité marquée 🇺🇸 fabrique
        ses pseudos et ses noms à partir de Jessye ; une identité 🇫🇷 garde les
        siens. Rien d'autre n'entre en compte — ni le serveur, ni le rôle
        Discord du VA.

    POURQUOI UNE SEULE FONCTION
        La règle vivait avant dans les DEUX boutons du panneau Jailbreak, et
        nulle part ailleurs. Résultat : `/name`, `/username` et les boutons du
        menu VA l'ignoraient. Un VA sur une identité 🇺🇸 recevait
        « Ibenhaastrup Belle » au lieu d'un nom de Jessye, selon le bouton
        cliqué. Le même contenu, deux résultats.

        Les deux boutons s'appuyaient en plus sur le RÔLE du VA
        (marche_du_membre), pas sur le drapeau de l'identité. Deux critères
        différents pour une seule intention.

    POURQUOI JESSYE PLUTÔT QUE LA MODEL
        generate_username_candidates et generate_display_names partent d'un
        PRÉNOM. Les identités US sont des pseudos de compte :

            ibenhaastrup  →  « Ibenhaastrup Belle »,  ibenhaastrupstn
            jessye        →  « Jessica Aubry »,       jess_crush

        Un pseudo n'a qu'un seul travail : être libre et plausible. Il n'a pas
        à rappeler la model, c'est un compte neuf. Le jour où chaque identité
        portera un vrai prénom sur le site, cette fonction pourra rendre
        `identity` tout du long.
    """
    idl = (identity or "").strip().lower()
    if not idl or idl == _US_SOURCE_IDENTITY:
        return identity
    try:
        if _market_of(idl) == "us":
            return _US_SOURCE_IDENTITY
    except Exception:
        pass                                # marché illisible -> on ne touche à rien
    return identity


def marche_du_membre(member) -> str:
    """Marche d'une personne d'apres ses roles @Jailbreak FR / @Jailbreak US.
    Par defaut « us » : c'est le marche du serveur ou vit ce menu."""
    try:
        for r in getattr(member, "roles", []) or []:
            n = (getattr(r, "name", "") or "").strip().lower()
            if n == "jailbreak fr":
                return "fr"
            if n == "jailbreak us":
                return "us"
    except Exception:
        pass
    return "us"


def _jb_models_marche(marche="us"):
    """Models d'un marche donne : c'est le DRAPEAU qui tranche, et lui seul.

    LA NATURE NE FILTRE PLUS CE MENU, et c'est un retour en arriere assume.
    Elle avait ete ajoutee ici parce que le proprietaire voulait sortir des
    ECRANS DE SUIVI les dossiers ouverts pour produire des videos. Applique
    au menu des models, ce filtre a fait disparaitre quinze de ses vingt-deux
    entrees d'un coup : le 12/09/2026, /menujailbreakus a poste un panneau
    vide, et le diagnostic a montre « 22 identites -> 7 rangees en modele ».

    Il a tranche : « identite, modele, c'est la meme ». Pour un VA qui vient
    chercher du contenu, oui -- il lui faut TOUTES les models de son marche.
    Le reglage garde son role la ou il a ete demande (Social Analytics, le
    perimetre de scrape) ; il n'en a aucun ici.

    CE QUI A RENDU L'ACCIDENT POSSIBLE : le panneau de tri en masse range en
    « identite » tout ce qui n'est pas coche. Une seule sauvegarde suffit
    donc a en demoter quinze sur vingt-deux, sans que rien ne le dise.
    """
    try:
        from cogs.welcome import list_identities
        return [n for n in list_identities()
                if not _jb_en_pause(n)
                and n.strip().lower() not in EXCLURE_MENU
                and _market_of(n) == marche]
    except Exception:
        return []


def _jb_en_pause(n) -> bool:
    """La PAUSE du Vault (identite_pause) : seul reglage d'activite qui
    retire une model des menus Jailbreak.

    26/09/2026 : le menu US montrait 14 models, le site 18. Les quatre
    manquantes (ema_bb0, nanas__nyspam, mxckeymeiji, mini_caryn) portaient
    « enabled: false » dans identities_config.json -- le drapeau de la
    ROTATION des nouveaux VA (/toggleidentity), que le site n'affiche nulle
    part. Le proprietaire : « sur le site il y a tout ». Le menu suit donc le
    site. Une identite retiree de la rotation reste proposee aux VA
    Jailbreak ; pour la cacher PARTOUT, c'est la pause du Vault, que
    is_identity_active et la rotation respectent aussi.
    """
    try:
        from cogs.welcome import load_identities_config
        e = (load_identities_config() or {}).get(n)
        return isinstance(e, dict) and bool(e.get("pause"))
    except Exception:
        return False


# Jessye est la SOURCE du menu (pseudo/name), pas une model a proposer.
EXCLURE_MENU = {"jessye"}


def _jb_us_models():
    """Les models du serveur US — EXACTEMENT celles que la vue affichera.

    ELLE DELEGUE, ELLE NE RECOPIE PLUS. Cette fonction gardait sa propre
    copie des filtres, a un pres : elle oubliait EXCLURE_MENU. Le jour ou la
    seule model US restante a ete Jessye -- qui est justement dans
    EXCLURE_MENU, parce qu'elle est la SOURCE du menu et pas une model a
    proposer -- la garde a compte « 1 model », laisse passer, et la vue a
    poste un panneau SANS UN SEUL BOUTON.

    C'est le defaut que le CLAUDE.md du depot decrit en toutes lettres :
    « deux mappings valent deux comportements ». Ici les deux listes
    decidaient la meme chose et divergeaient d'un element.
    """
    return _jb_models_marche("us")


def _jb_diagnostic_marche(marche="us") -> str:
    """Pourquoi la liste est vide. En une phrase, avec des chiffres.

    Un menu vide ne dit rien de ce qui manque : le proprietaire voit un
    panneau sans boutons et ne peut ni le reparer ni savoir quoi regarder.
    On compte donc ce que chaque filtre retire, dans l'ordre ou il retire.
    """
    try:
        from cogs.welcome import list_identities
    except Exception as e:                                   # noqa: BLE001
        return "impossible de lire les identites (%s)" % type(e).__name__
    toutes = list(list_identities() or [])
    # Meme filtre que la liste : la pause seule (voir _jb_en_pause).
    actives = [n for n in toutes if not _jb_en_pause(n)]
    # LE DIAGNOSTIC COMPTE CE QUE LA LISTE FILTRE, pas autre chose. Il
    # comptait la nature alors que la liste ne la regarde plus : deux
    # comptages divergents, c'est le defaut qu'on vient de corriger.
    du_marche = [n for n in actives if _market_of(n) == marche]
    retenues = [n for n in du_marche if n.strip().lower() not in EXCLURE_MENU]
    # Les RESERVES sont deja retirees par list_identities : on les compte
    # quand meme, sinon « 22 au total » devient « 21 » sans explication le
    # jour ou une entree passe en reserve. Illisible -> etape omise.
    try:
        from cogs.welcome import reserves_hors_liste
        reserves = list(reserves_hors_liste() or [])
    except Exception:
        reserves = []
    bouts = ["%d identite(s) au total" % (len(toutes) + len(reserves))]
    if reserves:
        bouts.append("%d reserve(s) hors grille (%s)"
                     % (len(reserves), ", ".join(sorted(reserves))))
    bouts += ["%d active(s)" % len(actives),
              "%d sur le marche %s" % (len(du_marche), marche.upper())]
    exclues = [n for n in du_marche if n.strip().lower() in EXCLURE_MENU]
    if exclues:
        bouts.append("%d exclue(s) du menu (%s)" % (len(exclues), ", ".join(sorted(exclues))))
    bouts.append("**%d affichable(s)**" % len(retenues))
    return " → ".join(bouts)


# ---------------------------------------------------------------------------
# MENUS DEROULANTS : UN CHOIX = UNE ACTION, PUIS LE MENU REPREND SON INTITULE.
#
# Discord garde l'option choisie affichee dans le menu tant que le message
# n'est pas redessine, et re-choisir la MEME option ne declenche rien : le
# VA qui veut un deuxieme « ⭐ Caption » cliquerait dans le vide. Chaque choix
# doit donc etre suivi d'un redessin du message -- mais l'action (via
# _run_for_model) consomme deja la reponse de l'interaction (defer,
# send_message) : une interaction, UNE reponse. Le redessin passe donc par un
# autre chemin que la reponse, choisi selon ce que l'action a fait d'elle.

#: Les taches de fond en cours : une reference forte, sinon le ramasse-miettes
#: peut detruire une tache avant sa fin (documentation d'asyncio).
_JB_TACHES = set()


def _jb_en_fond(coro, quoi):
    """Lance `coro` sans l'attendre. La tache rend True si tout s'est bien
    passe, False sinon -- et l'echec est journalise, jamais avale."""
    async def _garde():
        try:
            await coro
            return True
        except Exception as e:                               # noqa: BLE001
            log.warning("%s : %s: %s", quoi, type(e).__name__, e)
            return False
    t = asyncio.get_running_loop().create_task(_garde())
    _JB_TACHES.add(t)
    t.add_done_callback(_JB_TACHES.discard)
    return t


async def _jb_tache_ok(tache) -> bool:
    """Le resultat d'une tache de _jb_en_fond, False si elle a echoue."""
    if tache is None:
        return False
    try:
        return bool(await tache)
    except Exception:                                        # noqa: BLE001
        return False


async def _jb_accuser(interaction, quoi="clic") -> bool:
    """Accuse reception d'un clic de composant (defer : rien ne change a
    l'ecran), sans jamais lever. -> True si l'interaction est acquittee (par
    cet appel ou avant lui), False si Discord a refuse l'accuse.

    Pourquoi a part : un accuse refuse (au-dela de 3 s, 10062 « Unknown
    interaction ») levait NotFound au milieu d'un try qui en attendait un
    autre -- celui du panneau supprime -- et le panneau etait pose une
    seconde fois. Ici l'echec est JOURNALISE et rendu : l'appelant sait
    qu'aucune reponse ni suite ne passera plus, et continue ce qui ne
    depend pas de l'interaction (les messages du salon)."""
    try:
        if interaction.response.is_done():
            return True
        await interaction.response.defer()
        return True
    except Exception as e:                                   # noqa: BLE001
        log.warning("%s : accuse de reception refuse (%s: %s) -- le choix est "
                    "applique quand meme, le VA lira « l'interaction a "
                    "echoue »", quoi, type(e).__name__, e)
        return False


async def _jb_menu_remettre(interaction, vue, quoi="panneau") -> bool:
    """Redessine le message du clic avec `vue`, APRES l'action : ses menus
    reprennent leur intitule. Ne leve jamais ; rend True si c'est fait.

    Le chemin depend de ce que l'action a fait de la reponse :
      - rien (elle n'a pas repondu) : on repond EN redessinant
        (edit_message), sans quoi Discord afficherait « l'interaction a
        echoue » ;
      - une mise a jour differee (le defer() d'un composant) : @original
        designe alors le message du clic, edit_original_response le redessine ;
      - un nouveau message : un message du salon se redessine par lui-meme
        (message.edit), un ephemere par le jeton de l'interaction
        (followup.edit_message).
    Un echec est JOURNALISE : le menu garde alors son choix, et le VA doit en
    prendre un autre avant de reprendre le meme.
    """
    msg = getattr(interaction, "message", None)
    try:
        rep = interaction.response
        if not rep.is_done():
            await rep.edit_message(view=vue)
            return True
        if getattr(rep, "type", None) in (
                discord.InteractionResponseType.deferred_message_update,
                discord.InteractionResponseType.message_update):
            await interaction.edit_original_response(view=vue)
            return True
        if msg is None:
            log.warning("%s : menu non remis sur son intitule (pas de message)", quoi)
            return False
        if getattr(getattr(msg, "flags", None), "ephemeral", False):
            await interaction.followup.edit_message(msg.id, view=vue)
        else:
            await msg.edit(view=vue)
        return True
    except Exception as e:                                   # noqa: BLE001
        log.warning("%s : menu non remis sur son intitule (%s: %s)",
                    quoi, type(e).__name__, e)
        return False


async def _jb_menu_deja_redessine(interaction, quoi="panneau") -> bool:
    """True si le message du clic ne porte PLUS le menu choisi : il a ete
    redessine pour un autre etat pendant l'action, et le remettre avec la vue
    du clic le ferait revenir EN ARRIERE.

    Le cas : le redessin de fond a echoue (panne Discord), l'action a dure
    30 s, et pendant ce temps le VA a clique Julia (panneau) ou une autre
    reserve (General). La vue construite au moment du choix est celle de
    Lola / Blonde : la reappliquer apres coup remettait le panneau sur Lola
    alors que _JB_PANNEAU_COURANT disait Julia (simule le 26/09/2026).
    _jb_remettre_epingle fait ce controle pour le redessin de fond ; ce
    repli-ci ne le faisait pas.

    Le custom_id du menu choisi porte tout l'etat (model, quantite et, pour
    le General, reserve) : s'il n'est plus dans le message relu, un autre
    redessin est passe. Ne relit QUE si la reponse est deja partie et que le
    message est du salon : sinon il faut repondre de toute facon
    (edit_message), et un ephemere ne change que par ce clic-ci. Ne leve
    jamais."""
    try:
        if not interaction.response.is_done():
            return False
        msg = getattr(interaction, "message", None)
        if msg is None or getattr(getattr(msg, "flags", None), "ephemeral", False):
            return False
        cid = (getattr(interaction, "data", None) or {}).get("custom_id")
        lire = getattr(getattr(interaction, "channel", None), "fetch_message", None)
        if not cid or lire is None:
            # Rien pour comparer : le chemin d'avant (remise a zero).
            return False
        try:
            frais = await lire(msg.id)
        except discord.NotFound:
            log.info("%s : message %s disparu, rien a remettre", quoi, msg.id)
            return True
        except Exception as e:                               # noqa: BLE001
            # Discord ne repond pas : impossible de savoir ce que montre le
            # message. Le laisser tel quel vaut mieux que risquer de le faire
            # revenir en arriere ; le menu garde seulement son choix.
            log.warning("%s : message %s illisible (%s: %s), menu non remis sur "
                        "son intitule", quoi, msg.id, type(e).__name__, e)
            return True
        if cid in _ids_composants(frais):
            return False
        log.info("%s : message %s deja redessine pour un autre etat (%s absent), "
                 "pas de remise a zero", quoi, msg.id, cid)
        return True
    except Exception as e:                                   # noqa: BLE001
        log.warning("%s : controle avant remise a zero en echec (%s: %s)",
                    quoi, type(e).__name__, e)
        return False


async def _jb_menu_refuser(interaction, texte, vue):
    """Refuse un choix de menu : le menu reprend son intitule ET le VA lit
    pourquoi. UNE reponse (l'edition du message), le texte en suivi
    ephemere. Si l'edition est refusee, le texte part en reponse : le VA
    doit au moins savoir pourquoi rien ne se passe."""
    try:
        await interaction.response.edit_message(view=vue)
    except Exception as e:                                   # noqa: BLE001
        log.warning("refus de menu : message non redessine (%s: %s)",
                    type(e).__name__, e)
        if not interaction.response.is_done():
            await interaction.response.send_message(texte, ephemeral=True)
            return
    await interaction.followup.send(texte, ephemeral=True)


async def _jb_menu_lancer(interaction, cog, model, cle, cmd, supports_count,
                          qty, vue, tache, quoi):
    """Lance l'action choisie dans un menu du panneau, EXACTEMENT comme son
    bouton (_run_for_model), puis s'assure que le menu reprend son intitule
    (_menu_lancer)."""
    await _menu_lancer(
        interaction,
        lambda: cog._run_for_model(interaction, model, cmd, count=qty,
                                   supports_count=supports_count),
        cle, vue, tache, quoi, detail=f" pour {model}")


async def _menu_lancer(interaction, action, cle, vue, tache, quoi, detail=""):
    """Lance `action()` (la coroutine de la variante choisie dans un menu
    deroulant), puis s'assure que le menu reprend son intitule. Sert le
    panneau US, le panneau ephemere et le menu VA.

    `tache` : le redessin deja lance en fond (None s'il n'y en a pas). S'il a
    echoue, ou si l'action n'a pas repondu, on redessine par l'interaction du
    choix -- ce qui repond aussi, quand il le faut -- sauf si le message du
    salon a entre-temps ete redessine pour un autre etat
    (_jb_menu_deja_redessine).

    Une action qui leve ne laisse pas le VA devant « l'interaction a
    echoue » : l'erreur est journalisee et DITE, en ephemere."""
    erreur = ""
    try:
        await action()
    except Exception as e:                                   # noqa: BLE001
        log.exception("%s : action %s%s en echec", quoi, cle, detail)
        erreur = (f"❌ **{_libelle_action(cle)}** : erreur ({type(e).__name__}). "
                  "Réessaie ; si ça recommence, préviens un admin.")
    if not await _jb_tache_ok(tache) or not interaction.response.is_done():
        # `vue` date du choix : si le message a ete redessine pour un autre
        # etat pendant l'action, la reappliquer le ferait revenir en arriere.
        if not await _jb_menu_deja_redessine(interaction, quoi):
            await _jb_menu_remettre(interaction, vue, quoi)
    if erreur:
        try:
            await interaction.followup.send(erreur, ephemeral=True)
        except Exception as e:                               # noqa: BLE001
            log.warning("%s : erreur non annoncee au VA (%s: %s)",
                        quoi, type(e).__name__, e)


_JB_REFUS_ROLE = "🔒 Réservé aux VA **Jailbreak** (rôle « Jailbreak »)."


class _JailbreakQtySelect(discord.ui.Select):
    """Choix de la quantite de media par action (multiplicateur jailbreak).

    Il garde son panneau en reference directe : dans un LayoutView, il vit
    dans une rangee, elle-meme dans un conteneur."""
    def __init__(self, current, panneau=None):
        super().__init__(
            placeholder=f"📦 Quantité : {current} par action",
            min_values=1, max_values=1, options=_jb_qty_options(current))
        self.panneau = panneau

    async def callback(self, interaction: discord.Interaction):
        if not _jb_can_use(interaction):
            await interaction.response.send_message(_JB_REFUS_ROLE, ephemeral=True)
            return
        view = self.panneau or self.view
        if self.values and self.values[0] == _JB_QTY_AUTRE:
            async def _suite(inter, q):
                view.quantity = q
                view._build()
                await inter.response.edit_message(view=view)
            await interaction.response.send_modal(_JBQtyModal(_suite))
            # La fenetre ouverte, le menu afficherait « Autre nombre… » : si
            # le VA la ferme sans rien taper, re-choisir « Autre » ne ferait
            # plus rien. On le redessine par le jeton du panneau.
            if getattr(view, "message", None) is not None:
                view._build()
                _jb_en_fond(view.message.edit(view=view),
                            "panneau Jailbreak : quantite remise apres « Autre »")
            return
        try:
            q = int(self.values[0])
        except Exception:
            q = 3
        view.quantity = q
        view._build()  # reconstruit pour refleter la nouvelle quantite
        await interaction.response.edit_message(view=view)


class _JailbreakActionButton(discord.ui.Button):
    """Un bouton d'action (reel, story, ...) pour une model donnee. Ephemere."""
    def __init__(self, cog, model, label, cmd_attr, supports_count, row=None, key="",
                 icone=None, panneau=None):
        # Icone du serveur si elle existe, sinon on garde le libelle tel quel,
        # emoji standard compris : c est exactement le comportement d avant.
        if icone is not None:
            super().__init__(label=_libelle_sans_emoji(label), emoji=icone,
                             style=discord.ButtonStyle.primary, row=row)
        else:
            super().__init__(label=label, style=discord.ButtonStyle.primary, row=row)
        self.cog = cog
        self.model = model
        self.cmd_attr = cmd_attr
        self.supports_count = supports_count
        self.key = key
        self.panneau = panneau

    async def callback(self, interaction: discord.Interaction):
        if not _jb_can_use(interaction):
            await interaction.response.send_message(_JB_REFUS_ROLE, ephemeral=True)
            return
        cmd = getattr(self.cog, self.cmd_attr, None)
        if cmd is None:
            await interaction.response.send_message("Action indisponible.", ephemeral=True)
            return
        # Le bouton ne redirige plus rien : pseudo et name sont arbitrés par
        # _source_pseudo_name, dans les commandes elles-mêmes, sur le DRAPEAU de
        # l'identité. Ici on s'appuyait sur le rôle Discord du VA et sur le
        # serveur — trois critères pour une seule intention, et les chemins qui
        # ne passaient pas par ce bouton n'arbitraient rien du tout.
        model = self.model
        qty = getattr(self.panneau or self.view, "quantity", 3)
        await self.cog._run_for_model(
            interaction, model, cmd, count=qty, supports_count=self.supports_count)


class _JailbreakFamilleSelect(discord.ui.Select):
    """Le menu d'une famille dans le panneau EPHEMERE (serveurs non-US).

    Ordinaire, pas dynamique : le panneau vit en memoire (model, quantite)
    et expire au bout de 3 minutes. Un element dynamique dans une vue qui
    expire emporterait, a l'expiration, les motifs de TOUS les panneaux US
    (voir _vue_sans_suivi)."""

    def __init__(self, panneau, fam):
        opts, self.inconnues = _jb_options_famille(fam, panneau.icones)
        super().__init__(placeholder=_jb_placeholder_famille(fam),
                         min_values=1, max_values=1, options=opts)
        self.panneau = panneau
        self.famille = fam.cle

    async def callback(self, interaction: discord.Interaction):
        vue = self.panneau
        choix = (self.values or [""])[0]
        fam = _famille_panneau(self.famille)
        refus, cmd, sc = "", None, False
        if not _jb_can_use(interaction):
            refus = _JB_REFUS_ROLE
        elif fam is None or choix not in fam.actions:
            # Une valeur hors de la liste blanche de la famille ne vient pas
            # d'un menu que le bot a pose : on refuse, et on le trace.
            log.warning("panneau Jailbreak : choix %r refuse (famille %r)",
                        choix, self.famille)
            refus = f"Option inconnue (`{choix}`) : rouvre le menu Jailbreak."
        else:
            entree = _jb_action(choix)
            cmd = getattr(vue.cog, entree[2], None) if entree else None
            sc = bool(entree and entree[3])
            if cmd is None:
                refus = f"Action indisponible (`{choix}`)."
        vue._build()                       # le menu reviendra sur son intitule
        if refus:
            await _jb_menu_refuser(interaction, refus, vue)
            return
        # Redessin TOUT DE SUITE, par le jeton de l'interaction qui a pose ce
        # panneau (valable 15 min) : le VA peut reprendre la meme variante
        # sans attendre la fin d'un rendu de 30 s.
        tache = (_jb_en_fond(vue.message.edit(view=vue),
                             "panneau Jailbreak : menu remis sur son intitule")
                 if vue.message is not None else None)
        await _jb_menu_lancer(interaction, vue.cog, vue.model, choix, cmd, sc,
                              vue.quantity, vue, tache, "panneau Jailbreak")


class JailbreakActionsView(discord.ui.LayoutView):
    """Quantite + actions pour UNE model. Ephemere (regeneree a chaque choix).
    us=True -> liste US (Reel caption au lieu du Reel brut).

    MEME DISPOSITION QUE LE PANNEAU US, lue dans la meme table
    (_jb_disposition : _JB_BOUTONS_V2 puis un menu par famille de
    _FAMILLES_PANNEAU), en « Components V2 ». Seule difference : la quantite
    reste un menu deroulant, sur sa rangee a elle, au lieu du bouton.

    Avant, c'etait une vue classique : cinq rangees au plus, et un menu en
    prend une entiere. Elle avait deja plante a la construction (« item would
    not fit at row 0 ») : choisir une model dans le menu Jailbreak des
    serveurs non-US ne repondait plus."""
    def __init__(self, cog, model, quantity=3, us=False, icones=None):
        self.icones = icones or {}
        # 180 s et non 600 : un panneau laisse ouvert apres un changement de
        # model sert l'ANCIENNE identite. Meme duree que le menu des brutes,
        # pour la meme raison.
        super().__init__(timeout=180)
        self.cog = cog
        self.model = model
        self.quantity = quantity
        self.us = us
        self.message = None      # pose par _poser_panneau_jb, pour l'eteindre
        self._hors = []
        self._inconnues = []
        self._build()

    async def on_timeout(self):
        """Eteint le panneau au lieu de le laisser mentir.

        Un ephemere ne disparait pas tout seul : sans ca, celui d'une model
        abandonnee reste cliquable et sert ses medias a la place de ceux de
        la model en cours. En V2 il n'y a pas d'embed : le panneau est
        remplace par une ligne de texte, sans aucun bouton.
        """
        self.clear_items()
        boite = discord.ui.Container(accent_colour=discord.Colour.dark_grey())
        boite.add_item(discord.ui.TextDisplay(
            f"### ⏳ Panneau expiré (model `{self.model}`)\n"
            "Rouvre le menu Jailbreak pour en obtenir un à jour."))
        self.add_item(boite)
        for cle, msg in list(_DERNIER_PANNEAU_JB.items()):
            if msg is self.message:
                _DERNIER_PANNEAU_JB.pop(cle, None)
        try:
            if self.message is not None:
                await self.message.edit(view=self)
        except Exception:
            pass

    def _bouton_action(self, key):
        entree = _jb_action(key)
        if entree is None:
            return None
        _k, label, cmd_attr, sc = entree
        return _JailbreakActionButton(
            self.cog, self.model, label, cmd_attr, sc, key=key,
            icone=self.icones.get(key), panneau=self)

    def _build(self):
        ui = discord.ui
        self.clear_items()
        disposition, self._hors = _jb_disposition()
        self._inconnues = []
        rangees = {}
        for sorte, cle, rangee in disposition:
            if sorte == "qte":
                continue                   # la quantite a sa rangee a elle
            if sorte == "menu":
                fam = _famille_panneau(cle)
                menu = _JailbreakFamilleSelect(self, fam)
                self._inconnues += menu.inconnues
                if not menu.options:
                    # Un menu sans option serait refuse par Discord, et le
                    # panneau ENTIER avec lui : on le retire, en le disant.
                    self._inconnues.append(f"menu {fam.nom}")
                    continue
                rangees.setdefault(rangee, ui.ActionRow()).add_item(menu)
                continue
            b = self._bouton_action(cle)
            if b is None:
                self._inconnues.append(cle)
                continue
            rangees.setdefault(rangee, ui.ActionRow()).add_item(b)
        boite = ui.Container(accent_colour=discord.Colour.dark_red())
        boite.add_item(ui.TextDisplay(self._texte()))
        qte = ui.ActionRow()
        qte.add_item(_JailbreakQtySelect(self.quantity, panneau=self))
        boite.add_item(qte)
        for r in sorted(rangees):
            boite.add_item(rangees[r])
        self.add_item(boite)

    def _texte(self):
        lignes = [f"## 🔓 {self.model.capitalize()} — que veux-tu générer ?",
                  f"📦 **Quantité : {self.quantity} média par action** "
                  "— change-la dans le menu juste en dessous ; elle est "
                  "plafonnée au stock dispo de la model.",
                  "ℹ️ *Pseudo* et *Name* en donnent toujours 5 (sans quantité)."]
        if self._hors:
            lignes.append(_jb_note_hors(self._hors))
        if self._inconnues:
            lignes.append(f"⚠️ {len(self._inconnues)} action(s) introuvable(s), "
                          "sans bouton : " + ", ".join(self._inconnues)
                          + " (à signaler à un admin).")
        lignes.append("Choisis une action 👇")
        return "\n".join(lignes)


class _DejaPret(Exception):
    """Signal interne : la variante vient de la reserve, rien a generer.

    Une exception plutot qu un « if » parce que la preparation du dossier de
    brutes vit deja dans le try : la sauter proprement demanderait sinon de
    dupliquer tout le bloc.
    """


def draft_caption(cap: dict, block: dict) -> dict:
    """Le brouillon que le moteur attend pour incruster UNE caption.

    Extrait de _gen_and_send_caption pour que la reserve de videos
    pre-generees fabrique EXACTEMENT ce que le bouton fabriquerait. Deux
    copies de cette recette divergeraient : la reserve servirait alors des
    videos qui ne ressemblent plus a ce que le clic produit, et rien ne le
    signalerait.
    """
    import json as _js
    gp = block.get("global_pos") or {}
    seg = {"text": cap.get("text") or "", "start": None, "end": None,
           "x": gp.get("x", 0.5) if gp.get("enabled") else cap.get("x", 0.5),
           "y": gp.get("y", 0.2) if gp.get("enabled") else cap.get("y", 0.5)}
    for k in ("wrapW", "lineSpacing"):
        if cap.get(k) is not None:
            seg[k] = cap[k]
    return {"segments": _js.dumps([seg]),
            "font": block.get("font") or "TikTokSans",
            "style": _js.dumps(block.get("style") or {})}


def _captions_block(identity):
    """Bloc caption d'une identité (data/captions.json, écrit par le site).
    {font, style, global_pos, items:[{id,text,desc?,x,y,wrapW?,enabled}]}."""
    import json as _js
    p = DATA_DIR / "captions.json"
    try:
        lib = _js.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    b = lib.get((identity or "").lower().strip()) if isinstance(lib, dict) else None
    return b if isinstance(b, dict) else {}


def _pick_fresh(pool, used, key):
    """Tire un élément non encore servi ; repart du début quand tout a servi
    (évite 2 fois la même caption/brute tant qu'il en reste d'autres)."""
    fresh = [x for x in pool if key(x) not in used]
    if not fresh:
        used.clear()
        fresh = list(pool)
    pick = random.choice(fresh)
    used.add(key(pick))
    return pick


def _identity_pp_file(ident):
    """Fichier image de la PP d'une identité : avatar.* sinon 1re profile_pic."""
    base = IDENTITIES_DIR / (ident or "").lower().strip()
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = base / f"avatar.{ext}"
        if p.exists():
            return p
    pdir = base / "profile_pics"
    if pdir.exists():
        for p in sorted(pdir.iterdir()):
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                return p
    return None


def _identity_emoji_name(ident):
    import re as _re
    return ("id" + _re.sub(r"[^a-z0-9_]", "", (ident or "").lower()))[:32]


# Les icones du menu, dessinees dans le style du site (outils_icones_discord.py).
# Cle d action -> nom de l emoji sur le serveur. Le prefixe « va » evite de
# heurter un emoji deja present, et les noms restent en [a-z] : Discord refuse
# le reste.
_ICONES_ACTIONS = {
    "reelcaption": "vareelcaption",
    "reelmonte": "vareelmonte",
    "story": "vastory",
    "post": "vapost",
    "storycta": "vastorycta",
    "pseudo": "vapseudo",
    "name": "vaname",
    "bio": "vabio",
    "pp": "vapp",
    "brute": "vabrute",
    "capbanger": "vacapbanger",
    "montagebanger": "vamontagebanger",
    "templatebrut": "vatemplatebrut",
    "templateflash": "vatemplateflash",
    "templateflashbanger": "vatemplateflashbanger",
    "templateflashbrut": "vatemplateflashbrut",
    "brutbanger": "vabrutbanger",
    # Les trois dernieres du panneau : la variante marquee du Template, les
    # Trends, et « Choisir ma brute ». Leurs dessins existaient dans
    # outils_icones_discord.py depuis leur ajout au menu, mais la table ne les
    # citait pas : les boutons gardaient donc leur emoji standard, et
    # personne ne le voyait — un emoji standard n'a pas l'air d'un oubli.
    "templatebanger": "vatemplatebanger",
    "trend": "vatrend",
    "brutchoix": "vabrutchoix",
    # Les quatre Trash partagent UNE icone (le template et la marque Trash) :
    # un serveur sans boost n'a que 50 emplacements d'emoji, partages avec la
    # PP de chaque model. Les etoiles restent dans le libelle
    # (_libelle_sans_emoji les garde) : c'est elles qui distinguent les
    # variantes, pas l'icone.
    **{_a: "vatemplatetrash" for _a in marques_montage.marque("trash")["actions"]},
    # « captionbrut » est parti d'ici : le bouton a quitte le menu le
    # 21/08 (il envoyait le meme couple brute ⭐ + caption ⭐ que « Montage »,
    # mais la caption en texte a recopier). Seules restent la commande
    # /captionbrut et sa rangee de repli, qui n'ont pas besoin d'icone. Le
    # fichier vacaptionbrut.png est GARDE : il a ete dessine a la main hors
    # du generateur et ne se reconstruit pas.
}


def icones_actions(guild) -> dict:
    """{cle d action: emoji} — LECTURE SEULE, instantanee.

    Appelee au clic : discord.py garde deja les emojis du serveur en memoire,
    donc rien ne part sur le reseau. Televerser ici ferait treize appels API
    dans le delai de 3 s d une interaction, et le bouton paraitrait mort.
    """
    if guild is None:
        return {}
    presents = {e.name: e for e in getattr(guild, "emojis", [])}
    return {cle: presents[nom] for cle, nom in _ICONES_ACTIONS.items()
            if nom in presents}


async def ensure_action_emojis(guild) -> dict:
    """Televerse une fois les icones manquantes. Appelee quand on POSTE un
    menu, jamais au clic.

    Best-effort : serveur plein, permission retiree, fichier absent — on
    renvoie ce qu on a, et les boutons gardent leur emoji standard. Un menu
    sans icone reste utilisable ; un menu qui plante, non.
    """
    out = {}
    if guild is None:
        return out
    presents = {e.name: e for e in getattr(guild, "emojis", [])}
    dossier = Path(__file__).resolve().parent.parent / "emojis"
    for cle, nom in _ICONES_ACTIONS.items():
        if nom in presents:
            out[cle] = presents[nom]
            continue
        f = dossier / f"{nom}.png"
        if not f.exists():
            continue
        try:
            data = f.read_bytes()
            if len(data) > 256000:          # limite Discord
                continue
            out[cle] = await guild.create_custom_emoji(
                name=nom, image=data, reason="icones du menu VA (style du site)")
            # Plusieurs actions partagent une icone (les quatre Trash) : sans
            # cette ligne, chacune televersait SA copie, et Discord accepte
            # les doublons de nom -- quatre emplacements pour une image.
            presents[nom] = out[cle]
        except Exception as e:
            log.warning(f"emoji action {nom}: {e}")
    return out


#: Le marqueur « contenu etoile ». Il n'est PAS un emoji de decor : il compte.
ETOILE = "⭐"


def _libelle_sans_emoji(label: str):
    """(texte,) sans son emoji de categorie, mais AVEC ses etoiles.

    Les libelles portent leur emoji dans la CHAINE (« 💬 Reel caption »). Pour
    poser une icone du serveur a la place, il faut retirer celui-la, sinon on
    en affiche deux.

    LES ETOILES DE TETE SURVIVENT.
        Elles ne decorent pas : il y en a UNE par ingredient marque qu'exige
        l'action. Les couper avec le reste faisait disparaitre la seule
        difference entre « Video brut » et « Video brut etoile », qui
        s'affichaient alors identiques dans le menu — deux boutons au meme nom,
        et personne pour deviner lequel prend quoi.
    """
    texte = (label or "").strip()
    etoiles = ""
    while texte.startswith(ETOILE):
        etoiles += ETOILE
        texte = texte[len(ETOILE):].lstrip()
    bouts = texte.split(" ", 1)
    if len(bouts) == 2 and bouts[0] and not bouts[0][0].isalnum():
        texte = bouts[1]
    return (etoiles + " " + texte) if etoiles else texte


async def ensure_identity_emojis(guild, models):
    """Crée (une seule fois) un emoji serveur par model à partir de sa PP, pour
    l'afficher dans le select. -> {identité: PartialEmoji}. Best-effort : une
    model sans PP (ou serveur plein) garde simplement son option sans image."""
    out = {}
    if guild is None:
        return out
    have = {e.name: e for e in getattr(guild, "emojis", [])}
    for m in models:
        name = _identity_emoji_name(m)
        if name in have:
            out[m] = have[name]
            continue
        src = _identity_pp_file(m)
        if not src:
            continue
        try:
            from PIL import Image
            import io as _io
            im = Image.open(src).convert("RGBA")
            im.thumbnail((128, 128))
            buf = _io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            data = buf.getvalue()
            if len(data) > 256000:            # limite Discord
                continue
            out[m] = await guild.create_custom_emoji(
                name=name, image=data, reason="PP de la model dans le menu")
        except Exception as e:
            log.warning(f"emoji PP {m}: {e}")
    return out


# (_JailbreakModelSelect et l'ancien JailbreakMenuView -- UN menu deroulant
#  coupe a 25 -- ont disparu le 26/09/2026 : le menu des models est en
#  « menus de 10 » (JailbreakModelsView, plus bas). Les messages deja postes
#  qui portent « jbmenu:model » / « jbmenuus:model » sont servis par
#  JBMenuModelsAncien.)


def _grappes_texte(s: str) -> list:
    """Decoupe une chaine en DESSINS, pas en caracteres.

    Une pastille chiffree vaut trois points de code (« 4 », le selecteur de
    variante, la marque d'encadrement). Couper entre eux laisse un « 4 » nu
    au bout du libelle -- exactement le chiffre nu qu'on vient de remplacer.
    """
    out = []
    for ch in s:
        colle = ch in "\uFE0F\u20E3\u200D" or (out and out[-1][-1] == "\u200D")
        if out and colle:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _long_discord(s: str) -> int:
    """La longueur que DISCORD compte, pas celle que voit len().

    Discord mesure en unites UTF-16 : une medaille, hors du plan de base, y
    vaut DEUX alors que len() en compte une. Un libelle juste sous la limite
    passait donc le controle ici et se faisait refuser la-bas -- et un seul
    libelle refuse fait echouer TOUT le message du menu, sans rien afficher.
    Le risque etait theorique tant que les rangs tenaient en un caractere ;
    depuis que chaque ligne porte un badge de trois a six, il ne l'est plus.
    """
    return len(s.encode("utf-16-le")) // 2


def _couper_discord(s: str, limite: int) -> str:
    """Coupe a `limite` unites Discord, sans casser un dessin en deux."""
    if _long_discord(s) <= limite:
        return s
    out, pris = [], 0
    for g in _grappes_texte(s):
        c = _long_discord(g)
        if pris + c > limite:
            break
        out.append(g)
        pris += c
    return "".join(out)


def _libelle_model(ident, libelles=None) -> str:
    """Le libelle d une model dans les menus : « 🏅④ Lola — Caption + Template ».

    Cette phrase annoncait « 3. Lola 💬⚡ » : les deux moities du format ont
    change depuis (le rang porte un badge, les styles s ecrivent en toutes
    lettres) et l exemple decrivait un menu que plus personne ne voit. Un
    commentaire faux coute plus cher que pas de commentaire.

    Le rang vient de identites_ordre, les pastilles de identity_styles — la
    MEME table que celle des pastilles du site. Tout ce qui affiche des
    models passe par ici -- depuis le 26/09/2026, les « menus de 10 »
    (_jb_models_entrees) et donc /demomodels ; avant, la grille et le menu
    unique --, sinon l un garde les vieux libelles au premier style ajoute.

    Le libelle est plafonne a 80 (limite d'un bouton, sous les 100 d'une
    option de menu) : on coupe le NOM,
    jamais les styles, sinon la coupe emporte precisement ce qu on vient
    d ajouter.
    """
    base = (libelles or {}).get(ident) or str(ident).capitalize()
    try:
        import identity_styles as _ist
        # EN TOUTES LETTRES, PAS EN PASTILLES. « 💬⚡ » arrive nu dans un menu
        # Discord, sans la legende qui l'accompagne sur le site : le
        # proprietaire l'a dit, « les emojis, ils n'arrivent pas a
        # comprendre ». « Template + Caption » se lit sans avoir appris un
        # code.
        past = _ist.mots(ident)
    except Exception:
        past = ""
    if not past:
        return _couper_discord(base, 80)
    # Le libelle d'un bouton Discord est plafonne a 80. On coupe le NOM,
    # jamais les styles : la coupe emporterait precisement ce qu'on vient de
    # rendre lisible. Les 3 retires sont le « — » et ses deux espaces.
    place = 80 - _long_discord(past) - 3
    if _long_discord(base) > place:
        base = _couper_discord(base, max(1, place - 1)) + "…"
    # DERNIER FILET, et il n'est pas decoratif : quand `past` mange a lui seul
    # les 80 unites, `place` tombe a zero ou moins et la ligne du dessus rend
    # un libelle PLUS LONG que la limite -- Discord refuse alors tout le
    # message du menu, sans rien afficher. Aujourd'hui `mots()` plafonne a
    # quatre styles (~34 unites) et le cas ne se produit pas ; un cinquieme
    # style suffirait a le declencher, et personne ne ferait le lien.
    return _couper_discord(f"{base} — {past}", 80)


class JBModelButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"jbus:m:(?P<ident>[a-z0-9_.\-]+)"):
    """UN bouton = UNE model (sa PP + son nom), clic = actions direct.
    custom_id porte l'identité -> persistant même si la liste des models change.

    PLUS POSE DEPUIS LE 26/09/2026 : le menu des models est passe en « menus
    de 10 » (JailbreakModelsView, JBModelsMenu). Les grilles deja epinglees le
    portent jusqu'a leur conversion : un clic fait exactement ce qu'il
    faisait (_jb_model_refus, puis _jb_model_ouvrir -- le MEME parcours que
    le menu deroulant), et convertit la grille au passage."""

    def __init__(self, ident, emoji=None, libelle=None):
        self.ident = (ident or "").lower()
        # Le libelle est calcule par l appelant, qui seul connait la LISTE
        # affichee — donc le vrai numero. from_custom_id ne le repasse pas :
        # ce chemin ne sert qu a repondre au clic, l affichage vient du
        # message deja poste.
        super().__init__(
            discord.ui.Button(
                label=libelle or self.ident.capitalize(), emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"jbus:m:{self.ident}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["ident"])

    async def callback(self, interaction: discord.Interaction):
        refus = _jb_model_refus(interaction, self.ident)
        if refus:
            await interaction.response.send_message(refus, ephemeral=True)
            return
        await _jb_model_ouvrir(interaction, self.ident)


def _jb_model_refus(interaction, ident, marche=None) -> str:
    """Pourquoi le choix de `ident` est refuse, ou "". LES gardes du choix
    d'une model, communes au bouton-photo (JBModelButton), au menu deroulant
    (JBModelsMenu) et a l'ancien menu unique (JBMenuModelsAncien) : deux
    copies divergeraient au premier correctif.

    `marche` (menus deroulants) : la valeur choisie doit aussi etre une des
    models de ce marche. Elle arrive de Discord, pas d'une liste que le bot
    tient en main : sans ce controle, une valeur forgee -- ou une model
    desactivee depuis que le menu a ete poste -- ouvrirait son panneau. Le
    bouton n'en a pas besoin : son identite est dans SON custom_id, pose
    par le bot (et un ancien bouton doit continuer de faire ce qu'il
    faisait)."""
    if not _jb_can_use(interaction):
        return _JB_REFUS_ROLE
    idl = (ident or "").strip().lower()
    # Une grille DEJA postee peut encore porter le bouton d'une entree
    # devenue reserve depuis (le rafraichissement peut echouer). Sans ce
    # refus, le panneau d'actions servirait son contenu comme celui d'une
    # model, monte sur SES brutes -- qu'une reserve n'a pas. AVANT le
    # controle du marche : une reserve n'est jamais dans la liste, et le VA
    # doit lire POURQUOI (la phrase de type_identite), pas « inconnue ».
    refus = _refus_reserve_jb(idl)
    if refus:
        return refus
    if marche is not None:
        if not idl or idl not in {str(n).strip().lower()
                                  for n in _jb_models_marche(marche)}:
            log.warning("menu des models %s : choix %r refuse (pas une model "
                        "du marche)", marche, ident)
            return (f"⚠️ **{_couper_discord(str(ident or '?'), 60)}** n'est pas "
                    f"(ou plus) dans les models {str(marche).upper()} : le menu "
                    "vient d'être remis à jour, choisis ta model dedans.")
    if interaction.client.get_cog("UserCog") is None:
        return "Indisponible."
    return ""


async def _jb_model_ouvrir(interaction, ident):
    """Ouvre les actions de la model `ident`, gardes deja passees
    (_jb_model_refus). Le MEME parcours pour le bouton-photo, le menu
    deroulant et l'ancien menu unique ; il repond TOUJOURS a l'interaction.

    Puis, si le clic vient d'un menu des models encore a l'ancien format
    (grille de boutons, ou un seul menu coupe a 25), il le convertit en
    « menus de 10 » -- apres coup : la reponse est deja partie."""
    cog = interaction.client.get_cog("UserCog")
    if cog is None:
        await interaction.response.send_message("Indisponible.", ephemeral=True)
        return
    await _jb_model_panneau(interaction, cog, (ident or "").lower())
    await _jb_menu_models_convertir(interaction)


async def _jb_model_panneau(interaction, cog, ident):
    """Le corps de l'ancien JBModelButton.callback : panneau ephemere hors
    serveur US, panneau PERMANENT du salon sur le serveur US (accuse de
    reception d'abord, puis edition, conversion, replis), puis le ✨ General."""
    try:
        import guild_features as gf
        us = gf.is_us_guild(getattr(interaction, "guild", None))
    except Exception:
        us = False
    # Le MARCHE du VA (role @Jailbreak FR / US) decide des actions, pas le
    # serveur : un VA FR sur le serveur US garde le menu FR.
    _marche = marche_du_membre(interaction.user)
    if not us:
        view = JailbreakActionsView(cog, ident, us=(_marche != "fr"),
                                    icones=icones_actions(interaction.guild))
        await _poser_panneau_jb(interaction, view)
        return
    # Serveur US : on met a jour le PANNEAU PERMANENT du salon au lieu
    # d'envoyer un message ephemere qui disparait au rafraichissement.
    #
    # ACCUSER RECEPTION D'ABORD, avant tout appel a Discord. Un defer de
    # composant ne change rien a l'ecran ; il ne fait que tenir les 3 s.
    # Avant, il suivait l'edition du panneau : trois choix en moins de 5 s
    # epuisaient le compteur des editions du salon (menu, panneau, General),
    # discord.py faisait attendre la 3e edition du panneau, le defer partait
    # apres les 3 s et levait NotFound (10062) -- que le `except NotFound`
    # de l'edition prenait pour « panneau supprime » : un SECOND panneau
    # epingle, et le ✨ General reste sur l'ancienne model (simule le
    # 26/09/2026 avec un faux Discord a compteur d'editions par salon).
    # Un accuse refuse ne bloque pas le choix : le panneau et le General sont
    # des messages du salon, ils se mettent a jour sans l'interaction.
    accuse = await _jb_accuser(interaction, "panneau US")
    vue = _jb_panel(cog, ident, 3, marche=_marche,
                    guild=interaction.guild)
    chan = interaction.channel
    moi = getattr(getattr(interaction.client, "user", None), "id", None)
    msg_id = _jb_panel_ids().get(str(getattr(chan, "id", 0)))
    cible = None
    try:
        if msg_id:
            cible = await chan.fetch_message(int(msg_id))
    except Exception:
        cible = None
    if cible is None:                      # panneau introuvable -> on le cherche
        try:
            for m in await chan.pins():
                # Les DEUX formats : l'ancien (pied d'embed) et le V2
                # (ligne-marque dans le texte). Rater l'un, c'etait poster
                # un second panneau a cote du premier.
                if _est_panneau_actions(m, moi):
                    cible = m
                    break
        except Exception:
            cible = None
    panneau_pose = False
    recree = cible is None
    try:
        if cible is not None:
            # Le try ne couvre QUE l'edition du panneau : un NotFound y veut
            # dire « panneau supprime entre-temps ». Il couvrait aussi le
            # defer, dont le NotFound (10062, accuse trop tard) faisait
            # poser un second panneau a cote du premier, deja edite.
            try:
                # Un ancien panneau (embed) passe en V2 par cette edition :
                # _jb_kw_format vide son texte et son embed.
                await cible.edit(view=vue, **_jb_kw_format(cible))
            except discord.NotFound:
                cible = None               # supprime entre-temps : on le repose
            except discord.HTTPException as e:
                # Conversion refusee par Discord : un NOUVEAU panneau V2
                # prend sa place (epingle, id memorise), l'ancien part.
                await _jb_panneau_reposer(
                    interaction.client, chan, cible, vue, ident,
                    f"edition refusee ({type(e).__name__}: {e})",
                    general=False)
                recree = True
        if cible is None:
            nouveau = await chan.send(view=vue)
            _jb_panel_set(chan.id, nouveau.id)
            try:
                await nouveau.pin()
            except Exception as e:
                log.warning("panneau US %s : pose mais non epingle (%s: %s)",
                            getattr(chan, "name", "?"), type(e).__name__, e)
            recree = True
        panneau_pose = True
    except Exception as e:
        log.warning("panneau US %s : non pose dans le salon (%s: %s) -- "
                    "envoye en ephemere", getattr(chan, "name", "?"),
                    type(e).__name__, e)
        # Le panneau en ephemere, mais SANS suivi : voir _vue_sans_suivi.
        # Suivi, il expirait au bout de 15 minutes et emportait les
        # motifs de TOUS les panneaux US du serveur. Une vue NEUVE : la
        # premiere a peut-etre ete rangee par un envoi a moitie reussi.
        secours = _vue_sans_suivi(_jb_panel(cog, ident, 3, marche=_marche,
                                            guild=interaction.guild))
        # L'accuse est deja parti : le panneau de secours suit en ephemere.
        # S'il a ete refuse, l'interaction est morte -- plus rien ne peut
        # atteindre le VA ; on le dit au journal au lieu de lever, sinon la
        # suite (etat retenu, sous-menus) sauterait.
        try:
            if accuse:
                await interaction.followup.send(view=secours, ephemeral=True)
            elif not interaction.response.is_done():
                await interaction.response.send_message(view=secours,
                                                        ephemeral=True)
        except Exception as e2:                              # noqa: BLE001
            log.warning("panneau US %s : panneau de secours non envoye non "
                        "plus (%s: %s) -- le VA n'a aucun panneau pour %s",
                        getattr(chan, "name", "?"), type(e2).__name__, e2,
                        ident)
    # Les sous-menus de famille ouverts portent l'ANCIENNE model dans
    # leurs boutons : on les efface, et on retient ce que montre le
    # panneau pour refuser ceux qu'on n'a plus le droit d'effacer.
    # Panneau de secours (ephemere) : l'epingle n'a pas change, l'etat
    # devient inconnu plutot que faux.
    _jb_panneau_noter(getattr(chan, "id", 0),
                      ident if panneau_pose else None, 3)
    await _jb_sous_menus_fermer(channel_id=getattr(chan, "id", 0) or 0)
    # Le ✨ General suit la model choisie, APRES le defer et dans son
    # propre try : le except du dessus repond par send_message, qui
    # leverait InteractionResponded si la reponse etait deja partie.
    # Panneau recree (absent, ou conversion refusee) : le General est
    # REPOSTE, sinon il resterait au-dessus du nouveau panneau. Panneau
    # non pose : on ne touche a rien, le salon a un probleme que le
    # General n'arrangera pas.
    if panneau_pose:
        try:
            await _jb_general_maj(interaction.client, chan, ident,
                                  interaction.guild,
                                  reposter=recree)
        except Exception as e:
            log.warning("General %s / %s : non mis a jour (%s: %s)",
                        getattr(chan, "name", "?"), ident,
                        type(e).__name__, e)


# ---------------------------------------------------------------------------
# MENU DES MODELS EN « MENUS DEROULANTS DE 10 » (26/09/2026).
#
# Avant : une grille de boutons-photos coupee a 25 -- cinq rangees de cinq,
# la limite d'un message classique -- et, pour /menujailbreak, UN menu
# deroulant coupe lui aussi a 25. Au-dela, les models disparaissaient sans
# un mot. Le proprietaire a essaye les dispositions de /demomodels (bot
# admin) et choisi « Menus deroulants de 10 » : « c'est ca, mets deja ca sur
# le bot ».
#
# Un bloc « Components V2 » : le texte de l'ancien embed en tete, puis UN MENU
# PAR DIZAINE, dans l'ordre de production (identites_ordre), intitules
# « 👤 1–10… », « 👤 11–20… ». Un menu de plus se cree tout seul a chaque
# dizaine franchie. Le V2 compte les composants (40 au plus) au lieu des
# rangees : le bloc et son texte en prennent 2, chaque menu 2 (sa rangee et
# lui), soit 19 menus -- 190 models. Au-dela : journalise ET dit dans le
# texte, jamais ecarte en silence.
#
# LA DISPOSITION VIT ICI ET NULLE PART AILLEURS : /demomodels appelle
# _jb_menus_de_10 et _jb_menus_models_poser au lieu d'en garder une copie --
# une maquette qui diverge de la production montre un menu qui n'existe pas.
#
# Repere : la derniere ligne du texte, « -# menu-models-<marche> » (le V2
# n'a pas d'embed). L'ancien format (embed « Menu Jailbreak … ») reste
# reconnu partout (_est_menu_models) jusqu'a sa conversion, au premier clic
# ou au prochain rafraichissement.

#: Models par menu : « si un jour j'en ai 60, il y en a 6 » (le proprietaire).
_JB_MM_TAILLE = 10
#: 40 composants au plus dans un message V2 : 2 pour le bloc et son texte,
#: 2 par menu (sa rangee + lui).
_JB_MM_MAX_MENUS = (40 - 2) // 2
_JB_MM_PIED = "menu-models"
_JB_MM_MARCHES = ("fr", "us")
#: Plafond Discord d'une valeur d'option de menu deroulant.
_JB_MM_VALEUR_MAX = 100


def _jb_menu_models_marque(marche) -> str:
    """La ligne-marque du menu V2 : « -# menu-models-us » (petit gris)."""
    return f"-# {_JB_MM_PIED}-{marche}"


def _jb_plage(debut: int, fin: int) -> str:
    """« 11–20 », numerotation du VA (a partir de 1) ; « 21 » s'il est seul."""
    return f"{debut}–{fin}" if fin > debut else f"{debut}"


def _jb_menus_de_10(items):
    """LA disposition du menu des models, sans Discord.

    -> (menus [(plage, bloc)], reste) : un menu par dizaine d'`items`, dans
    leur ordre, au plus _JB_MM_MAX_MENUS ; `reste` = ce qui ne tient pas.
    Chaque item finit dans EXACTEMENT un menu, ou dans `reste` -- a
    l'appelant de le dire (JailbreakModelsView le journalise et l'ecrit).
    Les items sont quelconques : la demo y met ses fausses models."""
    menus, reste, k = [], list(items or []), 0
    while reste and len(menus) < _JB_MM_MAX_MENUS:
        bloc, reste = reste[:_JB_MM_TAILLE], reste[_JB_MM_TAILLE:]
        menus.append((_jb_plage(k + 1, k + len(bloc)), bloc))
        k += len(bloc)
    return menus, reste


def _jb_menus_models_poser(vue, texte, menus, fabrique):
    """Remplit `vue` (une LayoutView) : un bloc a accent rouge fonce, le
    texte en tete, puis une rangee par menu, `fabrique(i, plage, bloc)`
    fournissant le menu. La production y passe JBModelsMenu, la demo son
    menu inerte : meme bloc, meme ordre, meme accent."""
    ui = discord.ui
    boite = ui.Container(accent_colour=discord.Colour.dark_red())
    boite.add_item(ui.TextDisplay(texte))
    for i, (plage, bloc) in enumerate(menus):
        rangee = ui.ActionRow()
        rangee.add_item(fabrique(i, plage, bloc))
        boite.add_item(rangee)
    vue.add_item(boite)
    return vue


def _jb_emojis_presents(guild, models) -> dict:
    """{model: emoji de sa PP} -- LECTURE SEULE des emojis deja crees sur le
    serveur. Au clic (remise a zero, conversion), pas le temps d'en creer :
    c'est ensure_identity_emojis, au moment de POSTER, qui s'en charge."""
    presents = {e.name: e for e in (getattr(guild, "emojis", None) or [])}
    out = {}
    for m in models or []:
        e = presents.get(_identity_emoji_name(m))
        if e is not None:
            out[m] = e
    return out


def _jb_models_entrees(models, emojis=None):
    """[(valeur, libelle, emoji)] dans l'ordre de production, et les rejets
    [(nom, raison)].

    Libelles d'apres la liste ENTIERE (_io.etiqueter) : au-dela de 25 le
    rang continue -- l'ancienne grille ne numerotait que ses 25 visibles.
    Une valeur doit etre unique dans un menu et tenir en 100 caracteres :
    sinon Discord refuse le message ENTIER. Ce qui ne le peut pas est rejete
    ET rendu, pour etre dit."""
    import identites_ordre as _io
    ordre = _io.lire()
    tri = _io.trier(list(models or []), ordre)
    libelles = _io.etiqueter(tri, ordre)
    emojis = emojis or {}
    entrees, rejets, vues = [], [], set()
    for m in tri:
        valeur = str(m).strip().lower()
        if not valeur or len(valeur) > _JB_MM_VALEUR_MAX:
            rejets.append((m, "nom vide ou trop long"))
            continue
        if valeur in vues:
            rejets.append((m, "en double"))
            continue
        vues.add(valeur)
        entrees.append((valeur, _libelle_model(m, libelles), emojis.get(m)))
    return entrees, rejets


def _jb_menu_models_texte(marche, models, guild=None) -> str:
    """Le texte en tete du menu : celui de l'ancien embed, titre compris.

    La derniere phrase dit qui peut s'en servir, d'apres _jb_can_use : sur
    le serveur US, tout le monde ; ailleurs, le role « Jailbreak ».
    L'ancien menu affirmait « ouvert a tout le monde » sur les deux, et
    /menujailbreak (serveur FR) le contraire -- avec une seule vue pour les
    deux, c'est la regle appliquee qui tranche. Sans serveur connu : la
    phrase d'avant."""
    # Un classement ne sert a rien si personne ne sait que c en est un :
    # sans cette phrase, « 1. Lola » n est qu une liste numerotee de plus.
    # Elle est vide tant qu aucune model affichee n a ete rangee a la main.
    import identites_ordre as _io
    _clst = _io.phrase_classement(models)
    # LE MOT AU BOUT DE LA LIGNE NE SE DEVINE PAS. « Genesaag — Caption »
    # ne dit rien tant qu'on n'a pas appris que ce mot designe ce qui
    # marche sur ce compte-la. Le proprietaire : « brut c'est que cette
    # identite marche plus avec du brut, caption avec de la caption ».
    # La legende ne liste QUE les styles presents dans ce menu : expliquer
    # un mot que personne ne porte, c'est une ligne de plus entre le VA et
    # le menu qu'il cherche.
    _leg = ""
    try:
        import identity_styles as _ist
        _lignes = _ist.legende(models)
    except Exception:
        _lignes = []
    if _lignes:
        _leg = ("**Le mot après le tiret dit ce qui marche pour elle :**\n"
                + "\n".join("• **%s** — %s" % (lab, txt)
                            for lab, txt in _lignes))
    acces = "Ce menu est ouvert à tout le monde sur ce serveur."
    if guild is not None:
        try:
            import guild_features as _gf
            if not _gf.is_us_guild(guild):
                acces = "Réservé aux membres portant le rôle **Jailbreak**."
        except Exception:                                    # noqa: BLE001
            pass
    titre = ("Menu Jailbreak FR — models FR" if marche == "fr"
             else "Menu Jailbreak US — models US")
    return (f"## {titre}\n"
            "Choisis une model ci-dessous, puis l'action à réaliser : "
            "reel, reel monté, story, post, story CTA, pseudo, name, "
            "bio ou pp.\n\n"
            + (_clst + "\n\n" if _clst else "")
            + (_leg + "\n\n" if _leg else "")
            + acces)


def _jb_texte_v2_borne(corps, pied, quoi="menu des models") -> str:
    """`corps` puis les lignes `pied` (gardees ENTIERES : alertes, marque),
    en _JB_TEXTE_V2_MAX unites Discord au plus. Un texte trop long fait
    refuser le message entier : le corps est coupe, et c'est journalise."""
    pied = "\n".join(l for l in pied if l)
    place = _JB_TEXTE_V2_MAX - (_long_discord(pied) + 1 if pied else 0)
    if _long_discord(corps) > place:
        log.warning("%s : texte coupe (%d unites Discord pour %d de place)",
                    quoi, _long_discord(corps), place)
        corps = _couper_discord(corps, max(0, place - 1)) + "…"
    return corps + ("\n" + pied if pied else "")


def _jb_noms(noms, n=8) -> str:
    """« Lola, Emma, … (+3) » : quelques noms, et le compte du reste."""
    noms = [str(x) for x in noms]
    txt = ", ".join(_couper_discord(x, 40) for x in noms[:n])
    return txt + (f" (+{len(noms) - n})" if len(noms) > n else "")


class JBModelsMenu(discord.ui.DynamicItem[discord.ui.Select],
                   template=r"jbus:ms:(?P<marche>fr|us):(?P<n>\d{1,3})"):
    """Un menu deroulant du menu des models : la dizaine `n` du marche.

    Rien d'autre dans le custom_id : la model choisie arrive avec le clic.
    Il repond donc apres un redemarrage (from_custom_id), et un menu poste
    avant l'ajout d'une model sert encore -- la valeur est VALIDEE contre la
    liste du moment (_jb_model_refus), jamais crue sur parole.

    Au choix : les gardes communes, puis EXACTEMENT le parcours du bouton-
    photo (_jb_model_ouvrir) ; et le menu reprend son intitule, sans quoi
    re-choisir la meme model ne declencherait rien (_menu_lancer).

    Prefixe « jbus:ms: » : discord.py lance TOUS les motifs dynamiques qui
    correspondent a un custom_id ; celui-ci ne recoupe aucun jbus:m/s/a/q/
    qb/f, ni jbg:."""

    def __init__(self, marche, n, plage="", bloc=()):
        self.marche = marche if marche in _JB_MM_MARCHES else "us"
        self.n = int(n)
        opts = [discord.SelectOption(label=lib, value=valeur, emoji=emoji)
                for valeur, lib, emoji in bloc]
        #: Aucune option : seul un vieux custom_id qui revient construit ce
        #: menu vide (from_custom_id) ; la vue n'en pose jamais.
        self.vide = not opts
        if not opts:
            opts = [discord.SelectOption(label="(aucune model)", value="_")]
        super().__init__(discord.ui.Select(
            placeholder=(f"👤 {plage}…" if plage else "👤 Choisis une model…"),
            min_values=1, max_values=1, options=opts,
            custom_id=f"jbus:ms:{self.marche}:{self.n}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["marche"], int(match["n"]))

    async def callback(self, interaction: discord.Interaction):
        choix = ((getattr(self.item, "values", None) or [""])[0] or "").strip().lower()
        msg = getattr(interaction, "message", None)
        ephemere = bool(getattr(getattr(msg, "flags", None), "ephemeral", False))
        guild = getattr(interaction, "guild", None)
        marche = self.marche

        def _frais():
            """Le menu sur ses intitules, avec la liste DU MOMENT : une model
            ajoutee depuis le post y apparait des le premier choix."""
            v = _jb_menu_models_vue(marche, guild)
            return _vue_sans_suivi(v) if ephemere else v

        refus = _jb_model_refus(interaction, choix, marche=marche)
        if refus:
            await _jb_menu_refuser(interaction, refus, _frais())
            return
        # PAS de redessin de fond par msg.edit (tache=None) : _menu_lancer
        # remet le menu sur ses intitules APRES l'action, par l'interaction
        # (edit_original_response, derriere le defer du panneau). Cette route
        # est celle du webhook de l'interaction : elle ne consomme pas le
        # compteur des editions du SALON, que le panneau et le ✨ General
        # partagent. L'edition de fond en faisait une troisieme par choix :
        # trois choix en moins de 5 s epuisaient ce compteur (5 par 5 s), le
        # panneau attendait, son accuse partait trop tard et un second
        # panneau etait epingle (simule le 26/09/2026 : 3 choix en 2 s
        # suffisaient). Hors serveur US, la reponse est le panneau
        # ephemere : _menu_lancer redessine alors par msg.edit, sans edition
        # de panneau en concurrence.
        await _menu_lancer(interaction, lambda: _jb_model_ouvrir(interaction, choix),
                           f"👤 {choix.capitalize()}", _frais(), None,
                           "menu des models")


class JBMenuModelsAncien(discord.ui.DynamicItem[discord.ui.Select],
                         template=r"jbmenu(?P<us>us)?:model"):
    """L'ANCIEN menu Jailbreak a UN seul menu deroulant, coupe a 25
    (« jbmenu:model » de /menujailbreak, « jbmenuus:model » de son repli US).

    Il n'est plus pose ; les messages deja postes le portent encore. Un choix
    passe par les gardes communes et le parcours commun (_jb_model_refus,
    _jb_model_ouvrir) -- qui convertit le message en « menus de 10 ». Il
    etait enregistre comme vue persistante : un motif dynamique fait le meme
    travail sans avoir a reconstruire, au demarrage, une liste de models
    qui ne sert qu'a router."""

    def __init__(self, us=False):
        self.us = bool(us)
        super().__init__(discord.ui.Select(
            placeholder="Choisis une model…", min_values=1, max_values=1,
            options=[discord.SelectOption(label="(aucune model)", value="__none__")],
            custom_id="jbmenuus:model" if self.us else "jbmenu:model"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(us=bool(match["us"]))

    async def callback(self, interaction: discord.Interaction):
        model = ((getattr(self.item, "values", None) or [""])[0] or "").strip().lower()
        if not model or model == "__none__":
            await interaction.response.send_message(
                "Aucune model disponible.", ephemeral=True)
            return
        refus = _jb_model_refus(interaction, model)
        if refus:
            await interaction.response.send_message(refus, ephemeral=True)
            return
        await _jb_model_ouvrir(interaction, model)


class JailbreakModelsView(discord.ui.LayoutView):
    """Le menu des models : un bloc V2, le texte en tete, un menu par dizaine.

    `models` : la liste du marche (_jb_models_marche) ; `emojis` : {model:
    PP} ; `guild` sert la phrase d'acces du texte. Ce qui ne tient pas
    (au-dela de 190, valeur en double ou trop longue) est journalise ET dit
    dans le texte. `hors` et `rejets` le gardent pour qui veut le compter."""

    def __init__(self, models, emojis=None, marche="us", guild=None, texte=None):
        super().__init__(timeout=None)
        self.marche = marche if marche in _JB_MM_MARCHES else "us"
        models = list(models or [])
        entrees, self.rejets = _jb_models_entrees(models, emojis)
        self.menus, self.hors = _jb_menus_de_10(entrees)
        alertes = []
        if not entrees:
            # Un menu vide ne dit rien de ce qui manque : les compteurs par
            # filtre designent la case a corriger sur le site.
            alertes.append("⚠️ **Aucune model à afficher.** "
                           + (_jb_diagnostic_marche(self.marche) if not models else ""))
        if self.hors:
            log.warning("menu des models %s : %d model(s) au-dela de %d, NON "
                        "affichees : %s", self.marche, len(self.hors),
                        _JB_MM_TAILLE * _JB_MM_MAX_MENUS,
                        ", ".join(v for v, _l, _e in self.hors))
            alertes.append(
                f"⚠️ **{len(self.hors)} model(s) non affichée(s)** — le menu en "
                f"montre {_JB_MM_TAILLE * _JB_MM_MAX_MENUS} au plus : "
                + _jb_noms(v.capitalize() for v, _l, _e in self.hors)
                + ". Préviens un admin.")
        if self.rejets:
            log.warning("menu des models %s : %d entree(s) sans place : %s",
                        self.marche, len(self.rejets),
                        ", ".join(f"{n!r} ({r})" for n, r in self.rejets))
            alertes.append(
                f"⚠️ {len(self.rejets)} entrée(s) sans place dans le menu : "
                + _jb_noms(f"{n} ({r})" for n, r in self.rejets)
                + ". Préviens un admin.")
        corps = (texte if texte is not None
                 else _jb_menu_models_texte(self.marche, models, guild))
        _jb_menus_models_poser(
            self,
            _jb_texte_v2_borne(corps, alertes + [_jb_menu_models_marque(self.marche)]),
            self.menus,
            lambda i, plage, bloc: JBModelsMenu(self.marche, i, plage, bloc))


class JailbreakMenuView(JailbreakModelsView):
    """Le menu de /menujailbreak (us=False : models FR) ou de son pendant US.

    C'etait un seul menu deroulant coupe a 25, qui listait en plus TOUTES
    les identites actives alors que la commande n'en comptait que les FR.
    Meme disposition, meme fonction que le menu des salons -menu desormais :
    une classe a part ne garde que la signature de ses appelants."""

    def __init__(self, cog=None, us=False, emojis=None, guild=None):
        marche = "us" if us else "fr"
        super().__init__(_jb_models_marche(marche), emojis=emojis,
                         marche=marche, guild=guild)
        self.cog = cog


def _jb_menu_models_vue(marche, guild=None, emojis=None):
    """Le menu des models du marche, avec la liste du moment. Sans `emojis`,
    les PP deja presentes sur le serveur (rien n'est cree : chemin du clic)."""
    models = _jb_models_marche(marche)
    if emojis is None:
        emojis = _jb_emojis_presents(guild, models)
    return JailbreakModelsView(models, emojis=emojis, marche=marche, guild=guild)


def _est_menu_models(m, moi=None) -> bool:
    """Ce message est-il le menu des models, dans l'un ou l'autre format ?

      - V2 : une ligne « -# menu-models-fr|us » dans son texte ;
      - ancien (embed) : « Jailbreak » dans le titre de son embed -- le
        reperage de toujours de _ensure_us_menu (« Menu Jailbreak US —
        models US », « Menu Jailbreak — toutes les models »…).
    Le panneau d'actions et le ✨ General n'en sont JAMAIS, quel que soit
    leur texte : ils se reconnaissent a leur propre marque, testee d'abord.
    Toute recherche du menu (welcome, /resetpanels, _delete_old_menus, la
    conversion au clic) passe par ici : deux reperages finiraient par ne plus
    reconnaitre la meme chose.

    `moi` : l'id du bot ; donne, un message d'un autre auteur ne compte
    jamais. Ne leve jamais."""
    try:
        if m is None:
            return False
        if moi is not None and getattr(getattr(m, "author", None), "id", None) != moi:
            return False
        if _est_panneau_actions(m) or _est_general(m):
            return False
        marques = {_jb_menu_models_marque(k) for k in _JB_MM_MARCHES}
        if any(ligne.strip() in marques
               for t in _textes_v2(m) for ligne in t.splitlines()):
            return True
        emb = getattr(m, "embeds", None) or []
        return bool(emb) and "Jailbreak" in (getattr(emb[0], "title", None) or "")
    except Exception as e:                                   # noqa: BLE001
        log.warning("menu des models : message %s illisible (%s: %s)",
                    getattr(m, "id", "?"), type(e).__name__, e)
        return False


_RE_PANNEAU_ETAT = re.compile(r"jbus:qb?:(?P<ident>[a-z0-9_.\-]+):(?P<qty>\d+)")


def _jb_panneau_etat_lu(panneau, chan_id=0):
    """(model, quantite) que montre le panneau `panneau`, lus dans son bouton
    (ou ancien menu) de quantite -- ce que le salon VOIT, meme apres un
    redemarrage. Repli : l'etat retenu en memoire, puis (« _ », 3)."""
    for cid in _ids_composants(panneau):
        mt = _RE_PANNEAU_ETAT.fullmatch(cid)
        if mt:
            return mt["ident"], int(mt["qty"])
    etat = _JB_PANNEAU_COURANT.get(int(chan_id or 0))
    return (etat[0], int(etat[1])) if etat else ("_", 3)


async def _jb_menu_models_reposer(client, chan, ancien, vue, raison):
    """Le REPLI quand Discord refuse d'editer (convertir) le menu des
    models : un NOUVEAU menu V2 est poste et epingle, l'ancien retire
    (_jb_message_reposer, le repli commun). Leve si le nouveau n'a pas pu
    etre poste.

    L'ORDRE menu / panneau / General : le nouveau menu arrive EN BAS du
    salon, sous le panneau et le General. Ils sont donc reposes dessous,
    le panneau sur la model qu'il montrait (_jb_panneau_reposer repose le
    General avec lui, serveur US seulement)."""
    nom = getattr(chan, "name", "?")
    nouveau = await _jb_message_reposer(chan, ancien, vue, lambda _mid: None,
                                        "menu des models", raison)
    moi = getattr(getattr(client, "user", None), "id", None)
    try:
        epingles = await chan.pins()
    except Exception as e:                                   # noqa: BLE001
        log.warning("menu des models %s : epingles illisibles (%s: %s) -- "
                    "panneau et General peut-etre AU-DESSUS du menu reposte",
                    nom, type(e).__name__, e)
        return nouveau
    panneau = next((m for m in epingles if _est_panneau_actions(m, moi)), None)
    if panneau is not None and panneau.id < nouveau.id:
        ident, qty = _jb_panneau_etat_lu(panneau, getattr(chan, "id", 0))
        cog = client.get_cog("UserCog") if client is not None else None
        await _jb_panneau_reposer(
            client, chan, panneau,
            _jb_panel(cog, ident, qty, guild=getattr(chan, "guild", None)),
            ident, f"menu des models reposte ({raison})", general=True)
        return nouveau
    general = next((m for m in epingles if _est_general(m, moi)), None)
    if general is not None and general.id < nouveau.id:
        # Pas de panneau, mais un General au-dessus : _ensure_us_general
        # retire ceux d'avant le menu et en repose un dessous.
        from cogs.welcome import _ensure_us_general
        await _ensure_us_general(client, chan, apres=nouveau)
    return nouveau


async def _jb_menu_models_editer(client, chan, ancien, vue) -> str:
    """Remplace le contenu du menu `ancien` par `vue` (V2), en le
    convertissant s'il est encore a l'ancien format : texte et embed vides
    dans la meme edition (_jb_kw_format).

    -> « edite », « repose » (Discord a refuse la conversion : nouveau menu,
    ordre du salon remis, _jb_menu_models_reposer) ou « absent » (supprime
    entre-temps). Un menu deja V2 dont l'edition echoue fait LEVER :
    l'appelant journalise, et en reposer un ferait un doublon."""
    kw = _jb_kw_format(ancien)
    try:
        await ancien.edit(view=vue, **kw)
        return "edite"
    except discord.NotFound:
        return "absent"
    except discord.HTTPException as e:
        if not kw:
            raise
        raison = f"conversion refusee ({type(e).__name__}: {e})"
    await _jb_menu_models_reposer(client, chan, ancien, vue, raison)
    return "repose"


def _jb_marche_ancien_menu(msg, chan, guild=None):
    """Le marche (« fr » / « us ») d'un ancien menu des models a convertir,
    et d'ou il vient -> (marche, source), pour le journal.

      1. Salon « -menu » : le marche de son PROPRIETAIRE (marche_du_salon),
         la regle de _ensure_us_menu qui l'a pose -- chacun de ces salons
         appartient a une seule personne.
      2. Ailleurs, l'ancien message lui-meme, qui dit quelle commande l'a
         pose : « jbmenu:model » (ancien /menujailbreak, que la commande pose
         aujourd'hui en FR) -> fr, « jbmenuus:model » -> us ; sinon le titre
         de son embed : « models FR » -> fr, « models US » -> us,
         « toutes les models » (ancien /menujailbreak) -> fr.
      3. En dernier repli, le marche du SERVEUR.

    Pourquoi pas marche_du_salon partout : hors -menu, il prenait le premier
    membre qui a une autorisation nominative sur le salon (un manager sur
    #jailbreak), et marche_du_membre rend « us » a qui n'a pas de role de
    marche. Le menu /menujailbreak partage du serveur FR passait alors en
    models US pour tous les VA du salon, sans rien au journal (simule le
    26/09/2026). Ne leve jamais."""
    if _est_salon_menu(chan):
        try:
            from cogs.welcome import marche_du_salon
            return marche_du_salon(chan), "proprietaire du salon -menu"
        except Exception as e:                               # noqa: BLE001
            log.warning("menu des models %s : marche du salon illisible (%s: %s), "
                        "lu dans le message", getattr(chan, "name", "?"),
                        type(e).__name__, e)
    try:
        ids = _ids_composants(msg)
    except Exception:                                        # noqa: BLE001
        ids = []
    if "jbmenuus:model" in ids:
        return "us", "ancien menu unique jbmenuus:model"
    if "jbmenu:model" in ids:
        return "fr", "ancien /menujailbreak (jbmenu:model)"
    try:
        emb = getattr(msg, "embeds", None) or []
        titre = (getattr(emb[0], "title", None) or "") if emb else ""
    except Exception:                                        # noqa: BLE001
        titre = ""
    if "models FR" in titre:
        return "fr", "titre de l'ancien menu"
    if "models US" in titre:
        return "us", "titre de l'ancien menu"
    if "toutes les models" in titre:
        return "fr", "titre de l'ancien /menujailbreak"
    try:
        import guild_features as _gf
        g = guild if guild is not None else getattr(chan, "guild", None)
        return ("us" if _gf.is_us_guild(g) else "fr"), "serveur (rien dans le message)"
    except Exception as e:                                   # noqa: BLE001
        log.warning("menu des models : marche illisible (%s: %s), US par defaut",
                    type(e).__name__, e)
        return "us", "defaut"


async def _jb_menu_models_convertir(interaction):
    """Si le clic vient d'un menu des models encore a l'ANCIEN format (grille
    de boutons-photos, ou un seul menu coupe a 25), il passe en « menus de
    10 » : edition, repli sur un nouveau message si Discord refuse.

    Appelee APRES la reponse au clic : ne repond pas, ne leve jamais -- un
    echec laisse l'ancien menu, dont les boutons repondent toujours, et le
    journal le dit."""
    msg = getattr(interaction, "message", None)
    try:
        if msg is None:
            return
        fl = getattr(msg, "flags", None)
        if getattr(fl, "components_v2", False) or getattr(fl, "ephemeral", False):
            return
        moi = getattr(getattr(interaction.client, "user", None), "id", None)
        if not _est_menu_models(msg, moi):
            return
        chan = getattr(interaction, "channel", None)
        marche, source = _jb_marche_ancien_menu(
            msg, chan, getattr(interaction, "guild", None))
        vue = _jb_menu_models_vue(marche, getattr(interaction, "guild", None))
        etat = await _jb_menu_models_editer(interaction.client, chan, msg, vue)
        log.info("menu des models %s : ancien format -> menus de 10 (%s d'apres "
                 "%s, %s)", getattr(chan, "name", "?"), marche, source, etat)
    except Exception as e:                                   # noqa: BLE001
        log.warning("menu des models %s : ancien menu %s non converti (%s: %s) "
                    "-- il reste a l'ancien format, ses boutons repondent "
                    "toujours", getattr(getattr(interaction, "channel", None),
                                        "name", "?"),
                    getattr(msg, "id", "?"), type(e).__name__, e)


def _jb_models_ecartees(marche="us"):
    """Chaque identite EXISTANTE absente du menu des models de `marche`, avec
    ses raisons : [(nom, [raison…])], dans l'ordre alphabetique.

    Le diagnostic de « les autres, celles que j'ai ajoutees, n'y sont pas »
    (le proprietaire, 26/09/2026) : on ne lit pas les donnees du serveur
    d'ici, c'est donc a /demomodels de les nommer, sur place. Les raisons
    sont les FILTRES DE PRODUCTION, un par un -- ceux de _jb_models_marche et
    de list_identities, puis la place dans le menu (au-dela de 190, valeur
    refusee par Discord). Une absence qu'aucun n'explique est dite « autre »,
    jamais tue. Rien n'est ecrit."""
    from cogs.welcome import (list_identities, is_identity_active,
                              load_identities_config, IDENTITIES_DIR, V2_PREFIX)
    menu = list(_jb_models_marche(marche))
    entrees, rejets = _jb_models_entrees(menu)
    _menus, hors = _jb_menus_de_10(entrees)
    affichees = {v for _p, bloc in _menus for v, _l, _e in bloc}
    raisons_place = {str(n).strip().lower(): r for n, r in rejets}
    raisons_place.update({v: "au-delà de %d (menu plein)"
                          % (_JB_MM_TAILLE * _JB_MM_MAX_MENUS)
                          for v, _l, _e in hors})
    try:
        tous = sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())
    except OSError as e:
        log.warning("diagnostic du menu : dossier des identites illisible (%s)", e)
        tous = list(list_identities(avec_reserves=True))
    avec_reserves = set(list_identities(avec_reserves=True))
    sans_reserves = set(list_identities())
    try:
        cfg = load_identities_config() or {}
    except Exception:                                        # noqa: BLE001
        cfg = {}
    out = []
    for n in tous:
        idl = n.strip().lower()
        if idl in affichees:
            continue
        raisons = []
        if idl.startswith(V2_PREFIX):
            raisons.append("Bibliothèque 2 (site seulement)")
        else:
            if n in avec_reserves and n not in sans_reserves:
                raisons.append("réserve")
            # La pause seule retire du menu (_jb_en_pause). « enabled: false »
            # ne concerne que la rotation des nouveaux VA : ce n'est pas une
            # raison d'absence, on ne la donne donc pas.
            if _jb_en_pause(n):
                raisons.append("en pause")
            if idl in EXCLURE_MENU:
                raisons.append("source du menu (pseudo/name)")
            mk = _market_of(n)
            if mk != marche:
                raisons.append(f"marché {str(mk).upper()}")
            if idl in raisons_place:
                raisons.append(raisons_place[idl])
        if not raisons:
            raisons.append("autre (aucun filtre connu ne l'explique)")
        out.append((n, raisons))
    return out


# ---------------------------------------------------------------------------
# Panneau d'actions PERMANENT du serveur US.
#
# Avant : cliquer une model envoyait un panneau EPHEMERE (« toi seul peux voir
# ceci »), qui disparaissait au moindre rafraichissement. Demande du patron :
# les deux messages restent affiches en permanence dans le salon -menu, le
# second suit la model choisie dans le premier, et le contenu genere part dans
# le salon -content.
#
# Tout l'etat (model, quantite) voyage dans le custom_id : les boutons
# survivent donc a un redemarrage du bot, sans rien avoir a re-armer.
_JB_PANEL_STORE = DATA_DIR / "us_panels.json"


def _jb_panel_ids() -> dict:
    try:
        import json as _j
        d = _j.loads(_JB_PANEL_STORE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _jb_panel_set(channel_id, message_id):
    d = _jb_panel_ids()
    d[str(channel_id)] = int(message_id)
    try:
        ok = safe_json.write(_JB_PANEL_STORE, d, indent=2)
    except Exception as e:                                   # noqa: BLE001
        ok = False
        log.warning("us_panels.json : %s", e)
    if not ok:
        # Sans l'id, le prochain clic cherche le panneau dans les epingles :
        # plus lent, pas faux. On le dit quand meme.
        log.warning("us_panels.json non ecrit : panneau du salon %s non memorise",
                    channel_id)


#: Ce qui designe le panneau d'actions, dans les DEUX formats :
#:   - l'ancien (embed) : le pied de l'embed vaut exactement cette chaine ;
#:   - le V2 (LayoutView), qui n'a PAS d'embed : une derniere ligne
#:     « -# panneau-actions-us » dans son texte (petit texte gris).
#: C'est la seule marque fiable : le titre change avec la model. Toute
#: recherche du panneau (clic sur une model, _ensure_us_menu,
#: _ensure_us_panel, _delete_old_menus) passe par _est_panneau_actions.
_JB_PANNEAU_PIED = "panneau-actions-us"
_JB_PANNEAU_MARQUE = "-# " + _JB_PANNEAU_PIED


def _textes_v2(obj) -> list:
    """Les textes (TextDisplay) d'un message « Components V2 », a toute
    profondeur (conteneur, section). Accepte un message recu de Discord
    (ses `components`) comme une vue construite ici (ses `children`).
    [] pour un message classique."""
    td = getattr(discord.ComponentType, "text_display", None)
    pile = list(getattr(obj, "components", None)
                or getattr(obj, "children", None) or [])
    out, vus = [], 0
    while pile and vus < 500:          # garde-fou : un message a 40 composants
        c = pile.pop(0)
        vus += 1
        texte = getattr(c, "content", None)
        if isinstance(texte, str) and td is not None and getattr(c, "type", None) == td:
            out.append(texte)
        enfants = getattr(c, "children", None)
        if isinstance(enfants, (list, tuple)):
            pile.extend(enfants)
    return out


def _ids_composants(obj) -> list:
    """Les custom_id des composants d'un message (ou d'une vue), a toute
    profondeur : rangees, conteneur, section et son accessoire. Sert a
    savoir si un message recu porte ENCORE un menu donne (_menu_lancer)."""
    pile = list(getattr(obj, "components", None)
                or getattr(obj, "children", None) or [])
    out, vus = [], 0
    while pile and vus < 500:          # garde-fou : un message a 40 composants
        c = pile.pop(0)
        vus += 1
        cid = getattr(c, "custom_id", None)
        if isinstance(cid, str) and cid:
            out.append(cid)
        enfants = getattr(c, "children", None)
        if isinstance(enfants, (list, tuple)):
            pile.extend(enfants)
        acc = getattr(c, "accessory", None)
        if acc is not None:
            pile.append(acc)
    return out


def _porte_marque(m, pied, moi=None, quoi="message") -> bool:
    """Ce message porte-t-il la marque `pied`, dans l'un ou l'autre format ?

      - l'ancien (embed) : le pied de son embed vaut exactement `pied` ;
      - le V2 (LayoutView), sans embed : une ligne « -# <pied> » dans son
        texte.
    Le panneau d'actions et le ✨ General passent TOUS DEUX par ici : deux
    reperages ecrits a part finiraient par ne plus reconnaitre la meme chose.

    `moi` : l'id du bot ; donne, un message d'un autre auteur ne compte
    jamais. Ne leve jamais."""
    try:
        if m is None:
            return False
        if moi is not None and getattr(getattr(m, "author", None), "id", None) != moi:
            return False
        emb = getattr(m, "embeds", None) or []
        if emb:
            texte_pied = getattr(getattr(emb[0], "footer", None), "text", None) or ""
            if texte_pied == pied:
                return True
        marque = "-# " + pied
        return any(ligne.strip() == marque
                   for t in _textes_v2(m) for ligne in t.splitlines())
    except Exception as e:                                   # noqa: BLE001
        log.warning("%s : message %s illisible (%s: %s)", quoi,
                    getattr(m, "id", "?"), type(e).__name__, e)
        return False


def _est_panneau_actions(m, moi=None) -> bool:
    """Ce message est-il le panneau d'actions US, dans l'un ou l'autre format ?

    `moi` : l'id du bot ; donne, un message d'un autre auteur n'est jamais le
    panneau. Ne leve jamais."""
    return _porte_marque(m, _JB_PANNEAU_PIED, moi, "panneau US")


def _jb_kw_format(message) -> dict:
    """Ce qu'une edition doit vider pour passer `message` au format V2.

    Discord accepte qu'un message classique devienne « Components V2 » par
    une EDITION, a condition d'effacer dans la meme requete son texte et ses
    embeds (discord.py pose alors le drapeau). Un message deja V2 n'a rien a
    vider : on n'envoie rien de plus que la vue."""
    fl = getattr(message, "flags", None)
    if fl is not None and getattr(fl, "components_v2", False):
        return {}
    return {"content": None, "embed": None}


async def _jb_message_reposer(chan, ancien, vue, memoriser, quoi, raison):
    """Le REPLI commun quand Discord refuse d'editer (convertir) un message
    permanent du salon : un NOUVEAU message V2 est poste, memorise
    (`memoriser(id)`), epingle, puis l'ancien est retire. Tout est
    journalise sous le nom `quoi`. Leve si le nouveau n'a pas pu etre poste :
    l'appelant a son propre repli.

    Le panneau d'actions et le ✨ General s'en servent tous les deux : deux
    replis recopies divergeraient au premier correctif."""
    nom = getattr(chan, "name", "?")
    nouveau = await chan.send(view=vue)
    memoriser(nouveau.id)
    log.warning("%s %s : %s -- nouveau message V2 %s a la place de %s",
                quoi, nom, raison, nouveau.id, getattr(ancien, "id", None))
    try:
        await nouveau.pin()
    except Exception as e:                                   # noqa: BLE001
        log.warning("%s %s : nouveau message non epingle (%s: %s)",
                    quoi, nom, type(e).__name__, e)
    if ancien is not None:
        try:
            await ancien.delete()
        except Exception as e:                               # noqa: BLE001
            log.warning("%s %s : ancien message %s non retire (%s: %s) "
                        "-- deux exemplaires dans le salon", quoi, nom,
                        getattr(ancien, "id", "?"), type(e).__name__, e)
    return nouveau


async def _jb_panneau_reposer(client, chan, ancien, vue, ident, raison,
                              general=True):
    """Le REPLI quand Discord refuse d'editer (convertir) le panneau :
    un NOUVEAU panneau V2 est poste, epingle et memorise, puis l'ancien est
    retire. Tout est journalise. Leve si le nouveau n'a pas pu etre poste :
    l'appelant a son propre repli.

    `general` : repose aussi le ✨ General (serveur US seulement), sinon il
    resterait AU-DESSUS du nouveau panneau. JBModelButton s'en charge
    lui-meme, avec la bonne model : il passe False."""
    nom = getattr(chan, "name", "?")
    nouveau = await _jb_message_reposer(
        chan, ancien, vue, lambda mid: _jb_panel_set(chan.id, mid),
        "panneau US", raison)
    if general and client is not None:
        try:
            import guild_features as _gf
            _us = _gf.is_us_guild(getattr(chan, "guild", None))
        except Exception:                                    # noqa: BLE001
            _us = False
        if _us:
            try:
                await _jb_general_maj(client, chan, ident,
                                      getattr(chan, "guild", None), reposter=True)
            except Exception as e:                           # noqa: BLE001
                log.warning("panneau US %s : General non repose (%s: %s)",
                            nom, type(e).__name__, e)
    return nouveau


async def _jb_panneau_en_reponse(interaction, vue, ident, quoi="panneau US",
                                 reposer=None) -> bool:
    """Remplace le panneau d'ou vient le clic par `vue`, EN REPONSE au clic.

    Un ancien panneau (embed) est converti au passage (_jb_kw_format). Si
    Discord refuse l'edition : le panneau du salon est repose en V2
    (_jb_panneau_reposer) ; un panneau ephemere est remplace par un nouvel
    ephemere. Une interaction = une reponse, dans tous les cas.
    Rend True si c'est le message du SALON qui porte desormais `vue`.

    Le menu VA s'en sert aussi (conversion d'un ancien menu) : `quoi` nomme
    le message dans le journal, `reposer(chan, ancien, vue, raison)`
    remplace le repli propre au panneau (memoire us_panels.json, ✨ General)."""
    msg = getattr(interaction, "message", None)
    ephemere = bool(getattr(getattr(msg, "flags", None), "ephemeral", False))
    try:
        await interaction.response.edit_message(
            view=(_vue_sans_suivi(vue) if ephemere else vue), **_jb_kw_format(msg))
        return not ephemere
    except discord.HTTPException as e:
        if interaction.response.is_done():
            raise
        refus = e
    log.warning("%s : edition refusee (%s: %s)%s", quoi, type(refus).__name__,
                refus, " -- nouvel ephemere" if ephemere else "")
    chan = getattr(interaction, "channel", None)
    if ephemere or msg is None or chan is None:
        await interaction.response.send_message(view=_vue_sans_suivi(vue),
                                                ephemeral=True)
        return False
    # Accuser reception AVANT de reposer : poster, epingler, retirer et
    # reposer le General ne tient pas dans les 3 s de Discord.
    await interaction.response.defer()
    raison = f"edition refusee ({type(refus).__name__}: {refus})"
    if reposer is None:
        await _jb_panneau_reposer(interaction.client, chan, msg, vue, ident, raison)
    else:
        await reposer(chan, msg, vue, raison)
    return True


class JBQtyBouton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"jbus:qb:(?P<ident>[a-z0-9_.\-]+):(?P<qty>\d+)"):
    """La quantite, en BOUTON plutot qu'en menu deroulant.

    POURQUOI. Un Select occupe une rangee Discord ENTIERE -- cinq places -- et
    ne peut rien partager. Le panneau plafonnait donc a vingt actions, et il
    etait plein : impossible d'en ajouter une seule sans en retirer une autre.
    En bouton, la quantite ne coute plus qu'UNE place : quatre se liberent.

    Le VA y perd le choix en un clic et y gagne la saisie libre : il tape le
    nombre qu'il veut au lieu de le chercher dans une liste fermee, et la
    valeur « Autre » du deroulant n'a plus de raison d'etre.

    JBQtySelect est CONSERVEE et reste enregistree : les panneaux deja postes
    dans les salons portent encore son custom_id, et sans sa classe leurs
    boutons deviendraient muets sans un mot.
    """

    def __init__(self, ident, qty):
        self.ident = (ident or "_").lower()
        self.qty = int(qty)
        super().__init__(discord.ui.Button(
            # Le libelle de la maquette validee : sur une rangee de cinq
            # boutons, la phrase « clique pour changer » ne tenait pas.
            label=f"📦 Quantité : {self.qty}",
            style=discord.ButtonStyle.secondary, row=0,
            custom_id=f"jbus:qb:{self.ident}:{self.qty}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["ident"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        if not _jb_can_use(interaction):
            await interaction.response.send_message(
                "🔒 Réservé aux VA **Jailbreak** (rôle « Jailbreak »).",
                ephemeral=True)
            return

        async def _suite(inter, q):
            vue2 = _jb_panel(inter.client.get_cog("UserCog"), self.ident,
                             q, guild=inter.guild,
                             marche=marche_du_membre(inter.user))
            # edit_message depuis une soumission de Modal modifie bien le
            # message d'origine : c'est ce qui evite de reposter un panneau en
            # double dans le salon. Un ancien panneau passe en V2 au passage.
            await _jb_panneau_en_reponse(inter, vue2, self.ident)
            await _jb_panneau_qte_changee(inter, self.ident, q)

        await interaction.response.send_modal(_JBQtyModal(_suite))


class JBQtySelect(discord.ui.DynamicItem[discord.ui.Select],
                  template=r"jbus:q:(?P<ident>[a-z0-9_.\-]+):(?P<qty>\d+)"):
    """Quantite du panneau permanent. La valeur choisie est recuite dans les
    custom_id des boutons -> aucun etat en memoire."""

    def __init__(self, ident, qty):
        self.ident = (ident or "_").lower()
        self.qty = int(qty)
        super().__init__(discord.ui.Select(
            placeholder=f"📦 Quantité : {self.qty} par action",
            min_values=1, max_values=1, options=_jb_qty_options(self.qty), row=0,
            custom_id=f"jbus:q:{self.ident}:{self.qty}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["ident"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        if not _jb_can_use(interaction):
            await interaction.response.send_message(
                "🔒 Réservé aux VA **Jailbreak** (rôle « Jailbreak »).", ephemeral=True)
            return
        vals = getattr(self.item, "values", None) or []

        def _repose(inter, q):
            """Reconstruit le panneau (V2) avec la quantite demandee."""
            return _jb_panel(inter.client.get_cog("UserCog"), self.ident, q,
                             guild=inter.guild,
                             marche=marche_du_membre(inter.user))

        if vals and vals[0] == _JB_QTY_AUTRE:
            async def _suite(inter, q):
                # edit_message depuis une soumission de Modal modifie bien le
                # message d origine : c est ce qui evite de reposter un
                # panneau en double dans le salon.
                await _jb_panneau_en_reponse(inter, _repose(inter, q), self.ident)
                await _jb_panneau_qte_changee(inter, self.ident, q)
            await interaction.response.send_modal(_JBQtyModal(_suite))
            return
        try:
            q = int(vals[0])
        except Exception:
            q = self.qty
        # Ce menu n'existe plus que sur les panneaux d'AVANT : y toucher les
        # fait passer au panneau V2.
        await _jb_panneau_en_reponse(interaction, _repose(interaction, q), self.ident)
        await _jb_panneau_qte_changee(interaction, self.ident, q)


async def _jb_panneau_qte_changee(inter, ident, q):
    """Apres un changement de quantite : les sous-menus ouverts portent
    l'ANCIENNE quantite dans leurs boutons. On les efface et on retient la
    nouvelle -- si c'est bien le panneau epingle qui a change ; sinon (le
    panneau de secours, ephemere) l'etat devient inconnu. Ne leve jamais :
    le panneau est deja a jour, c'est l'essentiel."""
    try:
        cid = getattr(getattr(inter, "channel", None), "id", 0) or 0
        _jb_panneau_noter(cid, ident if _jb_est_panneau_epingle(inter) else None, q)
        await _jb_sous_menus_fermer(channel_id=cid)
    except Exception as e:
        log.warning("panneau US : sous-menus non mis a jour (%s: %s)",
                    type(e).__name__, e)


def _jb_action(key):
    """Definition d'une action par sa cle, quel que soit le MARCHE.
    Chercher seulement dans _JB_ACTIONS_US faisait repondre « Action
    indisponible » a tout VA FR (sa cle « reel » n'y est pas)."""
    for lst in (_JB_ACTIONS_US, _JB_ACTIONS):
        for e in lst:
            if e[0] == key:
                return e
    return None


class JBActionButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"jbus:a:(?P<ident>[a-z0-9_.\-]+):(?P<key>[a-z]+):(?P<qty>\d+)"):
    """Une action du panneau permanent (reel caption, story, pseudo...)."""

    def __init__(self, ident, key, qty, label=None, row=1, icone=None):
        self.ident = (ident or "_").lower()
        self.key = key
        self.qty = int(qty)
        _e = _jb_action(key)
        lib = label or (_e[1] if _e else key)
        # C est CE bouton qui compose le panneau epingle du salon — pas
        # _JailbreakActionButton, qui ne sert qu au menu ephemere. Les deux
        # doivent porter les memes icones, sinon le panneau qu on regarde
        # toute la journee est le seul a garder les vieux emojis.
        # from_custom_id ne repasse pas d icone : ce chemin ne sert qu a
        # REPONDRE au clic, le rendu vient du message deja poste.
        # Le vert isole les TRENDS du reste : ce sont les seules videos deja
        # finies, et les confondre avec de la matiere premiere ferait poster du
        # non-fini. Discord n offre que quatre couleurs — le vert est la seule
        # libre ici, les autres portent deja un sens (bleu = action, rouge =
        # destructif).
        _btn = discord.ui.Button(
            label=(_libelle_sans_emoji(lib) if icone is not None else lib),
            style=(discord.ButtonStyle.success if key in _JB_CLES_TREND
                   else discord.ButtonStyle.primary), row=row,
            custom_id=f"jbus:a:{self.ident}:{self.key}:{self.qty}")
        if icone is not None:
            _btn.emoji = icone
        super().__init__(_btn)

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["ident"], match["key"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        if not _jb_can_use(interaction):
            await interaction.response.send_message(
                "🔒 Réservé aux VA **Jailbreak** (rôle « Jailbreak »).", ephemeral=True)
            return
        # Un panneau d'actions peut rester affiche sur une entree devenue
        # reserve depuis (seul le menu est rafraichi, pas ce panneau). Sans ce
        # refus, Template partait monte sur ses brutes -- vides -- et le VA
        # recevait un template nu marque « NE POSTE PAS ».
        _refus = _refus_reserve_jb(self.ident)
        if _refus:
            await interaction.response.send_message(_refus, ephemeral=True)
            return
        # Un sous-menu de famille reste cliquable apres que le panneau a
        # change de model ou de quantite (au-dela de 15 min on ne peut plus
        # l'effacer). Son clic servirait l'ANCIENNE model dans le -content :
        # on refuse, en disant quoi faire.
        _perime = _jb_sous_menu_perime(interaction, self.ident, self.qty)
        if _perime:
            await interaction.response.send_message(_perime, ephemeral=True)
            return
        cog = interaction.client.get_cog("UserCog")
        entree = _jb_action(self.key)
        if cog is None or entree is None:
            await interaction.response.send_message(
                f"Action indisponible (`{self.key}`).", ephemeral=True)
            return
        _k, _label, cmd_attr, supports_count = entree
        cmd = getattr(cog, cmd_attr, None)
        if cmd is None:
            await interaction.response.send_message(
                f"Action indisponible (`{cmd_attr}`).", ephemeral=True)
            return
        # Même remarque que dans _JailbreakActionButton : pseudo et name sont
        # arbitrés par _source_pseudo_name, sur le drapeau de l'identité.
        model = self.ident
        # ORDRE DES ARGUMENTS : (interaction, model, cmd, count, supports_count).
        # Les inverser faisait echouer l'action avant toute reponse -> Discord
        # affichait « n'a pas repondu a temps ».
        await cog._run_for_model(interaction, model, cmd,
                                 count=self.qty, supports_count=supports_count)


def _vue_sans_suivi(view):
    """Rend `view` envoyable en ephemere SANS que discord.py la suive.

    LE PIEGE. Une vue envoyee en ephemere recoit un delai de 15 minutes (si
    elle n'en a pas) et discord.py la range ; a l'expiration, il la retire.
    Quand elle a ete rangee sans numero de message -- sous la cle des vues
    PERSISTANTES, ce que fait discord.py 2.4 pour une reponse a un bouton --,
    ce retrait emporte les MOTIFS de ses elements dynamiques (JBActionButton,
    JBFamilleBouton…), c'est-a-dire les enregistrements de cog_load : un seul
    sous-menu expire, et TOUS les panneaux US deviennent muets jusqu'au
    prochain redemarrage, sans une erreur. Reproduit en simulation sur 2.7.1
    (vue rangee sans numero) ; la version du VPS n'est pas figee
    (requirements.txt : >= 2.3.2).

    Une vue ARRETEE avant l'envoi n'est pas rangee du tout, quelle que soit
    la version : ses boutons partent quand meme, et chacun est servi par son
    motif, enregistre une fois pour toutes au demarrage. Ils n'ont besoin de
    rien d'autre : tout leur etat (model, action, quantite) est dans leur
    custom_id.
    """
    view.stop()
    return view


class JBFamilleBouton(discord.ui.DynamicItem[discord.ui.Button],
                      template=r"jbus:f:(?P<ident>[a-z0-9_.\-]+):(?P<fam>[a-z]+):(?P<qty>\d+)"):
    """Le lanceur « ▸ » d'une famille (« 💬 Caption ▸ »…) des panneaux US
    postes entre dc157c3 et le passage aux menus directs.

    IL N'EST PLUS POSE. Il ouvrait les variantes dans un sous-menu
    ephemere ; le panneau V2 les offre directement, dans un menu deroulant
    par famille (JBMenuFamille). Les panneaux deja epingles le portent encore
    jusqu'a leur prochaine mise a jour : au clic, apres les memes gardes
    qu'une action (role, reserve), il RECONSTRUIT le panneau qui le porte, en
    V2, a la place -- plus de sous-menu. Le VA choisit ensuite sa variante
    dans le menu de la famille.

    Prefixe « jbus:f: » : discord.py lance TOUS les motifs dynamiques qui
    correspondent a un custom_id, celui-ci ne doit recouper ni jbus:a/m/q/qb/s,
    ni jbg:. L'identite ne contient pas « : », la famille est en [a-z].
    """

    def __init__(self, ident, famille, qty, row=None, icone=None):
        self.ident = (ident or "_").lower()
        self.famille = famille
        self.qty = int(qty)
        fam = _famille_menu(famille)
        lib = f"{fam.emoji} {fam.nom} ▸" if fam else f"{famille} ▸"
        _btn = discord.ui.Button(
            label=(_libelle_sans_emoji(lib) if icone is not None else lib),
            style=discord.ButtonStyle.primary, row=row,
            custom_id=f"jbus:f:{self.ident}:{self.famille}:{self.qty}")
        if icone is not None:
            _btn.emoji = icone
        super().__init__(_btn)

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["ident"], match["fam"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        if not _jb_can_use(interaction):
            await interaction.response.send_message(_JB_REFUS_ROLE, ephemeral=True)
            return
        _refus = _refus_reserve_jb(self.ident)
        if _refus:
            await interaction.response.send_message(_refus, ephemeral=True)
            return
        fam = _famille_menu(self.famille)
        if fam is None or self.ident == "_":
            await interaction.response.send_message(
                f"Famille indisponible (`{self.famille}`) : reclique la model "
                "au-dessus, le panneau se remet à jour.", ephemeral=True)
            return
        vue = _jb_panel(interaction.client.get_cog("UserCog"), self.ident,
                        self.qty, guild=interaction.guild,
                        marche=marche_du_membre(interaction.user))
        epingle = _jb_est_panneau_epingle(interaction)
        await _jb_panneau_en_reponse(interaction, vue, self.ident)
        # Le panneau d'ou part ce clic dit ce qu'il montre : si l'etat etait
        # inconnu (redemarrage), on l'apprend ici -- mais seulement depuis
        # l'epingle, pas depuis un panneau de secours.
        if epingle:
            _jb_panneau_noter(getattr(interaction.channel, "id", 0),
                              self.ident, self.qty)


class JBMenuFamille(discord.ui.DynamicItem[discord.ui.Select],
                    template=r"jbus:s:(?P<ident>[a-z0-9_.\-]+):(?P<fam>[a-z]+):(?P<qty>\d+)"):
    """Le menu deroulant d'une famille du panneau US (« 💬 Caption… »).

    Ses options sont les actions de la famille (_FAMILLES_PANNEAU) : libelle
    de production, ligne d'explication, icone du serveur. Tout l'etat (model,
    famille, quantite) est dans le custom_id : le menu repond encore apres un
    redemarrage (from_custom_id), comme les boutons du panneau.

    Au choix : les memes gardes que JBActionButton (role, reserve, panneau
    perime), la valeur VALIDEE contre la liste blanche de la famille, puis
    _run_for_model exactement comme le bouton -- et le menu reprend son
    intitule, sans quoi re-choisir la meme variante ne declencherait rien.

    Prefixe « jbus:s: » : il ne recoupe aucun autre motif (jbus:a/m/q/qb/f,
    jbg:) -- discord.py les lance TOUS quand ils correspondent.
    """

    def __init__(self, ident, famille, qty, icones=None):
        self.ident = (ident or "_").lower()
        self.famille = famille
        self.qty = int(qty)
        fam = _famille_panneau(famille)
        if fam is not None:
            opts, self.inconnues = _jb_options_famille(fam, icones)
            intitule = _jb_placeholder_famille(fam)
        else:
            opts, self.inconnues, intitule = [], [], f"{famille}…"
        #: Aucune option : _jb_panel ne pose pas ce menu (Discord refuserait
        #: le message ENTIER) et le dit. L'option factice ne sert qu'a
        #: construire l'objet quand un vieux custom_id revient.
        self.vide = not opts
        if not opts:
            opts = [discord.SelectOption(label="(aucune variante)", value="_")]
        super().__init__(discord.ui.Select(
            placeholder=intitule, min_values=1, max_values=1, options=opts,
            custom_id=f"jbus:s:{self.ident}:{self.famille}:{self.qty}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["ident"], match["fam"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        choix = (getattr(self.item, "values", None) or [""])[0]
        cog = interaction.client.get_cog("UserCog")
        msg = getattr(interaction, "message", None)
        ephemere = bool(getattr(getattr(msg, "flags", None), "ephemeral", False))

        def _frais():
            """Le panneau tel qu'il etait avant le choix : ses menus sur leur
            intitule. En ephemere, une vue ARRETEE (_vue_sans_suivi)."""
            v = _jb_panel(cog, self.ident, self.qty, guild=interaction.guild)
            return _vue_sans_suivi(v) if ephemere else v

        fam = _famille_panneau(self.famille)
        refus, cmd, sc = "", None, False
        if not _jb_can_use(interaction):
            refus = _JB_REFUS_ROLE
        else:
            # Un panneau peut rester affiche sur une entree devenue reserve
            # depuis : son contenu partirait monte sur des brutes qu'elle n'a
            # pas (meme refus que JBActionButton).
            refus = _refus_reserve_jb(self.ident)
        if not refus:
            if fam is None or self.ident == "_":
                refus = (f"Famille indisponible (`{self.famille}`) : reclique la "
                         "model au-dessus, le panneau se remet à jour.")
            elif choix not in fam.actions:
                # Hors de la liste blanche : ce choix ne vient pas d'un menu
                # que le bot a pose. Refuse, et trace.
                log.warning("panneau US : choix %r refuse (famille %r, model %r)",
                            choix, self.famille, self.ident)
                refus = f"Option inconnue (`{choix}`) : reclique la model au-dessus."
            else:
                refus = _jb_sous_menu_perime(interaction, self.ident,
                                             self.qty, panneau=True)
        if not refus:
            entree = _jb_action(choix)
            cmd = getattr(cog, entree[2], None) if (cog is not None and entree) else None
            sc = bool(entree and entree[3])
            if cmd is None:
                refus = f"Action indisponible (`{choix}`)."
        if refus:
            await _jb_menu_refuser(interaction, refus, _frais())
            return
        if _jb_est_panneau_epingle(interaction):
            _jb_panneau_noter(getattr(interaction.channel, "id", 0),
                              self.ident, self.qty)
        # Le panneau du SALON se redessine tout de suite, sans attendre la fin
        # d'un rendu de 30 s : c'est un message du bot, il s'edite sans passer
        # par l'interaction. Un ephemere n'a pas ce chemin : il est redessine
        # apres coup, par l'interaction (_jb_menu_remettre).
        tache = None
        if not ephemere and msg is not None:
            tache = _jb_en_fond(
                _jb_remettre_epingle(interaction, self.ident, self.qty, _frais()),
                "panneau US : menu remis sur son intitule")
        await _jb_menu_lancer(interaction, cog, self.ident, choix, cmd, sc,
                              self.qty, _frais(), tache, "panneau US")


async def _jb_remettre_epingle(interaction, ident, qty, vue, quoi="panneau US"):
    """Redessine le message du salon d'ou vient le choix (panneau d'actions,
    ou ✨ General) : ses menus reprennent leur intitule.

    SAUF si le panneau a change entre-temps (autre model, autre quantite) :
    un redessin l'a alors deja remis a zero, et le redessiner avec l'etat du
    clic le ferait revenir EN ARRIERE -- le panneau montrerait Lola pendant
    que le VA vient de choisir Julia.

    `qty=None` (le ✨ General) : seule la MODEL est comparee. Le General a sa
    propre quantite, mais il suit la model du panneau (_jb_general_maj) :
    passe sur une autre, il a deja ete redessine pour elle."""
    cid = int(getattr(getattr(interaction, "channel", None), "id", 0) or 0)
    etat = _JB_PANNEAU_COURANT.get(cid)
    ident = (ident or "").lower()
    if etat is not None and (etat[0] != ident
                             or (qty is not None and int(etat[1]) != int(qty))):
        log.info("%s %s : deja redessine (%s), pas de remise a zero",
                 quoi, cid, etat)
        return
    await interaction.message.edit(view=vue)


def _jb_panel_texte(ident, qty, hors=(), inconnues=()) -> str:
    """Le texte en tete du panneau (TextDisplay). Sa DERNIERE ligne est la
    marque qui le designe (_JB_PANNEAU_MARQUE) : le format V2 n'a pas de pied
    d'embed ou la mettre.

    Ni « menu » ni « Jailbreak » dans ce texte : le premier fait supprimer un
    message par _delete_old_menus, le second designe le menu des models dans
    _ensure_us_menu."""
    if ident == "_":
        lignes = ["## 🔓 Choisis une model au-dessus 👆",
                  "Clique sur une model dans la grille du dessus : les actions "
                  "apparaissent ici.",
                  f"📦 **Quantité : {qty} média par action** — le bouton "
                  "ci-dessous la change.",
                  "Le contenu généré part dans ton salon **-content**."]
    else:
        lignes = [f"## 🔓 {ident.capitalize()} — que veux-tu générer ?",
                  f"📦 **Quantité : {qty} média par action** — plafonnée au "
                  "stock dispo de la model."]
        if hors:
            lignes.append(_jb_note_hors(hors))
        if inconnues:
            lignes.append(f"⚠️ {len(inconnues)} action(s) introuvable(s), sans "
                          "bouton : " + ", ".join(inconnues)
                          + " (à signaler à un admin).")
        lignes.append("Le contenu arrive dans ton salon **-content** 👇")
    lignes.append(_JB_PANNEAU_MARQUE)
    return "\n".join(lignes)


def _jb_panel_probleme(ident, qty) -> str:
    """Pourquoi le panneau de `ident` ne peut PAS porter de boutons, ou "".

    Un nom hors de [a-z0-9_.-] fait lever discord.py a la construction (le
    motif des custom_id le refuse), et un custom_id de plus de 100 caracteres
    fait refuser le message ENTIER par Discord. Dans les deux cas, un panneau
    qui le DIT vaut mieux qu'un clic qui echoue sans un mot."""
    if not _JB_NOM_BOUTON.fullmatch(ident):
        return ("Nom de model illisible dans un bouton Discord (lettres "
                "minuscules, chiffres, « _ . - ») : renomme-la sur le site.")
    ids = [f"jbus:qb:{ident}:{qty}"]
    ids += [f"jbus:a:{ident}:{k}:{qty}" for ks in _JB_BOUTONS_V2 for k in ks]
    ids += [f"jbus:a:{ident}:{a[0]}:{qty}" for a in _JB_ACTIONS_US]
    ids += [f"jbus:s:{ident}:{f.cle}:{qty}" for f in _FAMILLES_PANNEAU]
    plus_long = max(len(i) for i in ids)
    if plus_long > _JB_CUSTOM_ID_MAX:
        return (f"Nom trop long pour Discord ({plus_long} caractères sur "
                f"{_JB_CUSTOM_ID_MAX}) : raccourcis le nom de la model sur le site.")
    return ""


def _jb_panel(cog, ident, qty=3, marche="us", guild=None):
    """Le panneau permanent : une LayoutView « Components V2 ».

    Un bloc (conteneur a accent rouge fonce) : le texte en tete, puis les
    rangees de boutons de _JB_BOUTONS_V2, puis UN MENU DEROULANT PAR FAMILLE
    de _FAMILLES_PANNEAU (Brut, Caption, Template, Trash, Flash) -- la
    disposition de la maquette /demopanneau, validee par le proprietaire.
    Plus d'embed : il ne rend que la vue.

    `ident` vaut « _ » tant qu'aucune model n'est choisie : le texte invite a
    en choisir une, et seule la quantite est la. `marche` n'est plus lu (la
    meme liste pour tout le monde : « Reel caption », pas de Reel brut) ; il
    reste pour les appelants.

    Tout l'etat (model, quantite) est dans les custom_id : aucune memoire, et
    les elements repondent encore apres un redemarrage.
    """
    ui = discord.ui
    ident = (ident or "_").lower()
    try:
        qty = max(1, int(qty))
    except (TypeError, ValueError):
        qty = 3
    vue = ui.LayoutView(timeout=None)
    boite = ui.Container(accent_colour=discord.Colour.dark_red())
    vue.add_item(boite)
    if ident == "_":
        boite.add_item(ui.TextDisplay(_jb_panel_texte("_", qty)))
        rangee = ui.ActionRow()
        rangee.add_item(JBQtyBouton("_", qty))
        boite.add_item(rangee)
        return vue
    probleme = _jb_panel_probleme(ident, qty)
    if probleme:
        log.warning("panneau US %r : sans boutons -- %s", ident, probleme)
        boite.add_item(ui.TextDisplay(
            f"## 🔓 {_couper_discord(ident.capitalize(), 100)}\n⚠️ {probleme}\n"
            + _JB_PANNEAU_MARQUE))
        return vue
    _ic = icones_actions(guild)          # lecture seule : rien sur le reseau
    disposition, hors = _jb_disposition()
    rangees, inconnues = {}, []
    for sorte, cle, r in disposition:
        if sorte == "qte":
            item = JBQtyBouton(ident, qty)
        elif sorte == "menu":
            item = JBMenuFamille(ident, cle, qty, icones=_ic)
            inconnues += item.inconnues
            if item.vide:
                # Un menu sans option serait refuse par Discord, et le
                # panneau ENTIER avec lui : on le retire, en le disant.
                inconnues.append(f"menu {cle}")
                continue
        else:
            entree = _jb_action(cle)
            if entree is None:
                inconnues.append(cle)
                log.warning("panneau US : action %r de _JB_BOUTONS_V2 inconnue", cle)
                continue
            item = JBActionButton(ident, cle, qty, label=entree[1], row=None,
                                  icone=_ic.get(cle))
        rangees.setdefault(r, ui.ActionRow()).add_item(item)
    boite.add_item(ui.TextDisplay(_jb_panel_texte(ident, qty, hors, inconnues)))
    for r in sorted(rangees):
        boite.add_item(rangees[r])
    return vue


# ---------------------------------------------------------------------------
# Menu « ✨ General » : 3e message epingle du salon -menu, sous le panneau
# d'actions (serveur US seulement, decision du proprietaire).
#
# Il sert le contenu des RESERVES liees a la model choisie (type_identite) :
# PP, bios, stories, story CTA, posts, captions, templates, trash, flash. Pendant un
# clic, l'identite active est la RESERVE (tout le contenu vient d'elle, sans
# toucher aux fonctions de tirage) et la brute vient de la MODEL
# (_MODEL_REELLE, _dossier_brutes).
#
# Un message A PART, pas des boutons de plus dans _jb_panel : quand il est
# ne, le panneau comptait 24 composants sur 25 (22 sur 40 depuis le passage
# au format V2 et aux menus directs).
#
# FORMAT « COMPONENTS V2 » DEPUIS LE 26/09/2026, comme le panneau d'actions.
# Le proprietaire, apres les menus directs du panneau : « le menu stp juste
# pour caption template trash et flash ». Ces quatre familles passent en
# menus deroulants (un par famille) ; PP, Bio, Story, Story CTA et Post
# restent des boutons. En format classique ca ne tiendrait pas : deux
# rangees de boutons (reserves + quantite, puis PP…Post) et quatre menus
# font six rangees, un message classique en admet cinq et un menu en prend
# une entiere.
#
# Prefixe « jbg: » : discord.py lance TOUS les templates dynamiques qui
# correspondent, celui-ci ne doit recouper aucun « jbus: ». Titre sans
# « Jailbreak » ni « menu » : du temps de l'embed, le premier designait le
# menu des models (_ensure_us_menu), le second faisait supprimer le message
# (_delete_old_menus). C'est la MARQUE « panneau-general-us » qui designe le
# General : pied de l'ancien embed, ou derniere ligne du texte V2
# (_est_general, les deux formats).

#: Les BOUTONS du General (rangee 1) : ce que la reserve sert telle quelle.
_JB_GEN_BOUTONS = ("pp", "bio", "story", "storycta", "post")

#: Les MENUS du General, dans l'ordre de _FAMILLES_MENU (Caption, Template,
#: Trash, Flash -- les marques dans l'ordre de marques_montage). Lus dans
#: cette table-la, rien de recopie : un libelle ou un logo change la-bas
#: change ici.
#:
#: Chaque famille garde ses DEUX premieres variantes -- la matiere seule, et
#: sa version etoilee. Les deux suivantes exigent une brute ⭐ (voir l'ordre
#: des familles, _MARQUE_VARIANTES) : le General pose le contenu de la
#: reserve sur une brute quelconque de la model, il n'a pas de Brut (une
#: reserve n'a pas de video brute). Ce sont exactement les huit boutons
#: d'avant (Caption, ⭐ Caption, Template, ⭐ Template, Trash, ⭐ Trash, Flash,
#: ⭐ Flash).
_JB_GEN_VARIANTES = 2
_JB_GEN_FAMILLES = tuple(
    _Famille(_f.cle, _f.emoji, _f.nom, tuple(_f.actions[:_JB_GEN_VARIANTES]))
    for _f in _FAMILLES_MENU)


def _jb_gen_famille(cle):
    """La famille `cle` des menus du General, ou None."""
    for f in _JB_GEN_FAMILLES:
        if f.cle == cle:
            return f
    return None


#: Les actions du General ET leur rangee prevue : 1 = les boutons, 2 et
#: suivantes = le menu de leur famille. DEDUITE des deux tables du dessus,
#: rien a tenir a jour a la main. Ses cles SONT la liste blanche : un
#: custom_id forge avec une autre cle est refuse (bouton comme menu).
#: Libelle, commande et quantite se lisent par _jb_action : rien n'est
#: recopie de _JB_ACTIONS_US.
_JB_GENERAL_RANGEES = {_k: 1 for _k in _JB_GEN_BOUTONS}
_JB_GENERAL_RANGEES.update({_a: 2 + _i for _i, _f in enumerate(_JB_GEN_FAMILLES)
                            for _a in _f.actions})

#: Celles qui posent le contenu sur une brute de la MODEL. Refusees d'avance
#: si elle n'en a aucune : sinon 30 s de rendu, puis un template nu marque
#: « NE POSTE PAS ». Template (reelmonte) n'y est pas : un brouillon sans
#: coupe n'utilise pas de brute, et son repli l'annonce deja.
_JB_GEN_BRUTE = frozenset({"reelcaption", "capbanger", "templatebanger"} | {
    _a for _mq in marques_montage.ORDRE
    for _a in marques_montage.marque(_mq)["actions"][:2]})

#: Boutons de choix de reserve, rangee 0 ; la 5e place est la quantite.
_JB_GEN_MAX_RESERVES = 4

_JB_GENERAL_FOOTER = "panneau-general-us"
#: La derniere ligne du texte du General V2 (petit texte gris) : c'est elle
#: qui le designe, un message V2 n'ayant pas de pied d'embed.
_JB_GENERAL_MARQUE = "-# " + _JB_GENERAL_FOOTER
#: Plafond Discord du texte d'un message V2 (tous ses TextDisplay).
_JB_TEXTE_V2_MAX = 4000
_JB_GENERAL_STORE = DATA_DIR / "us_general_panels.json"
#: Plafond Discord d'un custom_id.
_JB_CUSTOM_ID_MAX = 100
#: Ce que les motifs jbg: acceptent comme nom (model ou reserve).
_JB_NOM_BOUTON = re.compile(r"[a-z0-9_.\-]+")


def _marques_en_toutes_lettres(majuscule=False) -> str:
    """« trash et flash » : les marques, dans l'ordre de marques_montage."""
    noms = [marques_montage.marque(m)["court"] for m in marques_montage.ORDRE]
    if not majuscule:
        noms = [n.lower() for n in noms]
    return " et ".join([", ".join(noms[:-1]), noms[-1]] if len(noms) > 1 else noms)


def _refus_reserve_jb(ident) -> str:
    """Le message ephemere a opposer au clic si `ident` est une reserve,
    sinon « ». La phrase de type_identite, la meme que sur le site, plus ce
    que le VA peut faire a la place. Repli OUVERT et journalise : un module
    qui ne repond pas ne doit pas bloquer tout le panneau."""
    idl = (ident or "").strip().lower()
    if not idl or idl == "_":
        return ""
    # En pause : les boutons deja postes restent cliquables tant que la
    # grille n'est pas redessinee ; ils refusent avec la raison.
    try:
        import identite_pause as _ip
        if _ip.en_pause(idl):
            return _ip.refus(idl)
    except Exception as e:
        log.warning("controle « pause » indisponible pour %r (%s: %s)",
                    idl, type(e).__name__, e)
    try:
        import type_identite as _ti
        refus = _ti.refus_assignation(idl)
    except Exception as e:
        log.warning("controle « reserve » indisponible pour %r (%s: %s)",
                    idl, type(e).__name__, e)
        return ""
    if not refus:
        return ""
    return (f"⛔ {refus}\nElle n'est plus dans la grille des models : "
            "clique une model qui y est liée, puis le **✨ General** "
            "sous le panneau d'actions.")


def _titre_general(titre: str) -> str:
    """Le titre, sauf s'il contient un mot qui designe un AUTRE message (un
    nom de model peut en contenir un) : on retombe alors sur « ✨ General »."""
    bas = (titre or "").lower()
    if "menu" in bas or "jailbreak" in bas:
        return "✨ General"
    return titre


def _jb_general_texte(titre, lignes=()) -> str:
    """Le texte du General (son TextDisplay) : le titre, les lignes, et en
    DERNIERE ligne la marque qui le designe (_JB_GENERAL_MARQUE) -- le format
    V2 n'a pas de pied d'embed ou la mettre.

    Coupe sous le plafond de Discord (4000) AVANT la marque : une longue
    liste de liens ecartes ne doit ni faire refuser le message entier, ni
    emporter la marque (sans elle, le General ne serait plus reconnu et un
    second serait pose a cote). La coupe est journalisee."""
    corps = "\n".join(["## " + _titre_general(titre)] + [l for l in lignes if l is not None])
    fin = "\n" + _JB_GENERAL_MARQUE
    place = _JB_TEXTE_V2_MAX - _long_discord(fin)
    if _long_discord(corps) > place:
        log.warning("General : texte trop long (%d > %d), coupe",
                    _long_discord(corps), place)
        corps = _couper_discord(corps, place - 1) + "…"
    return corps + fin


def _jb_general_ids_poses(model, reserves, active, qty) -> list:
    """Tous les custom_id que le General de `model` porterait : ce sont
    EUX que Discord mesure (100 au plus). Un seul trop long fait refuser le
    message ENTIER."""
    ids = [f"jbg:r:{model}:{r}:{qty}" for r in reserves]
    ids.append(f"jbg:qb:{model}:{active}:{qty}")
    ids += [f"jbg:a:{model}:{active}:{k}:{qty}" for k in _JB_GEN_BOUTONS]
    ids += [f"jbg:s:{model}:{active}:{f.cle}:{qty}" for f in _JB_GEN_FAMILLES]
    return ids


def _jb_general(cog, model, qty=3, reserve=None, guild=None):
    """Le menu ✨ General de `model` : une LayoutView « Components V2 », comme
    le panneau d'actions. Plus d'embed : il ne rend que la vue.

    Un bloc (conteneur a accent turquoise -- la couleur de l'ancien embed,
    qui le distingue du panneau rouge juste au-dessus) : le texte en tete,
    puis, quand il y a de quoi servir :
      - rangee : les reserves liees en boutons de choix (s'il y en a
        plusieurs, 4 au plus) + 📦 Quantite ;
      - rangee : les boutons de _JB_GEN_BOUTONS (PP, Bio, Story, Story CTA,
        Post) ;
      - un menu deroulant par famille de _JB_GEN_FAMILLES (Caption,
        Template, Trash, Flash).

    Les etats sans action n'ont QUE le texte : edite, le message perd donc
    les boutons de la model PRECEDENTE, qui serviraient SA brute.
      - « _ » : aucune model choisie, on attend le clic au-dessus ;
      - aucune reserve retenue : on le dit, avec les liens ecartes et leur
        raison (rien n'est ecarte en silence), et le chemin sur le site ;
      - sinon : la reserve active (`reserve` si elle est encore liee, sinon
        la premiere), et ses voisines en boutons de choix.
    `cog` n'est pas lu : il est la pour la symetrie avec _jb_panel.
    """
    ui = discord.ui
    model = (model or "_").strip().lower() or "_"
    try:
        qty = max(1, int(qty))
    except (TypeError, ValueError):
        qty = 3

    def _vue(titre, lignes, rangees=()):
        vue = ui.LayoutView(timeout=None)
        boite = ui.Container(accent_colour=discord.Colour.teal())
        vue.add_item(boite)
        boite.add_item(ui.TextDisplay(_jb_general_texte(titre, lignes)))
        for r in rangees:
            boite.add_item(r)
        return vue

    if model == "_":
        return _vue("✨ General — choisis une model au-dessus 👆", [
            "Quand tu cliques une model, ce message sert le contenu des "
            "**réserves** qui lui sont liées : PP, bios, stories, posts, "
            "captions, templates, " + _marques_en_toutes_lettres() + "."])
    nom = model.capitalize()
    if _est_reserve_sure(model):
        return _vue(f"✨ General — {nom} est une réserve",
                    ["Une réserve ne se choisit pas dans la grille : "
                     "clique une model qui y est liée."])
    try:
        import type_identite as _ti
        retenues, ecartees = _ti.reserves_liees(model)
    except Exception as e:
        log.warning("General %s : liens des reserves illisibles (%s: %s)",
                    model, type(e).__name__, e)
        return _vue(f"✨ General — {nom}",
                    [f"Liens des réserves illisibles ({type(e).__name__}) : "
                     "reclique la model dans un instant."])
    # Le custom_id n'accepte que [a-z0-9_.-] (motif des boutons) : un nom
    # hors de ce jeu ferait lever discord.py a la construction, et le
    # General entier tomberait. On l'ecarte, en le disant.
    _hors_motif = [r for r in retenues if not _JB_NOM_BOUTON.fullmatch(r)]
    if _hors_motif:
        retenues = [r for r in retenues if r not in _hors_motif]
        ecartees = list(ecartees) + [(r, "nom illisible dans un bouton Discord")
                                     for r in _hors_motif]
    if not _JB_NOM_BOUTON.fullmatch(model):
        return _vue(f"✨ General — {nom}",
                    ["Nom de model illisible dans un bouton Discord "
                     "(lettres minuscules, chiffres, « _ . - ») : "
                     "renomme-la sur le site."])
    lignes_ecartees = [f"• `{n}` : {r}" for n, r in ecartees[:10]]
    if len(ecartees) > 10:
        lignes_ecartees.append(f"• … et {len(ecartees) - 10} autre(s)")
    if not retenues:
        desc = [f"Rien à servir ici pour **{nom}**."]
        if lignes_ecartees:
            desc.append("Lien(s) écarté(s) :")
            desc += lignes_ecartees
        desc.append(f"Pour en lier une : site → **Bibliothèque › {nom} › "
                    "Modifier › Réserves liées**.")
        return _vue(f"✨ General — aucune réserve liée à {nom}", desc)
    reserve = (reserve or "").strip().lower()
    active = reserve if reserve in retenues else retenues[0]
    montrees = []
    if len(retenues) >= 2:
        montrees = retenues[:_JB_GEN_MAX_RESERVES]
        # La reserve active reste toujours visible et marquee, meme si un
        # custom_id plus ancien la designe au-dela des quatre premieres.
        if active not in montrees:
            montrees[-1] = active
    # Un custom_id de plus de 100 caracteres fait refuser le message ENTIER
    # par Discord : on le dit plutot que de poster des boutons morts. Chaque
    # reserve montree est mesuree comme si elle etait l'active : cliquer son
    # bouton ne doit pas mener a un General sans boutons.
    _plus_long = max(len(i) for r in (montrees or [active])
                     for i in _jb_general_ids_poses(model, montrees, r, qty))
    if _plus_long > _JB_CUSTOM_ID_MAX:
        log.warning("General %s : custom_id de %d caracteres (> %d), noms trop "
                    "longs", model, _plus_long, _JB_CUSTOM_ID_MAX)
        return _vue(f"✨ General — {nom}",
                    [f"Noms trop longs pour Discord ({_plus_long} caractères "
                     f"sur {_JB_CUSTOM_ID_MAX}) : raccourcis le nom de la "
                     "model ou de la réserve sur le site."])
    rangees = []
    haut = ui.ActionRow()
    for r in montrees:
        haut.add_item(JBGenReserveBouton(model, r, qty, active=(r == active)))
    haut.add_item(JBGenQtyBouton(model, active, qty))
    rangees.append(haut)
    _ic = icones_actions(guild)          # lecture seule : rien sur le reseau
    manquantes = []
    boutons = ui.ActionRow()
    for key in _JB_GEN_BOUTONS:
        entree = _jb_action(key)
        if entree is None:
            manquantes.append(key)
            continue
        boutons.add_item(JBGenButton(model, active, key, qty, label=entree[1],
                                     row=None, icone=_ic.get(key)))
    if boutons.children:
        rangees.append(boutons)
    for fam in _JB_GEN_FAMILLES:
        menu = JBGenMenu(model, active, fam.cle, qty, icones=_ic)
        manquantes += menu.inconnues
        if menu.vide:
            # Un menu sans option serait refuse par Discord, et le General
            # ENTIER avec lui : on le retire, en le disant.
            manquantes.append(f"menu {fam.cle}")
            continue
        r = ui.ActionRow()
        r.add_item(menu)
        rangees.append(r)
    if manquantes:
        log.warning("General : actions inconnues de _jb_action, absentes : %s",
                    ", ".join(manquantes))
    act = active.capitalize()
    desc = [f"Contenu de la réserve **{act}**. Caption, Template, "
            + _marques_en_toutes_lettres(majuscule=True)
            + f" sont posés sur une brute de **{nom}**."]
    if montrees:
        desc.append(f"{len(retenues)} réserves liées : clique un nom ci-dessous "
                    "pour changer de réserve.")
        cachees = [r for r in retenues if r not in montrees]
        if cachees:
            desc.append(f"+{len(cachees)} autre(s), sans bouton (4 au plus) : "
                        + ", ".join(cachees[:10])
                        + ("…" if len(cachees) > 10 else "") + ".")
    if lignes_ecartees:
        desc.append("Lien(s) écarté(s) :")
        desc += lignes_ecartees
    if manquantes:
        desc.append(f"⚠️ {len(manquantes)} action(s) indisponible(s) : "
                    + ", ".join(manquantes) + " (à signaler à un admin).")
    desc.append(f"\n📦 **Quantité : {qty} média par action** "
                "_(bouton Quantité, puis tape le nombre)_.")
    desc.append("Le contenu arrive dans ton salon **-content** 👇")
    return _vue(f"✨ General — {act} pour {nom}", desc, rangees)


def _jb_gen_controle(interaction, model, res, key):
    """(refus, cmd, supports_count) d'un clic du ✨ General, bouton OU menu.

    `refus` vaut "" quand l'action peut partir. Les memes gardes, dans le
    meme ordre, pour les deux : role Jailbreak, liste blanche du General
    (_JB_GENERAL_RANGEES), action connue du cog, model devenue reserve, lien
    model-reserve REVERIFIE, brute de la model. Deux copies de ces gardes
    divergeraient au premier correctif : un menu servirait ce qu'un bouton
    refuse.

    Ne repond pas : l'appelant choisit comment dire le refus (ephemere pour
    un bouton ; pour un menu, le message redessine -- le menu reprend son
    intitule -- et la raison en suivi)."""
    if not _jb_can_use(interaction):
        return _JB_REFUS_ROLE, None, False
    if key not in _JB_GENERAL_RANGEES:
        return f"Action `{key}` absente du ✨ General.", None, False
    cog = interaction.client.get_cog("UserCog")
    entree = _jb_action(key)
    if cog is None or entree is None:
        return f"Action indisponible (`{key}`).", None, False
    _k, _label, cmd_attr, supports_count = entree
    cmd = getattr(cog, cmd_attr, None)
    if cmd is None:
        return f"Action indisponible (`{cmd_attr}`).", None, False
    # La model a pu devenir une reserve depuis que ce General est affiche.
    _refus = _refus_reserve_jb(model)
    if _refus:
        return _refus, None, False
    nom, nres = model.capitalize(), res.capitalize()
    # LE LIEN EST REVERIFIE AU CLIC : il a pu etre retire sur le site,
    # la reserve changer de marche ou de nature, depuis que ce message est
    # affiche. Rien ne se rafraichit tout seul dans le salon.
    try:
        import type_identite as _ti
        retenues, ecartees = _ti.reserves_liees(model)
    except Exception as e:
        log.warning("General %s/%s : liens illisibles (%s: %s)",
                    model, res, type(e).__name__, e)
        return "Liens des réserves illisibles : réessaie dans un instant.", None, False
    if res not in retenues:
        raison = dict(ecartees).get(res)
        return (f"La réserve **{nres}** n'est plus liée à **{nom}**"
                + (f" ({raison})" if raison else "")
                + ". Reclique la model au-dessus : ce message se remet à jour.",
                None, False)
    if key in _JB_GEN_BRUTE:
        try:
            import brutes_off as _off
            brutes = _off.lister(IDENTITIES_DIR / model / "brutes",
                                 extensions=VIDEO_EXTS)
        except Exception as e:
            # La commande relit le meme dossier et dira son propre echec.
            log.warning("General %s : brutes illisibles (%s: %s)",
                        model, type(e).__name__, e)
            brutes = None
        if brutes is not None and not brutes:
            return (f"**{nom}** n'a aucune vidéo brute active : "
                    f"{_libelle_sans_emoji(_label)} pose le contenu de "
                    f"**{nres}** sur une brute de la model.\n"
                    f"_(Un admin en ajoute sur le site, onglet **Vidéo brut** "
                    f"de {nom}.)_", None, False)
    return "", cmd, supports_count


async def _jb_general_reposer(chan, ancien, vue, raison):
    """Le repli du General quand Discord refuse de l'editer (le convertir en
    V2) : le repli commun (_jb_message_reposer), memorise dans
    us_general_panels.json. Le nouveau se pose en bas du salon, donc SOUS le
    panneau d'actions : l'ordre des trois messages tient.

    Meme signature que le `reposer` de _jb_panneau_en_reponse."""
    return await _jb_message_reposer(
        chan, ancien, vue, lambda mid: _jb_general_set(chan.id, mid),
        "General", raison)


async def _jb_general_convertir(interaction, model, res, qty) -> bool:
    """Passe au format V2 l'ANCIEN General (embed) d'ou vient un clic
    d'action : son premier clic, quel qu'il soit, le convertit -- le choix
    de reserve et la quantite le font en redessinant (_jb_panneau_en_reponse),
    une action le fait ici.

    Rien a faire pour un General deja V2 (le cas de tous, apres le premier
    clic) ni pour un ephemere. La vue garde la model, la reserve et la
    quantite du bouton clique : le General ne change que de format. Discord
    refuse l'edition : un NOUVEAU General V2 le remplace (_jb_general_reposer).

    Appele APRES l'action : retirer le message du clic pendant qu'elle y
    repond ferait echouer sa reponse. Ne leve jamais -- l'action est deja
    partie, c'est l'essentiel ; un echec est journalise, et le prochain clic
    sur une model (_jb_general_maj) reessaiera.

    LE MESSAGE EST RELU AVANT D'ETRE CONVERTI. interaction.message est une
    photo prise au clic : ses drapeaux disent « ancien format » pour
    toujours, alors que l'action a pu durer 30 s. Pendant ce temps, un clic
    sur une model (_jb_general_maj), sur une reserve ou sur la quantite a pu
    deja convertir ce General -- pour une autre model ou une autre reserve.
    Convertir d'apres la photo le remettait sur « Blonde pour Lola » pendant
    que le panneau montrait Julia (simule le 26/09/2026). Un General deja V2
    ne coute aucun appel de plus : on ne relit que si la photo dit « ancien
    format »."""
    msg = getattr(interaction, "message", None)
    try:
        if msg is None or getattr(getattr(msg, "flags", None), "ephemeral", False):
            return False
        if not _jb_kw_format(msg) or not _est_general(msg):
            return False
        chan = getattr(interaction, "channel", None)
        if chan is None:
            # Sans salon, pas de relecture : convertir a l'aveugle pourrait
            # ecraser un General deja passe sur une autre model.
            log.warning("General : ancien message %s non converti, pas de salon "
                        "pour le relire", msg.id)
            return False
        try:
            frais = await chan.fetch_message(msg.id)
        except discord.NotFound:
            log.info("General : message %s disparu avant sa conversion", msg.id)
            return False
        kw = _jb_kw_format(frais)
        if not kw:
            log.info("General %s : deja converti pendant l'action, rien a "
                     "ecraser", msg.id)
            return False
        if not _est_general(frais):
            log.warning("General : le message %s n'est plus le General, non "
                        "converti", msg.id)
            return False
        # Meme garde que _jb_remettre_epingle : un clic sur une model note le
        # panneau AVANT de mettre le General a jour (_jb_general_maj). Si le
        # panneau est deja sur une autre model, sa mise a jour est en cours
        # (ou a echoue) : la conversion pour la model du clic la defairait.
        etat = _JB_PANNEAU_COURANT.get(int(getattr(chan, "id", 0) or 0))
        if etat is not None and etat[0] != (model or "").lower():
            log.info("General %s : le panneau est passe sur %s, pas de "
                     "conversion pour %s", msg.id, etat[0], model)
            return False
        vue = _jb_general(interaction.client.get_cog("UserCog"), model, qty,
                          reserve=res, guild=getattr(interaction, "guild", None))
        try:
            await frais.edit(view=vue, **kw)
            return True
        except discord.NotFound:
            log.info("General : message %s disparu avant sa conversion", msg.id)
            return False
        except discord.HTTPException as e:
            await _jb_general_reposer(chan, frais, vue, f"conversion refusee "
                                                        f"({type(e).__name__}: {e})")
            return True
    except Exception as e:                                   # noqa: BLE001
        log.warning("General : ancien message %s non converti (%s: %s)",
                    getattr(msg, "id", "?"), type(e).__name__, e)
        return False


class JBGenButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"jbg:a:(?P<model>[a-z0-9_.\-]+):(?P<res>[a-z0-9_.\-]+)"
                           r":(?P<key>[a-z]+):(?P<qty>\d+)"):
    """Une action du ✨ General : le contenu de la reserve `res`, la brute de
    la model `model`. Tout l'etat voyage dans le custom_id : le bouton repond
    encore apres un redemarrage.

    Le General V2 ne pose plus en boutons que PP, Bio, Story, Story CTA et
    Post ; Caption, Template, Trash et Flash sont dans ses menus (JBGenMenu).
    Les anciens General portent encore leurs boutons « jbg:a:…:reelcaption:… »
    etc. : la liste blanche est la meme (_JB_GENERAL_RANGEES), ils repondent
    toujours, et leur premier clic convertit le message (_jb_general_convertir)."""

    def __init__(self, model, res, key, qty, label=None, row=1, icone=None):
        self.model = (model or "_").lower()
        self.res = (res or "_").lower()
        self.key = key
        self.qty = int(qty)
        _e = _jb_action(key)
        lib = label or (_e[1] if _e else key)
        _btn = discord.ui.Button(
            label=(_libelle_sans_emoji(lib) if icone is not None else lib),
            style=discord.ButtonStyle.primary, row=row,
            custom_id=f"jbg:a:{self.model}:{self.res}:{self.key}:{self.qty}")
        if icone is not None:
            _btn.emoji = icone
        super().__init__(_btn)

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["model"], match["res"], match["key"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        refus, cmd, sc = _jb_gen_controle(interaction, self.model, self.res, self.key)
        if refus:
            await interaction.response.send_message(refus, ephemeral=True)
            return
        await interaction.client.get_cog("UserCog")._run_for_model(
            interaction, self.res, cmd, count=self.qty, supports_count=sc,
            brute_de=self.model)
        await _jb_general_convertir(interaction, self.model, self.res, self.qty)


class JBGenMenu(discord.ui.DynamicItem[discord.ui.Select],
                template=r"jbg:s:(?P<model>[a-z0-9_.\-]+):(?P<res>[a-z0-9_.\-]+)"
                         r":(?P<fam>[a-z]+):(?P<qty>\d+)"):
    """Le menu deroulant d'une famille du ✨ General (« 💬 Caption… »).

    Ses options sont les variantes retenues pour le General
    (_JB_GEN_FAMILLES), construites comme celles du panneau d'actions
    (_jb_options_famille : libelle de production, ligne d'explication, icone
    du serveur). Tout l'etat (model, reserve, famille, quantite) est dans le
    custom_id : le menu repond encore apres un redemarrage.

    Au choix : les gardes de JBGenButton (_jb_gen_controle), la valeur
    VALIDEE contre sa famille, puis _run_for_model exactement comme le bouton
    (contenu de la reserve, brute de la model). Le menu reprend ensuite son
    intitule -- sinon re-choisir la meme variante ne declencherait rien --
    par la mecanique du panneau d'actions (_jb_remettre_epingle,
    _menu_lancer, _jb_menu_refuser), pas par une seconde.

    Prefixe « jbg:s: » : il ne recoupe aucun autre motif (jbg:a/qb/r,
    jbus:) -- discord.py les lance TOUS quand ils correspondent.
    """

    def __init__(self, model, res, famille, qty, icones=None):
        self.model = (model or "_").lower()
        self.res = (res or "_").lower()
        self.famille = famille
        self.qty = int(qty)
        fam = _jb_gen_famille(famille)
        if fam is not None:
            opts, self.inconnues = _jb_options_famille(fam, icones)
            intitule = _jb_placeholder_famille(fam)
        else:
            opts, self.inconnues, intitule = [], [], f"{famille}…"
        #: Aucune option : _jb_general ne pose pas ce menu (Discord refuserait
        #: le message ENTIER) et le dit. L'option factice ne sert qu'a
        #: construire l'objet quand un vieux custom_id revient.
        self.vide = not opts
        if not opts:
            opts = [discord.SelectOption(label="(aucune variante)", value="_")]
        super().__init__(discord.ui.Select(
            placeholder=intitule, min_values=1, max_values=1, options=opts,
            custom_id=f"jbg:s:{self.model}:{self.res}:{self.famille}:{self.qty}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["model"], match["res"], match["fam"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        choix = (getattr(self.item, "values", None) or [""])[0]
        cog = interaction.client.get_cog("UserCog")
        msg = getattr(interaction, "message", None)
        ephemere = bool(getattr(getattr(msg, "flags", None), "ephemeral", False))

        def _frais():
            """Le General tel qu'il etait avant le choix : ses menus sur leur
            intitule. Relu (liens des reserves compris) : s'il a change
            entre-temps, c'est l'etat du moment qu'on affiche."""
            v = _jb_general(cog, self.model, self.qty, reserve=self.res,
                            guild=interaction.guild)
            return _vue_sans_suivi(v) if ephemere else v

        fam = _jb_gen_famille(self.famille)
        refus, cmd, sc = "", None, False
        if not _jb_can_use(interaction):
            refus = _JB_REFUS_ROLE
        elif fam is None:
            refus = (f"Famille indisponible (`{self.famille}`) : reclique la "
                     "model au-dessus, ce message se remet à jour.")
        elif choix not in fam.actions:
            # Hors de la liste blanche de la famille : ce choix ne vient pas
            # d'un menu que le bot a pose. Refuse, et trace.
            log.warning("General : choix %r refuse (famille %r, model %r, "
                        "reserve %r)", choix, self.famille, self.model, self.res)
            refus = f"Option inconnue (`{choix}`) : reclique la model au-dessus."
        else:
            refus, cmd, sc = _jb_gen_controle(interaction, self.model,
                                              self.res, choix)
        if refus:
            await _jb_menu_refuser(interaction, refus, _frais())
            return
        # Le General du SALON se redessine tout de suite, sans attendre la fin
        # d'un rendu de 30 s -- sauf s'il a deja suivi une autre model
        # (_jb_remettre_epingle, qty=None). Un ephemere n'a pas ce chemin :
        # il est redessine apres coup, par l'interaction (_menu_lancer).
        tache = None
        if not ephemere and msg is not None:
            tache = _jb_en_fond(
                _jb_remettre_epingle(interaction, self.model, None, _frais(),
                                     quoi="General"),
                "General : menu remis sur son intitule")
        await _menu_lancer(
            interaction,
            lambda: cog._run_for_model(interaction, self.res, cmd, count=self.qty,
                                       supports_count=sc, brute_de=self.model),
            choix, _frais(), tache, "General",
            detail=f" pour {self.res} (brute de {self.model})")


class JBGenQtyBouton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"jbg:qb:(?P<model>[a-z0-9_.\-]+):(?P<res>[a-z0-9_.\-]+)"
                              r":(?P<qty>\d+)"):
    """La quantite du ✨ General : meme fenetre de saisie que le panneau
    d'actions, et la reserve active reste celle qu'on regardait."""

    def __init__(self, model, res, qty):
        self.model = (model or "_").lower()
        self.res = (res or "_").lower()
        self.qty = int(qty)
        super().__init__(discord.ui.Button(
            label=f"📦 Quantité : {self.qty} — clique pour changer",
            style=discord.ButtonStyle.secondary, row=0,
            custom_id=f"jbg:qb:{self.model}:{self.res}:{self.qty}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["model"], match["res"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        if not _jb_can_use(interaction):
            await interaction.response.send_message(
                "🔒 Réservé aux VA **Jailbreak** (rôle « Jailbreak »).", ephemeral=True)
            return

        async def _suite(inter, q):
            vue2 = _jb_general(inter.client.get_cog("UserCog"), self.model,
                               q, reserve=self.res, guild=inter.guild)
            # Depuis une soumission de Modal, edit_message modifie le message
            # d'origine : pas de General en double dans le salon. Un ancien
            # General (embed) passe en V2 au passage ; si Discord refuse, un
            # nouveau General V2 le remplace (_jb_general_reposer).
            await _jb_panneau_en_reponse(inter, vue2, self.model, quoi="General",
                                         reposer=_jb_general_reposer)

        await interaction.response.send_modal(_JBQtyModal(_suite))


class JBGenReserveBouton(discord.ui.DynamicItem[discord.ui.Button],
                         template=r"jbg:r:(?P<model>[a-z0-9_.\-]+):(?P<res>[a-z0-9_.\-]+)"
                                  r":(?P<qty>\d+)"):
    """Choix de la reserve active, quand une model en a plusieurs. Une seule
    a la fois : les fonctions de tirage ne prennent qu'une identite."""

    def __init__(self, model, res, qty, active=False):
        self.model = (model or "_").lower()
        self.res = (res or "_").lower()
        self.qty = int(qty)
        super().__init__(discord.ui.Button(
            label=_couper_discord(self.res.capitalize(), 80),
            style=(discord.ButtonStyle.success if active
                   else discord.ButtonStyle.secondary), row=0,
            custom_id=f"jbg:r:{self.model}:{self.res}:{self.qty}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["model"], match["res"], match["qty"])

    async def callback(self, interaction: discord.Interaction):
        if not _jb_can_use(interaction):
            await interaction.response.send_message(
                "🔒 Réservé aux VA **Jailbreak** (rôle « Jailbreak »).", ephemeral=True)
            return
        # _jb_general revalide le lien : une reserve deliee entre-temps
        # retombe sur la premiere encore liee, ou sur l'etat « aucune ».
        # Un ancien General (embed) passe en V2 au passage, avec son repli.
        vue = _jb_general(interaction.client.get_cog("UserCog"), self.model,
                          self.qty, reserve=self.res, guild=interaction.guild)
        await _jb_panneau_en_reponse(interaction, vue, self.model, quoi="General",
                                     reposer=_jb_general_reposer)


def _jb_general_ids() -> dict:
    """{str(id du salon): str(id du General)}. Un fichier a part de
    us_panels.json : celui-la est lu par int(), un autre format y casserait
    le panneau d'actions."""
    try:
        d = safe_json.load(_JB_GENERAL_STORE, default={}) or {}
    except Exception as e:
        log.warning("us_general_panels.json illisible (%s: %s)",
                    type(e).__name__, e)
        return {}
    if not isinstance(d, dict):
        return {}
    return {str(k): str(v) for k, v in d.items()}


def _jb_general_set(channel_id, message_id):
    d = _jb_general_ids()
    d[str(channel_id)] = str(int(message_id))
    try:
        safe_json.write(_JB_GENERAL_STORE, d, indent=2)
    except Exception as e:
        # Sans l'id, le prochain clic cherche le General dans les epingles :
        # plus lent, pas faux. On le dit quand meme.
        log.warning("us_general_panels.json non ecrit (%s: %s)",
                    type(e).__name__, e)


def _jb_panneaux_oublier(channel_id):
    """Oublie les ids memorises du panneau d'actions ET du General d'un
    salon (messages supprimes). Un seul point d'oubli pour les deux fichiers :
    cogs/welcome.py l'appelle au lieu d'ecrire ces chemins en dur."""
    cle = str(channel_id)
    for chemin, lire in ((_JB_PANEL_STORE, _jb_panel_ids),
                         (_JB_GENERAL_STORE, _jb_general_ids)):
        d = lire()
        if cle not in d:
            continue
        d.pop(cle, None)
        try:
            safe_json.write(chemin, d, indent=2)
        except Exception as e:
            log.warning("%s : id du salon %s non oublie (%s: %s)",
                        chemin.name, cle, type(e).__name__, e)


def _est_general(m, moi=None) -> bool:
    """Ce message est-il le ✨ General, dans l'un ou l'autre format ?

    L'ancien (embed) se reconnait au pied « panneau-general-us », le V2 a la
    derniere ligne « -# panneau-general-us » de son texte -- le meme reperage
    que le panneau d'actions (_porte_marque). Toute recherche du General
    (_jb_general_maj, _delete_old_menus, cogs/welcome.py) passe par ici :
    rater le V2, c'etait en poser un second, ou le supprimer comme un menu.

    `moi` : l'id du bot ; donne, un message d'un autre auteur n'est jamais le
    General. Ne leve jamais."""
    return _porte_marque(m, _JB_GENERAL_FOOTER, moi, "General")


async def _jb_general_editer(chan, m, vue) -> bool:
    """Edite le General `m` (un message complet : son format est connu) avec
    `vue`, en le convertissant au format V2 s'il est encore ancien : texte et
    embed vides dans la meme edition (_jb_kw_format).

    Conversion refusee par Discord : un NOUVEAU General V2 le remplace
    (_jb_general_reposer), comme pour le panneau d'actions. Un General deja
    V2 dont l'edition echoue fait LEVER : l'appelant journalise, et en
    reposer un ferait un doublon dont les boutons serviraient l'ancienne
    model."""
    kw = _jb_kw_format(m)
    try:
        await m.edit(view=vue, **kw)
    except discord.NotFound:
        raise
    except discord.HTTPException as e:
        if not kw:
            raise
        await _jb_general_reposer(chan, m, vue, f"conversion refusee "
                                                f"({type(e).__name__}: {e})")
        return True
    _jb_general_set(chan.id, m.id)
    return True


async def _jb_general_maj(client, chan, model, guild, reposter=False):
    """Met le ✨ General du salon `chan` a jour pour `model`. -> True si fait.

    Edite par l'id memorise, sans le relire (un appel reseau de moins) ; a
    defaut cherche dans les epingles, sous ses deux formats (_est_general) ;
    a defaut le poste, l'epingle et memorise son id.

    UN ANCIEN GENERAL (embed) PASSE EN V2 ICI, au premier clic sur une model.
    Discord refuse une vue V2 sur un message qui garde son embed : l'edition
    par l'id echoue, on relit alors le message pour connaitre son format, et
    on le convertit (_jb_general_editer) -- avec le repli d'un nouveau
    General si Discord refuse encore. Une fois converti, l'edition par l'id
    passe du premier coup.

    reposter=True : le panneau d'actions vient d'etre RECREE en bas du salon.
    Un General simplement edite resterait au-dessus de lui ; on supprime
    l'ancien et on en poste un nouveau, dessous.
    """
    if chan is None:
        return False
    cog = client.get_cog("UserCog") if client is not None else None
    vue = _jb_general(cog, model, 3, guild=guild)
    moi = getattr(getattr(client, "user", None), "id", None)
    _nom = getattr(chan, "name", "?")
    memo = _jb_general_ids().get(str(chan.id))
    try:
        epingles = None
        if reposter:
            anciens = set()
            if memo:
                try:
                    anciens.add(int(memo))
                except ValueError:
                    pass
            try:
                epingles = await chan.pins()
                anciens |= {m.id for m in epingles if _est_general(m, moi)}
            except Exception as e:
                log.warning("General %s : epingles illisibles (%s: %s)",
                            _nom, type(e).__name__, e)
            for mid in anciens:
                try:
                    await chan.get_partial_message(mid).delete()
                except Exception as e:
                    # Deja supprime le plus souvent (NotFound) : sans gravite,
                    # mais un General reste peut-etre au-dessus du panneau.
                    log.info("General %s : ancien message %s non supprime "
                             "(%s)", _nom, mid, type(e).__name__)
        else:
            if memo:
                try:
                    await chan.get_partial_message(int(memo)).edit(view=vue)
                    return True
                except (discord.NotFound, discord.Forbidden, ValueError):
                    pass                       # supprime ou id perime : on cherche
                except discord.HTTPException as e:
                    # Refuse : un ANCIEN General (embed) a convertir, ou un
                    # autre refus (debit, panne). Seul le message le dit : on
                    # le relit. Deja V2, le message existe sans doute encore,
                    # en poster un second ferait un doublon dont les boutons
                    # serviraient l'ancienne model.
                    try:
                        ancien = await chan.fetch_message(int(memo))
                    except Exception as e2:            # noqa: BLE001
                        log.warning("General %s : edition refusee (%s: %s), "
                                    "message illisible (%s)", _nom,
                                    type(e).__name__, e, type(e2).__name__)
                        return False
                    if _est_general(ancien, moi):
                        if not _jb_kw_format(ancien):
                            log.warning("General %s : edition refusee (%s: %s)",
                                        _nom, type(e).__name__, e)
                            return False
                        return await _jb_general_editer(chan, ancien, vue)
                    # L'id memorise designe un AUTRE message : on cherche le
                    # General dans les epingles, comme sans memoire.
                    log.warning("General %s : l'id memorise %s n'est pas le "
                                "General, recherche dans les epingles", _nom, memo)
            try:
                epingles = await chan.pins()
            except Exception as e:
                log.warning("General %s : epingles illisibles (%s: %s)",
                            _nom, type(e).__name__, e)
                epingles = []
            for m in epingles:
                if _est_general(m, moi):
                    return await _jb_general_editer(chan, m, vue)
        msg = await chan.send(view=vue)
        _jb_general_set(chan.id, msg.id)
        try:
            await msg.pin()
        except Exception as e:
            log.warning("General %s : pose mais non epingle (%s: %s)",
                        _nom, type(e).__name__, e)
        return True
    except Exception as e:
        log.warning("General %s / %s : %s: %s", _nom, model,
                    type(e).__name__, e)
        return False


class GenLinkModal(discord.ui.Modal, title="🔗 Générer un lien GetMySocial"):
    identite = discord.ui.TextInput(
        label="Identité (modèle)", placeholder="ex: sarah, amelia, julia…",
        required=True, max_length=40,
    )
    pseudo = discord.ui.TextInput(
        label="Pseudo du VA (pour nommer le lien)", placeholder="ex: ozen28 (optionnel)",
        required=False, max_length=40,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if not _menu_feature_check(interaction, "liens"):
            await interaction.response.send_message("⚠️ Génération de lien désactivée sur ce serveur.", ephemeral=True)
            return
        ident = str(self.identite.value or "").strip().lower()
        handle = str(self.pseudo.value or "").strip().lstrip("@")
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        # Bloc DUR anti-doublon : si ce pseudo a déjà un lien va_@<handle>, on refuse.
        # Match STRICT (pas de substring) pour ne pas bloquer un pseudo voisin.
        if handle:
            try:
                _all = await asyncio.to_thread(gms.list_all_links)
            except Exception:
                _all = {"ok": False}
            if not _all.get("ok"):
                await interaction.followup.send(
                    "⚠️ Impossible de vérifier sur GetMySocial pour l'instant (API indispo). "
                    "Génération annulée par sécurité (anti-doublon) — réessaie dans un instant.",
                    ephemeral=True,
                )
                return
            _hit = _gms_exact_link(handle, _all.get("links") or [])
            if _hit:
                _sc = _hit.get("shortcode", "")
                _u = f"{gms.PUBLIC_LINK_DOMAIN}/{_sc}" if _sc else ""
                await interaction.followup.send(
                    f"🔒 **`@{handle}` a déjà un lien** — génération bloquée (anti-doublon)."
                    + (f"\n🔗 {_u}" if _u else "")
                    + "\n\n_Pour en recréer un, il faudra une commande dédiée (pas encore dispo)._",
                    ephemeral=True,
                )
                return
        try:
            res = await asyncio.to_thread(gms.quick_generate_for_identity, ident, handle)
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        if not res.get("ok"):
            await interaction.followup.send(f"❌ {res.get('error', 'Génération échouée')}", ephemeral=True)
            return
        url = res.get("public_url", "")
        # Si un salon va-<pseudo> existe, on y dépose aussi le lien
        posted = ""
        if handle:
            import re as _re_h
            for g in interaction.client.guilds:
                vch = discord.utils.find(
                    lambda c: _re_h.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (c.name or "").lower())
                    and _re_h.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (c.name or "").lower()).group(1) == handle.lower(),
                    g.text_channels,
                )
                if vch:
                    try:
                        await vch.send(_link_message(url, getattr(vch, "guild", None)))
                        posted = f"\n→ envoyé dans {vch.mention}"
                    except Exception:
                        pass
                    try:
                        await _apply_va_link_mark(vch, True, reason="lien généré")
                    except Exception:
                        pass
                    break
        await interaction.followup.send(
            f"✅ **Lien généré** — {res.get('va_name', '')} · identité `{ident}`\n"
            f"🔗 {url}\nShortcode `/{res.get('shortcode', '')}`{posted}",
            ephemeral=True,
        )


class LinkPanelView(discord.ui.View):
    """Panneau permanent : un bouton 'Générer un lien' qui ouvre le mini-formulaire."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Générer un lien", emoji="🔗", style=discord.ButtonStyle.success, custom_id="linkpanel:gen")
    async def gen(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _is_staff_member(interaction.user):
            await interaction.response.send_message("Réservé aux managers/admins.", ephemeral=True)
            return
        if not _menu_feature_check(interaction, "liens"):
            await interaction.response.send_message("⚠️ Génération de lien désactivée sur ce serveur.", ephemeral=True)
            return
        await interaction.response.send_modal(GenLinkModal())


async def setup(bot):
    await bot.add_cog(UserCog(bot))
