# -*- coding: utf-8 -*-
"""Un dossier du vault branché sur un profil TikTok ou Instagram.

On colle le lien d'un profil à la création du dossier — la plateforme se
déduit du lien — : les vidéos au-dessus d'un seuil de vues descendent dans
sa « Vidéo brut » (sous-dossier brutes), chacune avec un voisin
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

#: Où descendent les vidéos : « Vidéo brut », la matière première des
#: montages (choix du propriétaire, 25/09/2026). Elles allaient d'abord dans
#: les Reels ; ANCIEN_SOUS_DOSSIER sert à rapatrier ce qui y est arrivé.
SOUS_DOSSIER = "brutes"
ANCIEN_SOUS_DOSSIER = "videos"

#: « Toutes les deux semaines, pas tous les jours. » TikTok bloque vite une
#: adresse qui relit trop souvent, et les vues d'une vidéo vieille de plus
#: de quinze jours bougent peu.
INTERVALLE_SEC = 14 * 86400

#: Combien de vidéos récentes on examine par profil. Au-delà, la liste
#: prend plusieurs minutes et TikTok finit par couper.
MAX_EXAMINEES = 600

#: Instagram passe par HikerAPI, payé à la requête (0,001 $, solde prépayé).
#: Une page de reels en rend 12 (mesuré le 25/09/2026 sur khaby00) : avant,
#: on n'en lisait qu'une, soit les 12 derniers reels d'un profil de 675.
#: Même borne que TikTok : 600 reels = 1 + 50 requêtes, environ 0,05 $.
MAX_EXAMINEES_INSTA = 600

#: Réserve HikerAPI propre au vault, par jour. Le suivi des comptes épuise
#: chaque jour l'enveloppe commune (10 000/10 000 le 25/09 au soir) : sur
#: elle, un import restait bloqué, et il ne doit pas non plus la vider.
#: 300 requêtes = une relecture complète de 5 profils, 0,30 $ au plus.
PLAFOND_JOUR_INSTA = 300
_BUDGET_INSTA = _ICI / "data" / "vault_social_hiker.json"
_BUDGET_VERROU = threading.Lock()


def budget_insta() -> dict:
    """{jour, utilise, plafond, restant} de la réserve du vault."""
    jour = time.strftime("%Y-%m-%d", time.gmtime())
    d = safe_json.load(_BUDGET_INSTA, default={})
    d = d if isinstance(d, dict) else {}
    utilise = int(d.get("utilise") or 0) if d.get("jour") == jour else 0
    return {"jour": jour, "utilise": utilise, "plafond": PLAFOND_JOUR_INSTA,
            "restant": max(0, PLAFOND_JOUR_INSTA - utilise)}


def _consommer_insta(n: int = 1) -> bool:
    """Réserve n requêtes AVANT l'appel ; faux si la réserve du jour est vide.
    Fermé en cas d'échec d'écriture, comme l'enveloppe commune : un compteur
    qu'on ne peut pas tenir n'autorise rien."""
    with _BUDGET_VERROU:
        e = budget_insta()
        if e["restant"] < n:
            return False
        try:
            safe_json.write(_BUDGET_INSTA, {"jour": e["jour"], "utilise": e["utilise"] + n})
        except Exception as err:
            print(f"[vault-social] compteur HikerAPI non écrit, appel refusé : {err}", flush=True)
            return False
        return True

#: LA LISTE D'UN PROFIL TIKTOK, DEPUIS LE VPS. Mesuré le 25/09/2026 : yt-dlp
#: se voit refuser la liste aux adresses de serveur (« Unable to extract
#: secondary user ID », puis un corps vide même à jour avec curl_cffi), tout
#: comme /api/post/item_list et l'API de l'application. /api/creator/item_list,
#: lui, répond — par pages de 15, vues et date comprises, gratuitement — à
#: condition de parler comme Chrome (curl_cffi) avec les cookies de la page
#: profil. Apify marchait aussi, mais le propriétaire n'en veut pas.
PAGE_CREATOR = 15          # au-delà : HTTP 400 « invalid count parameter »
MAX_PAGES_CREATOR = 60
#: Plus loin que MAX_EXAMINEES, SEULEMENT pour retrouver les videos du dossier
#: nommees avec leur numero : ibenhaastrup (26/09/2026) en avait 77 plus
#: anciennes que ses 600 dernieres, restees sans vues. Rien n'est telecharge
#: au-dela : on y cherche des vues, pas du contenu.
MAX_PAGES_PROFOND = 200

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
#: UNE FILE PAR RESEAU. Deux profils TikTok lus en parallele depuis la meme
#: adresse, c'est le 403 assure (constate) : TikTok reste un a la fois. Un
#: TikTok et un Instagram ne se genent pas (HikerAPI d'un cote) : le
#: 26/09/2026, treize profils attendaient derriere un seul import.
VOIES = ("tiktok", "instagram")
_travailleurs: Dict[str, threading.Thread] = {}
#: {cle: reseau} des relectures en cours, fixe a la prise. Relu dans le
#: registre, un profil debranche en pleine relecture n'avait plus de reseau :
#: son import Instagram passait pour un TikTok et bloquait la file TikTok.
_voie_active: Dict[str, str] = {}
#: Dernier tour « qui est du ? », commun aux files : le premier fil libre le
#: fait. Reserve a la file TikTok, un Instagram du attendait la fin de tout
#: l'import TikTok (des heures, avec treize profils en file).
_dernier_tour = [0.0]


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


#: PLUSIEURS SOURCES PAR DOSSIER (26/09/2026) : « faire pk pas instagram et
#: tiktok ». La premiere garde la cle « <identite> » (tout l existant la lit
#: ainsi) ; celle de l autre plateforme vit sous « <identite>|<plateforme> ».
#: Chaque cle est une unite de relecture a part entiere (planifier,
#: synchroniser, bandeau), et identite_admin suit ces cles « <nom>|... » au
#: renommage et au retrait (_PREFIXES).
SEP_SOURCE = "|"


def identite_de(cle: str) -> str:
    """Le dossier d'une cle du registre (« lea|instagram » -> « lea »)."""
    return (cle or "").lower().split(SEP_SOURCE, 1)[0]


def sources_de(identite: str) -> list:
    """[(cle, entree)] des profils branches sur un dossier, principal d'abord."""
    ident = (identite or "").lower()
    reg = _registre()
    out = [(k, dict(v)) for k, v in reg.items()
           if isinstance(v, dict) and v.get("url")
           and (k == ident or k.startswith(ident + SEP_SOURCE))]
    return sorted(out, key=lambda kv: (kv[0] != ident, kv[0]))


def brancher_existante(identite: str, lien: str, seuil) -> dict:
    """Branche un profil sur un dossier QUI EXISTE DEJA, sans rien retirer.

    Meme plateforme que le profil principal (ou aucun profil) : c'est lui qui
    change. Autre plateforme : une seconde source, a cote. Un AUTRE compte
    sur la meme source repart de zero (ses recus, ecartes et doublons ne
    valent plus). Ne lance pas la relecture."""
    info = analyser_lien(lien)
    if info.get("erreur"):
        return {"ok": False, "error": info["erreur"]}
    pas_prete = source_prete(info["plateforme"])
    if pas_prete:
        return {"ok": False, "error": pas_prete}
    try:
        seuil = max(0, int(str(seuil).replace(" ", "").replace("\u202f", "")))
    except (TypeError, ValueError):
        return {"ok": False, "error": f"seuil illisible : {seuil!r}"}
    ident = (identite or "").lower()
    with _verrou:
        reg = _registre()
        principal = reg.get(ident) if isinstance(reg.get(ident), dict) else {}
        if not principal.get("url") or principal.get("plateforme") == info["plateforme"]:
            cle = ident
        else:
            cle = ident + SEP_SOURCE + info["plateforme"]
        ancien = reg.get(cle) if isinstance(reg.get(cle), dict) else {}
        champs = {"plateforme": info["plateforme"], "username": info["username"],
                  "url": info["url"], "seuil": seuil, "branche_le": int(time.time())}
        if ancien.get("username") and ancien.get("username") != info["username"]:
            champs.update(recus=[], photos=[], echecs={}, doublons={}, bilan={},
                          derniere_synchro=None, statut="", erreur="", reessai_le=None)
        e = _maj(cle, **champs)
    return {"ok": True, "cle": cle, **e}


def debrancher(cle: str) -> dict:
    """Oublie un profil branche. Les videos deja descendues RESTENT."""
    c = (cle or "").lower()
    with _verrou:
        reg = _registre()
        if c not in reg:
            return {"ok": False, "error": "aucun profil sous cette clé"}
        e = reg.pop(c)
        if not _ecrire(reg):
            return {"ok": False, "error": "registre non écrit"}
        if c in _file_attente:
            _file_attente.remove(c)
    return {"ok": True, "cle": c, "username": (e or {}).get("username"),
            "plateforme": (e or {}).get("plateforme")}


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


def date_numero_tiktok(num: str) -> Optional[int]:
    """La date (s) inscrite dans un numero de video TikTok (ses 32 bits de
    tete), ou None si ce nombre n'en est pas un."""
    try:
        ts = int(num) >> 32
    except (TypeError, ValueError):
        return None
    return ts if 1_450_000_000 < ts < time.time() + 86400 else None


def _lister_tiktok_creator(username: str, info: Optional[dict] = None,
                           chercher: Optional[set] = None) -> list:
    """La liste d'un profil TikTok par /api/creator/item_list, au format des
    entrées yt-dlp (id, url, view_count, timestamp, title) + « photo ».

    `chercher` : des numeros de videos DEJA dans le dossier. La lecture va
    au-dela des MAX_EXAMINEES dernieres tant qu'il en manque (jusqu'a leur
    date), et rend celles-la marquees « au_dela » : pour leurs vues seules."""
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
                if info is not None:
                    info["avatar"] = (user.get("avatarLarger") or user.get("avatarMedium")
                                      or user.get("avatarThumb") or "")
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
    chercher = {c for c in (chercher or ()) if date_numero_tiktok(c)}
    for _ in range(MAX_PAGES_PROFOND if chercher else MAX_PAGES_CREATOR):
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
        if not neufs or not j.get("hasMorePrevious"):
            break
        # Page suivante : ce qui a été posté avant la plus ancienne reçue.
        curseur = min(int(it.get("createTime") or 0) for it in items) * 1000
        if len(vus) >= MAX_EXAMINEES:
            reste = chercher - vus.keys()
            # plus rien a trouver, ou deja plus ancien que la plus ancienne
            # cherchee (a un jour pres : elle a ete supprimee du profil)
            if not reste or curseur < (min(date_numero_tiktok(c) for c in reste) - 86400) * 1000:
                break
        time.sleep(0.6)
    out = []
    for i, (vid, it) in enumerate(vus.items()):
        au_dela = i >= MAX_EXAMINEES
        if au_dela and vid not in chercher:
            continue
        vues = (it.get("stats") or {}).get("playCount")
        out.append({"id": vid, "au_dela": au_dela,
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


def _lister_instagram(username: str, info: Optional[dict] = None) -> list:
    """Les reels d'un profil, les plus récents d'abord, au format des entrées
    yt-dlp (id, url, view_count, timestamp, title) plus video_url, que
    HikerAPI rend dans le même appel.

    Appels directs de HikerAPI, PAS d'insta_scraper.scrape_profile : ce
    dernier range le profil dans le cache de la veille Trends, et chaque
    dossier d'inspiration serait apparu dans Trends. Comptés sur la réserve
    du vault, pas sur l'enveloppe du suivi des comptes.

    Une lecture arrêtée en route (réserve vide, erreur sur une page) rend ce
    qui a été lu et le DIT dans info["incomplet"] : le bandeau l'affiche."""
    import hiker_reels as _hk
    jeton = _hk.get_token()
    if not jeton:
        raise RuntimeError("HikerAPI : jeton absent")
    if not _consommer_insta(1):
        raise RuntimeError(f"réserve HikerAPI du vault épuisée pour aujourd'hui "
                           f"({PLAFOND_JOUR_INSTA} requêtes) — nouvel essai demain")
    data, err = _hk._appel("/v1/user/by/username", jeton, 45, username=username)
    if err:
        raise RuntimeError("HikerAPI : " + err)
    user = data.get("user") if isinstance((data or {}).get("user"), dict) else (data or {})
    pk = user.get("pk") or user.get("id")
    if not pk:
        raise RuntimeError("HikerAPI : profil introuvable")
    if user.get("is_private"):
        raise RuntimeError("profil privé : ses reels ne sont pas lisibles")
    if info is not None:
        # Même appel que la liste : la photo ne coûte aucune requête de plus.
        info["avatar"] = user.get("profile_pic_url_hd") or user.get("profile_pic_url") or ""
    out, vus, page = [], set(), ""
    while len(out) < MAX_EXAMINEES_INSTA:
        if not _consommer_insta(1):
            if info is not None:
                info["incomplet"] = (f"réserve HikerAPI du jour épuisée après {len(out)} "
                                     "reels — la suite à la prochaine relecture")
            break
        params = {"user_id": pk}
        if page:
            params["page_id"] = page
        data, err = _hk._appel("/v2/user/clips", jeton, 60, **params)
        if err:
            if not out:
                raise RuntimeError("HikerAPI : " + err)
            if info is not None:
                info["incomplet"] = f"lecture arrêtée après {len(out)} reels : {err[:120]}"
            break
        rep = (data or {}).get("response") or {}
        items = rep.get("items") if isinstance(rep, dict) else None
        items = items if isinstance(items, list) else []
        for it in items:
            m = it.get("media") if isinstance(it.get("media"), dict) else it
            if not isinstance(m, dict):
                continue
            code = m.get("code") or ""
            if not code or code in vus:
                continue
            vus.add(code)
            vues = m.get("play_count")
            if vues is None:
                vues = m.get("view_count")
            out.append({"id": code,
                        # le numero long, que gardent certains telechargements
                        # (« …_DbJxrPKKSDn_3947905023860089063.mp4 »)
                        "pk": str(m.get("pk") or "").split("_")[0],
                        "url": f"https://www.instagram.com/reel/{code}/",
                        "view_count": int(vues) if isinstance(vues, (int, float)) else None,
                        "timestamp": _hk._horodatage(m.get("taken_at_ts") or m.get("taken_at")) or None,
                        "title": _hk._legende(m) or "",
                        "video_url": _hk._url_video(m)})
        page = (data or {}).get("next_page_id") or ""
        if not page or not items:
            break
    return out[:MAX_EXAMINEES_INSTA]


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


def _lister(src: dict, bilan: Optional[dict] = None,
            info: Optional[dict] = None, chercher: Optional[set] = None) -> list:
    """La liste du profil. TikTok : l'API « creator » d'abord (la seule qui
    réponde depuis le VPS), yt-dlp en secours — tous deux gratuits."""
    if src.get("plateforme") == "instagram":
        if bilan is not None:
            bilan["source"] = "HikerAPI"
        return _lister_instagram(src.get("username") or "", info)
    try:
        out = _lister_tiktok_creator(src.get("username") or "", info, chercher)
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


_EXT_IMAGE = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
              "image/webp": "webp"}


def _poser_avatar(dossier_identite: Path, url: str) -> str:
    """La photo du profil devient celle du dossier — SEULEMENT s'il n'en a
    pas : une photo choisie à la création ou changée à la main l'emporte.
    Rend le nom du fichier posé, '' sinon."""
    if not url or any(dossier_identite.glob("avatar.*")):
        return ""
    try:
        from curl_cffi import requests as _http
        r = _http.get(url, impersonate="chrome", timeout=30)
    except ImportError:
        import requests as _http
        r = _http.get(url, timeout=30)
    if r.status_code != 200 or len(r.content) < 512:
        raise RuntimeError(f"photo de profil : HTTP {r.status_code}")
    type_ = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = _EXT_IMAGE.get(type_)
    if not ext:
        # HEIC, AVIF… : le site ne sert que png/jpg/webp (_identity_avatar_path).
        raise RuntimeError(f"photo de profil : format {type_ or 'inconnu'} non géré")
    final = dossier_identite / f"avatar.{ext}"
    tmp = dossier_identite / f".avatar.{ext}.tmp"
    tmp.write_bytes(r.content)
    os.replace(tmp, final)
    return final.name


def _rapatrier(dossier: Path) -> int:
    """Déplace dans ``dossier`` les vidéos importées restées dans l'ancien
    sous-dossier (Reels), avec TOUS leurs voisins. Ne supprime rien : un nom
    déjà pris à l'arrivée reste où il est, et c'est compté dans le journal."""
    ancien = dossier.parent / ANCIEN_SOUS_DOSSIER
    if dossier.name == ANCIEN_SOUS_DOSSIER or not ancien.is_dir():
        return 0
    deplaces = 0
    for voisin in sorted(ancien.glob("*" + SUFFIXE)):
        stem = voisin.name[:-len(SUFFIXE)]
        if not stem.startswith(tuple(PREFIXES.values())):
            continue
        for f in sorted(ancien.glob(stem + ".*")):
            cible = dossier / f.name
            if cible.exists():
                print(f"[vault-social] {f.name} déjà dans {dossier.name}, laissé en place",
                      flush=True)
                continue
            shutil.move(str(f), str(cible))
            if f.suffix.lower() in EXTS_VIDEO:
                deplaces += 1
    return deplaces


class _DejaLa(Exception):
    """La video telechargee est deja dans le dossier sous un autre nom."""


#: Un numero de publication plus court pourrait etre un mot du titre.
NUMERO_MIN = 9


def _noms_etrangers(dossier: Path, prefixe: str) -> list:
    """Les videos du dossier qui ne viennent pas de CETTE source, triees."""
    try:
        return sorted(p.name for p in dossier.iterdir()
                      if p.is_file() and p.suffix.lower() in EXTS_VIDEO
                      and not p.name.startswith(prefixe))
    except OSError:
        return []


def _porte_le_numero(noms: list, *numeros: str) -> Optional[str]:
    """Le premier de `noms` qui porte l'un de ces numeros ENTIER (ni lettre
    ni chiffre colle devant ou derriere).

    Les telechargements en masse gardent le numero de la publication :
    « ibenhaastrup__#fyp_7129973973982563590_bulk.mp4 », « mikkibunni_2026-
    07-24_DbJxrPKKSDn_3947905023860089063.mp4 ». Le 26/09/2026, 190 videos
    sur 193 d'ibenhaastrup etaient ainsi nommees, et restaient sans vues :
    l'import ne les reconnaissait qu'a SON nom (tt_<numero>), et la
    comparaison a l'image les aurait toutes retelechargees pour conclure."""
    for num in numeros:
        num = str(num or "")
        if len(num) < NUMERO_MIN:
            continue
        motif = None
        for nom in noms:
            if num not in nom:
                continue
            motif = motif or re.compile(r"(?<![A-Za-z0-9])" + re.escape(num) + r"(?![A-Za-z0-9])")
            if motif.search(nom):
                return nom
    return None


def _jumeau(brut: Path, dossier: Path) -> Optional[Path]:
    """Le fichier du dossier qui est la MEME video que `brut`, ou None.
    Une panne de la comparaison n'empeche pas l'import : elle se dit."""
    try:
        import empreintes_video as _ev
        return _ev.trouver_doublon(brut, dossier)
    except Exception as err:
        print(f"[vault-social] comparaison au contenu indisponible : {err}", flush=True)
        return None


def _vues_sur_jumeau(dossier: Path, nom: str, voisin: dict) -> bool:
    """Pose les vues sur le fichier deja la (badge de la galerie) -- sauf
    s'il porte deja celles d'une AUTRE source : on n'ecrase pas les vues
    TikTok d'une video par celles de son double Instagram. Vrai si ecrit."""
    stem = Path(nom).stem
    chemin = dossier / (stem + SUFFIXE)
    ancien = safe_json.load(chemin, default={}) if chemin.exists() else {}
    ancien = ancien if isinstance(ancien, dict) else {}
    if ancien and (ancien.get("plateforme"), str(ancien.get("id"))) != (voisin.get("plateforme"), str(voisin.get("id"))):
        return False
    v = {k: val for k, val in voisin.items() if not k.startswith("_")}
    if ancien.get("vues") == v.get("vues") and ancien.get("titre") == v.get("titre"):
        return False
    ancien.update(v)
    return _ecrire_voisin(dossier, stem, ancien)


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
    #: {id: fichier} : les videos reconnues DEJA PRESENTES sous un autre nom
    #: (deposees a la main, ou venues de l'autre reseau) -- jamais importees
    #: une seconde fois, jamais retelechargees (empreintes_video).
    doublons = dict(src.get("doublons") or {})
    bilan = {"examinees": 0, "au_dessus": 0, "deja_la": 0, "nouvelles": 0,
             "sous_seuil": 0, "vues_inconnues": 0, "retirees_a_la_main": 0,
             "photos": 0, "echecs": 0, "abandonnees": 0, "vues_maj": 0,
             "doublons": 0}
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
    tmp = FICHIER.parent / "_vault_social_tmp" / ident.replace(SEP_SOURCE, "__")
    try:
        if not dossier_videos.parent.is_dir():
            raise RuntimeError("dossier introuvable dans le vault")
        dossier_videos.mkdir(exist_ok=True)
        bilan["rapatriees"] = _rapatrier(dossier_videos)
        tmp.mkdir(parents=True, exist_ok=True)
        info: Dict[str, Any] = {}
        etrangers = _noms_etrangers(dossier_videos, prefixe)
        chercher = {n for nom in etrangers
                    for n in re.findall(r"(?<![A-Za-z0-9])([0-9]{15,20})(?![A-Za-z0-9])", nom)}
        entrees = _lister(src, bilan, info, chercher)
        if info.get("incomplet"):
            bilan["incomplet"] = info["incomplet"]
        try:
            if _poser_avatar(dossier_videos.parent, info.get("avatar") or ""):
                bilan["photo"] = True
        except Exception as err_pp:
            # Sans photo, le dossier garde son initiale : ce n'est pas une
            # raison d'arrêter l'import. Mais ça se dit.
            print(f"[vault-social] {ident} : {err_pp}", flush=True)
        liste_lue = True
        bilan["examinees"] = sum(1 for e in entrees if not e.get("au_dela"))
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
            if vid not in doublons:
                nom = _porte_le_numero(etrangers, vid, e.get("pk"))
                if nom:
                    # deja la sous un autre nom, et ce nom le dit : c'est un
                    # doublon reconnu sans rien telecharger
                    doublons[vid] = nom
            if vid in doublons:
                # deja present sous un autre nom : ses vues suivent sur le
                # fichier qui est la (badge), sans rien retelecharger
                bilan["doublons"] += 1
                if (dossier_videos / doublons[vid]).exists() and isinstance(vues, int):
                    if _vues_sur_jumeau(dossier_videos, doublons[vid], voisin):
                        bilan["vues_maj"] += 1
                continue
            if e.get("au_dela"):
                continue    # lue pour les vues d'un fichier du dossier, pas a importer
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
        # La comparaison au contenu ne sert que si le dossier a des videos
        # d'une AUTRE origine (deposees a la main, ou de l'autre reseau) :
        # entre elles, les videos d'une meme source se reconnaissent a leur
        # numero. Un import neuf ne paie donc rien.
        comparer = bool(etrangers)
        for i, (vid, stem, voisin) in enumerate(a_prendre):
            try:
                brut = _telecharger(src, voisin, tmp / stem)
                if not dossier_videos.is_dir():
                    try:
                        brut.unlink()
                    except OSError:
                        pass
                    raise RuntimeError("dossier renommé ou archivé pendant la relecture")
                jumeau = _jumeau(brut, dossier_videos) if comparer else None
                if jumeau is not None:
                    # Deja la sous un autre nom : le telechargement (hors du
                    # vault) repart, rien du vault n'est touche.
                    try:
                        brut.unlink()
                    except OSError:
                        pass
                    doublons[vid] = jumeau.name
                    bilan["doublons"] += 1
                    voisin.pop("_video_url", None)
                    _vues_sur_jumeau(dossier_videos, jumeau.name, voisin)
                    echecs.pop(vid, None)
                    raise _DejaLa()
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
                comparer = True   # la suivante peut etre ce meme contenu
            except _DejaLa:
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
                if not _maj(ident, creer=False, recus=sorted(recus),
                            photos=sorted(photos), echecs=echecs, doublons=doublons):
                    # Debranche (ou renomme) en route : sans ca, tout le
                    # profil descendait quand meme dans le dossier.
                    raise RuntimeError("profil débranché pendant la relecture")
            time.sleep(PAUSE_SEC)
        _maj(ident, creer=False, statut="ok", erreur="", reessai_le=None,
             derniere_synchro=int(time.time()), bilan=bilan,
             recus=sorted(recus), photos=sorted(photos), echecs=echecs,
             doublons=doublons)
        return {"ok": True, "bilan": bilan}
    except Exception as err:
        msg = str(err).strip().splitlines()[0][:300] if str(err).strip() else type(err).__name__
        champs = {"statut": "erreur", "erreur": msg,
                  # Réessai demain, pas toutes les demi-heures (un profil qui
                  # répond 403 serait relu en boucle), ni dans deux semaines.
                  "reessai_le": int(time.time()) + REESSAI_SEC,
                  "recus": sorted(recus), "photos": sorted(photos),
                  "echecs": echecs, "doublons": doublons}
        # Liste refusée : le bilan précédent reste. L'écraser par des zéros
        # faisait annoncer « 0 dans le dossier » à côté de 40 vidéos.
        if liste_lue:
            champs["bilan"] = bilan
        _maj(ident, creer=False, **champs)
        print(f"[vault-social] {ident} : {msg}", flush=True)
        return {"ok": False, "error": msg, "bilan": bilan}
    finally:
        with _verrou:
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
        # SA PLACE et ce qui passe avant : « en file d'attente » tout court,
        # sur treize dossiers d'un coup, ressemblait a une panne.
        reg = _registre()
        voie = _voie(ident, reg)
        with _verrou:
            if ident not in _file_attente:
                return None
            devant = [k for k in _file_attente[:_file_attente.index(ident)] if _voie(k, reg) == voie]
            actifs = [(k, dict(v)) for k, v in _en_cours.items() if _voie(k, reg) == voie]
        etape = f"en file d'attente ({len(devant) + 1}e)"
        if actifs:
            k, p = actifs[0]
            etape += f" — en cours : @{identite_de(k)}" + (
                f" {p.get('fait', 0)}/{p['total']}" if p.get("total") else "")
        return {"fait": 0, "total": 0, "etape": etape}
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
    # un clic passe DEVANT la file : derriere treize profils, « Relire
    # maintenant » attendait des heures
    planifier(ident, devant=True)
    return {"ok": True}


# --------------------------------------------------------------- la file

_dossier_de: Callable[[str], Optional[Path]] = lambda ident: None
_apres_global: Optional[Callable[[], None]] = None


def planifier(identite: str, devant: bool = False) -> bool:
    """Met un dossier dans la file de son réseau (une synchro à la fois par
    réseau : deux profils TikTok lus en parallèle, c'est le 403 assuré).
    `devant` : en tête de file (un clic de l'utilisateur).

    Un dossier EN COURS de relecture est remis en file : un seuil changé ou
    un « Relire » cliqué pendant la relecture était sinon perdu, alors que le
    site répondait « relecture lancée ». La demande est aussi écrite dans le
    registre, pour survivre à un redémarrage du bot.
    """
    ident = (identite or "").lower()
    _maj(ident, creer=False, demande=True)
    with _verrou:
        if ident in _file_attente:
            if not devant:
                return False
            _file_attente.remove(ident)
        if devant:
            _file_attente.insert(0, ident)
        else:
            _file_attente.append(ident)
    _assurer_travailleur()
    return True


def _assurer_travailleur():
    with _verrou:
        for voie in VOIES:
            t = _travailleurs.get(voie)
            if t is not None and t.is_alive():
                continue
            t = threading.Thread(target=_boucle, args=(voie,), daemon=True,
                                 name=f"vault-social-{voie}")
            _travailleurs[voie] = t
            t.start()


def _voie(cle: str, reg: Optional[dict] = None) -> str:
    """Le reseau d'une cle (sa file). `reg` : le registre deja lu.
    Un reseau inconnu va dans la premiere file : sinon aucune ne le prenait
    et il restait « en file d'attente » pour toujours."""
    if cle in _voie_active:
        return _voie_active[cle]
    e = (reg if reg is not None else _registre()).get(cle) or {}
    v = e.get("plateforme") or VOIES[0]
    return v if v in VOIES else VOIES[0]


def _prendre(voie: str) -> Optional[str]:
    """La premiere cle en file pour ce reseau dont l'IDENTITE n'est pas deja
    en cours : ses deux profils ecrivent dans le meme dossier, et lus en
    parallele, une video publiee sur les deux reseaux passerait deux fois
    (chacun la compare au dossier avant que l'autre l'y ait posee)."""
    with _verrou:
        # lu SOUS le verrou : un profil branche entre la lecture et la prise
        # partait sinon dans la mauvaise file
        reg = _registre()
        # un reseau deja en cours ne prend rien de plus : deux TikTok en
        # parallele, c'est le 403 -- verifie ici, pas seulement suppose par
        # le nombre de fils
        if any(_voie(k, reg) == voie for k in _en_cours):
            return None
        occupees = {identite_de(k) for k in _en_cours}
        for i, k in enumerate(_file_attente):
            if _voie(k, reg) != voie or identite_de(k) in occupees:
                continue
            _file_attente.pop(i)
            # reserve AVANT de relacher le verrou : l'autre file la voit prise
            _en_cours[k] = {"fait": 0, "total": 0, "etape": "démarrage"}
            _voie_active[k] = voie
            return k
    return None


def _dus(maintenant: float) -> list:
    """Les dossiers à relire. Un « en_cours » du registre absent de _en_cours
    est une relecture interrompue (redémarrage du bot), qu'on reprend au lieu
    d'attendre deux semaines ; celle que fait l'autre file est dans _en_cours."""
    out = []
    for ident, e in _registre().items():
        if not e.get("url") or ident in _en_cours:
            continue
        if (e.get("demande") or e.get("statut") == "en_cours"
                or maintenant >= (prochaine(ident) or 0)):
            out.append(ident)
    return out


def _boucle(voie: str = "tiktok"):
    while True:
        try:
            _un_tour(voie)
        except Exception as err:
            # Un fil mort laissait sa file « en file d'attente » sans fin et
            # sans un mot : on le dit, et on continue.
            print(f"[vault-social] file {voie} : {type(err).__name__}: {err}", flush=True)
            time.sleep(60)


def _un_tour(voie: str) -> None:
    ident = _prendre(voie)
    if ident:
        try:
            dossier = _dossier_de(ident)
            if dossier is None:
                # Dossier supprimé ou renommé : le dire dans le registre,
                # ne pas relire un profil pour rien.
                _maj(ident, creer=False, statut="erreur", demande=False,
                     erreur="dossier introuvable dans le vault",
                     reessai_le=int(time.time()) + REESSAI_SEC)
            else:
                synchroniser(ident, dossier, _apres_global)
        finally:
            # synchroniser le fait ; ici pour ses sorties anticipees et le
            # dossier introuvable, sinon l'identite resterait « occupee »
            with _verrou:
                _en_cours.pop(ident, None)
                _voie_active.pop(ident, None)
        return
    # File vide : toutes les demi-heures, qui est dû ? Le premier fil libre
    # s'en charge ; planifier range chaque profil dans la bonne file.
    with _verrou:
        du = time.time() - _dernier_tour[0] >= 1800
        if du:
            _dernier_tour[0] = time.time()
    if du:
        for ident2 in _dus(time.time()):
            planifier(ident2)
        return
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
