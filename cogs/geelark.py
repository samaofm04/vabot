"""GeeLark integration : push media (reels/stories/storyctas) to cloud phones.

V2 features :
- /geelarkpush avec autocomplete sur groupe (API GeeLark) et identite (data locales)
- Si parametres heure/minute fournis : SCHEDULE quotidien (heure de Paris)
- Mode SEQUENTIEL : start phone -> attend running -> upload -> stop -> phone suivante
  (contourne le rate-limit "Too many requests for selected phone version")
- Background loop tasks.loop(minutes=1) qui declenche les schedules
- Storage litterbox.catbox.moe pour rendre les fichiers locaux du VPS accessibles via URL

Credentials :
- GEELARK_BEARER dans le .env du VPS
"""
import asyncio
import json
import logging
import os
import random
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger("vabot.geelark")

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
WHITELIST_FILE = DATA_DIR / "whitelist.json"
SCHEDULES_FILE = DATA_DIR / "geelark_schedules.json"

GEELARK_BASE = "https://openapi.geelark.com"
LITTERBOX_URL = "https://litterbox.catbox.moe/resources/internals/api.php"
LITTERBOX_EXPIRY = "72h"

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Status GeeLark : 2 = stopped. Les phones running ont un autre code.
PHONE_STOPPED_STATUS = 2

# Polling / timeouts
MAX_WAIT_RUNNING_SEC = 90    # combien on attend qu'une phone passe de stopped a running
POLL_INTERVAL_SEC = 5        # tous les X sec on re-check le statut

try:
    from zoneinfo import ZoneInfo
    PARIS_TZ = ZoneInfo("Europe/Paris")
except ImportError:
    PARIS_TZ = timezone(timedelta(hours=1))


def sanitize_identity_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or "").lower()).strip("_-")


# ---- Selection des fichiers locaux ----------------------------------------

def list_example_reels(identity: str) -> list[Path]:
    d = IDENTITIES_DIR / sanitize_identity_name(identity) / "videos"
    if not d.exists():
        return []
    return sorted([
        p for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
        and p.stem.lower().endswith(".example")
    ])


def list_stories(identity: str) -> list[Path]:
    d = IDENTITIES_DIR / sanitize_identity_name(identity) / "stories"
    if not d.exists():
        return []
    return sorted([
        p for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        and not p.stem.lower().endswith(".example")
    ])


def list_storyctas(identity: str) -> list[Path]:
    d = IDENTITIES_DIR / sanitize_identity_name(identity) / "storyctas"
    if not d.exists():
        return []
    return sorted([
        p for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    ])


def pick_n_unique(items: list[Path], n: int) -> list[Path]:
    if not items or n <= 0:
        return []
    if n >= len(items):
        return list(items)
    return random.sample(items, n)


# ---- Litterbox upload -----------------------------------------------------

def litterbox_upload_sync(file_path: Path) -> str:
    if not file_path.exists() or not file_path.is_file():
        raise RuntimeError(f"Fichier introuvable : {file_path}")
    size_mo = file_path.stat().st_size / (1024 * 1024)
    if size_mo > 1024:
        raise RuntimeError(f"Fichier trop lourd : {size_mo:.1f} Mo > 1024 Mo")
    with file_path.open("rb") as f:
        r = requests.post(
            LITTERBOX_URL,
            data={"reqtype": "fileupload", "time": LITTERBOX_EXPIRY},
            files={"fileToUpload": (file_path.name, f)},
            timeout=300,
        )
    if r.status_code != 200:
        raise RuntimeError(f"Litterbox HTTP {r.status_code} : {r.text[:200]}")
    url = r.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"Litterbox reponse invalide : {url[:200]}")
    return url


# ---- GeeLark API ----------------------------------------------------------

def gl_bearer() -> str | None:
    return os.getenv("GEELARK_BEARER")


def gl_headers() -> dict | None:
    b = gl_bearer()
    if not b:
        return None
    return {"Authorization": f"Bearer {b}", "Content-Type": "application/json"}


def gl_call_sync(path: str, payload: dict) -> tuple[int, dict]:
    headers = gl_headers()
    if not headers:
        raise RuntimeError(
            "GEELARK_BEARER non configure sur le VPS. "
            "Ajoute `GEELARK_BEARER=ta_cle` dans /opt/va-bot/.env puis redemarre va-bot."
        )
    r = requests.post(GEELARK_BASE + path, headers=headers, json=payload, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:500]}


def gl_list_phones_in_group(group_name: str, max_count: int = 500) -> list[dict]:
    phones = []
    page = 1
    while len(phones) < max_count:
        _, body = gl_call_sync("/open/v1/phone/list", {
            "page": page, "pageSize": 100, "groupName": group_name,
        })
        if body.get("code") != 0:
            raise RuntimeError(f"GeeLark list phones erreur : {body.get('msg', body)}")
        data = body.get("data", {})
        items = data.get("items", [])
        if not items:
            break
        phones.extend(items)
        total = data.get("total", 0)
        if len(phones) >= total:
            break
        page += 1
    return phones[:max_count]


def gl_list_all_groups() -> list[dict]:
    groups = []
    page = 1
    while len(groups) < 200:
        _, body = gl_call_sync("/open/v1/group/list", {"page": page, "pageSize": 100})
        if body.get("code") != 0:
            raise RuntimeError(f"GeeLark list groups erreur : {body.get('msg', body)}")
        data = body.get("data", {})
        items = data.get("list", [])
        if not items:
            break
        groups.extend(items)
        total = data.get("total", 0)
        if len(groups) >= total:
            break
        page += 1
    return groups


def gl_upload_file_to_phone(phone_id: str, file_url: str, file_name: str | None = None) -> dict:
    payload = {"id": str(phone_id), "fileUrl": file_url}
    if file_name:
        payload["fileName"] = file_name
    _, body = gl_call_sync("/open/v1/phone/uploadFile", payload)
    return body


def gl_start_phone(phone_id: str) -> dict:
    _, body = gl_call_sync("/open/v1/phone/start", {"ids": [str(phone_id)]})
    return body


def gl_stop_phone(phone_id: str) -> dict:
    _, body = gl_call_sync("/open/v1/phone/stop", {"ids": [str(phone_id)]})
    return body


def gl_get_phone_status(phone_id: str) -> int | None:
    """Retourne le status int d'un phone (None si pas trouve). Status 2 = stopped."""
    _, body = gl_call_sync("/open/v1/phone/list", {"page": 1, "pageSize": 200})
    if body.get("code") != 0:
        return None
    for it in body.get("data", {}).get("items", []):
        if str(it.get("id")) == str(phone_id):
            return it.get("status")
    return None


# ---- Persistance des schedules --------------------------------------------

def load_schedules() -> list:
    if not SCHEDULES_FILE.exists():
        return []
    try:
        return json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_schedules(items: list):
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


# ---- Cog Discord ----------------------------------------------------------

class GeeLark(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self.scheduler_loop.start()

    def cog_unload(self):
        self.scheduler_loop.cancel()

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
            msg = "Tu n'es pas autorise."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    # ============================================================
    # Coeur : prepare les URLs litterbox a partir de l'identite locale
    # ============================================================

    async def _prepare_urls(self, identite: str, reels: int, stories: int, storyctas: int) -> tuple[list[tuple[str, str]], str]:
        """Pioche les fichiers locaux + upload sur litterbox.

        Retourne (list de (url, filename), message d'erreur ou "").
        """
        reel_files = pick_n_unique(list_example_reels(identite), reels)
        story_files = pick_n_unique(list_stories(identite), stories)
        cta_files = pick_n_unique(list_storyctas(identite), storyctas)

        missing = []
        safe = sanitize_identity_name(identite)
        if reels > 0 and not reel_files:
            missing.append(f"reels example (`data/identities/{safe}/videos/*.example.*`)")
        if stories > 0 and not story_files:
            missing.append(f"stories (`data/identities/{safe}/stories/`)")
        if storyctas > 0 and not cta_files:
            missing.append(f"storyctas (`data/identities/{safe}/storyctas/`)")
        if missing:
            return [], f"Fichiers manquants pour `{identite}` :\n• " + "\n• ".join(missing)

        all_files = reel_files + story_files + cta_files
        urls = []
        for f in all_files:
            try:
                url = await asyncio.to_thread(litterbox_upload_sync, f)
                urls.append((url, f.name))
            except Exception as e:
                return [], f"Upload litterbox echoue pour `{f.name}` : {str(e)[:300]}"
        return urls, ""

    # ============================================================
    # Sequential push : 1 phone a la fois (start -> wait -> upload -> stop)
    # ============================================================

    async def _push_sequential(
        self,
        phones: list[dict],
        urls: list[tuple[str, str]],
        progress_send=None,
    ) -> dict:
        """Lance les uploads en mode sequentiel (1 phone a la fois).

        progress_send: callable async (str) -> None pour reporter le progress
        (peut etre None pour mode silencieux).

        Retourne un dict {ok, failed, started_failed, upload_failed, failures}.
        """
        async def progress(msg: str):
            if progress_send:
                try:
                    await progress_send(msg)
                except Exception:
                    pass

        ok_count = 0
        upload_failed_count = 0
        started_failed_count = 0
        failures = []

        for idx, phone in enumerate(phones, start=1):
            phone_id = phone["id"]
            phone_label = phone.get("serialName", phone_id)
            was_already_running = False

            # 0) Check si deja running (par ex. l'admin a demarre a la main)
            try:
                current_status = await asyncio.to_thread(gl_get_phone_status, phone_id)
            except Exception:
                current_status = None
            if current_status is not None and current_status != PHONE_STOPPED_STATUS:
                was_already_running = True
                # Skip start + wait, on attaque direct l'upload
            else:
                # 1) Demarrer la phone
                try:
                    start_res = await asyncio.to_thread(gl_start_phone, phone_id)
                except Exception as e:
                    started_failed_count += 1
                    if len(failures) < 8:
                        failures.append(f"{phone_label}: start exception ({str(e)[:60]})")
                    continue
                if start_res.get("code") != 0:
                    started_failed_count += 1
                    if len(failures) < 8:
                        failures.append(f"{phone_label}: start KO ({start_res.get('msg', '?')[:60]})")
                    continue
                data = start_res.get("data", {})
                if data.get("failAmount", 0) > 0:
                    fdets = data.get("failDetails", [{}])
                    started_failed_count += 1
                    if len(failures) < 8:
                        failures.append(f"{phone_label}: start refuse ({fdets[0].get('msg', '?')[:60]})")
                    continue

                # 2) Attend que la phone soit running (status != 2)
                running = False
                elapsed = 0
                while elapsed < MAX_WAIT_RUNNING_SEC:
                    await asyncio.sleep(POLL_INTERVAL_SEC)
                    elapsed += POLL_INTERVAL_SEC
                    try:
                        status = await asyncio.to_thread(gl_get_phone_status, phone_id)
                    except Exception:
                        status = None
                    if status is not None and status != PHONE_STOPPED_STATUS:
                        running = True
                        break
                if not running:
                    started_failed_count += 1
                    try:
                        await asyncio.to_thread(gl_stop_phone, phone_id)
                    except Exception:
                        pass
                    if len(failures) < 8:
                        failures.append(f"{phone_label}: timeout ({MAX_WAIT_RUNNING_SEC}s) pas running")
                    continue

            # 3) Upload tous les fichiers
            phone_upload_ok = True
            for url, fname in urls:
                try:
                    res = await asyncio.to_thread(gl_upload_file_to_phone, phone_id, url, fname)
                except Exception as e:
                    upload_failed_count += 1
                    phone_upload_ok = False
                    if len(failures) < 8:
                        failures.append(f"{phone_label} ({fname}): {str(e)[:60]}")
                    continue
                if res.get("code") != 0:
                    upload_failed_count += 1
                    phone_upload_ok = False
                    if len(failures) < 8:
                        failures.append(f"{phone_label} ({fname}): {res.get('msg', '?')[:60]}")

            # 4) Stop la phone — UNIQUEMENT si on l'a demarree nous-meme
            # (si l'admin l'avait demarree manuellement, on la laisse running)
            if not was_already_running:
                try:
                    await asyncio.to_thread(gl_stop_phone, phone_id)
                except Exception:
                    pass

            if phone_upload_ok:
                ok_count += 1
                mark = "✓" if not was_already_running else "✓ (deja running)"
                await progress(f"{mark} {idx}/{len(phones)} `{phone_label}` OK")
            else:
                await progress(f"✗ {idx}/{len(phones)} `{phone_label}` upload partiel")

        return {
            "ok": ok_count,
            "started_failed": started_failed_count,
            "upload_failed": upload_failed_count,
            "failures": failures,
        }

    # ============================================================
    # Slash command : /geelarkpush
    # ============================================================

    @app_commands.command(
        name="geelarkpush",
        description="[ADMIN] Push GeeLark : immediate ou planifie (heure Paris)",
    )
    @app_commands.describe(
        groupe="Groupe GeeLark (autocomplete)",
        identite="Identite locale (autocomplete)",
        reels="Nb de reels example par phone (defaut 0, max 5)",
        stories="Nb de stories par phone (defaut 0, max 10)",
        storyctas="Nb de story CTAs par phone (defaut 0, max 5)",
        heure="Heure (Paris) du push planifie (0-23). Vide = push immediat.",
        minute="Minute du push planifie (0-59, defaut 0). Ignore si heure vide.",
    )
    async def geelarkpush(
        self,
        interaction: discord.Interaction,
        groupe: str,
        identite: str,
        reels: app_commands.Range[int, 0, 5] = 0,
        stories: app_commands.Range[int, 0, 10] = 0,
        storyctas: app_commands.Range[int, 0, 5] = 0,
        heure: app_commands.Range[int, 0, 23] = None,
        minute: app_commands.Range[int, 0, 59] = 0,
    ):
        if not await self.require_admin(interaction):
            return

        # Nettoyage
        groupe = groupe.strip().strip('"').strip("'").strip()
        identite = identite.strip()
        total_per_phone = reels + stories + storyctas
        if total_per_phone == 0:
            await interaction.response.send_message(
                "Tu dois demander au moins 1 media (reels/stories/storyctas > 0).",
                ephemeral=True,
            )
            return

        # ============ MODE SCHEDULE ============
        if heure is not None:
            schedules = load_schedules()
            schedule = {
                "id": uuid.uuid4().hex[:8],
                "groupe": groupe,
                "identite": identite,
                "reels": reels,
                "stories": stories,
                "storyctas": storyctas,
                "hour_paris": heure,
                "minute_paris": minute,
                "recurring": True,  # daily by default
                "channel_id": interaction.channel_id,
                "created_by": interaction.user.id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_run_date": None,
            }
            schedules.append(schedule)
            save_schedules(schedules)
            await interaction.response.send_message(
                f"📅 **Push planifie**\n"
                f"• ID : `{schedule['id']}`\n"
                f"• Groupe : **{groupe}**\n"
                f"• Identite : **{identite}**\n"
                f"• Par phone : {reels} reels + {stories} stories + {storyctas} CTAs\n"
                f"• Heure (Paris) : **{heure:02d}:{minute:02d}** — chaque jour\n"
                f"• Mode : sequentiel (1 phone a la fois -> contourne le rate-limit)\n\n"
                f"💡 Pour annuler : modifie/efface manuellement `data/geelark_schedules.json` "
                f"(ou demande la commande d'annulation en V3).",
                ephemeral=True,
            )
            return

        # ============ MODE IMMEDIAT ============
        await interaction.response.defer(ephemeral=True)
        if not gl_bearer():
            await interaction.followup.send(
                "❌ `GEELARK_BEARER` non configure. Ajoute dans /opt/va-bot/.env puis restart va-bot.",
                ephemeral=True,
            )
            return

        # 1) Prepare URLs (pioche files + litterbox)
        urls, err = await self._prepare_urls(identite, reels, stories, storyctas)
        if err:
            await interaction.followup.send(f"❌ {err}", ephemeral=True)
            return

        # 2) Liste phones du groupe
        try:
            phones = await asyncio.to_thread(gl_list_phones_in_group, groupe, 500)
        except Exception as e:
            await interaction.followup.send(f"❌ GeeLark : {str(e)[:500]}", ephemeral=True)
            return
        if not phones:
            await interaction.followup.send(
                f"❌ Aucun phone dans le groupe **{groupe}**. Verifie le nom exact.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"🚀 **Push GeeLark (sequentiel)**\n"
            f"• Groupe : **{groupe}** ({len(phones)} phones)\n"
            f"• Identite : **{identite}**\n"
            f"• Fichiers : {len(urls)} (deja sur litterbox)\n"
            f"• Estimation : ~{len(phones) * 90 // 60} min (start + upload + stop par phone)\n\n"
            f"Le processus tourne en arriere-plan, je te tiendrai au courant...",
            ephemeral=True,
        )

        # 3) Sequential
        async def progress_to_channel(msg: str):
            try:
                ch = interaction.channel
                if ch:
                    await ch.send(msg)
            except Exception:
                pass

        result = await self._push_sequential(phones, urls, progress_send=progress_to_channel)

        msg = (
            f"✅ **Push termine**\n"
            f"• Phones OK : **{result['ok']}/{len(phones)}**\n"
            f"• Echec demarrage : **{result['started_failed']}**\n"
            f"• Echec upload : **{result['upload_failed']}**"
        )
        if result["failures"]:
            msg += "\n\n**Premiers echecs :**\n" + "\n".join(f"  • {x}" for x in result["failures"][:8])
        try:
            await interaction.followup.send(msg[:1990], ephemeral=True)
        except Exception:
            # Si l'interaction est expiree, on poste dans le channel
            ch = interaction.channel
            if ch:
                await ch.send(msg[:1990])

    @geelarkpush.autocomplete("groupe")
    async def _groupe_ac(self, interaction: discord.Interaction, current: str):
        if not gl_bearer():
            return [app_commands.Choice(name="GEELARK_BEARER non configure", value="")]
        try:
            groups = await asyncio.to_thread(gl_list_all_groups)
        except Exception as e:
            return [app_commands.Choice(name=f"Erreur API : {str(e)[:80]}", value="")]
        q = (current or "").strip().lower()
        matches = [g for g in groups if q in g.get("name", "").lower()] if q else groups
        matches = [g for g in matches if g.get("name") not in ("Ungrouped", "Station de recyclage")]
        return [app_commands.Choice(name=g["name"][:100], value=g["name"]) for g in matches[:25]]

    @geelarkpush.autocomplete("identite")
    async def _identite_ac(self, interaction: discord.Interaction, current: str):
        if not IDENTITIES_DIR.exists():
            return []
        names = sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())
        q = (current or "").strip().lower()
        if q:
            names = [n for n in names if q in n.lower()]
        return [app_commands.Choice(name=n, value=n) for n in names[:25]]

    # ============================================================
    # Background scheduler
    # ============================================================

    @tasks.loop(minutes=1)
    async def scheduler_loop(self):
        """Tourne toutes les minutes : check si un schedule doit etre declenche."""
        try:
            schedules = load_schedules()
            if not schedules:
                return
            now_paris = datetime.now(PARIS_TZ)
            today_str = now_paris.strftime("%Y-%m-%d")
            cur_hour = now_paris.hour
            cur_min = now_paris.minute
            modified = False
            for sched in schedules:
                if sched.get("last_run_date") == today_str:
                    continue  # deja fait aujourd'hui
                if sched["hour_paris"] != cur_hour or sched["minute_paris"] != cur_min:
                    continue
                # Declencher !
                log.info(f"GeeLark scheduler : declenche {sched['id']} ({sched['groupe']})")
                sched["last_run_date"] = today_str
                modified = True
                # Run in background pour ne pas bloquer le loop
                asyncio.create_task(self._run_scheduled(sched))
            if modified:
                save_schedules(schedules)
        except Exception as e:
            log.error(f"GeeLark scheduler erreur: {e}")

    @scheduler_loop.before_loop
    async def _scheduler_before(self):
        await self.bot.wait_until_ready()

    async def _run_scheduled(self, sched: dict):
        """Execute un schedule en background, notifie le channel a la fin."""
        channel_id = sched.get("channel_id")
        channel = self.bot.get_channel(channel_id) if channel_id else None

        async def notify(msg: str):
            if channel:
                try:
                    await channel.send(msg)
                except Exception:
                    pass

        await notify(
            f"🌙 **Push planifie {sched['id']} demarre** (heure Paris {sched['hour_paris']:02d}:{sched['minute_paris']:02d})\n"
            f"• Groupe : **{sched['groupe']}** / identite : **{sched['identite']}**\n"
            f"• {sched['reels']} reels + {sched['stories']} stories + {sched['storyctas']} CTAs par phone"
        )

        if not gl_bearer():
            await notify("❌ GEELARK_BEARER non configure, push annule.")
            return

        urls, err = await self._prepare_urls(
            sched["identite"], sched["reels"], sched["stories"], sched["storyctas"]
        )
        if err:
            await notify(f"❌ {err}")
            return

        try:
            phones = await asyncio.to_thread(gl_list_phones_in_group, sched["groupe"], 500)
        except Exception as e:
            await notify(f"❌ GeeLark : {str(e)[:500]}")
            return
        if not phones:
            await notify(f"❌ Aucun phone dans le groupe **{sched['groupe']}**.")
            return

        await notify(f"🚀 {len(phones)} phones a traiter en sequentiel (~{len(phones) * 90 // 60} min estime)...")

        result = await self._push_sequential(phones, urls, progress_send=notify)

        msg = (
            f"✅ **Push planifie {sched['id']} termine**\n"
            f"• Phones OK : **{result['ok']}/{len(phones)}**\n"
            f"• Echec demarrage : **{result['started_failed']}**\n"
            f"• Echec upload : **{result['upload_failed']}**"
        )
        if result["failures"]:
            msg += "\n\n**Premiers echecs :**\n" + "\n".join(f"  • {x}" for x in result["failures"][:8])
        await notify(msg[:1990])


async def setup(bot):
    await bot.add_cog(GeeLark(bot))
