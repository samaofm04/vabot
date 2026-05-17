import re
import discord
from discord.ext import commands

STEPS = [
    {
        "title": "👋 Bienvenue dans l'agence !",
        "description": (
            "Voici une vidéo explicative qui va te montrer comment va se dérouler ton job "
            "en tant que VA dans l'agence.\n\n"
            "Tout va t'être expliqué étape par étape par le bot. Suis simplement les "
            "instructions et clique sur le bouton **→** pour passer à l'étape suivante.\n\n"
            "*(La vidéo d'explication sera ajoutée ici par le boss bientôt.)*\n\n"
            "Quand tu es prêt, clique sur **→**."
        ),
    },
    {
        "title": "Étape 2 — Création du compte Instagram",
        "description": (
            "Pour créer le compte Instagram, tu dois utiliser un **numéro US**. "
            "Demande-le au boss avant de continuer.\n\n"
            "Une fois prêt, fais la commande `/username` ici — le bot te donnera un "
            "username aléatoire à utiliser pour le compte.\n\n"
            "Quand le compte est créé, clique sur **→**."
        ),
    },
    {
        "title": "Étape 3 — Bio du profil",
        "description": (
            "Fais la commande `/bio` ici.\n\n"
            "Le bot te donnera une bio aléatoire. Copie-colle-la dans la bio Instagram "
            "(modifier le profil → bio).\n\n"
            "Quand c'est fait, clique sur **→**."
        ),
    },
    {
        "title": "Étape 4 — Photo de profil",
        "description": (
            "Fais la commande `/profilepic` ici.\n\n"
            "Le bot t'enverra une photo. Télécharge-la sur ton téléphone et "
            "définis-la comme photo de profil Instagram.\n\n"
            "Quand c'est fait, clique sur **→**."
        ),
    },
    {
        "title": "Étape 5 — Suivre 5 comptes",
        "description": (
            "Suis **5 comptes** pour amorcer ton profil :\n"
            "• **Marché FR** si ton audience cible est francophone\n"
            "• **Marché US** si ton audience cible est anglophone\n\n"
            "Choisis selon le type de contenu que tu vas publier. Demande au boss "
            "si tu ne sais pas quel marché viser.\n\n"
            "Quand c'est fait, clique sur **→**."
        ),
    },
    {
        "title": "Étape 6 — Warmup",
        "description": (
            "Avant de poster, fais un **warmup** pendant 2-3 jours pour que ton compte "
            "ait l'air naturel :\n\n"
            "• Like 10-20 posts par jour\n"
            "• Suis 5-10 nouveaux comptes par jour\n"
            "• Scrolle des reels naturellement\n"
            "• Regarde des stories\n\n"
            "Quand tu es prêt à poster ton premier reel, clique sur **→**."
        ),
    },
    {
        "title": "Étape 7 — Génération du premier reel 🚀",
        "description": (
            "Tu y es ! Fais la commande `/reel` ici.\n\n"
            "Le bot va te générer :\n"
            "• Une **vidéo** (tirée de ton identité)\n"
            "• Une **caption** (à mettre par-dessus la vidéo dans Instagram)\n\n"
            "Télécharge la vidéo, ajoute la caption en overlay (texte dans l'éditeur "
            "Instagram), publie-la en reel.\n\n"
            "Tu peux refaire `/reel` à chaque fois que tu veux publier un nouveau reel."
        ),
    },
]


def step_embed(index: int) -> discord.Embed:
    s = STEPS[index]
    embed = discord.Embed(
        title=s["title"],
        description=s["description"],
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"Étape {index + 1}/{len(STEPS)}")
    return embed


class OnboardingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="→",
        style=discord.ButtonStyle.primary,
        custom_id="va_onboarding_next",
    )
    async def next_step(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message or not interaction.message.embeds:
            await interaction.response.send_message("Erreur: étape inconnue.", ephemeral=True)
            return
        footer = interaction.message.embeds[0].footer.text or ""
        m = re.match(r"Étape (\d+)/(\d+)", footer)
        if not m:
            await interaction.response.send_message("Erreur: étape introuvable.", ephemeral=True)
            return
        current = int(m.group(1)) - 1
        next_index = current + 1
        if next_index >= len(STEPS):
            await interaction.response.send_message("Tu es déjà à la dernière étape.", ephemeral=True)
            return
        new_embed = step_embed(next_index)
        view = None if next_index == len(STEPS) - 1 else OnboardingView()
        await interaction.response.send_message(embed=new_embed, view=view)


class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(OnboardingView())


async def setup(bot):
    await bot.add_cog(Onboarding(bot))
