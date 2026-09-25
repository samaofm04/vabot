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

UNE TROISIEME NATURE : LA RESERVE (25/09/2026)

  - une RESERVE : du contenu PARTAGE par plusieurs modeles (ex. « Blonde » :
    PP, bios, stories, story CTA, posts, captions, templates, flash). Jamais
    de video brute. Comme une identite, elle n'est pas une modele (ni
    Jailbreak, ni scrape, ni rotation des VA) ; a la difference d'une
    identite, son MARCHE compte (bios FR ou US) et elle alimente le menu
    « ✨ General » des modeles qui y sont liees.

Elle a son propre nom, et pas « identite generale », a la demande du
proprietaire : les deux doivent se distinguer d'un coup d'oeil.
"""
from __future__ import annotations

from pathlib import Path

import safe_json

FICHIER = Path("data") / "identity_type.json"

MODELE = "modele"
IDENTITE = "identite"
RESERVE = "reserve"
#: Les seules valeurs que le fichier peut porter.
NATURES = (MODELE, IDENTITE, RESERVE)

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
    """« modele », « identite » ou « reserve ». Jamais autre chose."""
    idl = (identity or "").strip().lower()
    if not idl:
        return IDENTITE
    if idl in TOUJOURS_MODELE:
        return MODELE
    if idl.startswith(_PREFIXE_V2):
        return IDENTITE
    v = _table().get(idl)
    if v in NATURES:
        return v
    return MODELE


def est_modele(identity: str) -> bool:
    return de(identity) == MODELE


def est_reserve(identity: str) -> bool:
    return de(identity) == RESERVE


def choisi(identity: str) -> bool:
    """Le proprietaire a-t-il tranche pour celle-ci, ou est-ce encore le repli ?

    Sert a l'ecran : on ne presente pas une valeur devinee comme un choix.
    """
    return _table().get((identity or "").strip().lower()) in NATURES


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
    v = str(valeur).strip().lower()
    d[idl] = v if v in NATURES else IDENTITE
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


def filtrer_reserves(identites) -> list:
    """Ne garde que les reserves, dans l'ordre recu."""
    return [i for i in (identites or []) if est_reserve(i)]


def sans_reserves(identites) -> list:
    """Tout SAUF les reserves, dans l'ordre recu.

    C'est le filtre des listes « a qui peut-on assigner un VA » : on filtre
    sur est_reserve et JAMAIS sur est_modele. Le 12/09/2026, un filtre sur la
    nature a vide quinze des vingt-deux entrees du menu Jailbreak : une
    « identite » doit rester dans les menus, une reserve jamais.
    """
    return [i for i in (identites or []) if not est_reserve(i)]


# ============ Liens model -> reserves (menu « ✨ General ») ============
#
# {model: [reserve, ...]} en minuscules. Un fichier a part : identity_type.json
# convertit chaque valeur en chaine, une liste y serait detruite. Le site
# ecrit, le bot lit — relu quand le fichier bouge, comme la nature.

FICHIER_LIENS = Path("data") / "identity_reserves.json"
_DOSSIER = Path("data") / "identities"
_CACHE_LIENS: dict = {"sig": None, "data": {}}


def _liens() -> dict:
    try:
        sig = FICHIER_LIENS.stat().st_mtime_ns
    except OSError:
        _CACHE_LIENS.update(sig=None, data={})
        return {}
    if _CACHE_LIENS["sig"] != sig:
        d = safe_json.load(FICHIER_LIENS, default={}) or {}
        out = {}
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, (list, tuple)):
                    out[str(k).strip().lower()] = [str(x).strip().lower() for x in v if str(x).strip()]
        _CACHE_LIENS.update(sig=sig, data=out)
    return _CACHE_LIENS["data"]


def liens_bruts() -> dict:
    """{model: [reserves]} tel qu'ecrit, SANS refiltrage (pour l'ecran)."""
    return {k: list(v) for k, v in _liens().items()}


def _marche(nom: str) -> str:
    try:
        import marche                      # paresseux : pas de cycle
        return marche.de(nom)
    except Exception:
        return ""


def _raison_invalide(modele: str, reserve: str) -> str:
    """« » si `reserve` peut servir `modele`, sinon la raison, en clair."""
    if not (_DOSSIER / reserve).is_dir():
        return "dossier absent"
    if not est_reserve(reserve):
        return "n'est plus une réserve"
    mm, mr = _marche(modele), _marche(reserve)
    if mm and mr and mm != mr:
        return f"marché {mr.upper()} (la model est {mm.upper()})"
    return ""


def reserves_liees(modele: str) -> tuple:
    """(retenues, ecartees) pour une model.

    Le lien est REFILTRE A LA LECTURE : le marche d'une model ou d'une
    reserve peut changer apres la pose du lien, une reserve peut repasser en
    identite ou disparaitre. `ecartees` = [(nom, raison)] : rien n'est ecarte
    en silence, l'ecran et Discord le disent.
    """
    idl = (modele or "").strip().lower()
    retenues, ecartees = [], []
    for r in _liens().get(idl, []):
        raison = _raison_invalide(idl, r)
        if raison:
            ecartees.append((r, raison))
        elif r not in retenues:
            retenues.append(r)
    return retenues, ecartees


def models_liees(reserve: str) -> list:
    """Les models qui pointent vers cette reserve (lien brut, pour l'ecran)."""
    r = (reserve or "").strip().lower()
    return sorted(m for m, rs in _liens().items() if r in rs)


def lier(modele: str, reserves) -> tuple:
    """Pose la liste COMPLETE des reserves d'une model -> (ok, refus).

    Refuse TOUT si une cible n'est pas valable (nommee, avec sa raison), ou si
    la model est elle-meme une reserve. Une liste vide delie.
    """
    idl = (modele or "").strip().lower()
    if not idl:
        return False, ["nom vide"]
    if est_reserve(idl):
        return False, [f"{idl} est elle-même une réserve"]
    voulues = []
    for r in reserves or []:
        r = str(r).strip().lower()
        if r and r not in voulues:
            voulues.append(r)
    refus = []
    for r in voulues:
        if r == idl:
            refus.append(f"{r} : une model ne se lie pas à elle-même")
            continue
        raison = _raison_invalide(idl, r)
        if raison:
            refus.append(f"{r} : {raison}")
    if refus:
        return False, refus
    d = dict(_liens())
    if voulues:
        d[idl] = voulues
    else:
        d.pop(idl, None)
    FICHIER_LIENS.parent.mkdir(parents=True, exist_ok=True)
    # safe_json.write avale l'exception et rend False : sans ce test, un
    # disque plein repondait « ok » et la case cochee n'etait nulle part.
    if not safe_json.write(FICHIER_LIENS, d):
        return False, ["écriture impossible (identity_reserves.json)"]
    _CACHE_LIENS.update(sig=None, data={})
    return True, []


def refus_assignation(nom: str) -> str:
    """« » si `nom` peut etre assigne a un VA, sinon LA phrase de refus —
    la meme, mot pour mot, sur Discord et sur le site."""
    idl = (nom or "").strip().lower()
    if idl and est_reserve(idl):
        return (f"`{idl}` est une réserve (contenu partagé) : "
                "elle ne s'assigne pas à un VA.")
    return ""

