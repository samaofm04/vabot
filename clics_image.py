# -*- coding: utf-8 -*-
"""Le report #click en DEUX IMAGES, avec les photos.

POURQUOI
--------
Demande du proprietaire du 29/09 (1) : « tu vois ce qu'on a fait pour les
sessions, tu peux faire la meme pour les clicks et subs, en mode un tableau
avec les PP et tout ». D'ou une premiere image, « Clicks ranking » (f77f466).

Demande du proprietaire du 29/09 (2), capture du tableau texte « Per link —
US vs global » a l'appui, dont les colonnes se collaient (« 1221450 4098 ») :
« il faut les clicks aujourd'hui, hier, quinzaine, quinzaine precedente --
fais un pour les clicks et un pour les subs, c'est pas mieux ? un pour les
clicks genre la US vs GLOB, et un autre pour les subs et la LTV ». Il a
valide deux maquettes, dessinees ici :

  « Clicks — US vs global »  Today · Yesterday · 16–30 · 1–15 ; dans chaque
      case, le US en gros et le global en petit dessous. Une ligne par
      PERSONNE (rang, photo, nom), triee par clics US de la quinzaine en
      cours ; sous une personne a plusieurs liens, une sous-ligne par lien
      (« (Roucham) 1SP   1 / 6 · 63 / 161 · 329 / 1 318 »), pour garder le
      detail que montrait le tableau texte.
  « Subs »  abonnes Today · 16–30 (en gras) · 1–15 et conversion (pastille).
      AUCUN MONTANT (ni net ni LTV) : l'image part dans #click, que les VA
      lisent (proprietaire, 29/09 au soir : « il ne faut surtout pas mettre
      ca »). Le revenu reste lu et calcule (tableau_subs), jamais dessine.

Ce module ne fait QUE le calcul et le dessin : ni Discord, ni reseau, ni
fichier ecrit. Il se teste seul ; le cog lui passe tout ce qu'il faut. Les
outils de dessin (polices, rond aux initiales, coupe des noms, palette)
viennent de sessions_image, valide par le proprietaire : on les IMPORTE, on
ne les recopie pas.

A QUELLE TAILLE ELLES SERONT LUES
---------------------------------
1100 px de large, affichees a ~550 dans le message : des textes de 22 px au
minimum (11 a l'ecran), dessines au double puis reduits pour lisser les
ronds. LES COLONNES TIENNENT TOUJOURS : leur largeur est MESUREE sur le plus
grand nombre a ecrire (le defaut de la capture : « 184421811205 », deux
nombres colles), et si la place manque, les chiffres rapetissent au lieu de
se chevaucher.

CE QUI N'EST JAMAIS INVENTE
---------------------------
- ce qu'on n'a pas su lire reste « — », jamais 0 ; une periode anterieure a
  l'arrivee d'un VA sur son lien reste « · » (ce n'est pas a lui) ;
- un total de personne dont UN lien n'a pas pu etre lu n'est pas un total :
  « — », et le detail par lien, dessous, montre ce qui a ete lu ;
- une personne sans lien de suivi MyPuls : « — » partout dans « Subs & LTV »,
  comptee dans le pied ;
- 0 abonne : pas de LTV (« — »), pas 0 $ -- la regle de la page Liens
  Infloww, IMPORTEE (infloww_liens._somme), pas recopiee ;
- un pseudo Discord introuvable ou ambigu : des initiales, jamais la photo
  de quelqu'un d'autre ;
- un caractere que la police ne dessine pas (emoji) : retire.
"""
import datetime
import decimal
import fractions
import io

from PIL import Image, ImageDraw

import clics_personnes as _cp
import sessions_image as _si
from sessions_image import (AMBRE, FOND, FOND_ENTETE, FOND_LIGNE, SEPARATEUR,
                            TEXTE, TEXTE_2, TEXTE_3, VERT_CLAIR, ajuster,
                            nettoyer, police)

#: Largeur FINALE des images, la meme que le bilan des sessions.
LARGEUR = 1100
_K = 2

#: Les noms des pieces jointes. [a-zA-Z0-9_.-] seulement : sinon Discord les
#: reecrit et la galerie « attachment://... » pointe dans le vide. Ils servent
#: aussi a RETROUVER le message deja poste apres un redemarrage.
NOM_CLICS = "clics_us_global.png"
NOM_SUBS = "abonnes_ltv.png"
#: L'image unique de f77f466 (« Clicks ranking ») : reconnue pour etre
#: CONVERTIE en place, jamais laissee a cote des deux nouvelles.
NOM_ANCIEN = "classement_clics.png"
NOMS = (NOM_CLICS, NOM_SUBS, NOM_ANCIEN)

#: Au-dela, les personnes ne sont plus dessinees et l'image le DIT. Soixante
#: lignes font deja une image de ~4 000 px de haut. Aujourd'hui : 27.
PLAFOND = 60

# --- Le taux de conversion : cinq couleurs, et un gris ----------------------
#
# LES SEUILS DU PROPRIETAIRE (29/09 au soir) : « la conversion, c'est les
# personnes qui cliquent et qui s'abonnent. 10 %, c'est bien, c'est la base.
# Jusqu'a 7,5 %, ca va. Entre 7,5 et 5, c'est orange. Moins de 5, rouge. A
# partir de 15, 20, c'est vraiment top. » Des bornes FIXES : une couleur qui
# change parce que les autres ont bouge ne se lit pas d'un jour sur l'autre.
#
# LE GRIS. Sous 50 clics, un seul abonne fait 2 % et deux font 4 % : le taux
# dit le hasard, pas la personne. On l'ecrit quand meme, en gris.
TAUX_TOP = 15.0
TAUX_BIEN = 10.0
TAUX_CORRECT = 7.5
TAUX_MOYEN = 5.0
CLICS_MIN_TAUX = 50

VERT_VIF_PASTILLE = (34, 197, 94)
VERT_PASTILLE = (36, 128, 70)
VERT_CLAIR_PASTILLE = (163, 207, 98)
ORANGE_PASTILLE = (240, 178, 50)
ROUGE_PASTILLE = (218, 55, 60)
GRIS_PASTILLE = (78, 80, 88)
_ENCRE_PASTILLE = {"top": (8, 40, 20), "bien": (255, 255, 255), "correct": (24, 40, 12),
                   "moyen": (30, 31, 34), "faible": (255, 255, 255), "petit": (225, 227, 230)}
_FOND_PASTILLE = {"top": VERT_VIF_PASTILLE, "bien": VERT_PASTILLE,
                  "correct": VERT_CLAIR_PASTILLE, "moyen": ORANGE_PASTILLE,
                  "faible": ROUGE_PASTILLE, "petit": GRIS_PASTILLE}

#: Le podium : or, argent, bronze -- les memes rangs que les medailles du
#: report texte (clics_personnes.medaille), dessinees puisque la police n'a
#: pas les emoji.
_PODIUM = [((236, 190, 58), (60, 42, 0)), ((196, 201, 210), (40, 42, 48)),
           ((205, 127, 50), (255, 255, 255))]

#: La fleche de la LTV : discrete, et seulement quand l'ecart se voit. Sous
#: 5 %, une fleche dirait une tendance que les centimes ne portent pas.
ECART_FLECHE = 0.05
FLECHE_HAUT = (87, 200, 120)
FLECHE_BAS = (230, 90, 90)

#: Les colonnes par defaut : aujourd'hui, hier, la quinzaine en cours, la
#: precedente. Le cog passe les vraies (« 1–15 » / « Aug 16–31 »...).
COLONNES = ("Today", "Yesterday", "16–30", "1–15")

# --- L'evolution : une fleche verte, orange ou rouge -------------------------
#
# Le proprietaire, le 29/09 au soir : « si c'est en train de faire plus de
# subs que d'habitude, il y a un truc vert vers le haut, sinon il y a un truc
# rouge, sinon il y a un truc orange » -- pour les clics comme pour les subs.
#
# « D'habitude », c'est le RYTHME de la quinzaine precedente. On compare des
# rythmes par jour, jamais des totaux : le 20 du mois, la quinzaine en cours
# n'a que 4 jours et perdrait toujours contre une quinzaine finie. Aujourd'hui
# n'est pas fini non plus : il sort du rythme en cours (a 9 h, il ferait
# baisser tout le monde).
#
# Plus de 10 % au-dessus de l'habitude : vert. Plus de 10 % en dessous :
# rouge. Entre les deux, c'est le rythme habituel : orange. Des seuils en
# fractions EXACTES : 1,1 en virgule flottante ne tombe pas pile, et un
# rythme exactement 10 % au-dessus doit etre vert.
EVO_HAUT = fractions.Fraction(11, 10)
EVO_BAS = fractions.Fraction(9, 10)
VERT_EVO = FLECHE_HAUT
ORANGE_EVO = ORANGE_PASTILLE
ROUGE_EVO = FLECHE_BAS
#: La fleche dessinee (px finaux), l'ecart qui la separe du chiffre, et la
#: place que le gabarit lui garde a droite de la colonne -- MESUREE dans la
#: largeur de la colonne, pour que la fleche ne morde jamais sur la suivante.
TAILLE_EVO = 16
ECART_EVO = 8
PLACE_EVO = ECART_EVO + TAILLE_EVO + 4


def niveau_taux(taux, clics) -> str:
    """« top » (15 % et plus), « bien » (10), « correct » (7,5), « moyen » (5),
    « faible » (sous 5 %), « petit » (trop peu de clics) ou « aucun »."""
    if taux is None:
        return "aucun"
    if not isinstance(clics, (int, float)) or clics < CLICS_MIN_TAUX:
        return "petit"
    if taux >= TAUX_TOP:
        return "top"
    if taux >= TAUX_BIEN:
        return "bien"
    if taux >= TAUX_CORRECT:
        return "correct"
    if taux >= TAUX_MOYEN:
        return "moyen"
    return "faible"


def _est_nombre(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _entier(v) -> int:
    """L'entier le plus proche, les demis vers le haut (en valeur absolue).

    round() de Python arrondit les demis au PAIR : 12,50 $ devenait « $12 » et
    13,50 $ « $14 », deux lignes voisines arrondies en sens contraires
    (relecture du 29/09)."""
    return int(decimal.Decimal(str(float(v))).quantize(
        decimal.Decimal(1), rounding=decimal.ROUND_HALF_UP))


def nombre(v) -> str:
    """« 4 098 » ; « · » avant l'arrivee (NA) ; « — » quand on n'a pas su lire."""
    if v == "NA":
        return "·"
    if not _est_nombre(v):
        return "—"
    return "{:,}".format(_entier(v)).replace(",", " ")


def dollars(v, cents: bool = False) -> str:
    """« $1 234 », « $12.40 » avec les centimes ; « — » / « · » sinon."""
    if v == "NA":
        return "·"
    if not _est_nombre(v):
        return "—"
    if cents:
        return "$" + "{:,.2f}".format(float(v)).replace(",", " ")
    return "$" + "{:,}".format(_entier(v)).replace(",", " ")


def taux_txt(t) -> str:
    """« 2.4% », comme le report texte (une decimale), ou « — »."""
    if t is None:
        return "—"
    return "%.1f%%" % float(t)


def somme(valeurs):
    """Le total d'une personne sur ses liens, SANS mentir.

      aucun lien               None  (rien a dire)
      tous « NA »              "NA"  (la periode precede son arrivee partout)
      un lien illisible        None  : un total partiel n'est pas un total
      sinon                    la somme des nombres, « NA » ignores
    """
    vals = list(valeurs or [])
    if not vals:
        return None
    if all(v == "NA" for v in vals):
        return "NA"
    total = 0
    for v in vals:
        if v == "NA":
            continue
        if not _est_nombre(v):
            return None
        total += v
    return total


def ltv(net, abonnes):
    """$ / sub = net ÷ abonnes, par LA regle de la page Liens Infloww.

    infloww_liens._somme est importee et non recopiee : deux definitions de la
    LTV finiraient par dire deux chiffres pour le meme lien. 0 abonne : None
    (« — »), pas 0 $. Les deux « NA » : « NA » (avant l'arrivee)."""
    if net == "NA" and abonnes == "NA":
        return "NA"
    if not (_est_nombre(net) and _est_nombre(abonnes)):
        return None
    try:
        import infloww_liens as _il
        r = _il._somme([{"clics": None, "abonnes": int(abonnes),
                         "net": int(round(float(net) * 100))}])
    except Exception as e:                       # noqa: BLE001
        print("[clics_image] LTV incalculable (%s: %s)" % (type(e).__name__, e), flush=True)
        return None
    return r.get("par_sub")


def fleche(actuel, avant) -> str:
    """« haut », « bas » ou "" : la LTV de la quinzaine contre la precedente."""
    if not (_est_nombre(actuel) and _est_nombre(avant)) or avant <= 0:
        return ""
    ecart = (float(actuel) - float(avant)) / float(avant)
    if ecart >= ECART_FLECHE:
        return "haut"
    if ecart <= -ECART_FLECHE:
        return "bas"
    return ""


def _date(v):
    """Une date, depuis un datetime.date ou une chaine ISO ; None sinon."""
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v or "").strip()[:10])
    except ValueError:
        return None


def _exact(v) -> fractions.Fraction:
    return fractions.Fraction(str(v))


def evolution(actuel, du_jour, precedent, debut_q, fin_q, debut_p, fin_p,
              aujourd_hui, arrivees=()) -> str:
    """« haut » (vert), « stable » (orange), « bas » (rouge) ou "" (pas de fleche).

    `actuel` : la valeur de la quinzaine en cours (aujourd'hui compris) ;
    `du_jour` : celle d'aujourd'hui ; `precedent` : la quinzaine precedente.
    Les bornes sont celles du report (dates ou ISO), jamais 15 jours en dur :
    le 16-31 en a 16, le 16-28 fevrier 13.

      rythme en cours  = (actuel - du_jour) / jours COMPLETS de la quinzaine
      rythme habituel  = precedent / jours de la quinzaine precedente
      rapport >= 1,10 -> « haut » ; <= 0,90 -> « bas » ; sinon « stable »

    PAS DE FLECHE plutot qu'une fleche inventee :
      - une valeur « — » (illisible) ou « · » (avant son arrivee) ;
      - le 1er jour de la quinzaine : aucun jour complet, aucun rythme ;
      - une arrivee sur un lien PENDANT l'une des deux quinzaines : l'une
        des periodes est coupee, les deux ne se comparent pas ;
      - precedente a 0 et rien depuis ; une valeur negative (incoherente).
    Precedente a 0 et quelque chose depuis : « haut ».
    """
    dq, fq, dp, fp, auj = (_date(x) for x in (debut_q, fin_q, debut_p, fin_p, aujourd_hui))
    if None in (dq, fq, dp, fp, auj) or not (dq <= auj <= fq) or dp > fp:
        return ""
    for a in arrivees or ():
        if not a:
            continue
        da = _date(a)
        # Une date d'arrivee illisible : on ne sait pas si les periodes sont
        # entieres, donc pas de fleche.
        if da is None or dp < da <= fq:
            return ""
    if not all(_est_nombre(v) for v in (actuel, du_jour, precedent)):
        return ""
    jours = (auj - dq).days
    if jours <= 0:
        return ""
    jours_p = (fp - dp).days + 1
    fait = _exact(actuel) - _exact(du_jour)
    avant = _exact(precedent)
    if fait < 0 or avant < 0:
        return ""
    if avant == 0:
        return "haut" if fait > 0 else ""
    rapport = (fait / jours) / (avant / jours_p)
    if rapport >= EVO_HAUT:
        return "haut"
    if rapport <= EVO_BAS:
        return "bas"
    return "stable"


def _evo(actuel, du_jour, precedent, bornes, arrivees) -> str:
    """evolution() avec les bornes du report ; sans bornes, pas de fleche."""
    if not isinstance(bornes, dict):
        return ""
    return evolution(actuel, du_jour, precedent, bornes.get("debut_q"), bornes.get("fin_q"),
                     bornes.get("debut_p"), bornes.get("fin_p"), bornes.get("aujourd_hui"),
                     arrivees)


def _cle(g) -> str:
    """La cle d'une personne, la meme que grouper() : le pseudo, sinon le
    premier lien (deux « VA 9 » anonymes restent deux lignes)."""
    return g.get("pseudo") or ("\x00" + str((g.get("liens") or [""])[0]).lower())


# ==============================================================================
# Les donnees : ce que les images montrent, calcule sans rien dessiner
# ==============================================================================

def _personnes(donnees, annuaire):
    """Les personnes du report, par clics_personnes (le MEME regroupement que
    le texte, la page web et la carte du tableau de bord)."""
    entrees = _cp.depuis_report(donnees or {}, "quinz")
    return _cp.grouper(entrees, annuaire or {})


def _gabarits(donnees, suivis_seulement: bool = False) -> list:
    """Les liens « gabarit » que grouper() ecarte : NOMMES dans le pied.

    Un gabarit n'est pas quelqu'un, il n'a pas de ligne. Mais le tableau texte
    les montrait, et l'image le remplace : sans ce pied, leurs clics et leurs
    abonnes n'etaient plus nulle part, et la somme des lignes ne tombait plus
    sur les tuiles sans explication (relecture du 29/09)."""
    out = []
    for e in _cp.depuis_report(donnees or {}, "quinz"):
        nom = _cp.propre(e.get("nom"))
        if nom and _cp.est_gabarit(nom):
            if suivis_seulement and not isinstance(e.get("suivi"), dict):
                continue
            out.append(nom)
    return out


def _pied_gabarits(noms) -> str:
    if not noms:
        return ""
    return "%d template link%s not shown: %s" % (
        len(noms), "" if len(noms) == 1 else "s", ", ".join(noms))


def _cellules_lien(e, marche: bool) -> list:
    """[(US, global)] x 4 periodes d'un lien, tels que le report les a lus."""
    per = list(((e or {}).get("brut") or {}).get("periodes") or [])
    out = []
    for k in range(4):
        p = per[k] if k < len(per) and isinstance(per[k], dict) else {}
        out.append((p.get("marche") if marche else None, p.get("total")))
    return out


def _tuiles(donnees) -> list:
    tuiles = []
    for r in (donnees or {}).get("resume") or []:
        m, t = r.get("marche"), r.get("total")
        if m is not None:
            # Le chiffre du marche en grand, le total mondial dessous.
            tuiles.append({"quand": str(r.get("quand") or ""), "valeur": m,
                           "detail": "global %s" % nombre(t)})
        else:
            tuiles.append({"quand": str(r.get("quand") or ""), "valeur": t,
                           "detail": "global"})
    return tuiles


def _tri(v) -> tuple:
    """Pour trier : les nombres d'abord, du plus grand au plus petit."""
    return (0, -float(v)) if _est_nombre(v) else (1, 0.0)


def tableau_clics(donnees: dict, annuaire=None, periode: str = "", espace: str = "",
                  liens: int = None, maj: str = "", colonnes=COLONNES,
                  bornes: dict = None) -> dict:
    """Le contenu de l'image « Clicks — US vs global ».

    `donnees` : le dictionnaire `_donnees` de _build_group_report -- les MEMES
    chiffres que le texte, jamais recalcules. `par_lien[i]["periodes"]` :
    aujourd'hui, hier, la quinzaine en cours, la precedente (4e, gardee sur
    disque par le cog ; absente -> « — »).

    `bornes` : {"debut_q", "fin_q", "debut_p", "fin_p", "aujourd_hui"}, les
    dates du report, pour la fleche d'evolution (voir evolution()). Absentes :
    aucune fleche.
    """
    donnees = donnees or {}
    marche = bool(donnees.get("marche"))
    gens = _personnes(donnees, annuaire)
    k_tri = 0 if marche else 1
    lignes = []
    for g in gens:
        detail = [{"nom": _cp.propre(e.get("nom")), "cellules": _cellules_lien(e, marche)}
                  for e in g.get("entrees") or []]
        cellules = []
        for k in range(4):
            us = somme([d["cellules"][k][0] for d in detail]) if marche else None
            gl = somme([d["cellules"][k][1] for d in detail])
            cellules.append((us, gl))
        # LA FLECHE, SUR LA PERSONNE SEULEMENT (pas sur ses sous-lignes par
        # lien), calculee sur le chiffre qu'on classe : les clics US, le
        # global quand le report n'a pas de marche.
        evo = _evo(cellules[2][k_tri], cellules[0][k_tri], cellules[3][k_tri], bornes,
                   [e.get("depuis") for e in g.get("entrees") or []])
        lignes.append({
            "titre": str(g.get("titre") or ""),
            "discord": str(g.get("discord") or ""),
            "cle": _cle(g),
            "cellules": cellules,
            # Le detail par lien n'a de sens que s'il y a plusieurs liens :
            # sous une personne a un seul lien, il recopierait sa ligne.
            "liens": detail if len(detail) > 1 else [],
            "n_liens": len(detail),
            "evo": evo,
        })
    # TRIE PAR CLICS US DE LA QUINZAINE EN COURS (le global sans marche) ;
    # un total illisible part en fin de liste, pas a zero.
    lignes.sort(key=lambda x: (_tri(x["cellules"][2][k_tri]), _tri(x["cellules"][2][1]),
                               x["titre"].lower()))
    # UN RANG, UNE MEDAILLE, SEULEMENT POUR UN NOMBRE. « — » (pas lu) et
    # « · » (avant son arrivee) ne classent personne : une medaille donnee
    # a un total inconnu est un podium invente.
    rang = 0
    for x in lignes:
        if _est_nombre(x["cellules"][2][k_tri]):
            rang += 1
            x["rang"] = rang
        else:
            x["rang"] = None
    return {
        "titre": "Clicks — %s vs global" % donnees["marche"] if marche else "Clicks — global",
        "periode": str(periode or ""),
        "espace": str(espace or ""),
        "marche": str(donnees.get("marche") or ""),
        "liens": liens,
        "maj": str(maj or ""),
        "colonnes": list(colonnes or COLONNES)[:4],
        "tuiles": _tuiles(donnees),
        "lignes": lignes[:PLAFOND],
        "caches": max(0, len(lignes) - PLAFOND),
        "personnes": len(lignes),
        "sans_discord": sum(1 for x in lignes if not x["discord"]),
        "gabarits": _gabarits(donnees),
        # Par quelle etape de fiche_de chacun a ete retrouve : pour le journal.
        "rattachements": _cp.bilan_rattachements(gens),
    }


def tableau_subs(donnees: dict, annuaire=None, periode: str = "", espace: str = "",
                 maj: str = "", colonnes=COLONNES, bornes: dict = None) -> dict:
    """Le contenu de l'image « Subs & LTV ».

    Les abonnes et le revenu viennent de `donnees["abonnes"]` : les TROIS
    appels tracking-links que le report fait deja (aujourd'hui, quinzaine en
    cours, precedente), le revenu lu dans la meme reponse. Un lien SANS lien de
    suivi MyPuls n'est pas un lien a zero abonne : il est hors du calcul, et
    une personne qui n'a que de ceux-la a « — » partout.

    LA CONVERSION se calcule sur les liens SUIVIS seulement (abonnes ÷ clics
    US de la quinzaine) : diviser les abonnes d'un lien par les clics de tous
    les liens de la personne la faisait paraitre moins bonne qu'elle n'est --
    meme choix que le CVR de la page Liens Infloww.

    LA FLECHE D'EVOLUTION porte sur les abonnes (aujourd'hui, quinzaine,
    precedente), avec les `bornes` du report ; les dates d'arrivee sont celles
    des liens SUIVIS, ceux dont viennent les chiffres.
    """
    donnees = donnees or {}
    marche = bool(donnees.get("marche"))
    gens = _personnes(donnees, annuaire)
    lignes = []
    for g in gens:
        suivies = [e for e in g.get("entrees") or [] if isinstance(e.get("suivi"), dict)]
        base = {"titre": str(g.get("titre") or ""), "discord": str(g.get("discord") or ""),
                "cle": _cle(g), "suivi": bool(suivies)}
        if not suivies:
            base.update(auj=None, quinz=None, prec=None, net=None, ltv=None,
                        ltv_prec=None, fleche="", taux=None, clics=None, niveau="aucun",
                        evo="")
            lignes.append(base)
            continue
        s = [e["suivi"] for e in suivies]
        auj = somme([x.get("auj") for x in s])
        quinz = somme([x.get("quinz") for x in s])
        prec = somme([x.get("prec") for x in s])
        net = somme([x.get("net_quinz") for x in s])
        net_p = somme([x.get("net_prec") for x in s])
        l_q, l_p = ltv(net, quinz), ltv(net_p, prec)
        clics = somme([c[2][0] if marche else c[2][1]
                       for c in (_cellules_lien(e, marche) for e in suivies)])
        taux = (round(quinz * 100.0 / clics, 1)
                if _est_nombre(quinz) and _est_nombre(clics) and clics > 0 else None)
        base.update(auj=auj, quinz=quinz, prec=prec, net=net, ltv=l_q, ltv_prec=l_p,
                    fleche=fleche(l_q, l_p), taux=taux, clics=clics,
                    niveau=niveau_taux(taux, clics),
                    evo=_evo(quinz, auj, prec, bornes, [e.get("depuis") for e in suivies]))
        lignes.append(base)
    # TRIE PAR ABONNES DE LA QUINZAINE EN COURS ; a egalite, celui qui a
    # depense le moins de clics d'abord (il convertit mieux). Les personnes
    # sans lien de suivi ferment la marche, sans rang.
    #
    # UN RANG SEULEMENT POUR UN NOMBRE. Quand la quinzaine n'avait pas pu
    # etre lue, tous valaient « — » et le critere d'egalite (le MOINS de
    # clics) donnait l'or a celui qui n'avait rien fait (relecture du 29/09).
    lignes.sort(key=lambda x: (not x["suivi"], _tri(x["quinz"]),
                               x["clics"] if _est_nombre(x["clics"]) else 10 ** 9,
                               x["titre"].lower()))
    rang = 0
    for x in lignes:
        if x["suivi"] and _est_nombre(x["quinz"]):
            rang += 1
            x["rang"] = rang
        else:
            x["rang"] = None
    return {
        "titre": "Subs",
        "periode": str(periode or ""),
        "espace": str(espace or ""),
        "maj": str(maj or ""),
        "colonnes": list(colonnes or COLONNES)[:4],
        "lignes": lignes[:PLAFOND],
        "caches": max(0, len(lignes) - PLAFOND),
        "personnes": len(lignes),
        "sans_suivi": sum(1 for x in lignes if not x["suivi"]),
        "sans_discord": sum(1 for x in lignes if not x["discord"]),
        # Combien ont un chiffre de quinzaine : a zero, l'image ne dirait
        # que des « — » et le cog garde la section texte.
        "quinz_lus": sum(1 for x in lignes if _est_nombre(x["quinz"])),
        "gabarits": _gabarits(donnees, suivis_seulement=True),
        "rattachements": _cp.bilan_rattachements(gens),
    }


def pseudos(*tables) -> list:
    """Les pseudos Discord dont les images montrent la photo."""
    return sorted({x["discord"] for t in tables for x in (t or {}).get("lignes") or []
                   if x.get("discord")})


def resoudre_pseudos(noms, membres) -> tuple:
    """({pseudo: id du membre}, compte) -- la regle de sessions_voc.attendus_jessye.

    Le pseudo d'une fiche VA est compare au NOM D'UTILISATEUR Discord (pas au
    surnom du serveur), en casefold. Une correspondance UNIQUE, sinon rien :
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

def _p(v):
    return int(round(v * _K))


def _pastille_rang(d, cx, cy, rang, f):
    """Or / argent / bronze pour le podium, sinon le numero."""
    if not rang:
        return
    if rang <= 3:
        fond, encre = _PODIUM[rang - 1]
        d.ellipse((_p(cx - 19), _p(cy - 19), _p(cx + 19), _p(cy + 19)), fill=fond)
        d.text((_p(cx), _p(cy)), str(rang), font=f, fill=encre, anchor="mm")
    else:
        d.text((_p(cx), _p(cy)), str(rang), font=f, fill=TEXTE_2, anchor="mm")


def _l(d, texte, f) -> float:
    """Largeur d'un texte en px FINAUX."""
    return _si._largeur(d, texte, f) / _K


def _entete(img, d, t, titre: str, marge: int, largeur: int, droite_txt: str) -> None:
    """Titre ; dessous « 16 Sep → 30 Sep · in progress · updated 14:30 »."""
    f_titre = police("bold", _p(44))
    f_sous = police("regular", _p(24))
    f_maj = police("bold", _p(24))
    f_compte = police("regular", _p(24))
    d.text((_p(marge), _p(marge)), titre, font=f_titre, fill=TEXTE, anchor="lt")
    fin = _p(largeur - marge)
    if droite_txt:
        d.text((fin, _p(marge + 12)), droite_txt, font=f_compte, fill=TEXTE_2, anchor="rt")
    x = _p(marge)
    # Sur la LIGNE DE BASE (« ls ») : ancre en haut, un « · » seul se
    # dessinait a la hauteur des majuscules, comme un point en l'air.
    y = _p(marge + 86)
    morceaux = [nettoyer(t.get("periode") or "", f_sous)]
    morceaux.append("in progress")
    sous = " · ".join(m for m in morceaux if m)
    maj = ("updated %s" % t["maj"]) if t.get("maj") else ""
    espace = nettoyer(t.get("espace") or "", f_sous)
    l_maj = _si._largeur(d, " · " + maj, f_maj) if maj else 0
    l_esp = _si._largeur(d, espace, f_sous) + _p(24) if espace else 0
    sous = ajuster(d, sous, f_sous, fin - x - l_maj - l_esp)
    d.text((x, y), sous, font=f_sous, fill=TEXTE_2, anchor="ls")
    x += _si._largeur(d, sous, f_sous)
    if maj:
        d.text((x, y), " · ", font=f_sous, fill=TEXTE_3, anchor="ls")
        x += _si._largeur(d, " · ", f_sous)
        d.text((x, y), maj, font=f_maj, fill=VERT_CLAIR, anchor="ls")
    if espace:
        d.text((fin, y), espace, font=f_sous, fill=TEXTE_3, anchor="rs")


def _pied(d, lignes_pied, y, marge, largeur) -> None:
    f_pied = police("bold", _p(24))
    d.line((_p(marge), _p(y), _p(largeur - marge), _p(y)), fill=SEPARATEUR, width=_p(2))
    for k, txt in enumerate(lignes_pied):
        txt = ajuster(d, nettoyer(txt, f_pied), f_pied, _p(largeur - 2 * marge))
        d.text((_p(marge), _p(y + 16 + 36 * k)), txt, font=f_pied, fill=AMBRE, anchor="lt")


def _finir(img, largeur, hauteur, quoi: str) -> bytes:
    final = img.resize((largeur, hauteur), Image.LANCZOS)
    out = io.BytesIO()
    final.save(out, "PNG", optimize=False, compress_level=6)
    octets = out.getvalue()
    if len(octets) > _si.POIDS_MAX:
        raise ValueError("image %s trop lourde (%d octets)" % (quoi, len(octets)))
    return octets


def _rond_personne(img, photos, g, x, y, avatar, nom):
    rond = _si._rond(photos.get(g["discord"]) if g.get("discord") else None,
                     g["cle"], nom or "?", _p(avatar))
    img.paste(rond, (_p(x), _p(y)), rond)


def _cellule_duo(v) -> tuple:
    """(US, global) -> (gros, petit) : le US en gros, le global dessous."""
    us, gl = v
    return nombre(us), nombre(gl)


#: Ou commencent les noms (apres le rang et la photo), en px finaux.
X_NOM = 40 + 62 + 46 + 14
#: La place gardee aux noms, au moins : en dessous, les chiffres rapetissent.
NOM_MIN_CLICS = 230
NOM_MIN_SUBS = 200
#: L'espace minimal entre deux colonnes de chiffres (px finaux).
ECART_COLONNES = 30


def libelle_lien(d, nom: str, f, largeur_max) -> str:
    """Le nom d'un lien en sous-ligne, raccourci SANS perdre ce qui le distingue.

    La personne est deja ecrite sur la ligne du dessus : ce qui distingue ses
    liens, c'est la FIN (« 1 », « 1SP », « 2 »). ajuster() coupe par la fin :
    « (VA 4 Noum) 1SP » devenait « (VA 4 Noum)… », et quatre liens se lisaient
    « (VA 4 N… » (relecture du 29/09). On raccourcit donc d'abord la
    parenthese (« (VA 4…) 1SP »), puis on la retire (« 1SP ») ; ajuster() ne
    sert qu'en dernier recours. `largeur_max` en px internes, comme ajuster()."""
    nom = str(nom or "")
    if _si._largeur(d, nom, f) <= largeur_max:
        return nom
    if nom.startswith("(") and ")" in nom:
        dedans, reste = nom[1:].split(")", 1)
        reste = reste.strip()
        if reste:
            fin = ") " + reste
            for n in range(len(dedans) - 1, 0, -1):
                essai = "(" + dedans[:n].rstrip() + "…" + fin
                if _si._largeur(d, essai, f) <= largeur_max:
                    return essai
            return ajuster(d, reste, f, largeur_max)
    if " " in nom.strip():
        # Sans parenthese (« va_@pseudo 3 ») : meme idee, le dernier mot reste.
        tete, fin = nom.strip().rsplit(" ", 1)
        for n in range(len(tete) - 1, 0, -1):
            essai = tete[:n].rstrip() + "… " + fin
            if _si._largeur(d, essai, f) <= largeur_max:
                return essai
        return ajuster(d, fin, f, largeur_max)
    return ajuster(d, nom, f, largeur_max)


def _mesureur():
    """Un ImageDraw pour MESURER sans dessiner (les tests, le gabarit)."""
    return ImageDraw.Draw(Image.new("RGB", (4, 4)))


def _gabarit_clics(d, t: dict) -> dict:
    """LA LARGEUR DES COLONNES DES CLICS, MESUREE.

    Sur le plus grand nombre de chaque colonne, en gros, en petit et dans les
    sous-lignes (« 4 218 / 11 205 »), plus ECART_COLONNES. Les quatre colonnes
    prennent la largeur de la plus large (des colonnes egales se lisent comme
    une grille) ; si les noms n'ont plus NOM_MIN_CLICS, chacune reprend SA
    largeur, puis les chiffres rapetissent (le gros jamais plus petit que le
    petit). Jamais deux nombres colles -- le defaut de la capture du 29/09
    (« 184421811205 ») ; au pire, c'est le NOM qui est coupe (« … »).

    LA FLECHE D'EVOLUTION a sa place a droite de la quinzaine en cours
    (PLACE_EVO, ajoutee a la largeur de CETTE colonne) : les chiffres restent
    alignes sur leur bord, la fleche ne mord jamais sur la colonne suivante.
    Pas de fleche dans le tableau, pas de place prise."""
    marche = bool(t.get("marche"))
    lignes = t.get("lignes") or []
    reserve = PLACE_EVO if any(g.get("evo") for g in lignes) else 0
    colonnes = list(t.get("colonnes") or COLONNES)[:4]
    while len(colonnes) < 4:
        colonnes.append("")
    f_col = police("bold", _p(22))
    f_col2 = police("regular", _p(20))
    meilleur = None
    for echelle in (1.0, 0.92, 0.84, 0.76, 0.68):
        t_petit = 22 * max(echelle, 0.84)
        f_gros = police("bold", _p(max(28 * echelle, t_petit + 3)))
        f_petit = police("regular", _p(t_petit))
        f_sous = police("regular", _p(t_petit))
        besoins = []
        for k in range(4):
            w = max(_l(d, colonnes[k], f_col),
                    _l(d, "%s / global" % t.get("marche") if marche else "", f_col2))
            for g in lignes:
                gros, petit = _cellule_duo(g["cellules"][k])
                w = max(w, _l(d, gros if marche else petit, f_gros))
                if marche:
                    w = max(w, _l(d, petit, f_petit))
                for li in g.get("liens") or []:
                    a, b = _cellule_duo(li["cellules"][k])
                    w = max(w, _l(d, ("%s / %s" % (a, b)) if marche else b, f_sous))
            besoins.append(w)
        l_col = max(max(besoins) + ECART_COLONNES, 118)
        largeurs = [l_col] * 4
        largeurs[2] += reserve
        x_fin_nom = LARGEUR - 40 - sum(largeurs)
        if x_fin_nom - X_NOM >= NOM_MIN_CLICS:
            break
        largeurs = [max(b + ECART_COLONNES, 100) for b in besoins]
        largeurs[2] += reserve
        x_fin_nom = LARGEUR - 40 - sum(largeurs)
        if x_fin_nom - X_NOM >= NOM_MIN_CLICS:
            break
        # RAPETISSER SANS RIEN GAGNER, NON. Quand ce sont les sous-lignes
        # (dont la police ne descend plus sous 0,84) qui fixent la largeur,
        # descendre a 0,68 reduisait les chiffres principaux de 23 % pour
        # la meme place (relecture du 29/09) : on garde la plus grande
        # echelle qui donne le plus de place aux noms.
        essai = {"besoins": besoins, "largeurs": largeurs, "x_fin_nom": x_fin_nom,
                 "echelle": echelle, "f_gros": f_gros, "f_petit": f_petit, "f_sous": f_sous}
        if meilleur is None or x_fin_nom > meilleur["x_fin_nom"] + 0.5:
            meilleur = essai
    else:
        besoins, largeurs, x_fin_nom = (meilleur["besoins"], meilleur["largeurs"],
                                        meilleur["x_fin_nom"])
        echelle, f_gros, f_petit, f_sous = (meilleur["echelle"], meilleur["f_gros"],
                                            meilleur["f_petit"], meilleur["f_sous"])
    return {"colonnes": colonnes, "besoins": besoins, "largeurs": largeurs,
            "x_fin_nom": x_fin_nom, "echelle": echelle, "reserve": reserve,
            "f_gros": f_gros, "f_petit": f_petit, "f_sous": f_sous}


def gabarit_clics(t: dict) -> dict:
    """Le gabarit des colonnes des clics, sans dessiner (pour les tests)."""
    g = _gabarit_clics(_mesureur(), t)
    return {k: g[k] for k in ("besoins", "largeurs", "x_fin_nom", "echelle", "reserve")}


def dessiner_clics(t: dict, photos: dict = None) -> bytes:
    """Le PNG « Clicks — US vs global ». Leve si l'image est impossible (le
    cog garde alors le tableau par lien en texte).

    `photos` : {pseudo Discord: octets d'image}. Une photo absente ou
    illisible donne un rond aux initiales -- jamais un echec.
    """
    photos = photos or {}
    marche = bool(t.get("marche"))
    largeur, marge = LARGEUR, 40
    h_tete, h_tuile = 118, 106
    h_entete = 64
    h_ligne = 68 if marche else 58
    h_sous = 38
    avatar = 46
    x_rang = marge + 32
    x_photo = marge + 62
    x_nom = X_NOM

    lignes = t.get("lignes") or []
    n_sous = sum(len(x.get("liens") or []) for x in lignes)
    corps = (h_ligne * len(lignes) + h_sous * n_sous + 8 * len(lignes)) if lignes else 90
    pied = []
    if t.get("caches"):
        pied.append("+%d more not shown (limit %d people)" % (t["caches"], PLAFOND))
    if t.get("sans_discord"):
        pied.append("%d without a Discord account on their VA card" % t["sans_discord"])
    if t.get("gabarits"):
        pied.append(_pied_gabarits(t["gabarits"]))
    h_pied = (26 + 36 * len(pied)) if pied else 0
    if not t.get("tuiles"):
        h_tuile = -24                  # pas de tuiles : pas de trou
    hauteur = marge + h_tete + h_tuile + 24 + h_entete + corps + h_pied + 30

    img = Image.new("RGB", (_p(largeur), _p(hauteur)), FOND)
    d = ImageDraw.Draw(img)

    gb = _gabarit_clics(d, t)
    colonnes, x_fin_nom = gb["colonnes"], gb["x_fin_nom"]
    f_gros, f_petit, f_sous_c = gb["f_gros"], gb["f_petit"], gb["f_sous"]
    # Les bords DROITS des colonnes (chiffres alignes a droite).
    x_cols = [x_fin_nom + sum(gb["largeurs"][:k + 1]) - 14 for k in range(4)]
    # La quinzaine en cours s'aligne a gauche de la place de la fleche.
    x_cols[2] -= gb["reserve"]

    # --- en-tete ---------------------------------------------------------
    n_pers = t.get("personnes") or 0
    droite = "%d %s" % (n_pers, "person" if n_pers == 1 else "people")
    if isinstance(t.get("liens"), int):
        droite += " · %d links" % t["liens"]
    _entete(img, d, t, t.get("titre") or "Clicks", marge, largeur, droite)

    # --- les periodes, en tuiles ----------------------------------------
    f_tuile_lib = police("regular", _p(22))
    f_tuile_val = police("bold", _p(36))
    f_tuile_det = police("regular", _p(22))
    y = marge + h_tete
    tuiles = t.get("tuiles") or []
    if tuiles:
        ec = 12
        l_t = (largeur - 2 * marge - ec * (len(tuiles) - 1)) / len(tuiles)
        for i, tu in enumerate(tuiles):
            x = marge + i * (l_t + ec)
            d.rounded_rectangle((_p(x), _p(y), _p(x + l_t), _p(y + h_tuile)),
                                radius=_p(12), fill=FOND_ENTETE)
            cx = x + l_t / 2
            d.text((_p(cx), _p(y + 14)), ajuster(d, nettoyer(tu["quand"], f_tuile_lib),
                                                f_tuile_lib, _p(l_t - 16)),
                   font=f_tuile_lib, fill=TEXTE_2, anchor="mt")
            val = nombre(tu["valeur"])
            d.text((_p(cx), _p(y + 44)), ajuster(d, val, f_tuile_val, _p(l_t - 16)),
                   font=f_tuile_val, fill=TEXTE if val != "—" else TEXTE_3, anchor="mt")
            d.text((_p(cx), _p(y + 84)), ajuster(d, tu["detail"], f_tuile_det, _p(l_t - 16)),
                   font=f_tuile_det, fill=TEXTE_3, anchor="mt")

    # --- en-tetes de colonnes ------------------------------------------
    f_col = police("bold", _p(22))
    f_col2 = police("regular", _p(20))
    y0 = y + h_tuile + 24
    d.rounded_rectangle((_p(marge), _p(y0), _p(largeur - marge), _p(y0 + h_entete - 6)),
                        radius=_p(12), fill=FOND_ENTETE)
    cy = y0 + (h_entete - 6) / 2
    d.text((_p(x_rang), _p(cy)), "#", font=f_col, fill=TEXTE_2, anchor="mm")
    d.text((_p(x_nom), _p(cy)), "VA", font=f_col, fill=TEXTE_2, anchor="lm")
    for k in range(4):
        # La quinzaine en cours est la colonne du tri : en blanc.
        coul = TEXTE if k == 2 else TEXTE_2
        if marche:
            d.text((_p(x_cols[k]), _p(cy - 2)), colonnes[k], font=f_col, fill=coul, anchor="rs")
            d.text((_p(x_cols[k]), _p(cy + 4)), "%s / global" % t["marche"], font=f_col2,
                   fill=TEXTE_3, anchor="rt")
        else:
            d.text((_p(x_cols[k]), _p(cy)), colonnes[k], font=f_col, fill=coul, anchor="rm")

    # --- une ligne par personne, et ses liens dessous ---------------------
    f_rang = police("bold", _p(24))
    f_nom = police("medium", _p(27))
    f_lien = police("regular", _p(22))
    y_corps = y0 + h_entete
    if not lignes:
        d.text((_p(marge + 20), _p(y_corps + 45)),
               "No link read on this period — nothing to show.",
               font=f_nom, fill=TEXTE_2, anchor="lm")
    yl = y_corps
    for r, g in enumerate(lignes):
        sous = g.get("liens") or []
        h_bloc = h_ligne + h_sous * len(sous) + 8
        if r % 2 == 0:
            d.rectangle((_p(marge), _p(yl), _p(largeur - marge), _p(yl + h_bloc)),
                        fill=FOND_LIGNE)
        cy = yl + h_ligne / 2 + 4
        _pastille_rang(d, x_rang, cy, g["rang"], f_rang)
        nom = nettoyer(g["titre"], f_nom)
        _rond_personne(img, photos, g, x_photo, cy - avatar / 2, avatar, nom)
        d.text((_p(x_nom), _p(cy)), ajuster(d, nom or "?", f_nom, _p(x_fin_nom - x_nom - 12)),
               font=f_nom, fill=TEXTE, anchor="lm")
        for k in range(4):
            gros, petit = _cellule_duo(g["cellules"][k])
            if marche and gros == petit and gros in ("—", "·"):
                # Rien de lu (ou pas a lui) des deux cotes : UN signe, pas
                # deux empiles qui se lisaient « = » ou « : ».
                d.text((_p(x_cols[k]), _p(cy)), gros, font=f_gros, fill=TEXTE_3, anchor="rm")
            elif marche:
                d.text((_p(x_cols[k]), _p(cy + 2)), gros, font=f_gros,
                       fill=TEXTE if gros not in ("—", "·") else TEXTE_3, anchor="rs")
                d.text((_p(x_cols[k]), _p(cy + 6)), petit, font=f_petit,
                       fill=TEXTE_3, anchor="rt")
            else:
                d.text((_p(x_cols[k]), _p(cy)), petit, font=f_gros,
                       fill=TEXTE if petit not in ("—", "·") else TEXTE_3, anchor="rm")
        if g.get("evo"):
            # A cote du chiffre qu'elle juge (le US, sinon le global), a sa
            # hauteur : centree sur le dessin reel des chiffres.
            gros2, petit2 = _cellule_duo(g["cellules"][2])
            if marche:
                bb = d.textbbox((_p(x_cols[2]), _p(cy + 2)), gros2, font=f_gros, anchor="rs")
            else:
                bb = d.textbbox((_p(x_cols[2]), _p(cy)), petit2, font=f_gros, anchor="rm")
            _fleche_evo(d, x_cols[2] + ECART_EVO, (bb[1] + bb[3]) / 2 / _K, g["evo"])
        ys = yl + h_ligne + 4
        for li in sous:
            cs = ys + h_sous / 2
            d.line((_p(x_nom + 6), _p(ys - 2), _p(x_nom + 6), _p(ys + h_sous - 6)),
                   fill=SEPARATEUR, width=_p(2))
            lab = nettoyer(li["nom"], f_lien) or "?"
            d.text((_p(x_nom + 20), _p(cs)), libelle_lien(d, lab, f_lien, _p(x_fin_nom - x_nom - 32)),
                   font=f_lien, fill=TEXTE_2, anchor="lm")
            for k in range(4):
                a, b = _cellule_duo(li["cellules"][k])
                if marche and a == b and a in ("—", "·"):
                    d.text((_p(x_cols[k]), _p(cs)), a, font=f_sous_c, fill=TEXTE_3, anchor="rm")
                elif marche:
                    # « 63 / 161 » : le US en clair, « / global » en retrait.
                    fin_b = " / %s" % b
                    d.text((_p(x_cols[k]), _p(cs)), fin_b, font=f_sous_c, fill=TEXTE_3, anchor="rm")
                    d.text((_p(x_cols[k] - _l(d, fin_b, f_sous_c)), _p(cs)), a, font=f_sous_c,
                           fill=TEXTE_2, anchor="rm")
                else:
                    d.text((_p(x_cols[k]), _p(cs)), b, font=f_sous_c, fill=TEXTE_2, anchor="rm")
            ys += h_sous
        yl += h_bloc

    if pied:
        _pied(d, pied, yl + 14, marge, largeur)
    return _finir(img, largeur, hauteur, "des clics")


def _triangle(d, x, cy, haut: bool, couleur, taille: float = 12) -> None:
    """Une fleche dessinee (la police n'a pas ↑ ↓ partout) : 12 px par defaut."""
    k = taille / 12.0
    if haut:
        pts = [(x, cy + 5 * k), (x + 12 * k, cy + 5 * k), (x + 6 * k, cy - 6 * k)]
    else:
        pts = [(x, cy - 5 * k), (x + 12 * k, cy - 5 * k), (x + 6 * k, cy + 6 * k)]
    d.polygon([(_p(a), _p(b)) for a, b in pts], fill=couleur)


def _fleche_evo(d, x, cy, sens: str, taille: float = TAILLE_EVO) -> None:
    """La fleche d'evolution, de `x` a `x + taille` (px finaux), centree sur cy :
    triangle vert vers le haut, fleche orange horizontale, triangle rouge vers
    le bas. Dessinee : la police n'a pas les emoji."""
    if sens == "haut":
        _triangle(d, x, cy, True, VERT_EVO, taille)
    elif sens == "bas":
        _triangle(d, x, cy, False, ROUGE_EVO, taille)
    elif sens == "stable":
        # « → » : un trait et une pointe, pour ne pas se lire « lecture ».
        ep = taille * 0.14
        d.rectangle((_p(x), _p(cy - ep), _p(x + taille * 0.6), _p(cy + ep)), fill=ORANGE_EVO)
        d.polygon([(_p(x + taille * 0.42), _p(cy - taille * 0.42)), (_p(x + taille), _p(cy)),
                   (_p(x + taille * 0.42), _p(cy + taille * 0.42))], fill=ORANGE_EVO)


def _gabarit_subs(d, t: dict) -> dict:
    """Les quatre colonnes des abonnes : Today, 16–30 (en gras : la quinzaine
    en cours), 1–15, Conv. Largeurs MESUREES sur le plus long texte de
    chacune, comme pour les clics ; la conversion prend la largeur de sa
    pastille.

    AUCUN MONTANT. Le proprietaire, le 29/09 au soir : « combien d'argent net
    ils ont rapporte a l'agence, il ne faut surtout pas mettre ca ». L'image
    part dans #click, que les VA lisent. La LTV sort aussi : multipliee par
    les abonnes, elle redonne le net.

    La fleche d'evolution des abonnes a sa place (PLACE_EVO) a droite de la
    colonne 16–30, comptee dans SA largeur, comme pour les clics."""
    lignes = t.get("lignes") or []
    reserve = PLACE_EVO if any(g.get("evo") for g in lignes) else 0
    colonnes = list(t.get("colonnes") or COLONNES)[:4]
    while len(colonnes) < 4:
        colonnes.append("")
    entetes = [colonnes[0], colonnes[2], colonnes[3], "Conv."]
    f_col = police("bold", _p(22))
    meilleur = None
    for echelle in (1.0, 0.9, 0.8, 0.72):
        f_ch = police("medium", _p(26 * echelle))
        f_ch_b = police("bold", _p(28 * echelle))
        f_pastille = police("bold", _p(22 * max(echelle, 0.9)))
        valeurs = [[], [], [], []]
        for g in lignes:
            valeurs[0].append((nombre(g["auj"]), f_ch))
            valeurs[1].append((nombre(g["quinz"]), f_ch_b))
            valeurs[2].append((nombre(g["prec"]), f_ch))
            valeurs[3].append((taux_txt(g["taux"]), f_pastille))
        besoins = []
        for k in range(4):
            w = _l(d, entetes[k], f_col)
            for txt, f in valeurs[k]:
                w = max(w, _l(d, txt, f) + (26 if k == 3 else 0))
            besoins.append(w + 26)
        besoins[3] = max(besoins[3], 116)
        besoins[1] += reserve
        x_fin_nom = LARGEUR - 40 - sum(besoins)
        if x_fin_nom - X_NOM >= NOM_MIN_SUBS:
            break
        # Meme regle que les clics : pas de chiffres plus petits pour rien.
        if meilleur is None or x_fin_nom > meilleur[2] + 0.5:
            meilleur = (echelle, besoins, x_fin_nom, f_ch, f_ch_b, f_pastille)
    else:
        echelle, besoins, x_fin_nom, f_ch, f_ch_b, f_pastille = meilleur
    return {"entetes": entetes, "besoins": besoins, "x_fin_nom": x_fin_nom,
            "echelle": echelle, "reserve": reserve, "f_col": f_col, "f_ch": f_ch, "f_ch_b": f_ch_b,
            "f_pastille": f_pastille}


def gabarit_subs(t: dict) -> dict:
    """Le gabarit des colonnes des abonnes, sans dessiner (pour les tests)."""
    g = _gabarit_subs(_mesureur(), t)
    return {k: g[k] for k in ("besoins", "x_fin_nom", "echelle", "reserve")}


def dessiner_subs(t: dict, photos: dict = None) -> bytes:
    """Le PNG « Subs ». Leve si l'image est impossible (le cog garde
    alors la section Subscribers en texte)."""
    photos = photos or {}
    largeur, marge = LARGEUR, 40
    h_tete = 118
    h_entete = 56
    h_ligne = 60
    avatar = 46
    x_rang = marge + 32
    x_photo = marge + 62
    x_nom = X_NOM

    lignes = t.get("lignes") or []
    corps = h_ligne * len(lignes) if lignes else 90
    pied = []
    if t.get("caches"):
        pied.append("+%d more not shown (limit %d people)" % (t["caches"], PLAFOND))
    if t.get("sans_suivi"):
        n = t["sans_suivi"]
        pied.append("%d %s without a MyPuls tracking link — subs unknown, not zero"
                    % (n, "person" if n == 1 else "people"))
    if t.get("gabarits"):
        pied.append(_pied_gabarits(t["gabarits"]))
    h_pied = (26 + 36 * len(pied)) if pied else 0
    hauteur = marge + h_tete + 10 + h_entete + corps + h_pied + 30

    img = Image.new("RGB", (_p(largeur), _p(hauteur)), FOND)
    d = ImageDraw.Draw(img)

    gb = _gabarit_subs(d, t)
    entetes, besoins, x_fin_nom = gb["entetes"], gb["besoins"], gb["x_fin_nom"]
    f_col, f_ch, f_ch_b, f_pastille = gb["f_col"], gb["f_ch"], gb["f_ch_b"], gb["f_pastille"]
    # Bords droits des colonnes (chiffres alignes a droite ; Conv. centree).
    bords, x = [], x_fin_nom
    for w in besoins:
        x += w
        bords.append(x - 12)
    x_conv = bords[3] - (besoins[3] - 12) / 2
    # Les abonnes de la quinzaine s'alignent a gauche de la place de la fleche.
    bords[1] -= gb["reserve"]

    n_pers = t.get("personnes") or 0
    droite = "%d %s" % (n_pers, "person" if n_pers == 1 else "people")
    _entete(img, d, t, t.get("titre") or "Subs", marge, largeur, droite)

    y0 = marge + h_tete + 10
    d.rounded_rectangle((_p(marge), _p(y0), _p(largeur - marge), _p(y0 + h_entete - 6)),
                        radius=_p(12), fill=FOND_ENTETE)
    cy = y0 + (h_entete - 6) / 2
    d.text((_p(x_rang), _p(cy)), "#", font=f_col, fill=TEXTE_2, anchor="mm")
    d.text((_p(x_nom), _p(cy)), "VA", font=f_col, fill=TEXTE_2, anchor="lm")
    for k in range(4):
        coul = TEXTE if k == 1 else TEXTE_2
        if k == 3:
            d.text((_p(x_conv), _p(cy)), entetes[k], font=f_col, fill=coul, anchor="mm")
        else:
            d.text((_p(bords[k]), _p(cy)), entetes[k], font=f_col, fill=coul, anchor="rm")

    f_rang = police("bold", _p(24))
    f_nom = police("medium", _p(27))
    y_corps = y0 + h_entete
    if not lignes:
        d.text((_p(marge + 20), _p(y_corps + 45)), "No link read on this period.",
               font=f_nom, fill=TEXTE_2, anchor="lm")
    for r, g in enumerate(lignes):
        yl = y_corps + r * h_ligne
        cy = yl + h_ligne / 2
        if r % 2 == 0:
            d.rectangle((_p(marge), _p(yl), _p(largeur - marge), _p(yl + h_ligne)), fill=FOND_LIGNE)
        _pastille_rang(d, x_rang, cy, g.get("rang"), f_rang)
        nom = nettoyer(g["titre"], f_nom)
        _rond_personne(img, photos, g, x_photo, yl + (h_ligne - avatar) / 2, avatar, nom)
        d.text((_p(x_nom), _p(cy)), ajuster(d, nom or "?", f_nom, _p(x_fin_nom - x_nom - 12)),
               font=f_nom, fill=TEXTE if g["suivi"] else TEXTE_2, anchor="lm")

        def _chiffre(k, txt, f, fort=False):
            vide = txt in ("—", "·")
            d.text((_p(bords[k]), _p(cy)), txt, font=f,
                   fill=TEXTE_3 if vide else (TEXTE if fort else TEXTE_2), anchor="rm")

        _chiffre(0, nombre(g["auj"]), f_ch)
        _chiffre(1, nombre(g["quinz"]), f_ch_b, fort=True)
        if g.get("evo"):
            bb = d.textbbox((_p(bords[1]), _p(cy)), nombre(g["quinz"]), font=f_ch_b, anchor="rm")
            _fleche_evo(d, bords[1] + ECART_EVO, (bb[1] + bb[3]) / 2 / _K, g["evo"])
        _chiffre(2, nombre(g["prec"]), f_ch)
        if g["niveau"] == "aucun":
            d.text((_p(x_conv), _p(cy)), "—", font=f_ch, fill=TEXTE_3, anchor="mm")
        else:
            lp = max(_l(d, taux_txt(g["taux"]), f_pastille) + 26, 96) / 2
            d.rounded_rectangle((_p(x_conv - lp), _p(cy - 19), _p(x_conv + lp), _p(cy + 19)),
                                radius=_p(19), fill=_FOND_PASTILLE[g["niveau"]])
            d.text((_p(x_conv), _p(cy)), taux_txt(g["taux"]), font=f_pastille,
                   fill=_ENCRE_PASTILLE[g["niveau"]], anchor="mm")

    if pied:
        _pied(d, pied, y_corps + corps + 14, marge, largeur)
    return _finir(img, largeur, hauteur, "des abonnes")


def texte_alt_clics(t: dict) -> str:
    """La description de l'image (lecteurs d'ecran, survol dans Discord)."""
    tete = (t.get("lignes") or [])[:3]
    podium = ", ".join("%s %s" % (x["titre"], nombre(x["cellules"][2][0] if t.get("marche")
                                                     else x["cellules"][2][1]))
                       for x in tete)
    return ("%s %s: %d people%s" % (
        t.get("titre") or "Clicks", t.get("periode") or "", t.get("personnes") or 0,
        (" — top: " + podium) if podium else ""))[:1024]


def texte_alt_subs(t: dict) -> str:
    tete = [x for x in (t.get("lignes") or []) if x.get("suivi")][:3]
    podium = ", ".join("%s %s subs" % (x["titre"], nombre(x["quinz"])) for x in tete)
    return ("Subs %s: %d people%s" % (
        t.get("periode") or "", t.get("personnes") or 0,
        (" — top: " + podium) if podium else ""))[:1024]
