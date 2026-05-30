"""sfs_setup.py - Infos SFS par identite (Niche, Abonnement, Abonnes, ...).

Stockage : data/sfs_setup.json
Structure :
{
    "identities": {
        "amelia": {
            "niche": "CAISSE",
            "abonnement": "2 CAISSE",
            "abonnes": "BCP",
            "anciens": "BCP",
            "interesses": "BCP",
            "emoji": "👱🏻‍♀️"
        }
    }
}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List

DATA_DIR = Path("data")
SETUP_FILE = DATA_DIR / "sfs_setup.json"

# Emoji defaut pour chaque modele (rotatif)
DEFAULT_EMOJIS = [
    "\U0001F471\U0001F3FB‍♀️",  # blonde
    "\U0001F469\U0001F3FB‍\U0001F9B1",     # brune
    "\U0001F469\U0001F3FD‍\U0001F9B0",     # rousse
    "\U0001F471\U0001F3FC‍♀️",   # light blonde
    "\U0001F469\U0001F3FE",                       # medium
    "\U0001F469\U0001F3FC‍\U0001F9B3",     # white hair
]

FIELDS = ["niche", "abonnement", "abonnes", "anciens", "interesses"]
FIELD_LABELS = {
    "niche": "Niche",
    "abonnement": "Abonnement",
    "abonnes": "Abonnes",
    "anciens": "Anciens abonnes",
    "interesses": "Interesses",
}


def _load() -> Dict[str, Any]:
    if not SETUP_FILE.exists():
        return {"identities": {}}
    try:
        data = json.loads(SETUP_FILE.read_text(encoding="utf-8"))
        if "identities" not in data:
            data["identities"] = {}
        return data
    except Exception:
        return {"identities": {}}


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETUP_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_identity(identity: str) -> Dict[str, Any]:
    """Retourne les infos pour une identite (defaut vide)."""
    data = _load()
    key = (identity or "").lower().strip()
    info = data.get("identities", {}).get(key, {})
    out = {f: info.get(f, "") for f in FIELDS}
    out["emoji"] = info.get("emoji", "")
    out["enabled"] = info.get("enabled", True)
    return out


def save_identity(identity: str, fields: Dict[str, str], emoji: str = "",
                  enabled: bool = True):
    """Sauvegarde les infos pour une identite."""
    key = (identity or "").lower().strip()
    if not key:
        return
    data = _load()
    info: Dict[str, Any] = {}
    for f in FIELDS:
        info[f] = (fields.get(f) or "").strip()
    if emoji:
        info["emoji"] = emoji.strip()
    info["enabled"] = bool(enabled)
    data["identities"][key] = info
    _save(data)


def all_info() -> Dict[str, Dict[str, Any]]:
    return _load().get("identities", {})


def generate_message(identities_ordered: List[str]) -> str:
    """Genere le message a copier-coller pour les identites donnees,
    dans l'ordre fourni.

    Format :
    \U0001F471\U0001F3FB‍♀️ MODELE 1 :
    -> Niche :  CAISSE
    -> Abonnement : 2 CAISSE
    -> Abonnes : BCP
    -> Anciens abonnes : BCP
    -> Interesses : BCP

    \U0001F471\U0001F3FB‍♀️ MODELE 2 :
    ...
    """
    data = all_info()
    lines: List[str] = []
    idx_actif = 0
    for ident in identities_ordered:
        key = ident.lower().strip()
        info = data.get(key, {})
        if not info.get("enabled", True):
            continue
        idx_actif += 1
        emoji = info.get("emoji") or DEFAULT_EMOJIS[(idx_actif - 1) % len(DEFAULT_EMOJIS)]
        lines.append(f"{emoji} MODELE {idx_actif} :")
        for f in FIELDS:
            label = FIELD_LABELS[f]
            val = (info.get(f) or "").strip()
            if not val:
                val = "-"
            lines.append(f"-> {label} : {val}")
        lines.append("")  # ligne vide entre les modeles
    return "\n".join(lines).rstrip()
