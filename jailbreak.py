"""jailbreak.py - Gestion des comptes Jailbreak par identite.

Pattern : par identite (amelia, julia, lola, ...) on stocke :
- Une liste de VAs (assistante virtuelle) responsables
- Une liste de comptes, chacun pouvant etre rattache a un VA

Nouveau schema (v2) :
{
    "amelia": {
        "vas": ["Marie", "Paul"],
        "accounts": [
            {"id": ..., "username": "amelia_main", "va": "Marie", ...}
        ]
    }
}

Ancien schema (v1, retrocompat lue automatiquement) :
{
    "amelia": [{"id": ..., "username": "...", "va": "Marie"}, ...]
}
-> Migre auto au premier _save : 'vas' est l union des va presents
   sur les accounts (preserve l ordre d apparition).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Any

DATA_DIR = Path("data")
JAILBREAK_FILE = DATA_DIR / "jailbreak.json"


def _migrate_identity_entry(entry: Any) -> Dict[str, Any]:
    """Normalise une entree d identite vers le format v2.
    - list -> {vas: [union des va], accounts: list}
    - dict avec 'accounts' -> garde tel quel (assure vas existe)
    - autre -> {vas: [], accounts: []}
    """
    if isinstance(entry, dict) and "accounts" in entry:
        # Deja v2 - juste s assurer que vas existe et est une list
        out = dict(entry)
        if not isinstance(out.get("vas"), list):
            out["vas"] = []
        if not isinstance(out.get("accounts"), list):
            out["accounts"] = []
        return out
    if isinstance(entry, list):
        # v1 -> v2
        vas: List[str] = []
        for a in entry:
            if isinstance(a, dict):
                va = (a.get("va") or "").strip()
                if va and va not in vas:
                    vas.append(va)
        return {"vas": vas, "accounts": list(entry)}
    return {"vas": [], "accounts": []}


def _load() -> Dict[str, Dict[str, Any]]:
    """Charge et NORMALISE tout vers le format v2."""
    if not JAILBREAK_FILE.exists():
        return {}
    try:
        raw = json.loads(JAILBREAK_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in raw.items():
            out[k] = _migrate_identity_entry(v)
        return out
    except Exception:
        return {}


def _save(data: Dict[str, Dict[str, Any]]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JAILBREAK_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _ensure_identity(data: Dict[str, Dict[str, Any]], identity: str) -> Dict[str, Any]:
    """Get-or-create l entree d une identite dans data, avec defaults v2."""
    if identity not in data or not isinstance(data[identity], dict):
        data[identity] = {"vas": [], "accounts": []}
    if not isinstance(data[identity].get("vas"), list):
        data[identity]["vas"] = []
    if not isinstance(data[identity].get("accounts"), list):
        data[identity]["accounts"] = []
    return data[identity]


# ============ Accounts ============

def list_accounts(identity: str) -> List[Dict[str, Any]]:
    """Liste les comptes d une identite (vide si aucun)."""
    identity = (identity or "").strip().lower()
    if not identity:
        return []
    data = _load()
    entry = data.get(identity)
    if not entry:
        return []
    return list(entry.get("accounts") or [])


def list_all() -> Dict[str, Dict[str, Any]]:
    """Retourne tout le storage par identite (format v2 normalise)."""
    return _load()


def add_account(identity: str, username: str, password: str = "",
                email: str = "", notes: str = "", two_fa: str = "",
                va: str = "") -> Dict[str, Any]:
    """Ajoute un compte. Si va est fourni et n existe pas encore dans la liste
    des vas de l identite, il y est ajoute automatiquement."""
    identity = (identity or "").strip().lower()
    if not identity:
        raise ValueError("Identite vide")
    username = (username or "").strip()[:80]
    if not username:
        raise ValueError("Username vide")
    data = _load()
    entry = _ensure_identity(data, identity)
    # ID unique global (toutes identites confondues)
    used_ids = set()
    for k, v in data.items():
        for a in (v.get("accounts") or []):
            try:
                used_ids.add(int(a.get("id", 0)))
            except Exception:
                pass
    new_id = int(time.time() * 1000)
    while new_id in used_ids:
        new_id += 1
    va_clean = (va or "").strip()[:60]
    acct = {
        "id": new_id,
        "username": username,
        "password": (password or "").strip()[:200],
        "email": (email or "").strip()[:120],
        "two_fa": (two_fa or "").strip()[:500],
        "va": va_clean,
        "notes": (notes or "").strip()[:500],
        "created_at": int(time.time()),
    }
    entry["accounts"].append(acct)
    # Auto-ajout du va dans la liste si pas deja la (insensible a la casse)
    if va_clean:
        if not any(v.lower() == va_clean.lower() for v in entry["vas"]):
            entry["vas"].append(va_clean)
    _save(data)
    return acct


def update_account(identity: str, account_id: int, **fields) -> bool:
    """Met a jour les champs d un compte. Si va change, on s assure qu il
    existe dans la liste des vas de l identite."""
    identity = (identity or "").strip().lower()
    if not identity:
        return False
    data = _load()
    entry = data.get(identity)
    if not entry:
        return False
    allowed = {"username", "password", "email", "two_fa", "va", "notes"}
    found = False
    for acct in entry["accounts"]:
        if int(acct.get("id", 0)) == int(account_id):
            for k, v in fields.items():
                if k in allowed:
                    if k == "username":
                        v = str(v or "").strip()[:80]
                        if not v:
                            continue  # ne pas vider le username
                    elif k == "va":
                        v = str(v or "").strip()[:60]
                    else:
                        v = str(v or "").strip()[:500]
                    acct[k] = v
            acct["updated_at"] = int(time.time())
            # Si on a touche au va, assurer qu il existe dans la liste
            if "va" in fields:
                new_va = acct.get("va", "").strip()
                if new_va and not any(v.lower() == new_va.lower() for v in entry["vas"]):
                    entry["vas"].append(new_va)
            found = True
            break
    if found:
        _save(data)
    return found


def remove_account(identity: str, account_id: int) -> bool:
    """Supprime un compte. Le VA (s il en avait un) reste dans la liste des
    vas de l identite (l user pourra le retirer manuellement)."""
    identity = (identity or "").strip().lower()
    if not identity:
        return False
    data = _load()
    entry = data.get(identity)
    if not entry:
        return False
    n_before = len(entry["accounts"])
    entry["accounts"] = [
        a for a in entry["accounts"] if int(a.get("id", 0)) != int(account_id)
    ]
    if len(entry["accounts"]) == n_before:
        return False
    _save(data)
    return True


# ============ VAs ============

def list_vas_for_identity(identity: str) -> List[str]:
    """Liste les VAs declares pour une identite (sources explicites + comptes)."""
    identity = (identity or "").strip().lower()
    data = _load()
    entry = data.get(identity)
    if not entry:
        return []
    seen: List[str] = list(entry.get("vas") or [])
    # Ajoute aussi tout va present sur un compte mais absent de la liste
    seen_lc = {v.lower() for v in seen}
    for a in (entry.get("accounts") or []):
        va = (a.get("va") or "").strip()
        if va and va.lower() not in seen_lc:
            seen.append(va)
            seen_lc.add(va.lower())
    return seen


def add_va(identity: str, va_name: str) -> bool:
    """Ajoute un VA a une identite (sans compte). Returns True si ajoute,
    False si vide ou doublon (case-insensitive)."""
    identity = (identity or "").strip().lower()
    if not identity:
        return False
    va_name = (va_name or "").strip()[:60]
    if not va_name:
        return False
    data = _load()
    entry = _ensure_identity(data, identity)
    if any(v.lower() == va_name.lower() for v in entry["vas"]):
        return False
    entry["vas"].append(va_name)
    _save(data)
    return True


def remove_va(identity: str, va_name: str) -> bool:
    """Retire un VA de la liste. Les comptes qui y referencent gardent leur
    champ va inchange (l user peut les reassigner)."""
    identity = (identity or "").strip().lower()
    va_name = (va_name or "").strip()
    if not identity or not va_name:
        return False
    data = _load()
    entry = data.get(identity)
    if not entry:
        return False
    new_list = [v for v in entry["vas"] if v.lower() != va_name.lower()]
    if len(new_list) == len(entry["vas"]):
        return False
    entry["vas"] = new_list
    _save(data)
    return True


def rename_va(identity: str, old_name: str, new_name: str) -> bool:
    """Renomme un VA dans la liste ET dans tous les comptes qui y referencent."""
    identity = (identity or "").strip().lower()
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()[:60]
    if not identity or not old_name or not new_name or old_name == new_name:
        return False
    data = _load()
    entry = data.get(identity)
    if not entry:
        return False
    if not any(v.lower() == old_name.lower() for v in entry["vas"]):
        return False
    if any(v.lower() == new_name.lower() for v in entry["vas"]):
        return False  # conflit
    entry["vas"] = [new_name if v.lower() == old_name.lower() else v for v in entry["vas"]]
    for a in entry["accounts"]:
        if (a.get("va") or "").strip().lower() == old_name.lower():
            a["va"] = new_name
    _save(data)
    return True


# ============ Stats ============

def stats() -> Dict[str, Any]:
    """Statistiques globales pour le header."""
    data = _load()
    total_accounts = 0
    identities_with_accounts = 0
    total_vas = 0
    for v in data.values():
        accts = v.get("accounts") or []
        total_accounts += len(accts)
        if accts:
            identities_with_accounts += 1
        total_vas += len(v.get("vas") or [])
    return {
        "total_accounts": total_accounts,
        "identities_with_accounts": identities_with_accounts,
        "total_vas": total_vas,
    }


def rename_identity_in_storage(old_name: str, new_name: str) -> bool:
    """Renomme la cle d une identite (pour le rename d identite).
    Ne touche PAS au filesystem - c est au caller (route Flask) de mv le dossier."""
    old_name = (old_name or "").strip().lower()
    new_name = (new_name or "").strip().lower()
    if not old_name or not new_name or old_name == new_name:
        return False
    data = _load()
    if old_name not in data:
        return True  # rien a faire, ok
    if new_name in data:
        return False
    data[new_name] = data.pop(old_name)
    _save(data)
    return True
