# -*- coding: utf-8 -*-
"""Telechargement d'un compte Instagram, depuis un panneau Discord.

OU CA VIT
    Chaque VA a un salon <pseudo>-download (cree par /ticketsall, voir
    cogs/welcome.py) qui porte DEUX panneaux permanents :

        « Telechargement - le compte »    Changer de compte. Le compte actif
                                          (au plus N publications, 30 par
                                          defaut, 200 au plus) est affiche.
        « Telechargement - les options »  Tout, Photo de profil, Bio,
                                          Posts photo, Reels, Top reels.

    /menudownload les repose a la main dans un salon.

OU PARTENT LES FICHIERS
    Dans <pseudo>-content : le salon -download ne porte que les panneaux, y
    deverser des dizaines de fichiers les repousserait hors de vue.

    Et une COPIE de chaque envoi dans « all-download », sur le meme serveur,
    precedee de « 📥 @VA · @compte · option · date heure de Paris ». Demande
    du proprietaire (26/09/2026) : savoir qui fait quoi, quand, et « surtout
    stocker les videos de mon cote ». La mention est AFFICHEE sans notifier
    personne. Sans ce salon, la livraison au VA continue (journalise une fois).

L'ORDRE D'ENVOI, TOUJOURS LE MEME

        1. la photo de profil
        2. la bio
        3. les publications PHOTO (un carrousel part en entier), avec leur description
        4. les REELS, avec leur description

    L'identite du compte arrive donc AVANT son contenu : le salon se lit de
    haut en bas, et sans cela on ne sait plus a qui appartiennent les fichiers
    qui defilent. Chaque fichier part DES QU'IL EST PRET, jamais en lot a la
    fin : un compte qui disparait en cours de route laisse tout ce qui est
    deja passe.

D'OU VIENNENT LES DONNEES
    HikerAPI SEULEMENT, par hiker_medias.py. Plus d'Apify (ecarte par le
    proprietaire), plus de session Instagram (aucun cookie n'est plus lu ni
    ecrit ici), plus de yt-dlp (il ne savait pas descendre une photo : « Posts
    photo » echouait a tous les coups). Les listes sont gardees 24 h et les
    fichiers par shortcode : ce qui a deja ete telecharge repart SANS depenser
    de credit, et le bilan de chaque demande dit ce qu'elle a coute.

CE QUI EST GARDE SUR LE DISQUE
    data/telechargement_choix.json   le compte actif de chaque VA (il survit
                                     a un redemarrage, comme l'embed qui
                                     l'affiche)
    data/telechargement_hiker.json   la reserve HikerAPI du jour (300 requetes)
    data/telechargement/             listes (24 h) et fichiers (purges apres
                                     30 jours sans redemande)
"""
from __future__ import annotations

import asyncio
import os
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

import safe_json

#: Le SEUL serveur ou /menudownload est proposee. Anna est sur plusieurs
#: serveurs, mais le telechargement ne concerne que celui-ci : la commande
#: n'est donc pas seulement refusee ailleurs, elle n'y est pas proposee du tout.
#:
#: On passe par un identifiant et non par un nom : il survit a un renommage.
#:     Youl4b        1535758943324999711
#:     YouLab AGENCY 1505418484052394004  (volontairement exclu)
SERVEUR_ID = int(os.getenv("IG_SERVEUR_ID") or "1535758943324999711")

_RACINE = Path(__file__).resolve().parents[1]

#: Le compte actif de chaque VA. Il vivait en memoire : chaque redemarrage
#: (un par deploiement) le perdait alors que l'embed l'affichait encore, et
#: le VA qui cliquait « Reels » lisait « Entre d'abord un compte » sous un
#: panneau qui lui montrait son compte.
CHOIX_FILE = _RACINE / "data" / "telechargement_choix.json"

#: L'ancien fichier Netscape fabrique depuis IG_SESSIONID par la voie cookies :
#: un identifiant de session en clair, dans un dossier que .gitignore ne
#: couvrait pas. Il n'est plus produit ; celui qui reste est retire au
#: chargement du cog.
_ANCIEN_COOKIE = _RACINE / "downloads" / "cookies_sessionid.txt"

#: Le salon d'archive du proprietaire, cherche par nom NORMALISE (tirets
#: sosies, majuscules) : un salon cree a la main depuis un iPhone ressemble au
#: notre sans etre egal caractere pour caractere.
NOM_ARCHIVE = "all-download"

#: Limite d'un fichier quand le serveur ne la donne pas : 10 Mio, celle d'un
#: serveur sans boost (et au boost 1). Le seuil etait 24,5 Mo en dur : au-dela
#: de 10 Mio, Discord repondait 413, une exception NON attrapee qui coupait la
#: livraison au milieu du compte.
LIMITE_DEFAUT = 10 * 1024 * 1024
#: Ce que l'enveloppe multipart et le texte ajoutent au fichier.
_MARGE_ENVOI = 256 * 1024
#: Discord n'accepte pas plus de dix pieces jointes par message.
_MAX_PAR_MESSAGE = 10

#: Pause entre deux publications : on reste sous la limite de debit de
#: Discord (5 messages / 5 s par salon) au lieu de la heurter. Pendant qu'il
#: attendait derriere ses propres messages, le bot ne servait plus aucune
#: interaction dans les trois secondes (constate le 27/08).
PAUSE_ENTRE_POSTS = 1.0

#: Un pseudo Instagram : lettres, chiffres, point et tiret bas, 30 au plus.
#: Sans ce controle, "#" ou une URL mal collee passait, et le bot annoncait
#: « Compte retenu : @# » avant d aller interroger un compte inexistant.
_PSEUDO_OK = re.compile(r"^[A-Za-z0-9._]{1,30}$")

#: {bouton: (libelle court pour l'archive, libelle long pour le VA)}
OPTIONS = {
    "tout": ("Tout", "tout"),
    "pp": ("Photo de profil", "la photo de profil"),
    "bio": ("Bio", "la bio"),
    "photos": ("Posts photo", "les posts photo"),
    "reels": ("Reels", "les reels"),
    "top": ("Top reels", "les reels les plus vus"),
}


# ───────────────────────────────────────────────────── compte retenu ──

def charger_choix(chemin=None) -> dict:
    """{id Discord: (pseudo, combien)} relu du disque.

    Une entree illisible est COMPTEE et dite dans le journal, pas ecartee en
    silence : un VA dont le compte « disparait » doit pouvoir etre explique.
    """
    brut = safe_json.load(chemin or CHOIX_FILE, default={})
    out, ecartes = {}, 0
    for cle, v in (brut.items() if isinstance(brut, dict) else []):
        try:
            uid = int(cle)
            pseudo = str((v or {}).get("pseudo") or "")
            n = max(1, min(int((v or {}).get("combien") or 30), 200))
        except (TypeError, ValueError, AttributeError):
            ecartes += 1
            continue
        if not _PSEUDO_OK.match(pseudo):
            ecartes += 1
            continue
        out[uid] = (pseudo, n)
    if ecartes:
        print(f"[telechargement] {ecartes} compte(s) retenu(s) illisible(s) "
              f"dans {Path(chemin or CHOIX_FILE).name}, ignore(s)")
    return out


# ─────────────────────────────────────────────────────────── salons ──

def _norm(nom) -> str:
    try:
        from cogs.welcome import _us_norm
        return _us_norm(nom)
    except Exception:
        return str(nom or "").strip().lower()


def salon_reserve(canal) -> bool:
    """Vrai pour un salon de service (« all-download »…), jamais un ticket."""
    nom = getattr(canal, "name", "") or ""
    try:
        from cogs.welcome import salon_de_service
        return salon_de_service(nom)
    except Exception:
        return _norm(nom).startswith("all-")


def salon_de_livraison(canal):
    """Ou les fichiers atterrissent : le salon -content du meme VA.

    Le salon -download ne porte que les deux panneaux ; y deverser des dizaines
    de fichiers les repousserait hors de vue. Le contenu genere vit deja dans
    -content, les telechargements l y rejoignent.

    Si le salon jumeau n existe pas, on reste sur place plutot que de perdre
    les fichiers.
    """
    nom = getattr(canal, "name", "") or ""
    if not _norm(nom).endswith("-download"):
        return canal
    vise = _norm(nom)[: -len("-download")] + "-content"
    guilde = getattr(canal, "guild", None)
    if guilde is None:
        return canal
    for c in guilde.text_channels:
        if _norm(c.name) == vise:
            return c
    return canal


#: Serveurs dont l'absence du salon d'archive a deja ete journalisee : une
#: ligne par serveur, pas une par fichier.
_ARCHIVE_ABSENTE = set()


def salon_all_download(guilde):
    """Le salon « all-download » du serveur, ou None (journalise une fois)."""
    if guilde is None:
        return None
    for c in getattr(guilde, "text_channels", []) or []:
        if _norm(c.name) == NOM_ARCHIVE:
            _ARCHIVE_ABSENTE.discard(getattr(guilde, "id", 0))
            return c
    gid = getattr(guilde, "id", 0)
    if gid not in _ARCHIVE_ABSENTE:
        _ARCHIVE_ABSENTE.add(gid)
        print(f"[telechargement] aucun salon « {NOM_ARCHIVE} » sur "
              f"{getattr(guilde, 'name', gid)} : les telechargements partent "
              f"au VA seulement, sans copie")
    return None


def _heure_paris() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


# ─────────────────────────────────────────────────────────── envoi ──

def _limite(canal) -> int:
    """Ce que CE serveur accepte par fichier (10 Mio sans boost)."""
    try:
        lim = int(getattr(getattr(canal, "guild", None), "filesize_limit", 0) or 0)
    except (TypeError, ValueError):
        lim = 0
    return lim or LIMITE_DEFAUT


def _taille(p) -> int:
    try:
        return Path(p).stat().st_size
    except OSError:
        return 0


def repartir(chemins, limite: int):
    """Range les fichiers en messages : (lots, trop_lourds).

    Au plus dix fichiers par message, et un total sous la limite du serveur
    (un carrousel de dix photos lourdes depassait sinon a lui seul). Un
    fichier plus lourd que la limite ne part pas : il sera donne en lien.
    """
    plafond = max(1, int(limite) - _MARGE_ENVOI)
    lots, lot, cumul, lourds = [], [], 0, []
    for p in chemins:
        t = _taille(p)
        if t > plafond:
            lourds.append(p)
            continue
        if lot and (len(lot) >= _MAX_PAR_MESSAGE or cumul + t > plafond):
            lots.append(lot)
            lot, cumul = [], 0
        lot.append(p)
        cumul += t
    if lot:
        lots.append(lot)
    return lots, lourds


async def _poster(canal, contenu: str = "", chemins=(), sans_ping: bool = False):
    """Un message, qui ne leve JAMAIS : (envoye, trop_lourd, erreur).

    Un envoi rate (413, permission, coupure) ne doit pas interrompre la
    livraison : le reste du compte a le droit de partir.
    """
    kw = {}
    if contenu:
        kw["content"] = contenu[:2000]
    if sans_ping:
        kw["allowed_mentions"] = discord.AllowedMentions(
            everyone=False, users=False, roles=False, replied_user=False)
    if not contenu and not chemins:
        return True, False, ""
    try:
        if chemins:
            # Ouverts DANS le try : un fichier retire entre-temps (purge) est
            # une erreur d'envoi comme une autre, pas une exception qui remonte.
            kw["files"] = [discord.File(str(p), filename=Path(p).name) for p in chemins]
        await canal.send(**kw)
        return True, False, ""
    except discord.HTTPException as e:
        lourd = getattr(e, "status", 0) == 413 or getattr(e, "code", 0) == 40005
        err = f"HTTP {getattr(e, 'status', '?')}"
    except Exception as e:                                  # noqa: BLE001
        lourd, err = False, f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        for f in kw.get("files") or []:
            try:
                f.close()
            except Exception:
                pass
    # Journalise : un salon ou le bot ne peut plus ecrire ne doit pas avaler
    # la livraison sans trace (le VA ne voit rien, le journal le dit).
    print(f"[telechargement] envoi refuse dans #{getattr(canal, 'name', '?')} : {err}")
    return False, lourd, err


async def _dire(canal, texte: str) -> None:
    """Un message d'etat : jamais d'exception, meme salon ferme."""
    await _poster(canal, texte)


class _Demande:
    """Une demande en cours : qui, quel compte, quelle option, quand."""

    def __init__(self, pseudo: str, option: str, demandeur, canal):
        self.pseudo = pseudo
        self.option = option
        self.demandeur_id = int(getattr(demandeur, "id", 0) or 0)
        self.quand = _heure_paris()
        self.archive = salon_all_download(getattr(canal, "guild", None))
        self.archivees = 0
        self.archives_ratees = 0
        self.trop_lourds = 0
        self.envois_rates = 0

    def entete(self) -> str:
        qui = f"<@{self.demandeur_id}>" if self.demandeur_id else "?"
        return f"📥 {qui} · @{self.pseudo} · {self.option} · {self.quand}"


class Telechargement(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        #: Compte retenu par personne : {id Discord: (pseudo, combien)}.
        self.choix = charger_choix()
        #: Anti double-clic : une demande a la fois par VA ET par compte. Deux
        #: clics rapides lancaient deux livraisons entrelacees du meme compte,
        #: chacune payee.
        self._en_cours_va = set()
        self._en_cours_pseudo = set()

    async def cog_load(self):
        """Reenregistre les panneaux deja poses dans les salons.

        SANS CECI, RIEN NE MARCHE APRES UN REDEMARRAGE. Les vues sont
        declarees persistantes (timeout=None, custom_id), mais discord.py ne
        rattache pas tout seul les boutons d un message poste par une instance
        precedente : il ne dispatche aucun callback, Discord n obtient jamais
        de reponse, et la personne voit « L application n a pas repondu a
        temps » sur un bouton pourtant intact (constate le 27/08).

        C est la convention de tous les autres cogs du bot : voir numeros.py,
        clickrecap.py, cta_reminder.py, onboarding.py.
        """
        for vue in (PanneauCompte(self), PanneauOptions(self)):
            try:
                self.bot.add_view(vue)
            except Exception as exc:
                print(f"[telechargement] add_view echoue : {exc}")
        try:
            if _ANCIEN_COOKIE.exists():
                _ANCIEN_COOKIE.unlink()
                print("[telechargement] ancien downloads/cookies_sessionid.txt "
                      "retire (identifiant de session en clair)")
        except OSError as exc:
            print(f"[telechargement] ancien fichier de cookies non retire : {exc}")
        try:
            if not self._purge_quotidienne.is_running():
                self._purge_quotidienne.start()
        except Exception as exc:
            print(f"[telechargement] purge quotidienne non lancee : {exc}")

    async def cog_unload(self):
        try:
            self._purge_quotidienne.cancel()
        except Exception:
            pass

    @tasks.loop(hours=24)
    async def _purge_quotidienne(self):
        """Les medias du cache non redemandes depuis 30 jours quittent le VPS."""
        try:
            import hiker_medias as hm
            await asyncio.to_thread(hm.purger)
        except Exception as exc:
            print(f"[telechargement] purge en echec : {exc}")

    @_purge_quotidienne.before_loop
    async def _avant_purge(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------- etat par VA --

    def retenir(self, user_id: int, pseudo: str, combien: int) -> bool:
        """Retient le compte actif d'un VA, sur le disque (ecriture atomique)."""
        self.choix[int(user_id)] = (pseudo, int(combien))
        ok = safe_json.write(CHOIX_FILE, {
            str(k): {"pseudo": p, "combien": n} for k, (p, n) in self.choix.items()})
        if not ok:
            print(f"[telechargement] compte actif de {user_id} non ecrit : il "
                  f"sera perdu au prochain redemarrage")
        return ok

    def reserver(self, user_id: int, pseudo: str) -> str:
        """Prend le verrou du VA et du compte. Rend "" si c'est libre, sinon
        la phrase a lui repondre. SYNCHRONE : aucun await entre le test et la
        prise, sinon deux clics en rafale passent tous les deux."""
        cle = (pseudo or "").lower()
        if user_id in self._en_cours_va:
            return ("Ton telechargement precedent n'est pas fini : attends son "
                    "bilan (« Termine pour … ») avant d'en lancer un autre.")
        if cle in self._en_cours_pseudo:
            return (f"@{pseudo} est deja en cours de telechargement : attends "
                    f"la fin, les fichiers deja descendus repartiront sans credit.")
        self._en_cours_va.add(user_id)
        self._en_cours_pseudo.add(cle)
        return ""

    def liberer(self, user_id: int, pseudo: str) -> None:
        self._en_cours_va.discard(user_id)
        self._en_cours_pseudo.discard((pseudo or "").lower())

    # ---------------------------------------------------------------- envoi --

    async def _archiver(self, dem: _Demande, texte: str, chemins) -> None:
        """La meme chose dans « all-download », avec qui / quoi / quand.

        Les fichiers sont relus du disque : un discord.File ne sert qu'une fois.
        La mention s'affiche mais ne notifie personne (AllowedMentions) : le
        salon est une archive, pas une sonnette.
        """
        if dem.archive is None:
            return
        contenu = dem.entete() + (("\n" + texte) if texte else "")
        ok, lourd, err = await _poster(dem.archive, contenu[:2000], chemins,
                                       sans_ping=True)
        if ok:
            dem.archivees += 1
        else:
            # _poster l'a journalise ; le total part dans le journal en fin
            # de demande (le VA, lui, n'a pas a s'en soucier).
            dem.archives_ratees += 1

    async def _envoyer(self, cible, dem: _Demande, corps: str, chemins, lien: str,
                       texte_archive: str = None) -> None:
        """Une unite (une publication, la photo de profil, la bio) dans
        -content, PUIS sa copie dans all-download. Ne leve jamais."""
        if not chemins:
            ok, _, err = await _poster(cible, corps)
            if ok:
                await self._archiver(dem, texte_archive or corps, [])
            else:
                dem.envois_rates += 1
            return
        limite = _limite(cible)
        lots, lourds = repartir(chemins, limite)
        premier = True
        for lot in lots:
            texte = corps if premier else ""
            premier = False
            ok, lourd, err = await _poster(cible, texte, lot)
            if not ok:
                # Discord a refuse malgre le calcul : le lien plutot que rien,
                # et surtout pas d'exception, qui coupait toute la livraison.
                if lourd:
                    dem.trop_lourds += len(lot)
                    raison = "trop lourd pour ce serveur"
                else:
                    dem.envois_rates += len(lot)
                    raison = f"envoi refuse par Discord : {err}"
                await _dire(cible, (texte + "\n" if texte else "")
                            + f"({raison}) {lien}")
                continue
            await self._archiver(dem, texte, lot)
        if lourds:
            dem.trop_lourds += len(lourds)
            lignes = [f"{Path(p).name} : {_taille(p) / 1048576:.1f} Mo, au-dela de "
                      f"la limite de {limite / 1048576:.0f} Mo de ce serveur"
                      for p in lourds]
            texte = ((corps + "\n") if premier else "") + "\n".join(lignes) + "\n" + lien
            await _dire(cible, texte)
            await self._archiver(dem, texte, [])

    def _bilan(self, pseudo: str, cpt, dem: _Demande, arret: str) -> str:
        import hiker_medias as hm
        if cpt.requetes == 0:
            cout = "0 credit HikerAPI"
        else:
            cout = f"{cpt.requetes} requete(s) HikerAPI"
            if cpt.rafraichies:
                cout += f" (dont {cpt.rafraichies} pour des liens expires)"
        morceaux = [cout]
        if cpt.reutilises:
            morceaux.append(f"{cpt.reutilises} fichier(s) deja la, renvoye(s) sans credit")
        if cpt.telecharges:
            morceaux.append(f"{cpt.telecharges} telecharge(s)")
        if dem.trop_lourds:
            morceaux.append(f"{dem.trop_lourds} trop lourd(s), donne(s) en lien")
        if cpt.echecs:
            morceaux.append(f"{cpt.echecs} fichier(s) non recupere(s)")
        if dem.envois_rates:
            morceaux.append(f"{dem.envois_rates} envoi(s) refuse(s) par Discord")
        try:
            b = hm.budget()
            morceaux.append(f"reserve du jour {b['utilise']}/{b['plafond']}")
        except Exception:
            pass
        tete = (f"Arrete pour @{pseudo} : {arret}" if arret
                else f"Termine pour @{pseudo}")
        return tete + " — " + " · ".join(morceaux) + "."

    async def livrer(self, canal, username: str, combien: int,
                     avatar: bool, bio: bool, photos: bool, reels: bool,
                     par_vues: bool = False, demandeur=None, option: str = ""):
        """Toute une demande, bilan compris. Ne leve jamais.

        Une reserve vide, un solde epuise ou un compte introuvable arretent la
        demande avec une phrase claire ; tout ce qui est deja parti reste.
        """
        import hiker_medias as hm
        dem = _Demande(username, option or "?", demandeur, canal)
        cpt = hm.Compteur()
        arret = ""
        try:
            await self._livrer(canal, dem, cpt, username, combien,
                               avatar, bio, photos, reels, par_vues)
        except hm.ErreurHiker as e:
            arret = str(e)
        except Exception as e:                              # noqa: BLE001
            traceback.print_exc()
            arret = f"erreur inattendue : {type(e).__name__}: {str(e)[:300]}"
        await _dire(canal, self._bilan(username, cpt, dem, arret))
        if dem.archives_ratees:
            print(f"[telechargement] @{username} : {dem.archives_ratees} copie(s) "
                  f"dans {NOM_ARCHIVE} ratee(s), {dem.archivees} reussie(s)")

    async def _livrer(self, canal, dem, cpt, username, combien,
                      avatar, bio, photos, reels, par_vues):
        import hiker_medias as hm
        a_part = asyncio.to_thread

        # La fiche coute une requete : on ne la paie que si elle sert. Une
        # photo de profil deja sur le disque, ou un identifiant deja connu du
        # suivi des comptes, s'en passent.
        pp_deja = hm.pp_locale(username) if avatar else None
        besoin_fiche = (bio or (avatar and pp_deja is None)
                        or ((photos or reels) and not hm.pk_connu(username)))
        if besoin_fiche:
            fiche = await a_part(hm.profil, username, cpt)
        else:
            fiche = hm.profil_en_cache(username)

        entete = f"**@{username}**"
        if fiche:
            if fiche.get("nom"):
                entete += f" - {fiche['nom']}"
            if fiche.get("posts") or fiche.get("abonnes"):
                entete += (f" - {fiche.get('posts', 0)} posts, "
                           f"{fiche.get('abonnes', 0)} abonnes")
        await _dire(canal, entete)

        if avatar:
            chemin, raison = await a_part(hm.photo_de_profil, username, fiche, cpt)
            if chemin is not None:
                await self._envoyer(canal, dem, "Photo de profil", [chemin],
                                    f"https://www.instagram.com/{username}/")
            else:
                await _dire(canal, f"Photo de profil indisponible : {raison}.")
        if bio:
            texte_bio = ((fiche or {}).get("bio") or "").strip() or "Pas de bio."
            # La bio dans SON message : le VA la copie telle quelle.
            await _dire(canal, "Bio :")
            await self._envoyer(canal, dem, texte_bio, [], "",
                                texte_archive="Bio :\n" + texte_bio)

        if not (photos or reels):
            return
        if fiche and fiche.get("prive"):
            await _dire(canal, f"@{username} est un compte PRIVE : ses publications "
                               f"ne sont pas lisibles.")
            return

        notes = []
        lot_photos, lot_reels = [], []
        if photos and reels and not par_vues:
            # « Tout » : UNE lecture des publications sert photos ET reels
            # (les videos du fil portent leur lien mp4). Lire aussi les reels
            # a part ferait payer deux fois les memes publications.
            posts, note = await a_part(hm.publications, username, combien, cpt)
            lot_photos = [p for p in posts if p.get("genre") != "video"]
            lot_reels = [p for p in posts if p.get("genre") == "video"]
            notes.append(note)
        else:
            if photos:
                lot_photos, note = await a_part(hm.publications, username,
                                                combien, cpt, True)
                notes.append(note)
            if reels and par_vues:
                lot_reels, note, source = await a_part(hm.top_reels, username,
                                                       combien, cpt)
                notes += [note, f"classement : {source}"]
            elif reels:
                lot_reels, note = await a_part(hm.reels, username, combien, cpt)
                notes.append(note)
        notes = [n for n in notes if n]

        if not lot_photos and not lot_reels:
            await _dire(canal, "Aucune publication trouvee sur ce profil."
                        + (("\n" + "\n".join(notes)) if notes else ""))
            return
        await _dire(canal,
                    f"{len(lot_photos)} publication(s) photo, {len(lot_reels)} "
                    f"reel(s). Envoi au fil de l'eau."
                    + (("\n" + "\n".join(notes)) if notes else ""))

        for titre, lot in (("POSTS PHOTO", lot_photos),
                           ("TOP REELS" if par_vues else "REELS", lot_reels)):
            if not lot:
                continue
            await _dire(canal, f"--- {titre} ({len(lot)}) ---")
            for idx, post in enumerate(lot, start=1):
                # UN SEUL MESSAGE PAR PUBLICATION, legende comprise : trente
                # posts en trois messages chacun faisaient quatre-vingt-dix
                # envois d'affilee, et le bot restait des minutes en file
                # d'attente derriere lui-meme (constate le 27/08).
                corps = _corps(idx, post, par_vues)
                res = await a_part(hm.preparer_post, post, cpt, username)
                chemins = [r["chemin"] for r in res if r["chemin"] is not None]
                rates = [r for r in res if r["chemin"] is None]
                lien = hm.permalien(post["code"])
                if chemins:
                    await self._envoyer(canal, dem, corps, chemins, lien)
                if rates:
                    detail = "; ".join(
                        f"element {r['i']} : {r['erreur'] or 'indisponible'}"
                        for r in rates)
                    await _dire(canal, (corps if not chemins else f"#{idx}")
                                + "\n" + detail[:600] + "\n" + lien)
                await asyncio.sleep(PAUSE_ENTRE_POSTS)

    # ----------------------------------------------------------------- menu --

    @app_commands.guilds(discord.Object(id=SERVEUR_ID))
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.command(
        name="menudownload",
        description="Poser les deux panneaux de telechargement dans ce salon")
    @app_commands.describe(
        epingler="true = epingle les panneaux pour qu'ils restent en haut du salon")
    async def menudownload(self, interaction: discord.Interaction,
                           epingler: bool = True):
        """Pose les deux panneaux (le compte, les options) a la demande.

        Il y en avait DEUX definitions : la seconde, seule retenue par Python,
        construisait une classe `Panneau` qui n'existait plus -- la commande
        echouait au premier appel. Et la premiere repondait APRES avoir pose
        les panneaux, bien au-dela des trois secondes accordees par Discord.
        """
        canal = interaction.channel
        if salon_reserve(canal):
            await interaction.response.send_message(
                f"#{getattr(canal, 'name', '?')} est un salon de service (archive) : "
                f"pas de panneaux ici.", ephemeral=True)
            return
        # On repond D'ABORD : vider l'ancien panneau et epingler prend
        # plusieurs secondes.
        await interaction.response.defer(ephemeral=True, thinking=True)
        # Le menage des messages du bot ne se fait que dans un salon -download :
        # ailleurs (un -content), il effacerait le contenu deja livre.
        nettoyer = _norm(getattr(canal, "name", "")).endswith("-download")
        n = await poser_panneaux(self, canal, epingler=epingler, nettoyer=nettoyer)
        await interaction.followup.send(
            f"{n} panneau(x) pose(s)." if n else
            "Impossible de poser les panneaux ici (droits du bot ?).",
            ephemeral=True)


def _corps(idx: int, post: dict, par_vues: bool) -> str:
    """Numero, date (et vues pour le top), puis la description."""
    entete = f"#{idx}"
    if post.get("date"):
        try:
            entete += " - " + datetime.fromtimestamp(
                int(post["date"]), tz=timezone.utc).strftime("%d/%m/%Y")
        except (OverflowError, OSError, ValueError):
            pass
    if par_vues and post.get("vues") is not None:
        entete += f" - {int(post['vues']):,} vues".replace(",", " ")
    legende = (post.get("legende") or "").strip()
    return entete + ((chr(10) + legende[:1800]) if legende else "")


#: Titres des deux panneaux. Ils servent aussi de marqueurs : c'est a eux que
#: poser_panneaux reconnait un ancien panneau a retirer.
TITRE_COMPTE = "Telechargement - le compte"
TITRE_OPTIONS = "Telechargement - les options"


def _embed_compte(username: str = "", combien: int = 30):
    """L embed du premier panneau, avec ou sans compte actif."""
    if username:
        return discord.Embed(
            title=TITRE_COMPTE,
            description=f"Compte actif : **@{username}**  (au plus {combien})"
                        + chr(10) + "Clique pour en changer.",
            color=discord.Color.blurple())
    return discord.Embed(
        title=TITRE_COMPTE,
        description="Clique et entre le pseudo du compte a descendre."
                    + chr(10) + "Il reste retenu jusqu a ce que tu en changes.",
        color=discord.Color.blurple())


def _embed_options():
    return discord.Embed(
        title=TITRE_OPTIONS,
        description="Choisis ce que tu veux de ce compte."
                    + chr(10) + chr(10)
                    + "Ordre d'envoi : photo de profil, bio, posts, puis reels."
                    + chr(10) + "Chaque fichier part des qu'il est pret."
                    + chr(10) + "Deja telecharge : renvoye sans credit.",
        color=discord.Color.green())


class ModalCompte(discord.ui.Modal, title="Quel compte ?"):
    """Retient le pseudo pour la personne qui l a saisi.

    Le pseudo est garde PAR PERSONNE, jamais dans la vue : un panneau est
    partage par tout un salon, et une valeur rangee dans la vue serait vue par
    tout le monde. Deux VA travaillant en meme temps se voleraient leur
    saisie -- l un choisit un compte, l autre clique, et recoit le compte du
    premier.
    """

    pseudo = discord.ui.TextInput(
        label="Pseudo Instagram",
        placeholder="sky.ards  ou  https://instagram.com/sky.ards",
        required=True, max_length=120)
    combien = discord.ui.TextInput(
        label="Combien au maximum (defaut 30)",
        placeholder="30", required=False, max_length=3)

    def __init__(self, cog: "Telechargement"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, inter: discord.Interaction):
        brut = str(self.pseudo).strip().rstrip("/")
        # Minuscules : Instagram ne distingue pas la casse, et le cache de
        # listing est range au pseudo -- « Sky.Ards » et « sky.ards » ne
        # doivent pas payer deux fois.
        username = brut.split("/")[-1].lstrip("@").split("?")[0].lower()
        if not username:
            await inter.response.send_message("Pseudo invalide.", ephemeral=True)
            return
        try:
            n = int(str(self.combien).strip() or "30")
        except ValueError:
            n = 30
        n = max(1, min(n, 200))
        if not _PSEUDO_OK.match(username):
            await inter.response.send_message(
                f"« {username} » ne ressemble pas a un pseudo Instagram.",
                ephemeral=True)
            return
        self.cog.retenir(inter.user.id, username, n)

        # Le panneau AFFICHE le compte actif. Chaque VA a son propre salon
        # -download : il n y a donc qu une personne par panneau, et l afficher
        # ne revele rien a personne d autre.
        # ON REPOND D ABORD, ON EDITE ENSUITE.
        #
        # Discord n accorde que TROIS SECONDES pour la premiere reponse a une
        # interaction. inter.message.edit() est un appel reseau : le placer
        # avant l accuse de reception faisait expirer le delai des que l API
        # trainait un peu (constate le 27/08).
        await inter.response.send_message(
            f"Compte actif : **@{username}** (au plus {n}).", ephemeral=True)
        try:
            await inter.message.edit(
                embed=_embed_compte(username, n),
                view=PanneauCompte(self.cog))
        except Exception:
            pass


class PanneauCompte(discord.ui.View):
    """Premier panneau : QUI. Il ne fait que retenir."""

    def __init__(self, cog: "Telechargement"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Changer de compte", style=discord.ButtonStyle.primary,
                       custom_id="dl:compte")
    async def b_compte(self, inter, _):
        await inter.response.send_modal(ModalCompte(self.cog))


class PanneauOptions(discord.ui.View):
    """Second panneau : QUOI. Il lit le compte retenu pour CETTE personne."""

    def __init__(self, cog: "Telechargement"):
        super().__init__(timeout=None)
        self.cog = cog

    async def _lancer(self, inter, quoi):
        court, long_ = OPTIONS[quoi]
        garde = self.cog.choix.get(inter.user.id)
        if not garde:
            await inter.response.send_message(
                "Entre d'abord un compte dans le panneau du dessus.",
                ephemeral=True)
            return
        username, n = garde
        occupe = self.cog.reserver(inter.user.id, username)
        if occupe:
            await inter.response.send_message(occupe, ephemeral=True)
            return
        try:
            cible = salon_de_livraison(inter.channel)
            await inter.response.send_message(
                f"**@{username}** - {long_} : ca part dans "
                f"{getattr(cible, 'mention', '#?')}.", ephemeral=True)
            await self.cog.livrer(
                cible, username, n,
                avatar=quoi in ("tout", "pp"),
                bio=quoi in ("tout", "bio"),
                photos=quoi in ("tout", "photos"),
                reels=quoi in ("tout", "reels", "top"),
                par_vues=(quoi == "top"),
                demandeur=inter.user, option=court)
        finally:
            self.cog.liberer(inter.user.id, username)

    @discord.ui.button(label="Tout", style=discord.ButtonStyle.success,
                       custom_id="dl:tout", row=0)
    async def b_tout(self, inter, _):
        await self._lancer(inter, "tout")

    @discord.ui.button(label="Photo de profil", style=discord.ButtonStyle.primary,
                       custom_id="dl:pp", row=0)
    async def b_pp(self, inter, _):
        await self._lancer(inter, "pp")

    @discord.ui.button(label="Bio", style=discord.ButtonStyle.primary,
                       custom_id="dl:bio", row=0)
    async def b_bio(self, inter, _):
        await self._lancer(inter, "bio")

    @discord.ui.button(label="Posts photo", style=discord.ButtonStyle.primary,
                       custom_id="dl:photos", row=1)
    async def b_photos(self, inter, _):
        await self._lancer(inter, "photos")

    @discord.ui.button(label="Reels", style=discord.ButtonStyle.primary,
                       custom_id="dl:reels", row=1)
    async def b_reels(self, inter, _):
        await self._lancer(inter, "reels")

    @discord.ui.button(label="Top reels", style=discord.ButtonStyle.secondary,
                       custom_id="dl:top", row=1)
    async def b_top(self, inter, _):
        await self._lancer(inter, "top")


async def poser_panneaux(cog, canal, epingler: bool = True, nettoyer: bool = True):
    """Pose les DEUX panneaux dans un salon. Rend le nombre de messages poses.

    Les anciens panneaux du bot sont retires d'abord : un message Discord est
    fige, donc une evolution du menu laisse sinon un panneau perime a cote du
    neuf, et personne ne sait lequel fait foi.

    Jamais dans un salon de service : « all-download » est l'archive du
    proprietaire, et le menage ci-dessous commence par vider les messages du
    bot -- c'est-a-dire l'archive elle-meme.
    """
    if salon_reserve(canal):
        print(f"[telechargement] {getattr(canal, 'name', '?')} est un salon de "
              f"service : panneaux NON poses")
        return 0
    poses = 0
    moi = getattr(getattr(cog.bot, "user", None), "id", 0)
    purge_faite = False
    if nettoyer:
        # On vide ce que LE BOT a poste : panneaux perimes, notices
        # d'epinglage, comptes rendus d'un ancien telechargement. Le salon ne
        # doit porter que les deux panneaux, sinon ils sortent de l'ecran et
        # plus personne ne les trouve. On ne touche pas aux messages des humains.
        try:
            await canal.purge(limit=200, check=lambda m: m.author.id == moi)
            purge_faite = True
        except Exception:
            purge_faite = False
    if not purge_faite:
        # Purge refusee (permission) ou pas voulue : on retire au moins les
        # anciens panneaux, sinon on en empilerait un troisieme.
        try:
            for p in await canal.pins():
                if (p.author.id == moi and p.embeds
                        and "Telechargement" in (p.embeds[0].title or "")):
                    try:
                        await p.delete()
                    except Exception:
                        pass
        except Exception:
            pass

    for emb, vue in ((_embed_compte(), PanneauCompte(cog)),
                     (_embed_options(), PanneauOptions(cog))):
        try:
            msg = await canal.send(embed=emb, view=vue)
            poses += 1
            if epingler:
                try:
                    await msg.pin(reason="Menu de telechargement permanent")
                    # Epingler produit une notice systeme « X a epingle un
                    # message ». Elle compte comme un message dans le salon :
                    # on la retire pour ne laisser QUE les panneaux.
                    await asyncio.sleep(0.5)
                    # Hors d'un salon -download (nettoyer=False), SEULE la
                    # notice part : les messages sans embed du bot y sont le
                    # contenu livre, pas des restes.
                    await canal.purge(
                        limit=5,
                        check=lambda m: (m.type == discord.MessageType.pins_add
                                         or (nettoyer and m.author.id == moi
                                             and not m.embeds)))
                except Exception:
                    pass
        except Exception:
            pass
    return poses


async def setup(bot: commands.Bot):
    await bot.add_cog(Telechargement(bot))
