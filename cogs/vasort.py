"""cogs/vasort.py — Range les salons VA + salons-séparateurs par groupe.

Ordre dans chaque catégorie :
  [salons non-VA : général, banger, exemple…]      (intouchés, en haut)
  ──🔗-lien-actif                                   (séparateur, staff only)
  1. 🔗 VA avec lien qui tourne — 🟢 puis 🟠 puis 🔴
  ──⚙️-lien-0-clic
  2. 🔗⚙️ VA avec lien à 0 clic (3 j) — 🟢 → 🔴
  ──😴-sans-lien
  3. VA sans lien — 🟢 → 🟠 → 🔴
Égalité -> ordre alphabétique du pseudo.

Séparateurs : salons texte verrouillés, visibles UNIQUEMENT par le staff
(deny @everyone ; les rôles contenant « boss » / « manager » + admins voient).
Créés automatiquement quand le groupe existe, supprimés si le groupe se vide.

Auto : re-tri toutes les 20 min (1 appel bulk par catégorie, seulement si
l'ordre a changé). Manuel : /rangerva (aperçu) puis /rangerva confirmer:True.
"""
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

_VA_RE = re.compile(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$")
DOT_RANK = {"🟢": 0, "🟠": 1, "🔴": 2}

SEP_LINK = "──🔗-lien-actif"
SEP_GEAR = "──⚙️-lien-0-clic"
SEP_NONE = "──😴-sans-lien"
SEP_BY_GROUP = {0: SEP_LINK, 1: SEP_GEAR, 2: SEP_NONE}


def _norm(s):
    """Compare sans le variation selector (⚙️ = ⚙ + U+FE0F) — anti-doublon."""
    return (s or "").replace("️", "")


def _is_sep(name):
    return _norm(name) in {_norm(s) for s in SEP_BY_GROUP.values()}


def _va_handle(name):
    m = _VA_RE.search((name or "").lower())
    return m.group(1) if m else None


def _sort_key(name: str):
    """(groupe, rond, pseudo) — plus petit = plus haut."""
    n = name or ""
    handle = _va_handle(n) or ""
    idx = n.lower().find("va-")
    prefix = n[:idx] if idx > 0 else ""
    dot = DOT_RANK.get(n[:1], 3)
    has_link = "🔗" in prefix
    has_gear = "⚙" in prefix
    if has_link and not has_gear:
        group = 0
    elif has_link:
        group = 1
    else:
        group = 2
    return (group, dot, handle)


def _split(category):
    """(others, groupes {0:[ch],1:[],2:[]}, separateurs existants {group: ch})"""
    txts = list(category.text_channels)
    others, seps = [], {}
    groups = {0: [], 1: [], 2: []}
    for c in txts:
        if _is_sep(c.name):
            for g, sname in SEP_BY_GROUP.items():
                if _norm(c.name) == _norm(sname):
                    seps[g] = c
            continue
        if _va_handle(c.name):
            groups[_sort_key(c.name)[0]].append(c)
        else:
            others.append(c)
    for g in groups:
        groups[g].sort(key=lambda c: _sort_key(c.name))
    return others, groups, seps


async def _staff_overwrites(guild):
    """Séparateurs visibles staff only : deny @everyone, allow boss/manager."""
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for role in guild.roles:
        rn = role.name.lower()
        if "boss" in rn or "manager" in rn or "staff" in rn:
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
    return ow


async def _sync_separators(guild, category, groups, seps, allow_create=True):
    """Crée les séparateurs manquants (groupe non vide) / supprime les inutiles."""
    changed = False
    for g in (0, 1, 2):
        need = bool(groups[g])
        have = seps.get(g)
        if need and not have and allow_create:
            try:
                ow = await _staff_overwrites(guild)
                ch = await guild.create_text_channel(
                    SEP_BY_GROUP[g], category=category, overwrites=ow,
                    reason="Séparateur tri VA")
                seps[g] = ch
                changed = True
            except Exception as e:
                print(f"[vasort] create sep {SEP_BY_GROUP[g]}: {e}", flush=True)
        elif not need and have:
            try:
                await have.delete(reason="Groupe VA vide — séparateur retiré")
                seps.pop(g, None)
                changed = True
            except Exception:
                pass
    return changed


def _desired(others, groups, seps):
    """Ordre voulu (avec les séparateurs qui EXISTENT)."""
    out = list(others)
    for g in (0, 1, 2):
        if not groups[g]:
            continue
        if seps.get(g):
            out.append(seps[g])
        out.extend(groups[g])
    return out


async def _apply_order(guild, category, desired):
    current = list(category.text_channels)
    if [c.id for c in current] == [c.id for c in desired]:
        return 0
    positions = sorted(c.position for c in current)
    payload = []
    for i, ch in enumerate(desired):
        if i < len(positions) and ch.position != positions[i]:
            payload.append({"id": ch.id, "position": positions[i]})
    if not payload:
        return 0
    try:
        await guild._state.http.bulk_channel_update(
            guild.id, payload, reason="Tri VA (liens/activité)")
    except Exception:
        for i, ch in enumerate(desired):
            try:
                await ch.move(category=category, beginning=True, offset=i)
            except Exception:
                pass
    return len(payload)


async def sort_guild(guild, create_seps=True) -> tuple:
    """Trie toutes les catégories avec des salons VA. -> (cats_modifiées, moves)"""
    cats = moves = 0
    for cat in guild.categories:
        others, groups, seps = _split(cat)
        n_vas = sum(len(v) for v in groups.values())
        if n_vas < 1:
            # plus de VA : retire les séparateurs orphelins
            for ch in list(seps.values()):
                try:
                    await ch.delete(reason="Plus de salons VA ici")
                except Exception:
                    pass
            continue
        sep_changed = await _sync_separators(guild, cat, groups, seps, allow_create=create_seps)
        desired = _desired(others, groups, seps)
        n = await _apply_order(guild, cat, desired)
        if n or sep_changed:
            cats += 1
            moves += n
    return cats, moves


class VASort(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_sort.start()

    def cog_unload(self):
        if self.auto_sort.is_running():
            self.auto_sort.cancel()

    @tasks.loop(minutes=20)
    async def auto_sort(self):
        for g in self.bot.guilds:
            try:
                await sort_guild(g)
            except Exception as e:
                print(f"[vasort] {g.name}: {e}", flush=True)

    @auto_sort.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="rangerva",
        description="Range les salons VA : séparateurs + liens en haut, puis 0 clic, puis 🟢🟠🔴",
    )
    @app_commands.describe(
        confirmer="Laisse vide = APERÇU (rien n'est déplacé). Mets True = range pour de vrai.",
    )
    async def rangerva(self, interaction: discord.Interaction, confirmer: bool = False):
        perms = getattr(interaction.user, "guild_permissions", None)
        if not (perms and perms.manage_channels):
            await interaction.response.send_message(
                "Il faut la permission « Gérer les salons ».", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not confirmer:
            # ---- APERÇU : montre le nouvel ordre, sans rien créer ni déplacer ----
            blocks = []
            for cat in interaction.guild.categories:
                others, groups, seps = _split(cat)
                if sum(len(v) for v in groups.values()) < 1:
                    continue
                # position actuelle (hors séparateurs) pour marquer ce qui bougerait
                cur_wo = [c for c in cat.text_channels if not _is_sep(c.name)]
                pos = {c.id: i for i, c in enumerate(cur_wo)}
                des_idx = 0
                rows = [f"\n📂 **{cat.name}**"]
                for c in others:
                    rows.append(f"▫️ {c.name}")
                    des_idx += 1
                for g in (0, 1, 2):
                    if not groups[g]:
                        continue
                    tag = "" if seps.get(g) else " _(sera créé)_"
                    rows.append(f"➖ `{SEP_BY_GROUP[g]}`{tag}")
                    for c in groups[g]:
                        mark = "🔀" if pos.get(c.id) != des_idx else "▫️"
                        rows.append(f"{mark} {c.name}")
                        des_idx += 1
                blocks.append("\n".join(rows))
            if not blocks:
                await interaction.followup.send("Aucune catégorie avec des salons VA.", ephemeral=True)
                return
            header = ("👀 **APERÇU — rien n'est déplacé ni créé.**\n"
                      "Séparateurs visibles STAFF uniquement (boss/manager/admin).\n")
            footer = "\n\nSi c'est bon : `/rangerva confirmer:True`"
            text = header + "\n".join(blocks) + footer
            chunks, buf = [], ""
            for line in text.split("\n"):
                if len(buf) + len(line) + 1 > 1900:
                    chunks.append(buf)
                    buf = line
                else:
                    buf += ("\n" if buf else "") + line
            if buf:
                chunks.append(buf)
            for c in chunks[:6]:
                await interaction.followup.send(c, ephemeral=True)
            return

        try:
            cats, moves = await sort_guild(interaction.guild)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return
        if not cats:
            await interaction.followup.send(
                "✅ Tout est déjà dans le bon ordre (séparateurs + 🔗 → 🔗⚙️ → 🟢🟠🔴).",
                ephemeral=True)
        else:
            await interaction.followup.send(
                f"✅ **{cats}** catégorie(s) rangée(s) ({moves} salon(s) déplacé(s)).\n"
                "Séparateurs staff-only en place. Le tri se refait tout seul toutes les 20 min.",
                ephemeral=True)


async def setup(bot):
    await bot.add_cog(VASort(bot))
