"""Gestion des bio links style Linktree par identité.

Chaque identité a sa page publique /bio/<identity>
avec ses liens (OF, MYM, Snap, customs).
"""
import json
import time
from pathlib import Path
from typing import List, Dict

DATA_DIR = Path("data")
BIO_FILE = DATA_DIR / "bio_links.json"


def _load_all() -> dict:
    if not BIO_FILE.exists():
        return {}
    try:
        return json.loads(BIO_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_all(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BIO_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_bio(identity: str) -> dict:
    """Récupère la config bio d'une identité."""
    data = _load_all()
    return data.get(identity.lower().strip(), {
        "display_name": "",
        "bio": "",
        "theme": "dark",
        "links": [],
    })


def set_bio_meta(identity: str, display_name: str, bio: str, theme: str = "dark"):
    """Met à jour les métadonnées (nom + bio + thème) d'une identité."""
    data = _load_all()
    key = identity.lower().strip()
    if key not in data:
        data[key] = {"display_name": "", "bio": "", "theme": "dark", "links": []}
    data[key]["display_name"] = display_name.strip()[:60]
    data[key]["bio"] = bio.strip()[:300]
    data[key]["theme"] = theme if theme in ("dark", "light", "gradient") else "dark"
    _save_all(data)


def add_link(identity: str, title: str, url: str, icon: str = "🔗"):
    """Ajoute un lien à une identité."""
    data = _load_all()
    key = identity.lower().strip()
    if key not in data:
        data[key] = {"display_name": "", "bio": "", "theme": "dark", "links": []}
    new_id = int(time.time() * 1000)
    data[key].setdefault("links", []).append({
        "id": new_id,
        "title": title.strip()[:100],
        "url": url.strip()[:500],
        "icon": (icon or "🔗")[:5],
    })
    _save_all(data)
    return new_id


def remove_link(identity: str, link_id: int) -> bool:
    data = _load_all()
    key = identity.lower().strip()
    if key not in data:
        return False
    before = len(data[key].get("links", []))
    data[key]["links"] = [
        l for l in data[key].get("links", []) if l.get("id") != link_id
    ]
    if len(data[key]["links"]) == before:
        return False
    _save_all(data)
    return True


def reorder_links(identity: str, link_ids: List[int]):
    """Réordonne les liens selon la liste d'ids."""
    data = _load_all()
    key = identity.lower().strip()
    if key not in data:
        return
    by_id = {l["id"]: l for l in data[key].get("links", [])}
    reordered = [by_id[lid] for lid in link_ids if lid in by_id]
    # Garder les liens non listés à la fin
    listed_ids = set(link_ids)
    for l in data[key].get("links", []):
        if l["id"] not in listed_ids:
            reordered.append(l)
    data[key]["links"] = reordered
    _save_all(data)


def stats() -> dict:
    """Stats globales : nb d'identités avec bio config, nb total de liens."""
    data = _load_all()
    nb_idents = sum(1 for v in data.values() if v.get("display_name") or v.get("links"))
    nb_links = sum(len(v.get("links", [])) for v in data.values())
    return {"nb_idents_with_bio": nb_idents, "nb_total_links": nb_links}
