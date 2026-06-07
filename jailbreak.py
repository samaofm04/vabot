"""jailbreak.py - Gestion des comptes Jailbreak par identite.

Pattern similaire a GeeLark mais ULTRA-LIGHT :
- Pas d execution automatique, juste un stockage de comptes
- Par identite (amelia, julia, lola, ...) = liste de comptes
- L user les cree/edite/supprime lui-meme via l UI

Stockage : data/jailbreak.json
Structure :
{
    "amelia": [
        {"id": 1733122334, "username": "amelia_main", "password": "...",
         "email": "...", "notes": "...", "created_at": 1750000000}
    ],
    "julia": [...]
}
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Any

DATA_DIR = Path("data")
JAILBREAK_FILE = DATA_DIR / "jailbreak.json"


def _load() -> Dict[str, List[Dict[str, Any]]]:
    if not JAILBREAK_FILE.exists():
        return {}
    try:
        data = json.loads(JAILBREAK_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save(data: Dict[str, List[Dict[str, Any]]]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JAILBREAK_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_accounts(identity: str) -> List[Dict[str, Any]]:
    """Liste les comptes d une identite (vide si aucun)."""
    identity = (identity or "").strip().lower()
    if not identity:
        return []
    data = _load()
    accts = data.get(identity, [])
    return list(accts) if isinstance(accts, list) else []


def list_all() -> Dict[str, List[Dict[str, Any]]]:
    """Tous les comptes, par identite. Pour les pages overview."""
    return _load()


def add_account(identity: str, username: str, password: str = "",
                email: str = "", notes: str = "") -> Dict[str, Any]:
    """Ajoute un compte a une identite. Retourne le compte ajoute."""
    identity = (identity or "").strip().lower()
    if not identity:
        raise ValueError("Identite vide")
    username = (username or "").strip()[:80]
    if not username:
        raise ValueError("Username vide")
    data = _load()
    if identity not in data or not isinstance(data[identity], list):
        data[identity] = []
    # ID unique = timestamp en ms (collision improbable pour l usage)
    new_id = int(time.time() * 1000)
    acct = {
        "id": new_id,
        "username": username,
        "password": (password or "").strip()[:200],
        "email": (email or "").strip()[:120],
        "notes": (notes or "").strip()[:500],
        "created_at": int(time.time()),
    }
    data[identity].append(acct)
    _save(data)
    return acct


def update_account(identity: str, account_id: int, **fields) -> bool:
    """Met a jour les champs d un compte (username/password/email/notes).
    Retourne True si trouve + mis a jour."""
    identity = (identity or "").strip().lower()
    if not identity:
        return False
    data = _load()
    if identity not in data:
        return False
    allowed = {"username", "password", "email", "notes"}
    found = False
    for acct in data[identity]:
        if int(acct.get("id", 0)) == int(account_id):
            for k, v in fields.items():
                if k in allowed:
                    if k == "username":
                        v = str(v or "").strip()[:80]
                        if not v: continue  # ne pas vider le username
                    else:
                        v = str(v or "").strip()[:500]
                    acct[k] = v
            acct["updated_at"] = int(time.time())
            found = True
            break
    if found:
        _save(data)
    return found


def remove_account(identity: str, account_id: int) -> bool:
    """Supprime un compte. Retourne True si trouve + supprime."""
    identity = (identity or "").strip().lower()
    if not identity:
        return False
    data = _load()
    if identity not in data:
        return False
    n_before = len(data[identity])
    data[identity] = [a for a in data[identity] if int(a.get("id", 0)) != int(account_id)]
    if len(data[identity]) == n_before:
        return False
    _save(data)
    return True


def stats() -> Dict[str, Any]:
    """Statistiques globales pour le header."""
    data = _load()
    total_accounts = sum(len(v) for v in data.values() if isinstance(v, list))
    identities_with_accounts = sum(1 for v in data.values() if isinstance(v, list) and v)
    return {
        "total_accounts": total_accounts,
        "identities_with_accounts": identities_with_accounts,
    }
