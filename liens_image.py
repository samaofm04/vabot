# -*- coding: utf-8 -*-
"""L'image de la quinzaine d'une page des liens de suivi (page Lia, YouCham).

POURQUOI
    Proprietaire, 31/10/2026, sur le salon 📊・click-et-sub de YouCham : « tu
    peux mettre une image de la quinzaine toujours stp dans le truc », puis
    « avec le lien colle ? ». Le message du salon porte donc l'image de la
    quinzaine EN COURS et, dessous, le bouton « 📊 Statistiques » vers la page
    (outils_communs). Memes colonnes, memes chiffres et memes couleurs que la
    page (infloww_liens, profil « lia ») : Clics US, Clics globaux (tous pays,
    proprietaire le 31/10 : « entre subs et clics US »), Subs, CVR, $ / sub. Les
    chiffres sont ceux de la page sur la meme periode, pas recalcules ici.

JAMAIS LE NET NI LA PAIE
    Le salon est lu par les VA : le $ / sub (LTV) seul, comme la page des VA.

Ce module ne fait QUE le dessin : ni Discord, ni reseau, ni fichier ecrit.
Polices, rond aux initiales, palette et pastilles du podium sont ceux des
images de clics (sessions_image, clics_image) : importes, pas recopies.
"""
import datetime

from PIL import Image, ImageDraw

import clics_image as _ci
import sessions_image as _si
from sessions_image import (FOND, FOND_ENTETE, FOND_LIGNE, SEPARATEUR, TEXTE,
                            TEXTE_2, TEXTE_3, VERT_CLAIR, ajuster, nettoyer,
                            police)

#: Le nom de la piece jointe : [a-zA-Z0-9_.-] seulement, sinon Discord le
#: reecrit et « attachment://... » pointe dans le vide.
NOM = "quinzaine_lia.png"
#: Plus large que les images de clics (1100) : cinq colonnes de chiffres
#: (Clics US, Clics globaux, Subs, CVR, $ / sub) s'y chevauchaient.
LARGEUR = 1240
_p = _ci._p

#: Les couleurs des pastilles de la page (infloww_liens, classes .nv) : fond,
#: encre. Une valeur absente (« — ») n'a pas de pastille.
PASTILLES = {"v3": ((22, 101, 52), (255, 255, 255)), "v2": ((22, 163, 74), (255, 255, 255)),
             "v1": ((74, 222, 128), (5, 46, 22)), "o1": ((251, 191, 36), (28, 18, 3)),
             "o2": ((249, 115, 22), (28, 10, 2)), "r": ((220, 38, 38), (255, 255, 255))}


def _jour(iso: str) -> str:
    try:
        return datetime.date.fromisoformat(str(iso)[:10]).strftime("%d/%m")
    except ValueError:
        return "?"


def tableau(t: dict, du: str, au: str, maj: str = "", nom: str = "") -> dict:
    """Ce que l'image montre, tire du tableau de la page (infloww_liens
    tableau_periode) : une ligne par personne, triee par subs puis clics US
    (une valeur inconnue en bas), le total, la periode. Rien n'est recalcule :
    CVR, $ / sub et couleurs sont ceux de la page."""
    import infloww_liens as _il
    lignes = []
    for x in t.get("lignes") or []:
        codes = [str(r.get("code")) for r in x.get("infloww") or [] if r.get("code")]
        lignes.append({
            "cle": str(x.get("cle") or ""), "nom": str(x.get("nom") or x.get("cle") or "?"),
            "sous": (" · ".join([str(x.get("nom_gms") or "")] + ["c" + c for c in codes]).strip(" ·")
                     # la page dit « lien MyPuls introuvable » : l'image aussi, pas un blanc
                     or ("lien de suivi introuvable" if x.get("introuvables") else "")),
            "us": x.get("us"), "glob": x.get("glob"), "subs": x.get("subs"), "cvr": x.get("cvr"),
            "par_sub": x.get("par_sub"),
            "niv_cvr": _il.niveau(x.get("cvr"), _il.SEUIL_CVR),
            "niv_sub": _il.niveau(x.get("par_sub"), _il.SEUIL_PAR_SUB)})

    def ordre(x):
        return (x["subs"] is None, -(x["subs"] or 0), x["us"] is None, -(x["us"] or 0), x["nom"].lower())
    lignes.sort(key=ordre)
    rang = 0
    for x in lignes:
        # classes : subs connus, et au moins un sub ou un clic. Sans ca, ni
        # « 1er » a zero, ni rang pour des subs qu'on n'a pas su lire.
        if x["subs"] is not None and (x["subs"] or x["us"]):
            rang += 1
            x["rang"] = rang
        else:
            x["rang"] = 0
    T = t.get("totaux") or {}
    return {"lignes": lignes, "du": du, "au": au, "maj": maj, "erreur": str(t.get("erreur") or ""),
            "nom": str(nom or ""),
            "total": {"us": T.get("us"), "glob": T.get("glob"), "subs": T.get("subs"), "cvr": T.get("cvr"),
                      "par_sub": T.get("par_sub"),
                      "niv_cvr": _il.niveau(T.get("cvr"), _il.SEUIL_CVR),
                      "niv_sub": _il.niveau(T.get("par_sub"), _il.SEUIL_PAR_SUB)}}


def _textes(x: dict) -> tuple:
    import infloww_liens as _il
    return (_il._nb(x.get("us"), " "), _il._nb(x.get("glob"), " "), _il._nb(x.get("subs"), " "),
            _il._pct(x.get("cvr"), " "), _il._dollars(x.get("par_sub"), " "))


def _pastille(d, cx, cy, texte, niv, f):
    texte = nettoyer(texte, f)
    if not niv or texte == "—":
        d.text((_p(cx), _p(cy)), texte, font=f, fill=TEXTE_3 if texte == "—" else TEXTE, anchor="mm")
        return
    fond, encre = PASTILLES[niv]
    lp = max(_ci._l(d, texte, f) + 24, 92) / 2
    d.rounded_rectangle((_p(cx - lp), _p(cy - 18), _p(cx + lp), _p(cy + 18)), radius=_p(9), fill=fond)
    d.text((_p(cx), _p(cy)), texte, font=f, fill=encre, anchor="mm")


def dessiner(v: dict, photos: dict = None) -> bytes:
    """Le PNG de la quinzaine. `photos` : {cle de personne: octets de sa
    photo Discord} ; sans photo, les initiales. Leve si l'image est
    impossible (le panneau garde alors son seul bouton)."""
    photos = photos or {}
    largeur, marge = LARGEUR, 40
    h_tete, h_entete, h_ligne, avatar = 118, 56, 66, 46
    x_rang, x_photo, x_nom = marge + 32, marge + 62, _ci.X_NOM
    # bords droits des nombres, centres des pastilles (px finaux)
    x_us, x_glob, x_subs, x_cvr, x_sub = 600, 780, 900, 1005, 1140
    lignes = v.get("lignes") or []
    corps = h_ligne * len(lignes) if lignes else 90
    h_total = h_ligne
    hauteur = marge + h_tete + 10 + h_entete + corps + h_total + 30

    img = Image.new("RGB", (_p(largeur), _p(hauteur)), FOND)
    d = ImageDraw.Draw(img)
    f_titre, f_sous, f_maj = police("bold", _p(44)), police("regular", _p(24)), police("bold", _p(24))
    f_col, f_rang = police("bold", _p(22)), police("bold", _p(24))
    f_nom, f_det = police("medium", _p(27)), police("regular", _p(20))
    f_ch, f_ch_b, f_pas = police("regular", _p(27)), police("bold", _p(27)), police("bold", _p(23))

    # en-tete : « Lia · clics & subs », « 16/10 → 31/10 · quinzaine en cours · mis a jour 19h00 »
    titre = nettoyer("%s · clics & subs" % (v.get("nom") or "Lia"), f_titre)
    d.text((_p(marge), _p(marge)), titre, font=f_titre, fill=TEXTE, anchor="lt")
    n = len(lignes)
    d.text((_p(largeur - marge), _p(marge + 12)), "%d VA" % n, font=f_sous, fill=TEXTE_2, anchor="rt")
    y = _p(marge + 86)
    sous = "%s → %s · quinzaine en cours" % (_jour(v.get("du")), _jour(v.get("au")))
    sous = nettoyer(sous, f_sous)
    d.text((_p(marge), y), sous, font=f_sous, fill=TEXTE_2, anchor="ls")
    if v.get("maj"):
        x = _p(marge) + _si._largeur(d, sous, f_sous)
        d.text((x, y), " · ", font=f_sous, fill=TEXTE_3, anchor="ls")
        x += _si._largeur(d, " · ", f_sous)
        d.text((x, y), nettoyer("mis à jour %s" % v["maj"], f_maj), font=f_maj, fill=VERT_CLAIR, anchor="ls")

    y0 = marge + h_tete + 10
    d.rounded_rectangle((_p(marge), _p(y0), _p(largeur - marge), _p(y0 + h_entete - 6)),
                        radius=_p(12), fill=FOND_ENTETE)
    cy = y0 + (h_entete - 6) / 2
    d.text((_p(x_rang), _p(cy)), "#", font=f_col, fill=TEXTE_2, anchor="mm")
    d.text((_p(x_nom), _p(cy)), "VA", font=f_col, fill=TEXTE_2, anchor="lm")
    d.text((_p(x_us), _p(cy)), "Clics US", font=f_col, fill=TEXTE_2, anchor="rm")
    d.text((_p(x_glob), _p(cy)), "Clics globaux", font=f_col, fill=TEXTE_2, anchor="rm")
    d.text((_p(x_subs), _p(cy)), "Subs", font=f_col, fill=TEXTE, anchor="rm")
    d.text((_p(x_cvr), _p(cy)), "CVR", font=f_col, fill=TEXTE_2, anchor="mm")
    d.text((_p(x_sub), _p(cy)), "$ / sub", font=f_col, fill=TEXTE_2, anchor="mm")

    y_corps = y0 + h_entete
    fin_nom = _p(x_us - 112)
    if not lignes:
        d.text((_p(marge + 20), _p(y_corps + 45)),
               nettoyer(v.get("erreur") or "Aucun lien sur cette quinzaine.", f_nom)[:120],
               font=f_nom, fill=TEXTE_2, anchor="lm")
    for r, x in enumerate(lignes):
        yl = y_corps + r * h_ligne
        cy = yl + h_ligne / 2
        if r % 2 == 0:
            d.rectangle((_p(marge), _p(yl), _p(largeur - marge), _p(yl + h_ligne)), fill=FOND_LIGNE)
        _ci._pastille_rang(d, x_rang, cy, x.get("rang"), f_rang)
        nom = nettoyer(x["nom"], f_nom) or "?"
        rond = _si._rond(photos.get(x["cle"]), x["cle"], nom.lstrip("@"), _p(avatar))
        img.paste(rond, (_p(x_photo), _p(yl + (h_ligne - avatar) / 2)), rond)
        d.text((_p(x_nom), _p(cy - 10 if x.get("sous") else cy)), ajuster(d, nom, f_nom, fin_nom - _p(x_nom)),
               font=f_nom, fill=TEXTE, anchor="lm")
        if x.get("sous"):
            d.text((_p(x_nom), _p(cy + 17)), ajuster(d, nettoyer(x["sous"], f_det), f_det, fin_nom - _p(x_nom)),
                   font=f_det, fill=TEXTE_3, anchor="lm")
        us, glob, subs, cvr, par_sub = _textes(x)
        d.text((_p(x_us), _p(cy)), us, font=f_ch, fill=TEXTE_3 if us == "—" else TEXTE_2, anchor="rm")
        d.text((_p(x_glob), _p(cy)), glob, font=f_ch, fill=TEXTE_3 if glob == "—" else TEXTE_2, anchor="rm")
        d.text((_p(x_subs), _p(cy)), subs, font=f_ch_b, fill=TEXTE_3 if subs == "—" else TEXTE, anchor="rm")
        _pastille(d, x_cvr, cy, cvr, x.get("niv_cvr"), f_pas)
        _pastille(d, x_sub, cy, par_sub, x.get("niv_sub"), f_pas)

    # le total, sous un trait
    yt = y_corps + corps
    d.line((_p(marge), _p(yt), _p(largeur - marge), _p(yt)), fill=SEPARATEUR, width=_p(2))
    cy = yt + h_total / 2
    T = v.get("total") or {}
    d.text((_p(x_nom), _p(cy)), "Total · %d VA" % n, font=f_ch_b, fill=TEXTE, anchor="lm")
    us, glob, subs, cvr, par_sub = _textes(T)
    d.text((_p(x_us), _p(cy)), us, font=f_ch_b, fill=TEXTE, anchor="rm")
    d.text((_p(x_glob), _p(cy)), glob, font=f_ch_b, fill=TEXTE if glob != "—" else TEXTE_3, anchor="rm")
    d.text((_p(x_subs), _p(cy)), subs, font=f_ch_b, fill=TEXTE, anchor="rm")
    _pastille(d, x_cvr, cy, cvr, T.get("niv_cvr"), f_pas)
    _pastille(d, x_sub, cy, par_sub, T.get("niv_sub"), f_pas)
    return _ci._finir(img, largeur, hauteur, "de la quinzaine")


def texte_alt(v: dict) -> str:
    """La description de l'image (lecteurs d'ecran, aperçu) : la quinzaine et
    le total, sans montant."""
    T = v.get("total") or {}
    return ("%s · quinzaine du %s au %s : %s clics US, %s clics globaux, %s subs"
            % (v.get("nom") or "Lia", _jour(v.get("du")), _jour(v.get("au")),
               T.get("us") if T.get("us") is not None else "—",
               T.get("glob") if T.get("glob") is not None else "—",
               T.get("subs") if T.get("subs") is not None else "—"))[:1000]
