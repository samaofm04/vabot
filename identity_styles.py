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
    return [{"cle": c, "emoji": e, "label": lab, "couleur": co, "titre": t}
            for c, e, lab, co, t in STYLES]
