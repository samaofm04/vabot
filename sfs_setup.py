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
# OF : que SUB Total + Last 30 Day (pas d abonnement, pas de niche, pas d age)
PLATFORM_FIELDS: Dict[str, List[str]] = {
    "mym": ["niche", "age", "abonnement", "abonnes", "anciens", "interesses"],
    "of":  ["sub_total", "last_30d"],
}
# Liste union pour la persistance / compat
FIELDS = ["niche", "age", "abonnement", "abonnes", "anciens", "interesses", "sub_total", "last_30d"]
FIELD_LABELS = {
    "niche": "Niche",
    "age": "Âge",
    "abonnement": "Abonnement",
    "abonnes": "Abonnes",
    "anciens": "Anciens abonnes",
    "interesses": "Interesses",
    "sub_total": "SUB Total",
    "last_30d": "Last 30 Day",
}
PLATFORMS = ("mym", "of")
DEFAULT_ABONNEMENT = "free"
# Champs eligibles au bulk-apply (Appliquer a TOUS) par plateforme
PLATFORM_BULK_FIELDS: Dict[str, tuple] = {
    "mym": ("niche", "age", "abonnement"),
    "of":  ("sub_total", "last_30d"),
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
    Pas d emoji sur la ligne MODELE - juste "MODELE N :".
    """
    data = all_info(platform)
    lines: List[str] = []
    idx_actif = 0
    plat_fields = fields_for(platform)
    has_any_field = False

    # Tri par ABONNÉS décroissant (les plus gros comptes en premier dans le
    # message), quel que soit l'ordre reçu. Alpha en secours.
    import re as _re

    def _ab(ident):
        v = str((data.get(ident.lower().strip(), {}) or {}).get("abonnes") or "").strip().lower()
        m = _re.search(r"([\d\s.,]+)\s*(k|m)?", v)
        if not m:
            return -1.0
        try:
            n = float(m.group(1).replace(" ", "").replace(",", "."))
        except Exception:
            return -1.0
        return n * (1000 if m.group(2) == "k" else 1_000_000 if m.group(2) == "m" else 1)

    identities_ordered = sorted(identities_ordered, key=lambda x: (-_ab(x), x.lower()))

    for ident in identities_ordered:
        key = ident.lower().strip()
        info = data.get(key, {})
        if not info or not info.get("enabled", True):
            continue
        # Skip les identites qui n ont AUCUN champ rempli (sauf abonnement default)
        any_filled = any((info.get(f) or "").strip() for f in plat_fields)
        if not any_filled:
            continue
        idx_actif += 1
        lines.append(f"MODELE {idx_actif} :")
        for f in plat_fields:
            label = FIELD_LABELS.get(f, f)
            val = (info.get(f) or "").strip()
            if not val:
                if f == "abonnement":
                    val = DEFAULT_ABONNEMENT
                else:
                    continue
            lines.append(f"-> {label} : {val}")
            has_any_field = True
        lines.append("")
    body = "\n".join(lines).rstrip()
    if not body:
        return ""
    # Mention "SFS DISPO <PLATEFORME>" en tete (avant tout), suivie d un saut de ligne
    tag = "OF" if platform == "of" else "MYM"
    return f"SFS DISPO {tag}\n\n" + body


# Cache TTL pour l auto-fetch MyPuls (en secondes)
_MYPULS_CACHE_TTL = 300  # 5 min
_mypuls_last_autofetch = {"ts": 0.0}


def autofill_mypuls_if_stale(force: bool = False) -> int:
    """Lance fetch_mypuls_subscribers() si le cache est plus vieux que TTL,
    et applique les counts a chaque identite MyM stockee, en preservant les
    autres champs (niche, age, abonnement deja saisis manuellement).

    Retourne le nombre d'identites mises a jour.
    """
    import time
    now = time.time()
    if not force and (now - _mypuls_last_autofetch["ts"]) < _MYPULS_CACHE_TTL:
        return 0
    try:
        data = fetch_mypuls_subscribers()
    except Exception:
        return 0
    if not data:
        return 0
    applied = 0
    for ident, counts in data.items():
        if not counts:
            continue
        # Charge les champs actuels (niche/age/abonnement preserves)
        current = get_identity("mym", ident)
        updated = {f: current.get(f, "") for f in fields_for("mym")}
        if counts.get("abonnes"):
            updated["abonnes"] = counts["abonnes"]
        if counts.get("anciens"):
            updated["anciens"] = counts["anciens"]
        if counts.get("interesses"):
            updated["interesses"] = counts["interesses"]
        save_identity(
            "mym", ident, updated,
            emoji=current.get("emoji", ""),
            enabled=current.get("enabled", True),
        )
        applied += 1
    _mypuls_last_autofetch["ts"] = now
    return applied


def fetch_mypuls_subscribers() -> Dict[str, Dict[str, str]]:
    """Fetch les counts d'abonnes / anciens / interesses depuis MyPuls.

    Approche : GET /creators retourne UNE page server-rendered qui contient
    les cards de TOUS les createurs avec les 3 stats deja calculees (les
    memes que celles affichees dans le widget agence). Beaucoup plus rapide
    qu un appel par createur, et donne les vraies valeurs (les endpoints
    DataTables /fans/data?old=1 comptent TOUS les anciens jamais inscrits,
    alors que le widget affiche un nombre filtre - actifs recuperables).

    Pattern HTML par card :
      <h5 class="...fw-bold">NomCreator</h5>
      ...
      <div class="stat-val">N</div><div class="stat-lbl">Abonnes</div>
      <div class="stat-val">M</div><div class="stat-lbl">Anciens</div>
      <div class="stat-val">K</div><div class="stat-lbl">Interesses</div>

    Retourne {identity_lowercase: {"abonnes": "N", "anciens": "M", "interesses": "K"}}
    """
    import re as _re
    out: Dict[str, Dict[str, str]] = {}
    try:
        import mypuls
    except Exception:
        return out
    if not mypuls.is_configured():
        return out
    s = mypuls._make_session()
    if s is None:
        return out
    try:
        r = s.get(f"{mypuls.BASE_URL}/creators", timeout=20)
        if r.status_code != 200:
            return out
    except Exception:
        return out

    # Parse CARTE PAR CARTE (split sur creator-card) et stats indépendantes.
    # L'ancienne regex exigeait les 3 stats dans l'ordre au sein d'un .*? DOTALL
    # global : une carte sans stats faisait DÉBORDER le match sur la carte
    # suivante -> la créatrice héritait des chiffres de sa voisine, et la
    # voisine disparaissait (c'est pour ça qu'il manquait des créatrices par
    # paires : amelia_xoxo, klarahockey...).
    chunks = _re.split(r'<div\s+class="creator-card', r.text)
    for chunk in chunks[1:]:
        nm = _re.search(r'<h5\s+class="[^"]*fw-bold[^"]*">([^<]+)</h5>', chunk)
        if not nm:
            continue
        name = nm.group(1).strip()
        if not name:
            continue
        vals: Dict[str, str] = {}
        for m2 in _re.finditer(
                r'<div\s+class="stat-val">\s*([^<]*?)\s*</div>\s*'
                r'<div\s+class="stat-lbl">\s*([^<]+?)\s*</div>', chunk):
            v = _re.sub(r'[\s., \xa0]', '', m2.group(1))
            if not v.isdigit():
                continue                     # '—', vide, 'N/A'... -> stat absente
            lbl = m2.group(2).lower()
            if "ancien" in lbl:              # 'Anciens' / 'Anciens abonnés'
                vals["anciens"] = v
            elif "abonn" in lbl:
                vals["abonnes"] = v
            elif "inter" in lbl or "intér" in lbl:
                vals["interesses"] = v
        if vals:                             # partiel accepté (autofill ne pose
            out[name.lower().strip()] = vals  # que les clés présentes)
    return out
