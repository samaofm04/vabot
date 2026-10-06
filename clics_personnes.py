# -*- coding: utf-8 -*-
"""Les liens de suivi, regroupes par PERSONNE.

TROIS ECRANS, UNE SEULE REGLE. Le report epingle de Discord, sa page web
(/clics) et la carte du tableau de bord montrent le meme classement. Tant que
la regle vivait dans web_upload.py, les deux autres n'avaient d'autre choix
que de la recopier -- et deux copies d'une regle finissent toujours par
diverger d'un caractere, sauf que celle-ci decide de ce qu'on paie.

Ce module ne connait ni Flask, ni Discord, ni GetMySocial, ni le disque : il
prend des listes de dictionnaires et rend des listes de dictionnaires. C'est
ce qui le rend testable, et importable par les trois sans le moindre cycle.
UNE exception, rattachements_identite() : le registre des liens d'identite
US (liens_identite_us), lu par import paresseux, parce que la question
« a qui est ce lien » doit avoir sa reponse ICI, pour le podium, la page
Infloww et la paie comme pour les clics.

TROIS VALEURS, TROIS SENS -- et c'est tout l'enjeu du fichier :

    un entier   ce qui a ete lu
    None        on n'a PAS su lire ; surtout pas un zero
    "NA"        la periode precede l'arrivee de la personne sur ce lien ;
                ce n'est ni un zero (elle n'a pas rien fait) ni un tiret
                (la donnee a bien ete lue), c'est le travail de quelqu'un
                d'autre

Sur un tableau, confondre les trois se voit a peine. Sur un CLASSEMENT, le
non-lu aplati a zero tombe en derniere place, et on lit « ce VA n'a rien
rapporte » la ou il faut lire « on ne sait pas ».
"""

from __future__ import annotations

import re
import unicodedata
import zlib

# --- L'espace GetMySocial du classement -------------------------------------
#
# UNE SEULE CREATRICE EST SUIVIE, et c'est une consigne du proprietaire, pas
# une limite technique : « les clics et les liens de suivi, tu ne regardes que
# Jessye ». L'identifiant est ecrit ici plutot que dans chacun des trois
# ecrans -- la carte du tableau de bord, le report Discord et la page /clics
# doivent parler du MEME espace, sinon ils classeront trois populations
# differentes sous le meme titre.
ESPACE_RANKING = "tm_6a0e4739bfa0c238f20a8bf5"
NOM_ESPACE_RANKING = "JESSY LE RETOUR"
#: L'identite du site correspondante : c'est par elle qu'on retrouve les
#: fiches VA, et donc les comptes Discord. Elle ne se devine pas depuis
#: l'identifiant GetMySocial.
IDENTITE_RANKING = "jessye"


# --- Un emoji par personne --------------------------------------------------
#
# Deux regles pour la palette :
#   pas de drapeau -- Windows ne dessine pas les indicateurs regionaux et les
#     rend en deux lettres minuscules (« 🇺🇸 » se lisait « us ») ;
#   pas de sequence ZWJ -- elle se casse en deux dessins sur les polices
#     anciennes, et une ligne de classement se met a compter double.
# Que des emoji d'UN SEUL point de code, et anciens (Emoji 1.0 a 5.0), pour
# qu'ils existent aussi sur les telephones qui lisent le report Discord.
_POINTS = (
    0x1F98A, 0x1F43C, 0x1F981, 0x1F42F, 0x1F428, 0x1F438, 0x1F435, 0x1F989,
    0x1F985, 0x1F43A, 0x1F98B, 0x1F419, 0x1F988, 0x1F42C, 0x1F984, 0x1F41D,
    0x1F407, 0x1F98C, 0x1F994, 0x1F999, 0x1F996, 0x1F992, 0x1F410, 0x1F433,
    0x1F41E, 0x1F422, 0x1F9A9, 0x1F426, 0x1F437, 0x1F434, 0x1F42E, 0x1F414,
    0x1F987, 0x1F98E, 0x1F420, 0x1F980, 0x1F982, 0x1F40C, 0x1F995, 0x1F998,
    0x1F424, 0x1F427, 0x1F42D, 0x1F439, 0x1F430, 0x1F418, 0x1F42B, 0x1F417,
    0x1F421, 0x1F40B, 0x1F41F, 0x1F40A, 0x1F40D, 0x1F41C, 0x1F997, 0x1F9A2,
    0x1F9A6, 0x1F9A5, 0x1F9A1, 0x1F408, 0x1F34E, 0x1F34C, 0x1F347, 0x1F353,
    0x1F349, 0x1F351, 0x1F352, 0x1F34D, 0x1F335, 0x1F340, 0x1F344, 0x1F680,
    0x1F525, 0x26A1, 0x1F3AF, 0x1F3B8, 0x1F3B2, 0x1F48E, 0x1F3A8, 0x1F514,
)
EMOJIS = tuple(chr(c) for c in _POINTS)

#: LE PODIUM. Trois medailles, pas plus : au-dela, un dessin de plus
#: n'ajoute rien et encombre la ligne — le numero suffit. Elles sont ici et
#: pas dans chacun des trois ecrans, pour que l'or reste l'or partout.
MEDAILLES = ("\U0001F947", "\U0001F948", "\U0001F949")


def medaille(i: int) -> str:
    """La medaille du rang i (0 = premier), ou "" au-dela du podium."""
    return MEDAILLES[i] if 0 <= i < len(MEDAILLES) else ""


#: Le dessin des lignes que personne n'a nommees. Il ne fait PAS partie de la
#: palette : il doit rester reconnaissable au milieu des autres.
EMOJI_ANONYME = "❔"


def emojis(pseudos) -> dict:
    """Un emoji par pseudo, et DEUX PSEUDOS N'ONT JAMAIS LE MEME.

    Tire au sort par le pseudo -- crc32, et surtout pas hash() : le hash des
    chaines est sale a chaque demarrage de Python, l'emoji de chacun aurait
    change a chaque redemarrage du bot.

    Quand deux pseudos tombent sur le meme dessin, le second prend le suivant
    libre. Un classement ou trois lignes portent le meme papillon ne sert plus
    a rien : c'est exactement ce que l'emoji est cense eviter.

    Le parcours suit l'ordre ALPHABETIQUE des pseudos, jamais le classement :
    sinon l'emoji de chacun changerait des que les positions bougent.

    PLUS DE PERSONNES QUE DE DESSINS : la palette se reutilise, et les pseudos
    concernes sortent dans `partages` -- l'appelant doit pouvoir le dire au
    lieu de laisser deux lignes se ressembler sans explication.
    """
    noms = sorted({str(x) for x in pseudos if x})
    pris, out, partages = set(), {}, []
    for ps in noms:
        d = zlib.crc32(ps.encode("utf-8")) % len(EMOJIS)
        choix, libre = EMOJIS[d], False
        for k in range(len(EMOJIS)):
            e = EMOJIS[(d + k) % len(EMOJIS)]
            if e not in pris:
                choix, libre = e, True
                break
        if not libre:
            partages.append(ps)
        pris.add(choix)
        out[ps] = choix
    out["__partages__"] = partages
    return out


# --- Le pseudo derriere un nom de lien --------------------------------------
_ESPACES = re.compile(r"\s+")
_PAREN = re.compile(r"\(([^()]*)\)")
#: Le « VA n » de TETE, et seulement au mot entier : sans la frontiere,
#: « vanessa 3 » se faisait amputer de ses deux premieres lettres.
_TETE_VA = re.compile(r"^va\b\s*\d*\s*[:.\-]?\s*", re.IGNORECASE)
_QUEUE_NUM = re.compile(r"\s+\d+$")
_QUEUE_X = re.compile(r"\s*x\s*\d+$", re.IGNORECASE)
#: Ce qu'on trouve entre parentheses quand elles nomment un APPAREIL et pas
#: quelqu'un : « LaBoule ( Phone ) », « Laboule ( X ) », « prisca 10 (Copy) ».
#: Chaque mot doit en etre un ; « (VA 2 Noum) » ou « (BO7) » n'en sont pas.
_MOT_APPAREIL = re.compile(r"^(?:i?phone|x\d*|spam|fixe|cop(?:y|ie)|\d+)$", re.IGNORECASE)

#: « TEMPLATE », et les quatre facons de l'ecrire de travers qu'on trouve dans
#: les vrais noms de liens (temaplte, tempalte, teamplte). Ce ne sont pas des
#: personnes : ce sont les gabarits dont on duplique les liens.
GABARITS = ("templ", "tempal", "temapl", "teampl")


def est_gabarit(nom) -> bool:
    """Ce lien est-il un gabarit et non quelqu'un ?

    Le filtre voyage AVEC la regle, et pas chez l'appelant : laisse dehors, un
    gabarit ressort comme une ligne anonyme au milieu du classement -- ce qui
    est arrive la premiere fois.

    REGLE LARGE (un morceau du mot n'importe ou), propre au report des clics
    qui l'applique depuis toujours. Le podium, la page Infloww et la paie
    n'ecartent QUE commence_par_gabarit : en sous-chaine, « Twitter VA 5
    @teamplayer » (le format des liens Twitter de liens_va) sortait du
    podium, des lignes de la page Infloww et de la paie.
    """
    return any(g in str(nom or "").lower() for g in GABARITS)


_MOT_DE_TETE = re.compile(r"^\s*([A-Za-z]+)")
_LETTRES_GABARIT = sorted("template")


def commence_par_gabarit(nom) -> bool:
    """Le nom COMMENCE par le mot du gabarit : « TEMPLATE ibenhaastrup »,
    « tempalte julia », « TEMPLATE » seul. C'est la regle des pages de base
    des liens d'identite US (liens_identite_us.est_base la reprend) et la
    seule que le podium (podium_discord.entites), la page Infloww et la paie
    appliquent : ils n'ecartaient rien avant elles, et un vrai VA ne doit pas
    en sortir parce que son pseudo contient « teampl » ou « templ ».

    Le mot : les huit lettres de « template », dans n'importe quel ordre (les
    fautes des vrais noms, temaplte, tempalte, teamplte, sont des lettres
    echangees), un « s » final permis, et un gabarit au sens d'est_gabarit.
    « Temple 1 », « Templeton », « (Teamplayer) 1 » n'en sont pas. Tout nom
    qui y repond est aussi un gabarit pour est_gabarit : la regle etroite est
    contenue dans la large, jamais l'inverse."""
    m = _MOT_DE_TETE.match(str(nom or ""))
    if not m:
        return False
    mot = m.group(1).lower()
    if mot.endswith("s"):
        mot = mot[:-1]
    return sorted(mot) == _LETTRES_GABARIT and est_gabarit(mot)


# --- Les liens d'identite US : a qui ils sont --------------------------------
#
# Un VA US cree lui-meme une page par identite (liens_identite_us) ; chaque
# page pointe vers LE MEME lien de suivi OnlyFans que son lien « global ».
# Proprietaire, 06/10 : ces pages ne sont pas des lignes payees, elles sont
# rattachees a la ligne du global. Le rattachement est un fait ecrit dans le
# registre (id de la page -> id du global), pas une deduction du nom : un nom
# se renomme, et les regles de nom du podium et de ce module divergent deja
# (« tsiry 1 » est « tsiry 1 » au podium, « tsiry » ici). Tous les ecrans le
# lisent par cette fonction, et seulement par elle.
_DEJA_DIT: set = set()


def _dire_une_fois(texte: str) -> None:
    """Le journal, une fois par processus : la fonction est appelee a chaque
    regroupement, plusieurs fois par affichage."""
    if texte not in _DEJA_DIT:
        _DEJA_DIT.add(texte)
        print(texte, flush=True)


def rattachements_identite_ou_panne() -> tuple:
    """({id du lien d'identite: id de son lien global}, panne).

    `panne` est vide quand le registre est lu, ou quand le module n'existe
    pas (fonction pas encore livree : aucun lien d'identite ne peut exister).
    Elle dit pourquoi quand le module existe mais ne repond pas : les pages
    d'identite redeviendraient alors des liens ordinaires -- des lignes
    payees -- et l'appelant doit pouvoir le dire au lieu de payer en silence.
    Ne leve jamais."""
    try:
        import liens_identite_us as _liu
        brut = _liu.rattachements() or {}
    except ModuleNotFoundError as e:
        if getattr(e, "name", "") != "liens_identite_us":
            # le module est la, c'est une de SES dependances qui manque :
            # une panne, pas une fonction absente
            raison = "%s : %s" % (type(e).__name__, e)
            _dire_une_fois("[clics_personnes] liens d'identite US : registre illisible (%s)" % raison)
            return {}, raison[:200]
        _dire_une_fois("[clics_personnes] liens d'identite US : module absent, aucun rattachement")
        return {}, ""
    except Exception as e:                                   # noqa: BLE001
        raison = "%s : %s" % (type(e).__name__, e)
        _dire_une_fois("[clics_personnes] liens d'identite US : registre illisible (%s)" % raison)
        return {}, raison[:200]
    out = {}
    for k, v in (brut.items() if isinstance(brut, dict) else ()):
        k, v = str(k or "").strip(), str(v or "").strip()
        # un lien rattache a lui-meme ne dirait rien, et ferait boucler qui
        # chercherait le global du global
        if k and v and k != v:
            out[k] = v
    return out, ""


def rattachements_identite() -> dict:
    """{id du lien d'identite: id de son lien global} ({} si inconnu)."""
    return rattachements_identite_ou_panne()[0]


def propre(nom) -> str:
    """« ( BO7 )  1 » -> « (BO7) 1 » : les noms sont tapes a la main."""
    n = _ESPACES.sub(" ", str(nom or "")).strip()
    return n.replace("( ", "(").replace(" )", ")")


# --- Le lien SPAM : une personne a part -------------------------------------
#
# 29/09 au soir, le proprietaire : « il n'y a pas les liens spam. Gerome, il
# devrait y avoir un Gerome SPAM. Abdoul, un deuxieme Abdoul, la meme PP et
# tout, mais juste avec ecrit SPAM a cote. » Le report rangeait
# « (Roucham) 1SPAM » SOUS Roucham, comme un telephone de plus, alors que le
# podium (podium_discord.personne / cle_entite) et la page Liens Infloww le
# comptent A PART -- et que la paie des VA SPAM (au sub) s'appuie sur cette
# separation. Deux regles pour la meme chose : c'est celle du podium qui gagne.
#
# UN LIEN EST SPAM SI « spam » EST DANS SON NOM, ou qu'il soit et quelle que
# soit la casse (« (Roucham) 1SPAM », « (PAMPAM) 1 SPAM », « (Abdoul) SPAM »,
# « (Roucham SPAM) ») : meme test que podium_discord (« SPAM » in n.upper()).
# La personne est alors l'etiquette du nom SANS « spam », suivie de « SPAM ».
#
# On n'ote que le MOT spam, pas les lettres « spam » collees a un mot : sans
# ca, « (Spamy) 1 » devenait « y SPAM », « (Espam) 1 » « E SPAM », et
# « va_@spamking » prenait le compte Discord « king » -- le @ et la photo de
# quelqu'un d'autre. Un chiffre devant reste accepte (« 1SPAM »). Un nom colle
# (« Spamy ») reste entier : « Spamy SPAM », comme le podium.
_SPAM = re.compile(r"[\s/._-]*(?<![^\W\d_])spam(?![^\W\d_])[\s/._-]*",
                   re.IGNORECASE)
_PAREN_VIDE = re.compile(r"\(\s*\)")
#: Ce qui s'ajoute a la personne de base : « Roucham » -> « Roucham SPAM ».
SUFFIXE_SPAM = " SPAM"


def est_spam(nom) -> bool:
    """Ce nom de lien est-il un lien SPAM ? (« spam » n'importe ou, toute casse)"""
    return "spam" in str(nom or "").lower()


def sans_spam(nom) -> str:
    """Le nom du lien sans le mot « spam » : « (Roucham) 1SPAM » -> « (Roucham) 1 ».

    Une parenthese qui ne contenait que lui disparait (« LaBoule (SPAM) » ->
    « LaBoule ») : laissee vide, elle faisait sortir « LaBoule () » tel quel."""
    n = _SPAM.sub(" ", str(nom or ""))
    return propre(_PAREN_VIDE.sub(" ", n))


def personne_de_base(personne) -> str:
    """« Roucham SPAM » -> « Roucham », « roucham spam » -> « roucham » ; une
    personne qui n'est pas SPAM est rendue telle quelle.

    C'est la personne dont la fiche VA (donc le @ et la photo) sert aussi a sa
    ligne SPAM : le lien SPAM est le sien, il n'a pas de fiche a lui."""
    p = str(personne or "").strip()
    if p.lower().endswith(SUFFIXE_SPAM.lower()):
        return p[:-len(SUFFIXE_SPAM)].strip()
    return p


def etiquette(nom) -> str:
    """La PERSONNE derriere un nom de lien, dans sa casse d'origine.

    UN LIEN SPAM EST UNE PERSONNE A PART (voir est_spam) : « (Roucham) 1SPAM »
    donne « Roucham SPAM », « (PAMPAM) 1 SPAM » donne « PAMPAM SPAM » -- la
    regle ci-dessous appliquee au nom sans « spam », puis « SPAM » en
    majuscules, quelle que soit la casse du lien. Si ce nom-la ne nomme
    personne (« VA 9 SPAM », « SPAM 1 » : aucune lettre), la ligne reste
    anonyme : pas de « SPAM » seul, pas de « 1 SPAM ».

    ECART CONNU AVEC LE PODIUM, anterieur au SPAM : podium_discord.personne
    prend le « @pseudo » ou qu'il soit dans le nom ; ici seul le prefixe
    « va_@ » le fait. « Twitter VA 1 @abdoul » reste donc tel quel, sans
    fiche. Aucun lien reel n'a cette forme au 29/09 ; si ca arrive, reprendre
    la regle de l'arobase du podium ici, avec un test.

    Les liens s'appellent « VA 12 (Roucham) », « VA 13 Gerome »,
    « VA 8 (VA 2 Noum) », « (BO7) 2 ». Deux numerotations s'y melangent, et
    elles ne veulent pas dire la meme chose :

        le « VA n » de TETE      le numero DU LIEN, jamais celui de quelqu'un
        le nombre de QUEUE       le telephone : « (BO7) 1 » et « (BO7) 2 »
                                 sont les deux appareils d'une meme personne
        le suffixe « X<n> »      idem, ajoute a la main sur les fiches VA

    LA PERSONNE EST TOUT CE QUI EST ENTRE PARENTHESES, ET ON N'Y PELE RIEN.
    « VA 1 Noum », « VA 2 Noum » et « VA 3 Noum » sont TROIS personnes
    differentes -- le proprietaire l'a confirme le 12/09/2026, apres qu'on les
    a fusionnees a tort pendant une journee. Seul ce qui SUIT la parenthese
    est un numero de telephone.

    Sans parentheses, le « VA n » de tete et le nombre final se pelent une
    fois chacun : « VA 13 Gerome » donne Gerome, « jaurel 10 » donne jaurel,
    et « VA 9 » ne nomme personne.

    UNE EXCEPTION, ET UNE SEULE : la parenthese qui nomme un APPAREIL.
    « LaBoule ( Phone ) » et « Laboule ( X ) » sont les deux telephones de
    LaBoule -- vu le 29/09 : le report en faisait deux personnes, « Phone » et
    « X », et aucune n'avait de fiche VA. Quand CHAQUE mot de la parenthese est
    un libelle d'appareil (phone, iphone, x, spam, fixe, copy, un nombre) ET
    qu'un nom la precede, la personne est ce nom, sans son nombre final ni
    son « X<n> ». Sans nom devant (« VA 3 (Phone) »), rien ne change.

    Le « VA n » de tete, lui, RESTE : « VA 2 Noum (Phone) » est VA 2 Noum,
    comme « (VA 2 Noum) 1 ». Le peler faisait de « VA 2 Noum (Phone) » et
    « VA 3 Noum (Phone) » une seule personne « Noum », rattachee ensuite a un
    compte -- la fusion du 12/09, payee cette fois. « VA 13 Gerome (Phone) »
    reste donc a part de « (Gerome) 1 » : une ligne en trop se voit.

    Rendre "" plutot que deviner : mieux vaut une ligne anonyme qu'un
    regroupement invente. Dans certains espaces, cinq liens s'appellent
    « VA 1 » sans etre la meme personne.
    """
    n = propre(nom)
    if not n or est_gabarit(n):
        return ""
    if est_spam(n):
        base = _etiquette_sans_spam(sans_spam(n))
        # « SPAM 1 », « (SPAM) 1 », « SPAM1 » : il ne reste qu'un numero de
        # telephone. Sans ce garde-fou, ils devenaient une personne « 1 SPAM »
        # ou deux liens SPAM de gens differents se retrouvaient fondus.
        if not any(ch.isalpha() for ch in base):
            return ""
        return base + SUFFIXE_SPAM
    return _etiquette_sans_spam(n)


def _etiquette_sans_spam(n: str) -> str:
    """etiquette() d'un nom deja propre, qui n'est ni un gabarit ni un SPAM."""
    if not n or est_gabarit(n):
        return ""
    if n.lower().startswith("va_"):            # « va_@pseudo » : le pseudo suit
        return n[3:].lstrip("@ ").strip()
    m = _PAREN.search(n)
    if m and m.group(1).strip():
        dedans = [x for x in re.split(r"[\s/._-]+", m.group(1)) if x]
        if dedans and all(_MOT_APPAREIL.match(x) for x in dedans):
            devant = n[:m.start()].strip()
            # Un vrai nom, avec au moins une lettre une fois le « VA n » de
            # tete ote : « VA 3 » ou « VA: 4 » seuls ne nomment personne.
            if any(ch.isalpha() for ch in _peler(devant)):
                devant = _QUEUE_NUM.sub("", devant).strip()
                return _QUEUE_X.sub("", devant).strip()
        # Rien n'est pele a l'interieur, sauf le suffixe « X<n> » : celui-la
        # designe bien un telephone de plus, pas quelqu'un d'autre.
        return _QUEUE_X.sub("", m.group(1).strip()).strip()
    return _peler(n)


def _peler(n: str) -> str:
    """Un nom SANS parentheses : le « VA n » de tete et le nombre final se
    pelent une fois chacun, puis le suffixe « X<n> »."""
    n = _TETE_VA.sub("", str(n or "").strip()).strip()
    n = _QUEUE_NUM.sub("", n).strip()
    return _QUEUE_X.sub("", n).strip()


def pseudo(nom) -> str:
    """La meme personne, en minuscules : c'est la cle de regroupement."""
    return etiquette(nom).lower()


# --- Le compte Discord derriere une ligne -----------------------------------
def norme_fiche(nom) -> str:
    """Le nom d'une fiche VA, sous la meme forme que `pseudo()`.

    C'est ce qui rend les deux cotes comparables : « BO7 X2 » sur la fiche et
    « (BO7) 3 » sur le lien donnent tous deux « bo7 ». La regle est celle de
    fusion_vas._norm, a la lettre -- si elles divergeaient, on rattacherait
    des gens au hasard.
    """
    return _QUEUE_X.sub("", _ESPACES.sub(" ", str(nom or "").strip().lower())).strip()


def annuaire_va(identite: str = "") -> dict:
    """{nom de fiche normalise: pseudo Discord, ou ""} pour UNE identite.

    LA FRONTIERE D'IDENTITE NE SE FRANCHIT PAS : le meme nom de fiche sous
    deux creatrices designe deux personnes differentes, fusion_vas le dit en
    toutes lettres et refuse deja de regrouper au-dela. Sans identite, on rend
    un annuaire VIDE plutot que de melanger tout le monde.

    Le pseudo n'est renseigne QUE quand quelqu'un l'a saisi a la main : une
    fiche nee d'un compte, d'une migration ou du Google Sheet arrive avec une
    chaine vide. Ces fiches-la ne rattachent personne, et c'est tres bien : un
    rattachement absent se voit, un rattachement faux se paie.

    MAIS ELLES SONT DANS L'ANNUAIRE, avec "" : sans elles, les etapes laches
    de fiche_de ne voyaient pas la propre fiche de quelqu'un et donnaient la
    personne au compte d'un AUTRE -- « (Andry) 1 » partait chez « Andry R »
    alors qu'une fiche « Andry X1 » existait, sans pseudo encore saisi.
    """
    ident = str(identite or "").strip().lower()
    if not ident:
        return {}
    try:
        import jailbreak as _jb
        fiches = _jb.list_vas_for_identity(ident)
    except Exception:
        return {}
    return annuaire_de_fiches(fiches)


def annuaire_de_fiches(fiches) -> dict:
    """Le calcul d'annuaire_va, sans disque : [{"name", "discord_username"}]
    -> {nom de fiche normalise: pseudo Discord, ou "" s'il n'est pas saisi}.

    Une cle qui a un pseudo sur UNE de ses fiches le garde : « Andry R X1 »
    (pseudo) et « Andry R X2 » (vide) sont les deux telephones d'Andry R.
    """
    out = {}
    for v in fiches or []:
        if not isinstance(v, dict):
            continue
        cle = norme_fiche(v.get("name"))
        pseudo_d = str(v.get("discord_username") or "").strip().lstrip("@")
        if not cle:
            continue
        if pseudo_d:
            # PREMIER ARRIVE, PREMIER SERVI parmi les fiches QUI ONT un pseudo,
            # et on ne remplace jamais : rien n'interdit a deux fiches de porter
            # le meme nom normalise (add_va ne verifie que le nom brut).
            # Ecraser reviendrait a attribuer la ligne au dernier lu,
            # c'est-a-dire au hasard du fichier.
            if not out.get(cle):
                out[cle] = pseudo_d
        else:
            out.setdefault(cle, "")
    return out


# --- Retrouver la fiche d'une personne malgre l'ecriture ---------------------
#
# 29/09 : le report disait « 21 without a Discord account » sur 27 personnes,
# alors que presque toutes ont un pseudo sur leur fiche VA. Le proprietaire :
# « normalement ils sont dans le truc VA, c'est bien la ». Les fiches et les
# liens sont tapes a la main, par des gens differents : « (Gerome) 1 » contre
# « Gérôme X1 », « (PAMPAM) 1 » contre « PAM PAM X1 », « (VA 4 Noum) 1 »
# contre « VA NOUM 4x1 », « (ANDRY) 1 » contre « Andry R X1 ». L'egalite
# stricte n'en rattachait que 6.
#
# UN SEUL RESOLVEUR, par etapes, de la plus sure a la moins sure. On s'arrete
# a la PREMIERE etape qui trouve quelque chose :
#   un seul compte Discord   -> rattache (plusieurs fiches d'un meme compte,
#                               comme les six « VA NOUM », comptent pour un) ;
#   plusieurs comptes        -> AUCUN rattachement, compte « ambigu », et on
#                               ne descend PAS aux etapes plus laches.
# Pas de distance d'edition, pas d'autre heuristique : un rattachement absent
# se voit, un rattachement faux se paie.

#: L'ordre des etapes, tel qu'il sort dans le journal et dans g["rattache"].
ETAPES = ("exact", "plie", "ordre", "premier mot", "pseudo")

#: Les suffixes d'appareil ajoutes a la main aux fiches : « X1 », « x 2 »,
#: « 1 IPHONE X », « 2 IPHONE X FIXE », « /SPAM », « FIXE ». Un nombre SEUL en
#: fin de fiche n'en est pas un : « VA NOUM 4 » n'est pas « VA NOUM ».
_SUFFIXE_APPAREIL = re.compile(
    r"(?:\s*/\s*spam|\s+spam|\s+fixe|\s*\bx\s*\d+"
    r"|\s+\d+\s*i?phone(?:\s*x)?|\s+i?phone(?:\s*x)?)\s*$", re.IGNORECASE)
#: Le pseudo Discord se coupe sur « . », « _ » et les chiffres : « moan_ofm »
#: -> moan, « laboule.8 » -> laboule, « travis_sctt_ » -> travis.
_COUPE_PSEUDO = re.compile(r"[._\d]+")
#: En dessous de 4 lettres, un mot rattache n'importe qui (« va », « bo »).
_LETTRES_MIN = 4


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _mots(s) -> list:
    """Les mots, en minuscules et sans accents ; ponctuation et espaces tombent."""
    return [m for m in re.split(r"[\W_]+", _sans_accents(str(s or "").lower())) if m]


def _base_fiche(cle) -> str:
    """Le nom de fiche sans ses suffixes d'appareil, retires jusqu'au dernier
    (« 2 IPHONE X FIXE » : FIXE, puis « 2 IPHONE X »)."""
    n, avant = _sans_accents(str(cle or "").lower()).strip(), None
    while n != avant:
        avant, n = n, _SUFFIXE_APPAREIL.sub("", n).strip()
    return n


def index_fiches(annuaire) -> list:
    """Les formes comparables de chaque fiche de l'annuaire (calculees une fois).

    Les fiches SANS pseudo y sont aussi, avec compte "" : elles ne rattachent
    jamais, mais elles ARRETENT la recherche (voir fiche_de)."""
    out = []
    for cle, compte in (annuaire or {}).items():
        compte = str(compte or "").strip().lstrip("@")
        if not cle:
            continue
        mots = _mots(_base_fiche(cle))
        tete = _COUPE_PSEUDO.split(_sans_accents(compte.lower()))[0] if compte else ""
        out.append({"cle": cle, "compte": compte,
                    "plie": "".join(mots),
                    "mots": tuple(sorted(mots)),
                    "premier": mots[0] if mots else "",
                    "tete": tete})
    return out


def fiche_de(personne, annuaire, index=None) -> tuple:
    """(compte Discord, etape) pour une personne de lien (`pseudo()`).

    Une personne SPAM (« roucham spam ») est cherchee SANS « spam » : sa
    fiche est celle de sa personne de base (personne_de_base).

    ("", "ambigu") quand une etape designe plusieurs comptes ; ("", "sans
    pseudo") quand elle ne trouve que des fiches dont le pseudo n'est pas
    saisi ; ("", "") quand aucune ne trouve rien. Les etapes, dans l'ordre :

      exact        norme_fiche(personne) est une cle de l'annuaire
      plie         memes lettres une fois plies des deux cotes : minuscules,
                   sans accents, sans ponctuation ni espaces, et cote fiche
                   sans suffixe d'appareil -- gerome = « Gérôme X1 »,
                   pampam = « PAM PAM X1 », yazid = « YAZID 1 IPHONE X »
      ordre        memes mots dans un autre ordre -- « va 4 noum » =
                   « VA NOUM 4x1 »
      premier mot  la personne est le premier mot de la fiche (4 lettres au
                   moins) -- andry = « Andry R X1 »
      pseudo       la personne est le debut du pseudo Discord de la fiche,
                   coupe sur « . _ chiffres » (4 lettres au moins) --
                   moan = moan_ofm (fiche « Maon 1 IPHONE X »)
    """
    # UNE PERSONNE SPAM PREND LA FICHE DE SA PERSONNE DE BASE : « Abdoul
    # SPAM » n'a pas de fiche, c'est le lien SPAM d'Abdoul -- meme @, meme
    # photo (le proprietaire : « la meme PP et tout »).
    ps = personne_de_base(personne)
    annu = annuaire or {}
    if not ps or not annu:
        return "", ""
    if norme_fiche(ps) in annu:
        # SA fiche existe. Sans pseudo, on s'arrete la : descendre aux etapes
        # laches donnerait la personne au compte de quelqu'un d'autre.
        c = str(annu.get(norme_fiche(ps)) or "").strip().lstrip("@")
        return (c, "exact") if c else ("", "sans pseudo")
    idx = index if index is not None else index_fiches(annu)
    p_mots = _mots(ps)
    p_plie = "".join(p_mots)
    if not p_plie:
        return "", ""
    assez = sum(ch.isalpha() for ch in p_plie) >= _LETTRES_MIN
    p_tri = tuple(sorted(p_mots))
    for etape, ok in (
            ("plie", lambda f: f["plie"] == p_plie),
            ("ordre", lambda f: f["mots"] == p_tri),
            ("premier mot", lambda f: assez and f["premier"] == p_plie),
            ("pseudo", lambda f: assez and f["tete"] == p_plie)):
        # UN COMPTE, pas une fiche : la casse du pseudo ne fait pas deux
        # personnes. Le premier trouve donne l'ecriture rendue.
        trouvees = [f for f in idx if ok(f)]
        comptes = {}
        for f in trouvees:
            if f["compte"]:
                comptes.setdefault(f["compte"].casefold(), f["compte"])
        # Une fiche SANS pseudo trouvee ici est peut-etre la vraie fiche de
        # cette personne : on ne rattache pas par-dessus, et on ne descend pas.
        # Seule exception : un autre telephone d'une fiche qui A un pseudo
        # (memes lettres ou memes mots une fois les suffixes d'appareil otes
        # -- « YAZID 2 IPHONE X » a cote de « YAZID 1 IPHONE X »).
        avec = {(f["plie"], f["mots"]) for f in trouvees if f["compte"]}
        autres = [f for f in trouvees if not f["compte"]
                  and not any(f["plie"] == pl or f["mots"] == mo for pl, mo in avec)]
        if autres:
            return "", ("ambigu" if comptes else "sans pseudo")
        if len(comptes) == 1:
            return next(iter(comptes.values())), etape
        if comptes:
            return "", "ambigu"
    return "", ""


def bilan_rattachements(gens) -> str:
    """« rattaches : exact 6, plie 3, ordre 6, premier mot 3, pseudo 3,
    lien 0, ambigus 0, fiche sans pseudo 0, sans fiche 4 » -- pour le journal.
    « fiche sans pseudo » : la fiche est trouvee, il manque le @ a saisir."""
    n = {}
    for g in gens or []:
        r = str((g or {}).get("rattache") or "")
        n[r] = n.get(r, 0) + 1
    morceaux = ["%s %d" % (e, n.get(e, 0)) for e in ETAPES + ("lien",)]
    morceaux.append("ambigus %d" % n.get("ambigu", 0))
    morceaux.append("fiche sans pseudo %d" % n.get("sans pseudo", 0))
    morceaux.append("sans fiche %d" % n.get("", 0))
    return "rattaches : " + ", ".join(morceaux)


# --- Le regroupement --------------------------------------------------------
def _ajouter(somme: dict, champ: str, v) -> None:
    """Verse une valeur dans un total, en retenant ce qu'elle VALAIT.

    Les trois etats sont comptes separement : sans ca, « — » et « · » se
    retrouvent additionnes a zero et le total ment sans le dire.
    """
    if v == "NA":
        somme[champ + "_na"] += 1
        return
    if v is None:
        somme[champ + "_non_lus"] += 1
        return
    try:
        somme[champ] = (somme[champ] or 0) + int(v)
    except (TypeError, ValueError):
        somme[champ + "_non_lus"] += 1
        return
    somme[champ + "_lus"] += 1


def _noms_des_globaux(entrees, rattachements) -> dict:
    """{id d'un lien d'identite: nom propre de SON lien global}, pour les
    liens d'identite dont le global est dans la MEME liste. Les entrees sans
    "id" n'y sont pas : rien n'est rattache par le nom."""
    noms = {}
    for e in entrees:
        lid = str((e or {}).get("id") or "")
        if lid and lid not in noms:
            noms[lid] = propre((e or {}).get("nom"))
    out = {}
    for lid in noms:
        g = rattachements.get(lid)
        # un global qui serait lui-meme un gabarit ne nomme personne : la page
        # garde alors son propre nom
        if g and noms.get(g) and not est_gabarit(noms[g]):
            out[lid] = noms[g]
    return out


def grouper(entrees, annuaire=None, rattachements=None) -> list:
    """Regroupe des liens par personne.

    `entrees` : [{"nom": str, "clics": int|None|"NA",
                  "abonnes": int|None|"NA", "depuis": "AAAA-MM-JJ",
                  "id": id GetMySocial (facultatif)}]

    Rend, par personne : pseudo, titre, emoji, liens, clics, abonnes, taux,
    et les compteurs qui disent POURQUOI un total peut etre incomplet.

    LES PAGES D'IDENTITE US vont a la personne de leur lien global, quel que
    soit leur nom, quand les deux sont dans la liste avec leur "id"
    (`rattachements`, par defaut rattachements_identite(), lu seulement si
    une entree porte un "id") : leurs clics s'ajoutent a sa ligne, sans
    ligne a part. Sans ca, la page de « tsiry 1 » faisait une personne
    « tsiry 1 » a cote de « tsiry ». Une page rattachee n'est jamais prise
    pour un gabarit, meme si le nom de son identite en a l'air.

    ATTENTION AU SENS DES CLICS : selon l'appelant, ils sont deja coupes a la
    date d'arrivee (le report Discord et sa page web le font dans le cog) ou
    ne le sont pas (la carte du tableau de bord lit un releve brut). Cette
    fonction ne coupe rien : elle additionne ce qu'on lui donne et transmet
    `depuis` pour que l'ecran puisse le dire.
    """
    annu = annuaire or {}
    idx = index_fiches(annu)
    entrees = list(entrees or [])
    if rattachements is None:
        rattachements = (rattachements_identite()
                         if any((e or {}).get("id") for e in entrees) else {})
    ratt = rattachements or {}
    globaux = _noms_des_globaux(entrees, ratt) if ratt else {}
    gens = {}
    for e in entrees:
        nom = propre((e or {}).get("nom"))
        lid = str((e or {}).get("id") or "")
        if not nom or (est_gabarit(nom) and lid not in ratt):
            continue                      # un gabarit n'est pas quelqu'un
        # Le nom qui DIT LA PERSONNE : celui du lien global pour une page
        # d'identite, le sien pour tout autre lien. `nom` reste celui affiche.
        nom_p = globaux.get(lid) or nom
        ps = pseudo(nom_p)
        # Sans pseudo, CHAQUE lien garde sa ligne : « VA 5 » et « VA 9 » ne
        # sont pas la meme personne sous pretexte qu'aucun des deux n'est
        # nomme. Le \x00 rend la cle impossible a confondre avec un pseudo.
        cle = ps or ("\x00" + nom_p.lower())
        g = gens.get(cle)
        if g is None:
            # Le titre garde la casse du LIEN : « .title() » rendait
            # « Va 2 Noum » la ou le lien dit « VA 2 Noum ».
            g = gens[cle] = {
                "pseudo": ps, "titre": etiquette(nom_p) or nom_p, "discord": "",
                "rattache": "",
                # Les entrees telles quelles, dans l'ordre : les images du
                # report y relisent le detail de chaque lien (quatre periodes,
                # revenu) sans refaire le regroupement -- une seconde regle
                # de regroupement finirait par diverger de celle-ci.
                "entrees": [],
                "liens": [], "depuis": "",
                "clics": None, "clics_lus": 0, "clics_non_lus": 0, "clics_na": 0,
                "abonnes": None, "abonnes_lus": 0, "abonnes_non_lus": 0,
                "abonnes_na": 0}
        g["liens"].append(nom)
        g["entrees"].append(e)
        if not g["discord"]:
            # DEUX CHEMINS, ET LE PREMIER NE DEMANDE RIEN A PERSONNE.
            # Un lien nomme « va_@pseudo » PORTE deja le compte Discord : il
            # n'y a pas de rapprochement a faire, donc pas d'erreur possible.
            # Sinon on cherche la fiche VA de cette personne, chez la MEME
            # creatrice, par fiche_de -- et on laisse vide au moindre doute.
            # « rattache » garde l'etape qui a trouve : le journal le dit.
            if nom_p.lower().startswith("va_"):
                # « va_@pseudo_spam » : le compte est le pseudo SANS spam.
                base = personne_de_base(ps)
                g["discord"], g["rattache"] = base, ("lien" if base else "")
            else:
                g["discord"], g["rattache"] = fiche_de(ps, annu, idx)
        _ajouter(g, "clics", e.get("clics"))
        _ajouter(g, "abonnes", e.get("abonnes"))
        d = str(e.get("depuis") or "")
        if d > g["depuis"]:
            g["depuis"] = d
    out = list(gens.values())
    emo = emojis([g["pseudo"] for g in out])
    partages = set(emo.pop("__partages__", []))
    for g in out:
        g["emoji"] = emo.get(g["pseudo"]) or EMOJI_ANONYME
        g["emoji_partage"] = g["pseudo"] in partages
        # « muet » : AUCUN des liens de cette personne n'a pu etre lu. Son
        # total n'est pas zero, il est inconnu -- et un classement par les
        # chiffres la mettrait derniere pour une panne de GetMySocial.
        g["clics_muets"] = g["clics_lus"] == 0
        g["abonnes_muets"] = g["abonnes_lus"] == 0
        g["taux"] = (round(g["abonnes"] * 100.0 / g["clics"], 1)
                     if (g["clics"] and g["abonnes"] is not None) else None)
    return out


def par_clics(entrees, annuaire=None, rattachements=None) -> list:
    """Qui envoie du trafic. Les non-lus sortent en fin de liste, pas a zero."""
    out = grouper(entrees, annuaire, rattachements)
    out.sort(key=lambda g: (g["clics_muets"], -(g["clics"] or 0), g["titre"]))
    return out


def par_abonnes(entrees, annuaire=None, rattachements=None) -> list:
    """Qui CONVERTIT ce trafic.

    Les clics disent qui envoie du monde, les abonnes disent qui en fait
    quelque chose : quelqu'un a 500 clics et 0 abonne ne se voyait nulle part.
    On classe donc par abonnes, et on garde les clics a cote -- ils ne
    s'additionnent pas, ce sont deux unites differentes, et un score qui les
    melangerait sans dire comment serait pire que deux colonnes.

    A egalite d'abonnes, celui qui a depense MOINS de clics passe devant :
    c'est lui qui convertit le mieux.
    """
    out = grouper(entrees, annuaire, rattachements)
    out.sort(key=lambda g: (g["abonnes_muets"], -(g["abonnes"] or 0),
                            g["clics"] if g["clics"] is not None else 10 ** 9,
                            g["titre"]))
    return out


def depuis_report(donnees: dict, periode: str = "quinz") -> list:
    """Les entrees de `grouper`, tirees du report des clics.

    Le report livre deja tout : `par_lien` porte les clics (periodes[2] est la
    quinzaine de paie en cours) et `abonnes` porte les abonnes gagnes sur la
    meme fenetre. Les deux sont nommes par la MEME chaine -- _nom_propre(lab),
    issue de la meme liste de liens dans le meme appel -- ce qui en fait une
    cle de jointure sure.

    `periode` : "quinz" (la quinzaine en cours) ou "auj".

    DEUX LIENS PEUVENT PORTER LE MEME NOM. GetMySocial ne garantit pas
    l'unicite des libelles, et les liens en masse sont dupliques d'un gabarit.
    On n'indexe donc PAS les abonnes dans un dictionnaire par nom -- le
    dernier ecraserait les autres et un telephone entier disparaitrait du
    total, en silence. On les apparie rang par rang, les deux listes etant
    construites dans le meme ordre a partir de la meme source.
    """
    par_lien = list((donnees or {}).get("par_lien") or [])
    ab = list((donnees or {}).get("abonnes") or [])
    idx = 2 if periode == "quinz" else 0
    # `abonnes` est un SOUS-ENSEMBLE de `par_lien`, dans le meme ordre : on le
    # parcourt en parallele, en avancant seulement quand les noms coincident.
    j, entrees = 0, []
    for r in par_lien:
        nom = str(r.get("lien") or "")
        per = r.get("periodes") or []
        v = per[idx] if idx < len(per) else None
        clics = None
        if isinstance(v, dict):
            clics = v.get("marche")
            if clics is None:
                clics = v.get("total")
        abo, suivi = None, None
        if j < len(ab) and str(ab[j].get("lien") or "") == nom:
            suivi = ab[j]
            abo = suivi.get("quinz" if periode == "quinz" else "auj")
            j += 1
        # « brut » et « suivi » : les lignes du report telles quelles (les
        # quatre periodes de clics, les abonnes et le revenu du lien de
        # suivi, None quand le lien n'en a pas). grouper les garde dans
        # g["entrees"] ; les images du report les relisent de la.
        e = {"nom": nom, "clics": clics, "abonnes": abo,
             "depuis": str(r.get("depuis") or ""),
             "brut": r, "suivi": suivi}
        # l'identifiant GetMySocial du lien, quand le report le porte : c'est
        # par lui qu'une page d'identite rejoint son lien global (grouper)
        if r.get("id"):
            e["id"] = str(r.get("id"))
        entrees.append(e)
    return entrees
