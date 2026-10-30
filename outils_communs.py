# -*- coding: utf-8 -*-
"""Les outils COMMUNS d'un serveur US : quatre salons pour tous, un salon perso par VA.

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
                      (cogs/numeros.py, boucle _panneau_commun)
    📁 SALONS PERSO, puis 📁 SALONS PERSO 2, 3... : Discord refuse un 51e
    salon dans une categorie. Un salon par VA, « <pseudo>-content » -- le
    nom de cogs/welcome._us_ticket_name, que toutes les recherches de -content
    connaissent deja --, prive : le VA, le staff, Ryuk et Rem (Rem y ecrit la
    carte du numero). Range par pseudo dans sa categorie.

LA REGLE DE LIVRAISON
    Un clic dans un salon commun livre dans le -content DU CLIQUEUR
    (content_de), jamais dans le salon commun : tout le monde y verrait ses
    fichiers. Quelqu'un sans -content (le staff) recoit un refus court, en
    ephemere (REFUS). Seuls les refus et les confirmations courtes sont
    ephemeres ; ce qui est livre vit dans le -content, qui survit a un
    rechargement de Discord.

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
          ("download", "⬇️・download"), ("numero", "📱・numéro"))
CLES = tuple(c for c, _n in SALONS)

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
#: "salons": {cle: id du salon}}}. Le message du menu : sans lui, chaque
#: passage relisait l'historique. Les ids des salons : voir « RECONNAITRE ».
ETAT = Path(__file__).resolve().parent / "data" / "outils_communs.json"

#: Le refus, le meme pour les quatre outils. Court, sans notice.
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
        if cle not in CLES:
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
    """🧰 OUTILS, ses quatre salons et les panneaux de Ryuk (menu, spoofer,
    download). Idempotent : ce qui existe n'est ni recree ni reposte. Le
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
    for cle, nom in SALONS:
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
                       ("download", lambda c: _assurer_download(c, bot))):
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
