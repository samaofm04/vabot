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

    Le format VAs evolue :
    - v2.0 : vas = ["Marie", "Paul"]  (string list)
    - v2.1 : vas = [{"name": "Marie", "discord_username": "marie123"}, ...]

    Cette fonction migre tous les anciens formats vers v2.1.
    """
    if isinstance(entry, dict) and "accounts" in entry:
        out = dict(entry)
        raw_vas = out.get("vas") if isinstance(out.get("vas"), list) else []
        # Normalise chaque va en {name, discord_username} (vs string)
        normalized_vas = []
        for v in raw_vas:
            if isinstance(v, dict):
                name = (v.get("name") or "").strip()
                if not name:
                    continue
                normalized_vas.append({
                    "name": name,
                    "discord_username": (v.get("discord_username") or "").strip(),
                })
            elif isinstance(v, str) and v.strip():
                normalized_vas.append({"name": v.strip(), "discord_username": ""})
        out["vas"] = normalized_vas
        if not isinstance(out.get("accounts"), list):
            out["accounts"] = []
        return out
    if isinstance(entry, list):
        # v1 -> v2 : extrait les vas depuis les comptes
        vas: List[Dict[str, str]] = []
        seen: set = set()
        for a in entry:
            if isinstance(a, dict):
                va = (a.get("va") or "").strip()
                if va and va.lower() not in seen:
                    seen.add(va.lower())
                    vas.append({"name": va, "discord_username": ""})
        return {"vas": vas, "accounts": list(entry)}
    return {"vas": [], "accounts": []}


def _va_name(va: Any) -> str:
    """Helper : extrait le nom d un VA (dict ou string)."""
    if isinstance(va, dict):
        return (va.get("name") or "").strip()
    if isinstance(va, str):
        return va.strip()
    return ""


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
                va: str = "", two_fa_validated: bool = False) -> Dict[str, Any]:
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
    two_fa_clean = (two_fa or "").strip()[:500]
    acct = {
        "id": new_id,
        "username": username,
        "password": (password or "").strip()[:200],
        "email": (email or "").strip()[:120],
        "two_fa": two_fa_clean,
        # Validated uniquement si on a un 2FA non vide ET le flag est True
        "two_fa_validated": bool(two_fa_validated) and bool(two_fa_clean),
        "va": va_clean,
        "notes": (notes or "").strip()[:500],
        "created_at": int(time.time()),
    }
    entry["accounts"].append(acct)
    # Auto-ajout du va dans la liste si pas deja la (insensible a la casse)
    if va_clean:
        if not any(_va_name(v).lower() == va_clean.lower() for v in entry["vas"]):
            entry["vas"].append({"name": va_clean, "discord_username": ""})
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
    allowed = {"username", "password", "email", "two_fa", "va", "notes", "two_fa_validated"}
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
                    elif k == "two_fa_validated":
                        # Bool field. Coerce les valeurs string ("on", "1", "true") en True.
                        if isinstance(v, str):
                            v = v.strip().lower() in ("on", "1", "true", "yes")
                        else:
                            v = bool(v)
                    else:
                        v = str(v or "").strip()[:500]
                    acct[k] = v
            # Coherence : si two_fa est vide, two_fa_validated doit etre False
            if not (acct.get("two_fa") or "").strip():
                acct["two_fa_validated"] = False
            acct["updated_at"] = int(time.time())
            # Si on a touche au va, assurer qu il existe dans la liste
            if "va" in fields:
                new_va = acct.get("va", "").strip()
                if new_va and not any(_va_name(v).lower() == new_va.lower() for v in entry["vas"]):
                    entry["vas"].append({"name": new_va, "discord_username": ""})
            found = True
            break
    if found:
        _save(data)
    return found


def bulk_add_accounts(identity: str, usernames: List[str], va: str = "") -> Dict[str, Any]:
    """Cree plusieurs comptes 'skeleton' (juste username + va) en une fois.
    L user complete plus tard les autres champs via Edit.

    Returns : {added: int, skipped_dup: int, skipped_invalid: int,
               added_usernames: [...], skipped_dups: [...]}
    Dedupe : ne re-cree pas un compte dont le username existe deja pour
    cette identite (case-insensitive)."""
    identity = (identity or "").strip().lower()
    if not identity:
        raise ValueError("Identite vide")
    if not usernames:
        return {"added": 0, "skipped_dup": 0, "skipped_invalid": 0,
                "added_usernames": [], "skipped_dups": []}
    data = _load()
    entry = _ensure_identity(data, identity)
    va_clean = (va or "").strip()[:60]
    # Set des usernames existants pour dedupe
    existing = {(a.get("username") or "").strip().lower(): True
                for a in entry["accounts"]}
    # IDs deja utilises (globalement)
    used_ids = set()
    for k, v in data.items():
        for a in (v.get("accounts") or []):
            try:
                used_ids.add(int(a.get("id", 0)))
            except Exception:
                pass
    added_usernames: List[str] = []
    skipped_dups: List[str] = []
    skipped_invalid = 0
    next_id = int(time.time() * 1000)
    now_ts = int(time.time())
    for raw in usernames:
        u = (raw or "").strip().lstrip("@")[:80]
        if not u:
            skipped_invalid += 1
            continue
        if u.lower() in existing:
            skipped_dups.append(u)
            continue
        while next_id in used_ids:
            next_id += 1
        acct = {
            "id": next_id,
            "username": u,
            "password": "",
            "email": "",
            "two_fa": "",
            "two_fa_validated": False,
            "va": va_clean,
            "notes": "",
            "created_at": now_ts,
        }
        entry["accounts"].append(acct)
        used_ids.add(next_id)
        existing[u.lower()] = True
        added_usernames.append(u)
        next_id += 1
    # Si va donne et n existe pas dans la liste -> ajoute auto
    if va_clean and added_usernames:
        if not any(_va_name(v).lower() == va_clean.lower() for v in entry["vas"]):
            entry["vas"].append({"name": va_clean, "discord_username": ""})
    _save(data)
    return {
        "added": len(added_usernames),
        "skipped_dup": len(skipped_dups),
        "skipped_invalid": skipped_invalid,
        "added_usernames": added_usernames,
        "skipped_dups": skipped_dups,
    }


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

def list_vas_for_identity(identity: str) -> List[Dict[str, str]]:
    """Liste les VAs declares pour une identite (sources explicites + comptes).
    Retourne une liste de dicts {name, discord_username}."""
    identity = (identity or "").strip().lower()
    data = _load()
    entry = data.get(identity)
    if not entry:
        return []
    result: List[Dict[str, str]] = list(entry.get("vas") or [])
    seen_lc = {_va_name(v).lower() for v in result if _va_name(v)}
    # Ajoute aussi tout va present sur un compte mais absent de la liste
    for a in (entry.get("accounts") or []):
        va = (a.get("va") or "").strip()
        if va and va.lower() not in seen_lc:
            result.append({"name": va, "discord_username": ""})
            seen_lc.add(va.lower())
    return result


def list_va_names_for_identity(identity: str) -> List[str]:
    """Helper : liste des noms (string) uniquement, pour autocomplete."""
    return [_va_name(v) for v in list_vas_for_identity(identity) if _va_name(v)]


def add_va(identity: str, va_name: str, discord_username: str = "") -> bool:
    """Ajoute un VA a une identite. Returns True si ajoute, False si doublon."""
    identity = (identity or "").strip().lower()
    if not identity:
        return False
    va_name = (va_name or "").strip()[:60]
    if not va_name:
        return False
    discord_username = (discord_username or "").strip()[:60]
    data = _load()
    entry = _ensure_identity(data, identity)
    if any(_va_name(v).lower() == va_name.lower() for v in entry["vas"]):
        return False
    entry["vas"].append({
        "name": va_name,
        "discord_username": discord_username,
    })
    _save(data)
    return True


def update_va(identity: str, old_name: str, new_name: str = None,
              discord_username: str = None) -> bool:
    """Met a jour un VA (nom et/ou discord_username).
    - Si new_name fourni et != old : renomme. Si conflit -> False.
    - Si discord_username fourni : met a jour.
    Si on renomme, les comptes referencant l ancien nom sont mis a jour aussi."""
    identity = (identity or "").strip().lower()
    old_name = (old_name or "").strip()
    if not identity or not old_name:
        return False
    data = _load()
    entry = data.get(identity)
    if not entry:
        return False
    target = None
    for v in entry["vas"]:
        if _va_name(v).lower() == old_name.lower():
            target = v
            break
    if target is None:
        return False
    new_name_clean = None
    if new_name is not None:
        new_name_clean = (new_name or "").strip()[:60]
        if not new_name_clean:
            return False
        # Conflit si nouveau nom existe (autre que le notre)
        if new_name_clean.lower() != old_name.lower():
            if any(_va_name(v).lower() == new_name_clean.lower() for v in entry["vas"]):
                return False
            target["name"] = new_name_clean
            # Propage le rename aux comptes
            for a in entry["accounts"]:
                if (a.get("va") or "").strip().lower() == old_name.lower():
                    a["va"] = new_name_clean
    if discord_username is not None:
        target["discord_username"] = discord_username.strip()[:60]
    _save(data)
    return True


def remove_va(identity: str, va_name: str) -> bool:
    """Retire un VA de la liste."""
    identity = (identity or "").strip().lower()
    va_name = (va_name or "").strip()
    if not identity or not va_name:
        return False
    data = _load()
    entry = data.get(identity)
    if not entry:
        return False
    new_list = [v for v in entry["vas"] if _va_name(v).lower() != va_name.lower()]
    if len(new_list) == len(entry["vas"]):
        return False
    entry["vas"] = new_list
    _save(data)
    return True


def rename_va(identity: str, old_name: str, new_name: str) -> bool:
    """Helper retrocompat - delegue a update_va(new_name=...)."""
    return update_va(identity, old_name, new_name=new_name)


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
