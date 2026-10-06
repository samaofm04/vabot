# -*- coding: utf-8 -*-
"""Le salon admin « bases-identites » du serveur US : une base GetMySocial par identite.

POURQUOI (proprietaire, 06/10/2026)
    « Avoir une base et juste changer les PP et la photo c'est tout. » Il
    poste le nom d'une identite US et deux photos ; le bot cree la page
    « TEMPLATE <identite> » dans GetMySocial (bases_identite_us.py) et
    repond son adresse, seule, pour qu'elle se copie d'un appui long.

CE QUE LE SALON ATTEND (un message d'administrateur)
    @Yoshi ibenhaastrup      1re ligne : l'identite
    Iben ♡                   2e ligne, facultative : le nom affiche sur la page
    + 2 photos               la 1re = photo de profil, la 2e = fond
    @Yoshi liste             les identites US : ✅ base faite, ➖ pas encore

    Reponse : ⏳ sur son message, puis ✅ et l'adresse seule, ou ❌ et la
    raison en une ligne. Aucun texte d'explication dans le salon, aucun
    message epingle : le proprietaire n'en veut pas.

POURQUOI IL FAUT MENTIONNER LE BOT
    Yoshi n'a pas l'intention « Message Content » : la demander dans le code
    sans la cocher dans le portail Discord empeche le bot de se connecter du
    tout (main.py, PrivilegedIntentsRequired). Sans elle, Discord livre les
    messages SANS texte ni pieces jointes -- sauf ceux qui mentionnent le
    bot. Un message vide est donc relu une fois par l'API (utile le jour ou
    l'intention sera cochee dans le portail) ; s'il l'est toujours, le bot le
    dit au lieu de se taire.

CE QUI N'EST PAS ICI
    Aucune commande slash : le bot principal en a 100 sur 100, une de plus
    fait echouer la synchronisation de tout l'arbre.
"""
from __future__ import annotations

import asyncio
import functools
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands, tasks

import bases_identite_us as bases

SALON_DEFAUT = "bases-identites"
#: Mentions d'utilisateur ou de role : le role gere du bot sort aussi de
#: l'autocompletion « @Yoshi ».
_MENTION = re.compile(r"<@[!&]?\d+>")
IMAGES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".bmp", ".tif", ".tiff"})
LIMITE_MESSAGE = 2000


# ───────────────────────────────────────────────────────────── le salon ──

def _norm(nom) -> str:
    """LA cle des salons du serveur US (welcome.nom_sans_decor) : le
    proprietaire decore les noms a la main (« 🧱・bases-identites »).
    nom_sans_decor ne retire que la decoration DE TETE et garde les accents :
    « bases-identités » ou « bases-identites-🧱 » rendaient le salon sourd,
    puis l'entretien en creait un second au redemarrage."""
    try:
        from cogs.welcome import nom_sans_decor
        n = nom_sans_decor(nom)
    except Exception:                                        # noqa: BLE001
        n = str(nom or "").strip().lower()
    n = "".join(c for c in unicodedata.normalize("NFKD", n) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+$", "", n)


def nom_salon() -> str:
    try:
        return bases.config().get("salon") or SALON_DEFAUT
    except Exception:                                        # noqa: BLE001
        return SALON_DEFAUT


def est_salon_bases(canal) -> bool:
    nom = getattr(canal, "name", "") or ""
    return bool(nom) and _norm(nom) == _norm(nom_salon())


def _serveur_us(guilde) -> bool:
    try:
        import guild_features as gf
        return gf.is_us_guild(guilde)
    except Exception:                                        # noqa: BLE001
        return False


def _est_admin(membre) -> bool:
    perms = getattr(membre, "guild_permissions", None)
    return bool(perms is not None and getattr(perms, "administrator", False))


#: Ce dont le bot a besoin dans le salon.
DROITS_BOT = dict(view_channel=True, send_messages=True, read_message_history=True,
                  add_reactions=True, embed_links=True, attach_files=True)
#: Sans l'un d'eux, le salon est sourd ou muet pour le bot.
DROITS_VITAUX = ("view_channel", "send_messages", "add_reactions", "read_message_history")


def droits_salon(guilde) -> Dict[Any, discord.PermissionOverwrite]:
    """Personne ne le voit, sauf le bot ; les administrateurs voient tout
    salon quoi qu'il arrive."""
    droits = {guilde.default_role: discord.PermissionOverwrite(view_channel=False)}
    moi = getattr(guilde, "me", None)
    if moi is not None:
        droits[moi] = discord.PermissionOverwrite(**DROITS_BOT)
    return droits


def _esc(texte) -> str:
    """Les noms tels quels a l'ecran : deux identites a « __ » soulignaient
    tout ce qui les separait, et « nanas__nyspam » se lisait « nanasnyspam »."""
    return discord.utils.escape_markdown(str(texte or ""))


# ─────────────────────────────────────────────────────────── identites ──

def identites_us() -> List[str]:
    """Les identites US, EXACTEMENT celles du menu US (cogs/user) : deux
    listes qui decident la meme chose finissent par diverger (CLAUDE.md)."""
    try:
        from cogs.user import _jb_models_marche
        noms = list(_jb_models_marche("us") or [])
        if noms:
            return sorted(noms, key=str.lower)
        print("[bases] menu US vide : repli sur le marche des dossiers", flush=True)
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases] menu US illisible ({type(e).__name__}: {e}) : repli sur le "
              "marche des dossiers", flush=True)
    try:
        import marche
        from cogs.welcome import list_identities
        try:
            from cogs.user import EXCLURE_MENU
        except Exception:                                    # noqa: BLE001
            EXCLURE_MENU = {"jessye"}
        return sorted((n for n in list_identities()
                       if marche.de(n) == "us" and n.strip().lower() not in EXCLURE_MENU),
                      key=str.lower)
    except Exception as e:                                   # noqa: BLE001
        print(f"[bases] identites US illisibles : {type(e).__name__}: {e}", flush=True)
        return []


# ─────────────────────────────────────────────────────────── le message ──

def lire_demande(texte: str) -> Dict[str, Any]:
    """{liste, identite, nom_affiche, erreur} d'apres le texte du message."""
    lignes = [l.strip() for l in _MENTION.sub(" ", texte or "").splitlines() if l.strip()]
    d = {"liste": False, "identite": "", "nom_affiche": None, "erreur": ""}
    if len(lignes) == 1 and lignes[0].lower() == "liste":
        d["liste"] = True
        return d
    if not lignes:
        d["erreur"] = "Écris le nom de l'identité avec les 2 photos."
        return d
    if len(lignes) > 2:
        d["erreur"] = "2 lignes au plus : l'identité, puis le nom affiché."
        return d
    d["identite"] = lignes[0].lstrip("@").strip()
    d["nom_affiche"] = lignes[1] if len(lignes) > 1 else None
    return d


def _est_image(piece) -> bool:
    ct = str(getattr(piece, "content_type", "") or "").lower()
    if ct.startswith("image/"):
        return True
    nom = str(getattr(piece, "filename", "") or "").lower()
    return any(nom.endswith(ext) for ext in IMAGES)


def erreur_pieces(pieces) -> str:
    """"" si on a exactement deux images, sinon la phrase a dire."""
    n = len(pieces)
    if n == 0:
        return "Il manque les 2 photos : la 1re = photo de profil, la 2e = fond."
    if n == 1:
        return "Une seule photo : il en faut 2 (la 1re = photo de profil, la 2e = fond)."
    if n > 2:
        return f"{n} pièces jointes : il en faut exactement 2 (la 1re = photo de profil, la 2e = fond)."
    for p in pieces:
        if not _est_image(p):
            return f"« {getattr(p, 'filename', '?')} » n'est pas une image."
    return ""


def textes_liste(identites: List[str], faites, raison: str = "") -> List[str]:
    """La liste ✅/➖ en messages de 2000 signes au plus, coupes entre deux
    lignes, dans l'ordre alphabetique de identites. `faites` : les identites
    qui ont une base (cles, ou un registre {identite: ...}). `raison` : la
    liste de l'equipe n'a pas pu etre lue -- dit en tete."""
    faites = {bases.cle(k) for k in (faites or ())}
    lignes = [("✅ " if bases.cle(n) in faites else "➖ ") + _esc(n) for n in identites]
    if not lignes:
        return ["Aucune identité US."]
    if raison:
        lignes.insert(0, f"⚠️ GetMySocial illisible ({_esc(raison)[:200]}) : d'après le registre du bot")
    morceaux, cour = [], ""
    for l in lignes:
        if cour and len(cour) + 1 + len(l) > LIMITE_MESSAGE:
            morceaux.append(cour)
            cour = l
        else:
            cour = f"{cour}\n{l}" if cour else l
    if cour:
        morceaux.append(cour)
    return morceaux


_SANS_MENTION = discord.AllowedMentions.none()


class BasesIdentite(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        #: une creation a la fois par identite (deux envois en rafale)
        self.en_cours = set()
        #: serveurs dont les ⏳ laisses par un redemarrage ont ete repris
        self.repris = set()

    async def cog_load(self):
        try:
            if not self._entretien.is_running():
                self._entretien.start()
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] entretien non lance : {e}", flush=True)

    async def cog_unload(self):
        try:
            self._entretien.cancel()
        except Exception:                                    # noqa: BLE001
            pass

    # ------------------------------------------------------------ le salon --

    async def assurer_salon(self, guilde):
        """Le salon prive, cree s'il manque. Un salon deja la (decore ou non,
        deplace dans une categorie) est garde ; seuls les droits du bot y sont
        reposes s'ils manquent."""
        if getattr(guilde, "unavailable", False) or getattr(guilde, "me", None) is None:
            # GUILD_CREATE pas encore recu (panne Discord, demarrage lent) :
            # aucun salon visible, et le creer donnait un doublon que le bot
            # lui-meme ne voyait pas
            print(f"[bases] serveur {getattr(guilde, 'id', '?')} indisponible : salon vérifié plus tard",
                  flush=True)
            return None
        existant = discord.utils.find(est_salon_bases, list(getattr(guilde, "text_channels", []) or []))
        if existant is not None:
            await self._verifier_droits(existant, guilde)
            return existant
        try:
            canal = await guilde.create_text_channel(
                nom_salon(), overwrites=droits_salon(guilde),
                reason="Bases GetMySocial des identites US")
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] salon {nom_salon()} non cree sur {getattr(guilde, 'name', '?')} : "
                  f"{type(e).__name__}: {e}", flush=True)
            return None
        print(f"[bases] salon #{canal.name} cree sur {getattr(guilde, 'name', '?')}", flush=True)
        return canal

    async def _verifier_droits(self, canal, guilde) -> None:
        """Un salon fait a la main dans une categorie reservee a un role, ou
        « Synchroniser les permissions » apres un deplacement : le bot ne le
        voit plus. Discord ne lui livre alors AUCUN message de ce salon -- ni
        ⏳, ni ❌, rien. On repose ses droits ; on dit si on ne peut pas."""
        moi = guilde.me
        try:
            p = canal.permissions_for(moi)
            manque = [d for d in DROITS_VITAUX if not getattr(p, d, False)]
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] droits du bot dans #{getattr(canal, 'name', '?')} illisibles : {e}", flush=True)
            manque = []
        if manque:
            try:
                await canal.set_permissions(moi, reason="Bases GetMySocial : le bot doit lire ce salon",
                                            **DROITS_BOT)
                print(f"[bases] #{canal.name} : droits du bot reposés ({', '.join(manque)} manquaient)",
                      flush=True)
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] #{canal.name} : le bot n'a pas {', '.join(manque)} et ne peut pas se "
                      f"les donner ({type(e).__name__}: {e}) — donner l'accès au bot à la main",
                      flush=True)
        try:
            if canal.permissions_for(guilde.default_role).view_channel:
                print(f"[bases] ATTENTION : #{canal.name} est visible de @everyone — les adresses "
                      "et la liste y sont lisibles par tous", flush=True)
        except Exception:                                    # noqa: BLE001
            pass

    async def _reprendre_interrompus(self, canal) -> int:
        """Au demarrage : un ⏳ du bot sans ✅ ni ❌, c'est une creation tuee par
        un redemarrage (le cron redemarre le bot a chaque push). Sans ca, ⏳
        restait affiche pour toujours, sans un mot."""
        # une creation en cours dans CE processus (rechargement du cog) n'est
        # pas interrompue : on ne touche alors a rien
        if not bases._VERROU.acquire(blocking=False):
            return 0
        bases._VERROU.release()
        n = 0
        try:
            async for m in canal.history(limit=50):
                miennes = {str(r.emoji) for r in (getattr(m, "reactions", None) or [])
                           if getattr(r, "me", False)}
                if "⏳" not in miennes or miennes & {"✅", "❌"}:
                    continue
                n += 1
                ident = lire_demande(getattr(m, "content", "") or "").get("identite") or ""
                await self._reagir(m, "❌", retirer="⏳")
                await self._dire(canal, "❌ " + (f"{_esc(ident)} : " if ident else "")
                                 + "interrompu par un redémarrage du bot — renvoie-le "
                                   "(une page créée entre-temps sera coupée)", reference=m)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] reprise des ⏳ de #{getattr(canal, 'name', '?')} : {type(e).__name__}: {e}",
                  flush=True)
        return n

    @tasks.loop(hours=24)
    async def _entretien(self):
        for guilde in list(getattr(self.bot, "guilds", []) or []):
            if not _serveur_us(guilde):
                continue
            try:
                canal = await self.assurer_salon(guilde)
                if canal is not None and guilde.id not in self.repris:
                    self.repris.add(guilde.id)
                    await self._reprendre_interrompus(canal)
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] salon de {getattr(guilde, 'name', '?')} : {type(e).__name__}: {e}",
                      flush=True)

    @_entretien.before_loop
    async def _avant_entretien(self):
        await self.bot.wait_until_ready()

    # --------------------------------------------------------- les messages --

    @commands.Cog.listener()
    async def on_message(self, message):
        auteur = getattr(message, "author", None)
        if auteur is None or getattr(auteur, "bot", False):
            return
        if getattr(message, "type", discord.MessageType.default) not in (
                discord.MessageType.default, discord.MessageType.reply):
            return
        guilde = getattr(message, "guild", None)
        if guilde is None or not _serveur_us(guilde):
            return
        if not est_salon_bases(getattr(message, "channel", None)):
            return
        if not _est_admin(auteur):
            return
        try:
            await self.traiter(message)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] message {getattr(message, 'id', '?')} : {type(e).__name__}: {e}", flush=True)
            # ⏳ a pu etre pose : sans le retirer, ⏳ et ❌ restaient cote a cote
            await self._reagir(message, "❌", retirer="⏳")
            await self._dire(message.channel, f"❌ {type(e).__name__}: {e}"[:LIMITE_MESSAGE])

    async def _contenu(self, message) -> Tuple[str, list]:
        texte = message.content or ""
        pieces = list(getattr(message, "attachments", None) or [])
        if texte.strip() or pieces:
            return texte, pieces
        # Vide : l'intention Message Content manque (voir l'en-tete). L'API
        # rend le contenu si elle est cochee dans le portail.
        try:
            m2 = await message.channel.fetch_message(message.id)
            return (m2.content or ""), list(getattr(m2, "attachments", None) or [])
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] message {getattr(message, 'id', '?')} non relu : {type(e).__name__}: {e}",
                  flush=True)
            return "", []

    async def _reagir(self, message, emoji: str, retirer: Optional[str] = None) -> None:
        if retirer:
            try:
                moi = getattr(getattr(message, "guild", None), "me", None) or self.bot.user
                await message.remove_reaction(retirer, moi)
            except Exception as e:                           # noqa: BLE001
                print(f"[bases] reaction {retirer} non retiree : {e}", flush=True)
        try:
            await message.add_reaction(emoji)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] reaction {emoji} non posee : {e}", flush=True)

    async def _dire(self, canal, texte: str, **kw) -> None:
        try:
            await canal.send(texte, allowed_mentions=_SANS_MENTION, **kw)
        except Exception as e:                               # noqa: BLE001
            print(f"[bases] message non envoye dans #{getattr(canal, 'name', '?')} : {e}", flush=True)

    async def _echec(self, message, texte: str) -> None:
        await self._reagir(message, "❌")
        await self._dire(message.channel, f"❌ {texte}"[:LIMITE_MESSAGE])

    async def traiter(self, message) -> None:
        texte, pieces = await self._contenu(message)
        canal = message.channel
        if not texte.strip() and not pieces:
            moi = getattr(getattr(self.bot, "user", None), "mention", "") or "@Yoshi"
            # « @Yoshi » propose aussi le ROLE gere du bot : sa mention ne
            # livre pas le message, et « mentionne-moi » laissait croire
            # qu'on l'avait fait. mention_roles arrive meme sans l'intention.
            role = getattr(getattr(message, "guild", None), "self_role", None)
            if role is not None and any(getattr(r, "id", None) == role.id
                                        for r in (getattr(message, "role_mentions", None) or [])):
                await self._echec(message, f"Tu as mentionné le rôle @{_esc(role.name)}, pas le bot : "
                                           f"mentionne le membre {moi} + le nom + les 2 photos.")
                return
            await self._echec(message, f"Je ne lis ce salon que si tu me mentionnes : {moi} + le nom + les 2 photos.")
            return
        d = lire_demande(texte)
        loop = asyncio.get_running_loop()
        if d["liste"]:
            noms = await loop.run_in_executor(None, identites_us)
            # la verite du module VA (pages « TEMPLATE x » de l'equipe, meme
            # faites a la main), pas le seul registre du bot
            faites, raison = await loop.run_in_executor(None, bases.etat_liste)
            for t in textes_liste(noms, faites, raison):
                await self._dire(canal, t)
            return
        if d["erreur"]:
            await self._echec(message, d["erreur"])
            return
        err = erreur_pieces(pieces)
        if err:
            await self._echec(message, err)
            return
        noms = await loop.run_in_executor(None, identites_us)
        if not noms:
            await self._echec(message, "Liste des identités US illisible (menu US vide).")
            return
        if not bases.trouver(d["identite"], noms):
            # avant ⏳ et le telechargement : c'est une faute de frappe, la
            # reponse doit etre immediate (creer_base refait la meme verification)
            p = bases.proches(d["identite"], noms)
            await self._echec(message, f"« {_esc(d['identite'])} » n'est pas une identité US"
                              + (f". Proches : {', '.join(_esc(x) for x in p)}" if p else "."))
            return
        cle = bases.cle(d["identite"])
        if cle in self.en_cours:
            await self._echec(message, f"« {_esc(d['identite'])} » est déjà en cours.")
            return
        self.en_cours.add(cle)
        try:
            await self._reagir(message, "⏳")
            try:
                pp, fond = await pieces[0].read(), await pieces[1].read()
            except Exception as e:                           # noqa: BLE001
                await self._reagir(message, "❌", retirer="⏳")
                await self._dire(canal, f"❌ Photos non téléchargées depuis Discord ({type(e).__name__}).")
                return
            par = f"{getattr(message.author, 'name', '?')} ({getattr(message.author, 'id', '?')})"
            # requests et PIL bloquent : jamais sur la boucle du bot
            res = await loop.run_in_executor(None, functools.partial(
                bases.creer_base, d["identite"], pp, fond,
                nom_affiche=d["nom_affiche"], par=par, identites=noms))
            if res.get("ok"):
                await self._reagir(message, "✅", retirer="⏳")
                # l'adresse SEULE : un appui long sur telephone copie tout le
                # message ; et sans apercu, qui doublerait le message
                await self._dire(canal, res["url"], suppress_embeds=True)
                if res.get("avertissement"):
                    await self._dire(canal, f"⚠️ {_esc(res['avertissement'])}"[:LIMITE_MESSAGE])
            else:
                await self._reagir(message, "❌", retirer="⏳")
                await self._dire(canal, f"❌ {_esc(res.get('erreur') or 'échec sans raison')}"[:LIMITE_MESSAGE])
        finally:
            self.en_cours.discard(cle)


async def setup(bot):
    await bot.add_cog(BasesIdentite(bot))
