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
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
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
        "ref_type": "Format refusé : JPG, PNG ou WebP seulement.",
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
        "ref_type": "Rejected format: JPG, PNG or WebP only.",
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
    },
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

def deposer_reference(utilisateur: str, octets: bytes, nom: str, mime: str,
                      langue: str = "fr") -> Dict[str, Any]:
    """Garde l'image en local (aperçu de l'historique) et chez Kie (24 h,
    le temps que la tâche la lise). Lève ValueError avec le message à
    montrer si le fichier ne convient pas."""
    t = _t(langue)
    mime = (mime or "").split(";")[0].strip().lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in kie_ai.TYPES_IMAGE:
        raise ValueError(t["ref_type"])
    if len(octets) > kie_ai.TAILLE_MAX_REF:
        raise ValueError(t["ref_trop_grosse"].format(mo=round(len(octets) / 1e6, 1)))
    if not octets:
        raise ValueError(t["ref_type"])
    rid = uuid.uuid4().hex[:16]
    ext = _EXT_PAR_MIME.get(mime, ".bin")
    _dossier_refs().mkdir(parents=True, exist_ok=True)
    local = _dossier_refs() / (rid + ext)
    local.write_bytes(octets)
    url = kie_ai.televerser(octets, (nom or "image") + ("" if (nom or "").lower().endswith(ext) else ext), mime)
    meta = {"id": rid, "nom": (nom or "image")[:120], "mime": mime, "taille": len(octets),
            "url": url, "utilisateur": utilisateur, "t": int(time.time())}
    safe_json.write(_dossier_refs() / (rid + ".json"), meta, backup=False)
    return {"id": rid, "nom": meta["nom"], "mime": mime, "taille": len(octets),
            "url": url, "apercu": "/studio-ia/reference/" + rid}


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

def _resume_options(m: Dict[str, Any], o: Dict[str, Any]) -> str:
    morceaux = []
    for k in ("mode", "resolution", "quality", "size"):
        if o.get(k):
            morceaux.append(str(o[k]))
    if o.get("aspect_ratio"):
        morceaux.append(str(o["aspect_ratio"]))
    if o.get("duration"):
        morceaux.append(f"{o['duration']} s")
    if o.get("sound") or o.get("generate_audio") or o.get("audio"):
        morceaux.append("audio")
    return " · ".join(morceaux)


def lancer(utilisateur: str, cle_modele: str, prompt: str, options: Any,
           refs: List[str], langue: str = "fr") -> Dict[str, Any]:
    """Vérifie, estime, lance chez Kie et enregistre la tâche. Renvoie
    {ok: True, tache} ou {ok: False, erreur, code}. Ne lève pas."""
    t = _t(langue)
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
        return {"ok": False, "erreur": t["ref_type_kling"], "code": "ref_type"}
    nb_ouvertes = sum(1 for x in _ouvertes() if x.get("utilisateur") == utilisateur)
    if nb_ouvertes >= MAX_OUVERTES:
        return {"ok": False, "erreur": t["trop_en_cours"].format(n=MAX_OUVERTES), "code": "trop"}
    o = kie_ai.normaliser(cle_modele, options)
    besoin = kie_ai.estimer(cle_modele, o, len(refs_meta))
    s = solde()
    if s["credits"] is not None and besoin > s["credits"]:
        return {"ok": False, "code": "credits",
                "erreur": t["credits_insuffisants"].format(reste=_nb(s["credits"]), besoin=_nb(besoin)),
                "credits": s["credits"]}
    modele_api, entree = kie_ai.entree_api(cle_modele, prompt, o, [r["url"] for r in refs_meta])
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
        "prompt": (prompt or "").strip(), "options": o, "resume": _resume_options(m, o),
        "references": [{"id": r["id"], "nom": r.get("nom", "")} for r in refs_meta],
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
        "references": [{"apercu": "/studio-ia/reference/" + r["id"], "nom": r.get("nom", "")}
                       for r in (t.get("references") or []) if _ID_OK.match(str(r.get("id") or ""))],
        "derniere_erreur": t.get("derniere_erreur", ""),
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
#sia-root .sia-ref img{width:100%;height:100%;object-fit:cover;display:block}
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
_SVG_PHOTO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>'
_SVG_ETINCELLE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 17l.7 1.8 1.8.7-1.8.7L19 22l-.7-1.8-1.8-.7 1.8-.7z"/></svg>'


def rendu_html(langue: str = "fr", admin: bool = False) -> str:
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
        "modeles": kie_ai.registre_public(langue), "max_ouvertes": MAX_OUVERTES,
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
</div>
<div class="sia-corps" id="sia-vue-creer">
  <aside>
    <section class="sia-carte"><h4>{e(t["modele"])}</h4><div id="sia-modeles"></div></section>
    <section class="sia-carte"><h4>{e(t["references"])} <small>{e(t["optionnel"])}</small></h4>
      <label class="sia-drop" id="sia-drop"><b>{e(t["deposer"])}</b>{e(t["deposer_aide"])}<input type="file" id="sia-fichier" accept="image/jpeg,image/png,image/webp" multiple></label>
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
                      "taches": taches_visibles(utilisateur(), _admin(), langue())})

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
        return _json({"ok": True, "taches": taches_visibles(utilisateur(), _admin(), langue())})

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
        if not kie_ai.modele(cle_m):
            return _json({"ok": False, "erreur": "modele"}, 400)
        return _json({"ok": True, "credits": kie_ai.estimer(cle_m, opts, nb)})

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
        octets = f.read(kie_ai.TAILLE_MAX_REF + 1)
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
