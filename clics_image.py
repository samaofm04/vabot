# -*- coding: utf-8 -*-
"""Les classements clics et abonnes du report #click en IMAGE, avec les photos.

POURQUOI
--------
Demande du proprietaire du 29/09 : « tu vois ce qu'on a fait pour les
sessions, tu peux faire la meme pour les clicks et subs, en mode un tableau
avec les PP et tout ». Le report texte portait deux classements coupes a dix
lignes (« … +17 more ») : les clics d'un cote, les abonnes de l'autre, et il
fallait chercher la meme personne dans les deux. Ici, UN tableau, une ligne
par personne, TOUTES les personnes : clics, abonnes, taux de conversion, et
le rang aux abonnes garde la reponse de l'ancien second classement (« qui
convertit »).

Ce module ne fait QUE le calcul et le dessin : ni Discord, ni reseau, ni
fichier ecrit. Il se teste seul ; le cog lui passe tout ce qu'il faut. Les
outils de dessin (polices, rond aux initiales, coupe des noms, palette)
viennent de sessions_image, valide par le proprietaire : on les IMPORTE, on
ne les recopie pas -- deux copies d'un rond aux initiales finiraient par
diverger.

A QUELLE TAILLE IL SERA LU
--------------------------
Comme le bilan des sessions : 1100 px de large, affiche a ~550 dans une
galerie « Components V2 », donc des textes de 22 px au minimum (11 a
l'ecran), dessine au double puis reduit pour lisser ronds et pastilles.

CE QUI N'EST JAMAIS INVENTE
---------------------------
- un total illisible reste « — », comme dans le report texte ;
- une personne sans lien de suivi MyPuls (« abonnes_muets ») : « — » en
  abonnes, en taux et en rang abonnes, jamais 0 ;
- un pseudo Discord introuvable ou ambigu sur le serveur : des initiales,
  jamais la photo de quelqu'un d'autre ;
- un caractere que la police ne dessine pas (emoji) : retire, pour ne pas
  laisser un carre vide.
"""
import io

from PIL import Image, ImageDraw

import clics_personnes as _cp
import sessions_image as _si
from sessions_image import (AMBRE, FOND, FOND_ENTETE, FOND_LIGNE, SEPARATEUR,
                            TEXTE, TEXTE_2, TEXTE_3, VERT_CLAIR, ajuster,
                            nettoyer, police)

#: Largeur FINALE de l'image, la meme que le bilan des sessions.
LARGEUR = 1100
_K = 2

#: Le nom de la piece jointe. [a-zA-Z0-9_.-] seulement : sinon Discord le
#: reecrit et la galerie « attachment://... » pointe dans le vide. Il sert
#: aussi a RETROUVER l'image deja postee apres un redemarrage.
NOM_IMAGE = "classement_clics.png"

#: Au-dela, les lignes ne sont plus dessinees et l'image le DIT. Soixante
#: lignes font deja une image de ~4 000 px de haut : Discord la reduirait
#: tant a l'affichage que plus rien ne se lirait. Aujourd'hui : 27 personnes.
PLAFOND = 60

# --- Le taux de conversion : trois couleurs, et un gris ---------------------
#
# LES SEUILS, cales sur le vrai report du 29/09 (capture du proprietaire) :
# les taux de l'equipe vont de 10,5 % a 28 % (443 abonnes pour 4 202 clics,
# 287 pour 1 415...). Des bornes a 1 % / 3 % mettaient tout le monde en vert.
# Sous 12 %, un lien envoie du monde qui s'abonne nettement moins que les
# autres (rouge) ; 20 % et plus, c'est une personne qui convertit nettement
# (vert) ; entre les deux, orange. Ce sont des bornes FIXES, pas relatives a
# l'equipe : une couleur qui change parce que les autres ont bouge ne se lit
# pas d'un jour sur l'autre.
#
# LE GRIS. Sous 50 clics, un seul abonne fait 2 % et deux font 4 % : le taux
# dit le hasard, pas la personne. On l'ecrit quand meme, en gris -- le cacher
# serait retirer un chiffre juste, le colorer serait lui preter un sens.
TAUX_FORT = 20.0
TAUX_MOYEN = 12.0
CLICS_MIN_TAUX = 50

VERT_PASTILLE = (36, 128, 70)
ORANGE_PASTILLE = (240, 178, 50)
ROUGE_PASTILLE = (218, 55, 60)
GRIS_PASTILLE = (78, 80, 88)
_ENCRE_PASTILLE = {"fort": (255, 255, 255), "moyen": (30, 31, 34),
                   "faible": (255, 255, 255), "petit": (225, 227, 230)}
_FOND_PASTILLE = {"fort": VERT_PASTILLE, "moyen": ORANGE_PASTILLE,
                  "faible": ROUGE_PASTILLE, "petit": GRIS_PASTILLE}

#: Le podium : or, argent, bronze -- les memes rangs que les medailles du
#: report texte (clics_personnes.medaille), dessinees puisque la police n'a
#: pas les emoji.
_PODIUM = [((236, 190, 58), (60, 42, 0)), ((196, 201, 210), (40, 42, 48)),
           ((205, 127, 50), (255, 255, 255))]
BARRE = (88, 101, 242)
BARRE_FOND = (60, 62, 70)


def niveau_taux(taux, clics) -> str:
    """« fort », « moyen », « faible », « petit » (trop peu de clics) ou « aucun »."""
    if taux is None:
        return "aucun"
    if not isinstance(clics, (int, float)) or clics < CLICS_MIN_TAUX:
        return "petit"
    if taux >= TAUX_FORT:
        return "fort"
    if taux >= TAUX_MOYEN:
        return "moyen"
    return "faible"


def nombre(v) -> str:
    """« 1 253 », ou « — » quand on n'a pas su lire (jamais 0)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "—"
    return "{:,}".format(int(v)).replace(",", " ")


def taux_txt(t) -> str:
    """« 2.4% », comme le report texte (une decimale), ou « — »."""
    if t is None:
        return "—"
    return "%.1f%%" % float(t)


def _cle(g) -> str:
    """La cle d'une personne, la meme que grouper() : le pseudo, sinon le
    premier lien (deux « VA 9 » anonymes restent deux lignes)."""
    return g.get("pseudo") or ("\x00" + str((g.get("liens") or [""])[0]).lower())


# ==============================================================================
# Les donnees : ce que l'image montre, calcule sans rien dessiner
# ==============================================================================

def tableau(donnees: dict, annuaire=None, periode: str = "", espace: str = "",
            liens: int = None, maj: str = "") -> dict:
    """Le contenu de l'image, a partir des donnees brutes du report.

    `donnees` : le dictionnaire `_donnees` de _build_group_report (resume,
    par_lien, abonnes) -- les MEMES chiffres que le texte, jamais recalcules.
    `annuaire` : {nom de fiche normalise: pseudo Discord} (annuaire_va) ; la
    fiche de chacun se retrouve par clics_personnes.fiche_de.
    `periode` : « 16 Sep → 30 Sep » ; `espace` : le nom du workspace ;
    `liens` : le nombre de liens suivis ; `maj` : « 14:30 ».
    """
    donnees = donnees or {}
    entrees = _cp.depuis_report(donnees, "quinz")
    gens = _cp.par_clics(entrees, annuaire or {})
    # Le rang aux abonnes, par la MEME regle que l'ancien second classement
    # (par_abonnes) : les personnes sans lien de suivi n'y figurent pas.
    conv = [g for g in _cp.par_abonnes(entrees, annuaire or {})
            if not g["abonnes_muets"]]
    rang_ab = {_cle(g): i + 1 for i, g in enumerate(conv)}
    lignes = []
    for i, g in enumerate(gens):
        muet = bool(g.get("abonnes_muets"))
        clics = None if g.get("clics_muets") else g.get("clics")
        taux = None if muet else g.get("taux")
        lignes.append({
            "rang": i + 1,
            "titre": str(g.get("titre") or ""),
            "discord": str(g.get("discord") or ""),
            "cle": _cle(g),
            "clics": clics,
            "liens": len(g.get("liens") or []),
            "abonnes": None if muet else g.get("abonnes"),
            "taux": taux,
            "niveau": niveau_taux(taux, clics),
            "rang_abonnes": None if muet else rang_ab.get(_cle(g)),
        })
    tuiles = []
    for r in donnees.get("resume") or []:
        m, t = r.get("marche"), r.get("total")
        if m is not None:
            # Le chiffre du marche en grand, le total mondial dessous : le
            # texte les met cote a cote, ici ils s'empilent.
            tuiles.append({"quand": str(r.get("quand") or ""), "valeur": m,
                           "detail": "global %s" % nombre(t)})
        else:
            tuiles.append({"quand": str(r.get("quand") or ""), "valeur": t,
                           "detail": "global"})
    return {
        "periode": str(periode or ""),
        "espace": str(espace or ""),
        "marche": str(donnees.get("marche") or ""),
        "liens": liens,
        "maj": str(maj or ""),
        "tuiles": tuiles,
        "lignes": lignes[:PLAFOND],
        "caches": max(0, len(lignes) - PLAFOND),
        "personnes": len(lignes),
        "sans_discord": sum(1 for x in lignes if not x["discord"]),
        # Par quelle etape de fiche_de chacun a ete retrouve : pour le journal.
        "rattachements": _cp.bilan_rattachements(gens),
        "abonnes_lus": any(x["abonnes"] is not None for x in lignes),
        "max_clics": max([x["clics"] for x in lignes
                          if isinstance(x["clics"], (int, float))] or [0]),
    }


def pseudos(t: dict) -> list:
    """Les pseudos Discord dont l'image montre la photo (pour aller les chercher)."""
    return sorted({x["discord"] for x in t.get("lignes") or [] if x.get("discord")})


def resoudre_pseudos(noms, membres) -> tuple:
    """({pseudo: id du membre}, compte) -- la regle de sessions_voc.attendus_jessye.

    Le pseudo d'une fiche VA est compare au NOM D'UTILISATEUR Discord (pas au
    surnom du serveur), en casefold. Une correspondance UNIQUE, sinon rien :
    deux comptes qui repondent au meme nom, c'est une photo tiree au sort, et
    une photo fausse se voit moins qu'une absence -- elle ne se corrige donc
    jamais. Les bots sont ignores.
    """
    index = {}
    for m in membres or []:
        if getattr(m, "bot", False):
            continue
        h = str(getattr(m, "name", "") or "").strip().casefold()
        if h:
            index.setdefault(h, []).append(m)
    out = {"introuvables": 0, "ambigus": 0}
    ids = {}
    for n in noms or []:
        cle = str(n or "").strip().lstrip("@").casefold()
        trouves = index.get(cle, [])
        if len(trouves) == 1:
            ids[n] = str(trouves[0].id)
        elif trouves:
            out["ambigus"] += 1
        else:
            out["introuvables"] += 1
    return ids, out


# ==============================================================================
# Le dessin
# ==============================================================================

def _pastille_rang(d, cx, cy, rang, f, p):
    """Or / argent / bronze pour le podium, sinon le numero."""
    if rang <= 3:
        fond, encre = _PODIUM[rang - 1]
        d.ellipse((p(cx - 19), p(cy - 19), p(cx + 19), p(cy + 19)), fill=fond)
        d.text((p(cx), p(cy)), str(rang), font=f, fill=encre, anchor="mm")
    else:
        d.text((p(cx), p(cy)), str(rang), font=f, fill=TEXTE_2, anchor="mm")


def dessiner(t: dict, photos: dict = None) -> bytes:
    """Le PNG du classement. Leve si l'image est impossible (le cog retombe
    alors sur les champs texte).

    `photos` : {pseudo Discord: octets d'image}. Une photo absente ou
    illisible donne un rond aux initiales -- jamais un echec.
    """
    photos = photos or {}
    K = _K

    def p(v):
        return int(round(v * K))

    f_titre = police("bold", p(46))
    f_sous = police("regular", p(24))
    f_compte = police("bold", p(34))
    f_compte2 = police("regular", p(25))
    f_petit_b = police("bold", p(24))
    f_tuile_lib = police("regular", p(22))
    f_tuile_val = police("bold", p(36))
    f_tuile_det = police("regular", p(22))
    f_col = police("bold", p(22))
    f_rang = police("bold", p(24))
    f_nom = police("medium", p(27))
    f_note = police("regular", p(22))
    f_chiffre = police("bold", p(27))
    f_pastille = police("bold", p(23))
    f_pied = police("bold", p(24))

    largeur, marge = LARGEUR, 40
    h_tete = 124
    h_tuile = 106
    h_entete = 50
    h_ligne = 60
    avatar = 46
    # Colonnes (px finaux, 1020 utiles). « Subs rank » (105 px en gras 22)
    # debordait de la marge droite centre a 972 : les colonnes de droite ont
    # ete resserrees vers la gauche, les noms gardent ~280 px.
    x_rang = marge + 32
    x_photo = marge + 62
    x_nom = x_photo + avatar + 14
    x_nom_fin = marge + 425
    x_clics_fin = marge + 540          # chiffre aligne a droite
    x_barre, l_barre = marge + 554, 100
    x_ab = marge + 718
    x_taux = marge + 838
    x_rang_ab = marge + 958

    lignes = t.get("lignes") or []
    corps = h_ligne * len(lignes) if lignes else 90
    pied = []
    if t.get("caches"):
        pied.append("+%d more not shown (limit %d rows)" % (t["caches"], PLAFOND))
    if t.get("sans_discord"):
        n = t["sans_discord"]
        pied.append("%d without a Discord account on their VA card" % n)
    h_pied = (26 + 36 * len(pied)) if pied else 0
    hauteur = marge + h_tete + h_tuile + 26 + h_entete + corps + h_pied + 30

    img = Image.new("RGB", (p(largeur), p(hauteur)), FOND)
    d = ImageDraw.Draw(img)

    # --- en-tete -----------------------------------------------------------
    d.text((p(marge), p(marge)), "Clicks ranking", font=f_titre, fill=TEXTE, anchor="lt")
    morceaux = [nettoyer(t.get("espace") or "", f_sous)]
    if t.get("marche"):
        morceaux.append("%s clicks" % nettoyer(t["marche"], f_sous))
    morceaux.append(("%s · in progress" % nettoyer(t["periode"], f_sous))
                    if t.get("periode") else "in progress")
    sous = " · ".join(x for x in morceaux if x)
    droite = p(largeur - marge)
    n_pers = t.get("personnes") or 0
    fin = (" · %d links" % t["liens"]) if isinstance(t.get("liens"), int) else ""
    compte = "%d %s" % (n_pers, "person" if n_pers == 1 else "people")
    d.text((droite, p(marge + 4)), fin, font=f_compte2, fill=TEXTE_2, anchor="rt")
    d.text((droite - _si._largeur(d, fin, f_compte2), p(marge)), compte,
           font=f_compte, fill=TEXTE, anchor="rt")
    maj = ("updated %s" % t["maj"]) if t.get("maj") else ""
    l_maj = _si._largeur(d, maj, f_petit_b) if maj else 0
    if maj:
        d.text((droite, p(marge + 64)), maj, font=f_petit_b, fill=VERT_CLAIR, anchor="rt")
    # Le sous-titre s'arrete avant « updated » : jamais de chevauchement.
    d.text((p(marge), p(marge + 64)),
           ajuster(d, sous, f_sous, droite - p(marge) - l_maj - p(24)),
           font=f_sous, fill=TEXTE_2, anchor="lt")

    # --- les periodes, en tuiles ------------------------------------------
    y = marge + h_tete
    tuiles = t.get("tuiles") or []
    if tuiles:
        ecart = 12
        l_t = (largeur - 2 * marge - ecart * (len(tuiles) - 1)) / len(tuiles)
        for i, tu in enumerate(tuiles):
            x = marge + i * (l_t + ecart)
            d.rounded_rectangle((p(x), p(y), p(x + l_t), p(y + h_tuile)),
                                radius=p(12), fill=FOND_ENTETE)
            cx = x + l_t / 2
            d.text((p(cx), p(y + 14)), ajuster(d, nettoyer(tu["quand"], f_tuile_lib),
                                              f_tuile_lib, p(l_t - 16)),
                   font=f_tuile_lib, fill=TEXTE_2, anchor="mt")
            val = nombre(tu["valeur"])
            d.text((p(cx), p(y + 44)), ajuster(d, val, f_tuile_val, p(l_t - 16)),
                   font=f_tuile_val, fill=TEXTE if val != "—" else TEXTE_3, anchor="mt")
            d.text((p(cx), p(y + 84)), ajuster(d, tu["detail"], f_tuile_det, p(l_t - 16)),
                   font=f_tuile_det, fill=TEXTE_3, anchor="mt")

    # --- en-tetes de colonnes ---------------------------------------------
    y0 = y + h_tuile + 26
    d.rounded_rectangle((p(marge), p(y0), p(largeur - marge), p(y0 + h_entete - 6)),
                        radius=p(12), fill=FOND_ENTETE)
    cy = y0 + (h_entete - 6) / 2
    d.text((p(x_rang), p(cy)), "#", font=f_col, fill=TEXTE_2, anchor="mm")
    d.text((p(x_nom), p(cy)), "VA", font=f_col, fill=TEXTE_2, anchor="lm")
    d.text((p(x_clics_fin), p(cy)), "Clicks", font=f_col, fill=TEXTE_2, anchor="rm")
    d.text((p(x_ab), p(cy)), "Subs", font=f_col, fill=TEXTE_2, anchor="mm")
    d.text((p(x_taux), p(cy)), "Conv.", font=f_col, fill=TEXTE_2, anchor="mm")
    d.text((p(x_rang_ab), p(cy)), "Subs rank", font=f_col, fill=TEXTE_2, anchor="mm")

    # --- une ligne par personne -------------------------------------------
    y_corps = y0 + h_entete
    if not lignes:
        d.text((p(marge + 20), p(y_corps + 45)),
               "No link read on this period — nothing to rank.",
               font=f_nom, fill=TEXTE_2, anchor="lm")
    max_c = t.get("max_clics") or 0
    for r, g in enumerate(lignes):
        yl = y_corps + r * h_ligne
        cy = yl + h_ligne / 2
        if r % 2 == 0:
            d.rectangle((p(marge), p(yl), p(largeur - marge), p(yl + h_ligne)), fill=FOND_LIGNE)
        _pastille_rang(d, x_rang, cy, g["rang"], f_rang, p)
        nom = nettoyer(g["titre"], f_nom)
        # Les initiales viennent du nom NETTOYE : un emoji donnait un carre.
        rond = _si._rond(photos.get(g["discord"]) if g["discord"] else None,
                         g["cle"], nom or "?", p(avatar))
        img.paste(rond, (p(x_photo), p(yl + (h_ligne - avatar) / 2)), rond)
        nom = nom or "?"
        l_nom = p(x_nom_fin - x_nom - 10)
        if g["liens"] > 1:
            d.text((p(x_nom), p(yl + 7)), ajuster(d, nom, f_nom, l_nom),
                   font=f_nom, fill=TEXTE, anchor="lt")
            d.text((p(x_nom), p(yl + h_ligne - 7)), "%d links" % g["liens"],
                   font=f_note, fill=TEXTE_3, anchor="ls")
        else:
            d.text((p(x_nom), p(cy)), ajuster(d, nom, f_nom, l_nom),
                   font=f_nom, fill=TEXTE, anchor="lm")
        # Clics : le chiffre, puis une barre discrete proportionnelle.
        c = g["clics"]
        d.text((p(x_clics_fin), p(cy)), nombre(c), font=f_chiffre,
               fill=TEXTE if c is not None else TEXTE_3, anchor="rm")
        if isinstance(c, (int, float)) and max_c > 0:
            d.rounded_rectangle((p(x_barre), p(cy - 5), p(x_barre + l_barre), p(cy + 5)),
                                radius=p(5), fill=BARRE_FOND)
            lb = max(10, l_barre * float(c) / max_c) if c > 0 else 0
            if lb:
                d.rounded_rectangle((p(x_barre), p(cy - 5), p(x_barre + lb), p(cy + 5)),
                                    radius=p(5), fill=BARRE)
        # Abonnes : « — » quand aucun lien de suivi MyPuls, jamais 0.
        a = g["abonnes"]
        d.text((p(x_ab), p(cy)), nombre(a), font=f_chiffre,
               fill=TEXTE if a is not None else TEXTE_3, anchor="mm")
        # Taux : une pastille coloree.
        if g["niveau"] == "aucun":
            d.text((p(x_taux), p(cy)), "—", font=f_chiffre, fill=TEXTE_3, anchor="mm")
        else:
            d.rounded_rectangle((p(x_taux - 54), p(cy - 20), p(x_taux + 54), p(cy + 20)),
                                radius=p(20), fill=_FOND_PASTILLE[g["niveau"]])
            d.text((p(x_taux), p(cy)), taux_txt(g["taux"]), font=f_pastille,
                   fill=_ENCRE_PASTILLE[g["niveau"]], anchor="mm")
        ra = g["rang_abonnes"]
        d.text((p(x_rang_ab), p(cy)), ("#%d" % ra) if ra else "—", font=f_chiffre,
               fill=TEXTE if ra and ra <= 3 else (TEXTE_2 if ra else TEXTE_3), anchor="mm")

    # --- pied ---------------------------------------------------------------
    if pied:
        yp = y_corps + corps + 14
        d.line((p(marge), p(yp), p(largeur - marge), p(yp)), fill=SEPARATEUR, width=p(2))
        for k, txt in enumerate(pied):
            d.text((p(marge), p(yp + 16 + 36 * k)), txt, font=f_pied, fill=AMBRE, anchor="lt")

    final = img.resize((largeur, hauteur), Image.LANCZOS)
    out = io.BytesIO()
    final.save(out, "PNG", optimize=False, compress_level=6)
    octets = out.getvalue()
    if len(octets) > _si.POIDS_MAX:
        raise ValueError("image du classement trop lourde (%d octets)" % len(octets))
    return octets


def texte_alt(t: dict) -> str:
    """La description de l'image (lecteurs d'ecran, et survol dans Discord)."""
    tete = [x for x in t.get("lignes") or []][:3]
    podium = ", ".join("%s %s" % (x["titre"], nombre(x["clics"])) for x in tete)
    return ("Clicks ranking %s: %d people%s" % (
        t.get("periode") or "", t.get("personnes") or 0,
        (" — top: " + podium) if podium else ""))[:1024]
