# -*- coding: utf-8 -*-
"""Une identite EN PAUSE : gardee, mais plus servie nulle part sur Discord.

POURQUOI CE FICHIER EXISTE

Le proprietaire, le 26/09/2026 : « c'est possible de disable une identite,
la mettre en pause pour plus l'avoir et tout sur le Discord, [...] la griser
dans la bibliotheque ». Retirer (la corbeille) sort le dossier ; la pause, elle,
laisse tout en place et se defait d'un clic.

POURQUOI PAS « enabled: false »

identities_config.json porte deja un drapeau `enabled`, mais il ne veut pas
dire pause : il ne retire l'identite que de la ROTATION des nouveaux VA (les
VA deja dessus continuent d'etre servis), et le site le pose de lui-meme sur
chaque dossier importe d'un TikTok/Instagram. S'en servir aurait grise tous
ces dossiers d'un coup. La pause est donc une cle a part, dans le MEME
fichier : identite_admin le suit deja au renommage et au retrait.

    {"<identite>": {"enabled": ..., "pause": true, "pause_le": 1790000000}}

Le site ecrit, le bot lit : deux processus. La table est relue quand la date
du fichier bouge, jamais gardee en memoire au-dela.
"""
from __future__ import annotations

import time
from pathlib import Path

import safe_json

FICHIER = Path(__file__).resolve().parent / "data" / "identities_config.json"

_CACHE: dict = {"sig": None, "pauses": frozenset()}


def _pauses() -> frozenset:
    try:
        sig = FICHIER.stat().st_mtime_ns
    except OSError:
        _CACHE.update(sig=None, pauses=frozenset())
        return _CACHE["pauses"]
    if _CACHE["sig"] != sig:
        d = safe_json.load(FICHIER, default={}) or {}
        p = frozenset(str(k).strip().lower() for k, v in (d.items() if isinstance(d, dict) else [])
                      if isinstance(v, dict) and v.get("pause"))
        _CACHE.update(sig=sig, pauses=p)
    return _CACHE["pauses"]


def en_pause(nom: str) -> bool:
    return bool(nom) and str(nom).strip().lower() in _pauses()


def pauses() -> frozenset:
    """Toutes les identites en pause."""
    return _pauses()


def sans_pauses(noms) -> list:
    p = _pauses()
    return [n for n in (noms or []) if str(n).strip().lower() not in p]


def refus(nom: str) -> str:
    """« » si `nom` n'est pas en pause, sinon LA phrase de refus, la meme
    partout (Discord et site)."""
    if en_pause(nom):
        return (f"⏸ @{str(nom).strip().lower()} est en pause : son contenu n'est "
                "plus servi. Elle se réactive dans le Vault (Modifier → Réactiver).")
    return ""


def definir(nom: str, pause: bool) -> bool:
    """Pose ou retire la pause. Vrai si le fichier a bien ete ecrit.
    Les autres cles de l'identite (enabled...) ne sont pas touchees."""
    n = str(nom or "").strip().lower()
    if not n:
        return False
    d = safe_json.load(FICHIER, default={}) or {}
    d = d if isinstance(d, dict) else {}
    e = d.get(n) if isinstance(d.get(n), dict) else {}
    if pause:
        e["pause"] = True
        e["pause_le"] = int(time.time())
    else:
        e.pop("pause", None)
        e.pop("pause_le", None)
    if e:
        d[n] = e
    else:
        d.pop(n, None)
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    ok = bool(safe_json.write(FICHIER, d, indent=2))
    _CACHE.update(sig=None)
    return ok
