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
    return ("🏆 **Les numéros sont un classement** : la n°1 est celle qui "
            "marche le mieux en ce moment. Commence par le haut de la liste.")


def etiqueter(identites, ordre=None, gabarit="{rang}. {nom}") -> dict:
    """{identité: libellé} — « 1. Lola », « 2. Emma »… puis les non rangées.

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
            sortie[ident] = gabarit.format(rang=n, nom=nom)
        else:
            sortie[ident] = nom
    return sortie
