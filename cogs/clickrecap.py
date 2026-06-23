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
import time

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


# ---- Report horaire des clics d'un GROUPE GMS (ex: Hybride) dans un salon dédié ----
# data/ est gitignore -> config runtime VPS. {guild_id: {channel_id, team_id,
# group_id, group_name, message_id}}. message_id = message live édité chaque heure.
_REPORT_CFG_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "report_click.json"


def _load_report_cfg() -> dict:
    try:
        d = json.loads(_REPORT_CFG_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_report_cfg(d: dict):
    try:
        _REPORT_CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _REPORT_CFG_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
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
# Cache court des clics calculés pour le bouton 'Mes clics' : évite de re-taper
# GetMySocial si un VA reclique rapidement (clé = (link_id, date du jour)).
_CLICKS_CACHE: dict = {}
_CLICKS_TTL = 60  # secondes
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


class MyClicksView(discord.ui.View):
    """Bouton persistant '📊 Mes clics' posé dans chaque salon va-.
    Au clic, le VA voit EN DIRECT ses clics (aujourd'hui / hier / semaine /
    quinzaine) pour le lien de CE salon. Réponse éphémère (privée)."""

    def __init__(self, cog=None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Mes clics", emoji="📊",
                       style=discord.ButtonStyle.primary, custom_id="myclicks:show")
    async def b_clicks(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog or interaction.client.get_cog("ClickRecap")
        if cog is None:
            await interaction.response.send_message("⚠️ Module indispo.", ephemeral=True)
            return
        await cog._handle_myclicks(interaction)


class ClickRecap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self._last_run = None  # date ISO du dernier récap auto (anti-doublon)
        self._report_last_hour = None  # heure Paris du dernier report horaire posté
        if _auto_enabled():
            self.daily_recap.start()
        self.hourly_report.start()

    async def cog_load(self):
        # Vue persistante : le bouton 'Mes clics' marche même après un restart.
        try:
            self.bot.add_view(MyClicksView(self))
        except Exception as e:
            print(f"[clickrecap] add_view échoué : {e}")

    def cog_unload(self):
        if self.daily_recap.is_running():
            self.daily_recap.cancel()
        if self.hourly_report.is_running():
            self.hourly_report.cancel()

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

    # ---------- Report HORAIRE des clics d'un groupe (ex: Hybride) ----------
    @tasks.loop(minutes=20)
    async def hourly_report(self):
        """Met à jour (édite) le message de report de chaque serveur configuré,
        une fois par heure Paris (aligné sur l'heure pile, survit aux restarts)."""
        now = _paris_now()
        if self._report_last_hour == now.hour:
            return
        self._report_last_hour = now.hour
        cfg = _load_report_cfg()
        for gid in list(cfg.keys()):
            try:
                await self._post_or_update_report(gid)
            except Exception as e:
                print(f"[reportclick] update {gid} échoué : {e}")
            await asyncio.sleep(1)

    @hourly_report.before_loop
    async def _before_report(self):
        await self.bot.wait_until_ready()

    async def _build_group_report(self, c: dict):
        """Construit l'embed du report d'un groupe : aujourd'hui / hier / semaine
        / période 1–15 / période 16–fin. None si le module GMS est indispo."""
        import gms
        team_id = c.get("team_id")
        group_id = c.get("group_id")
        identity = c.get("identity")  # si défini -> énumération par suffixe (clé API)
        name = c.get("group_name") or "Groupe"
        metas = await asyncio.to_thread(gms.report_links_meta, team_id, identity, group_id)
        # None = board GMS injoignable (cookie expiré, HTTP KO…). On NE réécrit
        # PAS le report avec un faux « 0 clic » : on skip et on garde le dernier
        # message valide (l'appelant voit None -> ne touche pas au message).
        if metas is None:
            return None
        ids = [m["id"] for m in metas if m.get("id")]
        today = _paris_now().date()
        yest = today - datetime.timedelta(days=1)
        week_start = today - datetime.timedelta(days=today.weekday())  # lundi
        last = calendar.monthrange(today.year, today.month)[1]
        p1s, p1e = today.replace(day=1), today.replace(day=15)
        p2s, p2e = today.replace(day=16), today.replace(day=last)
        ranges = [
            (today, today),        # aujourd'hui
            (yest, yest),          # hier
            (week_start, today),   # cette semaine
            (p1s, p1e),            # période 1–15
            (p2s, p2e),            # période 16–fin
        ]
        vals = await asyncio.gather(*[
            asyncio.to_thread(gms.clicks_for_ids, ids, s.isoformat(), e.isoformat())
            for (s, e) in ranges
        ])
        c_today, c_yest, c_week, c_p1, c_p2 = vals
        all_none = all(v is None for v in vals)

        def fmt(v):
            return "—" if v is None else f"**{v}**"

        if all_none:
            color = discord.Color.orange()
        elif (c_today or 0) > 0 or (c_week or 0) > 0:
            color = discord.Color.green()
        else:
            color = discord.Color.dark_grey()
        emb = discord.Embed(
            title=f"📊 Report clics — {name}",
            description=f"Clics cumulés du groupe **{name}** ({len(ids)} lien(s)).",
            color=color,
        )
        emb.add_field(name="🟢 Aujourd'hui", value=f"{fmt(c_today)} clic(s)", inline=True)
        emb.add_field(name="📅 Hier", value=f"{fmt(c_yest)} clic(s)", inline=True)
        emb.add_field(name=f"🗓️ Cette semaine (dep. {_fr(week_start)})",
                      value=f"{fmt(c_week)} clic(s)", inline=False)
        emb.add_field(name=f"💰 Période 1–15 ({_fr(p1s)}–{_fr(p1e)})",
                      value=f"{fmt(c_p1)} clic(s)", inline=True)
        emb.add_field(name=f"💰 Période 16–{p2e.day} ({_fr(p2s)}–{_fr(p2e)})",
                      value=f"{fmt(c_p2)} clic(s)", inline=True)
        if all_none:
            emb.add_field(name="⚠️ Données indisponibles",
                          value="GetMySocial ne répond pas pour l'instant.", inline=False)
        elif not ids:
            # board OK mais 0 lien : groupe réellement vide OU group_id périmé
            # (groupe supprimé/recréé) -> on le signale (sinon « 0 clic » trompeur).
            emb.color = discord.Color.orange()
            emb.add_field(
                name="⚠️ Aucun lien dans ce groupe",
                value="Groupe vide, ou config périmée (groupe supprimé/recréé). "
                      "Relance `/setreportclick` si c'est inattendu.", inline=False)

        # ---- Détail par VA : 1 ligne par lien (clics aujourd'hui + cycle en cours) ----
        # Limité pour borner les appels analytics + la taille de l'embed.
        _MAX_PER_VA = 60
        if ids and not all_none and len(ids) <= _MAX_PER_VA:
            cyc_s, cyc_e = _pay_period(today)  # quinzaine de paie en cours
            per = await asyncio.gather(*[
                asyncio.gather(
                    asyncio.to_thread(gms.clicks_for_link, m["id"], today.isoformat(), today.isoformat()),
                    asyncio.to_thread(gms.clicks_for_link, m["id"], cyc_s.isoformat(), cyc_e.isoformat()),
                )
                for m in metas if m.get("id")
            ])
            rows = []
            for m, (ct, cc) in zip([m for m in metas if m.get("id")], per):
                label = m.get("display_name") or m.get("shortcode") or "?"
                rows.append((label, ct, cc))
            # tri : plus de clics aujourd'hui en premier, puis cycle, puis nom
            rows.sort(key=lambda r: (-(r[1] or 0), -(r[2] or 0), str(r[0])))

            def _vfmt(v):
                return "—" if v is None else str(v)
            lines = [f"**{lab}** — {_vfmt(ct)} auj · {_vfmt(cc)} cycle" for lab, ct, cc in rows]
            # Découpe en blocs <1024 chars (limite Discord par field)
            block, blocks = "", []
            for ln in lines:
                if len(block) + len(ln) + 1 > 1000:
                    blocks.append(block)
                    block = ""
                block += ("\n" if block else "") + ln
            if block:
                blocks.append(block)
            for i, b in enumerate(blocks):
                title = (f"📋 Détail par VA — auj · cycle {cyc_s.day}–{cyc_e.day} {FR_MONTHS[cyc_s.month]}"
                         if i == 0 else "📋 Détail par VA (suite)")
                emb.add_field(name=title, value=b, inline=False)
        elif ids and not all_none and len(ids) > _MAX_PER_VA:
            emb.add_field(name="📋 Détail par VA",
                          value=f"_(trop de liens ({len(ids)}) pour le détail par lien — agrégat ci-dessus.)_",
                          inline=False)

        emb.set_footer(text=f"🕐 Mis à jour à {_paris_now().strftime('%H:%M')} · maj chaque heure · GetMySocial")
        return emb

    async def _post_or_update_report(self, guild_id: str):
        """Édite le message live de report du serveur, ou le poste (1re fois)."""
        cfg = _load_report_cfg()
        c = cfg.get(guild_id)
        if not c:
            return
        ch = self.bot.get_channel(int(c["channel_id"]))
        if ch is None:
            try:
                ch = await self.bot.fetch_channel(int(c["channel_id"]))
            except Exception:
                return
        emb = await self._build_group_report(c)
        if emb is None:
            return
        mid = c.get("message_id")
        msg = None
        if mid:
            try:
                msg = await ch.fetch_message(int(mid))
            except discord.NotFound:
                msg = None  # message vraiment supprimé -> on en reposte un
            except Exception:
                return  # erreur transitoire (5xx/perm) -> on garde l'ancien
        if msg is not None:
            try:
                await msg.edit(embed=emb)
                return
            except discord.NotFound:
                pass  # supprimé entre fetch et edit -> repost ci-dessous
            except Exception as e:
                # 5xx / perte de perm / 429 : on NE reposte PAS (sinon doublons
                # de messages épinglés qui s'accumulent) -> on garde l'ancien.
                print(f"[reportclick] edit transitoire échoué, ancien gardé : {e}")
                return
        try:
            m = await ch.send(embed=emb)
            try:
                await m.pin()
            except Exception:
                pass
            # Re-load juste avant d'écrire : un /reportclick_off ou un autre
            # /setreportclick a pu modifier le fichier pendant le ch.send().
            # On ne touche QUE le message_id de CE serveur (pas d'écrasement
            # du snapshot complet, pas de résurrection d'un guild supprimé).
            fresh = _load_report_cfg()
            if guild_id in fresh:
                fresh[guild_id]["message_id"] = m.id
                _save_report_cfg(fresh)
        except Exception as e:
            print(f"[reportclick] post initial échoué : {e}")

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

    async def _fetch_myclicks(self, lid, gms, today):
        """Récupère les 4 compteurs (aujourd'hui/hier/semaine/quinzaine) EN
        PARALLÈLE (au lieu de 4 appels réseau en série) + cache court.
        Retourne (c_today, c_yest, c_week, c_period) — chaque valeur int ou None."""
        ck = (lid, today.isoformat())
        cached = _CLICKS_CACHE.get(ck)
        if cached and (time.time() - cached[0]) < _CLICKS_TTL:
            return cached[1]
        yest = today - datetime.timedelta(days=1)
        week_start = today - datetime.timedelta(days=today.weekday())  # lundi
        p_start, _p_end = _pay_period(today)
        ranges = [
            (today, today),            # aujourd'hui
            (yest, yest),              # hier
            (week_start, today),       # cette semaine
            (p_start, today),          # quinzaine en cours
        ]
        vals = await asyncio.gather(*[
            asyncio.to_thread(gms.clicks_for_link, lid, s.isoformat(), e.isoformat())
            for (s, e) in ranges
        ])
        vals = tuple(vals)
        # On ne met en cache que les résultats exploitables (pas un échec total).
        if not all(v is None for v in vals):
            _CLICKS_CACHE[ck] = (time.time(), vals)
        return vals

    def _myclicks_embed(self, link, today, counts):
        """Construit l'embed à partir des compteurs déjà récupérés."""
        shortcode = link.get("shortcode") or ""
        week_start = today - datetime.timedelta(days=today.weekday())
        p_start, p_end = _pay_period(today)
        c_today, c_yest, c_week, c_period = counts
        all_none = all(v is None for v in counts)

        def fmt(v):
            return "—" if v is None else f"**{v}**"

        if all_none:
            color = discord.Color.orange()
        elif (c_today or 0) > 0 or (c_week or 0) > 0:
            color = discord.Color.green()
        else:
            color = discord.Color.dark_grey()
        emb = discord.Embed(
            title="📊 Tes clics — en direct",
            description=f"🔗 {GMS_DOMAIN}/{shortcode}",
            color=color,
        )
        emb.add_field(name="🟢 Aujourd'hui", value=f"{fmt(c_today)} clic(s)", inline=True)
        emb.add_field(name="📅 Hier", value=f"{fmt(c_yest)} clic(s)", inline=True)
        emb.add_field(name=f"🗓️ Cette semaine (depuis {_fr(week_start)})",
                      value=f"{fmt(c_week)} clic(s)", inline=False)
        emb.add_field(name=f"💰 Quinzaine ({_fr(p_start)}–{_fr(p_end)})",
                      value=f"{fmt(c_period)} clic(s)", inline=False)
        if all_none:
            emb.add_field(name="⚠️ Données indisponibles",
                          value="GetMySocial ne répond pas pour l'instant — réessaie dans un instant.",
                          inline=False)
        emb.set_footer(text="Mis à jour à l'instant · GetMySocial")
        return emb

    async def _handle_myclicks(self, interaction: discord.Interaction):
        """Clic sur le bouton 'Mes clics' : calcule et montre en privé les clics
        du lien de CE salon va-, en temps réel."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        import guild_features as gf
        if not gf.enabled(interaction.guild, "clics"):
            await interaction.followup.send("⚠️ Fonction désactivée sur ce serveur.", ephemeral=True)
            return
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        ch = interaction.channel
        if not _ch_handle(getattr(ch, "name", "")):
            await interaction.followup.send(
                "⚠️ Ce bouton fonctionne dans ton salon `va-…`.", ephemeral=True)
            return
        links = await self._links()
        link = await self._resolve_link(ch, links)
        if not link:
            await interaction.followup.send(NO_LINK_MSG, ephemeral=True)
            return
        today = _paris_now().date()
        counts = await self._fetch_myclicks(link.get("id"), gms, today)
        emb = self._myclicks_embed(link, today, counts)
        try:
            await interaction.followup.send(embed=emb, ephemeral=True)
        except Exception as e:
            print(f"[clickrecap] followup myclicks échoué : {e}")

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
        import guild_features as gf
        for guild in self.bot.guilds:
            if not gf.enabled(guild, "clics"):
                continue  # serveur bridé sans la fonction clics
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
        name="clicsbouton",
        description="[OWNER] Pose le bouton '📊 Mes clics' dans CE salon",
    )
    async def clicsbouton(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ch = interaction.channel
        if not _ch_handle(getattr(ch, "name", "")):
            await interaction.followup.send(
                "Lance ça dans un salon `va-<pseudo>` (ou `/clicsboutontous` pour tous).",
                ephemeral=True)
            return
        try:
            msg = await ch.send(
                "📊 **Tes clics en direct** — clique pour voir tes clics "
                "(aujourd'hui, hier, cette semaine, quinzaine).",
                view=MyClicksView(self),
            )
            try:
                await msg.pin()
            except Exception:
                pass
            await interaction.followup.send("✅ Bouton « Mes clics » posé ici.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Échec : {e}", ephemeral=True)

    @app_commands.command(
        name="clicsboutontous",
        description="[OWNER] Pose le bouton '📊 Mes clics' dans TOUS les salons va- (sans rien à remplir)",
    )
    async def clicsboutontous(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        n = 0
        fails = []
        for guild in self.bot.guilds:
            for ch in guild.text_channels:
                if not _ch_handle(ch.name):
                    continue
                try:
                    msg = await ch.send(
                        "📊 **Tes clics en direct** — clique pour voir tes clics "
                        "(aujourd'hui, hier, cette semaine, quinzaine).",
                        view=MyClicksView(self),
                    )
                    try:
                        await msg.pin()
                    except Exception:
                        pass
                    n += 1
                except discord.Forbidden:
                    fails.append(f"{ch.name} (pas la permission)")
                except Exception as e:
                    fails.append(f"{ch.name} ({type(e).__name__})")
                    print(f"[clickrecap] bouton #{getattr(ch, 'name', '?')} : {e}")
                await asyncio.sleep(1.0)  # rate-limit friendly (succès ET échec)
        msg = f"✅ Bouton « Mes clics » posé dans **{n}** salon(s) va-."
        if fails:
            msg += f"\n⚠️ **{len(fails)}** échec(s) : " + ", ".join(fails[:10])
            if len(fails) > 10:
                msg += f" … (+{len(fails) - 10})"
        await interaction.followup.send(msg[:1900], ephemeral=True)

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


    @app_commands.command(
        name="setreportclick",
        description="[OWNER] Report horaire des clics d'un groupe GMS dans CE salon",
    )
    @app_commands.describe(
        groupe="Nom du groupe GMS (défaut : identité du serveur, ex: Hybride)",
    )
    async def setreportclick(self, interaction: discord.Interaction, groupe: str = None):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        data, err = await self._resolve_report_group(interaction.guild, groupe)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return
        gid = str(interaction.guild.id)
        cfg = _load_report_cfg()
        new_c = {
            "channel_id": interaction.channel.id, "team_id": data["team_id"],
            "group_id": data["group_id"], "identity": data["identity"],
            "group_name": data["group_name"],
        }
        # Re-lancer dans le MÊME salon : on réutilise le message épinglé existant
        # (sinon on poste un doublon). Salon différent -> nouveau message.
        old = cfg.get(gid)
        if isinstance(old, dict) and old.get("channel_id") == interaction.channel.id and old.get("message_id"):
            new_c["message_id"] = old["message_id"]
        cfg[gid] = new_c
        _save_report_cfg(cfg)
        self._report_last_hour = _paris_now().hour  # évite un double post immédiat par la boucle
        await self._post_or_update_report(gid)
        await interaction.followup.send(
            f"✅ Report horaire des clics **{data['group_name']}** (workspace **{data['ws']}**, "
            f"{data['n']} lien(s)) activé dans {interaction.channel.mention}.\n"
            f"Message **édité chaque heure** (aujourd'hui / hier / semaine / période 1–15 / 16–fin). "
            f"Snapshot à la demande : `/reportclicknow`. Désactive : `/reportclick_off`.{data['ambig']}",
            ephemeral=True)

    @app_commands.command(
        name="reportclick_off",
        description="[OWNER] Désactive le report horaire des clics sur CE serveur",
    )
    async def reportclick_off(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        cfg = _load_report_cfg()
        if str(interaction.guild.id) in cfg:
            cfg.pop(str(interaction.guild.id), None)
            _save_report_cfg(cfg)
            await interaction.response.send_message("🛑 Report horaire désactivé.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ Aucun report configuré ici.", ephemeral=True)

    async def _resolve_report_group(self, guild, groupe):
        """Résout la cible d'un report de clics. Retourne (data, None) si OK —
        data = {team_id, identity, group_id, group_name, ws, ambig, n} —, sinon
        (None, message_erreur). Partagé par /setreportclick et /reportclicknow."""
        import gms
        import guild_features as gf
        name = (groupe or gf.get_server_identity(guild) or "").strip()
        if not name:
            return None, ("⚠️ Précise le groupe : `groupe:Hybride` — ou définis l'identité "
                          "du serveur (`/setidentite`).")
        ident = name.lower()
        group_name = name[0].upper() + name[1:]  # hybride -> Hybride (groupes capitalisés)

        def _ws_label(tid):
            if tid == getattr(gms, "THREADS_US_TID", None):
                return "Threads US"
            if tid == getattr(gms, "MARCHE_FRANCAIS_TID", None):
                return "marché FR"
            return str(tid)

        team_id = group_id = identity = None
        ambig = ""
        suffix = getattr(gms, "_SHORTCODE_SUFFIX", {}).get(ident)
        pref_team = getattr(gms, "IDENTITY_TEAM", {}).get(ident)
        if suffix and pref_team:
            # Identité connue (ex: hybride) -> workspace préféré + énumération par
            # suffixe `…secret` via la CLÉ API (insensible à l'expiration du cookie).
            team_id, identity = pref_team, ident
        else:
            # Groupe arbitraire -> résolution par nom de groupe (cookie de session).
            order = list(getattr(gms, "KNOWN_TEAMS", ()))
            if pref_team and pref_team in order:
                order.remove(pref_team)
                order.insert(0, pref_team)
            matches = []
            for tid in order:
                g = await asyncio.to_thread(gms.group_id_by_name, tid, group_name)
                if g:
                    matches.append((tid, g))
            if not matches:
                return None, (f"❌ Groupe « **{group_name}** » introuvable.\n"
                              f"Si tu visais un groupe perso, le **cookie de session GMS du VPS** "
                              f"est peut-être expiré. Pour **hybride**, essaie `groupe:hybride` (clé API).")
            team_id, group_id = matches[0]
            if len(matches) > 1:
                ambig = (f"\n⚠️ Un groupe « {group_name} » existe dans **{len(matches)}** workspaces "
                         f"— j'ai pris **{_ws_label(team_id)}**.")
        ids = await asyncio.to_thread(gms.report_link_ids, team_id, identity, group_id)
        if ids is None:
            return None, ("❌ Impossible de lister les liens (API/cookie GMS injoignable). "
                          "Réessaie dans un instant.")
        return {"team_id": team_id, "identity": identity, "group_id": group_id,
                "group_name": group_name, "ws": _ws_label(team_id),
                "ambig": ambig, "n": len(ids)}, None

    @app_commands.command(
        name="reportclicknow",
        description="[OWNER] Poste MAINTENANT un report complet des clics (snapshot)",
    )
    @app_commands.describe(groupe="Nom du groupe GMS (défaut : identité du serveur, ex: Hybride)")
    async def reportclicknow(self, interaction: discord.Interaction, groupe: str = None):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms  # noqa: F401 (vérifie juste que le module est dispo)
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        data, err = await self._resolve_report_group(interaction.guild, groupe)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return
        emb = await self._build_group_report({
            "team_id": data["team_id"], "group_id": data["group_id"],
            "identity": data["identity"], "group_name": data["group_name"],
        })
        if emb is None:
            await interaction.followup.send(
                "❌ GMS injoignable pour l'instant — réessaie dans un instant.", ephemeral=True)
            return
        try:
            await interaction.channel.send(embed=emb)
        except Exception as e:
            await interaction.followup.send(f"❌ Envoi impossible ici : {e}", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Report complet **{data['group_name']}** posté ici ({data['n']} lien(s)).{data['ambig']}",
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(ClickRecap(bot))
