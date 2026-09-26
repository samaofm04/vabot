"""Deux menus de TEST, jumeaux de /menujailbreak et /menujailbreakus.

POURQUOI UN DOUBLE PLUTOT QU'UNE MODIFICATION DES VRAIS
-------------------------------------------------------
Le panneau de contenu des VA (_JB_ACTIONS_US) est PLEIN : vingt entrees pour
vingt places, Discord n'autorisant que quatre rangees de cinq une fois le
selecteur de quantite pose sur la premiere. Y toucher pour essayer une idee,
c'est deplacer des boutons que les VA connaissent par coeur.

Ici on n'a pas cette contrainte : pas de selecteur de quantite, donc les CINQ
rangees sont libres -- vingt-cinq places au lieu de vingt.

POURQUOI SUR LE BOT ADMIN
-------------------------
Le bot principal declare deja 101 commandes slash pour un plafond Discord de
100 : une de plus ferait echouer la synchronisation de TOUT son arbre. Le bot
admin, lui, en compte 78 et a vingt-deux places libres. Un banc d'essai n'a de
toute facon rien a faire sur le bot que manipulent les VA.

LA LISTE EST LUE A L'EXECUTION, PAS RECOPIEE
--------------------------------------------
_JB_ACTIONS_US est importee au moment d'ouvrir le menu : le double suit donc
la production tout seul, et on n'ajoute par-dessus que ce qu'on essaie
(_ESSAIS). Recopier la liste aurait garanti qu'elle derive au premier
changement, et qu'on finisse par tester un panneau qui n'existe plus.
"""
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

BOT_DIR = Path(__file__).resolve().parent.parent
IDENTITIES_DIR = BOT_DIR / "data" / "identities"

#: Ce qu'on essaie, en plus de la production. UNE LIGNE PAR IDEE -- c'est le
#: seul endroit a toucher pour ajouter une option au banc d'essai.
#:
#: (cle, libelle, APRES_QUOI). Le troisieme champ est la cle de production
#: derriere laquelle l'essai vient se ranger.
#:
#: POURQUOI PAS A LA FIN. Groupes en bas, les trois essais formaient une
#: quatrieme famille qui n'existe pas. Le menu se lit par degre a l'interieur
#: d'une meme matiere -- Caption, ⭐ Caption, ⭐ Brut + Caption, ⭐⭐ Caption +
#: Brut -- et c'est cet ordre qui apprend au VA ce que chaque etoile designe.
#: Un essai range ailleurs se compare a rien.
_ESSAIS = [
    ("brutcaption",  "⭐ Brut + Caption",  "capbanger"),
    ("bruttemplate", "⭐ Brut + Template", "templatebanger"),
    ("brutflash",    "⭐ Brut + Flash",    "templateflashbanger"),
]

#: Vingt-cinq places : cinq rangees de cinq, selecteur de quantite en moins.
_PLACES_MAX = 25


def _entrees():
    """Les entrees de production, PUIS les essais. Rend [(cle, libelle, essai)].

    Les doublons de cle sont ecartes : si un essai finit par etre adopte en
    production, il ne doit pas apparaitre deux fois le lendemain.
    """
    try:
        from cogs.user import _JB_ACTIONS_US as prod
    except Exception:
        prod = []
    vues, sortie = set(), []
    for cle, libelle, *_r in list(prod):
        if cle in vues:
            continue
        vues.add(cle)
        sortie.append((cle, libelle, False))

    # Chaque essai se glisse DERRIERE son ancre, pas a la fin. Une ancre
    # introuvable -- production remaniee, essai adopte -- renvoie l'essai en
    # queue plutot que de le faire disparaitre : mieux vaut mal range que
    # perdu.
    for cle, libelle, apres in _ESSAIS:
        if cle in vues:
            continue
        vues.add(cle)
        pos = next((i for i, (k, _l, _e) in enumerate(sortie) if k == apres), None)
        if pos is None:
            sortie.append((cle, libelle, True))
        else:
            sortie.insert(pos + 1, (cle, libelle, True))
    return sortie


def _models(marche: str):
    """Les models du marche, meme source que les menus reels, avec repli.

    On passe par les helpers de cogs.user quand ils repondent, pour proposer
    exactement ce que le menu de production propose. Sinon on lit le dossier :
    mieux vaut un banc d'essai un peu large qu'un menu vide.
    """
    try:
        from cogs.user import _jb_us_models, _market_of
        if marche == "us":
            noms = list(_jb_us_models() or [])
        else:
            from cogs.welcome import list_active_identities
            noms = [m for m in list_active_identities() if _market_of(m) == "fr"]
        noms = [n for n in noms if not str(n).lower().startswith("v2_")]
        if noms:
            return sorted(noms)[:25]
    except Exception:
        pass
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(d.name for d in IDENTITIES_DIR.iterdir()
                  if d.is_dir() and not d.name.lower().startswith("v2_"))[:25]


class _Bouton(discord.ui.Button):
    """Un bouton du double. Sert une variante DEJA en reserve.

    On ne fabrique rien ici : un montage prend 15 a 30 secondes et une
    interaction Discord expire avant. La reserve est remplie d'avance par
    cogs/noctuspool ; ce menu la SERT, exactement comme le fait le parc.

    Les boutons qui ne passent PAS par la reserve (PP, Story, Post, brutes...)
    le DISENT au lieu d'echouer : leur contenu vient d'un dossier du site ou se
    fabrique a la demande, et c'est une information utile a l'essai.
    """

    def __init__(self, cle, libelle, essai, rangee):
        # TOUS LES BOUTONS SE RESSEMBLENT. Distinguer les essais en vert
        # revenait a annoncer une difference que le VA n'a pas a connaitre :
        # un bouton se juge sur ce qu'il rend, pas sur son anciennete.
        super().__init__(label=libelle[:80],
                         style=discord.ButtonStyle.secondary,
                         row=rangee)
        self.cle = cle

    async def callback(self, interaction: discord.Interaction):
        vue = self.view
        await interaction.response.defer(thinking=True)

        import noctus_reserve as _res
        famille = _res.famille_de(self.cle)
        if not famille:
            await interaction.followup.send(
                "**{}** — pas de reserve pour `{}`.\n"
                "_Ce bouton sert un dossier du site, ou se fabrique a la "
                "demande : il n'y a rien a tirer d'avance._".format(
                    self.label, self.cle))
            return

        chemin, desc = _res.prendre(vue.identite, famille, demandeur="menutest")
        if not chemin:
            # Vide n'est pas une panne : le remplisseur repasse toutes les deux
            # minutes. On le DIT, plutot que de laisser croire a un bug.
            await interaction.followup.send(
                "**{}** — rien en stock pour `{}` (famille `{}`).\n"
                "_Le remplisseur repasse toutes les 2 minutes._".format(
                    self.label, vue.identite, famille))
            return

        f = Path(chemin)
        try:
            await interaction.followup.send(
                "**{}** — `{}` / `{}`\n{}".format(
                    self.label, vue.identite, famille, (desc or "")[:180]),
                file=discord.File(str(f), filename=f.name))
        finally:
            # Meme regle que le parc : on solde dans tous les cas. Un doublon
            # publie coute un shadowban, une variante perdue vingt-cinq
            # secondes de calcul.
            try:
                _res.solder(f, motif="menutest")
            except Exception:
                pass


class PanneauTest(discord.ui.View):
    """Les actions, pour une model donnee. Gris = production, vert = essai."""

    def __init__(self, identite: str):
        # Sans delai : c'est un panneau qu'on POSTE, pas une bulle. Il ne
        # survit pas a un redemarrage du bot -- une vue n'est persistante que
        # si tous ses boutons portent un custom_id fixe, ce que la liste
        # dynamique des essais interdit. Il suffit de reposter le menu.
        super().__init__(timeout=None)
        self.identite = identite
        self.tronque = 0
        e = _entrees()
        if len(e) > _PLACES_MAX:
            # On ne laisse PAS discord.py lever au 26e bouton : mieux vaut un
            # menu incomplet qui le dit qu'une commande qui plante.
            self.tronque = len(e) - _PLACES_MAX
            e = e[:_PLACES_MAX]
        for i, (cle, libelle, essai) in enumerate(e):
            self.add_item(_Bouton(cle, libelle, essai, i // 5))


class _SelectModel(discord.ui.Select):
    def __init__(self, marche: str):
        noms = _models(marche)
        super().__init__(
            placeholder="Choisis une model…",
            options=[discord.SelectOption(label=n[:100], value=n[:100])
                     for n in noms] or
                    [discord.SelectOption(label="(aucune model)", value="_")],
            disabled=not noms)

    async def callback(self, interaction: discord.Interaction):
        ident = (self.values[0] or "").strip().lower()
        vue = PanneauTest(ident)
        avert = ("\n⚠️ %d entree(s) non affichee(s) : Discord plafonne a 25 "
                 "boutons." % vue.tronque) if vue.tronque else ""
        # Un NOUVEAU message, pas une edition : on garde le selecteur en place
        # pour enchainer sur une autre model sans reposter le menu.
        await interaction.response.send_message(
            "## 🧪 Que veux-tu generer ? — `%s`%s" % (ident, avert),
            view=vue)


class MenuTestEntree(discord.ui.View):
    """Le panneau d'entree : le menu deroulant des models, rien d'autre."""

    def __init__(self, marche: str):
        super().__init__(timeout=None)
        self.add_item(_SelectModel(marche))


def _embed(marche: str, nb: int) -> discord.Embed:
    emb = discord.Embed(
        title="🧪 Menu de TEST — %s" % ("marché US" if marche == "us"
                                        else "marché FR"),
        description=(
            "Choisis une model dans le menu déroulant, puis l'action à "
            "essayer.\n\n"
            "_Banc d'essai : le menu des VA n'est pas touché._"),
        color=discord.Color.green())
    emb.set_footer(text="%d model(s) — à reposter après un redémarrage du bot"
                        % nb)
    return emb


# ---------------------------------------------------------------------------
# /demopanneau : MAQUETTE CLIQUABLE du panneau US a menus deroulants.
#
# 25/09/2026. Le proprietaire a vu une premiere maquette ou « Template ▸ »
# ouvrait quatre menus, et l'a corrigee : pas d'etape, les menus sont LA des
# le depart, un par famille, Brut avant Template. Il veut le VOIR sur Discord
# avant qu'on refasse le vrai panneau : la navigation marche, les menus
# s'ouvrent, mais RIEN n'est genere ni envoye.
#
# POURQUOI LE FORMAT « COMPONENTS V2 » (LayoutView)
#     Un message classique plafonne a CINQ rangees, et un menu deroulant en
#     occupe une entiere. Deux rangees de boutons + cinq menus = sept : ca ne
#     tient pas. Le format V2 compte les composants (40 au plus) au lieu des
#     rangees. Il demande discord.py 2.6 ; la commande le verifie et le dit,
#     puisque c'est justement ce qu'on veut savoir du serveur.
#     Revers du V2 : pas d'embed, le texte passe dans un TextDisplay.
#
# Message EPHEMERE, sans custom_id fixe ni DynamicItem : rien de persistant.
# Une vue ephemere qui expire en portant un DynamicItem efface le motif
# enregistre pour les vrais panneaux -- d'ou aucun ici.
#
# Libelles, rangees de boutons, familles et explications LUS dans cogs.user
# (_jb_action, _JB_BOUTONS_V2, _FAMILLES_PANNEAU, _EXPLICATIONS) : la TABLE
# UNIQUE du vrai panneau depuis qu'il a pris cette forme. La maquette montre
# donc les vrais noms, dans le vrai ordre (Brut avant Template), logo Trash
# compris -- et ne peut plus s'en ecarter.


def _demo_libelle(cle: str) -> str:
    try:
        from cogs.user import _jb_action
        e = _jb_action(cle)
        if e:
            return e[1]
    except Exception:                                        # noqa: BLE001
        pass
    return cle


def _demo_familles() -> list:
    """[(emoji, nom, (actions...))] des menus du vrai panneau, dans son ordre."""
    try:
        from cogs.user import _FAMILLES_PANNEAU
        return [(f.emoji, f.nom, tuple(f.actions)) for f in _FAMILLES_PANNEAU]
    except Exception:                                        # noqa: BLE001
        return []


def _demo_rangees() -> tuple:
    """Les rangees de boutons du vrai panneau ; « _qte » = la quantite."""
    try:
        from cogs.user import _JB_BOUTONS_V2
        return _JB_BOUTONS_V2
    except Exception:                                        # noqa: BLE001
        return (("_qte",),)


def _demo_expli(cle: str) -> str:
    try:
        from cogs.user import _EXPLICATIONS
        return _EXPLICATIONS.get(cle, "")
    except Exception:                                        # noqa: BLE001
        return ""


def _demo_v2_dispo() -> bool:
    return all(hasattr(discord.ui, n)
               for n in ("LayoutView", "Container", "TextDisplay", "ActionRow"))


async def _demo_recu(interaction: discord.Interaction, cle: str, vue):
    """Ce qu'un vrai clic aurait fait, dit au lieu d'etre fait."""
    vue.construire()                     # les menus reviennent sur leur intitule
    await interaction.response.edit_message(view=vue)
    await interaction.followup.send(
        "🧪 **Démo** — ici le VA recevrait **%s** × %d dans son salon "
        "-content.\n_%s_" % (_demo_libelle(cle), vue.qty,
                             _demo_expli(cle) or "—"),
        ephemeral=True)


class _DemoBouton(discord.ui.Button):
    def __init__(self, vue, cle, label, style=discord.ButtonStyle.primary):
        super().__init__(label=label[:80], style=style)
        # La vue est gardee a part : dans un LayoutView, un bouton est range
        # dans une rangee, elle-meme dans un conteneur.
        self.vue_demo = vue
        self.cle = cle

    async def callback(self, interaction: discord.Interaction):
        vue = self.vue_demo
        if self.cle == "_qty":
            vue.qty = {1: 3, 3: 5, 5: 10}.get(vue.qty, 1)
            vue.construire()
            await interaction.response.edit_message(view=vue)
            return
        await _demo_recu(interaction, self.cle, vue)


class _DemoSelect(discord.ui.Select):
    def __init__(self, vue, emoji, nom, actions):
        opts = []
        for a in actions:
            ex = _demo_expli(a)
            opts.append(discord.SelectOption(
                label=_demo_libelle(a)[:100], value=a,
                description=ex[:100] if ex else None))
        super().__init__(placeholder=f"{emoji} {nom}…", options=opts,
                         min_values=1, max_values=1)
        self.vue_demo = vue

    async def callback(self, interaction: discord.Interaction):
        await _demo_recu(interaction, self.values[0], self.vue_demo)


if _demo_v2_dispo():
    class DemoPanneauDirect(discord.ui.LayoutView):
        """Le panneau US a menus directs, en maquette."""

        def __init__(self, ident="model"):
            super().__init__(timeout=900)
            self.ident = ident
            self.qty = 3
            self.construire()

        def construire(self):
            self.clear_items()
            ui = discord.ui
            boite = ui.Container(accent_colour=discord.Colour.dark_red())
            boite.add_item(ui.TextDisplay(
                f"## 🔓 {self.ident.capitalize()} — que veux-tu générer ?\n"
                f"📦 **Quantité : {self.qty} média par action** — plafonnée "
                "au stock dispo de la model.\n"
                "-# 🧪 Maquette : les menus s'ouvrent, rien n'est envoyé."))
            # Pas de « ⭐⭐⭐ Trends » : le proprietaire l'a retire le 25/09/2026,
            # la fonction n'est « pas encore good » (_JB_MASQUEES de cogs.user).
            for rangee in _demo_rangees():
                r = ui.ActionRow()
                for cle in rangee:
                    if cle == "_qte":
                        r.add_item(_DemoBouton(self, "_qty",
                                               f"📦 Quantité : {self.qty}",
                                               discord.ButtonStyle.secondary))
                    else:
                        r.add_item(_DemoBouton(self, cle, _demo_libelle(cle)))
                boite.add_item(r)
            for e, nom, actions in _demo_familles():
                r = ui.ActionRow()
                r.add_item(_DemoSelect(self, e, nom, actions))
                boite.add_item(r)
            self.add_item(boite)


# ---------------------------------------------------------------------------
# /demomodels : le MENU DES MODELS au-dela de 25 (26/09/2026).
#
# L'ancien vrai menu mettait un bouton-photo par model et COUPAIT a 25 : cinq
# rangees de cinq, la limite d'un message Discord. Le proprietaire a compare
# ici plusieurs dispositions, puis choisi « menus10 » (« c'est ca, mets deja
# ca sur le bot ») : c'est devenu le VRAI menu (JailbreakModelsView,
# cogs/user.py). Cette variante n'a donc plus de code a elle : elle appelle
# la disposition de production (_jb_menus_de_10, _jb_menus_models_poser),
# avec un menu inerte a la place du vrai. Les autres restent pour comparer :
#   groupes      « 1–10 », « 11–20 »… ; un clic ouvre, EN PRIVE, les dix
#                boutons-photos du groupe (le message public est partage par
#                tous les VA : on ne l'edite jamais pour un seul d'entre eux)
#   top10        les dix premieres en photos, puis les groupes pour le reste
#   photos_menu  vingt photos + un menu deroulant « Autres models » (45 max)
#   menus        uniquement des menus deroulants « 1–25 », « 26–50 »… (125 max)
#
# Tout est EPHEMERE et rien n'est envoye. Liste, libelles, ordre et photos
# sont ceux de la production (_jb_models_marche, puis _jb_models_entrees :
# identites_ordre, _libelle_model, _identity_emoji_name) : la demo montre les
# vrais noms dans le vrai ordre. Les photos sont les emojis DEJA crees sur le
# serveur (_jb_emojis_presents) : jamais de creation d'emoji ici.
#
# Sous l'apercu : les identites ECARTEES du menu de ce marche, avec leur
# raison (_jb_models_ecartees). Le proprietaire voit ses models US mais pas
# « les autres, celles que j'ai ajoutees » ; on ne lit pas les donnees du
# serveur d'ici, c'est donc cet ecran, visible de lui seul, qui les nomme.
#
# Au-dela de ce qu'une disposition peut montrer, les models restantes sont
# COMPTEES et dites (« N non affichees »), jamais ecartees en silence : c'est
# precisement le defaut du [:25] de production qu'on cherche a eviter.

#: Limites Discord d'un message classique (hors Components V2).
_LIM_COMPOSANTS = 25
_LIM_PAR_RANGEE = 5
_LIM_OPTIONS = 25
_LIM_LIBELLE_BOUTON = 80
_LIM_LIBELLE_OPTION = 100
#: Taille d'un groupe « 1–10 » : deux rangees de cinq boutons-photos.
_TAILLE_GROUPE = 10

_DEMO_MODELS_VARIANTES = {
    # EN TETE : ce que le proprietaire a montre le 26/09/2026 (« comme ca »,
    # sur la capture des menus directs) avec des tranches de 10 (« si j'en ai
    # 60, il y en a 6 »).
    # Choisie par lui le meme jour : c'est desormais le VRAI menu.
    "menus10": "Menus déroulants de 10 (le vrai menu depuis le 26/09)",
    "groupes": "Groupes 1–10, 11–20… (un clic = les photos du groupe, en privé)",
    "top10": "Top 10 en photos + groupes pour la suite",
    "photos_menu": "20 photos + menu déroulant « Autres models »",
    "menus": "Menus déroulants uniquement : 1–25, 26–50…",
    # « Un bouton qui ouvre un menu » : une lecture de sa demande, gardee
    # pour comparer.
    "groupes_menu": "Boutons 1–10, 11–20… : un clic ouvre un menu déroulant (en privé)",
}


def _plage(debut: int, fin: int) -> str:
    """« 11–20 » : la numerotation du vrai menu (_jb_plage), lue et non
    recopiee -- les groupes des autres variantes se lisent comme ses menus."""
    from cogs.user import _jb_plage
    return _jb_plage(debut, fin)


def _demo_models_liste(marche: str, simuler: int, guild=None):
    """[(ident, libelle, emoji, fausse)] dans l'ordre de production, puis les
    fausses entrees « 🧪 Model test N » jusqu'a `simuler`. Rend aussi le
    nombre de vraies models, pour le dire a l'ecran.

    Les vraies sont EXACTEMENT les entrees du vrai menu (_jb_models_entrees :
    ordre, libelles d'apres la liste entiere, PP) -- une maquette qui les
    recalculerait finirait par montrer autre chose que la production."""
    reelles = []
    try:
        from cogs.user import (_jb_models_marche, _jb_models_entrees,
                               _jb_emojis_presents)
        models = list(_jb_models_marche(marche) or [])
        entrees, _rejets = _jb_models_entrees(
            models, _jb_emojis_presents(guild, models))
        reelles = [(v, lib, emoji, False) for v, lib, emoji in entrees]
    except Exception as e:                                   # noqa: BLE001
        # Une demo vide sans raison ferait chercher un bug qui n'existe pas.
        import logging
        logging.getLogger(__name__).warning(
            "demomodels : models de production illisibles (%s: %s)",
            type(e).__name__, e)
        reelles = []
    n_reelles = len(reelles)
    total = max(1, int(simuler or 0))
    items = list(reelles)
    for i in range(len(items) + 1, total + 1):
        items.append((f"zztest{i}", f"🧪 Model test {i}", None, True))
    return items[:total], n_reelles


def demo_models_plan(variante: str, items: list) -> dict:
    """La disposition, sans Discord : ce que chaque zone montre.

    {"photos": [items], "groupes": [(libelle, [items])],
     "menus": [(libelle, [items])], "non_affichees": [items]}

    Chaque item de `items` se retrouve dans EXACTEMENT une zone, ou dans
    non_affichees : c'est ce que les tests verifient.
    """
    photos, groupes, menus = [], [], []
    reste = list(items)

    def _grouper(depuis: int, liste: list, places: int):
        out = []
        for k in range(0, len(liste), _TAILLE_GROUPE):
            if len(out) >= places:
                break
            bloc = liste[k:k + _TAILLE_GROUPE]
            out.append((_plage(depuis + k, depuis + k + len(bloc) - 1), bloc))
        pris = sum(len(b) for _l, b in out)
        return out, liste[pris:]

    if variante in ("groupes", "groupes_menu"):
        groupes, reste = _grouper(1, reste, _LIM_COMPOSANTS)
    elif variante == "top10":
        photos, reste = reste[:10], reste[10:]
        # 10 photos = 2 rangees ; il en reste 3, soit 15 boutons de groupe.
        groupes, reste = _grouper(11, reste, 3 * _LIM_PAR_RANGEE)
    elif variante == "photos_menu":
        photos, reste = reste[:20], reste[20:]
        if reste:
            menus = [("Autres models", reste[:_LIM_OPTIONS])]
            reste = reste[_LIM_OPTIONS:]
    elif variante == "menus10":
        # LA disposition du vrai menu, pas une copie : c'est la variante que
        # le proprietaire a choisie, et elle doit rester ce qu'il a vu.
        from cogs.user import _jb_menus_de_10
        menus, reste = _jb_menus_de_10(reste)
    elif variante == "menus":
        k = 0
        while reste and len(menus) < _LIM_PAR_RANGEE:
            bloc, reste = reste[:_LIM_OPTIONS], reste[_LIM_OPTIONS:]
            menus.append((_plage(k + 1, k + len(bloc)), bloc))
            k += len(bloc)
    else:
        raise ValueError(f"variante inconnue : {variante}")
    return {"photos": photos, "groupes": groupes, "menus": menus,
            "non_affichees": reste,
            "groupes_en_menu": variante == "groupes_menu"}


async def _demo_model_choisie(interaction: discord.Interaction, libelle: str):
    await interaction.response.send_message(
        f"🧪 **Démo** — ici le VA ouvrirait le menu d'actions de **{libelle}**.",
        ephemeral=True)


class _DemoModelBouton(discord.ui.Button):
    def __init__(self, item, row=None):
        _ident, libelle, emoji, _f = item
        super().__init__(label=libelle[:_LIM_LIBELLE_BOUTON], emoji=emoji,
                         style=discord.ButtonStyle.secondary, row=row)
        self.libelle = libelle

    async def callback(self, interaction: discord.Interaction):
        await _demo_model_choisie(interaction, self.libelle)


class _DemoGroupeBouton(discord.ui.Button):
    """Ouvre les photos du groupe dans une NOUVELLE reponse privee : le
    message de depart n'est jamais edite (en production il est partage)."""

    def __init__(self, libelle, bloc, row=None, en_menu=False):
        super().__init__(label=libelle, style=discord.ButtonStyle.primary,
                         row=row)
        self.bloc = bloc
        # en_menu : les models du groupe arrivent dans UN menu deroulant (avec
        # leur photo) au lieu de dix boutons.
        self.en_menu = en_menu

    async def callback(self, interaction: discord.Interaction):
        vue = discord.ui.View(timeout=900)
        if self.en_menu:
            vue.add_item(_DemoModelsMenu(self.label, self.bloc))
            texte = f"🧪 Models **{self.label}** — choisis dans le menu :"
        else:
            for i, it in enumerate(self.bloc):
                vue.add_item(_DemoModelBouton(it, row=i // _LIM_PAR_RANGEE))
            texte = f"🧪 Models **{self.label}** — clique une model :"
        await interaction.response.send_message(texte, view=vue, ephemeral=True)


class _DemoModelsMenu(discord.ui.Select):
    def __init__(self, libelle, bloc, row=None):
        self.par_valeur = {}
        opts = []
        for ident, lib, emoji, _f in bloc:
            self.par_valeur[ident] = lib
            opts.append(discord.SelectOption(
                label=lib[:_LIM_LIBELLE_OPTION], value=ident, emoji=emoji))
        super().__init__(placeholder=f"👤 {libelle}…", options=opts,
                         min_values=1, max_values=1, row=row)

    async def callback(self, interaction: discord.Interaction):
        v = self.values[0]
        await _demo_model_choisie(interaction, self.par_valeur.get(v, v))


def demo_models_vue_v2(plan: dict, texte: str):
    """La variante « menus10 » : le bloc du VRAI menu (_jb_menus_models_poser),
    avec un menu inerte a la place de JBModelsMenu.

    Pourquoi pas les vrais menus : ce sont des elements dynamiques, et une
    vue ephemere qui expire en portant un element dynamique efface le motif
    enregistre pour les vrais menus (voir _vue_sans_suivi, cogs/user.py) --
    sans compter qu'un choix ouvrirait le vrai panneau d'actions. Le texte
    est borne a 4000 (limite du V2) par _jb_texte_v2_borne, qui le dit."""
    from cogs.user import _jb_menus_models_poser, _jb_texte_v2_borne
    return _jb_menus_models_poser(
        discord.ui.LayoutView(timeout=900),
        _jb_texte_v2_borne(texte, [], quoi="demomodels"),
        plan["menus"],
        lambda _i, plage, bloc: _DemoModelsMenu(plage, bloc))


#: Un nom plus long est coupe proprement (« … »), le compte reste exact.
_ECARTEES_NOM_MAX = 40


def demo_ecartees_texte(marche: str, budget: int) -> str:
    """La section « Écartées du menu » : chaque identite EXISTANTE absente
    du menu de `marche`, groupee par raison (_jb_models_ecartees, les filtres
    de production), en `budget` unites Discord au plus.

    Trop de noms : on coupe par groupe (« … (+k) ») et on DIT combien n'ont
    pas pu etre listes, avec le total -- jamais un nom qui disparait sans
    etre compte. Ne leve jamais : un diagnostic en panne le dit."""
    try:
        from cogs.user import _jb_models_ecartees, _long_discord, _couper_discord
    except Exception as e:                                   # noqa: BLE001
        return ("⚠️ Écartées du menu : diagnostic indisponible (%s)"
                % type(e).__name__)[:max(0, budget)]
    try:
        ecartees = _jb_models_ecartees(marche)
    except Exception as e:                                   # noqa: BLE001
        return _couper_discord("⚠️ Écartées du menu : diagnostic impossible "
                               "(%s: %s)" % (type(e).__name__, e), max(0, budget))
    mk = marche.upper()
    if not ecartees:
        return _couper_discord(
            f"### Écartées du menu {mk} : aucune\n"
            "Toutes les identités existantes sont dans le menu.", max(0, budget))
    groupes = {}
    for nom, raisons in ecartees:
        groupes.setdefault(" + ".join(raisons), []).append(nom)
    # Les plus nombreuses d'abord : c'est la que se cache la cause probable.
    ordre = sorted(groupes.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    def _court(nom):
        nom = str(nom).replace("`", "'")
        c = _couper_discord(nom, _ECARTEES_NOM_MAX)
        return f"`{c}…`" if c != nom else f"`{c}`"

    # LE PIED D'ABORD : la piste du marche, et le compte de ce qui n'aura pas
    # pu etre liste. Sa place est retenue AVANT de poser les noms -- mesuree
    # au pire (tout non liste) -- sinon la derniere coupe emportait
    # precisement la ligne qui dit combien manquent.
    total = len(ecartees)
    titre = f"### Écartées du menu {mk} : {total}"

    def _compte(k):
        return (f"-# {k} nom(s) non listé(s) faute de place — {total} "
                "écartée(s) au total.")
    place_compte = _long_discord(_compte(total)) + 1
    if budget < _long_discord(titre) + place_compte:
        # Pas meme la place de nommer : le titre porte le total, c'est lui
        # qui reste.
        return _couper_discord(f"{titre} (pas la place de les nommer ici)",
                               max(0, budget))
    # La piste du marche passe APRES le compte : elle n'est posee que s'il
    # reste de quoi nommer quelques identites a cote.
    piste = ("-# Le marché se règle sur le site : Bibliothèque → ✏️ Modifier "
             "→ Marché 🇫🇷/🇺🇸." if any("marché" in r for r in groupes) else "")
    if piste and (budget - _long_discord(titre) - place_compte
                  < _long_discord(piste) + 1 + 80):
        piste = ""
    reserve = place_compte + (_long_discord(piste) + 1 if piste else 0)

    out, pris, non_listees = [titre], _long_discord(titre), 0
    for i, (raison, noms) in enumerate(ordre):
        tete = f"• **{raison}** ({len(noms)}) : "
        place = budget - reserve - pris - 1 - _long_discord(tete)
        if place < 30:
            non_listees += sum(len(ns) for _r, ns in ordre[i:])
            break
        mis, long_mis = [], 0
        for nom in noms:
            m = _court(nom)
            plus = _long_discord(m) + (2 if mis else 0)
            # 12 : la place du « , … (+k) » s'il faut couper ensuite.
            if long_mis + plus > place - 12:
                break
            mis.append(m)
            long_mis += plus
        reste = len(noms) - len(mis)
        ligne = tete + ", ".join(mis) + ((", " if mis else "") + f"… (+{reste})"
                                         if reste else "")
        out.append(ligne)
        pris += 1 + _long_discord(ligne)
        non_listees += reste
    pied = [x for x in (piste, _compte(non_listees) if non_listees else "") if x]
    corps = "\n".join(out)
    place = max(0, budget) - sum(_long_discord(x) + 1 for x in pied)
    if _long_discord(corps) > place:
        # Budget trop petit meme pour le titre : le pied (le compte) passe
        # avant les noms, qui sont de toute facon comptes dedans.
        corps = _couper_discord(corps, max(0, place - 1)) + "…"
    return _couper_discord("\n".join([corps] + pied), max(0, budget))


def demo_models_vue(plan: dict) -> discord.ui.View:
    """La vue classique d'un plan. Les rangees sont POSEES, pas devinees :
    un menu deroulant prend une rangee entiere, et discord.py leve au 6e
    element d'une rangee -- on veut que ca casse dans les tests, pas chez le
    proprietaire."""
    vue = discord.ui.View(timeout=900)
    rang = 0
    for i, it in enumerate(plan["photos"]):
        vue.add_item(_DemoModelBouton(it, row=i // _LIM_PAR_RANGEE))
    if plan["photos"]:
        rang = (len(plan["photos"]) - 1) // _LIM_PAR_RANGEE + 1
    for i, (lib, bloc) in enumerate(plan["groupes"]):
        vue.add_item(_DemoGroupeBouton(lib, bloc,
                                       row=rang + i // _LIM_PAR_RANGEE,
                                       en_menu=plan.get("groupes_en_menu", False)))
    if plan["groupes"]:
        rang += (len(plan["groupes"]) - 1) // _LIM_PAR_RANGEE + 1
    for i, (lib, bloc) in enumerate(plan["menus"]):
        vue.add_item(_DemoModelsMenu(lib, bloc, row=rang + i))
    return vue


class MenuTest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="demomodels",
        description="[DÉMO] Le menu des models au-delà de 25 — 4 dispositions, rien n'est envoyé",
    )
    @app_commands.describe(
        variante="La disposition à essayer",
        marche="Le marché des models (us ou fr)",
        simuler="Nombre total de models à afficher (des « 🧪 Model test » complètent)")
    @app_commands.choices(
        variante=[app_commands.Choice(name=v[:100], value=k)
                  for k, v in _DEMO_MODELS_VARIANTES.items()],
        marche=[app_commands.Choice(name="US", value="us"),
                app_commands.Choice(name="FR", value="fr")])
    async def demomodels(self, interaction: discord.Interaction,
                         variante: app_commands.Choice[str],
                         marche: app_commands.Choice[str] = None,
                         simuler: app_commands.Range[int, 1, 200] = None):
        mk = marche.value if marche else "us"
        if simuler is None:
            # « menus10 » : on part de ce qui EXISTE (« tu fais avec ce qu'il y
            # a ») ; les autres gardent 40 pour montrer l'au-dela de 25.
            if variante.value == "menus10":
                simuler = max(1, _demo_models_liste(mk, 1, None)[1])
            else:
                simuler = 40
        items, n_reelles = _demo_models_liste(mk, simuler, interaction.guild)
        plan = demo_models_plan(variante.value, items)
        n_fausses = sum(1 for it in items if it[3])
        lignes = [
            f"## 🧪 Menu des models — {_DEMO_MODELS_VARIANTES[variante.value]}",
            f"Marché **{mk.upper()}** : **{n_reelles}** vraie(s) model(s)"
            + (f" + **{n_fausses}** fausse(s) « 🧪 Model test »" if n_fausses else "")
            + f" = **{len(items)}**.",
            "_Maquette : rien n'est envoyé ; le vrai menu n'est pas touché._",
        ]
        if n_reelles > len(items):
            lignes.append(f"⚠️ {n_reelles - len(items)} vraie(s) model(s) "
                          f"au-delà de « simuler = {len(items)} ».")
        if plan["non_affichees"]:
            lignes.append(f"⚠️ **{len(plan['non_affichees'])} model(s) non "
                          "affichée(s)** : cette disposition ne peut pas en "
                          "montrer plus.")
        # Les identites ECARTEES du menu de ce marche, avec leur raison, dans
        # la place qui reste : 4000 pour un message V2, 2000 pour le texte
        # d'un message classique.
        from cogs.user import _long_discord
        entete = "\n".join(lignes)
        plafond = 4000 if variante.value == "menus10" else 2000
        texte = entete + "\n" + demo_ecartees_texte(
            mk, plafond - _long_discord(entete) - 1)
        if variante.value == "menus10":
            await interaction.response.send_message(
                view=demo_models_vue_v2(plan, texte), ephemeral=True)
            return
        await interaction.response.send_message(
            texte, view=demo_models_vue(plan), ephemeral=True)

    @app_commands.command(
        name="demopanneau",
        description="[DÉMO] Aperçu du panneau US avec menus déroulants — rien n'est envoyé",
    )
    async def demopanneau(self, interaction: discord.Interaction):
        # C'est aussi la sonde : le serveur sait-il faire ce format ? On le
        # DIT au lieu de planter, avec la version a mettre a jour.
        if not _demo_v2_dispo():
            await interaction.response.send_message(
                "⚠️ discord.py %s sur le serveur : trop ancien pour ce format "
                "(menus directs = « Components V2 », discord.py 2.6 minimum)."
                % discord.__version__, ephemeral=True)
            return
        await interaction.response.send_message(
            view=DemoPanneauDirect("model"), ephemeral=True)

    async def _poster(self, interaction: discord.Interaction, marche: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                "À utiliser dans un serveur.", ephemeral=True)
            return
        noms = _models(marche)
        if not noms:
            await interaction.response.send_message(
                "⚠️ Aucune model à afficher pour le marché %s." % marche.upper(),
                ephemeral=True)
            return
        await interaction.response.send_message(
            embed=_embed(marche, len(noms)), view=MenuTestEntree(marche))

    @app_commands.command(
        name="menutest",
        description="[TEST] Poste ICI le menu de test — marché FR",
    )
    async def menutest(self, interaction: discord.Interaction):
        await self._poster(interaction, "fr")

    @app_commands.command(
        name="menutestus",
        description="[TEST] Poste ICI le menu de test — marché US",
    )
    async def menutestus(self, interaction: discord.Interaction):
        await self._poster(interaction, "us")


async def setup(bot):
    await bot.add_cog(MenuTest(bot))
