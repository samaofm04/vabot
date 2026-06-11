"""Welcome flow: auto-message on member join with 'Continuer' button.
Click → creates VA channel + assigns random identity + sends intro with payment info + 'Commencer' button.
Click → posts step 1 of onboarding.
"""
import os
import json
import asyncio
import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Union
import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger("vabot.welcome")

BOT_DIR = Path(__file__).parent.parent.resolve()
ENV_FILE = BOT_DIR / ".env"
DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
USERS_FILE = DATA_DIR / "users.json"
WHITELIST_FILE = DATA_DIR / "whitelist.json"
WELCOME_CONFIG_FILE = DATA_DIR / "welcome_config.json"


def _write_env_var(key: str, value: str) -> bool:
    """Ecrit/remplace une variable dans .env. Retourne True si OK."""
    try:
        if ENV_FILE.exists():
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        else:
            lines = []
        found = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        content = "\n".join(new_lines).rstrip("\n") + "\n"
        ENV_FILE.write_text(content, encoding="utf-8")
        try:
            os.chmod(ENV_FILE, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        log.error(f"Erreur ecriture .env: {e}")
        return False


def _schedule_exit(delay_sec: float = 3.0):
    """Exit process apres delay -> systemd auto-restart."""
    def _do_exit():
        time.sleep(delay_sec)
        log.warning("Exit demande -> systemd va relancer le bot")
        os._exit(0)
    threading.Thread(target=_do_exit, daemon=True).start()
PENDING_DELETIONS_FILE = DATA_DIR / "pending_deletions.json"
INTRO_IMAGES_DIR = DATA_DIR / "intro_images"  # photos attachees a l'intro paiement

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def list_intro_images():
    """Retourne la liste triee des fichiers image du dossier intro_images."""
    if not INTRO_IMAGES_DIR.exists():
        return []
    return sorted(
        p for p in INTRO_IMAGES_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )


def build_intro_files():
    """Construit la liste de discord.File pour les photos d'intro (max 10)."""
    return [discord.File(str(p)) for p in list_intro_images()[:10]]

DEFAULT_WELCOME_CONFIG = {
    "welcome_channel_id": None,
    "cleanup_days_after_leave": 7,
    "hide_all_channels_from_va": True,  # cache tous les salons aux VAs sauf leur ticket
    "extra_visible_channel_ids": [],  # exceptions: salons que les VAs peuvent voir
    "assignment_mode": "round_robin",  # "round_robin" ou "random"
    "rotation_pool": [],  # identites restantes dans le tour actuel
    "auto_create_ticket_on_join": True,  # True = ticket cree direct, False = passe par bouton "Continuer"
    "welcome_public_message": (
        "👋 **Bienvenue dans l'agence {mention} !**\n\n"
        "Tu es là parce que tu vas bosser avec nous comme VA. "
        "Pour démarrer, clique sur **Continuer** ci-dessous : ton salon perso sera créé "
        "automatiquement et on commencera l'onboarding ensemble.\n\n"
        "↓"
    ),
    "ticket_intro_message": (
        "🎫 **Bienvenue {mention} !**\n\n"
        "Voici comment fonctionne le **paiement** dans l'agence :\n\n"
        "💰 **PAIEMENT PRINCIPAL** *(clics FR/jour, payés tous les 1 et 16 du mois)*\n"
        "• 50 clics/jour → **30 $**\n"
        "• 100 clics/jour → **50 $**\n"
        "• 200 clics/jour → **75 $**\n"
        "• 500 clics/jour → **150 $**\n"
        "• 1 000 clics/jour → **300 $**\n"
        "*+ paliers supérieurs pour très gros volumes.*\n\n"
        "🎁 **BONUS CLICS** *(comptés sur chaque période 1→15 / 16→fin du mois)*\n"
        "• 500 clics → **+20 $**\n"
        "• 1 000 clics → **+30 $**\n"
        "• 2 000 clics → **+50 $**\n"
        "*Au-delà de 2 000 clics : +20 $ tous les 1 000 clics supplémentaires, sans limite.*\n\n"
        "📈 **BONUS ABONNÉS**\n"
        "• 600 abonnés gagnés → **+15 $**\n"
        "• 2 000 abonnés → **+20 $**\n"
        "• 5 000 abonnés → **+30 $**\n"
        "*Et plus de bonus à chaque palier supérieur.*\n\n"
        "Les primes dépendent des **performances réelles** du compte : publications, reels, "
        "activité, croissance et engagement. Plus le compte performe grâce à ton travail, "
        "plus tu débloques de récompenses.\n\n"
        "**En résumé :**\n"
        "✅ Tu gagnes grâce aux clics\n"
        "✅ Tu débloques des bonus grâce aux performances\n"
        "✅ Plus les chiffres montent, plus les primes augmentent\n\n"
        "Clique sur **🎬 Commencer l'onboarding** ci-dessous quand tu es prêt.\n\n"
        "↓"
    ),
    # Version de la config: incrementer pour forcer la mise a jour d'un message
    # cote VPS au prochain demarrage du bot (migration automatique).
    "config_version": 2,
}


def load_welcome_config():
    if not WELCOME_CONFIG_FILE.exists():
        save_welcome_config(DEFAULT_WELCOME_CONFIG)
        return dict(DEFAULT_WELCOME_CONFIG)
    try:
        cfg = json.loads(WELCOME_CONFIG_FILE.read_text(encoding="utf-8"))
        # Migration: si la config sauvegardee a une version plus ancienne,
        # on force la reecriture des champs "message" pour appliquer les nouveaux
        # textes par defaut. Apres migration on bump la version.
        current_version = cfg.get("config_version", 1)
        target_version = DEFAULT_WELCOME_CONFIG.get("config_version", 1)
        if current_version < target_version:
            cfg["ticket_intro_message"] = DEFAULT_WELCOME_CONFIG["ticket_intro_message"]
            cfg["welcome_public_message"] = DEFAULT_WELCOME_CONFIG["welcome_public_message"]
            cfg["config_version"] = target_version
            save_welcome_config(cfg)
            log.info(f"welcome_config migre de v{current_version} -> v{target_version}")
        merged = dict(DEFAULT_WELCOME_CONFIG)
        merged.update(cfg)
        return merged
    except Exception:
        return dict(DEFAULT_WELCOME_CONFIG)


def save_welcome_config(cfg):
    WELCOME_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    WELCOME_CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def load_pending():
    if not PENDING_DELETIONS_FILE.exists():
        return {}
    try:
        return json.loads(PENDING_DELETIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_pending(pending):
    PENDING_DELETIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_DELETIONS_FILE.write_text(json.dumps(pending, indent=2, ensure_ascii=False), encoding="utf-8")


IDENTITIES_CONFIG_FILE = DATA_DIR / "identities_config.json"


def load_identities_config():
    if not IDENTITIES_CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(IDENTITIES_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_identities_config(cfg):
    IDENTITIES_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDENTITIES_CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def is_identity_active(name):
    cfg = load_identities_config()
    entry = cfg.get(name)
    if isinstance(entry, dict):
        return entry.get("enabled", True)
    return True  # par defaut actif


def list_identities():
    """Toutes les identités existantes (active ou non)."""
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())


# Identités réservées à Jailbreak : JAMAIS assignées aux VAs Discord (pas de
# salon général, gérées dans le système Jailbreak). Aligné avec web_upload.py.
JAILBREAK_ONLY_IDENTITIES = {"jessye"}


def list_active_identities():
    """Seulement les identités activées (utilisées pour les nouvelles assignations).
    Exclut les identités jailbreak-only (jamais assignées aux VAs Discord)."""
    jb = {x.lower() for x in JAILBREAK_ONLY_IDENTITIES}
    return [n for n in list_identities()
            if is_identity_active(n) and n.strip().lower() not in jb]


def pick_next_identity():
    """Pick the next identity based on assignment_mode (round_robin par defaut).
    N'utilise que les identités actives (enabled).
    """
    cfg = load_welcome_config()
    identities = list_active_identities()
    if not identities:
        return None
    mode = cfg.get("assignment_mode", "round_robin")
    if mode == "random":
        return random.choice(identities)
    # Round robin
    pool = cfg.get("rotation_pool", [])
    # Filtrer le pool pour ne garder que les identites actives
    pool = [p for p in pool if p in identities]
    # Si pool vide ou trop petit, recharger avec toutes les identites actives melangees
    if not pool:
        pool = list(identities)
        random.shuffle(pool)
    picked = pool.pop(0)
    cfg["rotation_pool"] = pool
    save_welcome_config(cfg)
    return picked


def find_identity_category(guild, identity):
    """Trouve la categorie portant le nom de l'identite (case-insensitive)."""
    target = identity.lower().strip()
    for cat in guild.categories:
        if cat.name.lower().strip() == target:
            return cat
    return None


def find_general_channel_for_identity(guild, identity):
    """Trouve le salon general-<identity> (case-insensitive, ignore accents)."""
    target = (identity or "").strip().lower()
    if not target:
        return None
    for ch in guild.text_channels:
        norm = ch.name.lower().replace("é", "e").replace("è", "e")
        if not norm.startswith("general-"):
            continue
        suffix = norm[len("general-"):].strip()
        if suffix == target:
            return ch
    return None


async def sync_general_channel_access(guild, member, identity):
    """Donne au VA l'acces au salon general-<identity> et le RETIRE des autres
    general-*. Best-effort, ignore les erreurs silencieusement.

    Si identity est vide/None : retire l'overwrite specifique du membre sur
    TOUS les salons general-* (utilise par /resetva).
    """
    ident_lc = (identity or "").strip().lower()
    for ch in guild.text_channels:
        norm = ch.name.lower().replace("é", "e").replace("è", "e")
        if not norm.startswith("general-"):
            continue
        suffix = norm[len("general-"):].strip()
        try:
            if ident_lc and suffix == ident_lc:
                await ch.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    reason=f"VA assignee a {ident_lc} - acces au general",
                )
            else:
                # retire l'overwrite specifique au membre (laisse les roles)
                if ch.overwrites_for(member).view_channel is not None:
                    await ch.set_permissions(
                        member,
                        overwrite=None,
                        reason=f"VA retiree de {suffix}" if ident_lc else "VA reset",
                    )
        except Exception:
            pass


async def create_va_channel(guild, member, identity):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_messages=True, attach_files=True
        ),
    }
    base_name = f"va-{member.name}".lower().replace(" ", "-")[:90]
    category = find_identity_category(guild, identity)
    try:
        return await guild.create_text_channel(
            name=base_name, overwrites=overwrites, category=category
        )
    except discord.Forbidden:
        return None


async def setup_va_ticket(guild, member):
    """Cree le ticket d'un VA: assignation identite + salon + intro.

    Retourne (channel, error_message_or_None).
    Reutilise une assignation existante si elle existe.
    Si l'user a deja un salon valide, le renvoie tel quel.
    """
    users = load_users()
    existing = users.get(str(member.id))

    # Si user a deja un salon valide, le re-utiliser
    if isinstance(existing, dict) and existing.get("channel_id"):
        existing_channel = guild.get_channel(existing["channel_id"])
        if existing_channel:
            try:
                await existing_channel.set_permissions(
                    member,
                    view_channel=True, send_messages=True,
                    read_message_history=True, attach_files=True,
                )
            except Exception:
                pass
            # Re-sync l'acces au general (au cas ou il aurait ete perdu)
            ident_existing = existing.get("identity") if isinstance(existing, dict) else None
            if ident_existing:
                try:
                    await sync_general_channel_access(guild, member, ident_existing)
                except Exception:
                    pass
            return existing_channel, None
        # Salon supprime -> clear et continuer comme nouveau VA
        users.pop(str(member.id), None)
        save_users(users)
        existing = None

    # Determiner l'identite
    if isinstance(existing, dict) and existing.get("identity"):
        identity = existing["identity"]
    elif isinstance(existing, str):
        identity = existing
    else:
        identity = pick_next_identity()
        if not identity:
            return None, "Aucune identité disponible. Préviens un admin."

    # Creer le salon
    channel = await create_va_channel(guild, member, identity)
    if not channel:
        return None, "Le bot n'a pas la permission de créer un salon."

    # Sauvegarder
    users[str(member.id)] = {
        "identity": identity,
        "channel_id": channel.id,
        "auto_post": True,
    }
    save_users(users)

    # Envoyer le message intro (avec photos optionnelles)
    cfg = load_welcome_config()
    intro_text = cfg["ticket_intro_message"].replace("\\n", "\n").format(mention=member.mention)
    files = build_intro_files()
    try:
        await channel.send(content=intro_text, view=StartOnboardingView(), files=files or None)
    except Exception as e:
        log.error(f"setup_va_ticket: erreur envoi intro: {e}")

    # Cacher TOUS les salons au VA sauf son ticket + le general-<identite> (anonymat)
    general_ch = find_general_channel_for_identity(guild, identity)
    if cfg.get("hide_all_channels_from_va", True):
        own_id = channel.id
        extra_visible = set(cfg.get("extra_visible_channel_ids", []))
        skip_ids = {own_id, *extra_visible}
        if general_ch:
            skip_ids.add(general_ch.id)
        for ch in guild.channels:
            if ch.id in skip_ids:
                continue
            if isinstance(ch, discord.CategoryChannel):
                continue
            try:
                await ch.set_permissions(
                    member,
                    view_channel=False,
                    reason="VA isolation - anonymat",
                )
            except Exception:
                pass

    # Donne acces au salon general de l'identite (apres le hide pour garantir l'ordre)
    try:
        await sync_general_channel_access(guild, member, identity)
    except Exception as e:
        log.warning(f"setup_va_ticket: sync_general_channel_access erreur: {e}")

    return channel, None


class StartOnboardingView(discord.ui.View):
    """2e bouton : dans le salon perso du VA, démarre l'onboarding."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎬 Commencer l'onboarding",
        style=discord.ButtonStyle.success,
        custom_id="va_start_onboarding",
    )
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verifier que c'est bien le VA proprietaire du salon qui clique
        from cogs.onboarding import step_embed, OnboardingView, send_step_media
        embed = step_embed(0)
        await interaction.response.send_message(
            content=interaction.user.mention, embed=embed, view=OnboardingView()
        )
        try:
            await send_step_media(interaction.channel, 0, bot=interaction.client)
        except Exception:
            pass


class WelcomeContinueView(discord.ui.View):
    """1er bouton : dans le salon welcome public, clic pour creer le ticket."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ Continuer",
        style=discord.ButtonStyle.primary,
        custom_id="welcome_continue",
    )
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Doit etre utilise dans un serveur.", ephemeral=True)
            return

        channel, error = await setup_va_ticket(guild, interaction.user)
        if error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        # Supprimer le message welcome public maintenant que le VA a son ticket
        try:
            if interaction.message:
                await interaction.message.delete()
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Ton salon a été créé : {channel.mention}\nRends-toi là-bas pour commencer.",
            ephemeral=True,
        )


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self.check_pending_deletions.start()
        self.auto_sort_channels.start()
        self.auto_secure_general_channels.start()

    def cog_unload(self):
        self.check_pending_deletions.cancel()
        self.auto_sort_channels.cancel()
        self.auto_secure_general_channels.cancel()

    async def cog_load(self):
        # Persistent views (survivent au restart)
        self.bot.add_view(WelcomeContinueView())
        self.bot.add_view(StartOnboardingView())

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

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Quand un nouveau membre rejoint:
        - si auto_create_ticket_on_join=True (defaut): cree direct le ticket
        - sinon: envoie un message dans le salon welcome avec bouton Continuer
        """
        if member.bot:
            return
        # Si l'user avait une suppression planifiee, l'annuler (il est revenu)
        pending = load_pending()
        if str(member.id) in pending:
            del pending[str(member.id)]
            save_pending(pending)
            log.info(f"on_member_join: suppression annulee pour {member.id} (revenu sur le serveur)")
        cfg = load_welcome_config()

        # Mode auto-ticket: cree direct le salon, sans passer par le welcome public
        if cfg.get("auto_create_ticket_on_join", True):
            try:
                channel, error = await setup_va_ticket(member.guild, member)
                if error:
                    log.error(f"on_member_join auto-ticket: {error} (member={member.id})")
                else:
                    log.info(f"on_member_join: ticket cree automatiquement pour {member.id} -> {channel.id}")
            except Exception as e:
                log.error(f"on_member_join auto-ticket exception: {e}")
            return

        # Mode classique: envoyer un message welcome avec bouton Continuer
        channel_id = cfg.get("welcome_channel_id")
        if not channel_id:
            log.warning(f"on_member_join: aucun welcome_channel_id configuré, member={member.id}")
            return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            log.warning(f"on_member_join: welcome_channel_id={channel_id} introuvable")
            return
        # Reset override perso (ancien VA revenu) sinon ils voient pas le message
        try:
            await channel.set_permissions(member, overwrite=None, reason="Reset override au rejoin")
        except Exception:
            pass
        try:
            text = cfg["welcome_public_message"].replace("\\n", "\n").format(mention=member.mention)
            await channel.send(content=text, view=WelcomeContinueView())
        except Exception as e:
            log.error(f"on_member_join: erreur envoi welcome: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Quand un membre quitte, planifier la suppression de son salon dans N jours."""
        if member.bot:
            return
        users = load_users()
        data = users.get(str(member.id))
        if not isinstance(data, dict) or not data.get("channel_id"):
            return
        cfg = load_welcome_config()
        days = cfg.get("cleanup_days_after_leave", 7)
        delete_at = datetime.now(timezone.utc) + timedelta(days=days)
        pending = load_pending()
        pending[str(member.id)] = {
            "channel_id": data["channel_id"],
            "guild_id": member.guild.id,
            "delete_at": delete_at.isoformat(),
            "user_name": str(member),
        }
        save_pending(pending)
        log.info(f"on_member_remove: suppression de {data['channel_id']} planifiee pour {member.id} a {delete_at.isoformat()}")

    @tasks.loop(hours=1)
    async def check_pending_deletions(self):
        """Verifie chaque heure les suppressions a effectuer."""
        pending = load_pending()
        if not pending:
            return
        now = datetime.now(timezone.utc)
        to_remove = []
        for user_id, data in list(pending.items()):
            try:
                delete_at = datetime.fromisoformat(data["delete_at"])
            except Exception:
                to_remove.append(user_id)
                continue
            if delete_at > now:
                continue
            # Suppression
            guild = self.bot.get_guild(data.get("guild_id"))
            if guild:
                channel = guild.get_channel(data.get("channel_id"))
                if channel:
                    try:
                        await channel.delete(reason="Auto-cleanup : VA a quitte le serveur depuis trop longtemps")
                        log.info(f"Salon {channel.id} supprime (VA {user_id} parti)")
                    except Exception as e:
                        log.error(f"Erreur suppression salon {data.get('channel_id')}: {e}")
            # Nettoyer users.json
            users = load_users()
            if user_id in users:
                del users[user_id]
                save_users(users)
            to_remove.append(user_id)
        for uid in to_remove:
            pending.pop(uid, None)
        if to_remove:
            save_pending(pending)

    @check_pending_deletions.before_loop
    async def before_check_deletions(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=10)
    async def auto_sort_channels(self):
        """Toutes les 10 min, range les salons va-* dans la bonne categorie
        d'identite (si l'admin les a deplaces, ou s'ils ont ete crees sans
        categorie). Silencieux : aucun message envoye, juste les moves."""
        try:
            users = load_users()
            if not users:
                return
            for guild in self.bot.guilds:
                # Pre-construit la map nom_category_lower -> CategoryChannel
                cat_map = {c.name.lower().strip(): c for c in guild.categories}
                for user_id, data in users.items():
                    ident = data if isinstance(data, str) else (data.get("identity") if isinstance(data, dict) else None)
                    channel_id = data.get("channel_id") if isinstance(data, dict) else None
                    if not ident or not channel_id:
                        continue
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue
                    target = ident.lower().strip()
                    category = cat_map.get(target)
                    if not category:
                        continue  # pas de categorie matching, skip silencieusement
                    if channel.category_id == category.id:
                        continue  # deja au bon endroit
                    try:
                        await channel.edit(
                            category=category,
                            reason="Auto-sort : range salon VA dans sa categorie d'identite",
                        )
                        log.info(f"auto_sort: {channel.name} -> {category.name}")
                    except discord.Forbidden:
                        pass  # permission refusee
                    except Exception as e:
                        log.warning(f"auto_sort: erreur {channel.name}: {e}")
        except Exception as e:
            log.error(f"auto_sort_channels erreur globale: {e}")

    @auto_sort_channels.before_loop
    async def before_auto_sort(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=10)
    async def auto_secure_general_channels(self):
        """Toutes les 10 min, securise les salons general-<identity> :
        - @everyone view_channel=False (cache par defaut)
        - chaque VA de l'identite X a view_channel=True sur general-X
        - les autres VAs (qui ne sont plus sur cette identite) sont retires.

        Silencieux : pas de message envoye.
        """
        try:
            users = load_users()
            for guild in self.bot.guilds:
                # Build identity_lower -> set of Member objects (VAs actifs)
                identity_to_members = {}
                for user_id, data in users.items():
                    ident = data if isinstance(data, str) else (
                        data.get("identity") if isinstance(data, dict) else None
                    )
                    if not ident:
                        continue
                    try:
                        member = guild.get_member(int(user_id))
                    except Exception:
                        member = None
                    if not member:
                        continue
                    identity_to_members.setdefault(
                        ident.lower().strip(), set()
                    ).add(member)

                for ch in guild.text_channels:
                    norm = ch.name.lower().replace("é", "e").replace("è", "e")
                    if not norm.startswith("general-"):
                        continue
                    suffix = norm[len("general-"):].strip()

                    # 1) @everyone : cache le salon par defaut
                    everyone = guild.default_role
                    if ch.overwrites_for(everyone).view_channel is not False:
                        try:
                            await ch.set_permissions(
                                everyone,
                                view_channel=False,
                                reason="Auto-secure: restreint au identite",
                            )
                        except Exception:
                            pass

                    # 2) Grant view aux VAs de cette identite
                    expected = identity_to_members.get(suffix, set())
                    for member in expected:
                        if ch.overwrites_for(member).view_channel is not True:
                            try:
                                await ch.set_permissions(
                                    member,
                                    view_channel=True,
                                    send_messages=True,
                                    read_message_history=True,
                                    attach_files=True,
                                    reason=f"Auto-secure: VA assignee a {suffix}",
                                )
                            except Exception:
                                pass

                    # 3) Remove l'overwrite des VAs qui ne sont pas/plus sur cette identite
                    for target, ow in list(ch.overwrites.items()):
                        if not isinstance(target, discord.Member):
                            continue
                        if target in expected:
                            continue
                        # Garde le bot lui-meme
                        if target == guild.me:
                            continue
                        # Garde le STAFF (boss / admins) : ne JAMAIS leur retirer
                        # l'acces aux generaux, sinon le boss ne voit plus general-X
                        # des identites ou il n'est pas assigne comme VA.
                        try:
                            gp = target.guild_permissions
                            if gp.administrator or gp.manage_guild or gp.manage_channels:
                                continue
                        except Exception:
                            pass
                        if ow.view_channel is not None:
                            try:
                                await ch.set_permissions(
                                    target,
                                    overwrite=None,
                                    reason="Auto-secure: VA pas sur cette identite",
                                )
                            except Exception:
                                pass
        except Exception as e:
            log.error(f"auto_secure_general_channels erreur: {e}")

    @auto_secure_general_channels.before_loop
    async def before_auto_secure(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="setwelcomechannel", description="[ADMIN] Définit le salon où arrivera le welcome auto + configure perms")
    @app_commands.describe(channel="Le salon (laisse vide pour utiliser le salon courant)")
    async def setwelcomechannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not await self.require_admin(interaction):
            return
        target = channel or interaction.channel
        cfg = load_welcome_config()
        cfg["welcome_channel_id"] = target.id
        save_welcome_config(cfg)
        perms_msg = ""
        try:
            await target.set_permissions(
                target.guild.default_role,
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                reason="Welcome channel: read-only pour @everyone",
            )
            perms_msg = (
                "\n✅ Permissions @everyone : voit le salon mais ne peut **pas écrire**.\n"
                "💡 Les messages de bienvenue s'auto-suppriment quand un VA clique sur Continuer "
                "→ le salon reste propre, les nouveaux VAs ne voient que leur message."
            )
        except Exception as e:
            perms_msg = f"\n⚠️ Impossible de configurer les permissions : {e}"
        await interaction.response.send_message(
            f"✅ Salon welcome auto : {target.mention}{perms_msg}",
            ephemeral=True,
        )

    @app_commands.command(
        name="autoticket",
        description="[ADMIN] True = ticket cree direct quand un VA rejoint, False = bouton Continuer",
    )
    @app_commands.describe(enabled="True (defaut) = auto, False = mode classique avec bouton")
    async def autoticket(self, interaction: discord.Interaction, enabled: bool):
        if not await self.require_admin(interaction):
            return
        cfg = load_welcome_config()
        cfg["auto_create_ticket_on_join"] = enabled
        save_welcome_config(cfg)
        if enabled:
            msg = (
                "✅ **Auto-ticket activé**\n\n"
                "Quand un VA rejoint, son salon est créé **automatiquement** "
                "sans passer par le salon welcome."
            )
        else:
            msg = (
                "✅ **Auto-ticket désactivé**\n\n"
                "Quand un VA rejoint, il reçoit un message dans le salon welcome "
                "avec le bouton **Continuer** pour créer son ticket."
            )
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="setwelcomemessage", description="[ADMIN] Modifie le message de bienvenue public (\\n pour retour ligne)")
    @app_commands.describe(message="Nouveau message complet du welcome public")
    async def setwelcomemessage(self, interaction: discord.Interaction, message: str):
        if not await self.require_admin(interaction):
            return
        cfg = load_welcome_config()
        cfg["welcome_public_message"] = message
        save_welcome_config(cfg)
        preview = message.replace("\\n", "\n").replace("{mention}", interaction.user.mention)
        await interaction.response.send_message(
            f"✅ Message welcome mis à jour. Preview :\n\n{preview[:1800]}",
            ephemeral=True,
        )

    @app_commands.command(name="setticketintrofile", description="[ADMIN] Modifie le message d'intro du ticket via fichier .txt (pratique pour long texte)")
    @app_commands.describe(file="Fichier .txt avec le texte complet (\\n = retour ligne automatique)")
    async def setticketintrofile(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self.require_admin(interaction):
            return
        if not file.filename.lower().endswith(".txt"):
            await interaction.response.send_message("Le fichier doit être un .txt", ephemeral=True)
            return
        content = (await file.read()).decode("utf-8", errors="ignore").strip()
        cfg = load_welcome_config()
        cfg["ticket_intro_message"] = content
        save_welcome_config(cfg)
        preview = content.replace("\\n", "\n").replace("{mention}", interaction.user.mention)
        await interaction.response.send_message(
            f"✅ Message ticket mis à jour depuis fichier. Preview :\n\n{preview[:1800]}",
            ephemeral=True,
        )

    @app_commands.command(name="welcomesettings", description="[ADMIN] Voir la config du welcome")
    async def welcomesettings(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        cfg = load_welcome_config()
        channel_id = cfg.get("welcome_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        text = (
            "⚙️ **Config welcome**\n"
            f"Salon welcome : {channel.mention if channel else '❌ Non configuré'}\n\n"
            "**Message public :**\n"
            f"```\n{cfg.get('welcome_public_message', '')[:500]}\n```\n"
            "**Message ticket (privé) :**\n"
            f"```\n{cfg.get('ticket_intro_message', '')[:500]}\n```"
        )
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="cleanupdays", description="[ADMIN] Délai avant suppression auto du salon quand un VA quitte")
    @app_commands.describe(days="Nombre de jours (défaut: 7)")
    async def cleanupdays(self, interaction: discord.Interaction, days: int):
        if not await self.require_admin(interaction):
            return
        if days < 0 or days > 365:
            await interaction.response.send_message("Doit être entre 0 et 365.", ephemeral=True)
            return
        cfg = load_welcome_config()
        cfg["cleanup_days_after_leave"] = days
        save_welcome_config(cfg)
        await interaction.response.send_message(
            f"✅ Suppression auto : **{days} jour(s)** après le départ d'un VA.",
            ephemeral=True,
        )

    @app_commands.command(
        name="showsalon",
        description="[ADMIN] Rendre un salon (texte OU vocal) visible par TOUS les VAs",
    )
    @app_commands.describe(salon="Le salon ou vocal a rendre visible aux VAs (existants + futurs)")
    async def showsalon(
        self,
        interaction: discord.Interaction,
        salon: Union[discord.TextChannel, discord.VoiceChannel, discord.StageChannel],
    ):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        # 1) Ajoute a la liste blanche -> les FUTURS VAs ne seront plus isoles de ce salon
        cfg = load_welcome_config()
        ids = list(cfg.get("extra_visible_channel_ids", []))
        already = salon.id in ids
        if not already:
            ids.append(salon.id)
            cfg["extra_visible_channel_ids"] = ids
            save_welcome_config(cfg)
        # 2) Debloque les VAs EXISTANTS : retire l'overwrite view_channel=False
        #    pose par l'isolation. Pour un VOCAL : on autorise aussi a REJOINDRE
        #    (connect), pas juste a voir.
        is_voice = isinstance(salon, (discord.VoiceChannel, discord.StageChannel))
        fixed = 0
        for target, ow in list(salon.overwrites.items()):
            if isinstance(target, discord.Member) and ow.view_channel is False:
                try:
                    if is_voice:
                        await salon.set_permissions(
                            target, view_channel=True, connect=True,
                            reason="showsalon - vocal visible aux VAs",
                        )
                    else:
                        await salon.set_permissions(
                            target, view_channel=True,
                            reason="showsalon - rendre visible aux VAs",
                        )
                    fixed += 1
                except Exception:
                    pass
        kind = "vocal" if is_voice else "salon"
        extra = " (voir + rejoindre)" if is_voice else ""
        await interaction.followup.send(
            f"✅ {salon.mention} ({kind}) est maintenant visible par les VAs.\n"
            f"• Liste blanche : {'déjà présent' if already else 'ajouté'} (futurs VAs ✅)\n"
            f"• {fixed} VA(s) existant(s) débloqué(s){extra}.\n\n"
            f"_Relance la commande pour chaque salon/vocal d'aide à rendre visible._",
            ephemeral=True,
        )

    @app_commands.command(
        name="hidesalon",
        description="[ADMIN] Re-cacher un salon/vocal aux VAs (inverse de /showsalon)",
    )
    @app_commands.describe(salon="Le salon ou vocal a cacher aux VAs (ex: bienvenue, payement)")
    async def hidesalon(
        self,
        interaction: discord.Interaction,
        salon: Union[discord.TextChannel, discord.VoiceChannel, discord.StageChannel],
    ):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("À utiliser dans un serveur.", ephemeral=True)
            return
        # 1) Retire de la liste blanche -> les futurs VAs seront isoles de ce salon
        cfg = load_welcome_config()
        ids = list(cfg.get("extra_visible_channel_ids", []))
        if salon.id in ids:
            ids.remove(salon.id)
            cfg["extra_visible_channel_ids"] = ids
            save_welcome_config(cfg)
        # 2) Cache pour chaque VA EXISTANT (membre dans users.json). On ne touche
        #    JAMAIS au staff (boss / admins) pour ne pas leur cacher le salon.
        users = load_users()
        hidden = 0
        for uid in list(users.keys()):
            if not str(uid).isdigit():
                continue
            member = guild.get_member(int(uid))
            if member is None:
                continue
            try:
                gp = member.guild_permissions
                if gp.administrator or gp.manage_guild or gp.manage_channels:
                    continue
            except Exception:
                pass
            try:
                await salon.set_permissions(
                    member, view_channel=False,
                    reason="hidesalon - cacher aux VAs",
                )
                hidden += 1
            except Exception:
                pass
        await interaction.followup.send(
            f"✅ {salon.mention} est maintenant **caché** aux VAs.\n"
            f"• Retiré de la liste blanche (futurs VAs isolés ✅)\n"
            f"• {hidden} VA(s) existant(s) recaché(s).\n"
            f"_(le staff garde l'accès)_",
            ephemeral=True,
        )

    @app_commands.command(name="pendingdeletions", description="[ADMIN] Liste les VAs partis dont le salon va être supprimé")
    async def pendingdeletions(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        pending = load_pending()
        if not pending:
            await interaction.response.send_message("Aucune suppression planifiée.", ephemeral=True)
            return
        lines = []
        for uid, data in pending.items():
            try:
                delete_at = datetime.fromisoformat(data["delete_at"])
                delta = delete_at - datetime.now(timezone.utc)
                days_left = max(0, delta.days)
                hours_left = max(0, int(delta.total_seconds() / 3600))
            except Exception:
                days_left = "?"
                hours_left = "?"
            name = data.get("user_name", uid)
            lines.append(f"• `{name}` (id: {uid}) → suppression dans **{days_left}j** ({hours_left}h)")
        await interaction.response.send_message(
            f"**Suppressions planifiées** ({len(pending)})\n" + "\n".join(lines[:20]),
            ephemeral=True,
        )

    @app_commands.command(name="canceldeletion", description="[ADMIN] Annule la suppression planifiée pour un VA")
    @app_commands.describe(user="Le VA dont annuler la suppression")
    async def canceldeletion(self, interaction: discord.Interaction, user: discord.User):
        if not await self.require_admin(interaction):
            return
        pending = load_pending()
        if str(user.id) not in pending:
            await interaction.response.send_message(
                f"Aucune suppression planifiée pour {user.mention}.", ephemeral=True
            )
            return
        del pending[str(user.id)]
        save_pending(pending)
        await interaction.response.send_message(
            f"✅ Suppression annulée pour {user.mention}. Son salon est conservé.",
            ephemeral=True,
        )




    @app_commands.command(name="resetva", description="[ADMIN] Reset complet d'un VA: efface assignation + supprime son salon")
    @app_commands.describe(
        user="Le VA à reset",
        delete_channel="True = supprime aussi son salon (défaut True)"
    )
    async def resetva(self, interaction: discord.Interaction, user: discord.Member, delete_channel: bool = True):
        if not await self.require_admin(interaction):
            return
        users = load_users()
        existing = users.get(str(user.id))
        deleted = False
        if delete_channel and isinstance(existing, dict) and existing.get("channel_id"):
            channel = interaction.guild.get_channel(existing["channel_id"])
            if channel:
                try:
                    await channel.delete(reason="Reset VA")
                    deleted = True
                except Exception:
                    pass
        users.pop(str(user.id), None)
        save_users(users)
        # Aussi clear les pending deletions
        pending = load_pending()
        pending.pop(str(user.id), None)
        save_pending(pending)
        # Retire l'acces a TOUS les salons general-*
        try:
            await sync_general_channel_access(interaction.guild, user, "")
        except Exception:
            pass
        msg = f"✅ {user.mention} reseté complètement."
        if deleted:
            msg += " Salon supprimé."
        await interaction.response.send_message(msg, ephemeral=True)


    @app_commands.command(name="assignmentmode", description="[ADMIN] Mode d'attribution: round_robin (équitable) ou random (aléatoire)")
    @app_commands.describe(mode="round_robin (chacune une fois avant repetition) ou random (aleatoire pur)")
    @app_commands.choices(mode=[
        app_commands.Choice(name="round_robin (équitable)", value="round_robin"),
        app_commands.Choice(name="random (aléatoire pur)", value="random"),
    ])
    async def assignmentmode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        if not await self.require_admin(interaction):
            return
        cfg = load_welcome_config()
        cfg["assignment_mode"] = mode.value
        if mode.value == "round_robin":
            # Reset le pool
            cfg["rotation_pool"] = []
        save_welcome_config(cfg)
        if mode.value == "round_robin":
            explanation = "Chaque identité sera attribuée une fois avant qu'aucune ne soit ré-utilisée."
        else:
            explanation = "Tirage aléatoire pur (peut répéter)."
        await interaction.response.send_message(
            f"✅ Mode d'attribution : **{mode.name}**\n{explanation}",
            ephemeral=True,
        )

    @app_commands.command(name="rotationstatus", description="[ADMIN] Voir l'état du round-robin (identités restantes dans le tour)")
    async def rotationstatus(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        cfg = load_welcome_config()
        identities = list_identities()
        pool = cfg.get("rotation_pool", [])
        pool = [p for p in pool if p in identities]
        mode = cfg.get("assignment_mode", "round_robin")
        msg = f"⚙️ **Mode :** `{mode}`\n\n"
        if mode == "round_robin":
            if pool:
                msg += f"**Identités restantes dans ce tour** ({len(pool)}) : `{', '.join(pool)}`"
            else:
                msg += "🔄 Pool vide. Au prochain VA, le tour repart avec toutes les identités."
        else:
            msg += "Mode random pur : pas de tour à suivre."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="toggleidentity", description="[ADMIN] Active/désactive une identité (donnees preservees)")
    @app_commands.describe(name="Nom de l'identité", enabled="True = active, False = désactivée (skip lors des assignations)")
    async def toggleidentity(self, interaction: discord.Interaction, name: str, enabled: bool):
        if not await self.require_admin(interaction):
            return
        safe = name.lower().strip()
        if safe not in list_identities():
            await interaction.response.send_message(
                f"Identité `{safe}` introuvable. Voir /listidentites.", ephemeral=True
            )
            return
        cfg = load_identities_config()
        cfg.setdefault(safe, {})["enabled"] = enabled
        save_identities_config(cfg)
        # Aussi nettoyer le pool de rotation
        welcome_cfg = load_welcome_config()
        pool = welcome_cfg.get("rotation_pool", [])
        if not enabled and safe in pool:
            pool.remove(safe)
            welcome_cfg["rotation_pool"] = pool
            save_welcome_config(welcome_cfg)
        await interaction.response.send_message(
            f"✅ Identité `{safe}` : {'**activée**' if enabled else '**désactivée** (skip lors des nouvelles assignations)'}",
            ephemeral=True,
        )

    @app_commands.command(name="identitystatus", description="[ADMIN] Voir le statut activé/désactivé de chaque identité")
    async def identitystatus(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        identities = list_identities()
        if not identities:
            await interaction.response.send_message("Aucune identité.", ephemeral=True)
            return
        lines = []
        for n in identities:
            status = "✅ Active" if is_identity_active(n) else "❌ Désactivée"
            lines.append(f"• `{n}` — {status}")
        await interaction.response.send_message(
            f"**Statut des identités** ({len(identities)})\n" + "\n".join(lines),
            ephemeral=True,
        )


    @app_commands.command(name="welcometest", description="[ADMIN] Simule l'arrivée d'un membre")
    @app_commands.describe(user="Sur quel user simuler (défaut: toi)")
    async def welcometest(self, interaction: discord.Interaction, user: discord.Member = None):
        if not await self.require_admin(interaction):
            return
        target = user or interaction.user
        await self.on_member_join(target)
        await interaction.response.send_message(
            f"✅ Welcome simulé pour {target.mention}", ephemeral=True
        )

    @app_commands.command(
        name="intropics",
        description="[ADMIN] Gere les photos attachees au message intro paiement",
    )
    @app_commands.describe(
        action="Action: add (ajouter), list (lister), remove (supprimer 1), clear (tout effacer)",
        image="Photo (requis si action=add)",
        name="Nom de fichier (requis si action=remove, vu via action=list)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="list", value="list"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="clear", value="clear"),
    ])
    async def intropics(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        image: discord.Attachment = None,
        name: str = None,
    ):
        if not await self.require_admin(interaction):
            return
        act = action.value

        if act == "add":
            if image is None:
                await interaction.response.send_message(
                    "Tu dois fournir une photo dans le parametre `image`.", ephemeral=True
                )
                return
            await interaction.response.defer(ephemeral=True)
            ext = Path(image.filename).suffix.lower()
            if ext not in IMAGE_EXTS:
                await interaction.followup.send(
                    f"Format non supporte. Accepte: {', '.join(sorted(IMAGE_EXTS))}",
                    ephemeral=True,
                )
                return
            INTRO_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            existing = list_intro_images()
            if len(existing) >= 10:
                await interaction.followup.send(
                    "Max 10 photos (limite Discord). Fais `/intropics action:clear` ou remove.",
                    ephemeral=True,
                )
                return
            next_index = len(existing) + 1
            safe_name = f"{next_index:02d}_{Path(image.filename).name}"
            (INTRO_IMAGES_DIR / safe_name).write_bytes(await image.read())
            await interaction.followup.send(
                f"✅ Photo ajoutee: `{safe_name}` ({len(existing) + 1}/10).",
                ephemeral=True,
            )
            return

        if act == "list":
            images = list_intro_images()
            if not images:
                await interaction.response.send_message(
                    "Aucune photo d'intro configuree.", ephemeral=True
                )
                return
            lines = [
                f"{i+1}. `{p.name}` ({p.stat().st_size // 1024} Ko)"
                for i, p in enumerate(images)
            ]
            await interaction.response.send_message(
                f"**Photos intro paiement** ({len(images)}/10):\n" + "\n".join(lines),
                ephemeral=True,
            )
            return

        if act == "remove":
            if not name:
                await interaction.response.send_message(
                    "Tu dois fournir le nom de fichier dans `name`. Vois la liste avec action=list.",
                    ephemeral=True,
                )
                return
            target = INTRO_IMAGES_DIR / name
            if not target.exists() or not target.is_file():
                await interaction.response.send_message(
                    f"`{name}` introuvable.", ephemeral=True
                )
                return
            try:
                target.unlink()
            except Exception as e:
                await interaction.response.send_message(f"Erreur: {e}", ephemeral=True)
                return
            await interaction.response.send_message(
                f"✅ `{name}` supprimee.", ephemeral=True
            )
            return

        if act == "clear":
            images = list_intro_images()
            for p in images:
                try:
                    p.unlink()
                except Exception:
                    pass
            await interaction.response.send_message(
                f"✅ {len(images)} photo(s) supprimee(s).", ephemeral=True
            )
            return

    @app_commands.command(
        name="setadmintoken",
        description="[OWNER] Configure le token du 2e bot (admin) et restart",
    )
    @app_commands.describe(token="Token Discord du bot admin (sera caché immédiatement)")
    async def setadmintoken(self, interaction: discord.Interaction, token: str):
        # Owner only (pas whitelist)
        owner_id = await self.get_owner_id()
        if interaction.user.id != owner_id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        token = token.strip()
        if len(token) < 50 or "." not in token:
            await interaction.response.send_message(
                "❌ Token invalide (trop court ou format incorrect).", ephemeral=True
            )
            return
        ok = _write_env_var("DISCORD_ADMIN_TOKEN", token)
        if not ok:
            await interaction.response.send_message(
                "❌ Erreur ecriture .env. Verifie les permissions du fichier.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "✅ Token sauvegardé dans `.env`.\n"
            "🔄 Le bot redémarre dans 3 sec — systemd va le relancer "
            "et le bot admin va se connecter automatiquement.\n"
            "Attends ~15-20 sec puis fais `/sync` sur les 2 bots.",
            ephemeral=True,
        )
        _schedule_exit(3.0)

    @app_commands.command(
        name="restartbot",
        description="[OWNER] Force le redémarrage du bot (systemd le relance)",
    )
    async def restartbot(self, interaction: discord.Interaction):
        owner_id = await self.get_owner_id()
        if interaction.user.id != owner_id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.send_message(
            "🔄 Restart dans 2 sec...", ephemeral=True
        )
        _schedule_exit(2.0)

    @app_commands.command(
        name="postcommands",
        description="[ADMIN] Poste la liste des commandes de ce bot dans ce salon (à pin)",
    )
    async def postcommands(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer()
        embeds = build_commands_embeds(self.bot)
        # 1er embed avec interaction.followup, le reste avec channel.send
        first = embeds[0]
        await interaction.followup.send(embed=first)
        for emb in embeds[1:]:
            await interaction.channel.send(embed=emb)


def build_commands_embeds(bot):
    """Construit 1+ embeds qui listent toutes les slash commands de ce bot.

    Groupe par section (Public / Admin / Owner) basee sur le prefixe de la description.
    Decoupe automatiquement si depasse les limites Discord (6000 char / embed, 1024 / field).
    """
    cmds = list(bot.tree.get_commands())
    cmds.sort(key=lambda c: c.name)
    sections = {"🌐 Public (pour les VAs)": [], "🔧 Admin": [], "👑 Owner": []}
    for cmd in cmds:
        desc = (cmd.description or "").strip()
        if desc.startswith("[OWNER]"):
            sections["👑 Owner"].append((cmd.name, desc.replace("[OWNER]", "").strip()))
        elif desc.startswith("[ADMIN]"):
            sections["🔧 Admin"].append((cmd.name, desc.replace("[ADMIN]", "").strip()))
        else:
            sections["🌐 Public (pour les VAs)"].append((cmd.name, desc))

    bot_name = bot.user.name if bot.user else "Bot"
    embeds = []
    current = discord.Embed(
        title=f"📚 Commandes — {bot_name}",
        description=f"Total : **{len(cmds)}** commandes",
        color=discord.Color.blurple(),
    )

    def _length(emb):
        # Approx: sum titles + description + field name+value
        n = len(emb.title or "") + len(emb.description or "")
        for f in emb.fields:
            n += len(f.name) + len(f.value)
        return n

    def _flush_field(section_name, lines):
        """Ajoute des fields a l'embed courant, en creant un nouvel embed si trop gros."""
        nonlocal current
        if not lines:
            return
        # Chunker les lignes pour rester sous 1024 par field
        chunk = ""
        chunk_idx = 0
        for line in lines:
            if len(chunk) + len(line) + 1 > 1000:
                # Push le chunk
                name = section_name + (f" (suite)" if chunk_idx > 0 else f" — {len(lines)}")
                # Verifier limite embed 6000
                if _length(current) + len(name) + len(chunk) > 5800 or len(current.fields) >= 24:
                    embeds.append(current)
                    current = discord.Embed(color=discord.Color.blurple())
                current.add_field(name=name, value=chunk, inline=False)
                chunk_idx += 1
                chunk = line
            else:
                chunk = (chunk + "\n" + line) if chunk else line
        if chunk:
            name = section_name + (f" (suite)" if chunk_idx > 0 else f" — {len(lines)}")
            if _length(current) + len(name) + len(chunk) > 5800 or len(current.fields) >= 24:
                embeds.append(current)
                current = discord.Embed(color=discord.Color.blurple())
            current.add_field(name=name, value=chunk, inline=False)

    for section_name, items in sections.items():
        if not items:
            continue
        lines = [f"`/{n}` — {d[:70]}" for n, d in items]
        _flush_field(section_name, lines)

    current.set_footer(text="Auto-générée — relance /postcommands pour rafraîchir")
    embeds.append(current)
    return embeds


async def setup(bot):
    await bot.add_cog(Welcome(bot))
