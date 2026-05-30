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

# Champs par plateforme - chaque plateforme a sa propre structure
PLATFORM_FIELDS: Dict[str, List[str]] = {
    "mym": ["niche", "age", "abonnement", "abonnes", "anciens", "interesses"],
    "of":  ["abonnement", "last_30d"],
}
# Liste union pour la persistance / compat
FIELDS = ["niche", "age", "abonnement", "abonnes", "anciens", "interesses", "last_30d"]
FIELD_LABELS = {
    "niche": "Niche",
    "age": "Âge",
    "abonnement": "Abonnement",
    "abonnes": "Abonnes",
    "anciens": "Anciens abonnes",
    "interesses": "Interesses",
    "last_30d": "Last 30 days",
}
PLATFORMS = ("mym", "of")
DEFAULT_ABONNEMENT = "free"
# Champs eligibles au bulk-apply (Appliquer a TOUS) par plateforme
PLATFORM_BULK_FIELDS: Dict[str, tuple] = {
    "mym": ("niche", "age", "abonnement"),
    "of":  ("abonnement", "last_30d"),
}
# Compat (pointe sur mym par defaut)
BULK_FIELDS = PLATFORM_BULK_FIELDS["mym"]


def fields_for(platform: str) -> List[str]:
    """Liste des champs visibles/utilises pour une plateforme."""
    return PLATFORM_FIELDS.get(platform, PLATFORM_FIELDS["mym"])


def bulk_fields_for(platform: str) -> tuple:
    """Liste des champs eligibles au bulk-apply pour une plateforme."""
    return PLATFORM_BULK_FIELDS.get(platform, PLATFORM_BULK_FIELDS["mym"])


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
    """Retourne les infos pour une identite sur une plateforme.

    Ne renvoie QUE les champs valides pour la plateforme (ex: pas de niche pour OF).
    """
    if platform not in PLATFORMS:
        platform = "mym"
    data = _load()
    key = (identity or "").lower().strip()
    info = data.get("platforms", {}).get(platform, {}).get("identities", {}).get(key, {})
    out: Dict[str, Any] = {}
    for f in fields_for(platform):
        out[f] = info.get(f, "")
    # Defaut abonnement = "free" si l identite n existe pas encore
    if "abonnement" in out and not out["abonnement"] and not info:
        out["abonnement"] = DEFAULT_ABONNEMENT
    out["emoji"] = info.get("emoji", "")
    out["enabled"] = info.get("enabled", True)
    return out


def save_identity(platform: str, identity: str, fields: Dict[str, str],
                  emoji: str = "", enabled: bool = True):
    """Sauvegarde les infos pour une identite sur une plateforme.

    Ne sauvegarde QUE les champs valides pour la plateforme.
    Preserve emoji/enabled existants si non fournis.
    """
    if platform not in PLATFORMS:
        platform = "mym"
    key = (identity or "").lower().strip()
    if not key:
        return
    data = _load()
    existing = data["platforms"][platform]["identities"].get(key, {})
    info: Dict[str, Any] = {}
    # On garde uniquement les champs pertinents pour cette plateforme
    for f in fields_for(platform):
        if f in fields:
            info[f] = (fields.get(f) or "").strip()
        else:
            # Conserve la valeur deja stockee si non fournie
            info[f] = existing.get(f, "")
    if emoji:
        info["emoji"] = emoji.strip()
    elif existing.get("emoji"):
        info["emoji"] = existing["emoji"]
    info["enabled"] = bool(enabled)
    data["platforms"][platform]["identities"][key] = info
    _save(data)


def all_info(platform: str) -> Dict[str, Dict[str, Any]]:
    if platform not in PLATFORMS:
        platform = "mym"
    return _load().get("platforms", {}).get(platform, {}).get("identities", {})


def generate_message(platform: str, identities_ordered: List[str]) -> str:
    """Genere le message a copier-coller pour les identites donnees.

    Ne sort QUE les champs de la plateforme (ex: pas de niche pour OF).
    Skip les champs vides (mais "abonnement" tombe sur 'free' par defaut).
    """
    data = all_info(platform)
    lines: List[str] = []
    idx_actif = 0
    plat_fields = fields_for(platform)
    for ident in identities_ordered:
        key = ident.lower().strip()
        info = data.get(key, {})
        if not info or not info.get("enabled", True):
            continue
        idx_actif += 1
        emoji = info.get("emoji") or DEFAULT_EMOJIS[(idx_actif - 1) % len(DEFAULT_EMOJIS)]
        lines.append(f"{emoji} MODELE {idx_actif} :")
        for f in plat_fields:
            label = FIELD_LABELS.get(f, f)
            val = (info.get(f) or "").strip()
            if not val:
                if f == "abonnement":
                    val = DEFAULT_ABONNEMENT
                else:
                    # Champ vide : on skip carrement la ligne
                    continue
            lines.append(f"-> {label} : {val}")
        lines.append("")
    return "\n".join(lines).rstrip()


def fetch_mypuls_subscribers() -> Dict[str, Dict[str, str]]:
    """Fetch les counts d'abonnes / anciens / interesses depuis MyPuls.

    Pour chaque createur, switche le contexte puis appelle les endpoints
    DataTables qui renvoient {recordsTotal: N}.

    Endpoints utilises (reverse-engineered) :
    - GET /switch-creator/<id>?from=app_fans  (bascule le contexte)
    - GET /fans/data?old=0  -> abonnes actuels
    - GET /fans/data?old=1  -> anciens abonnes
    - GET /fans/new/data    -> interesses

    Retourne {identity_lowercase: {"abonnes": "N", "anciens": "M", "interesses": "K"}}
    """
    out: Dict[str, Dict[str, str]] = {}
    try:
        import mypuls
    except Exception:
        return out
    if not mypuls.is_configured():
        return out
    res = mypuls.list_creators()
    if not res.get("ok"):
        return out
    creators_map = res.get("creators", {})
    s = mypuls._make_session()
    if s is None:
        return out
    headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}

    def _count(path: str) -> str:
        try:
            r = s.get(f"{mypuls.BASE_URL}{path}", timeout=20, headers=headers)
            if r.status_code != 200:
                return ""
            j = r.json()
            tot = j.get("recordsTotal")
            if isinstance(tot, int):
                return str(tot)
        except Exception:
            return ""
        return ""

    for name, cid in creators_map.items():
        try:
            # Switch context vers ce createur
            s.get(
                f"{mypuls.BASE_URL}/switch-creator/{int(cid)}?from=app_fans",
                timeout=15,
                allow_redirects=True,
            )
            # Get les 3 counts
            abonnes = _count("/fans/data?old=0")
            anciens = _count("/fans/data?old=1")
            interesses = _count("/fans/new/data")
            out[name.lower().strip()] = {
                "abonnes": abonnes,
                "anciens": anciens,
                "interesses": interesses,
            }
        except Exception:
            continue
    return out
