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

    # ---------------------------------------------------------------- envoi --

    async def livrer(self, canal, username: str, combien: int,
                     avatar: bool, bio: bool, photos: bool, reels: bool,
                     par_vues: bool = False):
        dossier = DOWNLOAD_DIR

        if avatar or bio:
            fiche = await asyncio.to_thread(profil_entete_sync, username)
            if not fiche:
                await canal.send(
                    f"Fiche de @{username} illisible (cookies expires ?). "
                    "Je continue avec les publications.")
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
                list_profile_posts_sync, username, combien)
        except Exception as e:
            await canal.send(f"Erreur en lisant le profil : {str(e)[:1500]}")
            return
        if not posts:
            await canal.send("Aucun post trouve sur ce profil.")
            return

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

                fichier = dossier / f"{uuid.uuid4().hex}.{ext}"
                try:
                    await asyncio.to_thread(
                        download_sync, post["url"], str(fichier))
                except Exception as e:
                    await canal.send(f"#{idx} - echec : {str(e)[:300]}")
                    await canal.send(post["url"])
                    if legende:
                        await canal.send(legende[:1900])
                    continue

                if not fichier.exists():
                    await canal.send(post["url"])
                    await canal.send(legende[:1900] or "Pas de description.")
                    continue

                taille_mo = fichier.stat().st_size / (1024 * 1024)
                if taille_mo > 24.5:
                    # Discord refuse au-dela : on donne le lien plutot que rien.
                    await canal.send(f"#{idx} - {taille_mo:.1f} Mo, trop lourd "
                                     "pour Discord")
                    await canal.send(post["url"])
                else:
                    await canal.send(
                        content=f"#{idx}" + (f" - {date_str}" if date_str else ""),
                        file=discord.File(str(fichier)))
                await canal.send(legende[:1900] or "Pas de description.")

        await canal.send(f"Termine pour @{username}.")

    # ----------------------------------------------------------------- menu --

    async def ouvrir_menu(self, interaction: discord.Interaction):
        """Ouvre la fenetre du pseudo. Appele par le menu central."""
        await interaction.response.send_modal(ModalProfil(self))

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


class ModalProfil(discord.ui.Modal, title="Telecharger un profil"):
    """Premier menu : QUI. Rien d'autre n'est demande ici.

    Separer le "qui" du "quoi" n'est pas cosmetique : on ne sait pas toujours
    ce qu'on veut d'un compte avant de voir de qui il s'agit, et le nombre a
    descendre depend de ce qu'on decouvre.
    """

    pseudo = discord.ui.TextInput(
        label="Pseudo Instagram",
        placeholder="sky.ards  ou  https://instagram.com/sky.ards",
        required=True, max_length=120)

    def __init__(self, cog: "Telechargement"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, inter: discord.Interaction):
        brut = str(self.pseudo).strip().rstrip("/")
        username = brut.split("/")[-1].lstrip("@").split("?")[0]
        if not username:
            await inter.response.send_message("Pseudo invalide.", ephemeral=True)
            return
        vue = MenuContenu(self.cog, username)
        await inter.response.send_message(
            f"**@{username}** — que veux-tu descendre ?",
            view=vue, ephemeral=True)


class MenuContenu(discord.ui.View):
    """Second menu : QUOI, et COMBIEN.

    Deux listes deroulantes plutot que dix boutons : le contenu et la quantite
    sont deux questions distinctes, et les combiner en boutons donnerait une
    grille illisible (tous les reels, top 10, top 20, top 50, les posts...).

    Le bouton Lancer n'agit qu'une fois : deux clics lanceraient deux
    telechargements du meme compte en parallele, et le salon deviendrait
    illisible.
    """

    def __init__(self, cog: "Telechargement", username: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.username = username
        self.quoi = "tout"
        self.combien = 30

    @discord.ui.select(
        placeholder="Quoi ?",
        options=[
            discord.SelectOption(label="Tout", value="tout", emoji="\U0001F4E6",
                                 description="photo de profil, bio, posts, reels"),
            discord.SelectOption(label="Photo de profil", value="pp", emoji="\U0001F464"),
            discord.SelectOption(label="Bio", value="bio", emoji="\U0001F4AC"),
            discord.SelectOption(label="Posts photo", value="photos", emoji="\U0001F5BC"),
            discord.SelectOption(label="Reels", value="reels", emoji="\U0001F3AC",
                                 description="les plus recents"),
            discord.SelectOption(label="Top reels", value="top", emoji="\U0001F525",
                                 description="les plus vus"),
        ])
    async def s_quoi(self, inter: discord.Interaction, select: discord.ui.Select):
        self.quoi = select.values[0]
        await inter.response.edit_message(content=self._resume(), view=self)

    @discord.ui.select(
        placeholder="Combien ?",
        options=[discord.SelectOption(label=f"{n}", value=str(n))
                 for n in (10, 15, 20, 30, 50, 100)])
    async def s_combien(self, inter: discord.Interaction, select: discord.ui.Select):
        self.combien = int(select.values[0])
        await inter.response.edit_message(content=self._resume(), view=self)

    def _resume(self) -> str:
        libelle = {"tout": "tout", "pp": "la photo de profil", "bio": "la bio",
                   "photos": "les posts photo", "reels": "les reels",
                   "top": "les reels les plus vus"}[self.quoi]
        if self.quoi in ("pp", "bio"):
            return f"**@{self.username}** — {libelle}"
        return f"**@{self.username}** — {libelle}, au plus {self.combien}"

    @discord.ui.button(label="Lancer", style=discord.ButtonStyle.success, row=2)
    async def b_lancer(self, inter: discord.Interaction, _):
        for enfant in self.children:
            enfant.disabled = True
        await inter.response.edit_message(content=self._resume() + " — en cours...",
                                          view=self)
        q = self.quoi
        await self.cog.livrer(
            inter.channel, self.username, self.combien,
            avatar=q in ("tout", "pp"),
            bio=q in ("tout", "bio"),
            photos=q in ("tout", "photos"),
            reels=q in ("tout", "reels", "top"),
            par_vues=(q == "top"))


class Panneau(discord.ui.View):
    """Le panneau qui reste dans le salon."""

    def __init__(self, cog: "Telechargement"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Telecharger un profil",
                       style=discord.ButtonStyle.success,
                       custom_id="panneau_telechargeur_ig")
    async def b_ouvrir(self, inter, _):
        await inter.response.send_modal(ModalProfil(self.cog))


async def setup(bot: commands.Bot):
    await bot.add_cog(Telechargement(bot))
