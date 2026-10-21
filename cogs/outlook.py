# -*- coding: utf-8 -*-
"""cogs/outlook.py — le coffre d'adresses Outlook sur Discord (Va IG).

POURQUOI (demande du proprietaire) : il garde SES adresses Outlook sur le site ;
un VA en demande une depuis le salon #adresse-outlook, son manager (a cote de
lui) valide, et le bot depose alors l'adresse + le mot de passe dans le TICKET
du VA. Le code 2FA se tire a la demande, en ephemere, avec le bouton. Le secret
2FA (« le code a 13 chiffres ») ne sort JAMAIS — ni vers Discord ni vers la page.

Sur le bot ADMIN (Peach) : c'est lui qui porte numeros et qui voit les salons
VA de Va IG. Le salon n'est pas cherche par id mais par nom nettoye finissant
par « adresse-outlook » (le proprietaire renomme a la main : emoji, « ・ »…),
comme numeros/outils reperent leurs salons (cogs/welcome.nom_sans_decor).

Deux vues PERSISTANTES (enregistrees dans cog_load pour repondre apres un
redemarrage) :
  - le PANNEAU (un seul message par salon, entretenu par une boucle, comme
    numeros._panneau_commun) : « 📧 Demander une adresse » et « 🔐 Code 2FA » ;
  - la CARTE de validation : « ✅ Valider » / « ❌ Refuser », reservees aux
    managers. L'etat de la demande ne vit PAS dans la vue mais dans un fichier
    (data/outlook_demandes.json, clef = id du message), comme les bilans de
    sessionsvoc : un clic apres redemarrage retrouve ainsi sa demande.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import discord
from discord.ext import commands, tasks

import outlook_comptes as oc
import safe_json

log = logging.getLogger("vabot.outlook")

#: Va IG (serveur FR) et son role manager : LU dans verif_discord.py, pas
#: recopie. La copie d'ici etait restee sur BOSS (1505821464375328798) quand
#: verif_discord est passe a 🛡️ Manager le 17/10/2026 : un vrai manager de
#: Va IG ne pouvait pas valider, et la carte sonnait le mauvais role. BOSS
#: passe toujours, par ses droits d'administrateur (_est_manager).
VA_IG_ID = 1505418484052394004


def _role_manager() -> int:
    try:
        import verif_discord
        return int(verif_discord.SERVEURS_EXTRA[verif_discord.VA_IG_ID]["role_manager"])
    except Exception as e:                                   # noqa: BLE001
        log.warning("outlook: role manager de verif_discord illisible (%s: %s) — "
                    "🛡️ Manager par defaut", type(e).__name__, e)
        return 1555968604032213102


ROLE_MANAGER = _role_manager()
#: Le salon est repere par son nom nettoye finissant ainsi (renommable a la main).
SUFFIXE_SALON = "adresse-outlook"
#: Fenetre d'historique balayee pour retrouver/deduire les panneaux, comme
#: numeros (FENETRE_PANNEAU) : assez large pour un salon ou l'on a ecrit.
FENETRE_PANNEAU = 200
#: Les custom_id qui identifient un panneau Outlook de CE bot.
CID_PANNEAU = ("outlook:demander", "outlook:2fa")

DATA_DIR = Path("data")
USERS_FILE = DATA_DIR / "users.json"
PANNEAUX_FILE = DATA_DIR / "outlook_panneaux.json"
DEMANDES_FILE = DATA_DIR / "outlook_demandes.json"

SANS_MENTION = discord.AllowedMentions.none()

TEXTE_PANNEAU = (
    "## \U0001F4E7 Adresses Outlook\n"
    "Besoin d'une adresse Outlook ? Clique sur « Demander une "
    "adresse » : ton manager valide, puis l'adresse et le mot de passe "
    "arrivent dans ton ticket.\n"
    "Pour ton code de connexion : « \U0001F510 Code 2FA »."
)


# ---- Reperage des salons et des managers ------------------------------------

def _nom_sans_decor(nom) -> str:
    """Le nom de salon nettoye. On reutilise le meme nettoyage que les autres
    salons VA (welcome.nom_sans_decor) : un salon renomme a la main (emoji,
    « ・ », tiret iPhone) doit rester reconnu."""
    try:
        from cogs.welcome import nom_sans_decor
        return nom_sans_decor(nom)
    except Exception:                                        # noqa: BLE001
        return str(nom or "").strip().lower()


def _est_salon_outlook(channel) -> bool:
    """Un salon texte de Va IG dont le nom nettoye finit par « adresse-outlook »."""
    g = getattr(channel, "guild", None)
    if g is None or int(getattr(g, "id", 0) or 0) != VA_IG_ID:
        return False
    if not isinstance(channel, discord.TextChannel):
        return False
    return _nom_sans_decor(getattr(channel, "name", "")).endswith(SUFFIXE_SALON)


def est_panneau_outlook(msg, moi) -> bool:
    """Vrai si `msg` est un panneau Outlook de CE bot : meme auteur, et il porte
    les boutons du panneau (custom_id outlook:demander / outlook:2fa).

    Sert a RETROUVER un panneau hors registre (data/ du VPS reparti de zero) et
    a retirer les doublons, comme numeros.est_panneau_numero : le registre seul
    ne suffit pas, sinon un panneau de plus s'empilait a chaque redemarrage."""
    if msg is None:
        return False
    auteur = getattr(msg, "author", None)
    if moi is not None and getattr(auteur, "id", None) != moi:
        return False
    for comp in getattr(msg, "components", None) or []:
        # Un bouton peut etre pose a plat ou dans une ActionRow (.children) :
        # on lit les deux pour ne rater aucun format rendu par Discord.
        if getattr(comp, "custom_id", None) in CID_PANNEAU:
            return True
        for enfant in getattr(comp, "children", None) or []:
            if getattr(enfant, "custom_id", None) in CID_PANNEAU:
                return True
    return False


def _est_manager(membre) -> bool:
    """Manager de Va IG : porte le role manager, OU a les droits serveur
    (administrateur / gestion des roles). Adapte de verif_discord._est_manager
    a un discord.Member."""
    perms = getattr(membre, "guild_permissions", None)
    if perms is not None and (getattr(perms, "administrator", False)
                              or getattr(perms, "manage_roles", False)):
        return True
    for r in getattr(membre, "roles", None) or []:
        try:
            if int(getattr(r, "id", 0) or 0) == ROLE_MANAGER:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _ticket_channel_id(uid):
    """Le salon ticket du VA (data/users.json[uid]["channel_id"]), ou None.

    Le bot admin ne charge pas cogs/welcome : on relit le fichier nous-memes,
    sans jamais planter dessus (illisible -> None, journalise)."""
    try:
        if not USERS_FILE.exists():
            return None
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        log.warning("outlook: users.json illisible (%s: %s)", type(e).__name__, e)
        return None
    rec = (data or {}).get(str(uid))
    if not isinstance(rec, dict):
        return None
    try:
        cid = int(rec.get("channel_id") or 0)
    except (TypeError, ValueError):
        return None
    return cid or None


# ---- Registre des panneaux et des demandes (ecritures atomiques) ------------

def _panneaux() -> dict:
    d = safe_json.load(PANNEAUX_FILE, default={})
    return d if isinstance(d, dict) else {}


def _panneau_ecrire(cid, mid) -> None:
    d = _panneaux()
    if mid is None:
        d.pop(str(cid), None)
    else:
        d[str(cid)] = int(mid)
    PANNEAUX_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(PANNEAUX_FILE, d):
        raise OSError("%s non ecrit" % PANNEAUX_FILE.name)


def _demandes() -> dict:
    d = safe_json.load(DEMANDES_FILE, default={})
    return d if isinstance(d, dict) else {}


def _demande_ecrire(mid, rec) -> None:
    d = _demandes()
    if rec is None:
        d.pop(str(mid), None)
    else:
        d[str(mid)] = rec
    DEMANDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(DEMANDES_FILE, d):
        raise OSError("%s non ecrit" % DEMANDES_FILE.name)


# ---- Vues persistantes ------------------------------------------------------

class PanneauOutlook(discord.ui.View):
    """Le panneau du salon #adresse-outlook : deux boutons, aucun reserve."""

    def __init__(self, cog=None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Demander une adresse", emoji="\U0001F4E7",
                       style=discord.ButtonStyle.success, custom_id="outlook:demander")
    async def demander(self, itx: discord.Interaction, button):
        cog = self.cog or itx.client.get_cog("OutlookCog")
        if cog is None:
            raise RuntimeError("OutlookCog absent de ce bot")
        await cog.demander(itx)

    @discord.ui.button(label="Code 2FA", emoji="\U0001F510",
                       style=discord.ButtonStyle.secondary, custom_id="outlook:2fa")
    async def code2fa(self, itx: discord.Interaction, button):
        cog = self.cog or itx.client.get_cog("OutlookCog")
        if cog is None:
            raise RuntimeError("OutlookCog absent de ce bot")
        await cog.code_2fa(itx)


class CarteValidation(discord.ui.View):
    """La carte « untel demande une adresse » : Valider / Refuser, aux managers.

    L'etat (quel VA) vit dans data/outlook_demandes.json, clef = id du message :
    le clic n'a rien a lire dans la vue, un redemarrage ne le perd pas."""

    def __init__(self, cog=None):
        super().__init__(timeout=None)
        self.cog = cog

    async def interaction_check(self, itx: discord.Interaction) -> bool:
        if _est_manager(itx.user):
            return True
        await itx.response.send_message("Réservé aux managers.",
                                        ephemeral=True, allowed_mentions=SANS_MENTION)
        return False

    @discord.ui.button(label="Valider", emoji="✅",
                       style=discord.ButtonStyle.success, custom_id="outlook:ok")
    async def valider(self, itx: discord.Interaction, button):
        cog = self.cog or itx.client.get_cog("OutlookCog")
        if cog is None:
            raise RuntimeError("OutlookCog absent de ce bot")
        await cog.valider(itx)

    @discord.ui.button(label="Refuser", emoji="❌",
                       style=discord.ButtonStyle.danger, custom_id="outlook:non")
    async def refuser(self, itx: discord.Interaction, button):
        cog = self.cog or itx.client.get_cog("OutlookCog")
        if cog is None:
            raise RuntimeError("OutlookCog absent de ce bot")
        await cog.refuser(itx)


class OutlookCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._dernier_log_absent = None

    async def cog_load(self):
        # Vues persistantes : les clics d'un message deja poste trouvent leur
        # repondant apres un redemarrage (le cron du VPS redemarre le bot a
        # chaque push).
        for vue in (PanneauOutlook(self), CarteValidation(self)):
            try:
                self.bot.add_view(vue)
            except Exception as e:                           # noqa: BLE001
                log.error("outlook: vue %s non enregistree (%s: %s) — ses boutons "
                          "ne repondront plus apres un redemarrage",
                          type(vue).__name__, type(e).__name__, e)
        try:
            self._entretien.start()
        except Exception as e:                               # noqa: BLE001
            log.error("outlook: boucle du panneau non lancee (%s: %s)",
                      type(e).__name__, e)

    async def cog_unload(self):
        self._entretien.cancel()

    # ---- Entretien du panneau ----------------------------------------------
    @tasks.loop(minutes=30)
    async def _entretien(self):
        """Garantit UN panneau dans chaque salon #adresse-outlook de Va IG.

        Aucun salon trouve : on le dit UNE fois par jour (sinon le journal se
        remplit toutes les 30 min), et on ne fait rien d'autre."""
        vus = 0
        for g in list(getattr(self.bot, "guilds", []) or []):
            if int(getattr(g, "id", 0) or 0) != VA_IG_ID:
                continue
            for c in list(getattr(g, "text_channels", []) or []):
                if not _est_salon_outlook(c):
                    continue
                vus += 1
                try:
                    await self._assurer_panneau(c)
                except Exception as e:                       # noqa: BLE001
                    log.exception("outlook: panneau de #%s (%s: %s)",
                                  getattr(c, "name", "?"), type(e).__name__, e)
        if vus == 0:
            self._signaler_absence()

    def _signaler_absence(self):
        jour = time.strftime("%Y-%m-%d")
        if self._dernier_log_absent == jour:
            return
        self._dernier_log_absent = jour
        log.info("outlook: aucun salon #%s sur Va IG — panneau non pose", SUFFIXE_SALON)

    @_entretien.before_loop
    async def _avant_entretien(self):
        await self.bot.wait_until_ready()
        # laisser les salons se charger apres la connexion
        await asyncio.sleep(30)

    async def _panneaux_du_salon(self, channel, moi) -> list:
        """Tous les panneaux Outlook de CE bot dans le salon, du plus recent au
        plus ancien. Un seul passage d'historique sert a la fois a en retrouver
        un hors registre et a lister les doublons a retirer (idiome numeros)."""
        trouves = []
        try:
            async for m in channel.history(limit=FENETRE_PANNEAU):
                if est_panneau_outlook(m, moi):
                    trouves.append(m)
        except Exception as e:                               # noqa: BLE001
            log.warning("outlook: historique de #%s illisible (%s: %s) — doublons "
                        "non balayes", getattr(channel, "name", "?"),
                        type(e).__name__, e)
        return trouves

    async def _assurer_panneau(self, channel):
        """Garantit UN panneau, jamais deux. Le registre seul ne suffit pas :
        sur le VPS, data/ repart de zero a chaque push alors que le message du
        panneau, lui, survit dans le salon. On consulte donc aussi l'historique
        pour reutiliser un panneau deja la (sinon on en empilait un de plus a
        chaque redemarrage), et on balaie les doublons — comme numeros."""
        moi = getattr(getattr(self.bot, "user", None), "id", None)
        garder = None
        mid = _panneaux().get(str(channel.id))
        if mid:
            try:
                await channel.fetch_message(int(mid))
                garder = int(mid)                            # le panneau connu est la
            except discord.NotFound:
                _panneau_ecrire(channel.id, None)            # il a disparu : on l'oublie
            except Exception as e:                           # noqa: BLE001
                log.warning("outlook: panneau de #%s illisible (%s: %s) — rien n'est "
                            "repose", getattr(channel, "name", "?"), type(e).__name__, e)
                return
        # Panneaux deja presents dans le salon (sert au repli ET au menage).
        panneaux = await self._panneaux_du_salon(channel, moi)
        if garder is None and panneaux:
            # Le registre ne sait rien (data/ reparti de zero) mais un panneau
            # est bien la : on le reprend plutot que d'en poster un second.
            garder = panneaux[0].id
            _panneau_ecrire(channel.id, garder)
            log.info("outlook: panneau %s retrouve dans #%s hors registre",
                     garder, getattr(channel, "name", "?"))
        if garder is None:
            try:
                msg = await channel.send(TEXTE_PANNEAU, view=PanneauOutlook(self),
                                         allowed_mentions=SANS_MENTION)
            except Exception as e:                           # noqa: BLE001
                log.warning("outlook: panneau non pose dans #%s (%s: %s)",
                            getattr(channel, "name", "?"), type(e).__name__, e)
                return
            garder = msg.id
            _panneau_ecrire(channel.id, garder)
            log.info("outlook: panneau pose dans #%s (message %s)",
                     getattr(channel, "name", "?"), garder)
        await self._balayer_doublons(channel, panneaux, garder)

    async def _balayer_doublons(self, channel, panneaux, garder) -> None:
        """Retire tout AUTRE panneau Outlook du bot : un doublon laisse par un
        redemarrage ou data/ avait ete perdu garderait ses boutons actifs."""
        vires = 0
        for m in panneaux:
            if getattr(m, "id", None) == garder:
                continue
            try:
                await m.delete()
                vires += 1
                await asyncio.sleep(0.3)
            except discord.NotFound:
                pass
            except Exception as e:                           # noqa: BLE001
                log.warning("outlook: doublon %s de #%s non supprime (%s: %s)",
                            getattr(m, "id", "?"), getattr(channel, "name", "?"),
                            type(e).__name__, e)
        if vires:
            log.info("outlook: %d panneau(x) Outlook en double retire(s) de #%s",
                     vires, getattr(channel, "name", "?"))

    # ---- Boutons ------------------------------------------------------------
    async def demander(self, itx: discord.Interaction):
        uid = itx.user.id
        if oc.compte_de_uid(uid) is not None:
            await itx.response.send_message(
                "Tu as déjà une adresse Outlook. Clique sur "
                "« \U0001F510 Code 2FA » pour ton code.",
                ephemeral=True, allowed_mentions=SANS_MENTION)
            return
        if not oc.nb_libres():
            # Coffre vide : la carte sonnait un manager qui ne pouvait rien
            # valider, et le VA attendait sans savoir pourquoi.
            await itx.response.send_message(oc.TEXTE_COFFRE_VIDE + " Reviens plus tard.",
                                            ephemeral=True, allowed_mentions=SANS_MENTION)
            await self._coffre_vide(uid)
            return
        # Une demande de ce VA attend deja un manager : ne pas reposter de
        # carte. Sans ca, 5 clics = 5 cartes = 5 pings du role manager (le
        # proprietaire ne veut pas de bruit dans les salons).
        for _rec in _demandes().values():
            if (str(_rec.get("uid")) == str(uid)
                    and _rec.get("statut") in ("attente", "en_cours")):
                await itx.response.send_message(
                    "Ta demande est déjà en attente : un manager doit la valider.",
                    ephemeral=True, allowed_mentions=SANS_MENTION)
                return
        contenu = ("<@&%d> \U0001F575️ <@%d> demande une adresse Outlook"
                   % (ROLE_MANAGER, uid))
        # On ne notifie QUE le role manager : le <@VA> est affiche mais ne sonne pas.
        am = discord.AllowedMentions(roles=[discord.Object(id=ROLE_MANAGER)],
                                     users=False, everyone=False)
        try:
            carte = await itx.channel.send(contenu, view=CarteValidation(self),
                                           allowed_mentions=am)
        except Exception as e:                               # noqa: BLE001
            log.warning("outlook: carte de demande non postee dans #%s (%s: %s)",
                        getattr(itx.channel, "name", "?"), type(e).__name__, e)
            await itx.response.send_message(
                "Impossible d'envoyer la demande au manager pour le moment.",
                ephemeral=True, allowed_mentions=SANS_MENTION)
            return
        _demande_ecrire(carte.id, {
            "uid": str(uid),
            "va": getattr(itx.user, "display_name", str(uid)),
            "channel_id": str(getattr(itx, "channel_id", "") or getattr(itx.channel, "id", "")),
            "statut": "attente",
        })
        await itx.response.send_message("Demande envoyée au manager.",
                                        ephemeral=True, allowed_mentions=SANS_MENTION)
        log.info("outlook: demande de %s (%s) dans #%s",
                 getattr(itx.user, "display_name", "?"), uid,
                 getattr(itx.channel, "name", "?"))

    def _vue_figee(self):
        vue = CarteValidation(self)
        for enfant in vue.children:
            try:
                enfant.disabled = True
            except Exception:                                # noqa: BLE001
                pass
        return vue

    async def valider(self, itx: discord.Interaction):
        rec = _demandes().get(str(itx.message.id))
        if not rec or rec.get("statut") != "attente":
            await itx.response.send_message(
                "Cette demande n'est plus en attente.",
                ephemeral=True, allowed_mentions=SANS_MENTION)
            return
        # Fermer la fenetre AVANT tout await : deux managers (a cote du VA) qui
        # cliquent « Valider » sur la meme carte dans la meme seconde passaient
        # tous deux le test « attente » (il y a un await reseau avant l'ecriture
        # de l'etat), et l'adresse + le mot de passe etaient livres DEUX fois
        # dans le ticket. On marque « en_cours » de facon SYNCHRONE : le second
        # clic lit alors != « attente » et tombe sur le message ci-dessus.
        _demande_ecrire(itx.message.id, {**rec, "statut": "en_cours"})
        uid = rec.get("uid")
        va = rec.get("va") or "?"
        compte, etat = oc.attribuer(uid, va)
        if compte is None:
            # Aucune adresse libre : la demande RESTE a traiter -> on la remet en
            # « attente » pour qu'un manager puisse reessayer quand une se libere.
            _demande_ecrire(itx.message.id, {**rec, "statut": "attente"})
            await itx.response.send_message(
                oc.TEXTE_COFFRE_VIDE + " La demande reste en attente : valide-la quand "
                "une adresse aura été ajoutée.",
                ephemeral=True, allowed_mentions=SANS_MENTION)
            log.warning("outlook: validation de %s refusee — aucune adresse libre "
                        "(manager %s)", uid, getattr(itx.user, "id", "?"))
            await self._coffre_vide(uid)
            return
        try:
            import outlook_x_discord
            await asyncio.to_thread(outlook_x_discord.suivre_coffre, str(uid))
        except Exception as e:                               # noqa: BLE001
            log.warning("outlook: suivi du coffre en echec (%s: %s)", type(e).__name__, e)
        livre, pourquoi = await self._livrer(uid, compte)
        manager = getattr(itx.user, "display_name", "?")
        txt = "✅ Attribuée à %s · validé par %s" % (va, manager)
        if not livre:
            # L'attribution est deja ecrite : rien n'est perdu. On le DIT sur la
            # carte et au journal, et le VA peut encore tirer son code 2FA.
            txt += ("\n⚠️ Livraison dans le ticket impossible (%s) : "
                    "à remettre à la main." % pourquoi)
        _demande_ecrire(itx.message.id, {**rec, "statut": "validee",
                                         "compte": compte.get("id")})
        await itx.response.edit_message(content=txt, view=self._vue_figee(),
                                        allowed_mentions=SANS_MENTION)
        # On ne journalise NI le seed NI le mot de passe : seulement l'id du compte.
        log.info("outlook: %s a attribué le compte %s à %s (%s) ; "
                 "livraison=%s", manager, compte.get("id"), va, uid, livre)

    async def refuser(self, itx: discord.Interaction):
        rec = _demandes().get(str(itx.message.id))
        manager = getattr(itx.user, "display_name", "?")
        await itx.response.edit_message(
            content="❌ Refusé par %s" % manager,
            view=self._vue_figee(), allowed_mentions=SANS_MENTION)
        if rec:
            _demande_ecrire(itx.message.id, {**rec, "statut": "refusee"})
        log.info("outlook: %s a refusé une demande (message %s)",
                 manager, getattr(itx.message, "id", "?"))

    async def code_2fa(self, itx: discord.Interaction):
        compte = oc.compte_de_uid(itx.user.id)
        if compte is None:
            await itx.response.send_message(
                "Tu n'as pas encore d'adresse — fais la demande.",
                ephemeral=True, allowed_mentions=SANS_MENTION)
            return
        texte, _code, _reste = oc.texte_2fa(compte)
        await itx.response.send_message(texte, ephemeral=True,
                                        allowed_mentions=SANS_MENTION)
        log.info("outlook: code 2FA fourni à %s pour le compte %s",
                 getattr(itx.user, "id", "?"), compte.get("id"))

    async def _coffre_vide(self, uid):
        """Journal + staff prevenu une fois : la meme alerte que Twitter
        (outlook_x_discord.coffre_vide), c'est le meme coffre."""
        try:
            import outlook_x_discord
            await asyncio.to_thread(outlook_x_discord.coffre_vide, str(uid))
        except Exception as e:                               # noqa: BLE001
            log.warning("outlook: coffre vide, alerte au staff en echec (%s: %s)",
                        type(e).__name__, e)

    async def _livrer(self, uid, compte):
        """Depose adresse + mot de passe (JAMAIS le seed) dans le ticket du VA.
        Rend (True, "") ou (False, raison) — l'attribution reste ecrite quoi
        qu'il arrive, et chaque echec est journalise, jamais avale."""
        cid = _ticket_channel_id(uid)
        if not cid:
            log.warning("outlook: ticket introuvable pour %s — email/mdp non livres", uid)
            return False, "ticket introuvable"
        ch = self.bot.get_channel(int(cid))
        if ch is None:
            log.warning("outlook: salon ticket %s introuvable pour ce bot (uid %s)", cid, uid)
            return False, "salon introuvable"
        try:
            am = discord.AllowedMentions(users=[discord.Object(id=int(uid))],
                                         roles=False, everyone=False)
            await ch.send("<@%s>\n%s" % (uid, oc.texte_livraison(compte)),
                          allowed_mentions=am)
            return True, ""
        except Exception as e:                               # noqa: BLE001
            log.warning("outlook: livraison impossible dans le ticket %s (%s: %s)",
                        cid, type(e).__name__, e)
            return False, type(e).__name__


async def setup(bot):
    await bot.add_cog(OutlookCog(bot))
