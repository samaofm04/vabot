"""GeeLark integration : push media (reels/stories/storyctas) to cloud phones.

Le flow simple (V1) :
- Les medias sont deja stockes sur le VPS (data/identities/{identity}/videos|stories|storyctas/)
  via les commandes existantes (/setreelexample, /addstory, /addstorycta)
- /geelark push :
  1. Pioche au hasard les medias demandes pour l'identite
  2. Upload chaque fichier sur litterbox.catbox.moe (72h, public, gratuit)
  3. Passe l'URL litterbox a l'API GeeLark
  4. Chaque phone du groupe telecharge le fichier via cette URL

Credentials :
- GEELARK_BEARER dans le .env du VPS
"""
import asyncio
import json
import logging
import os
import random
from pathlib import Path

import discord
import requests
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("vabot.geelark")

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
WHITELIST_FILE = DATA_DIR / "whitelist.json"

GEELARK_BASE = "https://openapi.geelark.com"
LITTERBOX_URL = "https://litterbox.catbox.moe/resources/internals/api.php"
LITTERBOX_EXPIRY = "72h"  # 1h, 12h, 24h ou 72h

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def sanitize_identity_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or "").lower()).strip("_-")


# ---- Selection des fichiers locaux ----------------------------------------

def list_example_reels(identity: str) -> list[Path]:
    """Liste les fichiers `.example.*` (videos pretes a poster) d'une identite."""
    d = IDENTITIES_DIR / sanitize_identity_name(identity) / "videos"
    if not d.exists():
        return []
    return sorted([
        p for p in d.iterdir()
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and p.stem.lower().endswith(".example")
    ])


def list_stories(identity: str) -> list[Path]:
    d = IDENTITIES_DIR / sanitize_identity_name(identity) / "stories"
    if not d.exists():
        return []
    return sorted([
        p for p in d.iterdir()
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTS
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
    """Uploade un fichier local sur litterbox.catbox.moe.

    Retourne l'URL publique du fichier (valide 72h).
    Raise RuntimeError si l'upload echoue.
    """
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
    """Liste tous les groupes GeeLark (paginated, max 200)."""
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


def gl_count_phones_per_group_cache():
    """Cache local des phones par groupe (TTL court via fonction sync simple)."""
    counts = {}
    try:
        # Recup 1ere page de phones avec gros pageSize (suffit pour la plupart)
        _, body = gl_call_sync("/open/v1/phone/list", {"page": 1, "pageSize": 200})
        if body.get("code") == 0:
            for it in body.get("data", {}).get("items", []):
                gname = (it.get("group") or {}).get("name") or "(Ungrouped)"
                counts[gname] = counts.get(gname, 0) + 1
    except Exception:
        pass
    return counts


def gl_upload_file_to_phone(phone_id: str, file_url: str, file_name: str | None = None) -> dict:
    payload = {"id": str(phone_id), "fileUrl": file_url}
    if file_name:
        payload["fileName"] = file_name
    _, body = gl_call_sync("/open/v1/phone/uploadFile", payload)
    return body


# ---- Cog Discord ----------------------------------------------------------

class GeeLark(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None

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

    @app_commands.command(
        name="geelarkpush",
        description="[ADMIN] Push des medias (reels example/stories/storyctas) vers les phones d'un groupe GeeLark",
    )
    @app_commands.describe(
        groupe="Groupe GeeLark (autocomplete : tape pour voir les groupes dispo)",
        identite="Identite locale d'ou piocher les medias (autocomplete)",
        reels="Nombre de reels example a pousser par phone (defaut 0, max 5)",
        stories="Nombre de stories par phone (defaut 0, max 10)",
        storyctas="Nombre de story CTAs par phone (defaut 0, max 5)",
    )
    async def geelarkpush(
        self,
        interaction: discord.Interaction,
        groupe: str,
        identite: str,
        reels: app_commands.Range[int, 0, 5] = 0,
        stories: app_commands.Range[int, 0, 10] = 0,
        storyctas: app_commands.Range[int, 0, 5] = 0,
    ):
        if not await self.require_admin(interaction):
            return
        # Nettoyage defensif : enleve les guillemets eventuellement tapes par l'utilisateur
        groupe = groupe.strip().strip('"').strip("'").strip()
        identite = identite.strip()
        total_per_phone = reels + stories + storyctas
        if total_per_phone == 0:
            await interaction.response.send_message(
                "Tu dois demander au moins 1 media (reels/stories/storyctas > 0).",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        if not gl_bearer():
            await interaction.followup.send(
                "❌ `GEELARK_BEARER` non configure. Ajoute la ligne dans `/opt/va-bot/.env` "
                "puis `systemctl restart va-bot`.",
                ephemeral=True,
            )
            return

        # 1) Pioche les fichiers locaux
        reel_files = pick_n_unique(list_example_reels(identite), reels)
        story_files = pick_n_unique(list_stories(identite), stories)
        cta_files = pick_n_unique(list_storyctas(identite), storyctas)

        missing = []
        if reels > 0 and not reel_files:
            missing.append(f"reels example (`data/identities/{sanitize_identity_name(identite)}/videos/*.example.*`)")
        if stories > 0 and not story_files:
            missing.append(f"stories (`data/identities/{sanitize_identity_name(identite)}/stories/`)")
        if storyctas > 0 and not cta_files:
            missing.append(f"storyctas (`data/identities/{sanitize_identity_name(identite)}/storyctas/`)")
        if missing:
            await interaction.followup.send(
                f"❌ Fichiers manquants pour `{identite}` :\n• " + "\n• ".join(missing),
                ephemeral=True,
            )
            return

        # 2) Liste des phones du groupe
        try:
            phones = await asyncio.to_thread(gl_list_phones_in_group, groupe, 500)
        except Exception as e:
            await interaction.followup.send(f"❌ GeeLark : {str(e)[:500]}", ephemeral=True)
            return
        if not phones:
            await interaction.followup.send(
                f"❌ Aucun phone dans le groupe **{groupe}**. Verifie le nom exact "
                f"(sensible a la casse).",
                ephemeral=True,
            )
            return

        all_files = reel_files + story_files + cta_files
        await interaction.followup.send(
            f"🚀 **Push GeeLark**\n"
            f"• Groupe : **{groupe}** ({len(phones)} phones)\n"
            f"• Identite : **{identite}**\n"
            f"• Fichiers : {len(reel_files)} reel(s) + {len(story_files)} story(s) + {len(cta_files)} cta(s)\n"
            f"• Upload sur litterbox (1x par fichier)...",
            ephemeral=True,
        )

        # 3) Upload chaque fichier sur litterbox (1x) -> obtient les URLs
        urls = []  # list of (url, filename)
        for f in all_files:
            try:
                url = await asyncio.to_thread(litterbox_upload_sync, f)
                urls.append((url, f.name))
                log.info(f"GeeLark : litterbox OK {f.name} -> {url}")
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Upload litterbox echoue pour `{f.name}` : {str(e)[:300]}",
                    ephemeral=True,
                )
                return

        await interaction.followup.send(
            f"✅ {len(urls)} fichier(s) sur litterbox. "
            f"Envoi sur les {len(phones)} phones en cours...",
            ephemeral=True,
        )

        # 4) Pour chaque phone, lance les uploads en parallele (semaphore)
        ok_phones = 0
        failed_phones = 0
        total_uploads = 0
        failed_uploads = 0
        failures = []
        first_off = True

        async def upload_for_phone(phone):
            nonlocal total_uploads, failed_uploads, first_off
            phone_ok = True
            phone_id = phone["id"]
            phone_label = phone.get("serialName", phone_id)
            for url, fname in urls:
                total_uploads += 1
                try:
                    res = await asyncio.to_thread(gl_upload_file_to_phone, phone_id, url, fname)
                    if res.get("code") != 0:
                        failed_uploads += 1
                        phone_ok = False
                        if len(failures) < 5:
                            failures.append(
                                f"  • `{phone_label}` ({fname}) : {res.get('msg', '?')[:80]}"
                            )
                except Exception as e:
                    failed_uploads += 1
                    phone_ok = False
                    if len(failures) < 5:
                        failures.append(f"  • {phone_label} : {str(e)[:80]}")
            return phone_ok

        sem = asyncio.Semaphore(5)

        async def with_sem(p):
            async with sem:
                return await upload_for_phone(p)

        results = await asyncio.gather(*[with_sem(p) for p in phones])
        ok_phones = sum(1 for r in results if r)
        failed_phones = len(phones) - ok_phones

        msg = (
            f"✅ **Push GeeLark termine**\n"
            f"• Phones OK : **{ok_phones}/{len(phones)}**\n"
            f"• Phones avec >=1 echec : **{failed_phones}**\n"
            f"• Uploads tentes : {total_uploads} (echecs : {failed_uploads})"
        )
        if failures:
            msg += "\n\n**Premiers echecs :**\n" + "\n".join(failures)
        if failed_phones > 0:
            msg += (
                "\n\n💡 *Si tu vois `env not running` : les phones doivent etre "
                "demarres sur GeeLark avant la commande. V2 ajoutera l'auto-start.*"
            )
        await interaction.followup.send(msg[:1990], ephemeral=True)

    # ---- Autocomplete ----------------------------------------------------

    @geelarkpush.autocomplete("groupe")
    async def _groupe_ac(self, interaction: discord.Interaction, current: str):
        if not gl_bearer():
            return [app_commands.Choice(name="GEELARK_BEARER non configure sur le VPS", value="")]
        try:
            groups = await asyncio.to_thread(gl_list_all_groups)
        except Exception as e:
            return [app_commands.Choice(name=f"Erreur API : {str(e)[:80]}", value="")]
        q = (current or "").strip().lower()
        matches = [g for g in groups if q in g.get("name", "").lower()] if q else groups
        # Filtre Ungrouped et Station de recyclage qui sont peu utiles
        matches = [g for g in matches if g.get("name") not in ("Ungrouped", "Station de recyclage")]
        return [
            app_commands.Choice(name=g["name"][:100], value=g["name"])
            for g in matches[:25]
        ]

    @geelarkpush.autocomplete("identite")
    async def _identite_ac(self, interaction: discord.Interaction, current: str):
        if not IDENTITIES_DIR.exists():
            return []
        names = sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())
        q = (current or "").strip().lower()
        if q:
            names = [n for n in names if q in n.lower()]
        return [app_commands.Choice(name=n, value=n) for n in names[:25]]


async def setup(bot):
    await bot.add_cog(GeeLark(bot))
