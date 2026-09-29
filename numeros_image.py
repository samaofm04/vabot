# -*- coding: utf-8 -*-
"""Le récap numéros SMS (« debrief-day ») en IMAGE, avec les photos des VA.

Demande du proprietaire du 29/09/2026 : « tu vois ce qu'on a fait pour les
sessions, fais un truc style pour les debrief-day, avec PP et tout ». Meme
carte sombre, memes polices, meme largeur que le bilan des sessions
(sessions_image) : les deux images se lisent de la meme facon. Les briques
(polices, palette, ronds, `ajuster`, `nettoyer`, initiales) viennent de
sessions_image, importe SEULEMENT au moment du dessin : cogs/numeros importe
ce module a son chargement (ordre des VA, pourcentage), et un Pillow absent
ou casse ne doit jamais empecher le cog des numeros de se charger -- le recap
retombe alors sur le texte.

Ce module ne fait QUE le dessin : ni Discord, ni reseau, ni fichier ecrit.

CE QUI N'EST JAMAIS CACHE
-------------------------
- quarante VA : l'image grandit en hauteur, aucune ligne n'est coupee ;
- une photo absente ou illisible : un rond aux initiales ;
- un nom Discord a emoji : l'emoji est retire (un carre vide sinon) ; un nom
  fait QUE d'emojis, ou un VA sans nom : son identifiant, comme le texte ;
- les mails et les numeros rendus par le bot : sous le total, comme le texte.
"""
import datetime as _dt
import io
import unicodedata

#: L'heure du Benin (UTC+1 toute l'annee). Le cog passe la sienne
#: (numeros.BENIN) : ceci n'est que la valeur par defaut.
BENIN = _dt.timezone(_dt.timedelta(hours=1), "Bénin")

#: Seuils de la barre de reussite (demande du 29/09) : vert a partir de 75 %,
#: orange de 40 a 74 %, rouge en dessous de 40 %.
SEUIL_VERT = 75
SEUIL_ORANGE = 40

_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def pourcent(codes, numeros) -> int:
    """Le pourcentage de reussite ARRONDI comme le texte du recap (4/9 -> 44)."""
    return int(codes * 100 / numeros + 0.5) if numeros else 0


def ordre_vas(vas: dict, cle_nom) -> list:
    """[(uid, v)] dans l'ordre du recap : numeros decroissants, puis codes
    decroissants, puis le nom (`cle_nom(uid)`). UNE definition, pour le texte
    et pour l'image : deux tris, c'etait deux ordres le jour ou l'un change."""
    return sorted(vas.items(), key=lambda kv: (-kv[1]["n"], -kv[1]["c"], cle_nom(kv[0])))


def niveau_reussite(pct) -> str:
    """« vert » (>= 75 %), « orange » (40-74 %) ou « rouge » (< 40 %)."""
    if pct >= SEUIL_VERT:
        return "vert"
    if pct >= SEUIL_ORANGE:
        return "orange"
    return "rouge"


def date_courte(jour) -> str:
    """« mardi 29/09 »."""
    return "%s %02d/%02d" % (_JOURS[jour.weekday()], jour.day, jour.month)


def _pl(n, singulier, pluriel=None) -> str:
    return "%d %s" % (n, singulier if n <= 1 else (pluriel or singulier + "s"))


def _hhmm(ts, tz) -> str:
    return _dt.datetime.fromtimestamp(float(ts), tz).strftime("%Hh%M")


def recap(jour, agg: dict, noms: dict, en_direct: bool, depuis_ts=None, maintenant=None,
          seuil_loupe: int = 4, tz=BENIN, cle_nom=None) -> dict:
    """Ce que l'image montre, calcule sans rien dessiner (testable seul).

    `agg` : le bilan d'UN serveur (numeros.agreger()[serveur]) ; `noms` :
    {uid: nom affiche}. `en_direct` : journee en cours (pastille verte, heure
    de mise a jour) ; sinon journee figee, « complète » ou « partielle »
    (`depuis_ts` : la journee de la mise en route n'est suivie que depuis
    cette heure-la)."""
    debut = _hhmm(depuis_ts, tz) if depuis_ts else "00h00"
    vide = not (agg.get("numeros") or agg.get("mails") or agg.get("rendus"))
    if en_direct:
        etat = "En direct"
        sous = ["depuis %s" % debut, "heure du Bénin"]
        # A 0, pas d'heure de mise a jour (regle du texte, 27/09/2026) :
        # « mis à jour à 09h05 » lu a 23h faisait croire que le recap
        # s'etait arrete a 09h05.
        maj = "" if vide or maintenant is None else "mis à jour à %s" % _hhmm(maintenant, tz)
    else:
        etat = "Journée partielle" if depuis_ts else "Journée complète"
        sous = ["de %s à 23h59" % debut, "heure du Bénin"]
        maj = ""
    if cle_nom is None:
        def cle_nom(uid):
            return str(noms.get(uid) or uid).lower()
    lignes = []
    codes = 0
    for uid, v in ordre_vas(agg.get("vas") or {}, cle_nom):
        pct = pourcent(v["c"], v["n"])
        codes += v["c"]
        lignes.append({
            "id": str(uid),
            # Le nom Discord affiche aujourd'hui dans le texte ; un VA sans
            # nom connu : son identifiant, comme le texte.
            "nom": str(noms.get(uid) or uid),
            "n": v["n"], "c": v["c"], "pct": pct, "niveau": niveau_reussite(pct),
            # Meme seuil que la loupe du texte (RECAP_SEUIL_LOUPE).
            "sans": v["sans"] if v["sans"] >= seuil_loupe else 0,
            "attente": int(v.get("attente") or 0),
        })
    n = int(agg.get("numeros") or 0)
    return {
        "date": date_courte(jour), "etat": etat, "en_direct": bool(en_direct),
        "sous": sous, "maj": maj, "lignes": lignes, "numeros": n, "codes": codes,
        "pct": pourcent(codes, n), "mails": int(agg.get("mails") or 0),
        "mails_codes": int(agg.get("mails_codes") or 0),
        "rendus": int(agg.get("rendus") or 0), "vide": vide,
    }


def choisir_pastilles(g: dict, place: float, largeur) -> list:
    """Les pastilles d'une ligne [(texte, genre)] -- genre « sans » (loupe)
    ou « attente » --, dans `place` (px). Longues si elles tiennent, puis
    « N att. », puis « N sans » : la pastille raccourcit, elle ne disparait
    pas et ne mord pas le chiffre. `largeur(texte, loupe)` mesure une
    pastille."""
    sans = [("%d sans code" % g["sans"], "%d sans" % g["sans"])] if g["sans"] else []
    att = [("%d en attente" % g["attente"], "%d att." % g["attente"])] if g["attente"] else []
    essais = [(0, 0), (0, 1), (1, 1)]
    for i_s, i_a in essais:
        choix = ([(sans[0][i_s], "sans")] if sans else []) \
            + ([(att[0][i_a], "attente")] if att else [])
        total = sum(largeur(tx, genre == "sans") for tx, genre in choix) + 8 * max(0, len(choix) - 1)
        if total <= place:
            return choix
    # Rien ne tient (impossible sous 10 000 numeros) : les plus courtes
    # quand meme -- une pastille n'est jamais cachee.
    return choix


def ids_photos(agg: dict) -> list:
    """Les identifiants dont l'image montre la photo (une par ligne de VA)."""
    return [str(u) for u in (agg.get("vas") or {})]


def texte_total(t: dict) -> str:
    """« Total : 20 numéros · 15 codes (75 %) »."""
    return "Total : %s · %s (%d %%)" % (_pl(t["numeros"], "numéro"), _pl(t["codes"], "code"),
                                         t["pct"])


def texte_rendus(n) -> str:
    """La ligne des numeros rendus, comme le texte, sans emoji."""
    if n <= 1:
        return "%d numéro rendu par le bot : impossible à afficher, remboursé" % n
    return "%d numéros rendus par le bot : impossibles à afficher, remboursés" % n


def nom_dessinable(si, nom: str, f) -> str:
    """Le nom tel que la police sait le dessiner. Les pseudos en lettres
    stylisees (𝓑𝓮𝓵𝓵𝓪, ＷＩＤＥ : alphanumeriques mathematiques, pleine
    chasse) n'ont pas de glyphe : nettoyer les retirait TOUS, et l'image
    montrait l'identifiant a 19 chiffres la ou le texte montrait le nom.
    NFKC les ramene a des lettres ordinaires -- retenu seulement s'il sauve
    plus de caractères (« Léa² » reste « Léa² »)."""
    brut = si.nettoyer(nom, f)
    k = unicodedata.normalize("NFKC", str(nom or ""))
    if k != unicodedata.normalize("NFC", str(nom or "")):
        alt = si.nettoyer(k, f)
        if len(alt) > len(brut):
            return k
    return nom


def dessiner_recap(jour, agg: dict, noms: dict, photos: dict, en_direct: bool,
                   depuis_ts=None, maintenant=None, *, seuil_loupe: int, zero_direct: str,
                   zero_final: str, tz=BENIN, cle_nom=None, mesures=None) -> bytes:
    """Le PNG du recap d'un serveur. Leve si l'image est impossible (le cog
    retombe alors sur le texte, en le journalisant).

    `mesures` (tests) : une liste qui recoit ce qui a ete pose, en px de
    l'image finale -- {"titre": ..., "compteur": ...} puis, par ligne,
    {"nom": ..., "nom_fin": x, "pastilles": [...], "pastilles_fin": x,
    "chiffre_debut": x}. Les chevauchements se verifient sans lire l'image."""
    import sessions_image as si
    from PIL import Image, ImageDraw

    t = recap(jour, agg, noms, en_direct, depuis_ts, maintenant, seuil_loupe, tz, cle_nom)
    photos = photos or {}
    K = si._K
    largeur = si.LARGEUR

    def p(v):
        return int(round(v * K))

    f_titre = si.police("bold", p(46))
    f_sous = si.police("regular", p(24))
    f_sous_b = si.police("bold", p(24))
    f_compte = si.police("bold", p(34))
    f_compte2 = si.police("regular", p(25))
    f_nom = si.police("medium", p(27))
    f_chiffre = si.police("bold", p(28))
    f_unite = si.police("regular", p(24))
    f_pct = si.police("bold", p(26))
    f_pastille = si.police("bold", p(23))
    f_etat = si.police("bold", p(24))
    f_total = si.police("bold", p(28))
    f_bas = si.police("regular", p(25))
    f_vide = si.police("medium", p(27))

    VERT_BARRE = (59, 165, 93)
    ROUGE = (237, 66, 69)
    PISTE = (64, 66, 72)
    ATTENTE = (88, 101, 242)
    couleurs = {"vert": VERT_BARRE, "orange": si.ORANGE, "rouge": ROUGE}

    marge = 40
    h_tete = 128
    h_ligne = 82
    h_vide = 80
    avatar = 56
    # Colonnes, de droite a gauche : le pourcentage, la barre, les codes, les
    # numeros ; le nom (et ses pastilles, en dessous) prend le reste.
    x_fin = largeur - marge - 14
    l_pct = 78
    x_barre_fin = x_fin - l_pct - 10
    l_barre = 150
    x_barre = x_barre_fin - l_barre
    x_codes_fin = x_barre - 26
    x_num_fin = x_codes_fin - 136
    x_nom = marge + 14 + avatar + 16
    l_nom = x_num_fin - 150 - x_nom

    hauteur = marge + h_tete
    hauteur += h_ligne * len(t["lignes"]) if t["lignes"] else h_vide
    bas = []
    if t["numeros"]:
        bas.append(("total", texte_total(t)))
    if t["mails"]:
        bas.append(("ligne", "%s · %s" % (_pl(t["mails"], "mail"), _pl(t["mails_codes"], "code"))))
    if t["rendus"]:
        bas.append(("ligne", texte_rendus(t["rendus"])))
    if bas:
        hauteur += 22 + sum(46 if k == "total" else 38 for k, _ in bas)
    hauteur += 26

    img = Image.new("RGB", (p(largeur), p(hauteur)), si.FOND)
    d = ImageDraw.Draw(img)

    # --- en-tete -------------------------------------------------------------
    droite = p(largeur - marge)
    compteur = _pl(t["numeros"], "numéro")
    titre = "Récap numéros SMS"
    l_pastille = si._largeur(d, t["etat"], f_etat) + p(36)
    # Le titre n'est JAMAIS coupe : « Journée partielle » et 377 numéros
    # donnaient « Récap numéros S… ». C'est le compteur qui retrecit (34 ->
    # 24 px), le titre et la pastille d'etat gardent leur taille.
    besoin = p(marge) + si._largeur(d, titre, f_titre) + p(18) + l_pastille + p(30)
    taille = 34
    while taille > 24 and besoin + si._largeur(d, compteur, f_compte) > droite:
        taille -= 1
        f_compte = si.police("bold", p(taille))
    d.text((droite, p(marge)), compteur, font=f_compte, fill=si.TEXTE, anchor="rt")
    x_compteur = droite - si._largeur(d, compteur, f_compte)
    if t["lignes"]:
        d.text((droite, p(marge + 62)), "%d VA" % len(t["lignes"]), font=f_compte2,
               fill=si.TEXTE_2, anchor="rt")
    place_titre = x_compteur - p(marge) - l_pastille - p(18 + 30)
    titre = si.ajuster(d, titre, f_titre, max(p(120), place_titre))
    d.text((p(marge), p(marge)), titre, font=f_titre, fill=si.TEXTE, anchor="lt")
    if mesures is not None:
        mesures.append({"titre": titre, "compteur": compteur, "taille_compteur": taille,
                        "titre_fin": (p(marge) + si._largeur(d, titre, f_titre)) / K,
                        "pastille_fin": (p(marge) + si._largeur(d, titre, f_titre) + p(18)
                                         + l_pastille) / K,
                        "compteur_debut": x_compteur / K})
    xp = p(marge) + si._largeur(d, titre, f_titre) + p(18)
    fond_p, encre_p = ((si.VERT, (255, 255, 255)) if t["en_direct"] else (si.GRIS_PASTILLE, si.TEXTE))
    d.rounded_rectangle((xp, p(marge + 5), xp + l_pastille, p(marge + 45)), radius=p(20), fill=fond_p)
    d.text((xp + l_pastille / 2, p(marge + 25)), t["etat"], font=f_etat, fill=encre_p, anchor="mm")
    sous = " · ".join([t["date"]] + t["sous"])
    d.text((p(marge), p(marge + 66)), sous, font=f_sous, fill=si.TEXTE_2, anchor="lt")
    if t["maj"]:
        x_maj = p(marge) + si._largeur(d, sous, f_sous)
        d.text((x_maj, p(marge + 66)), " · " + t["maj"], font=f_sous_b, fill=si.VERT_CLAIR,
               anchor="lt")

    y = marge + h_tete
    d.line((p(marge), p(y - 10), p(largeur - marge), p(y - 10)), fill=si.SEPARATEUR, width=p(2))

    def chiffre(x_droite, cy, n, unite):
        """« 9 numéros » cale a droite : le chiffre en gras, l'unite en gris."""
        u = " " + unite
        d.text((p(x_droite), p(cy)), u, font=f_unite, fill=si.TEXTE_2, anchor="rm")
        xu = p(x_droite) - si._largeur(d, u, f_unite)
        d.text((xu, p(cy)), str(n), font=f_chiffre, fill=si.TEXTE, anchor="rm")

    def loupe(x, cy, encre):
        """Une loupe dessinee (pas d'emoji dans l'image : la police n'en a pas)."""
        r = 7
        cx, cyy = x + r + 1, cy - 2
        d.ellipse((p(cx - r), p(cyy - r), p(cx + r), p(cyy + r)), outline=encre, width=p(2.4))
        d.line((p(cx + r * 0.7), p(cyy + r * 0.7), p(cx + r * 0.7 + 6), p(cyy + r * 0.7 + 6)),
               fill=encre, width=p(3))
        return 2 * r + 14

    def l_pastille_ligne(texte, icone=False):
        return si._largeur(d, texte, f_pastille) / K + (28 if icone else 0) + 26

    def debut_chiffre(x_droite, n, unite):
        """Ou commence REELLEMENT « 128 numéros » cale a droite sur x_droite."""
        return x_droite - (si._largeur(d, " " + unite, f_unite)
                           + si._largeur(d, str(n), f_chiffre)) / K

    def pastille(x, cy, texte, fond, encre, icone=False):
        """Une pastille arrondie ; rend sa largeur."""
        l = l_pastille_ligne(texte, icone)
        d.rounded_rectangle((p(x), p(cy - 16), p(x + l), p(cy + 16)), radius=p(16), fill=fond)
        xt = x + 13
        if icone:
            xt += loupe(xt, cy + 1, encre)
        d.text((p(xt), p(cy)), texte, font=f_pastille, fill=encre, anchor="lm")
        return l

    styles_pastille = {"sans": ((74, 56, 22), si.AMBRE),
                       "attente": ((44, 50, 92), (201, 205, 251))}

    for r, g in enumerate(t["lignes"]):
        if r % 2 == 0:
            d.rectangle((p(marge), p(y), p(largeur - marge), p(y + h_ligne)), fill=si.FOND_LIGNE)
        cy = y + h_ligne / 2
        # « VA NOUM 1X1 / VA NOUM 2X1 » : une personne, plusieurs fiches --
        # le premier nom et « +1 », comme le bilan des sessions. Seul « / »
        # ENTRE ESPACES separe des fiches : ici ce sont des pseudos Discord, et
        # « ROUCHAM 1 IPHONE X FIXE/SPAM » (vrai recap du 29/09) devenait
        # « ROUCHAM 1 IPHONE X FIXE +1 », un second compte qui n'existe pas.
        _nd = nom_dessinable(si, g["nom"], f_nom)
        _segs = [s.strip() for s in str(_nd or "").split(" / ") if s.strip()]
        court, autres = (_segs[0], len(_segs) - 1) if _segs else ("", 0)
        court = si.nettoyer(court, f_nom)
        rond = si._rond(photos.get(g["id"]), g["id"], court or g["id"], p(avatar))
        img.paste(rond, (p(marge + 14), p(y + (h_ligne - avatar) / 2)), rond)
        # Un nom fait QUE d'emojis : l'identifiant, comme le texte pour un VA
        # sans nom -- jamais une ligne sans nom.
        suffixe = " +%d" % autres if autres else ""
        unite_n = "numéro" if g["n"] <= 1 else "numéros"
        # Le nom et ses pastilles s'arretent au debut REEL du chiffre de la
        # ligne, mesure : une borne fixe laissait « 1 en attente » passer
        # sur le « 20 » de « 20 numéros », et un nom tronque toucher « 100 ».
        x_lim = debut_chiffre(x_num_fin, g["n"], unite_n)
        l_nom_l = min(l_nom, x_lim - 16 - x_nom)
        affiche = si.libelle_absent(d, court or g["id"], suffixe, f_nom, p(l_nom_l))
        pastilles = choisir_pastilles(g, x_lim - 12 - x_nom, l_pastille_ligne)
        if pastilles:
            d.text((p(x_nom), p(y + 23)), affiche, font=f_nom, fill=si.TEXTE, anchor="lm")
            xq = x_nom
            for texte, genre in pastilles:
                fond, encre = styles_pastille[genre]
                xq += pastille(xq, y + 58, texte, fond, encre, genre == "sans") + 8
        else:
            d.text((p(x_nom), p(cy)), affiche, font=f_nom, fill=si.TEXTE, anchor="lm")
        chiffre(x_num_fin, cy, g["n"], unite_n)
        if mesures is not None:
            mesures.append({"nom": affiche, "nom_fin": x_nom + si._largeur(d, affiche, f_nom) / K,
                            "pastilles": [tx for tx, _g in pastilles],
                            "pastilles_fin": (xq - 8) if pastilles else x_nom,
                            "chiffre_debut": x_lim})
        chiffre(x_codes_fin, cy, g["c"], "code" if g["c"] <= 1 else "codes")
        coul = couleurs[g["niveau"]]
        d.rounded_rectangle((p(x_barre), p(cy - 7), p(x_barre_fin), p(cy + 7)), radius=p(7), fill=PISTE)
        plein = l_barre * max(0, min(100, g["pct"])) / 100.0
        if plein >= 14:
            d.rounded_rectangle((p(x_barre), p(cy - 7), p(x_barre + plein), p(cy + 7)),
                                radius=p(7), fill=coul)
        elif plein > 0:
            d.ellipse((p(x_barre), p(cy - 7), p(x_barre + 14), p(cy + 7)), fill=coul)
        d.text((p(x_fin), p(cy)), "%d %%" % g["pct"], font=f_pct, fill=coul, anchor="rm")
        y += h_ligne

    if not t["lignes"]:
        d.rounded_rectangle((p(marge), p(y), p(largeur - marge), p(y + h_vide - 12)),
                            radius=p(12), fill=si.FOND_LIGNE)
        d.text((p(marge + 20), p(y + (h_vide - 12) / 2)),
               zero_direct if t["en_direct"] else zero_final,
               font=f_vide, fill=si.TEXTE_2, anchor="lm")
        y += h_vide

    if bas:
        y += 10
        d.line((p(marge), p(y), p(largeur - marge), p(y)), fill=si.SEPARATEUR, width=p(2))
        y += 12
        for k, texte in bas:
            if k == "total":
                d.text((p(marge), p(y + 23)), si.ajuster(d, texte, f_total, p(largeur - 2 * marge)),
                       font=f_total, fill=si.TEXTE, anchor="lm")
                y += 46
            else:
                d.text((p(marge), p(y + 19)), si.ajuster(d, texte, f_bas, p(largeur - 2 * marge)),
                       font=f_bas, fill=si.TEXTE_2, anchor="lm")
                y += 38

    final = img.resize((largeur, hauteur), Image.LANCZOS)
    out = io.BytesIO()
    final.save(out, "PNG", optimize=False, compress_level=6)
    octets = out.getvalue()
    if len(octets) > si.POIDS_MAX:
        raise ValueError("image du recap trop lourde (%d octets)" % len(octets))
    return octets
