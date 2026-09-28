# -*- coding: utf-8 -*-
"""Le bilan des sessions vocales en IMAGE : un tableau, avec les photos.

POURQUOI UNE IMAGE
------------------
Le bilan texte du 27/09 faisait environ soixante-dix lignes : une section par
session, une ligne par VA. Le proprietaire l'a trouve illisible et a choisi,
parmi trois maquettes, la « A » : un tableau (une ligne par VA, une colonne
par session, un total), les photos de profil, et en bas les absents de toute
la journee. Ce module ne fait QUE le dessin : ni Discord, ni reseau, ni
fichier ecrit. Il se teste donc seul, et le cog lui passe tout ce qu'il faut.

A QUELLE TAILLE IL SERA LU
--------------------------
Discord n'affiche pas une image a sa taille reelle : une image d'embed est
reduite a ~400 px de large (et ~300 de haut), une piece jointe simple ou une
galerie « Components V2 » a une seule image a ~550 px sur ordinateur. Le
message est donc une galerie V2 (la plus large des trois), et l'image fait
1100 px de large : affichee a ~550, elle est reduite de moitie, d'ou des
textes de 24 px au minimum (12 px a l'ecran) et 27-28 px pour les noms.
Dessine au double (2200 px) puis reduit : les ronds et les pastilles sont
lisses, Pillow ne lissant pas ses formes.
La largeur reste 1100 jusqu'a cinq sessions (une image plus large est
reduite d'autant a l'affichage). La hauteur suit le jour : le vrai 27/09
(7 lignes, 11 absents) tient en 1100 x 1096, a peine moins haut que large ;
au-dela il devient portrait. Discord plafonne-t-il la hauteur d'une galerie
a une image ? Non verifie : a regarder avec /demosessions.

CE QUI N'EST JAMAIS CACHE
-------------------------
- une personne vue mais absente de la liste des attendus : sa ligne porte
  « hors liste » (le bilan texte la filtrait : Bo07, 1 h 16 le 27/09, ne
  figurait nulle part) ;
- une session non surveillee, en cours ou a venir : colonne hachuree et
  etiquetee, aucune absence n'en est deduite ;
- liste des attendus inconnue : pas de section « absents », et c'est ecrit ;
- soixante VA : l'image grandit en hauteur, aucune ligne n'est coupee ;
- une photo absente ou illisible : un rond aux initiales ;
- un caractere que la police ne sait pas dessiner (emoji) : retire, pour ne
  pas laisser un carre vide dans un nom.
"""
import datetime as _dt
import hashlib
import io
import unicodedata
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

#: Largeur FINALE de l'image (voir « A quelle taille il sera lu »).
LARGEUR = 1100
#: Facteur de sur-echantillonnage : on dessine a 2x puis on reduit.
_K = 2

_DOSSIER_POLICES = Path(__file__).resolve().parent / "noctus" / "fonts"
#: (fichier, graisse pour une police variable). LES « Inter-*.ttf » DU DEPOT
#: SONT DES PAGES HTML (un telechargement rate, 28/09/2026 : « <!DOCTYPE
#: html> » en tete, sur le Mac comme sur le VPS) : Pillow les refuse. Sans
#: repli, le dessin tombait sur la police interne de Pillow, qui n'a ni « é »
#: ni « — » : « Gérôme » devenait « Grme ». Montserrat, elle, est dans git,
#: complete (accents, tirets) et variable : une graisse par usage.
_POLICES = {
    "regular": [("Inter-Regular.ttf", None), ("Montserrat-Bold.ttf", 400), ("DejaVuSans.ttf", None)],
    "medium": [("Inter-Medium.ttf", None), ("Montserrat-Bold.ttf", 500), ("DejaVuSans.ttf", None)],
    "bold": [("Inter-Bold.ttf", None), ("Montserrat-Bold.ttf", 700), ("DejaVuSans-Bold.ttf", None)],
}
_DEJAVU = Path("/usr/share/fonts/truetype/dejavu")

# Couleurs du theme sombre de Discord : l'image se pose dans le salon sans
# faire tache.
FOND = (43, 45, 49)
FOND_LIGNE = (49, 51, 56)
FOND_ENTETE = (35, 36, 40)
FOND_COLONNE_GRISE = (38, 39, 43)
HACHURE = (58, 60, 66)
TEXTE = (242, 243, 245)
TEXTE_2 = (181, 186, 193)
TEXTE_3 = (128, 132, 142)
VERT = (36, 128, 70)
ORANGE = (240, 178, 50)
ORANGE_TEXTE = (30, 31, 34)
AMBRE = (250, 190, 90)
BLEU = (88, 101, 242)
SEPARATEUR = (63, 65, 71)
_PALETTE_INITIALES = [(88, 101, 242), (35, 165, 90), (235, 69, 158), (237, 66, 69),
                      (250, 166, 26), (26, 188, 156), (155, 89, 182), (52, 152, 219)]

_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre"]

#: Au-dela, Discord refuserait la piece jointe d'un bot (10 Mo) : mieux vaut
#: lever ici et laisser le cog retomber sur le bilan texte.
POIDS_MAX = 8 * 1024 * 1024


# ==============================================================================
# Les donnees : qui figure dans le tableau, et comment
# ==============================================================================

def duree(secondes) -> str:
    """« 3 min », « 1 h 27 » — la forme du bilan texte, pour ne pas en avoir deux."""
    m = int(secondes or 0) // 60
    return "%d min" % m if m < 60 else "%d h %02d" % divmod(m, 60)


def nom_court(nom: str) -> tuple:
    """(premier compte, nombre d'autres comptes).

    « VA NOUM 1X1 / VA NOUM 2X1 / … / VA NOUM 6x1 » est UNE personne avec six
    fiches : afficher les six ne tient pas dans une colonne et ne dit rien de
    plus. Le premier segment identifie la personne, « +5 » dit qu'il y en a
    d'autres.
    """
    segments = [s.strip() for s in str(nom or "").split("/") if s.strip()]
    if not segments:
        return "", 0
    return segments[0], len(segments) - 1


def etat_session(s: dict, maintenant: float) -> str:
    """« jugee », « non_suivie », « a_venir » ou « en_cours »."""
    if not s.get("surveillee", True):
        return "non_suivie"
    if not s.get("terminee", True):
        try:
            if float(s.get("debut")) > float(maintenant):
                return "a_venir"
        except (TypeError, ValueError):
            pass
        return "en_cours"
    return "jugee"


def tableau(resume: dict, attendus, maintenant: float = None) -> dict:
    """Ce que l'image montre, calcule sans rien dessiner (et donc testable).

    `resume` vient de `sessions_voc.resume_jour(..., limiter_aux_attendus=
    False)` : TOUS ceux que le registre a vus. Ceux qui ne sont pas dans
    `attendus` restent, marques « hors liste » -- les filtrer, c'etait les
    faire disparaitre du bilan sans un mot.
    """
    import time as _t
    maintenant = _t.time() if maintenant is None else float(maintenant)
    attendus = [a for a in (attendus or []) if isinstance(a, dict) and a.get("id")]
    index = {str(a["id"]): a for a in attendus}
    liste_connue = bool(index)
    colonnes, gens = [], {}
    for s in resume.get("sessions") or []:
        etat = etat_session(s, maintenant)
        hl = s.get("heures_locales") or {}
        colonnes.append({"id": s["id"], "nom": s.get("nom") or s["id"],
                         "heure": hl.get("BJ") or s.get("heure") or "?",
                         "mg": hl.get("MG") or "", "etat": etat})
        for statut, cle in (("present", "presents"), ("partiel", "partiels")):
            for p in s.get(cle) or []:
                uid = str(p.get("id") or "")
                if not uid:
                    continue
                g = gens.setdefault(uid, {
                    "id": uid,
                    # Le nom du SITE quand la personne est attendue : c'est
                    # celui que le proprietaire connait.
                    "nom": (index.get(uid) or {}).get("nom") or p.get("nom") or uid,
                    "attendu": uid in index, "cellules": {}, "total": 0})
                g["cellules"][s["id"]] = (statut, int(p.get("secondes") or 0))
                g["total"] += int(p.get("secondes") or 0)
    lignes = sorted(gens.values(), key=lambda g: (-g["total"], g["nom"].casefold()))
    jugees = [c for c in colonnes if c["etat"] == "jugee"]
    absents_etablis = liste_connue and bool(jugees)
    absents = ([dict(a, id=str(a["id"])) for a in attendus if str(a["id"]) not in gens]
               if absents_etablis else [])
    absents.sort(key=lambda a: str(a.get("nom") or "").casefold())
    return {
        "jour": resume.get("jour"), "fuseau": resume.get("fuseau") or "",
        "colonnes": colonnes, "lignes": lignes, "absents": absents,
        "liste_connue": liste_connue, "absents_etablis": absents_etablis,
        # « absents toute la journee » n'est vrai que si TOUTES les sessions
        # ont ete jugees ; sinon on dit « aux sessions terminees ».
        "journee_complete": bool(colonnes) and len(jugees) == len(colonnes),
        "attendus": len(index),
        "attendus_vus": sum(1 for g in lignes if g["attendu"]),
        "hors_liste": sum(1 for g in lignes if not g["attendu"]) if liste_connue else 0,
    }


def ids_dessines(resume: dict, attendus) -> list:
    """Les identifiants dont l'image montre la photo (pour aller les chercher)."""
    t = tableau(resume, attendus)
    return [g["id"] for g in t["lignes"]] + [a["id"] for a in t["absents"]]


# ==============================================================================
# Le texte : polices, caracteres dessinables, coupe
# ==============================================================================

_CACHE_POLICES = {}
_CACHE_GLYPHES = {}


def police(poids: str, taille: int):
    """Inter, sinon Montserrat (dans git), sinon DejaVu (VPS), sinon Pillow."""
    cle = (poids, taille)
    if cle in _CACHE_POLICES:
        return _CACHE_POLICES[cle]
    f = None
    for nom, graisse in _POLICES.get(poids, _POLICES["regular"]):
        for dossier in (_DOSSIER_POLICES, _DEJAVU):
            try:
                f = ImageFont.truetype(str(dossier / nom), taille)
                if graisse is not None:
                    # Une police variable s'ouvre a sa graisse PAR DEFAUT --
                    # pour Montserrat, « Thin » : illisible reduit de moitie.
                    f.set_variation_by_axes([graisse])
                break
            except Exception:                         # noqa: BLE001
                f = None
                continue
        if f is not None:
            break
    if f is None:
        print("[sessions] aucune police lisible : police interne de Pillow "
              "(sans accents)", flush=True)
        f = ImageFont.load_default(size=taille)
    _CACHE_POLICES[cle] = f
    return f


def nom_police(f) -> str:
    """La famille de la police chargee (« Montserrat »), pour les tests et le journal.

    La famille seule : pour une police variable, Pillow rend le style de
    l'instance PAR DEFAUT (« Thin ») meme apres le choix de la graisse.
    """
    try:
        return str(f.getname()[0] or "")
    except Exception:                                 # noqa: BLE001
        return type(f).__name__


def _dessinable(f, ch: str) -> bool:
    """La police a-t-elle un dessin pour ce caractere, ou rendrait-elle un carre ?

    On compare au rendu d'un caractere a coup sur absent (zone privee du
    plan 16) : meme masque = le « carre vide » de la police.
    """
    if ch.isspace():
        return True
    cle = (id(f), ch)
    if cle not in _CACHE_GLYPHES:
        try:
            vide = _CACHE_GLYPHES.get((id(f), None))
            if vide is None:
                m = f.getmask("\U0010FFFD")
                vide = (m.size, bytes(m))
                _CACHE_GLYPHES[(id(f), None)] = vide
            m = f.getmask(ch)
            _CACHE_GLYPHES[cle] = (m.size, bytes(m)) != vide
        except Exception:
            _CACHE_GLYPHES[cle] = False
    return _CACHE_GLYPHES[cle]


def nettoyer(texte: str, f) -> str:
    """Retire ce que la police ne sait pas dessiner (emojis, symboles rares)."""
    t = unicodedata.normalize("NFC", str(texte or ""))
    out = []
    for ch in t:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Cs", "Co", "Cn") or 0xFE00 <= ord(ch) <= 0xFE0F \
                or 0x1F3FB <= ord(ch) <= 0x1F3FF:
            continue
        if cat == "So" or not _dessinable(f, ch):
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def _largeur(dessin, texte, f) -> int:
    return int(dessin.textlength(texte, font=f))


def ajuster(dessin, texte: str, f, largeur_max: int) -> str:
    """Le texte, raccourci d'un « … » s'il deborde. Jamais de debordement."""
    if _largeur(dessin, texte, f) <= largeur_max:
        return texte
    bas, haut = 0, len(texte)
    while bas < haut:
        milieu = (bas + haut + 1) // 2
        if _largeur(dessin, texte[:milieu].rstrip() + "…", f) <= largeur_max:
            bas = milieu
        else:
            haut = milieu - 1
    return texte[:bas].rstrip() + "…"


def lignes_etiquette(dessin, texte: str, f, largeur_max: int) -> list:
    """L'etiquette d'une colonne, sur deux lignes si elle deborde.

    « non suivie » (128 px en gras 24) remplit une colonne de 128 : deux
    colonnes voisines non suivies donnaient « non suivienon suivie ».
    """
    if _largeur(dessin, texte, f) <= largeur_max or " " not in texte:
        return [texte]
    return texte.split(" ", 1)


def libelle_absent(dessin, nom: str, suffixe: str, f, largeur_max: int) -> str:
    """Le nom d'un absent tronque, PUIS son « +N » : jamais avale par le « … ».

    Tronque avec le nom, le « +2 » de « Gérôme Ñúñez Ëlodie +2 » disparaissait,
    alors que la meme personne presente affiche « +2 comptes ».
    """
    return ajuster(dessin, nom, f, max(0, largeur_max - _largeur(dessin, suffixe, f))) + suffixe


def texte_compteur(vus: int, liste_connue: bool = True) -> str:
    """« 1 VA présent », « 6 VA présents » (« 1 VA présents » etait lu en premier)."""
    s = "s" if vus > 1 else ""
    return ("%d VA présent%s" % (vus, s)) if liste_connue else ("%d VA vu%s" % (vus, s))


# ==============================================================================
# Les photos
# ==============================================================================

def _initiales(nom: str) -> str:
    """« Gérôme X1 » -> « GÉ », « Maon 1 IPHONE X » -> « MI ».

    Les mots d'une seule lettre (« X1 », « X ») sont des numeros de compte,
    pas des noms : « Bo07 X1 » donnait « BX ».
    """
    court, _ = nom_court(nom)
    mots = [m for m in court.split() if sum(c.isalpha() for c in m) >= 2]
    if not mots:
        mots = [m for m in court.split() if any(c.isalpha() for c in m)]
    if len(mots) >= 2:
        lettres = "".join(next(c for c in m if c.isalpha()) for m in mots[:2])
    elif mots:
        lettres = "".join(c for c in mots[0] if c.isalpha())[:2]
    else:
        lettres = ""
    return (lettres or "?").upper()


def _rond(photo, uid: str, nom: str, taille: int, attenue: bool = False) -> Image.Image:
    """Un disque de `taille` px : la photo, ou les initiales si elle manque."""
    grand = taille * 4
    img = None
    if photo:
        try:
            src = Image.open(io.BytesIO(photo))
            src.load()
            src = src.convert("RGBA")
            cote = min(src.size)
            gauche, haut = (src.width - cote) // 2, (src.height - cote) // 2
            img = src.crop((gauche, haut, gauche + cote, haut + cote)).resize(
                (grand, grand), Image.LANCZOS)
        except Exception:
            img = None
    if img is None:
        n = int(hashlib.md5(str(uid).encode()).hexdigest(), 16)
        img = Image.new("RGBA", (grand, grand), _PALETTE_INITIALES[n % len(_PALETTE_INITIALES)] + (255,))
        d = ImageDraw.Draw(img)
        f = police("bold", int(grand * 0.40))
        d.text((grand / 2, grand / 2), _initiales(nom), font=f, fill=(255, 255, 255), anchor="mm")
    # La transparence de la photo, gardee : un avatar detoure (logo, PNG a
    # fond transparent) sortait sur un disque NOIR -- Pillow ramene un pixel
    # transparent a (0,0,0,0) en redimensionnant, et remplacer l'alpha par le
    # disque rendait ce noir opaque. Un logo sombre y disparaissait, alors
    # que Discord le montre sur le fond du salon.
    alpha = img.getchannel("A")
    if attenue:
        gris = img.convert("L").convert("RGBA")
        img = Image.blend(gris, Image.new("RGBA", gris.size, FOND + (255,)), 0.45)
    masque = Image.new("L", (grand, grand), 0)
    ImageDraw.Draw(masque).ellipse((0, 0, grand - 1, grand - 1), fill=255)
    img.putalpha(ImageChops.multiply(masque, alpha))
    return img.resize((taille, taille), Image.LANCZOS)


# ==============================================================================
# Le dessin
# ==============================================================================

def _titre_jour(jour: str) -> tuple:
    try:
        d = _dt.date.fromisoformat(str(jour))
    except ValueError:
        return "Sessions du %s" % jour, ""
    return ("Sessions du %02d/%02d" % (d.day, d.month),
            "%s %d %s %d" % (_JOURS[d.weekday()], d.day, _MOIS[d.month - 1], d.year))


def _fuseau_lisible(fuseau: str) -> str:
    return "heures du Bénin" if fuseau in ("Africa/Porto-Novo", "") else "heures %s" % fuseau


_ETIQUETTES = {"non_suivie": "non suivie", "en_cours": "en cours", "a_venir": "à venir"}


def dessiner_bilan(resume: dict, attendus, photos: dict, jour: str = "",
                   maintenant: float = None) -> bytes:
    """Le PNG du bilan de la journee. Leve si l'image est impossible.

    `photos` : {id: octets d'image}. Une photo absente ou illisible donne un
    rond aux initiales -- jamais un echec.
    """
    t = tableau(resume, attendus, maintenant)
    photos = photos or {}
    jour = jour or t["jour"] or ""
    K = _K

    def p(v):
        return int(round(v * K))

    # --- polices (tailles FINALES, en px de l'image a 1100 de large) ------
    f_titre = police("bold", p(46))
    f_sous = police("regular", p(24))
    f_compte = police("bold", p(34))
    f_compte2 = police("regular", p(25))
    f_heure = police("bold", p(32))
    f_petit = police("regular", p(24))
    f_petit_b = police("bold", p(24))
    f_nom = police("medium", p(27))
    f_pastille = police("bold", p(25))
    f_total = police("bold", p(28))
    f_section = police("bold", p(28))
    f_absent = police("regular", p(25))

    # --- geometrie ---------------------------------------------------------
    # Une feuille de mesure : les choix de mise en page (etiquettes sur deux
    # lignes, absents sur 3 ou 4 colonnes) dependent de la largeur des textes.
    mesure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    marge = 40
    col_total, col_nom_min = 116, 284
    n = max(1, len(t["colonnes"]))
    # 4 sessions (la configuration du 28/09) : 128 px chacune, 392 pour les
    # noms. Au-dela, les sessions se serrent (124 px au moins : « MG 04:00 »
    # en fait 117) et la colonne des noms cede de la place, pour RESTER a
    # 1100 px : une image plus large est reduite plus fort a l'affichage, et
    # a 6 sessions le texte tombait a 9,7 px a l'ecran.
    col_session = max(124, min(128, (LARGEUR - 2 * marge - col_total - col_nom_min) // n))
    largeur = max(LARGEUR, 2 * marge + col_nom_min + n * col_session + col_total)
    if largeur > LARGEUR:
        print("[sessions] %d sessions : image élargie à %d px, texte réduit d'autant "
              "à l'affichage" % (n, largeur), flush=True)
    col_nom = largeur - 2 * marge - n * col_session - col_total
    h_tete = 120
    avec_etat = any(c["etat"] != "jugee" for c in t["colonnes"])
    # Trop large pour sa colonne, l'etiquette passe sur deux lignes.
    etiquettes = {}
    for c in t["colonnes"]:
        if c["etat"] != "jugee":
            etiquettes[c["id"]] = lignes_etiquette(mesure, _ETIQUETTES[c["etat"]], f_petit_b,
                                                   p(col_session - 14))
    deux_lignes = any(len(v) > 1 for v in etiquettes.values())
    h_entete = 112 + (30 if avec_etat else 0) + (28 if deux_lignes else 0)
    # 72 px par ligne (et 54 par rang d'absents) : a 84/60, le vrai 27/09
    # (7 lignes, 11 absents) sortait en portrait, 1100 x 1230.
    h_ligne = 72
    h_vide = 96
    avatar = 56
    h_abs = 54
    petit = 44

    # Les absents : nom court et « +N » gardes a part (libelle_absent). Quatre
    # colonnes si tous tiennent entiers, sinon trois : un nom coupe vaut
    # moins qu'un rang de plus.
    libelles_abs = []
    for a in t["absents"]:
        court, autres = nom_court(a.get("nom"))
        court = nettoyer(court, f_absent)
        libelles_abs.append((court, court or "VA …%s" % str(a["id"])[-4:],
                             " +%d" % autres if autres else ""))

    def place_abs(nb):
        return p((largeur - 2 * marge) / nb - petit - 28)

    nb_col_abs = 4 if libelles_abs and all(
        _largeur(mesure, nom + suf, f_absent) <= place_abs(4)
        for _, nom, suf in libelles_abs) else 3

    corps = h_ligne * len(t["lignes"]) if t["lignes"] else h_vide
    if t["absents_etablis"]:
        rangs = (len(t["absents"]) + nb_col_abs - 1) // nb_col_abs
        bas = 30 + 42 + (h_abs * rangs if rangs else 48)
    else:
        bas = 30 + 66
    hauteur = marge + h_tete + h_entete + corps + bas + 32

    img = Image.new("RGB", (p(largeur), p(hauteur)), FOND)
    d = ImageDraw.Draw(img)

    # --- titre et compteur --------------------------------------------------
    titre, date_longue = _titre_jour(jour)
    d.text((p(marge), p(marge)), titre, font=f_titre, fill=TEXTE, anchor="lt")
    sous = " · ".join(x for x in (date_longue, _fuseau_lisible(t["fuseau"])) if x)
    d.text((p(marge), p(marge + 62)), sous, font=f_sous, fill=TEXTE_2, anchor="lt")
    droite = p(largeur - marge)
    if t["liste_connue"]:
        fin = " sur %d" % t["attendus"]
        d.text((droite, p(marge + 4)), fin, font=f_compte2, fill=TEXTE_2, anchor="rt")
        x_fin = droite - _largeur(d, fin, f_compte2)
        d.text((x_fin, p(marge)), texte_compteur(t["attendus_vus"]),
               font=f_compte, fill=TEXTE, anchor="rt")
        if t["hors_liste"]:
            d.text((droite, p(marge + 62)), "+ %d hors liste" % t["hors_liste"],
                   font=f_petit_b, fill=AMBRE, anchor="rt")
    else:
        d.text((droite, p(marge)), texte_compteur(len(t["lignes"]), False),
               font=f_compte, fill=TEXTE, anchor="rt")
        d.text((droite, p(marge + 62)), "liste des attendus inconnue",
               font=f_petit_b, fill=AMBRE, anchor="rt")

    # --- en-tetes de colonnes ----------------------------------------------
    y0 = marge + h_tete
    x_sessions = marge + col_nom
    y_corps = y0 + h_entete
    y_fin_corps = y_corps + corps
    d.rounded_rectangle((p(marge), p(y0), p(largeur - marge), p(y0 + h_entete - 8)),
                        radius=p(12), fill=FOND_ENTETE)
    for i, c in enumerate(t["colonnes"]):
        x = x_sessions + i * col_session
        cx = p(x + col_session / 2)
        # Colonne entiere assombrie : rien n'y est juge. Pas de tuile quand
        # personne n'a ete vu -- elle n'a aucune cellule a couvrir, et la
        # phrase « Personne n'a ete vu... » s'ecrivait par-dessus.
        if c["etat"] != "jugee" and t["lignes"]:
            tuile = Image.new("RGB", (p(col_session - 8), p(corps)), FOND_COLONNE_GRISE)
            if c["etat"] in ("non_suivie", "a_venir"):
                # Hachures dessinees DANS la tuile : tracees sur l'image
                # entiere, elles debordaient sur les colonnes voisines.
                dt_ = ImageDraw.Draw(tuile)
                for k in range(-corps, col_session + 22, 22):
                    dt_.line((p(k), p(corps), p(k + corps), 0), fill=HACHURE, width=p(2))
            img.paste(tuile, (p(x + 4), p(y_corps)))
        couleur_h = TEXTE if c["etat"] == "jugee" or c["etat"] == "en_cours" else TEXTE_3
        d.text((cx, p(y0 + 14)), str(c["heure"]), font=f_heure, fill=couleur_h, anchor="mt")
        if c["mg"]:
            d.text((cx, p(y0 + 52)), "MG %s" % c["mg"], font=f_petit, fill=TEXTE_2, anchor="mt")
        d.text((cx, p(y0 + 80)), ajuster(d, nettoyer(c["nom"], f_petit), f_petit, p(col_session - 8)),
               font=f_petit, fill=TEXTE_3, anchor="mt")
        if c["etat"] != "jugee":
            couleur = (87, 242, 135) if c["etat"] == "en_cours" else AMBRE
            # Ancre sur la ligne de base : « à venir » (accent) et « en cours »
            # s'alignent, ce qu'une ancre « haut » ne garantissait pas.
            for k, morceau in enumerate(etiquettes[c["id"]]):
                d.text((cx, p(y0 + 132 + 28 * k)), morceau, font=f_petit_b,
                       fill=couleur, anchor="ms")
    d.text((p(marge + 20), p(y0 + h_entete / 2 - 4)), "VA", font=f_petit_b,
           fill=TEXTE_2, anchor="lm")
    d.text((p(largeur - marge - col_total / 2), p(y0 + 14)), "Total", font=f_heure,
           fill=TEXTE, anchor="mt")

    # --- une ligne par personne vue -----------------------------------------
    if not t["lignes"]:
        d.text((p(marge + 20), p(y_corps + h_vide / 2)),
               ajuster(d, "Personne n'a été vu aux sessions ce jour-là.", f_nom,
                       p(largeur - 2 * marge - 40)),
               font=f_nom, fill=TEXTE_2, anchor="lm")
    for r, g in enumerate(t["lignes"]):
        y = y_corps + r * h_ligne
        if r % 2 == 0:
            d.rectangle((p(marge), p(y), p(x_sessions), p(y + h_ligne)), fill=FOND_LIGNE)
            d.rectangle((p(largeur - marge - col_total), p(y), p(largeur - marge), p(y + h_ligne)),
                        fill=FOND_LIGNE)
            for i, c in enumerate(t["colonnes"]):
                if c["etat"] == "jugee":
                    x = x_sessions + i * col_session
                    d.rectangle((p(x), p(y), p(x + col_session), p(y + h_ligne)), fill=FOND_LIGNE)
        court, autres = nom_court(g["nom"])
        court = nettoyer(court, f_nom)
        # Les initiales viennent du nom NETTOYE : « Ｘ😀 » donnait un carre vide.
        rond = _rond(photos.get(g["id"]), g["id"], court, p(avatar))
        img.paste(rond, (p(marge + 14), p(y + (h_ligne - avatar) / 2)), rond)
        court = court or "VA …%s" % g["id"][-4:]
        x_nom = marge + 14 + avatar + 16
        l_nom = col_nom - (x_nom - marge) - 12
        notes = []
        # « hors liste » D'ABORD : c'est l'information qui demande une
        # action ; « +3 comptes » n'est qu'une precision.
        if not g["attendu"] and t["liste_connue"]:
            notes.append(("hors liste", AMBRE, f_petit_b))
        if autres:
            notes.append(("+%d compte%s" % (autres, "s" if autres > 1 else ""), TEXTE_3, f_petit))
        if notes:
            d.text((p(x_nom), p(y + 8)), ajuster(d, court, f_nom, p(l_nom)),
                   font=f_nom, fill=TEXTE, anchor="lt")
            xn, x_max = p(x_nom), p(x_nom + l_nom)
            base = p(y + 61)
            for k, (txt, coul, fn) in enumerate(notes):
                if k:
                    txt = "· " + txt
                    xn += _largeur(d, " ", fn)
                txt = ajuster(d, txt, fn, max(0, x_max - xn))
                d.text((xn, base), txt, font=fn, fill=coul, anchor="ls")
                xn += _largeur(d, txt, fn)
        else:
            d.text((p(x_nom), p(y + h_ligne / 2)), ajuster(d, court, f_nom, p(l_nom)),
                   font=f_nom, fill=TEXTE, anchor="lm")
        for i, c in enumerate(t["colonnes"]):
            cx = x_sessions + i * col_session + col_session / 2
            cy = y + h_ligne / 2
            cel = g["cellules"].get(c["id"])
            if cel:
                statut, sec = cel
                fond, encre = (VERT, (255, 255, 255)) if statut == "present" else (ORANGE, ORANGE_TEXTE)
                d.rounded_rectangle((p(cx - 57), p(cy - 23), p(cx + 57), p(cy + 23)),
                                    radius=p(23), fill=fond)
                d.text((p(cx), p(cy)), duree(sec), font=f_pastille, fill=encre, anchor="mm")
            elif c["etat"] == "jugee":
                d.text((p(cx), p(cy)), "—", font=f_pastille, fill=TEXTE_3, anchor="mm")
            elif c["etat"] == "en_cours":
                d.text((p(cx), p(cy)), "·", font=f_pastille, fill=TEXTE_3, anchor="mm")
        d.text((p(largeur - marge - col_total / 2), p(y + h_ligne / 2)), duree(g["total"]),
               font=f_total, fill=TEXTE, anchor="mm")

    # --- en bas : les absents, ou pourquoi on ne peut pas les donner --------
    y = y_fin_corps + 30
    d.line((p(marge), p(y - 15), p(largeur - marge), p(y - 15)), fill=SEPARATEUR, width=p(2))
    if not t["liste_connue"]:
        d.text((p(marge), p(y + 8)),
               "Liste des VA attendus inconnue : les absents ne peuvent pas être établis.",
               font=f_absent, fill=AMBRE, anchor="lt")
    elif not t["absents_etablis"]:
        d.text((p(marge), p(y + 8)),
               "Aucune session terminée et suivie : les absents ne sont pas encore établis.",
               font=f_absent, fill=AMBRE, anchor="lt")
    else:
        libelle = ("Absents toute la journée (%d)" if t["journee_complete"]
                   else "Absents aux sessions terminées (%d)") % len(t["absents"])
        d.text((p(marge), p(y)), libelle, font=f_section, fill=TEXTE, anchor="lt")
        y += 42
        if not t["absents"]:
            d.text((p(marge), p(y + 6)), "Aucun : tous les VA attendus sont passés.",
                   font=f_absent, fill=TEXTE_2, anchor="lt")
        l_case = (largeur - 2 * marge) / nb_col_abs
        for k, a in enumerate(t["absents"]):
            ligne_a, col_a = divmod(k, nb_col_abs)
            x = marge + col_a * l_case
            ya = y + ligne_a * h_abs
            court_net, nom, suf = libelles_abs[k]
            rond = _rond(photos.get(a["id"]), a["id"], court_net, p(petit), attenue=True)
            img.paste(rond, (p(x), p(ya + (h_abs - petit) / 2)), rond)
            d.text((p(x + petit + 12), p(ya + h_abs / 2)),
                   libelle_absent(d, nom, suf, f_absent, place_abs(nb_col_abs)),
                   font=f_absent, fill=TEXTE_2, anchor="lm")

    final = img.resize((largeur, hauteur), Image.LANCZOS)
    out = io.BytesIO()
    final.save(out, "PNG", optimize=False, compress_level=6)
    octets = out.getvalue()
    if len(octets) > POIDS_MAX:
        raise ValueError("image du bilan trop lourde (%d octets)" % len(octets))
    return octets
