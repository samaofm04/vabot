import discord
from discord import app_commands
from discord.ext import commands


class PanneauPerime(discord.ui.View):
    """Repond a la place d un panneau que ce bot ne sait plus servir.

    Un bouton Discord n est servi QUE par l application qui a poste le
    message. Le panneau « Numeros & Mails » a ete pose le 15/08 par le bot
    PRINCIPAL, a l epoque ou le cog `numeros` etait dans MAIN_COGS ; il a
    depuis demenage dans ADMIN_COGS pour liberer des places de commandes
    (le principal est a 100/100). Le message epingle appartient donc a une
    application qui n a plus le code : les clics ne trouvaient personne, et
    Discord affichait « n a pas repondu a temps ». Rien, nulle part, ne
    disait que le panneau etait orphelin — on croyait le service casse.

    Cette vue ne remet pas le service ici : elle DIT ce qui se passe et ce
    qu il faut faire. Elle ne coute aucune place de commande (une vue n est
    pas une commande), et elle ne peut pas voler les clics du bon panneau :
    un panneau repose par le bot admin appartient au bot admin, qui le sert
    lui-meme.
    """

    _MOT = ("⚠️ **Ce panneau est périmé.**\n"
            "Il a été posté par un bot qui ne gère plus les numéros — le "
            "service a déménagé sur l'autre bot de l'agence.\n\n"
            "Un admin doit le reposer avec **`/panelnumero`** dans ce salon "
            "(ou **`/panelnumeroall`** pour tous les salons d'un coup). "
            "Les boutons remarcheront aussitôt.")

    def __init__(self):
        super().__init__(timeout=None)

    async def _dire(self, itx: discord.Interaction):
        await itx.response.send_message(self._MOT, ephemeral=True)

    @discord.ui.button(label="Numéro Instagram / Threads", emoji="📱",
                       style=discord.ButtonStyle.success, custom_id="numgen:sms")
    async def sms(self, itx: discord.Interaction, btn: discord.ui.Button):
        await self._dire(itx)

    @discord.ui.button(label="Mail Instagram", emoji="📧",
                       style=discord.ButtonStyle.primary, custom_id="numgen:mail")
    async def mail(self, itx: discord.Interaction, btn: discord.ui.Button):
        await self._dire(itx)

    @discord.ui.button(label="Autre service", emoji="⚙️", row=1,
                       style=discord.ButtonStyle.secondary, custom_id="numgen:other")
    async def other(self, itx: discord.Interaction, btn: discord.ui.Button):
        await self._dire(itx)


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Uniquement si CE bot n a pas le vrai cog : sinon on lui volerait
        # ses propres clics. Le bot admin, lui, charge NumerosCog et sert ses
        # panneaux normalement.
        if self.bot.get_cog("NumerosCog") is not None:
            return
        try:
            self.bot.add_view(PanneauPerime())
        except Exception:
            pass                    # un filet qui tombe ne doit rien casser

    @app_commands.command(name="ping", description="Test de latence du bot")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong! {latency_ms}ms")


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
