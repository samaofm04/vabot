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


# ── La bibliothèque des captions (data/captions.json) ─────────────────────
# Le 23/10/2026, tests_site.py lancé DANS le dossier de prod du VPS a réécrit
# data/captions.json en « {} » : 86 captions de 17 identités perdues, .prev
# compris, et « Reel + caption » répondait « Aucune caption active » partout
# jusqu'au 31/10. Aucune action du site ne vide plus d'une identité à la fois
# (retirer une identité, vider sa liste, la renommer) : une écriture qui fait
# disparaître TOUTES les captions de CAPTIONS_EFFACEMENT_MAX identités ou plus
# est refusée, et dite au journal. Ici, pas dans le site : tout le monde écrit
# par safe_json (site, identite_admin, favoris, scripts, tests).
_CAPTIONS_NOM = "captions.json"
CAPTIONS_EFFACEMENT_MAX = 2
#: Les identités de test se créent et s'effacent ensemble : hors du compte.
_CAPTIONS_TEST = "_tst"


def _identites_avec_captions(lib: Any):
    """Les identités qui ont au moins une caption écrite, ou None si `lib`
    n'est pas une bibliothèque {identité: {"items": [...]}} (celle de Noctus,
    data/noctus/captions.json, est une liste)."""
    if not isinstance(lib, dict):
        return None
    return {str(k) for k, b in lib.items()
            if not str(k).startswith(_CAPTIONS_TEST) and isinstance(b, dict)
            and isinstance(b.get("items"), list)
            and any(isinstance(i, dict) and str(i.get("text") or "").strip()
                    for i in b["items"])}


def _captions_effacees(p: Path, text: str) -> list:
    """Les identités dont `text` effacerait toutes les captions, comparé à
    `p` (à son .prev si `p` est illisible). [] quand rien ne se compare."""
    avant = None
    for f in (p, p.with_suffix(p.suffix + ".prev")):
        try:
            avant = _identites_avec_captions(json.loads(f.read_text(encoding="utf-8")))
            break
        except (OSError, ValueError):
            continue
    if not avant:
        return []
    try:
        apres = _identites_avec_captions(json.loads(text))
    except ValueError:
        apres = None
    # un texte qui n'est plus une bibliothèque les efface toutes
    return sorted(avant - (apres or set()))


def write_text(path, text: str, backup: bool | None = None) -> bool:
    """Écrit `text` de façon ATOMIQUE. Retourne True si écrit.

    backup=None (défaut) : copie `.prev` sauf pour les fichiers de cache.
    Refuse (False) une bibliothèque de captions qui en perdrait trop d'un
    coup (voir plus haut).
    """
    p = Path(path)
    with _lock_for(p):
        if p.name == _CAPTIONS_NOM:
            try:
                perdues = _captions_effacees(p, text)
            except Exception as e:                           # noqa: BLE001
                # le garde ne bloque jamais une écriture sur sa propre panne
                print(f"[safe_json] garde des captions indisponible ({type(e).__name__}: {e})",
                      flush=True)
                perdues = []
            if len(perdues) >= CAPTIONS_EFFACEMENT_MAX:
                print(f"[safe_json] ALERTE {p} : écriture REFUSÉE, elle effaçait toutes les "
                      f"captions de {len(perdues)} identités ({', '.join(perdues[:10])}"
                      f"{'…' if len(perdues) > 10 else ''}) — fichier gardé tel quel",
                      flush=True)
                return False
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
                print(f"[safe_json] ATTENTION : {p.name} illisible ({e}) — tentative .prev", flush=True)
        prev = p.with_suffix(p.suffix + ".prev")
        if prev.exists():
            try:
                data = json.loads(prev.read_text(encoding="utf-8"))
                print(f"[safe_json] OK : {p.name} restauré depuis {prev.name}", flush=True)
                try:
                    write_text(p, json.dumps(data, indent=2, ensure_ascii=False), backup=False)
                except Exception:
                    pass
                return data
            except Exception:
                pass
        return default


def load_or_prev(path):
    """Comme json.loads(path.read_text()) mais avec le filet .prev.

    LEVE si rien n'est lisible (les appelants ont deja un try/except qui
    retombe sur leur valeur par defaut) : on ne fait donc jamais croire a un
    fichier vide alors qu'une sauvegarde existe.
    """
    import json as _j
    from pathlib import Path as _P
    p = _P(path)
    txt = p.read_text(encoding="utf-8")     # laisse remonter FileNotFoundError
    try:
        return _j.loads(txt)
    except Exception:
        prev = p.with_suffix(p.suffix + ".prev")
        data = _j.loads(prev.read_text(encoding="utf-8"))
        print(f"[safe_json] OK : {p.name} illisible -> restauré depuis {prev.name}", flush=True)
        try:
            write_text(p, _j.dumps(data, indent=2, ensure_ascii=False), backup=False)
        except Exception:
            pass
        return data
