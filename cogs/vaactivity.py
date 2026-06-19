"""Score d'activité des VAs (/100) + rond 🟢/🟠/🔴 devant le nom du salon va-<handle>.

Activité comptée (fenêtre 14 jours glissants, « jours actifs ») :
- clics sur les boutons (contenu / onboarding / demander un lien) -> on_interaction
- messages écrits dans les salons va-… et général-… -> on_message
Score = (jours actifs sur 14) / 14 * 100. 🟢 >=60 · 🟠 >=30 · 🔴 <30.

L'auto-renommage des salons est OFF par défaut (data/vaactivity.json -> "auto").
Le bot a besoin de « Gérer les salons » + ne renomme que si le rond change
(anti rate-limit Discord : 2 renames / 10 min / salon).
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

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
ACT_FILE = DATA_DIR / "va_activity.json"        # {user_id: {"YYYY-MM-DD": count}}
CFG_FILE = DATA_DIR / "vaactivity.json"          # {"auto": bool}
WINDOW = 14                                       # jours de la fenêtre de score
KEEP_DAYS = 25                                    # purge au-delà
DOTS = ("🟢", "🟠", "🔴")

# Détection robuste d'un salon VA, tolérante à un rond en préfixe :
#   "va-ozen", "🟢-va-ozen", "🟠 va-ozen" -> handle "ozen"
_VA_RE = re.compile(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$")


def va_handle(channel_name: str):
    m = _VA_RE.search((channel_name or "").lower())
    return m.group(1) if m else None


def _paris_now():
    u = datetime.datetime.utcnow()
    y = u.year

    def last_sun(mo):
        for w in reversed(calendar.monthcalendar(y, mo)):
            if w[6]:
                return w[6]
        return 28
    dst_start = datetime.datetime(y, 3, last_sun(3), 1)
    dst_end = datetime.datetime(y, 10, last_sun(10), 1)
    off = 2 if (dst_start <= u < dst_end) else 1
    return u + datetime.timedelta(hours=off)


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _emoji_for(score: int) -> str:
    if score >= 60:
        return "🟢"
    if score >= 30:
        return "🟠"
    return "🔴"


class VAActivity(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self._act = _load(ACT_FILE, {})       # cache mémoire
        self._last_run = None
        if bool(_load(CFG_FILE, {}).get("auto")):
            self.daily.start()

    def cog_unload(self):
        if self.daily.is_running():
            self.daily.cancel()
        _save(ACT_FILE, self._act)

    async def _is_owner(self, uid):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return uid == self._owner_id

    # ---------- Enregistrement de l'activité ----------
    def _record(self, user_id):
        d = _paris_now().date().isoformat()
        uid = str(user_id)
        u = self._act.setdefault(uid, {})
        u[d] = u.get(d, 0) + 1
        # purge des vieux jours
        cutoff = (_paris_now().date() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
        for k in [k for k in u if k < cutoff]:
            u.pop(k, None)
        _save(ACT_FILE, self._act)

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.bot or not message.guild:
                return
            nm = (getattr(message.channel, "name", "") or "").lower()
            if va_handle(nm) or nm.startswith("général") or nm.startswith("general") or "general-" in nm or "général-" in nm:
                self._record(message.author.id)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        try:
            # composants (boutons/menus) + commandes : signe d'activité du VA
            if interaction.user and not interaction.user.bot:
                self._record(interaction.user.id)
        except Exception:
            pass

    # ---------- Score ----------
    def _score(self, user_id) -> int:
        u = self._act.get(str(user_id), {})
        if not u:
            return 0
        today = _paris_now().date()
        active = 0
        for i in range(WINDOW):
            d = (today - datetime.timedelta(days=i)).isoformat()
            if u.get(d, 0) > 0:
                active += 1
        return round(active / WINDOW * 100)

    def _dot(self, user_id) -> str:
        """Couleur du rond (recency) :
        🔴 rien depuis 3 jours · 🟠 au moins une interaction récente · 🟢 très actif (>=5 des 7 derniers jours)."""
        u = self._act.get(str(user_id), {})
        today = _paris_now().date()

        def act(i):
            return u.get((today - datetime.timedelta(days=i)).isoformat(), 0) > 0
        if not any(act(i) for i in range(3)):   # 3 jours sans rien
            return "🔴"
        active7 = sum(1 for i in range(7) if act(i))
        return "🟢" if active7 >= 5 else "🟠"

    def _member_for_handle(self, guild, handle):
        h = (handle or "").lower()
        for m in guild.members:
            if (m.name or "").lower() == h:
                return m
        return None

    def _va_channels(self, guild):
        out = []
        for ch in guild.text_channels:
            h = va_handle(ch.name)
            if h:
                out.append((ch, h))
        return out

    # ---------- Auto-renommage ----------
    async def _apply_all(self):
        renamed = 0
        for guild in self.bot.guilds:
            for ch, h in self._va_channels(guild):
                member = self._member_for_handle(guild, h)
                dot = self._dot(member.id) if member else "🔴"
                cur = (ch.name or "").strip()
                cur_dot = cur[0] if cur[:1] in DOTS else ""
                if cur_dot == dot:
                    continue  # déjà le bon rond -> pas de rename (anti rate-limit)
                target = f"{dot}-va-{h}"
                try:
                    await ch.edit(name=target, reason="VA activity score")
                    renamed += 1
                    await asyncio.sleep(2)
                except discord.Forbidden:
                    pass
                except Exception as e:
                    print(f"[vaactivity] rename #{ch.name} : {e}")
        print(f"[vaactivity] {renamed} salon(s) renommé(s)")
        return renamed

    @tasks.loop(minutes=30)
    async def daily(self):
        now = _paris_now()
        dstr = now.date().isoformat()
        if now.hour == 0 and self._last_run != dstr:
            self._last_run = dstr
            try:
                await self._apply_all()
            except Exception as e:
                print(f"[vaactivity] loop : {e}")

    @daily.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ---------- Commandes ----------
    @app_commands.command(name="vascore", description="[OWNER] Aperçu des scores d'activité des VAs (sans renommer)")
    async def vascore(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("À utiliser dans le serveur.", ephemeral=True)
                return
            rows = []
            for ch, h in self._va_channels(guild):
                member = self._member_for_handle(guild, h)
                score = self._score(member.id) if member else 0
                dot = self._dot(member.id) if member else "🔴"
                rows.append((score, f"{dot} `va-{h}` — **{score}/100**" + ("" if member else " ⚠️ membre introuvable")))
            if not rows:
                await interaction.followup.send("Aucun salon `va-…` trouvé.", ephemeral=True)
                return
            rows.sort(key=lambda x: x[0])  # du moins actif au plus actif
            auto = bool(_load(CFG_FILE, {}).get("auto"))
            head = (f"📊 **Activité VA** ({WINDOW}j · auto {'ON' if auto else 'OFF'})\n"
                    "🔴 rien depuis 3j · 🟠 actif récemment · 🟢 très actif (≥5/7j)\n\n")
            # cap à <2000 caractères (limite Discord) sinon l'envoi échoue (= ça tourne dans le vide)
            lines, total, shown = [], len(head), 0
            for _s, line in rows:
                if total + len(line) + 1 > 1900:
                    break
                lines.append(line); total += len(line) + 1; shown += 1
            body = "\n".join(lines)
            extra = len(rows) - shown
            if extra > 0:
                body += f"\n… +{extra} autre(s) (trop pour un message)"
            await interaction.followup.send(head + body, ephemeral=True)
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Erreur vascore : {e}", ephemeral=True)
            except Exception:
                pass

    @app_commands.command(name="vascore_auto", description="[OWNER] Active/désactive le renommage auto des salons va- avec le rond")
    @app_commands.describe(actif="true = renomme les salons va- avec 🟢/🟠/🔴 chaque nuit + applique maintenant")
    async def vascore_auto(self, interaction: discord.Interaction, actif: bool):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        _save(CFG_FILE, {"auto": actif})
        if actif and not self.daily.is_running():
            self.daily.start()
        elif not actif and self.daily.is_running():
            self.daily.cancel()
        await interaction.response.defer(ephemeral=True, thinking=True)
        if actif:
            n = await self._apply_all()
            await interaction.followup.send(
                f"✅ Auto-renommage **activé** (chaque nuit). {n} salon(s) mis à jour maintenant.\n"
                "⚠️ Si rien ne change : le bot a besoin de la perm **Gérer les salons** et d'un rôle au-dessus.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send("🛑 Auto-renommage **désactivé** (les ronds restent en place jusqu'au prochain rename).", ephemeral=True)


async def setup(bot):
    await bot.add_cog(VAActivity(bot))
