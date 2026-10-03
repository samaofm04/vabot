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
    err = "" if d else "durée illisible"
    if d:
        lire = min(d, max(INSTANTS) + 0.5)
        try:
            r = subprocess.run(_NICE + ["ffmpeg", "-v", "error", "-t", f"{lire:.2f}", "-i", str(f),
                                        "-vf", f"fps={PAS},scale={LARGEUR}:{HAUTEUR}:flags=area,format=gray",
                                        "-f", "rawvideo", "-"],
                               capture_output=True, timeout=120)
            px = r.stdout or b""
            if r.returncode != 0:
                err = f"ffmpeg code {r.returncode}"
        except subprocess.TimeoutExpired as e:
            # les images lues avant l'arret restent bonnes : leur rang suit le temps
            px, err = e.stdout or b"", "ffmpeg > 120 s"
        except Exception as e:
            px, err = b"", str(e)[:200]
        taille = LARGEUR * HAUTEUR
        n = len(px) // taille
        for t in INSTANTS:
            if t > d - 0.3:
                break
            k = int(round(t * PAS))
            if k >= n:
                break
            images[str(t)] = _hash_image(px[k * taille:(k + 1) * taille])
    if err:
        # Sans « v », l'entree du cache est recalculee au prochain passage :
        # marquee comme les autres, un echec d'UN ffmpeg (VPS charge) cachait
        # pour toujours une empreinte vide, et le doublon n'etait plus jamais
        # reconnu -- sans trace.
        print(f"[empreintes] {f.name} : {err}, {len(images)} image(s) lue(s)", flush=True)
        return {"duree": d, "images": images}
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
    return _memes_images(a.get("images") or {}, b.get("images") or {})


def _memes_images(ia: dict, ib: dict) -> bool:
    """La plupart des images informatives communes, a quelques bits pres."""
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


# ------------------------------------------------------------ la fin d'une video
#
# Les templates de montage, le 03/10/2026 : « le doublon souvent c'est la
# deuxieme partie, la premiere elle est toujours differente ». Un template est
# une accroche (partie 1, changee a chaque fois) suivie de la partie 2, la
# meme d'une copie a l'autre. Les INSTANTS comptes depuis le debut tombent
# tous dans l'accroche (coupure mediane a 4,2 s sur le VPS) : on regarde la
# FIN, a des instants fixes comptes depuis la derniere image. Les templates
# sont des reels Instagram, sans carton de fin : la fin est la partie 2.

#: Secondes AVANT LA FIN ou l'on regarde l'image.
INSTANTS_FIN = (0.3, 0.7, 1.2, 1.8, 2.5, 3.3, 4.2, 5.5, 7.0, 9.0)
VERSION_FIN = 1


def empreinte_fin(f: Path, d: Optional[float] = None) -> dict:
    """{"duree": s, "vf": VERSION_FIN, "images": {"0.3": [hash, informative]}}
    -- les cles sont des secondes avant la fin. Une seule lecture des
    dernieres secondes (-sseof), a PAS images/s."""
    d = duree(f) if d is None else d
    images = {}
    if not d:
        return {"duree": d, "images": images}
    lire = min(d, max(INSTANTS_FIN) + 0.5)
    ok = False
    try:
        r = subprocess.run(_NICE + ["ffmpeg", "-v", "error", "-sseof", f"-{lire:.2f}",
                                    "-i", str(f), "-vf",
                                    f"fps={PAS},scale={LARGEUR}:{HAUTEUR}:flags=area,format=gray",
                                    "-f", "rawvideo", "-"],
                           capture_output=True, timeout=120)
        px, ok = r.stdout or b"", r.returncode == 0
    except subprocess.TimeoutExpired as e:
        px = e.stdout or b""
    except Exception:
        px = b""
    taille = LARGEUR * HAUTEUR
    n = len(px) // taille
    for t in INSTANTS_FIN:
        if t > d - 0.3:
            break
        # rang compte depuis la DERNIERE image lue : deux copies s'alignent
        # sur leur fin, quelle que soit la longueur de leur accroche
        k = n - 1 - int(round(t * PAS))
        if k < 0:
            break
        images[str(t)] = _hash_image(px[k * taille:(k + 1) * taille])
    if not ok:
        # sans « vf », recalculee au prochain passage (meme regle qu'empreinte)
        print(f"[empreintes] fin de {f.name} : lecture incomplete, {len(images)} image(s)",
              flush=True)
        return {"duree": d, "images": images}
    return {"duree": d, "vf": VERSION_FIN, "images": images}


def _images_avant(e: dict, longueur: float) -> dict:
    """Les images de la fin qui tombent dans les `longueur` dernieres secondes."""
    return {t: h for t, h in (e.get("images") or {}).items()
            if float(t) <= longueur - 0.15}


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
    if not e_neuf.get("duree") or not e_neuf.get("images"):
        # rien a comparer (lecture ratee, dite par empreinte()) : inutile de
        # calculer celles de tout le dossier
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
            # une lecture ratee se retente, trois fois : un fichier casse ne
            # repasse pas deux minutes dans ffmpeg a chaque video comparee
            if "images" not in c or (c.get("v") != VERSION and c.get("essais", 0) < 3):
                c.update(empreinte(f, c.get("duree")))
                if c.get("v") != VERSION:
                    c["essais"] = c.get("essais", 0) + 1
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


def trouver_doublon_fin(nouveau: Path, dossier: Path, longueur: float,
                        exclure: Iterable[str] = (), coupes: dict = None) -> Optional[Path]:
    """Le fichier de `dossier` dont les `longueur` dernieres secondes sont la
    MEME video que celles de `nouveau` -- sa partie 2 -- ou None.

    `coupes` {nom: coupure entre partie 1 et partie 2} quand on la connait :
    une partie 2 d'une autre duree (a ECART_EGAL pres) n'est pas la meme, et
    ses images ne sont meme pas lues."""
    if not longueur or longueur < 1.0:
        return None
    try:
        e_neuf = empreinte_fin(nouveau)
    except Exception:
        return None
    im_neuf = _images_avant(e_neuf, longueur)
    if sum(1 for h in im_neuf.values() if h[1]) < MIN_IMAGES:
        return None
    exclus = set(exclure or ())
    coupes = coupes or {}
    with _VERROU:
        cache = _cache(dossier)
        change = False
        calcules = 0
        trouve = None
        try:
            fichiers = sorted(p for p in dossier.iterdir()
                              if p.is_file() and p.suffix.lower() in EXTS_VIDEO)
        except OSError:
            fichiers = []
        for f in fichiers:
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
            d = c.get("duree")
            if not d or d < longueur - ECART_EGAL:
                continue
            coupe = coupes.get(f.name)
            if coupe is not None and abs((d - float(coupe)) - longueur) > ECART_EGAL:
                continue
            fin = c.get("fin")
            if not isinstance(fin, dict) or (fin.get("vf") != VERSION_FIN
                                             and c.get("essais_fin", 0) < 3):
                fin = empreinte_fin(f, d)
                c["fin"] = fin
                if fin.get("vf") != VERSION_FIN:
                    c["essais_fin"] = c.get("essais_fin", 0) + 1
                change = True
                calcules += 1
                if calcules % 20 == 0:
                    _ecrire_cache(dossier, cache)
            if _memes_images(im_neuf, _images_avant(fin, longueur)):
                trouve = f
                break
        if change:
            _ecrire_cache(dossier, cache)
    return trouve
