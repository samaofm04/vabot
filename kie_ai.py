"""kie_ai.py — client Kie.ai et registre des modèles du Studio IA.

Kie.ai (https://docs.kie.ai) expose un marché de modèles derrière une seule
API : POST /api/v1/jobs/createTask lance une tâche, GET /api/v1/jobs/recordInfo
dit où elle en est, GET /api/v1/chat/credit donne le solde. Une tâche est
asynchrone (quelques secondes pour une image, plusieurs minutes pour une
vidéo) ; ses fichiers restent 14 jours chez eux, studio_ia.py les rapatrie.

Les images de référence doivent être des URL publiques : l'API de dépôt
(kieai.redpandaai.co) les héberge 24 h, le temps que la tâche les lise.

La clé reste ici, côté serveur : collée par un admin dans l'onglet (gardée
dans data/studio_ia/cle.json, lisible du seul service), sinon KIE_API_KEY
dans l'environnement, sinon le .env du VPS (relu toutes les 30 s pour
qu'ajouter la clé n'oblige pas à redémarrer). Elle ne sort jamais dans les
journaux ni dans une réponse HTTP : l'écran ne voit que ses 4 derniers
caractères.

Ce module ne connaît ni Flask ni le dashboard : studio_ia.py s'en sert.
Paramètres et prix relevés dans la doc et sur kie.ai le 03/11/2026 ; les
prix servent à l'ESTIMATION affichée avant le clic, Kie fait foi ensuite
(creditsConsumed sur la tâche finie).
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

import safe_json

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
#: la clé collée dans l'onglet ; les tests déplacent ce chemin hors de data/
FICHIER_CLE = BOT_DIR / "data" / "studio_ia" / "cle.json"


def _fiche_site() -> Dict[str, Any]:
    d = safe_json.load(FICHIER_CLE, default={}) or {}
    return d if isinstance(d, dict) else {}


def _cle_site() -> str:
    return str(_fiche_site().get("cle") or "").strip()


def cle() -> str:
    """La clé collée dans l'onglet d'abord : c'est celle que le propriétaire
    vient de poser, elle doit gagner sur un vieux KIE_API_KEY. Sinon
    l'environnement (main.py charge le .env au démarrage), sinon le .env relu
    toutes les 30 s. Sans ça, poser la clé sur le VPS obligeait à redémarrer
    le bot pour qu'elle serve."""
    k = _cle_site()
    if k:
        return k
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


def source_cle() -> Dict[str, Any]:
    """Pour l'écran : d'où vient la clé et ses 4 derniers caractères, jamais
    la clé entière."""
    f = _fiche_site()
    k = str(f.get("cle") or "").strip()
    if k:
        return {"source": "site", "fin": k[-4:], "le": f.get("le"), "par": f.get("par") or ""}
    k = cle()
    return {"source": "env" if k else "", "fin": k[-4:] if k else "", "le": None, "par": ""}


def enregistrer_cle(valeur: str, par: str, langue: str = "fr") -> Tuple[bool, str, Optional[float]]:
    """Garde la clé collée dans l'onglet, APRÈS l'avoir essayée sur le solde :
    une clé refusée par Kie n'écraserait pas une clé peut-être encore bonne,
    et un Kie injoignable ne fait rien garder (le propriétaire recolle dans
    une minute). Renvoie (ok, message, solde)."""
    t = _MESSAGES.get(langue) or _MESSAGES["fr"]
    v = (valeur or "").strip()
    if v.lower().startswith("bearer "):
        v = v[7:].strip()
    if len(v) < 16 or len(v) > 512 or any(c.isspace() for c in v):
        return False, t["cle_mal_copiee"], None
    try:
        d = _requete("GET", BASE + "/api/v1/chat/credit", cle_=v)
    except ErreurKie as e:
        if e.code == 401:
            return False, t["cle_refusee"], None
        return False, str(e), None
    try:
        solde: Optional[float] = float(d.get("data"))
    except (TypeError, ValueError):
        solde = None
    try:
        FICHIER_CLE.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    # pas de copie .prev : une seconde copie de la clé pour rien ; perdue,
    # elle se recolle en deux secondes
    if not safe_json.write(FICHIER_CLE, {"cle": v, "le": time.time(), "par": par or ""}, backup=False):
        return False, t["cle_non_ecrite"], None
    try:
        os.chmod(FICHIER_CLE, 0o600)
    except OSError:
        pass
    return True, t["cle_posee"].format(fin=v[-4:]), solde


# ------------------------------------------------------------ messages --

_MESSAGES = {
    "fr": {
        "sans_cle": "Clé Kie.ai absente : un admin la colle dans l'onglet Studio IA (bouton 🔑), ou KIE_API_KEY dans le .env.",
        "cle_mal_copiee": "Clé vide ou mal copiée : colle-la en entier, sans espace.",
        "cle_refusee": "Kie.ai refuse cette clé : vérifie-la sur kie.ai/api-key et recolle-la.",
        "cle_non_ecrite": "Écriture impossible dans data/ : clé non enregistrée.",
        "cle_posee": "Clé Kie.ai enregistrée (…{fin}).",
        "reseau": "Kie.ai injoignable ({detail}) : réessaie dans un instant.",
        401: "Clé Kie.ai refusée : recolle une clé valide dans Studio IA (bouton 🔑).",
        402: "Crédits Kie.ai insuffisants : recharge le compte sur kie.ai.",
        404: "Adresse Kie.ai inconnue (modèle retiré ?) : {detail}",
        422: "Paramètres refusés par Kie.ai : {detail}",
        429: "Kie.ai limite les demandes : réessaie dans une minute.",
        455: "Kie.ai est en maintenance : réessaie plus tard.",
        "autre": "Kie.ai a répondu {code} : {detail}",
    },
    "en": {
        "sans_cle": "Kie.ai key missing: an admin pastes it in the Studio IA tab (🔑 button), or KIE_API_KEY in the .env.",
        "cle_mal_copiee": "Empty or badly copied key: paste it whole, without spaces.",
        "cle_refusee": "Kie.ai rejects this key: check it on kie.ai/api-key and paste it again.",
        "cle_non_ecrite": "Cannot write in data/: key not saved.",
        "cle_posee": "Kie.ai key saved (…{fin}).",
        "reseau": "Kie.ai unreachable ({detail}): try again in a moment.",
        401: "Kie.ai key rejected: paste a valid key again in Studio IA (🔑 button).",
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
             files: Any = None, timeout: float = DELAI,
             cle_: Optional[str] = None) -> Dict[str, Any]:
    """Le seul point de sortie HTTP vers Kie : un seul endroit pour la clé,
    les délais et la lecture du `code` (Kie répond HTTP 200 même en échec,
    le vrai verdict est dans le corps). Les tests le remplacent.
    `cle_` : essayer une clé précise (celle qu'on est en train de coller)."""
    k = cle_ or cle()
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
#: vidéo de gestes des modèles « motion » (Kling : MP4 ou MOV, 100 Mo, 3–30 s)
TYPES_VIDEO = ("video/mp4", "video/quicktime")
TAILLE_MAX_VIDEO = 100_000_000
_REFS_MOTION = {
    "max": 2, "modes": ["motion"], "types": ("image/jpeg", "image/png") + TYPES_VIDEO, "duree": (3, 30),
    "aide": "1 photo de la model (JPG/PNG, 10 Mo, buste visible) + 1 vidéo des gestes (MP4/MOV, 3–30 s, 100 Mo). "
            "Le visage, la tenue et le décor viennent de la photo ; les mouvements de la vidéo. Le texte incrusté dans la vidéo n'est pas repris.",
    "aide_en": "1 photo of the model (JPG/PNG, 10 MB, head and torso visible) + 1 video of the moves (MP4/MOV, 3–30 s, 100 MB). "
               "Face, outfit and background come from the photo; the moves from the video. Text burned into the video is not kept.",
}
_OPTIONS_MOTION = [
    {"cle": "mode", "nom": "Résolution", "nom_en": "Resolution", "type": "choix",
     "valeurs": ["720p", "1080p"], "defaut": "720p"},
    {"cle": "character_orientation", "nom": "Orientation du personnage", "nom_en": "Character orientation", "type": "choix",
     "valeurs": ["video", "image"], "defaut": "video",
     "libelles": {"video": {"fr": "Comme la vidéo (recommandé)", "en": "Like the video (recommended)"},
                  "image": {"fr": "Comme la photo (10 s max)", "en": "Like the photo (10 s max)"}},
     "aide": "« Comme la vidéo » : le personnage se tourne comme dans la vidéo, jusqu'à 30 s. « Comme la photo » : il garde l'orientation de la photo, vidéo de 10 s au plus.",
     "aide_en": "“Like the video”: the character turns as in the video, up to 30 s. “Like the photo”: it keeps the photo's orientation, video of 10 s at most."},
]

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
        "references": {"max": 9, "modes": ["cadres", "references"], "types": TYPES_IMAGE + TYPES_VIDEO,
                       "videos_max": 3, "duree": (2, 30),
                       "aide": "Jusqu'à 9 images (JPG/PNG/WebP, 300–6000 px) et des vidéos de référence (MP4/MOV, 2–30 s, 720p max) : "
                               "le prompt dit quoi prendre de chaque (« la femme de l'image 1, la tenue, le décor et les gestes de la vidéo »). "
                               "Avec une vidéo, la sortie reste en 480p/720p et la vidéo est facturée en plus. En cadres : 1 = première image, 2 = première et dernière.",
                       "aide_en": "Up to 9 images (JPG/PNG/WebP, 300–6000 px) and reference videos (MP4/MOV, 2–30 s, 720p max): "
                                  "the prompt says what to take from each (“the woman from image 1, the outfit, room and moves of the video”). "
                                  "With a video the output stays 480p/720p and the video is billed on top. As frames: 1 = first, 2 = first and last."},
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
        "references": {"max": 9, "modes": ["cadres", "references"], "types": TYPES_IMAGE + TYPES_VIDEO,
                       "videos_max": 3, "duree": (2, 15),
                       "aide": "Jusqu'à 9 images (JPG/PNG/WebP, 300–6000 px) et des vidéos de référence (MP4/MOV, 2–15 s, 720p max) : "
                               "le prompt dit quoi prendre de chaque (« la femme de l'image 1, la tenue, le décor et les gestes de la vidéo »). "
                               "La vidéo est facturée en plus. En cadres : 1 = première image, 2 = première et dernière.",
                       "aide_en": "Up to 9 images (JPG/PNG/WebP, 300–6000 px) and reference videos (MP4/MOV, 2–15 s, 720p max): "
                                  "the prompt says what to take from each (“the woman from image 1, the outfit, room and moves of the video”). "
                                  "The video is billed on top. As frames: 1 = first, 2 = first and last."},
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
    # Motion control : la personne de la photo refait les gestes de la vidéo
    # (docs.kie.ai/market/kling/motion-control-v3 et /motion-control). Pas de
    # prompt obligatoire ; la durée de sortie = celle de la vidéo, facturée
    # à la seconde.
    {
        "cle": "kling3motion", "nom": "Kling 3.0 Motion Control", "editeur": "Kuaishou", "type": "motion",
        "resume": "720p / 1080p · la model de la photo refait les gestes de la vidéo (3–30 s)",
        "resume_en": "720p / 1080p · the model in the photo redoes the moves of the video (3–30 s)",
        "modele_api": "kling-3.0/motion-control", "prompt_max": 2500, "prompt_min": 0,
        "references": _REFS_MOTION, "options": _OPTIONS_MOTION,
    },
    {
        "cle": "kling26motion", "nom": "Kling 2.6 Motion Control", "editeur": "Kuaishou", "type": "motion",
        "resume": "720p / 1080p · même principe, génération précédente, presque moitié prix",
        "resume_en": "720p / 1080p · same idea, previous generation, nearly half price",
        "modele_api": "kling-2.6/motion-control", "prompt_max": 2500, "prompt_min": 0,
        "references": _REFS_MOTION, "options": _OPTIONS_MOTION,
    },
    # Wan 2.2 Animate (docs.kie.ai/market/wan/2-2-animate-move et -replace) :
    # pas de prompt, pas de borne de durée documentée, et surtout
    # nsfw_checker=false — Kling refuse une vidéo « sensible » (lingerie
    # entrevue, 03/11/2026), Wan non.
    {
        "cle": "wan22move", "nom": "Wan 2.2 Animate", "editeur": "Alibaba", "type": "motion",
        "badge": "sans filtre", "badge_en": "no filter",
        "resume": "720p · la model de la photo refait les gestes, décor de la photo · passe où Kling refuse",
        "resume_en": "720p · the model in the photo redoes the moves, photo background · passes where Kling refuses",
        "modele_api": "wan/2-2-animate-move", "prompt_max": 2500, "prompt_min": 0, "sans_prompt": True,
        "references": {
            "max": 2, "modes": ["motion"], "types": TYPES_IMAGE + TYPES_VIDEO, "duree": (1, 60),
            "aide": "1 photo de la model (JPG/PNG/WebP, 5 Mo) + 1 vidéo des gestes (MP4/MOV, 100 Mo). Visage, tenue et décor viennent de la photo ; pas de filtre de contenu.",
            "aide_en": "1 photo of the model (JPG/PNG/WebP, 5 MB) + 1 video of the moves (MP4/MOV, 100 MB). Face, outfit and background come from the photo; no content filter.",
        },
        "options": [
            {"cle": "resolution", "nom": "Résolution", "nom_en": "Resolution", "type": "choix",
             "valeurs": ["720p"], "defaut": "720p"},
        ],
    },
    {
        "cle": "wan22replace", "nom": "Wan 2.2 Animate Replace", "editeur": "Alibaba", "type": "motion",
        "badge": "le moins cher", "badge_en": "cheapest",
        "resume": "480p / 580p / 720p · garde le décor (et le texte) de la vidéo, remplace la personne",
        "resume_en": "480p / 580p / 720p · keeps the video's scene (and text), replaces the person",
        "modele_api": "wan/2-2-animate-replace", "prompt_max": 2500, "prompt_min": 0, "sans_prompt": True,
        "references": {
            "max": 2, "modes": ["motion"], "types": TYPES_IMAGE + TYPES_VIDEO, "duree": (1, 60),
            "aide": "1 photo de la model (JPG/PNG/WebP, 10 Mo) + 1 vidéo (MP4/MOV, 10 Mo). La personne de la vidéo est remplacée par celle de la photo ; le décor, la lumière et le texte incrusté restent ceux de la vidéo.",
            "aide_en": "1 photo of the model (JPG/PNG/WebP, 10 MB) + 1 video (MP4/MOV, 10 MB). The person in the video is replaced by the one in the photo; background, lighting and burned-in text stay those of the video.",
        },
        "options": [
            {"cle": "resolution", "nom": "Résolution", "nom_en": "Resolution", "type": "choix",
             "valeurs": ["480p", "580p", "720p"], "defaut": "720p"},
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
    "kling3motion": {"720p": 20, "1080p": 27},     # par seconde de vidéo de gestes
    "kling26motion": {"720p": 11, "1080p": 18},
    "wan22move": {"720p": 12.5},
    "wan22replace": {"480p": 6, "580p": 9.5, "720p": 12.5},
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


def estimer(cle_: str, options: Any, nb_refs: int = 0, duree_video: float = 0.0) -> float:
    """Crédits attendus pour cette génération (0 si le modèle est inconnu).
    `duree_video` : les modèles motion sortent une vidéo aussi longue que
    celle des gestes ; Kie facture à la seconde, on arrondit au-dessus."""
    m = modele(cle_)
    if not m:
        return 0.0
    o = normaliser(cle_, options)
    p = PRIX.get(cle_) or {}
    if m["type"] == "motion":
        try:
            secondes = math.ceil(float(duree_video or 0))
        except (TypeError, ValueError):
            secondes = 0
        qualite = o.get("mode") or o.get("resolution")
        return round(float(p.get(qualite, 0)) * max(0, secondes), 2)
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
    mini = int(m.get("prompt_min", 1))     # 0 = prompt facultatif (motion)
    if len(p) < mini:
        if langue == "en":
            return f"Write a prompt first ({mini} characters minimum)."
        return f"Écris d'abord un prompt ({mini} caractères minimum)."
    if len(p) > int(m["prompt_max"]):
        if langue == "en":
            return f"Prompt too long: {len(p)} characters, {m['prompt_max']} maximum for {m['nom']}."
        return f"Prompt trop long : {len(p)} caractères, {m['prompt_max']} maximum pour {m['nom']}."
    return ""


def entree_api(cle_: str, prompt: str, options: Any, refs: List[str],
               videos: Optional[List[str]] = None) -> Tuple[str, Dict[str, Any]]:
    """(modèle Kie, input de createTask) pour cette demande. `refs` : les URL
    publiques des images, dans l'ordre déposé ; `videos` : celles des vidéos
    (modèles motion seulement). Les bornes de nombre et de types viennent du
    registre ; ce qui n'y est pas n'est pas envoyé."""
    m = modele(cle_)
    if not m:
        raise ErreurKie("Modèle inconnu.", "modele")
    o = normaliser(cle_, options)
    p = (prompt or "").strip()
    refs = [r for r in (refs or []) if isinstance(r, str) and r.startswith("http")]
    refs = refs[:int(m["references"]["max"])]
    if m["type"] == "motion":
        videos = [v for v in (videos or []) if isinstance(v, str) and v.startswith("http")]
        if not refs or not videos:
            raise ErreurKie("Il faut une photo et une vidéo.", "refs")
        if cle_.startswith("wan"):
            # nsfw_checker=false : pas de filtre en plus de celui du modèle
            return m["modele_api"], {"video_url": videos[0], "image_url": refs[0],
                                     "resolution": o["resolution"], "nsfw_checker": False}
        e_m: Dict[str, Any] = {"input_urls": refs[:1], "video_urls": videos[:1], "mode": o["mode"],
                               "character_orientation": o["character_orientation"]}
        if p:
            e_m["prompt"] = p
        return m["modele_api"], e_m
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
             "duration": int(o["duration"]), "generate_audio": bool(o["generate_audio"]),
             "nsfw_checker": False}
        videos = [v for v in (videos or []) if isinstance(v, str) and v.startswith("http")]
        videos = videos[:int(m["references"].get("videos_max") or 0)]
        if videos:
            # une vidéo de référence exclut les cadres : tout passe en références,
            # et la sortie ne dépasse pas 720p (la doc borne la vidéo à 480p/720p)
            if refs:
                e["reference_image_urls"] = refs
            e["reference_video_urls"] = videos
            if e["resolution"] == "1080p":
                e["resolution"] = "720p"
        else:
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
        prix_s = 0.0
        if m["type"] == "motion":
            # le prix de base est par seconde de vidéo : l'écran l'affiche « /s »
            defaut_mode = next((o["defaut"] for o in m["options"] if o["cle"] in ("mode", "resolution")), "720p")
            prix_s = float((PRIX.get(m["cle"]) or {}).get(defaut_mode, 0))
        out.append({
            "cle": m["cle"], "nom": m["nom"], "editeur": m["editeur"], "type": m["type"],
            "prix_seconde": prix_s, "sans_prompt": bool(m.get("sans_prompt")),
            "duree": list(r.get("duree") or []),
            "badge": (m.get("badge_en") if en else m.get("badge")) or "",
            "resume": m.get("resume_en") if en and m.get("resume_en") else m.get("resume", ""),
            "prompt_max": m["prompt_max"], "prompt_min": int(m.get("prompt_min") or 1),
            "references": {"max": r["max"], "modes": list(r["modes"]), "types": list(r["types"]),
                           "videos_max": int(r.get("videos_max") or 0),
                           "aide": r.get("aide_en") if en and r.get("aide_en") else r.get("aide", "")},
            "options": opts,
            "estimation_defaut": estimer(m["cle"], {}, 0),
        })
    return out
