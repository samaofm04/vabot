# -*- coding: utf-8 -*-
"""Analyses GRATUITES : lire un texte sur une image, couper un template.

Le propriétaire veut ces tâches gratuites, même plus lentes (25/09/2026).
Rien ici n'appelle d'API payante :

* le TEXTE se lit par Gemini, dans son offre gratuite (il recopie aussi les
  emojis), et par Tesseract, local, quand Gemini ne répond pas ;
* la COUPURE d'un template se lit dans les changements de plan de ffmpeg ;
* les VISAGES (OpenCV, local) servent à dire quand une coupure est douteuse.

Tout ce qui dépend d'un programme absent (Tesseract, OpenCV) le dit au lieu
de répondre « rien trouvé » : une vidéo qu'on n'a pas su lire n'est pas une
vidéo sans texte.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ICI = Path(__file__).resolve().parent
_NICE = ["nice", "-n", "10"] if shutil.which("nice") else []

# --------------------------------------------------------------------- Gemini

CONSIGNE_CAPTURE = (
    "C'est une capture d'écran d'une vidéo TikTok ou Instagram. Recopie "
    "UNIQUEMENT le texte incrusté sur la vidéo (la caption / l'accroche), "
    "exactement, emojis compris, en gardant les retours à la ligne. "
    "N'inclus PAS l'interface : pseudo, description en bas, musique, heure, "
    "« Pour toi », boutons, compteurs de likes. S'il n'y a aucun texte "
    "incrusté, réponds exactement AUCUN. Réponds par le texte seul."
)

CONSIGNE_TEMPLATE = (
    "Image extraite d'une vidéo verticale. Recopie le texte incrusté au "
    "montage (la caption), exactement, emojis compris, retours à la ligne "
    "gardés. Ignore le texte qui appartient au décor (t-shirt, enseigne, "
    "écran filmé). Réponds UNIQUEMENT par un objet JSON : "
    '{"texte": "...", "x": centre horizontal du texte entre 0 et 1, '
    '"y": centre vertical du texte entre 0 et 1}. '
    'Sans texte incrusté : {"texte": ""}.'
)


def cle_gemini() -> str:
    """La clé Gemini, lue au même endroit que la veille Telegram."""
    try:
        import tg_router as _tg
        return _tg._env_gemini_key() or ""
    except Exception:
        return (os.environ.get("GEMINI_API_KEY") or "").strip()


def gemini_texte(image: bytes, consigne: str, mime: str = "image/jpeg",
                 timeout: int = 45) -> Tuple[str, str]:
    """(texte, erreur). Passe par tg_router._gemini_generate : c'est LA seule
    définition des modèles Gemini du projet (alias stable, repli sur 404, 429
    et 503). Une seconde liste ici aurait fini par viser un modèle retiré
    pendant que l'autre était à jour."""
    cle = cle_gemini()
    if not cle:
        return "", "clé Gemini absente"
    try:
        import tg_router as _tg
    except Exception as err:
        return "", f"Gemini indisponible : {str(err)[:120]}"
    parts = [{"inline_data": {"mime_type": mime,
                              "data": base64.b64encode(image).decode()}},
             {"text": consigne}]
    try:
        data, _modele = _tg._gemini_generate(parts, cle, timeout=timeout)
    except Exception as err:
        return "", str(err)[:300]
    try:
        texte = "".join(p.get("text", "") for p in
                        data["candidates"][0]["content"]["parts"]).strip()
    except Exception:
        return "", "réponse Gemini vide (contenu bloqué ?)"
    return texte, ""


def _json_souple(texte: str) -> dict:
    """Le premier objet JSON d'une réponse, même entouré de ``` ou de texte."""
    try:
        return json.loads(texte[texte.index("{"):texte.rindex("}") + 1])
    except Exception:
        return {}


# ------------------------------------------------------------------ Tesseract

#: Pixels plus clairs que ce seuil = texte blanc (mesuré sur les brutes :
#: c'est ce qui rend lisible le texte TikTok blanc posé sur une vidéo).
SEUIL_BLANC = 225
CONFIANCE_MIN = 55


def _ocr_tsv(image: Path) -> List[dict]:
    """Les mots lus, avec leur boîte, en coordonnées de l'image."""
    r = subprocess.run(
        _NICE + ["tesseract", str(image), "-", "-l", "eng+fra", "--psm", "11",
                 "-c", "tessedit_do_invert=0", "tsv"],
        capture_output=True, text=True, timeout=90)
    mots = []
    for ligne in r.stdout.splitlines()[1:]:
        c = ligne.split("\t")
        if len(c) != 12 or not c[11].strip():
            continue
        try:
            conf = float(c[10])
            x, y, w, h = (int(c[6]), int(c[7]), int(c[8]), int(c[9]))
        except ValueError:
            continue
        if conf < CONFIANCE_MIN:
            continue
        mots.append({"t": c[11].strip(), "conf": conf, "x": x, "y": y, "w": w, "h": h})
    return mots


def _en_lignes(mots: List[dict]) -> List[dict]:
    """Regroupe les mots en lignes par hauteur (le --psm 11 les rend épars),
    puis coupe une ligne là où l'écart entre deux mots dépasse ~2,5 hauteurs :
    sans ça, les compteurs de la colonne de droite (likes, partages) se
    collaient à la caption et passaient le filtre d'interface avec elle."""
    lignes: List[dict] = []
    for m in sorted(mots, key=lambda m: (m["y"] + m["h"] / 2, m["x"])):
        cy = m["y"] + m["h"] / 2
        for l in lignes:
            if abs(l["cy"] - cy) <= max(l["h"], m["h"]) * 0.6:
                l["mots"].append(m)
                l["h"] = max(l["h"], m["h"])
                break
        else:
            lignes.append({"cy": cy, "h": m["h"], "mots": [m]})
    morceaux = []
    for l in sorted(lignes, key=lambda l: l["cy"]):
        ms = sorted(l["mots"], key=lambda m: m["x"])
        courant = [ms[0]]
        for m in ms[1:]:
            fin = courant[-1]["x"] + courant[-1]["w"]
            if m["x"] - fin > 2.5 * max(l["h"], 1):
                morceaux.append(courant)
                courant = [m]
            else:
                courant.append(m)
        morceaux.append(courant)
    out = []
    for ms in morceaux:
        x0 = min(m["x"] for m in ms); y0 = min(m["y"] for m in ms)
        x1 = max(m["x"] + m["w"] for m in ms); y1 = max(m["y"] + m["h"] for m in ms)
        out.append({"texte": " ".join(m["t"] for m in ms),
                    "conf": sum(m["conf"] for m in ms) / len(ms),
                    "box": (x0, y0, x1 - x0, y1 - y0),
                    "score": sum(m["conf"] * len(m["t"]) for m in ms)})
    return out


def _preparer(image: Path, dest: Path, blanc: bool, hauteur: int = 1280) -> bool:
    vf = f"scale=-2:{hauteur},format=gray"
    if blanc:
        vf += f",lutyuv=y=if(gt(val\\,{SEUIL_BLANC})\\,0\\,255)"
    r = subprocess.run(_NICE + ["ffmpeg", "-v", "error", "-y", "-i", str(image),
                                "-frames:v", "1", "-vf", vf, str(dest)],
                       capture_output=True, timeout=60)
    return r.returncode == 0 and dest.exists()


def _dimensions(image: Path) -> Tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0",
                        str(image)], capture_output=True, text=True, timeout=30)
    try:
        w, h = r.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:
        return 0, 0


def transcrire_tesseract(image: Path, capture: bool = False) -> dict:
    """Le texte d'une image, par Tesseract, en deux lectures : texte BLANC
    (filtre sur les pixels clairs) et texte FONCÉ (image grise telle quelle,
    pour le noir sur fond blanc). La meilleure l'emporte.

    capture=True : c'est une capture d'écran d'appli. Les lignes tombées
    dans l'interface (barre du haut, description et musique en bas, colonne
    de boutons à droite) sont ÉCARTÉES mais rendues, pour être montrées.

    Rend {texte, conf, box (fractions x,y,w,h), polarite, ecartees, erreur}.
    """
    if not shutil.which("tesseract"):
        return {"texte": "", "erreur": "Tesseract absent du serveur"}
    meilleur = None
    with tempfile.TemporaryDirectory(prefix="ocrtx_") as tmp:
        for blanc in (True, False):
            prep = Path(tmp) / ("b.png" if blanc else "g.png")
            if not _preparer(image, prep, blanc):
                continue
            W, H = _dimensions(prep)
            if not W or not H:
                continue
            gardees, ecartees = [], []
            for l in _en_lignes(_ocr_tsv(prep)):
                x, y, w, h = l["box"]
                cx, cy = (x + w / 2) / W, (y + h / 2) / H
                if len(re.sub(r"[^\w]", "", l["texte"])) < 2:
                    continue
                if capture and (cy < 0.09 or cy > 0.80 or cx > 0.86):
                    ecartees.append(l["texte"])
                    continue
                gardees.append(dict(l, fx=x / W, fy=y / H, fw=w / W, fh=h / H))
            score = sum(l["score"] for l in gardees)
            if meilleur is None or score > meilleur["score"]:
                meilleur = {"score": score, "gardees": gardees, "ecartees": ecartees,
                            "polarite": "blanc" if blanc else "sombre"}
    if not meilleur or not meilleur["gardees"]:
        return {"texte": "", "conf": 0, "box": None, "ecartees":
                (meilleur or {}).get("ecartees", []), "polarite": "", "erreur": ""}
    g = meilleur["gardees"]
    x0 = min(l["fx"] for l in g); y0 = min(l["fy"] for l in g)
    x1 = max(l["fx"] + l["fw"] for l in g); y1 = max(l["fy"] + l["fh"] for l in g)
    return {"texte": "\n".join(l["texte"] for l in g),
            "conf": round(sum(l["conf"] for l in g) / len(g)),
            "box": (round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)),
            # Chaque ligne avec sa boîte (fractions) : l'appelant peut ne
            # garder que celles de la caption pour la placer.
            "lignes": [{"texte": l["texte"], "box": (round(l["fx"], 4), round(l["fy"], 4),
                                                   round(l["fw"], 4), round(l["fh"], 4))}
                       for l in g],
            "ecartees": meilleur["ecartees"], "polarite": meilleur["polarite"],
            "erreur": ""}


def lire_capture(image: Path) -> dict:
    """Le texte incrusté d'une capture d'écran : Gemini d'abord (il lit les
    emojis), Tesseract si Gemini ne répond pas. {texte, source, conf,
    ecartees, erreur}. Ne décide rien : l'écran de relecture tranche."""
    try:
        octets = image.read_bytes()
    except OSError as err:
        return {"texte": "", "source": "", "erreur": str(err)[:120]}
    mime = "image/png" if image.suffix.lower() == ".png" else (
        "image/webp" if image.suffix.lower() == ".webp" else "image/jpeg")
    texte, err_g = gemini_texte(octets, CONSIGNE_CAPTURE, mime=mime)
    if texte and texte.strip().upper() != "AUCUN":
        return {"texte": texte.strip(), "source": "Gemini", "conf": None,
                "ecartees": [], "erreur": ""}
    if texte.strip().upper() == "AUCUN":
        return {"texte": "", "source": "Gemini", "conf": None, "ecartees": [],
                "erreur": "aucun texte incrusté vu"}
    t = transcrire_tesseract(image, capture=True)
    t["source"] = "Tesseract"
    if err_g and not t.get("erreur"):
        # Gemini est tombé : on le dit, sinon une lecture moins bonne passe
        # pour la lecture normale.
        t["note"] = f"Gemini indisponible ({err_g}) — lu par Tesseract, sans emojis"
    return t


# ----------------------------------------------------------- coupe du template

#: La coupure entre la partie 1 (accroche : on garde la caption, on pose la
#: brute) et la partie 2 (gardée telle quelle). Mesuré sur les 28 templates
#: distincts validés du VPS : « premier changement de plan de score ≥ 0,2
#: après 1,5 s » retrouve la coupure 26 fois sur 28 (±0,05 s) ; stable de
#: 0,5 à 2 s de délai, moins bon avec un seuil de 0,5. Réserve : 26 de ces
#: coupures venaient de l'ancienne analyse, validées telles quelles.
SEUIL_PLAN = 0.2
DELAI_MIN = 1.5


def choisir_coupe(scenes: List[Tuple[float, float]], duree: float) -> Tuple[float, str, List[float]]:
    """(coupe, raison, candidats). Sans candidat : toute la vidéo (pas de
    partie 2), comme l'a fait le propriétaire sur ses templates sans plan."""
    cand = [t for t, s in scenes if s >= SEUIL_PLAN and 0.3 <= t <= duree - 0.2]
    for t in cand:
        if t >= DELAI_MIN:
            sc = next(s for tt, s in scenes if tt == t)
            return round(t, 3), f"changement de plan à {t:.2f} s (score {sc:.2f})", cand
    return round(max(0.0, duree - 0.05), 3), "aucun changement de plan net : vidéo entière", cand


def visages(video: Path, jusqua: float, fps: int = 4) -> Optional[List[Tuple[float, int]]]:
    """[(seconde, 1 si un visage est vu)] — None si OpenCV est absent.

    Signal donné par le propriétaire : la partie 1 montre presque toujours
    UNE personne, la partie 2 est un montage générique. Mesuré sur les 28
    templates : visage sur ~75 % des images avant la coupure, ~0 après
    (24 sur 28). Il ne place pas la coupure mieux que les plans ; il dit
    quand la coupure proposée est douteuse."""
    try:
        import cv2
    except Exception:
        return None
    if not hasattr(cv2, "CascadeClassifier"):
        return None            # OpenCV 5 a retiré ces détecteurs
    face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    profil = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    out = []
    with tempfile.TemporaryDirectory(prefix="vis_") as tmp:
        subprocess.run(_NICE + ["ffmpeg", "-v", "error", "-t", f"{max(0.5, jusqua):.2f}",
                                "-i", str(video), "-vf", f"fps={fps},scale=-2:480",
                                f"{tmp}/f%04d.jpg"], capture_output=True, timeout=180)
        for i, f in enumerate(sorted(os.listdir(tmp))):
            img = cv2.imread(os.path.join(tmp, f))
            if img is None:
                continue
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            n = len(face.detectMultiScale(g, 1.15, 5, minSize=(40, 40))) or \
                len(profil.detectMultiScale(g, 1.15, 5, minSize=(40, 40)))
            out.append(((i + 0.5) / fps, 1 if n else 0))
    return out


def _taux(vis, a: float, b: float) -> Optional[float]:
    xs = [x for t, x in (vis or []) if a <= t < b]
    return sum(xs) / len(xs) if xs else None


def raisons_de_verifier(coupe: float, candidats: List[float], duree: float,
                        vis, caption_lue: bool,
                        scenes: Optional[List[Tuple[float, float]]] = None) -> Tuple[str, List[str]]:
    """(priorite, raisons). Tout est « à vérifier » de toute façon ; la
    priorité dit par où commencer."""
    haute, raisons = [], []
    tot = [t for t in candidats if t < DELAI_MIN]
    if coupe >= duree - 0.2 and tot:
        # Un plan net AVANT 1,5 s, écarté par la règle : l'accroche est
        # peut-être très courte. Le taire donnait toute la vidéo en « normale ».
        haute.append(f"changement de plan très tôt ({tot[0]:.2f} s) ignoré : "
                     "accroche très courte ?")
    elif not candidats:
        haute.append("aucun changement de plan : toute la vidéo est gardée comme partie 1")
    apres = [t for t in candidats if coupe < t <= coupe + 1.2]
    if apres:
        haute.append(f"un 2e changement de plan juste après ({apres[0]:.2f} s) : "
                     "deux plans d'accroche ?")
    if vis is not None and coupe < duree - 0.2:
        av, ap = _taux(vis, 0, coupe), _taux(vis, coupe, coupe + 3)
        if ap is not None and ap > 0.3:
            haute.append(f"une personne est encore visible après la coupure ({ap:.0%} des images)")
        if av is not None and av < 0.3:
            haute.append("aucune personne vue avant la coupure")
    if not caption_lue:
        raisons.append("caption de la partie 1 non lue")
    if vis is None:
        # OpenCV absent : la vérification des visages n'a pas eu lieu. Le
        # taire faisait passer une coupure douteuse en priorité normale.
        raisons.append("visages non vérifiés (OpenCV absent)")
    return ("haute" if haute else "normale"), haute + raisons
