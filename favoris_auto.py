# -*- coding: utf-8 -*-
"""Favoris des bangers : ce qui a fait un banger est PROPOSE en ⭐, a verifier.

LA DEMANDE (27/09/2026)
    Les reels qui font des vues deviennent des bangers (bangers.py,
    all_banger.py : la video est archivee dans data/bangers/). Le proprietaire
    veut « decortiquer » chaque banger et etoiler ce qui a marche :
      - la BRUTE d'origine -> ⭐ sur l'identite (fav_brutes.json) ;
      - le TEXTE incruste -> la caption ⭐ dans la bibliotheque de l'identite,
        et recopiee ⭐ dans ses reserves liees (Blonde, Brune...) ;
      - le TEMPLATE (montage, Flash, Trash) -> ⭐ sur la copie de l'identite
        (⭐ + marque Flash/Trash = Flash/Trash Banger).
    Exemple reel : DdtYlgRgOGg (Jorel, 64 498 vues) -> brute
    ibenhaastrup/brutes/tt_7637556520955251990.mp4 ⭐, caption « 7 texts that
    make her want you baddd😱 » ⭐ dans ibenhaastrup puis dans blonde.

PLUS AUCUNE ETOILE AUTOMATIQUE (demande du proprietaire, 27/09/2026 apres-midi)
    « tu peux pas mettre automatiquement dans banger stp, juste tu me mets une
    notif a verifier [...] en mode je dois check, et pour la caption aussi ».
    L'analyse est la meme (seuils, refus memorises, variantes, registres) ;
    ce qui change, c'est QUI pose l'etoile. Tout ce qu'elle trouve, « sur »
    compris, devient une proposition de la liste « À vérifier » (niveau
    « sûr » ou « probable ») ; le bouton Valider pose exactement ce que la
    pose automatique posait (brute ; caption + reserves liees ; template et
    ses copies), Refuser memorise le refus. Le centre de notifications du site
    (⚠ du selecteur de marche) compte ces propositions.

GRATUIT, ET OU CA TOURNE
    Aucun appel reseau. ffmpeg (images reduites a 17x16) et Tesseract
    (analyse_gratuite.transcrire_tesseract, JAMAIS lire_capture ni
    /captions/ocr, qui passent d'abord par Gemini) tournent sur le VPS, a
    nice 19, dans un SOUS-PROCESSUS (`python favoris_auto.py analyser ...`) :
    plusieurs secondes de calcul Python par banger ne doivent pas prendre le
    verrou de l'interpreteur du bot et du site. Seule la pose des etoiles
    (quelques ecritures JSON, au clic sur Valider) se fait dans le processus
    principal, par les fonctions du site qu'on nous branche (brancher()).
    Aucun HikerAPI, aucun Apify, aucune API d'IA : ce module n'importe rien
    qui parle au reseau.

DEUX CHEMINS POUR RETROUVER LA RECETTE
    1. LA LIVRAISON (le plus fiable). Chaque video livree par le bot est
       notee avec sa recette dans data/livraisons/AAAA-MM.jsonl
       (noter_livraison), puis son empreinte est calculee en tache de fond.
       Un banger dont l'image colle a une livraison a sa recette EXACTE --
       une hypothese : chaque ingredient (brute, template, caption incrustee)
       est encore retrouve a l'image ou au texte avant d'etre etoile
       (_depuis_recette).
    2. LE RATTRAPAGE (bangers d'avant, ou livraison introuvable). On compare
       l'image du banger a toutes les brutes et a tous les templates du vault,
       et on lit son texte par Tesseract. L'identite n'est ecrite nulle part
       (tous les bangers valent « jessye », l'identite des comptes geres) :
       elle se DEDUIT de la brute retrouvee.

SEUILS : calibres le 27/09/2026 sur les 152 bangers du VPS, en lecture seule
    (scratchpad/favoris_explo.md, §6). dHash 256 bits sur des images 17x16.
    Ils ne decident plus d'une etoile, seulement du NIVEAU de la proposition :
    « sûr » (ce qui etait pose d'office avant) ou « probable » (l'ancien
    « À confirmer »), avec la raison et le score.

RIEN N'EST ECARTE EN SILENCE
    Chaque banger traite a une ligne dans le registre (data/favoris_auto.json)
    avec ce qui a ete decide et pourquoi ; ceux qu'on ne traite pas (hors
    equipe, sans video) sont comptes et montres. Une proposition refusee, ou
    une etoile validee puis retiree a la main, ne revient pas : le refus est
    memorise (variantes du texte comprises).
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import safe_json

# ----------------------------------------------------------------- chemins --
#
# RELATIFS AU DOSSIER COURANT, comme web_upload.DATA_DIR et cogs/user.DATA_DIR :
# le bot et le site tournent depuis le depot, et un test qui se place dans un
# dossier temporaire ne peut PAS ecrire dans les vraies donnees par megarde.
# Tout est relu a chaque appel (fonctions, pas constantes figees) : rediriger
# DATA suffit a deplacer tout le module.

DATA = Path("data")


def _data() -> Path:
    return Path(DATA)


def fichier_registre() -> Path:
    return _data() / "favoris_auto.json"


def dossier_livraisons() -> Path:
    return _data() / "livraisons"


def dossier_attente() -> Path:
    """Copies (liens durs) des videos livrees, le temps de calculer leur
    empreinte : la plupart sont effacees juste apres l'envoi (dossiers
    temporaires, reserve soldee)."""
    return dossier_livraisons() / "a_empreinter"


def dossier_index() -> Path:
    return _data() / "empreintes_denses"


def dossier_identites() -> Path:
    return _data() / "identities"


# ------------------------------------------------------------------ seuils --
#
# Les chiffres ci-dessous viennent de la calibration (favoris_explo.md §5-6).
# Les changer sans refaire la calibration, c'est classer au hasard (« sûr » /
# « probable » : l'ordre dans lequel le proprietaire verifie).

L, H = 17, 16                  # 16 x 16 differences = 256 bits (empreintes_video)
RELIEF_MIN = 6.0               # image unie (fondu, noir) : ne dit rien
FPS_BANGER = 10                # le banger : 10 images/s ...
SECONDES_BANGER = 12.0         # ... sur ses 12 premieres secondes
#: Index des brutes : 2 images/s sur toute la duree (plafond 120 s). La
#: preselection n'a pas besoin de plus ; la verification relit les candidates
#: a 10 images/s. Les montages prennent une FENETRE AU HASARD dans la brute
#: (noctus_web.assemble_brute_template) : lire seulement le debut, comme
#: empreintes_video, rate les brutes longues.
FPS_INDEX = {"brutes": 2, "templates": 10}
SECONDES_INDEX = {"brutes": 120.0, "templates": 20.0}
SECONDES_DENSE = 120.0
INDEX_VERSION = 1

#: Template (partie 2 du montage, apres le trait de coupe). Observe : les bons
#: entre 4 et 24, les autres >= 76 (84 sur 85 au-dessus de 96).
TPL_SUR, TPL_MIN_IMAGES, TPL_A_CONFIRMER = 30, 15, 60

#: Brute (mediane au meilleur decalage ; « 2e » = meilleur candidat qui n'est
#: pas une jumelle). Observe : brute seule 4-30 (ecart >= 51), brute + caption
#: 13-34 (>= 33), montage 8-44 (>= 25) ; sosies (autre prise, meme tenue)
#: 30 a 78, ecartes par l'ecart au 2e.
BRUTE_SUR = ((25, 15), (45, 35))      # (mediane max, ecart au 2e min)
BRUTE_A_CONFIRMER = 55
JUMELLES_MAX = 25                     # deux brutes « identiques » (doublon perceptif)
#: Pas mesure par la calibration, ajoute par prudence : moins d'images
#: comparees que ca, une mediane ne prouve rien.
BRUTE_MIN_IMAGES = 8
PRESELECTION = 8                      # candidates gardees a l'etape 1
VERIFIEES = 6                         # candidates relues a 10 images/s (>= 3 a 5)

#: Texte (Tesseract, 2 images). Les fausses correspondances restaient a un
#: rappel <= 0,57 ; les 88 sures, relues une a une, etaient toutes justes.
INSTANTS_OCR = (0.6, 1.3)
TEXTE_SUR = 0.85                      # rappel ET precision
TEXTE_MARGE = 0.5                     # sur (rappel + precision), hors variantes
TEXTE_A_CONFIRMER = 0.6               # rappel
VARIANTE = 0.9                        # deux textes « identiques » (ratio des cles)
#: Une caption « a copier » (le VA l'ecrit lui-meme dans Instagram) n'est
#: comptee que si Tesseract la retrouve : c'est la seule preuve qu'il l'a
#: utilisee. La recette restreint le choix a UN texte, d'ou le seuil bas.
TEXTE_A_COPIER = 0.6

#: Livraison retrouvee : meme video reencodee par Instagram (< 16 bits), ou
#: brute + texte ecrit dans Instagram (~ +8). Memes marges que la brute.
LIVRAISON_SUR = (25, 15)
LIVRAISON_A_CONFIRMER = 40
LIVRAISON_JOURS = 45                  # on ne cherche pas plus loin en arriere
FPS_LIVRAISON, SECONDES_LIVRAISON = 2, 10.0

#: File des copies a empreinter : au-dela, on n'en copie plus (et on le note
#: sur la livraison) plutot que de remplir le disque du VPS.
ATTENTE_MAX_FICHIERS = 300
ATTENTE_MAX_OCTETS = 200 * 1024 * 1024

EXTS_VIDEO = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv"})
_NICE = ["nice", "-n", "19"] if shutil.which("nice") else []

# ------------------------------------------------------------ empreintes --


def _hash_px(px: bytes) -> Tuple[int, bool]:
    """dHash 256 bits d'une image 17x16 en gris, et « informative » (relief).

    MEME calcul que empreintes_video._hash_image : deux methodes differentes
    ne tombent pas sur les memes bits, et la calibration a ete faite avec
    celle-ci."""
    bits = 0
    for y in range(H):
        ligne = px[y * L:(y + 1) * L]
        for x in range(L - 1):
            bits = (bits << 1) | (1 if ligne[x] < ligne[x + 1] else 0)
    try:
        relief = statistics.pstdev(px)
    except Exception:
        relief = 0.0
    return bits, relief >= RELIEF_MIN


def lire_images(video, fps: int, duree: Optional[float] = None,
                debut: float = 0.0, timeout: int = 300) -> Tuple[List[Tuple[int, bool]], str]:
    """([(hash, informative)], erreur). UNE lecture ffmpeg, a nice 19.

    Les images lues avant une erreur restent bonnes (leur rang suit le
    temps) : on les garde, et l'erreur est rendue a cote, jamais avalee."""
    cmd = _NICE + ["ffmpeg", "-v", "error"]
    if debut > 0:
        cmd += ["-ss", f"{debut:.2f}"]
    if duree:
        cmd += ["-t", f"{duree:.2f}"]
    cmd += ["-i", str(video), "-vf",
            f"fps={fps},scale={L}:{H}:flags=area,format=gray",
            "-f", "rawvideo", "-"]
    err = ""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        px = r.stdout or b""
        if r.returncode != 0:
            lignes = (r.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
            err = (lignes[-1] if lignes else f"ffmpeg code {r.returncode}")[:200]
    except subprocess.TimeoutExpired as e:
        px, err = e.stdout or b"", f"ffmpeg > {timeout} s"
    except Exception as e:                                    # noqa: BLE001
        px, err = b"", f"ffmpeg indisponible : {e}"[:200]
    t = L * H
    n = len(px) // t
    return [_hash_px(px[k * t:(k + 1) * t]) for k in range(n)], err


def _coder(images: List[Tuple[int, bool]]) -> Tuple[str, str]:
    return ("".join(f"{h:064x}" for h, _i in images),
            "".join("1" if i else "0" for _h, i in images))


def _decoder(h: str, inf: str) -> List[Tuple[int, bool]]:
    n = min(len(h) // 64, len(inf))
    return [(int(h[k * 64:(k + 1) * 64], 16), inf[k] == "1") for k in range(n)]


def _mediane(ds: List[int]) -> int:
    ds = sorted(ds)
    return ds[len(ds) // 2]


# ------------------------------------------------------------- les cles --


def cle_media(chemin, identite_defaut: str = "", section: str = "") -> str:
    """« identite|section|fichier » : la cle des registres du site.

    Un fichier sous data/identities/<ident>/<section>/ donne sa cle
    directement. Ailleurs (dossier temporaire d'une brute imposee, lien dur),
    on cherche le meme nom dans la section de `identite_defaut` ; sans
    correspondance, on rend "" plutot que d'inventer une cle."""
    if not chemin:
        return ""
    p = Path(chemin)
    try:
        rel = p.resolve().relative_to(dossier_identites().resolve())
        parts = rel.parts
        if len(parts) == 3:
            return "|".join(parts)
    except Exception:
        pass
    # Deux ecritures du meme dossier (relative et absolue) : resolve() suffit
    # d'habitude, mais un lien symbolique de data/ (poste de dev) casse
    # relative_to. On compare aussi sur les trois derniers morceaux.
    parts = p.parts
    if len(parts) >= 4 and parts[-4] == "identities":
        return "|".join(parts[-3:])
    ident = (identite_defaut or "").strip().lower()
    if ident and section:
        cand = dossier_identites() / ident / section / p.name
        if cand.is_file():
            return f"{ident}|{section}|{p.name}"
    return ""


def chemin_de_cle(cle: str) -> Optional[Path]:
    parts = (cle or "").split("|")
    if len(parts) != 3 or not all(parts) or any(x in (".", "..") or "/" in x or "\\" in x
                                                for x in parts):
        return None
    return dossier_identites() / parts[0] / parts[1] / parts[2]


# ------------------------------------------------------------ livraisons --

_VERROU_LIVRAISONS = threading.Lock()


def _fichier_mois(ts: float) -> Path:
    return dossier_livraisons() / (time.strftime("%Y-%m", time.localtime(ts)) + ".jsonl")


#: L'id d'une livraison porte le MOIS ou elle a ete notee : « AAAAMM » + 10
#: chiffres hexadecimaux. La copie en attente s'appelle <id>.<ext>, et c'est
#: ce nom -- pas la date du fichier -- qui dit ou ranger l'empreinte.
_RID_MOIS = re.compile(r"(\d{4})(\d{2})[0-9a-f]{10}")


def _nouvel_id(ts: float) -> str:
    return time.strftime("%Y%m", time.localtime(ts)) + uuid.uuid4().hex[:10]


def _mois_du_rid(rid: str) -> str:
    """« AAAA-MM » lu dans l'id d'une livraison, "" pour un id d'avant."""
    m = _RID_MOIS.fullmatch(str(rid or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return ""
    return f"{m.group(1)}-{m.group(2)}"


def _fichier_de_livraison(rid: str) -> Path:
    """Le fichier du mois qui porte la ligne d'ORIGINE de cette livraison.

    Avant, l'empreinte allait dans le mois de la DATE DU FICHIER en attente.
    Or cette copie est un lien dur (ou un copy2) : elle garde la date de la
    video d'origine. Une brute du vault livree telle quelle porte la date de
    son import (2026-05-08 pour l'exemple de Jorel, 359 brutes sur ~7 000
    seulement dataient du mois courant sur le VPS) : l'empreinte partait dans
    2026-05.jsonl, hors de la fenetre de 45 jours, et la livraison etait
    relue SANS empreinte -- plus jamais retrouvee. Meme chose pour une
    variante du stock (os.replace garde sa date de fabrication) ou une video
    generee le 30 a 23 h 59 et livree le 1er. Pas d'utime pour autant : sur
    un lien dur, il changerait la date de la brute du vault et invaliderait
    son index."""
    mois = _mois_du_rid(rid)
    if mois:
        return dossier_livraisons() / f"{mois}.jsonl"
    # Id d'avant ce format (copie restee en attente pendant un deploiement) :
    # sa ligne d'origine est dans l'un des derniers mois.
    d = dossier_livraisons()
    for f in sorted(d.glob("*.jsonl"), reverse=True)[:3] if d.is_dir() else []:
        if rid in _lire_mois(f)[0]:
            return f
    return _fichier_mois(time.time())


def _ajouter_ligne(fichier: Path, rec: dict) -> bool:
    """Ajoute UNE ligne JSON. Un ajout, pas une reecriture : le fichier du
    mois grossit de centaines de lignes par jour, le reecrire a chaque
    livraison couterait plus que la livraison.

    Une coupure au milieu d'un ajout laisse une derniere ligne tronquee : on
    commence donc par un saut de ligne si le fichier n'en finit pas par un,
    pour que la ligne suivante ne se colle pas a la moitie de l'autre. La
    lecture compte les lignes illisibles (lire_livraisons) au lieu de les
    taire."""
    ligne = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _VERROU_LIVRAISONS:
        try:
            fichier.parent.mkdir(parents=True, exist_ok=True)
            prefixe = ""
            if fichier.exists() and fichier.stat().st_size > 0:
                with open(fichier, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        prefixe = "\n"
            with open(fichier, "a", encoding="utf-8") as f:
                f.write(prefixe + ligne)
                f.flush()
                os.fsync(f.fileno())
            return True
        except Exception as e:                                # noqa: BLE001
            print(f"[favoris-auto] livraison non notee ({fichier.name}) : {e}", flush=True)
            return False


def _normaliser_recette(recette: dict, identite: str) -> dict:
    """Garde les champs connus, avec des cles de registre (« ident|section|f »)."""
    r = dict(recette or {})
    out = {"action": str(r.get("action") or "")[:60],
           "famille": str(r.get("famille") or "")[:40]}
    # « media » : ce qui n'est ni brute ni template ni reel pret (une trend) --
    # note pour la trace, jamais etoile.
    for champ, section in (("brute", "brutes"), ("template", "templates"),
                           ("reel", "videos"), ("media", "")):
        v = r.get(champ)
        if v:
            out[champ] = (v if isinstance(v, str) and v.count("|") == 2
                          else cle_media(v, r.get("identite_media") or identite, section))
            if not out[champ]:
                out[champ + "_nom"] = Path(str(v)).name[:200]
    try:
        if r.get("brute_debut") is not None:
            out["brute_debut"] = round(float(r["brute_debut"]), 2)
    except (TypeError, ValueError):
        pass
    cap = r.get("caption")
    if isinstance(cap, dict) and str(cap.get("text") or cap.get("texte") or "").strip():
        out["caption"] = {"id": str(cap.get("id") or "")[:48],
                          "texte": str(cap.get("text") or cap.get("texte") or "")[:300],
                          "ident": str(cap.get("ident") or identite or "").lower(),
                          "mode": "a_copier" if cap.get("mode") == "a_copier" else "incrustee"}
    for champ in ("reserve", "repli"):
        if r.get(champ):
            out[champ] = True
    if r.get("model"):
        out["model"] = str(r["model"]).lower()[:60]
    return out


def noter_livraison(identite: str, video, recette: dict, va: str = "",
                    va_nom: str = "", salon: str = "", guild: str = "",
                    quoi: str = "") -> str:
    """Note la recette d'une video LIVREE. Rend son id ('' si non notee).

    A appeler APRES l'envoi, hors de la boucle Discord (asyncio.to_thread) :
    la copie de la video (lien dur, sinon copie) prend quelques millisecondes
    et doit se faire AVANT que l'appelant n'efface son fichier temporaire.
    L'empreinte, elle, est calculee plus tard par le fil (empreinter_attente),
    jamais dans le delai d'un clic."""
    now = time.time()
    rid = _nouvel_id(now)            # porte le mois : voir _fichier_de_livraison
    rec = {"id": rid, "le": int(now), "identite": str(identite or "").lower(),
           "va": str(va or ""), "va_nom": str(va_nom or "")[:80],
           "salon": str(salon or ""), "guild": str(guild or ""),
           "quoi": str(quoi or "")[:80],
           "fichier": Path(str(video)).name[:200] if video else ""}
    rec.update(_normaliser_recette(recette, rec["identite"]))
    src = Path(str(video)) if video else None
    if src is None or not src.is_file():
        rec["empreinte_erreur"] = "fichier livre introuvable"
    elif not fil_actif():
        # Personne ne calculerait l'empreinte (poste de dev, fil pas encore
        # lance) : la copie resterait sur le disque pour rien -- des Go de
        # liens durs vers des videos que le bot croit avoir effacees.
        rec["empreinte_erreur"] = "fil des favoris automatiques arrêté sur cette machine"
    else:
        try:
            attente = dossier_attente()
            attente.mkdir(parents=True, exist_ok=True)
            deja = [p for p in attente.iterdir() if p.is_file()]
            taille = src.stat().st_size
            if len(deja) >= ATTENTE_MAX_FICHIERS:
                rec["empreinte_erreur"] = f"file d'empreintes pleine ({len(deja)} videos)"
            elif taille > ATTENTE_MAX_OCTETS:
                rec["empreinte_erreur"] = f"video trop lourde ({taille // (1024 * 1024)} Mo)"
            else:
                cible = attente / (rid + (src.suffix.lower() or ".mp4"))
                try:
                    os.link(str(src), str(cible))
                except Exception:
                    shutil.copy2(str(src), str(cible))
                # Sous une AUTRE cle que l'empreinte : ecrit sous « empreinte »,
                # ce marqueur pouvait ecraser l'empreinte calculee a la relecture.
                rec["empreinte_etat"] = "attente"
        except Exception as e:                                # noqa: BLE001
            rec["empreinte_erreur"] = f"copie impossible : {e}"[:160]
    if not _ajouter_ligne(_fichier_mois(now), rec):
        return ""
    reveiller()
    return rid


def empreinter_attente(limite: int = 50) -> dict:
    """Calcule l'empreinte des videos livrees en attente. Rend un bilan."""
    bilan = {"faites": 0, "echecs": 0, "restantes": 0}
    d = dossier_attente()
    if not d.is_dir():
        return bilan
    fichiers = sorted((p for p in d.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
    for i, p in enumerate(fichiers):
        if i >= limite:
            bilan["restantes"] = len(fichiers) - limite
            break
        images, err = lire_images(p, FPS_LIVRAISON, duree=SECONDES_LIVRAISON, timeout=120)
        rid = p.stem
        # Le mois de la LIVRAISON (dans son id), pas la date du fichier : voir
        # _fichier_de_livraison.
        f_mois = _fichier_de_livraison(rid)
        if images:
            h, inf = _coder(images)
            _ajouter_ligne(f_mois, {"id": rid, "empreinte": {
                "fps": FPS_LIVRAISON, "h": h, "inf": inf}, "empreinte_etat": "faite",
                "empreinte_le": int(time.time())})
            bilan["faites"] += 1
        else:
            _ajouter_ligne(f_mois, {"id": rid, "empreinte_etat": "echec",
                                    "empreinte_erreur": err or "aucune image lue"})
            bilan["echecs"] += 1
        try:
            p.unlink()
        except OSError:
            pass
    return bilan


#: Fichier du mois deja lu : (taille, mtime) -> (livraisons, illisibles). Le
#: sous-processus analyse jusqu'a dix bangers d'affilee : relire et redecoder
#: des milliers de livraisons pour chacun couterait plus que l'analyse.
_CACHE_MOIS: Dict[str, tuple] = {}


def _lire_mois(f: Path) -> Tuple[Dict[str, dict], int]:
    try:
        st = f.stat()
    except OSError:
        return {}, 0
    sig = (st.st_size, st.st_mtime_ns)
    c = _CACHE_MOIS.get(str(f))
    if c and c[0] == sig:
        return c[1], c[2]
    out: Dict[str, dict] = {}
    illisibles = 0
    try:
        lignes = f.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lignes = []
    for ligne in lignes:
        if not ligne.strip():
            continue
        try:
            rec = json.loads(ligne)
        except ValueError:
            illisibles += 1
            continue
        if not isinstance(rec, dict) or not rec.get("id"):
            illisibles += 1
            continue
        _fusionner(out.setdefault(rec["id"], {}), rec)
    _CACHE_MOIS[str(f)] = (sig, out, illisibles)
    return out, illisibles


def _fusionner(dst: dict, rec: dict) -> None:
    """Fusionne une ligne dans la livraison, sans jamais laisser une valeur
    qui n'est pas une empreinte ecraser une empreinte CALCULEE (dict).

    Les lignes d'avant ce correctif ecrivaient le marqueur « attente » sous
    « empreinte », et lire_livraisons fusionne les mois dans l'ordre : la
    ligne d'origine du mois courant effacait l'empreinte rangee dans un mois
    plus ancien, et la livraison etait relue sans empreinte (reproduit :
    scratchpad/rv_fa/mtime.py)."""
    for k, v in rec.items():
        if k == "empreinte" and not isinstance(v, dict) and isinstance(dst.get(k), dict):
            continue
        dst[k] = v


def lire_livraisons(depuis: float = 0.0) -> Tuple[Dict[str, dict], int]:
    """({id: livraison fusionnee}, lignes illisibles). Les fichiers des mois
    concernes seulement. Une ligne tronquee (coupure pendant un ajout) est
    COMPTEE, et l'ecran la montre."""
    d = dossier_livraisons()
    out: Dict[str, dict] = {}
    illisibles = 0
    if not d.is_dir():
        return out, 0
    mois_min = time.strftime("%Y-%m", time.localtime(depuis)) if depuis else ""
    for f in sorted(d.glob("*.jsonl")):
        if mois_min and f.stem < mois_min:
            continue
        o, n = _lire_mois(f)
        illisibles += n
        for k, v in o.items():
            _fusionner(out.setdefault(k, {}), v)
    if depuis:
        out = {k: v for k, v in out.items() if int(v.get("le") or 0) >= depuis}
    return out, illisibles


#: Un fichier de mois est supprime quand son DERNIER jour a plus de
#: LIVRAISON_JOURS + 31 jours : trouver_livraison ne remonte que 45 jours
#: avant la publication du banger, et sur les 166 bangers du VPS (copie de
#: calibration, 27/09) un banger est detecte 6 jours apres sa publication en
#: mediane, 17 jours pour 90 % d'entre eux. Un banger detecte plus tard encore
#: (120 jours au plus vu) n'a plus sa recette : il passe par l'image.
PURGE_JOURS = LIVRAISON_JOURS + 31


def purger_livraisons(maintenant: Optional[float] = None) -> List[dict]:
    """Supprime les fichiers de mois que plus rien ne lit. Rend ce qui est parti.

    Sans ca, data/livraisons/ grossissait sans limite : ~0,5 Ko par
    livraison plus ~1,4 Ko d'empreinte, 10 a 30 Mo par mois gardes a vie sur
    le VPS. Ce ne sont pas des medias (le site n'en efface jamais) : des
    lignes de trace, que trouver_livraison ne relit plus. Chaque suppression
    est ecrite au journal, avec son nombre de lignes."""
    now = time.time() if maintenant is None else float(maintenant)
    limite = now - PURGE_JOURS * 86400
    d = dossier_livraisons()
    faits: List[dict] = []
    if not d.is_dir():
        return faits
    for f in sorted(d.glob("*.jsonl")):
        m = re.fullmatch(r"(\d{4})-(\d{2})", f.stem)
        if not m or not 1 <= int(m.group(2)) <= 12:
            continue                     # pas un fichier de mois de ce module
        a, mo = int(m.group(1)), int(m.group(2))
        a2, mo2 = (a + 1, 1) if mo == 12 else (a, mo + 1)
        # Premier instant du mois SUIVANT : toute ligne du fichier est avant.
        fin = time.mktime((a2, mo2, 1, 0, 0, 0, 0, 0, -1))
        if fin >= limite:
            continue
        with _VERROU_LIVRAISONS:
            try:
                taille = f.stat().st_size
                lignes = sum(1 for x in f.read_text(encoding="utf-8", errors="replace")
                             .splitlines() if x.strip())
                f.unlink()
            except OSError as e:
                faits.append({"mois": f.stem, "erreur": str(e)[:160]})
                print(f"[favoris-auto] livraisons {f.name} non supprimées : {e}", flush=True)
                continue
        _CACHE_MOIS.pop(str(f), None)
        faits.append({"mois": f.stem, "lignes": lignes, "octets": taille})
        print(f"[favoris-auto] livraisons {f.name} supprimées : {lignes} ligne(s), "
              f"{taille // 1024} Ko, plus lues depuis {PURGE_JOURS} jours", flush=True)
    return faits


def _signature_sources(liv: dict) -> str:
    cap = (liv.get("caption") or {})
    return "|".join([liv.get("brute") or liv.get("brute_nom") or "",
                     liv.get("template") or "", liv.get("reel") or "",
                     liv.get("media") or liv.get("media_nom") or "",
                     _cle_texte(cap.get("texte") or "")])


_CACHE_EMP: Dict[str, list] = {}


def _images_livraison(liv: dict) -> Tuple[list, int]:
    emp = liv.get("empreinte")
    rid = str(liv.get("id") or "")
    if rid not in _CACHE_EMP:
        try:
            _CACHE_EMP[rid] = [_decoder(emp.get("h") or "", emp.get("inf") or ""),
                               max(1, int(round(FPS_BANGER / int(emp.get("fps") or FPS_LIVRAISON))))]
        except Exception:                                     # noqa: BLE001
            _CACHE_EMP[rid] = [[], 1]
    lf, pas = _CACHE_EMP[rid]
    return lf, pas


def _score_rapide(bf: List[Tuple[int, bool]], liv: dict) -> int:
    """Premier tri, sans decalage, sur 8 images : des milliers de livraisons
    par mois, la recherche complete n'est faite que sur les meilleures."""
    lf, pas = _images_livraison(liv)
    ds = []
    for i, (h, inf) in enumerate(lf):
        if not inf:
            continue
        k = i * pas
        c = [bf[j][0] for j in (k - 1, k, k + 1) if 0 <= j < len(bf) and bf[j][1]]
        if c:
            ds.append(min((h ^ x).bit_count() for x in c))
        if len(ds) >= 8:
            break
    return _mediane(ds) if len(ds) >= 3 else 999


def _score_livraison(bf: List[Tuple[int, bool]], liv: dict) -> Optional[Tuple[int, int]]:
    """(mediane, images comparees) de la livraison contre le banger, au
    meilleur decalage global (-1 s a +1 s : Instagram peut rogner une image
    de debut), une image de tolerance de part et d'autre."""
    lf, pas = _images_livraison(liv)
    if not lf:
        return None
    best = None
    for o in range(-10, 11):
        ds = []
        for i, (h, inf) in enumerate(lf):
            if not inf:
                continue
            k = i * pas + o
            c = [bf[j][0] for j in (k - 1, k, k + 1) if 0 <= j < len(bf) and bf[j][1]]
            if c:
                ds.append(min((h ^ x).bit_count() for x in c))
        if len(ds) >= 6:
            m = _mediane(ds)
            if best is None or m < best[0]:
                best = (m, len(ds))
    return best


def trouver_livraison(bf: List[Tuple[int, bool]], poste_le: int = 0) -> dict:
    """La livraison dont la video EST ce banger. {decision, livraison, med, marge}."""
    fin = (poste_le or time.time()) + 86400
    livs, illisibles = lire_livraisons(depuis=fin - (LIVRAISON_JOURS + 1) * 86400)
    rapides = []
    sans_empreinte = 0
    for rid, liv in livs.items():
        if int(liv.get("le") or 0) > fin:
            continue
        if not isinstance(liv.get("empreinte"), dict):
            sans_empreinte += 1
            continue
        rapides.append((_score_rapide(bf, liv), rid))
    rapides.sort()
    # Au plus 5 par recette, puis les 60 meilleures : la meme brute livree a
    # trente VA remplirait sinon la liste, et la « 2e d'une autre recette »
    # (celle qui dit si c'est ambigu) n'y serait plus -- l'ecart vaudrait 99
    # par defaut, une certitude inventee.
    par_recette: Dict[str, int] = {}
    retenues = []
    for r, rid in rapides:
        s = _signature_sources(livs[rid])
        if par_recette.get(s, 0) >= 5:
            continue
        par_recette[s] = par_recette.get(s, 0) + 1
        retenues.append((r, rid))
    scores = []
    for _r, rid in retenues[:60]:
        s = _score_livraison(bf, livs[rid])
        if s:
            scores.append((s[0], -s[1], rid))
    scores.sort()
    res = {"decision": "rien", "livraisons_lues": len(livs),
           "sans_empreinte": sans_empreinte, "illisibles": illisibles}
    if not scores:
        return res
    med, n_neg, rid = scores[0]
    liv = livs[rid]
    sig = _signature_sources(liv)
    # Le 2e : la meilleure livraison d'une AUTRE recette. La meme brute livree
    # a dix VA donne dix empreintes presque identiques -- ce n'est pas une
    # ambiguite, c'est la meme recette.
    marge = 99
    for m2, _n, r2 in scores[1:]:
        if _signature_sources(livs[r2]) != sig:
            marge = m2 - med
            break
    res.update(livraison=liv, med=med, n=-n_neg, marge=marge)
    if med <= LIVRAISON_SUR[0] and marge >= LIVRAISON_SUR[1]:
        res["decision"] = "sur"
    elif med <= LIVRAISON_A_CONFIRMER:
        res["decision"] = "a_confirmer"
    return res


# ------------------------------------------------------------------ index --

_VERROU_INDEX = threading.Lock()


def _fichier_index(ident: str, section: str) -> Path:
    return dossier_index() / f"{ident}__{section}.json"


def identites_du_vault() -> List[str]:
    d = dossier_identites()
    if not d.is_dir():
        return []
    # « _xxx » / « .xxx » : dossiers de test ou de rangement, pas des identites.
    return sorted(p.name for p in d.iterdir()
                  if p.is_dir() and not p.name.startswith(("_", ".")))


def _videos(dossier: Path) -> List[Path]:
    try:
        return sorted(p for p in dossier.iterdir()
                      if p.is_file() and p.suffix.lower() in EXTS_VIDEO)
    except OSError:
        return []


def _signature(p: Path) -> str:
    st = p.stat()
    return f"{st.st_size}-{st.st_mtime_ns}"


def mettre_a_jour_index(identites: Optional[Iterable[str]] = None,
                        sections: Iterable[str] = ("brutes", "templates"),
                        budget_s: float = 0.0,
                        progres: Optional[Callable[[dict], None]] = None) -> dict:
    """Calcule les empreintes denses manquantes (fichier par fichier, reprise
    possible : le cache est ecrit toutes les 25 videos -- chaque deploiement
    redemarre le bot, un index d'une heure ne doit pas repartir de zero).

    Rend {videos, a_jour, calculees, echecs, restantes}. `restantes` > 0 si
    le budget de temps est epuise : l'index n'est pas complet et on le dit."""
    t0 = time.monotonic()
    bilan = {"videos": 0, "a_jour": 0, "calculees": 0, "echecs": 0, "restantes": 0}
    with _VERROU_INDEX:
        for ident in (list(identites) if identites is not None else identites_du_vault()):
            for section in sections:
                dossier = dossier_identites() / ident / section
                fichiers = _videos(dossier)
                f_idx = _fichier_index(ident, section)
                cache = safe_json.load(f_idx, default={}) if f_idx.exists() else {}
                if not isinstance(cache, dict):
                    cache = {}
                change = False
                vus = set()
                depuis_ecriture = 0
                for f in fichiers:
                    vus.add(f.name)
                    bilan["videos"] += 1
                    try:
                        sig = _signature(f)
                    except OSError:
                        continue
                    e = cache.get(f.name)
                    if isinstance(e, dict) and e.get("sig") == sig:
                        if e.get("v") == INDEX_VERSION:
                            bilan["a_jour"] += 1
                            continue
                        if int(e.get("essais") or 0) >= 3:
                            bilan["echecs"] += 1          # casse : dit, pas relu sans fin
                            continue
                    if budget_s and time.monotonic() - t0 > budget_s:
                        bilan["restantes"] += 1
                        continue
                    images, err = lire_images(f, FPS_INDEX[section],
                                              duree=SECONDES_INDEX[section])
                    if images:
                        h, inf = _coder(images)
                        cache[f.name] = {"sig": sig, "v": INDEX_VERSION,
                                         "fps": FPS_INDEX[section], "h": h, "inf": inf}
                        bilan["calculees"] += 1
                    else:
                        essais = int((e or {}).get("essais") or 0) + 1 if isinstance(e, dict) and e.get("sig") == sig else 1
                        cache[f.name] = {"sig": sig, "essais": essais, "erreur": err or "aucune image"}
                        bilan["echecs"] += 1
                    change = True
                    depuis_ecriture += 1
                    if depuis_ecriture >= 25:
                        safe_json.write(f_idx, cache, indent=None, backup=False)
                        depuis_ecriture = 0
                        if progres:
                            progres(dict(bilan, en_cours=f"{ident}/{section}"))
                for nom in [n for n in cache if n not in vus]:
                    cache.pop(nom, None)       # parti du dossier (corbeille, doublon range)
                    change = True
                if change:
                    if cache or f_idx.exists():
                        safe_json.write(f_idx, cache, indent=None, backup=False)
    return bilan


def charger_index(section: str, identites: Optional[Iterable[str]] = None) -> Dict[str, List[Tuple[int, bool]]]:
    """{« ident/section/fichier »: images} pour les fichiers ENCORE presents."""
    out = {}
    for ident in (list(identites) if identites is not None else identites_du_vault()):
        f_idx = _fichier_index(ident, section)
        if not f_idx.exists():
            continue
        cache = safe_json.load(f_idx, default={})
        if not isinstance(cache, dict):
            continue
        dossier = dossier_identites() / ident / section
        for nom, e in cache.items():
            if not isinstance(e, dict) or e.get("v") != INDEX_VERSION:
                continue
            if not (dossier / nom).is_file():
                continue
            out[f"{ident}/{section}/{nom}"] = _decoder(e.get("h") or "", e.get("inf") or "")
    return out


# ------------------------------------------------------------- templates --


def _brouillon(rel_video: str) -> dict:
    p = dossier_identites() / rel_video
    d = safe_json.load(p.with_suffix(".montage.json"), default=None)
    return d if isinstance(d, dict) else {}


def _coupe(brouillon: dict) -> float:
    try:
        return float(brouillon.get("cut_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def chercher_template(bf: List[Tuple[int, bool]], templates: Dict[str, list]) -> dict:
    """Le template dont la partie 2 (apres le trait de coupe) est dans le banger.

    Si la brute etait plus courte que la place, le DEBUT du montage a ete coupe
    de « gap » secondes (assemble_brute_template) : l'image du template a
    l'instant T se retrouve dans le banger a T - gap. On cherche gap entre 0 et
    la coupe, par pas de 0,1 s, et on ne compare que les images APRES la coupe
    (+ 0,2 s), la ou le template est visible."""
    nb = len(bf)
    groupes: Dict[tuple, List[str]] = {}
    coupes: Dict[tuple, float] = {}
    for rel, tf in templates.items():
        cut = _coupe(_brouillon(rel))
        # Pas de coupe, ou coupe a la fin (« template caption » : la brute
        # remplace TOUT le template) : rien a reconnaitre a l'image. Ceux-la
        # se reconnaissent au texte.
        if cut <= 0.05 or cut * FPS_INDEX["templates"] >= len(tf) - 3:
            continue
        k = (_coder(tf)[0], round(cut, 2))       # copies identiques : calculees une fois
        groupes.setdefault(k, []).append(rel)
        coupes[k] = cut
    cands = []
    for k, rels in groupes.items():
        tf = templates[rels[0]]
        cut = coupes[k]
        debut = int(round((cut + 0.2) * 10))
        best = None
        for gap10 in range(0, int(round(cut * 10)) + 1):
            ds = []
            for j in range(debut, len(tf)):
                kb = j - gap10
                if 0 <= kb < nb and tf[j][1] and bf[kb][1]:
                    ds.append((tf[j][0] ^ bf[kb][0]).bit_count())
            if len(ds) < 5:
                continue
            m = _mediane(ds)
            if best is None or m < best[0]:
                best = (m, gap10 / 10, len(ds))
        if best:
            cands.append({"med": best[0], "gap": best[1], "n": best[2], "cut": round(cut, 3),
                          "copies": sorted(rels)})
    cands.sort(key=lambda c: (c["med"], -c["n"]))
    res = {"decision": "rien", "candidats": cands[:3]}
    if cands:
        c = cands[0]
        res.update(c)
        if c["med"] <= TPL_SUR and c["n"] >= TPL_MIN_IMAGES:
            res["decision"] = "sur"
        elif c["med"] <= TPL_A_CONFIRMER:
            res["decision"] = "a_confirmer"
    return res


# ----------------------------------------------------------------- brutes --


def _partie_brute(bf: List[Tuple[int, bool]], tpl: dict) -> List[Tuple[int, int]]:
    """[(rang, hash)] : les images du banger ou la brute est visible."""
    if tpl.get("decision") == "sur":
        fin = int((float(tpl["cut"]) - float(tpl["gap"]) - 0.15) * 10)
    else:
        fin = len(bf)
    return [(k, h) for k, (h, inf) in enumerate(bf[:max(1, fin)]) if inf]


def preselectionner(q: List[Tuple[int, int]], index: Dict[str, list],
                    entier: bool) -> List[dict]:
    """Etape 1 : chaque image connue de chaque brute contre TOUTES les images
    de la partie brute du banger, sans supposer d'alignement (fenetre au
    hasard). Score = plus petite distance ; departage au nombre d'images
    proches (<= 28 bits)."""
    qh = [h for _k, h in q]
    if entier:
        qh = qh[::2]                   # une image sur deux suffit a preselectionner
    if not qh:
        return []
    scores = []
    for rel, ims in index.items():
        best, hits = 999, 0
        for hb, inf in ims:
            if not inf:
                continue
            m = min((hb ^ x).bit_count() for x in qh)
            if m < best:
                best = m
            if m <= 28:
                hits += 1
        if best < 999:
            scores.append((best, -hits, rel))
    scores.sort()
    return [{"rel": r, "min": b, "hits": -h} for b, h, r in scores[:PRESELECTION]]


def score_dense(q: List[Tuple[int, int]], br: List[Tuple[int, bool]]) -> Optional[dict]:
    """Etape 2 : le DECALAGE o tel que l'image k du banger ressemble a
    l'image k+o de la brute, sur toute la partie brute. Une seule image
    proche ne suffit pas : c'est une SEQUENCE qui doit coller, ce qui ecarte
    les sosies (meme chambre, meme tenue, autre prise)."""
    if not br or len(q) < 3:
        return None
    best = None
    for o in range(-3, len(br)):
        ds = []
        for k, h in q:
            j = k + o
            if 0 <= j < len(br) and br[j][1]:
                ds.append((h ^ br[j][0]).bit_count())
        if len(ds) < max(3, int(0.6 * len(q))):
            continue
        m = _mediane(ds)
        ok = sum(1 for d in ds if d <= 30) / len(ds)
        if best is None or (m, -ok) < (best["med"], -best["ok"]):
            best = {"med": m, "ok": round(ok, 2), "decalage": round(o / 10, 1), "n": len(ds)}
    return best


def jumelles(a: List[Tuple[int, bool]], b: List[Tuple[int, bool]]) -> int:
    """Mediane de distance entre deux brutes au meilleur decalage (+-6 s)."""
    best = 999
    for o in range(-60, 61):
        ds = [(a[k][0] ^ b[k + o][0]).bit_count() for k in range(len(a))
              if 0 <= k + o < len(b) and a[k][1] and b[k + o][1]]
        if len(ds) >= 20:
            best = min(best, _mediane(ds))
    return best


def chercher_brute(bf: List[Tuple[int, bool]], tpl: dict, index: Dict[str, list],
                   lire=None) -> dict:
    """La brute d'origine, parmi TOUTES celles du vault. {decision, rel, ...}."""
    lire = lire or (lambda rel: lire_images(dossier_identites() / rel, FPS_BANGER,
                                            duree=SECONDES_DENSE)[0])
    q = _partie_brute(bf, tpl)
    res = {"decision": "rien", "images_banger": len(q)}
    if len(q) < 3:
        res["raison"] = "trop peu d'images informatives dans le banger"
        return res
    pre = preselectionner(q, index, entier=tpl.get("decision") != "sur")
    res["preselection"] = pre[:3]
    denses: Dict[str, list] = {}
    verifs = []
    for c in pre[:VERIFIEES]:
        br = lire(c["rel"])
        denses[c["rel"]] = br
        s = score_dense(q, br)
        if s:
            verifs.append(dict(s, rel=c["rel"]))
    verifs.sort(key=lambda x: (x["med"], -x["ok"]))
    res["candidats"] = verifs[:4]
    if not verifs:
        res["raison"] = "aucune brute candidate lisible"
        return res
    a = verifs[0]
    notes, second = [], None
    jum = []
    for x in verifs[1:]:
        if x["med"] - a["med"] < 15 and jumelles(denses[a["rel"]], denses[x["rel"]]) <= JUMELLES_MAX:
            jum.append(x["rel"])
            continue
        second = x
        break
    marge = (second["med"] - a["med"]) if second else 99
    res.update(rel=a["rel"], med=a["med"], ok=a["ok"], decalage=a["decalage"],
               n=a["n"], marge=marge, jumelles=jum)
    sur = any(a["med"] <= m and marge >= e for m, e in BRUTE_SUR)
    if sur and a["n"] < BRUTE_MIN_IMAGES:
        sur = False
        notes.append(f"seulement {a['n']} images comparées")
    if sur:
        res["decision"] = "sur"
    elif a["med"] <= BRUTE_A_CONFIRMER:
        res["decision"] = "a_confirmer"
    if jum:
        idents = {r.split("/")[0] for r in [a["rel"]] + jum}
        if len(idents) > 1:
            # La meme video dans deux identites : le contenu est sur, pas
            # l'identite. On ne choisit pas a la place du proprietaire.
            if res["decision"] == "sur":
                res["decision"] = "a_confirmer"
            notes.append("même vidéo dans plusieurs identités : " + ", ".join(sorted(idents)))
        else:
            notes.append("jumelle(s) : " + ", ".join(r.split("/")[-1] for r in jum))
    res["notes"] = notes
    return res


# ------------------------------------------------------------------ texte --


def _cle_texte(t) -> str:
    """Meme principe que web_upload._caption_cle (casse, accents composes,
    ponctuation ignores), plus les emojis retires : Tesseract ne les lit pas."""
    t = unicodedata.normalize("NFKC", str(t or "")).lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9à-ɏ\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _segments(brouillon: dict) -> list:
    s = brouillon.get("segments")
    if isinstance(s, str):
        try:
            s = json.loads(s or "[]")
        except ValueError:
            s = []
    return [x for x in (s or []) if isinstance(x, dict)]


def corpus_textes() -> List[dict]:
    """Tous les textes incrustables connus, avec leur origine :
    bibliotheque de captions, brouillons de montage des templates,
    captions minutees du moteur (data/noctus/captions.json)."""
    out = []
    lib = safe_json.load(_data() / "captions.json", default={})
    for ident, bloc in (lib.items() if isinstance(lib, dict) else []):
        for it in ((bloc or {}).get("items") or []) if isinstance(bloc, dict) else []:
            if isinstance(it, dict) and str(it.get("text") or "").strip():
                out.append({"texte": it["text"], "source": "bibliotheque", "ident": ident,
                            "ref": it.get("id"), "fav": it.get("fav") is True})
    for ident in identites_du_vault():
        d = dossier_identites() / ident / "templates"
        try:
            brouillons = sorted(d.glob("*.montage.json"))
        except OSError:
            brouillons = []
        for b in brouillons:
            m = safe_json.load(b, default=None)
            if not isinstance(m, dict):
                continue
            nom = b.name[:-len(".montage.json")]
            for s in _segments(m):
                if str(s.get("text") or "").strip():
                    out.append({"texte": s["text"], "source": "template", "ident": ident,
                                "ref": f"{ident}/templates/{nom}", "coupe": _coupe(m)})
    nc = safe_json.load(_data() / "noctus" / "captions.json", default=[])
    for e in (nc if isinstance(nc, list) else []):
        if not isinstance(e, dict):
            continue
        for s in e.get("captions") or []:
            if isinstance(s, dict) and str(s.get("text") or "").strip():
                out.append({"texte": s["text"], "source": "noctus", "ident": "",
                            "ref": str(e.get("label") or "")})
    for o in out:
        o["cle"] = _cle_texte(o["texte"])
    return [o for o in out if o["cle"]]


def _mots(t: str) -> List[str]:
    return [m for m in t.split() if len(m) >= 3]


def _proche(m: str, ens: set) -> bool:
    return m in ens or any(SequenceMatcher(None, m, x).ratio() >= 0.8 for x in ens)


def comparer(lu: str, connu: str) -> Tuple[float, float, float]:
    """(rappel, precision, ratio) entre une lecture et un texte connu.
    rappel : mots (>= 3 lettres) du texte connu retrouves dans la lecture ;
    precision : mots lus retrouves dans le texte connu (ecarte un texte connu
    noye dans une lecture qui dit autre chose)."""
    lk, k = _cle_texte(lu), _cle_texte(connu)
    if not lk or not k:
        return 0.0, 0.0, 0.0
    mk, ml = _mots(k), _mots(lk)
    sml, smk = set(ml), set(mk)
    rap = sum(1 for m in mk if _proche(m, sml)) / len(mk) if mk else 0.0
    pre = sum(1 for m in ml if _proche(m, smk)) / len(ml) if ml else 0.0
    return round(rap, 2), round(pre, 2), round(SequenceMatcher(None, lk, k).ratio(), 2)


def ocr_image(video, t: float) -> dict:
    """Le texte incruste a l'instant t : Tesseract LOCAL, rien d'autre.

    Pas analyse_gratuite.lire_capture : elle essaie Gemini d'abord. Ici on
    appelle directement transcrire_tesseract, gratuit et sur la machine."""
    import analyse_gratuite as _ag
    with tempfile.TemporaryDirectory(prefix="fa_ocr_") as tmp:
        png = Path(tmp) / "i.png"
        try:
            subprocess.run(_NICE + ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.2f}",
                                    "-i", str(video), "-frames:v", "1", str(png)],
                           capture_output=True, timeout=60)
        except Exception as e:                                # noqa: BLE001
            return {"texte": "", "erreur": f"image non extraite : {e}"[:160]}
        if not png.exists():
            return {"texte": "", "erreur": "image non extraite"}
        r = _ag.transcrire_tesseract(png)
    return {"texte": str(r.get("texte") or ""), "erreur": str(r.get("erreur") or "")}


def chercher_texte(video, corpus: List[dict], ocr=None) -> dict:
    """Le texte incruste du banger, reconnu dans le corpus. {decision, ...}"""
    ocr = ocr or ocr_image
    lectures, erreurs = [], []
    for t in INSTANTS_OCR:
        r = ocr(video, t)
        if r.get("erreur"):
            erreurs.append(r["erreur"])
        if str(r.get("texte") or "").strip():
            lectures.append({"t": t, "texte": r["texte"]})
    res = {"decision": "aucun", "lectures": lectures}
    if erreurs and not lectures:
        # « Tesseract absent » n'est pas « aucun texte » : on ne classe pas
        # le banger en « brute seule » sur une lecture qui n'a pas eu lieu.
        res.update(decision="non_lu", erreur=erreurs[0])
        return res
    par_cle: Dict[str, List[dict]] = {}
    for c in corpus:
        par_cle.setdefault(c["cle"], []).append(c)
    # Premier tri : un texte connu qui ne partage AUCUN debut de mot (3
    # lettres) avec la lecture ne peut pas atteindre les seuils. La
    # bibliotheque peut monter a 300 captions par identite : comparer mot a
    # mot chacune d'elles couterait des secondes pour rien.
    prefixes = {m[:3] for l in lectures for m in _mots(_cle_texte(l["texte"]))}
    best = []
    for k, items in par_cle.items():
        if not any(m[:3] in prefixes for m in _mots(k)):
            continue
        top = None
        for lec in lectures:
            rap, pre, rat = comparer(lec["texte"], k)
            if top is None or rap + pre > top[0] + top[1]:
                top = (rap, pre, rat, lec["t"])
        if top and (top[0] or top[1]):
            best.append({"cle": k, "rappel": top[0], "precision": top[1], "ratio": top[2],
                         "t": top[3], "items": items})
    best.sort(key=lambda x: -(x["rappel"] + x["precision"]))
    lu = " ".join(l["texte"] for l in lectures)
    mots_lus = _mots(_cle_texte(lu))
    res["lu"] = lu[:300]
    if best:
        top = best[0]
        somme = top["rappel"] + top["precision"]
        rivaux = [b for b in best[1:] if SequenceMatcher(None, top["cle"], b["cle"]).ratio() < VARIANTE
                  and b["rappel"] + b["precision"] > somme - TEXTE_MARGE]
        variantes = [b["cle"] for b in best[1:]
                     if SequenceMatcher(None, top["cle"], b["cle"]).ratio() >= VARIANTE]
        res.update(cle=top["cle"], rappel=top["rappel"], precision=top["precision"],
                   t=top["t"], variantes=variantes[:5],
                   sources=sorted({(i["source"], i["ident"], str(i.get("ref") or ""))
                                   for i in top["items"]})[:12],
                   # TOUS les brouillons de template qui portent ce texte (noms
                   # sans extension), a part : la liste « sources » est
                   # tronquee, et « template » y vient en dernier.
                   templates=sorted({Path(str(i.get("ref") or "")).name for i in top["items"]
                                     if i["source"] == "template"}),
                   texte=_texte_prefere(top["items"]))
        if top["rappel"] >= TEXTE_SUR and top["precision"] >= TEXTE_SUR and not rivaux:
            res["decision"] = "sur"
            return res
        if top["rappel"] >= TEXTE_A_CONFIRMER:
            res["decision"] = "a_confirmer"
            if rivaux:
                res["rival"] = rivaux[0]["cle"]
            return res
    if len(mots_lus) >= 3:
        res["decision"] = "inconnu"
    return res


def _texte_prefere(items: List[dict]) -> str:
    """Le texte a ajouter : celui d'une bibliotheque d'abord (deja relu), puis
    d'un brouillon de template, puis du moteur. Jamais la lecture OCR : elle
    perd les emojis et se trompe de lettres."""
    for src in ("bibliotheque", "template", "noctus"):
        for i in items:
            if i["source"] == src:
                return i["texte"]
    return items[0]["texte"] if items else ""


def texte_de_la_brute(lu_banger: str, rel_brute: str, t_brute: float, ocr=None) -> Tuple[bool, str]:
    """Le texte lu sur le banger est-il deja incruste dans la BRUTE elle-meme
    (titre TikTok, texte d'origine) ? Alors ce n'est pas une caption a
    etoiler. Deux preuves : les mots sont dans le nom du fichier, ou
    Tesseract lit le meme texte sur la brute au meme instant."""
    mots = _mots(_cle_texte(lu_banger))
    if len(mots) < 2:
        return False, ""
    nom = set(_cle_texte(Path(rel_brute).stem.replace("_", " ")).split())
    if sum(1 for m in mots if m in nom) / len(mots) >= 0.6:
        return True, "mots dans le nom du fichier"
    ocr = ocr or ocr_image
    r = ocr(dossier_identites() / rel_brute, t_brute)
    lb = set(_mots(_cle_texte(r.get("texte") or "")))
    if lb and sum(1 for m in mots if _proche(m, lb)) / len(mots) >= 0.6:
        return True, f"même texte lu sur la brute à {t_brute:.1f} s"
    return False, ""


# --------------------------------------------------------------- analyse --


def _fiche_banger(sc: str) -> dict:
    import bangers as _bg
    return dict((_bg.charger().get("reels") or {}).get(sc) or {})


def vues_citees(sc: str, fiche: Optional[dict] = None) -> Tuple[int, dict]:
    """Le chiffre qu'on cite, et d'ou il vient : LE MAXIMUM connu, comme le
    salon all-banger (all_banger.vues_de). Le detail est garde : l'exemple du
    proprietaire (64 498) etait « vues_actuelles », le registre disait 86 724."""
    import bangers as _bg
    f = fiche if fiche is not None else _fiche_banger(sc)
    detail = {"vues": _bg._entier(f.get("vues")), "vues_detection": _bg._entier(f.get("vues_detection"))}
    try:
        va = _bg.lire_details(sc).get("vues_actuelles")
        if va is not None:
            detail["vues_actuelles"] = _bg._entier(va)
    except Exception:                                         # noqa: BLE001
        pass
    return max(list(detail.values()) + [0]), detail


def _reserves(ident: str) -> List[str]:
    try:
        import type_identite as _ti
        return list(_ti.reserves_liees(ident)[0])
    except Exception:                                         # noqa: BLE001
        return []


def _identite_du_compte(compte: str, registre: dict) -> Tuple[str, int]:
    """L'identite des bangers SURS du meme compte Instagram. Sur les donnees
    du 27/09 : 71 comptes, aucun n'a poste deux identites. Sert a PROPOSER
    (« À confirmer »), jamais a etoiler seul."""
    vus = {}
    for e in (registre.get("bangers") or {}).values():
        if isinstance(e, dict) and e.get("compte") == compte and e.get("identite_sure"):
            vus[e["identite"]] = vus.get(e["identite"], 0) + 1
    if len(vus) == 1:
        (i, n), = vus.items()
        return i, n
    return "", 0


def _desactivee(rel: str) -> bool:
    try:
        import brutes_off as _off
        return _off.est_desactivee(dossier_identites() / rel)
    except Exception:                                         # noqa: BLE001
        return False


def _cause_desactivation(rel: str) -> str:
    """« désactivée à la main le 26/09/2026 22:29 » : la cause ET la date
    ecrites dans le voisin .off.json. Sans elles, l'ecran disait « caption
    deja incrustee » pour TOUTES, y compris les deux brutes eteintes a la main
    la veille alors qu'elles avaient fait des bangers (Ddi--TfI1nl,
    DdkemDDsBoG, 46 k vues) -- justement celles ou le proprietaire doit
    trancher en connaissance de cause."""
    try:
        import brutes_off as _off
        v = _off.lire(dossier_identites() / rel)
    except Exception:                                         # noqa: BLE001
        v = {}
    cause = str((v or {}).get("cause") or "").strip() or "cause non notée"
    le = str((v or {}).get("le") or "").strip()
    return f"désactivée ({cause}" + (f", le {le})" if le else ")")


def _proposer_brute_desactivee(a: dict, cle: str, ident: str, raison: str, score: dict) -> None:
    """Une brute qui a fait un banger mais que le proprietaire a eteinte
    (.off.json) : JAMAIS une etoile silencieuse, jamais une simple note non
    plus -- une ligne « À confirmer » avec la cause. Avant, seule une note
    le disait : rien a valider ni refuser, et la brute d'un banger a 46 k
    vues disparaissait des decisions. Valider pose l'etoile ; la brute ne
    repartira chez les VA qu'une fois reactivee (fav_brutes_for les ecarte)."""
    cause = _cause_desactivation(cle.replace("|", "/"))
    a["notes"].append(f"brute {cle.split('|')[-1]} {cause} : à confirmer, pas étoilée d'office")
    _proposer(a, "brute", cle, ident, "a_confirmer",
              f"{raison} ; brute {cause} -- l'étoile ne servira qu'une fois la brute réactivée",
              dict(score or {}, desactivee=True))


def analyser_banger(sc: str, *, index_brutes=None, index_templates=None, corpus=None,
                    registre=None, ocr=None, lire=None) -> dict:
    """Decortique UN banger. Ne pose rien : rend les propositions.

    {sc, vues, nature, identite, identite_sure, methode, template, brute,
     texte, livraison, propositions: [{type, cle, ident, decision, raison,
     score, ...}], notes, ignore}"""
    import bangers as _bg
    t0 = time.monotonic()
    fiche = _fiche_banger(sc)
    vues, vues_detail = vues_citees(sc, fiche)
    a = {"sc": sc, "vues": vues, "vues_detail": vues_detail,
         "compte": str(fiche.get("compte") or ""), "va": str(fiche.get("va") or ""),
         "poste_le": int(fiche.get("poste_le") or 0), "url": str(fiche.get("url") or ""),
         "identite_registre": str(fiche.get("identite") or ""),
         "propositions": [], "notes": [], "ignore": ""}
    if not fiche:
        a["ignore"] = "absent du registre des bangers"
        return a
    if not a["identite_registre"]:
        # ncy.prs, rafael265782 : comptes hors equipe (contenu en francais).
        a["ignore"] = f"compte @{a['compte']} hors équipe (aucune identité)"
        return a
    video = _bg.chemin_video(sc)
    if not _bg.video_presente(sc):
        a["ignore"] = "vidéo pas encore archivée"
        return a
    bf, err = lire_images(video, FPS_BANGER, duree=SECONDES_BANGER)
    if len(bf) < 10:
        a["ignore"] = f"vidéo illisible ({err or 'trop peu d images'})"
        return a
    if err:
        a["notes"].append(f"lecture partielle du banger : {err}")
    registre = registre if registre is not None else charger()

    # 1) LA LIVRAISON : la recette exacte, si le bot l'a notee.
    liv = trouver_livraison(bf, a["poste_le"])
    a["livraison"] = {k: v for k, v in liv.items() if k != "livraison"}
    if liv.get("livraison"):
        a["livraison"]["id"] = liv["livraison"].get("id")
    if liv["decision"] == "sur":
        a["methode"] = "recette"
        _depuis_recette(a, liv["livraison"], video, corpus, ocr, bf=bf,
                        index_brutes=index_brutes, index_templates=index_templates, lire=lire)
    else:
        a["methode"] = "empreinte"
        if liv["decision"] == "a_confirmer":
            a["notes"].append(f"une livraison ressemble (médiane {liv['med']}, écart {liv['marge']}) "
                              "sans être sûre : analyse à l'image")
        _depuis_empreintes(a, bf, video, index_brutes, index_templates, corpus,
                           registre, ocr, lire)
    a["duree_s"] = round(time.monotonic() - t0, 1)
    return a


def _proposer(a: dict, type_: str, cle: str, ident: str, decision: str, raison: str,
              score: dict, **extra) -> None:
    a["propositions"].append(dict({"type": type_, "cle": cle, "ident": ident,
                                   "decision": decision, "raison": raison,
                                   "score": score}, **extra))


def _textes_template(rel: str) -> List[str]:
    """Les textes du brouillon d'un template (« x.montage.json » a cote de la
    video). Une copie sans brouillon prend celui d'une autre copie du meme
    nom : le partage copie le brouillon, mais pas les copies plus anciennes."""
    p = dossier_identites() / rel
    brouillons = [p.with_suffix(".montage.json")]
    try:
        brouillons += sorted(dossier_identites().glob(f"*/templates/{p.stem}.montage.json"))
    except (OSError, ValueError):
        pass
    for b in brouillons:
        m = safe_json.load(b, default=None) if b.is_file() else None
        if not isinstance(m, dict):
            continue
        textes = [str(s["text"]) for s in _segments(m) if str(s.get("text") or "").strip()]
        if textes:
            return textes
    return []


def verifier_template(bf: List[Tuple[int, bool]], cle: str, index_templates=None,
                      video=None, ocr=None) -> dict:
    """La recette dit « ce template » : est-il VRAIMENT dans le banger ?

    La livraison retrouvee prouve que le banger RESSEMBLE a la video livree
    (mediane de 20 images), pas que chaque ingredient y est : sur un montage
    dont la partie template est courte, la partie brute domine la mediane,
    et B + T2 recevait l'etoile de T. On reconnait donc la partie 2 de CE
    template a l'image (chercher_template, memes seuils qu'au rattrapage).
    Un template sans partie visible (la brute le remplace en entier) se
    reconnait a son texte : celui de son brouillon, retrouve par Tesseract.
    Ni l'un ni l'autre : « À confirmer ». {decision, par, raison, ...}"""
    rel = cle.replace("|", "/")
    res = {"decision": "rien", "cle": cle}
    if not (dossier_identites() / rel).is_file():
        res["raison"] = "template absent du vault"
        return res
    ims = (index_templates or {}).get(rel)
    if not ims:
        ims = lire_images(dossier_identites() / rel, FPS_INDEX["templates"],
                          duree=SECONDES_INDEX["templates"])[0]
    t = chercher_template(bf, {rel: ims}) if bf and ims else {"decision": "rien", "candidats": []}
    if t.get("candidats"):
        res.update({k: v for k, v in t.items() if k != "candidats"}, par="image")
        if t["decision"] != "sur":
            res["raison"] = f"partie 2 du template pas reconnue à l'image (médiane {t.get('med')})"
        return res
    # Aucune partie a comparer a l'image : le texte du brouillon.
    textes = _textes_template(rel)
    if not textes:
        res["raison"] = "template sans partie visible ni texte : rien pour le vérifier"
        return res
    corpus = [{"texte": x, "cle": _cle_texte(x), "source": "template",
               "ident": rel.split("/")[0], "ref": rel} for x in textes if _cle_texte(x)]
    tx = chercher_texte(video, corpus, ocr=ocr)
    res.update(par="texte", rappel=tx.get("rappel"), lu=str(tx.get("lu") or "")[:120])
    if tx.get("cle") and float(tx.get("rappel") or 0) >= TEXTE_A_COPIER:
        res["decision"] = "sur"
    elif tx["decision"] == "non_lu":
        res["raison"] = f"texte du template non lu : {tx.get('erreur')}"
    else:
        res["raison"] = ("texte du brouillon du template pas retrouvé sur l'image"
                         + (f" (lu « {res['lu'][:60]} »)" if res["lu"] else " (aucun texte lu)"))
    return res


def verifier_brute(bf: List[Tuple[int, bool]], cle: str, tpl: dict, index_brutes=None,
                   lire=None) -> dict:
    """La recette dit « cette brute » : est-elle VRAIMENT dans le banger ?

    Meme raison que verifier_template : la ressemblance d'ensemble ne prouve
    pas l'ingredient. Deux preuves, dans l'ordre :
      1. la partie brute du banger colle a CETTE brute (score_dense) sous la
         mediane la plus stricte de BRUTE_SUR (25) : les sosies (autre prise,
         meme tenue) n'y sont jamais descendus a la calibration (30 a 78) ;
      2. sinon, la recherche dans TOUT le vault (chercher_brute, BRUTE_SUR
         avec l'ecart au 2e) la designe, elle ou une jumelle.
    Rien des deux : « À confirmer », avec ce que l'image designe."""
    rel = cle.replace("|", "/")
    lire = lire or (lambda r: lire_images(dossier_identites() / r, FPS_BANGER,
                                          duree=SECONDES_DENSE)[0])
    res = {"decision": "rien", "cle": cle}
    if not (dossier_identites() / rel).is_file():
        res["raison"] = "brute absente du vault"
        return res
    q = _partie_brute(bf, tpl)
    if len(q) < 3:
        res["raison"] = "trop peu d'images du banger à comparer"
        return res
    s = score_dense(q, lire(rel))
    if s:
        res.update(s)
        if s["med"] <= BRUTE_SUR[0][0] and s["n"] >= BRUTE_MIN_IMAGES:
            res.update(decision="sur", par="image")
            return res
    if index_brutes is None:
        index_brutes = charger_index("brutes")
    br = chercher_brute(bf, tpl, index_brutes, lire=lire) if index_brutes else {"decision": "rien"}
    res["recherche"] = {k: br.get(k) for k in ("decision", "rel", "med", "marge", "n")}
    if br["decision"] == "sur" and (br.get("rel") == rel or rel in (br.get("jumelles") or [])):
        res.update(decision="sur", par="vault", med=br.get("med"), marge=br.get("marge"),
                   n=br.get("n"))
        return res
    res["decision"] = "a_confirmer"
    if br.get("rel") and br.get("rel") != rel and br["decision"] in ("sur", "a_confirmer"):
        res["raison"] = f"l'image désigne plutôt {br['rel']} (médiane {br.get('med')})"
    elif s:
        res["raison"] = f"brute pas reconnue à l'image (médiane {s['med']} sur {s['n']} images)"
    else:
        res["raison"] = "brute pas comparable à l'image"
    return res


def _depuis_recette(a: dict, liv: dict, video, corpus, ocr, bf=None, index_brutes=None,
                    index_templates=None, lire=None) -> None:
    """Les propositions d'un banger relie a SA livraison.

    LA RECETTE EST UNE HYPOTHESE, confirmee ingredient par ingredient.
    trouver_livraison compare 20 images et prend la mediane : il prouve que le
    banger ressemble a la video livree, pas que chaque ingredient y figure.
    Avant, la brute, le template et la caption incrustee de la recette
    passaient en « sûr » sans autre preuve : VA1 recoit la brute B nue et
    ecrit la caption Y ; VA2 a recu B avec X incrustee ; le banger de VA1
    (B + Y) est a +8 a +16 bits de B + X -- sous le seuil -- et X etait
    etoilee au nom de VA2 alors que le texte du banger est Y. Chaque
    ingredient a donc sa preuve : la brute et le template a l'image
    (verifier_brute, verifier_template), la caption par Tesseract restreint a
    CE texte. Sans preuve : « À confirmer », avec la raison."""
    score = {"livraison": liv.get("id"), "med": a["livraison"].get("med"),
             "marge": a["livraison"].get("marge")}
    brute, tpl = liv.get("brute") or "", liv.get("template") or ""
    ident = (brute.split("|")[0] if brute else "") or liv.get("model") or liv.get("identite") or ""
    cap_incrustee = bool((liv.get("caption") or {}).get("texte")) and \
        (liv.get("caption") or {}).get("mode") != "a_copier"
    a.update(identite=ident, identite_sure=bool(ident), nature=(
        "montage" if tpl else "brute + caption" if cap_incrustee else
        "reel prêt" if liv.get("reel") else "brute seule" if brute else
        "autre vidéo livrée"))
    raison = f"livraison du {time.strftime('%d/%m %H:%M', time.localtime(int(liv.get('le') or 0)))}"
    if liv.get("va_nom"):
        raison += f" à {liv['va_nom']}"
    if bf is None:
        # Appel direct (sans analyser_banger) : l'image est lue ici. Une video
        # illisible ne prouve rien -- tout part en « À confirmer ».
        bf = lire_images(video, FPS_BANGER, duree=SECONDES_BANGER)[0] \
            if video and Path(str(video)).is_file() else []
    repli = bool(tpl and liv.get("repli") and not brute)

    # --- le template d'abord : sa partie 2 dit ou s'arrete la brute -------------
    vt = {"decision": "rien"}
    if tpl and not repli:
        vt = verifier_template(bf, tpl, index_templates, video=video, ocr=ocr)
        a["template"] = {k: v for k, v in vt.items() if k != "candidats"}
    tpl_img = vt if vt.get("par") == "image" and vt.get("decision") == "sur" else {"decision": "rien"}

    # --- la brute -----------------------------------------------------------------
    brute_ok = True
    if brute and _desactivee(brute.replace("|", "/")):
        _proposer_brute_desactivee(a, brute, ident, raison, score)
    elif brute:
        vb = verifier_brute(bf, brute, tpl_img, index_brutes, lire)
        brute_ok = vb["decision"] == "sur"
        a["brute"] = {k: v for k, v in vb.items() if k != "candidats"}
        sb = dict(score, brute_med=vb.get("med"), brute_n=vb.get("n"), brute_par=vb.get("par"))
        if vb["decision"] == "sur":
            _proposer(a, "brute", brute, ident, "sur",
                      raison + f" (brute reconnue à l'image, médiane {vb.get('med')})", sb)
        else:
            a["notes"].append(f"brute {brute.split('|')[-1]} de la recette pas confirmée à "
                              f"l'image : {vb.get('raison')}")
            _proposer(a, "brute", brute, ident, "a_confirmer",
                      raison + f" ; brute pas confirmée à l'image ({vb.get('raison')})", sb)
    elif liv.get("brute_nom"):
        a["notes"].append(f"brute {liv['brute_nom']} livrée hors du vault : pas d'étoile possible")
    elif tpl and not repli:
        # Montage SANS brute notee (stock fabrique avant le 27/09 : sa fiche
        # n'a pas « brutes »). Avant, seul le template etait etoile, sans
        # chercher la brute ni dire qu'elle manquait.
        a["notes"].append("brute inconnue de la recette : cherchée à l'image")
        idx = index_brutes if index_brutes is not None else charger_index("brutes")
        br = chercher_brute(bf, tpl_img, idx, lire=lire) if bf and idx else \
            {"decision": "rien", "raison": "aucune image ou aucun index"}
        a["brute"] = {k: v for k, v in br.items() if k not in ("preselection", "candidats")}
        a["notes"] += br.get("notes") or []
        if br["decision"] in ("sur", "a_confirmer"):
            ib, _s, nom = br["rel"].split("/", 2)
            cle_b = f"{ib}|brutes|{nom}"
            sb = dict(score, brute_med=br.get("med"), brute_marge=br.get("marge"))
            rb = (raison + f" ; brute absente de la recette, "
                  + ("reconnue" if br["decision"] == "sur" else "probable")
                  + f" à l'image (médiane {br.get('med')}, écart {br.get('marge')} au 2e)")
            if _desactivee(br["rel"]):
                _proposer_brute_desactivee(a, cle_b, ib, rb, sb)
            else:
                _proposer(a, "brute", cle_b, ib, br["decision"], rb, sb)
        else:
            a["notes"].append("brute inconnue de la recette et introuvable à l'image"
                              + (f" ({br['raison']})" if br.get("raison") else ""))

    # --- le template ----------------------------------------------------------------
    if repli:
        # Livree SANS brute (le montage avait echoue : template entier, avec
        # l'accroche d'une autre creatrice). Qu'elle ait fait des vues ne dit
        # pas qu'il faut la refaire : au proprietaire de trancher.
        _proposer(a, "template", tpl, tpl.split("|")[0], "a_confirmer",
                  raison + " : vidéo livrée SANS brute (template entier)", score)
    elif tpl and vt["decision"] == "sur":
        # La copie EXACTE qui a servi (celle de la reserve pendant un clic
        # ✨ General) est etoilee en plus de celle de la model.
        _proposer_template(a, tpl.split("|")[2], ident, "sur",
                           raison + (" (template reconnu au texte)" if vt.get("par") == "texte"
                                     else " (template reconnu à l'image)"),
                           dict(score, tpl_med=vt.get("med"), tpl_par=vt.get("par")),
                           copie_vue=tpl, inclure_vue=True)
    elif tpl:
        # UNE ligne a trancher (la copie de la model si elle l'a, sinon celle
        # qui a servi) : valider la recopie pas d'office dans les reserves.
        nom = tpl.split("|")[2]
        copie = (f"{ident}|templates|{nom}" if ident and
                 (dossier_identites() / ident / "templates" / nom).is_file() else tpl)
        a["notes"].append(f"template {nom} de la recette pas confirmé : {vt.get('raison')}")
        _proposer(a, "template", copie, copie.split("|")[0], "a_confirmer",
                  raison + f" ; template pas confirmé ({vt.get('raison')})",
                  dict(score, tpl_med=vt.get("med"), tpl_par=vt.get("par")))
    if liv.get("reel"):
        a["notes"].append("reel prêt livré : rien à proposer "
                          "(l'étoile des reels publie sur Discord)")
    if liv.get("media") or liv.get("media_nom"):
        a["notes"].append(f"vidéo livrée hors brutes/templates "
                          f"({liv.get('media') or liv.get('media_nom')}) : rien à étoiler")
    cap = liv.get("caption") or {}
    if cap.get("texte") and cap.get("mode") != "a_copier":
        # La caption INCRUSTEE par le bot : Tesseract doit la retrouver, et
        # seulement elle (corpus restreint a ce texte, meme seuil qu'une
        # caption « a copier »). L'image ne distingue pas X de Y.
        seul = [{"texte": cap["texte"], "cle": _cle_texte(cap["texte"]), "source": "bibliotheque",
                 "ident": cap.get("ident") or "", "ref": cap.get("id")}]
        t = chercher_texte(video, seul, ocr=ocr)
        a["texte"] = {k: v for k, v in t.items() if k != "items"}
        stx = dict(score, rappel=t.get("rappel"), precision=t.get("precision"))
        if t.get("cle") and float(t.get("rappel") or 0) >= TEXTE_A_COPIER:
            _proposer_caption(a, cap["texte"], ident, "sur",
                              raison + " (caption incrustée, retrouvée sur l'image)", stx)
        else:
            pourquoi = (f"texte non lu : {t.get('erreur')}" if t["decision"] == "non_lu" else
                        f"lu « {str(t.get('lu') or '')[:60]} »" if t.get("lu") else "aucun texte lu")
            a["notes"].append(f"caption incrustée de la recette pas retrouvée sur l'image "
                              f"({pourquoi}) : à confirmer")
            _proposer_caption(a, cap["texte"], ident, "a_confirmer",
                              raison + f" (caption incrustée NON retrouvée sur l'image : {pourquoi})",
                              stx)
        return
    if tpl or not brute:
        return                  # un montage porte le texte de son template
    # UNE BRUTE LIVREE SANS TEXTE INCRUSTE : le VA a pu ecrire une caption
    # dans Instagram -- celle qu'on lui proposait « a copier », ou une autre.
    # Seul Tesseract peut le dire. Sans cette lecture, un banger « brute +
    # caption » ne d'une brute livree nue passait pour « brute seule ».
    corpus = list(corpus if corpus is not None else corpus_textes())
    if cap.get("texte"):
        corpus.append({"texte": cap["texte"], "cle": _cle_texte(cap["texte"]),
                       "source": "bibliotheque", "ident": cap.get("ident") or "",
                       "ref": cap.get("id")})
    t = chercher_texte(video, corpus, ocr=ocr)
    a["texte"] = {k: v for k, v in t.items() if k != "items"}
    origine = False
    if t["decision"] in ("sur", "a_confirmer", "inconnu"):
        rel = brute.replace("|", "/")
        origine, pourquoi = texte_de_la_brute(t.get("lu") or "", rel,
                                              float(t.get("t") or INSTANTS_OCR[0])
                                              + float(liv.get("brute_debut") or 0), ocr=ocr)
        if origine:
            a["texte"]["origine"] = pourquoi
            a["notes"].append(f"texte déjà présent dans la brute ({pourquoi}) : pas une caption")
    if t["decision"] == "non_lu":
        a["nature"] = "brute (texte non lu)"
        a["notes"].append(f"texte non lu : {t.get('erreur')}")
        return
    if origine or t["decision"] not in ("sur", "a_confirmer"):
        if cap.get("texte"):
            a["notes"].append("caption proposée au VA mais pas retrouvée sur l'image : "
                              "il ne l'a pas utilisée")
        if t["decision"] == "inconnu" and not origine:
            a["nature"] = "brute + texte inconnu"
            a["notes"].append(f"texte lu mais absent des bibliothèques : « {t.get('lu', '')[:80]} »")
        return
    a["nature"] = "brute + caption"
    stx = dict(score, rappel=t.get("rappel"), precision=t.get("precision"))
    la_proposee = bool(cap.get("texte")) and (
        t.get("cle") == _cle_texte(cap["texte"])
        or SequenceMatcher(None, t.get("cle") or "", _cle_texte(cap["texte"])).ratio() >= VARIANTE)
    if la_proposee and t.get("rappel", 0) >= TEXTE_A_COPIER:
        # La recette restreint le choix a CE texte : il suffit de le retrouver.
        _proposer_caption(a, cap["texte"], ident, "sur",
                          raison + " (caption à copier, retrouvée sur l'image)", stx)
    else:
        # Un texte pris dans TOUTES les bibliotheques : l'identite ou l'etoiler
        # vient de la recette, donc de la brute. Brute pas confirmee a
        # l'image, identite pas sure : a confirmer (comme au rattrapage).
        _proposer_caption(a, t.get("texte") or "", ident,
                          t["decision"] if brute_ok else "a_confirmer",
                          raison + f" (texte écrit par le VA, rappel {t.get('rappel')}, "
                                   f"précision {t.get('precision')})"
                          + ("" if brute_ok else ", brute pas confirmée"), stx)


def _proposer_template(a: dict, nom: str, ident: str, decision: str, raison: str,
                       score: dict, copie_vue: str = "", inclure_vue: bool = False) -> None:
    """La copie de l'identite, plus celles des reserves liees qui l'ont.

    Le meme template est copie dans 11 a 16 identites, et l'etoile vaut PAR
    copie : on etoile celle de l'identite de la brute (et de ses reserves),
    pas toutes. `inclure_vue` : la recette dit quelle copie a servi, on
    l'etoile aussi."""
    cibles = [ident] + _reserves(ident) if ident else []
    if inclure_vue and copie_vue and copie_vue.split("|")[0] not in cibles:
        cibles.append(copie_vue.split("|")[0])
    poses = 0
    for i in cibles:
        if (dossier_identites() / i / "templates" / nom).is_file():
            _proposer(a, "template", f"{i}|templates|{nom}", i, decision, raison, score)
            poses += 1
    if not poses:
        # Le template existe ailleurs (il est copie dans 11 a 16 identites) :
        # on ne choisit pas la copie a la place du proprietaire.
        prop = copie_vue or ""
        _proposer(a, "template", prop, prop.split("|")[0] if prop else "", "a_confirmer",
                  (f"template absent de {ident}" if ident else "identité inconnue")
                  + " : quelle copie étoiler ?", score)


def _proposer_caption(a: dict, texte: str, ident: str, decision: str, raison: str,
                      score: dict) -> None:
    """Dans l'identite, puis recopiee dans ses reserves liees. Une caption
    « À confirmer » n'est proposee qu'une fois (l'identite) : la valider la
    recopie dans les reserves (trancher), sans une ligne par reserve a
    trancher en double."""
    cibles = [ident] + (_reserves(ident) if decision == "sur" else [])
    for i in cibles:
        _proposer(a, "caption", f"{i}|captions|{_cle_texte(texte)[:120]}", i, decision,
                  raison + ("" if i == ident else f" (réserve liée à {ident})"), score,
                  texte=texte)


def _depuis_empreintes(a: dict, bf, video, index_brutes, index_templates, corpus,
                       registre, ocr, lire) -> None:
    index_templates = index_templates if index_templates is not None else charger_index("templates")
    index_brutes = index_brutes if index_brutes is not None else charger_index("brutes")
    corpus = corpus if corpus is not None else corpus_textes()

    tpl = chercher_template(bf, index_templates)
    a["template"] = {k: v for k, v in tpl.items() if k != "candidats"}
    br = chercher_brute(bf, tpl, index_brutes, lire=lire)
    a["brute"] = br
    a["notes"] += br.get("notes") or []
    tx = chercher_texte(video, corpus, ocr=ocr)
    a["texte"] = {k: v for k, v in tx.items() if k != "items"}

    # --- l'identite : celle de la brute retrouvee ------------------------
    ident, sure = "", False
    if br["decision"] in ("sur", "a_confirmer"):
        ident = br["rel"].split("/")[0]
        sure = br["decision"] == "sur"
    indice, n_indice = _identite_du_compte(a["compte"], registre)
    if not ident and indice:
        ident = indice
        a["notes"].append(f"identité proposée d'après les {n_indice} autre(s) banger(s) "
                          f"sûr(s) de @{a['compte']}")
    a.update(identite=ident, identite_sure=sure)

    # --- texte d'origine de la brute ? -------------------------------------
    origine = False
    if tx["decision"] in ("sur", "a_confirmer", "inconnu") and br.get("rel") \
            and br["decision"] in ("sur", "a_confirmer"):
        t_lu = float(tx.get("t") or INSTANTS_OCR[0])
        origine, pourquoi = texte_de_la_brute(tx.get("lu") or "", br["rel"],
                                              t_lu + float(br.get("decalage") or 0), ocr=ocr)
        if origine:
            a["texte"]["origine"] = pourquoi
            a["notes"].append(f"texte déjà présent dans la brute ({pourquoi}) : pas une caption")

    # --- le texte appartient-il au template reconnu ? -----------------------
    du_template = False
    if tpl["decision"] == "sur" and tx["decision"] in ("sur", "a_confirmer"):
        # Compare sur le NOM SANS EXTENSION : le brouillon s'appelle
        # « x.montage.json », la video « x.mp4 ». Compare avec l'extension,
        # le texte du template reconnu (« Sending him videos of my... »)
        # partait en caption sur les montages -- vu sur les vrais bangers.
        noms = {Path(c).stem for c in tpl.get("copies") or []}
        du_template = bool(noms & set(tx.get("templates") or []))
        if du_template:
            a["notes"].append("texte du brouillon du template : il fait partie du template")

    # --- nature -------------------------------------------------------------
    if tpl["decision"] == "sur":
        a["nature"] = "montage"
    elif tx["decision"] in ("sur", "a_confirmer") and not origine:
        a["nature"] = "brute + caption"
    elif tx["decision"] == "non_lu":
        a["nature"] = "brute (texte non lu)"
        a["notes"].append(f"texte non lu : {tx.get('erreur')}")
    elif tx["decision"] == "inconnu" and not origine:
        a["nature"] = "brute + texte inconnu"
        a["notes"].append(f"texte lu mais absent des bibliothèques : « {tx.get('lu', '')[:80]} »")
    else:
        a["nature"] = "brute seule"
    if br["decision"] == "rien" and tpl["decision"] != "sur" and tx["decision"] not in ("sur", "a_confirmer"):
        a["nature"] = "indéterminé"

    # --- propositions ------------------------------------------------------
    sb = {"med": br.get("med"), "marge": br.get("marge"), "decalage": br.get("decalage"),
          "n": br.get("n")}
    if br["decision"] in ("sur", "a_confirmer"):
        ib, _s, nom = br["rel"].split("/", 2)
        cle = f"{ib}|brutes|{nom}"
        raison = (f"brute reconnue (médiane {br['med']}, écart {br['marge']} au 2e)"
                  if br["decision"] == "sur" else
                  f"brute probable (médiane {br['med']}, écart {br['marge']} au 2e)")
        if _desactivee(br["rel"]):
            _proposer_brute_desactivee(a, cle, ib, raison, sb)
        else:
            _proposer(a, "brute", cle, ib, br["decision"], raison, sb)
    elif br.get("candidats"):
        a["notes"].append(f"brute introuvable (meilleure : médiane {br['candidats'][0]['med']})")
    else:
        a["notes"].append("brute introuvable : " + (br.get("raison") or "aucune candidate"))

    if tpl["decision"] in ("sur", "a_confirmer"):
        st = {"med": tpl.get("med"), "gap": tpl.get("gap"), "n": tpl.get("n")}
        nom = tpl["copies"][0].split("/")[-1]
        vue = tpl["copies"][0].replace("/", "|")
        if ident and sure and tpl["decision"] == "sur":
            _proposer_template(a, nom, ident, "sur",
                               f"partie 2 du template reconnue (médiane {tpl['med']})", st,
                               copie_vue=vue)
        else:
            # template sur mais identite pas sure, ou template douteux
            copie = (f"{ident}|templates|{nom}" if ident and
                     (dossier_identites() / ident / "templates" / nom).is_file() else vue)
            _proposer(a, "template", copie, copie.split("|")[0], "a_confirmer",
                      (f"template probable (médiane {tpl['med']})" if tpl["decision"] != "sur"
                       else "template reconnu, mais identité pas sûre"), st)

    if tx["decision"] in ("sur", "a_confirmer") and not origine and not du_template:
        stx = {"rappel": tx.get("rappel"), "precision": tx.get("precision")}
        if not ident:
            _proposer(a, "caption", "", "", "a_confirmer",
                      "texte reconnu, identité inconnue", stx, texte=tx.get("texte"))
        else:
            dec = "sur" if (tx["decision"] == "sur" and sure) else "a_confirmer"
            raison = (f"texte lu (rappel {tx['rappel']}, précision {tx['precision']})"
                      + ("" if sure else ", identité pas sûre"))
            _proposer_caption(a, tx.get("texte") or "", ident, dec, raison, stx)


# ------------------------------------------------------------- registre --

_VERROU = threading.RLock()


def _vide() -> dict:
    return {"version": 1, "active_depuis": 0, "bangers": {}, "etoiles": [],
            "a_confirmer": [], "refus": {}, "rattrapage": {}, "index": {}, "erreurs": []}


def charger() -> dict:
    d = safe_json.load(fichier_registre(), default=None)
    if not isinstance(d, dict):
        d = _vide()
    for k, v in _vide().items():
        if not isinstance(d.get(k), type(v)):
            d[k] = v
    return d


def _ecrire(d: dict) -> bool:
    ok = bool(safe_json.write(fichier_registre(), d, indent=1))
    _oublier_compte()
    return ok


#: Les fonctions du site qui posent vraiment les etoiles (web_upload les
#: branche au demarrage). SANS elles, rien n'est pose -- et on le dit : une
#: seconde facon d'ecrire fav_brutes.json ou captions.json, a cote de celle
#: du site, finirait par ecraser l'une ou l'autre.
#:   brute(cle, allumer) -> (ok, erreur)          fav_brutes.json, SANS Discord
#:   brutes_etoilees() -> set                     cles actuellement etoilees
#:   caption(ident, texte, allumer, retirer_ajoutee=False, cid="") ->
#:        {"ok", "id", "ajoutee", "deja", "desactivee", "erreur"}
#:   caption_etoilee(ident, texte) -> bool
APPLICATEURS: Dict[str, Callable] = {}


def brancher(**fonctions) -> None:
    APPLICATEURS.update(fonctions)


def _refus_cle(type_: str, cle: str) -> str:
    return f"{type_}#{cle}"


def _refus_de(reg: dict, type_: str, cle: str, texte: str = "") -> str:
    """La cle de refus qui couvre cette proposition, "" si aucune.

    Une caption se refuse avec le MEME critere que celui qui la pose :
    _caption_favori la retrouve par VARIANTE (ratio >= VARIANTE des cles sans
    emojis), et l'OCR retient l'une ou l'autre selon la lecture. Refusee sous
    sa cle exacte seulement, « so he can talk » retiree revenait par « so can
    talk » : ajoutee et ⭐ a la place, ou l'ancienne re-etoilee (reproduit
    avec les vraies fonctions du site : scratchpad/rv_fa/variante.py)."""
    if not cle:
        return ""
    rk = _refus_cle(type_, cle)
    if rk in reg["refus"]:
        return rk
    if type_ != "caption":
        return ""
    parts = cle.split("|", 2)
    if len(parts) != 3:
        return ""
    k = _cle_texte(texte)[:120] if str(texte or "").strip() else parts[2]
    if not k:
        return ""
    pref = f"caption#{parts[0]}|captions|"
    for r in reg["refus"]:
        if r.startswith(pref):
            k2 = r[len(pref):]
            if k2 and SequenceMatcher(None, k, k2).ratio() >= VARIANTE:
                return r
    return ""


def _deja_etoile(type_: str, cle: str, ident: str, texte: str) -> Optional[bool]:
    """True / False si le registre a pu etre LU ; None dans le doute.

    Les fonctions du site rendent None pour un registre illisible : un
    ensemble vide aurait fait conclure « etoile retiree a la main » -- un
    refus DEFINITIF pour une etoile que personne n'a retiree."""
    try:
        if type_ in ("brute", "template"):
            etoilees = APPLICATEURS["brutes_etoilees"]()
            return None if etoilees is None else cle in etoilees
        v = APPLICATEURS["caption_etoilee"](ident, texte)
        return None if v is None else bool(v)
    except KeyError:
        return None
    except Exception:                                         # noqa: BLE001
        return None


def _poser(type_: str, cle: str, ident: str, texte: str, allumer: bool = True,
           retirer_ajoutee: bool = False, cid: str = "") -> dict:
    try:
        if type_ in ("brute", "template"):
            ok, err = APPLICATEURS["brute"](cle, allumer)
            return {"ok": bool(ok), "erreur": err or ""}
        return APPLICATEURS["caption"](ident, texte, allumer,
                                       retirer_ajoutee=retirer_ajoutee, cid=cid)
    except KeyError:
        return {"ok": False, "erreur": "fonctions du site non branchées : rien n'est posé"}
    except Exception as e:                                    # noqa: BLE001
        return {"ok": False, "erreur": f"{type(e).__name__}: {e}"[:200]}


def _id() -> str:
    return uuid.uuid4().hex[:10]


def niveau(e: dict) -> str:
    """« sur » ou « probable » : l'ordre de la liste « À vérifier ».

    Les lignes d'avant le 27/09 apres-midi n'ont pas le champ : elles etaient
    toutes « À confirmer », donc « probable »."""
    n = str(e.get("niveau") or "")
    if n in ("sur", "probable"):
        return n
    return "sur" if e.get("decision") == "sur" else "probable"


def cibles(e: dict) -> List[Tuple[str, str, str]]:
    """[(type, cle, ident)] : tout ce que Valider posera pour cette ligne.

    Une ligne porte TOUTES les copies que la pose automatique etoilait
    ensemble (la caption et ses reserves liees, le template et ses copies) :
    le proprietaire tranche l'objet une fois, pas chaque copie. Une ligne
    d'avant (sans « cibles ») n'a que sa cle."""
    out, vus = [], set()
    for x in e.get("cibles") or []:
        if isinstance(x, (list, tuple)) and len(x) == 2 and x[0] and x[0] not in vus:
            vus.add(x[0])
            out.append((e.get("type") or "", str(x[0]), str(x[1] or "")))
    if not out and e.get("cle"):
        out = [(e.get("type") or "", e["cle"], e.get("ident") or "")]
    return out


def _objet(type_: str, ident: str, cle: str, texte: str = "") -> tuple:
    """CE QUE LE PROPRIETAIRE TRANCHE : une brute ; un template POUR une
    identite ; une caption POUR une identite (sans identite : le texte seul).

    Deux bangers qui proposent le meme objet partagent UNE ligne. Avant, la
    ligne se retrouvait par N'IMPORTE QUELLE de ses cles : or une reserve
    (Blonde, Brune...) est liee a plusieurs models, et la caption « probable »
    de mod_a et la caption « sûre » de mod_b (meme texte) se rejoignaient par
    la cle de la reserve -- une seule ligne, passee « sûr », que « Valider
    les sûres » etoilait dans mod_a sur une preuve seulement probable, en
    presentant mod_b comme une « réserve »."""
    cle = cle or ""
    if type_ == "caption" and str(texte or "").strip():
        return ("caption", (ident or "") if cle else "", _cle_texte(texte)[:120])
    if not cle:
        # Rien pour reconnaitre l'objet : une ligne a part, jamais fusionnee
        # avec une autre ligne sans cle (qui parlerait d'autre chose).
        return (type_ or "", "?" + uuid.uuid4().hex)
    if type_ == "template":
        return ("template", ident or "", cle.split("|")[-1])
    if type_ == "caption":
        return ("caption", ident or "", cle.split("|")[-1])
    return (type_ or "", cle)


def _objet_ligne(e: dict) -> tuple:
    o = e.get("objet")
    if isinstance(o, (list, tuple)) and o:
        return tuple(o)
    # Ligne ecrite avant ce champ : son identite principale en tient lieu.
    return _objet(e.get("type") or "", e.get("ident") or "", e.get("cle") or "", e.get("texte") or "")


def _cle_sans_identite(texte: str) -> str:
    """La cle sous laquelle se REFUSE une caption lue sans identite (pas de
    bibliotheque ou la poser). Sans elle, refuser la ligne ne retenait rien :
    le banger suivant au meme texte la reproposait. Meme forme que les autres
    (« |captions|<texte> ») : _refus_de y retrouve aussi les variantes."""
    k = _cle_texte(texte)[:120] if str(texte or "").strip() else ""
    return f"|captions|{k}" if k else ""


def _grouper(propositions: list) -> List[List[dict]]:
    """Les propositions d'une analyse, UNE ligne par objet : la brute ; le
    template (copies de l'identite, de ses reserves, et celle qui a servi) ;
    la caption (identite puis reserves liees). _proposer_template et
    _proposer_caption en font une par copie : c'etait l'unite de la pose
    automatique, pas celle d'une decision du proprietaire."""
    groupes: Dict[tuple, List[dict]] = {}
    for p in propositions:
        if not isinstance(p, dict):
            continue
        t, cle = p.get("type") or "", p.get("cle") or ""
        if t == "template" and cle:
            k = (t, cle.split("|")[-1])
        elif t == "caption" and str(p.get("texte") or "").strip():
            k = (t, _cle_texte(p.get("texte"))[:120], bool(cle))
        else:
            k = (t, cle or id(p))
        groupes.setdefault(k, []).append(p)
    return list(groupes.values())


def appliquer(a: dict) -> dict:
    """Range les propositions d'une analyse dans « À vérifier ». NE POSE RIEN.

    Demande du proprietaire du 27/09/2026 : plus aucune etoile automatique,
    « juste une notif a verifier ». Ce qui etait pose d'office devient une
    ligne de niveau « sûr », le reste une ligne « probable » ; Valider (trancher)
    pose ensuite exactement ce que la pose automatique posait.

    Ce qui ne donne PAS de ligne, avec sa trace sur la ligne du banger :
      - une cle refusee (variante du texte comprise), ou une etoile validee
        puis retiree a la main sur le site (le refus est alors memorise) ;
      - une cle deja ⭐ (par le proprietaire ou une validation).
    Un objet deja en attente (propose par un autre banger) ne se double pas :
    la ligne existante gagne ce banger, et passe « sûr » si celui-ci l'est.

    Rend {posees (toujours 0), deja, a_confirmer (lignes creees), refusees,
    erreurs}."""
    bilan = {"posees": 0, "deja": 0, "a_confirmer": 0, "refusees": 0, "erreurs": 0}
    now = int(time.time())
    with _VERROU:
        reg = charger()
        sc = a.get("sc") or ""
        ligne = {"le": now, "vues": a.get("vues"), "vues_detail": a.get("vues_detail"),
                 "compte": a.get("compte"), "va": a.get("va"), "url": a.get("url"),
                 "nature": a.get("nature") or "", "identite": a.get("identite") or "",
                 "identite_sure": bool(a.get("identite_sure")),
                 "methode": a.get("methode") or "", "notes": list(a.get("notes") or [])[:12],
                 "ignore": a.get("ignore") or "", "duree_s": a.get("duree_s"),
                 "etat": "ignore" if a.get("ignore") else "fait"}
        for k in ("brute", "template", "texte", "livraison"):
            if isinstance(a.get(k), dict):
                ligne[k] = {kk: vv for kk, vv in a[k].items()
                            if kk not in ("preselection", "candidats", "lectures", "items")}
        actives = {(e["type"], e["cle"]): e for e in reg["etoiles"]
                   if isinstance(e, dict) and e.get("etat") == "posee"}
        journal_deja = {(e.get("type"), e.get("cle")) for e in reg["etoiles"]
                        if isinstance(e, dict) and e.get("etat") == "deja"}
        # L'OBJET d'une ligne en attente -> la ligne : le meme objet propose
        # par un autre banger la rejoint (_objet : jamais par la cle d'une
        # reserve partagee entre deux models).
        attente: Dict[tuple, dict] = {}
        for e in reg["a_confirmer"]:
            if isinstance(e, dict) and e.get("etat") == "attente":
                attente.setdefault(_objet_ligne(e), e)
        for groupe in _grouper(a.get("propositions") or []):
            p0 = groupe[0]
            t = p0.get("type") or ""
            texte = p0.get("texte") or ""
            niv = "sur" if all(p.get("decision") == "sur" for p in groupe) else "probable"
            obj = _objet(t, p0.get("ident") or "", p0.get("cle") or "", texte)
            membres = list(groupe)
            if t == "caption" and p0.get("cle") and p0.get("ident"):
                # Valider une caption la recopie dans les reserves liees : la
                # ligne les NOMME des maintenant (« caption + réserves visées »),
                # une caption « probable » comprise (_proposer_caption ne
                # propose alors que l'identite).
                # Par IDENTITE : une caption vaut une ligne par bibliotheque,
                # quelle que soit l'ecriture de sa cle.
                deja_la = {p.get("ident") for p in membres}
                k = _cle_texte(texte)[:120]
                for r in _reserves(p0["ident"]):
                    if r not in deja_la:
                        membres.append(dict(p0, cle=f"{r}|captions|{k}", ident=r))
            # L'OBJET REFUSE NE REVIENT PAS, SOUS AUCUNE COPIE. Refuser (ou
            # retirer) la copie de l'identite, c'est refuser l'objet pour
            # elle : avant, un template refuse en « probable » (sa seule copie)
            # revenait par la copie de la reserve des qu'un banger « sûr » le
            # proposait, et une caption refusee revenait par une reserve liee
            # apres coup. Une caption sans identite se refuse par son texte.
            cle0 = p0.get("cle") or (_cle_sans_identite(texte) if t == "caption" else "")
            rk0 = _refus_de(reg, t, cle0, texte) if cle0 else ""
            if rk0:
                # Compte par COPIE ecartee (identite + reserves), comme le
                # refus copie par copie : le bilan ne change pas de sens.
                bilan["refusees"] += len([p for p in membres if p.get("cle")]) or 1
                ligne["notes"].append(f"{t} {(cle0.split('|')[-1] or texte)[:60]} "
                                      f"({p0.get('ident') or 'sans identité'}) : refusé auparavant, "
                                      "pas reproposé")
                continue
            retenues: List[list] = []
            retiree_identite = False
            for p in membres:
                cle, ident = p.get("cle") or "", p.get("ident") or ""
                if not cle:
                    continue
                rk = _refus_de(reg, t, cle, texte) or _refus_cle(t, cle)
                if rk in reg["refus"]:
                    bilan["refusees"] += 1
                    ligne["notes"].append(f"{t} {cle.split('|')[-1][:60]} ({ident}) : "
                                          "refusé auparavant, pas reproposé")
                    continue
                deja = _deja_etoile(t, cle, ident, texte)
                ancienne = actives.get((t, cle))
                if ancienne and deja is False:
                    # Validee par le proprietaire, retiree a la main depuis :
                    # c'est un refus. Seulement sur un registre RELU (False) :
                    # dans le doute (None), la ligne est proposee.
                    ancienne["etat"] = "retiree_a_la_main"
                    reg["refus"][rk] = {"le": now, "motif": "étoile retirée à la main", "sc": sc}
                    bilan["refusees"] += 1
                    if p is p0:
                        # La copie de l'identite retiree : l'objet est refuse
                        # pour elle, ses reserves ne sont pas reproposees.
                        retiree_identite = True
                        break
                    continue
                if deja:
                    bilan["deja"] += 1
                    ligne["notes"].append(f"{t} {cle.split('|')[-1][:60]} ({ident}) : "
                                          "déjà ⭐, rien à vérifier")
                    if not ancienne and p.get("decision") == "sur" and (t, cle) not in journal_deja:
                        # Le journal garde qu'un banger SUR a confirme une
                        # etoile deja en place (« N déjà en place » a l'ecran).
                        reg["etoiles"].append({"id": _id(), "sc": sc, "vues": a.get("vues"),
                                               "type": t, "cle": cle, "ident": ident,
                                               "texte": texte, "source": a.get("methode"),
                                               "raison": p.get("raison"), "score": p.get("score"),
                                               "le": now, "etat": "deja"})
                        journal_deja.add((t, cle))
                    continue
                if cle not in {x[0] for x in retenues}:
                    retenues.append([cle, ident])
            if retiree_identite or (not retenues and any(p.get("cle") for p in groupe)):
                continue            # tout refuse ou deja ⭐ : dit sur la ligne du banger
            existante = attente.get(obj)
            if existante:
                if sc and sc not in existante.setdefault("bangers", []):
                    existante["bangers"].append(sc)
                connues = {c for _t, c, _i in cibles(existante)}
                if not existante.get("cibles"):
                    existante["cibles"] = [[c, i] for _t, c, i in cibles(existante)]
                existante["cibles"] += [x for x in retenues if x[0] not in connues]
                if niv == "sur" and niveau(existante) != "sur":
                    # Un banger SUR confirme une ligne « probable » : elle
                    # passe en tete, avec la preuve de ce banger-la. Avant,
                    # l'etoile etait posee d'office ; c'est au proprietaire.
                    existante.update(niveau="sur", decision="sur", raison=p0.get("raison"),
                                     score=p0.get("score"), sc=sc, vues=a.get("vues"),
                                     url=a.get("url"), compte=a.get("compte") or "",
                                     confirme_par=sc, confirme_le=now)
                continue
            principale = retenues[0] if retenues else ["", p0.get("ident") or ""]
            e = {"id": _id(), "sc": sc, "bangers": [sc], "vues": a.get("vues"),
                 "compte": a.get("compte") or "", "url": a.get("url"), "type": t,
                 "cle": principale[0], "ident": principale[1], "cibles": retenues,
                 "texte": texte, "niveau": niv, "decision": "sur" if niv == "sur" else "a_confirmer",
                 "raison": p0.get("raison"), "score": p0.get("score"),
                 "methode": a.get("methode") or "", "le": now, "etat": "attente",
                 "objet": list(obj)}
            reg["a_confirmer"].append(e)
            attente[obj] = e
            bilan["a_confirmer"] += 1
        ligne["bilan"] = bilan
        # Plus de pose ici, donc plus d'echec de pose : un banger analyse est
        # « fait ». (« a_reprendre » reste compris a la relecture, pour une
        # ligne ecrite avant.)
        reg["bangers"][sc] = ligne
        _ecrire(reg)
    return bilan


def _noter_erreur(reg: dict, sc: str, texte: str) -> None:
    reg["erreurs"] = (reg.get("erreurs") or [])[-49:] + [{"le": int(time.time()), "sc": sc,
                                                           "erreur": str(texte)[:240]}]


def _trouver(liste: list, eid: str) -> Optional[dict]:
    return next((e for e in liste if e.get("id") == eid), None)


def annuler(eid: str, par: str = "") -> dict:
    """Retire une etoile posee depuis cette liste (Valider ; ou d'office avant
    le 27/09 apres-midi), et memorise le refus : elle ne sera plus proposee.
    Une caption qu'on avait AJOUTEE a la bibliotheque en repart (etat
    d'avant) ; une caption qui y etait deja garde son texte, sans l'etoile."""
    with _VERROU:
        reg = charger()
        e = _trouver(reg["etoiles"], eid)
        if not e:
            return {"ok": False, "erreur": "étoile inconnue"}
        if e.get("etat") != "posee":
            return {"ok": False, "erreur": "cette étoile n'a pas été posée depuis cette liste"
                    if e.get("etat") == "deja" else "déjà retirée"}
        # UN CLIC DEFAIT CE QU'UN BANGER A POSE ENSEMBLE : la caption et ses
        # copies dans les reserves, le template et ses copies. Sinon « Retirer »
        # laissait la meme caption etoilee dans Blonde, sans rien dire.
        groupe = [x for x in reg["etoiles"] if x.get("etat") == "posee"
                  and x.get("sc") == e.get("sc") and x.get("type") == e["type"]
                  and _meme_objet(x, e)]
        now = int(time.time())
        faites, erreurs, notes = 0, [], []
        for x in groupe:
            r = _poser(x["type"], x["cle"], x.get("ident") or "", x.get("texte") or "", False,
                       retirer_ajoutee=bool(x.get("ajoutee")), cid=x.get("caption_id") or "")
            if not r.get("ok"):
                erreurs.append(r.get("erreur") or "échec")
                continue
            x.update(etat="annulee", annulee_le=now, par=par)
            if r.get("note"):
                # Ce qui a ete fait A LA PLACE de ce qu'on attendait (caption
                # ajoutee introuvable par son id : rien supprime) -- dit.
                x["note_retrait"] = r["note"]
                notes.append(f"{x.get('ident') or '?'} : {r['note']}")
            reg["refus"][_refus_cle(x["type"], x["cle"])] = {"le": now, "motif": "annulée",
                                                              "sc": x.get("sc"), "par": par}
            faites += 1
        _ecrire(reg)
    if not faites:
        return {"ok": False, "erreur": erreurs[0] if erreurs else "échec"}
    return {"ok": True, "retirees": faites, "erreurs": erreurs, "notes": notes}


def _meme_objet(x: dict, e: dict) -> bool:
    """Meme brute (cle), meme template (nom de fichier), meme caption (texte)."""
    if e["type"] == "caption":
        return _cle_texte(x.get("texte")) == _cle_texte(e.get("texte"))
    if e["type"] == "template":
        return x["cle"].split("|")[-1] == e["cle"].split("|")[-1]
    return x["cle"] == e["cle"]


def trancher(eid: str, valider: bool, par: str = "") -> dict:
    """Valide ou refuse UNE ligne de « À vérifier ».

    Valider pose exactement ce que la pose automatique posait : chaque cible
    de la ligne (la brute ; la caption, ajoutee si besoin, ⭐ dans l'identite
    ET ses reserves liees ; le template et ses copies), par les fonctions du
    site, sans Discord. Une reserve qui a refuse le texte (meme en variante)
    n'est pas servie. Refuser memorise le refus de CHAQUE cible : l'objet ne
    revient pas, meme propose par un autre banger."""
    with _VERROU:
        reg = charger()
        e = _trouver(reg["a_confirmer"], eid)
        if not e:
            return {"ok": False, "erreur": "proposition inconnue"}
        if e.get("etat") != "attente":
            return {"ok": False, "erreur": "déjà tranchée"}
        now = int(time.time())
        cs = cibles(e)
        if not valider:
            e.update(etat="refuse", tranche_le=now, par=par)
            if not cs and e.get("type") == "caption" and _cle_sans_identite(e.get("texte")):
                # Caption lue SANS identite : rien a poser, mais le refus doit
                # tenir -- sinon le banger suivant au meme texte la reproposait.
                cs = [("caption", _cle_sans_identite(e.get("texte")), "")]
            for t, cle, _i in cs:
                reg["refus"][_refus_cle(t, cle)] = {"le": now, "motif": "refusée",
                                                    "sc": e.get("sc"), "par": par}
            _ecrire(reg)
            return {"ok": True, "refusees": len(cs)}
        if not e.get("cle") or not e.get("ident"):
            return {"ok": False, "erreur": "identité inconnue : rien à poser. Étoile la bonne "
                                           "copie dans la Bibliothèque, puis refuse cette ligne."}
        if e["type"] == "caption":
            # Les reserves liees d'AUJOURD'HUI aussi : un lien pose depuis la
            # proposition sert a la validation (et une ligne d'avant, sans
            # « cibles », garde sa recopie).
            k = _cle_texte(e.get("texte"))[:120]
            connues = {i for _t, _c, i in cs}
            cs += [("caption", f"{r}|captions|{k}", r) for r in _reserves(e["ident"])
                   if r not in connues]
        poses, deja_n, erreurs = [], 0, []
        for t, cle, ident in cs:
            # Refusee, meme sous une VARIANTE du texte (_refus_de) : valider
            # une caption ne la recopie pas dans une reserve qui l'a refusee.
            if _refus_de(reg, t, cle, e.get("texte") or "") and cle != e["cle"]:
                continue
            if _deja_etoile(t, cle, ident, e.get("texte") or ""):
                deja_n += 1
                continue
            r = _poser(t, cle, ident, e.get("texte") or "", True)
            if not r.get("ok"):
                erreurs.append(f"{ident or '?'} : {r.get('erreur') or 'échec'}")
                continue
            reg["etoiles"].append({"id": _id(), "sc": e.get("sc"), "vues": e.get("vues"),
                                   "type": t, "cle": cle, "ident": ident,
                                   "texte": e.get("texte") or "", "source": "validée à la main",
                                   "raison": e.get("raison"), "score": e.get("score"),
                                   "le": now, "etat": "posee", "ajoutee": bool(r.get("ajoutee")),
                                   "caption_id": r.get("id") or "", "par": par,
                                   **({"note": "caption hors tirage (désactivée)"}
                                      if r.get("desactivee") else {})})
            poses.append(cle)
        if erreurs and not poses:
            # Rien de pose (registre illisible, bibliotheque pleine...) : la
            # ligne RESTE a verifier, et l'erreur est dite au clic.
            return {"ok": False, "erreur": erreurs[0]}
        reg["refus"].pop(_refus_cle(e["type"], e["cle"]), None)
        e.update(etat="valide", tranche_le=now, par=par)
        if erreurs:
            e["non_posees"] = erreurs[:6]
        _ecrire(reg)
    return {"ok": True, "posees": len(poses), "deja": deja_n, "erreurs": erreurs}


def valider_surs(par: str = "") -> dict:
    """« Valider les sûres » : chaque ligne « sûr » en attente, comme autant de
    clics sur Valider (memes poses, meme journal). Une ligne qui echoue reste
    a verifier, et l'erreur est rendue ; les « probable » ne bougent pas."""
    with _VERROU:
        ids = [e["id"] for e in charger()["a_confirmer"]
               if isinstance(e, dict) and e.get("etat") == "attente" and niveau(e) == "sur"
               and e.get("cle") and e.get("ident") and e.get("id")]
        validees, posees, erreurs = 0, 0, []
        for eid in ids:
            r = trancher(eid, True, par=par)
            if r.get("ok"):
                validees += 1
                posees += int(r.get("posees") or 0)
                erreurs += list(r.get("erreurs") or [])
            else:
                erreurs.append(str(r.get("erreur") or "échec"))
    return {"ok": True, "lignes": len(ids), "validees": validees, "posees": posees,
            "erreurs": erreurs}


#: (fichier, taille, date, inode) -> nombre de lignes en attente. Le centre de
#: notifications le demande toutes les 5 s par page ouverte : relire et
#: decoder le registre a chaque fois pour un seul nombre couterait pour rien.
_CACHE_NB: Dict[str, object] = {"sig": None, "n": 0}


def _oublier_compte() -> None:
    _CACHE_NB.update(sig=None, n=0)


def nb_a_verifier() -> int:
    """Combien de propositions attendent le proprietaire (« À vérifier »)."""
    f = fichier_registre()
    try:
        st = f.stat()
    except OSError:
        return 0
    sig = (str(f.resolve()), st.st_size, st.st_mtime_ns, st.st_ino)
    if _CACHE_NB.get("sig") != sig:
        reg = charger()
        _CACHE_NB.update(sig=sig, n=sum(1 for e in reg["a_confirmer"]
                                        if isinstance(e, dict) and e.get("etat") == "attente"))
    return int(_CACHE_NB.get("n") or 0)


# ------------------------------------------------------------------ le fil --

_FILE: "queue.Queue" = queue.Queue()
_ETAT = {"thread": None, "en_cours": "", "depuis": 0.0, "dernier": {}, "progres": {}}
#: Entre deux passages quand rien n'arrive : empreintes des livraisons, et
#: bangers archives par un autre chemin que all-banger (publication du matin).
PERIODE_SEC = 900.0
#: Le premier passage peut calculer l'index de tout le vault (1 a 2 h de CPU
#: a nice 19, une seule fois) : pas de coupure avant.
TIMEOUT_ANALYSE_SEC = 4 * 3600
LOT = 10
#: Un banger dont l'analyse plante trois fois n'est plus retente (il reste
#: montre a l'ecran avec son erreur) : sinon il repasserait toutes les 15 min.
ESSAIS_MAX = 3


def fil_actif() -> bool:
    th = _ETAT.get("thread")
    return bool(th is not None and th.is_alive())


def reveiller() -> None:
    _FILE.put(("reveil", None))


def signaler(sc: str) -> None:
    """Un banger vient d'etre archive (all_banger.traiter_job). Non bloquant :
    on est dans le fil d'envoi du salon all-banger."""
    if sc:
        _FILE.put(("banger", str(sc)))


def demander_rattrapage(par: str = "") -> dict:
    """Relance l'analyse des bangers archives jamais analyses (bouton du site).

    Le premier rattrapage part TOUT SEUL (demarrer) depuis que plus rien n'est
    pose sans le proprietaire : il ne fait que proposer. Ce bouton ne sert
    qu'a le relancer s'il reste des bangers jamais vus."""
    with _VERROU:
        reg = charger()
        rat = reg.get("rattrapage") or {}
        if rat.get("demande_le") and not rat.get("fini_le"):
            return {"ok": True, "deja": True}
        reg["rattrapage"] = {"demande_le": int(time.time()), "par": par}
        _ecrire(reg)
    _FILE.put(("rattrapage", None))
    return {"ok": True}


#: Combien de bangers des models FR la derniere selection a laisses aux
#: salons de Va IG (bangers.pour_les_favoris), par sorte de passage (le
#: rattrapage relit les deux tour a tour) : dit au journal a chaque
#: changement, pas a chaque passage.
_HORS_FAVORIS: Dict[bool, int] = {False: 0, True: 0}


def _a_traiter(reg: dict, tous: bool) -> List[str]:
    """Les bangers archives pas encore traites. Sans `tous` : seulement ceux
    archives depuis la mise en service (le passe attend le rattrapage).

    Pas les reels des models de Va IG sous le seuil reglable : depuis le
    06/10/2026 ils sont des bangers a 1 000 vues pour LEURS salons
    (bangers.SEUIL_FR), pas pour les favoris (bangers.pour_les_favoris).
    Comptes et dits, jamais ecartes en silence."""
    import bangers as _bg
    depuis = int(reg.get("active_depuis") or 0)
    out = []
    hors = 0
    for sc, f in (_bg.charger().get("reels") or {}).items():
        e = (reg.get("bangers") or {}).get(sc) or {}
        if e.get("etat") == "fait":
            continue
        if e.get("etat") == "ignore" and e.get("ignore") != "vidéo pas encore archivée":
            continue
        if e.get("etat") == "erreur" and int(e.get("essais") or 0) >= ESSAIS_MAX:
            continue           # casse trois fois : dit a l'ecran, plus retente
        if e.get("etat") == "a_reprendre" and int(e.get("essais") or 0) >= ESSAIS_MAX:
            continue           # pose refusee trois fois : dite a l'ecran, plus retentee
        if not _bg.video_presente(sc):
            continue
        # Une pose a reprendre l'est meme hors rattrapage : le banger a deja
        # ete analyse une fois, il est dans le perimetre quel que soit son age.
        if not tous and e.get("etat") != "a_reprendre":
            try:
                if _bg.chemin_video(sc).stat().st_mtime < depuis:
                    continue
            except OSError:
                continue
        # Compte seulement ce qui aurait ete analyse (video archivee, dans le
        # perimetre du passage) ; une pose a reprendre a deja ete analysee.
        if e.get("etat") != "a_reprendre" and not _bg.pour_les_favoris(f):
            hors += 1
            continue
        out.append(sc)
    if hors != _HORS_FAVORIS.get(bool(tous), 0):
        _HORS_FAVORIS[bool(tous)] = hors
        print(f"[favoris-auto] {hors} banger(s) des models de Va IG sous {_bg.seuil()} vues "
              f"(seuil des salons Va IG : {_bg.SEUIL_FR}) laisse(s) hors des favoris", flush=True)
    return sorted(out)


def _lancer_analyse(scs: List[str]) -> Iterable[dict]:
    """Analyse dans un SOUS-PROCESSUS a nice 19 : le calcul Python (plusieurs
    secondes par banger, une heure pour le premier index) ne doit pas
    disputer le verrou de l'interpreteur au bot et au site. Rend les
    analyses au fil de l'eau (une ligne JSON par banger)."""
    cmd = _NICE + [sys.executable, str(Path(__file__).resolve()), "analyser", "--data",
                   str(_data().resolve())] + list(scs)
    # stderr dans un fichier, pas un tuyau : un tuyau plein (avertissements en
    # rafale) bloquerait l'enfant pendant qu'on lit sa sortie -- blocage mutuel.
    erreurs = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=erreurs,
                         text=True, encoding="utf-8", errors="replace",
                         cwd=str(Path.cwd()))
    minuteur = threading.Timer(TIMEOUT_ANALYSE_SEC, p.kill)
    minuteur.daemon = True
    minuteur.start()
    try:
        for ligne in p.stdout:
            try:
                msg = json.loads(ligne)
            except ValueError:
                continue
            if msg.get("type") == "progres":
                _ETAT["progres"] = msg
            elif msg.get("type") == "analyse":
                yield msg["analyse"]
        p.wait()
    finally:
        minuteur.cancel()
    try:
        erreurs.seek(0)
        err = erreurs.read()[-400:]
    finally:
        erreurs.close()
    if p.returncode:
        raise RuntimeError(f"analyse interrompue (code {p.returncode}) : {err.strip()[-240:]}")


def traiter(scs: List[str], deja: int = 0, total: int = 0) -> dict:
    """Analyse puis range les propositions, lot par lot. Rend un bilan.
    `deja` / `total` : ou en est le passage entier (rattrapage decoupe en
    lots), pour l'ecran."""
    bilan = {"analyses": 0, "posees": 0, "a_confirmer": 0, "ignores": 0, "erreurs": 0}
    vus = set()
    for i in range(0, len(scs), LOT):
        lot = scs[i:i + LOT]
        _ETAT["en_cours"] = f"{deja + i + len(lot)}/{total or len(scs)} banger(s)"
        try:
            for a in _lancer_analyse(lot):
                vus.add(a.get("sc"))
                b = appliquer(a)
                bilan["analyses"] += 1
                bilan["posees"] += b["posees"]
                bilan["a_confirmer"] += b["a_confirmer"]
                bilan["ignores"] += 1 if a.get("ignore") else 0
        except Exception as e:                                # noqa: BLE001
            bilan["erreurs"] += 1
            with _VERROU:
                reg = charger()
                for sc in lot:
                    if sc in vus:
                        continue
                    _noter_erreur(reg, sc, str(e))
                    ligne = reg["bangers"].get(sc) or {}
                    if ligne.get("etat") in (None, "erreur"):
                        reg["bangers"][sc] = {"le": int(time.time()), "etat": "erreur",
                                              "essais": int(ligne.get("essais") or 0) + 1,
                                              "erreur": str(e)[:240]}
                _ecrire(reg)
            print(f"[favoris-auto] {e}", flush=True)
    return bilan


def _tour(tous: bool = False) -> dict:
    b = {"empreintes": empreinter_attente()}
    try:
        purge = purger_livraisons()
    except Exception as e:                                    # noqa: BLE001
        purge = [{"erreur": f"{type(e).__name__}: {e}"[:160]}]
        print(f"[favoris-auto] purge des livraisons : {e}", flush=True)
    if purge:
        b["livraisons_purgees"] = purge
    reg = charger()
    if not tous:
        scs = _a_traiter(reg, False)
        if scs:
            b.update(traiter(scs))
        return b
    # LE RATTRAPAGE PASSE APRES LES NOUVEAUX. Il part tout seul et dure des
    # heures la premiere fois (index du vault, puis ~150 bangers) : d'un bloc,
    # un banger archive pendant ce temps attendait la fin de tous les anciens.
    # Lot par lot, et avant chaque lot, ce qui est arrive entre-temps passe
    # devant. Un banger n'est tente qu'une fois par passage : un lot qui
    # plante sans rien noter (« a_reprendre » d'avant) ne boucle pas.
    tentes: set = set()
    total = len(_a_traiter(reg, True))
    for _k in ("analyses", "posees", "a_confirmer", "ignores", "erreurs"):
        b[_k] = 0
    while True:
        reg = charger()
        neufs = [sc for sc in _a_traiter(reg, False) if sc not in tentes]
        anciens = [sc for sc in _a_traiter(reg, True) if sc not in tentes and sc not in neufs]
        lot = (neufs + anciens)[:LOT]
        if not lot:
            break
        tentes.update(lot)
        r = traiter(lot, deja=len(tentes) - len(lot), total=max(total, len(tentes)))
        for _k, _v in r.items():
            b[_k] = b.get(_k, 0) + _v
    with _VERROU:
        reg = charger()
        reg["rattrapage"].update(fini_le=int(time.time()), bilan=b)
        _ecrire(reg)
    return b


def demarrer() -> bool:
    """Lance LE fil (un seul par processus). Rend True s'il vient de partir."""
    with _VERROU:
        t = _ETAT.get("thread")
        if t is not None and t.is_alive():
            return False
        reg = charger()
        change = False
        if not reg.get("active_depuis"):
            # La mise en service : les bangers archives AVANT passent par le
            # rattrapage (lot par lot, apres les nouveaux).
            reg["active_depuis"] = int(time.time())
            change = True
        if not (reg.get("rattrapage") or {}).get("demande_le"):
            # UNE FOIS, TOUT SEUL : depuis le 27/09 apres-midi le rattrapage ne
            # fait plus que PROPOSER (rien n'est pose sans le proprietaire),
            # il n'y a donc plus de moment a choisir. Priorite basse : sous-
            # processus a nice 19, et les nouveaux bangers passent devant
            # (_tour). Interrompu par un redemarrage, il reprend (_boucle).
            reg["rattrapage"] = {"demande_le": int(time.time()), "par": "automatique"}
            change = True
        if change:
            _ecrire(reg)

        def _boucle():
            reg0 = charger()
            rat = reg0.get("rattrapage") or {}
            if rat.get("demande_le") and not rat.get("fini_le"):
                _FILE.put(("rattrapage", None))      # interrompu par un redemarrage
            while True:
                try:
                    try:
                        quoi, _v = _FILE.get(timeout=PERIODE_SEC)
                    except queue.Empty:
                        quoi = "periode"
                    # tout ce qui attend est traite d'un coup
                    tous = quoi == "rattrapage"
                    while True:
                        try:
                            q2, _v2 = _FILE.get_nowait()
                            tous = tous or q2 == "rattrapage"
                        except queue.Empty:
                            break
                    _ETAT.update(en_cours="passage", depuis=time.time())
                    b = _tour(tous=tous)
                    _ETAT.update(dernier=dict(b, le=int(time.time())))
                    if b.get("analyses") or (b.get("empreintes") or {}).get("faites") \
                            or b.get("livraisons_purgees"):
                        print(f"[favoris-auto] passage : {b}", flush=True)
                except Exception as ex:                        # noqa: BLE001
                    print(f"[favoris-auto] fil : {type(ex).__name__}: {ex}", flush=True)
                    time.sleep(30)
                finally:
                    _ETAT.update(en_cours="", depuis=0.0)

        t = threading.Thread(target=_boucle, daemon=True, name="favoris-auto")
        _ETAT["thread"] = t
        t.start()
    return True


def etat() -> dict:
    """Pour l'ecran : le registre et ce que fait le fil maintenant."""
    reg = charger()
    th = _ETAT.get("thread")
    return {"registre": reg, "actif": bool(th is not None and th.is_alive()),
            "en_cours": _ETAT.get("en_cours") or "", "progres": dict(_ETAT.get("progres") or {}),
            "dernier": dict(_ETAT.get("dernier") or {})}


def a_rattraper() -> int:
    """Combien de bangers archives n'ont jamais ete analyses."""
    try:
        return len(_a_traiter(charger(), tous=True))
    except Exception:                                         # noqa: BLE001
        return 0


# -------------------------------------------------------- sous-processus --


def _principal(argv: List[str]) -> int:
    """`python favoris_auto.py analyser [--data D] SC...` : met l'index a jour,
    analyse chaque banger, ecrit une ligne JSON par banger sur la sortie.
    `python favoris_auto.py index [--data D]` : l'index seul."""
    global DATA
    args = list(argv)
    if "--data" in args:
        i = args.index("--data")
        DATA = Path(args[i + 1])
        del args[i:i + 2]
    if not args:
        print("usage : favoris_auto.py analyser|index [--data D] [SC...]", file=sys.stderr)
        return 2
    cmd, scs = args[0], args[1:]
    # Le registre et les videos des bangers suivent le MEME dossier de
    # donnees : sans ca, un essai sur des donnees de test lirait les bangers
    # de production (bangers.py les situe a cote du module).
    import bangers as _bg
    _bg.FICHIER = _data() / "bangers.json"
    _bg.DOSSIER = _data() / "bangers"
    _bg.DETAILS_DIR = _data() / "bangers_details"

    def _progres(b):
        print(json.dumps({"type": "progres", **b}, ensure_ascii=False), flush=True)

    bilan = mettre_a_jour_index(progres=_progres)
    _progres(dict(bilan, fini=True))
    if cmd == "index":
        return 0
    idx_b = charger_index("brutes")
    idx_t = charger_index("templates")
    corpus = corpus_textes()
    reg = charger()
    for sc in scs:
        try:
            a = analyser_banger(sc, index_brutes=idx_b, index_templates=idx_t,
                                corpus=corpus, registre=reg)
            if bilan.get("restantes"):
                a["notes"].append(f"index incomplet ({bilan['restantes']} vidéo(s) non lues)")
            if bilan.get("echecs"):
                a["notes"].append(f"{bilan['echecs']} vidéo(s) du vault illisibles")
        except Exception as e:                                # noqa: BLE001
            a = {"sc": sc, "ignore": f"erreur d'analyse : {type(e).__name__}: {e}"[:240],
                 "propositions": [], "notes": []}
        print(json.dumps({"type": "analyse", "analyse": a}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    # Le dossier du module d'abord : safe_json, bangers, analyse_gratuite...
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(_principal(sys.argv[1:]))
