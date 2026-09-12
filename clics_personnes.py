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
import zlib

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
_TETE_VA = re.compile(r"^va\s*\d*\s*[:.\-]?\s*", re.IGNORECASE)
_QUEUE_NUM = re.compile(r"\s+\d+$")
_QUEUE_X = re.compile(r"\s*x\s*\d+$", re.IGNORECASE)

#: « TEMPLATE », et les quatre facons de l'ecrire de travers qu'on trouve dans
#: les vrais noms de liens (temaplte, tempalte, teamplte). Ce ne sont pas des
#: personnes : ce sont les gabarits dont on duplique les liens.
GABARITS = ("templ", "tempal", "temapl", "teampl")


def est_gabarit(nom) -> bool:
    """Ce lien est-il un gabarit et non quelqu'un ?

    Le filtre voyage AVEC la regle, et pas chez l'appelant : laisse dehors, un
    gabarit ressort comme une ligne anonyme au milieu du classement -- ce qui
    est arrive la premiere fois.
    """
    return any(g in str(nom or "").lower() for g in GABARITS)


def propre(nom) -> str:
    """« ( BO7 )  1 » -> « (BO7) 1 » : les noms sont tapes a la main."""
    n = _ESPACES.sub(" ", str(nom or "")).strip()
    return n.replace("( ", "(").replace(" )", ")")


def pseudo(nom) -> str:
    """La PERSONNE derriere un nom de lien, en minuscules, ou "" si anonyme.

    Les liens de Jessye s'appellent « VA 12 (Roucham) », « VA 13 Gerome »,
    « VA 4 (VA 1 Noum) ». Le numero de tete est celui du LIEN, pas de la
    personne ; ce qui reste est le pseudo.

    DIVERGENCE ASSUMEE avec cogs/clickrecap._personne_du_lien. Celui-la garde
    « VA 1 Noum » et « VA 2 Noum » separes, sur la foi d'un commentaire du
    23/08 qui les dit trois personnes differentes. Le proprietaire a tranche
    l'inverse le 12/09 : « meme pseudo c'est meme personne, y a pas de x1 x2 ».
    On fusionne donc -- et les ecrans AFFICHENT les liens reunis sous chaque
    nom, pour que l'erreur, s'il y en a une, se voie du premier coup d'oeil au
    lieu de se cacher dans un total.

    Ne nomme jamais personne pour un gabarit ni pour « VA 9 » tout nu : mieux
    vaut une ligne anonyme qu'un regroupement invente. Dans certains espaces,
    cinq liens s'appellent « VA 1 » sans etre la meme personne.
    """
    n = propre(nom)
    if not n or est_gabarit(n):
        return ""
    bas = n.lower()
    if bas.startswith("va_"):                  # « va_@pseudo » : le pseudo suit
        return bas[3:].lstrip("@ ").strip()
    m = _PAREN.search(n)
    if m and m.group(1).strip():
        n = m.group(1).strip()
    # « VA 4 (VA 1 Noum) » : deux etages de numerotation, on pele les deux.
    avant = None
    while avant != n:
        avant = n
        n = _TETE_VA.sub("", n).strip()
        n = _QUEUE_NUM.sub("", n).strip()
    return _QUEUE_X.sub("", n).strip().lower()


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


def grouper(entrees) -> list:
    """Regroupe des liens par personne.

    `entrees` : [{"nom": str, "clics": int|None|"NA",
                  "abonnes": int|None|"NA", "depuis": "AAAA-MM-JJ"}]

    Rend, par personne : pseudo, titre, emoji, liens, clics, abonnes, taux,
    et les compteurs qui disent POURQUOI un total peut etre incomplet.

    ATTENTION AU SENS DES CLICS : selon l'appelant, ils sont deja coupes a la
    date d'arrivee (le report Discord et sa page web le font dans le cog) ou
    ne le sont pas (la carte du tableau de bord lit un releve brut). Cette
    fonction ne coupe rien : elle additionne ce qu'on lui donne et transmet
    `depuis` pour que l'ecran puisse le dire.
    """
    gens = {}
    for e in entrees or []:
        nom = propre((e or {}).get("nom"))
        if not nom or est_gabarit(nom):
            continue                      # un gabarit n'est pas quelqu'un
        ps = pseudo(nom)
        # Sans pseudo, CHAQUE lien garde sa ligne : « VA 5 » et « VA 9 » ne
        # sont pas la meme personne sous pretexte qu'aucun des deux n'est
        # nomme. Le \x00 rend la cle impossible a confondre avec un pseudo.
        cle = ps or ("\x00" + nom.lower())
        g = gens.get(cle)
        if g is None:
            g = gens[cle] = {
                "pseudo": ps, "titre": ps.title() if ps else nom,
                "liens": [], "depuis": "",
                "clics": None, "clics_lus": 0, "clics_non_lus": 0, "clics_na": 0,
                "abonnes": None, "abonnes_lus": 0, "abonnes_non_lus": 0,
                "abonnes_na": 0}
        g["liens"].append(nom)
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


def par_clics(entrees) -> list:
    """Qui envoie du trafic. Les non-lus sortent en fin de liste, pas a zero."""
    out = grouper(entrees)
    out.sort(key=lambda g: (g["clics_muets"], -(g["clics"] or 0), g["titre"]))
    return out


def par_abonnes(entrees) -> list:
    """Qui CONVERTIT ce trafic.

    Les clics disent qui envoie du monde, les abonnes disent qui en fait
    quelque chose : quelqu'un a 500 clics et 0 abonne ne se voyait nulle part.
    On classe donc par abonnes, et on garde les clics a cote -- ils ne
    s'additionnent pas, ce sont deux unites differentes, et un score qui les
    melangerait sans dire comment serait pire que deux colonnes.

    A egalite d'abonnes, celui qui a depense MOINS de clics passe devant :
    c'est lui qui convertit le mieux.
    """
    out = grouper(entrees)
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
        abo = None
        if j < len(ab) and str(ab[j].get("lien") or "") == nom:
            abo = ab[j].get("quinz" if periode == "quinz" else "auj")
            j += 1
        entrees.append({"nom": nom, "clics": clics, "abonnes": abo,
                        "depuis": str(r.get("depuis") or "")})
    return entrees
