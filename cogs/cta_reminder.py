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

Salon « rappels » (serveurs de guild_features.ANNONCES_POST, Va IG) : pas de
rappel par ticket mais, dans le salon « ─│⏰┤-rappels », UN message public par
tache et par jour (Story 10h, Reel 16h, Story CTA 20h), puis au plus 3 relances
anonymes tant qu'un VA n'a pas clique (Story 12h 15h 18h, Reel 17h 19h 21h,
Story CTA 21h 22h 23h), et le message « comptes » lundi, jeudi et dimanche a
12h. Tout le monde clique le meme bouton ; la reponse est ephemere, donc chacun
voit SON bouton passer au vert sans toucher au message commun. Etat :
data/annonces_post.json.

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

import asyncio
import json
import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
import safe_json

log = logging.getLogger("vabot.cta_reminder")


def _reminders_on(guild) -> bool:
    """False si les rappels/suivi sont désactivés sur ce serveur (ex: mode
    Threads -> pas de rappels Insta). True par défaut."""
    try:
        import guild_features as gf
        return gf.reminders_enabled(guild)
    except Exception:
        return True


def _annonces_on(guild) -> bool:
    """True si ce serveur recoit les annonces, relances et message comptes du
    salon « rappels ». False si guild_features ne repond pas : rien de tout
    ca ne doit apparaitre sur un serveur qui ne l'a pas demande."""
    try:
        import guild_features as gf
        return gf.annonces_post_enabled(guild)
    except Exception:
        return False


DATA_DIR = Path("data")
USERS_FILE = DATA_DIR / "users.json"
STATE_FILE = DATA_DIR / "cta_reminder_state.json"
TRACKING_STATE_FILE = DATA_DIR / "account_tracking_state.json"
ANNONCES_FILE = DATA_DIR / "annonces_post.json"

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


def _save_state(state: dict) -> bool:
    # Rend le resultat de safe_json, qui ne leve pas : sans ca, un clic
    # d'annonce sur un disque plein repondait « noté » sans rien noter.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return safe_json.write_text(STATE_FILE, json.dumps(state, indent=2, ensure_ascii=False))


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
    return _save_state(state)


def is_done_today(user_id: str, task_type: str) -> bool:
    return _fait(_load_state(), _today_key(), user_id, task_type)


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
    safe_json.write_text(TRACKING_STATE_FILE, json.dumps(state, indent=2, ensure_ascii=False))


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


# =============================================================
# SALON « RAPPELS » (serveurs de guild_features.ANNONCES_POST)
# =============================================================
# Va IG, proprietaire 03/10/2026 : les rappels dans chaque ticket sont coupes
# (SANS_RAPPELS) ; a la place, le bot ecrit dans UN salon commun. Le bouton est
# le meme pour tout le monde : un clic ne modifie JAMAIS le message public
# (sinon le premier qui clique le fait passer au vert pour tous) et repond en
# ephemere, au seul cliqueur.
#
# Le salon est « ─│⏰┤-rappels », categorie NOTIFICATION : « c'est ici
# maintenant pour envoyer les notifs, et chacun voit son truc a lui ».
# « ⏱️・heure-de-post », le premier choix, est devenu le salon du proprietaire
# (il y poste lui-meme) : le bot n'y ecrit plus jamais.
#
# Permissions du salon : les VA ont besoin de « Voir le salon » ET de « Voir
# les anciens messages » -- sans la seconde, Discord ne leur montre que les
# messages arrives pendant qu'ils regardent le salon : l'annonce de 10h est
# invisible a 10h30, donc pas de bouton. « Envoyer des messages » peut rester
# coupe. Le bot : voir, envoyer, et voir les anciens messages (sans quoi
# Discord lui rend un historique VIDE et la relecture apres redemarrage ne
# retrouve rien).

#: Le salon se reconnait a son nom une fois decor, emoji et accents retires
#: (« ─│⏰┤-rappels » -> « rappels »). L'id ne sert que de repli : un salon
#: renomme a la main ne doit pas faire taire les rappels.
SALON_ANNONCES_NOM = "rappels"
SALON_ANNONCES_ID = {"1505418484052394004": 1555954270304473118}   # Va IG
#: Jamais ici, meme renomme : « ⏱️・heure-de-post » est au proprietaire.
SALONS_INTERDITS = frozenset({1555926908229914684})
NOMS_INTERDITS = ("heure-de-post",)
#: Une categorie d'archives garde parfois un vieux salon « rappels » : y
#: ecrire parlerait dans le vide.
CATEGORIE_ARCHIVES = "archives"
#: Messages relus apres une perte de l'etat. Une journee pose jusqu'a 13
#: messages (3 annonces, 9 relances, le message comptes) : 100 couvre aussi la
#: veille a griser, en un seul appel a Discord.
HISTORIQUE_ANNONCES = 100

ANNONCE_TEXTES = {
    "story": "C'est l'heure de poster une story classique sur ton compte.",
    "reel": "C'est l'heure de poster ton reel sur ton compte.",
    "cta": "C'est l'heure de poster ta story CTA sur ton compte.",
}
# Accord des boutons : « Reel posté », « Story postée ».
_ANNONCE_ACCORD = {"reel": "", "story": "e", "cta": "e"}

ANNONCE_PREREQUIS = (
    "⚠️ **Important** : ne le fais que si ton compte Instagram **est warmé** "
    "et **à jour 6+**. Si pas encore prêt, ignore ce message."
)

#: Relances, heures de Paris. Proprietaire, 03/10/2026 : « si le mec il clique
#: pas sur j'ai poste mon reel, ca le relance 3 dans la journee et c'est
#: tout ». Il a ecarte la mention, le MP et le ticket : la relance est
#: publique et anonyme, dans le meme salon, avec le MEME bouton que l'annonce.
RELANCES = {"story": (12, 15, 18), "reel": (17, 19, 21), "cta": (21, 22, 23)}
RELANCE_TEXTES = {
    "story": "📷 **Rappel — story du jour**\n"
             "Si ce n'est pas encore fait, poste ta story et clique le bouton vert.",
    "reel": "🎬 **Rappel — reel du jour**\n"
            "Si ce n'est pas encore fait, poste ton reel et clique le bouton vert.",
    # les mots du proprietaire
    "cta": "📸 **Si t'as pas encore fait ta story CTA du jour, fais-la !**\n"
           "Clique le bouton vert quand c'est fait.",
}
#: Ecart minimal entre une annonce et sa relance, en minutes : celui d'une
#: journee normale (Reel 16h -> 17h, CTA 20h -> 21h). Comparer les seules
#: heures laissait une annonce posee a 16h59 (bot revenu en retard) suivie a
#: 17h00 de « si ce n'est pas encore fait ». La relance attend alors 17h59 ;
#: hors de son heure, elle n'est pas rattrapee.
ECART_RELANCE_MIN = 60
#: La derniere relance de la journee (23h) le dit : apres, plus rien.
RELANCE_DERNIERE = {
    "cta": "📸 **Dernier rappel — story CTA du jour**\n"
           "Si t'as pas encore fait ta story CTA, fais-la maintenant et clique le bouton vert.",
}

#: Message « comptes ». Proprietaire, 03/10/2026 : « un tous les lundi, jeudi
#: et dimanche qui dit : bro si t'as un compte, faut avoir 3 comptes crees ».
#: Ce ne sont pas les jours du suivi par ticket (TRACKING_DAYS), qui reste
#: coupe sur Va IG (SANS_RAPPELS).
JOURS_COMPTES = (0, 3, 6)          # lundi, jeudi, dimanche
HEURE_COMPTES = 12                 # puis jusqu'a 23h59 si le bot etait coupe a midi
TEXTE_COMPTES = (
    "📱 **Tes comptes**\n"
    f"Bro, il faut avoir **{NB_COMPTES} comptes** créés. Si t'en as qu'un, crée les "
    "autres et ajoute-les avec 📷 Mes comptes dans ton ticket."
)
COMPTES_NEUTRE = ("📷 Rien à afficher : ce bouton sert aux VA qui ont un ticket et "
                  "une model sur ce serveur.")
COMPTES_ILLISIBLES = "⚠️ Pas pu lire tes comptes, réessaie dans un instant."
#: Au plus autant de lignes : COMPTES_FR_MAX (cogs/user) plafonne a 10 par
#: personne, la marge couvre les comptes poses a la main sur le site.
COMPTES_AFFICHES = 15

#: Le JOUR est dans le custom_id : un clic sur le bouton d'hier se reconnait,
#: et le bouton repond apres un redemarrage sans rien garder en memoire.
_ANNONCE_MOTIF = (r"annonce_post:(?P<tache>" + "|".join(re.escape(t) for t in TASK_CONFIG)
                  + r"):(?P<jour>[0-9]{8})")
#: Ici le jour ne sert qu'a retrouver le message du jour dans le salon apres
#: un redemarrage : le bouton reste valable les jours suivants.
_COMPTES_MOTIF = r"annonce_comptes:(?P<jour>[0-9]{8})"


def custom_id_annonce(tache: str, jour8: str) -> str:
    return f"annonce_post:{tache}:{jour8}"


def custom_id_comptes(jour8: str) -> str:
    return f"annonce_comptes:{jour8}"


def fenetre_annonce(tache: str) -> tuple:
    """(premiere heure, derniere heure) des rappels de la tache. L'annonce part
    a la premiere ; un bot relance plus tard dans la fenetre la pose encore,
    un bot reste coupe jusqu'apres la derniere ne la pose plus (un « c'est
    l'heure » a 23h pour un creneau fini a 22h tromperait)."""
    h = TASK_CONFIG[tache]["hours"]
    return min(h), max(h)


def taches_annonces() -> list:
    """Taches dans l'ordre de la journee : apres un redemarrage tardif, la
    plus recente arrive en bas du salon."""
    return sorted(TASK_CONFIG, key=lambda t: (fenetre_annonce(t)[0], t))


def _entete_annonce(tache: str) -> str:
    """Debut de l'annonce, et rien d'autre ne commence ainsi : c'est ce qui la
    distingue de ses relances, qui portent le MEME bouton."""
    cfg = TASK_CONFIG[tache]
    return f"{cfg['emoji']} **{cfg['label']} du jour** — "


def texte_annonce(tache: str, jour: date) -> str:
    cfg = TASK_CONFIG[tache]
    return (
        f"{_entete_annonce(tache)}{jour:%d/%m}\n"
        f"{ANNONCE_TEXTES[tache]}\n"
        "Quand c'est fait, clique sur le bouton vert : ça ne compte que pour toi.\n\n"
        f"{cfg['limit_note']}\n"
        f"{ANNONCE_PREREQUIS}"
    )


def texte_relance(tache: str, heure: int) -> str:
    if heure == max(RELANCES[tache]) and tache in RELANCE_DERNIERE:
        return RELANCE_DERNIERE[tache]
    return RELANCE_TEXTES[tache]


def _est_annonce(tache: str, contenu) -> bool:
    return str(contenu or "").startswith(_entete_annonce(tache))


def _jj_mm(jour8: str) -> str:
    return f"{jour8[6:8]}/{jour8[4:6]}"


def _minutes_de(hhmm):
    """« 16:20 » -> 980 (minutes depuis minuit) ; None si illisible."""
    try:
        h, m = str(hhmm).split(":")[:2]
        h, m = int(h), int(m)
    except Exception:
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def _tz_paris():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Paris")
    except Exception:
        return _paris_now().tzinfo


def _moment_paris(message):
    """Date et heure de Paris d'un message (created_at, sinon son snowflake),
    ou None."""
    quand = getattr(message, "created_at", None)
    if quand is None:
        try:
            quand = discord.utils.snowflake_time(int(message.id))
        except Exception:
            return None
    try:
        if quand.tzinfo is None:
            quand = quand.replace(tzinfo=timezone.utc)
        return quand.astimezone(_tz_paris())
    except Exception:
        return None


def _load_annonces() -> dict:
    d = safe_json.load(ANNONCES_FILE, default={})
    return d if isinstance(d, dict) else {}


def _save_annonces(etat: dict) -> bool:
    return safe_json.write(ANNONCES_FILE, etat)


def _entree_annonce(etat: dict, gid: str, tache: str) -> dict:
    g = etat.get(str(gid))
    e = g.get(tache) if isinstance(g, dict) else None
    return e if isinstance(e, dict) else {}


def _nom_nu(nom) -> str:
    """« ─│⏰┤-rappels » -> « rappels » : sans emoji, sans decor, sans accent,
    en minuscules."""
    s = unicodedata.normalize("NFKD", str(nom or "")).lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s.strip("-")


def _salon_permis(ch) -> bool:
    try:
        if int(getattr(ch, "id", 0) or 0) in SALONS_INTERDITS:
            return False
    except Exception:
        return False
    nom = _nom_nu(getattr(ch, "name", ""))
    if any(n in nom for n in NOMS_INTERDITS):
        return False
    cat = getattr(ch, "category", None)
    if cat is not None and CATEGORIE_ARCHIVES in _nom_nu(getattr(cat, "name", "")):
        return False
    return hasattr(ch, "send")


def salon_annonces(guild):
    """Salon « rappels » de ce serveur, ou None. Jamais le salon du
    proprietaire ni un salon d'archives, meme par l'id de repli."""
    repli = SALON_ANNONCES_ID.get(str(getattr(guild, "id", "")))
    candidats = [ch for ch in list(getattr(guild, "text_channels", None) or [])
                 if SALON_ANNONCES_NOM in _nom_nu(getattr(ch, "name", "")) and _salon_permis(ch)]
    # Le nom exact d'abord (« rappels » plutot que « rappels-managers »),
    # puis celui qui porte l'id connu.
    candidats.sort(key=lambda ch: (_nom_nu(getattr(ch, "name", "")) != SALON_ANNONCES_NOM,
                                   getattr(ch, "id", None) != repli))
    if candidats:
        return candidats[0]
    if repli:
        try:
            ch = guild.get_channel(int(repli))
        except Exception:
            ch = None
        if ch is not None and _salon_permis(ch):
            return ch
    return None


def _boutons_du_message(message):
    """(custom_id, disabled) de chaque composant d'un message, lignes et
    conteneurs compris."""
    pile = list(getattr(message, "components", None) or [])
    vus = 0
    while pile and vus < 200:          # borne : un message a au plus 40 composants
        c = pile.pop(0)
        vus += 1
        cid = getattr(c, "custom_id", None)
        if cid:
            yield cid, bool(getattr(c, "disabled", False))
        enfants = getattr(c, "children", None)
        if enfants:
            pile.extend(enfants)


def _fiche_ici(guild, uid, users=None):
    """La fiche users.json du membre si son ticket est un salon de CE serveur,
    sinon None : une fiche du serveur principal ne fait pas un VA de Va IG."""
    if guild is None:
        return None
    users = _load_users() if users is None else users
    fiche = users.get(str(uid)) if isinstance(users, dict) else None
    if not isinstance(fiche, dict):
        return None
    try:
        cid = int(fiche.get("channel_id") or 0)
    except Exception:
        return None
    if not cid:
        return None
    try:
        ch = guild.get_channel(cid)
    except Exception:
        ch = None
    return fiche if ch is not None else None


def _fait(etat_rappels: dict, jour_iso: str, uid, tache: str) -> bool:
    """La regle de is_done_today, sur un etat deja lu : la relance consulte
    tous les VA d'un coup, une lecture du fichier par VA serait 160 lectures."""
    j = etat_rappels.get(jour_iso) if isinstance(etat_rappels, dict) else None
    u = j.get(str(uid)) if isinstance(j, dict) else None
    t = u.get(tache) if isinstance(u, dict) else None
    return bool(t.get("done", False)) if isinstance(t, dict) else False


class AnnoncePostButton(discord.ui.DynamicItem[discord.ui.Button], template=_ANNONCE_MOTIF):
    """Bouton vert d'une annonce publique et de ses relances. Ne reutilise PAS
    les custom_id de TaskDoneView (« reel_done_button »…) : celle-ci reecrit le
    message clique, ce qui, sur un message commun, le changerait pour tout le
    monde."""

    def __init__(self, tache: str, jour8: str):
        self.tache = tache
        self.jour8 = jour8
        super().__init__(discord.ui.Button(
            label=TASK_CONFIG[tache]["btn_label"],
            style=discord.ButtonStyle.success,
            custom_id=custom_id_annonce(tache, jour8),
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["tache"], match["jour"])

    async def callback(self, interaction: discord.Interaction):
        await repondre_clic_annonce(interaction, self.tache, self.jour8)


class AnnonceComptesButton(discord.ui.DynamicItem[discord.ui.Button], template=_COMPTES_MOTIF):
    """Bouton « 📷 Mes comptes » du message comptes : montre au seul cliqueur
    les comptes qu'il a enregistres. Ne touche jamais le message public."""

    def __init__(self, jour8: str):
        self.jour8 = jour8
        super().__init__(discord.ui.Button(
            label="Mes comptes",
            emoji="📷",
            style=discord.ButtonStyle.primary,
            custom_id=custom_id_comptes(jour8),
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["jour"])

    async def callback(self, interaction: discord.Interaction):
        await repondre_clic_comptes(interaction)


def vue_annonce(tache: str, jour8: str) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(AnnoncePostButton(tache, jour8))
    return v


def vue_comptes(jour8: str) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(AnnonceComptesButton(jour8))
    return v


def _vue_verte(label: str) -> discord.ui.View:
    """Bouton vert grise, dans la reponse ephemere : c'est le « truc en vert »
    que seul le cliqueur voit."""
    v = discord.ui.View()
    v.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.success,
                                 disabled=True))
    return v


async def repondre_clic_annonce(interaction: discord.Interaction, tache: str, jour8: str):
    """Clic sur une annonce ou une relance : reponse EPHEMERE seulement, le
    message public n'est jamais modifie. Chaque clic vaut pour le seul
    cliqueur."""
    cfg = TASK_CONFIG.get(tache, TASK_CONFIG["cta"])
    label = cfg["label"]
    e = _ANNONCE_ACCORD.get(tache, "")
    aujourd_hui = _paris_now().date()
    if jour8 != aujourd_hui.strftime("%Y%m%d"):
        # Un clic d'aujourd'hui sur le bouton d'hier ne doit pas valider la
        # journee : il dirait « poste » pour un jour deja fini.
        txt = f"⏳ Ce bouton était pour le {_jj_mm(jour8)}."
        try:
            gid = getattr(interaction, "guild_id", None)
            if gid is not None and _entree_annonce(_load_annonces(), str(gid), tache).get(
                    "jour") == aujourd_hui.isoformat():
                txt += " Celui d'aujourd'hui est plus bas."
        except Exception:
            pass
        await interaction.response.send_message(txt, ephemeral=True)
        return
    uid = str(interaction.user.id)
    if is_done_today(uid, tache):
        await interaction.response.send_message(
            "👍 Déjà noté pour toi aujourd'hui.",
            view=_vue_verte(f"✅ {label} déjà noté{e} aujourd'hui"),
            ephemeral=True,
        )
        return
    try:
        note = mark_done(uid, tache)
        raison = "etat non enregistre"
    except Exception as ex:
        note, raison = False, ex
    if not note:
        # Un « noté » affiche alors que l'etat n'est pas ecrit ferait croire
        # au VA que c'est compte, et son 2e clic redirait « noté » au lieu de
        # « deja noté » : on lui dit plutot de recommencer.
        log.warning(f"[annonces] clic {tache} de {uid} pas note : {raison}")
        await interaction.response.send_message(
            "⚠️ Pas pu le noter, réessaie dans un instant.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ **{label} noté{e} pour toi aujourd'hui.** Les autres ne voient pas ton clic.",
        view=_vue_verte(f"✅ {label} posté{e}"),
        ephemeral=True,
    )


def _pseudo(s) -> str:
    return str(s or "").strip().lstrip("@").lower()


def comptes_du_va(nom, models) -> list:
    """Les @ des comptes Va IG du VA : ceux de SES models (ses roles), model
    par model.

    Un compte est a lui s'il est range sous son nom Discord (la regle de
    cogs/user._comptes_fr_du_va, celle de la fenetre 📷 Mes comptes de son
    ticket) ou sous une fiche de la model qui porte son pseudo Discord (la
    regle de jailbreak.accounts_for_discord_username). Cette derniere fouille
    TOUTES les identites : six VA sont arrives sur Va IG avec une identite US
    (welcome.identite_pour_serveur) et leurs comptes US les faisaient passer
    pour « ✅ T'as tes 3 comptes » sans un seul compte Va IG -- d'ou la
    restriction aux models du membre."""
    import jailbreak
    from cogs.user import _comptes_fr_du_va
    nom = _pseudo(nom)
    out, vus = [], set()
    for m in models or []:
        fiches = [nom]
        for v in jailbreak.list_vas_for_identity(m):
            n = str(v.get("name") or "").strip().lower() if isinstance(v, dict) else ""
            if n and n not in fiches and _pseudo(v.get("discord_username")) == nom:
                fiches.append(n)
        for n in fiches:
            for u in _comptes_fr_du_va(m, n):
                u = str(u or "").strip().lstrip("@")
                if u and u.lower() not in vus:
                    vus.add(u.lower())
                    out.append(u)
    return out


def texte_comptes_du_va(handles) -> str:
    n = len(handles)
    lignes = [f"📷 **Tes comptes enregistrés : {n}**"]
    lignes += [f"• @{discord.utils.escape_markdown(h)}" for h in handles[:COMPTES_AFFICHES]]
    if n > COMPTES_AFFICHES:
        lignes.append(f"… et {n - COMPTES_AFFICHES} autre(s)")
    if n >= NB_COMPTES:
        lignes.append(f"✅ T'as tes {NB_COMPTES} comptes.")
    else:
        manque = NB_COMPTES - n
        les = "le" if manque == 1 else "les"
        lignes.append(f"Il t'en manque {manque} : crée-{les} et ajoute-{les} avec "
                      "📷 Mes comptes dans ton ticket.")
    return "\n".join(lignes)


def _texte_clic_comptes(guild, membre) -> str:
    if membre is None or _fiche_ici(guild, getattr(membre, "id", "")) is None:
        return COMPTES_NEUTRE
    from cogs.welcome import models_du_membre
    models = models_du_membre(membre)
    if not models:
        return COMPTES_NEUTRE
    return texte_comptes_du_va(comptes_du_va(getattr(membre, "name", ""), models))


async def repondre_clic_comptes(interaction: discord.Interaction):
    """Clic sur « 📷 Mes comptes » : ses comptes, a lui seul (ephemere)."""
    membre = getattr(interaction, "user", None)
    guild = getattr(interaction, "guild", None)
    if guild is None:
        try:
            guild = interaction.client.get_guild(int(interaction.guild_id))
        except Exception:
            guild = None
    try:
        # jailbreak.json et users.json se lisent sur le disque : hors de la
        # boucle, un gros fichier ne doit pas figer le bot.
        txt = await asyncio.to_thread(_texte_clic_comptes, guild, membre)
    except Exception as ex:
        log.warning(f"[annonces] comptes de {getattr(membre, 'id', '?')} illisibles : {ex}")
        txt = COMPTES_ILLISIBLES
    await interaction.response.send_message(
        txt, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class AnnoncesPost:
    """Ecrit dans le salon « rappels » des serveurs de ANNONCES_POST :
    l'annonce de chaque tache, ses relances, le message comptes ; grise les
    boutons de la veille. Appele chaque minute par
    CTAReminderCog.annonces_loop ; `now` se passe pour les tests."""

    def __init__(self, bot):
        self.bot = bot
        self._deja_dit: set = set()
        #: (gid, tache ou « comptes ») -> jour iso des messages poses ou
        #: retrouves par CE processus. safe_json.write ne leve pas : un etat
        #: non ecrit (disque plein) laissait la tache « due » chaque minute, et
        #: seul l'historique evitait de reposter -- or un bot sans « Voir les
        #: anciens messages » recoit de Discord une liste vide : une annonce
        #: par minute toute la fenetre. Avec ce garde, un etat perdu coute au
        #: pire un doublon par redemarrage.
        self._poses: dict = {}
        #: (gid, tache) -> (jour iso, minute du jour de l'annonce ou None) :
        #: une relance attend ECART_RELANCE_MIN apres son annonce.
        self._heure_pose: dict = {}
        #: (gid, tache, jour iso, heure) des relances posees ou retrouvees :
        #: le meme garde que _poses, pour les relances.
        self._relances_faites: set = set()
        #: (gid, tache, jour iso, heure) dont le salon a deja ete relu avant une
        #: relance : une relecture par heure, pas par minute.
        self._relu: set = set()
        #: Relecture du salon partagee le temps d'un tour : annonce, relance et
        #: message comptes peuvent la demander dans la meme minute.
        self._hist_tour = None

    def _log_une_fois(self, jour, gid, quoi: str, message: str, niveau=logging.WARNING):
        """Une boucle d'une minute qui echoue sur un salon introuvable ecrirait
        1 440 lignes par jour : une seule suffit, et le lendemain on le redit."""
        cle = (str(jour), str(gid), quoi)
        if cle in self._deja_dit:
            return
        self._deja_dit = {k for k in self._deja_dit if k[0] == str(jour)}
        self._deja_dit.add(cle)
        log.log(niveau, message)

    def _sauver(self, etat: dict, jour, gid: str):
        """safe_json rend False sans lever : on le dit (une fois par jour),
        sinon l'annonce semble enregistree alors qu'un redemarrage la
        reposterait. Le garde en memoire (_poses) evite deja la repetition."""
        if not _save_annonces(etat):
            self._log_une_fois(jour, gid, "etat",
                               f"[annonces] {ANNONCES_FILE} pas enregistre : les "
                               f"annonces du jour ne sont gardees qu'en memoire "
                               f"(un redemarrage peut en reposter une)")

    def _salon(self, guild, jour, quoi: str):
        salon = salon_annonces(guild)
        if salon is None:
            gid = str(getattr(guild, "id", ""))
            self._log_une_fois(jour, gid, "salon",
                               f"[annonces] {getattr(guild, 'name', gid)} : aucun salon "
                               f"« {SALON_ANNONCES_NOM} » -> pas de {quoi} aujourd'hui")
        return salon

    async def tick(self, now: datetime | None = None):
        now = now or _paris_now()
        jour_iso = now.date().isoformat()
        # Les gardes ne valent que pour le jour : la boucle tourne des semaines.
        self._relances_faites = {k for k in self._relances_faites if k[2] == jour_iso}
        self._relu = {k for k in self._relu if k[2] == jour_iso}
        for guild in list(getattr(self.bot, "guilds", None) or []):
            if not _annonces_on(guild):
                continue
            self._hist_tour = {}
            try:
                # Etapes isolees : une relance en echec ne doit pas empecher
                # l'annonce du lendemain, ni l'inverse.
                for etape in (self._annonces_du_jour, self._relancer, self._message_comptes):
                    try:
                        await etape(guild, now)
                    except Exception as ex:
                        self._log_une_fois(now.date(), getattr(guild, "id", "?"),
                                           f"erreur:{etape.__name__}:{type(ex).__name__}",
                                           f"[annonces] {getattr(guild, 'name', '?')} "
                                           f"({etape.__name__}) : {ex}")
            finally:
                self._hist_tour = None

    # ------------------------------------------------------------ annonces --
    async def _annonces_du_jour(self, guild, now: datetime):
        jour = now.date()
        jour_iso = jour.isoformat()
        jour8 = jour.strftime("%Y%m%d")
        gid = str(guild.id)
        nom = getattr(guild, "name", gid)
        dues = [t for t in taches_annonces()
                if fenetre_annonce(t)[0] <= now.hour <= fenetre_annonce(t)[1]]
        if not dues:
            return
        dues = [t for t in dues if self._poses.get((gid, t)) != jour_iso]
        if not dues:
            return
        etat = _load_annonces()
        dues = [t for t in dues if _entree_annonce(etat, gid, t).get("jour") != jour_iso]
        if not dues:
            return
        salon = self._salon(guild, jour, f"annonce ({', '.join(dues)})")
        if salon is None:
            return
        # L'etat dit deja ce qui est poste ; on ne relit le salon que s'il
        # manque l'annonce du jour (data/ perdu ou pas copie sur le VPS) :
        # sans ca, un redemarrage reposterait la meme annonce.
        hist = await self._historique(salon, jour, gid)
        for t in dues:
            if t in hist["annonces"]:
                self._retrouver(etat, gid, t, hist, jour, salon, nom)
                continue
            precedent = dict(_entree_annonce(etat, gid, t))
            try:
                msg = await salon.send(
                    content=texte_annonce(t, jour),
                    view=vue_annonce(t, jour8),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception as ex:
                self._log_une_fois(jour, gid, f"envoi:{t}",
                                   f"[annonces] {nom} : {t} pas poste ({ex}) -- "
                                   f"nouvel essai chaque minute")
                continue
            # Enregistre AVANT de griser la veille : une coupure entre les deux
            # laisse un vieux bouton actif (inoffensif), pas une annonce en double.
            self._poses[(gid, t)] = jour_iso
            self._heure_pose[(gid, t)] = (jour_iso, now.hour * 60 + now.minute)
            g = etat.get(gid) if isinstance(etat.get(gid), dict) else {}
            g[t] = {"jour": jour_iso, "message": msg.id, "salon": salon.id,
                    "pose": now.strftime("%H:%M"), "relances": {}}
            etat[gid] = g
            self._sauver(etat, jour, gid)
            log.info(f"[annonces] {nom} : {t} du {jour:%d/%m} poste ({msg.id})")
            # La veille : l'annonce ET ses relances, qui portent le meme bouton
            # (l'etat les nomme ; le salon relu rattrape un etat perdu).
            a_griser = []
            if precedent.get("jour") and precedent["jour"] != jour_iso:
                try:
                    j_prec = date.fromisoformat(precedent["jour"])
                    ids = [precedent.get("message")]
                    rel = precedent.get("relances")
                    ids += list(rel.values()) if isinstance(rel, dict) else []
                    for mid in ids:
                        if mid:
                            a_griser.append((precedent.get("salon"), int(mid), j_prec))
                except Exception as ex:
                    log.warning(f"[annonces] entree precedente illisible ({t}) : {ex}")
            for mid, j8 in hist["anciens"].get(t, []):
                try:
                    a_griser.append((salon.id, int(mid),
                                     date(int(j8[:4]), int(j8[4:6]), int(j8[6:]))))
                except Exception:
                    pass
            faits = set()
            for salon_id, mid, j in a_griser:
                if mid in faits or mid == msg.id:
                    continue
                faits.add(mid)
                await self._griser(guild, salon, salon_id, mid, t, j)

    def _retrouver(self, etat: dict, gid: str, t: str, hist: dict, jour, salon, nom):
        """Annonce du jour retrouvee dans le salon (etat perdu) : l'etat et la
        memoire la reprennent, avec ses relances, pour ne rien reposter."""
        jour_iso = jour.isoformat()
        rel = hist["relances"].get(t, {})
        g = etat.get(gid) if isinstance(etat.get(gid), dict) else {}
        g[t] = {"jour": jour_iso, "message": hist["annonces"][t], "salon": salon.id,
                "retrouve": True, "relances": {str(h): mid for h, mid in sorted(rel.items())}}
        pose = hist["poses"].get(t)
        if pose:
            g[t]["pose"] = pose
        etat[gid] = g
        self._poses[(gid, t)] = jour_iso
        self._heure_pose[(gid, t)] = (jour_iso, _minutes_de(pose) if pose else None)
        for h in rel:
            self._relances_faites.add((gid, t, jour_iso, int(h)))
        self._sauver(etat, jour, gid)
        log.info(f"[annonces] {nom} : {t} du {jour:%d/%m} retrouvee dans le salon, "
                 f"pas reposte" + (f" (relances de {', '.join(f'{h}h' for h in sorted(rel))})"
                                   if rel else ""))

    # ------------------------------------------------------------ relances --
    def _annonce_connue(self, etat: dict, gid: str, t: str, jour_iso: str):
        """(annonce du jour posee ?, minute du jour de l'annonce ou None)."""
        e = _entree_annonce(etat, gid, t)
        if e.get("jour") == jour_iso and e.get("message"):
            return True, (_minutes_de(e.get("pose")) if e.get("pose") else None)
        if self._poses.get((gid, t)) == jour_iso:
            j, m = self._heure_pose.get((gid, t), (None, None))
            return True, (m if j == jour_iso else None)
        return False, None

    def _reprendre_relances(self, etat: dict, gid: str, t: str, hist: dict, jour, nom):
        """Relances du jour trouvees au salon alors que l'etat nomme deja
        l'annonce : l'etat et la memoire les reprennent, sans toucher a
        l'annonce."""
        jour_iso = jour.isoformat()
        trouvees = hist["relances"].get(t) or {}
        for hh in trouvees:
            self._relances_faites.add((gid, t, jour_iso, int(hh)))
        e = _entree_annonce(etat, gid, t)
        if e.get("jour") == jour_iso:
            rel = e.get("relances") if isinstance(e.get("relances"), dict) else {}
            for hh, mid in sorted(trouvees.items()):
                rel.setdefault(str(hh), mid)
            e["relances"] = rel
            self._sauver(etat, jour, gid)
        log.info(f"[annonces] {nom} : relance(s) {t} de "
                 f"{', '.join(f'{hh}h' for hh in sorted(trouvees))} retrouvee(s) dans le "
                 f"salon, pas repostee(s)")

    def _sans_clic(self, guild, jour, taches) -> tuple:
        """(VA eligibles, {tache: eligibles qui n'ont pas clique aujourd'hui}).
        Eligible : membre du serveur, fiche users.json dont le ticket est un
        salon d'ICI, et au moins un role de model (sur Va IG les roles font
        foi : cogs.welcome.models_du_membre)."""
        from cogs.welcome import models_du_membre
        gid = str(guild.id)
        users = _load_users()
        eligibles, absents = [], []
        for uid in list(users):
            if _fiche_ici(guild, uid, users) is None:
                continue
            try:
                membre = guild.get_member(int(uid))
            except Exception:
                membre = None
            if membre is None:
                absents.append(str(uid))
                continue
            try:
                if models_du_membre(membre):
                    eligibles.append(str(uid))
            except Exception as ex:
                log.warning(f"[annonces] roles de {uid} illisibles : {ex}")
        if absents:
            # Sans l'intention « membres » ou avant que le cache soit rempli,
            # get_member rend None : on le dit, plutot que de relancer pour
            # des gens qu'on ne sait pas lire.
            self._log_une_fois(jour, gid, "absents",
                               f"[annonces] {getattr(guild, 'name', gid)} : {len(absents)} "
                               f"VA avec un ticket ici mais absent(s) du cache des membres, "
                               f"ignore(s) pour les relances : {', '.join(absents[:10])}"
                               + (" ..." if len(absents) > 10 else ""))
        etat = _load_state()
        j = jour.isoformat()
        return eligibles, {t: [u for u in eligibles if not _fait(etat, j, u, t)] for t in taches}

    async def _relancer(self, guild, now: datetime):
        """Une relance par tache a l'heure prevue, et dans cette heure
        seulement : un bot coupe de 11h a 16h ne rattrape ni 12h ni 15h (le
        proprietaire veut 3 rappels au plus, pas une rafale au redemarrage)."""
        h = now.hour
        jour = now.date()
        jour_iso = jour.isoformat()
        jour8 = jour.strftime("%Y%m%d")
        gid = str(guild.id)
        nom = getattr(guild, "name", gid)
        taches = [t for t in taches_annonces() if h in RELANCES.get(t, ())
                  and (gid, t, jour_iso, h) not in self._relances_faites]
        if not taches:
            return
        etat = _load_annonces()
        restent = []
        for t in taches:
            e = _entree_annonce(etat, gid, t)
            rel = e.get("relances") if isinstance(e.get("relances"), dict) else {}
            if e.get("jour") == jour_iso and str(h) in rel:
                self._relances_faites.add((gid, t, jour_iso, h))
            else:
                restent.append(t)
        if not restent:
            return
        eligibles, attente = self._sans_clic(guild, jour, restent)
        a_faire = []
        for t in restent:
            if not eligibles:
                self._log_une_fois(jour, gid, f"relance:{t}:{h}",
                                   f"[annonces] {nom} : pas de relance {t} a {h}h, aucun VA "
                                   f"avec un ticket et un role de model", logging.INFO)
            elif not attente.get(t):
                self._log_une_fois(jour, gid, f"relance:{t}:{h}",
                                   f"[annonces] {nom} : pas de relance {t} a {h}h, les "
                                   f"{len(eligibles)} VA ont clique", logging.INFO)
            else:
                a_faire.append(t)
        if not a_faire:
            return
        salon = self._salon(guild, jour, "relance")
        if salon is None:
            return
        for t in a_faire:
            cle = (gid, t, jour_iso, h)
            connue, m_annonce = self._annonce_connue(etat, gid, t, jour_iso)
            if cle not in self._relu:
                # Ni la memoire ni l'etat ne nomment la relance de cette heure :
                # elle est peut-etre deja au salon. Etat perdu, mais aussi etat
                # qui nomme l'annonce sans la relance (ecriture ratee sur un
                # disque plein, coupure pendant l'envoi) : sans cette relecture,
                # un redemarrage dans l'heure la reposait. Une par heure, comme
                # l'annonce, qui relit le salon avant chaque premier envoi.
                self._relu.add(cle)
                hist = await self._historique(salon, jour, gid)
                if not connue and t in hist["annonces"]:
                    self._retrouver(etat, gid, t, hist, jour, salon, nom)
                    connue, m_annonce = self._annonce_connue(etat, gid, t, jour_iso)
                elif connue and h in (hist["relances"].get(t) or {}):
                    self._reprendre_relances(etat, gid, t, hist, jour, nom)
            if cle in self._relances_faites:
                continue
            if not connue:
                self._log_une_fois(jour, gid, f"relance:{t}:{h}",
                                   f"[annonces] {nom} : pas de relance {t} a {h}h, l'annonce "
                                   f"du jour n'a pas ete postee", logging.INFO)
                continue
            if m_annonce is not None and now.hour * 60 + now.minute - m_annonce < ECART_RELANCE_MIN:
                # Annonce posee il y a moins d'une heure (bot revenu en
                # retard) : une relance dans la foulee la repeterait.
                continue
            try:
                msg = await salon.send(
                    content=texte_relance(t, h),
                    view=vue_annonce(t, jour8),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception as ex:
                self._log_une_fois(jour, gid, f"envoi:relance:{t}:{h}",
                                   f"[annonces] {nom} : relance {t} de {h}h pas postee "
                                   f"({ex}) -- nouvel essai chaque minute jusqu'a {h}h59")
                continue
            self._relances_faites.add(cle)
            g = etat.get(gid) if isinstance(etat.get(gid), dict) else {}
            e = g.get(t)
            if isinstance(e, dict) and e.get("jour") == jour_iso:
                rel = e.get("relances") if isinstance(e.get("relances"), dict) else {}
                rel[str(h)] = msg.id
                e["relances"] = rel
                self._sauver(etat, jour, gid)
            log.info(f"[annonces] {nom} : relance {t} de {h}h postee ({msg.id}, "
                     f"{len(attente.get(t) or [])} VA sans clic)")

    # ------------------------------------------------------- message comptes --
    async def _message_comptes(self, guild, now: datetime):
        if now.weekday() not in JOURS_COMPTES or now.hour < HEURE_COMPTES:
            return
        jour = now.date()
        jour_iso = jour.isoformat()
        jour8 = jour.strftime("%Y%m%d")
        gid = str(guild.id)
        nom = getattr(guild, "name", gid)
        if self._poses.get((gid, "comptes")) == jour_iso:
            return
        etat = _load_annonces()
        if _entree_annonce(etat, gid, "comptes").get("jour") == jour_iso:
            self._poses[(gid, "comptes")] = jour_iso
            return
        salon = self._salon(guild, jour, "message comptes")
        if salon is None:
            return
        hist = await self._historique(salon, jour, gid)
        g = etat.get(gid) if isinstance(etat.get(gid), dict) else {}
        if hist["comptes"]:
            self._poses[(gid, "comptes")] = jour_iso
            g["comptes"] = {"jour": jour_iso, "message": hist["comptes"], "salon": salon.id,
                            "retrouve": True}
            etat[gid] = g
            self._sauver(etat, jour, gid)
            log.info(f"[annonces] {nom} : message comptes du {jour:%d/%m} retrouve dans le "
                     f"salon, pas reposte")
            return
        try:
            msg = await salon.send(
                content=TEXTE_COMPTES,
                view=vue_comptes(jour8),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as ex:
            self._log_une_fois(jour, gid, "envoi:comptes",
                               f"[annonces] {nom} : message comptes pas poste ({ex}) -- "
                               f"nouvel essai chaque minute")
            return
        self._poses[(gid, "comptes")] = jour_iso
        g["comptes"] = {"jour": jour_iso, "message": msg.id, "salon": salon.id,
                        "pose": now.strftime("%H:%M")}
        etat[gid] = g
        self._sauver(etat, jour, gid)
        log.info(f"[annonces] {nom} : message comptes du {jour:%d/%m} poste ({msg.id})")

    # ------------------------------------------------------------ le salon --
    async def _historique(self, salon, jour, gid: str) -> dict:
        """Dans les derniers messages DU BOT :
          annonces : tache -> id de l'annonce du jour ; poses : son heure ;
          relances : tache -> {heure de Paris: id} des relances du jour ;
          anciens  : tache -> [(id, jour8)] des boutons d'avant encore actifs ;
          comptes  : id du message comptes du jour, ou None.
        Annonce et relances portent le meme bouton : seul le debut du texte
        (_entete_annonce) les separe."""
        cle = getattr(salon, "id", None)
        if self._hist_tour is not None and cle in self._hist_tour:
            return self._hist_tour[cle]
        jour8 = jour.strftime("%Y%m%d")
        res = {"annonces": {}, "poses": {}, "relances": {}, "anciens": {}, "comptes": None}
        moi = getattr(getattr(self.bot, "user", None), "id", None)
        motif = AnnoncePostButton.__discord_ui_compiled_template__
        motif_c = AnnonceComptesButton.__discord_ui_compiled_template__
        try:
            async for m in salon.history(limit=HISTORIQUE_ANNONCES):
                if moi is None or getattr(getattr(m, "author", None), "id", None) != moi:
                    continue
                for cid, desactive in _boutons_du_message(m):
                    mc = motif_c.fullmatch(cid)
                    if mc:
                        if mc["jour"] == jour8 and res["comptes"] is None:
                            res["comptes"] = m.id
                        continue
                    mt = motif.fullmatch(cid)
                    if not mt:
                        continue
                    t, j8 = mt["tache"], mt["jour"]
                    if j8 == jour8:
                        quand = _moment_paris(m)
                        if _est_annonce(t, getattr(m, "content", "")):
                            if t not in res["annonces"]:
                                res["annonces"][t] = m.id
                                res["poses"][t] = quand.strftime("%H:%M") if quand else None
                        elif quand is not None:
                            res["relances"].setdefault(t, {}).setdefault(quand.hour, m.id)
                    elif j8 < jour8 and not desactive:
                        res["anciens"].setdefault(t, []).append((m.id, j8))
        except Exception as ex:
            # Sans historique on poste quand meme : un message en double vaut
            # mieux qu'une journee sans rappel.
            self._log_une_fois(jour, gid, "historique",
                               f"[annonces] historique de #{getattr(salon, 'name', '?')} "
                               f"illisible : {ex}")
        if self._hist_tour is not None:
            self._hist_tour[cle] = res
        return res

    async def _griser(self, guild, salon_defaut, salon_id, message_id: int, tache: str, jour):
        """Bouton gris desactive « Journée du jj/mm terminée ». Le message
        reste : il n'est jamais supprime."""
        try:
            salon = None
            if salon_id:
                try:
                    salon = guild.get_channel(int(salon_id))
                except Exception:
                    salon = None
            salon = salon or salon_defaut
            v = discord.ui.View()
            v.add_item(discord.ui.Button(
                label=f"Journée du {jour:%d/%m} terminée",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                custom_id=f"annonce_post_fini:{tache}:{jour:%Y%m%d}",
            ))
            await salon.get_partial_message(int(message_id)).edit(view=v)
        except Exception as ex:
            log.warning(f"[annonces] {tache} du {jour:%d/%m} ({message_id}) pas grise : {ex}")


class CTAReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.annonces = AnnoncesPost(bot)
        self.check_loop.start()
        self.annonces_loop.start()

    def cog_unload(self):
        self.check_loop.cancel()
        self.annonces_loop.cancel()

    async def cog_load(self):
        # Enregistre les 3 views persistantes (une par task_type)
        for tt in TASK_CONFIG:
            self.bot.add_view(TaskDoneView(task_type=tt, target_user_id=0))
        # View pour le suivi comptes
        self.bot.add_view(AccountTrackingView(target_user_id=0))
        # Boutons du salon « rappels » (annonces, relances, message comptes) :
        # ce qu'il leur faut est dans le custom_id, ils repondent donc apres un
        # redemarrage. Isole : un echec ici ne doit pas priver les tickets des
        # boutons ci-dessus.
        try:
            self.bot.add_dynamic_items(AnnoncePostButton, AnnonceComptesButton)
        except Exception as e:
            log.error(f"[annonces] boutons non enregistres : {e}")

    @tasks.loop(minutes=1)
    async def annonces_loop(self):
        # Boucle a part : check_loop ne travaille que les 5 premieres minutes
        # de l'heure (un bot relance a 16h20 ne poserait pas le reel), et une
        # exception qui sort d'une tasks.loop l'arrete pour de bon -- les
        # rappels des autres serveurs n'ont pas a en dependre.
        try:
            await self.annonces.tick()
        except Exception as e:
            log.warning(f"[annonces] tour rate : {e}")

    @annonces_loop.before_loop
    async def before_annonces(self):
        await self.bot.wait_until_ready()

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
