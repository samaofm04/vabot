"""cta_reminder.py - Rappels quotidiens + suivi comptes hebdomadaire.

3 types de taches journalieres :
- REEL  : 16h 17h 18h 19h 20h 21h (1 reel par jour)
- STORY : 10h 15h 19h              (1 story classique par jour)
- CTA   : 20h 21h 22h               (1 story CTA par jour)

Suivi comptes hebdomadaire (Lundi/Mercredi/Dimanche a 12h) :
- 1 message par VA avec 3 lignes (1 par compte)
- Chaque ligne a 2 boutons : 🟢 Actif / 🔴 Inactif
- Une fois clique : ligne disabled + status sauvegarde

Pour chaque VA dans users.json, le bot envoie un rappel a chaque heure
prevue UNIQUEMENT si la tache n'a pas deja ete marquee "done" pour
aujourd'hui. Click sur le bouton vert -> done -> plus de rappel.

Prerequisites : les rappels ne sont actifs QUE si l'user a complete le
warm de son compte Instagram + compte au jour 6+.

Storage : data/cta_reminder_state.json
{
  "2026-06-04": {
    "user_id_1": {
      "reel": {"done": false, "h16_sent": true, ...},
      "story": {"done": true, "h10_sent": true, ...},
      "cta": {"done": false, "h20_sent": true, ...}
    }
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


def _reminders_on(guild) -> bool:
    """False si les rappels/suivi sont désactivés sur ce serveur (ex: mode
    Threads -> pas de rappels Insta). True par défaut."""
    try:
        import guild_features as gf
        return gf.reminders_enabled(guild)
    except Exception:
        return True


DATA_DIR = Path("data")
USERS_FILE = DATA_DIR / "users.json"
STATE_FILE = DATA_DIR / "cta_reminder_state.json"
TRACKING_STATE_FILE = DATA_DIR / "account_tracking_state.json"

# Suivi comptes : Lundi=0, Mercredi=2, Dimanche=6 - heure 12h
TRACKING_DAYS = [0, 2, 6]
TRACKING_HOUR = 12
NB_COMPTES = 3  # 3 comptes par VA

# Config par type de tache
TASK_CONFIG = {
    "reel": {
        "hours": [16, 17, 18, 19, 20, 21],
        "emoji": "🎬",
        "label": "Reel",
        "btn_label": "✅ J'ai posté mon reel",
        "btn_custom_id": "reel_done_button",
        "limit_note": "📌 **1 reel max par jour**",
        "messages": {
            "first": "**Reel du jour !**\nC'est l'heure de poster ton reel sur ton compte.\nFais-le maintenant et click le bouton vert pour ne plus avoir de rappel aujourd'hui.",
            "remind": "**Rappel : Reel toujours pas posté**\nPense à poster ton reel du jour. Click le bouton quand c'est fait.",
            "last": "**DERNIER RAPPEL — Reel**\nC'est ton dernier rappel pour aujourd'hui. Poste ton reel et click le bouton.",
        },
    },
    "story": {
        "hours": [10, 15, 19],
        "emoji": "📷",
        "label": "Story",
        "btn_label": "✅ J'ai posté ma story",
        "btn_custom_id": "story_done_button",
        "limit_note": "📌 **3 stories max par jour**",
        "messages": {
            "first": "**Story du jour !**\nC'est l'heure de poster une story classique sur ton compte.\nFais-le maintenant et click le bouton vert.",
            "remind": "**Rappel : Story toujours pas postée**\nPense à poster une story classique. Click le bouton quand c'est fait.",
            "last": "**DERNIER RAPPEL — Story**\nC'est ton dernier rappel pour la story aujourd'hui.",
        },
    },
    "cta": {
        "hours": [20, 21, 22],
        "emoji": "📸",
        "label": "Story CTA",
        "btn_label": "✅ J'ai posté ma story CTA",
        "btn_custom_id": "cta_done_button",
        "limit_note": "📌 **1 story CTA max le soir**",
        "messages": {
            "first": "**Story CTA du jour !**\nC'est l'heure de poster ta story CTA sur ton compte.\nFais-le maintenant et click le bouton vert pour ne plus avoir de rappel aujourd'hui.",
            "remind": "**Rappel : Story CTA toujours pas postée**\nPense à poster ta story CTA. Click le bouton quand c'est fait.",
            "last": "**DERNIER RAPPEL — Story CTA**\nC'est ton dernier rappel pour aujourd'hui. Poste ta story CTA et click le bouton.",
        },
    },
}

# Note prerequisites (envoye dans le 1er rappel de chaque type chaque jour)
PREREQUISITES_NOTE = (
    "\n\n⚠️ **Important** : Ne fais ces tâches que si ton compte Instagram "
    "**est warmé** et **à jour 6+**. Si pas encore prêt, ignore ces rappels."
)


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
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        from datetime import timezone as _tz, timedelta as _td
        utc_now = datetime.now(timezone.utc)
        if 4 <= utc_now.month <= 10:
            return utc_now.astimezone(_tz(_td(hours=2)))
        return utc_now.astimezone(_tz(_td(hours=1)))


def _today_key() -> str:
    return _paris_now().date().isoformat()


def _ensure_user_state(state: dict, today: str, uid: str, task_type: str):
    if today not in state:
        state[today] = {}
    if uid not in state[today]:
        state[today][uid] = {}
    if task_type not in state[today][uid]:
        state[today][uid][task_type] = {}


def mark_done(user_id: str, task_type: str) -> bool:
    state = _load_state()
    today = _today_key()
    _ensure_user_state(state, today, str(user_id), task_type)
    state[today][str(user_id)][task_type]["done"] = True
    _save_state(state)
    return True


def is_done_today(user_id: str, task_type: str) -> bool:
    state = _load_state()
    today = _today_key()
    return state.get(today, {}).get(str(user_id), {}).get(task_type, {}).get("done", False)


def mark_sent(user_id: str, task_type: str, hour: int):
    state = _load_state()
    today = _today_key()
    _ensure_user_state(state, today, str(user_id), task_type)
    state[today][str(user_id)][task_type][f"h{hour}_sent"] = True
    _save_state(state)


def was_sent_today(user_id: str, task_type: str, hour: int) -> bool:
    state = _load_state()
    today = _today_key()
    return state.get(today, {}).get(str(user_id), {}).get(task_type, {}).get(f"h{hour}_sent", False)


def was_any_sent_today(user_id: str, task_type: str) -> bool:
    """True si au moins un rappel a deja ete envoye pour cette tache aujourd'hui."""
    state = _load_state()
    today = _today_key()
    tdata = state.get(today, {}).get(str(user_id), {}).get(task_type, {})
    for k in tdata:
        if k.startswith("h") and k.endswith("_sent") and tdata[k]:
            return True
    return False


def cleanup_old_state(days_to_keep: int = 7):
    state = _load_state()
    today_key = _today_key()
    today = datetime.fromisoformat(today_key).date()
    from datetime import timedelta
    cutoff = today - timedelta(days=days_to_keep)
    cleaned = {k: v for k, v in state.items()
               if datetime.fromisoformat(k).date() >= cutoff}
    if len(cleaned) != len(state):
        _save_state(cleaned)


class TaskDoneView(discord.ui.View):
    """View generique avec un bouton 'J'ai fait la tache'.
    custom_id encode le task_type pour pouvoir gerer plusieurs types
    avec la meme classe View persistante."""

    def __init__(self, task_type: str = "cta", target_user_id: int = 0):
        super().__init__(timeout=None)
        self.task_type = task_type
        self.target_user_id = target_user_id
        # Cree le bouton dynamiquement selon le task_type
        cfg = TASK_CONFIG.get(task_type, TASK_CONFIG["cta"])
        btn = discord.ui.Button(
            label=cfg["btn_label"],
            style=discord.ButtonStyle.success,
            custom_id=cfg["btn_custom_id"],
        )
        btn.callback = self._on_click
        self.add_item(btn)

    async def _on_click(self, interaction: discord.Interaction):
        # Trouve le task_type depuis le custom_id
        cid = interaction.data.get("custom_id", "")
        task_type = "cta"
        for tt, cfg in TASK_CONFIG.items():
            if cfg["btn_custom_id"] == cid:
                task_type = tt
                break
        # Si view a un target restreint, verifie. Sinon n'importe qui peut click
        # (cas restart du bot : on accepte le clicker).
        if self.target_user_id and interaction.user.id != self.target_user_id:
            await interaction.response.send_message(
                "❌ Ce bouton est reserve a la personne taggee.", ephemeral=True
            )
            return
        mark_done(str(interaction.user.id), task_type)
        # Update le message original
        label = TASK_CONFIG.get(task_type, {}).get("label", "Tâche")
        new_view = discord.ui.View(timeout=None)
        done_btn = discord.ui.Button(
            label=f"✅ {label} marquée faite !",
            style=discord.ButtonStyle.secondary,
            disabled=True,
        )
        new_view.add_item(done_btn)
        try:
            await interaction.response.edit_message(
                content=(
                    f"✅ **{label} marquée comme postée !**\n"
                    "Plus de rappel pour aujourd'hui. À demain ! 👋"
                ),
                view=new_view,
            )
        except Exception:
            try:
                await interaction.followup.send(
                    f"✅ {label} marquée. Plus de rappel aujourd'hui.", ephemeral=True
                )
            except Exception:
                pass


# =============================================================
# SUIVI COMPTES INSTAGRAM (Lundi/Mercredi/Dimanche)
# =============================================================

def _load_tracking_state() -> dict:
    if not TRACKING_STATE_FILE.exists():
        return {}
    try:
        return json.loads(TRACKING_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_tracking_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRACKING_STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def tracking_was_sent_today(uid: str) -> bool:
    state = _load_tracking_state()
    today = _today_key()
    return state.get(today, {}).get(str(uid), {}).get("sent", False)


def tracking_mark_sent(uid: str):
    state = _load_tracking_state()
    today = _today_key()
    if today not in state:
        state[today] = {}
    if str(uid) not in state[today]:
        state[today][str(uid)] = {"accounts": {}}
    state[today][str(uid)]["sent"] = True
    _save_tracking_state(state)


def tracking_set_account_status(uid: str, account_idx: int, status: str):
    """status = 'actif' ou 'inactif'."""
    state = _load_tracking_state()
    today = _today_key()
    if today not in state:
        state[today] = {}
    if str(uid) not in state[today]:
        state[today][str(uid)] = {"accounts": {}}
    if "accounts" not in state[today][str(uid)]:
        state[today][str(uid)]["accounts"] = {}
    state[today][str(uid)]["accounts"][str(account_idx)] = status
    _save_tracking_state(state)


def tracking_reset_today(uid: str):
    """Reset les accounts du user pour aujourd'hui (mais garde sent=True
    pour pas re-envoyer le message du cron)."""
    state = _load_tracking_state()
    today = _today_key()
    if today not in state:
        state[today] = {}
    if str(uid) not in state[today]:
        state[today][str(uid)] = {}
    state[today][str(uid)]["accounts"] = {}
    _save_tracking_state(state)


def tracking_get_account_status(uid: str, account_idx: int) -> str | None:
    state = _load_tracking_state()
    today = _today_key()
    return state.get(today, {}).get(str(uid), {}).get("accounts", {}).get(str(account_idx))


class AccountTrackingView(discord.ui.View):
    """View avec 3 lignes de 2 boutons (🟢/🔴) pour chaque compte."""

    def __init__(self, target_user_id: int = 0):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id
        # Cree 6 boutons : 3 comptes x 2 statuts
        for i in range(1, NB_COMPTES + 1):
            # Bouton vert
            btn_green = discord.ui.Button(
                label=f"Compte {i} 🟢 Actif",
                style=discord.ButtonStyle.success,
                custom_id=f"track_c{i}_actif",
                row=i - 1,  # ligne i-1
            )
            btn_green.callback = self._make_callback(i, "actif")
            self.add_item(btn_green)
            # Bouton rouge
            btn_red = discord.ui.Button(
                label=f"Compte {i} 🔴 Inactif",
                style=discord.ButtonStyle.danger,
                custom_id=f"track_c{i}_inactif",
                row=i - 1,
            )
            btn_red.callback = self._make_callback(i, "inactif")
            self.add_item(btn_red)

    def _make_callback(self, account_idx: int, status: str):
        async def callback(interaction: discord.Interaction):
            if self.target_user_id and interaction.user.id != self.target_user_id:
                await interaction.response.send_message(
                    "❌ Ce suivi est reserve a la personne taggee.", ephemeral=True
                )
                return
            # Save le status (avec ordre de click pour le staggering)
            tracking_set_account_status(str(interaction.user.id), account_idx, status)
            # Disable la row du compte cliqué + mark le bouton choisi avec ✓
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.row == account_idx - 1:
                    item.disabled = True
                    if item.custom_id == f"track_c{account_idx}_{status}":
                        item.label = item.label + " ✓"
            # Recupere l'etat pour savoir si tous les 3 sont reportes
            state = _load_tracking_state()
            today = _today_key()
            user_data = state.get(today, {}).get(str(interaction.user.id), {})
            accounts = user_data.get("accounts", {})
            done_count = len(accounts)
            try:
                # Pas encore tous reportes : juste update l'edit (silencieux)
                if done_count < NB_COMPTES:
                    await interaction.response.edit_message(view=self)
                    return
                # Les 3 sont reportes -> message d'action complet
                actifs_ids = [aid for aid, st in accounts.items() if st == "actif"]
                inactifs_ids = [aid for aid, st in accounts.items() if st == "inactif"]
                # Tri par numero de compte pour ordre logique
                inactifs_ids.sort(key=lambda x: int(x))
                # Staggering : 24h pour le 1er inactif, 72h pour 2e, 7j pour 3e
                delais = ["24h", "72h", "7 jours"]
                actifs_list = "Aucun" if not actifs_ids else ", ".join(
                    f"Compte {aid}" for aid in sorted(actifs_ids, key=lambda x: int(x))
                )
                # Construit le message
                parts = [
                    f"📊 <@{interaction.user.id}> **Suivi terminé !**",
                    f"",
                    f"🟢 **Actifs** : {actifs_list}",
                    f"🔴 **Inactifs** : "
                    + ("Aucun" if not inactifs_ids else ", ".join(f"Compte {aid}" for aid in inactifs_ids)),
                ]
                if not inactifs_ids:
                    parts.append("")
                    parts.append("✅ Tout est bon, continue ton bon travail ! 🎉")
                else:
                    parts.append("")
                    parts.append("📋 **Plan d'action staggered** (jamais créer plusieurs comptes d'un coup = red flag Instagram) :")
                    parts.append("")
                    for i, aid in enumerate(inactifs_ids):
                        delai = delais[i] if i < len(delais) else "+1 semaine"
                        emoji_alerte = "🚨" if i >= 2 else "⚠️"
                        parts.append(
                            f"{emoji_alerte} **Compte {aid}** — dans **{delai}** :"
                        )
                        parts.append(
                            f"   • Crée un nouveau mail + nouveau compte Instagram"
                        )
                        parts.append(
                            f"   • Reprends le warmup depuis le début"
                        )
                        if i < len(inactifs_ids) - 1:
                            parts.append("")
                msg = "\n".join(parts)
                # Update le message original (boutons disabled) + envoie le plan
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(content=msg)
            except Exception as e:
                log.warning(f"[tracking] update fail : {e}")
        return callback


class CTAReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_loop.start()

    def cog_unload(self):
        self.check_loop.cancel()

    async def cog_load(self):
        # Enregistre les 3 views persistantes (une par task_type)
        for tt in TASK_CONFIG:
            self.bot.add_view(TaskDoneView(task_type=tt, target_user_id=0))
        # View pour le suivi comptes
        self.bot.add_view(AccountTrackingView(target_user_id=0))

    @tasks.loop(minutes=1)
    async def check_loop(self):
        now = _paris_now()
        hour = now.hour
        minute = now.minute
        if minute >= 5:
            return  # Fire seulement dans les 5 premieres minutes de l'heure
        # Pour chaque type, check si on doit fire pour cette heure
        users = _load_users()
        for task_type, cfg in TASK_CONFIG.items():
            if hour not in cfg["hours"]:
                continue
            # Determine "first/remind/last"
            hours_sorted = sorted(cfg["hours"])
            if hour == hours_sorted[0]:
                msg_key = "first"
            elif hour == hours_sorted[-1]:
                msg_key = "last"
            else:
                msg_key = "remind"
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
                if is_done_today(uid_str, task_type):
                    continue
                if was_sent_today(uid_str, task_type, hour):
                    continue
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel is None:
                        try:
                            channel = await self.bot.fetch_channel(int(channel_id))
                        except Exception:
                            continue
                    if not _reminders_on(getattr(channel, "guild", None)):
                        continue  # serveur Threads / rappels off -> pas de rappel
                    body = cfg["messages"][msg_key]
                    full_msg = f"{cfg['emoji']} <@{uid}> {body}"
                    # 1er rappel du jour pour ce type : ajout limite + prerequisites
                    if not was_any_sent_today(uid_str, task_type):
                        full_msg += f"\n\n{cfg['limit_note']}"
                        full_msg += PREREQUISITES_NOTE
                    view = TaskDoneView(task_type=task_type, target_user_id=uid)
                    await channel.send(content=full_msg, view=view)
                    mark_sent(uid_str, task_type, hour)
                except Exception as e:
                    log.warning(f"[cta_reminder] Send fail {task_type} pour {uid_str}: {e}")
        # Suivi comptes Lundi/Mercredi/Dimanche a 12h
        weekday = now.weekday()  # 0=Lundi, 6=Dimanche
        if weekday in TRACKING_DAYS and hour == TRACKING_HOUR:
            day_label_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi",
                            "Samedi", "Dimanche"][weekday]
            date_str = now.strftime("%d/%m/%Y")
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
                if tracking_was_sent_today(uid_str):
                    continue
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel is None:
                        try:
                            channel = await self.bot.fetch_channel(int(channel_id))
                        except Exception:
                            continue
                    if not _reminders_on(getattr(channel, "guild", None)):
                        continue  # serveur Threads / rappels off -> pas de suivi
                    msg = (
                        f"📊 <@{uid}> **Suivi de tes comptes — {day_label_fr} {date_str}**\n"
                        f"\nPour chacun de tes **{NB_COMPTES} comptes**, "
                        f"indique le statut en cliquant :\n"
                        f"🟢 **Actif** si le compte fonctionne et tu y travailles\n"
                        f"🔴 **Inactif** si le compte est ban, restreint, ou tu n'y travailles plus"
                    )
                    view = AccountTrackingView(target_user_id=uid)
                    await channel.send(content=msg, view=view)
                    tracking_mark_sent(uid_str)
                except Exception as e:
                    log.warning(f"[tracking] Send fail pour {uid_str}: {e}")
        # Cleanup une fois par jour vers 22h05
        if hour == 22 and minute >= 4:
            cleanup_old_state()

    @check_loop.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="tracking_test", description="[OWNER] Envoie le message de suivi comptes"
    )
    async def tracking_test(self, interaction: discord.Interaction):
        app = await self.bot.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        # IMPORTANT : reset les accounts du user pour aujourd'hui afin que
        # le test parte sur un etat propre (sinon les clicks precedents
        # restent en state et firent le message d'action des le 1er click)
        tracking_reset_today(str(interaction.user.id))
        msg = (
            f"📊 <@{interaction.user.id}> **[TEST] Suivi de tes comptes**\n"
            f"\nPour chacun de tes **{NB_COMPTES} comptes**, indique le statut :\n"
            f"🟢 **Actif** = compte fonctionnel\n"
            f"🔴 **Inactif** = compte ban / restreint / abandonne"
        )
        view = AccountTrackingView(target_user_id=interaction.user.id)
        await interaction.response.send_message(content=msg, view=view)

    @app_commands.command(
        name="cta_test", description="[OWNER] Envoie un rappel test (reel/story/cta)"
    )
    @app_commands.describe(task_type="Type de tache a tester")
    @app_commands.choices(task_type=[
        app_commands.Choice(name="Reel", value="reel"),
        app_commands.Choice(name="Story", value="story"),
        app_commands.Choice(name="Story CTA", value="cta"),
    ])
    async def cta_test(self, interaction: discord.Interaction, task_type: str = "cta"):
        app = await self.bot.application_info()
        if interaction.user.id != app.owner.id:
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        cfg = TASK_CONFIG.get(task_type, TASK_CONFIG["cta"])
        view = TaskDoneView(task_type=task_type, target_user_id=interaction.user.id)
        body = cfg["messages"]["first"]
        full_msg = (
            f"{cfg['emoji']} <@{interaction.user.id}> **[TEST]** {body}"
            f"\n\n{cfg['limit_note']}{PREREQUISITES_NOTE}"
        )
        await interaction.response.send_message(content=full_msg, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(CTAReminderCog(bot))
