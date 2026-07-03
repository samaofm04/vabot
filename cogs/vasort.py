"""cogs/vasort.py — Range les salons VA dans chaque catégorie par "qui travaille".

Ordre (du haut vers le bas), à l'intérieur de chaque catégorie :
  1. 🔗 VA avec lien qui tourne (pas de ⚙️)      — les 🟢 d'abord, puis 🟠, 🔴
  2. 🔗⚙️ VA avec lien à 0 clic (3 j)            — pareil 🟢 → 🔴
  3. VA sans lien                                 — 🟢 → 🟠 → 🔴 → sans rond
Égalité -> ordre alphabétique du pseudo (stable).

Les salons non-VA de la catégorie (général-X, banger-X, exemple-compte-X…)
restent au-dessus, dans leur ordre actuel.

Auto : re-tri toutes les 20 min (uniquement si l'ordre a changé -> 1 seul
appel API bulk par catégorie). Manuel : /rangerva.
"""
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

_VA_RE = re.compile(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$")
DOT_RANK = {"🟢": 0, "🟠": 1, "🔴": 2}


def _va_handle(name):
    m = _VA_RE.search((name or "").lower())
    return m.group(1) if m else None


def _sort_key(name: str):
    """(groupe, rond, pseudo) — plus petit = plus haut dans la catégorie."""
    n = name or ""
    handle = _va_handle(n) or ""
    idx = n.lower().find("va-")
    prefix = n[:idx] if idx > 0 else ""
    dot = DOT_RANK.get(n[:1], 3)
    has_link = "🔗" in prefix
    has_gear = "⚙" in prefix
    if has_link and not has_gear:
        group = 0     # lien qui tourne
    elif has_link:
        group = 1     # lien mais 0 clic
    else:
        group = 2     # pas de lien
    return (group, dot, handle)


def _desired_order(category):
    """Liste des salons texte dans l'ordre voulu, ou None si rien à trier."""
    txts = list(category.text_channels)  # déjà triés par position
    vas = [c for c in txts if _va_handle(c.name)]
    if len(vas) < 2:
        return None
    others = [c for c in txts if not _va_handle(c.name)]
    vas_sorted = sorted(vas, key=lambda c: _sort_key(c.name))
    desired = others + vas_sorted
    return None if desired == txts else desired


async def _apply_order(guild, category, desired):
    """Réordonne en UN appel bulk (fallback: move un par un)."""
    current = list(category.text_channels)
    positions = sorted(c.position for c in current)
    payload = []
    for i, ch in enumerate(desired):
        if ch.position != positions[i]:
            payload.append({"id": ch.id, "position": positions[i]})
    if not payload:
        return 0
    try:
        await guild._state.http.bulk_channel_update(
            guild.id, payload, reason="Tri VA (liens/activité)")
    except Exception:
        # Fallback : déplacements individuels (plus lent mais sûr)
        for i, ch in enumerate(desired):
            try:
                await ch.move(category=category, beginning=True, offset=len(
                    [c for c in desired[:i]]))
            except Exception:
                pass
    return len(payload)


async def sort_guild(guild) -> tuple:
    """Trie toutes les catégories contenant des salons VA. -> (cats, moves)"""
    cats = moves = 0
    for cat in guild.categories:
        desired = _desired_order(cat)
        if not desired:
            continue
        n = await _apply_order(guild, cat, desired)
        if n:
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
        description="Range les salons VA : liens en haut, puis liens 0 clic, puis 🟢🟠🔴",
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
            # ---- APERÇU : montre le nouvel ordre, sans rien déplacer ----
            blocks = []
            for cat in interaction.guild.categories:
                desired = _desired_order(cat)
                if not desired:
                    continue
                current = list(cat.text_channels)
                rows = [f"\n📂 **{cat.name}**"]
                for i, ch in enumerate(desired):
                    mark = "🔀" if current.index(ch) != i else "▫️"
                    rows.append(f"{mark} {ch.name}")
                blocks.append("\n".join(rows))
            if not blocks:
                await interaction.followup.send(
                    "✅ Tout est déjà dans le bon ordre (🔗 → 🔗⚙️ → 🟢🟠🔴) — rien à déplacer.",
                    ephemeral=True)
                return
            header = ("👀 **APERÇU — rien n'est déplacé.** Nouvel ordre "
                      "(🔀 = salon qui bougerait) :\n")
            footer = ("\n\nSi c'est bon : `/rangerva confirmer:True`\n"
                      "_(le tri auto toutes les 20 min appliquera aussi cet ordre)_")
            text = header + "\n".join(blocks) + footer
            # Discord = 2000 chars max par message -> on découpe
            chunks, buf = [], ""
            for line in text.split("\n"):
                if len(buf) + len(line) + 1 > 1900:
                    chunks.append(buf)
                    buf = line
                else:
                    buf += ("\n" if buf else "") + line
            if buf:
                chunks.append(buf)
            for c in chunks[:5]:
                await interaction.followup.send(c, ephemeral=True)
            return

        # ---- EXÉCUTION ----
        try:
            cats, moves = await sort_guild(interaction.guild)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return
        if not cats:
            await interaction.followup.send(
                "✅ Tout est déjà dans le bon ordre (🔗 → 🔗⚙️ → 🟢🟠🔴).", ephemeral=True)
        else:
            await interaction.followup.send(
                f"✅ **{cats}** catégorie(s) rangée(s) ({moves} salon(s) déplacé(s)).\n"
                "Ordre : 🔗 lien actif → 🔗⚙️ lien 0 clic → 🟢 → 🟠 → 🔴. "
                "Le tri se refait tout seul toutes les 20 min.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(VASort(bot))
