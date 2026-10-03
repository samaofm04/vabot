"""Le Drive range les vidéos, le plan les ramasse tout seul.

Le propriétaire dépose ses vidéos dans un dossier par étape, sur Google Drive.
Ce module les y trouve et les rattache à l'étape correspondante du plan — qui
les publie ensuite dans Discord. Personne ne recopie une adresse à la main.

LE NUMÉRO EN TÊTE DU DOSSIER FAIT LOI. « 01 - JOUR 0 … » va à la deuxième
étape, quoi qu'il arrive au titre ensuite. Se fier au titre aurait casse le
rattachement au premier mot change, et une video serait partie sur le mauvais
jour sans que personne le voie.

UNE VIDÉO N'EST AJOUTÉE QU'UNE FOIS. On reconnaît un fichier à son identifiant
Drive, pas à son nom : renommer un fichier ne doit pas le faire apparaître en
double dans le message.

RIEN N'EST SUPPRIMÉ. Retirer une vidéo du Drive ne la retire pas de l'étape :
le plan reste la source, et on n'efface pas le travail de quelqu'un sur la foi
d'un dossier qu'on a peut-être mal lu.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FICHIER = DATA_DIR / "onboarding_drive.json"

# Mon Drive > Unbording, partagé avec le compte de service en Éditeur
RACINE_DEFAUT = "1ZxZCjY8VclVX3VDaisdECX1u6UIs8RTz"
API = "https://www.googleapis.com/drive/v3/files"
MEDIA = ("video/", "image/")


def config() -> Dict[str, Any]:
    try:
        return safe_json.load(CONFIG_FICHIER, default={}) or {}
    except Exception:
        return {}


def racine() -> str:
    return str(config().get("racine") or RACINE_DEFAUT)


def actif() -> bool:
    return config().get("actif", True) is not False


def _enfants(session, parent: str) -> List[Dict[str, Any]]:
    r = session.get(API, params={"q": f"'{parent}' in parents and trashed = false",
                                 "fields": "files(id,name,mimeType,size,createdTime)",
                                 "pageSize": 200, "orderBy": "name",
                                 "includeItemsFromAllDrives": "true",
                                 "supportsAllDrives": "true"}, timeout=60)
    if r.status_code != 200:
        print(f"[drive] lecture de {parent} : HTTP {r.status_code}", flush=True)
        return []
    return r.json().get("files", [])


def _rang(nom: str) -> Optional[int]:
    """« 03 - JOUR 1 … » → 3. None si le dossier n'est pas numéroté."""
    m = re.match(r"\s*(\d{1,2})\s*[-–—]", str(nom or ""))
    return int(m.group(1)) if m else None


def _deja(etape: Dict[str, Any], file_id: str) -> bool:
    """Ce fichier Drive est-il déjà rattaché ? On compare l'identifiant."""
    for m in (etape.get("media") or []):
        if file_id and file_id in str(m.get("url") or "") + str(m.get("name") or ""):
            return True
    return False


def scanner() -> Dict[str, Any]:
    """Ramasse les vidéos du Drive et les rattache aux étapes. Rend le bilan."""
    bilan = {"ajoutes": [], "ignores": [], "rates": []}
    if not actif():
        bilan["rates"].append("ramassage désactivé")
        return bilan
    try:
        import gdrive_sync as g
        import onboarding as ob
        session = g._session()
    except Exception as e:
        bilan["rates"].append(f"Drive indisponible : {type(e).__name__}: {e}")
        return bilan
    if session is None:
        bilan["rates"].append("Drive indisponible : pas de session")
        return bilan

    etapes = ob.list_steps()
    change = False
    for d in _enfants(session, racine()):
        if not str(d.get("mimeType", "")).endswith("folder"):
            continue
        n = _rang(d.get("name"))
        if n is None or n >= len(etapes):
            bilan["ignores"].append(f'{d.get("name")} (hors plan)')
            continue
        etape = etapes[n]
        for f in _enfants(session, d["id"]):
            if not str(f.get("mimeType", "")).startswith(MEDIA):
                continue
            etape = ob.get_step(etape["id"]) or etape      # relire : on vient d'ecrire
            if _deja(etape, f["id"]):
                continue
            url = f'https://drive.google.com/file/d/{f["id"]}/view'
            r = ob.add_media_link(etape["id"], url, f.get("name") or "vidéo")
            if r.get("ok"):
                bilan["ajoutes"].append(f'{etape.get("title")} ← {f.get("name")}')
                change = True
            else:
                bilan["rates"].append(f'{f.get("name")} : {r.get("error")}')
    if change:
        try:
            import onboarding_discord as od
            od.planifier(2.0)
        except Exception as e:
            bilan["rates"].append(f"publication : {type(e).__name__}: {e}")
    return bilan
