"""safe_json.py — écriture/lecture ROBUSTE des fichiers de données JSON.

Pourquoi : partout dans le projet on écrivait `PATH.write_text(json.dumps(...))`.
Ce motif a deux défauts qui coûtent des données :

1. **Écriture non atomique** — le fichier est tronqué à zéro puis rempli. Si le
   process meurt entre les deux (le VPS redémarre à CHAQUE déploiement), il
   reste un JSON incomplet. Le chargeur, qui fait `except: return {}`, croit
   alors à une base vide… et la première sauvegarde suivante grave ce vide.
2. **Aucune protection contre l'écriture concurrente** — deux threads (poller
   Sheets, requêtes web, scrape) écrivent le même fichier en même temps.

Ici : écriture atomique (tmp + fsync + os.replace), verrou par fichier, et une
copie `.prev` qui permet de récupérer l'état précédent si le fichier principal
devient illisible.

Usage :
    import safe_json
    safe_json.write_text(PATH, json.dumps(data, indent=2, ensure_ascii=False))
    data = safe_json.load(PATH, default={})
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

# Un verrou par chemin de fichier (créé à la demande).
_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()

# Fichiers de cache régénérables : pas de copie .prev (inutile, et ça double les
# écritures sur des fichiers qui bougent souvent).
_CACHE_HINTS = ("cache", "_state", "status", "health", "lastgood", "counters")


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lk = _LOCKS.get(key)
        if lk is None:
            lk = _LOCKS[key] = threading.RLock()
        return lk


def _is_cache(path: Path) -> bool:
    n = path.name.lower()
    return any(h in n for h in _CACHE_HINTS)


def write_text(path, text: str, backup: bool | None = None) -> bool:
    """Écrit `text` de façon ATOMIQUE. Retourne True si écrit.

    backup=None (défaut) : copie `.prev` sauf pour les fichiers de cache.
    """
    p = Path(path)
    with _lock_for(p):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if backup is None:
                backup = not _is_cache(p)
            if backup and p.exists() and p.stat().st_size > 1:
                try:
                    shutil.copy2(p, p.with_suffix(p.suffix + ".prev"))
                except Exception:
                    pass
            tmp = p.with_suffix(p.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp), str(p))
            return True
        except Exception as e:
            print(f"[safe_json] échec écriture {p.name} : {e}", flush=True)
            return False


def write(path, data: Any, indent: int | None = 2, ensure_ascii: bool = False,
          backup: bool | None = None) -> bool:
    """Sérialise puis écrit atomiquement."""
    return write_text(path, json.dumps(data, indent=indent, ensure_ascii=ensure_ascii),
                      backup=backup)


def load(path, default: Any = None) -> Any:
    """Lit un JSON. Si le fichier est illisible/tronqué, tente `.prev` avant de
    rendre `default` — et signale le repli dans les logs (au lieu de faire
    croire silencieusement à un fichier vide)."""
    p = Path(path)
    with _lock_for(p):
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8")
                if txt.strip():
                    return json.loads(txt)
            except Exception as e:
                print(f"[safe_json] ⚠ {p.name} illisible ({e}) — tentative .prev", flush=True)
        prev = p.with_suffix(p.suffix + ".prev")
        if prev.exists():
            try:
                data = json.loads(prev.read_text(encoding="utf-8"))
                print(f"[safe_json] ✔ {p.name} restauré depuis {prev.name}", flush=True)
                try:
                    write_text(p, json.dumps(data, indent=2, ensure_ascii=False), backup=False)
                except Exception:
                    pass
                return data
            except Exception:
                pass
        return default
