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
import os
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Any

DATA_DIR = Path("data")
JAILBREAK_FILE = DATA_DIR / "jailbreak.json"
BACKUP_DIR = DATA_DIR / "jailbreak_backups"
_BACKUPS_KEEP = 15

# Verrou REENTRANT global : toute sequence lire-modifier-ecrire doit se faire
# sous ce verrou, sinon deux ecritures concurrentes (poller Sheet toutes les
# 2 min + action web) s ecrasent l une l autre = comptes perdus en silence.
_LOCK = threading.RLock()
# Dernier etat SAIN vu par ce process : permet une restauration EXACTE si le
# fichier est trouve corrompu/vide (sans perdre la derniere operation).
_LAST_GOOD: Dict[str, Any] = {"data": None}


@contextmanager
def transaction():
    """Verrouille la base le temps d une sequence load -> modif -> save.

    Usage (y compris depuis sheets_sync) :
        with jailbreak.transaction():
            data = jailbreak._load()
            ...
            jailbreak._save(data)
    """
    with _LOCK:
        yield


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


def _parse(txt: str) -> Dict[str, Dict[str, Any]]:
    raw = json.loads(txt)
    if not isinstance(raw, dict):
        raise ValueError("racine JSON invalide")
    return {k: _migrate_identity_entry(v) for k, v in raw.items()}


PREV_FILE = DATA_DIR / "jailbreak.prev.json"


def _backups_newest_first() -> List[Path]:
    """Candidats de restauration, du plus récent au plus ancien.
    jailbreak.prev.json (état juste avant la DERNIÈRE écriture) passe devant :
    une restauration ne perd alors qu'une seule opération."""
    out: List[Path] = []
    try:
        if PREV_FILE.exists():
            out.append(PREV_FILE)
    except Exception:
        pass
    try:
        out += sorted(BACKUP_DIR.glob("jailbreak_*.json"), reverse=True)
    except Exception:
        pass
    return out


def _load() -> Dict[str, Dict[str, Any]]:
    """Charge et NORMALISE tout vers le format v2.

    JAMAIS de {} silencieux sur fichier corrompu : un fichier tronque (crash /
    redemarrage pendant l ecriture) renverrait une base VIDE, que le premier
    _save suivant graverait pour de bon (et que le push repliquerait dans les
    Sheets). On repli donc sur le dernier backup valide.
    """
    with _LOCK:
        if not JAILBREAK_FILE.exists():
            return {}
        try:
            txt = JAILBREAK_FILE.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[jailbreak] lecture impossible : {e}", flush=True)
            txt = ""
        if txt.strip():
            try:
                data = _parse(txt)
                _LAST_GOOD["data"] = json.loads(json.dumps(data))   # copie profonde
                return data
            except Exception as e:
                print(f"[jailbreak] ⚠ FICHIER CORROMPU ({e}) — repli", flush=True)
        else:
            print("[jailbreak] ⚠ fichier VIDE — repli", flush=True)
        # 1) dernier état SAIN vu par ce process (restauration exacte)
        if _LAST_GOOD.get("data") is not None:
            data = json.loads(json.dumps(_LAST_GOOD["data"]))
            print(f"[jailbreak] ✔ restauré depuis la mémoire "
                  f"({sum(len(v.get('accounts') or []) for v in data.values())} comptes)", flush=True)
            try:
                _write_atomic(data)
            except Exception:
                pass
            return data
        # 2) sinon : jailbreak.prev.json puis l historique horodaté
        for b in _backups_newest_first():
            try:
                data = _parse(b.read_text(encoding="utf-8"))
            except Exception:
                continue
            print(f"[jailbreak] ✔ restauré depuis {b.name} "
                  f"({sum(len(v.get('accounts') or []) for v in data.values())} comptes)", flush=True)
            try:                       # remet le fichier principal d aplomb
                _write_atomic(data)
            except Exception:
                pass
            return data
        # Aucun backup exploitable : on refuse de faire croire a une base vide
        # (sinon la moindre ecriture suivante detruit tout pour de bon).
        raise RuntimeError("jailbreak.json illisible et aucun backup valide")


def _write_atomic(data: Dict[str, Dict[str, Any]]):
    """Ecriture ATOMIQUE (tmp + os.replace) : un crash en pleine ecriture ne
    peut plus laisser un jailbreak.json tronque."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JAILBREAK_FILE.with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(JAILBREAK_FILE))


_BACKUP_EVERY_S = 600          # historique horodaté : au plus 1 / 10 min


def _rotate_backup():
    """Sauvegarde l état AVANT écrasement, à deux niveaux :
    - jailbreak.prev.json : SYSTÉMATIQUE (état N-1 exact) ;
    - jailbreak_backups/  : historique horodaté, au plus un toutes les 10 min,
      rotation sur _BACKUPS_KEEP (une rafale d écritures dans la même seconde
      ne doit pas remplir l historique et chasser les états utiles)."""
    try:
        if not JAILBREAK_FILE.exists() or JAILBREAK_FILE.stat().st_size < 2:
            return
        try:
            shutil.copy2(JAILBREAK_FILE, PREV_FILE)
        except Exception:
            pass
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        hist = sorted(BACKUP_DIR.glob("jailbreak_*.json"), reverse=True)
        if hist:
            try:
                if time.time() - hist[0].stat().st_mtime < _BACKUP_EVERY_S:
                    return
            except Exception:
                pass
        shutil.copy2(JAILBREAK_FILE,
                     BACKUP_DIR / f"jailbreak_{time.strftime('%Y%m%d_%H%M%S')}.json")
        for old in sorted(BACKUP_DIR.glob("jailbreak_*.json"), reverse=True)[_BACKUPS_KEEP:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception as e:
        print(f"[jailbreak] backup impossible : {e}", flush=True)


def _save(data: Dict[str, Dict[str, Any]]):
    with _LOCK:
        _rotate_backup()
        _write_atomic(data)
        try:
            _LAST_GOOD["data"] = json.loads(json.dumps(data))
        except Exception:
            pass
    # Sync -> Google Sheet (best-effort, non bloquant, no-op si non configure).
    try:
        import sheets_sync
        sheets_sync.push_all_async(data)
    except Exception:
        pass


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


def _norm_handle(s: str) -> str:
    return (s or "").strip().lower().lstrip("@")


def accounts_for_discord_username(discord_username: str) -> List[Dict[str, Any]]:
    """Tous les comptes Insta reliés à un pseudo Discord.

    On relie via le champ `discord_username` des VAs : on cherche dans TOUTES
    les identités les VAs dont le discord_username == le pseudo donné, puis on
    remonte les comptes dont le champ `va` correspond à ces VAs.
    Retourne une liste de comptes (dicts), vide si rien."""
    h = _norm_handle(discord_username)
    if not h:
        return []
    data = _load()
    out: List[Dict[str, Any]] = []
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        va_names = {
            _va_name(v).lower()
            for v in (entry.get("vas") or [])
            if _norm_handle(v.get("discord_username") if isinstance(v, dict) else "") == h
            and _va_name(v)
        }
        if not va_names:
            continue
        for a in (entry.get("accounts") or []):
            if (a.get("va") or "").strip().lower() in va_names:
                out.append(a)
    return out


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
    # Anti-doublon : un double-clic sur Sauvegarder envoyait 2 POST -> 2 comptes
    if any((a.get("username") or "").strip().lower() == username.lower()
           for a in entry["accounts"]):
        raise ValueError(f"@{username} existe deja pour cette identite")
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
    tomb_clear("accounts", identity, username)
    if va_clean:
        tomb_clear("vas", identity, va_clean)
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
                        # Anti-doublon : deux comptes au meme username finissaient
                        # fusionnes par _dedup_accounts (un des deux, avec son mot
                        # de passe et son 2FA, disparaissait).
                        if any(o is not acct and (o.get("username") or "").strip().lower() == v.lower()
                               for o in entry["accounts"]):
                            return False
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
    if added_usernames:
        # re-ajout volontaire -> ces comptes (et le VA) ne sont plus "supprimes"
        tomb_clear("accounts", identity, *added_usernames)
        if (va or "").strip():
            tomb_clear("vas", identity, va)
    _save(data)
    return {
        "added": len(added_usernames),
        "skipped_dup": len(skipped_dups),
        "skipped_invalid": skipped_invalid,
        "added_usernames": added_usernames,
        "skipped_dups": skipped_dups,
    }



# ============ Tombstones (anti-resurrection via le Google Sheet) ============
# Un VA/compte supprime sur le site etait RE-IMPORTE par le poller Sheet (2 min)
# si le pull passait avant le push (ou si un vieil onglet trainait). On marque
# donc chaque suppression 7 jours : pull_and_merge refuse de re-importer.
TOMB_FILE = DATA_DIR / "jb_tombstones.json"
_TOMB_TTL = 7 * 86400


def _tomb_key(identity: str, name: str) -> str:
    return f"{(identity or '').strip().lower()}|{(name or '').strip().lower()}"


def _tomb_load() -> Dict[str, Dict[str, int]]:
    try:
        d = json.loads(TOMB_FILE.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    now = int(time.time())
    out: Dict[str, Dict[str, int]] = {}
    for kind in ("vas", "accounts"):
        m = d.get(kind) if isinstance(d.get(kind), dict) else {}
        out[kind] = {k: int(v) for k, v in m.items() if now - int(v or 0) < _TOMB_TTL}
    return out


def _tomb_save(d: Dict[str, Dict[str, int]]):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TOMB_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def tomb_add(kind: str, identity: str, *names: str):
    names = [n for n in names if (n or "").strip()]
    if not (identity or "").strip() or not names:
        return
    d = _tomb_load()
    now = int(time.time())
    for n in names:
        d[kind][_tomb_key(identity, n)] = now
    _tomb_save(d)


def tomb_clear(kind: str, identity: str, *names: str):
    d = _tomb_load()
    hit = False
    for n in names:
        if d[kind].pop(_tomb_key(identity, n), None) is not None:
            hit = True
    if hit:
        _tomb_save(d)


def tombstones() -> Dict[str, Dict[str, int]]:
    """{'vas': {'ident|va': ts}, 'accounts': {'ident|username': ts}} (TTL purge)."""
    return _tomb_load()


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
    gone = [a for a in entry["accounts"] if int(a.get("id", 0)) == int(account_id)]
    entry["accounts"] = [
        a for a in entry["accounts"] if int(a.get("id", 0)) != int(account_id)
    ]
    if len(entry["accounts"]) == n_before:
        return False
    tomb_add("accounts", identity, *[(a.get("username") or "") for a in gone])
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
    tomb_clear("vas", identity, va_name)
    _save(data)
    return True


def reorder_vas(identity: str, ordered_names: List[str]) -> bool:
    """Reordonne les VAs d une identite selon ordered_names (drag & drop du site).
    Un nom inconnu de la liste devient un VA explicite (cas des VAs implicites,
    presents seulement via leurs comptes) ; les VAs non cites restent a la fin."""
    identity = (identity or "").strip().lower()
    names = [str(n or "").strip()[:60] for n in (ordered_names or [])]
    names = [n for n in names if n]
    if not identity or not names:
        return False
    data = _load()
    entry = _ensure_identity(data, identity)
    by_lc = {_va_name(v).lower(): v for v in entry["vas"] if _va_name(v)}
    new_list, seen = [], set()
    for n in names:
        lc = n.lower()
        if lc in seen:
            continue
        seen.add(lc)
        new_list.append(by_lc.get(lc) or {"name": n, "discord_username": ""})
    for v in entry["vas"]:
        if _va_name(v).lower() not in seen:
            new_list.append(v)
    entry["vas"] = new_list
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
            # Pierre tombale sur l ANCIEN nom, exactement comme pour une
            # suppression. Sans elle, le Sheet — qui porte encore l ancien nom
            # tant que le push suivant n a pas eu lieu — fait RESSUSCITER la
            # fiche au tour de scrutation suivant (toutes les 2 min) : le site
            # se retrouve avec deux fiches pour un seul VA, l une avec les
            # comptes, l autre vide. C est le doublon constate le 22/08.
            #
            # Et on leve celle du NOUVEAU nom : renommer vers un nom
            # recemment supprime doit marcher, pas etre bloque par sa propre
            # tombe.
            try:
                tomb_add("vas", identity, old_name)
                tomb_clear("vas", identity, new_name_clean)
            except Exception:
                pass          # une annotation perdue ne doit pas rater le rename
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


def remove_va_and_accounts(identity: str, va_name: str) -> int:
    """Supprime un VA ET tous ses comptes. Retourne le nb de comptes supprimes,
    ou -1 si identite/VA vide ou identite introuvable. (Sinon le VA revient car il
    est re-deduit de ses comptes -> il faut supprimer les comptes aussi.)"""
    identity = (identity or "").strip().lower()
    va_name = (va_name or "").strip()
    if not identity or not va_name:
        return -1
    data = _load()
    entry = data.get(identity)
    if not isinstance(entry, dict):
        return -1
    vl = va_name.lower()
    accts = entry.get("accounts") or []
    before = len(accts)
    gone = [a for a in accts if (a.get("va") or "").strip().lower() == vl]
    entry["accounts"] = [a for a in accts if (a.get("va") or "").strip().lower() != vl]
    entry["vas"] = [v for v in (entry.get("vas") or []) if _va_name(v).lower() != vl]
    tomb_add("vas", identity, va_name)
    tomb_add("accounts", identity, *[(a.get("username") or "") for a in gone])
    _save(data)
    return before - len(entry["accounts"])


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


# ============ Atomicite des ecritures ============
# Chaque fonction publique ci-dessous fait « _load -> modifier -> _save ».
# Sans verrou tenu sur TOUTE la sequence, deux appels concurrents (poller Sheet
# toutes les 2 min, actions AJAX du site, scrape) repartent chacun d une copie
# et le dernier _save efface les modifications de l autre. On enveloppe donc
# ces fonctions dans le verrou reentrant global.
def _with_lock(fn):
    import functools

    @functools.wraps(fn)
    def _wrapped(*a, **kw):
        with _LOCK:
            return fn(*a, **kw)
    return _wrapped


for _fname in ("add_account", "update_account", "remove_account", "bulk_add_accounts",
               "add_va", "update_va", "remove_va", "remove_va_and_accounts",
               "reorder_vas", "rename_va", "rename_identity_in_storage",
               "tomb_add", "tomb_clear", "stats", "list_all", "list_accounts",
               "list_vas_for_identity", "accounts_for_discord_username"):
    if _fname in globals():
        globals()[_fname] = _with_lock(globals()[_fname])
del _fname
