# -*- coding: utf-8 -*-
"""Le salon <pseudo>-generateur-de-lien d'un VA US : un lien GetMySocial par identite.

POURQUOI (demande du proprietaire, 06/10/2026)
    Chaque VA du serveur Youl4b US a un LIEN GLOBAL GetMySocial, celui que le
    proprietaire lui donne : il mene a son lien de suivi OnlyFans de Jessye
    (onlyfans.com/jessyewdiference/c<N>, suivi par Infloww). Les meilleurs VA
    postent avec plusieurs identites, et « pour mieux convertir faut ca » :
    une page par identite, avec SA tete, dont le bouton OnlyFans mene au MEME
    suivi c<N>. Ses ventes restent donc a lui ; rien de neuf a creer chez
    Infloww ni MyPuls. Le VA la cree seul, sans validation, et voit toujours
    combien de liens actifs il a.

OU CA VIT
    Un salon par VA, « <pseudo>-generateur-de-lien », dans son dossier (cree
    par cogs/welcome.create_us_tickets ; les dossiers deja la le recoivent de
    l'entretien ci-dessous). Lecture seule, comme -menu : le VA ne fait que
    choisir. Il porte UN panneau, sans texte de notice :

        🟢 3 liens actifs
        [🪪 Choisis une identite…        ▾]
        [🔗 Lien global]                      (admin seulement)

    puis, chacun SEUL dans un message ordinaire (copie d'un appui long sur
    telephone, voir cogs/user._envoyer_a_copier), le lien global sous un
    bouton gris « 🌐 Global » et un lien par identite sous un bouton gris a
    son nom. Rien n'est epingle (pas de notice « a epingle un message »).

    Un dossier partage entre plusieurs VA (completer_dossiers_us donne le
    salon a TOUS les humains du -content) porte un panneau PAR VA, son nom
    sur le compteur et sur ses boutons gris : chacun a son global, ses liens
    et son chiffre.

    Le registre suit GetMySocial a chaque entretien (liens_identite_us.
    actualiser) : une adresse changee est repostee, et les pages d'un VA dont
    le global a change sont rebranchees sans attendre son clic.

CE QUI N'EST PAS ICI
    Tout ce qui parle a GetMySocial : liens_identite_us.py (registre, copie de
    la page de base « TEMPLATE <identite> », reecriture du bouton OnlyFans,
    comptage). Ce cog l'importe paresseusement : s'il manque, le panneau
    reste pose, menu grise, et le journal le dit.
    Aucune commande slash : le bot principal en a 100 sur 100.

APPELS GETMYSOCIAL
    Le compteur lit la liste de l'equipe EN CACHE (liens_identite_us.
    liens_equipe, appuye sur le cache de gms.list_links_team) : un passage
    d'entretien, toutes les ENTRETIEN_HEURES, pour tous les salons ; un clic
    relit ce cache (un appel au plus par quart d'heure, quand il a expire) ;
    seules une CREATION et un REBRANCHEMENT font travailler GetMySocial
    (copie, lecture, reecriture des boutons, par liens_identite_us). Un
    rebranchement n'arrive que si le global d'un VA a change (admin, ou
    GetMySocial) : environ deux appels par page donnee, une fois.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import importlib
import os
import re
import time
from pathlib import Path

import discord
from discord.ext import commands, tasks

import safe_json

#: Le suffixe du salon. LE MEME que dans cogs/welcome.US_TICKET_SUFFIXES :
#: /ticketsall supprime tout salon de ticket dont le suffixe n'y est pas.
SUFFIXE = "generateur-de-lien"

#: Youl4b US. Repli seulement : la constante qui fait foi est
#: liens_identite_us.GUILD_ID (un seul endroit decide du serveur).
GUILD_ID_DEFAUT = "1535758943324999711"

#: Prefixe de TOUS les custom_id de ce cog. discord.py lance tous les motifs
#: dynamiques qui correspondent a un custom_id : celui-ci ne recoupe aucun
#: des existants (jbus: jbg: jbmenu cmenu: genlink: spf: numgen: lien: essai:
#: usdc: copie: dl: sessions: annonce_…), verifie par tests_generateur_lien.
PREFIXE = "gdl:"
CID_GLOBAL_BOUTON = "gdl:gl:{uid}"           # 🔗 Lien global (admin)
CID_MENU = "gdl:id:{uid}:{n}"                # menu des identites n° n
CID_FENETRE = "gdl:fen:{uid}:{alea}"         # fenetre du lien global
CID_ETIQUETTE_GLOBAL = "gdl:g:{uid}"         # bouton gris « 🌐 Global » du VA uid
CID_ETIQUETTE = "gdl:e:{uid}:{ident}"        # bouton gris au nom de l'identite

#: Options par menu deroulant : le plafond de Discord.
TAILLE_MENU = 25
#: 40 composants au plus dans un message V2 : le bloc, le compteur, la
#: rangee du bouton et le bouton (4), puis 2 par menu (sa rangee + lui).
MAX_MENUS = (40 - 4) // 2
#: Plafonds Discord : un custom_id, une valeur et un libelle d'option.
CUSTOM_ID_MAX = 100
VALEUR_MAX = 100
LIBELLE_MAX = 100
#: Ce qu'un nom d'identite doit etre pour servir de valeur d'option ET de
#: custom_id d'etiquette (le meme motif que les boutons du menu VA).
_NOM_IDENT = re.compile(r"[a-z0-9_.\-]{1,80}")

VERT = 0x23A55A

#: Cadence de l'entretien. Le proprietaire veut un compteur juste, mais la
#: quota GetMySocial est journaliere et commune aux quatre cles (epuisee une
#: fois) : un passage toutes les quatre heures, une liste en cache pour tous
#: les salons. Une creation, elle, redessine aussitot le panneau du VA.
ENTRETIEN_HEURES = 4
#: GetMySocial indisponible a un passage : on repasse plus tot, sans quoi un
#: salon neuf garderait un menu vide quatre heures.
REESSAI_MINUTES = 60

#: Une creation plus recente que ca et absente de la liste en cache (gardee
#: jusqu'a 15 min par gms.list_links_team) compte quand meme : sans ca, le
#: compteur affiche juste apres la creation n'aurait pas bouge.
RECENT_S = 30 * 60

INTITULE_MENU = "🪪 Choisis une identité…"
INTITULE_VERROU = "🔒 En attente du lien global"
INTITULE_VIDE = "🪪 Aucune identité pour l'instant"
INTITULE_INDISPO = "🔒 Générateur indisponible"

WHITELIST = Path("data") / "whitelist.json"


# ─────────────────────────────────────────────────────── le module liens ──

_LU_DIT = {"fait": False}


def _lu():
    """liens_identite_us, ou None (dit UNE fois au journal). Importe au
    besoin : ce cog se charge meme si le module manque ou casse, et le
    panneau le montre (menu grise) au lieu de disparaitre."""
    try:
        return importlib.import_module("liens_identite_us")
    except Exception as e:                                   # noqa: BLE001
        if not _LU_DIT["fait"]:
            _LU_DIT["fait"] = True
            print(f"[gdl] liens_identite_us indisponible : {type(e).__name__}: {e}",
                  flush=True)
        return None


def guild_id() -> str:
    lu = _lu()
    return str(getattr(lu, "GUILD_ID", "") or GUILD_ID_DEFAUT)


def serveur_ok(guild) -> bool:
    """Youl4b US seulement : partout ailleurs, aucun panneau, aucun clic."""
    return str(getattr(guild, "id", "") or "") == guild_id()


# ───────────────────────────────────────────────────────────── salons ──

def _norm(nom) -> str:
    try:
        from cogs.welcome import nom_sans_decor
        return nom_sans_decor(nom)
    except Exception:
        return str(nom or "").strip().lower()


def est_salon(canal) -> bool:
    """Un salon <pseudo>-generateur-de-lien de VA (jamais un salon de service)."""
    nom = getattr(canal, "name", "") or ""
    try:
        from cogs.welcome import salon_de_service
        if salon_de_service(nom):
            return False
    except Exception:
        pass
    return _norm(nom).endswith("-" + SUFFIXE)


def vas_du_salon(canal) -> list:
    """Les VA a qui appartient ce salon : les membres humains qui y ont une
    autorisation nominative de voir (cogs/welcome._us_droits_ticket). Un
    dossier partage les donne TOUS (completer_dossiers_us : « ses VA sont les
    membres humains qui voient le -content ») : chacun a son panneau. Plus
    personne a deviner -- un dossier renomme a deux humains n'avait aucun
    panneau, et le second VA d'un dossier partage se voyait refuser chaque
    choix. Celui dont le pseudo fait le nom du salon d'abord, puis par
    identifiant : l'ordre des panneaux ne bouge pas d'un passage a l'autre."""
    base = _norm(getattr(canal, "name", ""))[: -len("-" + SUFFIXE)]
    vas = [t for t, ow in (getattr(canal, "overwrites", None) or {}).items()
           if getattr(t, "bot", None) is False and getattr(ow, "view_channel", None)]
    try:
        from cogs.welcome import _us_base
    except Exception:
        _us_base = None

    def rang(m):
        try:
            sien = _us_base is not None and _us_base(m) == base
        except Exception:
            sien = False
        return (0 if sien else 1, int(getattr(m, "id", 0) or 0))
    return sorted(vas, key=rang)


def nom_va(membre) -> str:
    """Le nom qui distingue les panneaux d'un dossier partage."""
    return str(getattr(membre, "display_name", None) or getattr(membre, "name", "") or "")[:40]


def nom_si_partage(canal, uid):
    """Le nom du VA `uid` si son salon en a plusieurs, sinon None (un salon
    a un seul VA garde son panneau sans nom, sans aucun texte de plus)."""
    vas = vas_du_salon(canal) if canal is not None else []
    if len(vas) < 2:
        return None
    m = next((v for v in vas if int(getattr(v, "id", 0) or 0) == int(uid)), None)
    return nom_va(m) if m is not None else None


def est_admin(membre) -> bool:
    """Le bouton 🔗 Lien global : administrateurs du serveur (le
    proprietaire du serveur l'est d'office) et liste blanche des admins du
    bot (data/whitelist.json, celle de cogs/welcome.is_admin). Un VA n'a ni
    l'un ni l'autre : le salon est a lui, le lien global ne l'est pas."""
    p = getattr(membre, "guild_permissions", None)
    if p is not None and (getattr(p, "administrator", False) or getattr(p, "manage_guild", False)):
        return True
    wl = safe_json.load(WHITELIST, default=[]) or []
    try:
        return int(getattr(membre, "id", 0)) in {int(x) for x in wl}
    except (TypeError, ValueError):
        return False


# ────────────────────────────────────────────── identites, registre, compte ──

def identites_us() -> list:
    """Les identites du menu US (cogs/user._jb_models_marche : le drapeau de
    marche, moins les pauses et Jessye) -- LA meme liste que le menu VA, pas
    une copie de ses filtres."""
    try:
        from cogs.user import _jb_models_marche
        return list(_jb_models_marche("us") or [])
    except Exception as e:                                   # noqa: BLE001
        print(f"[gdl] identites US illisibles : {type(e).__name__}: {e}", flush=True)
        return []


def emojis(guild, idents) -> dict:
    """{identite: emoji « id<nom> »} parmi ceux DEJA sur le serveur (le menu
    VA les cree ; le serveur est plein, rien n'est cree ici)."""
    if guild is None:
        return {}
    try:
        from cogs.user import _jb_emojis_presents
        return dict(_jb_emojis_presents(guild, idents) or {})
    except Exception as e:                                   # noqa: BLE001
        print(f"[gdl] emojis illisibles : {type(e).__name__}: {e}", flush=True)
        return {}


def libelles(idents) -> list:
    """[(identite, libelle)] dans l'ordre du proprietaire, le rang devant le
    nom (identites_ordre) : le meme ordre et les memes medailles que le menu
    des models."""
    try:
        import identites_ordre as _io
        ordre = _io.lire()
        tri = _io.trier(list(idents), ordre)
        lib = _io.etiqueter(tri, ordre)
        return [(i, lib.get(i) or str(i).capitalize()) for i in tri]
    except Exception as e:                                   # noqa: BLE001
        print(f"[gdl] ordre des identites illisible : {type(e).__name__}: {e}", flush=True)
        return [(i, str(i).capitalize()) for i in sorted(idents)]


def _horodatage(q) -> float:
    """`quand` du registre en secondes : nombre, chaine de chiffres ou ISO."""
    if isinstance(q, (int, float)):
        return float(q)
    s = str(q or "").strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def compter(uid, liens):
    """Les liens actifs du VA (liens_identite_us.liens_actifs sur la liste en
    cache), plus ses creations des RECENT_S dernieres secondes que cette
    liste ne montre pas encore (liens_de : son registre). None si on ne sait
    pas (module absent, liste indisponible) : l'appelant garde alors le
    chiffre deja affiche."""
    lu = _lu()
    if lu is None or liens is None:
        return None
    try:
        n = int(lu.liens_actifs(uid, liens))
        vus = {str(l.get("id")) for l in (lu.liens_du_va(uid, liens) or [])
               if isinstance(l, dict)}
        siens = list(lu.liens_de(uid) or [])
    except Exception as e:                                   # noqa: BLE001
        print(f"[gdl] compte de {uid} impossible : {type(e).__name__}: {e}", flush=True)
        return None
    maintenant = time.time()
    for f in siens:
        if (isinstance(f, dict) and f.get("etat") == "ok"
                and str(f.get("link_id")) not in vus
                and maintenant - _horodatage(f.get("quand")) <= RECENT_S):
            n += 1
    return n


_SEP_NOM = " · "


def texte_compteur(n, nom=None) -> str:
    if n is None:
        t = "## 🟢 ? liens actifs"
    else:
        t = f"## 🟢 {n} lien{'s' if n > 1 else ''} actif{'s' if n > 1 else ''}"
    return t + (f"{_SEP_NOM}{nom}" if nom else "")


def cid_global(uid) -> str:
    return CID_ETIQUETTE_GLOBAL.format(uid=int(uid))[:CUSTOM_ID_MAX]


def cid_identite(uid, ident) -> str:
    # l'uid AVANT l'identite : coupe a 100 caracteres, c'est la fin du nom
    # qui saute, jamais l'uid -- et la comparaison coupe pareil
    return CID_ETIQUETTE.format(uid=int(uid), ident=ident)[:CUSTOM_ID_MAX]


def adresse_publique(fiche) -> str:
    """L'adresse a copier d'un lien du registre : public_url, sinon une url
    getmysocial, sinon reconstruite du shortcode."""
    if not isinstance(fiche, dict):
        return ""
    for cle in ("public_url", "url"):
        u = str(fiche.get(cle) or "").strip()
        if u and "getmysocial" in u.lower():
            return u
    sc = str(fiche.get("shortcode") or "").strip()
    if sc:
        try:
            import gms
            dom = gms.PUBLIC_LINK_DOMAIN
        except Exception:
            dom = "https://getmysocial.com"
        return f"{dom}/{sc}"
    return ""


# ──────────────────────────────────────────────────────────── le panneau ──

def entrees_panneau(uid, guild, liens):
    """(entrees, sans_base) : [(identite, libelle, emoji, cree)] des
    identites US qui ont une page de base, et les identites US qui n'en ont
    pas (a dire au journal : sans « TEMPLATE <identite> » dans l'equipe, une
    identite n'est pas proposee)."""
    lu = _lu()
    idents = identites_us()
    if lu is None:
        return [], []
    try:
        # LA coche vient du module (son registre : lien « ok » de ce VA pour
        # cette identite) -- pas d'une seconde lecture ici, qui finirait par
        # ne plus dire la meme chose. Un lien « a_reparer » n'a pas sa coche :
        # le rechoisir le repare.
        props = lu.identites_proposables(idents, liens if liens is not None else [], uid=uid)
    except Exception as e:                                   # noqa: BLE001
        print(f"[gdl] identites proposables illisibles : {type(e).__name__}: {e}", flush=True)
        return [], []
    noms, deja = [], set()
    for p in props or []:
        nom, cree = (p[0], bool(p[1])) if isinstance(p, (tuple, list)) and len(p) > 1 else (p, False)
        nom = str(nom or "").strip().lower()
        if nom and nom not in noms:
            noms.append(nom)
            if cree:
                deja.add(nom)
    sans_base = [i for i in idents if str(i).strip().lower() not in noms]
    emo = emojis(guild, noms)
    return ([(i, lib, emo.get(i), i in deja) for i, lib in libelles(noms)], sans_base)


def vue_panneau(uid, n, global_pose: bool, entrees, actif=True, nom=None) -> discord.ui.LayoutView:
    """Le panneau, en Components V2 comme le spoofer et le menu VA : un bloc
    vert, le compteur, le(s) menu(s) des identites, le bouton admin.

    Sans lien global (ou module indisponible : `actif` faux), UN menu grise
    dont l'intitule dit pourquoi -- la seule chose qu'on y lit. Ce qui ne
    tient pas dans le message (plus de MAX_MENUS menus, nom inutilisable) est
    journalise, jamais ecarte en silence."""
    ui = discord.ui
    vue = ui.LayoutView(timeout=None)
    boite = ui.Container(accent_colour=VERT)
    boite.add_item(ui.TextDisplay(texte_compteur(n, nom)))
    bons = []
    for ident, lib, emo, cree in entrees or []:
        if not _NOM_IDENT.fullmatch(str(ident)):
            print(f"[gdl] identite {ident!r} inutilisable dans un menu Discord : non proposee",
                  flush=True)
            continue
        bons.append((ident, lib, emo, cree))
    blocs = [bons[i:i + TAILLE_MENU] for i in range(0, len(bons), TAILLE_MENU)]
    if len(blocs) > MAX_MENUS:
        hors = [e[0] for b in blocs[MAX_MENUS:] for e in b]
        print(f"[gdl] {len(hors)} identite(s) au-dela de {MAX_MENUS} menus, NON proposees : "
              + ", ".join(hors), flush=True)
        blocs = blocs[:MAX_MENUS]
    if not actif:
        menus = [GdlIdentites(uid, 0, intitule=INTITULE_INDISPO)]
    elif not global_pose:
        menus = [GdlIdentites(uid, 0, intitule=INTITULE_VERROU)]
    elif not blocs:
        menus = [GdlIdentites(uid, 0, intitule=INTITULE_VIDE)]
    else:
        menus, k = [], 0
        for i, bloc in enumerate(blocs):
            plage = (f"🪪 {k + 1}–{k + len(bloc)}…" if len(blocs) > 1 else INTITULE_MENU)
            menus.append(GdlIdentites(uid, i, bloc=bloc, intitule=plage))
            k += len(bloc)
    for m in menus:
        rangee = ui.ActionRow()
        rangee.add_item(m)
        boite.add_item(rangee)
    rangee = ui.ActionRow()
    rangee.add_item(GdlGlobal(uid))
    boite.add_item(rangee)
    vue.add_item(boite)
    return vue


def vue_etiquette(libelle, emoji, custom_id) -> discord.ui.View:
    """Le bouton gris qui nomme un lien : desactive, il ne fait rien (comme
    cogs/user._vue_etiquette). Rien a ecouter : la vue n'est pas gardee."""
    v = discord.ui.View(timeout=1)
    v.add_item(discord.ui.Button(label=str(libelle)[:80], emoji=emoji, disabled=True,
                                 style=discord.ButtonStyle.secondary,
                                 custom_id=str(custom_id)[:CUSTOM_ID_MAX]))
    return v


# ────────────────────────────────────────────── reconnaitre les messages ──

def _composants(message) -> list:
    """Les composants d'un message, a plat (V2 compris)."""
    out, pile = [], list(getattr(message, "components", None) or [])
    while pile:
        c = pile.pop(0)
        out.append(c)
        pile += list(getattr(c, "children", None) or [])
        pile += list(getattr(c, "components", None) or [])
        acc = getattr(c, "accessory", None)
        if acc is not None:
            pile.append(acc)
    return out


def custom_ids(message) -> set:
    return {c.custom_id for c in _composants(message) if getattr(c, "custom_id", None)}


def _du_bot(message, moi) -> bool:
    return getattr(getattr(message, "author", None), "id", None) == moi


_UID_PANNEAU = re.compile(r"^gdl:(?:id|gl):(\d{1,20})(?::|$)")


def uid_du_panneau(message, moi):
    """L'uid du VA dont ce message est le panneau, ou None."""
    if not _du_bot(message, moi):
        return None
    for c in custom_ids(message):
        m = _UID_PANNEAU.match(c)
        if m:
            return int(m.group(1))
    return None


def est_panneau(message, moi, uid=None) -> bool:
    u = uid_du_panneau(message, moi)
    return u is not None and (uid is None or u == int(uid))


def est_message_global(message, moi, uid=None) -> bool:
    if not _du_bot(message, moi):
        return False
    cids = custom_ids(message)
    if uid is None:
        return any(c.startswith("gdl:g:") for c in cids)
    return cid_global(uid) in cids


def est_message_identite(message, moi, ident, uid) -> bool:
    return _du_bot(message, moi) and cid_identite(uid, ident) in custom_ids(message)


_CHIFFRE = re.compile(r"🟢\s*(\d+)")


def compteur_affiche(message):
    """Le nombre que montre un panneau deja pose, ou None."""
    for c in _composants(message):
        m = _CHIFFRE.search(str(getattr(c, "content", "") or ""))
        if m:
            return int(m.group(1))
    return None


def _dicts_a_plat(message):
    """Les dictionnaires d'API des composants d'un message, a plat ; None si
    l'un ne se relit pas."""
    pile = []
    for c in getattr(message, "components", None) or []:
        try:
            pile.append(c.to_dict())
        except Exception:
            return None
    out = []
    while pile:
        d = pile.pop(0)
        if isinstance(d, dict):
            out.append(d)
            pile = list(d.get("components") or []) + pile
    return out


def vue_du_message(uid, message):
    """Le panneau tel qu'il est AFFICHE, refait a l'identique (meme chiffre,
    memes identites, memes coches, meme nom) : de quoi remettre le menu sur
    son intitule quand la liste GetMySocial manque pour le recalculer (juste
    apres un redemarrage pendant une pause de quota). Sans ca, le menu
    restait sur l'identite choisie, et la rechoisir ne declenchait rien. None
    si le message ne se relit pas."""
    dicts = _dicts_a_plat(message)
    if not dicts:
        return None
    n, nom = compteur_affiche(message), None
    for d in dicts:
        t = str(d.get("content") or "")
        if "🟢" in t and _SEP_NOM in t:
            nom = t.split(_SEP_NOM, 1)[1].strip() or None
    menus = [d for d in dicts if d.get("type") == 3
             and str(d.get("custom_id") or "").startswith(f"gdl:id:{int(uid)}:")]
    if not menus:
        return None
    if len(menus) == 1 and menus[0].get("disabled"):
        ph = menus[0].get("placeholder")
        if ph == INTITULE_VERROU:
            return vue_panneau(uid, n, False, [], nom=nom)
        if ph == INTITULE_INDISPO:
            return vue_panneau(uid, n, False, [], actif=False, nom=nom)
        return vue_panneau(uid, n, True, [], nom=nom)
    entrees = []
    for d in menus:
        for o in d.get("options") or []:
            val, lib = str(o.get("value") or ""), str(o.get("label") or "")
            if not val or val == "_":
                continue
            cree = lib.endswith(" ✅")
            if cree:
                lib = lib[:-2]
            e = o.get("emoji")
            emo = None
            if isinstance(e, dict) and (e.get("id") or e.get("name")):
                try:
                    emo = discord.PartialEmoji.from_dict(e)
                except Exception:
                    emo = None
            entrees.append((val, lib, emo, cree))
    return vue_panneau(uid, n, True, entrees, nom=nom)


def _emoji_cle(e):
    if e is None:
        return None
    if isinstance(e, dict):
        return (str(e.get("name") or ""), str(e.get("id") or ""))
    return (str(getattr(e, "name", "") or e), str(getattr(e, "id", "") or ""))


def _empreinte_dicts(composants) -> list:
    """Ce qui se VOIT d'un message, a plat : sert a ne redessiner un panneau
    que s'il a change. Les deux cotes (la vue a poser, le message pose)
    passent par leurs dictionnaires d'API, les cles techniques en moins
    (« id » numerote par Discord, « required »…)."""
    out, pile = [], list(composants or [])
    while pile:
        d = pile.pop(0)
        if not isinstance(d, dict):
            continue
        out.append((d.get("type"), d.get("content"), d.get("custom_id"), d.get("label"),
                    bool(d.get("disabled", False)), d.get("placeholder"),
                    _emoji_cle(d.get("emoji")),
                    tuple((o.get("label"), o.get("value"), _emoji_cle(o.get("emoji")))
                          for o in (d.get("options") or []))))
        pile = list(d.get("components") or []) + pile
    return out


def empreinte_vue(vue) -> list:
    return _empreinte_dicts(vue.to_components())


def empreinte_message(message) -> list:
    dicts = []
    for c in getattr(message, "components", None) or []:
        try:
            dicts.append(c.to_dict())
        except Exception:
            return []
    return _empreinte_dicts(dicts)


# ──────────────────────────────────────────────────────────── composants ──

class GdlIdentites(discord.ui.DynamicItem[discord.ui.Select],
                   template=r"gdl:id:(?P<uid>\d{1,20}):(?P<n>\d{1,2})"):
    """Un menu des identites du VA `uid` (le n-ieme, par TAILLE_MENU).

    Seul l'uid est dans le custom_id : l'identite choisie arrive avec le clic
    et elle est VALIDEE contre la liste du moment, jamais crue sur parole. Il
    repond donc apres un redemarrage (from_custom_id)."""

    def __init__(self, uid, n=0, bloc=(), intitule=None):
        self.uid = int(uid)
        self.n = int(n)
        opts = []
        for ident, lib, emo, cree in bloc or ():
            texte = f"{lib} ✅" if cree else str(lib)
            opts.append(discord.SelectOption(label=texte[:LIBELLE_MAX],
                                             value=str(ident)[:VALEUR_MAX], emoji=emo))
        vide = not opts
        if vide:
            opts = [discord.SelectOption(label="—", value="_")]
        super().__init__(discord.ui.Select(
            placeholder=intitule or INTITULE_MENU, min_values=1, max_values=1,
            options=opts, disabled=vide,
            custom_id=CID_MENU.format(uid=self.uid, n=self.n)))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["uid"], match["n"])

    async def callback(self, interaction: discord.Interaction):
        choix = ((getattr(self.item, "values", None) or [""])[0] or "").strip().lower()
        cog = interaction.client.get_cog("GenerateurLien") if interaction.client else None
        if cog is None:
            await _dire(interaction, "🔒 Générateur indisponible pour le moment.")
            return
        await cog.choisir(interaction, self.uid, choix)


class GdlGlobal(discord.ui.DynamicItem[discord.ui.Button],
                template=r"gdl:gl:(?P<uid>\d{1,20})"):
    """🔗 Lien global : un admin y pose le lien global du VA `uid`."""

    def __init__(self, uid):
        self.uid = int(uid)
        super().__init__(discord.ui.Button(label="Lien global", emoji="🔗",
                                           style=discord.ButtonStyle.secondary,
                                           custom_id=CID_GLOBAL_BOUTON.format(uid=self.uid)))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["uid"])

    async def callback(self, interaction: discord.Interaction):
        # La fenetre doit etre la TOUTE PREMIERE reponse (trois secondes) :
        # rien d'asynchrone avant.
        if not serveur_ok(getattr(interaction, "guild", None)):
            await interaction.response.send_message("🔒 Réservé au serveur US.", ephemeral=True)
            return
        if not est_admin(interaction.user):
            await _dire(interaction, "🔒 Réservé aux admins.")
            return
        defaut = ""
        lu = _lu()
        if lu is not None:
            try:
                g = lu.global_de(self.uid) or {}
                defaut = str(g.get("shortcode") or "")
            except Exception as e:                           # noqa: BLE001
                print(f"[gdl] global de {self.uid} illisible : {type(e).__name__}: {e}", flush=True)
        await interaction.response.send_modal(FenetreGlobal(self.uid, defaut=defaut))


#: custom_id des fenetres ouvertes PAR CE PROCESSUS (cogs/spoofer._OUVERTES) :
#: une fenetre ouverte avant un redemarrage (un par deploiement) et validee
#: apres etait jetee par discord.py sans reponse ; on la reconstruit.
_OUVERTES: set = set()


class FenetreGlobal(discord.ui.Modal, title="🔗 Lien global"):
    valeur = discord.ui.TextInput(label="Shortcode, adresse ou nom du lien",
                                  placeholder="msgejessye", required=True,
                                  min_length=2, max_length=200, custom_id="gdl:valeur")

    def __init__(self, uid, defaut: str = "", custom_id: str = None):
        self.uid = int(uid)
        super().__init__(custom_id=custom_id or CID_FENETRE.format(
            uid=self.uid, alea=os.urandom(4).hex()))
        if custom_id is None:
            _OUVERTES.add(self.custom_id)
        if defaut:
            self.valeur.default = defaut

    async def on_submit(self, interaction: discord.Interaction):
        # Le custom_id RESTE dans _OUVERTES : discord.py remet la fenetre ET
        # l'evenement « interaction » ; le retirer ici ferait reprendre par
        # on_interaction une soumission deja traitee (le spoofer l'a vu).
        cog = interaction.client.get_cog("GenerateurLien") if interaction.client else None
        if cog is None:
            await interaction.response.send_message("🔒 Générateur indisponible.", ephemeral=True)
            return
        await cog.definir(interaction, self.uid, str(self.valeur.value or "").strip())


# ─────────────────────────────────────────────────────────── utilitaires ──

async def _accuser(interaction) -> None:
    try:
        from cogs.user import _jb_accuser
        await _jb_accuser(interaction, "generateur de lien")
        return
    except Exception:
        pass
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except Exception:
        pass


async def _dire(interaction, texte: str) -> None:
    """Une ligne au VA, dans son -content (regle du proprietaire : jamais
    dans le salon du panneau). Repli en ephemere. Ne leve jamais."""
    try:
        from cogs.user import _jb_dire
        await _jb_dire(interaction, texte, "generateur de lien")
        return
    except Exception as e:                                   # noqa: BLE001
        print(f"[gdl] message non dit ({type(e).__name__}: {e}) : {texte[:160]}", flush=True)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(texte, ephemeral=True)
        else:
            await interaction.followup.send(texte, ephemeral=True)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────── cog ──

_PAS_LU = object()


class GenerateurLien(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        #: une creation a la fois par VA (le module a son verrou ; celui-ci
        #: sert a DIRE « deja en cours » au lieu d'attendre en silence)
        self.en_cours = set()
        self._taches = set()

    async def cog_load(self):
        try:
            self.bot.add_dynamic_items(GdlIdentites, GdlGlobal)
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] composants non rattaches : {e}", flush=True)
        try:
            if not self._entretien.is_running():
                self._entretien.start()
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] entretien non lance : {e}", flush=True)

    async def cog_unload(self):
        try:
            self._entretien.cancel()
        except Exception:
            pass

    @property
    def moi(self) -> int:
        return getattr(getattr(self.bot, "user", None), "id", 0)

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        """Une fenetre « 🔗 Lien global » ouverte AVANT un redemarrage et
        validee apres : reconstruite a partir de son custom_id."""
        if interaction.type is not discord.InteractionType.modal_submit:
            return
        data = interaction.data or {}
        cid = str(data.get("custom_id") or "")
        if not cid.startswith("gdl:fen:") or cid in _OUVERTES:
            return
        print(f"[gdl] fenetre d'avant redemarrage reprise : {cid}", flush=True)
        try:
            m = FenetreGlobal(cid.split(":")[2], custom_id=cid)
            t = m._dispatch_submit(interaction, data.get("components") or [],
                                   data.get("resolved") or {})
            self._taches.add(t)
            t.add_done_callback(self._taches.discard)
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] fenetre {cid} non reprise : {type(e).__name__}: {e}", flush=True)

    # ------------------------------------------------------------ donnees --

    async def liste(self, force=False):
        """(liens, raison) de l'equipe, hors de la boucle (requete reseau
        possible quand le cache a expire). liens None si indisponible."""
        lu = _lu()
        if lu is None:
            return None, "module liens_identite_us absent"
        try:
            liens, raison = await asyncio.to_thread(lu.liens_equipe, force)
        except Exception as e:                               # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"
        if raison:
            return (liens or None), str(raison)
        return list(liens or []), ""

    def vue_pour(self, uid, guild, liens, n=_PAS_LU, nom=None):
        """Le panneau du VA `uid` avec l'etat du moment."""
        lu = _lu()
        if lu is None:
            return vue_panneau(uid, None, False, [], actif=False, nom=nom)
        try:
            gl = lu.global_de(uid)
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] global de {uid} illisible : {type(e).__name__}: {e}", flush=True)
            gl = None
        pose = bool(gl)
        if pose and liens is not None:
            # un global retire de l'equipe remet le panneau en attente : un
            # choix d'identite n'y menerait qu'a une erreur (et a une
            # relecture de GetMySocial)
            try:
                pose = lu.global_present(uid, liens) is not False
            except Exception as e:                           # noqa: BLE001
                print(f"[gdl] presence du global de {uid} inconnue : {e}", flush=True)
        entrees, _sans = entrees_panneau(uid, guild, liens)
        if n is _PAS_LU:
            n = compter(uid, liens)
        return vue_panneau(uid, n, pose, entrees, nom=nom)

    # -------------------------------------------------------------- clics --

    def _refus(self, interaction, uid) -> str:
        if not serveur_ok(getattr(interaction, "guild", None)):
            return "🔒 Réservé au serveur US."
        if getattr(interaction.user, "id", None) != uid and not est_admin(interaction.user):
            canal = getattr(interaction, "channel", None)
            siens = {int(getattr(v, "id", 0) or 0) for v in vas_du_salon(canal)} if canal else set()
            if int(getattr(interaction.user, "id", 0) or 0) in siens:
                return "🔒 Ce menu n'est pas le tien : prends celui à ton nom."
            return "🔒 Ce salon n'est pas le tien."
        return ""

    async def _redessiner(self, interaction, uid, liens=_PAS_LU):
        """Le panneau du clic, avec le compteur et les coches du moment : le
        menu reprend aussi son intitule (sans ca, rechoisir la meme identite
        ne declencherait rien). Ne leve jamais."""
        try:
            msg = getattr(interaction, "message", None)
            nom = nom_si_partage(getattr(interaction, "channel", None), uid)
            if liens is _PAS_LU:
                liens, _r = await self.liste()
            if liens is None and _lu() is not None:
                # Liste GetMySocial indisponible : sans elle, aucune page de
                # base n'est connue et le panneau passerait a « Aucune
                # identité ». Il est refait A L'IDENTIQUE de ce qu'il montre,
                # pour que le menu reprenne son intitule ; l'entretien le
                # remettra a jour.
                vue = vue_du_message(uid, msg) if msg is not None else None
                if vue is None:
                    print(f"[gdl] panneau de {uid} laisse tel quel : liste GetMySocial "
                          "indisponible, message illisible", flush=True)
                    return
            else:
                n = compter(uid, liens)
                if n is None:
                    n = compteur_affiche(msg)
                vue = self.vue_pour(uid, getattr(interaction, "guild", None), liens, n=n, nom=nom)
            try:
                await interaction.edit_original_response(view=vue)
            except Exception:
                if msg is not None:
                    await msg.edit(view=vue)
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] panneau de {uid} non redessine : {type(e).__name__}: {e}", flush=True)

    async def choisir(self, interaction, uid, ident):
        """Un VA choisit une identite : son lien, cree ou redonne, SEUL dans
        un message du salon ; les refus et erreurs dans son -content."""
        await _accuser(interaction)
        refus = self._refus(interaction, uid)
        lu = _lu()
        if not refus and lu is None:
            refus = "🔒 Générateur indisponible pour le moment."
        if not refus and (not ident or ident == "_"):
            refus = "🪪 Aucune identité choisie."
        if not refus and ident not in {str(i).strip().lower() for i in identites_us()}:
            refus = f"🪪 {ident} n'est plus proposée."
        if not refus and uid in self.en_cours:
            refus = "⏳ Un lien est déjà en cours de création."
        if refus:
            await _dire(interaction, refus)
            await self._redessiner(interaction, uid)
            return
        canal = getattr(interaction, "channel", None)
        nom_va_ = nom_si_partage(canal, uid)
        self.en_cours.add(uid)
        try:
            try:
                res = await asyncio.to_thread(lu.creer_pour_identite, uid, ident,
                                              interaction.user.id)
            except Exception as e:                           # noqa: BLE001
                res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
            res = res if isinstance(res, dict) else {"ok": False, "erreur": "réponse illisible"}
            nom = ident.capitalize()
            url = str(res.get("url") or "").strip()
            if res.get("ok") and url:
                emo = emojis(getattr(interaction, "guild", None), [ident]).get(ident)
                await self.poster_lien(canal, ident, url, emo, uid, nom_va_)
            elif res.get("ok"):
                print(f"[gdl] creation {uid}:{ident} : ok sans adresse ({res})", flush=True)
                await _dire(interaction, f"❌ {nom} : lien créé mais adresse introuvable, "
                                         "préviens un admin.")
            else:
                await _dire(interaction, f"❌ {nom} : {res.get('erreur') or 'échec'}")
            # le clic a pu voir le global change dans GetMySocial (c<N>,
            # nom) : ses autres pages suivent tout de suite, pas au prochain
            # clic de chacune
            try:
                autres = [i for i in (lu.a_rebrancher(uid) or []) if str(i).lower() != ident]
            except Exception as e:                           # noqa: BLE001
                print(f"[gdl] pages a rebrancher de {uid} illisibles : {e}", flush=True)
                autres = []
            if autres:
                await self._rebrancher(canal, uid, autres, interaction.user.id, nom_va_)
        finally:
            self.en_cours.discard(uid)
        await self._redessiner(interaction, uid)

    async def _est_membre(self, guild, uid) -> bool:
        """`uid` est-il encore membre du serveur ? Dans le doute, oui : un
        global ne se reprend qu'a un VA PARTI, Discord le confirmant."""
        if guild is None:
            return True
        try:
            if guild.get_member(int(uid)) is not None:
                return True
        except Exception:
            pass
        try:
            await guild.fetch_member(int(uid))
            return True
        except discord.NotFound:
            return False
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] membre {uid} non verifie ({type(e).__name__}: {e}) : suppose present",
                  flush=True)
            return True

    async def definir(self, interaction, uid, valeur):
        """Un admin pose le lien global du VA `uid` (fenetre « 🔗 Lien
        global ») : il est poste SEUL dans le salon, le panneau se deverrouille.
        La reponse est pour l'admin, en ephemere : le VA n'a pas a lire la
        cuisine des liens dans son -content."""
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception:
            pass

        async def _repondre(texte):
            try:
                await interaction.followup.send(texte, ephemeral=True)
            except Exception as e:                           # noqa: BLE001
                print(f"[gdl] reponse a l'admin perdue ({e}) : {texte[:160]}", flush=True)

        if not serveur_ok(getattr(interaction, "guild", None)):
            await _repondre("🔒 Réservé au serveur US.")
            return
        if not est_admin(interaction.user):
            await _repondre("🔒 Réservé aux admins.")
            return
        lu = _lu()
        if lu is None:
            await _repondre("🔒 Générateur indisponible (module liens_identite_us absent).")
            return
        guild = getattr(interaction, "guild", None)

        async def _definir(partis=()):
            try:
                if partis:
                    r = await asyncio.to_thread(lu.definir_global, uid, valeur, interaction.user.id,
                                                partis=list(partis))
                else:
                    r = await asyncio.to_thread(lu.definir_global, uid, valeur, interaction.user.id)
            except Exception as e:                           # noqa: BLE001
                r = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
            return r if isinstance(r, dict) else {"ok": False, "erreur": "réponse illisible"}

        res = await _definir()
        autre = res.get("autre_uid")
        if not res.get("ok") and autre and not await self._est_membre(guild, autre):
            # le lien d'un VA parti passe au suivant (« quand un VA part, le
            # suivant herite du lien ») : Discord dit qu'il n'est plus la
            res = await _definir(partis=[autre])
        if not res.get("ok"):
            await _repondre(f"❌ {res.get('erreur') or 'échec'}")
            return
        g = res.get("global") or {}
        notes = []
        anc = res.get("remplace")
        if isinstance(anc, dict):
            notes.append(f"remplace « {anc.get('nom') or anc.get('shortcode')} »")
        if res.get("repris_de"):
            n_p = int(res.get("pages_du_parti") or 0)
            notes.append(f"repris de <@{res['repris_de']}>, parti"
                         + (f" ; ses {n_p} page(s) d'identité restent sur ce lien" if n_p else ""))
        if res.get("meme_personne"):
            notes.append("même personne que " + ", ".join(
                f"<@{a}>" for a in res["meme_personne"]))
        canal = getattr(interaction, "channel", None)
        nom_va_ = nom_si_partage(canal, uid)
        poste = await self.poster_global(canal, g, uid, nom_va_) if canal is not None else False
        # Ses pages d'identite visaient l'ancien suivi : rebranchees MAINTENANT
        # (deux appels GetMySocial chacune, geste d'admin borne). Attendre le
        # clic du VA, c'etait attendre pour rien : son message garde la meme
        # adresse, rien ne l'invite a rechoisir -- et ses ventes allaient a
        # l'ancien global.
        a_rb = list(res.get("a_rebrancher") or [])
        if a_rb:
            faits, rates = await self._rebrancher(canal, uid, a_rb, interaction.user.id, nom_va_)
            notes.append(f"{faits}/{len(a_rb)} page(s) d'identité rebranchée(s)"
                         + (f", {len(rates)} au prochain entretien" if rates else ""))
        liens, _r = await self.liste()
        try:
            vue = self.vue_pour(uid, guild, liens, nom=nom_va_)
            msg = getattr(interaction, "message", None)
            if msg is not None and est_panneau(msg, self.moi, uid):
                await msg.edit(view=vue)
            elif canal is not None:
                await self.assurer_panneau(canal, liens, _r)
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] panneau de {uid} non redessine : {type(e).__name__}: {e}", flush=True)
        if not poste:
            notes.append("message du lien non posté, voir le journal")
        await _repondre(f"✅ {g.get('nom') or g.get('shortcode') or 'lien global'}"
                        + (f" ({' ; '.join(notes)})" if notes else ""))

    async def _rebrancher(self, canal, uid, idents, par, nom_va_=None):
        """Rebranche les pages d'identite `idents` du VA sur son global du
        moment (creer_pour_identite : meme adresse, ~2 appels chacune). Une
        page RECREEE (supprimee entre-temps dans GetMySocial) change
        d'adresse : la nouvelle est postee. Rend (rebranchees, [echecs])."""
        lu = _lu()
        if lu is None or not idents:
            return 0, []
        try:
            avant = {str(e.get("identite") or "").strip().lower(): adresse_publique(e)
                     for e in (lu.liens_de(uid) or []) if isinstance(e, dict)}
        except Exception:
            avant = {}
        faits, rates = 0, []
        for ident in idents:
            k = str(ident or "").strip().lower()
            try:
                r = await asyncio.to_thread(lu.creer_pour_identite, uid, ident, par)
            except Exception as e:                           # noqa: BLE001
                r = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
            r = r if isinstance(r, dict) else {"ok": False, "erreur": "réponse illisible"}
            url = str(r.get("url") or "").strip()
            if r.get("ok") and url:
                faits += 1
                if canal is not None and (url != avant.get(k) or r.get("adresse_changee")):
                    emo = emojis(getattr(canal, "guild", None), [k]).get(k)
                    await self.poster_lien(canal, k, url, emo, uid, nom_va_)
            else:
                rates.append(f"{ident} : {r.get('erreur') or 'échec'}")
        print(f"[gdl] {uid} : {faits}/{len(idents)} page(s) d'identite rebranchee(s)"
              + (f" ; reste : {' | '.join(rates)[:300]}" if rates else ""), flush=True)
        return faits, rates

    # ------------------------------------------------------------ messages --

    async def _retirer(self, canal, quoi) -> None:
        """Retire les messages du bot que `quoi(message)` designe : un lien
        repose remplace l'ancien, le salon garde UN message par lien."""
        try:
            async for m in canal.history(limit=200):
                if quoi(m):
                    try:
                        await m.delete()
                    except Exception as e:                   # noqa: BLE001
                        print(f"[gdl] ancien message non retire de #{canal.name} : {e}",
                              flush=True)
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] #{getattr(canal, 'name', '?')} illisible : {e}", flush=True)

    async def _poster(self, canal, url, vue) -> bool:
        """L'adresse SEULE (cogs/user._envoyer_a_copier) : ni titre, ni bloc
        de code, pas d'apercu, aucune mention. Le nom est le bouton gris."""
        try:
            await canal.send(url, view=vue, allowed_mentions=discord.AllowedMentions.none(),
                             suppress_embeds=True)
            return True
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] lien non poste dans #{getattr(canal, 'name', '?')} : "
                  f"{type(e).__name__}: {e}", flush=True)
            return False

    async def poster_global(self, canal, g, uid, nom_va_=None) -> bool:
        url = adresse_publique(g)
        if not url:
            print(f"[gdl] lien global sans adresse : {g}", flush=True)
            return False
        moi = self.moi
        await self._retirer(canal, lambda m: est_message_global(m, moi, uid))
        return await self._poster(canal, url, vue_etiquette(
            "Global" + (f"{_SEP_NOM}{nom_va_}" if nom_va_ else ""), "🌐", cid_global(uid)))

    async def poster_lien(self, canal, ident, url, emoji=None, uid=0, nom_va_=None) -> bool:
        moi = self.moi
        await self._retirer(canal, lambda m: est_message_identite(m, moi, ident, uid))
        return await self._poster(canal, url, vue_etiquette(
            ident.capitalize() + (f"{_SEP_NOM}{nom_va_}" if nom_va_ else ""), emoji,
            cid_identite(uid, ident)))

    # ------------------------------------------------------------- salons --

    async def assurer_panneau(self, canal, liens=_PAS_LU, raison="") -> int:
        """Les panneaux du salon (un par VA), a jour et seuls ; le lien global
        de chacun pose s'il manque OU si son adresse a change. Avec une liste
        GetMySocial fraiche, le registre la suit d'abord (liens_identite_us.
        actualiser, sans appel) : adresses changees repostees, pages d'un
        global change rebranchees. Un panneau deja juste n'est pas touche.
        Rend le nombre de panneaux poses ou redessines."""
        if not est_salon(canal) or not serveur_ok(getattr(canal, "guild", None)):
            return 0
        vas = vas_du_salon(canal)
        if not vas:
            print(f"[gdl] #{getattr(canal, 'name', '?')} : aucun VA n'y voit -- panneau non pose",
                  flush=True)
            return 0
        moi = self.moi
        try:
            msgs = [m async for m in canal.history(limit=200)]
        except Exception as e:                               # noqa: BLE001
            print(f"[gdl] #{getattr(canal, 'name', '?')} illisible : {e}", flush=True)
            return 0
        if liens is _PAS_LU:
            liens, raison = await self.liste()
        lu = _lu()
        partage = len(vas) > 1
        uids = [int(va.id) for va in vas]
        # un panneau dont le VA n'est plus dans le salon : retire
        for m in msgs:
            u = uid_du_panneau(m, moi)
            if u is not None and u not in uids:
                try:
                    await m.delete()
                except Exception as e:                       # noqa: BLE001
                    print(f"[gdl] panneau d'un VA parti non retire de #{canal.name} : {e}",
                          flush=True)
        # 1. le registre suit GetMySocial (liste fraiche seulement)
        suivis = {}
        if lu is not None and liens is not None and not raison:
            for va in vas:
                try:
                    suivis[va.id] = await asyncio.to_thread(lu.actualiser, va.id, liens) or {}
                except Exception as e:                       # noqa: BLE001
                    print(f"[gdl] registre de {va.id} non actualise : {type(e).__name__}: {e}",
                          flush=True)
        for va in vas:
            a_rb = list((suivis.get(va.id) or {}).get("a_rebrancher") or [])
            if a_rb:
                await self._rebrancher(canal, va.id, a_rb, "entretien",
                                       nom_va(va) if partage else None)
        # 2. les panneaux, un par VA, dans l'ordre des VA
        fait = 0
        for va in vas:
            panneaux = [m for m in msgs if est_panneau(m, moi, va.id)]
            if raison and panneaux:
                # GetMySocial indisponible : un panneau deja la garde son
                # chiffre et ses identites plutot que de passer a « 0 ».
                continue
            n = compter(va.id, liens)
            if n is None and panneaux:
                n = compteur_affiche(panneaux[-1])
            vue = self.vue_pour(va.id, canal.guild, liens, n=n,
                                nom=nom_va(va) if partage else None)
            # l'historique va du plus recent au plus ancien : on garde le plus
            # ANCIEN panneau, en tete du salon, et on retire les autres
            garde = panneaux[-1] if panneaux else None
            for m in panneaux[:-1]:
                try:
                    await m.delete()
                except Exception as e:                       # noqa: BLE001
                    print(f"[gdl] panneau en double non retire de #{canal.name} : {e}", flush=True)
            try:
                if garde is None:
                    await canal.send(view=vue)
                    fait += 1
                elif empreinte_message(garde) != empreinte_vue(vue):
                    await garde.edit(view=vue)
                    fait += 1
            except Exception as e:                           # noqa: BLE001
                print(f"[gdl] panneau non pose dans #{getattr(canal, 'name', '?')} : "
                      f"{type(e).__name__}: {e}", flush=True)
        # 3. Les liens APRES les panneaux : un salon neuf se lit de haut en
        # bas, panneaux puis liens. Le global est repose s'il manque (salon
        # recree, message supprime a la main) ou si son adresse a change dans
        # GetMySocial -- le message gardait sinon une adresse morte, celle que
        # le VA copie d'un appui long.
        if lu is None:
            return fait
        for va in vas:
            nom_ = nom_va(va) if partage else None
            try:
                g = lu.global_de(va.id)
            except Exception as e:                           # noqa: BLE001
                print(f"[gdl] global de {va.id} illisible : {e}", flush=True)
                g = None
            if g:
                poses = [m for m in msgs if est_message_global(m, moi, va.id)]
                url = adresse_publique(g)
                if not poses or any(str(getattr(m, "content", "") or "").strip() != url
                                    for m in poses):
                    await self.poster_global(canal, g, va.id, nom_)
            for ident in (suivis.get(va.id) or {}).get("adresses") or []:
                k = str(ident).strip().lower()
                e = next((x for x in (lu.liens_de(va.id) or [])
                          if str(x.get("identite") or "").strip().lower() == k), None)
                url = adresse_publique(e) if e else ""
                if url:
                    emo = emojis(getattr(canal, "guild", None), [k]).get(k)
                    await self.poster_lien(canal, k, url, emo, va.id, nom_)
        return fait

    @tasks.loop(hours=ENTRETIEN_HEURES)
    async def _entretien(self):
        for guilde in list(getattr(self.bot, "guilds", []) or []):
            if not serveur_ok(guilde):
                continue
            try:
                # Les dossiers deja la recoivent leur salon par leurs DROITS
                # (completer_dossiers_us) : un VA qui a change de pseudo
                # garde un dossier a l'ancien nom.
                try:
                    from cogs.welcome import completer_dossiers_us
                    b = await completer_dossiers_us(guilde, (SUFFIXE,))
                    if b.get("crees"):
                        await asyncio.sleep(2.0)   # le cache recoit les salons neufs
                except Exception as e:                       # noqa: BLE001
                    print(f"[gdl] dossiers non completes : {type(e).__name__}: {e}", flush=True)
                liens, raison = await self.liste()
                if raison:
                    print(f"[gdl] liste GetMySocial indisponible ({raison}) : panneaux "
                          f"existants laisses tels quels, nouvel essai dans {REESSAI_MINUTES} min",
                          flush=True)
                    self._entretien.change_interval(minutes=REESSAI_MINUTES)
                else:
                    self._entretien.change_interval(hours=ENTRETIEN_HEURES)
                    _e, sans = entrees_panneau(0, None, liens)
                    if sans:
                        print(f"[gdl] {len(sans)} identite(s) US sans page « TEMPLATE <identite> » "
                              f"dans l'equipe, non proposees : {', '.join(sans)}", flush=True)
                poses = 0
                for canal in list(guilde.text_channels):
                    if est_salon(canal):
                        poses += await self.assurer_panneau(canal, liens, raison)
                        await asyncio.sleep(0.5)
                if poses:
                    print(f"[gdl] {poses} panneau(x) pose(s) ou redessine(s)", flush=True)
            except Exception as e:                           # noqa: BLE001
                print(f"[gdl] entretien de {getattr(guilde, 'name', '?')} : "
                      f"{type(e).__name__}: {e}", flush=True)

    @_entretien.before_loop
    async def _avant_entretien(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(GenerateurLien(bot))
