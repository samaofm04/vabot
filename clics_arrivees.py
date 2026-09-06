# -*- coding: utf-8 -*-
"""Depuis quand un lien de suivi appartient a la personne qui le porte.

LE PROBLEME. Les liens de suivi survivent aux personnes : quand un VA part,
son lien est repris par le suivant. Les clics et les abonnes d'avant restent
attaches au lien, donc au nouveau venu, qui lit comme siens des chiffres qui
ne le sont pas — et qui peut de bonne foi s'en prevaloir.

CE MODULE ne fait qu'une chose : retenir, par lien, la date a partir de
laquelle on compte. Le report s'en sert pour couper chaque periode a cette
date, et pour distinguer trois etats qui n'ont rien a voir :

    un nombre   ce qui a ete lu, et qui lui revient
    « — »       la source n'a pas repondu : on ne sait pas
    « · »       la periode est ANTERIEURE a son arrivee : ce n'est pas a lui

Le troisieme n'existait pas, et c'est tout le sujet : il ressortait en
chiffre, indistinguable d'un travail reellement fourni.

La cle est l'IDENTIFIANT du lien (lnk_…), jamais son nom : le nom change
justement quand la personne change, c'est ce qui rend le nom inutilisable
comme reference — et c'est aussi pourquoi on ne peut pas deviner la date en
regardant le nom.
"""

from __future__ import annotations

import pathlib
import re
import time
from typing import Dict, List

import safe_json

FICHIER = pathlib.Path(__file__).resolve().parent / "data" / "clics_arrivees.json"

_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _vide() -> dict:
    return {"liens": {}, "depuis": {}}


def charger() -> dict:
    d = safe_json.load(FICHIER, None)
    if not isinstance(d, dict):
        return _vide()
    d.setdefault("liens", {})
    d.setdefault("depuis", {})
    if not isinstance(d["liens"], dict):
        d["liens"] = {}
    if not isinstance(d["depuis"], dict):
        d["depuis"] = {}
    return d


def _ecrire(d: dict) -> None:
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(FICHIER, d)


def date_de(link_id: str) -> str:
    """« YYYY-MM-DD » ou "" si personne n'a fixe de date pour ce lien."""
    return str(charger()["depuis"].get(str(link_id or "")) or "")


def toutes() -> Dict[str, str]:
    """Toutes les dates d'un coup : le report en lit trente, une par lien.

    Trente appels a `date_de` reliraient trente fois le meme fichier.
    """
    return {str(k): str(v) for k, v in charger()["depuis"].items() if v}


def definir(link_id: str, date: str) -> bool:
    """Fixe (ou efface, avec une date vide) la date d'arrivee d'un lien."""
    lid = str(link_id or "").strip()
    if not lid:
        return False
    date = str(date or "").strip()
    if date and not _RE_DATE.match(date):
        return False
    d = charger()
    if date:
        d["depuis"][lid] = date
    else:
        d["depuis"].pop(lid, None)
    d.setdefault("liens", {}).setdefault(lid, {})["maj"] = int(time.time())
    _ecrire(d)
    return True


def enregistrer_liens(liens: List[dict], cle_report: str = "") -> None:
    """Retient les liens VUS par le report : id, nom affiche, d'ou ils viennent.

    Sans ca, le panneau de reglage devrait redemander la liste des liens a
    GetMySocial a chaque ouverture — c'est-a-dire depenser du quota pour
    afficher un formulaire. Le report passe deja devant ces liens : il les
    depose ici en chemin.
    """
    if not liens:
        return
    d = charger()
    change = False
    for l in liens:
        lid = str((l or {}).get("id") or "").strip()
        if not lid:
            continue
        nom = str((l or {}).get("nom") or "")[:80]
        e = d["liens"].setdefault(lid, {})
        if e.get("nom") != nom or (cle_report and e.get("cle") != cle_report):
            e["nom"] = nom
            if cle_report:
                e["cle"] = str(cle_report)[:80]
            change = True
        e["vu"] = int(time.time())
    # On ecrit meme sans changement de nom : « vu » sert a reperer un lien
    # disparu du report, qu'on ne veut pas proposer indefiniment.
    _ecrire(d)


def liste(cle_report: str = "") -> List[dict]:
    """Ce que le panneau affiche : [{id, nom, depuis, vu}] trie par nom.

    Le tri reprend la MEME cle que le report — « VA 10 » apres « VA 2 » — pour
    qu'on retrouve une ligne au meme endroit dans les deux ecrans.
    """
    d = charger()
    try:
        from cogs.clickrecap import _cle_tri
    except Exception:
        def _cle_tri(n):
            return (str(n or "").lower(),)
    out = []
    for lid, e in (d.get("liens") or {}).items():
        if cle_report and e.get("cle") and e.get("cle") != cle_report:
            continue
        out.append({"id": lid, "nom": e.get("nom") or lid,
                    "depuis": d["depuis"].get(lid, ""), "vu": e.get("vu") or 0})
    out.sort(key=lambda r: _cle_tri(r["nom"]))
    return out


def couper(plage, depuis: str):
    """Coupe une periode a la date d'arrivee.

    Rend la plage telle quelle, une plage raccourcie, ou None quand la
    periode est ENTIEREMENT anterieure a l'arrivee — et ce None-la veut dire
    « pas a lui », pas « pas lu ». Les deux se ressemblent a l'ecran ; les
    confondre etait tout le probleme.

    Rend TOUJOURS des chaines « YYYY-MM-DD », que l'appelant passe des dates
    ou des chaines : melanger les deux donnait une plage dont une borne avait
    `.isoformat()` et l'autre non.
    """
    if not plage:
        return None
    debut, fin = str(plage[0])[:10], str(plage[1])[:10]
    if not depuis:
        return (debut, fin)
    if fin < depuis:
        return None
    if debut < depuis:
        return (depuis, fin)
    return (debut, fin)
