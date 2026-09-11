# -*- coding: utf-8 -*-
"""Renommer ou retirer une identite, sans laisser de liens morts derriere.

POURQUOI CE FICHIER EXISTE

Le nom d'une identite n'est pas une etiquette : c'est une CLE. Il est a la
fois le nom du dossier `data/identities/<nom>`, une cle de premier niveau dans
cinq fichiers JSON, un element de liste dans deux autres, et le premier
segment des identifiants de fichiers (`<nom>|<sous-dossier>|<fichier>`).

La route de renommage existante refusait donc tout ce qui n'etait pas la
Bibliotheque 2, avec ce commentaire : « celles de la Bibliotheque sont
referencees par leur NOM un peu partout -- les renommer casserait ces liens
en silence ». Le refus etait sage tant que personne n'avait fait la liste.
La voici.

LE PRINCIPE : RIEN EN SILENCE

Chaque emplacement est DECLARE ici, dans une seule table. Un renommage rend
le compte de ce qu'il a touche, emplacement par emplacement -- et, surtout,
la liste de ce qu'il NE SAIT PAS suivre. Les salons et categories Discord
portent le nom de l'identite dans leur propre nom : le bot ne peut pas les
renommer depuis le site, et pretendre le contraire serait pire que de se
taire. On le dit.

LA SUPPRESSION N'EFFACE RIEN

Regle du depot : « le site n'efface jamais un media ». Retirer une identite
DEPLACE son dossier dans `data/_corbeille_identites/<nom>-<horodatage>/` et
ecrit a cote un `_fiche.json` portant tout ce qu'on savait d'elle -- son
referentiel Jailbreak (VA et comptes, y compris les bannis, qu'on ne
supprime jamais), son marche, sa nature, ses styles. Revenir en arriere,
c'est remettre le dossier en place et recharger la fiche.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import safe_json

DATA = Path("data")
IDENTITES = DATA / "identities"
CORBEILLE = DATA / "_corbeille_identites"

#: Fichiers ou le nom est une CLE DE PREMIER NIVEAU d'un dictionnaire.
_CLES = (
    ("jailbreak.json", "le referentiel Jailbreak (VA et comptes Instagram)"),
    ("identity_market.json", "le marche FR/US"),
    ("identity_type.json", "la nature (modele ou identite)"),
    ("identity_styles.json", "les pastilles « ce qui marche »"),
)

#: Fichiers qui sont une LISTE de noms.
_LISTES = (
    ("identity_order.json", "l'ordre d'affichage"),
    ("scrape_identites.json", "le perimetre du scrape Instagram"),
)

#: Fichiers dont les cles sont des identifiants « <nom>|<sous-dossier>|<fichier> ».
_PREFIXES = (
    ("fav_brutes.json", "les brutes mises en favori"),
)

#: Ce qu'aucun code du site ne peut suivre. Dit a l'ecran, jamais tu.
IMPOSSIBLE = (
    "Les salons et categories Discord (general-X, banger-X, exemple-compte-X) "
    "portent l'ancien nom : le bot les retrouve par ce nom, il faut les "
    "renommer sur Discord.",
    "Les menus deja postes sur Discord gardent l'ancien libelle jusqu'a leur "
    "prochain repost.",
    "Les reglages memorises par ton navigateur (onglet courant, filtres, tri) "
    "pointent sur l'ancien nom : ils se retablissent au premier clic.",
)


def _charger(nom_fichier: str):
    return safe_json.load(DATA / nom_fichier, default=None)


def _ecrire(nom_fichier: str, contenu) -> bool:
    return bool(safe_json.write(DATA / nom_fichier, contenu, indent=2))


def normaliser(brut: str) -> str:
    """Le nom tel qu'il sera stocke. Refuse tout ce qui n'est pas sur."""
    import re
    return re.sub(r"[^a-z0-9_\-]", "", str(brut or "").strip().lower())[:40]


def existe(nom: str) -> bool:
    if (IDENTITES / nom).is_dir():
        return True
    d = _charger("jailbreak.json")
    return isinstance(d, dict) and nom in d


def _ou_apparait(nom: str) -> list:
    """Les emplacements qui portent REELLEMENT ce nom, avec leur libelle.

    Sert au recapitulatif montre avant d'agir : une confirmation qui ne dit
    pas ce qu'elle engage n'est pas une confirmation.
    """
    trouves = []
    if (IDENTITES / nom).is_dir():
        n = sum(1 for _ in (IDENTITES / nom).rglob("*") if _.is_file())
        trouves.append({"ou": "le dossier de la Bibliotheque",
                        "detail": f"{n} fichier(s)"})
    for fichier, libelle in _CLES:
        d = _charger(fichier)
        if isinstance(d, dict) and nom in d:
            trouves.append({"ou": libelle, "detail": fichier})
    for fichier, libelle in _LISTES:
        d = _charger(fichier)
        if isinstance(d, list) and nom in [str(x).lower() for x in d]:
            trouves.append({"ou": libelle, "detail": fichier})
    for fichier, libelle in _PREFIXES:
        d = _charger(fichier)
        cles = (d.keys() if isinstance(d, dict) else d) if d else []
        n = sum(1 for k in (cles or []) if str(k).lower().startswith(nom + "|"))
        if n:
            trouves.append({"ou": libelle, "detail": f"{n} entree(s)"})
    d = _charger("text_pool.json")
    if isinstance(d, dict):
        n = 0
        for items in d.values():
            if isinstance(items, list):
                n += sum(1 for e in items if isinstance(e, dict)
                         and str(e.get("identity") or "").lower() == nom)
        if n:
            trouves.append({"ou": "les bios et CTA", "detail": f"{n} texte(s)"})
    return trouves


def apercu(nom: str) -> dict:
    """Ce qu'une action sur ce nom toucherait. Ne modifie rien."""
    nom = normaliser(nom)
    return {"identite": nom, "existe": existe(nom),
            "emplacements": _ou_apparait(nom), "impossible": list(IMPOSSIBLE)}


# ==============================================================================
# Renommer
# ==============================================================================

def renommer(ancien: str, nouveau: str) -> dict:
    """Renomme partout ou le nom est une cle. Rend le detail de ce qui a bouge.

    L'ORDRE COMPTE. Le dossier vient en premier : c'est la seule operation qui
    peut echouer pour une raison exterieure (fichier ouvert, disque plein). Si
    elle echoue, rien d'autre n'a bouge et l'identite reste entiere. Les
    ecritures JSON qui suivent sont atomiques une a une ; si l'une d'elles
    echoue, elle est NOMMEE dans le rapport plutot que passee sous silence --
    on saura exactement quoi rattraper a la main.
    """
    ancien, nouveau = normaliser(ancien), normaliser(nouveau)
    if not ancien or not nouveau:
        return {"ok": False, "error": "Nom invalide (lettres, chiffres, _ ou -)"}
    if ancien == nouveau:
        return {"ok": True, "identite": ancien, "touches": [], "echecs": []}
    if not existe(ancien):
        return {"ok": False, "error": f"« {ancien} » n'existe pas"}
    if existe(nouveau):
        return {"ok": False, "error": f"« {nouveau} » existe deja"}

    touches, echecs = [], []

    if (IDENTITES / ancien).is_dir():
        try:
            (IDENTITES / ancien).rename(IDENTITES / nouveau)
            touches.append({"ou": "le dossier de la Bibliotheque", "detail": "deplace"})
        except Exception as e:
            return {"ok": False,
                    "error": f"Le dossier n'a pas pu etre renomme ({e}). "
                             "Rien d'autre n'a ete touche."}

    for fichier, libelle in _CLES:
        d = _charger(fichier)
        if not isinstance(d, dict) or ancien not in d:
            continue
        d[nouveau] = d.pop(ancien)
        (touches if _ecrire(fichier, d) else echecs).append(
            {"ou": libelle, "detail": fichier})

    for fichier, libelle in _LISTES:
        d = _charger(fichier)
        if not isinstance(d, list):
            continue
        bas = [str(x).lower() for x in d]
        if ancien not in bas:
            continue
        neuf = [nouveau if x == ancien else x for x in bas]
        (touches if _ecrire(fichier, neuf) else echecs).append(
            {"ou": libelle, "detail": fichier})

    for fichier, libelle in _PREFIXES:
        d = _charger(fichier)
        if isinstance(d, dict):
            neuf, n = {}, 0
            for k, v in d.items():
                if str(k).lower().startswith(ancien + "|"):
                    k = nouveau + str(k)[len(ancien):]
                    n += 1
                neuf[k] = v
        elif isinstance(d, list):
            neuf, n = [], 0
            for k in d:
                if str(k).lower().startswith(ancien + "|"):
                    k = nouveau + str(k)[len(ancien):]
                    n += 1
                neuf.append(k)
        else:
            continue
        if not n:
            continue
        (touches if _ecrire(fichier, neuf) else echecs).append(
            {"ou": libelle, "detail": f"{n} entree(s)"})

    d = _charger("text_pool.json")
    if isinstance(d, dict):
        n = 0
        for items in d.values():
            if isinstance(items, list):
                for e in items:
                    if isinstance(e, dict) and str(e.get("identity") or "").lower() == ancien:
                        e["identity"] = nouveau
                        n += 1
        if n:
            (touches if _ecrire("text_pool.json", d) else echecs).append(
                {"ou": "les bios et CTA", "detail": f"{n} texte(s)"})

    return {"ok": True, "identite": nouveau, "ancien": ancien,
            "touches": touches, "echecs": echecs, "impossible": list(IMPOSSIBLE)}


# ==============================================================================
# Retirer (jamais effacer)
# ==============================================================================

def archiver(nom: str) -> dict:
    """Sort une identite de la circulation, sans rien detruire.

    Le dossier part dans `data/_corbeille_identites/<nom>-<horodatage>/`, et
    un `_fiche.json` garde a cote tout ce qu'on savait d'elle. Ses comptes
    Instagram y compris : la regle de l'agence est que les comptes BANNIS ne
    se suppriment jamais, ils sont la trace de comment et pourquoi un compte
    meurt. Les effacer ici reviendrait a contourner cette regle par la porte
    de derriere.
    """
    nom = normaliser(nom)
    if not nom:
        return {"ok": False, "error": "Nom invalide"}
    if not existe(nom):
        return {"ok": False, "error": f"« {nom} » n'existe pas"}

    fiche = {"identite": nom, "archivee_le": int(time.time()), "sources": {}}
    for fichier, libelle in _CLES:
        d = _charger(fichier)
        if isinstance(d, dict) and nom in d:
            fiche["sources"][fichier] = d[nom]

    horodatage = time.strftime("%Y%m%d-%H%M%S")
    dossier = CORBEILLE / f"{nom}-{horodatage}"
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "_fiche.json").write_text(
            json.dumps(fiche, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"Corbeille inaccessible ({e})"}

    retires = []
    if (IDENTITES / nom).is_dir():
        try:
            shutil.move(str(IDENTITES / nom), str(dossier / "media"))
            retires.append({"ou": "le dossier de la Bibliotheque",
                            "detail": "deplace dans la corbeille"})
        except Exception as e:
            return {"ok": False,
                    "error": f"Le dossier n'a pas pu etre deplace ({e}). "
                             "Rien n'a ete retire."}

    for fichier, libelle in _CLES:
        d = _charger(fichier)
        if isinstance(d, dict) and nom in d:
            d.pop(nom, None)
            if _ecrire(fichier, d):
                retires.append({"ou": libelle, "detail": "copie dans la fiche"})

    for fichier, libelle in _LISTES:
        d = _charger(fichier)
        if isinstance(d, list) and nom in [str(x).lower() for x in d]:
            if _ecrire(fichier, [x for x in d if str(x).lower() != nom]):
                retires.append({"ou": libelle, "detail": "retiree"})

    return {"ok": True, "identite": nom, "corbeille": str(dossier),
            "retires": retires, "impossible": list(IMPOSSIBLE)}
