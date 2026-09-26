# -*- coding: utf-8 -*-
"""Reconnaitre une MEME video sous un autre nom : les doublons du vault.

POURQUOI CE FICHIER EXISTE

Le proprietaire, le 26/09/2026, en branchant un TikTok ou un Instagram sur une
identite qui a deja du contenu : « juste les doublons ca les met pas [...] et
si j'avais add a la main avant aussi ». Le vault ne reconnaissait une video
qu'a son numero TikTok/Instagram dans le nom du fichier : une video deposee a
la main (« IMG_2041.mov »), telechargee avec le filigrane, ou publiee sur les
DEUX reseaux, serait arrivee une seconde fois.

LE CONTENU, PAS LE NOM NI LES OCTETS

Une copie telechargee ailleurs est reencodee : ni son nom ni son md5 ne
correspondent. On compare donc ce qu'on VOIT : la duree, et huit images prises
a des instants FIXES depuis le debut (0,5 s, 1 s, 1,7 s...). Absolus et non en
pourcentage : le carton de fin que TikTok ajoute au telechargement (3 a 4 s)
decale tous les pourcentages, jamais le debut.

Chaque image est reduite a 17x16 en gris et resumee par un dHash de 256 bits
(le sens de la difference entre deux pixels voisins). Un reencodage, un
changement de resolution ou de debit n'en change que quelques bits ; deux
videos differentes d'une meme createrice, tournees dans la meme piece, en
changent des dizaines : c'est pour elles que le hash est plus fin que le
classique 8x8 (64 bits), qui les aurait confondues.

Les images unies (un noir de fondu, un blanc) ne disent rien : toutes les
videos y ont le meme hash. Elles sont ignorees, et il en faut au moins trois
informatives pour conclure.

Rien n'est jamais supprime ici : ce module ne fait que repondre « c'est la
meme que ce fichier-la » ; c'est l'appelant qui renonce a importer.
"""
from __future__ import annotations

import shutil
import statistics
import subprocess
import threading
from pathlib import Path
from typing import Iterable, Optional

import safe_json

_ICI = Path(__file__).resolve().parent
DOSSIER_CACHE = _ICI / "data" / "empreintes"

#: Instants (secondes depuis le debut) ou l'on regarde l'image.
INSTANTS = (0.5, 1.0, 1.7, 2.5, 3.5, 5.0, 7.0, 9.5)
LARGEUR, HAUTEUR = 17, 16            # 16 x 16 differences = 256 bits
#: Au-dela, deux images ne sont pas « la meme » (sur 256 bits).
BITS_MAX = 40
#: Part des images comparees qui doivent se ressembler.
PART_MIN = 0.75
MIN_IMAGES = 3
#: Ecart-type minimal (niveaux de gris) d'une image pour qu'elle compte.
RELIEF_MIN = 6.0
#: La meme video : duree egale a une demi-seconde pres, ou copie locale plus
#: longue du carton de fin qu'ajoute le telechargement TikTok.
ECART_EGAL = 0.6
CARTON_MIN, CARTON_MAX = 2.0, 5.5

EXTS_VIDEO = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv"})
#: Version de la methode de lecture des images. Les empreintes d'une autre
#: version sont recalculees : deux methodes ne tombent pas exactement sur la
#: meme image (jusqu'a 53 bits d'ecart mesures sur une video tres animee),
#: les melanger ferait rater des doublons.
#: v2 (26/09/2026) : une seule lecture de 10 s a 10 images/s, 2 a 3 fois plus
#: rapide que huit recherches (v1) -- 13 profils attendaient derriere une file.
VERSION = 2
PAS = 10                              # images par seconde lues
_NICE = ["nice", "-n", "10"] if shutil.which("nice") else []
_VERROU = threading.RLock()


# ------------------------------------------------------------------ mesures

def duree(f: Path) -> Optional[float]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(f)],
                           capture_output=True, text=True, timeout=30)
        d = float((r.stdout or "").strip())
        return d if d > 0 else None
    except Exception:
        return None


def _hash_image(px: bytes) -> list:
    bits = 0
    for y in range(HAUTEUR):
        ligne = px[y * LARGEUR:(y + 1) * LARGEUR]
        for x in range(LARGEUR - 1):
            bits = (bits << 1) | (1 if ligne[x] < ligne[x + 1] else 0)
    try:
        relief = statistics.pstdev(px)
    except Exception:
        relief = 0.0
    return [f"{bits:064x}", relief >= RELIEF_MIN]


def empreinte(f: Path, d: Optional[float] = None) -> dict:
    """{"duree": s, "v": VERSION, "images": {"0.5": [hash, informative], ...}}.

    UNE lecture des premieres secondes, a PAS images/s, dont on garde celles
    des INSTANTS -- plutot que huit recherches, qui redecodaient chacune
    depuis l'image cle precedente."""
    d = duree(f) if d is None else d
    images = {}
    if d:
        lire = min(d, max(INSTANTS) + 0.5)
        try:
            r = subprocess.run(_NICE + ["ffmpeg", "-v", "error", "-t", f"{lire:.2f}", "-i", str(f),
                                        "-vf", f"fps={PAS},scale={LARGEUR}:{HAUTEUR}:flags=area,format=gray",
                                        "-f", "rawvideo", "-"],
                               capture_output=True, timeout=120)
            px = r.stdout if r.returncode == 0 else b""
        except Exception:
            px = b""
        taille = LARGEUR * HAUTEUR
        n = len(px) // taille
        for t in INSTANTS:
            if t > d - 0.3:
                break
            k = int(round(t * PAS))
            if k >= n:
                break
            images[str(t)] = _hash_image(px[k * taille:(k + 1) * taille])
    return {"duree": d, "v": VERSION, "images": images}


# ---------------------------------------------------------------- comparaison

def durees_compatibles(a: Optional[float], b: Optional[float]) -> bool:
    if not a or not b:
        return False
    ecart = abs(a - b)
    return ecart <= ECART_EGAL or CARTON_MIN <= ecart <= CARTON_MAX


def correspond(a: dict, b: dict) -> bool:
    """Meme video ? Durees compatibles, et la plupart des images informatives
    communes a quelques bits pres."""
    if not durees_compatibles(a.get("duree"), b.get("duree")):
        return False
    ia, ib = a.get("images") or {}, b.get("images") or {}
    vues = ok = 0
    for t, (ha, infa) in ia.items():
        if t not in ib:
            continue
        hb, infb = ib[t]
        if not (infa and infb):
            continue
        vues += 1
        if bin(int(ha, 16) ^ int(hb, 16)).count("1") <= BITS_MAX:
            ok += 1
    return vues >= MIN_IMAGES and ok / vues >= PART_MIN


# ---------------------------------------------------------------------- cache

def _signature(f: Path) -> str:
    st = f.stat()
    return f"{st.st_size}-{st.st_mtime_ns}"


def _fichier_cache(dossier: Path) -> Path:
    # data/identities/<ident>/brutes -> data/empreintes/<ident>__brutes.json
    return DOSSIER_CACHE / f"{dossier.parent.name}__{dossier.name}.json"


def _cache(dossier: Path) -> dict:
    d = safe_json.load(_fichier_cache(dossier), default={})
    return d if isinstance(d, dict) else {}


def _ecrire_cache(dossier: Path, c: dict) -> None:
    try:
        DOSSIER_CACHE.mkdir(parents=True, exist_ok=True)
        safe_json.write(_fichier_cache(dossier), c)
    except Exception:
        pass    # un cache perdu se recalcule : rien a remonter


# ---------------------------------------------------------------- l'essentiel

def trouver_doublon(nouveau: Path, dossier: Path, exclure: Iterable[str] = ()) -> Optional[Path]:
    """Le fichier de `dossier` qui est la MEME video que `nouveau`, ou None.

    Les durees des fichiers du dossier sont lues une fois (ffprobe) puis
    gardees en cache, comme leurs empreintes, calculees seulement pour ceux
    dont la duree colle. `exclure` : noms de fichiers a ne pas considerer.
    """
    try:
        e_neuf = empreinte(nouveau)
    except Exception:
        return None
    if not e_neuf.get("duree"):
        return None
    exclus = set(exclure or ())
    with _VERROU:
        cache = _cache(dossier)
        change = False
        calcules = 0
        vus = set()
        trouve = None
        try:
            fichiers = sorted(p for p in dossier.iterdir()
                              if p.is_file() and p.suffix.lower() in EXTS_VIDEO)
        except OSError:
            fichiers = []
        for f in fichiers:
            vus.add(f.name)
            if f.name in exclus or f.resolve() == nouveau.resolve():
                continue
            try:
                sig = _signature(f)
            except OSError:
                continue
            c = cache.get(f.name)
            if not isinstance(c, dict) or c.get("sig") != sig:
                c = {"sig": sig, "duree": duree(f)}
                cache[f.name] = c
                change = True
            if not durees_compatibles(e_neuf["duree"], c.get("duree")):
                continue
            if "images" not in c or c.get("v") != VERSION:
                c.update(empreinte(f, c.get("duree")))
                change = True
                calcules += 1
                # au fil de l'eau : un redemarrage du bot (chaque deploiement)
                # ne perd pas un quart d'heure de calcul
                if calcules % 20 == 0:
                    _ecrire_cache(dossier, cache)
            if correspond(e_neuf, c):
                trouve = f
                break
        # un fichier parti du dossier ne garde pas son empreinte en cache
        if trouve is None:
            for nom in [n for n in cache if n not in vus]:
                cache.pop(nom, None)
                change = True
        if change:
            _ecrire_cache(dossier, cache)
    return trouve
