"""Marché d'une identité : 🇫🇷 FR ou 🇺🇸 US.

Source UNIQUE, importée par le site (web_upload), le bot (cogs/user) et la
synchro Drive (gdrive_sync). La règle était dupliquée dans les trois : au
premier oubli, le drapeau affiché n'aurait plus correspondu au serveur
Discord réellement servi.

  - FR  -> Discord « YouL4b Agency »
  - US  -> serveur « Youl4b » uniquement

Le choix se fait sur le site (Bibliothèque -> ✏️ Modifier -> Marché) et
atterrit dans data/identity_market.json, écrit en clair pour les deux
valeurs : ne stocker que l'exception ferait retomber un retour en FR sur le
défaut… qui est US.
"""
from __future__ import annotations

from pathlib import Path

import pathlib

import safe_json

FICHIER = Path("data") / "identity_market.json"

# Répartition historique, appliquée tant qu'aucun choix n'a été enregistré.
# Jessye en fait partie : elle n'est pas une model du menu US, elle en est la
# SOURCE (pseudo et name).
FR_DEFAUT = {"julia", "emma", "lola", "sarah", "amelia", "alicia", "jessye"}

_CACHE: dict = {"sig": None, "data": {}}


def _table() -> dict:
    """{identité: 'fr'|'us'}, relue quand le fichier bouge — le site écrit,
    le bot lit, ce sont deux processus."""
    try:
        sig = FICHIER.stat().st_mtime_ns
    except OSError:
        _CACHE.update(sig=None, data={})
        return {}
    if _CACHE["sig"] != sig:
        d = safe_json.load(FICHIER, default={}) or {}
        d = ({str(k).lower(): str(v).lower() for k, v in d.items()}
             if isinstance(d, dict) else {})
        _CACHE.update(sig=sig, data=d)
    return _CACHE["data"]


def de(identity: str) -> str:
    """« fr » ou « us ».

    LE DEFAUT EST « FR » DEPUIS LE 11/09/2026, a la demande du proprietaire.
    Il etait « us » : toute entree creee sans choix explicite partait donc sur
    le serveur americain, celui que voient les VA US, avec un drapeau qu on
    n avait pas choisi. Le marche se regle dans « Modifier », a cote de la
    nature ; tant qu il n est pas pose, l entree reste du cote francais --
    celui ou le proprietaire travaille.

    FR_DEFAUT ne sert donc plus qu a documenter la repartition historique :
    la regle rend « fr » avec ou sans elle. On la garde pour que la liste
    reste lisible, et parce qu un jour le defaut peut rechanger.
    """
    idl = (identity or "").strip().lower()
    v = _table().get(idl)
    if v in ("fr", "us"):
        return v
    return "fr"


#: Marqueur pose dans le fichier lui-meme : aucune identite ne peut porter ce
#: nom, et il voyage avec les donnees qu'il decrit -- un fichier temoin a part
#: se perd le jour d'une restauration.
_CLE_MIGRE = "__repartition_historique_figee__"


def migrer_historique(identites) -> int:
    """Fige la repartition d'AVANT le changement de defaut. Une seule fois.

    LE PROBLEME QU'ELLE REPARE. Le defaut est passe de « us » a « fr » le
    11/09/2026, pour qu'une identite nouvellement creee ne parte plus toute
    seule sur le serveur americain. Mais la regle ne s'applique pas qu'aux
    nouvelles : toutes celles qui n'avaient jamais ete reglees A LA MAIN
    dependaient du defaut, et sont passees en francais du jour au lendemain.
    Le filtre US n'affichait plus rien, et des comptes comme e30princesss
    portaient un drapeau francais qu'ils n'ont jamais eu.

    Ce qu'on ecrit ici n'est pas une devinette : c'est EXACTEMENT ce que
    l'ancienne regle rendait (`fr` si le nom est dans FR_DEFAUT, `us` sinon),
    appliquee aux identites qui existent aujourd'hui. Une fois ecrite, la
    repartition ne depend plus d'un defaut qui peut rechanger.

    Rend le nombre d'entrees figees. Zero si c'est deja fait.
    """
    d = dict(_table())
    if d.get(_CLE_MIGRE):
        return 0
    poses = 0
    for nom in (identites or []):
        idl = str(nom or "").strip().lower()
        if not idl or idl in d:
            continue                      # un choix explicite ne se touche pas
        d[idl] = "fr" if idl in FR_DEFAUT else "us"
        poses += 1
    d[_CLE_MIGRE] = "1"
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(FICHIER, d)
    _CACHE.update(sig=None, data={})
    return poses


def migrer_depuis_dossier(dossier=None) -> int:
    """Meme chose, en lisant les identites sur le disque.

    marche.py n'importe pas web_upload -- l'inverse est deja vrai, et un
    cycle d'imports casse les deux. On lit donc le dossier directement, comme
    le fait `_list_identities` de son cote.
    """
    dossier = pathlib.Path(dossier) if dossier else (pathlib.Path("data") / "identities")
    try:
        noms = sorted(p.name for p in dossier.iterdir() if p.is_dir())
    except OSError:
        return 0
    return migrer_historique(noms)


def definir(identity: str, marche: str) -> bool:
    d = dict(_table())
    d[(identity or "").strip().lower()] = "us" if str(marche).lower() == "us" else "fr"
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    ok = bool(safe_json.write(FICHIER, d, indent=2))
    _CACHE.update(sig=None, data={})          # relecture forcée au prochain appel
    return ok


def libelle(identity: str) -> str:
    """« FR » / « US » — pour les noms de dossiers Drive."""
    return de(identity).upper()
