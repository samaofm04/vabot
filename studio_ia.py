"""studio_ia.py — l'onglet « Studio IA » du tableau de bord : vidéos et
photos générées par IA via Kie.ai (Kling, Seedance, Wan, Seedream).

Même motif que veille_tiktok_ui.py et parc_web.py : le rendu, les routes et
le suivi des tâches vivent ici ; web_upload.py ne fait que brancher
(bouton de menu, rendu paresseux, permission, register). Le module ne
l'importe jamais : ses dépendances arrivent par `register(app, deps)`.

Le JavaScript de l'écran est un fichier à part (studio_ia_app.js, servi par
/studio-ia/app.js) : `node --check` le vérifie tel qu'il est servi, au lieu
de vivre dans une chaîne Python où une apostrophe tue le script en silence.

Une génération est une tâche Kie asynchrone. Elle est écrite dans
data/studio_ia/taches.json (safe_json), un fil d'arrière-plan interroge Kie
tant qu'il en reste d'ouvertes, et chaque résultat est rapatrié dans
data/studio_ia/sorties/ (Kie ne garde les fichiers que 14 jours). Le site
n'efface jamais un média : « retirer de l'historique » masque la tâche, le
fichier reste.

Le genre « Visage » ne passe pas par Kie : FaceFusion (libre, gratuit) tourne
sur une machine à nous — le Mac du propriétaire aujourd'hui, le VPS quand il
aura la place (2 Go de modèles) — qui vient chercher le travail ici avec
visage_worker.py et un jeton (data/studio_ia/machine.json). Le site ne
calcule rien : il garde la file, la progression et le résultat.
"""
from __future__ import annotations

import hmac
import html
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import kie_ai
import safe_json

BOT_DIR = Path(__file__).resolve().parent
#: Surchargeable (les tests y mettent un dossier jetable : rien n'écrit
#: dans le vrai data/ pendant une suite).
DOSSIER = BOT_DIR / "data" / "studio_ia"

#: Générations ouvertes au plus par personne : un clic qui part en boucle ne
#: doit pas vider le compte.
MAX_OUVERTES = 5
#: Une tâche encore ouverte après ce délai est déclarée perdue (Kie dit que
#: certaines vidéos dépassent 10 min ; 2 h est large).
DELAI_MAX_S = 2 * 3600
#: Tentatives de rapatriement avant de se contenter de l'URL Kie (14 jours).
ESSAIS_DL = 5
ETATS_OUVERTS = ("en_attente", "en_cours")
#: Visage : une machine qui ne donne plus signe pendant 10 min a planté (ou
#: dort) : le travail est remis en file, deux fois, puis déclaré perdu.
SILENCE_MAX_VISAGE_S = 10 * 60
#: Visage : sans machine en ligne, un travail attend jusqu'à 24 h (le Mac
#: peut être éteint le soir), pas 2 h comme une tâche Kie.
ATTENTE_MAX_VISAGE_S = 24 * 3600
DUREE_MAX_VISAGE_S = 180
#: Une machine vue il y a moins de 90 s est « en ligne » (elle passe toutes
#: les 10 s).
MACHINE_EN_LIGNE_S = 90
TAILLE_MAX_RESULTAT = 400_000_000
_MACHINES: Dict[str, Dict[str, Any]] = {}
_ID_OK = re.compile(r"^[a-f0-9]{12,32}$")
_VERROU = threading.RLock()
_SUIVI: Dict[str, Any] = {"fil": None}
_CREDITS: Dict[str, Any] = {"valeur": None, "t": 0.0, "erreur": ""}

_EXT_PAR_MIME = {"video/mp4": ".mp4", "video/quicktime": ".mov", "image/png": ".png",
                 "image/jpeg": ".jpg", "image/webp": ".webp"}
_MIME_PAR_EXT = {v: k for k, v in _EXT_PAR_MIME.items()}
_MIME_PAR_EXT[".jpeg"] = "image/jpeg"


# -------------------------------------------------------------- textes --

T = {
    "fr": {
        "titre": "Studio IA",
        "sous": "Vidéos et photos générées par IA via Kie.ai — Kling, Seedance, Wan, Seedream.",
        "creer": "Créer", "historique": "Historique",
        "reels": "Reels · vidéo", "photo": "Photo",
        "modele": "Modèle", "references": "Références", "optionnel": "optionnel",
        "deposer": "Clique, dépose ou colle une image", "deposer_aide": "JPG, PNG ou WebP",
        "reglages": "Réglages", "estime": "Estimé", "credits": "crédits",
        "generer": "Générer", "generation": "Génération…",
        "raccourci": "⌘ / Ctrl + Entrée pour générer",
        "prompt": "Prompt",
        "prompt_ph_video": "Décris le clip comme un plan déjà tourné : qui est là, où, comment c'est filmé, puis ce qui se passe.",
        "prompt_ph_image": "Décris la photo : sujet, tenue, décor, lumière, cadrage.",
        "recents": "Résultats", "vide_recents": "Rien pour l'instant : écris un prompt et clique Générer.",
        "vide_hist": "Aucune génération pour l'instant.",
        "etat_en_attente": "En file d'attente", "etat_en_cours": "Génération…",
        "etat_fini": "Terminé", "etat_echec": "Échec", "rapatriement": "Rapatriement du fichier…",
        "telecharger": "Télécharger", "apercu": "Aperçu", "reutiliser": "Réutiliser le prompt",
        "masquer": "Retirer de l'historique",
        "masquer_confirm": "Retirer cette génération de l'historique ? Le fichier reste sur le serveur.",
        "credits_insuffisants": "Crédits insuffisants : il en reste {reste}, cette génération en demande environ {besoin}. Recharge sur kie.ai.",
        "credits_inconnus": "solde inconnu", "solde": "{n} crédits",
        "refs_max": "{n} image(s) maximum pour ce modèle.",
        "ref_type": "Format refusé : JPG, PNG ou WebP (MP4/MOV pour la vidéo des gestes).",
        "motion": "Motion · gestes",
        "deposer_motion": "Clique, dépose ou colle la photo de la model et la vidéo des gestes",
        "deposer_aide_motion": "JPG/PNG + MP4/MOV de 3 à 30 s",
        "prompt_ph_motion": "Optionnel : précise ce qui doit rester (tenue, décor, cadrage) ou l'ambiance.",
        "video_type": "Vidéo refusée : MP4 ou MOV seulement.",
        "video_trop_grosse": "Vidéo trop lourde ({mo} Mo) : 100 Mo maximum.",
        "video_duree": "La vidéo des gestes doit durer entre {min} et {max} s (celle-ci : {s} s).",
        "sans_prompt": "Ce modèle n'a pas de prompt : la photo et la vidéo suffisent.",
        "video_10s": "Orientation « comme la photo » : vidéo de 10 s au plus (celle-ci : {s} s). Passe en « comme la vidéo » ou coupe-la.",
        "motion_refs": "Il faut une photo de la model et une vidéo des gestes.",
        "webp_converti": "Image WebP convertie en PNG (Kling n'accepte que JPG et PNG).",
        "par_seconde": "/s",
        "ref_type_kling": "Kling n'accepte que le JPG et le PNG.",
        "ref_trop_grosse": "Image trop lourde ({mo} Mo) : 30 Mo maximum.",
        "envoi_ref": "Envoi de l'image…",
        "lance": "Génération lancée (≈ {n} crédits).",
        "erreur_reseau": "Le site n'a pas répondu.",
        "trop_en_cours": "Attends la fin des générations en cours ({n} au plus à la fois).",
        "actualiser": "Actualiser", "il_y_a": "il y a {d}", "par": "par",
        "cle_absente": "Clé Kie.ai absente : demande à un admin de la coller dans Studio IA (bouton 🔑).",
        "cle_titre": "Clé Kie.ai",
        "cle_aide": "Colle ici la clé créée sur",
        "cle_aide2": "Elle reste sur le serveur : personne ne la revoit, pas même toi. Il faut aussi des crédits sur le compte Kie.",
        "cle_ph": "Colle la clé ici",
        "cle_enregistrer": "Enregistrer la clé",
        "cle_annuler": "Annuler",
        "cle_en_place": "Clé en place (…{fin})",
        "cle_manquante_admin": "Aucune clé : colle-la pour ouvrir le Studio.",
        "cle_ok": "Clé enregistrée (…{fin}). Solde : {n} crédits.",
        "cle_bouton": "Changer la clé Kie.ai",
        "doc": "Clé et crédits sur kie.ai",
        "fermer": "Fermer", "secondes": "s", "ouvrir_kie": "Ouvrir chez Kie",
        "usage_refs_sans": "Aucune image : le modèle part du prompt seul.",
        "trad_options": "Les réglages suivent le modèle choisi.",
        "visage": "Visage · même vidéo",
        "deposer_visage": "Clique ou dépose la photo du visage et la vidéo à modifier",
        "deposer_aide_visage": "JPG/PNG/WebP + MP4/MOV (100 Mo, 3 min au plus)",
        "visage_refs": "Il faut une photo du visage et une vidéo.",
        "gratuit": "gratuit",
        "visage_lance": "Remplacement de visage mis en file (gratuit).",
        "visage_machine_ok": "Machine en ligne : {nom} (vue il y a {d}).",
        "visage_machine_occupee": "{nom} travaille (vue il y a {d}).",
        "visage_sans_machine": "Aucune machine en ligne pour le visage : le travail attendra qu'elle se connecte (le Mac, allumé et déverrouillé).",
        "visage_sans_machine_admin": "Sur le Mac, une seule fois (puis elle se reconnecte seule) :",
        "visage_etape_modeles": "téléchargement des modèles",
        "visage_etape_analysing": "analyse de la vidéo",
        "visage_etape_extracting": "extraction des images",
        "visage_etape_processing": "remplacement du visage",
        "visage_etape_merging": "assemblage",
        "visage_etape_envoi": "envoi du résultat",
        "visage_etape_attente": "en attente d'une machine",
        "visage_copier": "📋 Copier la commande",
        "visage_copiee": "Commande copiée : colle-la dans le Terminal et appuie sur Entrée.",
    },
    "en": {
        "titre": "Studio IA",
        "sous": "AI-generated videos and photos via Kie.ai — Kling, Seedance, Wan, Seedream.",
        "creer": "Create", "historique": "History",
        "reels": "Reels · video", "photo": "Photo",
        "modele": "Model", "references": "References", "optionnel": "optional",
        "deposer": "Click, drop or paste an image", "deposer_aide": "JPG, PNG or WebP",
        "reglages": "Settings", "estime": "Estimated", "credits": "credits",
        "generer": "Generate", "generation": "Generating…",
        "raccourci": "⌘ / Ctrl + Enter to generate",
        "prompt": "Prompt",
        "prompt_ph_video": "Describe the clip like footage already shot: who is in it, where, how it is filmed, then what happens.",
        "prompt_ph_image": "Describe the photo: subject, outfit, setting, light, framing.",
        "recents": "Results", "vide_recents": "Nothing yet: write a prompt and click Generate.",
        "vide_hist": "No generation yet.",
        "etat_en_attente": "Queued", "etat_en_cours": "Generating…",
        "etat_fini": "Done", "etat_echec": "Failed", "rapatriement": "Fetching the file…",
        "telecharger": "Download", "apercu": "Preview", "reutiliser": "Reuse prompt",
        "masquer": "Remove from history",
        "masquer_confirm": "Remove this generation from history? The file stays on the server.",
        "credits_insuffisants": "Not enough credits: {reste} left, this generation needs about {besoin}. Top up on kie.ai.",
        "credits_inconnus": "balance unknown", "solde": "{n} credits",
        "refs_max": "At most {n} image(s) for this model.",
        "ref_type": "Rejected format: JPG, PNG or WebP (MP4/MOV for the moves video).",
        "motion": "Motion · moves",
        "deposer_motion": "Click, drop or paste the model's photo and the moves video",
        "deposer_aide_motion": "JPG/PNG + MP4/MOV, 3 to 30 s",
        "prompt_ph_motion": "Optional: say what must stay (outfit, background, framing) or the mood.",
        "video_type": "Video rejected: MP4 or MOV only.",
        "video_trop_grosse": "Video too large ({mo} MB): 100 MB maximum.",
        "video_duree": "The moves video must last {min} to {max} s (this one: {s} s).",
        "sans_prompt": "This model takes no prompt: the photo and the video are enough.",
        "video_10s": "“Like the photo” orientation: video of 10 s at most (this one: {s} s). Switch to “like the video” or trim it.",
        "motion_refs": "A photo of the model and a moves video are both needed.",
        "webp_converti": "WebP image converted to PNG (Kling only takes JPG and PNG).",
        "par_seconde": "/s",
        "ref_type_kling": "Kling only accepts JPG and PNG.",
        "ref_trop_grosse": "Image too large ({mo} MB): 30 MB maximum.",
        "envoi_ref": "Uploading image…",
        "lance": "Generation started (≈ {n} credits).",
        "erreur_reseau": "The site did not answer.",
        "trop_en_cours": "Wait for the running generations to finish ({n} at a time at most).",
        "actualiser": "Refresh", "il_y_a": "{d} ago", "par": "by",
        "cle_absente": "Kie.ai key missing: ask an admin to paste it in Studio IA (🔑 button).",
        "cle_titre": "Kie.ai key",
        "cle_aide": "Paste here the key created on",
        "cle_aide2": "It stays on the server: nobody sees it again, not even you. The Kie account also needs credits.",
        "cle_ph": "Paste the key here",
        "cle_enregistrer": "Save the key",
        "cle_annuler": "Cancel",
        "cle_en_place": "Key in place (…{fin})",
        "cle_manquante_admin": "No key: paste it to open the Studio.",
        "cle_ok": "Key saved (…{fin}). Balance: {n} credits.",
        "cle_bouton": "Change the Kie.ai key",
        "doc": "Key and credits on kie.ai",
        "fermer": "Close", "secondes": "s", "ouvrir_kie": "Open on Kie",
        "usage_refs_sans": "No image: the model starts from the prompt alone.",
        "trad_options": "Settings follow the chosen model.",
        "visage": "Face · same video",
        "deposer_visage": "Click or drop the face photo and the video to change",
        "deposer_aide_visage": "JPG/PNG/WebP + MP4/MOV (100 MB, 3 min at most)",
        "visage_refs": "A face photo and a video are both needed.",
        "gratuit": "free",
        "visage_lance": "Face swap queued (free).",
        "visage_machine_ok": "Machine online: {nom} (seen {d}).",
        "visage_machine_occupee": "{nom} is working (seen {d}).",
        "visage_sans_machine": "No machine online for faces: the job will wait until it connects (the Mac, on and unlocked).",
        "visage_sans_machine_admin": "On the Mac, once (it reconnects by itself afterwards):",
        "visage_etape_modeles": "downloading the models",
        "visage_etape_analysing": "analysing the video",
        "visage_etape_extracting": "extracting frames",
        "visage_etape_processing": "swapping the face",
        "visage_etape_merging": "merging",
        "visage_etape_envoi": "uploading the result",
        "visage_etape_attente": "waiting for a machine",
        "visage_copier": "📋 Copy the command",
        "visage_copiee": "Command copied: paste it in the Terminal and press Enter.",
    },
}

#: Le « modèle » Visage tel que l'écran le lit, à côté du registre Kie
#: (même forme que kie_ai.registre_public : l'écran ne fait pas la
#: différence, sauf pour le prix : gratuit).
MODELE_VISAGE = {
    "cle": "visage", "nom": "FaceFusion", "editeur": "sur notre machine", "editeur_en": "on our machine",
    "type": "visage", "badge": "gratuit", "badge_en": "free",
    "resume": "la vidéo reste identique (tenue, gestes, son, texte), seule la tête devient celle de la photo",
    "resume_en": "the video stays identical (outfit, moves, sound, text), only the head becomes the photo's",
    "prompt_max": 0, "prompt_min": 0, "sans_prompt": True,
    "references": {
        "max": 2, "modes": ["visage"], "videos_max": 1, "duree": [1, DUREE_MAX_VISAGE_S],
        "aide": "1 photo du visage (de face, nette, bien éclairée) + 1 vidéo MP4/MOV de 3 min au plus. Les cheveux, le corps, le son et le texte restent ceux de la vidéo. Gratuit : le calcul se fait sur notre machine, compte ~30 s par seconde de vidéo.",
        "aide_en": "1 face photo (front-facing, sharp, well lit) + 1 MP4/MOV video of 3 min at most. Hair, body, sound and text stay those of the video. Free: computed on our machine, count ~30 s per second of video.",
    },
    "options": [
        {"cle": "finition", "nom": "Finition", "nom_en": "Finish", "type": "choix",
         "valeurs": ["nette", "rapide"], "defaut": "nette",
         "libelles": {"nette": {"fr": "Nette (visage lissé)", "en": "Sharp (face enhanced)"},
                      "rapide": {"fr": "Rapide (sans lissage)", "en": "Fast (no enhancing)"}},
         "aide": "Nette : GFPGAN affine le visage posé (2× plus long). Rapide : le visage seul, pour un essai.",
         "aide_en": "Sharp: GFPGAN refines the swapped face (2× slower). Fast: the swap alone, for a quick try."},
    ],
}


def registre_visage(langue: str = "fr") -> Dict[str, Any]:
    en = langue == "en"
    m = MODELE_VISAGE
    r = m["references"]
    opts = []
    for o in m["options"]:
        opts.append({"cle": o["cle"], "nom": o["nom_en"] if en else o["nom"], "type": o["type"], "defaut": o["defaut"],
                     "valeurs": list(o["valeurs"]),
                     "libelles": {k: (v["en"] if en else v["fr"]) for k, v in o["libelles"].items()},
                     "aide": o["aide_en"] if en else o["aide"]})
    return {
        "cle": m["cle"], "nom": m["nom"], "editeur": m["editeur_en"] if en else m["editeur"], "type": m["type"],
        "prix_seconde": 0, "sans_prompt": True, "duree": list(r["duree"]),
        "badge": m["badge_en"] if en else m["badge"], "resume": m["resume_en"] if en else m["resume"],
        "prompt_max": 0, "prompt_min": 0,
        "references": {"max": r["max"], "modes": list(r["modes"]), "types": list(kie_ai.TYPES_IMAGE + kie_ai.TYPES_VIDEO),
                       "videos_max": r["videos_max"], "aide": r["aide_en"] if en else r["aide"]},
        "options": opts, "estimation_defaut": 0,
    }


def _t(langue: str) -> Dict[str, str]:
    return T["en"] if langue == "en" else T["fr"]


# ------------------------------------------------------------ stockage --

def _fichier_taches() -> Path:
    return DOSSIER / "taches.json"


def _dossier_sorties() -> Path:
    return DOSSIER / "sorties"


def _dossier_refs() -> Path:
    return DOSSIER / "references"


def _charger() -> List[Dict[str, Any]]:
    d = safe_json.load(_fichier_taches(), default=[])
    return [t for t in d if isinstance(t, dict)] if isinstance(d, list) else []


def _ecrire(taches: List[Dict[str, Any]]) -> None:
    DOSSIER.mkdir(parents=True, exist_ok=True)
    # Les plus anciennes sortent du fichier (pas du disque) au-delà de 400 :
    # le fichier reste petit, les sorties restent.
    if len(taches) > 400:
        ouvertes = [t for t in taches if t.get("etat") in ETATS_OUVERTS]
        fermees = [t for t in taches if t.get("etat") not in ETATS_OUVERTS]
        fermees.sort(key=lambda t: t.get("cree_le", 0))
        taches = fermees[-(400 - len(ouvertes)):] + ouvertes
    safe_json.write(_fichier_taches(), taches)


def _maj(tid: str, **champs: Any) -> Optional[Dict[str, Any]]:
    """Modifie une tâche sous verrou (le fil de suivi et les routes écrivent
    le même fichier)."""
    with _VERROU:
        taches = _charger()
        for t in taches:
            if t.get("id") == tid:
                t.update(champs)
                t["maj_le"] = int(time.time())
                _ecrire(taches)
                return t
    return None


def _ouvertes() -> List[Dict[str, Any]]:
    return [t for t in _charger() if t.get("etat") in ETATS_OUVERTS]


# ------------------------------------------------------------- crédits --

def solde(force: bool = False) -> Dict[str, Any]:
    """{credits: float|None, erreur: str}. Mis en cache 60 s : chaque
    changement de réglage de l'écran n'a pas à interroger Kie."""
    if not kie_ai.cle_presente():
        return {"credits": None, "erreur": "sans_cle"}
    if not force and _CREDITS["valeur"] is not None and time.time() - _CREDITS["t"] < 60:
        return {"credits": _CREDITS["valeur"], "erreur": ""}
    try:
        _CREDITS["valeur"] = kie_ai.credits()
        _CREDITS["erreur"] = ""
    except kie_ai.ErreurKie as e:
        _CREDITS["erreur"] = str(e.code or "")
        print(f"[studio-ia] solde Kie illisible : {e}", flush=True)
    _CREDITS["t"] = time.time()
    return {"credits": _CREDITS["valeur"], "erreur": _CREDITS["erreur"]}


def _oublier_solde() -> None:
    _CREDITS["t"] = 0.0


# ---------------------------------------------------------- références --

def _webp_en_png(octets: bytes) -> Optional[bytes]:
    """Kling refuse le WebP ; converti ici une fois pour toutes, le fichier
    reste bon pour tous les modèles. None si ffmpeg ne peut pas."""
    with tempfile.TemporaryDirectory(prefix="sia_webp_") as d:
        src, dst = Path(d) / "in.webp", Path(d) / "out.png"
        src.write_bytes(octets)
        try:
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1", str(dst)],
                               capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0 or not dst.exists():
            return None
        return dst.read_bytes()


def _duree_media(chemin: Path) -> float:
    """Durée en secondes lue par ffprobe (0 si illisible : la vidéo est
    alors refusée, pas devinée)."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(chemin)], capture_output=True, text=True, timeout=60)
        return max(0.0, float((r.stdout or "0").strip() or 0))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def deposer_reference(utilisateur: str, octets: bytes, nom: str, mime: str,
                      langue: str = "fr") -> Dict[str, Any]:
    """Garde le fichier en local (aperçu de l'historique) et chez Kie (24 h,
    le temps que la tâche le lise). Image de référence, ou vidéo des gestes
    pour les modèles motion (sa durée est mesurée ici : elle fait le prix).
    Lève ValueError avec le message à montrer si le fichier ne convient pas."""
    t = _t(langue)
    mime = (mime or "").split(";")[0].strip().lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    nom_bas = (nom or "").lower()
    if mime in ("", "application/octet-stream"):
        # certains navigateurs n'étiquettent pas les .mov
        if nom_bas.endswith((".mov", ".qt")):
            mime = "video/quicktime"
        elif nom_bas.endswith(".mp4"):
            mime = "video/mp4"
    video = mime in kie_ai.TYPES_VIDEO
    if not video and mime not in kie_ai.TYPES_IMAGE:
        raise ValueError(t["ref_type"])
    if not octets:
        raise ValueError(t["ref_type"])
    if video and len(octets) > kie_ai.TAILLE_MAX_VIDEO:
        raise ValueError(t["video_trop_grosse"].format(mo=round(len(octets) / 1e6, 1)))
    if not video and len(octets) > kie_ai.TAILLE_MAX_REF:
        raise ValueError(t["ref_trop_grosse"].format(mo=round(len(octets) / 1e6, 1)))
    converti = False
    if mime == "image/webp":
        png = _webp_en_png(octets)
        if png:
            octets, mime, converti = png, "image/png", True
    rid = uuid.uuid4().hex[:16]
    ext = _EXT_PAR_MIME.get(mime, ".bin")
    _dossier_refs().mkdir(parents=True, exist_ok=True)
    local = _dossier_refs() / (rid + ext)
    local.write_bytes(octets)
    duree = _duree_media(local) if video else 0.0
    if video and duree <= 0:
        try:
            local.unlink()
        except OSError:
            pass
        raise ValueError(t["video_type"])
    nom_envoi = (nom or ("video" if video else "image"))
    if not nom_envoi.lower().endswith(ext):
        nom_envoi += ext
    url = kie_ai.televerser(octets, nom_envoi, mime)
    meta = {"id": rid, "nom": (nom or ("video" if video else "image"))[:120], "mime": mime, "taille": len(octets),
            "type": "video" if video else "image", "duree": round(duree, 2), "converti": converti,
            "url": url, "utilisateur": utilisateur, "t": int(time.time())}
    safe_json.write(_dossier_refs() / (rid + ".json"), meta, backup=False)
    return {"id": rid, "nom": meta["nom"], "mime": mime, "taille": len(octets), "type": meta["type"],
            "duree": meta["duree"], "converti": converti, "url": url, "apercu": "/studio-ia/reference/" + rid}


def _reference(rid: str) -> Optional[Dict[str, Any]]:
    if not _ID_OK.match(str(rid or "")):
        return None
    meta = safe_json.load(_dossier_refs() / (rid + ".json"), default=None)
    if not isinstance(meta, dict):
        return None
    for ext in _EXT_PAR_MIME.values():
        p = _dossier_refs() / (rid + ext)
        if p.exists():
            meta["chemin"] = p
            return meta
    return None


# --------------------------------------------------------- générations --

def _resume_options(m: Dict[str, Any], o: Dict[str, Any], duree_video: float = 0.0) -> str:
    morceaux = []
    for k in ("mode", "resolution", "quality", "size"):
        if o.get(k):
            morceaux.append(str(o[k]))
    if o.get("aspect_ratio"):
        morceaux.append(str(o["aspect_ratio"]))
    if o.get("duration"):
        morceaux.append(f"{o['duration']} s")
    if duree_video:
        morceaux.append(f"{_nb(duree_video)} s")
    if o.get("sound") or o.get("generate_audio") or o.get("audio"):
        morceaux.append("audio")
    return " · ".join(morceaux)


def lancer(utilisateur: str, cle_modele: str, prompt: str, options: Any,
           refs: List[str], langue: str = "fr") -> Dict[str, Any]:
    """Vérifie, estime, lance chez Kie et enregistre la tâche. Renvoie
    {ok: True, tache} ou {ok: False, erreur, code}. Ne lève pas."""
    t = _t(langue)
    if cle_modele == "visage":
        return lancer_visage(utilisateur, options, refs, langue)
    m = kie_ai.modele(cle_modele)
    if not m:
        return {"ok": False, "erreur": "Modèle inconnu." if langue != "en" else "Unknown model.", "code": "modele"}
    pb = kie_ai.verifier_prompt(cle_modele, prompt, langue)
    if pb:
        return {"ok": False, "erreur": pb, "code": "prompt"}
    if not kie_ai.cle_presente():
        return {"ok": False, "erreur": t["cle_absente"], "code": "sans_cle"}
    refs_meta = [r for r in (_reference(x) for x in (refs or [])[:int(m["references"]["max"])]) if r]
    if m["references"].get("types") and any(r.get("mime") not in m["references"]["types"] for r in refs_meta):
        return {"ok": False, "erreur": t["motion_refs" if m["type"] == "motion" else "ref_type_kling"], "code": "ref_type"}
    o = kie_ai.normaliser(cle_modele, options)
    images = [r for r in refs_meta if str(r.get("mime") or "").startswith("image/")]
    videos = [r for r in refs_meta if str(r.get("mime") or "").startswith("video/")]
    duree_video = 0.0
    if m["type"] == "motion":
        # exactement une photo et une vidéo ; la durée de la vidéo borne
        # Kling (3–30 s, 10 s si le personnage suit la photo) et fait le prix
        if len(images) != 1 or len(videos) != 1:
            return {"ok": False, "erreur": t["motion_refs"], "code": "refs"}
        duree_video = float(videos[0].get("duree") or 0)
        d_min, d_max = tuple(m["references"].get("duree") or (1, 60))
        if not d_min <= duree_video <= d_max:
            return {"ok": False, "code": "video_duree",
                    "erreur": t["video_duree"].format(s=_nb(duree_video), min=_nb(d_min), max=_nb(d_max))}
        if o.get("character_orientation") == "image" and duree_video > 10:
            return {"ok": False, "erreur": t["video_10s"].format(s=_nb(duree_video)), "code": "video_duree"}
    elif m["references"].get("videos_max"):
        # Seedance : des vidéos de référence en plus des images, chacune dans
        # les bornes du modèle ; la sortie garde la durée réglée
        videos = videos[:int(m["references"]["videos_max"])]
        d_min, d_max = tuple(m["references"].get("duree") or (1, 60))
        for v in videos:
            d = float(v.get("duree") or 0)
            if not d_min <= d <= d_max:
                return {"ok": False, "code": "video_duree",
                        "erreur": t["video_duree"].format(s=_nb(d), min=_nb(d_min), max=_nb(d_max))}
    else:
        videos = []       # une vidéo déposée puis un autre modèle choisi : pas envoyée
    nb_ouvertes = sum(1 for x in _ouvertes() if x.get("utilisateur") == utilisateur)
    if nb_ouvertes >= MAX_OUVERTES:
        return {"ok": False, "erreur": t["trop_en_cours"].format(n=MAX_OUVERTES), "code": "trop"}
    besoin = kie_ai.estimer(cle_modele, o, len(images), duree_video=duree_video)
    s = solde()
    if s["credits"] is not None and besoin > s["credits"]:
        return {"ok": False, "code": "credits",
                "erreur": t["credits_insuffisants"].format(reste=_nb(s["credits"]), besoin=_nb(besoin)),
                "credits": s["credits"]}
    modele_api, entree = kie_ai.entree_api(cle_modele, prompt, o, [r["url"] for r in images],
                                           videos=[r["url"] for r in videos])
    try:
        task_id = kie_ai.creer_tache(modele_api, entree)
    except kie_ai.ErreurKie as e:
        _oublier_solde()
        msg = kie_ai.message_pour(e.code, str(e), langue) if e.code in (401, 402, 404, 422, 429, 455, "reseau", "sans_cle") else str(e)
        if e.code == 402:
            s = solde(force=True)
            if s["credits"] is not None:
                msg = t["credits_insuffisants"].format(reste=_nb(s["credits"]), besoin=_nb(besoin))
        print(f"[studio-ia] createTask refusé ({e.code}) pour {utilisateur} / {modele_api} : {e}", flush=True)
        return {"ok": False, "erreur": msg, "code": e.code}
    maintenant = int(time.time())
    tache = {
        "id": uuid.uuid4().hex[:12], "task_id": task_id, "utilisateur": utilisateur,
        "modele": cle_modele, "nom_modele": m["nom"], "modele_api": modele_api, "type": m["type"],
        "prompt": (prompt or "").strip(), "options": o, "resume": _resume_options(m, o, duree_video),
        "references": [{"id": r["id"], "nom": r.get("nom", ""), "mime": r.get("mime", "")} for r in images + videos],
        "etat": "en_attente", "message": "", "credits_estimes": besoin, "credits": None,
        "cree_le": maintenant, "maj_le": maintenant, "fini_le": None,
        "fichiers": [], "urls_kie": [], "essais_dl": 0, "masque": False,
    }
    with _VERROU:
        taches = _charger()
        taches.append(tache)
        _ecrire(taches)
    print(f"[studio-ia] tâche {tache['id']} lancée par {utilisateur} : {modele_api}, ≈{besoin} crédits", flush=True)
    _assurer_suivi()
    return {"ok": True, "tache": _publique(tache, langue)}


def _nb(x: Any) -> str:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return "?"
    return str(int(f)) if f == int(f) else f"{f:.1f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------- suivi --

def _assurer_suivi() -> None:
    """Un seul fil ; il s'arrête tout seul quand plus rien n'est ouvert et
    repart à la génération suivante (ou au démarrage s'il en reste)."""
    with _VERROU:
        fil = _SUIVI.get("fil")
        if fil is not None and fil.is_alive():
            return
        if not _ouvertes():
            return
        fil = threading.Thread(target=_boucle_suivi, daemon=True, name="studio-ia-suivi")
        _SUIVI["fil"] = fil
        fil.start()


def _boucle_suivi() -> None:
    while True:
        ouvertes = _ouvertes()
        if not ouvertes:
            break
        for t in ouvertes:
            try:
                verifier(t["id"])
            except Exception as e:      # jamais tuer le fil pour une tâche
                print(f"[studio-ia] suivi {t.get('id')} : {type(e).__name__}: {e}", flush=True)
        # Les toutes jeunes tâches sont relues vite (une image sort en
        # quelques secondes) ; les vieilles, moins souvent.
        age_min = min(time.time() - t.get("cree_le", 0) for t in ouvertes)
        time.sleep(4 if age_min < 120 else 10)
    with _VERROU:
        _SUIVI["fil"] = None


def verifier(tid: str) -> Optional[Dict[str, Any]]:
    """Interroge Kie pour UNE tâche et met l'enregistrement à jour."""
    taches = _charger()
    t = next((x for x in taches if x.get("id") == tid), None)
    if not t or t.get("etat") not in ETATS_OUVERTS:
        return t
    if t.get("type") == "visage":
        return _verifier_visage(t)
    if time.time() - t.get("cree_le", 0) > DELAI_MAX_S:
        return _maj(tid, etat="echec", message="Délai dépassé (2 h) : Kie n'a jamais rendu cette tâche.",
                    fini_le=int(time.time()))
    # Résultat connu mais pas encore rapatrié : on réessaie le téléchargement.
    if t.get("urls_kie") and not t.get("fichiers"):
        return _rapatrier(t)
    try:
        d = kie_ai.detail_tache(t["task_id"])
    except kie_ai.ErreurKie as e:
        # Panne de réseau ou de Kie : on garde l'état, on note, on réessaie.
        return _maj(tid, derniere_erreur=f"{e.code}: {e}"[:200])
    etat = d.get("state")
    if etat in ("waiting", "queuing"):
        return _maj(tid, etat="en_attente", derniere_erreur="")
    if etat == "generating":
        return _maj(tid, etat="en_cours", derniere_erreur="")
    if etat == "fail":
        _oublier_solde()
        raison = (d.get("failMsg") or "").strip() or f"code {d.get('failCode') or '?'}"
        return _maj(tid, etat="echec", message=raison[:400], fini_le=int(time.time()),
                    credits=d.get("creditsConsumed"))
    if etat == "success":
        _oublier_solde()
        t = _maj(tid, etat="en_cours", urls_kie=list(d.get("resultUrls") or []),
                 credits=d.get("creditsConsumed"), duree_calcul=d.get("costTime"), derniere_erreur="")
        if not t.get("urls_kie"):
            return _maj(tid, etat="echec", message="Succès annoncé sans fichier.", fini_le=int(time.time()))
        return _rapatrier(t)
    return _maj(tid, derniere_erreur=f"état inconnu : {etat}"[:200])


def _rapatrier(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tid = t["id"]
    fichiers: List[Dict[str, Any]] = []
    _dossier_sorties().mkdir(parents=True, exist_ok=True)
    for n, url in enumerate(t.get("urls_kie") or []):
        ext = Path(url.split("?")[0]).suffix.lower()
        if ext not in _MIME_PAR_EXT:
            ext = ".mp4" if t.get("type") == "video" else ".png"
        nom = f"{tid}_{n}{ext}"
        dest = _dossier_sorties() / nom
        try:
            if not dest.exists():
                taille, ctype = kie_ai.telecharger(url, dest)
                if ctype in _EXT_PAR_MIME and _EXT_PAR_MIME[ctype] != ext:
                    neuf = dest.with_suffix(_EXT_PAR_MIME[ctype])
                    dest.replace(neuf)
                    dest, nom, ext = neuf, neuf.name, neuf.suffix
            fichiers.append({"nom": nom, "mime": _MIME_PAR_EXT.get(ext, "application/octet-stream"),
                             "taille": dest.stat().st_size, "vignette": _vignette(dest)})
        except Exception as e:
            essais = int(t.get("essais_dl") or 0) + 1
            print(f"[studio-ia] rapatriement {tid} ({essais}/{ESSAIS_DL}) : {type(e).__name__}: {e}", flush=True)
            if essais >= ESSAIS_DL:
                # On ne bloque pas l'utilisateur : la tâche est finie, les
                # liens Kie restent valables 14 jours.
                return _maj(tid, etat="fini", fini_le=int(time.time()), essais_dl=essais,
                            message="Fichier non rapatrié : lien Kie direct (14 jours).")
            return _maj(tid, essais_dl=essais, message="")
    return _maj(tid, etat="fini", fichiers=fichiers, fini_le=int(time.time()), message="")


def _vignette(video: Path) -> Optional[str]:
    """Une image fixe pour la carte d'une vidéo (ffmpeg s'il est là ; sinon
    la carte montre la vidéo elle-même)."""
    if video.suffix.lower() not in (".mp4", ".mov"):
        return None
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    dest = video.with_suffix(".jpg")
    try:
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "0.3", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=540:-2", str(dest)],
                       timeout=60, check=True, capture_output=True)
        return dest.name if dest.exists() else None
    except Exception as e:
        print(f"[studio-ia] vignette {video.name} : {type(e).__name__}: {e}", flush=True)
        return None


# ------------------------------------------------------------- lecture --

def _publique(t: Dict[str, Any], langue: str = "fr") -> Dict[str, Any]:
    """La tâche telle que l'écran la lit : liens du site, jamais le taskId
    brut ni les chemins disque."""
    fichiers = []
    for n, f in enumerate(t.get("fichiers") or []):
        fichiers.append({"url": f"/studio-ia/fichier/{t['id']}/{n}",
                         "dl": f"/studio-ia/fichier/{t['id']}/{n}?dl=1",
                         "mime": f.get("mime", ""), "taille": f.get("taille"),
                         "vignette": f"/studio-ia/fichier/{t['id']}/{n}?vignette=1" if f.get("vignette") else None})
    return {
        "id": t["id"], "modele": t.get("modele"), "nom_modele": t.get("nom_modele"),
        "type": t.get("type"), "prompt": t.get("prompt", ""), "options": t.get("options") or {},
        "resume": t.get("resume", ""), "etat": t.get("etat"), "message": t.get("message", ""),
        "credits_estimes": t.get("credits_estimes"), "credits": t.get("credits"),
        "cree_le": t.get("cree_le"), "fini_le": t.get("fini_le"), "utilisateur": t.get("utilisateur"),
        "fichiers": fichiers,
        "urls_kie": list(t.get("urls_kie") or []) if (t.get("etat") == "fini" and not fichiers) else [],
        "references": [{"apercu": "/studio-ia/reference/" + r["id"], "nom": r.get("nom", ""), "mime": r.get("mime", "")}
                       for r in (t.get("references") or []) if _ID_OK.match(str(r.get("id") or ""))],
        "derniere_erreur": t.get("derniere_erreur", ""),
        "visage": ({"progression": int((t.get("visage") or {}).get("progression") or 0),
                    "etape": str((t.get("visage") or {}).get("etape") or ""),
                    "machine": str((t.get("visage") or {}).get("machine") or "")}
                   if t.get("type") == "visage" else None),
    }


def taches_visibles(utilisateur: str, admin: bool, langue: str = "fr") -> List[Dict[str, Any]]:
    out = []
    for t in _charger():
        if t.get("masque"):
            continue
        if not admin and t.get("utilisateur") != utilisateur:
            continue
        out.append(_publique(t, langue))
    out.sort(key=lambda x: x.get("cree_le") or 0, reverse=True)
    return out


# -------------------------------------------------------------- visage --

def _fichier_jeton_machine() -> Path:
    return DOSSIER / "machine.json"


def jeton_machine() -> str:
    """Le jeton que la machine (visage_worker.py) présente. Créé au premier
    besoin, fichier 600, jamais renouvelé : il ne circule que vers un admin
    (commande à lancer) et dans l'en-tête de la machine."""
    with _VERROU:
        d = safe_json.load(_fichier_jeton_machine(), default=None)
        if isinstance(d, dict) and d.get("jeton"):
            return str(d["jeton"])
        jeton = secrets.token_hex(24)
        DOSSIER.mkdir(parents=True, exist_ok=True)
        safe_json.write(_fichier_jeton_machine(), {"jeton": jeton, "cree_le": int(time.time())}, backup=False)
        try:
            _fichier_jeton_machine().chmod(0o600)
        except OSError:
            pass
        return jeton


def jeton_machine_ok(envoye: str) -> bool:
    envoye = (envoye or "").strip()
    return bool(envoye) and hmac.compare_digest(envoye, jeton_machine())


def commande_machine(site: str) -> str:
    """La commande à lancer une fois sur la machine (montrée à l'admin seul) :
    elle va chercher visage_worker.py sur le site (au jeton), puis l'installe
    (FaceFusion, venv, agent launchd) dans ~/.vabot/visage."""
    j = jeton_machine()
    return (f"mkdir -p ~/.vabot/visage && curl -fsS -H 'X-Visage-Jeton: {j}' {site}/studio-ia/visage/worker.py "
            f"-o ~/.vabot/visage/visage_worker.py && python3 ~/.vabot/visage/visage_worker.py installer --site {site} --jeton {j}")


def voir_machine(nom: str, etat: str = "libre", tid: str = "") -> None:
    nom = (nom or "machine")[:40]
    _MACHINES[nom] = {"nom": nom, "vu_le": int(time.time()), "etat": etat, "tache": tid}


def machines_visage() -> List[Dict[str, Any]]:
    """Les machines vues récemment (en mémoire : au redémarrage, la
    prochaine passe de la machine la remet en 10 s)."""
    limite = time.time() - 6 * 3600
    return sorted([dict(m) for m in _MACHINES.values() if m["vu_le"] > limite], key=lambda m: -m["vu_le"])


def etat_visage(langue: str = "fr", admin: bool = False, site: str = "https://youl4b.com") -> Dict[str, Any]:
    d: Dict[str, Any] = {"machines": machines_visage(), "en_ligne_s": MACHINE_EN_LIGNE_S}
    if admin:
        d["commande"] = commande_machine(site)
    return d


def lancer_visage(utilisateur: str, options: Any, refs: List[str], langue: str = "fr") -> Dict[str, Any]:
    """Met un remplacement de visage en file : 1 photo (le visage) + 1 vidéo
    (ce qui est modifié). Rien ne part chez Kie, rien n'est débité."""
    t = _t(langue)
    refs_meta = [r for r in (_reference(x) for x in (refs or [])[:2]) if r]
    images = [r for r in refs_meta if str(r.get("mime") or "").startswith("image/")]
    videos = [r for r in refs_meta if str(r.get("mime") or "").startswith("video/")]
    if len(images) != 1 or len(videos) != 1:
        return {"ok": False, "erreur": t["visage_refs"], "code": "refs"}
    duree_video = float(videos[0].get("duree") or 0)
    if not 1 <= duree_video <= DUREE_MAX_VISAGE_S:
        return {"ok": False, "code": "video_duree",
                "erreur": t["video_duree"].format(s=_nb(duree_video), min="1", max=str(DUREE_MAX_VISAGE_S))}
    nb_ouvertes = sum(1 for x in _ouvertes() if x.get("utilisateur") == utilisateur)
    if nb_ouvertes >= MAX_OUVERTES:
        return {"ok": False, "erreur": t["trop_en_cours"].format(n=MAX_OUVERTES), "code": "trop"}
    o = {"finition": "rapide" if isinstance(options, dict) and options.get("finition") == "rapide" else "nette"}
    maintenant = int(time.time())
    tache = {
        "id": uuid.uuid4().hex[:12], "task_id": "", "utilisateur": utilisateur,
        "modele": "visage", "nom_modele": MODELE_VISAGE["nom"], "modele_api": "facefusion", "type": "visage",
        "prompt": "", "options": o, "resume": f"{o['finition']} · {_nb(duree_video)} s",
        "references": [{"id": r["id"], "nom": r.get("nom", ""), "mime": r.get("mime", "")} for r in images + videos],
        "etat": "en_attente", "message": "", "credits_estimes": 0, "credits": 0,
        "cree_le": maintenant, "maj_le": maintenant, "fini_le": None,
        "fichiers": [], "urls_kie": [], "essais_dl": 0, "masque": False,
        "visage": {"progression": 0, "etape": "attente", "machine": "", "pris_le": 0, "vu_le": 0, "reprises": 0,
                   "duree": round(duree_video, 2)},
    }
    with _VERROU:
        taches = _charger()
        taches.append(tache)
        _ecrire(taches)
    print(f"[studio-ia] visage {tache['id']} mis en file par {utilisateur} ({o['finition']}, {_nb(duree_video)} s)", flush=True)
    _assurer_suivi()
    return {"ok": True, "tache": _publique(tache, langue)}


def _verifier_visage(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pas de Kie à interroger : seuls les délais. Une machine muette rend
    son travail à la file (deux fois), un travail sans machine finit par
    expirer."""
    tid = t["id"]
    v = dict(t.get("visage") or {})
    maintenant = time.time()
    if t.get("etat") == "en_cours":
        dernier = max(float(v.get("vu_le") or 0), float(v.get("pris_le") or 0))
        if maintenant - dernier > SILENCE_MAX_VISAGE_S:
            reprises = int(v.get("reprises") or 0) + 1
            if reprises > 2:
                return _maj(tid, etat="echec", fini_le=int(maintenant),
                            message=f"La machine {v.get('machine') or '?'} n'a plus donné signe (3 fois) : travail abandonné.")
            v.update({"reprises": reprises, "progression": 0, "etape": "attente", "machine": ""})
            print(f"[studio-ia] visage {tid} : machine muette, remis en file ({reprises})", flush=True)
            return _maj(tid, etat="en_attente", visage=v,
                        message="La machine n'a plus donné signe : remis en file.")
        return t
    if maintenant - float(t.get("cree_le") or 0) > ATTENTE_MAX_VISAGE_S:
        return _maj(tid, etat="echec", fini_le=int(maintenant),
                    message="Aucune machine n'a pris ce travail en 24 h.")
    return t


def prendre_travail(nom_machine: str) -> Optional[Dict[str, Any]]:
    """Le plus ancien travail en attente passe à la machine qui le demande.
    Une machine qui en tient déjà un (reprise après coupure) le retrouve."""
    with _VERROU:
        taches = _charger()
        miens = [x for x in taches if x.get("type") == "visage" and x.get("etat") == "en_cours"
                 and (x.get("visage") or {}).get("machine") == nom_machine]
        attente = sorted([x for x in taches if x.get("type") == "visage" and x.get("etat") == "en_attente"],
                         key=lambda x: x.get("cree_le") or 0)
        t = miens[0] if miens else (attente[0] if attente else None)
        if not t:
            return None
        v = dict(t.get("visage") or {})
        v.update({"machine": nom_machine, "pris_le": int(time.time()), "vu_le": int(time.time()),
                  "progression": 0, "etape": "demarrage"})
        t["etat"], t["visage"], t["message"], t["maj_le"] = "en_cours", v, "", int(time.time())
        _ecrire(taches)
    entrees = []
    for n, r in enumerate(t.get("references") or []):
        meta = _reference(r.get("id") or "")
        if not meta:
            continue
        role = "visage" if str(meta.get("mime") or "").startswith("image/") else "cible"
        entrees.append({"role": role, "n": n, "url": f"/studio-ia/visage/entree/{t['id']}/{n}",
                        "ext": Path(meta["chemin"]).suffix, "duree": meta.get("duree") or 0})
    return {"id": t["id"], "finition": (t.get("options") or {}).get("finition", "nette"), "entrees": entrees}


def avancement_visage(tid: str, progression: Any, etape: str, machine: str) -> Optional[Dict[str, Any]]:
    try:
        p = max(0, min(100, int(float(progression))))
    except (TypeError, ValueError):
        p = 0
    t = next((x for x in _charger() if x.get("id") == tid), None)
    if not t or t.get("type") != "visage" or t.get("etat") != "en_cours":
        return None
    v = dict(t.get("visage") or {})
    v.update({"progression": p, "etape": (etape or "")[:40], "vu_le": int(time.time()), "machine": machine or v.get("machine", "")})
    return _maj(tid, visage=v)


def resultat_visage(tid: str, octets: bytes, nom: str) -> Optional[Dict[str, Any]]:
    """Le fichier rendu par la machine entre dans sorties/ comme un résultat
    Kie : même carte, même aperçu, même téléchargement."""
    t = next((x for x in _charger() if x.get("id") == tid), None)
    if not t or t.get("type") != "visage" or t.get("etat") not in ETATS_OUVERTS:
        return None
    ext = Path(nom or "").suffix.lower()
    if ext not in _MIME_PAR_EXT:
        ext = ".mp4"
    _dossier_sorties().mkdir(parents=True, exist_ok=True)
    dest = _dossier_sorties() / f"{tid}_0{ext}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(octets)
    tmp.replace(dest)
    fichier = {"nom": dest.name, "mime": _MIME_PAR_EXT[ext], "taille": dest.stat().st_size, "vignette": _vignette(dest)}
    v = dict(t.get("visage") or {})
    v.update({"progression": 100, "etape": "fini", "vu_le": int(time.time())})
    print(f"[studio-ia] visage {tid} rendu par {v.get('machine') or '?'} ({fichier['taille']} octets)", flush=True)
    return _maj(tid, etat="fini", fichiers=[fichier], fini_le=int(time.time()), message="", credits=0, visage=v)


def echec_visage(tid: str, erreur: str) -> Optional[Dict[str, Any]]:
    t = next((x for x in _charger() if x.get("id") == tid), None)
    if not t or t.get("type") != "visage" or t.get("etat") not in ETATS_OUVERTS:
        return None
    print(f"[studio-ia] visage {tid} en échec : {erreur[:200]}", flush=True)
    return _maj(tid, etat="echec", fini_le=int(time.time()), message=(erreur or "échec sur la machine")[:400])


# --------------------------------------------------------------- rendu --

_CSS = """
#sia-root{--sia-carte:#1a1a1a;--sia-carte2:#121212;--sia-bord:#2a2a2a;--sia-texte:#eee;--sia-faible:#9a9a9a;--sia-chip:#222;--sia-accent:var(--ui-accent,#3b82f6);--sia-accent-rgb:var(--ui-accent-rgb,59,130,246);--sia-sur-accent:var(--ui-on-accent,#fff);--sia-ok:#22c55e;--sia-ko:#ef4444;--sia-att:#f59e0b;color:var(--sia-texte);max-width:1400px}
body.infloww #sia-root{--sia-carte:#242424;--sia-carte2:#1b1b1b;--sia-bord:#3a3a3a;--sia-texte:#f2f2f2;--sia-faible:#999;--sia-chip:#2c2c2c}
body.light #sia-root{--sia-carte:#fff;--sia-carte2:#f5f5f5;--sia-bord:#e0e0e0;--sia-texte:#151515;--sia-faible:#666;--sia-chip:#f3f3f3}
#sia-root *{box-sizing:border-box}
/* [hidden] perdait contre le display:grid de .sia-corps : la vue Creer restait
   affichee sous l'Historique. */
#sia-root [hidden]{display:none!important}
#sia-root .sia-entete{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:14px}
#sia-root h2{margin:0 0 4px;font-size:22px;font-weight:800;letter-spacing:-.02em}
#sia-root .sia-sous{margin:0;color:var(--sia-faible);font-size:13px;flex:1;min-width:200px}
#sia-root .sia-droite{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#sia-root .sia-credits{display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border-radius:999px;border:1px solid var(--sia-bord);background:var(--sia-carte);font-size:13px;font-weight:700;white-space:nowrap}
#sia-root .sia-credits.ko{color:var(--sia-ko);border-color:rgba(239,68,68,.45)}
#sia-root .sia-credits a{color:inherit;text-decoration:none;opacity:.7;font-weight:500}
#sia-root .sia-seg{display:inline-flex;padding:3px;border-radius:10px;border:1px solid var(--sia-bord);background:var(--sia-carte)}
#sia-root .sia-seg button{appearance:none;border:0;background:transparent;color:var(--sia-faible);padding:7px 14px;border-radius:8px;font:inherit;font-size:13px;font-weight:600;cursor:pointer}
#sia-root .sia-seg button.on{background:var(--sia-accent);color:var(--sia-sur-accent)}
#sia-root .sia-seg .sia-nb{display:inline-block;min-width:18px;padding:0 5px;border-radius:999px;background:var(--sia-att);color:#1c1600;font-size:11px;margin-left:4px}
#sia-root .sia-types{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
#sia-root .sia-type{appearance:none;border:1px solid var(--sia-bord);background:var(--sia-carte);color:var(--sia-faible);padding:9px 14px;border-radius:10px;font:inherit;font-size:13px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;gap:8px}
#sia-root .sia-type svg{width:16px;height:16px}
#sia-root .sia-type.on{color:var(--sia-accent);border-color:var(--sia-accent);background:rgba(var(--sia-accent-rgb),.10)}
#sia-root .sia-corps{display:grid;grid-template-columns:330px minmax(0,1fr);gap:16px;align-items:start}
#sia-root .sia-carte{background:var(--sia-carte);border:1px solid var(--sia-bord);border-radius:14px;padding:16px;margin-bottom:14px}
#sia-root .sia-carte h4{margin:0 0 10px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--sia-faible);font-weight:700;display:flex;align-items:center;gap:8px}
#sia-root .sia-carte h4 small{font-weight:500;text-transform:none;letter-spacing:0;opacity:.8}
#sia-root .sia-carte-tete{display:flex;align-items:center;justify-content:space-between;gap:10px}
#sia-root .sia-modele{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--sia-bord);border-radius:12px;cursor:pointer;margin-bottom:8px;background:var(--sia-carte2);transition:border-color .15s}
#sia-root .sia-modele:last-child{margin-bottom:0}
#sia-root .sia-modele:hover{border-color:var(--sia-faible)}
#sia-root .sia-modele.on{border-color:var(--sia-accent);box-shadow:0 0 0 1px var(--sia-accent) inset}
#sia-root .sia-logo{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;color:#fff;flex-shrink:0}
#sia-root .sia-logo.l-kling{background:linear-gradient(135deg,#3b82f6,#6366f1)}
#sia-root .sia-logo.l-seedance{background:linear-gradient(135deg,#f97316,#ef4444)}
#sia-root .sia-logo.l-wan{background:linear-gradient(135deg,#a855f7,#7c3aed)}
#sia-root .sia-logo.l-seedream{background:linear-gradient(135deg,#ec4899,#f43f5e)}
#sia-root .sia-logo.l-visage{background:linear-gradient(135deg,#22c55e,#0ea5e9)}
#sia-root .sia-barre{width:100%;height:6px;border-radius:999px;background:var(--sia-bord);overflow:hidden;margin:4px 0}
#sia-root .sia-barre i{display:block;height:100%;background:var(--sia-accent);border-radius:999px;transition:width .6s}
#sia-root .sia-machine{padding:10px 12px;border-radius:10px;font-size:12px;line-height:1.5;margin-bottom:14px;border:1px solid var(--sia-bord);background:var(--sia-carte);color:var(--sia-faible)}
#sia-root .sia-machine.ko{background:rgba(245,158,11,.10);border-color:rgba(245,158,11,.45);color:var(--sia-att)}
#sia-root .sia-machine.ok{color:var(--sia-ok)}
#sia-root .sia-machine code{display:block;margin-top:6px;padding:8px;border-radius:8px;background:var(--sia-carte2);color:var(--sia-texte);font-size:11px;word-break:break-all;user-select:all}
#sia-root .sia-modele-txt{min-width:0;flex:1}
#sia-root .sia-modele-nom{font-weight:700;font-size:14px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
#sia-root .sia-badge{font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;background:rgba(34,197,94,.14);color:var(--sia-ok);text-transform:uppercase;letter-spacing:.04em}
#sia-root .sia-modele-sous{font-size:12px;color:var(--sia-faible);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sia-root .sia-prix{font-size:12px;color:var(--sia-faible);white-space:nowrap}
#sia-root .sia-drop{border:1.5px dashed var(--sia-bord);border-radius:12px;padding:18px 12px;text-align:center;cursor:pointer;color:var(--sia-faible);font-size:13px;transition:border-color .15s,background .15s}
#sia-root .sia-drop:hover,#sia-root .sia-drop.sur{border-color:var(--sia-accent);background:rgba(var(--sia-accent-rgb),.06)}
#sia-root .sia-drop b{display:block;color:var(--sia-texte);font-size:13px;margin-bottom:3px}
#sia-root .sia-drop input{display:none}
#sia-root .sia-refs{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
#sia-root .sia-ref{position:relative;width:64px;height:64px;border-radius:10px;overflow:hidden;border:1px solid var(--sia-bord);background:var(--sia-carte2)}
#sia-root .sia-ref img,#sia-root .sia-ref video{width:100%;height:100%;object-fit:cover;display:block}
#sia-root .sia-ref.video{width:96px}
#sia-root .sia-refs-mini video{width:44px;height:44px;object-fit:cover;border-radius:8px;border:1px solid var(--sia-bord)}
#sia-root .sia-ref .sia-ref-x{position:absolute;top:3px;right:3px;width:20px;height:20px;border-radius:50%;border:0;background:rgba(0,0,0,.65);color:#fff;font-size:12px;line-height:20px;cursor:pointer;padding:0}
#sia-root .sia-ref .sia-ref-n{position:absolute;left:4px;bottom:3px;font-size:10px;font-weight:700;color:#fff;background:rgba(0,0,0,.55);padding:1px 5px;border-radius:6px}
#sia-root .sia-ref.envoi{display:flex;align-items:center;justify-content:center}
#sia-root .sia-aide{margin:8px 0 0;font-size:12px;color:var(--sia-faible);line-height:1.45}
#sia-root .sia-opt{margin-bottom:14px}
#sia-root .sia-opt:last-child{margin-bottom:0}
#sia-root .sia-opt-tete{display:flex;align-items:center;justify-content:space-between;font-size:12px;font-weight:700;color:var(--sia-faible);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
#sia-root .sia-opt-val{font-weight:800;color:var(--sia-texte);text-transform:none;letter-spacing:0;background:var(--sia-chip);padding:3px 9px;border-radius:8px;font-size:12px}
#sia-root .sia-chips{display:flex;flex-wrap:wrap;gap:6px}
#sia-root .sia-chip{appearance:none;border:1px solid var(--sia-bord);background:var(--sia-chip);color:var(--sia-texte);padding:7px 12px;border-radius:9px;font:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:border-color .12s,background .12s,color .12s}
#sia-root .sia-chip.on{background:rgba(var(--sia-accent-rgb),.14);border-color:var(--sia-accent);color:var(--sia-accent)}
#sia-root input[type=range].sia-range{width:100%;padding:0;margin:4px 0 0;background:transparent;border:0;accent-color:var(--sia-accent);height:22px}
#sia-root .sia-range-bornes{display:flex;justify-content:space-between;font-size:11px;color:var(--sia-faible);margin-top:2px}
#sia-root .sia-switch{display:flex;align-items:center;justify-content:space-between;gap:12px;cursor:pointer}
#sia-root .sia-switch .sia-switch-txt{font-size:13px;font-weight:600}
#sia-root .sia-switch .sia-switch-aide{display:block;font-size:12px;color:var(--sia-faible);font-weight:400;margin-top:2px;line-height:1.4}
#sia-root .sia-switch input{display:none}
#sia-root .sia-switch .sia-track{width:40px;height:22px;border-radius:999px;background:var(--sia-bord);position:relative;flex-shrink:0;transition:background .15s}
#sia-root .sia-switch .sia-track::after{content:'';position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:left .15s}
#sia-root .sia-switch input:checked + .sia-track{background:var(--sia-ok)}
#sia-root .sia-switch input:checked + .sia-track::after{left:21px}
#sia-root .sia-estim-l{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;font-size:13px;color:var(--sia-faible)}
#sia-root .sia-estim-l b{display:inline-flex;align-items:center;gap:5px;padding:5px 11px;border-radius:999px;background:rgba(var(--sia-accent-rgb),.12);color:var(--sia-accent);font-size:13px;font-weight:800}
#sia-root .sia-generer{appearance:none;width:100%;border:0;border-radius:11px;padding:13px;background:var(--sia-accent);color:var(--sia-sur-accent);font:inherit;font-size:15px;font-weight:800;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:0 8px 22px rgba(var(--sia-accent-rgb),.3);transition:transform .12s,box-shadow .12s,opacity .12s}
#sia-root .sia-generer:hover{transform:translateY(-1px);box-shadow:0 12px 28px rgba(var(--sia-accent-rgb),.4)}
#sia-root .sia-generer:disabled{opacity:.45;cursor:not-allowed;transform:none;box-shadow:none}
#sia-root .sia-generer svg{width:16px;height:16px}
#sia-root .sia-raccourci{text-align:center;font-size:11px;color:var(--sia-faible);margin:8px 0 0}
#sia-root .sia-alerte{display:none;margin:10px 0 0;padding:10px 12px;border-radius:10px;font-size:13px;line-height:1.45;background:rgba(239,68,68,.10);border:1px solid rgba(239,68,68,.4);color:var(--sia-ko)}
#sia-root .sia-alerte.on{display:block}
#sia-root .sia-alerte.att{background:rgba(245,158,11,.10);border-color:rgba(245,158,11,.45);color:var(--sia-att)}
#sia-root .sia-alerte a{color:inherit}
#sia-root textarea.sia-textarea{width:100%;min-height:170px;resize:vertical;background:var(--sia-carte2);border:1px solid var(--sia-bord);color:var(--sia-texte);border-radius:10px;padding:14px;font:inherit;font-size:14px;line-height:1.55}
#sia-root textarea.sia-textarea:focus{outline:none;border-color:var(--sia-accent);box-shadow:0 0 0 3px rgba(var(--sia-accent-rgb),.18)}
#sia-root .sia-compteur{font-size:12px;color:var(--sia-faible);font-variant-numeric:tabular-nums}
#sia-root .sia-compteur.ko{color:var(--sia-ko)}
#sia-root .sia-grille{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
#sia-root .sia-vide{grid-column:1/-1;padding:40px 16px;text-align:center;color:var(--sia-faible);font-size:13px;border:1px dashed var(--sia-bord);border-radius:12px}
#sia-root .sia-tache{position:relative;border-radius:12px;overflow:hidden;background:var(--sia-carte2);border:1px solid var(--sia-bord);aspect-ratio:9/16;cursor:pointer}
#sia-root .sia-tache.paysage{aspect-ratio:16/10}
#sia-root .sia-tache.carre{aspect-ratio:1/1}
#sia-root .sia-tache img,#sia-root .sia-tache video{width:100%;height:100%;object-fit:cover;display:block;background:#000}
#sia-root .sia-tache .sia-sur{position:absolute;left:0;right:0;bottom:0;padding:26px 10px 9px;background:linear-gradient(transparent,rgba(0,0,0,.78));color:#fff;font-size:12px;line-height:1.35;pointer-events:none}
#sia-root .sia-tache .sia-sur b{display:block;font-size:12px;font-weight:700}
#sia-root .sia-tache .sia-sur span{opacity:.85}
#sia-root .sia-tache .sia-actions{position:absolute;top:7px;right:7px;display:flex;gap:5px;opacity:0;transition:opacity .15s}
#sia-root .sia-tache:hover .sia-actions,#sia-root .sia-tache.attente .sia-actions{opacity:1}
#sia-root .sia-tache .sia-actions a,#sia-root .sia-tache .sia-actions button{width:28px;height:28px;border-radius:8px;border:0;background:rgba(0,0,0,.6);color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;text-decoration:none;padding:0}
#sia-root .sia-tache .sia-actions svg{width:14px;height:14px}
#sia-root .sia-tache.attente{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;text-align:center;padding:14px;color:var(--sia-faible);font-size:12px;cursor:default}
#sia-root .sia-tache.attente .sia-etat{color:var(--sia-texte);font-weight:700;font-size:13px}
#sia-root .sia-tache.echec{border-color:rgba(239,68,68,.5)}
#sia-root .sia-tache.echec .sia-etat{color:var(--sia-ko)}
#sia-root .sia-tache .sia-chrono{font-variant-numeric:tabular-nums}
#sia-root .sia-tache .sia-prompt-min{font-size:11px;line-height:1.4;max-height:4.2em;overflow:hidden;color:var(--sia-faible)}
#sia-root .sia-rouet{width:28px;height:28px;border-radius:50%;border:3px solid rgba(var(--sia-accent-rgb),.2);border-top-color:var(--sia-accent);animation:siaSpin .8s linear infinite}
@keyframes siaSpin{to{transform:rotate(360deg)}}
#sia-root .sia-hist-tete{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}
#sia-root .sia-lien{appearance:none;border:1px solid var(--sia-bord);background:var(--sia-carte);color:var(--sia-texte);padding:7px 12px;border-radius:9px;font:inherit;font-size:13px;font-weight:600;cursor:pointer}
#sia-root .sia-modal{position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.82);display:none;align-items:center;justify-content:center;padding:20px}
#sia-root .sia-modal.on{display:flex}
#sia-root .sia-modal-boite{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:0;max-width:1100px;width:100%;max-height:92vh;background:var(--sia-carte);border:1px solid var(--sia-bord);border-radius:16px;overflow:hidden}
#sia-root .sia-modal-media{background:#000;display:flex;align-items:center;justify-content:center;min-height:320px}
#sia-root .sia-modal-media img,#sia-root .sia-modal-media video{max-width:100%;max-height:92vh;display:block}
#sia-root .sia-modal-cote{padding:18px;overflow:auto;display:flex;flex-direction:column;gap:12px;font-size:13px}
#sia-root .sia-modal-cote h3{margin:0;font-size:16px}
#sia-root .sia-modal-cote .sia-meta{color:var(--sia-faible);font-size:12px;line-height:1.5}
#sia-root .sia-modal-cote .sia-prompt-plein{white-space:pre-wrap;background:var(--sia-carte2);border:1px solid var(--sia-bord);border-radius:10px;padding:10px;font-size:13px;line-height:1.5;max-height:260px;overflow:auto}
#sia-root .sia-modal-cote .sia-btns{display:flex;flex-direction:column;gap:8px;margin-top:auto}
#sia-root .sia-btn{appearance:none;border:1px solid var(--sia-bord);background:var(--sia-chip);color:var(--sia-texte);padding:10px 12px;border-radius:10px;font:inherit;font-size:13px;font-weight:700;cursor:pointer;text-align:center;text-decoration:none;display:flex;align-items:center;justify-content:center;gap:8px}
#sia-root .sia-btn.primaire{background:var(--sia-accent);border-color:var(--sia-accent);color:var(--sia-sur-accent)}
#sia-root .sia-btn.danger{color:var(--sia-ko)}
#sia-root .sia-btn svg{width:15px;height:15px}
/* Theme clair : « body.light.inflowwlight a{color:#1677FF!important} » (0,2,1)
   repeignait le lien Telecharger en bleu sur son fond bleu -> bouton vide. Il
   faut une regle PLUS SPECIFIQUE (1,3,1) et !important, pas seulement !important. */
body.light #sia-root a.sia-btn.primaire{color:var(--sia-sur-accent)!important}
body.light #sia-root .sia-tache .sia-actions a{color:#fff!important}
#sia-root .sia-fermer{position:absolute;top:14px;right:16px;width:36px;height:36px;border-radius:50%;border:0;background:rgba(255,255,255,.12);color:#fff;font-size:20px;cursor:pointer}
#sia-root .sia-refs-mini{display:flex;gap:6px;flex-wrap:wrap}
#sia-root .sia-refs-mini img{width:44px;height:44px;object-fit:cover;border-radius:8px;border:1px solid var(--sia-bord)}
#sia-root .sia-sans-cle{padding:14px 16px;border-radius:12px;background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.45);color:var(--sia-att);font-size:13px;line-height:1.5;margin-bottom:14px}
#sia-root .sia-sans-cle code{font-size:12px}
#sia-root .sia-cle{padding:14px 16px;border-radius:12px;background:var(--sia-carte);border:1px solid var(--sia-bord);margin-bottom:14px}
#sia-root .sia-cle-tete{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
#sia-root .sia-cle-tete h4{margin:0;font-size:14px}
#sia-root .sia-cle-etat{font-size:12px;color:var(--sia-faible)}
#sia-root .sia-cle-etat.ko{color:var(--sia-att)}
#sia-root .sia-cle .sia-aide{margin:8px 0 0}
#sia-root .sia-cle-ligne{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
#sia-root .sia-cle-ligne input{flex:1 1 260px;min-width:0;background:var(--sia-carte2);border:1px solid var(--sia-bord);color:var(--sia-texte);border-radius:9px;padding:9px 12px;font:inherit;font-size:13px}
#sia-root .sia-cle-ligne input:focus{outline:none;border-color:var(--sia-accent)}
#sia-root .sia-lien.primaire{background:var(--sia-accent);color:var(--sia-sur-accent);border-color:var(--sia-accent)}
#sia-root .sia-lien:disabled{opacity:.55;cursor:default}
#sia-root .sia-cle-msg{font-size:12px;margin-top:8px;min-height:1em;color:var(--sia-faible)}
#sia-root .sia-cle-msg.ko{color:var(--sia-ko)}
#sia-root .sia-cle-msg.ok{color:var(--sia-ok)}
/* thème clair : la règle générale du site bleuit les liens et peut assombrir
   un texte blanc ; le bouton plein garde son blanc sur l'accent */
body.light #sia-root button.sia-lien.primaire{color:var(--sia-sur-accent)!important;background:var(--sia-accent)!important}
@media (max-width:980px){#sia-root .sia-corps{grid-template-columns:1fr}#sia-root .sia-modal-boite{grid-template-columns:1fr;max-height:95vh;overflow:auto}#sia-root .sia-modal-media{min-height:200px}}
"""

_SVG_FILM = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M7 4v16M17 4v16M2 9h5M2 15h5M17 9h5M17 15h5"/></svg>'
_SVG_MOTION = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="4" r="1.8"/><path d="m6 20 4-7 3 2 2 5"/><path d="m4 12 5-3 4 1 3 3 4-1"/><path d="m9 9-1.5 5"/></svg>'
_SVG_VISAGE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="9" r="4"/><path d="M5 20a7 7 0 0 1 14 0"/><path d="m17 3 2 2-2 2"/><path d="m7 3-2 2 2 2"/></svg>'
_SVG_PHOTO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>'
_SVG_ETINCELLE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 17l.7 1.8 1.8.7-1.8.7L19 22l-.7-1.8-1.8-.7 1.8-.7z"/></svg>'


def rendu_html(langue: str = "fr", admin: bool = False, site: str = "https://youl4b.com") -> str:
    """Le fragment de l'onglet (CSS + HTML + configuration JSON + script).
    Sans état de page : réinjectable tel quel par le chargeur paresseux.
    `admin` : montrer le panneau de la clé (coller / changer)."""
    t = _t(langue)
    e = html.escape
    try:
        version = int((BOT_DIR / "studio_ia_app.js").stat().st_mtime)
    except OSError:
        version = 0
    src = kie_ai.source_cle()
    conf = {
        "langue": langue, "t": t, "cle": kie_ai.cle_presente(), "admin": bool(admin),
        "cle_fin": src["fin"], "cle_source": src["source"],
        "modeles": kie_ai.registre_public(langue) + [registre_visage(langue)], "max_ouvertes": MAX_OUVERTES,
        "visage": etat_visage(langue, admin, site),
    }
    # Sans clé : l'admin a le champ pour la coller, les autres savent à qui la
    # demander. Avec clé, l'admin retrouve le panneau par le bouton 🔑.
    sans_cle = "" if (conf["cle"] or admin) else f'<div class="sia-sans-cle">{e(t["cle_absente"])}</div>'
    bouton_cle = (f'<button type="button" class="sia-lien" id="sia-cle-ouvrir" title="{e(t["cle_bouton"])}">🔑</button>'
                  if admin else "")
    panneau_cle = "" if not admin else f"""<div class="sia-cle" id="sia-cle"{"" if not conf["cle"] else " hidden"}>
  <div class="sia-cle-tete"><h4>🔑 {e(t["cle_titre"])}</h4><span class="sia-cle-etat{"" if conf["cle"] else " ko"}" id="sia-cle-etat">{e(t["cle_en_place"].format(fin=src["fin"]) if conf["cle"] else t["cle_manquante_admin"])}</span></div>
  <p class="sia-aide">{e(t["cle_aide"])} <a href="https://kie.ai/api-key" target="_blank" rel="noopener">kie.ai/api-key</a>. {e(t["cle_aide2"])}</p>
  <form class="sia-cle-ligne" id="sia-cle-form" autocomplete="off">
    <input type="password" id="sia-cle-input" placeholder="{e(t["cle_ph"])}" autocomplete="new-password" spellcheck="false" maxlength="512">
    <button type="submit" class="sia-lien primaire" id="sia-cle-btn">{e(t["cle_enregistrer"])}</button>
    <button type="button" class="sia-lien" id="sia-cle-annuler"{"" if conf["cle"] else " hidden"}>{e(t["cle_annuler"])}</button>
  </form>
  <div class="sia-cle-msg" id="sia-cle-msg"></div>
</div>"""
    return f"""<style>{_CSS}</style>
<div id="sia-root" class="sia" data-langue="{e(langue)}">
<div class="sia-entete">
  <p class="sia-sous">{e(t["sous"])}</p>
  <div class="sia-droite">
    <span class="sia-credits" id="sia-credits" title="{e(t["doc"])}">⚡ <span id="sia-credits-txt">…</span> <a href="https://kie.ai/pricing" target="_blank" rel="noopener">↗</a></span>
    {bouton_cle}
    <div class="sia-seg" id="sia-vues"><button type="button" class="on" data-vue="creer">{e(t["creer"])}</button><button type="button" data-vue="historique">{e(t["historique"])}<span class="sia-nb" id="sia-nb-ouvertes" hidden>0</span></button></div>
  </div>
</div>
{sans_cle}
{panneau_cle}
<div class="sia-types" id="sia-types">
  <button type="button" class="sia-type on" data-type="video">{_SVG_FILM}{e(t["reels"])}</button>
  <button type="button" class="sia-type" data-type="image">{_SVG_PHOTO}{e(t["photo"])}</button>
  <button type="button" class="sia-type" data-type="motion">{_SVG_MOTION}{e(t["motion"])}</button>
  <button type="button" class="sia-type" data-type="visage">{_SVG_VISAGE}{e(t["visage"])}</button>
</div>
<div class="sia-corps" id="sia-vue-creer">
  <aside>
    <section class="sia-carte"><h4>{e(t["modele"])}</h4><div id="sia-modeles"></div></section>
    <div class="sia-machine" id="sia-machine" hidden></div>
    <section class="sia-carte"><h4>{e(t["references"])} <small>{e(t["optionnel"])}</small></h4>
      <label class="sia-drop" id="sia-drop"><b id="sia-drop-t">{e(t["deposer"])}</b><span id="sia-drop-a">{e(t["deposer_aide"])}</span><input type="file" id="sia-fichier" accept="image/jpeg,image/png,image/webp" multiple></label>
      <div class="sia-refs" id="sia-refs"></div>
      <p class="sia-aide" id="sia-refs-aide"></p>
    </section>
    <section class="sia-carte"><h4>{e(t["reglages"])}</h4><div id="sia-options"></div></section>
    <section class="sia-carte">
      <div class="sia-estim-l"><span>{e(t["estime"])}</span><b>⚡ <span id="sia-estime">—</span></b></div>
      <button type="button" class="sia-generer" id="sia-generer">{_SVG_ETINCELLE}<span id="sia-generer-txt">{e(t["generer"])}</span></button>
      <p class="sia-raccourci">{e(t["raccourci"])}</p>
      <div class="sia-alerte" id="sia-alerte"></div>
    </section>
  </aside>
  <main>
    <section class="sia-carte"><div class="sia-carte-tete"><h4>{e(t["prompt"])} <span style="color:var(--sia-ko)">*</span></h4><span class="sia-compteur" id="sia-compteur">0 / —</span></div>
      <textarea class="sia-textarea" id="sia-prompt" placeholder="{e(t["prompt_ph_video"])}"></textarea></section>
    <section class="sia-carte"><div class="sia-carte-tete"><h4>{e(t["recents"])}</h4><button type="button" class="sia-lien" id="sia-actualiser">{e(t["actualiser"])}</button></div>
      <div class="sia-grille" id="sia-recents"><div class="sia-vide">{e(t["vide_recents"])}</div></div></section>
  </main>
</div>
<div id="sia-vue-historique" hidden>
  <section class="sia-carte"><div class="sia-hist-tete"><h4 style="margin:0">{e(t["historique"])}</h4><button type="button" class="sia-lien" id="sia-actualiser2">{e(t["actualiser"])}</button></div>
    <div class="sia-grille" id="sia-historique"><div class="sia-vide">{e(t["vide_hist"])}</div></div></section>
</div>
<div class="sia-modal" id="sia-modal"><button type="button" class="sia-fermer" id="sia-modal-fermer" title="{e(t["fermer"])}">×</button><div class="sia-modal-boite"><div class="sia-modal-media" id="sia-modal-media"></div><div class="sia-modal-cote" id="sia-modal-cote"></div></div></div>
</div>
<script>window.SIA_CONF = {json.dumps(conf, ensure_ascii=False).replace("</", "<\\/")};</script>
<script src="/studio-ia/app.js?v={version}" defer></script>
"""


# -------------------------------------------------------------- routes --

def _sha_worker() -> str:
    import hashlib
    p = BOT_DIR / "visage_worker.py"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def register(app, deps: Dict[str, Any]) -> None:
    """Branche les routes. `deps` : is_auth (obligatoire), is_admin,
    onglets (-> set des onglets du rôle, ou None = accès complet),
    utilisateur (-> nom de session), langue (-> 'fr'|'en')."""
    from flask import jsonify, request, send_file

    is_auth = deps["is_auth"]
    is_admin = deps.get("is_admin") or (lambda: True)
    onglets = deps.get("onglets") or (lambda: None)
    utilisateur = deps.get("utilisateur") or (lambda: "admin")
    langue = deps.get("langue") or (lambda: "fr")

    def _refus():
        """None si la personne peut ouvrir le Studio, sinon la réponse."""
        if not is_auth():
            return jsonify({"ok": False, "erreur": "unauth"}), 401
        try:
            a = onglets()
        except Exception:
            a = None
        if a is not None and "studioia" not in a:
            return jsonify({"ok": False, "erreur": "forbidden"}), 403
        return None

    def _admin() -> bool:
        try:
            return bool(is_admin())
        except Exception:
            return False

    def _json(d, code=200):
        r = jsonify(d)
        r.status_code = code
        r.headers["Cache-Control"] = "no-store"
        return r

    def _site() -> str:
        try:
            return (request.url_root or "https://youl4b.com").rstrip("/")
        except Exception:
            return "https://youl4b.com"

    # -- la machine qui fait les visages (visage_worker.py) : jeton, pas de
    # session. Le garde d'écriture laisse passer l'anonyme (chaque handler
    # décide) ; ici c'est le jeton qui décide.
    def _machine_refus():
        if jeton_machine_ok(request.headers.get("X-Visage-Jeton") or request.args.get("jeton") or ""):
            return None
        return _json({"ok": False, "erreur": "jeton"}, 401)

    @app.route("/studio-ia/visage/travail")
    def studio_ia_visage_travail():
        r = _machine_refus()
        if r:
            return r
        nom = (request.args.get("nom") or "machine")[:40]
        t = prendre_travail(nom)
        voir_machine(nom, "occupee" if t else "libre", t["id"] if t else "")
        if _ouvertes():
            _assurer_suivi()
        try:
            sha = _sha_worker()
        except OSError:
            sha = ""
        return _json({"ok": True, "tache": t, "worker_sha": sha})

    @app.route("/studio-ia/visage/entree/<tid>/<int:n>")
    def studio_ia_visage_entree(tid, n):
        r = _machine_refus()
        if r:
            return r
        if not _ID_OK.match(str(tid)):
            return "", 404
        t = next((x for x in _charger() if x.get("id") == tid), None)
        refs = (t or {}).get("references") or []
        if not t or t.get("type") != "visage" or n < 0 or n >= len(refs):
            return "", 404
        meta = _reference(refs[n].get("id") or "")
        if not meta:
            return "", 404
        return send_file(str(meta["chemin"]), mimetype=meta.get("mime"), conditional=True)

    @app.route("/studio-ia/visage/avancement/<tid>", methods=["POST"])
    def studio_ia_visage_avancement(tid):
        r = _machine_refus()
        if r:
            return r
        d = request.get_json(silent=True) or {}
        nom = str(d.get("machine") or "machine")[:40]
        voir_machine(nom, "occupee", tid)
        t = avancement_visage(tid, d.get("progression"), str(d.get("etape") or ""), nom) if _ID_OK.match(str(tid)) else None
        return _json({"ok": bool(t), "etat": (t or {}).get("etat")}, 200 if t else 404)

    @app.route("/studio-ia/visage/resultat/<tid>", methods=["POST"])
    def studio_ia_visage_resultat(tid):
        r = _machine_refus()
        if r:
            return r
        f = request.files.get("fichier")
        if f is None or not _ID_OK.match(str(tid)):
            return _json({"ok": False, "erreur": "fichier"}, 400)
        octets = f.read(TAILLE_MAX_RESULTAT + 1)
        if not octets or len(octets) > TAILLE_MAX_RESULTAT:
            return _json({"ok": False, "erreur": "taille"}, 400)
        t = resultat_visage(tid, octets, f.filename or "sortie.mp4")
        voir_machine(str(request.form.get("machine") or "machine")[:40], "libre", "")
        return _json({"ok": bool(t)}, 200 if t else 404)

    @app.route("/studio-ia/visage/echec/<tid>", methods=["POST"])
    def studio_ia_visage_echec(tid):
        r = _machine_refus()
        if r:
            return r
        d = request.get_json(silent=True) or {}
        voir_machine(str(d.get("machine") or "machine")[:40], "libre", "")
        t = echec_visage(tid, str(d.get("erreur") or "")) if _ID_OK.match(str(tid)) else None
        return _json({"ok": bool(t)}, 200 if t else 404)

    @app.route("/studio-ia/visage/worker.py")
    def studio_ia_visage_worker():
        """Le programme de la machine, tel qu'il est dans git : la machine
        se met à jour seule quand il change (worker_sha)."""
        r = _machine_refus()
        if r:
            return r
        p = BOT_DIR / "visage_worker.py"
        if not p.exists():
            return "", 404
        return send_file(str(p), mimetype="text/x-python", conditional=True)

    @app.route("/studio-ia/app.js")
    def studio_ia_app_js():
        # Le .js est LOAD-BEARING : le garde de lecture exempte les assets
        # par extension (voir parc_web).
        if not is_auth():
            return "", 401
        p = BOT_DIR / "studio_ia_app.js"
        if not p.exists():
            return "// studio_ia_app.js manquant", 404
        return send_file(str(p), mimetype="text/javascript", conditional=True)

    @app.route("/studio-ia/etat")
    def studio_ia_etat():
        r = _refus()
        if r:
            return r
        s = solde(force=request.args.get("force") == "1")
        src = kie_ai.source_cle()
        return _json({"ok": True, "cle": kie_ai.cle_presente(), "credits": s["credits"],
                      "erreur_credits": s["erreur"], "admin": _admin(),
                      "cle_fin": src["fin"], "cle_source": src["source"],
                      "taches": taches_visibles(utilisateur(), _admin(), langue()),
                      "visage": etat_visage(langue(), _admin(), _site())})

    @app.route("/studio-ia/cle", methods=["POST"])
    def studio_ia_cle():
        """La clé collée par un admin. Essayée chez Kie avant d'être gardée ;
        jamais renvoyée (seulement sa fin). Admin seul : le garde d'écriture
        du site la refuse aussi aux rôles restreints (_ADMIN_ONLY_WRITE)."""
        r = _refus()
        if r:
            return r
        if not _admin():
            return _json({"ok": False, "erreur": "forbidden"}, 403)
        corps = request.get_json(silent=True) or {}
        ok, msg, credits_ = kie_ai.enregistrer_cle(str(corps.get("cle") or ""), utilisateur(), langue())
        if not ok:
            return _json({"ok": False, "erreur": msg}, 400)
        _oublier_solde()
        return _json({"ok": True, "message": msg, "fin": kie_ai.source_cle()["fin"], "credits": credits_})

    @app.route("/studio-ia/taches")
    def studio_ia_taches():
        r = _refus()
        if r:
            return r
        if _ouvertes():
            _assurer_suivi()
        return _json({"ok": True, "taches": taches_visibles(utilisateur(), _admin(), langue()),
                      "visage": etat_visage(langue(), _admin(), _site())})

    @app.route("/studio-ia/estimer")
    def studio_ia_estimer():
        r = _refus()
        if r:
            return r
        cle_m = request.args.get("modele") or ""
        opts = {k[2:]: v for k, v in request.args.items() if k.startswith("o_")}
        try:
            nb = int(request.args.get("nb_refs") or 0)
        except ValueError:
            nb = 0
        try:
            duree = float(request.args.get("duree") or 0)
        except ValueError:
            duree = 0.0
        if cle_m == "visage":
            return _json({"ok": True, "credits": 0})
        if not kie_ai.modele(cle_m):
            return _json({"ok": False, "erreur": "modele"}, 400)
        return _json({"ok": True, "credits": kie_ai.estimer(cle_m, opts, nb, duree_video=duree)})

    @app.route("/studio-ia/generer", methods=["POST"])
    def studio_ia_generer():
        r = _refus()
        if r:
            return r
        d = request.get_json(silent=True) or {}
        refs = [str(x) for x in (d.get("references") or []) if isinstance(x, (str, int))][:10]
        res = lancer(utilisateur(), str(d.get("modele") or ""), str(d.get("prompt") or ""),
                     d.get("options") or {}, refs, langue())
        return _json(res, 200 if res.get("ok") else 400)

    @app.route("/studio-ia/reference", methods=["POST"])
    def studio_ia_reference():
        r = _refus()
        if r:
            return r
        f = request.files.get("fichier")
        if f is None:
            return _json({"ok": False, "erreur": _t(langue())["ref_type"]}, 400)
        octets = f.read(kie_ai.TAILLE_MAX_VIDEO + 1)
        try:
            ref = deposer_reference(utilisateur(), octets, f.filename or "image",
                                    f.mimetype or "", langue())
        except ValueError as e:
            return _json({"ok": False, "erreur": str(e)}, 400)
        except kie_ai.ErreurKie as e:
            print(f"[studio-ia] dépôt de référence refusé ({e.code}) : {e}", flush=True)
            return _json({"ok": False, "erreur": kie_ai.message_pour(e.code, str(e), langue())
                          if e.code in (401, 402, 429, "reseau", "sans_cle") else str(e)}, 502)
        return _json({"ok": True, "reference": ref})

    @app.route("/studio-ia/reference/<rid>")
    def studio_ia_reference_lire(rid):
        r = _refus()
        if r:
            return r
        meta = _reference(rid)
        if not meta:
            return "", 404
        return send_file(str(meta["chemin"]), mimetype=meta.get("mime"), conditional=True)

    @app.route("/studio-ia/fichier/<tid>/<int:n>")
    def studio_ia_fichier(tid, n):
        r = _refus()
        if r:
            return r
        if not _ID_OK.match(str(tid)):
            return "", 404
        t = next((x for x in _charger() if x.get("id") == tid), None)
        if not t or (not _admin() and t.get("utilisateur") != utilisateur()):
            return "", 404
        fichiers = t.get("fichiers") or []
        if n < 0 or n >= len(fichiers):
            return "", 404
        f = fichiers[n]
        if request.args.get("vignette") == "1" and f.get("vignette"):
            p = _dossier_sorties() / f["vignette"]
            return send_file(str(p), mimetype="image/jpeg", conditional=True) if p.exists() else ("", 404)
        p = _dossier_sorties() / f["nom"]
        if not p.exists():
            return "", 404
        if request.args.get("dl") == "1":
            nom_dl = f"studio-ia_{t.get('modele', 'ia')}_{tid}{p.suffix}"
            return send_file(str(p), mimetype=f.get("mime"), as_attachment=True,
                             download_name=nom_dl, conditional=True)
        return send_file(str(p), mimetype=f.get("mime"), conditional=True)

    @app.route("/studio-ia/tache/<tid>/masquer", methods=["POST"])
    def studio_ia_masquer(tid):
        r = _refus()
        if r:
            return r
        if not _ID_OK.match(str(tid)):
            return _json({"ok": False, "erreur": "id"}, 404)
        t = next((x for x in _charger() if x.get("id") == tid), None)
        if not t or (not _admin() and t.get("utilisateur") != utilisateur()):
            return _json({"ok": False, "erreur": "introuvable"}, 404)
        _maj(tid, masque=True)
        return _json({"ok": True})

    @app.route("/studio-ia/tache/<tid>/verifier", methods=["POST"])
    def studio_ia_verifier(tid):
        r = _refus()
        if r:
            return r
        if not _ID_OK.match(str(tid)):
            return _json({"ok": False, "erreur": "id"}, 404)
        t = next((x for x in _charger() if x.get("id") == tid), None)
        if not t or (not _admin() and t.get("utilisateur") != utilisateur()):
            return _json({"ok": False, "erreur": "introuvable"}, 404)
        try:
            t2 = verifier(tid) or t
        except kie_ai.ErreurKie as e:
            return _json({"ok": False, "erreur": str(e)}, 502)
        return _json({"ok": True, "tache": _publique(t2, langue())})

    # Après un redémarrage, les tâches ouvertes reprennent leur suivi.
    try:
        _assurer_suivi()
    except Exception as e:
        print(f"[studio-ia] reprise du suivi : {type(e).__name__}: {e}", flush=True)
