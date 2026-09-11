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
