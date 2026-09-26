# -*- coding: utf-8 -*-
"""Salon « all-banger » : chaque banger dont la vidéo a été récupérée, reposté
tel quel — la vidéo et sa description, rien d'autre.

La demande du propriétaire (26/09/2026) : « toutes les vidéos que tu arrives à
télécharger au niveau des bangers, tu les retélécharges ici, mais uniquement
celles que tu as réussi à télécharger. Juste la vidéo et la description, pas
besoin du nom du VA. OK vidéo, c'est bon, on passe à la suivante. »

Pourquoi un module à part, et pas une case de plus dans bangers.json :
bangers.examiner() relit et réécrit TOUT ce registre à chaque compte scrapé,
depuis quatre threads à la fois, sans verrou entre la lecture et l'écriture.
Un état d'envoi rangé là pouvait être effacé par un examen parti une seconde
plus tôt — et un envoi oublié, c'est un banger posté deux fois. Ici, un seul
fichier, un seul verrou, et personne d'autre n'y écrit.

Ce qui coûte, et ce qui ne coûte pas :
  - le lien `video_url` vient du scrape HikerAPI DÉJÀ PAYÉ ; le télécharger
    est un simple GET sur le CDN d'Instagram, gratuit ;
  - aucun appel HikerAPI de plus, aucun Apify (le propriétaire refuse Apify,
    cf. la mémoire « pas-d-apify »). Si le lien a expiré, on attend le scrape
    suivant, qui en apporte un neuf — UNE fois, pas davantage.

Le chemin d'un banger :
  video  → (téléchargé)  → pret → envoi → envoye
        ↘ 2 échecs ↘ echec       ↘ trop_lourd / echec_envoi
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import queue
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from typing import Callable, Dict, List, Optional

import safe_json

import bangers as _bg

log = logging.getLogger("vabot.all_banger")

_ICI = pathlib.Path(__file__).resolve().parent

#: Le registre d'envoi. Séparé de bangers.json : voir l'en-tête.
FICHIER = _ICI / "data" / "bangers_all.json"

#: Le cache vidéo des Trends. Un reel qui y est déjà n'a pas à être
#: retéléchargé : on le COPIE (le démon le purge à 31 jours, l'archive des
#: bangers doit survivre à ça — cf. bangers.DOSSIER).
DOSSIER_CACHE_INSTA = _ICI / "data" / "insta" / "videos"

#: Le serveur où vit le salon. Celui de la publication quotidienne : Youl4b.
GUILD_ID = _bg.GUILD_ID

#: Le nom du salon, tel que le propriétaire l'a écrit. Il est comparé une fois
#: réduit à ses lettres et chiffres (cf. est_salon_all_banger).
NOM_SALON = "all-banger"

#: LA détection + UNE relance au scrape suivant. « Uniquement celles que tu
#: as réussi » : au-delà, on renonce, et on le dit.
ESSAIS_MAX = 2

#: Un banger qu'aucun scrape n'a revu en trois jours n'apportera plus de lien
#: neuf : il resterait « en attente » pour toujours, sans que personne sache
#: pourquoi. On le classe en échec, avec la raison.
ATTENTE_LIEN_MAX_SEC = 3 * 86400

#: Refus nets de Discord (4xx) tolérés avant de renoncer à un banger. Un 403
#: (droits retirés) frapperait tous les messages : on s'arrête au premier et
#: on reprend au tour suivant, sans marteler.
ENVOIS_MAX = 5

#: « OK vidéo, c'est bon, on passe à la suivante » : une à la fois, avec un
#: court répit. Discord tolère 5 messages / 5 s par salon ; un envoi de vidéo
#: dure déjà plusieurs secondes, ce délai ne sert qu'à ne pas enchaîner à vide.
DELAI_ENTRE_MESSAGES = 4.0

#: Une intention d'envoi plus jeune que ça peut encore être en vol (envoi
#: lent, délai du fil dépassé) : on ne la vérifie pas tout de suite, sinon on
#: conclurait « absent » pendant que Discord reçoit encore le fichier.
DELAI_VERIFICATION = 120.0

#: Le tour d'horizon quand rien n'arrive : reprise des envois en attente
#: (salon créé entre-temps, bot reconnecté, redémarrage).
PERIODE_SEC = 600.0

#: Limite d'envoi de Discord quand le serveur ne la donne pas : 10 Mio, celle
#: d'un serveur sans boost (niveau 0 ou 1).
LIMITE_DEFAUT = 10 * 1024 * 1024

#: Au-delà, la description part en fichier .txt : un message Discord ne porte
#: pas plus de 2000 signes.
MAX_TEXTE = 2000

_SC_OK = re.compile(r"^[A-Za-z0-9_-]{5,30}$")

#: Un seul verrou pour toutes les lectures-modifications-écritures du
#: registre : quatre threads de scrape et le fil d'envoi y écrivent.
_VERROU = threading.RLock()

#: La file des téléchargements, et ce qui y est déjà : un reel publié en
#: collaboration apparaît sur deux comptes scrapés en même temps.
FILE: "queue.Queue[dict]" = queue.Queue()
_EN_COURS: set = set()
_TRAVAILLEUR: Dict[str, object] = {"thread": None}

#: Les messages déjà journalisés une fois (salon absent…). Remis à zéro dès
#: que la cause disparaît, pour qu'une rechute se voie aussi.
_DITS: set = set()


# ---------------------------------------------------------------- registre --

def _vide() -> dict:
    return {"schema": 1, "reels": {}}


def charger() -> dict:
    d = safe_json.load(FICHIER, None)
    if not isinstance(d, dict):
        return _vide()
    if not isinstance(d.get("reels"), dict):
        d["reels"] = {}
    return d


def _ecrire(d: dict) -> bool:
    return safe_json.write(FICHIER, d)


def entree(shortcode: str) -> dict:
    return dict((charger().get("reels") or {}).get(str(shortcode or ""), {}))


def nonce_de(shortcode: str) -> str:
    """Le nonce Discord de ce banger : toujours le même pour le même reel.

    discord.py envoie `enforce_nonce` avec tout nonce : Discord rend alors le
    message déjà créé au lieu d'en créer un second si le même nonce revient
    dans les minutes qui suivent. 25 signes au plus.
    """
    return hashlib.sha256(("all-banger:" + str(shortcode)).encode()).hexdigest()[:24]


def _empreinte_lien(url: str) -> str:
    """De quoi reconnaître un lien DÉJÀ essayé, sans garder l'URL signée."""
    return hashlib.sha1(str(url or "").encode()).hexdigest()[:12] if url else ""


def _dire_une_fois(cle: str, message: str, niveau=logging.WARNING) -> None:
    if cle in _DITS:
        return
    _DITS.add(cle)
    log.log(niveau, message)


# --------------------------------------------------------------- détection --

def signaler(nouveaux, reels, maintenant: float = 0.0) -> List[dict]:
    """Appelé à chaque scrape d'un compte, APRÈS bangers.examiner().

    `nouveaux` : les fiches que l'examen vient d'ouvrir. Seules celles-là
    entrent — pas de rattrapage du passé (cf. rattrapage()). Les fiches
    « muettes » (plus de 30 jours à la détection) et les « essais » du bouton
    de test restent dehors : ce ne sont pas des bangers du moment.

    `reels` : la liste BRUTE du scrape, qui porte le `video_url` frais. Elle
    sert aussi à la relance : un banger dont le premier téléchargement a
    échoué retrouve ici un lien neuf.

    Rend les téléchargements à faire. Aucun réseau ici : ce code tourne dans
    le pool de scrape, où une seconde perdue l'est sept cents fois.
    """
    now = float(maintenant or time.time())
    par_sc = {}
    for r in (reels or []):
        if isinstance(r, dict):
            sc = str(r.get("shortcode") or "").strip()
            if _SC_OK.match(sc):
                par_sc[sc] = r
    travaux: List[dict] = []
    with _VERROU:
        d = charger()
        reg = d["reels"]
        change = False
        for f in (nouveaux or []):
            if not isinstance(f, dict):
                continue
            sc = str(f.get("shortcode") or "").strip()
            if not _SC_OK.match(sc) or sc in reg:
                continue
            if f.get("muet") or f.get("essai"):
                continue
            reg[sc] = {"etat": "video", "essais": 0, "detecte_le": int(now)}
            change = True
        for sc, r in par_sc.items():
            e = reg.get(sc)
            if not isinstance(e, dict) or e.get("etat") != "video" or sc in _EN_COURS:
                continue
            url = str(r.get("video_url") or "").strip()
            if not url and not _copie_locale(sc):
                # Un scrape SANS lien (source de repli qui ne le donne pas)
                # n'est pas une relance : on ne brûle pas l'essai, on attend un
                # scrape qui en porte un. La raison est gardée pour le bilan.
                if e.get("raison") != "scrape_sans_lien":
                    e["raison"] = "scrape_sans_lien"
                    change = True
                continue
            # LA RELANCE VEUT UN LIEN NEUF. Un scrape qui rend le même lien
            # (relevé repris du cache après un scrape vide, cf. _write_cache)
            # brûlerait la seule relance sur un lien déjà mort.
            if e.get("essais") and url and _empreinte_lien(url) == e.get("lien_essaye"):
                continue
            _EN_COURS.add(sc)
            travaux.append({"shortcode": sc, "video_url": url,
                            "description": str(r.get("caption") or "")})
        if change and not _ecrire(d):
            # Sans registre écrit, pas de téléchargement : un banger posté
            # sans trace serait reposté au redémarrage.
            for t in travaux:
                _EN_COURS.discard(t["shortcode"])
            log.error("[all-banger] registre non enregistré : détection remise au scrape suivant")
            return []
    return travaux


# ---------------------------------------------------------- téléchargement --

def _copie_locale(sc: str) -> bool:
    """La vidéo est-elle déjà sur le disque (archive ou cache des Trends) ?"""
    if _bg.video_presente(sc):
        return True
    try:
        c = DOSSIER_CACHE_INSTA / (sc + ".mp4")
        return c.is_file() and c.stat().st_size > 1024
    except OSError:
        return False


def _est_une_video(chemin: pathlib.Path) -> bool:
    """Un vrai fichier vidéo, pas une page d'erreur ni un reste d'échec.

    ffprobe quand il est là (comme bangers.preparer_fiches). Sans lui, la
    signature MP4 (« ftyp » en tête) : le CDN d'Instagram ne sert que ça, et
    une page HTML de refus ne la porte jamais.
    """
    try:
        if chemin.stat().st_size <= 1024:
            return False
    except OSError:
        return False
    if shutil.which("ffprobe"):
        try:
            p = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_type", "-of", "json", str(chemin)],
                capture_output=True, text=True, timeout=30)
            return p.returncode == 0 and bool(json.loads(p.stdout or "{}").get("streams"))
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
    try:
        with open(chemin, "rb") as fh:
            return b"ftyp" in fh.read(64)
    except OSError:
        return False


def _octets_cdn(url: str, info: dict) -> Optional[bytes]:
    """Le téléchargeur par défaut : un GET sur le CDN, sans clé ni cookie."""
    import veille_telegram as _vt
    return _vt.download_video_bytes(url, timeout=60, info=info)


def telecharger(shortcode: str, video_url: str,
                telecharger_octets: Optional[Callable] = None) -> tuple:
    """Met la vidéo dans l'archive des bangers. Rend (ok, raison, source).

    Trois sources, de la moins chère à la plus chère — les trois gratuites :
      archive  déjà dans data/bangers/ (la publication du matin l'a descendue) ;
      cache    déjà dans data/insta/videos/ : copie, jamais déplacement ;
      cdn      le lien du scrape.
    Le fichier n'entre dans l'archive qu'une fois reconnu comme vidéo, par un
    remplacement atomique : un arrêt en plein téléchargement ne laisse jamais
    un mp4 tronqué qui passerait pour une archive.
    """
    sc = str(shortcode or "").strip()
    if not _SC_OK.match(sc):
        return False, "shortcode_illisible", ""
    cible = _bg.chemin_video(sc)
    if _bg.video_presente(sc):
        # On ne remplace JAMAIS une archive existante : le site n'efface pas
        # un média. Illisible, elle est signalée, pas écrasée.
        return ((True, "", "archive") if _est_une_video(cible)
                else (False, "archive_illisible", "archive"))
    try:
        _bg.DOSSIER.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"dossier:{type(e).__name__}", ""
    # Un suffixe qui n'est PAS .mp4 : un glob("*.mp4") (rattrapage, bilans)
    # ne doit jamais prendre un tampon pour une vidéo.
    tampon = cible.with_name(sc + ".all-banger.part")
    raison, source = "pas_de_lien", ""
    essais = []
    cache = DOSSIER_CACHE_INSTA / (sc + ".mp4")
    try:
        if cache.is_file() and cache.stat().st_size > 1024:
            essais.append("cache")
    except OSError:
        pass
    if video_url:
        essais.append("cdn")
    for src in essais:
        source = src
        try:
            if src == "cache":
                shutil.copyfile(cache, tampon)
            else:
                info: dict = {}
                octets = (telecharger_octets or _octets_cdn)(video_url, info)
                if not octets:
                    raison = str(info.get("reason") or "telechargement_vide")[:80]
                    continue
                tampon.write_bytes(octets)
            if _est_une_video(tampon):
                os.replace(str(tampon), str(cible))
                return True, "", src
            raison = "fichier_video_invalide"
        except Exception as e:                                # noqa: BLE001
            raison = f"{src}:{type(e).__name__}"
        finally:
            try:
                if tampon.exists():
                    tampon.unlink()
            except OSError:
                pass
    return False, raison, source


def _ecrire_description(sc: str, texte: str) -> None:
    """Garde la description à côté de la vidéo — la plus longue connue.

    Le scrape la tronque à 280 signes ; la publication du matin, elle, peut
    avoir déposé le texte complet. On n'écrase donc jamais par plus court.
    """
    texte = str(texte or "").strip()
    if not texte:
        return
    chemin = _bg.chemin_description(sc)
    try:
        ancien = chemin.read_text(encoding="utf-8") if chemin.exists() else ""
    except (OSError, ValueError):       # ValueError : fichier pas en UTF-8
        ancien = ""
    if len(texte) > len(ancien.strip()):
        safe_json.write_text(chemin, texte, backup=False)


def traiter_job(job: dict, telecharger_octets: Optional[Callable] = None,
                maintenant: float = 0.0) -> Optional[bool]:
    """Un téléchargement de la file. Rend True/False, ou None s'il n'y avait
    plus rien à faire (déjà traité entre-temps)."""
    sc = str((job or {}).get("shortcode") or "")
    url = str((job or {}).get("video_url") or "")
    try:
        with _VERROU:
            e = (charger().get("reels") or {}).get(sc)
            if not isinstance(e, dict) or e.get("etat") != "video":
                return None
        ok, raison, source = telecharger(sc, url, telecharger_octets)
        if ok:
            _ecrire_description(sc, job.get("description") or "")
        now = float(maintenant or time.time())
        with _VERROU:
            d = charger()
            e = d["reels"].get(sc)
            if not isinstance(e, dict) or e.get("etat") != "video":
                return None
            e["essais"] = int(e.get("essais") or 0) + 1
            if url:
                e["lien_essaye"] = _empreinte_lien(url)
            e["source"] = source
            if ok:
                e.update(etat="pret", video_le=int(now))
                e.pop("raison", None)
                try:
                    e["taille"] = _bg.chemin_video(sc).stat().st_size
                except OSError:
                    pass
            else:
                e["raison"] = raison
                if e["essais"] >= ESSAIS_MAX:
                    e.update(etat="echec", echec_le=int(now))
            _ecrire(d)
        if ok:
            log.info(f"[all-banger] {sc} : vidéo récupérée ({source}), prête à poster")
        elif e.get("etat") == "echec":
            log.warning(f"[all-banger] {sc} : vidéo NON récupérée après {e['essais']} essais "
                        f"({raison}) — rien ne sera posté")
        else:
            log.info(f"[all-banger] {sc} : vidéo non récupérée ({raison}), "
                     f"une relance au prochain scrape")
        return ok
    finally:
        _EN_COURS.discard(sc)


def expirer(maintenant: float = 0.0) -> int:
    """Classe en échec les bangers qui attendent un lien depuis trop longtemps."""
    now = float(maintenant or time.time())
    n = 0
    with _VERROU:
        d = charger()
        for sc, e in d["reels"].items():
            if (isinstance(e, dict) and e.get("etat") == "video" and sc not in _EN_COURS
                    and now - int(e.get("detecte_le") or 0) > ATTENTE_LIEN_MAX_SEC):
                e.update(etat="echec", echec_le=int(now),
                         raison=e.get("raison") or "plus_revu_dans_un_scrape")
                n += 1
        if n:
            _ecrire(d)
    if n:
        log.warning(f"[all-banger] {n} banger(s) sans lien neuf depuis 3 jours : "
                    f"classés en échec, rien ne sera posté pour eux")
    return n


# ------------------------------------------------------------------ salon --

#: Sosies cyrilliques d'usage courant (cf. _US_CONFUSABLES de cogs/welcome.py) :
#: un « а » russe tapé par erreur est invisible à l'écran.
_SOSIES = str.maketrans({"а": "a", "е": "e", "о": "o", "с": "c", "р": "p",
                         "х": "x", "у": "y", "і": "i", "ѕ": "s", "ј": "j",
                         "ԁ": "d", "ь": "b", "к": "k", "м": "m", "т": "t",
                         "н": "h", "в": "b"})


def _squelette(nom: str) -> str:
    """Le nom d'un salon réduit à ses lettres et chiffres ASCII.

    Discord et les humains décorent : « 🔥・all-banger », « │all‑banger »
    (tiret insécable tapé sur iPhone), « ALL_BANGERS ». Même idée que
    _us_norm de cogs/welcome.py, poussée jusqu'au bout : tout ce qui n'est
    pas une lettre ou un chiffre disparaît.
    """
    t = unicodedata.normalize("NFKC", str(nom or "")).casefold().translate(_SOSIES)
    t = "".join(c for c in unicodedata.normalize("NFD", t)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", t)


def est_salon_all_banger(nom: str) -> bool:
    """ÉGALITÉ, pas inclusion : « tall-banger » ou « all-banger-archive » ne
    sont pas ce salon, et y poster serait pire que ne rien poster."""
    return _squelette(nom) in ("allbanger", "allbangers")


def trouver_salon(guild):
    """Le salon texte « all-banger » du serveur, ou None."""
    salons = [c for c in (getattr(guild, "text_channels", None) or [])
              if est_salon_all_banger(getattr(c, "name", ""))]
    if not salons:
        return None
    salons.sort(key=lambda c: (getattr(c, "position", 0) or 0, getattr(c, "id", 0) or 0))
    if len(salons) > 1:
        _dire_une_fois("plusieurs", "[all-banger] plusieurs salons « all-banger » sur le "
                       f"serveur : envoi dans #{salons[0].name} ({salons[0].id})")
    if getattr(salons[0], "id", None) == _bg.CHANNEL_ID:
        _dire_une_fois("meme_salon", "[all-banger] le salon « all-banger » est AUSSI celui "
                       "de la publication du matin : les bangers de Jessye y passeront deux fois")
    return salons[0]


# ---------------------------------------------------------------- message --

def description_de(shortcode: str) -> str:
    """La description la plus complète connue pour ce reel.

    Trois endroits peuvent la porter : le fichier voisin de la vidéo, la
    fiche du registre des bangers, le détail de la publication du matin. Ce
    sont des versions du MÊME texte, dont certaines tronquées : la plus
    longue est la bonne.
    """
    sc = str(shortcode or "")
    textes = []
    try:
        p = _bg.chemin_description(sc)
        if p.exists():
            textes.append(p.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        pass
    try:
        textes.append(str(_bg.fiche(sc).get("description") or ""))
    except Exception:                                         # noqa: BLE001
        pass
    try:
        textes.append(str(_bg.lire_details(sc).get("description") or ""))
    except Exception:                                         # noqa: BLE001
        pass
    textes = [t.strip() for t in textes if t and t.strip()]
    return max(textes, key=len) if textes else ""


_LIEN = re.compile(r"https?://\S+")


def _echapper(texte: str) -> str:
    """Neutralise la mise en forme Discord sans rien changer au texte affiché.

    « #mon_tag et #ton_tag » s'afficherait en italique entre les deux tirets
    bas, et le texte COPIÉ depuis Discord les perdrait. Discord lit « \\x »
    comme « x » pour toute ponctuation : on échappe donc chaque signe de mise
    en forme, et ceux de début de ligne (titre, citation, liste) seulement
    là. Pas discord.utils.escape_markdown : sur une ligne « ␣␣- », il pose la
    barre oblique devant les ESPACES, et elle s'affiche.
    Les liens restent intacts : une barre dans une URL la casserait.
    """
    def _brut(t: str) -> str:
        t = re.sub(r"([\\*_~|`\[\]])", r"\\\1", t)
        return re.sub(r"(?m)^([ \t]*)([#>\-])", r"\1\\\2", t)
    morceaux, pos = [], 0
    for m in _LIEN.finditer(texte):
        morceaux.append(_brut(texte[pos:m.start()]))
        morceaux.append(m.group(0))
        pos = m.end()
    morceaux.append(_brut(texte[pos:]))
    return "".join(morceaux)


def contenu_message(description: str) -> tuple:
    """(texte du message, texte à joindre en .txt) — l'un ou l'autre.

    Au-delà de 2000 signes (une fois échappé), Discord refuse le message :
    la description part alors, complète et telle quelle, en fichier joint.
    """
    brut = str(description or "").strip()
    if not brut:
        return None, ""
    affiche = _echapper(brut)
    if len(affiche) > MAX_TEXTE:
        return None, brut
    return affiche, ""


async def retrouver(client, salon, shortcode: str, depuis: float):
    """Le message de ce banger, s'il a été posté après `depuis`.

    Deux marques, dont une suffit : le nonce (que Discord ne renvoie pas
    toujours à la relecture) et le NOM de la pièce jointe, `<shortcode>.mp4`,
    qui, lui, reste.
    """
    from datetime import datetime, timezone
    nonce = nonce_de(shortcode)
    nom = f"{shortcode}.mp4"
    apres = datetime.fromtimestamp(max(0.0, float(depuis or 0) - 60), timezone.utc)
    moi = getattr(getattr(client, "user", None), "id", None)
    async for m in salon.history(limit=200, after=apres):
        if getattr(getattr(m, "author", None), "id", None) != moi:
            continue
        if str(getattr(m, "nonce", "") or "") == nonce or any(
                getattr(a, "filename", "") == nom for a in (getattr(m, "attachments", None) or [])):
            return m
    return None


async def envoyer(client, shortcode: str, e: dict, guild_id: int = 0) -> dict:
    """Poste UN banger. Tourne dans la boucle du bot.

    Rend un seul de ces cas, que traiter_envois() sait appliquer :
      {"message_id", "channel_id"}      posté (ou retrouvé : "retrouve")
      {"absent": True}                  vérification : rien dans le salon
      {"salon_absent": raison}          rien envoyé, on attendra le salon
      {"trop_lourd", "taille", "limite"}
      {"echec": raison}                 définitif (vidéo disparue)
      {"refuse": raison, "status"}      Discord a dit non (4xx) : rien créé
      {"incertain": raison}             peut-être parti : on vérifiera
    """
    import discord
    sc = str(shortcode or "")
    guild = client.get_guild(int(guild_id or GUILD_ID))
    if guild is None:
        return {"salon_absent": "serveur Youl4b hors de portée du bot"}
    salon = trouver_salon(guild)
    if salon is None:
        return {"salon_absent": f"aucun salon « {NOM_SALON} » sur Youl4b"}
    moi = getattr(guild, "me", None)
    if moi is not None and hasattr(salon, "permissions_for"):
        droits = salon.permissions_for(moi)
        if not (getattr(droits, "send_messages", True) and getattr(droits, "attach_files", True)):
            return {"salon_absent": f"le bot n'a pas le droit d'écrire ou de joindre un "
                                    f"fichier dans #{salon.name}"}
    if e.get("verifier"):
        try:
            trouve = await retrouver(client, salon, sc, float(e.get("intention_le") or 0))
        except discord.HTTPException as ex:
            # Sans l'historique, on ne peut pas savoir si le message est parti :
            # on ne renvoie PAS à l'aveugle, on attend (et on le dit une fois).
            return {"salon_absent": f"relecture de #{salon.name} impossible "
                                    f"(http_{getattr(ex, 'status', 0)}) : droit "
                                    f"« Voir les anciens messages » ?"}
        if trouve is not None:
            return {"message_id": trouve.id, "channel_id": salon.id, "retrouve": True}
        return {"absent": True, "channel_id": salon.id}
    fichier = _bg.chemin_video(sc)
    if not _bg.video_presente(sc):
        return {"echec": "video_disparue"}
    taille = fichier.stat().st_size
    limite = int(getattr(guild, "filesize_limit", 0) or LIMITE_DEFAUT)
    if taille > limite:
        # Aucune compression simple dans le dépôt : celle de video_transform
        # change l'image (c'est son but), ce n'est plus la vidéo d'origine.
        return {"trop_lourd": True, "taille": taille, "limite": limite}
    texte, joint = contenu_message(description_de(sc))
    fichiers = []
    try:
        fichiers.append(discord.File(str(fichier), filename=f"{sc}.mp4"))
        if joint:
            import io
            fichiers.append(discord.File(io.BytesIO(joint.encode("utf-8")),
                                         filename=f"{sc}_description.txt"))
    except Exception as ex:                                   # noqa: BLE001
        for f in fichiers:
            f.close()
        return {"refuse": f"fichier:{type(ex).__name__}", "status": 0}
    try:
        # RIEN D'AUTRE que la vidéo et la description : ni VA, ni compte, ni
        # vues (demande expresse). Aucune mention ne notifie, et un lien dans
        # la légende ne déroule pas d'aperçu sous la vidéo.
        m = await salon.send(content=texte, files=fichiers, nonce=nonce_de(sc),
                             allowed_mentions=discord.AllowedMentions.none(),
                             suppress_embeds=True)
    except discord.HTTPException as ex:
        status = int(getattr(ex, "status", 0) or 0)
        if status == 413:
            return {"trop_lourd": True, "taille": taille, "limite": limite}
        if 400 <= status < 500:
            return {"refuse": f"http_{status}", "status": status}
        return {"incertain": f"http_{status}"}
    except Exception as ex:                                   # noqa: BLE001
        return {"incertain": type(ex).__name__}
    finally:
        for f in fichiers:
            f.close()
    return {"message_id": m.id, "channel_id": salon.id}


def poster_via_bot(bot, shortcode: str, e: dict, timeout: float = 300.0) -> dict:
    """Passe envoyer() à la boucle du bot depuis le fil d'envoi."""
    import asyncio
    import concurrent.futures
    if bot is None or not bot_pret(bot):
        return {"salon_absent": "bot Discord pas prêt"}
    try:
        fut = asyncio.run_coroutine_threadsafe(envoyer(bot, shortcode, e), bot.loop)
        return fut.result(timeout=timeout) or {"incertain": "reponse_vide"}
    except concurrent.futures.TimeoutError:
        # L'envoi peut continuer après ce délai : on vérifiera dans le salon.
        return {"incertain": "delai_depasse"}
    except Exception as ex:                                   # noqa: BLE001
        return {"incertain": type(ex).__name__}


def bot_pret(bot) -> bool:
    try:
        loop = getattr(bot, "loop", None)
        return bool(bot is not None and bot.is_ready() and loop is not None
                    and loop.is_running())
    except Exception:                                         # noqa: BLE001
        return False


# ---------------------------------------------------------------- envois --

def a_poster() -> List[str]:
    """Les bangers à poster ou à vérifier, le plus anciennement détecté d'abord."""
    reg = charger().get("reels") or {}
    out = [(int(e.get("detecte_le") or 0), sc) for sc, e in reg.items()
           if isinstance(e, dict) and e.get("etat") in ("pret", "envoi")]
    return [sc for _, sc in sorted(out)]


def traiter_envois(poster: Callable, dormir: Callable = time.sleep,
                   delai: Optional[float] = None, maintenant: float = 0.0) -> dict:
    """Poste, un par un, les bangers prêts. Rend le bilan du passage.

    L'INTENTION EST ÉCRITE AVANT L'ENVOI (état « envoi » + nonce), comme la
    publication du matin : si le processus meurt pendant l'envoi, on ne
    renvoie pas à l'aveugle au redémarrage, on va d'abord regarder dans le
    salon si le message y est.
    """
    delai = DELAI_ENTRE_MESSAGES if delai is None else float(delai)
    bilan = {"envoyes": 0, "retrouves": 0, "trop_lourds": 0, "refus": 0,
             "echecs": 0, "incertains": 0, "attente": ""}
    deja_envoye = False
    for sc in a_poster():
        now = float(maintenant or time.time())
        with _VERROU:
            d = charger()
            e = d["reels"].get(sc)
            if not isinstance(e, dict) or e.get("etat") not in ("pret", "envoi"):
                continue
            verifier = e.get("etat") == "envoi"
            if verifier and now - float(e.get("intention_le") or 0) < DELAI_VERIFICATION:
                continue
            if not verifier:
                e.update(etat="envoi", intention_le=now, nonce=nonce_de(sc))
                if not _ecrire(d):
                    bilan["attente"] = "registre non enregistré"
                    log.error("[all-banger] intention d'envoi non enregistrée : envoi suspendu")
                    break
            demande = dict(e, shortcode=sc, verifier=verifier)
        if deja_envoye and not verifier:
            dormir(delai)
        res = poster(sc, demande) or {"incertain": "reponse_vide"}
        with _VERROU:
            d = charger()
            e = d["reels"].get(sc)
            if not isinstance(e, dict):
                continue
            if res.get("message_id"):
                e.update(etat="envoye", message_id=int(res["message_id"]),
                         channel_id=int(res.get("channel_id") or 0), envoye_le=int(time.time()))
                e.pop("raison_envoi", None)
                _ecrire(d)
                bilan["retrouves" if res.get("retrouve") else "envoyes"] += 1
                deja_envoye = deja_envoye or not res.get("retrouve")
                for _cle in [k for k in _DITS if k.startswith("salon_absent:")]:
                    _DITS.discard(_cle)
                log.info(f"[all-banger] {sc} : {'retrouvé' if res.get('retrouve') else 'posté'} "
                         f"dans le salon (message {res['message_id']})")
                continue
            if res.get("absent"):
                # Vérifié dans le salon : l'envoi interrompu n'a rien créé.
                # On le repose en « prêt » ; il partira au prochain passage.
                e["etat"] = "pret"
                e.pop("intention_le", None)
                _ecrire(d)
                log.info(f"[all-banger] {sc} : envoi interrompu, absent du salon — sera reposté")
                continue
            if res.get("salon_absent"):
                if not verifier:
                    e["etat"] = "pret"          # rien n'est parti
                    e.pop("intention_le", None)
                    _ecrire(d)
                bilan["attente"] = str(res["salon_absent"])
                # Une ligne par CAUSE : si le bot revient mais que le salon
                # manque toujours, cette seconde cause doit se voir aussi.
                _dire_une_fois("salon_absent:" + bilan["attente"],
                               f"[all-banger] {res['salon_absent']} : les vidéos restent "
                               f"en attente et partiront dès que ce sera réglé")
                break
            if res.get("trop_lourd"):
                e.update(etat="trop_lourd", taille=int(res.get("taille") or 0),
                         limite=int(res.get("limite") or 0))
                _ecrire(d)
                bilan["trop_lourds"] += 1
                log.warning(f"[all-banger] {sc} : trop lourd pour Discord "
                            f"({int(res.get('taille') or 0) / 1048576:.1f} Mo > "
                            f"{int(res.get('limite') or 0) / 1048576:.0f} Mo) — non posté")
                continue
            if res.get("echec"):
                e.update(etat="echec", raison=str(res["echec"])[:80], echec_le=int(time.time()))
                _ecrire(d)
                bilan["echecs"] += 1
                log.warning(f"[all-banger] {sc} : {res['echec']} — non posté")
                continue
            if res.get("refuse"):
                e["essais_envoi"] = int(e.get("essais_envoi") or 0) + 1
                e["raison_envoi"] = str(res["refuse"])[:80]
                e["etat"] = "echec_envoi" if e["essais_envoi"] >= ENVOIS_MAX else "pret"
                e.pop("intention_le", None)
                _ecrire(d)
                bilan["refus"] += 1
                log.warning(f"[all-banger] {sc} : Discord refuse ({res['refuse']}), "
                            f"essai {e['essais_envoi']}/{ENVOIS_MAX}")
                break
            # Incertain : l'état « envoi » reste, la vérification tranchera.
            e["raison_envoi"] = str(res.get("incertain") or "inconnu")[:80]
            _ecrire(d)
            bilan["incertains"] += 1
            log.warning(f"[all-banger] {sc} : issue d'envoi incertaine "
                        f"({e['raison_envoi']}) — vérification dans le salon au prochain passage")
            break
    return bilan


# --------------------------------------------------------------- fil d'envoi --

def pousser(travaux: List[dict]) -> int:
    for t in (travaux or []):
        FILE.put(dict(t))
    return len(travaux or [])


def tour(poster: Callable, pret: Callable, attente: float = 0.0,
         telecharger_octets: Optional[Callable] = None,
         dormir: Callable = time.sleep) -> dict:
    """Un tour du fil : UN téléchargement s'il y en a, puis — file vide — les
    envois. Télécharger d'abord : un lien de CDN expire en quelques heures,
    un fichier sur le disque attend sans rien perdre."""
    try:
        job = FILE.get(timeout=attente) if attente else FILE.get_nowait()
    except queue.Empty:
        job = None
    if job:
        traiter_job(job, telecharger_octets=telecharger_octets)
    if not FILE.empty():
        return {"file": FILE.qsize()}
    expirer()
    if not pret():
        return {"attente": "bot Discord pas prêt"}
    return traiter_envois(poster, dormir=dormir)


def demarrer(poster: Callable, pret: Callable,
             telecharger_octets: Optional[Callable] = None) -> bool:
    """Lance LE fil d'envoi (un seul par processus). Rend True s'il vient
    d'être lancé."""
    with _VERROU:
        t = _TRAVAILLEUR.get("thread")
        if t is not None and t.is_alive():
            return False

        def _boucle():
            while True:
                try:
                    b = tour(poster, pret, attente=PERIODE_SEC,
                             telecharger_octets=telecharger_octets)
                    if any(b.get(k) for k in ("envoyes", "retrouves", "trop_lourds",
                                              "refus", "echecs", "incertains")):
                        log.info(f"[all-banger] passage : {b} — registre : {bilan()}")
                except Exception as ex:                       # noqa: BLE001
                    log.error(f"[all-banger] fil d'envoi : {type(ex).__name__}: {ex}")
                    time.sleep(30)

        t = threading.Thread(target=_boucle, daemon=True, name="all-banger")
        _TRAVAILLEUR["thread"] = t
        t.start()
    log.info("[all-banger] fil d'envoi démarré")
    return True


# ------------------------------------------------------------------ bilan --

def bilan() -> dict:
    """Combien de bangers dans chaque état — rien n'est écarté sans compte."""
    compte: Dict[str, int] = {}
    for e in (charger().get("reels") or {}).values():
        if isinstance(e, dict):
            k = str(e.get("etat") or "?")
            compte[k] = compte.get(k, 0) + 1
    return compte


# -------------------------------------------------------------- rattrapage --

def rattrapage(inclure_muets: bool = False, maintenant: float = 0.0) -> dict:
    """Met en file de publication les bangers DÉJÀ archivés (data/bangers/*.mp4).

    NON DÉCLENCHÉE : rien dans le site ne l'appelle. Le propriétaire a demandé
    les bangers à partir de maintenant ; poster d'un coup l'archive entière
    noierait le salon. Elle est là pour le jour où il le voudra :
        import all_banger; all_banger.rattrapage()
    Le fil d'envoi les postera ensuite un par un, au même rythme que les autres.

    Rend ce qui a été ajouté ET ce qui a été laissé, avec la raison.
    """
    now = int(maintenant or time.time())
    ajoutes, deja = 0, 0
    ecartes: Dict[str, int] = {}
    fiches = _bg.charger().get("reels") or {}
    with _VERROU:
        d = charger()
        for mp4 in sorted(_bg.DOSSIER.glob("*.mp4")):
            sc = mp4.stem
            if not _SC_OK.match(sc):
                ecartes["nom_illisible"] = ecartes.get("nom_illisible", 0) + 1
                continue
            if sc in d["reels"]:
                deja += 1
                continue
            f = fiches.get(sc)
            raison = ("hors_registre" if not isinstance(f, dict) else
                      "essai" if f.get("essai") else
                      "muet" if (f.get("muet") and not inclure_muets) else
                      "fichier_trop_petit" if not _bg.video_presente(sc) else "")
            if raison:
                ecartes[raison] = ecartes.get(raison, 0) + 1
                continue
            d["reels"][sc] = {"etat": "pret", "essais": 0, "source": "archive",
                              "detecte_le": int(f.get("detecte_le") or now),
                              "rattrapage": now}
            ajoutes += 1
        if ajoutes and not _ecrire(d):
            return {"ajoutes": 0, "deja": deja, "ecartes": ecartes,
                    "erreur": "registre non enregistré"}
    log.info(f"[all-banger] rattrapage : {ajoutes} ajouté(s), {deja} déjà connu(s), "
             f"écartés {ecartes}")
    return {"ajoutes": ajoutes, "deja": deja, "ecartes": ecartes}
