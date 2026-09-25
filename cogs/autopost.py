"""Auto-post quotidien : à une heure fixe, le bot poste reel + post + story + storycta
dans le salon de chaque VA actif. Quand le VA se reveille, tout est deja la.
"""
import asyncio
from contextlib import contextmanager
import fcntl
import io
import json
import logging
import random
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks

from video_transform import load_config as load_video_config
from image_transform import transform_image, load_config as load_image_config
import safe_json

log = logging.getLogger("vabot.autopost")

DATA_DIR = Path("data")
USERS_FILE = DATA_DIR / "users.json"
IDENTITIES_DIR = DATA_DIR / "identities"
AUTOPOST_CONFIG = DATA_DIR / "autopost_config.json"
AUTOPOST_RUNS = DATA_DIR / "autopost_runs"
AUTOPOST_MAX_ATTEMPTS = 3
AUTOPOST_RETRY_SECONDS = 15 * 60
AUTOPOST_KINDS = ("reel", "post", "story", "storycta")
STORY_CTA_CAPTIONS_FILE = DATA_DIR / "story_cta_captions.txt"

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

DEFAULT_AUTOPOST_CONFIG = {
    "enabled": False,
    "hour_utc": 7,       # 8h Paris hiver, 9h Paris ete
    "minute_utc": 0,
    "post_reel": True,
    "post_post": True,
    "post_story": True,
    "post_storycta": True,
    "last_run_date": None,
}


def load_autopost_config():
    if not AUTOPOST_CONFIG.exists():
        save_autopost_config(DEFAULT_AUTOPOST_CONFIG)
        return dict(DEFAULT_AUTOPOST_CONFIG)
    try:
        cfg = json.loads(AUTOPOST_CONFIG.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_AUTOPOST_CONFIG)
        merged.update(cfg)
        return merged
    except Exception:
        return dict(DEFAULT_AUTOPOST_CONFIG)


def save_autopost_config(cfg):
    AUTOPOST_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write_text(AUTOPOST_CONFIG, json.dumps(cfg, indent=2, ensure_ascii=False)):
        raise OSError("Impossible de sauvegarder la configuration Autopost")


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


def get_user_data(user_id):
    """Returns dict {identity, channel_id, auto_post} or None."""
    users = load_users()
    data = users.get(str(user_id))
    if data is None:
        return None
    if isinstance(data, str):
        return {"identity": data, "channel_id": None, "auto_post": True}
    return {
        "identity": data.get("identity"),
        "channel_id": data.get("channel_id"),
        "auto_post": data.get("auto_post", True),
    }


def unescape_newlines(text):
    return text.replace("\\n", "\n") if text else text


def random_reel_data(identity):
    videos_dir = IDENTITIES_DIR / identity / "videos"
    if not videos_dir.exists():
        return None, None, None, None
    videos = [
        p for p in videos_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not videos:
        return None, None, None, None
    video = random.choice(videos)
    cap_p = video.with_suffix(".txt")
    desc_p = video.with_suffix(".desc.txt")
    caption = unescape_newlines(cap_p.read_text(encoding="utf-8").strip()) if cap_p.exists() else None
    description = unescape_newlines(desc_p.read_text(encoding="utf-8").strip()) if desc_p.exists() else None
    example = None
    for ext in VIDEO_EXTS:
        c = videos_dir / f"{video.stem}.example{ext}"
        if c.exists():
            example = c
            break
    return video, caption, description, example


def random_image_with_pair(directory):
    if not directory.exists():
        return None, None, None, None
    images = [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        and not p.stem.lower().endswith(".example")
    ]
    if not images:
        return None, None, None, None
    img = random.choice(images)
    cap_p = img.with_suffix(".txt")
    desc_p = img.with_suffix(".desc.txt")
    caption = unescape_newlines(cap_p.read_text(encoding="utf-8").strip()) if cap_p.exists() else None
    description = unescape_newlines(desc_p.read_text(encoding="utf-8").strip()) if desc_p.exists() else None
    example = None
    for ext in IMAGE_EXTS:
        c = directory / f"{img.stem}.example{ext}"
        if c.exists():
            example = c
            break
    return img, caption, description, example


def random_storycta_data(identity):
    d = IDENTITIES_DIR / identity / "storyctas"
    if not d.exists():
        return None, None
    images = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    if not images:
        return None, None
    img = random.choice(images)
    caption = None
    if STORY_CTA_CAPTIONS_FILE.exists():
        lines = [l.strip() for l in STORY_CTA_CAPTIONS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            caption = unescape_newlines(random.choice(lines))
    return img, caption


async def send_reel(channel, identity):
    video, caption, description, example = random_reel_data(identity)
    if not video:
        return False
    intro = f"🎬 **REEL — identité `{identity}`**\n📥 Télécharge la vidéo CLEAN."
    if example:
        intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE — NE PAS la télécharger."
    files = [discord.File(video, filename=video.name)]
    if example:
        files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
    try:
        await channel.send(content=intro, files=files)
    except discord.HTTPException:
        try:
            await channel.send(content=intro, file=discord.File(video, filename=video.name))
        except discord.HTTPException:
            return False
    if caption:
        await channel.send("📝 **CAPTION** (à mettre **PAR-DESSUS la vidéo** dans l'éditeur Insta) :")
        await channel.send(caption)
    if description:
        await channel.send("📄 **DESCRIPTION** (à coller dans le **champ légende** du post) :")
        await channel.send(description)
    return True


async def _send_image(channel, identity, kind_label, kind_target, random_fn, transform_cfg):
    image, caption, description, example = random_fn(identity)
    if not image:
        return False
    tmp_dir = None
    send_path = image
    try:
        if transform_cfg.get("enabled", True):
            tmp_dir = tempfile.mkdtemp(prefix=f"{kind_target}_")
            tmp_path = Path(tmp_dir) / image.name
            if await asyncio.to_thread(transform_image, image, tmp_path, transform_cfg, kind_target):
                send_path = tmp_path
        intro = f"🖼️ **{kind_label.upper()} — identité `{identity}`**\n📥 Télécharge la photo CLEAN."
        if example:
            intro += "\n👁️ La 2e pièce jointe est l'EXEMPLE — NE PAS la télécharger."
        files = [discord.File(send_path, filename=image.name)]
        if example:
            files.append(discord.File(example, filename=f"EXEMPLE_{example.name}"))
        try:
            await channel.send(content=intro, files=files)
        except discord.HTTPException:
            return False
        if caption:
            await channel.send(f"📝 **CAPTION {kind_label.upper()}** (à mettre **PAR-DESSUS la photo** dans l'éditeur Insta) :")
            await channel.send(caption)
        if description:
            await channel.send(f"📄 **DESCRIPTION {kind_label.upper()}** (à coller dans le **champ légende** du post) :")
            await channel.send(description)
        return True
    finally:
        if tmp_dir:
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


async def send_post(channel, identity):
    return await _send_image(channel, identity, "post", "post",
                             lambda i: random_image_with_pair(IDENTITIES_DIR / i / "posts"),
                             load_image_config())


async def send_story(channel, identity):
    return await _send_image(channel, identity, "story", "story",
                             lambda i: random_image_with_pair(IDENTITIES_DIR / i / "stories"),
                             load_image_config())


async def send_storycta(channel, identity):
    image, caption = random_storycta_data(identity)
    if not image or not caption:
        return False
    tmp_dir = None
    send_path = image
    try:
        cfg = load_image_config()
        if cfg.get("enabled", True):
            tmp_dir = tempfile.mkdtemp(prefix="storycta_")
            tmp_path = Path(tmp_dir) / image.name
            if await asyncio.to_thread(transform_image, image, tmp_path, cfg, "storycta"):
                send_path = tmp_path
        intro = (
            f"📲 **STORY CTA — identité `{identity}`**\n"
            f"📥 Télécharge la photo + écris la caption dessus.\n\n"
            f"🕖 **À POSTER LE SOIR ENTRE 19H ET 23H** — c'est le créneau "
            f"où tes clics convertissent le mieux 💰"
        )
        try:
            await channel.send(content=intro, file=discord.File(send_path))
        except discord.HTTPException:
            return False
        await channel.send(caption)
        return True
    finally:
        if tmp_dir:
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


async def resolve_autopost_channel(bot, channel_id):
    """Un cache vide ne prouve pas que le salon a été supprimé."""
    channel_id = int(channel_id)
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await asyncio.wait_for(bot.fetch_channel(channel_id), timeout=30)
    if not callable(getattr(channel, "send", None)):
        raise ValueError("Le salon ne permet pas l'envoi de messages")
    return channel


@contextmanager
def _autopost_lock():
    """Un seul passage à la fois, y compris après un rechargement du cog."""
    AUTOPOST_RUNS.mkdir(parents=True, exist_ok=True)
    with (AUTOPOST_RUNS / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _load_autopost_run(day):
    path = AUTOPOST_RUNS / f"{day}.json"
    if not path.exists():
        return None
    # Ne jamais restaurer une ancienne copie de ce journal : elle pourrait
    # faire oublier une livraison déjà réalisée et provoquer un doublon.
    run = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(run, dict) or run.get("schema") != 1 or run.get("date") != day:
        raise ValueError("Journal Autopost invalide")
    if not isinstance(run.get("targets"), dict):
        raise ValueError("Cibles Autopost invalides")
    states = {"pending", "preparing", "sending", "retry", "sent", "failed", "uncertain", "cancelled"}
    for target in run["targets"].values():
        if not isinstance(target, dict) or not isinstance(target.get("items"), dict):
            raise ValueError("Cible Autopost invalide")
        for kind, item in target["items"].items():
            if kind not in AUTOPOST_KINDS or not isinstance(item, dict):
                raise ValueError("Contenu Autopost invalide")
            if item.get("status") not in states or not isinstance(item.get("attempts"), int):
                raise ValueError("État Autopost invalide")
    return run


class AutopostJournalError(OSError):
    pass


def _save_autopost_run(run):
    if not safe_json.write(AUTOPOST_RUNS / f"{run['date']}.json", run, backup=False):
        raise AutopostJournalError("Impossible de sauvegarder le suivi Autopost ; envois suspendus")


def _autopost_target(raw):
    if isinstance(raw, str):
        return raw, None, True
    if not isinstance(raw, dict):
        raise ValueError("Fiche VA invalide")
    channel_id = raw.get("channel_id")
    try:
        channel_id = int(channel_id) if channel_id else None
    except (TypeError, ValueError):
        channel_id = None
    return raw.get("identity"), channel_id, raw.get("auto_post", True)


def _en_pause(identity) -> bool:
    """identite_pause.en_pause, repli OUVERT et journalise : un module qui ne
    repond pas ne coupe pas l'autopost de tout le monde."""
    try:
        import identite_pause as _ip
        return _ip.en_pause(identity)
    except Exception as exc:
        log.warning("controle « pause » indisponible pour %r (%s)", identity, type(exc).__name__)
        return False


def _new_autopost_run(day, cfg, users):
    targets = {}
    kinds = [kind for kind in AUTOPOST_KINDS if cfg.get(f"post_{kind}", True)]
    for user_id, raw in users.items():
        identity, channel_id, enabled = _autopost_target(raw)
        if not enabled or not kinds:
            continue
        valid = bool(identity and channel_id)
        # Identite en pause : annulee AVEC sa raison, visible dans le bilan.
        pause = valid and _en_pause(identity)
        targets[user_id] = {
            "identity": identity, "channel_id": channel_id,
            "items": {kind: {"status": ("cancelled" if pause else "pending") if valid else "failed",
                             "attempts": 0,
                             "reason": ("identity_paused" if pause else "") if valid
                                       else "identity_or_channel_missing"}
                      for kind in kinds},
        }
    return {"schema": 1, "date": day, "targets": targets}


def _autopost_users_strict():
    users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    if not isinstance(users, dict):
        raise ValueError("Base des VAs invalide")
    return users


class AutopostDeliveryUncertain(Exception):
    """Discord a pu recevoir un message sans que le bot reçoive sa réponse."""


class _TrackedAutopostChannel:
    def __init__(self, channel, run, item):
        self.channel, self.run, self.item = channel, run, item

    async def send(self, *args, **kwargs):
        self.item["status"] = "sending"
        _save_autopost_run(self.run)  # obligatoirement AVANT l'appel Discord
        try:
            message = await self.channel.send(*args, **kwargs)
        except discord.HTTPException as exc:
            if 400 <= exc.status < 500:
                # Rejet explicite : conserver le repli historique sans exemple
                # lorsque Discord refuse la taille des pièces jointes du reel.
                self.item["status"] = "sending" if self.item.get("message_ids") else "preparing"
                raise
            raise AutopostDeliveryUncertain("Réponse Discord incertaine") from exc
        except Exception as exc:
            raise AutopostDeliveryUncertain("Réponse Discord incertaine") from exc
        self.item.setdefault("message_ids", []).append(str(message.id))
        _save_autopost_run(self.run)
        return message


def _autopost_retry(item, reason, now):
    item.update(status="retry" if item["attempts"] < AUTOPOST_MAX_ATTEMPTS else "failed",
                reason=reason, retry_after=now.timestamp() + AUTOPOST_RETRY_SECONDS)


def _autopost_summary(run):
    served = errors = 0
    states = {}
    for target in run["targets"].values():
        items = list(target["items"].values())
        served += any(item["status"] == "sent" or item.get("message_ids") for item in items)
        errors += any(item["status"] in {"failed", "uncertain", "retry"} for item in items)
        for item in items:
            state = item["status"]
            states[state] = states.get(state, 0) + 1
    return served, errors, states


async def run_autopost_for_all(bot, *, now=None):
    """Run du jour et reprise bornée des seuls contenus sans livraison possible."""
    clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    now = clock()
    cfg = load_autopost_config()
    if not cfg.get("enabled", False) or not bot.is_ready():
        return None
    scheduled = now.replace(hour=int(cfg.get("hour_utc", 7)), minute=int(cfg.get("minute_utc", 0)),
                            second=0, microsecond=0)
    if now < scheduled:
        return None
    today = now.date().isoformat()
    with _autopost_lock() as acquired:
        if not acquired:
            return None
        run = _load_autopost_run(today)
        if run is None and cfg.get("last_run_date") == today:
            # Migration : cette journée a déjà été traitée sans journal détaillé.
            # Ne pas la rejouer, même si certains anciens envois ont échoué.
            return None
        # Lecture stricte : une base illisible ne doit pas solder la journée à vide.
        users = _autopost_users_strict()
        if run is None:
            run = _new_autopost_run(today, cfg, users)
            _save_autopost_run(run)
        if run.get("finished_at"):
            return None
        changed = False
        for user_id, target in run["targets"].items():
            channel = None
            for kind, item in target["items"].items():
                if item["status"] == "sending":
                    item.update(status="uncertain", reason="interrupted_during_delivery")
                    _save_autopost_run(run)
                    changed = True
                if item["status"] in {"sent", "failed", "uncertain", "cancelled"}:
                    continue
                # Arrêter aussi si le service est désactivé pendant un long run.
                latest = load_autopost_config()
                if not latest.get("enabled", False) or not bot.is_ready() or clock().date() != now.date():
                    return _autopost_summary(run)[:2]
                current = _autopost_target(_autopost_users_strict().get(user_id, {}))
                if (not current[2] or current[:2] != (target["identity"], target["channel_id"])
                        or not latest.get(f"post_{kind}", True)):
                    item.update(status="cancelled", reason="configuration_changed")
                    _save_autopost_run(run)
                    changed = True
                    continue
                if _en_pause(target["identity"]):
                    # mise en pause PENDANT le passage
                    item.update(status="cancelled", reason="identity_paused")
                    _save_autopost_run(run)
                    changed = True
                    continue
                if item.get("retry_after", 0) > clock().timestamp():
                    continue
                if item["attempts"] >= AUTOPOST_MAX_ATTEMPTS:
                    item.update(status="failed", reason="attempt_limit")
                    _save_autopost_run(run)
                    changed = True
                    continue
                changed = True
                item.update(status="preparing", attempts=item["attempts"] + 1)
                _save_autopost_run(run)
                try:
                    if channel is None:
                        channel = await resolve_autopost_channel(bot, target["channel_id"])
                except (discord.NotFound, discord.Forbidden, ValueError) as exc:
                    item.update(status="failed", reason=type(exc).__name__)
                    _save_autopost_run(run)
                    continue
                except Exception as exc:
                    _autopost_retry(item, f"channel_{type(exc).__name__}", clock())
                    _save_autopost_run(run)
                    continue
                tracked = _TrackedAutopostChannel(channel, run, item)
                try:
                    sender = globals()[f"send_{kind}"]
                    ok = await asyncio.wait_for(sender(tracked, target["identity"]), timeout=300)
                except AutopostJournalError:
                    # Un journal non durable impose l'arrêt, pas un nouvel envoi.
                    raise
                except Exception as exc:
                    if item["status"] == "sending" or item.get("message_ids"):
                        item.update(status="uncertain", reason=type(exc).__name__)
                    else:
                        _autopost_retry(item, type(exc).__name__, clock())
                else:
                    if ok:
                        item.update(status="sent", reason="")
                    elif item.get("message_ids"):
                        item.update(status="uncertain", reason="partial_delivery")
                    else:
                        _autopost_retry(item, "no_media_or_send_rejected", clock())
                _save_autopost_run(run)
        count, errors, states = _autopost_summary(run)
        if not any(states.get(state) for state in ("pending", "preparing", "sending", "retry")):
            run["finished_at"] = clock().isoformat()
            _save_autopost_run(run)
            latest = load_autopost_config()
            latest["last_run_date"] = today
            save_autopost_config(latest)
        if changed or errors:
            log.info("Autopost: %s VA(s) avec livraison, %s VA(s) en erreur ; contenus %s", count, errors, states)
        return count, errors


async def run_broadcast(
    bot,
    identity_filter: str = None,
    n_reels: int = 0,
    n_posts: int = 0,
    n_stories: int = 0,
    n_storyctas: int = 0,
):
    """Envoie N de chaque type a chaque VA correspondant (ou tous si filter=None).

    Retourne (nb_vas_touches, nb_erreurs, details) ou `details` compte ce qui
    n'est PAS parti : VAs dont le salon est introuvable, VAs pour lesquels
    AUCUN media n'a pu etre envoye (stock vide pour leur identite), et le
    nombre reel d'envois. Sans ces compteurs, /broadcast annoncait « N VAs
    touches » et un total d'items alors qu'une identite sans stock ne recevait
    strictement rien — send_reel/post/story rendent False en silence.
    """
    users = load_users()
    count = 0
    errors = 0
    envois = 0        # medias REELLEMENT postes
    sans_salon = 0    # salon introuvable (bot absent du serveur, salon supprime)
    sans_contenu = 0  # VA cible mais 0 media envoye (stock de l'identite vide)
    en_pause = 0      # VA dont l'identite est en pause : rien d'envoye, compte
    vides = {}        # identite -> nb de VAs restes sans rien
    for user_id_str, raw_data in users.items():
        if isinstance(raw_data, str):
            identity = raw_data
            channel_id = None
            auto_enabled = True
        else:
            identity = raw_data.get("identity")
            channel_id = raw_data.get("channel_id")
            auto_enabled = raw_data.get("auto_post", True)
        if not auto_enabled or not channel_id or not identity:
            continue
        # Filtre par identite si specifie (comparaison case-insensitive)
        if identity_filter and identity.lower() != identity_filter.lower():
            continue
        if _en_pause(identity):
            en_pause += 1
            continue
        try:
            channel = await resolve_autopost_channel(bot, channel_id)
        except Exception as exc:
            sans_salon += 1
            errors += 1
            log.warning("Broadcast: salon %s inaccessible pour %s (%s)", channel_id, user_id_str, type(exc).__name__)
            continue
        try:
            n_ok = 0
            for _ in range(n_reels):
                n_ok += 1 if await send_reel(channel, identity) else 0
            for _ in range(n_posts):
                n_ok += 1 if await send_post(channel, identity) else 0
            for _ in range(n_stories):
                n_ok += 1 if await send_story(channel, identity) else 0
            for _ in range(n_storyctas):
                n_ok += 1 if await send_storycta(channel, identity) else 0
            envois += n_ok
            if n_ok:
                count += 1
            else:
                sans_contenu += 1
                vides[identity] = vides.get(identity, 0) + 1
                log.warning(f"Broadcast: rien envoye a {user_id_str} "
                            f"(identite {identity} sans stock ?)")
            if n_ok < n_reels + n_posts + n_stories + n_storyctas:
                errors += 1
        except Exception as e:
            log.error(f"Broadcast erreur pour user {user_id_str}: {e}")
            errors += 1
    return count, errors, {"envois": envois, "sans_salon": sans_salon,
                           "sans_contenu": sans_contenu, "vides": vides, "en_pause": en_pause}


class AutoPost(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self.check_autopost.start()

    def cog_unload(self):
        self.check_autopost.cancel()

    async def get_owner_id(self):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return self._owner_id

    async def is_admin(self, user_id):
        if user_id == await self.get_owner_id():
            return True
        wl_path = DATA_DIR / "whitelist.json"
        if wl_path.exists():
            try:
                wl = json.loads(wl_path.read_text(encoding="utf-8"))
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

    @tasks.loop(minutes=1)
    async def check_autopost(self):
        try:
            await run_autopost_for_all(self.bot)
        except Exception:
            # Une panne de stockage ou une configuration invalide ne doit pas
            # tuer définitivement le planificateur de tous les jours suivants.
            log.exception("Autopost: passage interrompu ; suivi conservé, prochain contrôle dans une minute")

    @check_autopost.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="autopostsettings", description="Affiche la config de l'auto-post quotidien")
    async def autopostsettings(self, interaction: discord.Interaction):
        if not await self.require_admin(interaction):
            return
        cfg = load_autopost_config()
        msg = (
            f"⚙️ **Auto-post quotidien**\n"
            f"État: {'✅ Activé' if cfg.get('enabled') else '❌ Désactivé'}\n"
            f"Heure: **{cfg.get('hour_utc'):02d}:{cfg.get('minute_utc'):02d} UTC** "
            f"({(cfg.get('hour_utc') + 2) % 24:02d}h Paris été, {(cfg.get('hour_utc') + 1) % 24:02d}h Paris hiver)\n"
            f"Dernier run: {cfg.get('last_run_date') or 'jamais'}\n\n"
            f"📦 Contenu posté:\n"
            f"  • Reel: {'✅' if cfg.get('post_reel') else '❌'}\n"
            f"  • Post: {'✅' if cfg.get('post_post') else '❌'}\n"
            f"  • Story: {'✅' if cfg.get('post_story') else '❌'}\n"
            f"  • Story CTA: {'✅' if cfg.get('post_storycta') else '❌'}\n"
        )
        try:
            run = _load_autopost_run(datetime.now(timezone.utc).date().isoformat())
            if run:
                served, errors, states = _autopost_summary(run)
                msg += (f"\n📋 Suivi du jour : {served} VA(s) avec livraison, {errors} en erreur.\n"
                        f"Contenus confirmés : {states.get('sent', 0)} ; "
                        f"à réessayer : {states.get('retry', 0)} ; "
                        f"échecs : {states.get('failed', 0)} ; "
                        f"à vérifier sans renvoi : {states.get('uncertain', 0)}.\n")
        except Exception:
            msg += "\n⚠️ Suivi du jour illisible : les envois automatiques sont suspendus.\n"
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="autopostenable", description="Active/désactive l'auto-post quotidien")
    @app_commands.describe(enabled="True ou False")
    async def autopostenable(self, interaction: discord.Interaction, enabled: bool):
        if not await self.require_admin(interaction):
            return
        cfg = load_autopost_config()
        cfg["enabled"] = enabled
        save_autopost_config(cfg)
        await interaction.response.send_message(
            f"✅ Auto-post : {'activé' if enabled else 'désactivé'}", ephemeral=True
        )

    @app_commands.command(name="autoposttime", description="Change l'heure du run quotidien (UTC)")
    @app_commands.describe(hour="Heure UTC (0-23)", minute="Minute (0-59)")
    async def autoposttime(self, interaction: discord.Interaction, hour: int, minute: int = 0):
        if not await self.require_admin(interaction):
            return
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            await interaction.response.send_message("Heure invalide.", ephemeral=True)
            return
        cfg = load_autopost_config()
        cfg["hour_utc"] = hour
        cfg["minute_utc"] = minute
        save_autopost_config(cfg)
        await interaction.response.send_message(
            f"✅ Heure de l'auto-post : **{hour:02d}:{minute:02d} UTC**", ephemeral=True
        )

    @app_commands.command(name="autoposttoggle", description="Active/désactive un type de contenu pour l'auto-post")
    @app_commands.describe(content_type="reel, post, story ou storycta", enabled="True ou False")
    async def autoposttoggle(self, interaction: discord.Interaction, content_type: str, enabled: bool):
        if not await self.require_admin(interaction):
            return
        key = f"post_{content_type.lower()}"
        if key not in ("post_reel", "post_post", "post_story", "post_storycta"):
            await interaction.response.send_message(
                "Type invalide. Utilise: reel, post, story, storycta", ephemeral=True
            )
            return
        cfg = load_autopost_config()
        cfg[key] = enabled
        save_autopost_config(cfg)
        await interaction.response.send_message(
            f"✅ Auto-post `{content_type}` : {'activé' if enabled else 'désactivé'}", ephemeral=True
        )

    @app_commands.command(
        name="broadcast",
        description="[ADMIN] Envoie N reels/posts/stories/storyctas a tous les VAs (filtre par identite)",
    )
    @app_commands.describe(
        identite="Si specifie, envoie SEULEMENT aux VAs de cette identite (ex: julia). Vide = tous.",
        reels="Nombre de reels a envoyer a chaque VA (defaut 0)",
        posts="Nombre de posts photo a envoyer a chaque VA (defaut 0)",
        stories="Nombre de stories a envoyer a chaque VA (defaut 0)",
        storyctas="Nombre de story CTAs a envoyer a chaque VA (defaut 0)",
    )
    async def broadcast(
        self,
        interaction: discord.Interaction,
        identite: str = None,
        reels: app_commands.Range[int, 0, 20] = 0,
        posts: app_commands.Range[int, 0, 20] = 0,
        stories: app_commands.Range[int, 0, 20] = 0,
        storyctas: app_commands.Range[int, 0, 20] = 0,
    ):
        if not await self.require_admin(interaction):
            return
        total = reels + posts + stories + storyctas
        if total == 0:
            await interaction.response.send_message(
                "Tu dois specifier au moins un type de contenu (reels / posts / stories / storyctas > 0).\n"
                "Exemple: `/broadcast identite:julia reels:3 stories:3 storyctas:1`",
                ephemeral=True,
            )
            return
        if total > 30:
            await interaction.response.send_message(
                f"Trop d'items demandes ({total}). Limite: 30 par VA pour eviter le spam.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        filtre_msg = f"identite **{identite}**" if identite else "**tous les VAs**"
        await interaction.followup.send(
            f"🚀 Broadcast en cours sur {filtre_msg} : "
            f"{reels} reels + {posts} posts + {stories} stories + {storyctas} CTAs par VA...",
            ephemeral=True,
        )
        count, errors, det = await run_broadcast(
            self.bot,
            identity_filter=identite,
            n_reels=reels,
            n_posts=posts,
            n_stories=stories,
            n_storyctas=storyctas,
        )
        # On annonce le nombre d'envois REELS (avant : count * total, un chiffre
        # theorique qui restait juste meme quand une identite sans stock n'avait
        # rien recu du tout).
        msg = (f"✅ Broadcast termine : **{count}** VA(s) servis, "
               f"**{det['envois']}** item(s) envoyes, **{errors}** erreur(s).")
        if det["sans_contenu"]:
            detail = ", ".join(f"`{k}` ×{v}" for k, v in sorted(det["vides"].items()))
            msg += (f"\n⚠️ **{det['sans_contenu']} VA(s) n'ont RIEN recu** — aucun media "
                    f"disponible pour leur identite ({detail}). Ajoute du contenu "
                    f"(`/addreels`, `/addstories`, …).")
        if det["sans_salon"]:
            msg += (f"\n⚠️ {det['sans_salon']} VA(s) ignores : salon introuvable "
                    f"(salon supprime, ou bot absent de leur serveur).")
        if det.get("en_pause"):
            msg += (f"\n⏸ {det['en_pause']} VA(s) ignores : leur identite est en pause "
                    f"(Vault → Modifier → Réactiver).")
        await interaction.followup.send(msg[:1990], ephemeral=True)

    @app_commands.command(name="setvachannel", description="[ADMIN] Définit le salon d'auto-post pour un VA")
    @app_commands.describe(user="Le VA", channel="Le salon (laisse vide pour utiliser le salon courant)")
    async def setvachannel(self, interaction: discord.Interaction, user: discord.Member, channel: discord.TextChannel = None):
        if not await self.require_admin(interaction):
            return
        target_channel = channel or interaction.channel
        users = load_users()
        data = users.get(str(user.id))
        if data is None:
            await interaction.response.send_message(
                f"{user.mention} n'a pas d'identité. Fais /adduser d'abord.", ephemeral=True
            )
            return
        if isinstance(data, str):
            users[str(user.id)] = {"identity": data, "channel_id": target_channel.id, "auto_post": True}
        else:
            data["channel_id"] = target_channel.id
            users[str(user.id)] = data
        save_users(users)
        await interaction.response.send_message(
            f"✅ Salon auto-post de {user.mention} : {target_channel.mention}", ephemeral=True
        )

    @app_commands.command(name="togglevaautopost", description="[ADMIN] Active/désactive l'auto-post pour UN VA spécifique")
    @app_commands.describe(user="Le VA", enabled="True ou False")
    async def togglevaautopost(self, interaction: discord.Interaction, user: discord.Member, enabled: bool):
        if not await self.require_admin(interaction):
            return
        users = load_users()
        data = users.get(str(user.id))
        if data is None:
            await interaction.response.send_message(f"{user.mention} n'a pas d'identité.", ephemeral=True)
            return
        if isinstance(data, str):
            users[str(user.id)] = {"identity": data, "channel_id": None, "auto_post": enabled}
        else:
            data["auto_post"] = enabled
            users[str(user.id)] = data
        save_users(users)
        await interaction.response.send_message(
            f"✅ Auto-post pour {user.mention} : {'activé' if enabled else 'désactivé'}", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(AutoPost(bot))
