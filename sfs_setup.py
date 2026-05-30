"""sfs_setup.py - Infos SFS par identite et par plateforme (MYM/OF).

Stockage : data/sfs_setup.json
Structure :
{
    "platforms": {
        "mym": {
            "identities": {
                "amelia": {
                    "niche": "CAISSE",
                    "abonnement": "free",
                    "abonnes": "BCP",
                    "anciens": "BCP",
                    "interesses": "BCP",
                    "emoji": "👱🏻‍♀️",
                    "enabled": true
                }
            }
        },
        "of": {
            "identities": {...}
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

DEFAULT_EMOJIS = [
    "\U0001F471\U0001F3FB‍♀️",
    "\U0001F469\U0001F3FB‍\U0001F9B1",
    "\U0001F469\U0001F3FD‍\U0001F9B0",
    "\U0001F471\U0001F3FC‍♀️",
    "\U0001F469\U0001F3FE",
    "\U0001F469\U0001F3FC‍\U0001F9B3",
]

FIELDS = ["niche", "abonnement", "abonnes", "anciens", "interesses"]
FIELD_LABELS = {
    "niche": "Niche",
    "abonnement": "Abonnement",
    "abonnes": "Abonnes",
    "anciens": "Anciens abonnes",
    "interesses": "Interesses",
}
PLATFORMS = ("mym", "of")
DEFAULT_ABONNEMENT = "free"


def _load() -> Dict[str, Any]:
    if not SETUP_FILE.exists():
        return {"platforms": {p: {"identities": {}} for p in PLATFORMS}}
    try:
        data = json.loads(SETUP_FILE.read_text(encoding="utf-8"))
        # Migration depuis l'ancien format (sans plateformes)
        if "identities" in data and "platforms" not in data:
            data = {"platforms": {
                "mym": {"identities": data["identities"]},
                "of": {"identities": {}},
            }}
        if "platforms" not in data:
            data["platforms"] = {}
        for p in PLATFORMS:
            if p not in data["platforms"]:
                data["platforms"][p] = {"identities": {}}
            if "identities" not in data["platforms"][p]:
                data["platforms"][p]["identities"] = {}
        return data
    except Exception:
        return {"platforms": {p: {"identities": {}} for p in PLATFORMS}}


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETUP_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_identity(platform: str, identity: str) -> Dict[str, Any]:
    """Retourne les infos pour une identite sur une plateforme."""
    if platform not in PLATFORMS:
        platform = "mym"
    data = _load()
    key = (identity or "").lower().strip()
    info = data.get("platforms", {}).get(platform, {}).get("identities", {}).get(key, {})
    out: Dict[str, Any] = {}
    for f in FIELDS:
        out[f] = info.get(f, "")
    # Defaut abonnement = "free"
    if not out["abonnement"] and not info:
        out["abonnement"] = DEFAULT_ABONNEMENT
    out["emoji"] = info.get("emoji", "")
    out["enabled"] = info.get("enabled", True)
    return out


def save_identity(platform: str, identity: str, fields: Dict[str, str],
                  emoji: str = "", enabled: bool = True):
    """Sauvegarde les infos pour une identite sur une plateforme."""
    if platform not in PLATFORMS:
        platform = "mym"
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
    data["platforms"][platform]["identities"][key] = info
    _save(data)


def all_info(platform: str) -> Dict[str, Dict[str, Any]]:
    if platform not in PLATFORMS:
        platform = "mym"
    return _load().get("platforms", {}).get(platform, {}).get("identities", {})


def generate_message(platform: str, identities_ordered: List[str]) -> str:
    """Genere le message a copier-coller pour les identites donnees."""
    data = all_info(platform)
    lines: List[str] = []
    idx_actif = 0
    for ident in identities_ordered:
        key = ident.lower().strip()
        info = data.get(key, {})
        if not info or not info.get("enabled", True):
            continue
        idx_actif += 1
        emoji = info.get("emoji") or DEFAULT_EMOJIS[(idx_actif - 1) % len(DEFAULT_EMOJIS)]
        lines.append(f"{emoji} MODELE {idx_actif} :")
        for f in FIELDS:
            label = FIELD_LABELS[f]
            val = (info.get(f) or "").strip()
            if not val:
                val = DEFAULT_ABONNEMENT if f == "abonnement" else "-"
            lines.append(f"-> {label} : {val}")
        lines.append("")
    return "\n".join(lines).rstrip()


def fetch_mypuls_subscribers() -> Dict[str, Dict[str, str]]:
    """Tente de fetch les counts d'abonnes depuis MyPuls pour chaque createur.

    Retourne {identity: {"abonnes": "N", "anciens": "M", "interesses": "K"}}
    ou un dict vide si MyPuls n'est pas configure ou si pas de mapping.
    """
    out: Dict[str, Dict[str, str]] = {}
    try:
        import mypuls
        if not mypuls.is_configured():
            return out
        # mypuls.list_creators() retourne {nom_creator: id}
        res = mypuls.list_creators()
        if not res.get("ok"):
            return out
        # Pour chaque createur, on essaie de parser sa page profil
        # NB: MyPuls n'expose pas directement les counts d'abonnes via API
        # Cette fonction est un placeholder pour une future implementation
        # via parsing de la page /creator/<id>
        # Pour l'instant on retourne juste les noms detectes
        creators_map = res.get("creators", {})
        for name in creators_map:
            out[name.lower().strip()] = {}
    except Exception:
        pass
    return out
