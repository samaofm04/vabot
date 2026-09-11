# -*- coding: utf-8 -*-
"""Modele ou identite : la difference que le proprietaire fait, et pas le code.

POURQUOI CE FICHIER EXISTE

Tout ce qui vit dans data/identities etait traite pareil. Or il y a deux
choses tres differentes la-dedans :

  - une MODELE : une creatrice reelle. Elle a des VA, des comptes Instagram,
    elle gagne de l'argent, et c'est elle qu'on veut voir dans Jailbreak, dans
    le perimetre de scrape, dans les pastilles et dans la page Revenus ;

  - une IDENTITE : un dossier ouvert pour produire des videos. Aucun VA,
    aucun compte, aucun revenu.

Le site ne connaissait que « des dossiers ». Chaque identite creee pour des
videos s'ajoutait donc a la colonne Jailbreak, au perimetre de scrape, au
menu deroulant des revenus, a la rotation des VA sur Discord et au menu
Jailbreak du serveur US -- ou un vrai VA pouvait se voir attribuer un dossier
de montage. Vingt-quatre lignes la ou il en fallait deux ou trois.

LE CHOIX EST EXPLICITE, PAS DEVINE

Un nom ne dit pas ce qu'une entree est. Le reglage se pose donc a la main,
dans « Modifier », a cote du marche -- au meme endroit et de la meme facon
que FR/US, parce que c'est la meme nature de decision.

LE DEFAUT : MODELE

Choix du proprietaire, le 11/09/2026 : « de base laisse-les toutes en modele
et je selectionne ». Tant qu'il n'a pas tranche pour une entree, elle reste
donc une modele et rien ne disparait de son ecran.

Une regle de repli plus maligne avait ete ecrite d'abord -- « modele si elle
a des VA ou des comptes dans le referentiel Jailbreak » -- et elle a ete
retiree. Elle avait pourtant l'air juste, mais elle DEVINE : une creatrice
toute neuve, pas encore montee, serait passee pour un dossier de montage et
aurait disparu de Social Analytics sans que personne ait rien demande. Un
defaut qui efface est un mauvais defaut ; celui qui garde ne coute qu'une
liste trop longue, le temps qu'il fasse le tri.

Les entrees de la Bibliotheque 2 (prefixe v2_) ne sont JAMAIS des modeles :
leur propre commentaire dans web_upload.py dit qu'elles sont « invisibles de
la Bibliotheque, des menus Discord, de la rotation des VAs et du Jailbreak ».
"""
from __future__ import annotations

from pathlib import Path

import safe_json

FICHIER = Path("data") / "identity_type.json"

MODELE = "modele"
IDENTITE = "identite"

#: Prefixe technique de la Bibliotheque 2. Recopie ici plutot qu'importe :
#: web_upload importe ce module, l'inverse creerait un cycle.
_PREFIXE_V2 = "v2_"

#: CELLES QU'ON NE PEUT PAS SORTIR, MEME PAR ERREUR DE CLIC.
#:
#: Jessye n'est ni tout a fait une modele ni une identite : c'est « un truc a
#: part », dit le proprietaire — elle est la SOURCE du menu US (pseudo et
#: name), et marche.py le note deja de son cote. Elle doit rester dans les
#: comptes par identite a cent pour cent.
#:
#: Le verrou est ici, dans la fonction qui REPOND, et pas seulement dans le
#: bouton : un bouton grise se contourne depuis la console, et une regle qui
#: ne vit que dans l'ecran n'en est pas une. Pour en proteger une autre :
#: ajouter son nom (en minuscules).
TOUJOURS_MODELE = {"jessye"}

_CACHE: dict = {"sig": None, "data": {}}


def _table() -> dict:
    """{identite: 'modele'|'identite'}, relue quand le fichier bouge.

    Le site ecrit, le bot lit : ce sont deux processus, on ne peut pas garder
    la table en memoire sans surveiller la date du fichier.
    """
    try:
        sig = FICHIER.stat().st_mtime_ns
    except OSError:
        _CACHE.update(sig=None, data={})
        return {}
    if _CACHE["sig"] != sig:
        d = safe_json.load(FICHIER, default={}) or {}
        d = ({str(k).strip().lower(): str(v).strip().lower()
              for k, v in d.items()} if isinstance(d, dict) else {})
        _CACHE.update(sig=sig, data=d)
    return _CACHE["data"]


def de(identity: str) -> str:
    """« modele » ou « identite ». Jamais autre chose."""
    idl = (identity or "").strip().lower()
    if not idl:
        return IDENTITE
    if idl in TOUJOURS_MODELE:
        return MODELE
    if idl.startswith(_PREFIXE_V2):
        return IDENTITE
    v = _table().get(idl)
    if v in (MODELE, IDENTITE):
        return v
    return MODELE


def est_modele(identity: str) -> bool:
    return de(identity) == MODELE


def choisi(identity: str) -> bool:
    """Le proprietaire a-t-il tranche pour celle-ci, ou est-ce encore le repli ?

    Sert a l'ecran : on ne presente pas une valeur devinee comme un choix.
    """
    return _table().get((identity or "").strip().lower()) in (MODELE, IDENTITE)


def verrouillee(identity: str) -> bool:
    """Cette entree refuse-t-elle qu'on la sorte des modeles ?"""
    return (identity or "").strip().lower() in TOUJOURS_MODELE


def definir(identity: str, valeur: str) -> bool:
    idl = (identity or "").strip().lower()
    if not idl:
        return False
    if idl in TOUJOURS_MODELE and str(valeur).strip().lower() != MODELE:
        return False
    d = dict(_table())
    d[idl] = MODELE if str(valeur).strip().lower() == MODELE else IDENTITE
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(FICHIER, d)
    _CACHE.update(sig=None, data={})
    return True


def filtrer_modeles(identites) -> list:
    """Ne garde que les modeles, dans l'ordre recu.

    C'est le seul point de passage : les listes de l'ecran et les listes
    ECRITES (« Tout allumer » du perimetre) doivent sortir d'ici toutes les
    deux, sinon on rallume des pastilles qu'on n'affiche pas -- c'est
    exactement ce qui se passait avant.
    """
    return [i for i in (identites or []) if est_modele(i)]
