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
import safe_json

log = logging.getLogger("vabot.welcome")

BOT_DIR = Path(__file__).parent.parent.resolve()
ENV_FILE = BOT_DIR / ".env"
DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
USERS_FILE = DATA_DIR / "users.json"
WHITELIST_FILE = DATA_DIR / "whitelist.json"
WELCOME_CONFIG_FILE = DATA_DIR / "welcome_config.json"

# /ticketsall : serveurs où un run est déjà en cours (anti double-clic / double-run).
_TICKETSALL_RUNNING = set()


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
        "💰 **PAIEMENT PRINCIPAL** *(clics FR, payés tous les 1 et 16 du mois)*\n"
        "• 0 à 50 clics/jour → **0,05 $** par clic\n"
        "• 51 à 100 clics/jour → **0,06 $** par clic\n"
        "• Plus de 100 clics/jour → **0,07 $** par clic\n\n"
        "**Exemples :**\n"
        "• 50 clics/jour → **2,50 $/jour**\n"
        "• 100 clics/jour → **6 $/jour**\n"
        "• 200 clics/jour → **14 $/jour**\n"
        "• 500 clics/jour → **35 $/jour**\n"
        "• 1 000 clics/jour → **70 $/jour**\n\n"
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
        "🤝 **PRIME D'ÉQUIPE** : **+10 $/semaine** au VA qui aide le plus dans le groupe — "
        "le plus impliqué, celui qui anime le **général**.\n\n"
        "Les primes dépendent des **performances réelles** du compte : publications, reels, "
        "activité, croissance et engagement. Plus le compte performe grâce à ton travail, "
        "plus tu débloques de récompenses.\n\n"
        "**En résumé :**\n"
        "✅ Tu es payé pour chaque clic généré\n"
        "✅ Tu débloques des bonus grâce aux performances\n"
        "✅ Plus les chiffres montent, plus les primes augmentent\n\n"
        "Clique sur **🎬 Commencer l'onboarding** ci-dessous quand tu es prêt.\n\n"
        "↓"
    ),
    # Version de la config: incrementer pour forcer la mise a jour d'un message
    # cote VPS au prochain demarrage du bot (migration automatique).
    "config_version": 3,
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
    safe_json.write_text(WELCOME_CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))


def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write_text(USERS_FILE, json.dumps(users, indent=2, ensure_ascii=False))


def load_pending():
    if not PENDING_DELETIONS_FILE.exists():
        return {}
    try:
        return json.loads(PENDING_DELETIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_pending(pending):
    PENDING_DELETIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write_text(PENDING_DELETIONS_FILE, json.dumps(pending, indent=2, ensure_ascii=False))


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
    safe_json.write_text(IDENTITIES_CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))


def is_identity_active(name):
    cfg = load_identities_config()
    entry = cfg.get(name)
    if isinstance(entry, dict):
        return entry.get("enabled", True)
    return True  # par defaut actif


# Bibliothèque 2 du site : espace 100 % séparé. Ses identités portent ce
# préfixe technique et NE DOIVENT JAMAIS remonter dans Discord (menus, rotation
# des VAs, Jailbreak, salons d'identité).
V2_PREFIX = "v2_"


def list_identities():
    """Toutes les identités existantes (active ou non), SAUF celles de la
    Bibliothèque 2 du site (préfixe v2_) qui n'existent que sur le site."""
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(p.name for p in IDENTITIES_DIR.iterdir()
                  if p.is_dir() and not p.name.lower().startswith(V2_PREFIX))


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


# Salons par identité : chaque identité a plusieurs salons réservés à SES VAs
# (general-X = discussion, banger-X = bangers, exemple-compte-X = exemples).
# Tous suivent le même modèle d'accès (visibles uniquement par les VAs de X + staff).
PER_IDENTITY_PREFIXES = ("general-", "banger-", "exemple-compte-")


def _identity_of_channel(ch_name):
    """Suffixe d'identité si le salon est un salon par-identité
    (general-/banger-/exemple-compte-), sinon None.

    Robuste aux préfixes emoji/séparateurs DANS le nom du salon
    (ex: '💥・banger-amelia', '📸-exemple-compte-lola') : on cherche le
    préfixe n'importe où, pas seulement au début. Accents ignorés.
    """
    import re as _re
    norm = (ch_name or "").lower().replace("é", "e").replace("è", "e")
    for p in PER_IDENTITY_PREFIXES:
        idx = norm.find(p)
        if idx != -1:
            m = _re.match(r"[a-z0-9]+", norm[idx + len(p):])
            if m:
                return m.group(0)
    return None


def find_identity_channels(guild, identity):
    """Tous les salons par-identité (general/banger/exemple-compte) d'une identité."""
    target = (identity or "").strip().lower()
    if not target:
        return []
    return [ch for ch in getattr(guild, "text_channels", [])
            if _identity_of_channel(ch.name) == target]


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
    """Aligne l'acces du VA aux salons par-identite (general-/banger-/exemple-
    compte-X) sur son identite ACTUELLE.

    - Son identite -> view=True (uniquement si pas deja le cas : economise des
      appels API / rate-limit).
    - Une AUTRE identite avec un acces qui traine (grant d'une ancienne
      identite) -> deny EXPLICITE (view=False). Le deny explicite est plus fort
      que de simplement retirer l'overwrite : il neutralise aussi un acces qui
      viendrait d'un role / d'une categorie. C'est ce qui corrige le cas "VA
      emma qui voit encore general-amelia" apres un changement d'identite.
    - identity vide/None (reset, /resetva) -> retire l'overwrite specifique du
      membre sur TOUS les salons par-identite.

    Best-effort (ignore les erreurs). Retourne (granted, revoked) pour le report.
    """
    ident_lc = (identity or "").strip().lower()
    granted = 0
    revoked = 0
    for ch in guild.text_channels:
        suffix = _identity_of_channel(ch.name)  # general-/banger-/exemple-compte-
        if suffix is None:
            continue
        try:
            cur = ch.overwrites_for(member)
            if ident_lc and suffix == ident_lc:
                # Son identite -> acces garanti (skip si deja accorde)
                if cur.view_channel is not True:
                    await ch.set_permissions(
                        member,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        reason=f"VA assignee a {ident_lc} - acces salons identite",
                    )
                    granted += 1
            elif not ident_lc:
                # Reset complet : retire l'overwrite specifique du membre
                if cur.view_channel is not None:
                    await ch.set_permissions(
                        member, overwrite=None, reason="VA reset")
                    revoked += 1
            else:
                # Pas son identite : il ne doit PAS voir ce salon. Si un acces
                # traine (ancienne identite / role) -> deny explicite.
                if cur.view_channel is True:
                    await ch.set_permissions(
                        member, view_channel=False,
                        reason=f"VA n'est pas {suffix} - retire acces salon identite")
                    revoked += 1
        except Exception:
            pass
    return granted, revoked


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
    # Catégorie : si le serveur a une catégorie d'accueil dédiée (ex: "Equipe 1"),
    # on y met TOUS les nouveaux VAs. Sinon, catégorie par identité (comportement
    # historique du serveur principal).
    category = None
    try:
        import guild_features as gf
        _cid = gf.get_va_category_id(guild)
        if _cid:
            _c = guild.get_channel(_cid)
            if isinstance(_c, discord.CategoryChannel):
                category = _c
    except Exception:
        category = None
    if category is None:
        category = find_identity_category(guild, identity)
    try:
        return await guild.create_text_channel(
            name=base_name, overwrites=overwrites, category=category
        )
    except discord.Forbidden:
        return None
    except discord.HTTPException:
        # Catégorie pleine (limite Discord 50 salons) ou autre -> on crée sans catégorie
        try:
            return await guild.create_text_channel(name=base_name, overwrites=overwrites)
        except Exception:
            return None


async def _isolate_va_and_grant(guild, member, identity, ticket_channel_id):
    """Isole un VA (anonymat) ET lui (re)donne ses accès.

    Cache TOUS les salons sauf : son ticket + ses salons d'identité
    (general/banger/exemple-compte-X) + les salons extra_visible (warm-up...).
    Puis GRANT explicitement l'accès aux salons extra_visible (sinon ils
    restent invisibles si @everyone est en deny). Idempotent : sûr à rappeler
    à chaque rejoin. Best-effort, ignore les erreurs."""
    cfg = load_welcome_config()
    if not cfg.get("hide_all_channels_from_va", True):
        return
    extra_visible = set(cfg.get("extra_visible_channel_ids", []))
    skip_ids = {ticket_channel_id, *extra_visible}
    for ch in find_identity_channels(guild, identity):
        skip_ids.add(ch.id)
    for ch in guild.channels:
        if ch.id in skip_ids or isinstance(ch, discord.CategoryChannel):
            continue
        try:
            await ch.set_permissions(member, view_channel=False,
                                     reason="VA isolation - anonymat")
        except Exception:
            pass
    # Grant explicite des salons d'aide (extra_visible) : warm-up, commande-va...
    for cid in extra_visible:
        ech = guild.get_channel(cid)
        if ech and not isinstance(ech, discord.CategoryChannel):
            try:
                await ech.set_permissions(member, view_channel=True,
                                          reason="VA - salon d'aide visible")
            except Exception:
                pass


async def _push_content_menu(bot, channel, identity, member):
    """Poste le menu contenu (boutons reel/story/...) dans le salon d'un VA, en le @pingant.
    Reutilise le helper du UserCog pour rester coherent avec le menu quotidien."""
    if not bot or not channel or not identity:
        return
    try:
        user_cog = bot.get_cog("UserCog")
        if user_cog and hasattr(user_cog, "_post_menu"):
            await user_cog._post_menu(channel, identity, mention_user_id=getattr(member, "id", None))
    except Exception as e:
        log.warning(f"_push_content_menu: {e}")


# ---- Tickets du serveur US (Youl4b) : 3 salons simples par membre ----
# Pas de parcours VA (identité, onboarding, isolation, users.json) : juste
# @pseudo-menu (lecture seule, menu Jailbreak US épinglé en permanence),
# @pseudo-content (le contenu généré arrive là) et @pseudo-numero-mail,
# privés, dans la catégorie TAFF. L'ordre du tuple = ordre de création
# (menu juste au-dessus de content).
US_TICKET_SUFFIXES = ("menu", "content", "numero-mail")


def _us_norm(nm):
    """Normalise un nom de salon pour comparaison : minuscules, NFKC, TOUS les
    tirets sosies unicode ramenés au '-' ASCII, caractères invisibles retirés.
    Sans ça, un salon créé À LA MAIN avec un tiret spécial (‑ – — etc., fréquent
    depuis iPhone) ressemble au nôtre à l'écran mais ne matche jamais par == ,
    et le bot recrée un doublon à chaque run."""
    import re as _re
    import unicodedata as _ud
    nm = _ud.normalize("NFKC", (nm or "")).strip().lower()
    nm = _re.sub(r"[​‌‍﻿]", "", nm)          # zéro-largeur
    nm = _re.sub(r"[‐‑‒–—―−]", "-", nm)  # tirets
    nm = nm.replace(".", "")             # Discord strippe les points des salons
    # homoglyphes cyrilliques/grecs (un « а » russe est INVISIBLE à l'œil)
    nm = nm.translate(_US_CONFUSABLES)
    return nm


_US_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "с": "c", "р": "p", "х": "x", "у": "y",
    "і": "i", "ѕ": "s", "ј": "j", "ԁ": "d", "ь": "b", "к": "k", "м": "m",
    "т": "t", "н": "h", "в": "b",
    "α": "a", "ο": "o", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ρ": "p",
    "τ": "t", "υ": "u", "β": "b",
})


def _us_base(member):
    """Base des salons/dossiers d'un membre = son username Discord sanitisé.
    ⚠️ PAS de point dans la base : Discord SUPPRIME les points des noms de
    salons ('laboule.8-menu' devient 'laboule8-menu') -> avec un point, le bot
    ne retrouvait jamais le salon créé et le recréait en boucle (cause RÉELLE
    de la saga laboule8). ⚠️ Si le membre CHANGE de pseudo, la base change :
    ses anciens salons deviennent des orphelins (nettoyés par /ticketsall)."""
    import re as _re
    return _re.sub(r"[^a-z0-9_-]", "", (member.name or "").lower()) or f"user{member.id % 100000}"


def _us_ticket_name(member, suffix):
    return f"{_us_base(member)}-{suffix}"


async def _us_member_category(guild, member):
    """Dossier (catégorie) personnel du membre — créé au besoin. Visible par
    LUI seul (+ staff/admin), ses 3 salons vivent dedans."""
    base = _us_base(member)
    cat = discord.utils.find(
        lambda c: _us_norm(c.name) == base, guild.categories)
    if cat is None:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                manage_channels=True, manage_messages=True),
        }
        cat = await guild.create_category(
            base, overwrites=overwrites, reason="Dossier tickets US du membre")
    return cat


# --------------------------------------------------------------------------
# Roles de marche : @Jailbreak FR / @Jailbreak US, poses d'apres le marche de
# l'IDENTITE du VA (data/identity_market.json, le meme drapeau que le site).
# « hoist » : Discord regroupe alors les membres par role dans la liste de
# droite — c'est tout l'interet, voir qui bosse sur quoi d'un coup d'oeil.
ROLES_MARCHE = {"fr": "Jailbreak FR", "us": "Jailbreak US"}


async def _role_marche(guild, marche):
    nom = ROLES_MARCHE[marche]
    r = discord.utils.find(
        lambda x: (x.name or "").strip().lower() == nom.lower(), guild.roles)
    if r is not None:
        return r
    try:
        return await guild.create_role(
            name=nom, hoist=True,
            colour=(discord.Color.blurple() if marche == "fr"
                    else discord.Color.red()),
            reason="Marche des VA (identite FR / US)")
    except Exception as e:
        log.warning(f"_role_marche {nom}: {e}")
        return None


async def appliquer_roles_marche(guild, membre=None):
    """Aligne les roles de marche sur l'identite de chaque VA.

    `membre` : ne traiter que celui-la (a l'assignation d'une identite).
    Retourne (poses, retires, sans_identite)."""
    if guild is None:
        return (0, 0, 0)
    try:
        import marche as mk
    except Exception:
        return (0, 0, 0)
    users = load_users()
    roles = {}
    for m in ("fr", "us"):
        roles[m] = await _role_marche(guild, m)
    if not any(roles.values()):
        return (0, 0, 0)
    poses = retires = sans = 0
    cibles = [membre] if membre is not None else None
    if cibles is None:
        cibles = []
        for uid in users:
            try:
                m = guild.get_member(int(uid))
            except Exception:
                m = None
            if m is not None:
                cibles.append(m)
    for m in cibles:
        rec = users.get(str(m.id))
        ident = (rec.get("identity") if isinstance(rec, dict) else rec) or ""
        if not ident:
            sans += 1
            continue
        bon = mk.de(ident)
        garder, jeter = roles.get(bon), roles.get("us" if bon == "fr" else "fr")
        try:
            if garder is not None and garder not in m.roles:
                await m.add_roles(garder, reason=f"identite {ident} -> {bon.upper()}")
                poses += 1
            if jeter is not None and jeter in m.roles:
                await m.remove_roles(jeter, reason="changement de marche")
                retires += 1
        except Exception as e:
            log.warning(f"roles marche {m}: {e}")
        await asyncio.sleep(0.4)          # on menage l'API
    return (poses, retires, sans)


def _proprio_du_salon(channel):
    """La personne a qui appartient ce salon prive : celle qui a une
    autorisation nominative dessus (les salons -menu sont prives)."""
    try:
        for cible, _perm in (channel.overwrites or {}).items():
            if isinstance(cible, discord.Member) and not cible.bot:
                return cible
    except Exception:
        pass
    return None


async def _ensure_us_menu(bot, channel):
    """Poste (et épingle) le menu Jailbreak US dans un salon -content s'il n'y est
    pas déjà (détection via les messages épinglés du bot). Idempotent."""
    if bot is None or channel is None:
        return False
    try:
        ucog = bot.get_cog("UserCog")
        if ucog is None or not hasattr(ucog, "jailbreak_us_menu"):
            return False
        try:
            pins = await channel.pins()
        except Exception:
            pins = []
        for p in pins:
            if (p.author.id == getattr(bot.user, "id", 0) and p.embeds
                    and "Jailbreak US" in (p.embeds[0].title or "")):
                return True  # déjà en place
        # Marche du PROPRIETAIRE du salon : chaque -menu appartient a une seule
        # personne, on peut donc lui servir SES models (role Jailbreak FR/US).
        marche = "us"
        try:
            from cogs.user import marche_du_membre
            proprio = _proprio_du_salon(channel)
            if proprio is not None:
                marche = marche_du_membre(proprio)
        except Exception:
            pass
        # PP des models dans le select (emojis serveur, créés une seule fois)
        try:
            emb, view = await ucog.jailbreak_us_menu_async(channel.guild, marche)
        except Exception:
            emb, view = ucog.jailbreak_us_menu(marche)
        msg = await channel.send(embed=emb, view=view)
        try:
            await msg.pin()
        except Exception:
            pass
        await _ensure_us_panel(bot, channel)
        return True
    except Exception as e:
        log.warning(f"_ensure_us_menu: {e}")
        return False


async def maj_menu_marche(bot, channel, marche=None):
    """Remplace le contenu du message de menu deja epingle par celui du
    marche demande. On EDITE : reposter laisserait deux menus dans le salon."""
    if bot is None or channel is None:
        return False
    try:
        ucog = bot.get_cog("UserCog")
        if ucog is None:
            return False
        if marche is None:
            from cogs.user import marche_du_membre
            proprio = _proprio_du_salon(channel)
            marche = marche_du_membre(proprio) if proprio is not None else "us"
        try:
            emb, view = await ucog.jailbreak_us_menu_async(channel.guild, marche)
        except Exception:
            emb, view = ucog.jailbreak_us_menu(marche)
        for m in await channel.pins():
            if (m.author.id == getattr(bot.user, "id", 0) and m.embeds
                    and "Menu Jailbreak" in (m.embeds[0].title or "")):
                await m.edit(embed=emb, view=view)
                return True
        msg = await channel.send(embed=emb, view=view)
        try:
            await msg.pin()
        except Exception:
            pass
        return True
    except Exception as e:
        log.warning(f"maj_menu_marche: {e}")
        return False


async def _ensure_us_panel(bot, channel):
    """Second message PERMANENT : le panneau d'actions, qui suit la model
    choisie dans le menu du dessus. Les deux restent affiches en
    permanence — avant, le panneau etait ephemere et disparaissait."""
    if bot is None or channel is None:
        return False
    try:
        from cogs.user import _jb_panel, _jb_panel_set
        try:
            for m in await channel.pins():
                if (m.author.id == getattr(bot.user, "id", 0) and m.embeds
                        and (m.embeds[0].footer.text or "") == "panneau-actions-us"):
                    _jb_panel_set(channel.id, m.id)
                    return True                   # deja en place
        except Exception:
            pass
        emb, view = _jb_panel(bot.get_cog("UserCog"), "_", 3)
        msg = await channel.send(embed=emb, view=view)
        _jb_panel_set(channel.id, msg.id)
        try:
            await msg.pin()
        except Exception:
            pass
        return True
    except Exception as e:
        log.warning(f"_ensure_us_panel: {e}")
        return False


async def reset_us_menu(bot, channel):
    """Repart de zero dans un salon -menu : on vide, puis on repose les deux
    messages permanents. Utile quand le salon s'est encombre de contenu."""
    if channel is None:
        return False
    try:
        await channel.purge(limit=200, check=lambda m: True)
    except Exception as e:
        log.warning(f"reset_us_menu purge: {e}")
    try:
        from cogs.user import _jb_panel_ids
        d = _jb_panel_ids()
        d.pop(str(channel.id), None)
        import safe_json
        from pathlib import Path as _P
        safe_json.write(_P("data") / "us_panels.json", d, indent=2)
    except Exception:
        pass
    return await _ensure_us_menu(bot, channel)


async def _ensure_num_panel(bot, channel):
    """Poste (et épingle) le panneau « Numéro & Mail » dans un salon
    -numero-mail s'il n'y est pas déjà. Idempotent."""
    if bot is None or channel is None:
        return False
    try:
        from cogs.numeros import NumPanelView, panel_embed
        ncog = bot.get_cog("NumerosCog")
        if ncog is None:
            return False
        try:
            pins = await channel.pins()
        except Exception:
            pins = []
        for p in pins:
            if (p.author.id == getattr(bot.user, "id", 0) and p.embeds
                    and "Numéro & Mail" in (p.embeds[0].title or "")):
                return True
        msg = await channel.send(embed=panel_embed(), view=NumPanelView(ncog))
        try:
            await msg.pin()
        except Exception:
            pass
        return True
    except Exception as e:
        log.warning(f"_ensure_num_panel: {e}")
        return False


async def create_us_tickets(guild, member, bot=None):
    """Garantit l'état cible d'un membre : UN dossier (catégorie) à son pseudo
    contenant ses 3 salons dans l'ordre menu → content → numero-mail, le menu
    Jailbreak US épinglé dans -menu (lecture seule). Idempotent.
    Retourne (créés, erreurs)."""
    created, errors = [], []
    try:
        cat = await _us_member_category(guild, member)
    except Exception as e:
        return created, [f"dossier {_us_base(member)}: {e}"]
    chans = {}
    for suffix in US_TICKET_SUFFIXES:
        name = _us_ticket_name(member, suffix)
        existing = discord.utils.find(
            lambda c, n=name: _us_norm(c.name) == n, guild.text_channels)
        if existing:
            chans[suffix] = existing
            continue  # déjà là (commande re-lançable sans doublons)
        writable = suffix != "menu"  # -menu : lecture seule, rien n'y est écrit
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=writable,
                read_message_history=True, attach_files=writable),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True,
                manage_messages=True),
        }
        try:
            ch = await guild.create_text_channel(
                name, category=cat, overwrites=overwrites,
                reason="Ticket US (menu / content / numero-mail)")
            created.append(ch)
            chans[suffix] = ch
        except Exception as e:
            errors.append(f"{name}: {e}")
    # Dossier + ordre : move() (endpoint bulk, fiable) SEULEMENT si nécessaire.
    in_cat = [chans[s] for s in US_TICKET_SUFFIXES if chans.get(s) is not None]
    ok_cat = all(c.category_id == cat.id for c in in_cat)
    ok_order = all(in_cat[i].position <= in_cat[i + 1].position
                   for i in range(len(in_cat) - 1))
    if in_cat and not (ok_cat and ok_order):
        for idx, ch in enumerate(in_cat):
            try:
                await ch.move(beginning=True, offset=idx, category=cat,
                              reason="rangement dossier US")
            except Exception:
                pass
            await asyncio.sleep(0.4)
    menu_ch, content_ch = chans.get("menu"), chans.get("content")
    # Le menu Jailbreak US vit dans -menu, en permanence.
    if menu_ch is not None:
        await _ensure_us_menu(bot, menu_ch)
    # Le panneau Numéro & Mail vit dans -numero-mail, en permanence.
    if chans.get("numero-mail") is not None:
        await _ensure_num_panel(bot, chans["numero-mail"])
    # Migration : retirer l'ancien menu épinglé dans -content (version précédente).
    if content_ch is not None and bot is not None:
        try:
            for p in await content_ch.pins():
                if (p.author.id == getattr(bot.user, "id", 0) and p.embeds
                        and "Jailbreak US" in (p.embeds[0].title or "")):
                    try:
                        await p.delete()
                    except Exception:
                        await p.unpin()
        except Exception:
            pass
    return created, errors


async def setup_va_ticket(guild, member, bot=None):
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
            # Re-sync l'acces aux salons d'identite (au cas ou il aurait ete perdu)
            ident_existing = existing.get("identity") if isinstance(existing, dict) else None
            if ident_existing:
                try:
                    await sync_general_channel_access(guild, member, ident_existing)
                except Exception:
                    pass
            # Rejoin : re-applique l'isolation + re-donne les salons d'aide
            # (warm-up...) car Discord efface les overwrites quand on quitte.
            try:
                await _isolate_va_and_grant(guild, member, ident_existing or "", existing_channel.id)
            except Exception:
                pass
            return existing_channel, None
        # Introuvable ICI ≠ supprimé : si le salon vit sur un AUTRE serveur du bot
        # (VA du serveur principal invité sur le serveur US, par ex.), on ne touche
        # PAS à sa fiche — sinon elle serait re-pointée ici et son vrai salon
        # deviendrait orphelin.
        if bot is not None:
            for g in bot.guilds:
                if g.id != guild.id and g.get_channel(existing["channel_id"]):
                    return None, (f"{member.mention} est déjà VA sur **{g.name}** "
                                  "(fiche protégée, aucun ticket créé ici).")
        # Salon supprimé -> on oublie SEULEMENT le channel mort, on conserve le
        # reste de la fiche (moyen de paiement, comptes Insta, identité).
        if isinstance(users.get(str(member.id)), dict):
            users[str(member.id)].pop("channel_id", None)
        save_users(users)

    # Determiner l'identite
    if isinstance(existing, dict) and existing.get("identity"):
        identity = existing["identity"]
    elif isinstance(existing, str):
        identity = existing
    else:
        # Si le serveur a une identité dédiée (ex: jessye pour le marché US),
        # on l'utilise directement (sinon rotation normale du marché français).
        identity = None
        try:
            import guild_features as gf
            identity = gf.get_server_identity(guild)
        except Exception:
            identity = None
        if not identity:
            identity = pick_next_identity()
        if not identity:
            return None, "Aucune identité disponible. Préviens un admin."

    # Creer le salon
    channel = await create_va_channel(guild, member, identity)
    if not channel:
        return None, "Le bot n'a pas la permission de créer un salon."

    # Sauvegarder (FUSION : ne pas écraser paiement / comptes Insta / notes)
    _e = users.get(str(member.id))
    _entry = dict(_e) if isinstance(_e, dict) else {}
    _entry.update({"identity": identity, "channel_id": channel.id})
    _entry.setdefault("auto_post", True)
    users[str(member.id)] = _entry
    save_users(users)
    # role de marche pose des l'assignation, sinon il faudrait y penser
    try:
        await appliquer_roles_marche(guild, member)
    except Exception:
        pass

    # Contenu d'accueil du ticket.
    import guild_features as gf
    if gf.threads_mode(guild) or not gf.enabled(guild, "onboarding"):
        # Serveur Threads (ou onboarding off) : on ne montre RIEN d'autre que le
        # menu (pas d'intro, pas d'images de bonus, pas de bouton onboarding).
        posted = False
        ucog = bot.get_cog("UserCog") if bot else None
        if ucog is not None:
            try:
                posted = await ucog._post_menu(channel, identity, mention_user_id=member.id)
            except Exception as e:
                log.error(f"setup_va_ticket: menu Threads échoué: {e}")
        if not posted:
            # Pas de menu à montrer (fonction contenu bridée, ou envoi raté) :
            # accueil neutre, sans promettre un menu qui n'arrivera pas.
            try:
                await channel.send(f"{member.mention} 👋 Bienvenue !")
            except Exception:
                pass
    else:
        # Flux classique (marché FR) : intro + images + bouton onboarding.
        cfg = load_welcome_config()
        _raw_intro = cfg["ticket_intro_message"].replace("\\n", "\n")
        try:
            intro_text = _raw_intro.format(mention=member.mention)
        except (KeyError, ValueError, IndexError):
            intro_text = _raw_intro.replace("{mention}", member.mention)
        files = build_intro_files()
        try:
            await channel.send(content=intro_text, view=StartOnboardingView(), files=files or None)
        except Exception as e:
            log.error(f"setup_va_ticket: erreur envoi intro: {e}")

    # Isole le VA (cache tout sauf ticket + salons d'identité + salons d'aide)
    # et grant les salons d'aide.
    await _isolate_va_and_grant(guild, member, identity, channel.id)

    # Donne acces aux salons de l'identite (general/banger/exemple-compte)
    try:
        await sync_general_channel_access(guild, member, identity)
    except Exception as e:
        log.warning(f"setup_va_ticket: sync_general_channel_access erreur: {e}")

    # Pousse le menu contenu (boutons) direct dans son salon, en le @pingant
    await _push_content_menu(bot, channel, identity, member)

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
        import guild_features as gf
        if not gf.enabled(interaction.guild, "onboarding"):
            await interaction.response.send_message("⚠️ Onboarding désactivé sur ce serveur.", ephemeral=True)
            return
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

        channel, error = await setup_va_ticket(guild, interaction.user, bot=interaction.client)
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

        # Serveur bridé sans la fonction tickets -> pas de ticket / welcome auto.
        import guild_features as gf
        if not gf.enabled(member.guild, "tickets"):
            return

        # Serveur US (Youl4b) : les tickets sont 2 salons simples par membre
        # (content / numero-mail), PAS le parcours VA classique.
        if gf.is_us_guild(member.guild):
            try:
                created, errors = await create_us_tickets(member.guild, member, bot=self.bot)
                if errors:
                    log.error(f"on_member_join US tickets: {errors} (member={member.id})")
                else:
                    log.info(f"on_member_join US: {len(created)} salon(s) crees pour {member.id}")
            except Exception as e:
                log.error(f"on_member_join US tickets exception: {e}")
            return

        # Mode auto-ticket: cree direct le salon, sans passer par le welcome public
        if cfg.get("auto_create_ticket_on_join", True):
            try:
                channel, error = await setup_va_ticket(member.guild, member, bot=self.bot)
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
            _raw_pub = cfg["welcome_public_message"].replace("\\n", "\n")
            try:
                text = _raw_pub.format(mention=member.mention)
            except (KeyError, ValueError, IndexError):
                text = _raw_pub.replace("{mention}", member.mention)
            await channel.send(content=text, view=WelcomeContinueView())
        except Exception as e:
            log.error(f"on_member_join: erreur envoi welcome: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Donner @Jailbreak FR doit changer le menu TOUT DE SUITE — sans
        avoir a lancer /resetmenus derriere."""
        try:
            if before.roles == after.roles:
                return
            import guild_features as gf
            if not gf.is_us_guild(after.guild):
                return
            from cogs.user import marche_du_membre
            avant, apres = marche_du_membre(before), marche_du_membre(after)
            if avant == apres:
                return
            cible = _us_ticket_name(after, "menu")
            salon = discord.utils.find(
                lambda c, n=cible: _us_norm(c.name) == n, after.guild.text_channels)
            if salon is None:
                return
            await maj_menu_marche(self.bot, salon, apres)
            log.info(f"[marche] menu de {after} passe en {apres.upper()}")
        except Exception as e:
            log.warning(f"on_member_update menu marche: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Quand un membre quitte, planifier la suppression de son salon dans N jours."""
        if member.bot:
            return
        users = load_users()
        data = users.get(str(member.id))
        if not isinstance(data, dict) or not data.get("channel_id"):
            return
        # Multi-serveurs : ne planifier QUE si le salon de la fiche appartient au
        # serveur QUITTÉ. Sinon (VA du serveur principal qui quitte le serveur US,
        # par ex.), la purge à J+7 effacerait toute sa fiche (identité, paiement,
        # comptes) alors que son salon vit ailleurs.
        if not member.guild.get_channel(data["channel_id"]):
            log.info(f"on_member_remove: {member.id} quitte {member.guild.id} mais son salon "
                     "est sur un autre serveur -> pas de suppression planifiee")
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
            # Nettoyer users.json — SAUF si la fiche a été re-pointée sur un AUTRE
            # salon entre-temps (VA recréé ailleurs, ex: /ticketsall serveur US) :
            # dans ce cas on garde la fiche, on retire juste l'entrée pending.
            users = load_users()
            u = users.get(user_id)
            repointe = (isinstance(u, dict) and u.get("channel_id")
                        and u.get("channel_id") != data.get("channel_id"))
            if user_id in users and not repointe:
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
                    suffix = _identity_of_channel(ch.name)  # general-/banger-/exemple-compte-
                    if suffix is None:
                        continue

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

    @app_commands.command(
        name="cleansalons",
        description="[ADMIN] Enlève les emojis au début des noms des salons d'identité",
    )
    async def cleansalons(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("À utiliser dans un serveur.", ephemeral=True)
            return
        import re as _re
        renamed = []
        for ch in guild.text_channels:
            # Seulement les salons par-identité (general/banger/exemple-compte-X)
            if _identity_of_channel(ch.name) is None:
                continue
            # Retire les caractères non-alphanumériques en DÉBUT de nom
            # (emoji, ・, ·, espaces, tirets décoratifs). Garde général-X (accent ok).
            clean = _re.sub(r"^[^0-9A-Za-zÀ-ÿ]+", "", ch.name).strip()
            if clean and clean != ch.name:
                try:
                    old = ch.name
                    await ch.edit(name=clean, reason="cleansalons - retrait emoji")
                    renamed.append(f"{old} → {clean}")
                except Exception as e:
                    renamed.append(f"⚠️ {ch.name} : {e}")
        if not renamed:
            await interaction.followup.send(
                "✅ Rien à nettoyer — les salons d'identité n'ont pas d'emoji au début.",
                ephemeral=True,
            )
            return
        txt = "✅ **Salons nettoyés** :\n" + "\n".join(f"• {r}" for r in renamed)
        await interaction.followup.send(txt[:1990], ephemeral=True)

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
        name="rolesmarche",
        description="[ADMIN] Pose @Jailbreak FR / @Jailbreak US sur les VA selon leur identité",
    )
    async def rolesmarche(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.send_message(
            "🎭 Mise à jour des rôles de marché…", ephemeral=True)

        async def _run():
            poses, retires, sans = await appliquer_roles_marche(interaction.guild)
            txt = (f"✅ **{poses}** rôle(s) posé(s)"
                   + (f", {retires} retiré(s)" if retires else "")
                   + (f" · {sans} VA sans identité" if sans else "")
                   + "\n_Les rôles sont affichés séparément : la liste de droite "
                     "regroupe désormais les membres par marché._")
            try:
                await interaction.followup.send(txt, ephemeral=True)
            except Exception:
                pass

        interaction.client.loop.create_task(_run())

    @app_commands.command(
        name="resetmenus",
        description="[ADMIN] Serveur US : vide les salons -menu et repose les 2 menus permanents",
    )
    @app_commands.describe(salon="Ne remettre a neuf QUE ce salon -menu (sinon : tous)")
    async def resetmenus(self, interaction: discord.Interaction,
                         salon: discord.TextChannel = None):
        if not await self.require_admin(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        import guild_features as gf
        if not gf.is_us_guild(guild):
            await interaction.response.send_message(
                "🔒 Réservé au serveur US (Youl4b) — protection du serveur principal.",
                ephemeral=True)
            return
        cibles = ([salon] if salon is not None
                  else [c for c in guild.text_channels if c.name.endswith("-menu")])
        if not cibles:
            await interaction.response.send_message(
                "Aucun salon `-menu` trouvé.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🧹 Remise à neuf de {len(cibles)} salon(s) `-menu`…", ephemeral=True)

        async def _run():
            faits, rates = [], []
            for ch in cibles:
                try:
                    ok = await reset_us_menu(self.bot, ch)
                    (faits if ok else rates).append(ch.name)
                except Exception as e:
                    rates.append(f"{ch.name} ({type(e).__name__})")
                await asyncio.sleep(1.2)          # on menage l'API Discord
            txt = f"✅ **{len(faits)}** salon(s) remis à neuf — menu + panneau d'actions épinglés."
            if rates:
                txt += f"\n⚠️ Échecs : {', '.join(rates[:8])}"
            try:
                await interaction.followup.send(txt, ephemeral=True)
            except Exception:
                pass

        interaction.client.loop.create_task(_run())

    @app_commands.command(
        name="ticketsall",
        description="[ADMIN] Serveur US : RANGE les tickets — crée les manquants, vire les doublons, remet l'ordre",
    )
    async def ticketsall(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        import guild_features as gf
        if not gf.is_us_guild(guild):
            await interaction.response.send_message(
                "🔒 Réservé au serveur US (Youl4b) — protection du serveur principal.", ephemeral=True)
            return
        # RÉCONCILIATEUR : l'objectif est « 3 salons par personne, c'est tout » —
        # menu → content → numero-mail, groupés par personne, sans doublon ni orphelin.
        import re as _re
        pat = _re.compile(r"-(menu|content|numero-mail)$")
        members = [m for m in guild.members if not m.bot and m.id != interaction.user.id]
        expected = {}
        for m in members:
            for s in US_TICKET_SUFFIXES:
                expected[_us_ticket_name(m, s)] = m
        # Clé = nom NORMALISÉ (tirets sosies inclus) : les salons créés à la main
        # qui RESSEMBLENT aux nôtres comptent comme le même salon.
        by_name = {}
        for c in guild.text_channels:
            nn = _us_norm(c.name)
            if pat.search(nn):
                by_name.setdefault(nn, []).append(c)
        n_create = sum(1 for n in expected if n not in by_name)
        # Doublons : MÊME pseudo+type -> ON N'EN GARDE QU'UN (demande user :
        # « même pseudo direct sup »). On garde le plus ancien AVEC messages
        # (le contenu généré vit dans -content), sinon le plus ancien tout court.
        # Les -menu en trop partent direct (le menu se reposte tout seul).
        del_dups, warn = [], []
        for n, chans in sorted(by_name.items()):
            if len(chans) < 2:
                continue
            chans = sorted(chans, key=lambda c: c.id)  # plus ancien d'abord
            if n.endswith("-menu"):
                del_dups += chans[1:]
                continue
            with_msgs = [c for c in chans if c.last_message_id]
            keep = with_msgs[0] if with_msgs else chans[0]
            del_dups += [c for c in chans if c.id != keep.id]
        # Orphelins : le nom (même normalisé) ne correspond à aucun membre actuel
        # (membre parti, salon créé à la main avec des lettres sosies…). Demande
        # user : on SUPPRIME tout ce qui est au format ticket sans propriétaire —
        # la liste complète est affichée avant confirmation.
        del_orph = []
        for n, chans in sorted(by_name.items()):
            if n in expected:
                continue
            del_orph.extend(chans)

        cog = self
        inv_id = interaction.user.id
        # Suppressions dédupliquées par id (un doublon peut aussi être orphelin)
        to_del = list({c.id: c for c in del_dups + del_orph}.values())
        plan = []
        if n_create:
            plan.append(f"➕ **{n_create}** salon(s) manquant(s) à créer")
        if to_del:
            _nd = ", ".join("#" + c.name for c in to_del[:8]) + ("…" if len(to_del) > 8 else "")
            plan.append(f"🗑 **{len(to_del)}** salon(s) à supprimer — doublons/orphelins ({_nd})")
        else:
            plan.append("🗑 rien à supprimer (aucun doublon ni orphelin détecté)")
        plan.append("📁 un **dossier par personne** (catégorie à son pseudo) avec ses 3 salons "
                    "dans l'ordre `menu` → `content` → `numero-mail`")
        warn_txt = ("\n⚠️ " + "\n⚠️ ".join(warn[:5])) if warn else ""

        class _ConfirmAll(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self._started = False

            async def on_timeout(self):
                try:
                    await interaction.edit_original_response(
                        content="⏱️ Confirmation expirée — relance `/ticketsall` si tu veux toujours le faire.",
                        view=None)
                except Exception:
                    pass

            @discord.ui.button(label="✅ Ranger tout ça", style=discord.ButtonStyle.danger)
            async def go(self, itx: discord.Interaction, button: discord.ui.Button):
                if itx.user.id != inv_id:
                    await itx.response.send_message("Pas pour toi.", ephemeral=True)
                    return
                # Anti double-clic / double-run : section SYNCHRONE (aucun await
                # avant), sinon 2 interactions en rafale lancent 2 boucles.
                if self._started or guild.id in _TICKETSALL_RUNNING:
                    await itx.response.send_message("Déjà en cours.", ephemeral=True)
                    return
                self._started = True
                _TICKETSALL_RUNNING.add(guild.id)
                self.stop()
                try:
                    await itx.response.edit_message(
                        content="🔄 Rangement lancé (suppressions → dossiers → ordre) — je préviens ici à la fin.",
                        view=None)
                    # 1) Suppressions (doublons + orphelins, dédupliqués)
                    removed = 0
                    for c in to_del:
                        try:
                            await c.delete(reason="ticketsall : doublon/orphelin")
                            removed += 1
                        except Exception as e:
                            log.error(f"ticketsall delete {c.id}: {e}")
                        await asyncio.sleep(0.8)
                    # 1b) Dossiers orphelins VIDES (ex: ancien pseudo) -> supprimés
                    orph_bases = set()
                    for c in to_del:
                        nn = _us_norm(c.name)
                        m2 = pat.search(nn)
                        if m2:
                            orph_bases.add(nn[:m2.start()])
                    member_bases = {_us_base(m) for m in members}
                    for cat2 in list(guild.categories):
                        nn = _us_norm(cat2.name)
                        if nn in orph_bases and nn not in member_bases and not cat2.channels:
                            try:
                                await cat2.delete(reason="ticketsall : dossier orphelin vide")
                                removed += 1
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
                    # 2) Dossier + 3 salons + ordre + menu, membre par membre
                    ok = failed = 0
                    for m in sorted(members, key=_us_base):
                        if guild.get_member(m.id) is None:
                            continue  # parti entre-temps
                        try:
                            created, errors = await create_us_tickets(guild, m, bot=cog.bot)
                            ok += len(created)
                            if errors:
                                failed += len(errors)
                                log.error(f"ticketsall: {errors} (member={m.id})")
                        except Exception as e:
                            failed += 1
                            log.error(f"ticketsall exception: {e} (member={m.id})")
                        await asyncio.sleep(0.5)
                    # 3) Récap par personne : « lui c'est good, lui aussi »
                    lines = []
                    for m in sorted(members, key=_us_base):
                        have = sum(1 for s in US_TICKET_SUFFIXES
                                   if discord.utils.find(
                                       lambda c, n=_us_ticket_name(m, s): _us_norm(c.name) == n,
                                       guild.text_channels))
                        lines.append(("✅" if have == 3 else "🛠") + f" `{_us_base(m)}` — {have}/3")
                    msg = (f"✅ <@{inv_id}> Rangement terminé : {removed} supprimé(s), "
                           f"{ok} créé(s)"
                           + (f", {failed} échec(s) (voir logs)" if failed else "") + "\n"
                           + "\n".join(lines))
                    try:
                        await itx.followup.send(msg[:1990], ephemeral=True)
                    except Exception:
                        # followup expiré (gros serveur) -> message public dans le salon
                        try:
                            await itx.channel.send(msg[:1990])
                        except Exception:
                            pass
                finally:
                    _TICKETSALL_RUNNING.discard(guild.id)

        await interaction.response.send_message(
            (f"⚠️ **{guild.name}** — rangement des tickets ({len(members)} membre(s), toi et les bots exclus) :\n"
             + "\n".join("• " + p for p in plan)
             + warn_txt + "\nConfirme 👇")[:1990],
            view=_ConfirmAll(), ephemeral=True)

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
