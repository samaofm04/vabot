# -*- coding: utf-8 -*-
"""Le salon admin « bases-identites » du serveur US : une base GetMySocial par identite.

POURQUOI (proprietaire, 06/10/2026)
    « Avoir une base et juste changer les PP et la photo c'est tout. » Il
    poste le nom d'une identite US et deux photos ; le bot cree la page
    « TEMPLATE <identite> » dans GetMySocial (bases_identite_us.py) et
    repond son adresse, seule, pour qu'elle se copie d'un appui long.

LE PANNEAU (proprietaire, 06/10/2026)
    « Ici ça peut me proposer les identités où il manque un lien ou si c'est
    pour modifier le lien template. » Un message du bot, pose et tenu a jour
    par l'entretien, JAMAIS epingle, sans un mot de notice :

        ## 🧱 3/18                      pages faites / identites US
        [🧱 Choisis une identité…  ▾]  ➖ d'abord (sans page), puis ✅

    Choisir une identite (admin seulement) ouvre une fenetre a son nom :
    « Photo de profil » et « Fond » (un fichier chacun), « Nom affiché »
    (facultatif, pre-rempli avec le nom de la page existante, meme faite a
    la main ; laisse vide, la page garde ce nom). A la soumission : l'adresse
    SEULE dans le salon, le panneau rafraichi ; une erreur, en ephemere
    (l'admin la voit, le salon reste une colonne d'adresses) -- sauf celle
    qui laisse quelque chose a faire dans GetMySocial (une ancienne page pas
    coupee), qui reste dans le salon comme par message. Un seul panneau :
    reedite quand il change, jamais reposte s'il est a jour.

CE QUE LE SALON ATTEND AUSSI (un message d'administrateur)
    @Yoshi ibenhaastrup      1re ligne : l'identite
    Iben ♡                   2e ligne, facultative : le nom affiche sur la page
    + 2 photos               la 1re = photo de profil, la 2e = fond
    @Yoshi liste             les identites US : ✅ base faite, ➖ pas encore

    Reponse : ⏳ sur son message, puis ✅ et l'adresse seule, ou ❌ et la
    raison en une ligne. Aucun texte d'explication dans le salon, aucun
    message epingle : le proprietaire n'en veut pas.

POURQUOI IL FAUT MENTIONNER LE BOT
    Yoshi n'a pas l'intention « Message Content » : la demander dans le code
    sans la cocher dans le portail Discord empeche le bot de se connecter du
    tout (main.py, PrivilegedIntentsRequired). Sans elle, Discord livre les
    messages SANS texte ni pieces jointes -- sauf ceux qui mentionnent le
    bot. Un message vide est donc relu une fois par l'API (utile le jour ou
    l'intention sera cochee dans le portail) ; s'il l'est toujours, le bot le
    dit au lieu de se taire.

APPELS GETMYSOCIAL
    L'entretien (toutes les ENTRETIEN_HEURES, et au demarrage) lit la liste
    de l'equipe -- le cache de 15 min de gms, partage avec le generateur de
    liens des VA ; un appel par page de 100 liens quand il est froid -- pour
    le compteur et les noms affiches, et range les pages de base dans le
    groupe TEMPLATES (bases_identite_us.ranger_templates : aucun appel si
    tout est en place). Tout cela au rang « fond » du budget du jour
    (bases_identite_us.ETIQUETTE_FOND) : quand la quota baisse, ce rangement
    cosmetique s'efface avant le podium et la paie. Une creation (rang
    normal : l'admin attend) met le panneau a jour SANS relire la liste.

REDEMARRAGE EN PLEINE CREATION
    Le cron redemarre le bot a chaque push. Par message : le ⏳ reste, il
    devient ❌ au demarrage. Par la fenetre : une trace sur disque
    (bases_identite_us.EN_COURS), reprise au demarrage par la meme ligne
    dans le salon.

CE QUI N'EST PAS ICI
    Aucune commande slash : le bot principal en a 100 sur 100, une de plus
    fait echouer la synchronisation de tout l'arbre.
"""
from __future__ import annotations

import asyncio
import functools
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands, tasks

import bases_identite_us as bases
import safe_json

SALON_DEFAUT = "bases-identites"
#: Mentions d'utilisateur ou de role : le role gere du bot sort aussi de
#: l'autocompletion « @Yoshi ».
_MENTION = re.compile(r"<@[!&]?\d+>")
IMAGES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".bmp", ".tif", ".tiff"})
LIMITE_MESSAGE = 2000

#: Prefixe de TOUS les custom_id du panneau. discord.py lance tous les motifs
#: dynamiques qui correspondent a un custom_id : celui-ci ne recoupe aucun
#: des existants (jbus: jbg: jbmenu cmenu: genlink: spf: numgen: lien:
#: essai: usdc: gdl: copie: dl: sessions: annonce_…), verifie par
#: tests_bases_identite.
PREFIXE = "bid:"
CID_MENU = "bid:m:{n}"                       # menu n° n du panneau
CID_FENETRE = "bid:f:{ident}:{alea}"         # fenetre de l'identite
CID_PP, CID_FOND, CID_NOM = "bid:pp", "bid:fond", "bid:nom"
#: Plafonds Discord : options par menu, rangees par message, custom_id,
#: libelle d'option, titre de fenetre.
TAILLE_MENU = 25
MAX_MENUS = 5
CUSTOM_ID_MAX = 100
LIBELLE_MAX = 100
TITRE_MAX = 45
#: Ce qu'une identite doit etre pour servir de valeur d'option ET tenir dans
#: le custom_id de sa fenetre (« bid:f:<identite>:<8 signes> », 100 au plus) :
#: une fenetre validee apres un redemarrage se reconstruit avec.
_NOM_IDENT = re.compile(r"[A-Za-z0-9_.\-]{1,80}")
INTITULE = "🧱 Choisis une identité…"
INTITULE_VIDE = "🧱 Aucune identité US"
FAITE, A_FAIRE = " ✅", " ➖"

#: L'entretien : salon, panneau, rangement du groupe TEMPLATES. La liste de
#: l'equipe qu'il lit est le cache de gms (un appel au plus par passage).
ENTRETIEN_HEURES = 6
#: GetMySocial muet a un passage : on repasse plus tot.
REESSAI_MINUTES = 60


# ───────────────────────────────────────────────────────────── le salon ──

def _norm(nom) -> str:
    """LA cle des salons du serveur US (welcome.nom_sans_decor) : le
    proprietaire decore les noms a la main (« 🧱・bases-identites »).
    nom_sans_decor ne retire que la decoration DE TETE et garde les accents :
    « bases-identités » ou « bases-identites-🧱 » rendaient le salon sourd,
    puis l'entretien en creait un second au redemarrage."""
    try:
        from cogs.welcome import nom_sans_decor
        n = nom_sans_decor(nom)
    except Exception:                                        # noqa: BLE001
        n = str(nom or "").strip().lower()
    n = "".join(c for c in unicodedata.normalize("NFKD", n) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+$", "", n)


def nom_salon() -> str:
    try:
        return bases.config().get("salon") or SALON_DEFAUT
    except Exception:                                        # noqa: BLE001
        return SALON_DEFAUT


def est_salon_bases(canal) -> bool:
    nom = getattr(canal, "name", "") or ""
    return bool(nom) and _norm(nom) == _norm(nom_salon())


def _serveur_us(guilde) -> bool:
    try:
        import guild_features as gf
        return gf.is_us_guild(guilde)
    except Exception:                                        # noqa: BLE001
        return False


def _est_admin(membre) -> bool:
    perms = getattr(membre, "guild_permissions", None)
    return bool(perms is not None and getattr(perms, "administrator", False))


#: Ce dont le bot a besoin dans le salon.
DROITS_BOT = dict(view_channel=True, send_messages=True, read_message_history=True,
                  add_reactions=True, embed_links=True, attach_files=True)
#: Sans l'un d'eux, le salon est sourd ou muet pour le bot.
DROITS_VITAUX = ("view_channel", "send_messages", "add_reactions", "read_message_history")


def droits_salon(guilde) -> Dict[Any, discord.PermissionOverwrite]:
    """Personne ne le voit, sauf le bot ; les administrateurs voient tout
    salon quoi qu'il arrive."""
    droits = {guilde.default_role: discord.PermissionOverwrite(view_channel=False)}
    moi = getattr(guilde, "me", None)
    if moi is not None:
        droits[moi] = discord.PermissionOverwrite(**DROITS_BOT)
    return droits


def _esc(texte) -> str:
    """Les noms tels quels a l'ecran : deux identites a « __ » soulignaient
    tout ce qui les separait, et « nanas__nyspam » se lisait « nanasnyspam »."""
    return discord.utils.escape_markdown(str(texte or ""))


# ─────────────────────────────────────────────────────────── identites ──

def identites_us() -> List[str]:
    """Les identites US, EXACTEMENT celles du menu US (cogs/user) : deux
    listes qui decident la meme chose finissent par diverger (CLAUDE.md)."""
    try:
        from cogs.user import _jb_models_marche
        noms = list(_jb_models_marche("us") or [])
        if noms:
            return sorted(noms, key=str.lower)
        print("[bases] menu US vide : repli sur le marche des dossiers", flush=True)
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases] menu US illisible ({type(e).__name__}: {e}) : repli sur le "
              "marche des dossiers", flush=True)
    try:
        import marche
        from cogs.welcome import list_identities
        try:
            from cogs.user import EXCLURE_MENU
        except Exception:                                    # noqa: BLE001
            EXCLURE_MENU = {"jessye"}
        return sorted((n for n in list_identities()
                       if marche.de(n) == "us" and n.strip().lower() not in EXCLURE_MENU),
                      key=str.lower)
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases] identites US illisibles : {type(e).__name__}: {e}", flush=True)
        return []


# ─────────────────────────────────────────────────────────── le message ──

def lire_demande(texte: str) -> Dict[str, Any]:
    """{liste, identite, nom_affiche, erreur} d'apres le texte du message."""
    lignes = [l.strip() for l in _MENTION.sub(" ", texte or "").splitlines() if l.strip()]
    d = {"liste": False, "identite": "", "nom_affiche": None, "erreur": ""}
    if len(lignes) == 1 and lignes[0].lower() == "liste":
        d["liste"] = True
        return d
    if not lignes:
        d["erreur"] = "Écris le nom de l'identité avec les 2 photos."
        return d
    if len(lignes) > 2:
        d["erreur"] = "2 lignes au plus : l'identité, puis le nom affiché."
        return d
    d["identite"] = lignes[0].lstrip("@").strip()
    d["nom_affiche"] = lignes[1] if len(lignes) > 1 else None
    return d


def _est_image(piece) -> bool:
    ct = str(getattr(piece, "content_type", "") or "").lower()
    if ct.startswith("image/"):
        return True
    nom = str(getattr(piece, "filename", "") or "").lower()
    return any(nom.endswith(ext) for ext in IMAGES)


def erreur_pieces(pieces) -> str:
    """"" si on a exactement deux images, sinon la phrase a dire."""
    n = len(pieces)
    if n == 0:
        return "Il manque les 2 photos : la 1re = photo de profil, la 2e = fond."
    if n == 1:
        return "Une seule photo : il en faut 2 (la 1re = photo de profil, la 2e = fond)."
    if n > 2:
        return f"{n} pièces jointes : il en faut exactement 2 (la 1re = photo de profil, la 2e = fond)."
    for p in pieces:
        if not _est_image(p):
            return f"« {getattr(p, 'filename', '?')} » n'est pas une image."
    return ""


def textes_liste(identites: List[str], faites, raison: str = "") -> List[str]:
    """La liste ✅/➖ en messages de 2000 signes au plus, coupes entre deux
    lignes, dans l'ordre alphabetique de identites. `faites` : les identites
    qui ont une base (cles, ou un registre {identite: ...}). `raison` : la
    liste de l'equipe n'a pas pu etre lue -- dit en tete."""
    faites = {bases.cle(k) for k in (faites or ())}
    lignes = [("✅ " if bases.cle(n) in faites else "➖ ") + _esc(n) for n in identites]
    if not lignes:
        return ["Aucune identité US."]
    if raison:
        lignes.insert(0, f"⚠️ GetMySocial illisible ({_esc(raison)[:200]}) : d'après le registre du bot")
    morceaux, cour = [], ""
    for l in lignes:
        if cour and len(cour) + 1 + len(l) > LIMITE_MESSAGE:
            morceaux.append(cour)
            cour = l
        else:
            cour = f"{cour}\n{l}" if cour else l
    if cour:
        morceaux.append(cour)
    return morceaux


_SANS_MENTION = discord.AllowedMentions.none()


# ─────────────────────────────────────────────────────────── le panneau ──

def emojis(guilde, idents) -> Dict[str, Any]:
    """{identite: emoji « id<nom> »} parmi ceux DEJA sur le serveur (le menu
    VA les cree ; le serveur est plein, rien n'est cree ici) -- la lecture
    de cogs/generateur_lien.emojis."""
    if guilde is None:
        return {}
    try:
        from cogs.user import _jb_emojis_presents
        return dict(_jb_emojis_presents(guilde, list(idents or [])) or {})
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases] emojis illisibles : {type(e).__name__}: {e}", flush=True)
        return {}


#: Ce qui a deja ete dit au journal : le panneau se recalcule a chaque
#: entretien et a chaque creation, la meme ligne n'a pas a revenir.
_DITS: set = set()


def _dire_une_fois(texte: str) -> None:
    if texte not in _DITS:
        _DITS.add(texte)
        print(texte, flush=True)


def texte_compteur(faites: int, total: int) -> str:
    return f"## 🧱 {int(faites)}/{int(total)}"


def entrees_panneau(noms: List[str], faites, emos=None) -> List[Tuple[str, str, Any, bool]]:
    """[(identite, libelle, emoji, faite)] : D'ABORD celles sans page (➖),
    PUIS celles qui en ont une (✅, a refaire) -- chaque groupe dans l'ordre
    de `noms` (alphabetique, celui de « liste »). Un nom qui ne tiendrait ni
    dans une option ni dans le custom_id de sa fenetre est dit au journal,
    jamais ecarte en silence."""
    faites = {bases.cle(k) for k in (faites or ())}
    emos = emos or {}
    sans, avec = [], []
    for n in noms or []:
        if not _NOM_IDENT.fullmatch(str(n)):
            _dire_une_fois(f"[bases] identité {n!r} inutilisable dans un menu Discord : non proposée")
            continue
        fait = bases.cle(n) in faites
        lib = f"{n}{FAITE if fait else A_FAIRE}"[:LIBELLE_MAX]
        (avec if fait else sans).append((str(n), lib, emos.get(n), fait))
    return sans + avec


def vue_panneau(entrees) -> discord.ui.View:
    """Les menus du panneau : 25 identites par menu, 5 menus au plus (une
    rangee chacun). Ce qui depasse est dit au journal."""
    vue = discord.ui.View(timeout=None)
    entrees = list(entrees or [])
    blocs = [entrees[i:i + TAILLE_MENU] for i in range(0, len(entrees), TAILLE_MENU)]
    if len(blocs) > MAX_MENUS:
        hors = [e[0] for b in blocs[MAX_MENUS:] for e in b]
        _dire_une_fois(f"[bases] {len(hors)} identité(s) au-delà de {MAX_MENUS} menus, NON proposées : "
                       + ", ".join(hors))
        blocs = blocs[:MAX_MENUS]
    if not blocs:
        vue.add_item(BidMenu(0, (), INTITULE_VIDE))
        return vue
    k = 0
    for i, bloc in enumerate(blocs):
        titre = INTITULE if len(blocs) == 1 else f"🧱 {k + 1}–{k + len(bloc)}…"
        vue.add_item(BidMenu(i, bloc, titre))
        k += len(bloc)
    return vue


def _dicts_a_plat(message) -> Optional[List[Dict[str, Any]]]:
    """Les dictionnaires d'API des composants d'un message, a plat ; None si
    l'un ne se relit pas."""
    pile = []
    for c in getattr(message, "components", None) or []:
        try:
            pile.append(c.to_dict())
        except Exception:                                    # noqa: BLE001
            return None
    out = []
    while pile:
        d = pile.pop(0)
        if isinstance(d, dict):
            out.append(d)
            pile = list(d.get("components") or []) + pile
    return out


def est_panneau(message, moi) -> bool:
    if getattr(getattr(message, "author", None), "id", None) != moi:
        return False
    return any(str(d.get("custom_id") or "").startswith("bid:m:") for d in (_dicts_a_plat(message) or []))


def _emoji_cle(e):
    if e is None:
        return None
    if isinstance(e, dict):
        return (str(e.get("name") or ""), str(e.get("id") or ""))
    return (str(getattr(e, "name", "") or e), str(getattr(e, "id", "") or ""))


def _empreinte(dicts) -> list:
    """Ce qui se VOIT des menus, sans les cles techniques (« id » numerote
    par Discord…) : de quoi ne reediter le panneau que s'il a change."""
    return [(d.get("type"), d.get("custom_id"), d.get("placeholder"), bool(d.get("disabled", False)),
             tuple((o.get("label"), o.get("value"), _emoji_cle(o.get("emoji")))
                   for o in (d.get("options") or [])))
            for d in dicts if d.get("type") == 3]


def empreinte_vue(contenu: str, vue) -> tuple:
    pile, dicts = list(vue.to_components()), []
    while pile:
        d = pile.pop(0)
        dicts.append(d)
        pile = list(d.get("components") or []) + pile
    return (contenu, _empreinte(dicts))


def empreinte_message(message) -> tuple:
    return (str(getattr(message, "content", "") or ""), _empreinte(_dicts_a_plat(message) or []))


def vue_du_message(message) -> Optional[discord.ui.View]:
    """Le panneau tel qu'il est AFFICHE, refait a l'identique, sans rien
    relire : apres l'ouverture d'une fenetre, le menu doit reprendre son
    intitule (sans ca, rechoisir la meme identite, fenetre fermee, ne
    declenchait rien). None si le message ne se relit pas."""
    menus = [d for d in (_dicts_a_plat(message) or []) if d.get("type") == 3
             and str(d.get("custom_id") or "").startswith("bid:m:")]
    if not menus:
        return None
    vue = discord.ui.View(timeout=None)
    for d in menus:
        try:
            n = int(str(d["custom_id"]).split(":")[2])
        except (ValueError, IndexError):
            continue
        entrees = []
        if not d.get("disabled"):
            for o in d.get("options") or []:
                val, lib = str(o.get("value") or ""), str(o.get("label") or "")
                if not val or val == "_":
                    continue
                e = o.get("emoji")
                emo = None
                if isinstance(e, dict) and (e.get("id") or e.get("name")):
                    try:
                        emo = discord.PartialEmoji.from_dict(e)
                    except Exception:                        # noqa: BLE001
                        emo = None
                entrees.append((val, lib, emo, lib.endswith(FAITE)))
        vue.add_item(BidMenu(n, entrees, d.get("placeholder") or INTITULE))
    return vue


class BidMenu(discord.ui.DynamicItem[discord.ui.Select], template=r"bid:m:(?P<n>[0-9])"):
    """Un menu des identites du panneau. Seul son rang est dans le custom_id :
    l'identite choisie arrive avec le clic et elle est VALIDEE contre la
    liste du moment a la soumission, jamais crue sur parole. Il repond donc
    apres un redemarrage (from_custom_id)."""

    def __init__(self, n=0, entrees=(), intitule=None):
        self.n = int(n)
        opts = []
        for ident, lib, emo, _fait in entrees or ():
            opts.append(discord.SelectOption(label=str(lib)[:LIBELLE_MAX], value=str(ident)[:LIBELLE_MAX],
                                             emoji=emo))
        vide = not opts
        if vide:
            opts = [discord.SelectOption(label="—", value="_")]
        super().__init__(discord.ui.Select(
            placeholder=intitule or INTITULE, min_values=1, max_values=1, options=opts,
            disabled=vide, custom_id=CID_MENU.format(n=self.n)))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["n"])

    async def callback(self, interaction: discord.Interaction):
        choix = ((getattr(self.item, "values", None) or [""])[0] or "").strip()
        cog = interaction.client.get_cog("BasesIdentite") if interaction.client else None
        if cog is None:
            await _ephemere(interaction, "🔒 Indisponible pour le moment.")
            return
        await cog.choisir(interaction, choix)


#: custom_id des fenetres ouvertes PAR CE PROCESSUS (cogs/spoofer._OUVERTES) :
#: une fenetre ouverte avant un redemarrage (un par deploiement) et validee
#: apres etait jetee par discord.py sans reponse -- les deux photos perdues.
#: on_interaction la reconstruit a partir de son custom_id.
_OUVERTES: set = set()


class FenetreBase(discord.ui.Modal):
    """La fenetre d'une identite : 2 photos obligatoires, le nom facultatif."""

    def __init__(self, ident: str, defaut_nom: str = "", custom_id: Optional[str] = None):
        self.ident = str(ident)
        super().__init__(title=f"🧱 {self.ident}"[:TITRE_MAX],
                         custom_id=custom_id or CID_FENETRE.format(
                             ident=self.ident, alea=os.urandom(4).hex())[:CUSTOM_ID_MAX])
        if custom_id is None:
            _OUVERTES.add(self.custom_id)
        self.pp = discord.ui.Label(text="Photo de profil", component=discord.ui.FileUpload(
            custom_id=CID_PP, min_values=1, max_values=1, required=True))
        self.fond = discord.ui.Label(text="Fond", component=discord.ui.FileUpload(
            custom_id=CID_FOND, min_values=1, max_values=1, required=True))
        self.nom = discord.ui.Label(text="Nom affiché", component=discord.ui.TextInput(
            custom_id=CID_NOM, required=False, max_length=80, default=(defaut_nom or None)))
        for x in (self.pp, self.fond, self.nom):
            self.add_item(x)

    async def on_submit(self, interaction: discord.Interaction):
        # Le custom_id RESTE dans _OUVERTES : discord.py remet la fenetre ET
        # l'evenement « interaction » ; le retirer ferait reprendre par
        # on_interaction une soumission deja traitee (vu au spoofer).
        cog = interaction.client.get_cog("BasesIdentite") if interaction.client else None
        if cog is None:
            await _ephemere(interaction, "🔒 Indisponible pour le moment.")
            return
        await cog.soumettre(interaction, self.ident,
                            list(getattr(self.pp.component, "values", None) or []),
                            list(getattr(self.fond.component, "values", None) or []),
                            str(getattr(self.nom.component, "value", None) or "").strip())


def _traces() -> Dict[str, Any]:
    """Les creations par la fenetre en cours ou coupees (bases.EN_COURS)."""
    try:
        d = safe_json.load(bases.EN_COURS, default={}) or {}
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases] {bases.EN_COURS.name} illisible : {type(e).__name__}: {e}", flush=True)
        return {}
    return d if isinstance(d, dict) else {}


def _tracer(cle: str, info: Optional[Dict[str, Any]]) -> None:
    """Pose (info) ou efface (None) la trace d'une creation par la fenetre.
    Ne leve jamais : sans trace, seul le message de reprise manque."""
    try:
        d = _traces()
        if info is None:
            if cle not in d:
                return
            d.pop(cle)
        else:
            d[cle] = info
        bases.EN_COURS.parent.mkdir(parents=True, exist_ok=True)
        if not safe_json.write(bases.EN_COURS, d, indent=1):
            print(f"[bases] {bases.EN_COURS.name} non écrit ({cle})", flush=True)
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases] trace de {cle} : {type(e).__name__}: {e}", flush=True)


async def _ephemere(interaction, texte: str) -> None:
    """Une ligne a l'admin seul. Ne leve jamais : dite au journal si perdue."""
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(texte[:LIMITE_MESSAGE], ephemeral=True)
        else:
            await interaction.followup.send(texte[:LIMITE_MESSAGE], ephemeral=True)
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases] réponse perdue ({type(e).__name__}: {e}) : {texte[:160]}", flush=True)


def _au_fond(f, *a, **k):
    """f dans un fil de l'executor, ses appels GetMySocial au rang « fond »."""
    with bases.au_fond():
        return f(*a, **k)


def _tel_quel(f, *a, **k):
    return f(*a, **k)


class BasesIdentite(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        #: une creation a la fois par identite (deux envois en rafale)
        self.en_cours = set()
        #: serveurs dont les ⏳ laisses par un redemarrage ont ete repris
        self.repris = set()
        #: le dernier etat lu AVEC la liste de l'equipe : {noms, faites}. Une
        #: creation le met a jour sur place -- relire la liste juste apres
        #: (son cache vient d'etre vide) aurait coute un appel par creation.
        self._etat: Optional[Dict[str, Any]] = None
        self._taches = set()

    async def cog_load(self):
        try:
            self.bot.add_dynamic_items(BidMenu)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] menu du panneau non rattaché : {e}", flush=True)
        try:
            if not self._entretien.is_running():
                self._entretien.start()
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] entretien non lance : {e}", flush=True)

    async def cog_unload(self):
        try:
            self._entretien.cancel()
        except Exception:                                    # noqa: BLE001
            pass

    @property
    def moi(self) -> int:
        return getattr(getattr(self.bot, "user", None), "id", 0)

    def _lancer(self, coro) -> None:
        t = asyncio.ensure_future(coro)
        self._taches.add(t)
        t.add_done_callback(self._taches.discard)

    # ------------------------------------------------------------ le panneau --

    async def calculer_etat(self, fond: bool = False) -> Dict[str, Any]:
        """{noms, faites, noms_affiches, raison} : les identites US, celles
        qui ont une page, et le nom affiche de cette page, d'apres la liste de
        l'equipe (le cache de gms). raison non vide : liste illisible, tout
        vient alors du registre du bot. `fond` : l'entretien, dont les appels
        passent au rang « fond » du budget (personne n'attend)."""
        loop = asyncio.get_running_loop()
        noms = await loop.run_in_executor(None, identites_us)
        faites, affiches, raison = await loop.run_in_executor(
            None, functools.partial(_au_fond if fond else _tel_quel, bases.etat_pages))
        etat = {"noms": list(noms or []), "faites": {bases.cle(k) for k in faites or ()},
                "noms_affiches": dict(affiches or {}), "raison": str(raison or "")}
        if etat["noms"] and not etat["raison"]:
            self._etat = {"noms": etat["noms"], "faites": set(etat["faites"]),
                          "noms_affiches": dict(etat["noms_affiches"])}
        return etat

    def _marquer_faite(self, identite, nom_affiche: str = "") -> None:
        if self._etat is not None:
            k = bases.cle(identite)
            self._etat["faites"].add(k)
            if nom_affiche:
                self._etat.setdefault("noms_affiches", {})[k] = str(nom_affiche)[:80]

    def nom_affiche_actuel(self, ident: str) -> str:
        """Le nom affiche de la page de cette identite, SANS appel : celui
        de la liste de l'equipe (lue par l'entretien, tenue a jour par chaque
        creation -- une page faite a la main n'est pas au registre du bot),
        sinon celui du registre."""
        k = bases.cle(ident)
        n = str(((self._etat or {}).get("noms_affiches") or {}).get(k) or "")
        if not n:
            try:
                n = str((bases.base_de(ident) or {}).get("nom_affiche") or "")
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] nom affiché de {ident} illisible : {e}", flush=True)
        return n[:80]

    def contenu_panneau(self, etat, guilde) -> Tuple[str, discord.ui.View]:
        noms = list(etat.get("noms") or [])
        faites = {bases.cle(k) for k in etat.get("faites") or ()}
        n = sum(1 for x in noms if bases.cle(x) in faites)
        return (texte_compteur(n, len(noms)),
                vue_panneau(entrees_panneau(noms, faites, emojis(guilde, noms))))

    async def assurer_panneau(self, canal, etat: Optional[Dict[str, Any]] = None,
                              creer: bool = True) -> int:
        """UN panneau dans le salon : pose s'il manque (`creer` : l'entretien
        seul le pose ; une creation ou « liste » ne font que le mettre a
        jour), reedite s'il a change, jamais reposte. Liste de
        l'equipe illisible ou menu US vide : un panneau deja la garde ce qu'il
        montre. Rend 1 si le salon a ete touche, 0 sinon. Ne leve jamais."""
        if canal is None:
            return 0
        try:
            moi = self.moi
            try:
                msgs = [m async for m in canal.history(limit=200)]
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] #{getattr(canal, 'name', '?')} illisible : {e}", flush=True)
                return 0
            panneaux = [m for m in msgs if est_panneau(m, moi)]
            if not panneaux and not creer:
                return 0
            if etat is None:
                etat = dict(self._etat) if self._etat is not None else await self.calculer_etat()
            # l'historique va du plus recent au plus ancien : on garde le plus
            # ANCIEN, on retire les doublons (deux demarrages croises)
            garde = panneaux[-1] if panneaux else None
            for m in panneaux[:-1]:
                try:
                    await m.delete()
                except Exception as e:                       # noqa: BLE001
                    print(f"[bases] panneau en double non retiré : {e}", flush=True)
            if garde is not None and (etat.get("raison") or not etat.get("noms")):
                print(f"[bases] panneau laissé tel quel : "
                      f"{etat.get('raison') or 'liste des identités US vide'}", flush=True)
                return 0
            contenu, vue = self.contenu_panneau(etat, getattr(canal, "guild", None))
            if garde is None:
                await canal.send(contenu, view=vue, allowed_mentions=_SANS_MENTION)
                return 1
            if empreinte_message(garde) != empreinte_vue(contenu, vue):
                await garde.edit(content=contenu, view=vue)
                return 1
            return 0
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] panneau de #{getattr(canal, 'name', '?')} : {type(e).__name__}: {e}",
                  flush=True)
            return 0

    def _refus(self, interaction) -> str:
        if not _serveur_us(getattr(interaction, "guild", None)):
            return "🔒 Réservé au serveur US."
        if not est_salon_bases(getattr(interaction, "channel", None)):
            return "🔒 Ce menu ne sert que dans #" + nom_salon() + "."
        if not _est_admin(getattr(interaction, "user", None)):
            return "🔒 Réservé aux admins."
        return ""

    async def choisir(self, interaction, ident: str) -> None:
        """Une identite choisie dans le panneau : sa fenetre. Elle doit etre
        la TOUTE PREMIERE reponse (trois secondes) : rien de lent avant --
        l'identite est verifiee contre la liste a la soumission."""
        refus = self._refus(interaction)
        if not refus and (not ident or ident == "_" or not _NOM_IDENT.fullmatch(ident)):
            refus = "🧱 Aucune identité choisie."
        if refus:
            await _ephemere(interaction, refus)
            return
        await interaction.response.send_modal(FenetreBase(ident, self.nom_affiche_actuel(ident)))
        msg = getattr(interaction, "message", None)
        if msg is not None:
            self._lancer(self._remettre(msg))

    async def _remettre(self, message) -> None:
        """Le menu reprend son intitule (l'identite choisie y restait
        affichee : la rechoisir, fenetre fermee, ne declenchait plus rien).
        Refait a l'identique du message, sans rien relire."""
        try:
            vue = vue_du_message(message)
            if vue is not None:
                await message.edit(view=vue)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] menu du panneau non remis : {type(e).__name__}: {e}", flush=True)

    async def soumettre(self, interaction, ident: str, pp: list, fond: list, nom: str) -> dict:
        """La fenetre validee : la page creee, son adresse SEULE dans le
        salon, le panneau a jour. Les refus et erreurs a l'admin seul.
        Rend le resultat de creer_base (ou {ok: False, erreur})."""
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception:                                    # noqa: BLE001
            pass

        async def non(texte):
            await _ephemere(interaction, f"❌ {texte}"[:LIMITE_MESSAGE])
            return {"ok": False, "erreur": texte}

        refus = self._refus(interaction)
        if refus:
            await _ephemere(interaction, refus)
            return {"ok": False, "erreur": refus}
        if len(pp) != 1 or len(fond) != 1:
            return await non("Il faut 1 photo de profil et 1 fond.")
        for piece in (pp[0], fond[0]):
            if not _est_image(piece):
                return await non(f"« {_esc(getattr(piece, 'filename', '?'))} » n'est pas une image.")
        loop = asyncio.get_running_loop()
        noms = await loop.run_in_executor(None, identites_us)
        if not noms:
            return await non("Liste des identités US illisible (menu US vide).")
        exact = bases.trouver(ident, noms)
        if not exact:
            p = bases.proches(ident, noms)
            return await non(f"« {_esc(ident)} » n'est plus une identité US"
                             + (f". Proches : {', '.join(_esc(x) for x in p)}" if p else "."))
        cle = bases.cle(exact)
        if cle in self.en_cours:
            return await non(f"« {_esc(exact)} » est déjà en cours.")
        self.en_cours.add(cle)
        user = getattr(interaction, "user", None)
        canal = getattr(interaction, "channel", None)
        # la trace d'un redemarrage en plein travail : sans elle, l'attente
        # ephemere tournait jusqu'a expirer, et rien dans le salon ne disait
        # de refaire (le flux par message, lui, garde son ⏳)
        _tracer(cle, {"identite": exact, "user_id": getattr(user, "id", None),
                      "channel_id": getattr(canal, "id", None),
                      "guild_id": getattr(getattr(interaction, "guild", None), "id", None),
                      "pid": os.getpid(), "quand": int(time.time())})
        try:
            try:
                pp_b, fond_b = await pp[0].read(), await fond[0].read()
            except Exception as e:                           # noqa: BLE001
                return await non(f"Photos non téléchargées depuis Discord ({type(e).__name__}).")
            par = f"{getattr(user, 'name', '?')} ({getattr(user, 'id', '?')})"
            try:
                # requests et PIL bloquent : jamais sur la boucle du bot
                res = await loop.run_in_executor(None, functools.partial(
                    bases.creer_base, exact, pp_b, fond_b, nom_affiche=nom or None, par=par,
                    identites=noms))
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] création {exact} : {type(e).__name__}: {e}", flush=True)
                res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
        finally:
            self.en_cours.discard(cle)
            _tracer(cle, None)
        res = res if isinstance(res, dict) else {"ok": False, "erreur": "réponse illisible"}
        if res.get("url"):
            # la page existe (meme si une ancienne n'a pas pu etre coupee)
            self._marquer_faite(exact, res.get("nom_affiche") or "")
        if res.get("ok") and res.get("url"):
            # l'adresse SEULE : un appui long sur telephone copie tout le
            # message ; sans apercu, qui doublerait le message
            await self._dire(canal, res["url"], suppress_embeds=True)
            if res.get("avertissement"):
                await _ephemere(interaction, f"⚠️ {_esc(res['avertissement'])}")
            else:
                try:
                    await interaction.delete_original_response()
                except Exception:                            # noqa: BLE001
                    pass
        elif res.get("url") or res.get("manuel"):
            # Une page creee mais une ancienne PAS coupee (le panneau dit deja
            # ✅), ou une page rejetee pas coupee/renommee : il reste a faire
            # dans GetMySocial. En ephemere, l'adresse et la consigne
            # disparaissaient a la fermeture ; par message, elles restent
            # dans le salon -- un seul comportement pour le meme cas.
            ligne = f"❌ {_esc(exact)} : {_esc(res.get('erreur') or 'échec sans raison')}"
            await self._dire(canal, ligne[:LIMITE_MESSAGE], suppress_embeds=True)
            try:
                await interaction.delete_original_response()
            except Exception:                                # noqa: BLE001
                pass
        else:
            await non(f"{_esc(exact)} : {_esc(res.get('erreur') or 'échec sans raison')}")
        await self.assurer_panneau(canal, creer=False)
        return res

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        """Une fenetre ouverte AVANT un redemarrage et validee apres :
        reconstruite a partir de son custom_id (l'identite y est)."""
        if getattr(interaction, "type", None) is not discord.InteractionType.modal_submit:
            return
        data = getattr(interaction, "data", None) or {}
        cid = str(data.get("custom_id") or "")
        if not cid.startswith("bid:f:") or cid in _OUVERTES:
            return                        # fenetre de ce processus : discord.py s'en charge
        morceaux = cid.split(":")
        if len(morceaux) < 4 or not _NOM_IDENT.fullmatch(morceaux[2]):
            print(f"[bases] fenêtre {cid} illisible : non reprise", flush=True)
            return
        print(f"[bases] fenêtre d'avant redémarrage reprise : {cid}", flush=True)
        try:
            m = FenetreBase(morceaux[2], custom_id=cid)
            t = m._dispatch_submit(interaction, data.get("components") or [],
                                   data.get("resolved") or {})
            if t is not None:
                self._taches.add(t)
                t.add_done_callback(self._taches.discard)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] fenêtre {cid} non reprise : {type(e).__name__}: {e}", flush=True)

    # ------------------------------------------------------------ le salon --

    async def assurer_salon(self, guilde):
        """Le salon prive, cree s'il manque. Un salon deja la (decore ou non,
        deplace dans une categorie) est garde ; seuls les droits du bot y sont
        reposes s'ils manquent."""
        if getattr(guilde, "unavailable", False) or getattr(guilde, "me", None) is None:
            # GUILD_CREATE pas encore recu (panne Discord, demarrage lent) :
            # aucun salon visible, et le creer donnait un doublon que le bot
            # lui-meme ne voyait pas
            print(f"[bases] serveur {getattr(guilde, 'id', '?')} indisponible : salon vérifié plus tard",
                  flush=True)
            return None
        existant = discord.utils.find(est_salon_bases, list(getattr(guilde, "text_channels", []) or []))
        if existant is not None:
            await self._verifier_droits(existant, guilde)
            return existant
        try:
            canal = await guilde.create_text_channel(
                nom_salon(), overwrites=droits_salon(guilde),
                reason="Bases GetMySocial des identites US")
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] salon {nom_salon()} non cree sur {getattr(guilde, 'name', '?')} : "
                  f"{type(e).__name__}: {e}", flush=True)
            return None
        print(f"[bases] salon #{canal.name} cree sur {getattr(guilde, 'name', '?')}", flush=True)
        return canal

    async def _verifier_droits(self, canal, guilde) -> None:
        """Un salon fait a la main dans une categorie reservee a un role, ou
        « Synchroniser les permissions » apres un deplacement : le bot ne le
        voit plus. Discord ne lui livre alors AUCUN message de ce salon -- ni
        ⏳, ni ❌, rien. On repose ses droits ; on dit si on ne peut pas."""
        moi = guilde.me
        try:
            p = canal.permissions_for(moi)
            manque = [d for d in DROITS_VITAUX if not getattr(p, d, False)]
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] droits du bot dans #{getattr(canal, 'name', '?')} illisibles : {e}", flush=True)
            manque = []
        if manque:
            try:
                await canal.set_permissions(moi, reason="Bases GetMySocial : le bot doit lire ce salon",
                                            **DROITS_BOT)
                print(f"[bases] #{canal.name} : droits du bot reposés ({', '.join(manque)} manquaient)",
                      flush=True)
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] #{canal.name} : le bot n'a pas {', '.join(manque)} et ne peut pas se "
                      f"les donner ({type(e).__name__}: {e}) — donner l'accès au bot à la main",
                      flush=True)
        try:
            if canal.permissions_for(guilde.default_role).view_channel:
                print(f"[bases] ATTENTION : #{canal.name} est visible de @everyone — les adresses "
                      "et la liste y sont lisibles par tous", flush=True)
        except Exception:                                    # noqa: BLE001
            pass

    async def _reprendre_interrompus(self, canal) -> int:
        """Au demarrage : un ⏳ du bot sans ✅ ni ❌, c'est une creation tuee par
        un redemarrage (le cron redemarre le bot a chaque push). Sans ca, ⏳
        restait affiche pour toujours, sans un mot."""
        # une creation en cours dans CE processus (rechargement du cog) n'est
        # pas interrompue : on ne touche alors a rien
        if not bases._VERROU.acquire(blocking=False):
            return 0
        bases._VERROU.release()
        n = 0
        try:
            async for m in canal.history(limit=50):
                miennes = {str(r.emoji) for r in (getattr(m, "reactions", None) or [])
                           if getattr(r, "me", False)}
                if "⏳" not in miennes or miennes & {"✅", "❌"}:
                    continue
                n += 1
                ident = lire_demande(getattr(m, "content", "") or "").get("identite") or ""
                await self._reagir(m, "❌", retirer="⏳")
                await self._dire(canal, "❌ " + (f"{_esc(ident)} : " if ident else "")
                                 + "interrompu par un redémarrage du bot — renvoie-le "
                                   "(une page créée entre-temps sera coupée)", reference=m)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] reprise des ⏳ de #{getattr(canal, 'name', '?')} : {type(e).__name__}: {e}",
                  flush=True)
        # les creations par la fenetre : pas de message a marquer, une trace
        # sur disque. Celles de CE processus (cog recharge) tournent encore.
        gid = getattr(getattr(canal, "guild", None), "id", None)
        for k, t in sorted(_traces().items()):
            if not isinstance(t, dict) or t.get("pid") == os.getpid():
                continue
            if t.get("guild_id") not in (None, gid):
                continue                  # celle d'un autre serveur : il la reprendra
            n += 1
            ident = str(t.get("identite") or k)
            await self._dire(canal, f"❌ {_esc(ident)} : interrompu par un redémarrage du bot — refais-le "
                                    "(une page créée entre-temps sera coupée)")
            _tracer(k, None)
            print(f"[bases] création de {ident} par la fenêtre interrompue par un redémarrage : dit dans "
                  f"#{getattr(canal, 'name', '?')}", flush=True)
        return n

    @tasks.loop(hours=ENTRETIEN_HEURES)
    async def _entretien(self):
        muet = False
        for guilde in list(getattr(self.bot, "guilds", []) or []):
            if not _serveur_us(guilde):
                continue
            try:
                canal = await self.assurer_salon(guilde)
                if canal is None:
                    continue
                if guilde.id not in self.repris:
                    self.repris.add(guilde.id)
                    await self._reprendre_interrompus(canal)
                etat = await self.calculer_etat(fond=True)
                muet = muet or bool(etat["raison"])
                await self.assurer_panneau(canal, etat)
                if not etat["raison"]:
                    # la liste vient d'etre lue (cache de gms) : le rangement
                    # ne coute un appel que s'il y a quelque chose a ranger --
                    # au rang « fond », comme la lecture
                    await asyncio.get_running_loop().run_in_executor(
                        None, functools.partial(_au_fond, bases.ranger_templates))
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] salon de {getattr(guilde, 'name', '?')} : {type(e).__name__}: {e}",
                      flush=True)
        try:
            if self._entretien.is_running():
                if muet:
                    self._entretien.change_interval(minutes=REESSAI_MINUTES)
                else:
                    self._entretien.change_interval(hours=ENTRETIEN_HEURES)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] cadence de l'entretien inchangée : {e}", flush=True)

    @_entretien.before_loop
    async def _avant_entretien(self):
        await self.bot.wait_until_ready()

    # --------------------------------------------------------- les messages --

    @commands.Cog.listener()
    async def on_message(self, message):
        auteur = getattr(message, "author", None)
        if auteur is None or getattr(auteur, "bot", False):
            return
        if getattr(message, "type", discord.MessageType.default) not in (
                discord.MessageType.default, discord.MessageType.reply):
            return
        guilde = getattr(message, "guild", None)
        if guilde is None or not _serveur_us(guilde):
            return
        if not est_salon_bases(getattr(message, "channel", None)):
            return
        if not _est_admin(auteur):
            return
        try:
            await self.traiter(message)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] message {getattr(message, 'id', '?')} : {type(e).__name__}: {e}", flush=True)
            # ⏳ a pu etre pose : sans le retirer, ⏳ et ❌ restaient cote a cote
            await self._reagir(message, "❌", retirer="⏳")
            await self._dire(message.channel, f"❌ {type(e).__name__}: {e}"[:LIMITE_MESSAGE])

    async def _contenu(self, message) -> Tuple[str, list]:
        texte = message.content or ""
        pieces = list(getattr(message, "attachments", None) or [])
        if texte.strip() or pieces:
            return texte, pieces
        # Vide : l'intention Message Content manque (voir l'en-tete). L'API
        # rend le contenu si elle est cochee dans le portail.
        try:
            m2 = await message.channel.fetch_message(message.id)
            return (m2.content or ""), list(getattr(m2, "attachments", None) or [])
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] message {getattr(message, 'id', '?')} non relu : {type(e).__name__}: {e}",
                  flush=True)
            return "", []

    async def _reagir(self, message, emoji: str, retirer: Optional[str] = None) -> None:
        if retirer:
            try:
                moi = getattr(getattr(message, "guild", None), "me", None) or self.bot.user
                await message.remove_reaction(retirer, moi)
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] reaction {retirer} non retiree : {e}", flush=True)
        try:
            await message.add_reaction(emoji)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] reaction {emoji} non posee : {e}", flush=True)

    async def _dire(self, canal, texte: str, **kw) -> None:
        try:
            await canal.send(texte, allowed_mentions=_SANS_MENTION, **kw)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] message non envoye dans #{getattr(canal, 'name', '?')} : {e}", flush=True)

    async def _echec(self, message, texte: str) -> None:
        await self._reagir(message, "❌")
        await self._dire(message.channel, f"❌ {texte}"[:LIMITE_MESSAGE])

    async def traiter(self, message) -> None:
        texte, pieces = await self._contenu(message)
        canal = message.channel
        if not texte.strip() and not pieces:
            moi = getattr(getattr(self.bot, "user", None), "mention", "") or "@Yoshi"
            # « @Yoshi » propose aussi le ROLE gere du bot : sa mention ne
            # livre pas le message, et « mentionne-moi » laissait croire
            # qu'on l'avait fait. mention_roles arrive meme sans l'intention.
            role = getattr(getattr(message, "guild", None), "self_role", None)
            if role is not None and any(getattr(r, "id", None) == role.id
                                        for r in (getattr(message, "role_mentions", None) or [])):
                await self._echec(message, f"Tu as mentionné le rôle @{_esc(role.name)}, pas le bot : "
                                           f"mentionne le membre {moi} + le nom + les 2 photos.")
                return
            await self._echec(message, f"Je ne lis ce salon que si tu me mentionnes : {moi} + le nom + les 2 photos.")
            return
        d = lire_demande(texte)
        loop = asyncio.get_running_loop()
        if d["liste"]:
            # la verite du module VA (pages « TEMPLATE x » de l'equipe, meme
            # faites a la main), pas le seul registre du bot
            etat = await self.calculer_etat()
            for t in textes_liste(etat["noms"], etat["faites"], etat["raison"]):
                await self._dire(canal, t)
            # le meme etat, lu de toute facon : le panneau suit sans appel
            await self.assurer_panneau(canal, etat, creer=False)
            return
        if d["erreur"]:
            await self._echec(message, d["erreur"])
            return
        err = erreur_pieces(pieces)
        if err:
            await self._echec(message, err)
            return
        noms = await loop.run_in_executor(None, identites_us)
        if not noms:
            await self._echec(message, "Liste des identités US illisible (menu US vide).")
            return
        exact = bases.trouver(d["identite"], noms)
        if not exact:
            # avant ⏳ et le telechargement : c'est une faute de frappe, la
            # reponse doit etre immediate (creer_base refait la meme verification)
            p = bases.proches(d["identite"], noms)
            await self._echec(message, f"« {_esc(d['identite'])} » n'est pas une identité US"
                              + (f". Proches : {', '.join(_esc(x) for x in p)}" if p else "."))
            return
        cle = bases.cle(d["identite"])
        if cle in self.en_cours:
            await self._echec(message, f"« {_esc(d['identite'])} » est déjà en cours.")
            return
        self.en_cours.add(cle)
        try:
            await self._reagir(message, "⏳")
            try:
                pp, fond = await pieces[0].read(), await pieces[1].read()
            except Exception as e:                           # noqa: BLE001
                await self._reagir(message, "❌", retirer="⏳")
                await self._dire(canal, f"❌ Photos non téléchargées depuis Discord ({type(e).__name__}).")
                return
            par = f"{getattr(message.author, 'name', '?')} ({getattr(message.author, 'id', '?')})"
            # requests et PIL bloquent : jamais sur la boucle du bot
            res = await loop.run_in_executor(None, functools.partial(
                bases.creer_base, d["identite"], pp, fond,
                nom_affiche=d["nom_affiche"], par=par, identites=noms))
            if res.get("ok"):
                await self._reagir(message, "✅", retirer="⏳")
                # l'adresse SEULE : un appui long sur telephone copie tout le
                # message ; et sans apercu, qui doublerait le message
                await self._dire(canal, res["url"], suppress_embeds=True)
                if res.get("avertissement"):
                    await self._dire(canal, f"⚠️ {_esc(res['avertissement'])}"[:LIMITE_MESSAGE])
            else:
                await self._reagir(message, "❌", retirer="⏳")
                await self._dire(canal, f"❌ {_esc(res.get('erreur') or 'échec sans raison')}"[:LIMITE_MESSAGE])
        finally:
            self.en_cours.discard(cle)
        if res.get("url"):
            # le panneau suit la page creee par message aussi : ➖ -> ✅
            self._marquer_faite(exact, res.get("nom_affiche") or "")
            await self.assurer_panneau(canal, creer=False)


async def setup(bot):
    await bot.add_cog(BasesIdentite(bot))
