"""L'ordre des identités, décidé par le propriétaire.

Pourquoi un module à part
-------------------------
DEUX endroits décident du même ordre : les barres latérales du site
(glisser-déposer, route `/identity/reorder`) et les menus Discord que
voient les VA. Deux implémentations, ce serait deux ordres différents le
jour où l'une des deux change — le dépôt a déjà payé ça avec les deux
tables de correspondance du Drive, où 598 fichiers étaient invisibles d'un
côté et pas de l'autre.

La RÈGLE vit donc ici, une seule fois. Le CHARGEMENT, lui, reste propre à
chaque côté : le site a son cache invalidé à l'écriture, le bot n'écrit
jamais et se contente de relire quand le fichier a changé.

Qui peut réordonner
-------------------
Personne d'autre que le propriétaire : `/identity/reorder` est couvert par
`_ADMIN_ONLY_WRITE` (« /identity/ »), donc un rôle restreint reçoit 403
même en appelant la route à la main depuis la console.
"""
from __future__ import annotations

import json
from pathlib import Path

#: LE PODIUM EST DEFINI UNE SEULE FOIS, ET C'EST LA-BAS.
#:
#: Ce module en gardait sa propre copie, alors que clics_personnes annonce
#: dans son commentaire etre le seul endroit « pour que l'or reste l'or
#: partout ». Deux tuples identiques, c'est le defaut que le CLAUDE.md du
#: depot decrit noir sur blanc : ils le restent jusqu'au jour ou l'un bouge.
#:
#: clics_personnes ne connait ni Flask, ni Discord, ni GetMySocial, ni le
#: disque -- il est ecrit pour etre importe par les trois ecrans qui s'en
#: servent, et il n'y a aucun cycle a craindre ici.
from clics_personnes import MEDAILLES

FICHIER = Path("data") / "identity_order.json"

# Cache minuscule, pour le côté qui n'écrit pas (le bot) : on relit quand la
# date de modification bouge. Sans ça, chaque construction de menu relisait le
# fichier autant de fois qu'il y a de models.
_CACHE: dict = {"mtime": None, "ordre": []}


def lire() -> list:
    """L'ordre enregistré, en minuscules. Liste vide si rien n'est rangé."""
    try:
        mtime = FICHIER.stat().st_mtime
    except OSError:
        _CACHE["mtime"], _CACHE["ordre"] = None, []
        return []
    if _CACHE["mtime"] != mtime:
        try:
            brut = json.loads(FICHIER.read_text(encoding="utf-8"))
        except Exception:
            brut = []
        _CACHE["ordre"] = ([str(x).lower() for x in brut]
                           if isinstance(brut, list) else [])
        _CACHE["mtime"] = mtime
    return list(_CACHE["ordre"])


def trier(identites, ordre=None) -> list:
    """Trie selon l'ordre choisi ; les non-classées après, en alphabétique.

    `ordre` permet à l'appelant de fournir sa propre lecture (le site passe
    la sienne, qui vient de son cache). Sans argument, on lit le fichier.
    """
    if ordre is None:
        ordre = lire()
    pos = {n: i for i, n in enumerate(ordre)}
    return sorted(identites,
                  key=lambda n: (pos.get(str(n).lower(), len(pos) + 1),
                                 str(n).lower()))


def rang(identite, ordre=None):
    """Le numéro à afficher (1, 2, 3…), ou None si l'identité n'est pas rangée.

    On ne numérote QUE ce qui a été rangé à la main. Numéroter une liste
    alphabétique donnerait un faux classement : le VA lirait « 1 » comme
    « celle qui marche le mieux » alors que personne n'aurait rien décidé.
    """
    if ordre is None:
        ordre = lire()
    n = str(identite or "").lower()
    try:
        return ordre.index(n) + 1
    except ValueError:
        return None


def phrase_classement(identites, ordre=None) -> str:
    """La phrase qui explique les numéros, ou "" s'il n'y a rien à expliquer.

    Sans elle, « 1. Lola » ressemble à une liste arbitraire : le VA voit un
    numéro et n'en tire rien. C'est le classement qui porte l'information —
    encore faut-il dire ce qu'il classe.

    Vide si aucune identité affichée n'a été rangée à la main : annoncer un
    classement qui n'existe pas serait pire que de ne rien dire.
    """
    if ordre is None:
        ordre = lire()
    connues = set(ordre)
    classees = [i for i in identites if str(i).lower() in connues]
    if not classees:
        return ""
    # ELLE DIT CE QUI EST CLASSE, ET DANS QUEL SENS. « Cette liste est un
    # classement » laissait deviner le reste : classement de quoi, du meilleur
    # vers le pire ou l'inverse ? Le propriétaire, en relisant le menu posté :
    # « dis ici c'est un classement des meilleures identités à la moins
    # bonne ». Un classement dont on ignore le sens ne se lit pas, il se
    # suppose — et une supposition sur deux est fausse.
    #
    # Elle ne parle plus de « numéros » : il n'y en a plus, chaque ligne porte
    # un badge. On montre donc la médaille elle-même, celle qu'il a sous les
    # yeux à la première ligne.
    phrase = ("**C'est un classement : de la meilleure model à la moins "
              "bonne.**\nCommence par le haut — la %s est celle qui marche le "
              "mieux en ce moment." % MEDAILLES[0])
    # ET ON DIT CE QUI N'EN EST PAS. Le propriétaire a demandé « une médaille
    # pour chacun » ; il en manque quand même une à toute identité qu'il n'a
    # pas rangée à la main, parce qu'on refuse d'inventer un rang (voir
    # `rang` : numéroter une liste alphabétique donnerait un faux classement,
    # et le VA lirait « 1 » comme « celle qui marche le mieux »).
    #
    # Le taire, c'est le laisser chercher pourquoi trois lignes sont nues.
    # Le dire, c'est lui donner le geste qui les remplit.
    nues = [i for i in identites if str(i).lower() not in connues]
    if nues:
        phrase += ("\n*%d model(s) ne sont pas encore classées : elles suivent "
                   "en bas, sans médaille. Range-les par glisser-déposer sur "
                   "le site pour leur en donner une.*" % len(nues))
    return phrase


#: LE RANG SE DESSINE, ET CA VAUT POUR TOUS -- PAS SEULEMENT LE PODIUM.
#:
#: Premiere version : une medaille pour les trois premiers, un chiffre nu
#: pour la suite. Le proprietaire, en relisant son menu : « je veux une
#: medaille pour chacun ». C'est le meme constat qu'avant, applique aux
#: lignes du bas : « 4. Genesaag » se lit comme un nom qui commencerait par
#: un chiffre, « 4️⃣ Genesaag » se voit avant d'etre lu. S'arreter a trois,
#: c'etait garder le probleme pour les douze lignes suivantes.
#:
#: Au-dela de dix il n'existe pas de pastille chiffree : on pose alors les
#: CHIFFRES un par un, « 1️⃣2️⃣ » pour douze. Ce n'est pas elegant, c'est
#: lisible -- et le menu US compte vingt-deux models.
#:
#: UNE REGLE DE PALETTE EST ENFREINTE ICI, SCIEMMENT. clics_personnes
#: n'accepte que des emoji d'UN SEUL point de code, parce qu'une sequence se
#: casse en deux dessins sur les polices anciennes. Une pastille chiffree en
#: compte trois (le chiffre, le selecteur de variante, la marque
#: d'encadrement) : elle ne respecte donc PAS cette regle.
#:
#: On la prend quand meme, pour deux raisons. La sequence keycap est l'une
#: des plus vieilles d'Unicode et Discord la dessine sur tous ses clients ; et
#: surtout, si elle se cassait, ce qui reste a l'ecran est le CHIFFRE -- soit
#: exactement l'ancien affichage. Le pire cas de ce choix, c'est l'etat
#: d'avant. Aucun ZWJ en revanche, la regle qui compte vraiment.
KEYCAPS = tuple(chr(0x30 + c) + "\uFE0F\u20E3" for c in range(10))
DIX = "\U0001F51F"


def prefixe_rang(n) -> str:
    """Le badge du rang : 1 → 🥇, 2 → 🥈, 3 → 🥉, 4 → 4️⃣, 10 → 🔟, 12 → 1️⃣2️⃣.

    Jamais un chiffre nu, et jamais rien : une ligne sans badge au milieu de
    lignes qui en portent un redeviendrait le cas particulier qu'on essaie
    justement de supprimer.

    Rend "" pour ce qui n'est PAS un rang (illisible, zero, negatif). Un
    badge invente vaudrait un classement invente.
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n < 1:
        return ""
    if n <= len(MEDAILLES):
        return MEDAILLES[n - 1]
    if n == 10:
        return DIX
    return "".join(KEYCAPS[int(c)] for c in str(n))


def etiqueter(identites, ordre=None, gabarit="{rang} {nom}") -> dict:
    """{identité: libellé} — « 🥇 Lola », « 🥈 Emma », « 4️⃣ Nina »…

    Le numéro est la position DANS LA LISTE AFFICHÉE, pas dans le fichier.
    Vérifié sur les vraies données : les six identités FR occupent les rangs
    1 à 6 du fichier, mais le menu US ne montre que les models US. Numéroter
    d'après le fichier y aurait affiché « 7. Ibenhaastrup » en première
    ligne — un numéro qui ne veut rien dire pour le VA qui le lit.

    Les identités jamais rangées à la main suivent, SANS numéro : leur
    donner un rang inventerait un classement que personne n'a décidé.
    """
    if ordre is None:
        ordre = lire()
    connues = set(ordre)
    sortie, n = {}, 0
    for ident in trier(identites, ordre):
        nom = str(ident).capitalize()
        if str(ident).lower() in connues:
            n += 1
            # `rang` arrive DEJA mis en forme : le gabarit par defaut colle
            # simplement la medaille au nom, sans point apres -- « 🥇. Lola »
            # se lirait comme une faute.
            sortie[ident] = gabarit.format(rang=prefixe_rang(n), nom=nom)
        else:
            sortie[ident] = nom
    return sortie
