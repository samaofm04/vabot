"""Gestion multi-comptes Instagram par VA.
- Max 3 comptes par VA
- 24h min entre chaque création
- Tracking jour par compte (warmup Jour 0-5, puis routine Jour 6+)
- Auto-reminder quotidien 9h Paris dans le salon de chaque VA
"""
import asyncio
import json
import logging
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger("vabot.accounts")

DATA_DIR = Path("data")
USERS_FILE = DATA_DIR / "users.json"
IDENTITIES_DIR = DATA_DIR / "identities"
REMINDER_FLAG_FILE = DATA_DIR / "last_daily_reminder.txt"

MAX_ACCOUNTS_PER_VA = 3
MIN_HOURS_BETWEEN_CREATIONS = 24

DAY_TASKS = {
    0: {
        "title": "Jour 0 — Création du compte",
        "tasks": [
            "🔁 Rotate IP (mode avion 10 sec + 5G)",
            "📧 Crée un Gmail (base = futur username)",
            "📱 Crée le compte Insta avec le username + name assignés",
            "⏳ ATTENDRE 24-48h avant les premières actions",
        ],
    },
    1: {
        "title": "Jour 1 — Engagement + photo de profil",
        "tasks": [
            "💬 Interagir 10-15 min (5-6 commentaires + max 3 abonnements)",
            "📸 Upload une photo de profil → fais `/profilepic`",
        ],
    },
    2: {
        "title": "Jour 2 — Bio + première story + premier post",
        "tasks": [
            "💬 Interagir 10 min",
            "📝 Ajouter la bio → fais `/bio`",
            "📲 Poster 1 story → fais `/story`",
            "📂 Créer bulle à la une **\"me\"** + y ajouter la story",
            "🖼️ Poster 1 photo feed → fais `/post`",
        ],
    },
    3: {
        "title": "Jour 3 — Story + post + PREMIER REEL",
        "tasks": [
            "💬 Interagir 10 min",
            "📲 Poster 1 story → fais `/story`",
            "📂 Créer bulle à la une **\"life\"**",
            "🖼️ Poster 1 photo feed → fais `/post`",
            "🎬 **PREMIER REEL** entre 18h-21h → fais `/reel`",
        ],
    },
    4: {
        "title": "Jour 4 — Carousels + bulle à la une",
        "tasks": [
            "💬 Interagir 10 min",
            "📲 Poster 1 story → fais `/story`",
            "📂 Créer bulle à la une **\"travel\"**",
            "📌 PIN les 3 carousels",
            "🎬 Publier 1 reel 18h-21h → fais `/reel`",
        ],
    },
    5: {
        "title": "Jour 5 — 12 stories + 1 reel à 20h",
        "tasks": [
            "💬 Interagir 10 min",
            "📲 Poster **12 stories** (4 par bulle me/life/travel) → fais `/story` x12",
            "🎬 Publier 1 reel à **20h** → fais `/reel`",
        ],
    },
    6: {
        "title": "Jour 6+ — Routine quotidienne (warmup terminé) 🎉",
        "tasks": [
            "💬 Interagir 2-3 min (commentaire + 3 abonnements)",
            "📲 Poster 1 story → fais `/story`",
            "🎬 Publier 1 reel 18h-21h → fais `/reel`",
            "📲 Repost reel veille en story avec texte CTA",
            "📲 Story CTA + lien → fais `/storycta`",
        ],
    },
}


def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def get_va_accounts(user_id):
    users = load_users()
    data = users.get(str(user_id))
    if isinstance(data, dict):
        return data.get("accounts", [])
    return []


def save_va_accounts(user_id, accounts):
    users = load_users()
    data = users.get(str(user_id))
    if not isinstance(data, dict):
        data = {"identity": data if isinstance(data, str) else None, "channel_id": None, "auto_post": True}
    data["accounts"] = accounts
    users[str(user_id)] = data
    save_users(users)


def get_va_identity(user_id):
    users = load_users()
    data = users.get(str(user_id))
    if isinstance(data, dict):
        return data.get("identity")
    if isinstance(data, str):
        return data
    return None


def get_day_tasks(day):
    if day >= 6:
        return DAY_TASKS[6]
    return DAY_TASKS.get(day, {"title": f"Jour {day}", "tasks": ["(pas de tâches)"]})


def render_account_task_block(acc, account_num):
    """Render the task block for one account."""
    status = acc.get("status", "warmup")
    if status == "paused":
        return f"⏸️ **Compte {account_num}** ({acc.get('username', '?')}) — *en pause*"
    day = acc.get("current_day", 0)
    day_info = get_day_tasks(day)
    block = f"📱 **Compte {account_num}** ({acc.get('username', '?')}) — **{day_info['title']}**\n"
    for task in day_info["tasks"]:
        block += f"  {task}\n"
    block += f"*Quand t'as fini : `/account done account:{account_num}`*"
    return block


class Accounts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_reminder.start()

    def cog_unload(self):
        self.daily_reminder.cancel()

    # ---------- COMMAND GROUP : /account ... ----------

    account = app_commands.Group(name="account", description="Gestion de tes comptes Instagram")

    @account.command(name="new", description="Démarre un nouveau compte Instagram")
    async def account_new(self, interaction: discord.Interaction):
        accounts = get_va_accounts(interaction.user.id)
        if len(accounts) >= MAX_ACCOUNTS_PER_VA:
            await interaction.response.send_message(
                f"⚠️ Tu as déjà **{MAX_ACCOUNTS_PER_VA}** comptes (le max). Pause-en un ou supprime-le d'abord.",
                ephemeral=True,
            )
            return
        # Verifier 24h depuis la derniere creation
        if accounts:
            last = accounts[-1]
            try:
                last_dt = datetime.fromisoformat(last["created_at"])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                elapsed_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                if elapsed_h < MIN_HOURS_BETWEEN_CREATIONS:
                    remaining = MIN_HOURS_BETWEEN_CREATIONS - elapsed_h
                    await interaction.response.send_message(
                        f"⚠️ Tu dois attendre **{remaining:.1f}h** avant de créer un nouveau compte "
                        f"(min 24h entre chaque création pour éviter le ban Instagram).",
                        ephemeral=True,
                    )
                    return
            except Exception:
                pass
        identity = get_va_identity(interaction.user.id)
        if not identity:
            await interaction.response.send_message(
                "Tu n'as pas d'identité assignée. Préviens un admin.", ephemeral=True
            )
            return
        # Picker username + name
        username = None
        name = None
        u_path = IDENTITIES_DIR / identity / "usernames.txt"
        n_path = IDENTITIES_DIR / identity / "names.txt"
        if u_path.exists():
            usernames = [l.strip() for l in u_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            if usernames:
                username = random.choice(usernames)
        if n_path.exists():
            names = [l.strip() for l in n_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            if names:
                name = random.choice(names)
        new_acc = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "current_day": 0,
            "status": "warmup",
            "username": username,
            "name": name,
            "last_done_at": None,
        }
        accounts.append(new_acc)
        save_va_accounts(interaction.user.id, accounts)
        n = len(accounts)
        await interaction.response.send_message(
            f"🆕 **Nouveau compte démarré** ({n}/{MAX_ACCOUNTS_PER_VA})\n\n"
            f"📱 **Username** : `{username or '(aucun dispo, demande admin)'}`\n"
            f"📝 **Name (display)** : `{name or '(aucun dispo, demande admin)'}`\n\n"
            f"**Tâches Jour 0 :**\n"
            + "\n".join(f"  {t}" for t in DAY_TASKS[0]["tasks"])
            + f"\n\n⏳ Attends **24-48h** avant Jour 1. Quand t'es prêt, fais `/account done account:{n}`.",
            ephemeral=True,
        )

    @account.command(name="list", description="Liste tes comptes Instagram")
    async def account_list(self, interaction: discord.Interaction):
        accounts = get_va_accounts(interaction.user.id)
        if not accounts:
            await interaction.response.send_message(
                "Aucun compte. Fais `/account new` pour en créer un.", ephemeral=True
            )
            return
        text = f"📱 **Tes comptes** ({len(accounts)}/{MAX_ACCOUNTS_PER_VA})\n\n"
        for i, acc in enumerate(accounts, 1):
            status_emoji = {"warmup": "🔥", "active": "✅", "paused": "⏸️"}.get(
                acc.get("status", "warmup"), "❓"
            )
            text += (
                f"{status_emoji} **Compte {i}** — `{acc.get('username') or 'sans username'}`\n"
                f"  • Jour **{acc.get('current_day', 0)}**\n"
                f"  • Statut : {acc.get('status', 'warmup')}\n"
                f"  • Créé : {acc.get('created_at', '?')[:10]}\n\n"
            )
        await interaction.response.send_message(text, ephemeral=True)

    @account.command(name="today", description="Voir tes tâches du jour pour chacun de tes comptes")
    async def account_today(self, interaction: discord.Interaction):
        accounts = get_va_accounts(interaction.user.id)
        if not accounts:
            await interaction.response.send_message(
                "Aucun compte. Fais `/account new`.", ephemeral=True
            )
            return
        text = f"📊 **Tâches du jour** ({len(accounts)} compte(s))\n\n"
        for i, acc in enumerate(accounts, 1):
            text += render_account_task_block(acc, i) + "\n\n"
        await interaction.response.send_message(text, ephemeral=True)

    @account.command(name="done", description="Marque la journée terminée pour un compte")
    @app_commands.describe(account="Numéro du compte (1, 2 ou 3 — voir /account list)")
    async def account_done(self, interaction: discord.Interaction, account: int):
        accounts = get_va_accounts(interaction.user.id)
        if not accounts or account < 1 or account > len(accounts):
            await interaction.response.send_message(
                f"Numéro invalide. Tu as {len(accounts)} compte(s).", ephemeral=True
            )
            return
        acc = accounts[account - 1]
        if acc.get("status") == "paused":
            await interaction.response.send_message(
                "Ce compte est en pause. Fais `/account resume account:X` pour le reprendre.",
                ephemeral=True,
            )
            return
        old_day = acc.get("current_day", 0)
        new_day = old_day + 1
        acc["current_day"] = new_day
        acc["last_done_at"] = datetime.now(timezone.utc).isoformat()
        if new_day >= 6:
            acc["status"] = "active"
        accounts[account - 1] = acc
        save_va_accounts(interaction.user.id, accounts)
        msg = f"✅ Compte {account} : **Jour {old_day} → Jour {new_day}**"
        if new_day == 6:
            msg += "\n\n🎉 **Warmup terminé !** Tu passes en routine quotidienne. Continue comme ça."
        await interaction.response.send_message(msg, ephemeral=True)

    @account.command(name="pause", description="Met un compte en pause")
    @app_commands.describe(account="Numéro du compte")
    async def account_pause(self, interaction: discord.Interaction, account: int):
        accounts = get_va_accounts(interaction.user.id)
        if not accounts or account < 1 or account > len(accounts):
            await interaction.response.send_message("Numéro invalide.", ephemeral=True)
            return
        accounts[account - 1]["status"] = "paused"
        save_va_accounts(interaction.user.id, accounts)
        await interaction.response.send_message(f"⏸️ Compte {account} en pause.", ephemeral=True)

    @account.command(name="resume", description="Réactive un compte en pause")
    @app_commands.describe(account="Numéro du compte")
    async def account_resume(self, interaction: discord.Interaction, account: int):
        accounts = get_va_accounts(interaction.user.id)
        if not accounts or account < 1 or account > len(accounts):
            await interaction.response.send_message("Numéro invalide.", ephemeral=True)
            return
        acc = accounts[account - 1]
        acc["status"] = "active" if acc.get("current_day", 0) >= 6 else "warmup"
        accounts[account - 1] = acc
        save_va_accounts(interaction.user.id, accounts)
        await interaction.response.send_message(f"▶️ Compte {account} réactivé.", ephemeral=True)

    @account.command(name="remove", description="Supprime un compte de tes comptes (irréversible)")
    @app_commands.describe(account="Numéro du compte", confirm="Tape le numéro pour confirmer")
    async def account_remove(self, interaction: discord.Interaction, account: int, confirm: int):
        accounts = get_va_accounts(interaction.user.id)
        if not accounts or account < 1 or account > len(accounts):
            await interaction.response.send_message("Numéro invalide.", ephemeral=True)
            return
        if confirm != account:
            await interaction.response.send_message(
                f"⚠️ Pour confirmer, refais avec `confirm:{account}`.", ephemeral=True
            )
            return
        removed = accounts.pop(account - 1)
        save_va_accounts(interaction.user.id, accounts)
        await interaction.response.send_message(
            f"🗑️ Compte supprimé : `{removed.get('username', '?')}`", ephemeral=True
        )

    # ---------- DAILY REMINDER 9h Paris ----------

    @tasks.loop(minutes=1)
    async def daily_reminder(self):
        now = datetime.now(timezone.utc)
        # 8h UTC = 9h Paris hiver, 10h Paris été. On vise 9h Paris hiver donc 8h UTC.
        # Pour Paris été (UTC+2), 9h Paris = 7h UTC.
        # Compromis: déclenche à 7h UTC (= 9h Paris été, 8h Paris hiver)
        if now.hour != 7 or now.minute != 0:
            return
        today = now.date().isoformat()
        if REMINDER_FLAG_FILE.exists():
            try:
                if REMINDER_FLAG_FILE.read_text().strip() == today:
                    return
            except Exception:
                pass
        log.info("Daily reminder: démarrage")
        users = load_users()
        sent = 0
        for user_id_str, data in users.items():
            if not isinstance(data, dict):
                continue
            accounts = data.get("accounts", [])
            if not accounts:
                continue
            channel_id = data.get("channel_id")
            if not channel_id:
                continue
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue
            text = f"☀️ **Bonjour ! Tâches du {now.strftime('%d/%m/%Y')}**\n\n"
            for i, acc in enumerate(accounts, 1):
                text += render_account_task_block(acc, i) + "\n\n"
            try:
                await channel.send(text)
                sent += 1
            except Exception as e:
                log.warning(f"Daily reminder erreur user {user_id_str}: {e}")
        REMINDER_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        REMINDER_FLAG_FILE.write_text(today, encoding="utf-8")
        log.info(f"Daily reminder: {sent} VAs notifiés")

    @daily_reminder.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Accounts(bot))
