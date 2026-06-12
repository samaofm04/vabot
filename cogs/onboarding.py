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
        "title": "📆 JOUR 0 — Création des comptes Instagram au téléphone",
        "description": (
            "**Sur ton téléphone, fais cette séquence :**\n\n"
            "1️⃣ **Rotate l'IP** : mode avion 10 sec → enlève → remets la 5G\n"
            "2️⃣ **Crée un Gmail** qui aura comme base le futur nom de l'Insta\n"
            "3️⃣ **Inscris le Gmail** sur Instagram\n"
            "4️⃣ **Mets le code** reçu par mail\n"
            "5️⃣ **Crée un mot de passe** fort\n"
            "6️⃣ **Mets un nom (display)** → clique sur **Name** ci-dessous, je t'en donne un\n"
            "7️⃣ **Mets un nom d'utilisateur** → clique sur **Username** ci-dessous, je t'en donne un\n"
            "8️⃣ Une fois sur l'Insta : va **regarder un profil + ouvre tes messages 30 sec** "
            "pour simuler une interaction humaine\n\n"
            "⚠️ **Numéro US requis** — demande au boss.\n\n"
            "Quand les comptes sont créés → clique sur **→**."
        ),
    },
    {
        "title": "⏳ ATTENDRE 24H à 48H",
        "description": (
            "**NE FAIS RIEN sur le compte pendant 24 à 48h.**\n\n"
            "Instagram doit considérer ton compte comme légitime. Si tu agis trop vite → "
            "shadowban garanti.\n\n"
            "Reviens cliquer sur **→** quand 24-48h sont passées."
        ),
    },
    {
        "title": "📆 JOUR 1 — Premier engagement + photo de profil",
        "description": (
            "**Engagement (10-15 min) :**\n"
            "• Va sur les reels et **swipe naturellement** comme un humain\n"
            "• Le but : avoir **que des filles OnlyFans** sur ton feed → like des filles au début\n"
            "• Quand tu tombes sur une **fille OF** : like ses reels, mets un **commentaire humain** "
            "adapté au contenu (pas un « trop belle mv » générique), regarde ses stories, puis **abonne-toi**\n\n"
            "⚠️ Max **3 abonnements** + max **5-6 commentaires** aujourd'hui.\n\n"
            "📸 **Photo de profil** (unique) → clique sur **Photo de profil** ci-dessous, mets-la sur l'Insta.\n\n"
            "Ferme Insta. Clique **→** quand c'est fait."
        ),
    },
    {
        "title": "📆 JOUR 2 — Ajout de contenu soft + story",
        "description": (
            "• **Interagis 10 min** comme au jour 1 (commentaires + max 3 abonnements)\n"
            "• Ajoute une **bio efficace** → clique sur **Bio** (modèle fourni)\n"
            "• Poste **1 story** simple (photo/vidéo neutre) → clique sur **Story**, puis crée une "
            "**bulle à la une « me »** et ajoute ta story dedans\n"
            "• Poste **1 publication photo** sur le feed avec musique → clique sur **Post**\n\n"
            "Clique **→** quand c'est fait."
        ),
    },
    {
        "title": "📆 JOUR 3 — Optimisation du profil",
        "description": (
            "• **Interagis 10 min** (commentaires + 3 abonnements)\n"
            "• Poste **1 story** simple → clique sur **Story**, puis crée une **bulle à la une « life »**\n"
            "• Poste **1 publication photo** avec musique → clique sur **Post**\n"
            "• 🎬 **Publie ton premier reel entre 18h et 21h** → clique sur **Reel**\n\n"
            "Clique **→** quand c'est fait."
        ),
    },
    {
        "title": "📆 JOUR 4 — Posts à la une + montée en reels",
        "description": (
            "• **Interagis 10 min** (commentaires + 3 abonnements)\n"
            "• Poste **1 story** simple → clique sur **Story**, puis crée une **bulle à la une « travel »**\n"
            "• **PIN les 3 carrousels** (épingle tes 3 derniers posts en haut du profil)\n"
            "• 🎬 **Publie 2 reels** entre 18h et 21h → clique sur **Reel** (possibilité de programmer)\n\n"
            "Clique **→** quand c'est fait."
        ),
    },
    {
        "title": "📆 JOUR 5 — Mise en place des stories à la une",
        "description": (
            "• **Interagis 10 min** (commentaires + 3 abonnements)\n"
            "• **Poste 12 stories** aujourd'hui → clique sur **Story** : ajoute **4 stories sur "
            "chacune des 3 bulles** (me / life / travel)\n"
            "• 🎬 **Publie 1 reel à 20h (heure française)** → clique sur **Reel**\n\n"
            "Clique **→** quand c'est fait."
        ),
    },
    {
        "title": "📆 JOUR 6+ — Activation Reels + Réflexes journaliers",
        "description": (
            "**Ta routine quotidienne à partir de maintenant :**\n"
            "• **Interagis 2-3 min/jour** (commentaire + 3 abonnements)\n"
            "• Poste **1 story** quotidienne → clique sur **Story**\n"
            "• 🎬 **Publie 2 reels entre 18h et 21h** → clique sur **Reel**\n"
            "• **Repost les 2 reels de la veille en story** avec un texte **CTA** → clique sur **Story CTA**\n"
            "• 📲 **Story CTA + liens de redirection** + crée une **bulle à la une « LINKS »** pour stocker les CTA\n\n"
            "🎉 **Le warm-up est terminé** — c'est ta routine de tous les jours. Bon courage 💪"
        ),
    },
]


def _web_steps():
    """Charge les etapes editees via le SITE WEB (data/onboarding.json, module
    racine `onboarding`). Retourne une liste de dicts {title, description} ou
    None si indispo/vide. Permet que les modifs faites sur le site se
    refletent dans l'onboarding Discord.

    SECURITE : tout est wrappe ; en cas de probleme on retourne None et le cog
    retombe sur les STEPS hardcodees -> l'onboarding ne casse jamais."""
    try:
        import onboarding as _web_ob  # bot/onboarding.py (module racine)
        steps = _web_ob.list_steps()
        if not steps:
            return None
        out = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            title = (s.get("title") or "").strip()
            icon = (s.get("icon") or "").strip()
            desc = (s.get("description") or "").strip()
            if icon and title and not title.startswith(icon):
                title = f"{icon} {title}".strip()
            elif icon and not title:
                title = icon
            out.append({"title": title, "description": desc})
        return out or None
    except Exception:
        return None


def step_embed(index: int) -> discord.Embed:
    # Structure canonique = STEPS hardcodees (compte, indexation des medias).
    # On override UNIQUEMENT le texte (titre/description) depuis les modifs
    # faites sur le site web, si elles existent pour cet index. Le footer garde
    # len(STEPS) pour ne pas perturber la navigation (boutons →).
    s = STEPS[index]
    title = s["title"]
    desc = s["description"]
    try:
        web = _web_steps()
        if web and 0 <= index < len(web):
            wt = (web[index].get("title") or "").strip()
            wd = (web[index].get("description") or "").strip()
            if wt:
                title = wt
            if wd:
                desc = wd
    except Exception:
        pass
    embed = discord.Embed(
        title=title,
        description=desc,
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


# Commandes qui acceptent un paramètre `nombre` (pour donner N items au warm-up)
_COUNT_CMDS = {"story", "post", "reel", "bio", "profilepic", "storycta"}


async def _invoke_user_cmd(interaction, cmd_name, count=None):
    """Lance une commande du UserCog (/name, /username, /profilepic, /bio, /story, /post, /reel)
    depuis un bouton de menu warm-up. Si `count` est fourni et que la commande le supporte,
    on lui passe ce nombre (ex: 12 stories au jour 5, 2 reels au jour 4).
    Récupère le cog au moment du clic → la vue n'a pas besoin de référence au cog."""
    cog = interaction.client.get_cog("UserCog")
    if cog is None:
        await interaction.response.send_message("Module indisponible, réessaie.", ephemeral=True)
        return
    cmd = getattr(cog, cmd_name, None)
    if cmd is None:
        await interaction.response.send_message("Commande indisponible.", ephemeral=True)
        return
    if count is not None and cmd_name in _COUNT_CMDS:
        await cmd.callback(cog, interaction, count)
    else:
        await cmd.callback(cog, interaction)


# Boutons disponibles dans les menus warm-up : cmd -> (label, emoji)
_WARMUP_BTN = {
    "username":   ("Username", "👤"),
    "name":       ("Name", "📝"),
    "profilepic": ("Photo de profil", "🖼"),
    "bio":        ("Bio", "💬"),
    "story":      ("Story", "📖"),
    "post":       ("Post", "🖼️"),
    "reel":       ("Reel", "🎬"),
    "storycta":   ("Story CTA", "📲"),
}


class _WarmupButton(discord.ui.Button):
    """Bouton de menu warm-up : lance une commande du UserCog au clic, avec un nombre
    d'items précis (ex: 12 stories au jour 5). Le nombre est encodé dans le custom_id
    (`warmup:story:12`) pour que le routing après redémarrage retrouve le bon nombre."""

    def __init__(self, cmd, count=None):
        label, emoji = _WARMUP_BTN[cmd]
        if count and count > 1:
            label = f"{label} ×{count}"
        cid = f"warmup:{cmd}" if not count else f"warmup:{cmd}:{count}"
        super().__init__(label=label, emoji=emoji,
                         style=discord.ButtonStyle.primary, custom_id=cid)
        self._cmd = cmd
        self._count = count

    async def callback(self, interaction: discord.Interaction):
        await _invoke_user_cmd(interaction, self._cmd, self._count)


# Mapping jour -> boutons de contenu : (index canonique, libellés titre, [(cmd, nombre)])
# Le `nombre` = ce que l'étape demande de poster (1 story, 2 reels, 12 stories, carrousel=3 photos...).
_WARMUP_DAYS = [
    (1, ("JOUR 0", "DAY 0"), [("name", None), ("username", None)]),
    (3, ("JOUR 1", "DAY 1"), [("profilepic", 1)]),
    (4, ("JOUR 2", "DAY 2"), [("bio", 1), ("story", 1), ("post", 1)]),
    (5, ("JOUR 3", "DAY 3"), [("story", 1), ("post", 1), ("reel", 1)]),
    (6, ("JOUR 4", "DAY 4"), [("story", 1), ("reel", 2)]),
    (7, ("JOUR 5", "DAY 5"), [("story", 12), ("reel", 1)]),
    (8, ("JOUR 6", "DAY 6"), [("story", 1), ("reel", 2), ("storycta", 2)]),
]


def _warmup_items_for(index, title=None):
    """Liste des (cmd, nombre) de cette étape (ou []).
    Détection par index canonique (STEPS) ET par titre (robuste si réordonné via le site)."""
    t = (title or "").upper()
    for day_index, labels, items in _WARMUP_DAYS:
        if index == day_index or any(lbl in t for lbl in labels):
            return items
    return []


def _all_warmup_combos():
    """Toutes les paires (cmd, count) uniques utilisées dans le warm-up."""
    seen = []
    for _, _, items in _WARMUP_DAYS:
        for cmd, count in items:
            if (cmd, count) not in seen:
                seen.append((cmd, count))
    return seen


def warmup_master_view():
    """Vue persistante couvrant TOUTES les paires (bouton, nombre) du warm-up
    (routing des clics après un redémarrage du bot)."""
    view = discord.ui.View(timeout=None)
    for cmd, count in _all_warmup_combos():
        view.add_item(_WarmupButton(cmd, count))
    return view


class _NextButton(discord.ui.Button):
    """Bouton « étape suivante » intégré au message de l'étape (même partie que les boutons)."""

    def __init__(self):
        super().__init__(label="Étape suivante →", style=discord.ButtonStyle.success,
                         custom_id="va_onboarding_next")

    async def callback(self, interaction: discord.Interaction):
        await _advance_step(interaction)


def build_step_view(index, title=None):
    """Vue d'une étape : boutons de contenu du jour + bouton → sur le MÊME message.
    Retourne None s'il n'y a rien à afficher (ne pas envoyer de vue vide)."""
    view = discord.ui.View(timeout=None)
    for cmd, count in _warmup_items_for(index, title):
        view.add_item(_WarmupButton(cmd, count))
    if index < len(STEPS) - 1:
        view.add_item(_NextButton())
    return view if view.children else None


async def _advance_step(interaction: discord.Interaction):
    """Passe à l'étape suivante (lit le footer « Étape X/Y » du message courant)."""
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
    view = build_step_view(next_index, new_embed.title)
    await interaction.response.send_message(embed=new_embed, view=view)
    # Envoyer les medias de l'etape (si presents)
    try:
        await send_step_media(interaction.channel, next_index, bot=interaction.client)
    except Exception as e:
        log.error(f"Erreur send_step_media step {next_index+1}: {e}")


class OnboardingView(discord.ui.View):
    """Vue persistante du bouton → (routing des clics après un redémarrage)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Étape suivante →",
        style=discord.ButtonStyle.success,
        custom_id="va_onboarding_next",
    )
    async def next_step(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _advance_step(interaction)


class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None

    async def cog_load(self):
        self.bot.add_view(OnboardingView())
        self.bot.add_view(warmup_master_view())

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
        view = build_step_view(index, embed.title)
        await interaction.response.send_message(embed=embed, view=view)
        await send_step_media(interaction.channel, index, bot=self.bot)

    @app_commands.command(
        name="resetonboarding",
        description="[ADMIN] Recharge le programme d'onboarding depuis le code (par défaut)",
    )
    async def resetonboarding(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        try:
            import onboarding as _web_ob
            data = _web_ob.reset_to_default()
            n = len(data.get("steps", []))
            await interaction.response.send_message(
                f"✅ Onboarding réinitialisé : **{n} étapes** rechargées depuis le programme du code.\n"
                "⚠️ Les médias attachés via le site ont été détachés — ré-uploade-les si besoin.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur reset : {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Onboarding(bot))
