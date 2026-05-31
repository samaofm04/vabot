"""onboarding.py - Plan d onboarding par etapes (JOUR 0, JOUR 1, ...).

Chaque etape a un titre + une icone + une description + une liste de medias
(fichiers locaux ou liens URL).

Stockage : data/onboarding.json
Medias uploades : data/onboarding/<step_id>/<filename>

Structure :
{
    "steps": [
        {
            "id": "uuid",
            "order": 1,
            "icon": "👋",
            "title": "Bienvenue dans l agence !",
            "description": "",
            "media": [
                {"id": "uuid", "kind": "video|image|audio|file|link",
                 "name": "filename.ext", "path": "data/onboarding/.../f.ext",
                 "url": "", "size": 12345}
            ]
        },
        ...
    ]
}
"""
from __future__ import annotations

import json
import uuid
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

DATA_DIR = Path("data")
ONBOARDING_FILE = DATA_DIR / "onboarding.json"
MEDIA_ROOT = DATA_DIR / "onboarding"

# Extensions par categorie - drive le rendering frontend
VIDEO_EXT = {"mp4", "mov", "webm", "mkv", "m4v"}
IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
AUDIO_EXT = {"mp3", "wav", "ogg", "m4a", "aac"}
PDF_EXT = {"pdf"}

# Limite par fichier - cohérent avec Telegram bot upload limit
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# Etapes par defaut (copie du screenshot user)
DEFAULT_STEPS = [
    {"icon": "👋", "title": "Bienvenue dans l'agence !", "description": ""},
    {"icon": "📅", "title": "JOUR 0 — Création du compte Instagram", "description": ""},
    {"icon": "⏳", "title": "ATTENDRE 24H à 48H", "description": "Laisse passer 24-48h avant la suite"},
    {"icon": "📅", "title": "JOUR 1 — Premier engagement + photo de profil", "description": ""},
    {"icon": "📅", "title": "JOUR 2 — Bio + première story + premier post", "description": ""},
    {"icon": "📅", "title": "JOUR 3 — Story + post + premier reel", "description": ""},
    {"icon": "📅", "title": "JOUR 4 — Carousels + bulle à la une", "description": ""},
    {"icon": "📅", "title": "JOUR 5 — Remplissage des stories à la une", "description": ""},
    {"icon": "📅", "title": "JOUR 6+ — Routine quotidienne (warmup terminé)", "description": ""},
]


def kind_for_filename(filename: str) -> str:
    """Devine le type d un media depuis l extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in PDF_EXT:
        return "pdf"
    return "file"


def _load() -> Dict[str, Any]:
    if not ONBOARDING_FILE.exists():
        return _seed()
    try:
        data = json.loads(ONBOARDING_FILE.read_text(encoding="utf-8"))
        if "steps" not in data:
            data["steps"] = []
        return data
    except Exception:
        return _seed()


def _seed() -> Dict[str, Any]:
    """Premiere init : cree les etapes par defaut."""
    steps = []
    for i, s in enumerate(DEFAULT_STEPS):
        steps.append({
            "id": uuid.uuid4().hex[:12],
            "order": i + 1,
            "icon": s["icon"],
            "title": s["title"],
            "description": s["description"],
            "media": [],
        })
    data = {"steps": steps}
    _save(data)
    return data


def _save(data: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ONBOARDING_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_steps() -> List[Dict[str, Any]]:
    data = _load()
    steps = data.get("steps", [])
    steps.sort(key=lambda s: s.get("order", 0))
    return steps


def get_step(step_id: str) -> Optional[Dict[str, Any]]:
    for s in list_steps():
        if s.get("id") == step_id:
            return s
    return None


def add_step(icon: str = "📅", title: str = "Nouvelle étape",
             description: str = "") -> Dict[str, Any]:
    data = _load()
    next_order = max([s.get("order", 0) for s in data["steps"]], default=0) + 1
    step = {
        "id": uuid.uuid4().hex[:12],
        "order": next_order,
        "icon": (icon or "📅").strip()[:8],
        "title": (title or "Nouvelle étape").strip()[:200],
        "description": (description or "").strip()[:1000],
        "media": [],
    }
    data["steps"].append(step)
    _save(data)
    return step


def update_step(step_id: str, **fields) -> bool:
    data = _load()
    for s in data["steps"]:
        if s.get("id") == step_id:
            for k in ("icon", "title", "description"):
                if k in fields and fields[k] is not None:
                    s[k] = str(fields[k]).strip()[:200 if k != "description" else 1000]
            _save(data)
            return True
    return False


def delete_step(step_id: str) -> bool:
    data = _load()
    before = len(data["steps"])
    # Drop le dossier media du step si dispo
    step_dir = MEDIA_ROOT / step_id
    if step_dir.exists():
        try:
            shutil.rmtree(step_dir)
        except Exception:
            pass
    data["steps"] = [s for s in data["steps"] if s.get("id") != step_id]
    if len(data["steps"]) != before:
        # Re-numerote pour combler le trou
        for i, s in enumerate(sorted(data["steps"], key=lambda x: x.get("order", 0))):
            s["order"] = i + 1
        _save(data)
        return True
    return False


def reorder_steps(ordered_ids: List[str]) -> bool:
    """Reordonne les etapes selon la liste d ids fournie."""
    data = _load()
    by_id = {s["id"]: s for s in data["steps"]}
    new_steps = []
    used = set()
    for i, sid in enumerate(ordered_ids):
        if sid in by_id and sid not in used:
            s = by_id[sid]
            s["order"] = i + 1
            new_steps.append(s)
            used.add(sid)
    # Ajoute les non-listes a la fin
    for s in data["steps"]:
        if s["id"] not in used:
            s["order"] = len(new_steps) + 1
            new_steps.append(s)
    data["steps"] = new_steps
    _save(data)
    return True


def add_media_file(step_id: str, filename: str, content: bytes) -> Dict[str, Any]:
    """Sauvegarde un fichier media uploade pour une etape.

    Retourne {ok, media|error}.
    """
    if not get_step(step_id):
        return {"ok": False, "error": "Etape introuvable"}
    if len(content) > MAX_FILE_SIZE:
        return {"ok": False, "error": f"Fichier trop lourd ({len(content)//(1024*1024)} MB > 50 MB)"}
    # Sanitize filename
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    if not safe_name:
        safe_name = f"media_{uuid.uuid4().hex[:6]}"
    step_dir = MEDIA_ROOT / step_id
    step_dir.mkdir(parents=True, exist_ok=True)
    # Evite les collisions
    target = step_dir / safe_name
    if target.exists():
        stem, _, ext = safe_name.rpartition(".")
        if not stem:
            stem = safe_name
            ext = ""
        target = step_dir / f"{stem}_{uuid.uuid4().hex[:4]}{('.' + ext) if ext else ''}"
    target.write_bytes(content)
    media = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind_for_filename(safe_name),
        "name": safe_name,
        "path": str(target.as_posix()),
        "url": "",
        "size": len(content),
    }
    data = _load()
    for s in data["steps"]:
        if s.get("id") == step_id:
            s.setdefault("media", []).append(media)
            _save(data)
            return {"ok": True, "media": media}
    return {"ok": False, "error": "Etape disparue"}


def add_media_link(step_id: str, url: str, name: str = "") -> Dict[str, Any]:
    """Ajoute un lien URL externe comme media."""
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "URL vide"}
    if not get_step(step_id):
        return {"ok": False, "error": "Etape introuvable"}
    media = {
        "id": uuid.uuid4().hex[:12],
        "kind": "link",
        "name": (name or url)[:200].strip() or url,
        "path": "",
        "url": url,
        "size": 0,
    }
    data = _load()
    for s in data["steps"]:
        if s.get("id") == step_id:
            s.setdefault("media", []).append(media)
            _save(data)
            return {"ok": True, "media": media}
    return {"ok": False, "error": "Etape disparue"}


def delete_media(step_id: str, media_id: str) -> bool:
    data = _load()
    for s in data["steps"]:
        if s.get("id") != step_id:
            continue
        media_list = s.get("media", [])
        target = next((m for m in media_list if m.get("id") == media_id), None)
        if not target:
            return False
        # Drop le fichier disque si local
        if target.get("path"):
            try:
                p = Path(target["path"])
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        s["media"] = [m for m in media_list if m.get("id") != media_id]
        _save(data)
        return True
    return False


def get_media(step_id: str, media_id: str) -> Optional[Dict[str, Any]]:
    s = get_step(step_id)
    if not s:
        return None
    for m in s.get("media", []):
        if m.get("id") == media_id:
            return m
    return None


def stats() -> Dict[str, Any]:
    """Stats globales pour le badge / overview."""
    steps = list_steps()
    total_media = sum(len(s.get("media", [])) for s in steps)
    total_size = 0
    for s in steps:
        for m in s.get("media", []):
            total_size += m.get("size", 0)
    return {
        "step_count": len(steps),
        "media_count": total_media,
        "total_size_mb": round(total_size / (1024 * 1024), 1),
    }
