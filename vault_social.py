# -*- coding: utf-8 -*-
"""Un dossier du vault branché sur un profil TikTok ou Instagram.

On colle le lien d'un profil à la création du dossier — la plateforme se
déduit du lien — : les vidéos au-dessus
d'un seuil de vues descendent dans ses Reels, chacune avec un voisin
``<stem>.social.json`` qui porte ses vues. Toutes les deux semaines, le profil
est relu : les compteurs sont mis à jour et les nouvelles vidéos qui ont
franchi le seuil arrivent.

Ce que ce module refuse de faire, et pourquoi :

* il ne supprime rien — une vidéo qui n'est plus sur le profil reste dans le
  vault (c'est le but : la garder) ;
* il ne retélécharge pas une vidéo que le propriétaire a supprimée du vault :
  l'identifiant reste dans ``recus``. Sans ça, chaque relecture ramenait ce
  qu'on venait de trier ;
* il ne tait rien : tout ce qui n'est pas descendu est compté dans le bilan
  (sous le seuil, vues inconnues, échecs, supprimées à la main).
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import safe_json

_ICI = Path(__file__).resolve().parent
FICHIER = _ICI / "data" / "vault_social.json"

#: Le voisin d'une vidéo importée : plateforme, lien, vues, date de post.
SUFFIXE = ".social.json"

#: Préfixe des fichiers importés. L'identifiant de la plateforme suffit à
#: les reconnaître : pas de doublon possible entre deux relectures.
PREFIXE_TIKTOK = "tt_"
PREFIXE_INSTA = "ig_"
PREFIXES = {"tiktok": PREFIXE_TIKTOK, "instagram": PREFIXE_INSTA}
LIBELLES = {"tiktok": "TikTok", "instagram": "Instagram"}

SEUIL_DEFAUT = 10_000

#: « Toutes les deux semaines, pas tous les jours. » TikTok bloque vite une
#: adresse qui relit trop souvent, et les vues d'une vidéo vieille de plus
#: de quinze jours bougent peu.
INTERVALLE_SEC = 14 * 86400

#: Combien de vidéos récentes on examine par profil. Au-delà, la liste
#: prend plusieurs minutes et TikTok finit par couper.
MAX_EXAMINEES = 600

#: Instagram passe par HikerAPI (payant à la requête, 2 requêtes par
#: relecture) : on lit ce que sa page de reels rend, au plus ce nombre.
MAX_EXAMINEES_INSTA = 100

#: LA LISTE D'UN PROFIL TIKTOK, DEPUIS LE VPS. Mesuré le 25/09/2026 : yt-dlp
#: se voit refuser la liste aux adresses de serveur (« Unable to extract
#: secondary user ID », puis un corps vide même à jour avec curl_cffi), tout
#: comme /api/post/item_list et l'API de l'application. /api/creator/item_list,
#: lui, répond — par pages de 15, vues et date comprises, gratuitement — à
#: condition de parler comme Chrome (curl_cffi) avec les cookies de la page
#: profil. Apify marchait aussi, mais le propriétaire n'en veut pas.
PAGE_CREATOR = 15          # au-delà : HTTP 400 « invalid count parameter »
MAX_PAGES_CREATOR = 60

#: Un échec de téléchargement est retenté aux relectures suivantes, mais pas
#: indéfiniment : une vidéo retirée ou privée échouerait à chaque passage.
MAX_ECHECS = 3

#: Pause entre deux téléchargements. Enchaîner sans pause fait passer
#: l'adresse du VPS pour un robot, et TikTok répond alors par des 403.
PAUSE_SEC = 1.5

_verrou = threading.RLock()
#: {identité: {"fait": n, "total": m, "etape": "..."}} — l'état d'une
#: synchro en cours, pour la barre de progression du site.
_en_cours: Dict[str, Dict[str, Any]] = {}
_file_attente: list = []
_travailleur: Optional[threading.Thread] = None


# ------------------------------------------------------------------ registre

def _registre() -> dict:
    d = safe_json.load(FICHIER, default={})
    return d if isinstance(d, dict) else {}


def _ecrire(reg: dict) -> bool:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    return bool(safe_json.write(FICHIER, reg, indent=2))


def lire(identite: str) -> dict:
    return dict(_registre().get((identite or "").lower()) or {})


def tout() -> dict:
    return _registre()


def _maj(identite: str, creer: bool = True, **champs) -> dict:
    """Fusionne des champs dans l'entrée d'un dossier.

    creer=False pour tout ce qui vient d'une relecture : si le dossier a été
    renommé ou archivé entre-temps, son entrée a changé de clé (voir
    identite_admin._CLES) et la recréer sous l'ancien nom laissait une
    entrée fantôme relue toutes les deux semaines.
    """
    with _verrou:
        reg = _registre()
        if not creer and identite not in reg:
            return {}
        e = dict(reg.get(identite) or {})
        e.update(champs)
        reg[identite] = e
        _ecrire(reg)
        return e


# ----------------------------------------------------------------- les liens

_RE_TIKTOK = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]{2,24})", re.I)
_RE_INSTA = re.compile(r"instagram\.com/([A-Za-z0-9_.]{1,30})(?:[/?#]|$)", re.I)

#: Ce qui suit « instagram.com/ » sans être un compte. Un lien de reel
#: (instagram.com/reel/xxx) aurait sinon branché un compte nommé « reel ».
_INSTA_PAS_UN_COMPTE = {"p", "reel", "reels", "tv", "stories", "explore",
                        "accounts", "direct", "about", "legal"}


def analyser_lien(lien: str) -> dict:
    """{plateforme, username, url} — ou {erreur} si le lien n'est pas lisible."""
    s = (lien or "").strip()
    if not s:
        return {"erreur": "lien vide"}
    # Un nom seul (« @lea ») n'est plus accepté : il ne dit pas de quelle
    # plateforme il s'agit, et c'est le lien qui décide.
    m = _RE_TIKTOK.search(s)
    if m:
        u = m.group(1).lower()
        return {"plateforme": "tiktok", "username": u,
                "url": f"https://www.tiktok.com/@{u}"}
    m = _RE_INSTA.search(s)
    if m:
        u = m.group(1).lower()
        if u in _INSTA_PAS_UN_COMPTE:
            return {"erreur": "c'est le lien d'une publication : colle celui "
                              "du profil (instagram.com/nom)"}
        return {"plateforme": "instagram", "username": u,
                "url": f"https://www.instagram.com/{u}/"}
    return {"erreur": "lien non reconnu — attendu : tiktok.com/@nom "
                      "ou instagram.com/nom"}


def source_prete(plateforme: str) -> str:
    """'' si la plateforme peut être lue d'ici, sinon la raison."""
    if plateforme == "instagram":
        try:
            import hiker_reels as _hk
            if _hk.configured():
                return ""
        except Exception:
            pass
        return ("Instagram passe par HikerAPI, et aucun jeton HikerAPI n'est "
                "configuré sur ce serveur (Settings)")
    return ""


def nom_dossier(username: str) -> str:
    """Le nom de dossier que le site accepte (a-z, 0-9, _ et -).

    Le point d'un username TikTok (« khaby.lame ») devient « _ » : le
    retirer collait les mots, et « khabylame » ne se retrouve plus.
    """
    s = (username or "").lower().replace(".", "_")
    return re.sub(r"[^a-z0-9_\-]", "", s)[:30]


def brancher(identite: str, lien: str, seuil: int) -> dict:
    """Associe un profil à un dossier. Ne lance pas la synchro."""
    info = analyser_lien(lien)
    if info.get("erreur"):
        return {"ok": False, "error": info["erreur"]}
    pas_prete = source_prete(info["plateforme"])
    if pas_prete:
        return {"ok": False, "error": pas_prete}
    try:
        seuil = max(0, int(str(seuil).replace(" ", "").replace("\u202f", "")))
    except (TypeError, ValueError):
        # Refuser plutôt que remplacer par 10 000 sans le dire.
        return {"ok": False, "error": f"seuil illisible : {seuil!r}"}
    e = _maj((identite or "").lower(), plateforme=info["plateforme"],
             username=info["username"], url=info["url"], seuil=seuil,
             branche_le=int(time.time()))
    return {"ok": True, **e}


def regler_seuil(identite: str, seuil: int) -> dict:
    ident = (identite or "").lower()
    if not lire(ident):
        return {"ok": False, "error": "aucun profil branché sur ce dossier"}
    try:
        seuil = max(0, int(seuil))
    except (TypeError, ValueError):
        return {"ok": False, "error": "seuil illisible"}
    return {"ok": True, **_maj(ident, seuil=seuil)}


# ------------------------------------------------------------------ voisins

def vues_du_dossier(dossier: Path) -> Dict[str, int]:
    """{stem: vues} pour les vidéos importées d'un dossier (lecture seule)."""
    out: Dict[str, int] = {}
    try:
        for v in dossier.glob("*" + SUFFIXE):
            stem = v.name[:-len(SUFFIXE)]
            d = safe_json.load(v, default={})
            if isinstance(d, dict) and isinstance(d.get("vues"), int):
                out[stem] = d["vues"]
    except Exception:
        pass
    return out


def format_vues(n: Optional[int]) -> str:
    """12 345 -> « 12,3 k », 1 200 000 -> « 1,2 M » (comme TikTok)."""
    if not isinstance(n, int):
        return ""
    if n >= 1_000_000:
        s = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") + " M"
    if n >= 1_000:
        s = f"{n / 1_000:.1f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") + " k"
    return str(n)


# ------------------------------------------------------------------ synchro

#: Ce qui compte comme une vidéo dans le dossier. Chercher « tt_<id>.* » sans
#: ce filtre prenait parfois un voisin pour la vidéo (.desc.txt, .thumb.jpg,
#: la sauvegarde .prev) : les vues partaient alors dans un
#: « tt_<id>.desc.social.json » que personne ne lit, et le badge se figeait.
EXTS_VIDEO = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv"})

#: Délai avant de retenter un profil en échec (liste refusée, TikTok qui
#: bloque). Attendre les deux semaines ordinaires laissait un dossier vide
#: pour quinze jours à cause d'un refus passager.
REESSAI_SEC = 86400

#: Combien de refus d'affilée (403/429) avant d'arrêter la relecture. Au-delà,
#: c'est l'adresse qui est bloquée, pas la vidéo : insister ne fait
#: qu'allonger le blocage.
MAX_REFUS_DAFFILEE = 3


class PasUneVideo(Exception):
    """Publication photo (carrousel) : TikTok n'en sert que la bande-son."""


def _est_un_refus(err: Exception) -> bool:
    """Un refus de TikTok (adresse bloquée), pas un défaut de la vidéo."""
    m = str(err).lower()
    return any(k in m for k in ("403", "429", "forbidden", "too many requests",
                                "rate limit", "blocked"))


def _video_existante(dossier: Path, stem: str) -> Optional[Path]:
    for ext in sorted(EXTS_VIDEO):
        p = dossier / (stem + ext)
        if p.is_file():
            return p
    return None


def _ecrire_voisin(dossier: Path, stem: str, donnees: dict) -> bool:
    # backup=False : une copie .prev resterait derrière une suppression du
    # média, et elle ressemblait à un fichier du dossier.
    return bool(safe_json.write(dossier / (stem + SUFFIXE), donnees,
                                indent=None, backup=False))


def _lister_tiktok_creator(username: str) -> list:
    """La liste d'un profil TikTok par /api/creator/item_list, au format des
    entrées yt-dlp (id, url, view_count, timestamp, title) + « photo »."""
    import json as _json
    from curl_cffi import requests as _cr
    s = _cr.Session(impersonate="chrome")
    page = s.get(f"https://www.tiktok.com/@{username}", timeout=30)
    sec = ""
    m = re.search(r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
                  page.text, re.S)
    if m:
        try:
            det = _json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]
            user = ((det.get("userInfo") or {}).get("user") or {})
            # Le secUid d'un AUTRE compte (suggestions de la page) listerait
            # les vidéos de quelqu'un d'autre, sans que rien ne le montre.
            if str(user.get("uniqueId") or "").lower() == username.lower():
                sec = user.get("secUid") or ""
            elif det.get("statusCode"):
                raise RuntimeError(f"profil introuvable ou privé (code {det['statusCode']})")
        except (KeyError, ValueError, TypeError):
            pass
    if not sec:
        raise RuntimeError(f"page du profil illisible (HTTP {page.status_code})")
    base = {"aid": 1988, "app_language": "en", "app_name": "tiktok_web",
            "browser_language": "en-US", "browser_name": "Mozilla",
            "browser_platform": "MacIntel", "channel": "tiktok_web",
            "cookie_enabled": "true", "device_platform": "web_pc",
            "secUid": sec, "region": "FR", "count": PAGE_CREATOR, "type": 1}
    curseur = int(time.time() * 1000)
    vus: Dict[str, dict] = {}
    for _ in range(MAX_PAGES_CREATOR):
        r = s.get("https://www.tiktok.com/api/creator/item_list/",
                  params=dict(base, cursor=curseur), timeout=30,
                  headers={"Referer": f"https://www.tiktok.com/@{username}"})
        try:
            j = _json.loads(r.text or "{}")
        except ValueError:
            j = {}
        items = j.get("itemList") or []
        if not items:
            if not vus:
                raise RuntimeError(f"liste refusée (HTTP {r.status_code}, "
                                   f"{j.get('statusMsg') or j.get('status_msg') or 'corps vide'})")
            break
        neufs = [it for it in items if str(it.get("id")) not in vus]
        for it in neufs:
            vus[str(it["id"])] = it
        if not neufs or not j.get("hasMorePrevious") or len(vus) >= MAX_EXAMINEES:
            break
        # Page suivante : ce qui a été posté avant la plus ancienne reçue.
        curseur = min(int(it.get("createTime") or 0) for it in items) * 1000
        time.sleep(0.6)
    out = []
    for vid, it in list(vus.items())[:MAX_EXAMINEES]:
        vues = (it.get("stats") or {}).get("playCount")
        out.append({"id": vid,
                    "url": f"https://www.tiktok.com/@{username}/video/{vid}",
                    "view_count": int(vues) if isinstance(vues, (int, float)) else None,
                    "timestamp": it.get("createTime") or None,
                    "title": it.get("desc") or "",
                    "photo": bool(it.get("imagePost"))})
    return out


def _lister_tiktok(url: str) -> list:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": "in_playlist", "playlistend": MAX_EXAMINEES,
            "socket_timeout": 30}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False) or {}
    return [e for e in (info.get("entries") or []) if isinstance(e, dict)]


def _lister_instagram(username: str) -> list:
    """Les reels récents, au format des entrées yt-dlp (id, url, view_count,
    timestamp, title) plus video_url, que HikerAPI rend dans le même appel.

    Appel direct de hiker_reels, PAS d'insta_scraper.scrape_profile : ce
    dernier range le profil dans le cache de la veille Trends, et chaque
    dossier d'inspiration serait apparu dans Trends."""
    import hiker_reels as _hk
    res = _hk.scrape_profile(username, MAX_EXAMINEES_INSTA)
    if res.get("error"):
        raise RuntimeError(str(res["error"]))
    out = []
    for r in res.get("reels") or []:
        code = r.get("shortcode") or ""
        if not code:
            continue
        vues = r.get("views")
        out.append({"id": code,
                    "url": f"https://www.instagram.com/reel/{code}/",
                    "view_count": int(vues) if isinstance(vues, (int, float)) else None,
                    "timestamp": r.get("taken_at") or None,
                    "title": r.get("caption") or "",
                    "video_url": r.get("video_url") or ""})
    return out


def _telecharger_direct(url_video: str, cible_sans_ext: Path) -> Path:
    """GET du mp4 sur le CDN Instagram. Le lien signé expire en quelques
    heures : il est pris dans la liste lue juste avant, jamais conservé."""
    if not url_video:
        # Les reels d'un profil sont tous des vidéos : un lien manquant est
        # un trou de HikerAPI, à retenter, pas une publication photo.
        raise RuntimeError("aucun lien vidéo rendu par HikerAPI")
    import requests
    final = cible_sans_ext.with_suffix(".mp4")
    part = cible_sans_ext.parent / (cible_sans_ext.name + ".mp4.part")
    with requests.get(url_video, stream=True, timeout=60) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP Error {r.status_code}")
        with open(part, "wb") as f:
            for bloc in r.iter_content(1 << 16):
                f.write(bloc)
    if part.stat().st_size < 1024:
        part.unlink()
        raise RuntimeError("fichier vide reçu")
    os.replace(part, final)
    return final


def _lister(src: dict, bilan: Optional[dict] = None) -> list:
    """La liste du profil. TikTok : l'API « creator » d'abord (la seule qui
    réponde depuis le VPS), yt-dlp en secours — tous deux gratuits."""
    if src.get("plateforme") == "instagram":
        if bilan is not None:
            bilan["source"] = "HikerAPI"
        return _lister_instagram(src.get("username") or "")
    try:
        out = _lister_tiktok_creator(src.get("username") or "")
        if bilan is not None:
            bilan["source"] = "TikTok"
        return out
    except Exception as err_creator:
        print(f"[vault-social] API creator refusée pour {src.get('username')} : "
              f"{str(err_creator)[:160]} — essai yt-dlp", flush=True)
        try:
            out = _lister_tiktok(src["url"])
        except Exception as err_ytdlp:
            raise RuntimeError(
                f"TikTok refuse de lister ce profil : {str(err_creator)[:150]} "
                f"(yt-dlp : {str(err_ytdlp)[:120]})") from err_ytdlp
        if bilan is not None:
            bilan["source"] = "yt-dlp"
        return out


def _telecharger(src: dict, voisin: dict, cible_sans_ext: Path) -> Path:
    if src.get("plateforme") == "instagram":
        return _telecharger_direct(voisin.get("_video_url") or "", cible_sans_ext)
    return _telecharger_tiktok(voisin["url"], cible_sans_ext)


def _telecharger_tiktok(url: str, cible_sans_ext: Path) -> Path:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "noprogress": True,
            "socket_timeout": 30,
            "outtmpl": str(cible_sans_ext) + ".%(ext)s",
            # h264 d'abord : le h265 (« bytevc1 ») ne se lit pas dans tous
            # les navigateurs — TikTok le sert en 1080p, le h264 souvent en
            # 720p seulement, et c'est le h264 qu'on garde. Le format
            # « download » de TikTok porte le filigrane : on l'écarte.
            # Le « ? » compte : sans lui, un format SANS note était écarté
            # aussi, et on retombait en silence sur le h265.
            # vcodec!=none partout : une publication photo n'a qu'un format
            # audio, et « best » descendait sa bande-son (.m4a) — invisible
            # dans la galerie, mais comptée comme une vidéo importée.
            "format": ("best[vcodec^=h264][format_note!*=?watermark]"
                       "/best[vcodec!=?none][format_note!*=?watermark]"
                       "/best[vcodec!=?none]"),
            "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True) or {}
            chemin = Path(y.prepare_filename(info))
    except Exception as err:
        if "requested format is not available" in str(err).lower():
            raise PasUneVideo(str(err)) from err
        raise
    if not chemin.is_file():
        # prepare_filename peut deviner une autre extension que celle écrite
        chemin = _video_existante(cible_sans_ext.parent, cible_sans_ext.name)
        if chemin is None:
            raise RuntimeError("fichier absent après téléchargement")
    if chemin.suffix.lower() not in EXTS_VIDEO:
        # Ce fichier vient d'être créé par nous, ce n'est pas un média du
        # vault : le laisser, c'était un .m4a invisible compté « importé ».
        try:
            chemin.unlink()
        except OSError:
            pass
        raise PasUneVideo(f"format {chemin.suffix} reçu au lieu d'une vidéo")
    return chemin


def synchroniser(identite: str, dossier_videos: Path,
                 apres: Optional[Callable[[], None]] = None) -> dict:
    """Relit le profil, met les vues à jour, descend les nouvelles vidéos.

    Bloquant (plusieurs minutes pour un gros profil) : à lancer via
    ``planifier``. Retourne le bilan, aussi rangé dans le registre.
    """
    ident = (identite or "").lower()
    src = lire(ident)
    if not src.get("url"):
        return {"ok": False, "error": "aucun profil branché"}
    plateforme = src.get("plateforme") or "tiktok"
    prefixe = PREFIXES.get(plateforme, PREFIXE_TIKTOK)
    seuil = int(src.get("seuil") or 0)
    recus = set(src.get("recus") or [])
    photos = set(src.get("photos") or [])
    # « Relire maintenant » remet les abandonnées en jeu. Lu ici, au début,
    # et pas effacé par relancer() : une relecture en cours aurait réécrit
    # ses propres échecs par-dessus en finissant.
    echecs = {} if src.get("raz_echecs") else dict(src.get("echecs") or {})
    bilan = {"examinees": 0, "au_dessus": 0, "deja_la": 0, "nouvelles": 0,
             "sous_seuil": 0, "vues_inconnues": 0, "retirees_a_la_main": 0,
             "photos": 0, "echecs": 0, "abandonnees": 0, "vues_maj": 0}
    liste_lue = False
    _en_cours[ident] = {"fait": 0, "total": 0, "etape": "lecture du profil"}
    # « demande » retombe ici et pas à la fin : un clic pendant la relecture
    # la reposera, et elle sera refaite après celle-ci.
    if not _maj(ident, creer=False, statut="en_cours", erreur="", demande=False,
                raz_echecs=False, echecs=echecs):
        _en_cours.pop(ident, None)
        return {"ok": False, "error": "profil débranché"}
    # Les téléchargements se font HORS du vault, puis sont déplacés : yt-dlp
    # recrée tout dossier manquant, et un dossier renommé ou archivé pendant
    # la relecture renaissait sous l'ancien nom, vide et orphelin.
    tmp = FICHIER.parent / "_vault_social_tmp" / ident
    try:
        if not dossier_videos.parent.is_dir():
            raise RuntimeError("dossier introuvable dans le vault")
        dossier_videos.mkdir(exist_ok=True)
        tmp.mkdir(parents=True, exist_ok=True)
        entrees = _lister(src, bilan)
        liste_lue = True
        bilan["examinees"] = len(entrees)
        now = int(time.time())
        a_prendre = []
        for e in entrees:
            vid = str(e.get("id") or "")
            if not vid:
                continue
            vues = e.get("view_count")
            stem = prefixe + vid
            existant = _video_existante(dossier_videos, stem)
            voisin = {"plateforme": plateforme, "id": vid,
                      "url": e.get("url") or f"{src['url']}/video/{vid}",
                      "vues": vues if isinstance(vues, int) else None,
                      "publie_le": e.get("timestamp"),
                      "titre": (e.get("title") or "")[:300],
                      "maj_le": now}
            if existant is not None:
                bilan["deja_la"] += 1
                if isinstance(vues, int):
                    ancien = safe_json.load(dossier_videos / (stem + SUFFIXE), default={})
                    ancien = ancien if isinstance(ancien, dict) else {}
                    # Réécrire un voisin inchangé n'est pas gratuit : la
                    # synchro Drive voit un fichier de taille différente et
                    # en téléverse un second, homonyme, à chaque relecture.
                    if (ancien.get("vues") != vues
                            or ancien.get("titre") != voisin["titre"]):
                        ancien.update(voisin)
                        _ecrire_voisin(dossier_videos, stem, ancien)
                        bilan["vues_maj"] += 1
                recus.add(vid)
                continue
            if vid in photos or e.get("photo") or "/photo/" in (e.get("url") or ""):
                bilan["photos"] += 1
                photos.add(vid)
                continue
            if not isinstance(vues, int):
                # Sans compteur on ne peut pas juger : compté, pas deviné.
                bilan["vues_inconnues"] += 1
                continue
            if vues < seuil:
                bilan["sous_seuil"] += 1
                continue
            bilan["au_dessus"] += 1
            if vid in recus:
                bilan["retirees_a_la_main"] += 1
                continue
            if echecs.get(vid, 0) >= MAX_ECHECS:
                bilan["abandonnees"] += 1
                continue
            # Le lien vidéo Instagram ne va pas dans le voisin : il expire
            # en quelques heures, le garder ferait croire qu'il sert encore.
            a_prendre.append((vid, stem, dict(voisin, _video_url=e.get("video_url") or "")))
        # Les plus vues d'abord : si TikTok coupe en route, on a le meilleur.
        a_prendre.sort(key=lambda t: -(t[2]["vues"] or 0))
        _en_cours[ident] = {"fait": 0, "total": len(a_prendre),
                            "etape": "téléchargement"}
        refus = 0
        for i, (vid, stem, voisin) in enumerate(a_prendre):
            try:
                brut = _telecharger(src, voisin, tmp / stem)
                if not dossier_videos.is_dir():
                    try:
                        brut.unlink()
                    except OSError:
                        pass
                    raise RuntimeError("dossier renommé ou archivé pendant la relecture")
                chemin = dossier_videos / brut.name
                shutil.move(str(brut), str(chemin))
                voisin.pop("_video_url", None)
                _ecrire_voisin(dossier_videos, stem, voisin)
                # La date du fichier = la date du post : « Récemment » et le
                # badge de date de la galerie parlent alors de TikTok, pas du
                # jour de l'import (sinon tout un profil porte la même date).
                if isinstance(voisin.get("publie_le"), (int, float)):
                    try:
                        os.utime(chemin, (voisin["publie_le"], voisin["publie_le"]))
                    except OSError:
                        pass
                recus.add(vid)
                echecs.pop(vid, None)
                bilan["nouvelles"] += 1
                refus = 0
            except PasUneVideo:
                photos.add(vid)
                bilan["photos"] += 1
            except Exception as err:
                if "pendant la relecture" in str(err):
                    raise
                bilan["echecs"] += 1
                print(f"[vault-social] {ident} {vid} : {err}", flush=True)
                if _est_un_refus(err):
                    # Un refus ne dit rien de la vidéo : il ne compte pas
                    # dans ses trois essais, sinon un blocage passager
                    # abandonnait tout le profil pour de bon.
                    refus += 1
                    if refus >= MAX_REFUS_DAFFILEE:
                        raise RuntimeError(
                            f"{LIBELLES.get(plateforme, plateforme)} refuse les "
                            "téléchargements (403/429) — nouvel essai dans 24 h") from err
                else:
                    echecs[vid] = echecs.get(vid, 0) + 1
            _en_cours[ident] = {"fait": i + 1, "total": len(a_prendre),
                                "etape": "téléchargement"}
            # Le registre est tenu à jour en route : un redémarrage du bot au
            # milieu d'un gros profil ne refait pas ce qui est déjà descendu.
            if (i + 1) % 10 == 0:
                _maj(ident, creer=False, recus=sorted(recus),
                     photos=sorted(photos), echecs=echecs)
            time.sleep(PAUSE_SEC)
        _maj(ident, creer=False, statut="ok", erreur="", reessai_le=None,
             derniere_synchro=int(time.time()), bilan=bilan,
             recus=sorted(recus), photos=sorted(photos), echecs=echecs)
        return {"ok": True, "bilan": bilan}
    except Exception as err:
        msg = str(err).strip().splitlines()[0][:300] if str(err).strip() else type(err).__name__
        champs = {"statut": "erreur", "erreur": msg,
                  # Réessai demain, pas toutes les demi-heures (un profil qui
                  # répond 403 serait relu en boucle), ni dans deux semaines.
                  "reessai_le": int(time.time()) + REESSAI_SEC,
                  "recus": sorted(recus), "photos": sorted(photos),
                  "echecs": echecs}
        # Liste refusée : le bilan précédent reste. L'écraser par des zéros
        # faisait annoncer « 0 dans le dossier » à côté de 40 vidéos.
        if liste_lue:
            champs["bilan"] = bilan
        _maj(ident, creer=False, **champs)
        print(f"[vault-social] {ident} : {msg}", flush=True)
        return {"ok": False, "error": msg, "bilan": bilan}
    finally:
        _en_cours.pop(ident, None)
        if apres:
            try:
                apres()
            except Exception:
                pass


def signature(identite: str) -> str:
    """Ce qui change quand une relecture se termine. Le bandeau la porte :
    une relecture finie avant que la page ne commence à suivre (échec en
    deux secondes) laissait sinon l'ancien bandeau, sans l'erreur."""
    e = lire(identite)
    return "|".join(str(e.get(k) or "") for k in
                    ("statut", "derniere_synchro", "reessai_le", "erreur"))


def progression(identite: str) -> Optional[dict]:
    ident = (identite or "").lower()
    if ident in _en_cours:
        return dict(_en_cours[ident])
    if ident in _file_attente:
        return {"fait": 0, "total": 0, "etape": "en file d'attente"}
    return None


def prochaine(identite: str) -> Optional[int]:
    e = lire(identite)
    if not e.get("url"):
        return None
    if e.get("reessai_le"):
        return int(e["reessai_le"])
    return int(e.get("derniere_synchro") or 0) + INTERVALLE_SEC


def relancer(identite: str) -> dict:
    """« Relire maintenant » : les vidéos abandonnées ont une nouvelle chance.

    Sans ça, trois échecs (réseau coupé, VPS redémarré) les écartaient pour
    toujours, et rien ne permettait de les reprendre.
    """
    ident = (identite or "").lower()
    if not lire(ident).get("url"):
        return {"ok": False, "error": "aucun profil branché"}
    _maj(ident, creer=False, raz_echecs=True)
    planifier(ident)
    return {"ok": True}


# --------------------------------------------------------------- la file

_dossier_de: Callable[[str], Optional[Path]] = lambda ident: None
_apres_global: Optional[Callable[[], None]] = None


def planifier(identite: str) -> bool:
    """Met un dossier dans la file. Une seule synchro à la fois : deux
    profils lus en parallèle depuis la même adresse, c'est le 403 assuré.

    Un dossier EN COURS de relecture est remis en file : un seuil changé ou
    un « Relire » cliqué pendant la relecture était sinon perdu, alors que le
    site répondait « relecture lancée ». La demande est aussi écrite dans le
    registre, pour survivre à un redémarrage du bot.
    """
    ident = (identite or "").lower()
    _maj(ident, creer=False, demande=True)
    with _verrou:
        if ident in _file_attente:
            return False
        _file_attente.append(ident)
    _assurer_travailleur()
    return True


def _assurer_travailleur():
    global _travailleur
    with _verrou:
        if _travailleur is not None and _travailleur.is_alive():
            return
        _travailleur = threading.Thread(target=_boucle, daemon=True,
                                        name="vault-social")
        _travailleur.start()


def _dus(maintenant: float) -> list:
    """Les dossiers à relire. Appelé par le seul fil de travail, file vide :
    un « en_cours » trouvé ici est donc forcément une relecture interrompue
    (redémarrage du bot), qu'on reprend au lieu d'attendre deux semaines."""
    out = []
    for ident, e in _registre().items():
        if not e.get("url") or ident in _en_cours:
            continue
        if (e.get("demande") or e.get("statut") == "en_cours"
                or maintenant >= (prochaine(ident) or 0)):
            out.append(ident)
    return out


def _boucle():
    dernier_tour = 0.0
    while True:
        ident = None
        with _verrou:
            if _file_attente:
                ident = _file_attente.pop(0)
        if ident:
            dossier = _dossier_de(ident)
            if dossier is None:
                # Dossier supprimé ou renommé : le dire dans le registre,
                # ne pas relire un profil pour rien.
                _maj(ident, creer=False, statut="erreur", demande=False,
                     erreur="dossier introuvable dans le vault",
                     reessai_le=int(time.time()) + REESSAI_SEC)
            else:
                synchroniser(ident, dossier, _apres_global)
            continue
        # File vide : toutes les demi-heures, qui est dû ?
        if time.time() - dernier_tour >= 1800:
            dernier_tour = time.time()
            for ident2 in _dus(time.time()):
                planifier(ident2)
            continue
        time.sleep(20)


def demarrer(dossier_de: Callable[[str], Optional[Path]],
             apres: Optional[Callable[[], None]] = None) -> None:
    """À appeler une fois au démarrage du site.

    ``dossier_de(identite)`` rend le dossier Reels, ou None s'il n'existe plus.
    ``apres()`` est appelé après chaque synchro (vider les caches du site).
    """
    global _dossier_de, _apres_global
    _dossier_de = dossier_de
    _apres_global = apres
    _assurer_travailleur()
