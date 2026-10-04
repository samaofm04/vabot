# -*- coding: utf-8 -*-
"""Le TYPE d'une story de reserve : 🌿 Life ou ✈️ Travel.

Le proprietaire, le 05/10/2026 : « on differencie les stories [...] story
me, story life, story travel » ; « les story me, c'est ce qu'il y a dans
l'identite, la model ». Seules les stories des RESERVES (US et FR) portent un
type : 📖 Story me vient du dossier de la model elle-meme, sans type.

UN SEUL ENDROIT pour les types, leur logo, leur couleur et leur registre : le
site (web_upload.py) et le bot (cogs/user.py) lisent ce module. Deux tables
recopiees, c'est deux comportements (CLAUDE.md : le Drive en a perdu 598
fichiers).

LE REGISTRE : data/story_types.json = {"<identite>|stories|<fichier>": type},
la cle d'un media du site. Une story sans entree n'a PAS de type : ni Story
life ni Story travel ne la servent, et le site l'affiche « SANS TYPE » --
jamais ecartee en silence. Un type est EXCLUSIF : poser Travel retire Life.
"""
from __future__ import annotations

import threading
from pathlib import Path

import safe_json

TYPES = {
    "life": {"court": "Life", "emoji": "🌿", "couleur": "#22c55e", "texte": "#05250f"},
    "travel": {"court": "Travel", "emoji": "✈️", "couleur": "#38bdf8", "texte": "#032536"},
}
ORDRE = ("life", "travel")
SOUS_DOSSIER = "stories"
FICHIER = Path(__file__).resolve().parent / "data" / "story_types.json"
_VERROU = threading.RLock()


def cle(identite: str, nom: str) -> str:
    return f"{str(identite or '').strip().lower()}|{SOUS_DOSSIER}|{nom}"


def lire() -> dict:
    """{cle: type}. Un registre absent ou illisible vaut « aucun type » : le
    site affiche alors SANS TYPE partout, ce qui se voit."""
    try:
        d = safe_json.load_or_prev(FICHIER)
    except Exception:
        d = None
    if not isinstance(d, dict):
        return {}
    return {str(k): v for k, v in d.items() if v in TYPES}


def type_de(identite: str, nom: str, registre: dict = None) -> str:
    """Le type de cette story, ou "" si elle n'en a pas."""
    return (lire() if registre is None else registre).get(cle(identite, nom), "")


def _ecrire(d: dict) -> None:
    if not safe_json.write(FICHIER, d):
        raise OSError(f"{FICHIER.name} non ecrit")


def poser(identite: str, noms, type_: str) -> int:
    """Pose `type_` sur ces stories (remplace l'autre). Rend le nombre change."""
    if type_ not in TYPES:
        raise ValueError(f"type inconnu : {type_!r}")
    with _VERROU:
        d = lire()
        n = 0
        for nom in noms or ():
            k = cle(identite, nom)
            if d.get(k) != type_:
                d[k] = type_
                n += 1
        if n:
            _ecrire(d)
    return n


def oublier(cle_media: str) -> bool:
    """Retire le type d'un media mis a la corbeille : sans ca, un fichier de
    MEME NOM televerse plus tard heriterait du type de l'ancien."""
    with _VERROU:
        d = lire()
        if cle_media not in d:
            return False
        d.pop(cle_media)
        _ecrire(d)
        return True


def transferer(de: str, vers: str) -> bool:
    """Un doublon range : son type passe sur l'exemplaire garde, s'il n'en a
    pas deja un."""
    with _VERROU:
        d = lire()
        if de not in d:
            return False
        if vers not in d:
            d[vers] = d[de]
        d.pop(de)
        _ecrire(d)
        return True
