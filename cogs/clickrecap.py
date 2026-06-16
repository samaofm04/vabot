"""Récap quotidien des clics GetMySocial, posté chaque nuit dans le salon
va-<handle> de CHAQUE VA — avec SES clics (aujourd'hui / hier / la quinzaine
de paie en cours : 1–15 ou 16–fin de mois). Si le VA n'a pas de lien :
message « pas de lien, demande à un manager ou au boss ».

Timing robuste sans zoneinfo : on poll toutes les 30 min et on calcule l'heure
de Paris à la main (DST inclus), pour lancer une seule fois après minuit Paris.
"""
import asyncio
import calendar
import datetime
import json
import pathlib

import discord
from discord import app_commands
from discord.ext import commands, tasks

# Flag persistant (data/ gitignore -> état runtime VPS). Cron OFF par défaut :
# on ne veut pas spammer « pas de lien » tant que les liens ne sont pas en va_@.
_CFG_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "clickrecap.json"


def _auto_enabled() -> bool:
    try:
        return bool(json.loads(_CFG_FILE.read_text(encoding="utf-8")).get("auto"))
    except Exception:
        return False


def _set_auto(v: bool):
    try:
        _CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CFG_FILE.write_text(json.dumps({"auto": bool(v)}), encoding="utf-8")
    except Exception:
        pass

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

    async def _recap_channel(self, ch, links, gms, today, yest):
        """Poste le récap dans un salon va-<handle>. Retourne 'sent'|'nolink'|'skip'."""
        handle = ch.name[3:] if ch.name.lower().startswith("va-") else ""
        if not handle:
            return "skip"
        link = gms.find_link_for_handle(handle, links)
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
                if not ch.name.lower().startswith("va-"):
                    continue
                r = await self._recap_channel(ch, links, gms, today, yest)
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
        va="Pseudo d'un VA précis → APERÇU privé de son récap (ne poste rien dans son salon)",
        partout="true = lance le récap dans TOUS les salons va- (comme le cron de minuit)",
    )
    async def recapclics(self, interaction: discord.Interaction, va: str = None, partout: bool = False):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        # Aperçu CIBLÉ d'un VA précis : montré en privé, rien posté chez le VA
        if va:
            handle = va.strip().lstrip("@")
            if handle.lower().startswith("va-"):
                handle = handle[3:]
            links = await self._links()
            link = gms.find_link_for_handle(handle, links)
            today = _paris_now().date()
            yest = today - datetime.timedelta(days=1)
            content, emb = await asyncio.to_thread(self._build_message, link, gms, yest, today)
            header = f"👁️ Aperçu récap pour **va-{handle}** (test — non posté chez le VA) :"
            if emb is not None:
                await interaction.followup.send(content=header, embed=emb, ephemeral=True)
            else:
                await interaction.followup.send(f"{header}\n{content}", ephemeral=True)
            return
        if partout:
            sent, nolink = await self._run_all()
            await interaction.followup.send(
                f"✅ Récap envoyé : **{sent}** salon(s) avec lien · **{nolink}** sans lien.",
                ephemeral=True,
            )
            return
        ch = interaction.channel
        if not getattr(ch, "name", "").lower().startswith("va-"):
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
            ("✅ Récap clics **automatique activé** (chaque nuit ~minuit, dans tous les salons va-)."
             if actif else
             "🛑 Récap clics automatique **désactivé**. Utilise `/recapclics` pour tester à la main."),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(ClickRecap(bot))
