# -*- coding: utf-8 -*-
"""Vignettes de vidéos, et planches-contact numérotées.

POURQUOI

Discord ne sait pas montrer une vidéo qu'il n'a pas reçue. Pour qu'un VA
choisisse SA brute au lieu d'en recevoir trois au hasard, il faut donc lui
montrer quelque chose — et téléverser dix vidéos pour qu'il en regarde dix
coûterait plus de temps qu'il n'en gagne.

Une image extraite de chaque vidéo pèse ~50 Ko et se fabrique en deux dixièmes
de seconde. Assemblées en une seule planche numérotée, dix brutes tiennent dans
un envoi unique et s'affichent instantanément.

LA VIGNETTE EST UN FICHIER VOISIN

`<stem>.thumb.jpg`, à côté de la vidéo — même convention que `<stem>.desc.txt`
ou `<stem>.montage.json`. Elle est donc fabriquée une fois puis relue, et elle
part avec la vidéo quand celle-ci est supprimée (voir le balayage des voisins
dans web_upload).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

#: Suffixe du voisin. Une constante, parce que la suppression des médias doit
#: le connaître : une vignette orpheline se rattacherait à une future vidéo
#: portant le même nom, et montrerait le mauvais contenu.
SUFFIXE = ".thumb.jpg"

#: Hauteur d'une vignette. Assez pour reconnaître un rush, assez peu pour que
#: douze tiennent dans une image que Discord affiche sans la réduire.
HAUTEUR = 240

#: Au-delà, la planche devient illisible et il faut paginer.
#:
#: Vingt plutôt que douze : les identités ont entre deux et six brutes
#: étoilées, et paginer à douze ajoutait deux boutons de navigation qui ne
#: servaient jamais. La pagination reste, en filet, pour l'identité qui
#: étoilerait tout son stock — mais elle ne se déclenche plus en usage normal.
#:
#: Vingt-cinq est la vraie limite : c'est le nombre d'entrées qu'un menu
#: déroulant Discord accepte. On reste dessous.
PAR_PLANCHE = 20


def chemin(video) -> Path:
    """Où vit la vignette de cette vidéo."""
    v = Path(video)
    return v.with_name(v.stem + SUFFIXE)


def _ffmpeg_dispo() -> bool:
    try:
        import noctus_web
        return bool(noctus_web.ffmpeg_available())
    except Exception:
        return False


def fabriquer(video, forcer: bool = False) -> Path | None:
    """Extrait une image de la vidéo et la range à côté. Rend son chemin.

    Prise à UNE SECONDE, pas à zéro : beaucoup de rushs commencent sur un noir
    ou un fondu, et une planche de douze carrés noirs n'aide personne à
    choisir. Si la vidéo est plus courte, ffmpeg retombe sur la dernière image
    disponible.
    """
    v = Path(video)
    cible = chemin(v)
    if cible.is_file() and not forcer:
        try:
            # Une vignette plus vieille que sa vidéo montre l'ancien contenu.
            if cible.stat().st_mtime >= v.stat().st_mtime:
                return cible
        except OSError:
            return cible
    if not v.is_file() or not _ffmpeg_dispo():
        return None
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(v),
             "-frames:v", "1", "-vf", "scale=-2:%d" % HAUTEUR, str(cible)],
            timeout=60, check=True)
    except Exception:
        return None
    return cible if cible.is_file() else None


def prechauffer(videos) -> dict:
    """Fabrique les vignettes manquantes d'un lot. Rend un petit compte rendu.

    Appelée avant d'ouvrir un menu de choix : la première fois coûte quelques
    secondes, les suivantes sont instantanées puisque les vignettes restent sur
    le disque.
    """
    faites = deja = ratees = 0
    for v in videos or ():
        c = chemin(v)
        if c.is_file():
            deja += 1
            continue
        if fabriquer(v) is None:
            ratees += 1
        else:
            faites += 1
    return {"faites": faites, "deja": deja, "ratees": ratees}


def planche(videos, colonnes: int = 4, depart: int = 0) -> bytes | None:
    """Assemble les vignettes en UNE image numérotée. Rend les octets JPEG.

    Les numéros comptent : ce sont eux que le VA retrouvera dans le menu
    déroulant. Sans eux, il verrait douze images sans savoir laquelle est
    « la 7 ».

    Une vidéo sans vignette occupe quand même sa case, en gris et numérotée :
    l'écarter décalerait toutes les suivantes, et le choix ne correspondrait
    plus à ce qui est affiché.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None

    # La police par defaut de PIL fait douze pixels : sur un telephone, ou
    # Discord reduit encore l image, le numero devient illisible — et c est
    # justement par ce numero que le VA choisit. On cherche donc une vraie
    # police, avec repli sur la petite si la machine n en a aucune.
    police = None
    for nom in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf",
                "DejaVuSans.ttf", "arial.ttf"):
        try:
            police = ImageFont.truetype(nom, 34)
            break
        except Exception:
            continue
    if police is None:
        try:
            police = ImageFont.load_default()
        except Exception:
            police = None
    videos = list(videos or ())[:PAR_PLANCHE]
    if not videos:
        return None

    cases = []
    for v in videos:
        c = chemin(v)
        img = None
        if c.is_file():
            try:
                img = Image.open(c).convert("RGB")
            except Exception:
                img = None
        if img is None:
            img = Image.new("RGB", (int(HAUTEUR * 9 / 16), HAUTEUR),
                            (48, 48, 54))
        cases.append(img)

    largeur_case = max(i.width for i in cases)
    lignes = (len(cases) + colonnes - 1) // colonnes
    marge = 6
    planche_img = Image.new(
        "RGB",
        (colonnes * (largeur_case + marge) + marge,
         lignes * (HAUTEUR + marge) + marge),
        (24, 24, 28))
    dessin = ImageDraw.Draw(planche_img)

    for i, img in enumerate(cases):
        x = marge + (i % colonnes) * (largeur_case + marge)
        y = marge + (i // colonnes) * (HAUTEUR + marge)
        planche_img.paste(img, (x + (largeur_case - img.width) // 2, y))
        # Le numéro, en blanc sur une pastille sombre : lisible sur une image
        # claire comme sur une image sombre, ce qu'un simple texte blanc n'est
        # pas.
        # `depart` decale la numerotation d une page a l autre : sans lui, la
        # page 2 recommencait a 1 alors que la page 1 finissait a 20, et deux
        # brutes differentes portaient le meme numero.
        etiquette = str(depart + i + 1)
        try:
            gauche, haut, droite, bas = dessin.textbbox((0, 0), etiquette,
                                                        font=police)
            larg, haut_txt = droite - gauche, bas - haut
        except Exception:
            larg, haut_txt = 10 * len(etiquette), 12
        marge_p = 9
        dessin.rectangle([x + 5, y + 5,
                          x + 5 + larg + 2 * marge_p,
                          y + 5 + haut_txt + 2 * marge_p],
                         fill=(0, 0, 0))
        dessin.text((x + 5 + marge_p, y + 5 + marge_p), etiquette,
                    fill=(255, 255, 255), font=police)

    import io
    tampon = io.BytesIO()
    planche_img.save(tampon, format="JPEG", quality=82)
    return tampon.getvalue()
