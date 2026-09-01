"""Fabrique les icones des boutons Discord, dans le style du site.

Pourquoi ce fichier existe
--------------------------
Les boutons du menu VA portaient des emojis standard, avec des doublons :
le meme 💬 pour « Reel caption » et « Bio », le meme 🖼️ pour « Post » et
« PP », et 🎬 quatre fois dans les menus. A la taille d un bouton Discord,
deux icones proches sont deux icones identiques.

Le site, lui, a un jeu d icones dessine maison, coherent : traits de 1,6,
rectangles arrondis en rx 3,4, viewBox 24x24. On reprend EXACTEMENT ces
formes pour Discord, au lieu d approximer avec des emojis.

Ce qui change entre le site et Discord
--------------------------------------
Un bouton Discord est bleu-violet (#5865F2) ou gris. Une icone violette du
site s y noierait : on garde donc les FORMES du site, tracees en blanc.
Le jeu est entierement monochrome, comme le theme Apple du site : ce qui
doit se detacher le fait par un CREUX dans la forme, jamais par une
couleur.

Le trait passe de 1,6 a 2,2 : une icone Discord fait ~22 px a l ecran,
un trait fin y disparait.

Usage
-----
    python outils_icones_discord.py

Ecrit 19 PNG de 128x128 dans emojis/. Ils sont versionnes : le VPS n a
donc besoin d aucune bibliotheque de rendu, il lit les fichiers.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

DOSSIER = Path(__file__).parent / "emojis"

# On dessine grand puis on reduit : c est ce qui donne des bords propres.
# PIL ne lisse pas les traits, le sur-echantillonnage s en charge.
UNITE = 24          # le viewBox du site
ECHELLE = 24        # 24 x 24 = 576 px de cote pendant le dessin
TAILLE = 576
FINAL = 128

BLANC = (255, 255, 255, 255)
# Jeu MONOCHROME, a la demande : les icones du theme Apple du site sont
# noires ou blanches, sans accent de couleur. L etoile des favoris se
# detache par un creux dans la forme, pas par une teinte.
TRAIT = 2.2                      # en unites de viewBox


def _p(x: float, y: float) -> tuple:
    """Un point du viewBox vers le canevas de dessin."""
    return (x * ECHELLE, y * ECHELLE)


def _ep(w: float = TRAIT) -> int:
    """Une epaisseur de trait, en pixels de dessin."""
    return max(1, round(w * ECHELLE))


class Icone:
    """Un dessin en cours, dans le repere 24x24 du site."""

    def __init__(self):
        self.im = Image.new("RGBA", (TAILLE, TAILLE), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    # --- primitives, toutes en unites de viewBox ---

    def rect(self, x, y, w, h, r, couleur=BLANC, ep=TRAIT):
        self.d.rounded_rectangle(
            [_p(x, y), _p(x + w, y + h)],
            radius=r * ECHELLE, outline=couleur, width=_ep(ep))

    def cercle(self, cx, cy, r, couleur=BLANC, ep=TRAIT, remplir=None):
        self.d.ellipse([_p(cx - r, cy - r), _p(cx + r, cy + r)],
                       outline=None if remplir else couleur,
                       fill=remplir, width=_ep(ep))

    def ligne(self, points, couleur=BLANC, ep=TRAIT):
        self.d.line([_p(x, y) for x, y in points],
                    fill=couleur, width=_ep(ep), joint="curve")
        # PIL ne met pas de bouts ronds : on les pose a la main, sinon les
        # angles des icones du site paraissent casses.
        r = ep / 2
        for x, y in points:
            self.d.ellipse([_p(x - r, y - r), _p(x + r, y + r)], fill=couleur)

    def polygone(self, points, couleur=BLANC):
        self.d.polygon([_p(x, y) for x, y in points], fill=couleur)

    def arc(self, cx, cy, r, deb, fin, couleur=BLANC, ep=TRAIT):
        self.d.arc([_p(cx - r, cy - r), _p(cx + r, cy + r)],
                   deb, fin, fill=couleur, width=_ep(ep))

    def cercle_pointille(self, cx, cy, r, n=13, part=0.62, couleur=BLANC, ep=TRAIT):
        """L anneau des stories : le site le dessine en tirets."""
        pas = 360.0 / n
        for i in range(n):
            deb = i * pas
            self.arc(cx, cy, r, deb, deb + pas * part, couleur, ep)

    def _detourer(self, points):
        """Creuse la zone d un polygone : l alpha y tombe a zero.

        Sans ca, un badge blanc pose sur un trait blanc se fond dedans. Les
        SF Symbols d Apple font exactement ce creux — c est lui qui detache
        le badge de la forme, sans ajouter de couleur.
        """
        masque = Image.new("L", (TAILLE, TAILLE), 0)
        ImageDraw.Draw(masque).polygon([_p(x, y) for x, y in points], fill=255)
        alpha = self.im.getchannel("A")
        alpha.paste(0, mask=masque)
        self.im.putalpha(alpha)
        self.d = ImageDraw.Draw(self.im)

    def _pts_etoile(self, cx, cy, r):
        pts = []
        for i in range(10):
            ray = r if i % 2 == 0 else r * 0.44
            a = math.radians(-90 + i * 36)
            pts.append((cx + ray * math.cos(a), cy + ray * math.sin(a)))
        return pts

    def etoile(self, cx, cy, r, couleur=BLANC):
        """L etoile pleine des favoris, detachee par un creux."""
        self._detourer(self._pts_etoile(cx, cy, r * 1.46))
        self.polygone(self._pts_etoile(cx, cy, r), couleur)

    def _pts_eclair(self, cx, cy, h):
        """Un eclair PLEIN et large. Un zigzag trace au trait devient une
        simple barre a 22 px : c est la surface qui le rend lisible."""
        l = h * 0.42
        return [(cx + l * 0.30, cy - h * 0.50),
                (cx - l * 1.00, cy + h * 0.10),
                (cx - l * 0.10, cy + h * 0.10),
                (cx - l * 0.30, cy + h * 0.50),
                (cx + l * 1.00, cy - h * 0.12),
                (cx + l * 0.10, cy - h * 0.12)]

    def eclair(self, cx, cy, h, couleur=BLANC, creux=False):
        """La marque des Flash. `creux` quand elle est posee SUR un trait."""
        if creux:
            pts = self._pts_eclair(cx, cy, h)
            self._detourer([(cx + (x - cx) * 1.9, cy + (y - cy) * 1.5)
                            for x, y in pts])
        self.polygone(self._pts_eclair(cx, cy, h), couleur)

    def enregistrer(self, nom: str):
        DOSSIER.mkdir(parents=True, exist_ok=True)
        petite = self.im.resize((FINAL, FINAL), Image.LANCZOS)
        chemin = DOSSIER / f"{nom}.png"
        petite.save(chemin, format="PNG", optimize=True)
        return chemin, chemin.stat().st_size


# --- Les icones -------------------------------------------------
# Chacune reprend une forme du site. Les commentaires disent laquelle, pour
# qu on puisse les retrouver si le site change.

def i_reelcaption():
    """Site : « Caption » — un cadre large et des lignes de texte."""
    ic = Icone()
    ic.rect(3, 4.6, 18, 13.4, 3.2)
    ic.ligne([(7.6, 10.8), (10.8, 10.8)])
    ic.ligne([(13.2, 10.8), (16.4, 10.8)])
    ic.ligne([(7.6, 14.2), (16.4, 14.2)])
    return ic


def i_reelmonte():
    """Site : « Reels » — un cadre et un triangle de lecture."""
    ic = Icone()
    ic.rect(3, 5, 18, 14, 3.4)
    ic.polygone([(10.2, 9.2), (10.2, 14.8), (15.2, 12)])
    return ic


def i_story():
    """Site : « Stories » — l anneau pointille d Instagram.

    Treize tirets serres donnaient un engrenage a la taille d un bouton.
    Huit tirets longs se lisent comme un anneau, qui est le but.
    """
    ic = Icone()
    ic.cercle_pointille(12, 12, 8.8, n=6, part=0.72, ep=2.3)
    ic.cercle(12, 12, 3.2)
    return ic


def i_post():
    """Site : « Posts » — cadre, soleil, ligne d horizon."""
    ic = Icone()
    ic.rect(3, 4, 18, 16, 3.4)
    ic.cercle(8.6, 9.4, 1.7)
    ic.ligne([(4.4, 16.4), (8.4, 12.8), (12.4, 16), (15.6, 13.6), (19.6, 16.6)])
    return ic


def i_storycta():
    """Site : « Story CTA » — un cadre haut et une fleche vers l action."""
    ic = Icone()
    ic.rect(4, 3.4, 16, 17.2, 3.4)
    ic.ligne([(8.8, 12), (14.8, 12)])
    ic.ligne([(12.4, 9.4), (15, 12), (12.4, 14.6)])
    return ic


def i_pseudo():
    """Un arobase : le pseudo est une adresse, pas un visage.

    Le site n a pas d icone dediee — « Accounts » y montre un buste, deja
    pris par la photo de profil. Deux bustes cote a cote sur un menu, ce
    sont deux boutons qu on confond.
    """
    ic = Icone()
    # L anneau exterieur, ouvert a droite : PIL trace dans le sens des
    # aiguilles, de « debut » vers « fin ». 55 -> 345 laisse la breche a
    # droite, la ou vient la queue de l arobase.
    ic.arc(12, 12, 8.6, 55, 345, ep=2.0)
    # Le « a » interieur : un rond et sa hampe droite.
    ic.cercle(11.4, 12, 3.2, ep=2.0)
    ic.ligne([(14.6, 9.6), (14.6, 13.6)], ep=2.0)
    ic.arc(12, 12, 3.2, 0, 55, ep=2.0)
    return ic


def i_name():
    """Une etiquette : le nom affiche.

    Le contour doit etre FERME. Ouvert a gauche, il se lisait comme une
    fleche — un bouton « Name » qui ressemble a « suivant » est pire que
    pas d icone du tout.
    """
    ic = Icone()
    ic.ligne([(4.6, 7.4), (14.2, 7.4), (19.6, 12), (14.2, 16.6), (4.6, 16.6),
              (4.6, 7.4)])
    ic.cercle(8.2, 12, 1.4, ep=1.9)
    return ic


def i_bio():
    """Site : « Bios » — une page et ses lignes."""
    ic = Icone()
    ic.rect(4.6, 3, 14.8, 18, 3)
    ic.ligne([(8.4, 8.4), (15.6, 8.4)])
    ic.ligne([(8.4, 12), (15.6, 12)])
    ic.ligne([(8.4, 15.6), (12.8, 15.6)])
    return ic


def i_pp():
    """Site : « Profile pictures » — un buste dans un cercle."""
    ic = Icone()
    ic.cercle(12, 12, 9.4)
    ic.cercle(12, 9.8, 3.0)
    ic.arc(12, 19.6, 5.6, 200, 340)
    return ic


def i_brute():
    """Site : « Raw video » — la camera, matiere premiere."""
    ic = Icone()
    ic.rect(2.4, 6.4, 13.4, 11.4, 2.4)
    ic.polygone([(21.6, 8.2), (16.4, 12), (21.6, 15.8)])
    return ic


def i_capbanger():
    """Caption du site, marquee de l etoile doree des favoris."""
    ic = i_reelcaption()
    ic.etoile(18.6, 5.4, 4.6)
    return ic


def i_montagebanger():
    """Site : « Editing template » — la note — marquee de l etoile.

    Le montage EST une note sur le site : les templates CapCut se choisissent
    par leur son. Ce n est pas une metaphore approximative, c est le code
    visuel deja en place.
    """
    ic = Icone()
    # La note est resserree vers le bas-gauche pour degager le coin ou se
    # pose l etoile : posee en bas a droite, elle percutait le cercle.
    ic.ligne([(8.4, 16.6), (8.4, 5.4), (17.4, 3.8), (17.4, 13.6)])
    ic.cercle(5.9, 16.8, 2.6)
    ic.cercle(14.9, 14.0, 2.6)
    ic.etoile(19.0, 5.0, 4.6)
    return ic


def i_templatebrut():
    """Les deux ensemble : la note du template, et la camera de la brute.

    Chacune tient dans SA moitie, sans se chevaucher. Superposees, elles ne
    faisaient qu une tache a la taille d un bouton.
    """
    ic = Icone()
    # le template : la note, moitie haute-gauche
    ic.ligne([(6.6, 11.0), (6.6, 4.0), (13.4, 2.8), (13.4, 8.8)], ep=2.0)
    ic.cercle(4.8, 11.2, 1.9, ep=2.0)
    ic.cercle(11.6, 9.0, 1.9, ep=2.0)
    # la brute : la camera, moitie basse-droite
    ic.rect(9.0, 14.8, 8.6, 6.6, 1.8, ep=2.0)
    ic.polygone([(21.4, 15.9), (18.4, 18.1), (21.4, 20.3)])
    return ic


def i_templatebanger():
    """Le Template (cadre + lecture) marque de l etoile : le ⭐ de reelmonte.

    Surtout PAS la note de i_montagebanger : deux icones « note + etoile »
    dans le meme menu sont deux boutons qu on confond. La variante marquee
    reprend l icone de SA base, comme capbanger reprend la caption.
    """
    ic = Icone()
    ic.rect(3, 5, 18, 14, 3.4)
    ic.polygone([(10.2, 9.2), (10.2, 14.8), (15.2, 12)])
    ic.etoile(19.4, 5.2, 4.4)
    return ic


def i_templateflash():
    """Le Template dont la lecture devient un ECLAIR : le montage Flash.

    L eclair est DANS le cadre, a la place du triangle. Pose dans un coin il
    se lisait comme un eclat a 22 px, et il occupait justement le coin ou
    l etoile doit venir pour la variante marquee.
    """
    ic = Icone()
    ic.rect(3, 5, 18, 14, 3.4)
    ic.eclair(12, 12, 9.6)
    return ic


def i_templateflashbanger():
    """Le Flash, marque de l etoile — meme regle que capbanger et brutbanger."""
    ic = Icone()
    ic.rect(3, 5, 18, 14, 3.4)
    ic.eclair(11.4, 12.2, 9.2)
    ic.etoile(19.4, 5.2, 4.4)
    return ic


def i_templateflashbrut():
    """Le Flash et la brute, chacun dans SA moitie — comme i_templatebrut."""
    ic = Icone()
    ic.rect(2.2, 2.8, 12.4, 9.6, 2.4, ep=2.0)
    ic.eclair(8.4, 7.6, 6.6)
    ic.rect(9.0, 14.8, 8.6, 6.6, 1.8, ep=2.0)
    ic.polygone([(21.4, 15.9), (18.4, 18.1), (21.4, 20.3)])
    return ic


def i_trend():
    """Les Trends : la courbe qui monte, et sa fleche.

    Pas un empilement de trois etoiles : le bouton en porte deja trois dans
    son libelle, et a 22 px elles ne feraient qu une tache.
    """
    ic = Icone()
    ic.ligne([(3.2, 16.8), (9.2, 10.8), (13.2, 14.8), (19.4, 8.6)], ep=2.4)
    ic.polygone([(21.0, 7.0), (21.0, 13.4), (14.6, 7.0)])
    return ic


def i_brutchoix():
    """La brute qu on CHOISIT : la camera, et la coche qui la valide.

    Chacune dans sa moitie, et la coche creuse son fond : posee sur le
    boitier elle s y fondait, les deux formes etant blanches.
    """
    ic = Icone()
    ic.rect(2.2, 5.0, 11.6, 9.2, 2.2)
    ic.polygone([(18.4, 6.6), (14.2, 9.6), (18.4, 12.6)])
    ic._detourer([(10.6, 22.0), (10.6, 13.2), (23.0, 13.2), (23.0, 22.0)])
    ic.ligne([(13.0, 18.0), (15.8, 20.8), (21.4, 15.2)], ep=2.6)
    return ic


# vabrutbanger et vacaptionbrut MANQUENT ici, et c est su : elles ont ete
# dessinees hors de ce fichier (commit b6fab02) et n ont jamais eu de
# fonction. On ne les reconstruit pas de memoire : le rendu obtenu ne
# retombait pas sur l existant (etoile et camera placees autrement), et
# regenerer changerait deux icones deja televersees sur les serveurs, ou
# Discord garde de toute facon l ancienne image.
ICONES = {
    "vareelcaption": i_reelcaption,
    "vareelmonte": i_reelmonte,
    "vastory": i_story,
    "vapost": i_post,
    "vastorycta": i_storycta,
    "vapseudo": i_pseudo,
    "vaname": i_name,
    "vabio": i_bio,
    "vapp": i_pp,
    "vabrute": i_brute,
    "vacapbanger": i_capbanger,
    "vamontagebanger": i_montagebanger,
    "vatemplatebrut": i_templatebrut,
    "vatemplatebanger": i_templatebanger,
    "vatemplateflash": i_templateflash,
    "vatemplateflashbanger": i_templateflashbanger,
    "vatemplateflashbrut": i_templateflashbrut,
    "vatrend": i_trend,
    "vabrutchoix": i_brutchoix,
}


def fabriquer() -> list:
    faits = []
    for nom, f in ICONES.items():
        chemin, poids = f().enregistrer(nom)
        # Discord refuse au-dela de 256 Ko. On est tres loin, mais si un jour
        # quelqu un passe la taille finale a 512, il faut que ca se voie.
        etat = "ok" if poids <= 256000 else "TROP LOURD"
        faits.append((nom, poids, etat))
    return faits


if __name__ == "__main__":
    for nom, poids, etat in fabriquer():
        print(f"  {nom:<18} {poids:>6} o  {etat}")
    print(f"\n  {len(ICONES)} icones dans {DOSSIER}")
