# -*- coding: utf-8 -*-
"""Salon « all-banger » : chaque banger dont la vidéo a été récupérée, reposté
tel quel — la vidéo, ses vues, sa description à copier, le lien du reel.

La demande du propriétaire (26/09/2026) : « toutes les vidéos que tu arrives à
télécharger au niveau des bangers, tu les retélécharges ici, mais uniquement
celles que tu as réussi à télécharger. Juste la vidéo et la description, pas
besoin du nom du VA. OK vidéo, c'est bon, on passe à la suivante. »
Puis, le même jour : « Réel, description et voir le reel sur Instagram. C'est
tout. » — « tu peux marquer les vues » — et « remettre tous les bangers que de
base ça trouve » : le rattrapage (cf. rattrapage()), fait UNE fois.

Le message est une carte Components V2 faite des MÊMES briques que la fiche
du matin (bangers.bloc_video_discord, bangers.blocs_description_discord),
sans son en-tête : ni compte, ni VA, ni likes, ni date.

Pourquoi un module à part, et pas une case de plus dans bangers.json :
bangers.examiner() relit et réécrit TOUT ce registre à chaque compte scrapé,
depuis quatre threads à la fois, sans verrou entre la lecture et l'écriture.
Un état d'envoi rangé là pouvait être effacé par un examen parti une seconde
plus tôt — et un envoi oublié, c'est un banger posté deux fois. Ici, un seul
fichier, un seul verrou, et personne d'autre n'y écrit.

Ce qui coûte, et ce qui ne coûte pas :
  - le lien `video_url` vient du scrape HikerAPI DÉJÀ PAYÉ ; le télécharger
    est un simple GET sur le CDN d'Instagram, gratuit ;
  - pour un NOUVEAU banger, aucun appel HikerAPI de plus, aucun Apify (le
    propriétaire refuse Apify, cf. la mémoire « pas-d-apify »). Si le lien a
    expiré, on attend le scrape suivant, qui en apporte un neuf — UNE fois ;
  - le RATTRAPAGE, lui, n'a plus de lien frais pour les vieux bangers : il
    prend d'abord les copies du disque (gratuites), puis UNE requête HikerAPI
    par reel manquant, sur une réserve à part plafonnée à 200 pour tout le
    rattrapage (PLAFOND_HIKER_RATTRAPAGE), jamais sur l'enveloppe du jour.

Le chemin d'un banger :
  video  → (téléchargé)  → pret → envoi → envoye
        ↘ 2 échecs ↘ echec       ↘ trop_lourd / echec_envoi
  rattrapage → (disque, ou HikerAPI + CDN) → pret | trop_lourd | echec
            ↘ HikerAPI coupé : reste « rattrapage », reprise 6 h plus tard
            ↘ lien gratuit d'un scrape → video (chemin des nouveaux)
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

#: Les refus qui ne visent QU'UN message : 400 (« Invalid Form Body », le
#: contenu de SA carte) et 0 (sa carte n'a pas pu être construite ici). Pour
#: eux, les suivants partent quand même. Avant, un seul banger refusé
#: arrêtait chaque passage à sa hauteur : tous les bangers derrière lui
#: attendaient qu'il ait épuisé ses ENVOIS_MAX essais — cinq passages, près
#: d'une heure, et autant de fois qu'il y avait de bangers refusés dans une
#: rafale de rattrapage. Les autres refus (401 jeton, 403 droits, 404 salon,
#: 429 cadence…) frappent tous les messages : ceux-là arrêtent le passage.
REFUS_PROPRES_AU_MESSAGE = (0, 400)

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

#: LE PLAFOND DU RATTRAPAGE, en requêtes HikerAPI, pour TOUT le rattrapage
#: (pas par jour) : 200 requêtes, 0,20 $ au plus au tarif noté dans
#: hiker_reels (0,001 $ la requête). Au-delà, les bangers restants sont
#: comptés « plafond atteint » et ne sont pas postés. Réserve à part : sur
#: l'enveloppe commune (PLAFOND_JOUR, épuisée chaque soir par le suivi des
#: comptes), le rattrapage aurait soit échoué, soit aveuglé l'Analytique.
PLAFOND_HIKER_RATTRAPAGE = 200

#: Le compteur de cette réserve. Un fichier à lui : il doit survivre aux
#: redémarrages (sinon chaque relance aurait droit à 200 requêtes de plus).
FICHIER_HIKER = _ICI / "data" / "bangers_all_hiker.json"
_VERROU_HIKER = threading.Lock()

#: Une coupure de NOTRE accès à HikerAPI (solde à zéro, jeton refusé ou
#: absent, cadence, réseau muet, compteur de réserve impossible à écrire) ne
#: dit rien des reels : le rattrapage est SUSPENDU, les reels restants gardent
#: leur état, et il reprend au bout de ce délai. Sans ça, un 402 au mauvais
#: moment marquait « fait » un rattrapage qui n'avait rien récupéré — et il
#: n'est jamais refait.
RATTRAPAGE_REPRISE_SEC = 6 * 3600

#: Au-delà de ce délai depuis la PREMIÈRE suspension, on cesse d'attendre :
#: les reels encore bloqués sont classés « hiker_coupe:<cause> », le
#: rattrapage est clos et le journal le dit. La réserve de 200 requêtes,
#: débitée avant chaque appel, borne la dépense de toutes ces reprises.
RATTRAPAGE_ABANDON_SEC = 7 * 86400

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
    entrent ici. Les fiches « muettes » (plus de 30 jours à la détection) et
    les « essais » du bouton de test restent dehors : ce ne sont pas des
    bangers du moment. Le passé — muets compris — est l'affaire du
    rattrapage, fait une seule fois (cf. rattrapage()).

    `reels` : la liste BRUTE du scrape, qui porte le `video_url` frais. Elle
    sert aussi à la relance : un banger dont le premier téléchargement a
    échoué retrouve ici un lien neuf — et à la reprise d'un banger du
    rattrapage que la source payante n'a pas servi (cf. _reprenable_par_scrape).

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
    repris: List[str] = []
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
            # La date de PUBLICATION du reel : c'est elle qui range les envois
            # (cf. a_poster), rattrapage et nouveaux bangers confondus.
            reg[sc] = {"etat": "video", "essais": 0, "detecte_le": int(now),
                       "poste_le": _bg._entier(f.get("poste_le"))}
            change = True
        for sc, r in par_sc.items():
            e = reg.get(sc)
            if not isinstance(e, dict) or sc in _EN_COURS:
                continue
            url = str(r.get("video_url") or "").strip()
            if url and _reprenable_par_scrape(e) and not _copie_locale(sc):
                # Un banger du rattrapage que la source payante n'a pas pu
                # servir (coupée, réserve épuisée) ou pas encore servi : le
                # scrape apporte son lien GRATUIT. Il prend le chemin des nouveaux bangers — sans
                # ça il restait perdu, alors que la vidéo était à portée.
                e["repris_par_scrape"] = {"le": int(now), "etat_avant": e.get("etat"),
                                          "raison_avant": str(e.get("raison") or "")[:80]}
                e.update(etat="video", essais=0, attente_depuis=int(now))
                e.pop("lien_essaye", None)
                e.pop("raison", None)
                change = True
                repris.append(f"{sc} (après « {e['repris_par_scrape']['raison_avant'] or e['repris_par_scrape']['etat_avant']} »)")
            if e.get("etat") != "video":
                continue
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
    if repris:
        log.info(f"[all-banger] repris par le scrape (lien gratuit) : {', '.join(repris)}")
    return travaux


def _reprenable_par_scrape(e: dict) -> bool:
    """Un banger que le lien gratuit d'un scrape peut reprendre : encore en
    attente du rattrapage, ou écarté faute d'HikerAPI (réserve épuisée, accès
    coupé) — jamais un échec propre au reel, ni un banger déjà posté."""
    etat = e.get("etat")
    raison = str(e.get("raison") or "")
    return etat == "rattrapage" or (etat == "echec" and (raison == "plafond_hiker"
                                                         or raison.startswith("hiker_coupe:")))


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
            # `attente_depuis` : un banger du rattrapage repris par un scrape
            # a une détection vieille de mois ; son attente commence à la reprise.
            if (isinstance(e, dict) and e.get("etat") == "video" and sc not in _EN_COURS
                    and now - int(e.get("attente_depuis") or e.get("detecte_le") or 0)
                    > ATTENTE_LIEN_MAX_SEC):
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

def _fiche(sc: str, fiche: Optional[dict]) -> dict:
    """La fiche du registre des bangers, relue seulement si on ne l'a pas.

    Un envoi en demande trois choses (description, vues, lien) : relire trois
    fois bangers.json — des milliers de fiches — pour chacun des centaines de
    messages du rattrapage, c'était du disque pour rien."""
    if isinstance(fiche, dict):
        return fiche
    try:
        return _bg.fiche(sc)
    except Exception:                                         # noqa: BLE001
        return {}


def description_de(shortcode: str, fiche: Optional[dict] = None) -> str:
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
    textes.append(str(_fiche(sc, fiche).get("description") or ""))
    try:
        textes.append(str(_bg.lire_details(sc).get("description") or ""))
    except Exception:                                         # noqa: BLE001
        pass
    textes = [t.strip() for t in textes if t and t.strip()]
    return max(textes, key=len) if textes else ""


def vues_de(shortcode: str, e: Optional[dict] = None, fiche: Optional[dict] = None) -> int:
    """Le nombre de vues à afficher : la PLUS HAUTE valeur connue.

    Le registre des bangers garde déjà le maximum vu par les scrapes
    (`vues`) ; la publication du matin a pu relever plus haut (`vues_actuelles`
    d'Apify), et le rattrapage lit le compteur du jour sur HikerAPI
    (`vues_hiker` de l'entrée). Un compteur ne redescend pas : prendre la
    dernière valeur afficherait parfois moins que ce qu'on a déjà vu.
    """
    sc = str(shortcode or "")
    f = _fiche(sc, fiche)
    valeurs = [f.get("vues"), f.get("vues_detection")]
    try:
        valeurs.append(_bg.lire_details(sc).get("vues_actuelles"))
    except Exception:                                         # noqa: BLE001
        pass
    valeurs.append((e or {}).get("vues_hiker"))
    return max([_bg._entier(v) for v in valeurs] + [0])


def url_de(shortcode: str, fiche: Optional[dict] = None) -> str:
    """Le lien du reel pour le bouton. Discord refuse tout le message si
    l'URL d'un bouton-lien n'est pas http(s) : on retombe alors sur le lien
    canonique, construit comme bangers.examiner le fait."""
    sc = str(shortcode or "")
    url = str(_fiche(sc, fiche).get("url") or "").strip()
    if not re.match(r"^https?://\S+$", url):
        url = f"https://www.instagram.com/p/{sc}/"
    return url


def ligne_vues(vues: int) -> str:
    """« **12 400** vues » : le format de l'en-tête de la fiche du matin."""
    return f"**{_bg._nombre(vues)}** vues"


def vue_message(shortcode: str, fichier, description: str, url: str, vues: int = 0):
    """La carte « all-banger » (Components V2). Rend (vue, fichiers).

    Dans l'ordre : la vidéo, ses vues juste dessous, puis — les mêmes blocs
    que la fiche du matin — la description à copier (et son .txt complet) et
    le bouton « Voir le reel sur Instagram ». RIEN d'autre : ni compte, ni VA,
    ni likes, ni date (demande expresse). La vidéo n'a pas de texte
    alternatif : celui du matin nomme le compte.
    """
    import discord
    sc = str(shortcode or "")
    galerie, video = _bg.bloc_video_discord(sc, fichier)
    enfants = [galerie]
    fichiers = [video]
    try:
        if vues:
            enfants.append(discord.ui.TextDisplay(ligne_vues(vues)))
        enfants.append(discord.ui.Separator())
        blocs, joints = _bg.blocs_description_discord(sc, description, url)
        enfants.extend(blocs)
        fichiers.extend(joints)
        vue = discord.ui.LayoutView(timeout=None)
        vue.add_item(discord.ui.Container(*enfants, accent_colour=_bg.COULEUR_FICHE))
    except Exception:
        # La vidéo est déjà ouverte : sans ça, une carte ratée laissait le
        # fichier ouvert à chaque essai.
        for f in fichiers:
            f.close()
        raise
    return vue, fichiers


def _urls_composants(o) -> List[str]:
    """Les ADRESSES d'un arbre de composants, et rien d'autre : le champ `url`
    du bouton-lien, `media.url` de la galerie, `file.url` du fichier joint.

    Jamais le texte (`content` des TextDisplay) : la description à copier est
    celle du créateur, et une légende « Partie 2, la 1 ici :
    instagram.com/reel/<autre> » faisait prendre le message de CE banger pour
    celui de l'autre — un banger jamais posté était alors marqué « envoyé »."""
    if isinstance(o, dict):
        out = [v for k, v in o.items() if k == "url" and isinstance(v, str)]
        for v in o.values():
            if isinstance(v, (dict, list)):
                out.extend(_urls_composants(v))
        return out
    if isinstance(o, list):
        return [u for v in o for u in _urls_composants(v)]
    return []


def _porte_le_reel(m, shortcode: str) -> bool:
    """Ce message du salon est-il celui de ce banger ?

    Trois marques, dont une suffit :
      - le nonce, que Discord ne renvoie pas toujours à la relecture ;
      - le NOM d'une pièce jointe (`<sc>.mp4`, `<sc>_description.txt`) ;
      - les ADRESSES des composants V2 : le bouton porte le lien du reel, la
        galerie celle de `<sc>.mp4`. C'est la marque qui reste quand la
        relecture ne rend ni nonce ni pièces jointes (message édité, cache
        partiel). Le texte de la carte n'est jamais lu (cf. _urls_composants).
    Le shortcode est cherché ENTIER, adresse par adresse : « ABC12 » ne doit
    pas reconnaître le message de « ABC123 ».
    """
    sc = str(shortcode or "")
    if not sc:
        return False
    if str(getattr(m, "nonce", "") or "") == nonce_de(sc):
        return True
    noms = {f"{sc}.mp4", f"{sc}_description.txt"}
    if any(getattr(a, "filename", "") in noms for a in (getattr(m, "attachments", None) or [])):
        return True
    try:
        urls = _urls_composants([c.to_dict() for c in (getattr(m, "components", None) or [])])
    except Exception:                                         # noqa: BLE001
        return False
    q = re.escape(sc)
    # Le lien du reel se termine après le code (/, ?, # ou fin) ; le fichier
    # est le dernier segment du chemin (« attachment://<sc>.mp4 » à l'envoi,
    # « https://cdn.discordapp.com/…/<sc>.mp4?ex=… » à la relecture).
    lien = re.compile(r"instagram\.com/(?:p|reels?|tv)/" + q + r"(?:[/?#]|$)")
    fichier = re.compile(r"/" + q + r"(?:\.mp4|_description\.txt)(?:[?#]|$)")
    return any(lien.search(u) or fichier.search(u) for u in urls)


async def retrouver(client, salon, shortcode: str, depuis: float):
    """Le message de ce banger, s'il a été posté par le bot après `depuis`."""
    from datetime import datetime, timezone
    apres = datetime.fromtimestamp(max(0.0, float(depuis or 0) - 60), timezone.utc)
    moi = getattr(getattr(client, "user", None), "id", None)
    async for m in salon.history(limit=200, after=apres):
        if getattr(getattr(m, "author", None), "id", None) != moi:
            continue
        if _porte_le_reel(m, shortcode):
            return m
    return None


async def envoyer(client, shortcode: str, e: dict, guild_id: int = 0) -> dict:
    """Poste UN banger. Tourne dans la boucle du bot.

    Rend un seul de ces cas, que traiter_envois() sait appliquer :
      {"message_id", "channel_id"}      posté (ou retrouvé : "retrouve")
      {"absent": True}                  vérification : rien dans le salon
      {"non_verifiable": raison}        vérification impossible (historique
                                        illisible) : ni renvoi ni abandon
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
            # Cause distincte d'un salon absent : elle ne frappe que CE banger,
            # les suivants (qui n'ont rien à vérifier) peuvent partir.
            return {"non_verifiable": f"relecture de #{salon.name} impossible "
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
    fiche = _fiche(sc, None)
    try:
        vue, fichiers = vue_message(sc, fichier, description_de(sc, fiche), url_de(sc, fiche),
                                    vues_de(sc, e, fiche))
    except Exception as ex:                                   # noqa: BLE001
        return {"refuse": f"carte:{type(ex).__name__}", "status": 0}
    try:
        # RIEN D'AUTRE que la carte : pas de texte à côté (un message en
        # composants V2 n'en porte pas), aucune mention ne notifie. Mêmes
        # paramètres que la fiche du matin (publier_fiche_discord), qui
        # tourne en production sous cette forme.
        m = await salon.send(view=vue, files=fichiers, nonce=nonce_de(sc),
                             allowed_mentions=discord.AllowedMentions.none())
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
    """Les bangers à poster ou à vérifier, dans l'ordre CHRONOLOGIQUE de
    publication du reel (le plus ancien d'abord).

    Le rattrapage verse d'un coup des centaines de reels de dates mêlées : le
    salon doit se lire comme un fil, du plus vieux au plus récent. La date
    vient de l'entrée (`poste_le`), à défaut de la fiche du registre des
    bangers (entrées d'avant ce champ), à défaut de la détection.
    """
    reg = charger().get("reels") or {}
    fiches = None
    out = []
    for sc, e in reg.items():
        if not isinstance(e, dict) or e.get("etat") not in ("pret", "envoi"):
            continue
        poste = _bg._entier(e.get("poste_le"))
        if not poste:
            if fiches is None:
                fiches = _bg.charger().get("reels") or {}
            poste = _bg._entier((fiches.get(sc) or {}).get("poste_le"))
        detecte = _bg._entier(e.get("detecte_le"))
        out.append((poste or detecte, detecte, sc))
    return [sc for _, _, sc in sorted(out)]


def traiter_envois(poster: Callable, dormir: Callable = time.sleep,
                   delai: Optional[float] = None, maintenant: float = 0.0,
                   entre_envois: Optional[Callable] = None) -> dict:
    """Poste, un par un, les bangers prêts. Rend le bilan du passage.

    L'INTENTION EST ÉCRITE AVANT L'ENVOI (état « envoi » + nonce), comme la
    publication du matin : si le processus meurt pendant l'envoi, on ne
    renvoie pas à l'aveugle au redémarrage, on va d'abord regarder dans le
    salon si le message y est.

    `entre_envois` est appelé avant chaque message : après le rattrapage, un
    passage dure des dizaines de minutes, et un nouveau banger signalé
    pendant ce temps ne doit pas laisser expirer son lien de CDN en file.

    L'ORDRE CHRONOLOGIQUE TIENT AUSSI APRÈS UNE COUPURE. Un banger resté
    « envoi » (processus tué en plein envoi, issue incertaine) n'est jamais
    sauté : une intention trop jeune pour être vérifiée, on ATTEND qu'elle
    ait l'âge (au plus DELAI_VERIFICATION) ; vérifiée absente, on la renvoie
    TOUT DE SUITE, avant le suivant. Sauter l'une ou l'autre, c'était poster
    le reel le plus ancien derrière toute la rafale — des centaines de
    messages plus bas (chaque déploiement redémarre le bot en pleine rafale).

    UN BANGER BLOQUÉ NE RETIENT PAS LES SUIVANTS. Refusé pour son propre
    contenu (cf. REFUS_PROPRES_AU_MESSAGE) ou impossible à vérifier
    (historique illisible), il garde son état et le passage continue ; seul
    ce qui frappe TOUS les messages (salon ou bot absent, droits, issue
    incertaine) arrête le passage. Avant, un reel resté « envoi » dans un
    salon sans « Voir les anciens messages » arrêtait chaque passage à sa
    hauteur : plus aucun banger ne partait, pour toujours.

    Les bangers devenus prêts PENDANT le passage (téléchargés entre deux
    envois) partent dans ce même passage, après les autres : sinon ils
    attendaient le tour suivant, jusqu'à PERIODE_SEC plus tard.
    """
    delai = DELAI_ENTRE_MESSAGES if delai is None else float(delai)
    bilan = {"envoyes": 0, "retrouves": 0, "trop_lourds": 0, "refus": 0,
             "echecs": 0, "incertains": 0, "attente": ""}
    deja_envoye = False
    # Le dernier envoi de ce passage a-t-il été refusé pour son contenu ? Deux
    # refus d'affilée, c'est la carte elle-même (format rejeté) : on s'arrête.
    refus_en_serie = False
    # Chaque banger est traité AU PLUS une fois par passage : un refusé ou un
    # non vérifiable reste « prêt » / « envoi », il ne doit pas boucler.
    vus: set = set()
    suite = "suivant"
    while suite != "arret":
        lot = [sc for sc in a_poster() if sc not in vus]
        if not lot:
            break
        for sc in lot:
            vus.add(sc)
            if entre_envois is not None:
                try:
                    entre_envois()
                except Exception as ex:                       # noqa: BLE001
                    log.warning(f"[all-banger] téléchargement entre deux envois : "
                                f"{type(ex).__name__}: {ex}")
            attendu = False
            appels = 0
            suite = "suivant"
            # Au plus : une attente, une vérification, un envoi. Jamais une boucle.
            while appels < 2:
                now = float(maintenant or time.time())
                with _VERROU:
                    d = charger()
                    e = d["reels"].get(sc)
                    if not isinstance(e, dict) or e.get("etat") not in ("pret", "envoi"):
                        break
                    verifier = e.get("etat") == "envoi"
                    reste = (DELAI_VERIFICATION - (now - float(e.get("intention_le") or 0))
                             if verifier else 0.0)
                    attendre = verifier and reste > 0 and not attendu
                    if not attendre:
                        if not verifier:
                            e.update(etat="envoi", intention_le=now, nonce=nonce_de(sc))
                            if not _ecrire(d):
                                bilan["attente"] = "registre non enregistré"
                                log.error("[all-banger] intention d'envoi non enregistrée : "
                                          "envoi suspendu")
                                suite = "arret"
                                break
                        demande = dict(e, shortcode=sc, verifier=verifier)
                if attendre:
                    # Hors du verrou : les scrapes continuent d'écrire pendant ce temps.
                    attendu = True
                    attente = min(reste, DELAI_VERIFICATION)
                    log.info(f"[all-banger] {sc} : envoi interrompu il y a peu — vérification "
                             f"dans {attente:.0f} s, avant le suivant (ordre chronologique)")
                    dormir(attente)
                    continue
                if deja_envoye and not verifier:
                    dormir(delai)
                appels += 1
                res = poster(sc, demande) or {"incertain": "reponse_vide"}
                suite = _appliquer_envoi(sc, res, verifier, bilan, refus_en_serie)
                if res.get("message_id"):
                    refus_en_serie = False
                    if not res.get("retrouve"):
                        deja_envoye = True
                elif res.get("refuse"):
                    refus_en_serie = True
                if suite != "reessayer":
                    break
            if suite == "arret":
                break
    return bilan


def _appliquer_envoi(sc: str, res: dict, verifier: bool, bilan: dict,
                     refus_en_serie: bool = False) -> str:
    """Consigne le résultat d'un envoi (ou d'une vérification). Rend la suite :
    « suivant » (banger tranché, ou bloqué seul : on passe au suivant),
    « reessayer » (vérifié absent : à renvoyer tout de suite) ou « arret »
    (plus rien ne partira dans ce passage).

    `refus_en_serie` : l'envoi précédent de ce passage a déjà été refusé pour
    son contenu."""
    with _VERROU:
        d = charger()
        e = d["reels"].get(sc)
        if not isinstance(e, dict):
            return "suivant"
        if verifier and (res.get("message_id") or res.get("absent")):
            # L'historique se relit de nouveau : une rechute se dira aussi.
            for _cle in [k for k in _DITS if k.startswith("non_verifiable:")]:
                _DITS.discard(_cle)
        if res.get("message_id"):
            e.update(etat="envoye", message_id=int(res["message_id"]),
                     channel_id=int(res.get("channel_id") or 0), envoye_le=int(time.time()))
            e.pop("raison_envoi", None)
            _ecrire(d)
            bilan["retrouves" if res.get("retrouve") else "envoyes"] += 1
            for _cle in [k for k in _DITS if k.startswith("salon_absent:")]:
                _DITS.discard(_cle)
            log.info(f"[all-banger] {sc} : {'retrouvé' if res.get('retrouve') else 'posté'} "
                     f"dans le salon (message {res['message_id']})")
            return "suivant"
        if res.get("absent"):
            # Vérifié dans le salon : l'envoi interrompu n'a rien créé. Il
            # repart TOUT DE SUITE, à sa place, avec le même nonce.
            e["etat"] = "pret"
            e.pop("intention_le", None)
            if not _ecrire(d):
                log.error(f"[all-banger] {sc} : retour à « prêt » non enregistré — "
                          f"envoi suspendu")
                bilan["attente"] = "registre non enregistré"
                return "arret"
            log.info(f"[all-banger] {sc} : envoi interrompu, absent du salon — reposté "
                     f"tout de suite")
            return "reessayer" if verifier else "suivant"
        if res.get("non_verifiable"):
            # Peut-être dans le salon, peut-être pas : ni renvoi (doublon
            # possible), ni abandon. Il reste « envoi », revérifié à chaque
            # passage ; les suivants, eux, n'ont rien à vérifier et partent.
            e["raison_envoi"] = str(res["non_verifiable"])[:120]
            _ecrire(d)
            bilan["attente"] = str(res["non_verifiable"])
            _dire_une_fois("non_verifiable:" + bilan["attente"],
                           f"[all-banger] {sc} : {res['non_verifiable']} — ce banger attend "
                           f"(ni renvoyé ni abandonné) ; les suivants partent")
            return "suivant"
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
            return "arret"
        if res.get("trop_lourd"):
            e.update(etat="trop_lourd", taille=int(res.get("taille") or 0),
                     limite=int(res.get("limite") or 0))
            _ecrire(d)
            bilan["trop_lourds"] += 1
            log.warning(f"[all-banger] {sc} : trop lourd pour Discord "
                        f"({int(res.get('taille') or 0) / 1048576:.1f} Mo > "
                        f"{int(res.get('limite') or 0) / 1048576:.0f} Mo) — non posté")
            return "suivant"
        if res.get("echec"):
            e.update(etat="echec", raison=str(res["echec"])[:80], echec_le=int(time.time()))
            _ecrire(d)
            bilan["echecs"] += 1
            log.warning(f"[all-banger] {sc} : {res['echec']} — non posté")
            return "suivant"
        if res.get("refuse"):
            propre = int(res.get("status") or 0) in REFUS_PROPRES_AU_MESSAGE
            bilan["refus"] += 1
            e.pop("intention_le", None)
            if propre and refus_en_serie:
                # Deux refus « de contenu » d'affilée : c'est plus sûrement la
                # carte elle-même que ces deux messages. Celui-ci n'est pas
                # compté contre ce banger (sinon un format rejeté ferait
                # épuiser ses essais à chaque banger de la file, un par un), et
                # le passage s'arrête, comme pour un 403.
                e["etat"] = "pret"
                e["raison_envoi"] = str(res["refuse"])[:80]
                _ecrire(d)
                log.warning(f"[all-banger] {sc} : Discord refuse ({res['refuse']}) — deuxième "
                            f"refus d'affilée, passage arrêté (essai non compté)")
                return "arret"
            e["essais_envoi"] = int(e.get("essais_envoi") or 0) + 1
            e["raison_envoi"] = str(res["refuse"])[:80]
            e["etat"] = "echec_envoi" if e["essais_envoi"] >= ENVOIS_MAX else "pret"
            _ecrire(d)
            log.warning(f"[all-banger] {sc} : Discord refuse ({res['refuse']}), "
                        f"essai {e['essais_envoi']}/{ENVOIS_MAX}"
                        + (" — refus propre à ce message, les suivants partent" if propre else ""))
            return "suivant" if propre else "arret"
        # Incertain : l'état « envoi » reste, la vérification tranchera.
        e["raison_envoi"] = str(res.get("incertain") or "inconnu")[:80]
        _ecrire(d)
        bilan["incertains"] += 1
        log.warning(f"[all-banger] {sc} : issue d'envoi incertaine "
                    f"({e['raison_envoi']}) — vérification dans le salon au prochain passage")
        return "arret"


# --------------------------------------------------------------- fil d'envoi --

def pousser(travaux: List[dict]) -> int:
    for t in (travaux or []):
        FILE.put(dict(t))
    return len(travaux or [])


def _un_job(telecharger_octets: Optional[Callable] = None) -> bool:
    """Traite UN téléchargement en file, s'il y en a un. Sert entre deux
    étapes longues (rattrapage, rafale d'envois) : un lien de CDN n'attend
    pas des heures."""
    try:
        job = FILE.get_nowait()
    except queue.Empty:
        return False
    traiter_job(job, telecharger_octets=telecharger_octets)
    return True


def limite_via_bot(bot) -> int:
    """La taille d'envoi acceptée par le serveur Youl4b, 0 si inconnue.

    Une simple lecture d'attribut (pas de coroutine) : sans danger depuis le
    fil d'envoi. Elle dépend des boosts du serveur, d'où la relecture."""
    try:
        guild = bot.get_guild(int(GUILD_ID)) if bot is not None else None
        return int(getattr(guild, "filesize_limit", 0) or 0)
    except Exception:                                         # noqa: BLE001
        return 0


def tour(poster: Callable, pret: Callable, attente: float = 0.0,
         telecharger_octets: Optional[Callable] = None,
         dormir: Callable = time.sleep, limite: Optional[Callable] = None) -> dict:
    """Un tour du fil : UN téléchargement s'il y en a, puis — file vide — le
    rattrapage s'il n'a jamais été fait, puis les envois.

    Télécharger d'abord : un lien de CDN expire en quelques heures, un
    fichier sur le disque attend sans rien perdre. Le rattrapage attend que
    le bot soit prêt : c'est le serveur qui dit quelle taille de vidéo il
    accepte, et une vidéo trop lourde doit être comptée comme telle dans son
    bilan, pas découverte au moment de l'envoi."""
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
    rat = None
    # Suspendu sur une coupure d'HikerAPI : pas avant l'heure de reprise (un
    # appel à chaque tour de 10 min redébiterait la réserve pour le même refus).
    if not rattrapage_fait() and rattrapage_du():
        rat = rattrapage(limite=(limite() if limite else 0) or LIMITE_DEFAUT,
                         telecharger_octets=telecharger_octets,
                         entre_deux=lambda: _un_job(telecharger_octets))
    b = traiter_envois(poster, dormir=dormir,
                       entre_envois=lambda: _un_job(telecharger_octets))
    if rat is not None:
        b["rattrapage"] = rat
    return b


def demarrer(poster: Callable, pret: Callable,
             telecharger_octets: Optional[Callable] = None,
             limite: Optional[Callable] = None) -> bool:
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
                             telecharger_octets=telecharger_octets, limite=limite)
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
#
# « Remettre tous les bangers que de base ça trouve » (26/09/2026) : TOUT le
# registre des bangers, pas seulement ceux détectés depuis la mise en ligne
# du salon. Fait UNE fois, automatiquement, au premier tour où le bot est
# prêt ; la marque `rattrapage.fait_le` du registre d'envoi interdit toute
# seconde fois (redémarrage, second processus).
#
# Deux temps, pour qu'un arrêt en route ne coûte rien de plus :
#   1. l'INSCRIPTION, en une seule écriture : chaque banger à récupérer passe
#      à l'état « rattrapage », et `rattrapage.commence_le` est posé. Elle ne
#      se refait jamais : au redémarrage, on reprend les « rattrapage »
#      restants, sans en ajouter ;
#   2. la RÉCUPÉRATION, reel par reel, chacun écrit dès qu'il est tranché ;
#      puis le bilan et `fait_le`.
# Les envois partent ENSUITE, par le chemin ordinaire (traiter_envois), dans
# l'ordre de publication des reels : attendre la fin de la récupération est
# ce qui garantit cet ordre (un vieux reel récupéré en dernier sur HikerAPI
# serait sinon passé après des plus récents).

def rattrapage_etat() -> dict:
    r = charger().get("rattrapage")
    return dict(r) if isinstance(r, dict) else {}


def rattrapage_fait() -> bool:
    return bool(rattrapage_etat().get("fait_le"))


def rattrapage_du(maintenant: float = 0.0) -> bool:
    """Vrai si le rattrapage peut être (re)lancé maintenant : faux tant qu'une
    suspension (coupure d'HikerAPI) n'a pas atteint son heure de reprise."""
    return float(maintenant or time.time()) >= float(rattrapage_etat().get("reprise_apres") or 0)


def budget_hiker() -> dict:
    """{utilise, plafond, restant} de la réserve HikerAPI du rattrapage."""
    d = safe_json.load(FICHIER_HIKER, default={})
    d = d if isinstance(d, dict) else {}
    utilise = _bg._entier(d.get("utilise"))
    return {"utilise": utilise, "plafond": PLAFOND_HIKER_RATTRAPAGE,
            "restant": max(0, PLAFOND_HIKER_RATTRAPAGE - utilise)}


def _consommer_hiker(n: int = 1) -> str:
    """Réserve n requêtes AVANT l'appel. Rend « ok », « plafond » (réserve
    vide) ou « compteur_non_ecrit ».

    Même modèle que vault_social._consommer_insta, fermé en cas d'échec
    d'écriture — mais le résultat de l'écriture est VÉRIFIÉ (safe_json.write
    rend False au lieu de lever) : un compteur qu'on ne peut pas tenir
    n'autorise rien. Les deux refus sont DISTINCTS : un disque plein passager
    était lu « réserve épuisée », et des bangers récupérables étaient
    abandonnés pour toujours sous une raison fausse."""
    with _VERROU_HIKER:
        e = budget_hiker()
        if e["restant"] < n:
            return "plafond"
        if not safe_json.write(FICHIER_HIKER, {"utilise": e["utilise"] + n,
                                               "plafond": PLAFOND_HIKER_RATTRAPAGE,
                                               "maj_le": int(time.time())}):
            log.error("[all-banger] compteur HikerAPI du rattrapage non écrit : requête refusée")
            return "compteur_non_ecrit"
        return "ok"


def _hiker_pret() -> bool:
    import hiker_reels as _hk
    try:
        return bool(_hk.get_token())
    except Exception:                                         # noqa: BLE001
        return False


#: Réponses HikerAPI qui disent que c'est NOTRE accès qui est en panne (jeton
#: refusé, solde épuisé, cadence), pas le reel. Continuer serait débiter la
#: réserve pour la même réponse, reel après reel, et déclarer « sans vidéo »
#: des centaines de bangers parfaitement récupérables.
HIKER_CODES_COUPURE = ("401", "402", "403", "429")

#: Autant d'erreurs d'affilée sans réponse HTTP (réseau coupé, délai) : même
#: raisonnement, le réseau est en cause, pas les reels.
HIKER_ERREURS_AFFILEE_MAX = 5


def _media_hiker(sc: str) -> dict:
    """UNE requête HikerAPI /v1/media/by/code. Rend {video_url, legende, vues}
    ou {erreur, detail}. La réserve est débitée par l'appelant, AVANT.

    L'erreur est ramenée à son code (« hiker:http_404 ») : le corps de la
    réponse, différent pour chaque reel, aurait éparpillé le bilan en autant
    de raisons que de reels. Il reste dans `detail`."""
    import hiker_reels as _hk
    data, err = _hk._appel("/v1/media/by/code", _hk.get_token(), 45, code=sc)
    if err:
        code = re.match(r"HTTP (\d{3})", str(err))
        return {"erreur": ("hiker:http_" + code.group(1)) if code else "hiker:reseau",
                "detail": str(err)[:160]}
    media = (data.get("media") if isinstance(data, dict) and isinstance(data.get("media"), dict)
             else data)
    if not isinstance(media, dict):
        return {"erreur": "hiker_reponse_illisible"}
    vues = media.get("play_count")
    if vues is None:
        vues = media.get("view_count")
    return {"video_url": _hk._url_video(media), "legende": _hk._legende(media),
            "vues": _bg._entier(vues)}


def _taille(sc: str) -> int:
    try:
        return _bg.chemin_video(sc).stat().st_size
    except OSError:
        return 0


def _marquer_requete(sc: str) -> None:
    """Écrit sur l'entrée, AVANT l'appel, qu'une requête HikerAPI est payée
    pour ce reel et d'où viendra sa vidéo.

    Un arrêt entre la requête et l'écriture de l'état (jusqu'à ~45 s
    d'HikerAPI + 60 s de CDN ; un déploiement suffit) laissait la vidéo sur
    le disque sans trace de la requête : la reprise la prenait pour une
    « archive » gratuite, et le bilan contredisait la réserve."""
    with _VERROU:
        d = charger()
        e = d["reels"].get(sc)
        if not isinstance(e, dict):
            return
        e.update(requete_hiker=True, source_prevue="hiker+cdn")
        if not _ecrire(d):
            log.error(f"[all-banger] rattrapage : requête HikerAPI de {sc} non consignée "
                      f"(le bilan la compte quand même, par la réserve)")


def _rattraper_un(sc: str, limite: int, telecharger_octets: Optional[Callable],
                  hiker_ferme: str = "") -> dict:
    """Récupère la vidéo d'UN banger du rattrapage. Rend les champs à poser
    sur son entrée : etat (pret | trop_lourd | echec), raison, source…
    — ou {"reporte": cause} : rien n'est tranché, le reel attend la reprise.

    `hiker_ferme` : vide si HikerAPI peut être appelé, sinon la cause de la
    coupure (pas de jeton, solde, réseau…) : le reel sans copie sur le disque
    est alors REPORTÉ, sans requête ni débit de la réserve."""
    out: dict = {}
    # 1. Le disque d'abord : archive des bangers, puis cache des Trends.
    #    Gratuit — et c'est la règle : aucune requête quand la vidéo est là.
    if _copie_locale(sc):
        ok, raison, source = telecharger(sc, "")
        if ok:
            out.update(source=source)
        elif raison == "archive_illisible":
            # L'archive n'est jamais écrasée (le site n'efface pas un média) :
            # une requête HikerAPI ne servirait à rien, le fichier resterait.
            return {"etat": "echec", "raison": raison, "source": source}
    # 2. Sinon UNE requête HikerAPI, sur la réserve du rattrapage, puis le CDN.
    if not out:
        if hiker_ferme:
            return {"reporte": hiker_ferme}
        jeton = _consommer_hiker(1)
        if jeton == "plafond":
            return {"etat": "echec", "raison": "plafond_hiker"}
        if jeton != "ok":
            # Compteur impossible à écrire : c'est le disque, pas le reel ni
            # la réserve. Coupure passagère, comme un 402.
            return {"reporte": jeton}
        _marquer_requete(sc)
        out["requete_hiker"] = True
        m = _media_hiker(sc)
        if m.get("erreur"):
            return dict(out, etat="echec", raison=m["erreur"], detail=m.get("detail", ""))
        if m.get("vues"):
            out["vues_hiker"] = m["vues"]
        if not m.get("video_url"):
            return dict(out, etat="echec", raison="hiker_sans_video")
        ok, raison, source = telecharger(sc, m["video_url"], telecharger_octets)
        if not ok:
            return dict(out, etat="echec", raison=(source + ":" if source else "") + raison,
                        source=source)
        out["source"] = "hiker+" + source if source == "cdn" else source
        # La légende COMPLÈTE : le scrape la coupait à 280 signes.
        # _ecrire_description garde la plus longue connue.
        _ecrire_description(sc, m.get("legende") or "")
    taille = _taille(sc)
    out["taille"] = taille
    if taille > limite:
        return dict(out, etat="trop_lourd", limite=limite)
    return dict(out, etat="pret")


def _inscrire(d: dict, fiches: dict, now: int) -> dict:
    """Premier temps : met à l'état « rattrapage » chaque banger à récupérer.
    Rend le compte de CHAQUE fiche du registre, rien n'est laissé sans raison."""
    c = {"total": 0, "essais_exclus": 0, "fiches_illisibles": 0, "shortcode_illisible": 0,
         "deja_postes": 0, "deja_en_file": 0, "deja_trop_lourds": 0,
         "refuses_par_discord": 0, "a_recuperer": 0, "repris_apres_echec": 0}
    for sc, f in fiches.items():
        if not isinstance(f, dict):
            c["fiches_illisibles"] += 1
            continue
        if f.get("essai"):
            # Les « essais » du bouton de test ne sont pas des bangers : pris
            # au hasard des dernières 24 h, souvent sous le seuil.
            c["essais_exclus"] += 1
            continue
        c["total"] += 1
        if not _SC_OK.match(str(sc)):
            c["shortcode_illisible"] += 1
            continue
        e = d["reels"].get(sc)
        etat = e.get("etat") if isinstance(e, dict) else None
        if etat == "envoye":
            c["deja_postes"] += 1
            continue
        if etat in ("video", "pret", "envoi", "rattrapage"):
            # Déjà en file (un nouveau banger en cours) : il partira par son
            # propre chemin, une fois — jamais deux.
            c["deja_en_file"] += 1
            continue
        if etat == "trop_lourd":
            c["deja_trop_lourds"] += 1
            continue
        if etat == "echec_envoi":
            c["refuses_par_discord"] += 1
            continue
        nouvelle = {"etat": "rattrapage", "essais": 0,
                    "detecte_le": _bg._entier(f.get("detecte_le")) or now,
                    "poste_le": _bg._entier(f.get("poste_le")), "rattrapage": now}
        if isinstance(e, dict):
            # Un nouveau banger dont la vidéo n'était pas descendue (lien
            # expiré…) : « tous les bangers » l'inclut, on retente ici.
            c["repris_apres_echec"] += 1
            nouvelle["raison_avant"] = str(e.get("raison") or "")[:80]
            nouvelle["detecte_le"] = _bg._entier(e.get("detecte_le")) or nouvelle["detecte_le"]
        d["reels"][sc] = nouvelle
        c["a_recuperer"] += 1
    return c


def _bilan_rattrapage(d: dict, depuis: int, inscription: dict, hiker_avant: int) -> dict:
    """Le bilan d'après la récupération, recalculé des entrées elles-mêmes :
    il reste juste même après une reprise sur redémarrage."""
    b = dict(inscription or {})
    b.update(postables=0, trop_lourds=0, sans_video=0, plafond_atteint=0,
             raisons_sans_video={}, sources={}, requetes_hiker=0)
    for e in (d.get("reels") or {}).values():
        if not isinstance(e, dict) or e.get("rattrapage") != depuis:
            continue
        etat = e.get("etat")
        if etat == "video":
            # Repris par un scrape (lien gratuit, cf. signaler) : il suit le
            # chemin des nouveaux bangers, son téléchargement est en cours.
            b["sans_video"] += 1
            b["raisons_sans_video"]["repris_par_scrape"] = (
                b["raisons_sans_video"].get("repris_par_scrape", 0) + 1)
            continue
        if etat in ("pret", "envoi", "envoye"):
            b["postables"] += 1
            src = str(e.get("source") or "?")
            b["sources"][src] = b["sources"].get(src, 0) + 1
        elif etat == "trop_lourd":
            b["trop_lourds"] += 1
        elif etat == "echec" and e.get("raison") == "plafond_hiker":
            b["plafond_atteint"] += 1
        elif etat == "echec":
            b["sans_video"] += 1
            r = str(e.get("raison") or "?")
            b["raisons_sans_video"][r] = b["raisons_sans_video"].get(r, 0) + 1
        else:
            b["sans_video"] += 1
            b["raisons_sans_video"]["inacheve"] = b["raisons_sans_video"].get("inacheve", 0) + 1
    h = budget_hiker()
    b["reserve_hiker"] = {"utilise": h["utilise"], "plafond": h["plafond"],
                          "avant": hiker_avant}
    # Les requêtes se comptent sur LA RÉSERVE, débitée avant chaque appel, et
    # non sur les entrées : un arrêt entre l'appel et l'écriture de l'état, ou
    # un reel redemandé à la reprise, faisaient mentir le bilan contre sa
    # propre ligne reserve_hiker.
    b["requetes_hiker"] = max(0, h["utilise"] - int(hiker_avant or 0))
    n = b["postables"]
    duree = n * DELAI_ENTRE_MESSAGES
    duree_txt = f"{duree / 60:.0f} min" if duree >= 90 else f"{duree:.0f} s"
    b["rafale"] = (f"{n} message(s) à poster dans #{NOM_SALON}, un par un, "
                   f"{DELAI_ENTRE_MESSAGES:.0f} s d'écart plus l'envoi de chaque vidéo : "
                   f"au moins {duree_txt} de publication continue"
                   if n else "rien à poster")
    return b


def rattrapage(limite: int = 0, telecharger_octets: Optional[Callable] = None,
               entre_deux: Optional[Callable] = None, maintenant: float = 0.0) -> dict:
    """Le rattrapage de TOUS les bangers du registre. Rend son bilan.

    Appelé par le fil d'envoi (tour), une seule fois dans la vie du salon ;
    un second appel rend {"deja_fait": …} sans rien toucher ni rien payer.
    `limite` : la taille acceptée par Discord (celle du serveur).
    `entre_deux` : appelé entre deux reels (téléchargements des nouveaux
    bangers en file, dont le lien de CDN expire).

    Trois fins possibles, et « fait » n'est posé que pour la dernière :
      {"suspendu": cause, …}  HikerAPI coupé (cf. RATTRAPAGE_REPRISE_SEC) :
                              les reels sans copie locale attendent, intacts ;
      {"erreur": …}           une entrée n'a pas pu être écrite : elle est
                              reprise au tour suivant (sa vidéo est sur le
                              disque, aucune nouvelle requête) ;
      le bilan                tout est tranché : `fait_le` est posé.
    """
    now = int(maintenant or time.time())
    limite = int(limite or LIMITE_DEFAUT)
    with _VERROU:
        d = charger()
        r = d.get("rattrapage") if isinstance(d.get("rattrapage"), dict) else {}
        if r.get("fait_le"):
            return {"deja_fait": r["fait_le"], "bilan": r.get("bilan") or {}}
        if not r.get("commence_le"):
            fiches = _bg.charger().get("reels") or {}
            if not fiches:
                # Un registre vide (ou illisible, safe_json rend alors {}) ne
                # doit pas « consommer » le rattrapage : il serait marqué fait
                # avec zéro banger, et jamais refait. On attend, et on le dit.
                _dire_une_fois("rattrapage_vide", "[all-banger] rattrapage différé : registre "
                               f"des bangers vide ou illisible ({_bg.FICHIER.name})")
                return {"attente": "registre des bangers vide ou illisible"}
            inscription = _inscrire(d, fiches, now)
            r = {"commence_le": now, "inscription": inscription,
                 "hiker_avant": budget_hiker()["utilise"], "limite": limite}
            d["rattrapage"] = r
            if not _ecrire(d):
                # Rien n'est inscrit tant que ce n'est pas écrit : sinon une
                # reprise ne saurait pas qu'il a commencé, et recompterait.
                log.error("[all-banger] rattrapage : registre non enregistré, remis au tour suivant")
                return {"erreur": "registre non enregistré"}
            log.info(f"[all-banger] rattrapage commencé : {inscription}")
        elif isinstance(r.get("suspendu"), dict):
            log.info(f"[all-banger] rattrapage repris après sa suspension "
                     f"({r['suspendu'].get('raison')}, "
                     f"{r['suspendu'].get('restants')} reel(s) en attente)")
        else:
            log.info("[all-banger] rattrapage repris après un arrêt")
        depuis = int(r["commence_le"])
        # L'ordre de RÉCUPÉRATION n'est pas celui des envois : si la réserve
        # HikerAPI s'épuise, mieux vaut qu'elle soit allée aux reels les plus
        # vus. (Les envois, eux, sont chronologiques : cf. a_poster.)
        vues = {sc: _bg._entier((f or {}).get("vues"))
                for sc, f in (_bg.charger().get("reels") or {}).items() if isinstance(f, dict)}
        a_faire = sorted((sc for sc, e in d["reels"].items()
                          if isinstance(e, dict) and e.get("etat") == "rattrapage"),
                         key=lambda sc: (-vues.get(sc, 0), sc))
    # `hiker_ferme` : la CAUSE de la coupure (vide tant qu'HikerAPI répond).
    # Une fois posée, les reels sans copie locale sont reportés, intacts ; ceux
    # qui ont leur vidéo sur le disque continuent, eux, gratuitement.
    hiker_ferme = "" if _hiker_pret() else "sans_jeton"
    detail_coupure = ""
    if a_faire and hiker_ferme:
        log.warning("[all-banger] rattrapage : pas de jeton HikerAPI — les vidéos déjà sur le "
                    "disque sont traitées, les autres attendent le jeton")
    # Les erreurs réseau d'une série ne sont pas tranchées tout de suite : si
    # la série atteint HIKER_ERREURS_AFFILEE_MAX, c'est le réseau qui est en
    # panne et ces reels en sont les victimes — ils restent à récupérer. Une
    # réponse d'HikerAPI prouve le contraire : la série est alors tranchée.
    serie_reseau: List[tuple] = []

    def _trancher(sc: str, res: dict) -> None:
        with _VERROU:
            d = charger()
            e = d["reels"].get(sc)
            if not isinstance(e, dict) or e.get("etat") != "rattrapage":
                return
            if res.get("source") == "archive" and e.get("source_prevue"):
                # La vidéo est sur le disque parce qu'une requête HikerAPI
                # l'a payée avant un arrêt : ce n'est pas une archive gratuite.
                res = dict(res, source=e["source_prevue"])
            e.update(res)
            e["tranche_le"] = int(time.time())
            if not _ecrire(d):
                log.error(f"[all-banger] rattrapage : {sc} non enregistré — repris au tour "
                          f"suivant")

    def _couper(cause: str, detail: str) -> None:
        log.warning(f"[all-banger] rattrapage : HikerAPI coupé ({cause} : {detail[:80]}) — plus "
                    f"aucune requête ; les reels restants sans vidéo sur le disque attendent la "
                    f"reprise (dans {RATTRAPAGE_REPRISE_SEC // 3600} h)")

    for i, sc in enumerate(a_faire):
        if entre_deux is not None:
            try:
                entre_deux()
            except Exception as ex:                           # noqa: BLE001
                log.warning(f"[all-banger] rattrapage, file des nouveaux : "
                            f"{type(ex).__name__}: {ex}")
        with _VERROU:
            e = charger()["reels"].get(sc)
            if not isinstance(e, dict) or e.get("etat") != "rattrapage":
                # Repris entre-temps par un scrape qui apportait un lien gratuit
                # (cf. signaler) : pas de requête payée pour rien.
                continue
        try:
            res = _rattraper_un(sc, limite, telecharger_octets, hiker_ferme)
        except Exception as ex:                               # noqa: BLE001
            res = {"etat": "echec", "raison": f"exception:{type(ex).__name__}"}
        raison = str(res.get("raison") or "")
        code = re.match(r"hiker:http_(\d{3})$", raison)
        if res.get("reporte"):
            if not hiker_ferme:
                # Le compteur de la réserve n'a pas pu être écrit.
                hiker_ferme, detail_coupure = str(res["reporte"]), "réserve HikerAPI"
                _couper(hiker_ferme, detail_coupure)
            continue
        if code and code.group(1) in HIKER_CODES_COUPURE:
            # Notre ACCÈS est refusé (solde, jeton, cadence) : ce reel n'est pas
            # tranché, il attend la reprise avec les autres.
            hiker_ferme = "http_" + code.group(1)
            detail_coupure = str(res.get("detail") or "")
            _couper(hiker_ferme, detail_coupure)
            continue
        if raison == "hiker:reseau":
            serie_reseau.append((sc, res))
            if len(serie_reseau) >= HIKER_ERREURS_AFFILEE_MAX:
                hiker_ferme = "reseau"
                detail_coupure = str(res.get("detail") or "")
                _couper(hiker_ferme, f"{len(serie_reseau)} erreurs d'affilée, {detail_coupure}")
                serie_reseau = []           # victimes de la panne : non tranchées
            continue
        if res.get("requete_hiker") and serie_reseau:
            # HikerAPI a répondu : le réseau passe, ces erreurs étaient isolées.
            for _sc, _res in serie_reseau:
                _trancher(_sc, _res)
            serie_reseau = []
        _trancher(sc, res)
        if raison == "plafond_hiker":
            _dire_une_fois("plafond_hiker", "[all-banger] rattrapage : réserve HikerAPI épuisée "
                           f"({PLAFOND_HIKER_RATTRAPAGE} requêtes) — les bangers restants sans "
                           "vidéo sur le disque ne seront pas postés")
        if (i + 1) % 50 == 0:
            log.info(f"[all-banger] rattrapage : {i + 1}/{len(a_faire)} reels traités")
    # Fin de parcours SANS coupure : une courte série d'erreurs réseau en
    # queue est tranchée comme avant (erreurs propres à ces reels). Après une
    # coupure (un 402 derrière deux délais dépassés…), elle attend la reprise.
    if not hiker_ferme:
        for _sc, _res in serie_reseau:
            _trancher(_sc, _res)
    with _VERROU:
        d = charger()
        r = d.get("rattrapage") if isinstance(d.get("rattrapage"), dict) else {}
        if r.get("fait_le"):
            return {"deja_fait": r["fait_le"], "bilan": r.get("bilan") or {}}
        restants = sorted(sc for sc, e in d["reels"].items()
                          if isinstance(e, dict) and e.get("rattrapage") == depuis
                          and e.get("etat") == "rattrapage")
        if restants and hiker_ferme:
            # L'heure de la FIN du parcours : il a pu durer une heure, la
            # reprise se compte à partir de la coupure constatée.
            fin = int(maintenant or time.time())
            susp = r.get("suspendu") if isinstance(r.get("suspendu"), dict) else {}
            debut = _bg._entier(susp.get("depuis")) or fin
            if fin - debut < RATTRAPAGE_ABANDON_SEC:
                reprise = fin + RATTRAPAGE_REPRISE_SEC
                r.update(suspendu={"raison": hiker_ferme, "detail": detail_coupure[:160],
                                   "le": fin, "depuis": debut, "restants": len(restants)},
                         reprise_apres=reprise,
                         suspensions=_bg._entier(r.get("suspensions")) + 1)
                d["rattrapage"] = r
                if not _ecrire(d):
                    # Sans reprise_apres écrit, le tour suivant relance tout de
                    # suite : une requête de plus, bornée par la réserve.
                    log.error("[all-banger] rattrapage : suspension non enregistrée")
                prets = sum(1 for e in d["reels"].values()
                            if isinstance(e, dict) and e.get("rattrapage") == depuis
                            and e.get("etat") == "pret")
                log.warning(f"[all-banger] rattrapage SUSPENDU ({hiker_ferme}) : "
                            f"{len(restants)} reel(s) sans vidéo sur le disque attendent la "
                            f"reprise dans {RATTRAPAGE_REPRISE_SEC // 3600} h ; "
                            f"{prets} déjà récupéré(s) partent maintenant, les autres "
                            f"suivront après eux ; abandon après "
                            f"{RATTRAPAGE_ABANDON_SEC // 86400} jours de coupure")
                return {"suspendu": hiker_ferme, "restants": len(restants),
                        "reprise_apres": reprise, "detail": detail_coupure[:160]}
            # Coupé depuis trop longtemps : on cesse d'attendre, et on le dit.
            for sc in restants:
                d["reels"][sc].update(etat="echec", raison="hiker_coupe:" + hiker_ferme,
                                      echec_le=fin, tranche_le=int(time.time()))
            r["abandon"] = {"raison": hiker_ferme, "le": fin, "depuis": debut,
                            "reels": len(restants)}
            log.warning(f"[all-banger] rattrapage : HikerAPI coupé ({hiker_ferme}) depuis "
                        f"{(fin - debut) // 86400} jour(s) — {len(restants)} reel(s) classés "
                        f"« hiker_coupe:{hiker_ferme} », non postés ; le rattrapage est clos")
            restants = []
        if restants:
            # Une entrée restée « rattrapage » est du travail inachevé (son
            # écriture a échoué) : la déclarer faite, c'était abandonner une
            # vidéo payée et déjà sur le disque. Le tour suivant la reprend.
            log.error(f"[all-banger] rattrapage : {len(restants)} entrée(s) non enregistrée(s) "
                      f"({', '.join(restants[:5])}) — pas marqué fait, repris au tour suivant")
            return {"erreur": f"{len(restants)} entrée(s) non enregistrée(s)",
                    "restants": restants[:20]}
        b = _bilan_rattrapage(d, depuis, r.get("inscription") or {}, _bg._entier(r.get("hiker_avant")))
        b["suspensions"] = _bg._entier(r.get("suspensions"))
        if isinstance(r.get("suspendu"), dict):
            r["derniere_suspension"] = r.pop("suspendu")
        r.pop("reprise_apres", None)
        r.update(fait_le=int(time.time()), bilan=b)
        d["rattrapage"] = r
        if not _ecrire(d):
            log.error("[all-banger] rattrapage : fin non enregistrée, sera reprise au tour suivant")
            return {"erreur": "fin non enregistrée", "bilan": b}
    log.info(f"[all-banger] rattrapage terminé : {b.get('total', 0)} banger(s) au registre, "
             f"{b['postables']} postable(s), {b.get('deja_postes', 0)} déjà posté(s), "
             f"{b.get('deja_en_file', 0)} déjà en file, {b['sans_video']} sans vidéo "
             f"{b['raisons_sans_video']}, "
             f"{b['trop_lourds'] + b.get('deja_trop_lourds', 0)} trop lourd(s), "
             f"{b['plafond_atteint']} au-delà du plafond HikerAPI, "
             f"{b['requetes_hiker']} requête(s) HikerAPI — {b['rafale']}")
    return b
