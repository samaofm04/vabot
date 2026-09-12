"""Ce qui MARCHE pour une identité : caption, brut, montage, template/flash.

Source UNIQUE, importée par le site (web_upload) et par le bot (cogs/user).
Le site sert les pastilles à côté du nom dans la Bibliothèque, le bot les
colle au bout des libellés du menu Jailbreak. La même information, à deux
endroits : elle ne peut donc pas vivre dans l'un des deux, sinon le jour où
un style s'ajoute il n'apparaît que d'un côté. C'est exactement ce que
`marche.py` fait déjà pour le drapeau FR/US, et pour la même raison.

Rien ici n'est déduit des chiffres : c'est le propriétaire qui coche, sur le
site (Bibliothèque -> ✎ Modifier -> « Ce qui marche »), parce que c'est lui
qui voit ce qui prend. Une identité peut porter plusieurs styles, ou aucun.

L'ordre de `STYLES` est l'ordre d'affichage — les pastilles se lisent
toujours dans le même sens d'une identité à l'autre, sinon l'œil doit relire
à chaque ligne. **L'emoji peut changer sans rien perdre, la CLÉ non** : c'est
elle qui est écrite dans data/identity_styles.json.
"""
from __future__ import annotations

from pathlib import Path

import safe_json

FICHIER = Path("data") / "identity_styles.json"

#: (clé, emoji, libellé court, couleur, ce que ça veut dire)
STYLES = (
    ("caption", "💬", "Caption",  "#38bdf8",
     "Les comptes marchent avec une caption incrustée"),
    ("brut",    "🎥", "Brut",     "#a3a3a3",
     "Les comptes marchent en publiant la vidéo brute, telle quelle"),
    ("montage", "🎬", "Montage",  "#f472b6",
     "Les comptes marchent avec un montage"),
    ("flash",   "⚡", "Template", "#facc15",
     "Les comptes marchent avec les templates / flash reels"),
)

#: LE MEME STYLE, DESSINE. L'emoji ci-dessus part sur Discord, qui ne sait
#: afficher que ca ; le SITE, lui, dessine tout le reste de son interface en
#: SVG (viewBox 24x24, trait 2, bouts arrondis), et une pastille en emoji au
#: milieu d'icones tracees se voit tout de suite.
#:
#: Les deux vivent cote a cote plutot que l'un a la place de l'autre : Discord
#: ne peut pas afficher de SVG, et le site n'a aucune raison de se contenter
#: d'un emoji. La CLE reste la seule chose qui compte pour les donnees.
TRACES = {
    # Une bulle de dialogue : la caption incrustee.
    "caption": ("<path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14"
                "a2 2 0 0 1 2 2z'/>"),
    # Une camera : la video brute, telle quelle.
    "brut": ("<rect x='2' y='6' width='13' height='12' rx='2'/>"
             "<path d='M22 8.5v7L15.5 12z'/>"),
    # Un clap : le montage.
    "montage": ("<path d='M3 7.5h18v12a1.5 1.5 0 0 1-1.5 1.5h-15"
                "A1.5 1.5 0 0 1 3 19.5z'/><path d='M3 7.5 5.4 3h13.2L21 7.5'/>"
                "<path d='M8.4 3 10.8 7.5'/><path d='M14.4 3l2.4 4.5'/>"),
    # Un eclair : les templates flash.
    "flash": "<path d='M13 2 4 14h7l-1 8 9-12h-7z'/>",
}


def trace(cle: str) -> str:
    """Le trace SVG d'un style, ou une chaine vide s'il n'en a pas encore.

    Rendre vide plutot que lever : un style ajoute demain sans dessin doit
    s'afficher quand meme, avec son emoji, pas faire tomber la page.
    """
    return TRACES.get(str(cle or "").strip().lower(), "")


#: LA FORME COURTE, celle qui va dans un menu Discord.
#:
#: Le texte de STYLES est ecrit pour une infobulle du site : il se suffit a
#: lui-meme (« Les comptes marchent avec une caption incrustee »). Empile
#: quatre fois dans un embed, il devient un mur ou chaque ligne recommence par
#: les memes trois mots -- et le proprietaire a deja dit que ses VA decrochent
#: sur moins que ca.
#:
#: Ce n'est PAS une seconde source de verite : la cle reste celle de STYLES,
#: et un test exige que chaque style ait sa forme courte. Si elle n'est pas
#: rangee DANS le tuple, c'est que sa forme est depaquetee telle quelle
#: (« for c, e, lab, co, t in STYLES ») par le site et par deux suites de
#: tests : l'elargir casserait trois fichiers pour un libelle.
COURT = {
    "caption": "une caption incrustée",
    "brut":    "la vidéo brute, telle quelle",
    "montage": "un montage",
    "flash":   "les templates / flash reels",
}

CLES = tuple(c for c, _e, _l, _co, _t in STYLES)
_PAR_CLE = {c: (e, lab, co, t) for c, e, lab, co, t in STYLES}

_CACHE: dict = {"sig": None, "data": {}}


def _table() -> dict:
    """{identité: [clés]}, relue quand le fichier bouge — le site écrit, le
    bot lit, ce sont deux processus."""
    try:
        sig = FICHIER.stat().st_mtime_ns
    except OSError:
        _CACHE.update(sig=None, data={})
        return {}
    if _CACHE["sig"] != sig:
        d = safe_json.load(FICHIER, default={}) or {}
        propre = {}
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, list):
                    # Une clé inconnue est ECARTEE ici, pas plus loin : sinon
                    # elle ressort en KeyError au moment de dessiner.
                    propre[str(k).lower()] = [s for s in v if s in CLES]
        _CACHE.update(sig=sig, data=propre)
    return _CACHE["data"]


def de(identity: str) -> list:
    """Les styles cochés, dans l'ordre d'affichage.

    On re-trie sur `STYLES` au lieu de rendre la liste telle qu'elle a été
    enregistrée : sans ça l'ordre dépendait de l'ordre des clics, et deux
    identités aux mêmes styles ne s'affichaient pas pareil.
    """
    poses = set(_table().get((identity or "").strip().lower()) or ())
    return [c for c in CLES if c in poses]


def emojis(identity: str) -> str:
    """« 💬⚡ », ou '' si rien n'est coché. Collés, sans séparateur : c'est
    une pastille, pas une phrase."""
    return "".join(_PAR_CLE[c][0] for c in de(identity))


def mots(identity: str, separateur: str = " + ") -> str:
    """« Template + Caption », ou '' si rien n'est coché.

    LES PASTILLES NE SE DEVINENT PAS. Sur le site elles sont accompagnees
    d'une legende ; dans un menu Discord, « 💬⚡ » arrive nu, et le
    proprietaire l'a dit : « les emojis, ils n'arrivent pas a comprendre ».
    Un VA qui lit « Template + Caption » sait quoi faire sans avoir appris un
    code.

    C'est la MEME table que les emojis : un style ajoute apparait des deux
    cotes, ou d'aucun.
    """
    return separateur.join(_PAR_CLE[c][1] for c in de(identity))


def legende(identites) -> list:
    """[(libellé, forme courte)] des styles PRÉSENTS dans cette liste.

    On n'explique que ce qu'on affiche : détailler « Template » alors
    qu'aucune model n'en porte, c'est du texte que le VA lit pour rien, et
    une ligne de plus entre lui et le bouton qu'il cherche.

    Ordre de STYLES, comme les pastilles : d'une identité à l'autre l'œil
    retrouve le même sens, sinon il relit à chaque ligne.
    """
    vus = set()
    for i in identites or []:
        vus.update(de(i))
    return [(_PAR_CLE[c][1], COURT[c]) for c in CLES if c in vus and c in COURT]


def definir(identity: str, styles) -> bool:
    """Écrit les styles d'une identité. Liste vide = on retire l'entrée.

    Tout décocher est une écriture comme une autre — sinon on ne pourrait
    jamais retirer la dernière pastille.
    """
    idl = (identity or "").strip().lower()
    if not idl:
        return False
    gardes = [c for c in CLES if c in set(styles or ())]
    d = dict(_table())
    if gardes:
        d[idl] = gardes
    else:
        # Pas de liste vide qui traîne : le fichier se lit à l'œil, autant
        # qu'il ne porte que ce qui existe vraiment.
        d.pop(idl, None)
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    ok = bool(safe_json.write(FICHIER, d, indent=2))
    _CACHE.update(sig=None, data={})          # relecture forcée au prochain appel
    return ok


def table_json() -> list:
    """La table, pour le navigateur. Le sélecteur du site se dessine depuis
    ELLE : une deuxième liste en dur côté JS, et un style ajouté n'apparaîtrait
    que d'un seul côté."""
    return [{"cle": c, "emoji": e, "label": lab, "couleur": co, "titre": t,
             "trace": trace(c)}
            for c, e, lab, co, t in STYLES]
