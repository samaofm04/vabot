# -*- coding: utf-8 -*-
"""La categorie « 🧰 Outils » du serveur FR : un salon par outil, commun a tous.

POURQUOI (demande du proprietaire, 03/10/2026)
    Les outils des dossiers US (spoofer, telechargement, numeros) sur Va IG. Un
    dossier par VA y coute 6 salons : 160 VA = 960 salons, Discord plafonne
    a 500 par serveur. Le proprietaire : « le meme channel pour tout le
    monde [...] chacun ne voit pas ce qu'il fait a l'interieur ».

CE QUI RESTE PRIVE
    Le panneau est commun. Un clic recoit sa reponse en ephemere (seul le VA
    la voit) et les FICHIERS partent dans SON salon va- (users.json) : un
    ephemere disparait au rechargement de Discord, le VA perdrait ce qu'il
    vient de demander. Sans salon a lui sur ce serveur, l'outil refuse :
    livrer dans le salon commun montrerait ses fichiers a tout le monde.

CE QUI N'EST PAS ICI
    Aucune commande slash : le bot principal en a 100 sur 100. Les panneaux
    et leurs boutons restent ceux de cogs/spoofer.py et cogs/telechargement.py,
    qui demandent a ce module ou livrer (salon_perso).
"""
from __future__ import annotations

import asyncio

import discord
from discord.ext import commands, tasks

#: Les serveurs qui ont la categorie Outils : Va IG (marche FR). Le serveur
#: US garde ses dossiers par VA.
SERVEURS = frozenset({1505418484052394004})

CATEGORIE = "🧰 Outils"
#: (cle, nom a la creation). La cle est le nom sans decor : le proprietaire
#: renomme les salons a la main (« ⬇️・all-download »), un salon renomme doit
#: rester reconnu.
#: « ・ » et pas « - » dans le nom du salon des numeros : « 📱-numero-mail »
#: finirait par « -numero-mail », le suffixe des salons PRIVES d'un VA US, et
#: /panelnumeroall le cacherait a tout le monde.
SALONS = (("spoofer", "📤・spoofer"), ("download", "⬇️・download"),
          ("numero-mail", "📱・numero-mail"))


def _norm(nom) -> str:
    try:
        from cogs.welcome import nom_sans_decor
        return nom_sans_decor(nom)
    except Exception:
        return str(nom or "").strip().lower()


def _serveur_outils(guilde) -> bool:
    return int(getattr(guilde, "id", 0) or 0) in SERVEURS


def est_categorie_outils(cat) -> bool:
    return (cat is not None and _serveur_outils(getattr(cat, "guild", None))
            and _norm(getattr(cat, "name", "")) == _norm(CATEGORIE))


def est_salon_outils(canal, outil: str = None) -> bool:
    """Un salon commun de la categorie Outils (de cet outil, si precise)."""
    if canal is None or not est_categorie_outils(getattr(canal, "category", None)):
        return False
    return outil is None or _norm(getattr(canal, "name", "")) == outil


def salon_perso(guilde, membre):
    """Le salon va- du membre sur ce serveur (users.json), ou None.

    Jamais un salon de la categorie Outils : y livrer rendrait public ce que
    le VA vient de demander."""
    if guilde is None or membre is None:
        return None
    try:
        from cogs.welcome import load_users
        entree = (load_users() or {}).get(str(getattr(membre, "id", "")))
        cid = int((entree or {}).get("channel_id") or 0)
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] users.json illisible : {type(e).__name__}: {e}")
        return None
    canal = guilde.get_channel(cid) if cid else None
    if not isinstance(canal, discord.TextChannel) or est_salon_outils(canal):
        return None
    return canal


#: La phrase du refus, la meme pour tous les outils.
SANS_SALON = "Tu n'as pas de salon VA sur ce serveur : rien ne peut t'être livré."


def _droits(guilde, moi):
    """Tout le monde voit, personne n'ecrit ; le bot pose ses panneaux."""
    voir = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=False,
        add_reactions=False, create_public_threads=False,
        create_private_threads=False, send_messages_in_threads=False)
    droits = {guilde.default_role: voir}
    if moi is not None:
        droits[moi] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            manage_messages=True, embed_links=True, attach_files=True)
    return droits


def _rendre_visible_aux_futurs_va(ids) -> None:
    """Les salons s'ajoutent aux « salons d'aide » de l'isolation : sinon un
    VA qui arrive est masque de TOUS les salons (anonymat) et ne verrait
    jamais les outils."""
    try:
        from cogs.welcome import load_welcome_config, save_welcome_config
        cfg = load_welcome_config()
        deja = [int(x) for x in cfg.get("extra_visible_channel_ids", []) or []]
        manquants = [i for i in ids if i not in deja]
        if manquants:
            cfg["extra_visible_channel_ids"] = deja + manquants
            save_welcome_config(cfg)
            print(f"[outils] {len(manquants)} salon(s) ajoute(s) aux salons visibles des VA")
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] salons non ajoutes a l'isolation : {type(e).__name__}: {e}")


class Outils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self._entretien.start()

    async def cog_unload(self):
        self._entretien.cancel()

    @tasks.loop(hours=24)
    async def _entretien(self):
        for guilde in list(getattr(self.bot, "guilds", []) or []):
            if not _serveur_outils(guilde):
                continue
            try:
                await self.assurer(guilde)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] {getattr(guilde, 'name', '?')} : {type(e).__name__}: {e}")

    @_entretien.before_loop
    async def _avant(self):
        await self.bot.wait_until_ready()

    async def assurer(self, guilde) -> dict:
        """La categorie, ses salons et leurs panneaux. Idempotent : ce qui
        existe et est a jour n'est pas touche. Rend un bilan."""
        bilan = {"crees": [], "panneaux": 0}
        moi = guilde.me
        cat = discord.utils.find(est_categorie_outils, guilde.categories)
        if cat is None:
            cat = await guilde.create_category(
                CATEGORIE, overwrites=_droits(guilde, moi),
                reason="Outils communs des VA (spoofer, telechargement)")
            bilan["crees"].append(cat.name)
        salons = {}
        for cle, nom in SALONS:
            canal = discord.utils.find(
                lambda c, k=cle: _norm(c.name) == k, cat.text_channels)
            if canal is None:
                canal = await guilde.create_text_channel(
                    nom, category=cat, overwrites=_droits(guilde, moi),
                    reason="Outils communs des VA")
                bilan["crees"].append(canal.name)
                await asyncio.sleep(1.0)
            salons[cle] = canal
        _rendre_visible_aux_futurs_va([c.id for c in salons.values()])

        spf = self.bot.get_cog("Spoofer")
        if spf is not None:
            bilan["panneaux"] += await spf.assurer_panneau(salons["spoofer"])
        else:
            print("[outils] cog Spoofer absent : panneau du spoofer non pose")
        dl = self.bot.get_cog("Telechargement")
        if dl is not None:
            from cogs import telechargement as tl
            canal = salons["download"]
            moi_id = getattr(getattr(self.bot, "user", None), "id", 0)
            du_bot = [m async for m in canal.history(limit=25) if m.author.id == moi_id]
            if not (len(du_bot) == 1 and tl.panneau_a_jour(du_bot[0], moi_id)):
                bilan["panneaux"] += await tl.poser_panneaux(dl, canal)
        else:
            print("[outils] cog Telechargement absent : panneau du download non pose")
        # Le panneau des numeros est pose par le bot ADMIN (cogs/numeros.py,
        # _panneau_commun) : c'est lui qui porte le module des numeros.
        if bilan["crees"] or bilan["panneaux"]:
            print(f"[outils] {guilde.name} : crees {bilan['crees']}, "
                  f"{bilan['panneaux']} panneau(x) pose(s)")
        return bilan


async def setup(bot):
    await bot.add_cog(Outils(bot))
