"""cta_reminder.py - Rappels Story CTA quotidiens (20h/21h/22h).

A 20h heure Paris : le bot envoie dans le channel de chaque VA un message
"C'est l'heure de poster ta story CTA du jour" avec un gros bouton vert.
- Si le VA clique le bouton vert -> marque "done" pour aujourd'hui -> plus
  de rappel les heures suivantes
- Sinon a 21h et 22h : nouveau rappel

Storage : data/cta_reminder_state.json
Format :
{
  "2026-06-04": {
    "user_id_1": {"done": true, "h20_sent": true, "h21_sent": false, "h22_sent": false, "channel_id": ...},
    ...
  }
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger("vabot.cta_reminder")

DATA_DIR = Path("data")
USERS_FILE = DATA_DIR / "users.json"
STATE_FILE = DATA_DIR / "cta_reminder_state.json"

REMINDER_HOURS = [20, 21, 22]  # Heures Paris des rappels


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _paris_now() -> datetime:
    """Datetime actuel a Paris (gere DST automatiquement)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        # Fallback : UTC+2 ete, UTC+1 hiver - approx
        from datetime import timezone as _tz, timedelta as _td
        # Approximation : UTC + 2 d'avril a octobre
        utc_now = datetime.now(timezone.utc)
        if 4 <= utc_now.month <= 10:
            return utc_now.astimezone(_tz(_td(hours=2)))
        return utc_now.astimezone(_tz(_td(hours=1)))


def _today_key() -> str:
    return _paris_now().date().isoformat()


def _get_user_channel_id(uid: str) -> int | None:
    """Retourne le channel_id Discord d'un user."""
    users = _load_users()
    data = users.get(str(uid))
    if isinstance(data, dict):
        cid = data.get("channel_id")
        if cid:
            return int(cid)
    return None


def mark_done(user_id: str) -> bool:
    """Marque l'user comme ayant fait sa CTA aujourd'hui."""
    state = _load_state()
    today = _today_key()
    if today not in state:
        state[today] = {}
    if str(user_id) not in state[today]:
        state[today][str(user_id)] = {}
    state[today][str(user_id)]["done"] = True
    _save_state(state)
    return True


def is_done_today(user_id: str) -> bool:
    state = _load_state()
    today = _today_key()
    return state.get(today, {}).get(str(user_id), {}).get("done", False)


def mark_sent(user_id: str, hour: int):
    state = _load_state()
    today = _today_key()
    if today not in state:
        state[today] = {}
    if str(user_id) not in state[today]:
        state[today][str(user_id)] = {}
    state[today][str(user_id)][f"h{hour}_sent"] = True
    _save_state(state)


def was_sent_today(user_id: str, hour: int) -> bool:
    state = _load_state()
    today = _today_key()
    return state.get(today, {}).get(str(user_id), {}).get(f"h{hour}_sent", False)


def cleanup_old_state(days_to_keep: int = 7):
    """Garde uniquement les N derniers jours."""
    state = _load_state()
    today_key = _today_key()
    today = datetime.fromisoformat(today_key).date()
    from datetime import timedelta
    cutoff = today - timedelta(days=days_to_keep)
    cleaned = {k: v for k, v in state.items()
               if datetime.fromisoformat(k).date() >= cutoff}
    if len(cleaned) != len(state):
        _save_state(cleaned)


class CTADoneView(discord.ui.View):
    """View persistante avec un bouton vert 'J'ai poste ma story CTA'."""
    def __init__(self, target_user_id: int):
        super().__init__(timeout=None)
        # custom_id pour persister entre redemarrages
        self.target_user_id = target_user_id

    @discord.ui.button(
        label="✅ J'ai posté ma story CTA",
        style=discord.ButtonStyle.success,
        custom_id="cta_done_button",
    )
    async def done_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Securite : seul le user cible peut cliquer
        if self.target_user_id and interaction.user.id != self.target_user_id:
            # Permet tout de meme aux admins de cliquer pour eux
            # Verifier si c est leur channel
            await interaction.response.send_message(
                "❌ Ce bouton est reserve a la personne taggee.", ephemeral=True
            )
            return
        mark_done(str(interaction.user.id))
        # Update le message original : bouton disabled + texte de confirmation
        button.disabled = True
        button.label = "✅ Marqué fait !"
        try:
            await interaction.response.edit_message(
                content=(
                    "✅ **Story CTA marquée comme postée !**\n"
                    "Plus de rappel pour aujourd'hui. À demain ! 👋"
                ),
                view=self,
            )
        except Exception:
            # Fallback : repond en followup
            await interaction.followup.send(
                "✅ Marque fait. Plus de rappel aujourd'hui.", ephemeral=True
            )


class CTAReminderCog(commands.Cog):
    """Rappels Story CTA quotidiens a 20h / 21h / 22h Paris."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_loop.start()

    def cog_unload(self):
        self.check_loop.cancel()

    async def cog_load(self):
        # Enregistre la view persistante au demarrage
        # On utilise target_user_id=0 pour le bot - le check du user se fait
        # via le "interaction.user.id" qui sera le clicker
        self.bot.add_view(CTADoneView(target_user_id=0))

    @tasks.loop(minutes=1)
    async def check_loop(self):
        """Verifie chaque minute si on est a 20h/21h/22h Paris."""
        now = _paris_now()
        hour = now.hour
        minute = now.minute
        # Fire dans les 5 premieres minutes de l'heure (au cas ou le bot
        # demarre en retard)
        if hour not in REMINDER_HOURS:
            return
        if minute >= 5:
            return
        # Pour chaque user dans users.json, send si pas done + pas deja sent
        users = _load_users()
        for uid_str, udata in users.items():
            if not isinstance(udata, dict):
                continue
            channel_id = udata.get("channel_id")
            if not channel_id:
                continue
            try:
                uid = int(uid_str)
            except Exception:
                continue
            # Skip si deja fait aujourd'hui
            if is_done_today(uid_str):
                continue
            # Skip si rappel deja envoye pour cette heure aujourd'hui
            if was_sent_today(uid_str, hour):
                continue
            # Envoie le rappel
            try:
                channel = self.bot.get_channel(int(channel_id))
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(int(channel_id))
                    except Exception:
                        continue
                # Texte selon l'heure (escalade)
                if hour == 20:
                    msg = (
                        f"📸 <@{uid}> **Story CTA du jour !**\n"
                        "C'est l'heure de poster ta story CTA sur ton compte.\n"
                        "Fais-le maintenant et clique le bouton vert pour ne plus "
                        "avoir de rappel aujourd'hui."
                    )
                elif hour == 21:
                    msg = (
                        f"⏰ <@{uid}> **Rappel : Story CTA toujours pas postée**\n"
                        "Pense à poster ta story CTA. Click le bouton quand c'est fait."
                    )
                else:  # 22h
                    msg = (
                        f"⚠️ <@{uid}> **DERNIER RAPPEL — Story CTA**\n"
                        "C'est ton dernier rappel pour aujourd'hui. Poste ta story "
                        "CTA et click le bouton."
                    )
                view = CTADoneView(target_user_id=uid)
                await channel.send(content=msg, view=view)
                mark_sent(uid_str, hour)
            except Exception as e:
                log.warning(f"[cta_reminder] Send fail pour {uid_str}: {e}")
        # Cleanup une fois par jour (a 22h05 environ)
        if hour == 22 and minute >= 4:
            cleanup_old_state()

    @check_loop.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # Commande manuelle pour tester
    @app_commands.command(
        name="cta_test", description="[OWNER] Envoie un rappel CTA de test maintenant"
    )
    async def cta_test(self, interaction: discord.Interaction):
        # Owner only
        app = await self.bot.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        view = CTADoneView(target_user_id=interaction.user.id)
        await interaction.response.send_message(
            content=(
                f"📸 <@{interaction.user.id}> **[TEST] Story CTA du jour !**\n"
                "C'est l'heure de poster ta story CTA sur ton compte.\n"
                "Fais-le maintenant et click le bouton vert."
            ),
            view=view,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CTAReminderCog(bot))
