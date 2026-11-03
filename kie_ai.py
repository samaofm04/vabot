"""kie_ai.py — client Kie.ai et registre des modèles du Studio IA.

Kie.ai (https://docs.kie.ai) expose un marché de modèles derrière une seule
API : POST /api/v1/jobs/createTask lance une tâche, GET /api/v1/jobs/recordInfo
dit où elle en est, GET /api/v1/chat/credit donne le solde. Une tâche est
asynchrone (quelques secondes pour une image, plusieurs minutes pour une
vidéo) ; ses fichiers restent 14 jours chez eux, studio_ia.py les rapatrie.

Les images de référence doivent être des URL publiques : l'API de dépôt
(kieai.redpandaai.co) les héberge 24 h, le temps que la tâche les lise.

La clé reste ici, côté serveur : KIE_API_KEY dans l'environnement, ou dans
le .env du VPS (relu si l'environnement ne la porte pas, pour qu'ajouter la
clé n'oblige pas à redémarrer). Elle ne sort jamais dans les journaux ni
dans une réponse HTTP.

Ce module ne connaît ni Flask ni le dashboard : studio_ia.py s'en sert.
Paramètres et prix relevés dans la doc et sur kie.ai le 03/11/2026 ; les
prix servent à l'ESTIMATION affichée avant le clic, Kie fait foi ensuite
(creditsConsumed sur la tâche finie).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BOT_DIR = Path(__file__).resolve().parent
BASE = "https://api.kie.ai"
BASE_DEPOT = "https://kieai.redpandaai.co"
UA = "youl4b-vabot/1.0"
DELAI = 30
#: au-delà, le dépôt passe en flux multipart (la doc conseille ≤ 10 Mo en base64)
TAILLE_BASE64 = 9_000_000
TAILLE_MAX_REF = 30_000_000


class ErreurKie(Exception):
    """Une réponse de Kie.ai qui n'est pas un succès, ou pas de réponse.
    `code` : le code Kie (401, 402…) ou un mot ("reseau", "sans_cle")."""

    def __init__(self, message: str, code: Any = None):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ clé --

_CLE_ENV = {"valeur": "", "t": 0.0}


def cle() -> str:
    """KIE_API_KEY : l'environnement d'abord (main.py charge le .env au
    démarrage), sinon le .env relu toutes les 30 s. Sans ça, poser la clé
    sur le VPS obligeait à redémarrer le bot pour qu'elle serve."""
    k = (os.environ.get("KIE_API_KEY") or "").strip()
    if k:
        return k
    if time.time() - _CLE_ENV["t"] < 30:
        return _CLE_ENV["valeur"]
    _CLE_ENV["t"] = time.time()
    _CLE_ENV["valeur"] = ""
    try:
        for ligne in (BOT_DIR / ".env").read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if ligne.startswith("KIE_API_KEY="):
                _CLE_ENV["valeur"] = ligne.split("=", 1)[1].strip().strip('"').strip("'")
                break
    except OSError:
        pass
    return _CLE_ENV["valeur"]


def cle_presente() -> bool:
    return bool(cle())


# ------------------------------------------------------------ messages --

_MESSAGES = {
    "fr": {
        "sans_cle": "Clé Kie.ai absente : ajoute KIE_API_KEY=... dans le .env du VPS (kie.ai/api-key).",
        "reseau": "Kie.ai injoignable ({detail}) : réessaie dans un instant.",
        401: "Clé Kie.ai refusée : vérifie KIE_API_KEY dans le .env du VPS.",
        402: "Crédits Kie.ai insuffisants : recharge le compte sur kie.ai.",
        404: "Adresse Kie.ai inconnue (modèle retiré ?) : {detail}",
        422: "Paramètres refusés par Kie.ai : {detail}",
        429: "Kie.ai limite les demandes : réessaie dans une minute.",
        455: "Kie.ai est en maintenance : réessaie plus tard.",
        "autre": "Kie.ai a répondu {code} : {detail}",
    },
    "en": {
        "sans_cle": "Kie.ai key missing: add KIE_API_KEY=... to the VPS .env (kie.ai/api-key).",
        "reseau": "Kie.ai unreachable ({detail}): try again in a moment.",
        401: "Kie.ai key rejected: check KIE_API_KEY in the VPS .env.",
        402: "Not enough Kie.ai credits: top up the account on kie.ai.",
        404: "Unknown Kie.ai endpoint (model removed?): {detail}",
        422: "Parameters rejected by Kie.ai: {detail}",
        429: "Kie.ai is rate-limiting: try again in a minute.",
        455: "Kie.ai is under maintenance: try again later.",
        "autre": "Kie.ai answered {code}: {detail}",
    },
}


def message_pour(code: Any, detail: str = "", langue: str = "fr") -> str:
    """Le texte à montrer pour un code Kie (ou un mot d'erreur du client)."""
    t = _MESSAGES["en" if langue == "en" else "fr"]
    try:
        c: Any = int(code)
    except (TypeError, ValueError):
        c = code
    gabarit = t.get(c) or t["autre"]
    return gabarit.format(code=c, detail=(detail or "—")[:300])


# ---------------------------------------------------------------- HTTP --

def _requete(methode: str, url: str, *, json_: Any = None, data: Any = None,
             files: Any = None, timeout: float = DELAI) -> Dict[str, Any]:
    """Le seul point de sortie HTTP vers Kie : un seul endroit pour la clé,
    les délais et la lecture du `code` (Kie répond HTTP 200 même en échec,
    le vrai verdict est dans le corps). Les tests le remplacent."""
    k = cle()
    if not k:
        raise ErreurKie(message_pour("sans_cle"), "sans_cle")
    entetes = {"Authorization": "Bearer " + k, "User-Agent": UA}
    try:
        r = requests.request(methode, url, json=json_, data=data, files=files,
                             headers=entetes, timeout=timeout)
    except requests.RequestException as e:
        raise ErreurKie(message_pour("reseau", type(e).__name__), "reseau")
    try:
        d = r.json()
    except ValueError:
        raise ErreurKie(message_pour("autre", f"HTTP {r.status_code}, corps illisible", ),
                        r.status_code)
    if not isinstance(d, dict):
        raise ErreurKie(message_pour("autre", "corps inattendu"), r.status_code)
    code = d.get("code", r.status_code)
    try:
        code = int(code)
    except (TypeError, ValueError):
        pass
    if code != 200:
        raise ErreurKie(message_pour(code, str(d.get("msg") or d.get("message") or "")), code)
    return d


def credits() -> float:
    """Solde du compte (crédits, décimales possibles)."""
    d = _requete("GET", BASE + "/api/v1/chat/credit")
    try:
        return float(d.get("data"))
    except (TypeError, ValueError):
        raise ErreurKie(message_pour("autre", "solde illisible"), "solde")


def creer_tache(modele_api: str, entree: Dict[str, Any],
                rappel: Optional[str] = None) -> str:
    """Lance une tâche ; renvoie son taskId."""
    corps: Dict[str, Any] = {"model": modele_api, "input": entree}
    if rappel:
        corps["callBackUrl"] = rappel
    d = _requete("POST", BASE + "/api/v1/jobs/createTask", json_=corps, timeout=60)
    tid = str((d.get("data") or {}).get("taskId") or "")
    if not tid:
        raise ErreurKie(message_pour("autre", "pas de taskId dans la réponse"), "sans_tache")
    return tid


def detail_tache(task_id: str) -> Dict[str, Any]:
    """L'état d'une tâche : {state, resultUrls, failCode, failMsg,
    creditsConsumed, costTime}. `state` ∈ waiting, queuing, generating,
    success, fail."""
    d = _requete("GET", BASE + "/api/v1/jobs/recordInfo?taskId="
                 + requests.utils.quote(str(task_id)))
    data = d.get("data") or {}
    urls: List[str] = []
    brut = data.get("resultJson")
    res: Any = None
    if isinstance(brut, str) and brut.strip():
        try:
            res = json.loads(brut)
        except ValueError:
            res = None
    if res is None and isinstance(data.get("response"), dict):
        res = data.get("response")
    if isinstance(res, dict):
        for u in res.get("resultUrls") or []:
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
    return {
        "state": str(data.get("state") or ""),
        "resultUrls": urls,
        "failCode": str(data.get("failCode") or ""),
        "failMsg": str(data.get("failMsg") or ""),
        "creditsConsumed": data.get("creditsConsumed"),
        "costTime": data.get("costTime"),
    }


def televerser(octets: bytes, nom: str, mime: str) -> str:
    """Dépose un fichier chez Kie (24 h) et renvoie son URL publique, celle
    qu'une tâche peut lire. Base64 jusqu'à 9 Mo, flux multipart au-delà."""
    nom = re.sub(r"[^A-Za-z0-9._-]+", "_", nom or "fichier")[:80] or "fichier"
    chemin = "youl4b/studio-ia"
    if len(octets) <= TAILLE_BASE64:
        corps = {"base64Data": f"data:{mime};base64," + base64.b64encode(octets).decode("ascii"),
                 "uploadPath": chemin, "fileName": nom}
        d = _requete("POST", BASE_DEPOT + "/api/file-base64-upload", json_=corps, timeout=120)
    else:
        d = _requete("POST", BASE_DEPOT + "/api/file-stream-upload",
                     files={"file": (nom, octets, mime)},
                     data={"uploadPath": chemin, "fileName": nom}, timeout=300)
    data = d.get("data") or {}
    url = str(data.get("downloadUrl") or data.get("fileUrl") or "")
    if not url.startswith("http"):
        raise ErreurKie(message_pour("autre", "dépôt sans URL en retour"), "depot")
    return url


def telecharger(url: str, dest: Path) -> Tuple[int, str]:
    """Rapatrie un résultat (URL publique, sans clé) : .part puis replace,
    pour ne jamais laisser un fichier tronqué sous son nom final."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with requests.get(url, stream=True, timeout=(15, 180),
                          headers={"User-Agent": UA}) as r:
            r.raise_for_status()
            ctype = str(r.headers.get("Content-Type") or "").split(";")[0].strip()
            n = 0
            with open(part, "wb") as f:
                for morceau in r.iter_content(chunk_size=1 << 16):
                    if morceau:
                        f.write(morceau)
                        n += len(morceau)
        if n <= 0:
            raise ErreurKie("fichier vide", "vide")
        os.replace(part, dest)
        return n, ctype
    except requests.RequestException as e:
        try:
            part.unlink()
        except OSError:
            pass
        raise ErreurKie(message_pour("reseau", type(e).__name__), "reseau")


# ----------------------------------------------------- registre modèles --
# Chaque modèle décrit ses options (ce que l'écran propose), ses références
# (combien d'images, et comment elles sont lues), son prix et la façon de
# bâtir l'`input` de createTask. L'écran se construit depuis ce registre :
# ajouter un modèle = ajouter une entrée, pas une page.

_FORMATS_VIDEO = ["9:16", "16:9", "1:1"]
_FORMATS_SEEDANCE = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "adaptive"]
_FORMATS_WAN = ["9:16", "16:9", "1:1", "4:3", "3:4", "adaptive"]
_FORMATS_IMAGE = ["9:16", "16:9", "1:1", "4:3", "3:4", "2:3", "3:2", "21:9"]
_LIB_FORMATS = {"adaptive": {"fr": "auto (suit l'image)", "en": "auto (follows the image)"}}

_OPT_FORMAT_VIDEO = {"cle": "aspect_ratio", "nom": "Format", "nom_en": "Aspect ratio",
                     "type": "choix", "valeurs": _FORMATS_VIDEO, "defaut": "9:16",
                     "aide": "9:16 = vertical, pour les Reels", "aide_en": "9:16 = vertical, for Reels"}
_OPT_USAGE_REFS = {"cle": "usage_refs", "nom": "Images envoyées", "nom_en": "Uploaded images",
                   "type": "choix", "valeurs": ["cadres", "references"], "defaut": "cadres",
                   "libelles": {"cadres": {"fr": "1re / dernière image", "en": "first / last frame"},
                                "references": {"fr": "références", "en": "references"}},
                   "aide": "Cadres : la 1re image ouvre la vidéo, la 2e la ferme. Références : le modèle s'en inspire.",
                   "aide_en": "Frames: the first image opens the video, the second closes it. References: the model draws on them.",
                   "si_refs": True}

TYPES_IMAGE = ("image/jpeg", "image/png", "image/webp")

MODELES: List[Dict[str, Any]] = [
    {
        "cle": "kling3", "nom": "Kling 3.0", "editeur": "Kuaishou", "type": "video",
        "resume": "std / pro / 4K · 3–15 s · son en option",
        "resume_en": "std / pro / 4K · 3–15 s · optional sound",
        "modele_api": "kling-3.0/video", "prompt_max": 2500,
        "references": {"max": 2, "modes": ["cadres"], "types": ("image/jpeg", "image/png"),
                       "aide": "1 image = première image de la vidéo ; 2 = première et dernière (JPG/PNG, 10 Mo).",
                       "aide_en": "1 image = first frame; 2 = first and last frame (JPG/PNG, 10 MB)."},
        "options": [
            {"cle": "mode", "nom": "Qualité", "nom_en": "Quality", "type": "choix",
             "valeurs": ["std", "pro", "4K"], "defaut": "std",
             "libelles": {"std": {"fr": "Standard 720p", "en": "Standard 720p"},
                          "pro": {"fr": "Pro 1080p", "en": "Pro 1080p"},
                          "4K": {"fr": "4K", "en": "4K"}}},
            _OPT_FORMAT_VIDEO,
            {"cle": "duration", "nom": "Durée", "nom_en": "Duration", "type": "nombre",
             "min": 3, "max": 15, "defaut": 5, "unite": "s"},
            {"cle": "sound", "nom": "Son généré", "nom_en": "Generated sound", "type": "bool",
             "defaut": False, "aide": "Voix, bruitages et ambiance (plus cher en std et pro)",
             "aide_en": "Voice, effects and ambience (costs more in std and pro)"},
        ],
    },
    {
        "cle": "kling3turbo", "nom": "Kling 3.0 Turbo", "editeur": "Kuaishou", "type": "video",
        "resume": "720p / 1080p · 3–15 s · son toujours inclus",
        "resume_en": "720p / 1080p · 3–15 s · sound always on",
        "modele_api": "kling/v3-turbo-text-to-video", "modele_api_image": "kling/v3-turbo-image-to-video",
        "prompt_max": 2500,
        "references": {"max": 1, "modes": ["cadres"], "types": ("image/jpeg", "image/png"),
                       "aide": "1 image = première image de la vidéo (JPG/PNG, 10 Mo). Le format suit l'image.",
                       "aide_en": "1 image = first frame (JPG/PNG, 10 MB). The ratio follows the image."},
        "options": [
            {"cle": "resolution", "nom": "Résolution", "nom_en": "Resolution", "type": "choix",
             "valeurs": ["720p", "1080p"], "defaut": "720p"},
            _OPT_FORMAT_VIDEO,
            {"cle": "duration", "nom": "Durée", "nom_en": "Duration", "type": "nombre",
             "min": 3, "max": 15, "defaut": 5, "unite": "s"},
        ],
    },
    {
        "cle": "seedance25", "nom": "Seedance 2.5", "editeur": "ByteDance", "type": "video",
        "resume": "480p / 720p / 1080p · 4–30 s · audio synchronisé",
        "resume_en": "480p / 720p / 1080p · 4–30 s · synced audio",
        "modele_api": "bytedance/seedance-2-5", "prompt_max": 20000,
        "references": {"max": 9, "modes": ["cadres", "references"], "types": TYPES_IMAGE,
                       "aide": "Jusqu'à 9 images (JPG/PNG/WebP, 300–6000 px). En cadres : 1 = première image, 2 = première et dernière.",
                       "aide_en": "Up to 9 images (JPG/PNG/WebP, 300–6000 px). As frames: 1 = first, 2 = first and last."},
        "options": [
            {"cle": "resolution", "nom": "Résolution", "nom_en": "Resolution", "type": "choix",
             "valeurs": ["480p", "720p", "1080p"], "defaut": "720p"},
            {"cle": "aspect_ratio", "nom": "Format", "nom_en": "Aspect ratio", "type": "choix",
             "valeurs": _FORMATS_SEEDANCE, "defaut": "9:16", "libelles": _LIB_FORMATS},
            {"cle": "duration", "nom": "Durée", "nom_en": "Duration", "type": "nombre",
             "min": 4, "max": 30, "defaut": 5, "unite": "s"},
            {"cle": "generate_audio", "nom": "Audio généré", "nom_en": "Generated audio", "type": "bool",
             "defaut": True, "aide": "Dialogues, ambiance et effets, synchronisés avec la vidéo",
             "aide_en": "Dialogue, ambience and effects, synced with the video"},
            _OPT_USAGE_REFS,
        ],
    },
    {
        "cle": "seedance2fast", "nom": "Seedance 2 Fast", "editeur": "ByteDance", "type": "video",
        "badge": "rapide", "badge_en": "fast",
        "resume": "480p / 720p · 4–15 s · le moins cher des Seedance",
        "resume_en": "480p / 720p · 4–15 s · cheapest Seedance",
        "modele_api": "bytedance/seedance-2-fast", "prompt_max": 20000,
        "references": {"max": 9, "modes": ["cadres", "references"], "types": TYPES_IMAGE,
                       "aide": "Jusqu'à 9 images (JPG/PNG/WebP, 300–6000 px). En cadres : 1 = première image, 2 = première et dernière.",
                       "aide_en": "Up to 9 images (JPG/PNG/WebP, 300–6000 px). As frames: 1 = first, 2 = first and last."},
        "options": [
            {"cle": "resolution", "nom": "Résolution", "nom_en": "Resolution", "type": "choix",
             "valeurs": ["480p", "720p"], "defaut": "720p"},
            {"cle": "aspect_ratio", "nom": "Format", "nom_en": "Aspect ratio", "type": "choix",
             "valeurs": _FORMATS_SEEDANCE, "defaut": "9:16", "libelles": _LIB_FORMATS},
            {"cle": "duration", "nom": "Durée", "nom_en": "Duration", "type": "nombre",
             "min": 4, "max": 15, "defaut": 5, "unite": "s"},
            {"cle": "generate_audio", "nom": "Audio généré", "nom_en": "Generated audio", "type": "bool",
             "defaut": True},
            _OPT_USAGE_REFS,
        ],
    },
    {
        "cle": "wan3", "nom": "Wan 3.0", "editeur": "Alibaba", "type": "video",
        "badge": "le moins cher", "badge_en": "cheapest",
        "resume": "480p / 720p / 1080p · 2–30 s · audio en option",
        "resume_en": "480p / 720p / 1080p · 2–30 s · optional audio",
        "modele_api": "wan/3-0-video", "prompt_max": 20000,
        "references": {"max": 10, "modes": ["cadres", "references"], "types": TYPES_IMAGE,
                       "aide": "Jusqu'à 10 images (JPG/PNG/WebP, 240–8000 px, 20 Mo). En cadres : 1 = première image, 2 = première et dernière.",
                       "aide_en": "Up to 10 images (JPG/PNG/WebP, 240–8000 px, 20 MB). As frames: 1 = first, 2 = first and last."},
        "options": [
            {"cle": "resolution", "nom": "Résolution", "nom_en": "Resolution", "type": "choix",
             "valeurs": ["480P", "720P", "1080P"], "defaut": "720P"},
            {"cle": "aspect_ratio", "nom": "Format", "nom_en": "Aspect ratio", "type": "choix",
             "valeurs": _FORMATS_WAN, "defaut": "9:16", "libelles": _LIB_FORMATS},
            {"cle": "duration", "nom": "Durée", "nom_en": "Duration", "type": "nombre",
             "min": 2, "max": 30, "defaut": 5, "unite": "s"},
            {"cle": "audio", "nom": "Audio généré", "nom_en": "Generated audio", "type": "bool",
             "defaut": True},
            _OPT_USAGE_REFS,
        ],
    },
    {
        "cle": "seedream5pro", "nom": "Seedream 5 Pro", "editeur": "ByteDance", "type": "image",
        "resume": "1K (basic) ou 2K (high) · texte ou retouche d'images",
        "resume_en": "1K (basic) or 2K (high) · text or image editing",
        "modele_api": "seedream/5-pro-text-to-image", "modele_api_image": "seedream/5-pro-image-to-image",
        "prompt_max": 5000, "prompt_min": 4,
        "references": {"max": 10, "modes": ["images"], "types": TYPES_IMAGE,
                       "aide": "Jusqu'à 10 images à retoucher ou combiner (JPG/PNG/WebP, 30 Mo). La 1re est comprise, les suivantes coûtent 0,5 crédit.",
                       "aide_en": "Up to 10 images to edit or combine (JPG/PNG/WebP, 30 MB). The first is included, each extra costs 0.5 credit."},
        "options": [
            {"cle": "quality", "nom": "Qualité", "nom_en": "Quality", "type": "choix",
             "valeurs": ["basic", "high"], "defaut": "basic",
             "libelles": {"basic": {"fr": "Basic (1K)", "en": "Basic (1K)"},
                          "high": {"fr": "High (2K)", "en": "High (2K)"}}},
            {"cle": "aspect_ratio", "nom": "Format", "nom_en": "Aspect ratio", "type": "choix",
             "valeurs": _FORMATS_IMAGE, "defaut": "9:16"},
            {"cle": "output_format", "nom": "Fichier", "nom_en": "File", "type": "choix",
             "valeurs": ["png", "jpeg"], "defaut": "png"},
        ],
    },
    {
        "cle": "seedream5flash", "nom": "Seedream 5 Flash", "editeur": "ByteDance", "type": "image",
        "badge": "le moins cher", "badge_en": "cheapest",
        "resume": "1K / 1.5K / 2K · rapide · texte ou retouche d'images",
        "resume_en": "1K / 1.5K / 2K · fast · text or image editing",
        "modele_api": "seedream/5-flash-text-to-image", "modele_api_image": "seedream/5-flash-image-to-image",
        "prompt_max": 5000, "prompt_min": 4,
        "references": {"max": 10, "modes": ["images"], "types": TYPES_IMAGE,
                       "aide": "Jusqu'à 10 images à retoucher ou combiner (JPG/PNG/WebP, 30 Mo).",
                       "aide_en": "Up to 10 images to edit or combine (JPG/PNG/WebP, 30 MB)."},
        "options": [
            {"cle": "size", "nom": "Taille", "nom_en": "Size", "type": "choix",
             "valeurs": ["1K", "1.5K", "2K"], "defaut": "1K"},
            {"cle": "aspect_ratio", "nom": "Format", "nom_en": "Aspect ratio", "type": "choix",
             "valeurs": _FORMATS_IMAGE, "defaut": "9:16"},
            {"cle": "output_format", "nom": "Fichier", "nom_en": "File", "type": "choix",
             "valeurs": ["png", "jpeg"], "defaut": "png"},
        ],
    },
]

_PAR_CLE = {m["cle"]: m for m in MODELES}

#: Prix en crédits, relevés sur kie.ai le 03/11/2026 (1 crédit ≈ 0,005 $).
#: Vidéo : par seconde ; image : par image. Indicatif : l'estimation sert à
#: prévenir AVANT de dépenser, le compte réel vient de creditsConsumed.
PRIX = {
    "kling3": {"std": (14, 20), "pro": (18, 27), "4K": (67, 67)},   # (sans son, avec son)
    "kling3turbo": {"720p": 18, "1080p": 22.5},
    "seedance25": {"480p": 28, "720p": 63, "1080p": 158},
    "seedance2fast": {"480p": 11.7, "720p": 24.8},
    "wan3": {"480P": 8, "720P": 16, "1080P": 32},
    "seedream5pro": {"basic": 7, "high": 14, "image_sup": 0.5},
    "seedream5flash": {"image": 3.24},
}


def modele(cle_: str) -> Optional[Dict[str, Any]]:
    return _PAR_CLE.get(str(cle_ or "").strip())


def normaliser(cle_: str, options: Any) -> Dict[str, Any]:
    """Les options telles que le modèle les accepte : valeur inconnue ->
    défaut, nombre ramené dans ses bornes, booléen vrai booléen. Ne lève
    pas : un écran qui envoie n'importe quoi obtient les défauts."""
    m = modele(cle_)
    if not m:
        return {}
    options = options if isinstance(options, dict) else {}
    out: Dict[str, Any] = {}
    for o in m["options"]:
        v = options.get(o["cle"], o.get("defaut"))
        if o["type"] == "choix":
            out[o["cle"]] = v if v in o["valeurs"] else o["defaut"]
        elif o["type"] == "nombre":
            try:
                n = int(round(float(v)))
            except (TypeError, ValueError):
                n = int(o["defaut"])
            out[o["cle"]] = max(int(o["min"]), min(int(o["max"]), n))
        elif o["type"] == "bool":
            out[o["cle"]] = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "oui", "on", "yes")
    return out


def estimer(cle_: str, options: Any, nb_refs: int = 0) -> float:
    """Crédits attendus pour cette génération (0 si le modèle est inconnu)."""
    m = modele(cle_)
    if not m:
        return 0.0
    o = normaliser(cle_, options)
    p = PRIX.get(cle_) or {}
    duree = float(o.get("duration") or 0)
    if cle_ == "kling3":
        sans, avec = p.get(o["mode"], (0, 0))
        return round((avec if o.get("sound") else sans) * duree, 2)
    if cle_ == "kling3turbo":
        return round(float(p.get(o["resolution"], 0)) * duree, 2)
    if cle_ in ("seedance25", "seedance2fast", "wan3"):
        return round(float(p.get(o["resolution"], 0)) * duree, 2)
    if cle_ == "seedream5pro":
        return round(float(p.get(o["quality"], 0)) + p["image_sup"] * max(0, int(nb_refs) - 1), 2)
    if cle_ == "seedream5flash":
        return round(float(p["image"]), 2)
    return 0.0


def verifier_prompt(cle_: str, prompt: str, langue: str = "fr") -> str:
    """'' si le prompt convient, sinon le message à montrer."""
    m = modele(cle_)
    if not m:
        return "Modèle inconnu." if langue != "en" else "Unknown model."
    p = (prompt or "").strip()
    mini = int(m.get("prompt_min") or 1)
    if len(p) < mini:
        if langue == "en":
            return f"Write a prompt first ({mini} characters minimum)."
        return f"Écris d'abord un prompt ({mini} caractères minimum)."
    if len(p) > int(m["prompt_max"]):
        if langue == "en":
            return f"Prompt too long: {len(p)} characters, {m['prompt_max']} maximum for {m['nom']}."
        return f"Prompt trop long : {len(p)} caractères, {m['prompt_max']} maximum pour {m['nom']}."
    return ""


def entree_api(cle_: str, prompt: str, options: Any, refs: List[str]) -> Tuple[str, Dict[str, Any]]:
    """(modèle Kie, input de createTask) pour cette demande. `refs` : les URL
    publiques des images, dans l'ordre déposé. Les bornes de nombre et de
    types viennent du registre ; ce qui n'y est pas n'est pas envoyé."""
    m = modele(cle_)
    if not m:
        raise ErreurKie("Modèle inconnu.", "modele")
    o = normaliser(cle_, options)
    p = (prompt or "").strip()
    refs = [r for r in (refs or []) if isinstance(r, str) and r.startswith("http")]
    refs = refs[:int(m["references"]["max"])]
    if cle_ == "kling3":
        e: Dict[str, Any] = {"prompt": p, "duration": str(o["duration"]), "mode": o["mode"],
                             "sound": bool(o["sound"]), "multi_shots": False}
        if refs:
            e["image_urls"] = refs[:2]       # le format suit la première image
        else:
            e["aspect_ratio"] = o["aspect_ratio"]
        return m["modele_api"], e
    if cle_ == "kling3turbo":
        e = {"prompt": p, "duration": str(o["duration"]), "resolution": o["resolution"]}
        if refs:
            e["image_urls"] = refs[:1]
            return m["modele_api_image"], e
        e["aspect_ratio"] = o["aspect_ratio"]
        return m["modele_api"], e
    if cle_ in ("seedance25", "seedance2fast"):
        e = {"prompt": p, "resolution": o["resolution"], "aspect_ratio": o["aspect_ratio"],
             "duration": int(o["duration"]), "generate_audio": bool(o["generate_audio"])}
        _poser_refs(e, refs, o.get("usage_refs"))
        return m["modele_api"], e
    if cle_ == "wan3":
        e = {"prompt": p, "resolution": o["resolution"], "aspect_ratio": o["aspect_ratio"],
             "duration": int(o["duration"]), "audio": bool(o["audio"])}
        _poser_refs(e, refs, o.get("usage_refs"))
        return m["modele_api"], e
    if cle_ == "seedream5pro":
        e = {"prompt": p, "aspect_ratio": o["aspect_ratio"], "quality": o["quality"],
             "output_format": o["output_format"]}
    else:   # seedream5flash
        e = {"prompt": p, "aspect_ratio": o["aspect_ratio"], "size": o["size"],
             "output_format": o["output_format"]}
    if refs:
        e["image_urls"] = refs
        return m["modele_api_image"], e
    return m["modele_api"], e


def _poser_refs(e: Dict[str, Any], refs: List[str], usage: Any) -> None:
    """Seedance et Wan lisent les images soit comme cadres (première,
    dernière), soit comme références libres ; les deux ne se mélangent pas."""
    if not refs:
        return
    if usage == "references":
        e["reference_image_urls"] = refs
        return
    e["first_frame_url"] = refs[0]
    if len(refs) >= 2:
        e["last_frame_url"] = refs[1]


def registre_public(langue: str = "fr") -> List[Dict[str, Any]]:
    """Le registre tel que l'écran le lit : libellés dans la langue, prix de
    base, sans rien d'interne. Sérialisable en JSON."""
    en = langue == "en"
    out = []
    for m in MODELES:
        opts = []
        for o in m["options"]:
            d = {"cle": o["cle"], "nom": o.get("nom_en") if en and o.get("nom_en") else o["nom"],
                 "type": o["type"], "defaut": o.get("defaut")}
            if o["type"] == "choix":
                d["valeurs"] = list(o["valeurs"])
                lib = o.get("libelles") or {}
                d["libelles"] = {k: (v.get("en") if en else v.get("fr")) if isinstance(v, dict) else v
                                 for k, v in lib.items()}
            if o["type"] == "nombre":
                d.update({"min": o["min"], "max": o["max"], "unite": o.get("unite", "")})
            aide = o.get("aide_en") if en and o.get("aide_en") else o.get("aide")
            if aide:
                d["aide"] = aide
            if o.get("si_refs"):
                d["si_refs"] = True
            opts.append(d)
        r = m["references"]
        out.append({
            "cle": m["cle"], "nom": m["nom"], "editeur": m["editeur"], "type": m["type"],
            "badge": (m.get("badge_en") if en else m.get("badge")) or "",
            "resume": m.get("resume_en") if en and m.get("resume_en") else m.get("resume", ""),
            "prompt_max": m["prompt_max"], "prompt_min": int(m.get("prompt_min") or 1),
            "references": {"max": r["max"], "modes": list(r["modes"]), "types": list(r["types"]),
                           "aide": r.get("aide_en") if en and r.get("aide_en") else r.get("aide", "")},
            "options": opts,
            "estimation_defaut": estimer(m["cle"], {}, 0),
        })
    return out
