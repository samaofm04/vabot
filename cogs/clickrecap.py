"""Récap quotidien des clics GetMySocial, posté chaque nuit dans le salon
va-<handle> de CHAQUE VA QUI A UN LIEN — avec SES clics (aujourd'hui / hier /
la quinzaine de paie en cours : 1–15 ou 16–fin de mois). En auto, les salons
sans lien sont ignorés (pas de spam). En test manuel sur un salon précis, on
affiche quand même le message « pas de lien » pour voir l'état.

Timing robuste sans zoneinfo : on poll toutes les 30 min et on calcule l'heure
de Paris à la main (DST inclus), pour lancer une seule fois après minuit Paris.
"""
import asyncio
import calendar
import datetime
import json
import pathlib
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

# Flag persistant (data/ gitignore -> état runtime VPS). Cron ON par défaut
# (opt-out) : le récap auto ne poste QUE dans les salons qui ont un lien, donc
# pas de spam « pas de lien ». On peut le couper via /recapclics_auto actif:false.
_CFG_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "clickrecap.json"


def _auto_enabled() -> bool:
    try:
        return bool(json.loads(_CFG_FILE.read_text(encoding="utf-8")).get("auto", True))
    except Exception:
        return True


def _set_auto(v: bool):
    try:
        _CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CFG_FILE.write_text(json.dumps({"auto": bool(v)}), encoding="utf-8")
    except Exception:
        pass


# Détection auto du lien d'un VA en scannant l'historique de son salon va-<handle>
# (cherche une URL getmysocial.com/<shortcode> postée par le bot/manager/boss).
_GMS_LINK_RE = re.compile(r"getmysocial\.com/([A-Za-z0-9_\-]+)", re.I)
# Détection robuste d'un salon VA, tolérante à un rond 🟢/🟠/🔴 en préfixe
_VA_CH_RE = re.compile(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$")


def _ch_handle(name):
    m = _VA_CH_RE.search((name or "").lower())
    return m.group(1) if m else None
_LINKCACHE_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "clickrecap_links.json"


def _load_linkcache() -> dict:
    try:
        return json.loads(_LINKCACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_linkcache(d: dict):
    try:
        _LINKCACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LINKCACHE_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _match_shortcode(sc, links):
    sc = (sc or "").lower()
    if not sc:
        return None
    for l in links:
        if (l.get("shortcode") or "").lower() == sc:
            return l
    return None

GMS_DOMAIN = "https://getmysocial.com"
FR_MONTHS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin",
             "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def _last_sunday(year: int, month: int) -> int:
    for week in reversed(calendar.monthcalendar(year, month)):
        if week[6]:  # dimanche
            return week[6]
    return 28


def _paris_now() -> datetime.datetime:
    """Heure locale de Paris calculée depuis l'UTC (CET=+1, CEST=+2).
    DST UE : dernier dimanche de mars 01:00 UTC → dernier dimanche d'octobre 01:00 UTC."""
    u = datetime.datetime.utcnow()
    y = u.year
    dst_start = datetime.datetime(y, 3, _last_sunday(y, 3), 1)
    dst_end = datetime.datetime(y, 10, _last_sunday(y, 10), 1)
    offset = 2 if (dst_start <= u < dst_end) else 1
    return u + datetime.timedelta(hours=offset)


def _pay_period(d: datetime.date):
    """Quinzaine de paie contenant la date d : (debut, fin)."""
    if d.day <= 15:
        return d.replace(day=1), d.replace(day=15)
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=16), d.replace(day=last)


def _fr(d: datetime.date) -> str:
    return f"{d.day} {FR_MONTHS[d.month]}"


NO_LINK_MSG = (
    "🔗 **Pas encore de lien GetMySocial.**\n"
    "Demande ton lien à un **manager** ou au **boss** "
    "(bouton « Demander un lien » dans tes commandes, ou `/lien`)."
)


class ClickRecap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self._last_run = None  # date ISO du dernier récap auto (anti-doublon)
        if _auto_enabled():
            self.daily_recap.start()

    def cog_unload(self):
        if self.daily_recap.is_running():
            self.daily_recap.cancel()

    async def _is_owner(self, uid):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return uid == self._owner_id

    # ---------- Loop : poll 30 min, déclenche 1×/jour après minuit Paris ----------
    @tasks.loop(minutes=30)
    async def daily_recap(self):
        now = _paris_now()
        dstr = now.date().isoformat()
        if now.hour == 0 and self._last_run != dstr:
            self._last_run = dstr
            try:
                await self._run_all()
            except Exception as e:
                print(f"[clickrecap] erreur loop : {e}")

    @daily_recap.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ---------- Coeur ----------
    async def _links(self):
        import gms
        res = await asyncio.to_thread(gms.list_all_links)
        return (res.get("links") or []) if res.get("ok") else []

    async def _resolve_link(self, ch, links):
        """Trouve le lien GMS d'un VA pour son salon va-<handle> :
        1) cache  2) nom du lien va_@handle  3) SCAN de l'historique du salon
        (1re URL getmysocial.com/<shortcode> qui correspond à un vrai lien)."""
        import gms
        handle = _ch_handle(getattr(ch, "name", ""))
        if not handle:
            return None
        cache = _load_linkcache()
        # 1) cache
        sc = cache.get(handle)
        if sc:
            l = _match_shortcode(sc, links)
            if l:
                return l
        # 2) nom du lien va_@handle
        l = gms.find_link_for_handle(handle, links)
        if l:
            cache[handle] = (l.get("shortcode") or "").lower()
            _save_linkcache(cache)
            return l
        # 3) scan de l'historique du salon
        try:
            async for msg in ch.history(limit=400):
                blobs = [msg.content or ""]
                for emb in msg.embeds:
                    blobs += [emb.title or "", emb.description or "", emb.url or ""]
                    for f in emb.fields:
                        blobs.append(f.value or "")
                for b in blobs:
                    for m in _GMS_LINK_RE.finditer(b or ""):
                        hit = _match_shortcode(m.group(1), links)
                        if hit:
                            cache[handle] = (hit.get("shortcode") or "").lower()
                            _save_linkcache(cache)
                            return hit
        except Exception as e:
            print(f"[clickrecap] scan historique #{getattr(ch, 'name', '?')} : {e}")
        return None

    def _build_message(self, link, gms, ref_yesterday, today):
        """(content, embed) pour un VA. link=None -> message 'pas de lien' (sans réseau)."""
        if not link:
            return (NO_LINK_MSG, None)
        lid = link.get("id")
        shortcode = link.get("shortcode") or ""
        p_start, p_end = _pay_period(ref_yesterday)
        c_today = gms.clicks_for_link(lid, today.isoformat(), today.isoformat())
        c_yest = gms.clicks_for_link(lid, ref_yesterday.isoformat(), ref_yesterday.isoformat())
        c_period = gms.clicks_for_link(lid, p_start.isoformat(), ref_yesterday.isoformat())

        def fmt(v):
            return "—" if v is None else f"**{v}**"

        emb = discord.Embed(
            title="📊 Tes clics — getmysocial.com",
            description=f"🔗 {GMS_DOMAIN}/{shortcode}",
            color=discord.Color.green() if (c_yest or 0) > 0 else discord.Color.dark_grey(),
        )
        emb.add_field(name="📅 Hier", value=f"{fmt(c_yest)} clic(s)", inline=True)
        emb.add_field(name="🟢 Aujourd'hui", value=f"{fmt(c_today)} clic(s)", inline=True)
        emb.add_field(
            name=f"🗓️ Quinzaine ({_fr(p_start)}–{_fr(p_end)})",
            value=f"{fmt(c_period)} clic(s)",
            inline=False,
        )
        emb.set_footer(text="Récap automatique chaque nuit · GetMySocial")
        return (None, emb)

    async def _recap_channel(self, ch, links, gms, today, yest, skip_if_no_link=False):
        """Poste le récap dans un salon va-<handle>. Retourne 'sent'|'nolink'|'skip'.
        skip_if_no_link=True -> on ne poste RIEN si le salon n'a pas de lien
        (utilisé par le cron auto : on ne reporte que là où il y a un lien)."""
        handle = _ch_handle(ch.name) or ""
        if not handle:
            return "skip"
        link = await self._resolve_link(ch, links)  # nom va_@ OU scan historique du salon
        if link is None and skip_if_no_link:
            return "skip"  # pas de lien -> pas de message (anti-spam)
        content, emb = await asyncio.to_thread(self._build_message, link, gms, yest, today)
        try:
            if emb is not None:
                await ch.send(content=content, embed=emb)
            else:
                await ch.send(content)
            return "sent" if link else "nolink"
        except discord.Forbidden:
            return "skip"
        except Exception as e:
            print(f"[clickrecap] envoi #{ch.name} échoué : {e}")
            return "skip"

    async def _run_all(self):
        import gms
        links = await self._links()
        today = _paris_now().date()
        yest = today - datetime.timedelta(days=1)
        sent = nolink = 0
        for guild in self.bot.guilds:
            for ch in guild.text_channels:
                if not _ch_handle(ch.name):
                    continue
                # Auto : on ne poste QUE dans les salons qui ont un lien (pas de spam).
                r = await self._recap_channel(ch, links, gms, today, yest, skip_if_no_link=True)
                if r == "sent":
                    sent += 1
                elif r == "nolink":
                    nolink += 1
                await asyncio.sleep(1.2)  # rate-limit friendly (Discord + GMS API)
        print(f"[clickrecap] récap posté : {sent} avec lien, {nolink} sans lien")
        return sent, nolink

    # ---------- Commandes ----------
    @app_commands.command(
        name="recapclics",
        description="[OWNER] Poste le récap des clics dans CE salon (test), ou partout",
    )
    @app_commands.describe(
        salon="Salon va-… du VA → APERÇU privé de son récap (recommandé : choisis le salon directement)",
        va="OU le pseudo exact (ce qui suit « va- » dans le nom du salon — PAS le nom affiché Discord)",
        partout="true = lance le récap dans TOUS les salons va- (comme le cron de minuit)",
    )
    async def recapclics(self, interaction: discord.Interaction,
                          salon: discord.TextChannel = None, va: str = None, partout: bool = False):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        # Aperçu CIBLÉ (par salon précis, ou pseudo) — montré en privé, rien posté chez le VA
        target_handle = None
        if salon is not None and _ch_handle(getattr(salon, "name", "")):
            target_handle = _ch_handle(salon.name)
        elif va:
            h = va.strip().lstrip("@")
            if h.lower().startswith("va-"):
                h = h[3:]
            target_handle = h
        if target_handle:
            links = await self._links()
            # retrouve le salon va-<handle> pour pouvoir scanner son historique
            tch = salon
            if tch is None:
                for g in self.bot.guilds:
                    tch = discord.utils.find(lambda c: _ch_handle(c.name) == target_handle, g.text_channels)
                    if tch is not None:
                        break
            if tch is not None:
                link = await self._resolve_link(tch, links)
            else:
                link = gms.find_link_for_handle(target_handle, links)
            today = _paris_now().date()
            yest = today - datetime.timedelta(days=1)
            if link:
                _c, emb = await asyncio.to_thread(self._build_message, link, gms, yest, today)
                via = " · 🔎 lien détecté dans l'historique du salon" if not gms.find_link_for_handle(target_handle, links) else ""
                await interaction.followup.send(
                    content=f"👁️ Aperçu — **va-{target_handle}** (test, non posté chez le VA){via} :",
                    embed=emb, ephemeral=True)
            else:
                va_names = sorted({(l.get("display_name") or "") for l in links
                                   if (l.get("display_name") or "").lower().startswith("va_@")})
                hint = ("\n\n**Liens `va_@…` existants sur GMS :**\n" + "\n".join("• `" + n + "`" for n in va_names[:25])) \
                    if va_names else "\n\n(aucun lien nommé `va_@…` sur GMS pour l'instant)"
                await interaction.followup.send(
                    f"👁️ **va-{target_handle}** : ❌ aucun lien `va_@{target_handle}` trouvé sur GMS.\n"
                    f"💡 Le récap relie le VA à son lien par le **nom du lien** `va_@<pseudo>` "
                    f"(le pseudo = ce qui suit `va-` dans le salon, **pas** le nom affiché Discord). "
                    f"Si son lien existe sous un autre nom, régénère-le via `/gmslink` **dans son salon** pour qu'il soit renommé `va_@{target_handle}`.{hint}",
                    ephemeral=True)
            return
        if partout:
            sent, nolink = await self._run_all()
            await interaction.followup.send(
                f"✅ Récap envoyé : **{sent}** salon(s) avec lien · **{nolink}** sans lien.",
                ephemeral=True,
            )
            return
        ch = interaction.channel
        if not _ch_handle(getattr(ch, "name", "")):
            await interaction.followup.send(
                "Lance cette commande dans un salon `va-<pseudo>` (ou `/recapclics partout:true`).",
                ephemeral=True,
            )
            return
        links = await self._links()
        today = _paris_now().date()
        yest = today - datetime.timedelta(days=1)
        r = await self._recap_channel(ch, links, gms, today, yest)
        msg = {"sent": "✅ Récap posté ici.", "nolink": "✅ Posté (ce VA n'a pas de lien).",
               "skip": "⚠️ Impossible de poster ici."}.get(r, "?")
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(
        name="recapclicstous",
        description="[OWNER] Envoie MAINTENANT le récap des clics dans TOUS les salons va- (sans rien à remplir)",
    )
    async def recapclicstous(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms  # noqa: F401  (vérifie juste que le module est dispo)
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        sent, nolink = await self._run_all()
        await interaction.followup.send(
            f"✅ Récap des clics envoyé dans **{sent}** salon(s) (ceux qui ont un lien). "
            f"Les salons sans lien sont ignorés.",
            ephemeral=True,
        )

    @app_commands.command(
        name="recapclics_auto",
        description="[OWNER] Active/désactive le récap clics AUTOMATIQUE de chaque nuit",
    )
    @app_commands.describe(actif="true = récap auto chaque nuit dans tous les salons va- · false = manuel seulement")
    async def recapclics_auto(self, interaction: discord.Interaction, actif: bool):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        _set_auto(actif)
        if actif and not self.daily_recap.is_running():
            self.daily_recap.start()
        elif not actif and self.daily_recap.is_running():
            self.daily_recap.cancel()
        await interaction.response.send_message(
            ("✅ Récap clics **automatique activé** (chaque nuit ~minuit, dans chaque salon va- **qui a un lien** — les autres sont ignorés)."
             if actif else
             "🛑 Récap clics automatique **désactivé**. Utilise `/recapclics` pour tester à la main."),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(ClickRecap(bot))
