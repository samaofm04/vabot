# -*- coding: utf-8 -*-
"""Les outils COMMUNS d'un serveur US : cinq salons pour tous, un salon perso par VA.

POURQUOI (proprietaire, 30/10/2026, maquette validee)
    « sur YouCham, un salon ou tout le monde voit un menu en commun, un
    spoofer en commun, un download en commun, un numero en commun, et un
    content qui est leur ticket a eux, personnel », puis « oui vas-y
    construis-le sur YouCham ». Un dossier de cinq salons par VA (Youl4b)
    bute sur le plafond de Discord : 500 salons par serveur, soit une
    centaine de VA. Youl4b garde ses dossiers ; seuls les serveurs de
    guild_features.OUTILS_COMMUNS passent ici (aucun module ne recopie l'id
    de YouCham).

CE QUI VIT OU
    🧰 OUTILS -- lecture seule : on voit, on clique, on n'ecrit pas
        📋・menu      « 📋 Ouvrir mon menu » : le menu Jailbreak US du
                      cliqueur, en ephemere (cogs/user.ouvrir_menu_commun)
        📤・spoofer   le panneau du -spoofer (cogs/spoofer.py)
        ⬇️・download  le panneau du -download (cogs/telechargement.py)
        📱・numéro    le panneau du -numero-mail, pose par Rem, le bot admin
                      (cogs/numeros.py, boucle _panneau_commun) ; le numero
                      s'affiche dans une carte ephemere du cliqueur, 20 min
                      (numeros.clic_partage, depuis le 31/10/2026)
        📊・click-et-sub  un bouton-lien vers la page des liens de suivi de
                      Lia (infloww_liens, profil « lia ») : clics US, subs,
                      CVR, $ / sub par VA (proprietaire, 31/10/2026) ; au
                      dessus, l'image de chaque quinzaine finie, gardee
                      (01/11/2026, voir _tourner). YouCham SEUL (salons_de) :
                      You US et You FR, branches le 10/11/2026, ont les
                      quatre outils, pas les chiffres des VA de YouCham
    📁 SALONS PERSO, puis 📁 SALONS PERSO 2, 3... : Discord refuse un 51e
    salon dans une categorie. Un salon par VA, « <pseudo>-content » -- le
    nom de cogs/welcome._us_ticket_name, que toutes les recherches de -content
    connaissent deja --, prive : le VA, le staff, Ryuk et Rem (Rem y ecrit la
    carte du numero). Range par pseudo dans sa categorie.

LA REGLE DE LIVRAISON
    Un clic dans un salon commun livre dans le -content DU CLIQUEUR
    (content_de), jamais dans le salon commun : tout le monde y verrait ses
    fichiers. Quelqu'un sans -content (arrive avant les outils communs : le
    proprietaire, Roucham) en recoit un au clic (perso_ou_creer,
    lancer_perso), comme a l'arrivee ; refuser l'obligeait a attendre un
    /ticketsall (proprietaire, 30/10 : « met ca aussi stp »). Le refus court,
    en ephemere (REFUS), ne reste que si la creation echoue (Discord la
    refuse, ou Ryuk ne voit pas encore le serveur). Seuls les
    refus et les confirmations courtes sont ephemeres ; ce qui est livre vit
    dans le -content, qui survit a un rechargement de Discord.

    Sauf le numero, depuis le 31/10/2026 (proprietaire : « que ça ne me le
    fasse pas prendre dans mon ticket, mais dans le même salon ... un
    message éphémère ») : la carte du numero est ephemere, dans le
    📱・numéro, et ne passe plus par le -content.

    Sur ces serveurs, la regle tient PAR SERVEUR, pas par nom de salon
    (cible_du_clic, clic_commun) : rien n'y est livre ailleurs que dans un
    -content. Un salon commun renomme a la main (« 📱・phone ») restait sinon
    un salon ordinaire, et le numero, le code SMS ou les telechargements d'un
    VA s'y affichaient devant tous les autres.

RECONNAITRE LES SALONS COMMUNS
    Par leur id d'abord, garde dans data/outils_communs.json a la creation
    (ou a la relecture) ; par leur nom ensuite, si data/ est reparti de zero.
    Par le nom seul, un renommage les faisait oublier : l'entretien recreait
    une seconde 🧰 OUTILS avec quatre nouveaux panneaux.

CE QUI N'EST PAS ICI
    Aucune commande slash : le bot principal en a 100 sur 100. Les panneaux
    gardent leur code (spoofer, telechargement, numeros, user) : ils demandent
    seulement a ce module si le salon est commun, et ou livrer.
"""
from __future__ import annotations

import asyncio
import copy
import re
import time
import unicodedata
from pathlib import Path

import discord

import safe_json

#: La categorie des salons communs, et ses salons : (cle, nom a la creation).
#: La cle est le nom sans decor ni accent (_cle) : un salon renomme a la main
#: (« 📱 numero », « numéro ») reste reconnu. « ・ » et jamais « - » devant le
#: nom : « 📱-numero-mail » finirait comme le salon PRIVE d'un VA US, et
#: /ticketsall le compterait comme un ticket.
CATEGORIE = "🧰 OUTILS"
SALONS = (("menu", "📋・menu"), ("spoofer", "📤・spoofer"),
          ("download", "⬇️・download"), ("numero", "📱・numéro"),
          ("click-et-sub", "📊・click-et-sub"))
CLES = tuple(c for c, _n in SALONS)

#: Le salon que tous les serveurs aux outils communs n'ont pas : la page des
#: liens de suivi de Lia est celle des VA de YouCham
#: (guild_features.CLICS_ET_SUBS).
CLE_CLICS = "click-et-sub"


def salons_de(guilde) -> tuple:
    """Les salons communs de CE serveur, (cle, nom) : les quatre outils
    partout, le 📊・click-et-sub la seulement ou guild_features le dit.

    You US et You FR (10/11/2026) ont les outils de YouCham, pas ses
    chiffres : cree partout, le salon y aurait montre a tous les clics et
    les subs des VA de YouCham, image redessinee toutes les heures. Serveur
    illisible : sans le click-et-sub -- un salon de trop se voit, il
    faudrait le supprimer a la main."""
    try:
        import guild_features as gf
        avec = bool(gf.clics_et_subs(guilde))
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils-communs] click-et-sub de {getattr(guilde, 'name', '?')} "
              f"indecidable ({type(e).__name__}: {e}) : sans lui", flush=True)
        avec = False
    return tuple((c, n) for c, n in SALONS if avec or c != CLE_CLICS)


def cles_de(guilde) -> tuple:
    return tuple(c for c, _n in salons_de(guilde))

#: Les categories des salons perso : « 📁 SALONS PERSO », puis « … 2 »,
#: « … 3 ». Discord refuse un 51e salon dans une categorie (code 50035) : la
#: suivante est creee avant.
CATEGORIE_PERSO = "📁 SALONS PERSO"
PLAFOND_CATEGORIE = 50
_RE_PERSO = re.compile(r"^salons perso(?: (\d+))?$")

#: Le bouton du salon 📋・menu. Prefixe propre : discord.py lance TOUS les
#: motifs qui correspondent a un custom_id, celui-ci ne recoupe aucun autre
#: (jbus:, jbg:, cmenu:, spf:, dl:, numgen:).
MENU_ID = "ocm:menu"

#: Par serveur : {gid: {"menu": id du message, "categorie": id de 🧰 OUTILS,
#: "salons": {cle: id du salon}, "click-et-sub": id du panneau vivant,
#: "click-et-sub-du": debut de la quinzaine qu'il montre, "click-et-sub-archive":
#: {"id", "du", "au"} de la derniere quinzaine finie}}. Le message du menu :
#: sans lui, chaque passage relisait l'historique. Les ids des salons : voir
#: « RECONNAITRE ». La quinzaine du panneau : voir _tourner.
ETAT = Path(__file__).resolve().parent / "data" / "outils_communs.json"

#: Le refus, le meme pour les quatre outils. Court, sans notice. Dit
#: seulement quand le -content n'a pas pu etre cree (perso_ou_creer) : un
#: membre sans salon en recoit un au clic.
REFUS = "Tu n'as pas de salon perso ici : rien ne peut t'être livré."

#: L'etat lu, et ce qui dit s'il est encore frais (chemin, date, taille).
#: est_salon_outil est appele pour chaque -content d'une recherche : relire
#: le JSON a chaque fois, c'etait des centaines de lectures par clic.
_CACHE = {"cle": None, "d": {}}


def _cle_fichier():
    try:
        st = ETAT.stat()
        return (str(ETAT), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(ETAT), None, None)


def _etat() -> dict:
    """L'etat (lecture seule : _noter et _noter_salons en ecrivent une copie)."""
    cle = _cle_fichier()
    if _CACHE["cle"] != cle:
        d = safe_json.load(ETAT, default={}) if cle[1] is not None else {}
        _CACHE["cle"], _CACHE["d"] = cle, (d if isinstance(d, dict) else {})
    return _CACHE["d"]


def _ecrire(d) -> bool:
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(ETAT, d, indent=1):
        print("[outils-communs] etat non ecrit : relu dans le salon au prochain "
              "passage", flush=True)
        return False
    _CACHE["cle"], _CACHE["d"] = _cle_fichier(), d
    return True


def _noter(gid, cle, mid) -> None:
    d = copy.deepcopy(_etat())
    d.setdefault(str(gid), {})[cle] = int(mid) if mid else None
    _ecrire(d)


def _noter_valeurs(gid, valeurs) -> bool:
    """Plusieurs cles d'un serveur en UNE ecriture. Le changement de quinzaine
    note trois choses (panneau neuf, sa quinzaine, l'archive) : ecrites une a
    une, une coupure entre deux laisserait l'archive notee comme panneau vivant."""
    d = copy.deepcopy(_etat())
    d.setdefault(str(gid), {}).update(valeurs)
    return _ecrire(d)


def _noter_salons(gid, cat_id, salons) -> None:
    """Les ids de 🧰 OUTILS et de ses salons. Ecrit seulement s'ils changent :
    l'entretien repasse toutes les six heures."""
    d = copy.deepcopy(_etat())
    g = d.setdefault(str(gid), {})
    nouveau = {k: int(v) for k, v in salons.items() if v}
    if g.get("categorie") == (int(cat_id) if cat_id else None) and g.get("salons") == nouveau:
        return
    g["categorie"] = int(cat_id) if cat_id else None
    g["salons"] = nouveau
    _ecrire(d)


def _ids_notes(guilde) -> tuple:
    """(id de 🧰 OUTILS ou None, {id de salon: cle}) notes pour ce serveur."""
    g = _etat().get(str(getattr(guilde, "id", ""))) or {}
    salons = g.get("salons") if isinstance(g.get("salons"), dict) else {}
    par_id = {}
    for k, v in salons.items():
        try:
            if k in CLES and v:
                par_id[int(v)] = k
        except (TypeError, ValueError):
            continue
    try:
        cat = int(g.get("categorie")) if g.get("categorie") else None
    except (TypeError, ValueError):
        cat = None
    return cat, par_id


def _norm(nom) -> str:
    """Le nom sans ce qu'on ajoute DEVANT a la main (emoji, « ・ ») : la cle
    de cogs/welcome (nom_sans_decor), pour que les deux disent la meme chose."""
    try:
        from cogs.welcome import nom_sans_decor
        return nom_sans_decor(nom)
    except Exception:                                        # noqa: BLE001
        return str(nom or "").strip().lower()


def _cle(nom) -> str:
    """_norm, accents retires : « numéro » et « numero » sont le meme salon."""
    n = unicodedata.normalize("NFKD", _norm(nom))
    return "".join(ch for ch in n if not unicodedata.combining(ch))


def serveur(guilde) -> bool:
    """Ce serveur a-t-il les outils communs ? (guild_features.OUTILS_COMMUNS)"""
    try:
        import guild_features as gf
        return bool(gf.outils_communs(guilde))
    except Exception:                                        # noqa: BLE001
        return False


def est_categorie_outils(cat) -> bool:
    """🧰 OUTILS : par son id note, sinon par son nom."""
    if cat is None or not serveur(getattr(cat, "guild", None)):
        return False
    note, _salons = _ids_notes(cat.guild)
    if note is not None and getattr(cat, "id", None) == note:
        return True
    return _cle(getattr(cat, "name", "")) == _cle(CATEGORIE)


def est_salon_outil(canal, outil=None) -> bool:
    """Un salon commun de 🧰 OUTILS (de cet outil, si precise) : par son id
    note -- meme renomme ou sorti de la categorie --, sinon par son nom dans
    🧰 OUTILS."""
    if canal is None or not serveur(getattr(canal, "guild", None)):
        return False
    _cat, par_id = _ids_notes(canal.guild)
    cle = par_id.get(getattr(canal, "id", None))
    if cle is None:
        if not est_categorie_outils(getattr(canal, "category", None)):
            return False
        cle = _cle(getattr(canal, "name", ""))
        # Au nom, seulement les salons que CE serveur a : un « click-et-sub »
        # cree a la main dans le 🧰 OUTILS de You US n'est pas le panneau des
        # chiffres de YouCham (le tour de l'heure l'y aurait pose).
        if cle not in cles_de(canal.guild):
            return False
    return outil is None or cle == outil


def est_categorie_perso(cat) -> bool:
    return cat is not None and bool(_RE_PERSO.match(_cle(getattr(cat, "name", ""))))


def _numero_perso(cat) -> int:
    m = _RE_PERSO.match(_cle(getattr(cat, "name", "")))
    return int(m.group(1) or 1) if m else 0


def _est_content(canal) -> bool:
    """Un salon « …-content » de VA : jamais un salon de service ni un outil."""
    nom = getattr(canal, "name", "") or ""
    if not _norm(nom).endswith("-content") or est_salon_outil(canal):
        return False
    try:
        from cogs.welcome import salon_de_service
        return not salon_de_service(nom)
    except Exception:                                        # noqa: BLE001
        return not _norm(nom).startswith("all-")


def _a_soi(canal, uid) -> bool:
    """`uid` a-t-il SA regle sur ce salon, qui le lui ouvre ? Compare les ids :
    un membre hors du cache de discord.py y est un simple Object."""
    for t, ow in (getattr(canal, "overwrites", None) or {}).items():
        if getattr(t, "id", None) == uid and getattr(ow, "view_channel", None):
            return True
    return False


def content_de(guilde, membre):
    """Le salon -content de `membre` sur ce serveur, ou None.

    Un salon n'est le sien que s'il y a SA regle (_a_soi) : _us_base retire
    les points, « lea.m » et « leam » ont donc le meme nom de salon, et un
    nouveau venu peut reprendre le pseudo d'un VA parti. Au seul nom, le
    second recevait le salon du premier : ses fichiers, son numero et son
    code SMS s'affichaient chez l'autre, et lui n'avait rien.

    Dans l'ordre : <pseudo>-content (la convention de create_us_tickets), le
    plus ancien s'il y en a deux, comme le garde /ticketsall ; puis
    <pseudo>-<chiffres>-content, le nom que salon_perso donne quand le premier
    est deja a quelqu'un d'autre ; puis le -content dont il est le SEUL
    membre nomme dans les droits : un VA qui a change de pseudo garde son
    salon a l'ancien nom (4vbtc devenu x0btc sur Youl4b, 27/09), et sans ce
    repli il passait pour quelqu'un sans salon. « Seul » : un manager ajoute
    a la main sur le salon d'un VA ne doit pas recevoir ses propres
    livraisons chez ce VA.

    Les salons crees il y a moins de deux minutes comptent aussi : discord.py
    ne les met dans son cache qu'a l'evenement de Discord (_recents)."""
    if guilde is None or membre is None or getattr(membre, "bot", False):
        return None
    try:
        from cogs.welcome import _us_ticket_name
        vise = _us_ticket_name(membre, "content")
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils-communs] nom du -content illisible : {type(e).__name__}: {e}", flush=True)
        return None
    uid = getattr(membre, "id", None)
    vus = {}
    for c in list(getattr(guilde, "text_channels", None) or []) + _recents(guilde)["salons"]:
        if getattr(c, "id", None) not in vus and _est_content(c):
            vus[c.id] = c
    salons = sorted(vus.values(), key=lambda c: int(getattr(c, "id", 0) or 0))
    bis = re.compile(r"^" + re.escape(vise[: -len("-content")]) + r"-\d+-content$")
    for convient in (lambda n: n == vise, bis.match):
        a_lui = [c for c in salons if convient(_norm(c.name)) and _a_soi(c, uid)]
        if a_lui:
            return a_lui[0]
    for c in salons:
        humains = [t for t, ow in (getattr(c, "overwrites", None) or {}).items()
                   if getattr(t, "bot", None) is False and getattr(ow, "view_channel", None)]
        if len(humains) == 1 and getattr(humains[0], "id", None) == uid:
            return c
    return None


def cible_du_clic(canal, membre):
    """Ou livrer un clic fait dans `canal` sur un serveur aux outils communs.

    Un clic DANS un -content (le menu « Choisir ma brute » y est poste) : ce
    salon -- meme clique par un manager qui aide son VA. Ailleurs (un salon
    commun, un ephemere qui en vient, un salon commun renomme) : le -content
    du cliqueur, ou None. JAMAIS le salon du clic, JAMAIS par categorie :
    📁 SALONS PERSO range jusqu'a 50 -content, la recherche « le -content du
    meme dossier » de Youl4b y prendrait celui d'un autre VA."""
    if canal is not None and _est_content(canal):
        return canal
    return content_de(getattr(canal, "guild", None), membre)


def clic_commun(canal) -> bool:
    """Un clic fait dans `canal` doit-il etre servi au seul cliqueur ? Oui sur
    un serveur aux outils communs, partout sauf dans un -content.

    C'est la question que posent les panneaux (menu, spoofer, download,
    numero) avant de repondre : panneau ephemere ou panneau du salon, achat
    dans le salon ou dans le -content. Par le NOM du salon commun seul, un
    « 📱・numéro » renomme « 📱・phone » redevenait un salon ordinaire : le
    numero et son code s'y affichaient pour tous, le download y livrait, le
    menu y epinglait un panneau qui changeait de model a chaque clic."""
    return (canal is not None and serveur(getattr(canal, "guild", None))
            and not _est_content(canal))


# ───────────────────────────────────────────────────────── salons perso ──

#: Ce que ce processus vient de creer (ou de deplacer) dans les salons perso,
#: par serveur : {gid: [(instant, "cat" | "salon", objet, id de categorie)]}.
#: discord.py ne met un salon ou une categorie dans son cache qu'a l'evenement
#: de Discord, qui suit la reponse a la creation : sans cette memoire, deux
#: arrivees rapprochees voyaient « aucune 📁 SALONS PERSO » et en creaient
#: deux, ou comptaient 49 salons dans une categorie qui en avait deja 50.
_RECENTS = {}
_DUREE_RECENTE = 120.0

#: Un verrou par serveur autour de salon_perso : chaque on_member_join est
#: une tache a part, /ticketsall aussi. {gid: (boucle, verrou)}.
_VERROUS = {}


def _retenir(guilde, genre, objet, cat_id=None) -> None:
    _RECENTS.setdefault(getattr(guilde, "id", 0), []).append(
        (time.monotonic(), genre, objet, cat_id))


def _recents(guilde) -> dict:
    """{"cats": [...], "salons": [...], "dans": {id de categorie: {ids}}} :
    ce que ce processus a cree ou deplace ici il y a moins de deux minutes."""
    gid = getattr(guilde, "id", 0)
    maintenant = time.monotonic()
    garde = [x for x in _RECENTS.get(gid, []) if maintenant - x[0] < _DUREE_RECENTE]
    if garde:
        _RECENTS[gid] = garde
    else:
        _RECENTS.pop(gid, None)
    out = {"cats": [], "salons": [], "dans": {}}
    for _t, genre, objet, cat_id in garde:
        # Un objet d'une session precedente (READY recree le serveur) : le
        # cache neuf le connait deja, et il pourrait avoir change depuis.
        if getattr(objet, "guild", None) is not guilde:
            continue
        if genre == "cat":
            out["cats"].append(objet)
        else:
            out["salons"].append(objet)
            out["dans"].setdefault(cat_id, set()).add(getattr(objet, "id", None))
    return out


def _verrou(guilde) -> asyncio.Lock:
    """Le verrou du serveur. Un par boucle : un verrou ne sert que la boucle
    ou il a attendu une premiere fois."""
    boucle = asyncio.get_running_loop()
    gid = getattr(guilde, "id", 0)
    v = _VERROUS.get(gid)
    if v is None or v[0] is not boucle:
        v = (boucle, asyncio.Lock())
        _VERROUS[gid] = v
    return v[1]


def _categorie_pleine(e) -> bool:
    """Le refus de Discord au 51e salon d'une categorie (50035,
    CHANNEL_PARENT_MAX_CHANNELS)."""
    t = f"{getattr(e, 'text', '')} {e}".lower()
    return "maximum number of channels in category" in t or "channel_parent_max_channels" in t


async def categorie_perso(guilde, pleines=()):
    """Une categorie 📁 SALONS PERSO avec de la place, creee au besoin.
    Cachee a @everyone : chaque salon porte ses propres droits. `pleines` :
    les categories que Discord vient de dire pleines malgre le compte."""
    rec = _recents(guilde)
    par_id = {c.id: c for c in guilde.categories if est_categorie_perso(c)}
    for c in rec["cats"]:
        if est_categorie_perso(c):
            par_id.setdefault(c.id, c)
    cats = sorted(par_id.values(), key=lambda c: (_numero_perso(c), getattr(c, "position", 0)))
    for c in cats:
        if c.id in pleines:
            continue
        ids = {getattr(x, "id", None) for x in (getattr(c, "channels", None) or [])}
        if len(ids | rec["dans"].get(c.id, set())) < PLAFOND_CATEGORIE:
            return c
    n = max((_numero_perso(c) for c in cats), default=0) + 1
    nom = CATEGORIE_PERSO if n == 1 else f"{CATEGORIE_PERSO} {n}"
    cat = await guilde.create_category(
        nom, overwrites={guilde.default_role: discord.PermissionOverwrite(view_channel=False)},
        reason="Salons perso des VA (outils communs)")
    _retenir(guilde, "cat", cat)
    print(f"[outils-communs] {getattr(guilde, 'name', '?')} : categorie « {nom} » creee"
          + (f" ({len(cats)} pleine(s))" if cats else ""), flush=True)
    # Sous les outils, comme sur la maquette. Une fois, a la creation : un
    # rangement fait ensuite a la main n'est jamais defait.
    outils = discord.utils.find(est_categorie_outils, guilde.categories)
    if outils is not None and n == 1:
        try:
            await cat.move(after=outils, reason="Salons perso sous les outils")
        except Exception as e:                               # noqa: BLE001
            print(f"[outils-communs] « {nom} » non placee sous {CATEGORIE} : "
                  f"{type(e).__name__}: {e}", flush=True)
    return cat


async def _avec_place(guilde, faire):
    """(categorie, faire(categorie)) dans une 📁 SALONS PERSO avec de la place.
    Si Discord la dit pleine malgre le compte (un salon cree a la main, ou
    par l'autre bot, pas encore dans le cache) : une fois dans la suivante.
    Sans cette reprise, le VA restait sans -content jusqu'a un /ticketsall."""
    pleines = set()
    while True:
        cat = await categorie_perso(guilde, pleines)
        try:
            return cat, await faire(cat)
        except discord.HTTPException as e:
            if pleines or not _categorie_pleine(e):
                raise
            print(f"[outils-communs] « {cat.name} » pleine pour Discord malgre le "
                  "compte : la suivante", flush=True)
            pleines.add(cat.id)


def _nom_libre(guilde, membre) -> str:
    """<pseudo>-content, ou, s'il est deja pris (le salon d'un autre : « lea.m »
    et « leam » ont la meme base, un pseudo libere est repris),
    <pseudo>-<4 derniers chiffres de l'id>-content -- que content_de
    reconnait. Le dit au journal : le nom attendu n'est pas le sien."""
    from cogs.welcome import _us_ticket_name
    nom = _us_ticket_name(membre, "content")
    pris = {_norm(getattr(c, "name", "")) for c in
            list(getattr(guilde, "text_channels", None) or []) + _recents(guilde)["salons"]}
    if nom not in pris:
        return nom
    base = nom[: -len("-content")]
    uid = int(getattr(membre, "id", 0) or 0)
    for alt in (f"{base}-{uid % 10000}-content", f"{base}-{uid}-content"):
        if alt not in pris:
            print(f"[outils-communs] #{nom} existe et n'est pas a {getattr(membre, 'name', '?')} "
                  f"({uid}) : son salon perso sera #{alt}", flush=True)
            return alt
    raise RuntimeError(f"aucun nom libre pour le -content de {uid}")


async def ranger_content(salon) -> bool:
    """Place `salon` a son rang alphabetique dans sa categorie. UN
    deplacement, et seulement s'il n'y est pas : 50 salons a reordonner a
    chaque arrivee epuiseraient la limite d'API pour rien. Rend True s'il a
    bouge."""
    cat = getattr(salon, "category", None)
    if cat is None:
        return False
    # Le salon qu'on vient de creer n'est pas toujours deja dans le cache de
    # discord.py (il y entre par l'evenement de Discord, pas par la reponse
    # a la creation) : il est ajoute a la main, sinon il ne serait jamais range.
    par_id = {getattr(c, "id", None): c for c in (getattr(cat, "text_channels", None) or [])}
    par_id[getattr(salon, "id", None)] = salon
    freres = sorted(par_id.values(),
                    key=lambda c: (getattr(c, "position", 0), getattr(c, "id", 0)))
    alpha = sorted(freres, key=lambda c: (_norm(c.name), getattr(c, "id", 0)))
    i = alpha.index(salon)
    if i == 0:
        if freres[0] is salon:
            return False
        kw = {"beginning": True}
    else:
        avant = alpha[i - 1]
        if freres.index(salon) == freres.index(avant) + 1:
            return False
        kw = {"after": avant}
    try:
        await salon.move(reason="Salons perso ranges par pseudo", **kw)
        return True
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils-communs] #{getattr(salon, 'name', '?')} non range : "
              f"{type(e).__name__}: {e}", flush=True)
        return False


def _dans_salons_perso(guilde, salon) -> bool:
    """Le salon est-il deja dans une 📁 SALONS PERSO ? Sa categorie peut etre
    toute neuve, pas encore dans le cache (_recents) : sans ce repli, un
    -content cree une seconde plus tot etait « deplace » dans sa propre
    categorie, et perdait son rang."""
    cat = getattr(salon, "category", None)
    if cat is None:
        cid = getattr(salon, "category_id", None)
        cat = next((c for c in _recents(guilde)["cats"] if getattr(c, "id", None) == cid), None)
    return est_categorie_perso(cat)


async def salon_perso(guilde, membre, droits) -> tuple:
    """(salon, cree) : LE -content du membre, cree au besoin dans une
    categorie 📁 SALONS PERSO avec de la place, et range par pseudo.

    Un -content deja la (retour d'un VA, pseudo change) est garde ; s'il vit
    encore dans un ancien dossier, il rejoint les salons perso -- c'est ce
    que /ticketsall vient chercher. Un seul a la fois par serveur (_verrou) :
    deux arrivees dans la meme seconde creaient deux 📁 SALONS PERSO. Leve si
    Discord refuse la creation : l'appelant compte l'erreur."""
    async with _verrou(guilde):
        deja = content_de(guilde, membre)
        if deja is not None:
            if not _dans_salons_perso(guilde, deja):
                async def _deplacer(cat):
                    await deja.move(category=cat, end=True, sync_permissions=False,
                                    reason="Salon perso : rejoint les salons perso")
                cat, _ = await _avec_place(guilde, _deplacer)
                _retenir(guilde, "salon", deja, cat.id)
                print(f"[outils-communs] #{deja.name} range dans « {cat.name} »", flush=True)
                await asyncio.sleep(0.4)
                await ranger_content(deja)
            return deja, False
        nom = _nom_libre(guilde, membre)

        async def _creer(cat):
            return await guilde.create_text_channel(
                nom, category=cat, overwrites=droits,
                reason="Salon perso du VA (outils communs)")
        cat, salon = await _avec_place(guilde, _creer)
        _retenir(guilde, "salon", salon, cat.id)
        await ranger_content(salon)
        return salon, True


# ─────────────────────────────────────────── salon perso cree au clic ──
#
# Proprietaire, 30/10 : il clique « 📋 Ouvrir mon menu » et lit REFUS, puis
# « met ca aussi stp ». Le -content naissait a l'arrivee (create_us_tickets)
# ou par /ticketsall : ceux qui etaient la avant les outils communs (lui,
# Roucham) n'en avaient pas, et chacun des quatre outils les renvoyait. Un
# clic sans salon le cree donc, ici, une fois pour les quatre.

#: Les creations lancees par un clic, par (serveur, membre) : la tache en
#: cours. 📤 puis 📋 dans la meme seconde attendent la MEME creation au lieu
#: d'en empiler une seconde derriere le verrou ; le verrou de salon_perso
#: garde de toute facon un seul salon (une arrivee, /ticketsall).
_CREATIONS = {}


def _guilde_createur(guilde):
    """Le serveur tel que le voit le bot PRINCIPAL (Ryuk) ; `guilde` s'il n'y
    a pas de bot principal du tout (web_upload pas charge) ; None si Ryuk est
    connu mais ne voit pas (ou pas encore) ce serveur.

    create_us_tickets tourne sur Ryuk : guild.me (Ryuk) et le bot admin (Rem)
    recoivent chacun leur regle dans le -content (_us_droits_ticket). Cree
    depuis le 📱・numéro, que sert Rem, le salon n'aurait porte que celle de
    Rem : Ryuk n'y aurait rien livre, ni menu, ni spoofer, ni download.

    Pas de repli sur le bot du clic quand Ryuk ne voit pas le serveur : la
    reference de Ryuk existe des avant bot.start() (main.py), et get_guild
    rend None tant qu'il n'est pas pret, ou pendant une reconnexion, alors
    que Rem sert deja le 📱. Le salon naissait alors sans la regle de Ryuk,
    et ni salon_perso ni /ticketsall ne la reposent ensuite : chaque
    livraison de Ryuk y aurait echoue, ou Ryuk, aveugle, en aurait cree un
    second au meme nom."""
    try:
        from cogs.welcome import _bot_principal
        bot = _bot_principal()
    except Exception:                                        # noqa: BLE001
        bot = None
    if bot is None:
        return guilde
    try:
        vu = bot.get_guild(guilde.id)
    except Exception:                                        # noqa: BLE001
        vu = None
    # Un serveur « unavailable » (panne Discord, READY pas fini) n'a ni roles
    # ni membres : @everyone y est None, les droits seraient faux.
    if vu is None or getattr(vu, "unavailable", False):
        return None
    return vu


async def _creer_perso(guilde, membre):
    """Le -content de `membre`, cree comme a son arrivee (create_us_tickets) :
    memes droits, meme salon_perso, donc meme verrou. Rend le salon, ou None
    si Discord refuse, ou si le bot principal ne voit pas le serveur -- la
    cause au journal : le VA ne lit que REFUS, et son prochain clic
    reessaie (la tache finie quitte _CREATIONS)."""
    cg = _guilde_createur(guilde)
    uid = int(getattr(membre, "id", 0) or 0)
    qui = f"{getattr(membre, 'name', '?')} ({uid})"
    if cg is None:
        print(f"[outils-communs] {getattr(guilde, 'name', '?')} : -content de {qui} non cree "
              f"au clic : le bot principal ne voit pas ce serveur (pas encore pret, ou "
              f"deconnecte), rien n'est cree", flush=True)
        return None
    cm = (cg.get_member(uid) if cg is not guilde else None) or membre
    try:
        from cogs.welcome import _us_droits_ticket
        salon, cree = await salon_perso(cg, cm, _us_droits_ticket(cg, [cm], "content"))
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils-communs] {getattr(guilde, 'name', '?')} : -content de {qui} non cree "
              f"au clic : {type(e).__name__}: {e}", flush=True)
        return None
    if cree:
        print(f"[outils-communs] {getattr(guilde, 'name', '?')} : #{salon.name} cree au clic "
              f"de {qui} (sans salon perso jusque-la)", flush=True)
    return salon


def lancer_perso(guilde, membre):
    """Lance la creation du -content de `membre` SANS l'attendre ; rend sa
    tache, ou None si personne ne doit en avoir ici (un bot, un serveur sans
    outils communs).

    Pour un clic qui ouvre une FENETRE (📤, 👤) : elle doit etre la premiere
    reponse, dans les 3 s, et categorie + salon + rangement peuvent les
    depasser. La creation court pendant que le VA remplit la fenetre ; a la
    validation, content_de retrouve le salon (_recents) ou perso_ou_creer
    attend la fin. La tache tourne sur la boucle du clic : celle du bot."""
    if (guilde is None or membre is None or getattr(membre, "bot", False)
            or not serveur(guilde)):
        return None
    try:
        boucle = asyncio.get_running_loop()
    except RuntimeError:
        return None
    cle = (getattr(guilde, "id", 0), getattr(membre, "id", 0))
    t = _CREATIONS.get(cle)
    if t is not None and not t.done() and t.get_loop() is boucle:
        return t
    t = boucle.create_task(_creer_perso(guilde, membre), name=f"salon-perso-{cle[1]}")
    _CREATIONS[cle] = t     # aussi la reference forte : asyncio n'en garde qu'une faible

    def _finie(fin, cle=cle):
        if _CREATIONS.get(cle) is fin:
            _CREATIONS.pop(cle, None)
    t.add_done_callback(_finie)
    return t


def creation_en_cours(guilde, membre) -> bool:
    """Une creation lancee par un clic tourne-t-elle encore pour ce membre ?
    Une fenetre validee tres vite la trouve en cours : ce n'est pas un echec."""
    t = _CREATIONS.get((getattr(guilde, "id", 0), getattr(membre, "id", 0)))
    return t is not None and not t.done()


async def _vu_par(guilde, salon):
    """`salon` tel que le voit le bot de `guilde`. Cree par Ryuk, l'objet
    parle au nom de Ryuk : Rem y aurait pose la carte du numero sous le nom
    de Ryuk, et ses boutons, que Rem seul sert, seraient restes muets. Pas
    encore dans le cache de Rem (l'evenement de Discord suit) : relu."""
    if salon is None or getattr(salon, "guild", None) is guilde:
        return salon
    vu = guilde.get_channel(salon.id)
    if vu is not None:
        return vu
    try:
        return await guilde.fetch_channel(salon.id)
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils-communs] #{getattr(salon, 'name', '?')} cree mais illisible pour ce "
              f"bot : {type(e).__name__}: {e}", flush=True)
        return None


async def perso_ou_creer(guilde, membre):
    """Le -content de `membre` sur un serveur aux outils communs, CREE s'il
    n'en a pas -- ce que font les quatre outils d'un clic sans salon perso.

    A appeler une fois le clic acquitte (defer) ou dans une fenetre deja
    acquittee : la creation peut depasser les 3 s. Une creation deja lancee
    (lancer_perso) est attendue, jamais doublee ; si elle a echoue, un nouvel
    essai est fait (une fenetre rouverte apres un redemarrage n'a rien lance).

    Rend le salon tel que le voit le bot du clic ; None pour un bot, un
    serveur sans outils communs, ou si la creation echoue -- Discord la
    refuse, ou le bot principal ne voit pas le serveur (cause au journal) --
    l'appelant dit alors REFUS."""
    if not serveur(guilde):
        return None
    deja = content_de(guilde, membre)
    if deja is not None:
        return deja
    t = lancer_perso(guilde, membre)
    if t is None:
        return None
    # shield : un clic abandonne n'interrompt pas la creation que d'autres
    # clics du meme membre attendent peut-etre.
    return await _vu_par(guilde, await asyncio.shield(t))


# ──────────────────────────────────────────────────────── salons communs ──

def _role_verifie(guilde):
    """✅ Verifie si le serveur ferme ses salons aux non verifies (meme regle
    que les outils de Va IG, cogs/outils._droits)."""
    try:
        from cogs.outils import _role_verifie as rv
        return rv(guilde)
    except Exception:                                        # noqa: BLE001
        return None


def droits_outil(guilde, bots=()) -> dict:
    """Tout le monde voit et lit l'historique ; personne n'ecrit, ne reagit
    ni n'ouvre de fil : un salon commun ne porte que son panneau. Les
    boutons marchent sans le droit d'ecrire. Les bots de `bots` (Ryuk, et
    Rem pour le numero) y posent et redessinent leur panneau.

    Ni commande slash, ni application externe, ni activite : une commande
    n'a pas besoin du droit d'ecrire, sa reponse passe par l'interaction.
    Un /profilepic tape dans 📋・menu y postait trois photos de profil sous
    les yeux de tous les VA, et repoussait le bouton. Les boutons et les
    fenetres (FileUpload compris) ne dependent pas de ce droit."""
    voir = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=False,
        add_reactions=False, create_public_threads=False,
        create_private_threads=False, send_messages_in_threads=False,
        use_application_commands=False, use_external_apps=False,
        use_embedded_activities=False)
    verifie = _role_verifie(guilde)
    if verifie is not None:
        droits = {guilde.default_role: discord.PermissionOverwrite(view_channel=False),
                  verifie: voir}
    else:
        droits = {guilde.default_role: voir}
    for b in bots:
        if b is not None:
            droits[b] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_messages=True, embed_links=True, attach_files=True)
    return droits


def _ids(message) -> set:
    out, pile = set(), list(getattr(message, "components", None) or [])
    while pile:
        c = pile.pop()
        cid = getattr(c, "custom_id", None)
        if cid:
            out.add(cid)
        pile += list(getattr(c, "children", None) or [])
        pile += list(getattr(c, "components", None) or [])
    return out


class PanneauMenu(discord.ui.LayoutView):
    """Le panneau du salon 📋・menu : UN bouton, sans texte (le proprietaire
    deteste les notices). Persistant : custom_id fixe, timeout None, vue
    enregistree au demarrage (cogs/outils.Outils.cog_load)."""

    def __init__(self):
        super().__init__(timeout=None)
        b = discord.ui.Button(label="Ouvrir mon menu", emoji="📋",
                              style=discord.ButtonStyle.primary, custom_id=MENU_ID)
        b.callback = self._ouvrir
        self.add_item(discord.ui.ActionRow(b))

    async def _ouvrir(self, interaction):
        from cogs.user import ouvrir_menu_commun
        await ouvrir_menu_commun(interaction)


async def assurer_panneau_menu(canal, bot) -> int:
    """Le panneau du salon 📋・menu, pose UNE fois. Retrouve par son id garde
    dans data/, sinon en relisant le salon ; un doublon (deux demarrages
    rapproches) est retire. Discord injoignable : rien n'est reposte -- un
    second panneau vaut moins qu'un passage rate. Rend 1 si un panneau est pose."""
    moi = getattr(getattr(bot, "user", None), "id", None)
    gid = getattr(getattr(canal, "guild", None), "id", 0)
    mid = (_etat().get(str(gid)) or {}).get("menu")
    if mid:
        try:
            m = await canal.fetch_message(int(mid))
            if MENU_ID in _ids(m):
                return 0
        except discord.NotFound:
            pass
        except Exception as e:                               # noqa: BLE001
            print(f"[outils-communs] panneau du menu illisible ({type(e).__name__}: {e}) : "
                  "rien n'est reposte", flush=True)
            return 0
    try:
        poses = [m async for m in canal.history(limit=50)
                 if getattr(getattr(m, "author", None), "id", None) == moi and MENU_ID in _ids(m)]
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils-communs] #{getattr(canal, 'name', '?')} illisible ({type(e).__name__}: "
              f"{e}) : panneau non pose", flush=True)
        return 0
    if poses:
        garde = max(poses, key=lambda m: m.id)
        for m in poses:
            if m is not garde:
                try:
                    await m.delete()
                except Exception as e:                       # noqa: BLE001
                    print(f"[outils-communs] panneau du menu en double non retire : {e}", flush=True)
        _noter(gid, "menu", garde.id)
        return 0
    msg = await canal.send(view=PanneauMenu())
    _noter(gid, "menu", msg.id)
    return 1


def salon_outil(guilde, cle):
    """Le salon commun `cle` de ce serveur (par son id note, sinon par son nom
    dans 🧰 OUTILS), ou None -- aussi hors des serveurs aux outils communs."""
    if guilde is None or not serveur(guilde):
        return None
    return discord.utils.find(lambda c: est_salon_outil(c, cle),
                              getattr(guilde, "text_channels", None) or [])


def url_clics() -> str:
    """La page des clics et subs de YouCham : celle des liens de suivi, profil
    Lia (proprietaire, 31/10/2026 : « comme lui mais pour Lia ... la même
    exacte »), avec la cle des VA -- jamais celle du paiement."""
    import infloww_liens
    return infloww_liens.profil("lia").url_page()


def _urls(message) -> set:
    """Les adresses des boutons-liens d'un message (ils n'ont pas de custom_id)."""
    out, pile = set(), list(getattr(message, "components", None) or [])
    while pile:
        c = pile.pop()
        u = getattr(c, "url", None)
        if u:
            out.add(str(u))
        pile += list(getattr(c, "children", None) or [])
        pile += list(getattr(c, "components", None) or [])
    return out


class PanneauClics(discord.ui.LayoutView):
    """Le panneau du 📊・click-et-sub : l'image de la quinzaine en cours
    (liens_image), et dessous UN bouton-lien, sans texte, comme celui du
    menu. Proprietaire, 31/10/2026 : « une image de la quinzaine toujours »,
    « avec le lien colle ». Sans image (lecture ratee), le bouton seul. Un
    lien n'a pas de rappel : rien a enregistrer au demarrage."""

    def __init__(self, url, image=None, alt=""):
        super().__init__(timeout=None)
        if image:
            self.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(
                "attachment://" + image, description=(alt or image)[:1024])))
        self.add_item(discord.ui.ActionRow(discord.ui.Button(
            label="Statistiques", emoji="📊", style=discord.ButtonStyle.link, url=url)))


class PanneauArchive(discord.ui.LayoutView):
    """Une quinzaine FINIE, gardee dans le 📊・click-et-sub : son image seule,
    sans bouton ni texte (voir _tourner). Sans bouton-lien vers
    /infloww/liens, _assurer_clics ne la compte pas parmi ses panneaux : elle
    n'est jamais retiree."""

    def __init__(self, image, alt=""):
        super().__init__(timeout=None)
        self.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(
            "attachment://" + image, description=(alt or image)[:1024])))


#: Ce qui a deja ete dit, par (serveur, sujet) : un echec est dit une fois
#: par raison, pas toutes les heures ; une reussite l'efface.
_DITS = {}


def _dire(cle, raison, texte) -> None:
    if _DITS.get(cle) != raison:
        _DITS[cle] = raison
        print(texte, flush=True)


#: Les cles de l'etat propres au 📊・click-et-sub (voir ETAT).
DU_CLICS, ARCHIVE_CLICS = "click-et-sub-du", "click-et-sub-archive"

#: L'archive d'une quinzaine finie est redessinee a chaque heure jusqu'au
#: tour de midi du 1er ou du 16, heure de Paris : MyPuls rattrape des heures
#: durant des subs de la veille, et le podium fige lui aussi a midi. Le tour
#: de midi part a 12h00 et quelques secondes : il compte (marge de 15 min),
#: celui de 13h non.
FIN_RATTRAPAGE = (12, 15)

#: Un verrou par serveur pour le 📊・click-et-sub : sans lui, l'entretien du
#: demarrage et le tour de l'heure pile, lances ensemble au changement de
#: quinzaine, posaient chacun leur panneau neuf (tests_youcham_outils, 3b).
_VERROUS_CLICS = {}


def _verrou_clics(canal) -> asyncio.Lock:
    """Comme _verrou : un par boucle."""
    boucle = asyncio.get_running_loop()
    gid = getattr(getattr(canal, "guild", None), "id", 0)
    v = _VERROUS_CLICS.get(gid)
    if v is None or v[0] is not boucle:
        v = (boucle, asyncio.Lock())
        _VERROUS_CLICS[gid] = v
    return v[1]


def _maintenant():
    """L'heure de Paris : le VPS tourne en UTC."""
    import datetime
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("Europe/Paris"))


def _quinzaines_clics() -> dict:
    """La quinzaine en cours et la precedente, au jour de Paris de la page Lia
    (infloww_liens, profil « lia » : du 1er au 15, du 16 a la fin du mois),
    en ISO : {"du", "au" (aujourd'hui), "prec_du", "prec_au" (veille de du)}."""
    import datetime

    import infloww_liens
    m = infloww_liens.profil("lia")
    auj = datetime.date.fromisoformat(m._aujourdhui())
    du = m.quinzaine_de(auj)[0]
    veille = du - datetime.timedelta(days=1)
    return {"du": du.isoformat(), "au": auj.isoformat(),
            "prec_du": m.quinzaine_de(veille)[0].isoformat(), "prec_au": veille.isoformat()}


def _quinzaines_ou_rien(gid):
    """_quinzaines_clics, ou None -- et la raison est dite, une fois."""
    try:
        q = _quinzaines_clics()
    except Exception as e:                                   # noqa: BLE001
        raison = f"{type(e).__name__}: {e}"[:300]
        _dire((gid, "quinzaine"), raison, f"[outils-communs] quinzaine de la page Lia illisible "
              f"({raison}) : panneau des clics laisse tel quel")
        return None
    _DITS.pop((gid, "quinzaine"), None)
    return q


def _rattrapage_ouvert(au) -> bool:
    """L'archive de la quinzaine finie le jour `au` se redessine-t-elle
    encore ? Oui jusqu'au tour de midi du lendemain (FIN_RATTRAPAGE)."""
    import datetime
    from zoneinfo import ZoneInfo
    try:
        jour = datetime.date.fromisoformat(str(au)[:10]) + datetime.timedelta(days=1)
    except ValueError:
        return False
    fin = datetime.datetime.combine(jour, datetime.time(*FIN_RATTRAPAGE),
                                    tzinfo=ZoneInfo("Europe/Paris"))
    return _maintenant() < fin


async def image_clics(guilde, bot, du=None, au=None, terminee=False) -> dict:
    """{"png", "alt"} : l'image d'une quinzaine de la page Lia, aux chiffres
    de la page sur la meme periode et avec la photo Discord de chaque VA ; ou
    {"erreur"}. Par defaut la quinzaine en cours (du 1er ou du 16 a
    aujourd'hui) ; `du`, `au` imposes et `terminee` : une quinzaine finie,
    gardee dans le salon (_tourner). Ne leve pas."""
    try:
        import datetime

        import clics_image as _ci
        import infloww_liens
        import liens_image as li
        m = infloww_liens.profil("lia")
        if not du or not au:
            auj = datetime.date.fromisoformat(m._aujourdhui())
            du, au = du or m.quinzaine_de(auj)[0].isoformat(), au or auj.isoformat()

        def lire():
            # MyPuls attendu plus longtemps que par la page (5 s) : personne
            # n'attend devant un ecran, et un premier appel lent rendait
            # « MyPuls ne repond pas encore » a la place des chiffres
            m._mypuls_periode(du, au, attente=60)
            return m.tableau_periode(du, au, us="calcul")
        t = await asyncio.to_thread(lire)
        if t.get("erreur"):
            return {"erreur": str(t["erreur"])[:300]}
        h = _maintenant()
        # finie, l'image dit aussi le JOUR de ses chiffres : redessinee
        # jusqu'au lendemain midi, « 11h00 » seul ne disait pas lequel
        maj = (h.strftime("%d/%m") + " à " + h.strftime("%Hh%M")) if terminee else h.strftime("%Hh%M")
        v = li.tableau(t, du, au, maj, nom=m.NOM_AFFICHE, terminee=terminee)
        # la ligne porte le pseudo du lien de suivi (« @roucham_79944 ») : le
        # nom d'utilisateur Discord du VA, sa photo quand il est unique
        ids, _compte = _ci.resoudre_pseudos([x["nom"] for x in v["lignes"]],
                                            list(getattr(guilde, "members", None) or []))
        photos = {}
        if ids:
            from cogs.sessionsvoc import photos_avatars
            par_id, _c = await photos_avatars(bot, sorted(set(ids.values())), guilde=guilde,
                                              journal="click-et-sub")
            photos = {x["cle"]: par_id.get(ids[x["nom"]]) for x in v["lignes"]
                      if ids.get(x["nom"]) and par_id.get(ids[x["nom"]])}
        png = await asyncio.to_thread(li.dessiner, v, photos)
        return {"png": png, "alt": li.texte_alt(v)}
    except Exception as e:                                   # noqa: BLE001
        return {"erreur": f"{type(e).__name__}: {e}"[:300]}


async def _image(guilde, bot, quoi, **periode) -> dict:
    """image_clics ; son echec est dit (une fois par raison), {} rendu."""
    im = await image_clics(guilde, bot, **periode)
    cle = (getattr(guilde, "id", 0), quoi)
    if im.get("png"):
        _DITS.pop(cle, None)
        return im
    _dire(cle, im.get("erreur"), f"[outils-communs] image {quoi} impossible : {im.get('erreur')}")
    return {}


async def _vue_clics(guilde, bot, url, du=None, au=None):
    """(vue, fichiers) du panneau vivant, avec l'image ; (None, []) si elle
    ne se fait pas."""
    import io

    import liens_image as li
    im = await _image(guilde, bot, "de la quinzaine", **({"du": du, "au": au} if du else {}))
    if not im:
        return None, []
    return (PanneauClics(url, li.NOM, im.get("alt", "")),
            [discord.File(io.BytesIO(im["png"]), filename=li.NOM)])


async def _vue_archive(guilde, bot, du, au):
    """(vue, fichiers) de l'archive d'une quinzaine finie : l'image seule, a
    son nom (liens_image.nom_archive) ; (None, []) si elle ne se fait pas."""
    import io

    import liens_image as li
    im = await _image(guilde, bot, "de la quinzaine terminee", du=du, au=au, terminee=True)
    if not im:
        return None, []
    nom = li.nom_archive(du, au)
    return (PanneauArchive(nom, im.get("alt", "")),
            [discord.File(io.BytesIO(im["png"]), filename=nom)])


def _porte_fichier(message, nom) -> bool:
    """Le message porte-t-il l'image `nom` ? Un message Components V2 ne liste
    PAS ses fichiers dans `attachments` (vide, relu le 31/10) : l'image est
    dans la galerie, son adresse finit par le nom du fichier."""
    if any(getattr(a, "filename", None) == nom for a in (getattr(message, "attachments", None) or [])):
        return True
    pile = list(getattr(message, "components", None) or [])
    while pile:
        c = pile.pop()
        for it in getattr(c, "items", None) or []:
            u = str(getattr(getattr(it, "media", None), "url", "") or "")
            if u.split("?", 1)[0].endswith("/" + nom) or u == "attachment://" + nom:
                return True
        pile += list(getattr(c, "children", None) or [])
        pile += list(getattr(c, "components", None) or [])
    return False


def _porte_image(message) -> bool:
    """Le panneau a-t-il son image ? Sans ce test, chaque entretien la
    redessinait pour rien."""
    import liens_image as li
    return _porte_fichier(message, li.NOM)


def _vivant(message) -> bool:
    """Un panneau vivant porte le bouton vers la page ; une archive, non."""
    return any("/infloww/liens" in u for u in _urls(message))


async def _assurer_clics(canal, bot) -> int:
    """Le panneau du 📊・click-et-sub : un seul message du bot avec le bouton,
    vers l'adresse du jour, avec l'image de la quinzaine. L'adresse changee
    (cle, acces libre), l'ancien bouton menerait a « Lien invalide » : il est
    remplace. Un panneau sans image (d'avant, ou lecture ratee) la recoit ;
    un panneau d'une autre quinzaine, ou dont la quinzaine n'est pas notee,
    devient son archive (_tourner) ; plus de panneau du tout alors que sa
    quinzaine est finie, l'archive est postee avant le neuf (_garder_finie).
    Les archives n'ont pas de bouton : jamais comptees ici, jamais retirees.
    Rend 1 si un panneau est pose ici (celui d'un changement de quinzaine
    est dit par _tourner)."""
    async with _verrou_clics(canal):
        moi = getattr(getattr(bot, "user", None), "id", None)
        url = url_clics()
        poses = [m async for m in canal.history(limit=25)
                 if getattr(getattr(m, "author", None), "id", None) == moi and _vivant(m)]
        bons = [m for m in poses if url in _urls(m)]
        garde = max(bons, key=lambda m: m.id) if bons else None
        for m in poses:
            if m is not garde:
                try:
                    await m.delete()
                except Exception as e:                       # noqa: BLE001
                    print(f"[outils-communs] ancien panneau des clics non retire : {e}", flush=True)
        gid = getattr(getattr(canal, "guild", None), "id", 0)
        if garde is not None:
            _noter(gid, "click-et-sub", garde.id)
            q = _quinzaines_ou_rien(gid)
            du_note = (_etat().get(str(gid)) or {}).get(DU_CLICS)
            if not _porte_image(garde) or (q is not None and du_note != q["du"]):
                await _maj_clics(canal, bot, garde, q)
            return 0
        q = _quinzaines_ou_rien(gid)
        g = _etat().get(str(gid)) or {}
        du_note = g.get(DU_CLICS)
        # Plus de panneau vivant alors que sa quinzaine est finie : retire a la
        # main le 31/10, ou a l'instant ci-dessus (cle changee). A 00h le 01/11,
        # maj_clics ne le relisait plus et laissait faire l'entretien, qui
        # posait un neuf sur le 01/11 et notait la quinzaine : celle du 16 au
        # 31/10 n'etait plus nulle part, sans une ligne au journal --
        # proprietaire, 01/11/2026 : « garde une trace de la période d'avant,
        # toujours ». Aucune quinzaine notee, mais un panneau d'avant ce
        # correctif retire ci-dessus (cle changee) : comme dans _maj_clics,
        # la finie est gardee. Un salon neuf (rien de note, rien de retire)
        # n'a pas d'archive : personne n'a vu cette quinzaine-la.
        gardee = True
        if q is not None and du_note != q["du"] and (du_note or poses):
            gardee = await _garder_finie(canal, bot, g, q)
        vue, fichiers = ((await _vue_clics(canal.guild, bot, url, q["du"], q["au"]))
                         if q is not None else (None, []))
        msg = await canal.send(view=vue or PanneauClics(url), files=fichiers)
        # pose maintenant, il est de la quinzaine en cours, image ou pas : sa
        # quinzaine est notee -- sauf si la finie n'a pas pu etre gardee :
        # l'ancienne reste notee, et au tour suivant _maj_clics fait de CE
        # panneau l'archive de la finie (_tourner, image redessinee sur elle)
        _noter_valeurs(gid, {"click-et-sub": msg.id, **({DU_CLICS: q["du"]} if q and gardee else {})})
        return 1


async def _garder_finie(canal, bot, g, q) -> bool:
    """Le panneau vivant a disparu avant d'avoir ete tourne : l'archive de la
    quinzaine finie est postee seule (PanneauArchive), avant le panneau neuf
    -- elle reste au-dessus, comme apres _tourner. Rend True si la finie est
    gardee (deja, ou maintenant). False : rien de note, la cause est dite
    une fois ; l'appelant garde la quinzaine d'avant notee pour que _tourner
    reessaie au tour suivant. Ne leve pas."""
    gid = getattr(getattr(canal, "guild", None), "id", 0)
    deja = await _archive_presente(canal, bot, g, q)
    if deja:
        return True
    if deja is None:
        return False            # salon illisible : dit par _archive_presente
    cle, quinz = (gid, "garder"), f"quinzaine du {q['prec_du']} au {q['prec_au']}"
    vue_a, f_a = await _vue_archive(canal.guild, bot, q["prec_du"], q["prec_au"])
    if vue_a is None:
        _dire(cle, "image", f"[outils-communs] {quinz} pas encore gardee (panneau vivant disparu, "
              "image impossible) : elle le sera au tour suivant, sur le panneau neuf")
        return False
    try:
        arch = await canal.send(view=vue_a, files=f_a)
    except Exception as e:                                   # noqa: BLE001
        raison = f"{type(e).__name__}: {e}"[:200]
        _dire(cle, "envoi " + raison, f"[outils-communs] {quinz} pas encore gardee (archive refusee : "
              f"{raison}) : elle le sera au tour suivant, sur le panneau neuf")
        return False
    _DITS.pop(cle, None)
    # notee tout de suite : le panneau neuf refuse ensuite, elle n'est ni
    # perdue (relue a son nom, _archive_presente) ni postee deux fois
    _noter_valeurs(gid, {ARCHIVE_CLICS: {"id": int(arch.id), "du": q["prec_du"], "au": q["prec_au"]}})
    print(f"[outils-communs] {quinz} gardee dans le salon (message {arch.id}) : le panneau vivant "
          "avait disparu avant le changement de quinzaine", flush=True)
    return True


async def maj_clics(canal, bot, message=None) -> bool:
    """L'image du panneau redessinee aux chiffres du moment (cogs/outils, a
    chaque heure pile) ; la quinzaine changee, le panneau devient l'archive
    de la finie et un neuf est pose (_tourner). Lecture ratee : l'image
    d'avant reste, plutot qu'un bouton seul. Rend True si un message a
    change."""
    async with _verrou_clics(canal):
        return await _maj_clics(canal, bot, message)


async def _maj_clics(canal, bot, message=None, q=None) -> bool:
    """maj_clics, verrou deja pris (_assurer_clics l'appelle aussi)."""
    gid = getattr(getattr(canal, "guild", None), "id", 0)
    if message is None:
        mid = (_etat().get(str(gid)) or {}).get("click-et-sub")
        if not mid:
            return False
        try:
            message = await canal.fetch_message(int(mid))
        except Exception as e:                               # noqa: BLE001
            print(f"[outils-communs] panneau des clics illisible ({type(e).__name__}) : "
                  "l'entretien le reposera", flush=True)
            return False
    if not _vivant(message):
        # le message note n'a pas de bouton : c'est une archive (etat ecrit a
        # moitie, ou relu d'ailleurs). La « tourner » encore poserait un
        # second panneau vivant ; l'entretien retrouve le vrai (_assurer_clics).
        _dire((gid, "vivant"), message.id, f"[outils-communs] le message {message.id} note comme "
              "panneau des clics n'a pas de bouton : laisse tel quel, l'entretien retrouvera le panneau")
        return False
    _DITS.pop((gid, "vivant"), None)
    q = q or _quinzaines_ou_rien(gid)
    if q is None:
        return False
    g = _etat().get(str(gid)) or {}
    change = await _maj_archive(canal, bot, g.get(ARCHIVE_CLICS))
    du_note = g.get(DU_CLICS)
    if du_note != q["du"]:
        # Une autre quinzaine, ou aucune de notee : le premier passage apres
        # le 01/11/2026, quand le panneau montrait deja « 01/11 → 01/11 » et
        # que la quinzaine du 16 au 31/10 n'etait plus nulle part. La finie
        # est gardee -- sauf si elle l'est deja (data/ reparti de zero, etat
        # ecrit a moitie) : une seconde archive serait du bruit.
        deja = await _archive_presente(canal, bot, g, q)
        if deja is None:
            return change
        if not deja:
            return await _tourner(canal, bot, message, q) or change
    vue, fichiers = await _vue_clics(canal.guild, bot, url_clics(), q["du"], q["au"])
    if vue is None:
        return change
    await message.edit(view=vue, attachments=fichiers)
    if du_note != q["du"]:
        _noter_valeurs(gid, {DU_CLICS: q["du"]})
    return True


async def _archive_presente(canal, bot, g, q):
    """La quinzaine precedente est-elle deja gardee : notee, ou relue dans le
    salon a son nom d'image (liens_image.nom_archive) ? None si le salon ne
    se lit pas -- rien ne tourne alors a l'aveugle, nouvel essai au tour
    suivant."""
    import liens_image as li
    a = g.get(ARCHIVE_CLICS)
    if isinstance(a, dict) and a.get("du") == q["prec_du"] and a.get("au") == q["prec_au"]:
        return True
    nom = li.nom_archive(q["prec_du"], q["prec_au"])
    moi = getattr(getattr(bot, "user", None), "id", None)
    gid = getattr(getattr(canal, "guild", None), "id", 0)
    try:
        async for m in canal.history(limit=25):
            if getattr(getattr(m, "author", None), "id", None) == moi and _porte_fichier(m, nom):
                return True
    except Exception as e:                                   # noqa: BLE001
        raison = f"{type(e).__name__}: {e}"[:200]
        _dire((gid, "salon"), raison, f"[outils-communs] #{getattr(canal, 'name', '?')} illisible "
              f"({raison}) : la quinzaine finie sera gardee au tour suivant")
        return None
    _DITS.pop((gid, "salon"), None)
    return False


async def _tourner(canal, bot, message, q) -> bool:
    """La quinzaine a change : le panneau vivant devient l'archive de la
    finie (son image redessinee du debut de la precedente a la veille de
    l'actuelle, « quinzaine terminée », sans bouton : PanneauArchive), et un
    panneau neuf est pose dessous, sur la quinzaine en cours.

    POURQUOI (proprietaire, 01/11/2026, devant le salon reparti a zero, « 01/11
    → 01/11 · quinzaine en cours ») : « ça doit faire un repost ... comment ils
    font pour voir combien de subs ils ont fait pour la période d'avant sans
    cliquer ; garde une trace de la période d'avant, toujours ». Le meme
    message, redessine chaque heure, passait du 31/10 au 01/11 sans rien
    garder ; et _assurer_clics retire tout panneau du bot qui porte le lien
    sauf le plus recent : l'archive n'a donc pas de bouton.

    Rien ne se perd. Les deux images d'abord : l'une ratee, rien n'est
    touche. Le neuf ensuite : refuse, l'ancien reste tel quel. L'ancien
    devient l'archive en dernier : refuse, le neuf est retire -- jamais deux
    panneaux vivants. La quinzaine n'est notee qu'apres : un echec est
    retente au tour suivant. Rend True si le salon a change."""
    gid = getattr(getattr(canal, "guild", None), "id", 0)
    vue_a, f_a = await _vue_archive(canal.guild, bot, q["prec_du"], q["prec_au"])
    if vue_a is None:
        return False
    vue, fichiers = await _vue_clics(canal.guild, bot, url_clics(), q["du"], q["au"])
    if vue is None:
        return False
    cle, quinz = (gid, "tourner"), f"quinzaine du {q['prec_du']} au {q['prec_au']}"
    try:
        neuf = await canal.send(view=vue, files=fichiers)
    except Exception as e:                                   # noqa: BLE001
        raison = f"{type(e).__name__}: {e}"[:200]
        _dire(cle, "envoi " + raison, f"[outils-communs] {quinz} : panneau neuf refuse ({raison}) ; "
              "l'ancien reste tel quel, nouvel essai au tour suivant")
        return False
    try:
        await message.edit(view=vue_a, attachments=f_a)
    except Exception as e:                                   # noqa: BLE001
        raison = f"{type(e).__name__}: {e}"[:200]
        _dire(cle, "archive " + raison, f"[outils-communs] {quinz} : ancien panneau non archive "
              f"({raison}) ; le neuf est retire, nouvel essai au tour suivant")
        try:
            await neuf.delete()
        except Exception as e2:                              # noqa: BLE001
            print(f"[outils-communs] DEUX panneaux des clics : le neuf ({neuf.id}) n'a pas pu etre "
                  f"retire ({type(e2).__name__}: {e2})", flush=True)
        return False
    _DITS.pop(cle, None)
    _noter_valeurs(gid, {"click-et-sub": int(neuf.id), DU_CLICS: q["du"],
                         ARCHIVE_CLICS: {"id": int(message.id), "du": q["prec_du"], "au": q["prec_au"]}})
    print(f"[outils-communs] {quinz} gardee dans le salon (message {message.id}) ; panneau de la "
          f"quinzaine en cours pose ({neuf.id})", flush=True)
    return True


async def _maj_archive(canal, bot, a) -> bool:
    """L'archive de la derniere quinzaine finie, redessinee jusqu'au tour de
    midi du 1er ou du 16 (FIN_RATTRAPAGE) ; ensuite plus jamais. Rend True si
    elle a change."""
    if not isinstance(a, dict) or not a.get("id") or not a.get("du") or not a.get("au"):
        return False
    if not _rattrapage_ouvert(a["au"]):
        return False
    gid = getattr(getattr(canal, "guild", None), "id", 0)
    cle = (gid, "archive")
    try:
        m = await canal.fetch_message(int(a["id"]))
        vue, fichiers = await _vue_archive(canal.guild, bot, a["du"], a["au"])
        if vue is None:
            return False
        await m.edit(view=vue, attachments=fichiers)
    except Exception as e:                                   # noqa: BLE001
        raison = f"{type(e).__name__}: {e}"[:200]
        _dire(cle, raison, f"[outils-communs] archive de la quinzaine du {a['du']} au {a['au']} "
              f"non redessinee ({raison})")
        return False
    _DITS.pop(cle, None)
    return True


async def _assurer_download(canal, bot) -> int:
    """Le panneau du ⬇️・download : un seul message du bot, a jour ; sinon le
    salon est remis au propre (cogs/telechargement.poser_panneaux)."""
    cog = bot.get_cog("Telechargement")
    if cog is None:
        print("[outils-communs] cog Telechargement absent : panneau du download non pose", flush=True)
        return 0
    from cogs import telechargement as tl
    moi = getattr(getattr(bot, "user", None), "id", 0)
    du_bot = [m async for m in canal.history(limit=25) if m.author.id == moi]
    if len(du_bot) == 1 and tl.panneau_a_jour(du_bot[0], moi):
        return 0
    return await tl.poser_panneaux(cog, canal)


async def assurer(guilde, bot) -> dict:
    """🧰 OUTILS, ses salons (salons_de : quatre outils, plus le click-et-sub
    sur YouCham) et les panneaux de Ryuk (menu, spoofer, download,
    click-et-sub). Idempotent : ce qui existe n'est ni recree ni reposte. Le
    panneau du numero est pose par Rem (cogs/numeros, _panneau_commun) : un
    bouton n'est servi que par l'application qui a poste le message.
    Rend un bilan ; chaque echec y est compte, aucun n'est tu."""
    bilan = {"crees": [], "panneaux": [], "rates": []}
    if not serveur(guilde):
        return bilan
    moi = getattr(guilde, "me", None)
    try:
        from cogs.welcome import _membre_bot_admin
        rem = _membre_bot_admin(guilde)
    except Exception:                                        # noqa: BLE001
        rem = None
    # est_categorie_outils lit l'id note avant le nom : renommee (« 🧰 TOOLS
    # »), la categorie n'etait plus trouvee au seul nom, et une seconde
    # 🧰 OUTILS naissait avec quatre nouveaux salons et leurs panneaux.
    _id_cat, par_id = _ids_notes(guilde)
    cat = discord.utils.find(est_categorie_outils, guilde.categories)
    if cat is None:
        cat = await guilde.create_category(CATEGORIE, overwrites=droits_outil(guilde, (moi, rem)),
                                           reason="Outils communs des VA")
        bilan["crees"].append(cat.name)
        # En tete du serveur, comme sur la maquette : une fois, a la creation.
        try:
            await cat.move(beginning=True, reason="Outils communs en tete")
        except Exception as e:                               # noqa: BLE001
            bilan["rates"].append(f"{CATEGORIE} non placee en tete ({type(e).__name__})")
    salons = {}
    id_de = {k: i for i, k in par_id.items()}
    for cle, nom in salons_de(guilde):
        # Renomme ou sorti de 🧰 OUTILS, un salon reste le sien par son id.
        canal = (discord.utils.get(guilde.text_channels, id=id_de[cle])
                 if cle in id_de else None)
        if canal is None:
            canal = discord.utils.find(lambda c, k=cle: _cle(c.name) == k,
                                       getattr(cat, "text_channels", None) or [])
        if canal is None:
            bots = (moi, rem) if cle == "numero" else (moi,)
            if cle == "numero" and rem is None:
                # Rem est administrateur de YouCham : il y ecrit quand meme.
                # Sans ce droit nomme, un Rem retrogade ne pourrait plus
                # poser le panneau -- on le dit au lieu de le decouvrir.
                bilan["rates"].append("Rem introuvable : 📱・numéro cree sans regle a son nom")
            try:
                canal = await guilde.create_text_channel(
                    nom, category=cat, overwrites=droits_outil(guilde, bots),
                    reason="Outils communs des VA")
                bilan["crees"].append(canal.name)
            except Exception as e:                           # noqa: BLE001
                bilan["rates"].append(f"{nom} non cree ({type(e).__name__}: {e})"[:200])
                continue
            await asyncio.sleep(1.0)
        salons[cle] = canal
    _noter_salons(guilde.id, cat.id, {k: c.id for k, c in salons.items()})
    # Les photos des models (menu des models), des reserves (✨ General) et
    # les icones des boutons : le menu ephemere les LIT au clic, sans le temps
    # d'en creer. Sans -menu sur ce serveur, rien d'autre ne les poserait
    # (Va IG n'en avait aucun le 03/10, cogs/outils._entretien). Sur
    # l'application du bot, elles existent deja le plus souvent : relu, rien
    # de cree.
    try:
        from cogs.user import (_jb_models_marche, ensure_action_emojis,
                               ensure_identity_emojis, ensure_reserve_emojis)
        models = list(dict.fromkeys(list(_jb_models_marche("us")) + list(_jb_models_marche("fr"))))
        await ensure_identity_emojis(guilde, models)
        await ensure_reserve_emojis(guilde)
        await ensure_action_emojis(guilde)
    except Exception as e:                                   # noqa: BLE001
        bilan["rates"].append(f"emojis des menus ({type(e).__name__}: {e})"[:200])
    for cle, poser in (("menu", lambda c: assurer_panneau_menu(c, bot)),
                       ("spoofer", lambda c: _assurer_spoofer(c, bot)),
                       ("download", lambda c: _assurer_download(c, bot)),
                       ("click-et-sub", lambda c: _assurer_clics(c, bot))):
        canal = salons.get(cle)
        if canal is None:
            continue
        try:
            if await poser(canal):
                bilan["panneaux"].append(cle)
        except Exception as e:                               # noqa: BLE001
            bilan["rates"].append(f"panneau {cle} ({type(e).__name__}: {e})"[:200])
    if bilan["crees"] or bilan["panneaux"] or bilan["rates"]:
        print(f"[outils-communs] {getattr(guilde, 'name', '?')} : crees {bilan['crees']}, "
              f"panneaux poses {bilan['panneaux']}, echecs {bilan['rates']}", flush=True)
    return bilan


async def _assurer_spoofer(canal, bot) -> int:
    cog = bot.get_cog("Spoofer")
    if cog is None:
        print("[outils-communs] cog Spoofer absent : panneau du spoofer non pose", flush=True)
        return 0
    return await cog.assurer_panneau(canal)
