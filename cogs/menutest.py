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


class MenuTest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
