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
# Libelles et familles LUS dans cogs.user (_jb_action, _FAMILLES_MENU,
# _EXPLICATIONS) : la maquette montre les vrais noms, logo Trash compris.

#: Le menu « Brut » : les trois boutons de brute du panneau actuel.
_DEMO_BRUT = ("brute", "brutbanger", "brutchoix")
_DEMO_BRUT_EXPLI = {
    "brute": "une vidéo brute, sans rien dessus",
    "brutbanger": "une de tes brutes ⭐",
    "brutchoix": "tu choisis toi-même la brute à utiliser",
}

#: L'ordre des menus, voulu par le proprietaire : Brut AVANT Template.
_DEMO_ORDRE_MENUS = ("brut", "caption", "template", "trash", "flash")


def _demo_libelle(cle: str) -> str:
    try:
        from cogs.user import _jb_action
        e = _jb_action(cle)
        if e:
            return e[1]
    except Exception:                                        # noqa: BLE001
        pass
    return cle


def _demo_familles() -> dict:
    """{cle: (emoji, nom, (actions...))} lu dans cogs.user, plus « brut »."""
    out = {}
    try:
        from cogs.user import _FAMILLES_MENU
        for f in _FAMILLES_MENU:
            out[f.cle] = (f.emoji, f.nom, tuple(f.actions))
    except Exception:                                        # noqa: BLE001
        pass
    out["brut"] = ("🎥", "Brut", _DEMO_BRUT)
    return out


def _demo_expli(cle: str) -> str:
    if cle in _DEMO_BRUT_EXPLI:
        return _DEMO_BRUT_EXPLI[cle]
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
            r0 = ui.ActionRow()
            r0.add_item(_DemoBouton(self, "_qty", f"📦 Quantité : {self.qty}",
                                    discord.ButtonStyle.secondary))
            for cle in ("name", "pseudo", "pp", "bio"):
                r0.add_item(_DemoBouton(self, cle, _demo_libelle(cle)))
            boite.add_item(r0)
            # Pas de « ⭐⭐⭐ Trends » : le proprietaire l'a retire le 25/09/2026,
            # la fonction n'est « pas encore good ».
            r1 = ui.ActionRow()
            for cle in ("story", "storycta", "post"):
                r1.add_item(_DemoBouton(self, cle, _demo_libelle(cle)))
            boite.add_item(r1)
            fam = _demo_familles()
            for cle in _DEMO_ORDRE_MENUS:
                if cle not in fam:
                    continue
                e, nom, actions = fam[cle]
                r = ui.ActionRow()
                r.add_item(_DemoSelect(self, e, nom, actions))
                boite.add_item(r)
            self.add_item(boite)


class MenuTest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
