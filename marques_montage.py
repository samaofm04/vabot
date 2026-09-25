"""Les marques EXCLUSIVES d'un montage : ⚡ Flash Trend et 💀 Trash Trend.

UN SEUL ENDROIT pour le nom, le logo, la couleur et le fichier de chaque
marque. Le site (web_upload.py), le bot (cogs/user.py) et le stock d'avance
lisent cette table. Le proprietaire a choisi 💀 pour Trash le 25/09/2026 et
compte revoir les logos : les changer ici les change partout. Deux tables
recopiees, c'est deux comportements -- le Drive en a deja fait les frais
(598 fichiers invisibles, voir CLAUDE.md).

CE QU'EST UNE MARQUE
    Elle REMPLACE la place du montage, elle ne s'ajoute pas : un montage
    marque sort de la vue de base et des Bangers du site. L'etoile ⭐, elle,
    se cumule (⭐ + Flash = « Flash Banger »).

    Un montage porte AU PLUS UNE marque. Poser Trash retire Flash, et
    inversement : sans ca, le meme template partait par deux familles de
    boutons Discord et se publiait deux fois. Si une ancienne donnee porte
    les deux, FLASH L'EMPORTE (elle existait avant) et le conflit est compte.

    L'ordre d'affichage suit la demande du proprietaire : les templates, puis
    Trash, puis Flash -- Trash vit « entre les deux ».

NOMMAGE
    Jamais « trash » seul : le mot designe deja la corbeille dans ce depot
    (bouton de suppression, fichiers « trashed » du Drive, data/_corbeille_*).
    On ecrit trash_trend, TRASH_TREND, templatetrash.
"""
from __future__ import annotations

import json
from pathlib import Path

MARQUES = {
    "flash": {
        "nom": "Flash Trend",
        "court": "Flash",
        "emoji": "⚡",
        # Couleur d'accent sur fond sombre, puis sa version lisible en theme
        # clair (le cyan pur disparait sur du blanc).
        "couleur": "#22d3ee",
        "couleur_clair": "#0e7490",
        "fichier": "flash_trend.json",
        # Cles d'action Discord, de la plus simple a la plus exigeante :
        # la marque seule, + etoile, brute etoilee + marque, marque etoilee +
        # brute etoilee. En [a-z]+ : c'est le motif des custom_id.
        "actions": ("templateflash", "templateflashbanger", "brutflash",
                    "templateflashbrut"),
    },
    "trash": {
        "nom": "Trash Trend",
        "court": "Trash",
        "emoji": "💀",
        "couleur": "#a3e635",
        "couleur_clair": "#4d7c0f",
        "fichier": "trash_trend.json",
        "actions": ("templatetrash", "templatetrashbanger", "bruttrash",
                    "templatetrashbrut"),
    },
}

#: Ordre d'affichage : Trash avant Flash, les deux apres les templates.
ORDRE = ("trash", "flash")

#: Quand une donnee ancienne porte deux marques, celle-ci gagne.
PRIORITE = ("flash", "trash")


def marque(cle: str) -> dict:
    """La fiche d'une marque. KeyError sur une cle inconnue : une faute de
    frappe doit se voir tout de suite, pas servir une fiche vide."""
    return MARQUES[cle]


def autres(cle: str) -> tuple:
    """Les marques qu'on retire quand on pose `cle` (exclusivite)."""
    return tuple(c for c in ORDRE if c != cle)


def chemin(cle: str, data_dir="data") -> Path:
    return Path(data_dir) / MARQUES[cle]["fichier"]


def lire_cles(fichier) -> set:
    """Les cles « identite|templates|fichier » d'un registre de marque.

    Tolere un fichier absent (trash_trend.json nait au premier marquage), une
    liste ou un dict. Un fichier ILLISIBLE rend aussi un ensemble vide : c'est
    au lecteur qui doit le signaler d'utiliser lire_cles_ou_erreur.
    """
    return lire_cles_ou_erreur(fichier)[0]


def lire_cles_ou_erreur(fichier):
    """(cles, erreur) -- erreur vide si tout va bien ou si le fichier n'existe
    pas encore ; sinon la raison, pour la dire au lieu de l'avaler."""
    p = Path(fichier)
    if not p.exists():
        return set(), ""
    try:
        texte = p.read_text(encoding="utf-8")
    except Exception as e:                                  # noqa: BLE001
        return set(), f"{p.name} illisible ({type(e).__name__})"
    # Un registre PRESENT mais vide n'est pas « aucune marque » : le code
    # n'en ecrit jamais (un registre vide s'ecrit « [] »). C'est une copie
    # interrompue -- un scp de data/ coupe en route. Le lire comme une liste
    # vide laissait passer le clic ; la premiere ecriture etait acceptee, et
    # la seconde ecrasait le .prev qui gardait encore les vraies marques
    # (safe_json ne sauvegarde pas un fichier de 1 octet ou moins).
    # safe_json.load, lui, le traitait deja comme illisible : deux lectures
    # pour une meme situation.
    if not texte.strip():
        return set(), (f"{p.name} vide -- la version precedente est peut-etre "
                       f"dans {p.name}.prev")
    try:
        raw = json.loads(texte)
    except Exception as e:                                  # noqa: BLE001
        return set(), f"{p.name} illisible ({type(e).__name__})"
    if isinstance(raw, dict):
        return {k for k in raw.keys() if isinstance(k, str)}, ""
    if isinstance(raw, list):
        return {k for k in raw if isinstance(k, str)}, ""
    return set(), f"{p.name} : format inattendu ({type(raw).__name__})"


def conflits(par_marque: dict) -> dict:
    """{cle_media: [marques]} pour chaque media porte par plusieurs marques.

    `par_marque` : {"flash": set(cles), "trash": set(cles)}.
    """
    vu = {}
    for m, cles in par_marque.items():
        for k in cles:
            vu.setdefault(k, []).append(m)
    return {k: sorted(ms, key=PRIORITE.index) for k, ms in vu.items() if len(ms) > 1}


def gagnante(marques_du_media) -> str:
    """La marque retenue pour un media qui en porte plusieurs (PRIORITE)."""
    for m in PRIORITE:
        if m in marques_du_media:
            return m
    return ""
