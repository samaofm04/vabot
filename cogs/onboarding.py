import re
import discord
from discord.ext import commands

STEPS = [
    {
        "title": "👋 Bienvenue dans l'agence !",
        "description": (
            "Voici une vidéo explicative qui va te montrer comment va se dérouler ton job "
            "en tant que VA dans l'agence.\n\n"
            "Tout va t'être expliqué étape par étape par le bot.\n\n"
            "*(La vidéo d'explication sera ajoutée ici par le boss bientôt.)*\n\n"
            "Quand tu es prêt, clique sur **→**."
        ),
    },
    {
        "title": "📆 JOUR 0 — Création du compte Instagram",
        "description": (
            "**Sur ton téléphone, fais cette séquence :**\n\n"
            "1️⃣ **Rotate l'IP** : mode avion 10 sec → enlève → remets la 5G\n"
            "2️⃣ **Crée un Gmail** qui aura comme base le futur nom Insta\n"
            "3️⃣ **Inscris le Gmail** sur Instagram\n"
            "4️⃣ **Mets le code reçu** par mail\n"
            "5️⃣ **Crée un mot de passe** fort\n"
            "6️⃣ **Mets un name (display)** → fais `/name` ici, je t'en donne un\n"
            "7️⃣ **Mets un username** → fais `/username` ici, je t'en donne un\n\n"
            "⚠️ **Numéro US requis** — demande au boss.\n\n"
            "Quand le compte est créé → clique sur **→** pour passer à la suite."
        ),
    },
    {
        "title": "⏳ ATTENDRE 24H à 48H",
        "description": (
            "**NE FAIS RIEN sur le compte pendant 24 à 48h.**\n\n"
            "Instagram doit considérer ton compte comme légitime. Si tu agis trop vite, "
            "shadowban garanti.\n\n"
            "Reviens cliquer sur **→** quand 24-48h sont passées."
        ),
    },
    {
        "title": "📆 JOUR 1 — Premier engagement + photo de profil",
        "description": (
            "**Engagement (10-15 min) :**\n"
            "• Va sur les reels et **swipe naturellement** comme un humain\n"
            "• Like seulement des **filles** au début (algo doit comprendre ton feed)\n"
            "• Quand tu tombes sur une **fille OnlyFans**, va sur son profil :\n"
            "  - Like ses reels\n"
            "  - Mets un **commentaire humain** (pas \"trop belle mv\" générique — adapte au contenu)\n"
            "  - Regarde ses stories\n"
            "  - **Abonne-toi**\n\n"
            "⚠️ Max **3 abonnements** + max **5-6 commentaires** aujourd'hui.\n\n"
            "**Photo de profil :** fais `/profilepic` ici → upload sur ton compte Insta.\n\n"
            "Ferme Insta. Clique **→** quand c'est fait."
        ),
    },
    {
        "title": "📆 JOUR 2 — Bio + première story + premier post",
        "description": (
            "• **Interagis 10 min** (5-6 commentaires + max 3 abonnements)\n"
            "• Ajoute la **bio** → fais `/bio` ici, je t'en donne une\n"
            "• Poste **1 story** simple (photo ou vidéo neutre) → fais `/story`\n"
            "• **Crée une bulle à la une** appelée **\"me\"** + ajoute ta story dedans\n"
            "• Poste **1 publication photo** sur le feed avec musique → fais `/post`\n\n"
            "Quand c'est fait, clique **→**."
        ),
    },
    {
        "title": "📆 JOUR 3 — Story + post + premier reel",
        "description": (
            "• **Interagis 10 min** (5-6 commentaires + 3 abonnements)\n"
            "• Poste **1 story** simple → fais `/story`\n"
            "• **Crée une bulle à la une** appelée **\"life\"** + ajoute ta story dedans\n"
            "• Poste **1 publication photo** avec musique → fais `/post`\n"
            "• 🎬 **PUBLIE TON PREMIER REEL entre 18h et 21h** → fais `/reel`\n\n"
            "Clique **→** quand c'est fait."
        ),
    },
    {
        "title": "📆 JOUR 4 — Carousels + bulle à la une",
        "description": (
            "• **Interagis 10 min** (commentaires + 3 abonnements)\n"
            "• Poste **1 story** simple → fais `/story`\n"
            "• **Crée une bulle à la une** appelée **\"travel\"** + ajoute ta story\n"
            "• **PIN les 3 carousels** (épingle les 3 derniers posts en haut du profil)\n"
            "• 🎬 **Publie 1 reel entre 18h et 21h** → fais `/reel`\n\n"
            "Clique **→**."
        ),
    },
    {
        "title": "📆 JOUR 5 — Remplissage des stories à la une",
        "description": (
            "• **Interagis 10 min** (commentaires + 3 abonnements)\n"
            "• **Poste 12 stories** aujourd'hui → fais `/story` (refais la commande pour chaque story)\n"
            "• Répartis-les : **4 stories par bulle à la une** (me / life / travel)\n"
            "• 🎬 **Publie 1 reel à 20h heure française** → fais `/reel`\n\n"
            "Clique **→** quand t'as fini."
        ),
    },
    {
        "title": "📆 JOUR 6+ — Routine quotidienne (warmup terminé)",
        "description": (
            "**Routine quotidienne à appliquer chaque jour :**\n\n"
            "• Interagir 2-3 min/jour (commentaire + 3 abonnements)\n"
            "• **1 story quotidienne** → fais `/story`\n"
            "• 🎬 **1 reel entre 18h et 21h** → fais `/reel`\n"
            "• **Repost le reel de la veille en story** avec texte CTA\n"
            "• 📲 **Story CTA + lien redirection** → fais `/storycta`\n"
            "• **Crée une bulle à la une \"LINKS\"** pour stocker les CTAs\n\n"
            "🎉 **Le warmup est terminé !** À partir de maintenant tu enchaînes la routine "
            "et tu utilises `/reel`, `/post`, `/story`, `/storycta` quand tu en as besoin.\n\n"
            "Bon courage 💪"
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
