# -*- coding: utf-8 -*-
"""Telechargement d'un compte Instagram, depuis un panneau Discord.

POURQUOI DANS CE BOT ET PAS DANS LE SIEN
    Le telechargeur avait son propre bot (ig-downloader), mais celui-ci n'est
    invite que sur UN serveur. Manageuse est deja partout : mettre la commande
    ici evite d'inviter un second bot et de gerer deux identites.

CE QUE FAIT LA COMMANDE
    /telechargeur   pose un panneau permanent dans le salon

    Un bouton ouvre une fenetre qui demande le pseudo, puis un menu propose
    quoi descendre. L'ordre d'envoi est toujours le meme, et il est voulu :

        1. la photo de profil
        2. la bio
        3. les publications PHOTO, avec leur description
        4. les REELS, avec leur description

    L'identite du compte arrive donc AVANT son contenu : le salon se lit de
    haut en bas, et sans cela on ne sait plus a qui appartiennent les fichiers
    qui defilent.

    Chaque fichier part DES QU'IL EST PRET, jamais en lot a la fin. Un compte
    qui disparait en cours de route laisse quand meme tout ce qui est passe --
    c'est tout l'interet de l'outil.

D'OU VIENT LE CODE DE TELECHARGEMENT
    Il a ete EXTRAIT de ig-downloader/bot.py et recopie ici, volontairement.
    Anna tourne sur un autre hote que le telechargeur : un import croise
    obligerait a deployer tout le dossier ig-downloader a cote du bot, et la
    commande echouerait au premier clic s'il manquait. Ce cog est donc
    autonome, un seul fichier a copier.

    Contrepartie assumee : si le telechargeur evolue, il faut rejouer
    l'extraction plutot que d'esperer que la correction se propage.

CE QU'IL FAUT A COTE, ET C'EST TOUT
    cookies.txt   dans le dossier du bot, session Instagram au format Netscape.
    Sans lui la liste des publications revient VIDE, sans message d'erreur :
    Instagram ne refuse pas, il ne montre rien. C'est le symptome le plus
    trompeur de tout l'outil.

    Deux variables d'environnement permettent de deplacer les chemins :
    IG_COOKIES et IG_DOWNLOAD_DIR.
"""
from __future__ import annotations

import asyncio
import http.cookiejar
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
import yt_dlp

import discord
from discord import app_commands
from discord.ext import commands

# ─────────────────────────────────────────────────────────────────────────
#  Ce qui suit vient de ig-downloader/bot.py, EXTRAIT automatiquement.
#
#  Pourquoi le recopier ici plutot que l'importer : Anna tourne sur un autre
#  hote que le telechargeur. Un import croise obligerait a deployer le dossier
#  ig-downloader a cote du bot, et la commande echouerait au premier clic s'il
#  manquait. Ce cog est donc autonome : un seul fichier a copier.
#
#  Contrepartie assumee : si le telechargeur evolue, il faut rejouer
#  l'extraction (scratchpad/rendre_autonome.py).
# ─────────────────────────────────────────────────────────────────────────

#: Le SEUL serveur ou cette commande existe. Anna est sur plusieurs serveurs,
#: mais le telechargement ne concerne que celui-ci : la commande n'est donc
#: pas seulement refusee ailleurs, elle n'y est pas proposee du tout.
#:
#: On passe par un identifiant et non par un nom : il survit a un renommage.
#:     Youl4b        1535758943324999711
#:     YouLab AGENCY 1505418484052394004  (volontairement exclu)
SERVEUR_ID = int(os.getenv("IG_SERVEUR_ID") or "1535758943324999711")

#: Ou atterrissent les fichiers descendus. A cote du bot, pas du cog.
DOWNLOAD_DIR = Path(
    os.getenv("IG_DOWNLOAD_DIR")
    or (Path(__file__).resolve().parents[1] / "downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

#: Session Instagram au format Netscape. SANS ELLE, la liste des publications
#: revient VIDE sans message d'erreur : Instagram ne refuse pas, il ne montre
#: rien. C'est le symptome le plus trompeur de tout l'outil.
COOKIES_FILE = Path(
    os.getenv("IG_COOKIES")
    or (Path(__file__).resolve().parents[1] / "cookies.txt"))

IG_WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "*/*",
    "Referer": "https://www.instagram.com/",
}


# ─────────────────────────────────────────────────────────────────────────
#  APIFY D'ABORD, COOKIES EN REPLI
#
#  apify_reels.py pose la regle du projet : Apify extrait avec SES proxys, donc
#  le compte Instagram de l'agence n'est jamais utilise -- aucun cookie, aucun
#  risque de ban. Le telechargeur passait a cote de cette regle : il ouvrait
#  une session avec cookies.txt pour lister un profil.
#
#  Le meme acteur officiel (apify~instagram-scraper) sait lister un compte : il
#  suffit de lui donner l'URL du profil au lieu d'une liste de liens de reels.
#  On ne retombe sur les cookies que si le jeton Apify est absent.
# ─────────────────────────────────────────────────────────────────────────


def _apify_pret() -> bool:
    """Vrai si le jeton Apify est configure. Sans lui, on retombe aux cookies."""
    try:
        import apify_reels
        return bool(apify_reels.get_token())
    except Exception:
        return False


def _apify_appel(charge: dict, timeout: int = 240):
    """Un run synchrone de l'acteur. Rend (items, raison d'echec).

    La raison est REMONTEE, pas seulement imprimee : un print part dans le
    journal du VPS, que personne ne lit au moment ou le bouton ne fait rien.
    C'est exactement ce qui s'est passe le 27/08 -- le salon annoncait
    « Termine » sans avoir rien descendu, et sans dire pourquoi.
    """
    import apify_reels
    import requests as _rq
    tok = apify_reels.get_token()
    if not tok:
        return [], "jeton Apify absent"
    try:
        r = _rq.post(
            f"{apify_reels.BASE}/acts/{apify_reels.ACTOR}"
            f"/run-sync-get-dataset-items?token={tok}",
            json=charge, timeout=timeout)
        if r.status_code not in (200, 201):
            return [], f"HTTP {r.status_code} : {r.text[:200]}"
        items = r.json()
        if not isinstance(items, list):
            return [], f"reponse inattendue : {str(items)[:200]}"
        if not items:
            return [], ("l'acteur n'a rien renvoye : compte prive, "
                        "inexistant, ou resultsType refuse")
        # Un item d'erreur est frequent : l'acteur repond 200 avec un objet
        # qui porte le probleme au lieu d'une publication.
        if len(items) == 1 and isinstance(items[0], dict):
            pb = (items[0].get("error") or items[0].get("errorDescription")
                  or items[0].get("message"))
            if pb and not items[0].get("url"):
                return [], str(pb)[:200]
        return items, ""
    except Exception as exc:
        return [], f"injoignable : {str(exc)[:150]}"


def profil_entete_apify(username: str) -> dict:
    """Fiche du compte via Apify. {} si indisponible."""
    items, raison = _apify_appel({
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "details",
        "resultsLimit": 1,
        "addParentData": False,
    }, timeout=120)
    # La raison est CONSERVEE, comme pour lister_posts_apify. Elle etait jetee :
    # la fiche echouait, le salon disait « illisible » et personne ne savait si
    # c etait le jeton, un compte prive, ou l acteur qui refusait la demande.
    profil_entete_apify.derniere_raison = raison
    for it in items:
        if not isinstance(it, dict):
            continue
        return {
            "avatar": (it.get("profilePicUrlHD") or it.get("profilePicUrl") or ""),
            "bio": (it.get("biography") or "").strip(),
            "nom": (it.get("fullName") or "").strip(),
            "posts": it.get("postsCount") or 0,
            "abonnes": it.get("followersCount") or 0,
        }
    return {}


def lister_posts_apify(username: str, max_posts: int) -> list:
    """Publications d'un compte via Apify, au meme format que la voie cookies.

    L'acteur ne dit pas toujours explicitement si un post est une video : on le
    deduit de la presence d'une videoUrl, plus fiable qu'un champ 'type' dont
    le libelle change d'une version a l'autre.
    """
    items, raison = _apify_appel({
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": int(max_posts),
        "addParentData": False,
    })
    lister_posts_apify.derniere_raison = raison
    posts = []
    for it in items:
        if not isinstance(it, dict):
            continue
        url = (it.get("url") or "").strip()
        if not url:
            continue
        video = bool(it.get("videoUrl")) or (it.get("type") == "Video")
        horo = None
        ts = it.get("timestamp")
        if ts:
            try:
                horo = datetime.fromisoformat(
                    str(ts).replace("Z", "+00:00")).timestamp()
            except Exception:
                horo = None
        posts.append({
            "shortcode": it.get("shortCode") or "",
            "url": url,
            "is_video": video,
            "timestamp": horo,
            "caption": (it.get("caption") or "").strip(),
            "views": it.get("videoViewCount") or it.get("videoPlayCount") or 0,
            "likes": it.get("likesCount") or 0,
            "comments": it.get("commentsCount") or 0,
        })
    return posts


def build_ydl_options(output_path: str) -> dict:
    opts = {
        "outtmpl": output_path,
        "format": "mp4/bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
    }
    if COOKIES_FILE.exists():
        opts["cookiefile"] = str(COOKIES_FILE)
    return opts


def download_sync(lien: str, output_path: str) -> dict:
    """Telechargement bloquant (sera execute dans un thread)."""
    with yt_dlp.YoutubeDL(build_ydl_options(output_path)) as ydl:
        info = ydl.extract_info(lien, download=True)
    return info


def _build_ig_session() -> requests.Session:
    """Cree une session requests avec les cookies Netscape charges."""
    if not COOKIES_FILE.exists():
        raise RuntimeError(
            "Fichier cookies.txt manquant. Exporte tes cookies Instagram et "
            "place-les a cote de bot.py."
        )
    s = requests.Session()
    cj = http.cookiejar.MozillaCookieJar(str(COOKIES_FILE))
    cj.load(ignore_discard=True, ignore_expires=True)
    s.cookies = cj
    s.headers.update(IG_WEB_HEADERS)
    return s


def profil_entete_sync(username: str) -> dict:
    """Fiche du compte : avatar, bio, nom affiche.

    Le meme endpoint que list_profile_posts_sync renvoie deja tout cela dans
    l'objet `user` : ni instaloader ni aucune autre bibliotheque n'est
    necessaire, et on reste sur les cookies que le projet gere deja.

    Renvoie {} si la fiche est illisible -- le telechargement des posts, lui,
    n'a pas de raison d'echouer pour autant.
    """
    try:
        s = _build_ig_session()
        r = s.get(
            "https://www.instagram.com/api/v1/users/web_profile_info/",
            params={"username": username},
            timeout=15,
        )
        if r.status_code != 200:
            return {}
        user = ((r.json().get("data") or {}).get("user") or {})
        return {
            "avatar": user.get("profile_pic_url_hd") or user.get("profile_pic_url") or "",
            "bio": (user.get("biography") or "").strip(),
            "nom": (user.get("full_name") or "").strip(),
            "posts": ((user.get("edge_owner_to_timeline_media") or {}).get("count") or 0),
            "abonnes": ((user.get("edge_followed_by") or {}).get("count") or 0),
        }
    except Exception:
        return {}


def telecharger_binaire_sync(url: str, destination: str) -> bool:
    """Descend un fichier simple (l'avatar). Rend True si le fichier est ecrit."""
    try:
        s = _build_ig_session()
        r = s.get(url, timeout=60)
        if r.status_code == 200 and r.content:
            Path(destination).write_bytes(r.content)
            return True
    except Exception:
        pass
    return False


def list_profile_posts_sync(username: str, max_posts: int) -> list[dict]:
    """Liste les N posts les plus recents via l'API web Instagram (cookies requis).

    Renvoie une liste de dicts normalises : shortcode, url, media_type, views,
    likes, comments, timestamp, caption, is_video.
    """
    s = _build_ig_session()

    # 1) username -> user_id
    r = s.get(
        "https://www.instagram.com/api/v1/users/web_profile_info/",
        params={"username": username},
        timeout=15,
    )
    if r.status_code == 404:
        raise RuntimeError(f"Compte @{username} introuvable.")
    if r.status_code != 200:
        raise RuntimeError(f"Erreur API profil ({r.status_code}). Cookies peut-etre expires.")
    data = r.json().get("data") or {}
    user = data.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise RuntimeError(f"Impossible de recuperer l'ID de @{username} (compte prive ?).")
    if user.get("is_private"):
        raise RuntimeError(
            f"Le compte @{username} est prive. "
            "Soit tu le suis avec le compte des cookies, soit ca ne passera pas."
        )

    # 2) feed paginé
    items: list[dict] = []
    max_id = None
    while len(items) < max_posts:
        params = {"count": min(50, max_posts - len(items))}
        if max_id:
            params["max_id"] = max_id
        r = s.get(
            f"https://www.instagram.com/api/v1/feed/user/{user_id}/",
            params=params,
            timeout=15,
        )
        if r.status_code != 200:
            break
        body = r.json()
        batch = body.get("items") or []
        if not batch:
            break
        items.extend(batch)
        if not body.get("more_available"):
            break
        max_id = body.get("next_max_id")
        if not max_id:
            break

    # 3) normalisation
    out = []
    for it in items[:max_posts]:
        code = it.get("code")
        if not code:
            continue
        media_type = it.get("media_type")  # 1=photo, 2=video, 8=carousel
        is_video = media_type == 2
        caption_obj = it.get("caption") or {}
        out.append({
            "shortcode": code,
            "url": f"https://www.instagram.com/p/{code}/",
            "media_type": media_type,
            "is_video": is_video,
            "views": it.get("play_count") or it.get("view_count") or 0,
            "likes": it.get("like_count") or 0,
            "comments": it.get("comment_count") or 0,
            "timestamp": it.get("taken_at"),
            "caption": (caption_obj.get("text") if isinstance(caption_obj, dict) else "") or "",
        })
    return out


class Telechargement(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Reenregistre les panneaux deja poses dans les salons.

        SANS CECI, RIEN NE MARCHE APRES UN REDEMARRAGE. Les vues sont
        declarees persistantes (timeout=None, custom_id), mais discord.py ne
        rattache pas tout seul les boutons d un message poste par une instance
        precedente : il ne dispatche aucun callback, Discord n obtient jamais
        de reponse, et la personne voit « L application n a pas repondu a
        temps » sur un bouton pourtant intact.

        Le symptome est trompeur -- il ressemble a une lenteur, alors que rien
        ne s execute. Constate le 27/08 : le panneau repondait juste apres avoir
        ete pose, puis plus jamais des le redemarrage suivant.

        C est la convention de tous les autres cogs du bot : voir numeros.py,
        clickrecap.py, cta_reminder.py, onboarding.py.
        """
        for vue in (PanneauCompte(self), PanneauOptions(self)):
            try:
                self.bot.add_view(vue)
            except Exception as exc:
                print(f"[telechargement] add_view echoue : {exc}")
        #: Compte retenu par personne : {id Discord: (pseudo, combien)}.
        #: En memoire seulement -- un redemarrage le vide, et c'est sans
        #: consequence : on ressaisit un pseudo en deux secondes.
        self.choix = {}

    # ---------------------------------------------------------------- envoi --

    async def livrer(self, canal, username: str, combien: int,
                     avatar: bool, bio: bool, photos: bool, reels: bool,
                     par_vues: bool = False):
        dossier = DOWNLOAD_DIR

        apify = _apify_pret()
        source = "Apify (sans cookie)" if apify else "cookies"

        if avatar or bio:
            fiche = await asyncio.to_thread(
                profil_entete_apify if apify else profil_entete_sync, username)
            if not fiche and apify:
                # Apify muet sur la fiche : les cookies peuvent encore l'avoir.
                fiche = await asyncio.to_thread(profil_entete_sync, username)
            if not fiche:
                # « Je continue avec les publications » etait affiche meme
                # quand aucune n avait ete demandee -- en cliquant « Bio » on
                # lisait une promesse jamais tenue, suivie d un « Termine »
                # qui paraissait fautif. On dit ce qui se passe vraiment.
                pourquoi = getattr(profil_entete_apify, "derniere_raison", "")
                suite = ("Je continue avec les publications."
                         if (photos or reels) else "Rien d autre n a ete demande.")
                await canal.send(
                    f"Fiche de @{username} illisible ({source})"
                    + (f" : {pourquoi}" if pourquoi else "")
                    + ". " + suite)
            else:
                entete = f"**@{username}**"
                if fiche.get("nom"):
                    entete += f" - {fiche['nom']}"
                if fiche.get("posts") or fiche.get("abonnes"):
                    entete += (f" - {fiche.get('posts', 0)} posts, "
                               f"{fiche.get('abonnes', 0)} abonnes")
                await canal.send(entete)

                if avatar and fiche.get("avatar"):
                    pp = dossier / f"pp_{username}_{uuid.uuid4().hex[:8]}.jpg"
                    if await asyncio.to_thread(telecharger_binaire_sync,
                                               fiche["avatar"], str(pp)):
                        await canal.send(content="Photo de profil",
                                         file=discord.File(str(pp)))
                    else:
                        await canal.send("Photo de profil indisponible.")
                if bio:
                    await canal.send("Bio :")
                    await canal.send(fiche.get("bio") or "Pas de bio.")

        if not (photos or reels):
            await canal.send(f"Termine pour @{username}.")
            return

        try:
            posts = await asyncio.to_thread(
                lister_posts_apify if apify else list_profile_posts_sync,
                username, combien)
            if apify and not posts:
                # On NE S ARRETE PAS sur un Apify muet : on dit pourquoi, et on
                # tente les cookies. Un « Termine » sans rien descendre ne
                # renseigne personne.
                raison = getattr(lister_posts_apify, "derniere_raison", "")
                await canal.send(
                    f"Apify n'a rien rendu pour @{username}"
                    + (f" : {raison}" if raison else "")
                    + ". Nouvel essai avec les cookies.")
                posts = await asyncio.to_thread(
                    list_profile_posts_sync, username, combien)
                source = "cookies (repli)"
        except Exception as e:
            await canal.send(f"Erreur en lisant le profil : {str(e)[:1500]}")
            return
        if not posts:
            await canal.send("Aucun post trouve sur ce profil.")
            return

        await canal.send(f"Source : {source}.")
        lot_photos = [p for p in posts if not p["is_video"]]
        lot_reels = [p for p in posts if p["is_video"]]
        if par_vues:
            # "Top reels" : les plus VUS, pas les plus recents. Le tri se
            # fait sur ce que list_profile_posts_sync a deja releve, donc
            # il ne coute aucune requete supplementaire.
            lot_reels.sort(key=lambda p: p.get("views") or 0, reverse=True)
            lot_reels = lot_reels[:combien]
        await canal.send(
            f"{len(posts)} publication(s) : {len(lot_photos)} photo(s), "
            f"{len(lot_reels)} video(s). Envoi au fil de l'eau.")

        for libelle, lot, actif, ext in (("PHOTOS", lot_photos, photos, "jpg"),
                                         ("REELS", lot_reels, reels, "mp4")):
            if not lot or not actif:
                continue
            await canal.send(f"--- {libelle} ({len(lot)}) ---")

            for idx, post in enumerate(lot, start=1):
                legende = (post.get("caption") or "").strip()
                date_str = ""
                if post.get("timestamp"):
                    date_str = datetime.fromtimestamp(
                        post["timestamp"], tz=timezone.utc).strftime("%d/%m/%Y")

                # UN SEUL MESSAGE PAR PUBLICATION.
                #
                # Le fichier, le numero, la date et la description partaient en
                # deux ou trois messages separes. Sur trente posts cela faisait
                # pres de QUATRE-VINGT-DIX envois d affilee dans le meme salon,
                # alors que Discord n en accepte qu environ cinq par cinq
                # secondes. Le bot passait donc plusieurs minutes en file
                # d attente derriere ses propres messages -- et pendant ce
                # temps AUCUNE interaction ne pouvait etre servie dans les trois
                # secondes imparties. D ou « L application n a pas repondu a
                # temps » sur un bouton sans rapport (constate le 27/08).
                #
                # Tout tient maintenant dans un envoi, legende comprise.
                entete = f"#{idx}" + (f" - {date_str}" if date_str else "")
                corps = entete + ((chr(10) + legende[:1800]) if legende else "")

                fichier = dossier / f"{uuid.uuid4().hex}.{ext}"
                try:
                    await asyncio.to_thread(
                        download_sync, post["url"], str(fichier))
                except Exception as e:
                    await canal.send(
                        corps + chr(10) + f"echec : {str(e)[:200]}"
                        + chr(10) + post["url"])
                    continue

                if not fichier.exists():
                    await canal.send(corps + chr(10) + post["url"])
                    continue

                taille_mo = fichier.stat().st_size / (1024 * 1024)
                if taille_mo > 24.5:
                    # Discord refuse au-dela : on donne le lien plutot que rien.
                    await canal.send(
                        corps + chr(10)
                        + f"({taille_mo:.1f} Mo, trop lourd pour Discord)"
                        + chr(10) + post["url"])
                else:
                    await canal.send(content=corps[:1900],
                                     file=discord.File(str(fichier)))

                # Une seconde entre deux publications : on reste sous la limite
                # au lieu de la heurter et d attendre que Discord nous relache.
                await asyncio.sleep(1.0)

        await canal.send(f"Termine pour @{username}.")

    # ----------------------------------------------------------------- menu --

    async def ouvrir_menu(self, interaction: discord.Interaction):
        """Pose les deux panneaux, pour qui veut les poser a la demande."""
        await poser_panneaux(self, interaction.channel)
        await interaction.response.send_message("Panneaux poses.", ephemeral=True)

    @app_commands.guilds(discord.Object(id=SERVEUR_ID))
    @app_commands.command(
        name="menudownload",
        description="Poser les deux panneaux de telechargement dans ce salon")
    async def menudownload(self, interaction: discord.Interaction):
        n = await poser_panneaux(self, interaction.channel)
        await interaction.response.send_message(
            f"{n} panneau(x) pose(s)." if n else
            "Impossible de poser les panneaux ici.", ephemeral=True)

    async def ouvrir_menu(self, interaction: discord.Interaction):
        """Pose le panneau en ephemere, pour qui veut l'ouvrir a la demande.

        Il montre les memes six boutons que le panneau permanent : on ne
        renvoie pas vers une fenetre de saisie sans avoir dit ce qu'on peut
        demander.
        """
        await interaction.response.send_message(
            "Que veux-tu telecharger ?", view=Panneau(self), ephemeral=True)

    @app_commands.guilds(discord.Object(id=SERVEUR_ID))
    @app_commands.command(
        name="menudownload",
        description="Poser le menu de telechargement Instagram dans ce salon")
    @app_commands.describe(
        epingler="true = epingle le menu pour qu'il reste en haut du salon")
    async def menudownload(self, interaction: discord.Interaction,
                           epingler: bool = True):
        """Pose un menu permanent, dans l'esprit du menu central du bot.

        Un menu A PART, et pas un bouton greffe dans le menu contenu : les
        deux ne servent pas la meme chose ni les memes gens, et melanger
        "recuperer du contenu d'un compte tiers" avec "recevoir SON contenu"
        rendrait les deux moins lisibles.
        """
        emb = discord.Embed(
            title="Telechargement - clique, entre un pseudo, choisis",
            description=(
                "Deux etapes : d'abord **qui**, ensuite **quoi**."
                "\n\n"
                "**Photo de profil** \u00b7 **Bio** \u00b7 "
                "**Posts photo** \u00b7 **Reels** \u00b7 "
                "**Top reels** (les plus vus)"
                "\n\n"
                "L'ordre d'envoi est toujours le meme : photo de profil, "
                "bio, posts, puis reels. Chaque fichier part **des qu'il "
                "est pret** - un compte qui disparait en cours de route "
                "laisse tout ce qui est deja passe."
            ),
            color=discord.Color.green())
        try:
            msg = await interaction.channel.send(embed=emb, view=Panneau(self))
        except Exception as e:
            await interaction.response.send_message(
                f"Impossible de poster le menu : {e}", ephemeral=True)
            return
        if epingler:
            try:
                await msg.pin(reason="Menu de telechargement permanent")
            except Exception:
                pass
        await interaction.response.send_message("Menu pose.", ephemeral=True)


#: Titres des deux panneaux. Ils servent aussi de marqueurs : c'est a eux que
#: _ensure_dl_panel reconnait un salon deja equipe.
#: Un pseudo Instagram : lettres, chiffres, point et tiret bas, 30 au plus.
#: Sans ce controle, "#" ou une URL mal collee passait, et le bot annonçait
#: « Compte retenu : @# » avant d aller interroger un compte inexistant.
_PSEUDO_OK = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def salon_de_livraison(canal):
    """Ou les fichiers atterrissent : le salon -content du meme VA.

    Le salon -download ne porte que les deux panneaux ; y deverser des dizaines
    de fichiers les repousserait hors de vue. Le contenu genere vit deja dans
    -content, les telechargements l y rejoignent.

    Si le salon jumeau n existe pas, on reste sur place plutot que de perdre
    les fichiers.
    """
    nom = getattr(canal, "name", "") or ""
    if not nom.endswith("-download"):
        return canal
    vise = nom[: -len("-download")] + "-content"
    guilde = getattr(canal, "guild", None)
    if guilde is None:
        return canal
    for c in guilde.text_channels:
        if c.name == vise:
            return c
    return canal


TITRE_COMPTE = "Telechargement - le compte"
TITRE_OPTIONS = "Telechargement - les options"


def _embed_compte(username: str = "", combien: int = 30):
    """L embed du premier panneau, avec ou sans compte actif."""
    import discord as _d
    if username:
        return _d.Embed(
            title=TITRE_COMPTE,
            description=f"Compte actif : **@{username}**  (au plus {combien})"
                        + chr(10) + "Clique pour en changer.",
            color=_d.Color.blurple())
    return _d.Embed(
        title=TITRE_COMPTE,
        description="Clique et entre le pseudo du compte a descendre."
                    + chr(10) + "Il reste retenu jusqu a ce que tu en changes.",
        color=_d.Color.blurple())


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
        username = brut.split("/")[-1].lstrip("@").split("?")[0]
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
        self.cog.choix[inter.user.id] = (username, n)

        # Le panneau AFFICHE le compte actif. Chaque VA a son propre salon
        # -download : il n y a donc qu une personne par panneau, et l afficher
        # ne revele rien a personne d autre.
        # ON REPOND D ABORD, ON EDITE ENSUITE.
        #
        # Discord n accorde que TROIS SECONDES pour la premiere reponse a une
        # interaction. inter.message.edit() est un appel reseau : le placer
        # avant l accuse de reception faisait expirer le delai des que l API
        # trainait un peu, et la personne voyait « n a pas repondu a temps »
        # alors que sa saisie avait bien ete enregistree (constate le 27/08).
        #
        # Une fois l interaction acquittee, l edition peut prendre le temps
        # qu elle veut sans rien casser.
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

    async def _lancer(self, inter, quoi, libelle):
        garde = self.cog.choix.get(inter.user.id)
        if not garde:
            await inter.response.send_message(
                "Entre d'abord un compte dans le panneau du dessus.",
                ephemeral=True)
            return
        username, n = garde
        cible = salon_de_livraison(inter.channel)
        await inter.response.send_message(
            f"**@{username}** - {libelle} : ca part dans {cible.mention}.",
            ephemeral=True)
        await self.cog.livrer(
            cible, username, n,
            avatar=quoi in ("tout", "pp"),
            bio=quoi in ("tout", "bio"),
            photos=quoi in ("tout", "photos"),
            reels=quoi in ("tout", "reels", "top"),
            par_vues=(quoi == "top"))

    @discord.ui.button(label="Tout", style=discord.ButtonStyle.success,
                       custom_id="dl:tout", row=0)
    async def b_tout(self, inter, _):
        await self._lancer(inter, "tout", "tout")

    @discord.ui.button(label="Photo de profil", style=discord.ButtonStyle.primary,
                       custom_id="dl:pp", row=0)
    async def b_pp(self, inter, _):
        await self._lancer(inter, "pp", "la photo de profil")

    @discord.ui.button(label="Bio", style=discord.ButtonStyle.primary,
                       custom_id="dl:bio", row=0)
    async def b_bio(self, inter, _):
        await self._lancer(inter, "bio", "la bio")

    @discord.ui.button(label="Posts photo", style=discord.ButtonStyle.primary,
                       custom_id="dl:photos", row=1)
    async def b_photos(self, inter, _):
        await self._lancer(inter, "photos", "les posts photo")

    @discord.ui.button(label="Reels", style=discord.ButtonStyle.primary,
                       custom_id="dl:reels", row=1)
    async def b_reels(self, inter, _):
        await self._lancer(inter, "reels", "les reels")

    @discord.ui.button(label="Top reels", style=discord.ButtonStyle.secondary,
                       custom_id="dl:top", row=1)
    async def b_top(self, inter, _):
        await self._lancer(inter, "top", "les reels les plus vus")


async def poser_panneaux(cog, canal, epingler: bool = True):
    """Pose les DEUX panneaux dans un salon. Rend le nombre de messages poses.

    Les anciens panneaux du bot sont retires d'abord : un message Discord est
    fige, donc une evolution du menu laisse sinon un panneau perime a cote du
    neuf, et personne ne sait lequel fait foi.
    """
    import discord as _d
    poses = 0
    # On vide ce que LE BOT a poste : panneaux perimes, notices d'epinglage,
    # comptes rendus d'un ancien telechargement. Le salon ne doit porter que
    # les deux panneaux, sinon ils sortent de l'ecran et plus personne ne les
    # trouve. On ne touche pas aux messages des humains.
    moi = getattr(getattr(cog.bot, "user", None), "id", 0)
    try:
        await canal.purge(limit=200, check=lambda m: m.author.id == moi)
    except Exception:
        # Purge refusee (permission manquante) : on retire au moins les
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

    e1 = _embed_compte()
    e2 = _d.Embed(
        title=TITRE_OPTIONS,
        description="Choisis ce que tu veux de ce compte."
                    + chr(10) + chr(10) +
                    "Ordre d'envoi : photo de profil, bio, posts, puis reels."
                    + chr(10) + "Chaque fichier part des qu'il est pret.",
        color=_d.Color.green())
    for emb, vue in ((e1, PanneauCompte(cog)), (e2, PanneauOptions(cog))):
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
                    await canal.purge(
                        limit=5,
                        check=lambda m: (m.type == _d.MessageType.pins_add
                                         or (m.author.id == moi and not m.embeds)))
                except Exception:
                    pass
        except Exception:
            pass
    return poses


async def setup(bot: commands.Bot):
    await bot.add_cog(Telechargement(bot))
