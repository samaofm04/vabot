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


#: Le nom public : les cogs spoofer, telechargement, numeros et user s'en servent.
serveur_outils = _serveur_outils


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


def _tickets() -> set:
    """Les salons va- des VA (users.json), toutes guildes confondues."""
    try:
        from cogs.welcome import load_users
        return {int((e or {}).get("channel_id") or 0)
                for e in (load_users() or {}).values() if isinstance(e, dict)}
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] users.json illisible : {type(e).__name__}: {e}")
        return set()


def ou_livrer(canal, membre):
    """Ou livrer un outil lance sur le serveur FR -- LA regle des trois outils.

    Depuis le ticket d'un VA (les boutons de son menu) : ce ticket, meme
    clique par un manager qui l'aide. Ailleurs -- le salon commun, un menu
    central, un salon public : le ticket du membre, ou None s'il n'en a pas.
    Jamais un salon que d'autres voient."""
    cible = _ticket_vise(canal, membre)
    if cible is not None and not _ticket_permis(cible):
        return None
    return cible


def _ticket_vise(canal, membre):
    """Le ticket ou livrer, identite non regardee (ou_livrer, refus)."""
    if (canal is not None and not est_salon_outils(canal)
            and int(getattr(canal, "id", 0) or 0) in _tickets()):
        return canal
    return salon_perso(getattr(canal, "guild", None), membre)


#: Les MODELS dont les VA ont les outils. Proprietaire, 03/10/2026 : « les
#: meufs de OF Julia, Amelia, Lola [...] uniquement, on fait par demande » ;
#: « c'est uniquement models, pas d'identite » -- Emma, Sarah et Alicia, les
#: identites du serveur FR, n'en ont pas. Dans le code, une model est une
#: identite (users.json « identity », sa categorie de tickets).
MODELS_OUTILS = frozenset({"julia", "amelia", "lola"})


def identite_permise(identite) -> bool:
    return str(identite or "").strip().lower() in MODELS_OUTILS


def identite_du_ticket(canal) -> str:
    """L'identite du VA a qui est ce ticket (users.json), ou ""."""
    try:
        from cogs.welcome import load_users
        cid = int(getattr(canal, "id", 0) or 0)
        for e in (load_users() or {}).values():
            if isinstance(e, dict) and int(e.get("channel_id") or 0) == cid:
                return str(e.get("identity") or "")
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] users.json illisible : {type(e).__name__}: {e}")
    return ""


#: La phrase du refus, la meme pour tous les outils.
SANS_SALON = "Tu n'as pas de salon VA sur ce serveur : rien ne peut t'être livré."
PAS_ENCORE = "🔒 Les outils ne sont pas encore ouverts pour ta model."


def models_du_ticket(canal) -> list:
    """Les models du VA a qui est ce ticket : celle de sa fiche, plus celles
    de ses roles (serveur FR, plusieurs roles = plusieurs models)."""
    out = []
    ident = identite_du_ticket(canal)
    if ident:
        out.append(ident.strip().lower())
    try:
        from cogs.welcome import load_users, models_du_membre
        cid = int(getattr(canal, "id", 0) or 0)
        uid = next((u for u, e in (load_users() or {}).items()
                    if isinstance(e, dict) and int(e.get("channel_id") or 0) == cid), None)
        g = getattr(canal, "guild", None)
        m = g.get_member(int(uid)) if (g is not None and uid) else None
        out += [x for x in (models_du_membre(m) if m is not None else []) if x not in out]
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] models du ticket : {type(e).__name__}: {e}")
    return out


def _ticket_permis(cible) -> bool:
    return any(identite_permise(m) for m in models_du_ticket(cible))


def refus(canal, membre) -> str:
    """"" si l'outil peut servir ce clic, sinon la phrase a dire au VA.
    Chaque outil la dit AVANT de travailler : un spoof ou un numero ne se
    paie pas pour etre refuse a la livraison."""
    cible = _ticket_vise(canal, membre)
    if cible is None:
        return SANS_SALON
    if not _ticket_permis(cible):
        return PAS_ENCORE
    return ""


def _role_verifie(guilde):
    """✅ Verifie si le serveur exige la verification (verif_discord, « porte »)."""
    try:
        import verif_discord as vd
        c = vd.serveur(str(guilde.id)) or {}
        if c.get("porte") and c.get("role_verifie"):
            return guilde.get_role(int(c["role_verifie"]))
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] verification illisible : {type(e).__name__}: {e}")
    return None


def _droits(guilde, moi):
    """Tout le monde voit, personne n'ecrit ; le bot pose ses panneaux. Sur
    un serveur a verification, « tout le monde » = ✅ Verifie : un nouveau
    non verifie ne voit que le salon de verification."""
    voir = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=False,
        add_reactions=False, create_public_threads=False,
        create_private_threads=False, send_messages_in_threads=False)
    verifie = _role_verifie(guilde)
    if verifie is not None:
        droits = {guilde.default_role: discord.PermissionOverwrite(view_channel=False),
                  verifie: voir}
    else:
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
            # un role de model a chaque VA qui a une fiche et aucun role
            # (fiches faites par /adduser, VA d'avant les roles)
            try:
                await self._roles_models(guilde)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] roles de model : {type(e).__name__}: {e}")
            # le message « Se vérifier » : pose par le bot de la verification
            # (Luigi), pas par celui-ci -- le clic irait a la mauvaise application
            try:
                import verif_discord as vd
                etat = await asyncio.to_thread(vd.assurer_message_verif, str(guilde.id))
                if etat not in ("deja", "pas de salon de verification"):
                    print(f"[outils] message de verification de {guilde.name} : {etat}")
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] message de verification : {type(e).__name__}: {e}")

    @_entretien.before_loop
    async def _avant(self):
        await self.bot.wait_until_ready()

    async def _roles_models(self, guilde) -> int:
        wcog = self.bot.get_cog("Welcome")
        if wcog is None or not hasattr(wcog, "donner_role_model"):
            return 0
        from cogs.welcome import load_users
        n = 0
        for uid, e in (load_users() or {}).items():
            if not isinstance(e, dict) or not e.get("identity"):
                continue
            m = guilde.get_member(int(uid)) if str(uid).isdigit() else None
            if m is not None and not m.bot and await wcog.donner_role_model(m, e["identity"]):
                n += 1
                await asyncio.sleep(0.5)
        if n:
            print(f"[outils] {guilde.name} : {n} role(s) de model pose(s)")
        return n

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
