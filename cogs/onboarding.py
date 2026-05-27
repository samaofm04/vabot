import re
import os
import json
import logging
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("vabot.onboarding")

DATA_DIR = Path("data")
ONBOARDING_MEDIA_DIR = DATA_DIR / "onboarding_media"
WHITELIST_FILE = DATA_DIR / "whitelist.json"

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


def step_media_dir(index: int) -> Path:
    """Dossier où sont stockés les médias de l'étape <index>."""
    d = ONBOARDING_MEDIA_DIR / f"step_{index + 1}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def step_links_file(index: int) -> Path:
    """Fichier JSON qui stocke les references de messages Discord (liens) pour l'etape."""
    return step_media_dir(index) / "_links.json"


def load_step_links(index: int) -> list:
    """Liste des references de messages Discord pour cette etape.

    Format: [{"channel_id": int, "message_id": int, "filenames": [str, ...]}, ...]
    """
    f = step_links_file(index)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_step_links(index: int, links: list):
    f = step_links_file(index)
    f.write_text(json.dumps(links, indent=2, ensure_ascii=False), encoding="utf-8")


def list_step_media(index: int) -> list:
    """Liste des fichiers media LOCAUX (hors metadata) pour l'etape."""
    d = step_media_dir(index)
    return sorted([
        p for p in d.iterdir()
        if p.is_file() and not p.name.startswith("_")  # ignore _links.json etc.
    ])


_MSG_LINK_RE = re.compile(
    r"https?://(?:www\.)?(?:discord|discordapp)\.com/channels/(\d+)/(\d+)/(\d+)"
)


def parse_message_link(link: str):
    """Parse https://discord.com/channels/GUILD/CHANNEL/MESSAGE -> (guild, channel, msg) ou None."""
    m = _MSG_LINK_RE.search(link.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


async def send_step_media(channel: discord.abc.Messageable, index: int, bot=None):
    """Envoie les médias attachés à l'étape <index> dans le salon.

    Gere 2 sources:
    - fichiers locaux dans step_media_dir(index) (limite 10 Mo serveur non boost)
    - liens vers des messages Discord (stockes via /setonboardingmedia lien:...)
      -> on re-fetch le message pour obtenir une URL CDN fraiche, Discord auto-embed
    """
    # Limite Discord serveur non-boost : 10 Mo en pratique (ex 25 Mo officiel)
    MAX_SIZE = 10 * 1024 * 1024

    # 1) Fichiers locaux
    files = list_step_media(index)
    for p in files:
        try:
            size = p.stat().st_size
        except Exception as e:
            await channel.send(f"⚠️ Impossible de lire `{p.name}` : {e}")
            continue
        if size > MAX_SIZE:
            await channel.send(
                f"⚠️ `{p.name}` fait **{size / (1024*1024):.1f} Mo**, "
                f"au-dessus de la limite Discord du serveur ({MAX_SIZE // (1024*1024)} Mo). "
                f"Utilise plutot un **lien de message** (/setonboardingmedia lien:...) "
                f"si tu veux un fichier plus lourd."
            )
            continue
        try:
            await channel.send(file=discord.File(str(p), filename=p.name))
        except discord.HTTPException as e:
            await channel.send(
                f"⚠️ Echec envoi `{p.name}` ({size / (1024*1024):.1f} Mo) : "
                f"{getattr(e, 'text', str(e))[:200]}"
            )
        except Exception as e:
            log.error(f"Erreur inattendue envoi media {p}: {e}")
            await channel.send(f"⚠️ Erreur inattendue sur `{p.name}` : {str(e)[:200]}")

    # 2) Liens vers des messages Discord
    links = load_step_links(index)
    if not links:
        return
    if bot is None:
        # On essaie d'extraire le bot via channel
        bot = getattr(channel, "_state", None) and channel._state._get_client()
    if bot is None:
        await channel.send("⚠️ Liens video configures mais le bot ne peut pas les recuperer (context manquant).")
        return
    for link_data in links:
        cid = link_data.get("channel_id")
        mid = link_data.get("message_id")
        if not cid or not mid:
            continue
        try:
            src_channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
            msg = await src_channel.fetch_message(mid)
        except discord.NotFound:
            await channel.send(
                f"⚠️ Lien video casse pour cette etape (message supprime). "
                f"Demande au boss de refaire la config."
            )
            continue
        except discord.Forbidden:
            await channel.send(
                "⚠️ Le bot n'a plus acces au salon source de la video. "
                "Demande au boss de verifier les permissions."
            )
            continue
        except Exception as e:
            log.error(f"Erreur fetch message link step {index+1}: {e}")
            await channel.send(f"⚠️ Erreur recuperation video : {str(e)[:200]}")
            continue
        if not msg.attachments:
            await channel.send(
                "⚠️ Le message lie ne contient plus de piece jointe."
            )
            continue
        # Re-poster chaque URL d'attachement (Discord auto-embed les videos/images)
        for att in msg.attachments:
            try:
                await channel.send(att.url)
            except Exception as e:
                log.error(f"Erreur envoi URL attachement: {e}")


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
        # Envoyer les medias de l'etape (si presents)
        try:
            await send_step_media(interaction.channel, next_index, bot=interaction.client)
        except Exception as e:
            log.error(f"Erreur send_step_media step {next_index+1}: {e}")


class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None

    async def cog_load(self):
        self.bot.add_view(OnboardingView())

    async def get_owner_id(self):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return self._owner_id

    async def is_admin(self, user_id):
        if user_id == await self.get_owner_id():
            return True
        if WHITELIST_FILE.exists():
            try:
                wl = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
                return user_id in wl
            except Exception:
                pass
        return False

    async def require_admin(self, interaction):
        if not await self.is_admin(interaction.user.id):
            msg = "Tu n'es pas autorisé."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    @app_commands.command(
        name="setonboardingmedia",
        description="[ADMIN] Ajoute une video/photo a une etape (fichier OU lien de message)",
    )
    @app_commands.describe(
        step="Numero de l'etape (1 = bienvenue, 2 = jour 0, etc.)",
        media="Fichier a attacher (max 10 Mo). Utilise plutot 'lien' pour les gros fichiers.",
        lien="Lien d'un message Discord contenant la video (clic droit -> Copier le lien)",
    )
    async def setonboardingmedia(
        self,
        interaction: discord.Interaction,
        step: int,
        media: discord.Attachment = None,
        lien: str = None,
    ):
        if not await self.require_admin(interaction):
            return
        if step < 1 or step > len(STEPS):
            await interaction.response.send_message(
                f"Etape invalide. Doit etre entre 1 et {len(STEPS)}.", ephemeral=True
            )
            return
        if not media and not lien:
            await interaction.response.send_message(
                "Tu dois fournir SOIT `media` (fichier) SOIT `lien` (lien de message Discord).\n\n"
                "**Pour un lien :** dans un salon, clic droit sur le message qui contient la video "
                "-> 'Copier le lien du message' -> colle-le ici.\n"
                "**Avantage du lien :** pas de limite 10 Mo (le bot ne re-uploade pas, il reutilise ton upload).",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        index = step - 1
        title = STEPS[index]["title"]
        messages = []

        # --- Cas 1 : fichier attache ---
        if media is not None:
            d = step_media_dir(index)
            target = d / media.filename
            i = 1
            while target.exists():
                stem, ext = os.path.splitext(media.filename)
                target = d / f"{stem}_{i}{ext}"
                i += 1
            try:
                await media.save(str(target))
                messages.append(f"📎 Fichier ajoute : `{target.name}`")
            except Exception as e:
                messages.append(f"❌ Erreur sauvegarde fichier : {e}")

        # --- Cas 2 : lien de message ---
        if lien:
            parsed = parse_message_link(lien)
            if not parsed:
                messages.append(
                    "❌ Lien invalide. Format attendu : "
                    "`https://discord.com/channels/SERVER/CHANNEL/MESSAGE`"
                )
            else:
                _gid, cid, mid = parsed
                # Verifier que le bot a acces et que le message contient un attachement
                try:
                    src_channel = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
                    msg = await src_channel.fetch_message(mid)
                except discord.NotFound:
                    messages.append("❌ Message introuvable (supprime ou ID invalide).")
                except discord.Forbidden:
                    messages.append(
                        "❌ Le bot n'a pas acces a ce salon. Donne-lui la permission de voir "
                        "le salon ou se trouve le message."
                    )
                except Exception as e:
                    messages.append(f"❌ Erreur acces message : {str(e)[:200]}")
                else:
                    if not msg.attachments:
                        messages.append(
                            "❌ Ce message ne contient aucune piece jointe (fichier). "
                            "Tu dois lier un message contenant une video/image en attachement, "
                            "pas juste un texte."
                        )
                    else:
                        links = load_step_links(index)
                        links.append({
                            "channel_id": cid,
                            "message_id": mid,
                            "filenames": [a.filename for a in msg.attachments],
                        })
                        save_step_links(index, links)
                        names = ", ".join(f"`{a.filename}`" for a in msg.attachments)
                        messages.append(
                            f"🔗 Lien enregistre — {len(msg.attachments)} fichier(s) : {names}"
                        )

        local_count = len(list_step_media(index))
        link_count = len(load_step_links(index))
        recap = (
            f"**Etape {step}** ({title})\n"
            f"{chr(10).join(messages)}\n\n"
            f"📊 Total maintenant : {local_count} fichier(s) local + {link_count} lien(s)"
        )
        await interaction.followup.send(recap[:1900], ephemeral=True)

    @app_commands.command(
        name="listonboardingmedia",
        description="[ADMIN] Liste les médias attachés à chaque étape d'onboarding",
    )
    async def listonboardingmedia(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        MAX_SIZE = 10 * 1024 * 1024
        lines = []
        for i, s in enumerate(STEPS):
            files = list_step_media(i)
            links = load_step_links(i)
            short_title = s["title"][:55]
            parts = []
            for f in files:
                try:
                    size_mo = f.stat().st_size / (1024 * 1024)
                    marker = "❌" if f.stat().st_size > MAX_SIZE else "✅"
                    parts.append(f"{marker} 📎 `{f.name}` ({size_mo:.1f} Mo)")
                except Exception:
                    parts.append(f"⚠️ `{f.name}` (illisible)")
            for j, lk in enumerate(links):
                names = ", ".join(lk.get("filenames", []))
                parts.append(f"🔗 lien #{j+1} → {names or '(no filename)'}")
            if parts:
                lines.append(
                    f"**{i+1}.** {short_title} — {len(files)} fichier(s) + {len(links)} lien(s) :\n  "
                    + "\n  ".join(parts)
                )
            else:
                lines.append(f"**{i+1}.** {short_title} — *aucun media*")
        msg = (
            "📚 **Medias onboarding par etape**\n"
            "✅ = fichier OK (≤10 Mo) | ❌ = trop lourd | 🔗 = lien de message (pas de limite)\n\n"
            + "\n".join(lines)
        )
        await interaction.response.send_message(msg[:1990], ephemeral=True)

    @app_commands.command(
        name="clearonboardingmedia",
        description="[ADMIN] Supprime TOUS les médias d'une étape",
    )
    @app_commands.describe(step="Numéro de l'étape à vider")
    async def clearonboardingmedia(self, interaction: discord.Interaction, step: int):
        if not await self.require_admin(interaction):
            return
        if step < 1 or step > len(STEPS):
            await interaction.response.send_message(
                f"Étape invalide. Doit être entre 1 et {len(STEPS)}.", ephemeral=True
            )
            return
        index = step - 1
        files = list_step_media(index)
        deleted_files = 0
        for p in files:
            try:
                p.unlink()
                deleted_files += 1
            except Exception:
                pass
        # Aussi supprimer les liens stockes
        deleted_links = len(load_step_links(index))
        lf = step_links_file(index)
        if lf.exists():
            try:
                lf.unlink()
            except Exception:
                deleted_links = 0
        await interaction.response.send_message(
            f"✅ Etape **{step}** videe : **{deleted_files}** fichier(s) + "
            f"**{deleted_links}** lien(s) supprime(s).",
            ephemeral=True,
        )

    @app_commands.command(
        name="testonboardingstep",
        description="[ADMIN] Affiche une étape d'onboarding ici (preview avec médias)",
    )
    @app_commands.describe(step="Numéro de l'étape à prévisualiser")
    async def testonboardingstep(self, interaction: discord.Interaction, step: int):
        if not await self.require_admin(interaction):
            return
        if step < 1 or step > len(STEPS):
            await interaction.response.send_message(
                f"Étape invalide. Doit être entre 1 et {len(STEPS)}.", ephemeral=True
            )
            return
        index = step - 1
        embed = step_embed(index)
        await interaction.response.send_message(embed=embed)
        await send_step_media(interaction.channel, index, bot=self.bot)


async def setup(bot):
    await bot.add_cog(Onboarding(bot))
