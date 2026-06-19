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


def _last_sunday(y, mo):
    for w in reversed(calendar.monthcalendar(y, mo)):
        if w[6]:
            return w[6]
    return 28


def _utc_offset(dt_naive_utc):
    y = dt_naive_utc.year
    ds = datetime.datetime(y, 3, _last_sunday(y, 3), 1)
    de = datetime.datetime(y, 10, _last_sunday(y, 10), 1)
    return 2 if (ds <= dt_naive_utc < de) else 1


def _paris_now():
    u = datetime.datetime.utcnow()
    return u + datetime.timedelta(hours=_utc_offset(u))


def _utc_to_paris_date(dt_naive_utc):
    return (dt_naive_utc + datetime.timedelta(hours=_utc_offset(dt_naive_utc))).date().isoformat()


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
            if self._is_va_channel(message.channel):
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

    def _is_va_channel(self, ch):
        nm = (getattr(ch, "name", "") or "").lower()
        return bool(va_handle(nm) or nm.startswith("général") or nm.startswith("general")
                    or "general-" in nm or "général-" in nm)

    async def _backfill_history(self, days=WINDOW):
        """Importe l'activité réelle depuis l'historique des messages (va-/général-)
        des `days` derniers jours. Fusion par MAX/jour (re-scan idempotent, ne double
        pas, garde les clics live). Retourne (messages, nb_users, nb_salons)."""
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days + 1)
        fresh = {}
        n_msgs = 0
        chans = 0
        for guild in self.bot.guilds:
            for ch in guild.text_channels:
                if not self._is_va_channel(ch):
                    continue
                chans += 1
                try:
                    async for msg in ch.history(limit=4000, after=cutoff):
                        if msg.author.bot:
                            continue
                        try:
                            day = _utc_to_paris_date(msg.created_at.replace(tzinfo=None))
                        except Exception:
                            continue
                        u = fresh.setdefault(str(msg.author.id), {})
                        u[day] = u.get(day, 0) + 1
                        n_msgs += 1
                except discord.Forbidden:
                    pass
                except Exception as e:
                    print(f"[vaactivity] scan #{getattr(ch,'name','?')} : {e}")
                await asyncio.sleep(0.25)
        # fusion : max par jour (garde le plus grand entre clics live et messages historiques)
        for uid, dmap in fresh.items():
            ex = self._act.setdefault(uid, {})
            for d, c in dmap.items():
                ex[d] = max(ex.get(d, 0), c)
        _save(ACT_FILE, self._act)
        return n_msgs, len(fresh), chans

    # ---------- Auto-renommage ----------
    async def _apply_all(self):
        """Renomme les salons va- avec le rond. Retourne un compteur de diagnostic."""
        st = {"found": 0, "renamed": 0, "skipped": 0, "forbidden": 0, "errored": 0}
        for guild in self.bot.guilds:
            for ch, h in self._va_channels(guild):
                st["found"] += 1
                member = self._member_for_handle(guild, h)
                dot = self._dot(member.id) if member else "🔴"
                cur = (ch.name or "").strip()
                cur_dot = cur[0] if cur[:1] in DOTS else ""
                if cur_dot == dot:
                    st["skipped"] += 1
                    continue  # déjà le bon rond -> pas de rename (anti rate-limit)
                target = f"{dot}-va-{h}"
                try:
                    await ch.edit(name=target, reason="VA activity score")
                    st["renamed"] += 1
                    await asyncio.sleep(2)
                except discord.Forbidden:
                    st["forbidden"] += 1
                except Exception as e:
                    st["errored"] += 1
                    print(f"[vaactivity] rename #{ch.name} : {e}")
        print(f"[vaactivity] {st}")
        return st

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
            # Importe d'abord l'activité réelle depuis l'historique (sinon tout le monde est 🔴)
            n_msgs, n_users, n_chan = await self._backfill_history()
            st = await self._apply_all()
            msg = (f"✅ Auto-renommage **activé** (chaque nuit).\n"
                   f"• Historique scanné : **{n_msgs}** messages de **{n_users}** membres ({n_chan} salons)\n"
                   f"• Salons `va-…` détectés : **{st['found']}**\n"
                   f"• Renommés : **{st['renamed']}** · déjà à jour : {st['skipped']}\n")
            if st["found"] == 0:
                msg += "\n⚠️ **Aucun salon `va-…` détecté.** Vérifie que les salons s'appellent bien `va-<pseudo>` et que le bot peut les voir."
            elif st["forbidden"] > 0 and st["renamed"] == 0:
                msg += (f"\n🚫 **{st['forbidden']} renommage(s) refusé(s) (permission).** Le bot n'a pas le droit de renommer ces salons.\n"
                        "→ Donne-lui la permission **Gérer les salons** ET place son rôle **au-dessus** dans Paramètres serveur → Rôles.")
            elif st["errored"] > 0:
                msg += f"\n⚠️ {st['errored']} erreur(s) — voir les logs."
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.followup.send("🛑 Auto-renommage **désactivé** (les ronds restent en place jusqu'au prochain rename).", ephemeral=True)

    @app_commands.command(name="vascore_scan", description="[OWNER] Importe l'activité réelle depuis l'historique (met les scores à jour)")
    @app_commands.describe(jours="Nombre de jours d'historique à scanner (défaut 14)")
    async def vascore_scan(self, interaction: discord.Interaction, jours: int = WINDOW):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            jours = max(1, min(30, int(jours)))
            n_msgs, n_users, n_chan = await self._backfill_history(days=jours)
            await interaction.followup.send(
                f"✅ Historique importé ({jours}j) : **{n_msgs}** messages de **{n_users}** membres sur **{n_chan}** salons.\n"
                "Fais **/vascore** pour voir les scores, puis **/vascore_auto actif:true** pour appliquer les ronds.",
                ephemeral=True,
            )
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Erreur scan : {e}", ephemeral=True)
            except Exception:
                pass


async def setup(bot):
    await bot.add_cog(VAActivity(bot))
