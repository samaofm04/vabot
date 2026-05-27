"""GeeLark integration : push media (via Discord message links) to cloud phones.

Le flow:
- L'admin uploade ses videos example dans un salon Discord prive (avec son Nitro, donc
  jusqu'a 50 Mo) et ajoute les liens des messages au pool d'une identite via
  /geelark linkadd
- Pour /geelark push : le bot re-fetche les messages pour obtenir des URLs Discord
  CDN fraiches, puis les passe a l'API GeeLark qui telecharge les fichiers sur les
  phones du groupe
- Pas de re-upload cote bot => pas de limite 10 Mo

Credentials :
- GEELARK_BEARER dans le .env du VPS (Bearer token de l'API GeeLark)
"""
import asyncio
import json
import logging
import os
import random
import re
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

# Types de contenu supportes
VALID_TYPES = ("reel", "story", "storycta")

_MSG_LINK_RE = re.compile(
    r"https?://(?:www\.)?(?:discord|discordapp)\.com/channels/(\d+)/(\d+)/(\d+)"
)


def parse_message_link(link: str):
    m = _MSG_LINK_RE.search(link.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def sanitize_identity_name(name: str) -> str:
    """Normalise le nom d'identite : lowercase, espaces/special -> _"""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or "").lower()).strip("_-")


def geelark_links_file(identity: str) -> Path:
    safe = sanitize_identity_name(identity)
    return IDENTITIES_DIR / safe / "geelark_links.json"


def load_geelark_links(identity: str) -> dict:
    """Retourne {reel: [...], story: [...], storycta: [...]} pour une identite."""
    f = geelark_links_file(identity)
    if not f.exists():
        return {"reel": [], "story": [], "storycta": []}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {"reel": [], "story": [], "storycta": []}
    # garantit la presence des 3 cles
    for t in VALID_TYPES:
        data.setdefault(t, [])
    return data


def save_geelark_links(identity: str, data: dict):
    f = geelark_links_file(identity)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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
            "Ajoute la ligne `GEELARK_BEARER=ta_cle` dans /opt/va-bot/.env et redemarre le service."
        )
    r = requests.post(GEELARK_BASE + path, headers=headers, json=payload, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:500]}


def gl_list_phones_in_group(group_name: str, max_count: int = 500) -> list[dict]:
    """Liste tous les phones d'un groupe (paginated, max 500)."""
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


def gl_upload_file_to_phone(phone_id: str, file_url: str, file_name: str | None = None) -> dict:
    payload = {"id": str(phone_id), "fileUrl": file_url}
    if file_name:
        payload["fileName"] = file_name
    _, body = gl_call_sync("/open/v1/phone/uploadFile", payload)
    return body


# --- Group Discord ----------------------------------------------------------

class GeeLark(commands.Cog):
    geelark_group = app_commands.Group(
        name="geelark",
        description="Gestion des medias GeeLark (admin only)",
    )

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

    # ---- linkadd ----------------------------------------------------------

    @geelark_group.command(
        name="linkadd",
        description="Ajoute un lien de message Discord au pool d'une identite (pour push GeeLark)",
    )
    @app_commands.describe(
        identite="Nom de l'identite (ex: emma, amelia, lola)",
        type_="Type de media",
        lien="Lien du message Discord contenant la video/photo (clic droit -> Copier le lien)",
    )
    @app_commands.choices(type_=[
        app_commands.Choice(name="reel", value="reel"),
        app_commands.Choice(name="story", value="story"),
        app_commands.Choice(name="storycta", value="storycta"),
    ])
    async def linkadd(
        self,
        interaction: discord.Interaction,
        identite: str,
        type_: app_commands.Choice[str],
        lien: str,
    ):
        if not await self.require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        parsed = parse_message_link(lien)
        if not parsed:
            await interaction.followup.send(
                "Lien invalide. Format attendu : `https://discord.com/channels/SERVER/CHANNEL/MESSAGE`",
                ephemeral=True,
            )
            return
        _gid, cid, mid = parsed
        # Verifier que le bot peut acceder au message
        try:
            src_channel = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
            msg = await src_channel.fetch_message(mid)
        except discord.NotFound:
            await interaction.followup.send("Message introuvable.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "Le bot n'a pas acces a ce salon. Donne-lui la permission de voir/lire le salon.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(f"Erreur acces message : {str(e)[:200]}", ephemeral=True)
            return
        if not msg.attachments:
            await interaction.followup.send(
                "Ce message ne contient aucune piece jointe.", ephemeral=True
            )
            return
        # Stocker le lien
        data = load_geelark_links(identite)
        attachment_names = [a.filename for a in msg.attachments]
        data[type_.value].append({
            "channel_id": cid,
            "message_id": mid,
            "filenames": attachment_names,
        })
        save_geelark_links(identite, data)
        await interaction.followup.send(
            f"✅ Lien ajoute au pool **{type_.value}** de `{identite}` "
            f"({len(msg.attachments)} fichier(s) : "
            f"{', '.join(f'`{n}`' for n in attachment_names)}).\n"
            f"Pool actuel : {len(data[type_.value])} {type_.value}(s).",
            ephemeral=True,
        )

    # ---- linklist ---------------------------------------------------------

    @geelark_group.command(
        name="linklist",
        description="Liste les liens stockes pour une identite",
    )
    @app_commands.describe(identite="Nom de l'identite")
    async def linklist(self, interaction: discord.Interaction, identite: str):
        if not await self.require_admin(interaction):
            return
        data = load_geelark_links(identite)
        lines = [f"**Liens GeeLark — identite `{identite}`**\n"]
        for t in VALID_TYPES:
            entries = data.get(t, [])
            lines.append(f"\n__{t.upper()}__ ({len(entries)})")
            if not entries:
                lines.append("  *(vide)*")
            else:
                for i, e in enumerate(entries, start=1):
                    names = ", ".join(e.get("filenames", []))
                    lines.append(f"  {i}. {names or '(no name)'}")
        text = "\n".join(lines)
        await interaction.response.send_message(text[:1990], ephemeral=True)

    # ---- linkremove -------------------------------------------------------

    @geelark_group.command(
        name="linkremove",
        description="Retire un lien du pool par son index (vu via linklist)",
    )
    @app_commands.describe(
        identite="Nom de l'identite",
        type_="Type de media",
        index="Index du lien dans la liste (1 = premier)",
    )
    @app_commands.choices(type_=[
        app_commands.Choice(name="reel", value="reel"),
        app_commands.Choice(name="story", value="story"),
        app_commands.Choice(name="storycta", value="storycta"),
    ])
    async def linkremove(
        self,
        interaction: discord.Interaction,
        identite: str,
        type_: app_commands.Choice[str],
        index: int,
    ):
        if not await self.require_admin(interaction):
            return
        data = load_geelark_links(identite)
        entries = data.get(type_.value, [])
        if index < 1 or index > len(entries):
            await interaction.response.send_message(
                f"Index invalide. Il y a {len(entries)} {type_.value}(s).", ephemeral=True
            )
            return
        removed = entries.pop(index - 1)
        save_geelark_links(identite, data)
        names = ", ".join(removed.get("filenames", []))
        await interaction.response.send_message(
            f"✅ Lien #{index} ({names}) retire du pool **{type_.value}** de `{identite}`.",
            ephemeral=True,
        )

    # ---- push ------------------------------------------------------------

    @geelark_group.command(
        name="push",
        description="Push des medias vers tous les phones d'un groupe GeeLark",
    )
    @app_commands.describe(
        groupe="Nom exact du groupe GeeLark (ex: EMMA ANDRY)",
        identite="Identite locale d'ou piocher les medias (ex: emma)",
        reels="Nombre de reels a pousser sur chaque phone (defaut 0)",
        stories="Nombre de stories a pousser (defaut 0)",
        storyctas="Nombre de story CTAs a pousser (defaut 0)",
    )
    async def push(
        self,
        interaction: discord.Interaction,
        groupe: str,
        identite: str,
        reels: app_commands.Range[int, 0, 10] = 0,
        stories: app_commands.Range[int, 0, 10] = 0,
        storyctas: app_commands.Range[int, 0, 10] = 0,
    ):
        if not await self.require_admin(interaction):
            return
        total = reels + stories + storyctas
        if total == 0:
            await interaction.response.send_message(
                "Tu dois demander au moins 1 media (reels/stories/storyctas > 0).",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        if not gl_bearer():
            await interaction.followup.send(
                "❌ `GEELARK_BEARER` non configure sur le VPS. "
                "Ajoute la ligne `GEELARK_BEARER=ta_cle` dans `/opt/va-bot/.env` "
                "puis `systemctl restart va-bot`.",
                ephemeral=True,
            )
            return

        # 1) Liste des phones du groupe GeeLark
        try:
            phones = await asyncio.to_thread(gl_list_phones_in_group, groupe, 500)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur GeeLark : {str(e)[:500]}", ephemeral=True)
            return
        if not phones:
            await interaction.followup.send(
                f"❌ Aucun phone trouve dans le groupe **{groupe}**. "
                f"Verifie le nom exact (sensible a la casse).",
                ephemeral=True,
            )
            return

        # 2) Charger les liens de l'identite
        links = load_geelark_links(identite)
        if reels > 0 and not links.get("reel"):
            await interaction.followup.send(
                f"❌ Aucun lien reel configure pour `{identite}`. Ajoute-en avec "
                f"`/geelark linkadd identite:{identite} type_:reel lien:...`",
                ephemeral=True,
            )
            return
        if stories > 0 and not links.get("story"):
            await interaction.followup.send(
                f"❌ Aucun lien story configure pour `{identite}`.",
                ephemeral=True,
            )
            return
        if storyctas > 0 and not links.get("storycta"):
            await interaction.followup.send(
                f"❌ Aucun lien storycta configure pour `{identite}`.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"🚀 Push GeeLark en cours :\n"
            f"• Groupe : **{groupe}** ({len(phones)} phones)\n"
            f"• Identite : **{identite}**\n"
            f"• Par phone : {reels} reel(s) + {stories} story(s) + {storyctas} storycta(s)\n"
            f"= **{len(phones) * total}** uploads au total. Patiente...",
            ephemeral=True,
        )

        # 3) Resoudre les liens en URLs CDN fraiches
        async def resolve_attachments(link_entries: list, n: int):
            """Pioche n entries au hasard et retourne une liste d'URLs CDN fraiches."""
            urls = []
            picks = random.choices(link_entries, k=n) if n > 0 else []
            for entry in picks:
                cid = entry["channel_id"]
                mid = entry["message_id"]
                try:
                    src_ch = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
                    msg = await src_ch.fetch_message(mid)
                    if msg.attachments:
                        att = msg.attachments[0]
                        urls.append((att.url, att.filename))
                except Exception as e:
                    log.error(f"Erreur resolve link {cid}/{mid}: {e}")
            return urls

        per_phone_urls = []
        per_phone_urls.extend(await resolve_attachments(links.get("reel", []), reels))
        per_phone_urls.extend(await resolve_attachments(links.get("story", []), stories))
        per_phone_urls.extend(await resolve_attachments(links.get("storycta", []), storyctas))

        if not per_phone_urls:
            await interaction.followup.send(
                "❌ Aucun lien valide n'a pu etre resolu (messages supprimes ?).",
                ephemeral=True,
            )
            return

        # 4) Pour chaque phone, uploader chaque URL (en parallele limite)
        ok_phones = 0
        failed_phones = 0
        failed_uploads = 0
        total_uploads = 0
        failures = []

        async def upload_for_phone(phone):
            nonlocal total_uploads, failed_uploads
            phone_ok = True
            phone_id = phone["id"]
            for url, fname in per_phone_urls:
                total_uploads += 1
                try:
                    res = await asyncio.to_thread(
                        gl_upload_file_to_phone, phone_id, url, fname
                    )
                    if res.get("code") != 0:
                        failed_uploads += 1
                        phone_ok = False
                        if len(failures) < 5:
                            failures.append(
                                f"  • phone `{phone.get('serialName', phone_id)}` "
                                f"({fname}) : {res.get('msg', 'unknown')}"
                            )
                except Exception as e:
                    failed_uploads += 1
                    phone_ok = False
                    if len(failures) < 5:
                        failures.append(f"  • phone {phone_id} : {str(e)[:100]}")
            return phone_ok

        # On limite la concurrence pour pas spammer l'API
        semaphore = asyncio.Semaphore(5)

        async def with_semaphore(phone):
            async with semaphore:
                return await upload_for_phone(phone)

        results = await asyncio.gather(*[with_semaphore(p) for p in phones])
        ok_phones = sum(1 for r in results if r)
        failed_phones = len(phones) - ok_phones

        msg = (
            f"✅ **Push GeeLark termine**\n"
            f"• Phones OK : **{ok_phones}/{len(phones)}**\n"
            f"• Phones avec >=1 echec : **{failed_phones}**\n"
            f"• Total uploads tentes : {total_uploads} (echecs : {failed_uploads})"
        )
        if failures:
            msg += "\n\n**Premiers echecs :**\n" + "\n".join(failures)
        if failed_phones > 0:
            msg += (
                "\n\n💡 *Tip : les phones doivent etre demarres (running). "
                "Les phones eteintes refusent l'upload avec `env not running`.*"
            )
        await interaction.followup.send(msg[:1990], ephemeral=True)


async def setup(bot):
    await bot.add_cog(GeeLark(bot))
