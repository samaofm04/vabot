# -*- coding: utf-8 -*-
"""🎬 Contenu dans le ticket d'un VA de TRUST INSTAGRAM.

POURQUOI (propriétaire, 30/10/2026)
    Le menu des identités US de Youl4b et YouCham dans le ticket des VA de
    TRUST INSTAGRAM, le contenu livré « dans leur ticket de base » (« je
    trouve que c'est plutôt pas mal »). La page de lien reste la même pour
    tous. Twitter et Threads ne changent pas.

OÙ ÇA VIT
    Un bouton « 🎬 Contenu » sur la 2e rangée du VA du menu épinglé
    (tickets_discord, enveloppe de boutons_va en fin de fichier, préfixe
    « cnt: »). TRUST INSTAGRAM n'a que Wario, en REST, sans gateway : chaque
    clic arrive sur /discord/interactions (web_upload._discord_repondre) et
    passe ici. Mêmes droits que 📤 et ⬇️ (outils_tickets._ticket_du_clic) :
    le VA du ticket, ou un manager/helper.

UN SEUL MESSAGE ÉPHÉMÈRE, QUI CHANGE D'ÉCRAN
    Le clic ouvre, pour le seul cliqueur, le menu des identités US — LE MÊME
    que celui des -menu de Youl4b (_jb_menu_models_vue : identités au drapeau
    US hors pause, menus de 10, jamais plus de 25 options par menu). Choisir
    une identité remplace ce message par SON panneau (_jb_panel : quantité,
    Name, Pseudo, PP, Bio, Story me/life/travel, Story CTA, Post, menus Brut,
    Caption, Template, Trash, Flash), puis « ✨ General » et « 👤 Identité »
    passent d'un écran à l'autre. Un message, réécrit sur place (réponse 7) :
    sur YouCham les éphémères empilés servaient la mauvaise identité (incident
    du 05/09/2026) ; ici il n'y en a qu'un, et chaque custom_id porte
    l'identité et la quantité — aucun état retenu. Les vues de cogs/user sont
    traduites en JSON (to_components) et leurs custom_id renommés « jbus: »
    → « cnt: », « jbg: » → « cng: » : une seule disposition, celle du menu US
    (« deux mappings valent deux comportements »).

    « 🎛️ Choisir ma brute » n'y est pas : il ouvre une vue discord.py de
    Yoshi, dont Wario ne recevrait jamais les clics.

LE MÊME MOTEUR QUE YOUL4B
    L'action part sur la boucle de Yoshi (bot principal, même processus) par
    cog._run_for_model, exactement comme un bouton du panneau US, avec une
    interaction FACTICE (_InteractionTicket) : tout ce que la commande envoie
    — réponse, suivi, salon, éphémère compris — part dans le TICKET par Wario
    en REST (cartes V2, flags 1<<15, et fichiers en multipart ; chaque texte à
    copier seul dans son message, comme partout). Le jeton du bot, jamais
    celui du clic : il meurt au bout de 15 minutes, un rendu en file en prend
    parfois plus. Deux livraisons dans le même ticket passent l'une après
    l'autre, ⬇️ et 📤 compris (outils_tickets.verrou_livraison) ; un clic qui
    attend son tour le dit (« ⏳ En file »). Le menu est reposé en dernier
    (ramener_menu, en_dernier). Chaque livraison acceptée est marquée sur le
    disque, celles en file comprises : un redémarrage les annonce toutes.

LIMITE DE TAILLE
    Celle du serveur (outils_tickets.limite_fichiers : 10 Mio sans boost),
    pour le message ENTIER, moins la marge de l'enveloppe (comme
    tl.repartir). Un message plus lourd n'est ni lu ni envoyé : la commande
    reçoit le refus que Discord aurait opposé (413) et le dit, comme sur
    Youl4b ; si rien ne l'a dit, une ligne le dit à la fin. Jamais écarté en
    silence.

UN CHOIX DE MENU DÉROULANT
    Toujours répondu en redessinant le message (type 7), refus compris, la
    raison en tête : Discord n'envoie rien pour une option déjà affichée.

CE QUI N'EST PAS ICI
    Aucune route, aucune commande slash. Aucun texte de notice, aucun
    montant, et jamais « YouLab » : les réponses d'interaction ne passent pas
    par la traduction TRUST de verif_discord.api.
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import re
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import outils_tickets as ot
# Les préfixes et les serveurs vivent avec le bouton, dans tickets_discord :
# le menu et les clics ne peuvent pas diverger.
from tickets_discord import (CONTENU_DANS_MENU as SERVEURS,
                             CONTENU_GENERAL_PREFIXE as GENERAL,
                             CONTENU_PREFIXE as PREFIXE)

#: IS_COMPONENTS_V2 : le panneau, ses menus et les cartes sont en « V2 ».
V2 = 1 << 15
#: Discord refuse le message ENTIER au-delà.
COMPOSANTS_MAX = 40
OPTIONS_MAX = 25
CUSTOM_ID_MAX = 100

#: Les livraisons en attente dans un ticket, en-cours compris : au-delà, le
#: clic est refusé. Sans plafond, dix clics impatients faisaient dix rendus
#: de suite pour un seul VA, devant tous les autres sur la boucle de Yoshi.
FILE_MAX = 5
#: Cinq messages par salon toutes les cinq secondes (limite de Discord) : on
#: attend son tour plutôt que d'enchaîner des 429, que verif_discord ne
#: retente que quatre fois — un texte à copier se serait perdu. L'attente se
#: fait sur la boucle (asyncio.sleep), jamais dans un fil : les fils de la
#: boucle de Yoshi servent aussi les encodages du spoofer.
RYTHME_N = 5
RYTHME_S = 5.2

#: Retirées du panneau du ticket (voir plus haut).
EXCLUES = frozenset({"brutchoix"})

TEXTE_FILE = "⏳ Trop d'envois en attente ici, attends qu'ils arrivent."
TEXTE_EXCLUE = "Pas dispo dans le ticket."
TEXTE_INCONNUE = "Action inconnue."
#: Le clic accepté qui attend son tour : un accusé muet laissait le VA
#: recliquer, trois rendus de plus en file pour rien.
TEXTE_EN_FILE = "⏳ En file ({n} avant), ça arrive dans ton ticket."
TEXTE_EN_FILE_AUTRE = "⏳ En file, ça arrive dans ton ticket."

_VERROU = threading.RLock()
#: {ticket: livraisons en attente ou en cours}
_EN_FILE: Dict[str, int] = {}
#: {ticket: instants des derniers messages postés}
_RYTHME: Dict[str, collections.deque] = {}


def _log(texte: str) -> None:
    print(f"[contenu] {texte}", flush=True)


async def _patienter(s: float) -> None:
    await asyncio.sleep(s)


# ─── Le bouton du menu ───────────────────────────────────────────────────
def bouton(uid: str) -> Dict[str, Any]:
    """« 🎬 Contenu », tel que tickets_discord le pose (décrit là-bas)."""
    import tickets_discord as tk
    return tk.bouton_contenu(uid)


# ─── Réponses à Discord ──────────────────────────────────────────────────
TEXTE_TROP_CHARGE = "Menu trop chargé pour Discord : préviens un admin."


def _dans_les_limites(composants: List[Dict[str, Any]], quoi: str) -> List[Dict[str, Any]]:
    """Discord refuse la réponse ENTIÈRE au-delà de 40 composants ou de 25
    options par menu, et le VA ne lit que « l'interaction a échoué ». Le
    refus est dit, et sa cause au journal."""
    n = compter(composants)
    pleins = [c for c in _a_plat(composants)
              if c.get("type") == 3 and len(c.get("options") or []) > OPTIONS_MAX]
    if n > COMPOSANTS_MAX or pleins:
        _log(f"{quoi} : {n} composant(s), {len(pleins)} menu(s) de plus de {OPTIONS_MAX} options "
             "— refusé par Discord, pas envoyé")
        raise _Refus(TEXTE_TROP_CHARGE)
    return composants


def _nouveau(composants: List[Dict[str, Any]], quoi: str = "menu") -> Dict[str, Any]:
    """Un message éphémère neuf, en V2 (sans texte : le V2 n'en admet pas)."""
    return {"type": 4, "data": {"flags": 64 | V2,
                                "components": _dans_les_limites(composants, quoi),
                                "allowed_mentions": {"parse": []}}}


def _maj(composants: List[Dict[str, Any]], quoi: str = "panneau") -> Dict[str, Any]:
    """Le message du clic réécrit sur place : un seul éphémère à l'écran."""
    return {"type": 7, "data": {"flags": V2,
                                "components": _dans_les_limites(composants, quoi),
                                "allowed_mentions": {"parse": []}}}


def _sur_menu(texte: str, ecran) -> Dict[str, Any]:
    """La réponse à un choix de MENU déroulant : le message redessiné
    (`ecran()`), la raison en tête quand il y en a une (refus, mise en file).
    Le menu reprend ainsi son intitulé : Discord n'envoie rien pour une
    option déjà affichée, et rechoisir la même variante après un refus
    (« Indisponible », file pleine, brute ⭐ ajoutée depuis) ne déclenchait
    plus rien, sans un mot. Une seule réponse à l'interaction (type 7), comme
    _jb_menu_refuser le fait pour le menu US. L'écran impossible à
    redessiner : la raison seule, en privé."""
    try:
        tete = [{"type": 10, "content": str(texte)[:4000]}] if texte else []
        return _maj(tete + ecran(), "menu redessiné")
    except _Refus as r:
        return ot._ephemere(texte or str(r))


def _bouton_nav(libelle: str, emoji: str, cid: str) -> Dict[str, Any]:
    return {"type": 2, "style": 2, "label": libelle[:80], "emoji": {"name": emoji},
            "custom_id": cid}


class _Refus(Exception):
    """Un refus à dire au cliqueur, en éphémère."""


# ─── Le cog de Yoshi et son module ───────────────────────────────────────
def _cog_et_module(bot) -> Tuple[Any, Any]:
    """(cog UserCog CHARGÉ, son module) ou (None, None). Le module du cog en
    service, jamais un « cogs.user » importé d'ici : discord.py exécute
    l'extension dans un module neuf, et ses contextvars (l'identité imposée
    de _run_for_model) sont les siennes."""
    try:
        cog = bot.get_cog("UserCog") if bot is not None else None
    except Exception:                                        # noqa: BLE001
        cog = None
    if cog is None:
        return None, None
    for k in type(cog).__mro__:
        m = sys.modules.get(getattr(k, "__module__", "") or "")
        if m is not None and hasattr(m, "_jb_panel") and hasattr(m, "_jb_general"):
            return cog, m
    return cog, None


def _cadre(bot) -> SimpleNamespace:
    """Ce que les gardes de cogs/user lisent d'une interaction quand le droit
    est déjà tranché (acces=True) : le client, pour get_cog."""
    return SimpleNamespace(client=bot, guild=None, user=None)


# ─── Les vues de cogs/user en JSON ───────────────────────────────────────
#: « jbus: » (panneau) → « cnt: », « jbg: » (✨ General) → « cng: ».
_RENOMMES = (("jbus:qb:", PREFIXE + "qb:"), ("jbus:a:", PREFIXE + "a:"),
             ("jbus:s:", PREFIXE + "s:"), ("jbg:r:", GENERAL + "r:"),
             ("jbg:qb:", GENERAL + "qb:"), ("jbg:a:", GENERAL + "a:"),
             ("jbg:s:", GENERAL + "s:"))


def _renommer(cid: str, qte: int) -> Optional[str]:
    """Le custom_id du ticket pour celui d'une vue US, ou None (sans
    équivalent). Le menu des identités (« jbus:ms:us:<n> ») y gagne la
    quantité : le panneau qu'il ouvre la garde."""
    if cid.startswith("jbus:ms:"):
        n = cid.rsplit(":", 1)[-1]
        return f"{PREFIXE}ms:{n}:{qte}" if n.isdigit() else None
    for avant, apres in _RENOMMES:
        if cid.startswith(avant):
            return apres + cid[len(avant):]
    return None


def _convertir(vue, qte: int, quoi: str) -> List[Dict[str, Any]]:
    """La vue discord.py `vue` en composants JSON pour Wario. Un élément sans
    équivalent est retiré, AU JOURNAL ; une rangée vidée part avec lui (une
    rangée vide fait refuser le message entier)."""
    ecartes: List[str] = []

    def _nettoyer(c):
        if not isinstance(c, dict):
            return c
        c = dict(c)
        if c.get("custom_id") is not None:
            neuf = _renommer(str(c["custom_id"]), qte)
            if neuf is None or len(neuf) > CUSTOM_ID_MAX:
                ecartes.append(str(c["custom_id"]))
                return None
            c["custom_id"] = neuf
        if isinstance(c.get("options"), list):
            c["options"] = [o for o in c["options"]
                            if str((o or {}).get("value")) not in EXCLUES]
            if not c["options"]:
                ecartes.append(str(c.get("custom_id") or "menu"))
                return None
        if isinstance(c.get("components"), list):
            c["components"] = [x for x in (_nettoyer(e) for e in c["components"]) if x is not None]
            if c.get("type") == 1 and not c["components"]:
                return None
        return c

    out = [x for x in (_nettoyer(c) for c in vue.to_components()) if x is not None]
    if ecartes:
        _log(f"{quoi} : {len(ecartes)} élément(s) sans équivalent dans le ticket, retirés : "
             + ", ".join(ecartes[:10]))
    return out


def _a_plat(composants: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in composants or []:
        if isinstance(c, dict):
            out.append(c)
            out += _a_plat(c.get("components"))
    return out


def compter(composants: Any) -> int:
    """Les composants d'un message tels que Discord les compte (tous, à
    toutes les profondeurs) : 40 au plus en V2."""
    n = 0
    for c in composants or []:
        if isinstance(c, dict):
            n += 1 + compter(c.get("components"))
            if isinstance(c.get("accessory"), dict):
                n += 1
    return n


# ─── Les écrans ──────────────────────────────────────────────────────────
def _qte(mod, brut: Any) -> int:
    try:
        q = int(brut)
    except (TypeError, ValueError):
        return int(mod._JB_QTE_DEFAUT)
    return q if 1 <= q <= int(mod._JB_QTY_MAX) else int(mod._JB_QTE_DEFAUT)


def ecran_identites(mod, qte: int) -> List[Dict[str, Any]]:
    """Le menu des identités US : celui des -menu de Youl4b."""
    return _convertir(mod._jb_menu_models_vue("us", None), qte, "identités")


def _general_vue(mod, model: str, qte: int, reserve: Optional[str] = None):
    return mod._jb_general(None, model, qte, reserve=reserve, guild=None)


def _a_un_general(vue) -> bool:
    """Le ✨ General a-t-il de quoi servir ? Sans réserve liée il n'a que sa
    quantité : pas de bouton pour lui (même règle que YouCham)."""
    ids = [str(getattr(c, "custom_id", "") or "") for c in vue.walk_children()]
    return any(i.startswith(("jbg:a:", "jbg:s:")) for i in ids)


def ecran_panneau(mod, ident: str, qte: int) -> List[Dict[str, Any]]:
    """Le panneau de `ident` (celui du menu US), et ses deux boutons de
    navigation : 👤 Identité, ✨ General. Lève _Refus quand son nom ne tient
    pas dans un bouton Discord (_jb_panel_probleme) : un panneau sans
    boutons ne servirait à rien, le refus le dit."""
    probleme = mod._jb_panel_probleme(ident, qte)
    if probleme:
        raise _Refus(f"⚠️ **{ident.capitalize()[:60]}** : {probleme}")
    comps = _convertir(mod._jb_panel(None, ident, qte, marche="us", guild=None), qte, "panneau")
    nav = [_bouton_nav("Identité", "👤", f"{PREFIXE}i:{qte}")]
    try:
        if _a_un_general(_general_vue(mod, ident, qte)):
            nav.append(_bouton_nav("General", "✨", f"{PREFIXE}g:{ident}:{qte}"))
    except Exception as e:                                   # noqa: BLE001
        _log(f"General de {ident} illisible ({type(e).__name__}: {e}) : panneau sans lui")
    comps.append({"type": 1, "components": nav})
    return comps


def ecran_general(mod, model: str, qte: int, reserve: Optional[str] = None) -> List[Dict[str, Any]]:
    """Le ✨ General de `model` (contenu de sa réserve, brute de la model),
    et le retour au panneau ou aux identités."""
    comps = _convertir(_general_vue(mod, model, qte, reserve), qte, "General")
    comps.append({"type": 1, "components": [
        _bouton_nav(model.capitalize(), "↩️", f"{PREFIXE}p:{model}:{qte}"),
        _bouton_nav("Identité", "👤", f"{PREFIXE}i:{qte}")]})
    return comps


def fenetre_quantite(cid: str, qte: int) -> Dict[str, Any]:
    """La saisie du nombre, comme _JBQtyModal du menu US."""
    return {"type": 9, "data": {
        "custom_id": cid, "title": "Quantité par action",
        "components": [{"type": 18, "label": "Combien de médias par action ?",
                        "component": {"type": 4, "custom_id": "nombre", "style": 1,
                                      "required": True, "min_length": 1, "max_length": 3,
                                      "placeholder": "ex : 7", "value": str(qte)}}]}}


def _lire_quantite(mod, p: Dict[str, Any]) -> int:
    brut = str(ot._champs((p.get("data") or {}).get("components")).get("nombre") or "").strip()
    try:
        q = int(brut)
    except ValueError:
        raise _Refus(f"« {brut[:20]} » n'est pas un nombre.")
    if not 1 <= q <= int(mod._JB_QTY_MAX):
        raise _Refus(f"Choisis un nombre entre 1 et {int(mod._JB_QTY_MAX)}.")
    return q


# ─── Les gardes ──────────────────────────────────────────────────────────
def _refus_identite(bot, mod, ident: str) -> str:
    """L'identité doit être une identité US du moment (drapeau, hors pause) :
    elle arrive de Discord, pas d'une liste que le bot tient en main. Puis
    les gardes du menu US (_jb_model_refus : réserve, pause, cog), le droit
    étant déjà tranché par le ticket."""
    idl = str(ident or "").strip().lower()
    if not idl or idl not in {str(n).strip().lower() for n in mod._jb_models_marche("us")}:
        return (f"⚠️ **{str(ident or '?').capitalize()[:60]}** n'est plus dans les identités US : "
                "rouvre 🎬 Contenu.")
    return mod._jb_model_refus(_cadre(bot), idl, acces=True)


def _cles_panneau(mod) -> set:
    """Les actions que le panneau du ticket pose en BOUTONS : un custom_id
    qui en porte une autre ne vient pas d'un message du bot."""
    return {cle for sorte, cle, _r in mod._jb_disposition("us")[0] if sorte == "action"}


def _commande(cog, mod, cle: str) -> Tuple[Any, bool]:
    entree = mod._jb_action(cle)
    cmd = getattr(cog, entree[2], None) if entree else None
    if cmd is None:
        raise _Refus(f"Action indisponible (`{cle}`).")
    return cmd, bool(entree[3])


# ─── L'aiguillage ────────────────────────────────────────────────────────
def traiter(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """La réponse à un clic « cnt: » / « cng: », ou None si ce n'est pas le
    nôtre : la route passe au module suivant."""
    p = p or {}
    cid = str((p.get("data") or {}).get("custom_id") or "")
    if p.get("type") not in (3, 5) or not cid.startswith((PREFIXE, GENERAL)):
        return None
    t, refus = ot._ticket_du_clic(p, SERVEURS)
    if t is None:
        return ot._ephemere(refus)
    bot = ot._bot_principal()
    cog, mod = _cog_et_module(bot)
    if mod is None:
        _log("menu UserCog du bot principal indisponible (démarrage ?) : rien d'ouvert")
        return ot._ephemere(ot.TEXTE_INDISPONIBLE)
    try:
        if cid.startswith(GENERAL):
            return _clic_general(p, t, bot, cog, mod, cid[len(GENERAL):].split(":"))
        return _clic_contenu(p, t, bot, cog, mod, cid[len(PREFIXE):].split(":"))
    except _Refus as r:
        return ot._ephemere(str(r))


def _valeur(p: Dict[str, Any]) -> str:
    return str(((p.get("data") or {}).get("values") or [""])[0] or "").strip().lower()


def _clic_contenu(p, t, bot, cog, mod, m: List[str]) -> Dict[str, Any]:
    action, modale = m[0], p.get("type") == 5
    if action == "o" and not modale:                 # 🎬 Contenu, dans le menu
        return _nouveau(ecran_identites(mod, int(mod._JB_QTE_DEFAUT)))
    if action == "i" and len(m) == 2 and not modale:  # 👤 Identité
        return _maj(ecran_identites(mod, _qte(mod, m[1])))
    if action == "ms" and len(m) == 3 and not modale:  # le choix de l'identité (menu)
        ident, qte = _valeur(p), _qte(mod, m[2])
        refus = _refus_identite(bot, mod, ident)
        if refus:
            return _sur_menu(refus, lambda: ecran_identites(mod, qte))
        try:
            return _maj(ecran_panneau(mod, ident, qte))
        except _Refus as r:
            return _sur_menu(str(r), lambda: ecran_identites(mod, qte))
    if action in ("p", "g") and len(m) == 3 and not modale:   # ↩️ panneau, ✨ General
        refus = _refus_identite(bot, mod, m[1])
        if refus:
            raise _Refus(refus)
        if action == "p":
            return _maj(ecran_panneau(mod, m[1], _qte(mod, m[2])))
        return _maj(ecran_general(mod, m[1], _qte(mod, m[2])))
    if action == "qb" and len(m) == 3 and not modale:
        return fenetre_quantite(f"{PREFIXE}qm:{m[1]}", _qte(mod, m[2]))
    if action == "qm" and len(m) == 2 and modale:
        q = _lire_quantite(mod, p)
        refus = _refus_identite(bot, mod, m[1])
        if refus:
            raise _Refus(refus)
        return _maj(ecran_panneau(mod, m[1], q))
    if action == "a" and len(m) == 4 and not modale:   # un bouton du panneau
        ident, cle, qte = m[1], m[2], _qte(mod, m[3])
        if cle in EXCLUES:
            raise _Refus(TEXTE_EXCLUE)
        if cle not in _cles_panneau(mod):
            raise _Refus(TEXTE_INCONNUE)
        refus = _refus_identite(bot, mod, ident)
        if refus:
            raise _Refus(refus)
        cmd, sc = _commande(cog, mod, cle)
        en_file = _lancer(t, cog, mod, ident, cle, cmd, sc, qte)
        # accusé silencieux : le contenu arrive dans le ticket — sauf s'il
        # attend son tour, ce que le VA doit savoir
        return ot._ephemere(en_file) if en_file else {"type": 6}
    if action == "s" and len(m) == 4 and not modale:   # un menu de famille
        ident, qte, cle = m[1], _qte(mod, m[3]), _valeur(p)

        def panneau():
            return ecran_panneau(mod, ident, qte)
        fam = mod._famille_panneau(m[2])
        if cle in EXCLUES:
            return _sur_menu(TEXTE_EXCLUE, panneau)
        if fam is None or cle not in fam.actions:
            _log(f"panneau du ticket {t['salon']} : choix {cle!r} refusé (famille {m[2]!r})")
            return _sur_menu(TEXTE_INCONNUE, panneau)
        refus = _refus_identite(bot, mod, ident)
        if refus:
            # l'identité n'est plus servie : son panneau non plus
            return _sur_menu(refus, lambda: ecran_identites(mod, qte))
        try:
            cmd, sc = _commande(cog, mod, cle)
            en_file = _lancer(t, cog, mod, ident, cle, cmd, sc, qte)
        except _Refus as r:
            return _sur_menu(str(r), panneau)
        # le panneau redessiné, refusé ou non (_sur_menu)
        return _sur_menu(en_file, panneau)
    return ot._ephemere(TEXTE_INCONNUE)


def _clic_general(p, t, bot, cog, mod, m: List[str]) -> Dict[str, Any]:
    action, modale = m[0], p.get("type") == 5
    if len(m) < 3:
        return ot._ephemere(TEXTE_INCONNUE)
    model, res = m[1], m[2]
    menu = action == "s" and len(m) == 5 and not modale
    refus = _refus_identite(bot, mod, model)
    if refus:
        if menu:
            # le menu reprend son intitulé (_sur_menu) ; l'identité n'est plus
            # servie : retour aux identités
            return _sur_menu(refus, lambda: ecran_identites(mod, _qte(mod, m[4])))
        raise _Refus(refus)
    if action == "r" and len(m) == 4 and not modale:   # choix de la réserve
        return _maj(ecran_general(mod, model, _qte(mod, m[3]), reserve=res))
    if action == "qb" and len(m) == 4 and not modale:
        return fenetre_quantite(f"{GENERAL}qm:{model}:{res}", _qte(mod, m[3]))
    if action == "qm" and len(m) == 3 and modale:
        return _maj(ecran_general(mod, model, _lire_quantite(mod, p), reserve=res))
    if action in ("a", "s") and len(m) == 5 and not modale:
        qte = _qte(mod, m[4])

        def general():
            return ecran_general(mod, model, qte, reserve=res)
        try:
            if action == "a":
                cle = m[3]
            else:
                cle, fam = _valeur(p), mod._jb_gen_famille(m[3])
                if fam is None or cle not in fam.actions:
                    _log(f"General du ticket {t['salon']} : choix {cle!r} refusé (famille {m[3]!r})")
                    raise _Refus(TEXTE_INCONNUE)
            # LES gardes du ✨ General (liste blanche, réserve encore liée,
            # brute de la model…), le droit étant tranché par le ticket
            refus, cmd, sc = mod._jb_gen_controle(_cadre(bot), model, res, cle, acces=True)
            if refus:
                raise _Refus(refus)
            en_file = _lancer(t, cog, mod, res, cle, cmd, sc, qte, brute_de=model)
        except _Refus as r:
            if not menu:
                raise
            return _sur_menu(str(r), general)
        if action == "a":
            return ot._ephemere(en_file) if en_file else {"type": 6}
        return _sur_menu(en_file, general)
    return ot._ephemere(TEXTE_INCONNUE)


# ─── Le lancement ────────────────────────────────────────────────────────
def _lancer(t: Dict[str, str], cog, mod, ident: str, cle: str, cmd, sc: bool, qte: int,
            brute_de: Optional[str] = None) -> str:
    """L'action sur la boucle de Yoshi, sans l'attendre (Discord laisse 3 s
    pour répondre au clic). Rend "" quand elle part tout de suite, sinon la
    phrase « en file » à dire au cliqueur (une autre livraison tient le
    ticket). Lève _Refus si rien n'est lancé."""
    bot = ot._bot_principal()
    boucle = ot._boucle(bot)
    if boucle is None:
        _log("boucle du bot principal indisponible : rien n'est lancé")
        raise _Refus(ot.TEXTE_INDISPONIBLE)
    salon = t["salon"]
    with _VERROU:
        n = _EN_FILE.get(salon, 0)
        if n >= FILE_MAX:
            raise _Refus(TEXTE_FILE)
        _EN_FILE[salon] = n + 1
    occupe = n > 0 or ot.ticket_occupe(salon)
    libelle = str(mod._libelle_action(cle))
    # La marque de redémarrage AVANT de lancer, une par livraison : posée
    # une fois le ticket pris, celles en file derrière (jusqu'à FILE_MAX - 1)
    # n'avaient aucune trace — un déploiement les perdait sans un mot, le VA
    # les attendait encore. Un numéro au hasard : celui d'un processus
    # précédent, pas encore annoncé, n'est jamais écrasé.
    numero = os.urandom(4).hex()
    ot._noter(salon, "contenu", {"gid": t["gid"], "uid": t["uid"], "nom": _nom_court(libelle, ident),
                                 "ordre": time.time()}, numero)
    coro = _livrer(bot, cog, t, ident, cle, libelle, cmd, sc, qte, brute_de, numero)
    try:
        fut = asyncio.run_coroutine_threadsafe(coro, boucle)
    except Exception as e:                                   # noqa: BLE001
        coro.close()
        _liberer_place(salon)
        ot._noter(salon, "contenu", None, numero)
        _log(f"{cle} non lancé dans {salon} ({type(e).__name__}: {e})")
        raise _Refus(ot.TEXTE_INDISPONIBLE)
    journal = ot._journaliser_fin(f"{cle} pour {ident} dans {salon}")

    def _fini(f):
        _liberer_place(salon)
        journal(f)
    fut.add_done_callback(_fini)
    if n > 0:
        return TEXTE_EN_FILE.format(n=n)
    return TEXTE_EN_FILE_AUTRE if occupe else ""


def _liberer_place(salon: str) -> None:
    with _VERROU:
        n = _EN_FILE.get(salon, 0) - 1
        if n > 0:
            _EN_FILE[salon] = n
        else:
            _EN_FILE.pop(salon, None)


def _nom_court(libelle: str, ident: str) -> str:
    """« Caption · lola » : le libellé sans son emoji de tête, pour l'annonce
    d'un redémarrage."""
    return f"{re.sub(r'^[^0-9A-Za-zÀ-ÿ⭐]+', '', libelle) or libelle} · {ident}"[:120]


async def _livrer(bot, cog, t: Dict[str, str], ident: str, cle: str, libelle: str, cmd,
                  sc: bool, qte: int, brute_de: Optional[str], numero: str = "") -> None:
    """Sur la boucle de Yoshi : une livraison à la fois par ticket, tous
    outils confondus (outils_tickets.verrou_livraison : un ⬇️ ou un 📤 du même
    ticket attend lui aussi), la commande du menu US jouée avec l'interaction
    du ticket, puis le menu reposé en dernier — AVANT de rendre le ticket, la
    livraison suivante ne le voit pas s'intercaler entre ses messages."""
    gid, salon, vau = t["gid"], t["salon"], t["uid"]
    livreur: Optional[_Livreur] = None
    arret = False
    try:
        async with ot.verrou_livraison(salon):
            limite = await asyncio.to_thread(ot.limite_fichiers, gid)
            livreur = _Livreur(gid, salon, limite)
            itx = _InteractionTicket(bot, t, livreur, f"{cle}:{ident}")
            livreur.tache = asyncio.ensure_future(cog._run_for_model(
                itx, ident, cmd, count=qte, supports_count=sc, brute_de=brute_de))
            try:
                await livreur.tache
            except asyncio.CancelledError:
                if not livreur.disparu:
                    raise                   # c'est nous qui sommes annulés (arrêt du bot)
            except Exception as e:                           # noqa: BLE001
                _log(f"{cle} pour {ident} dans {salon} : {type(e).__name__}: {e}")
                await livreur.dire(f"❌ **{libelle}** : erreur ({type(e).__name__}). "
                                   "Réessaie ; si ça recommence, préviens un admin.")
            if not livreur.disparu:
                await livreur.dire_les_lourds()
                if livreur.postes:
                    await asyncio.to_thread(ot._ramener_menu, gid, vau, salon)
    except asyncio.CancelledError:
        # L'arrêt du bot (un déploiement), pendant la livraison OU dans la
        # file : la marque RESTE, le démarrage suivant l'annonce dans le
        # ticket (outils_tickets). L'effacer ici, c'était laisser le VA
        # attendre une livraison coupée.
        arret = True
        raise
    finally:
        if not arret:
            await asyncio.to_thread(ot._noter, salon, "contenu", None, numero)
        _log(f"{cle} ×{qte} pour {ident}{f' (brute de {brute_de})' if brute_de else ''}, "
             f"ticket {salon} : {len(livreur.postes) if livreur else 0} message(s)"
             + (f", {len(livreur.lourds)} trop lourd(s)" if livreur and livreur.lourds else "")
             + (", ticket supprimé" if livreur and livreur.disparu else "")
             + (", coupée par l'arrêt du bot" if arret else ""))


# ─── Écrire dans le ticket ────────────────────────────────────────────────
#: Ce qu'une réponse, un suivi ou un salon discord.py accepte et qui se
#: traduit en REST ; les autres n'ont pas de sens ici (dits au journal).
_KW_TRADUITS = frozenset({"view", "embed", "embeds", "file", "files", "allowed_mentions",
                          "suppress_embeds", "silent", "attachments"})
#: La façon de répondre à une interaction, pas le message : retirés sans bruit.
_KW_INTERACTION = frozenset({"ephemeral", "wait", "thinking"})
_ABSENT = object()


def _figer(composants: Any) -> int:
    """Désactive sur place les boutons (hors liens) et menus encore actifs :
    leurs clics arriveraient à Wario, qui ne les connaît pas. Rend leur
    nombre (au journal). Les étiquettes grises des textes à copier le sont
    déjà."""
    n = 0
    for c in composants or []:
        if not isinstance(c, dict):
            continue
        if (c.get("type") == 2 and c.get("style") != 5) or c.get("type") in (3, 5, 6, 7, 8):
            if not c.get("disabled"):
                c["disabled"] = True
                n += 1
        n += _figer(c.get("components"))
        if isinstance(c.get("accessory"), dict):
            n += _figer([c["accessory"]])
    return n


def _nom_fichier(f) -> str:
    return str(getattr(f, "filename", None) or "fichier")


def _taille(f) -> int:
    """Le poids d'un discord.File, SANS le lire : un fichier refusé pour son
    poids était d'abord chargé en entier, sur la boucle de Yoshi — 60 Mo
    d'une brute, deux fois (la carte, puis l'ancien envoi), pendant que tous
    les clics de Youl4b attendaient. 0 si illisible : il part, et un refus de
    Discord (413) reste compté et dit."""
    fp = getattr(f, "fp", None)
    if fp is None:
        return 0
    try:
        pos = fp.tell()
        fin = fp.seek(0, os.SEEK_END)
        fp.seek(pos)
        return max(0, int(fin) - int(pos))
    except Exception:                                        # noqa: BLE001
        try:
            return int(os.fstat(fp.fileno()).st_size)
        except Exception:                                    # noqa: BLE001
            return 0


def _fermer(fichiers) -> None:
    """Comme discord.py après un envoi, réussi ou non : les commandes ouvrent
    un discord.File neuf pour chaque essai."""
    for _n, f in fichiers:
        try:
            f.close()
        except Exception:                                    # noqa: BLE001
            pass


def _corps(content: Any, kw: Dict[str, Any], edition: bool = False
           ) -> Tuple[Dict[str, Any], List[Tuple[str, Any]]]:
    """Le message REST (corps, [(nom, discord.File)]) de ce qu'une commande
    voulait envoyer par discord.py. Les fichiers ne sont PAS lus ici (_poster
    les lit, dans un fil). Aucune mention ne notifie : c'est le ticket."""
    import discord
    inconnus = sorted(k for k in kw if k not in _KW_TRADUITS and k not in _KW_INTERACTION)
    if inconnus:
        _log("envoi dans le ticket : argument(s) sans équivalent ignoré(s) " + ", ".join(inconnus))
    corps: Dict[str, Any] = {"allowed_mentions": {"parse": []}}
    flags = 0
    if content is not _ABSENT and content is not discord.utils.MISSING:
        if content is not None:
            corps["content"] = str(content)
        elif edition:
            corps["content"] = ""
    vue = kw.get("view", _ABSENT)
    if vue is not _ABSENT and vue is not discord.utils.MISSING:
        if vue is None:
            if edition:
                corps["components"] = []
        else:
            comps = vue.to_components()
            actifs = _figer(comps)
            if actifs:
                _log(f"envoi dans le ticket : {actifs} bouton(s)/menu(s) d'une vue de Yoshi "
                     "désactivé(s) (Wario n'en recevrait pas les clics)")
            corps["components"] = comps
            try:
                if vue.has_components_v2():
                    flags |= V2
            except Exception:                                # noqa: BLE001
                pass
    embeds = []
    if kw.get("embed") not in (None, _ABSENT, discord.utils.MISSING):
        embeds.append(kw["embed"].to_dict())
    for e in kw.get("embeds") or []:
        embeds.append(e.to_dict())
    if embeds or (edition and ("embed" in kw or "embeds" in kw)):
        corps["embeds"] = embeds
    if kw.get("suppress_embeds"):
        flags |= 4
    if kw.get("silent"):
        flags |= 4096
    if flags:
        corps["flags"] = flags
    if edition and isinstance(kw.get("attachments"), list) and not kw["attachments"]:
        corps["attachments"] = []
    fichiers: List[Tuple[str, Any]] = []
    if not edition:
        if kw.get("file") not in (None, _ABSENT, discord.utils.MISSING):
            fichiers.append((_nom_fichier(kw["file"]), kw["file"]))
        for f in kw.get("files") or []:
            fichiers.append((_nom_fichier(f), f))
    return corps, fichiers


def _son_tour(salon: str) -> float:
    """Ce qu'il faut attendre avant le prochain message de ce ticket — sa
    place est réservée : au plus RYTHME_N messages par RYTHME_S secondes."""
    with _VERROU:
        dq = _RYTHME.setdefault(str(salon), collections.deque(maxlen=RYTHME_N))
        maintenant = time.time()
        attente = max(0.0, dq[0] + RYTHME_S - maintenant) if len(dq) >= RYTHME_N else 0.0
        dq.append(maintenant + attente)
    return attente


def _poster(gid: str, salon: str, corps: Dict[str, Any],
            fichiers: List[Tuple[str, Any]]) -> Tuple[int, Any]:
    """Un message dans le ticket avec le jeton de Wario (multipart s'il y a des
    fichiers). Appelée dans un fil (asyncio.to_thread) : les fichiers sont lus
    ICI, jamais sur la boucle de Yoshi, puis refermés. Rend (code, corps) ;
    ne lève pas."""
    chemin = f"/channels/{salon}/messages"
    try:
        if not fichiers:
            return ot._api("POST", chemin, json=corps, gid=gid)
        octets = [(nom, (f.fp.read() if getattr(f, "fp", None) is not None else b""))
                  for nom, f in fichiers]
        corps = dict(corps, attachments=[{"id": i, "filename": nom}
                                         for i, (nom, _o) in enumerate(octets)])
        return ot._api("POST", chemin, gid=gid,
                       data={"payload_json": json.dumps(corps, ensure_ascii=False)},
                       files={f"files[{i}]": (nom, o, ot._type_mime(nom))
                              for i, (nom, o) in enumerate(octets)})
    except Exception as e:                                   # noqa: BLE001
        return 0, {"message": f"{type(e).__name__}: {str(e)[:160]}"}
    finally:
        _fermer(fichiers)


def _exception(code: int, rep: Any):
    """Le refus tel que discord.py l'aurait levé : les commandes savent déjà
    le dire (« trop lourd », « envoi impossible »)."""
    import discord
    raison = {400: "Bad Request", 403: "Forbidden", 404: "Not Found",
              413: "Payload Too Large", 429: "Too Many Requests"}.get(int(code or 0), "")
    reponse = SimpleNamespace(status=int(code or 0), reason=raison)
    message = rep if isinstance(rep, (dict, str)) else str(rep)
    classe = {403: discord.Forbidden, 404: discord.NotFound}.get(int(code or 0), discord.HTTPException)
    return classe(reponse, message)


def _mo(octets: int) -> str:
    return f"{octets / ot.MIO:.1f}".replace(".", ",").replace(",0", "")


class _Livreur:
    """Tout ce qu'une livraison poste dans UN ticket, par Wario en REST."""

    def __init__(self, gid: str, salon: str, limite: int):
        from cogs import telechargement as tl
        self.gid, self.salon, self.limite = str(gid), str(salon), int(limite)
        #: Ce qu'un message peut porter EN TOUT : Discord borne le message
        #: entier, enveloppe multipart comprise (tl.repartir, même marge) ;
        #: une carte vidéo + exemple de 13 Mo passait fichier par fichier,
        #: partait en entier, et revenait en 413.
        self.plafond = max(1, self.limite - int(tl._MARGE_ENVOI))
        self.postes: List[str] = []
        #: {nom: poids} des fichiers refusés pour leur poids et pas livrés
        #: depuis — une fois chacun : la carte puis l'ancien envoi refusaient
        #: la même vidéo deux fois, et la fin disait « 2 fichiers » pour une —
        #: et si c'est dit
        self.lourds: Dict[str, int] = {}
        self.lourd_dit = True
        self.disparu = False
        #: la tâche de la commande, annulée si le ticket disparaît
        self.tache: Optional[asyncio.Future] = None

    def _arreter(self) -> None:
        if not self.disparu:
            self.disparu = True
            _log(f"ticket {self.salon} supprimé pendant la livraison : arrêtée")
            if self.tache is not None:
                self.tache.cancel()

    def _refuser_lourds(self, lourds: List[Tuple[str, int]], poids: int):
        for n, t in lourds:
            self.lourds[n] = t
        self.lourd_dit = False
        detail = ", ".join(f"{n} ({_mo(t)} Mo)" for n, t in lourds)
        _log(f"ticket {self.salon} : trop lourd pour {_mo(self.plafond)} Mo — {detail}")
        return _exception(413, {"code": 40005, "message":
                                f"trop lourd pour Discord ({_mo(poids)} Mo, {_mo(self.plafond)} au plus)"})

    async def envoyer(self, content: Any, kw: Dict[str, Any]) -> "_MessageTicket":
        if self.disparu:
            raise _exception(404, {"code": 10003, "message": "Unknown Channel"})
        corps, fichiers = _corps(_ABSENT if content is None else content, kw)
        tailles = [(n, _taille(f)) for n, f in fichiers]
        total = sum(t for _n, t in tailles)
        lourds = [(n, t) for n, t in tailles if t > self.plafond]
        if not lourds and total > self.plafond:
            lourds = tailles            # chacun passe, pas ensemble
        if lourds:
            # pas envoyé, pas même lu : Discord l'aurait refusé après l'avoir
            # reçu en entier
            _fermer(fichiers)
            raise self._refuser_lourds(lourds, max(total, max(t for _n, t in lourds)))
        attente = _son_tour(self.salon)
        if attente > 0:
            await _patienter(attente)
        code, rep = await asyncio.to_thread(_poster, self.gid, self.salon, corps, fichiers)
        if code in (200, 201) and isinstance(rep, dict):
            mid = str(rep.get("id") or "")
            self.postes.append(mid)
            for n, _t in tailles:
                self.lourds.pop(n, None)        # livré finalement (ancien envoi)
            if self.lourds and "lourd" in str(corps.get("content") or "").lower():
                self.lourd_dit = True
            return _MessageTicket(self, mid)
        if ot._ticket_disparu(code, rep):
            self._arreter()
        elif ot._trop_lourd(code, rep):
            raise self._refuser_lourds(tailles or [("message", 0)], total)
        else:
            _log(f"envoi refusé dans {self.salon} (HTTP {code}) {str(rep)[:160]}")
        raise _exception(code, rep)

    async def editer(self, mid: Any, kw: Dict[str, Any]) -> "_MessageTicket":
        if self.disparu:
            raise _exception(404, {"code": 10003, "message": "Unknown Channel"})
        kw = dict(kw)
        corps, _f = _corps(kw.pop("content", _ABSENT), kw, edition=True)
        code, rep = await asyncio.to_thread(ot._api, "PATCH",
                                            f"/channels/{self.salon}/messages/{mid}",
                                            json=corps, gid=self.gid)
        if code == 200:
            return _MessageTicket(self, str(mid))
        # 404 sur une édition : le MESSAGE peut avoir été retiré (10008) ;
        # seul « salon inconnu » (10003) arrête la livraison
        if isinstance(rep, dict) and rep.get("code") == 10003:
            self._arreter()
        raise _exception(code, rep)

    async def effacer(self, mid: Any) -> None:
        code, rep = await asyncio.to_thread(ot._api, "DELETE",
                                            f"/channels/{self.salon}/messages/{mid}", gid=self.gid)
        if code not in (200, 204, 404):
            _log(f"message {mid} du ticket {self.salon} non retiré (HTTP {code}) {str(rep)[:120]}")

    async def dire(self, texte: str) -> bool:
        """Un texte court dans le ticket, sans lever."""
        try:
            await self.envoyer(texte, {})
            return True
        except Exception as e:                               # noqa: BLE001
            _log(f"message non posté dans {self.salon} ({type(e).__name__}: {e}) : {texte[:120]}")
            return False

    async def dire_les_lourds(self) -> None:
        """Un fichier refusé pour son poids que la commande n'a pas dit : dit
        ici, une fois. Jamais écarté en silence."""
        if self.lourds and not self.lourd_dit:
            n = len(self.lourds)
            await self.dire(f"⚠️ {n} fichier{'s' if n > 1 else ''} trop lourd{'s' if n > 1 else ''} "
                            f"pour Discord ({_mo(self.plafond)} Mo au plus) : "
                            f"pas envoyé{'s' if n > 1 else ''}.")
            self.lourd_dit = True


class _MessageTicket:
    """Un message posté dans le ticket, comme discord.py le rend (edit,
    delete) : la barre de progression s'édite sur place."""

    def __init__(self, livreur: _Livreur, mid: str):
        self._l = livreur
        self.id = int(mid) if str(mid).isdigit() else mid
        self.channel = SimpleNamespace(id=int(livreur.salon) if livreur.salon.isdigit()
                                       else livreur.salon)

    async def edit(self, **kw):
        return await self._l.editer(self.id, kw)

    async def delete(self, **_kw):
        await self._l.effacer(self.id)


class _Reponse:
    """`interaction.response` : le clic est déjà acquitté par le site (Wario
    a répondu à Discord) ; tout ce qui s'y envoie part dans le ticket."""

    def __init__(self, livreur: _Livreur):
        self._l = livreur
        self._fait = False

    def is_done(self) -> bool:
        return self._fait

    async def defer(self, **_kw) -> None:
        self._fait = True

    async def send_message(self, content=None, **kw):
        self._fait = True
        return await self._l.envoyer(content, kw)

    async def edit_message(self, **kw):
        # Il aurait réécrit le panneau éphémère du clic : le contenu, lui,
        # part dans le ticket — et le journal le dit.
        self._fait = True
        _log("edit_message d'une commande détourné vers le ticket")
        kw = dict(kw)
        kw.pop("attachments", None)
        return await self._l.envoyer(kw.pop("content", None), kw)

    async def send_modal(self, *_a, **_kw):
        raise RuntimeError("fenêtre de saisie impossible depuis le ticket")


class _Suivi:
    """`interaction.followup` : dans le ticket aussi."""

    def __init__(self, livreur: _Livreur):
        self._l = livreur

    async def send(self, content=None, **kw):
        return await self._l.envoyer(content, kw)

    async def edit_message(self, message_id, **kw):
        return await self._l.editer(message_id, kw)

    async def delete_message(self, message_id, **_kw):
        await self._l.effacer(message_id)


class _SalonContenu:
    """`interaction.channel` : le ticket."""

    def __init__(self, livreur: _Livreur, guild):
        self._l = livreur
        self.id = int(livreur.salon)
        self.name = f"ticket {livreur.salon}"
        self.mention = f"<#{livreur.salon}>"
        self.guild = guild

    async def send(self, content=None, **kw):
        return await self._l.envoyer(content, kw)


class _InteractionTicket:
    """L'interaction que les commandes du menu US reçoivent pour un clic dans
    un ticket de TRUST INSTAGRAM. Serveur hors US : _run_for_model ne la
    redirige pas, tout passe par elle. L'utilisateur est le VA du ticket
    (c'est sa livraison, même quand son manager clique) ; le serveur porte
    `livraison_reelle` : la livraison est notée comme une vraie
    (_livraison_a_noter), pour les favoris automatiques."""

    def __init__(self, bot, t: Dict[str, str], livreur: _Livreur, quoi: str = ""):
        gid, uid = int(t["gid"]), int(t["uid"])
        nom = t.get("nom") if t.get("qui") == t["uid"] else ""
        nom = str(nom or t["uid"])
        self.client = bot
        self.guild = SimpleNamespace(id=gid, name="TRUST INSTAGRAM", emojis=[], me=None,
                                     text_channels=[], filesize_limit=livreur.limite,
                                     premium_tier=0, livraison_reelle=True,
                                     get_member=lambda _i: None, get_channel=lambda _i: None)
        self.guild_id = gid
        self.channel = _SalonContenu(livreur, self.guild)
        self.channel_id = self.channel.id
        self.user = SimpleNamespace(id=uid, name=nom, display_name=nom, global_name=nom,
                                    mention=f"<@{uid}>", bot=False, roles=[], guild=self.guild)
        self.response = _Reponse(livreur)
        self.followup = _Suivi(livreur)
        self.message = None
        self.data = {"custom_id": quoi}
        self.extras: Dict[str, Any] = {}
        self._l = livreur

    async def edit_original_response(self, **kw):
        # pas de réponse d'origine dans le ticket : un message de plus, dit
        _log("edit_original_response d'une commande détourné vers le ticket")
        kw = dict(kw)
        kw.pop("attachments", None)
        return await self._l.envoyer(kw.pop("content", None), kw)

    async def delete_original_response(self):
        _log("delete_original_response d'une commande ignoré (pas de réponse dans le ticket)")

    async def original_response(self):
        raise RuntimeError("pas de réponse d'origine dans le ticket")
