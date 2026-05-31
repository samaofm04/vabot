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
import os
import re
import uuid
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

import requests

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

# Etapes par defaut - importees depuis cogs/onboarding.py (le bot Discord)
DEFAULT_STEPS = [
    {
        "icon": "👋",
        "title": "Bienvenue dans l'agence !",
        "description": (
            "Voici une vidéo explicative qui va te montrer comment va se dérouler ton job "
            "en tant que VA dans l'agence.\n\n"
            "Tout va t'être expliqué étape par étape par le bot.\n\n"
            "*(La vidéo d'explication sera ajoutée ici par le boss bientôt.)*\n\n"
            "Quand tu es prêt, clique sur l'étape suivante."
        ),
    },
    {
        "icon": "📆",
        "title": "JOUR 0 — Création du compte Instagram",
        "description": (
            "Sur ton téléphone, fais cette séquence :\n\n"
            "1) Rotate l'IP : mode avion 10 sec → enlève → remets la 5G\n"
            "2) Crée un Gmail qui aura comme base le futur nom Insta\n"
            "3) Inscris le Gmail sur Instagram\n"
            "4) Mets le code reçu par mail\n"
            "5) Crée un mot de passe fort\n"
            "6) Mets un name (display) → fais /name ici, je t'en donne un\n"
            "7) Mets un username → fais /username ici, je t'en donne un\n\n"
            "⚠️ Numéro US requis — demande au boss.\n\n"
            "Quand le compte est créé → passe à la suite."
        ),
    },
    {
        "icon": "⏳",
        "title": "ATTENDRE 24H à 48H",
        "description": (
            "NE FAIS RIEN sur le compte pendant 24 à 48h.\n\n"
            "Instagram doit considérer ton compte comme légitime. Si tu agis trop vite, "
            "shadowban garanti.\n\n"
            "Reviens cliquer quand 24-48h sont passées."
        ),
    },
    {
        "icon": "📆",
        "title": "JOUR 1 — Premier engagement + photo de profil",
        "description": (
            "Engagement (10-15 min) :\n"
            "• Va sur les reels et swipe naturellement comme un humain\n"
            "• Like seulement des filles au début (algo doit comprendre ton feed)\n"
            "• Quand tu tombes sur une fille OnlyFans, va sur son profil :\n"
            "   - Like ses reels\n"
            "   - Mets un commentaire humain (pas \"trop belle mv\" générique — adapte au contenu)\n"
            "   - Regarde ses stories\n"
            "   - Abonne-toi\n\n"
            "⚠️ Max 3 abonnements + max 5-6 commentaires aujourd'hui.\n\n"
            "Photo de profil : fais /profilepic ici → upload sur ton compte Insta.\n\n"
            "Ferme Insta. Passe à la suite quand c'est fait."
        ),
    },
    {
        "icon": "📆",
        "title": "JOUR 2 — Bio + première story + premier post",
        "description": (
            "• Interagis 10 min (5-6 commentaires + max 3 abonnements)\n"
            "• Ajoute la bio → fais /bio ici, je t'en donne une\n"
            "• Poste 1 story simple (photo ou vidéo neutre) → fais /story\n"
            "• Crée une bulle à la une appelée \"me\" + ajoute ta story dedans\n"
            "• Poste 1 publication photo sur le feed avec musique → fais /post"
        ),
    },
    {
        "icon": "📆",
        "title": "JOUR 3 — Story + post + premier reel",
        "description": (
            "• Interagis 10 min (5-6 commentaires + 3 abonnements)\n"
            "• Poste 1 story simple → fais /story\n"
            "• Crée une bulle à la une appelée \"life\" + ajoute ta story dedans\n"
            "• Poste 1 publication photo avec musique → fais /post\n"
            "• 🎬 PUBLIE TON PREMIER REEL entre 18h et 21h → fais /reel"
        ),
    },
    {
        "icon": "📆",
        "title": "JOUR 4 — Carousels + bulle à la une",
        "description": (
            "• Interagis 10 min (commentaires + 3 abonnements)\n"
            "• Poste 1 story simple → fais /story\n"
            "• Crée une bulle à la une appelée \"travel\" + ajoute ta story\n"
            "• PIN les 3 carousels (épingle les 3 derniers posts en haut du profil)\n"
            "• 🎬 Publie 1 reel entre 18h et 21h → fais /reel"
        ),
    },
    {
        "icon": "📆",
        "title": "JOUR 5 — Remplissage des stories à la une",
        "description": (
            "• Interagis 10 min (commentaires + 3 abonnements)\n"
            "• Poste 12 stories aujourd'hui → fais /story (refais la commande pour chaque story)\n"
            "• Répartis-les : 4 stories par bulle à la une (me / life / travel)\n"
            "• 🎬 Publie 1 reel à 20h heure française → fais /reel"
        ),
    },
    {
        "icon": "📆",
        "title": "JOUR 6+ — Routine quotidienne (warmup terminé)",
        "description": (
            "Routine quotidienne à appliquer chaque jour :\n\n"
            "• Interagir 2-3 min/jour (commentaire + 3 abonnements)\n"
            "• 1 story quotidienne → fais /story\n"
            "• 🎬 1 reel entre 18h et 21h → fais /reel\n"
            "• Repost le reel de la veille en story avec texte CTA\n"
            "• 📲 Story CTA + lien redirection → fais /storycta\n"
            "• Crée une bulle à la une \"LINKS\" pour stocker les CTAs\n\n"
            "🎉 Le warmup est terminé ! À partir de maintenant tu enchaînes la routine "
            "et tu utilises /reel, /post, /story, /storycta quand tu en as besoin.\n\n"
            "Bon courage 💪"
        ),
    },
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


def _load_bot_token() -> Optional[str]:
    """Recupere le DISCORD_TOKEN du .env."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    tok = os.getenv("DISCORD_TOKEN", "").strip()
    return tok or None


def fetch_discord_message(message_url: str) -> Dict[str, Any]:
    """Fetch un message Discord via l API (GET /channels/{ch}/messages/{msg}).

    URL accepte : https://discord.com/channels/{guild|@me}/{channel}/{message}
    Retourne {ok, content, attachments, embeds, author, error}.
    """
    token = _load_bot_token()
    if not token:
        return {"ok": False, "error": "DISCORD_TOKEN absent du .env serveur"}
    m = re.search(r'/channels/(?:\d+|@me)/(\d+)/(\d+)', message_url or '')
    if not m:
        return {"ok": False, "error": "URL Discord invalide (format attendu : .../channels/X/Y/Z)"}
    channel_id, message_id = m.group(1), m.group(2)
    try:
        r = requests.get(
            f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}",
            headers={"Authorization": f"Bot {token}", "User-Agent": "VA-AUTO Onboarding/1.0"},
            timeout=15,
        )
    except Exception as e:
        return {"ok": False, "error": f"Erreur reseau Discord : {e}"}
    if r.status_code != 200:
        try:
            j = r.json()
            return {"ok": False, "error": f"Discord {r.status_code}: {j.get('message', '?')}"}
        except Exception:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
    try:
        msg = r.json()
    except Exception:
        return {"ok": False, "error": "Reponse Discord non-JSON"}
    return {
        "ok": True,
        "content": msg.get("content", ""),
        "attachments": msg.get("attachments", []),
        "embeds": msg.get("embeds", []),
        "author": (msg.get("author") or {}).get("username", "?"),
        "channel_id": channel_id,
        "message_id": message_id,
    }


def _build_text_from_embeds(embeds: list, fallback_content: str = "") -> str:
    """Concatene title + description des embeds Discord en un seul texte propre."""
    parts: List[str] = []
    for emb in embeds or []:
        t = (emb.get("title") or "").strip()
        d = (emb.get("description") or "").strip()
        if t:
            parts.append(t)
        if d:
            parts.append(d)
        # Fields = sous-sections
        for f in emb.get("fields") or []:
            fn = (f.get("name") or "").strip()
            fv = (f.get("value") or "").strip()
            if fn or fv:
                parts.append(f"{fn}\n{fv}" if fn and fv else (fn or fv))
    if fallback_content and fallback_content.strip():
        parts.insert(0, fallback_content.strip())
    return "\n\n".join(parts).strip()


def import_from_discord_message_url(step_id: str, message_url: str,
                                    use_text_as_description: bool = True) -> Dict[str, Any]:
    """Importe un message Discord (attachments + embeds) dans une etape.

    Comportement :
    - Telecharge TOUS les attachments (fichiers) comme medias locaux
    - Extrait le TEXTE des embeds (title + description + fields)
    - Si l etape n a pas encore de description (ou si use_text_as_description=True),
      met le texte de l embed dans step.description
    - Sinon, ajoute le texte comme media kind=note

    Retourne {ok, imported, total, text_imported, errors}.
    """
    if not get_step(step_id):
        return {"ok": False, "error": "Etape introuvable"}
    info = fetch_discord_message(message_url)
    if not info.get("ok"):
        return info

    attachments = info.get("attachments") or []
    embeds = info.get("embeds") or []
    content = (info.get("content") or "").strip()
    embed_text = _build_text_from_embeds(embeds, fallback_content=content)

    imported = 0
    errors: List[str] = []
    for att in attachments:
        try:
            url = att.get("url") or att.get("proxy_url")
            if not url:
                errors.append(f"{att.get('filename', '?')}: pas d URL CDN")
                continue
            r = requests.get(url, timeout=60, stream=True)
            if r.status_code != 200:
                errors.append(f"{att.get('filename', '?')}: HTTP {r.status_code}")
                continue
            chunks = []
            total = 0
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_FILE_SIZE:
                    errors.append(f"{att.get('filename', '?')}: > {MAX_FILE_SIZE // (1024*1024)} MB")
                    chunks = []
                    break
            if not chunks:
                continue
            bytes_ = b"".join(chunks)
            res = add_media_file(step_id, att.get("filename", "discord_media"), bytes_)
            if res.get("ok"):
                imported += 1
            else:
                errors.append(f"{att.get('filename', '?')}: {res.get('error', '?')}")
        except Exception as e:
            errors.append(f"{att.get('filename', '?')}: {e}")

    text_imported = False
    if embed_text:
        step = get_step(step_id)
        existing_desc = (step.get("description") or "").strip()
        if use_text_as_description and (not existing_desc or len(embed_text) > len(existing_desc) + 50):
            # On utilise le texte de l embed comme description de l etape
            update_step(step_id, description=embed_text)
            text_imported = True
        else:
            # On garde la description et on ajoute le texte comme note media
            data = _load()
            note_media = {
                "id": uuid.uuid4().hex[:12],
                "kind": "note",
                "name": f"Note Discord (par @{info.get('author', '?')})",
                "path": "",
                "url": "",
                "text": embed_text[:4000],
                "size": 0,
            }
            for s in data["steps"]:
                if s.get("id") == step_id:
                    s.setdefault("media", []).append(note_media)
                    text_imported = True
                    break
            _save(data)

    if imported == 0 and not text_imported:
        # Vraiment rien d utile -> fallback link
        res = add_media_link(step_id, message_url, name=f"Discord (par @{info.get('author', '?')})")
        if res.get("ok"):
            return {"ok": True, "imported": 0, "total": 0, "text_imported": False, "errors": errors,
                    "note": "Aucun attachment ni texte - ajoute comme simple lien"}

    return {
        "ok": True,
        "imported": imported,
        "total": len(attachments),
        "text_imported": text_imported,
        "errors": errors,
    }


def import_from_discord_cog() -> Dict[str, Any]:
    """Re-importe les textes du cog Discord + scanne data/onboarding_media/.

    - Met a jour les titres + descriptions des etapes existantes a partir
      de DEFAULT_STEPS (qui est la copie du cog Discord).
    - Pour chaque step_N dans data/onboarding_media/ : copie les fichiers
      qui ne sont pas deja dans data/onboarding/<step_id>/ (par nom).
    - Lit les _links.json et ajoute les liens Discord comme media kind=link
      (le user pourra cliquer dessus, Discord ne les decode pas mais on
      sait ce que c est).

    Retourne {ok, steps_updated, files_imported, links_imported, errors}.
    """
    out = {
        "ok": True,
        "steps_updated": 0,
        "files_imported": 0,
        "links_imported": 0,
        "errors": [],
    }
    data = _load()
    cog_media_root = Path("data/onboarding_media")

    # 1) Refresh les textes des etapes par ordre - on assume meme ordre
    # que DEFAULT_STEPS
    steps_sorted = sorted(data["steps"], key=lambda s: s.get("order", 0))
    for i, step in enumerate(steps_sorted):
        if i >= len(DEFAULT_STEPS):
            break
        ref = DEFAULT_STEPS[i]
        if step.get("title") != ref["title"] or step.get("description") != ref["description"] or step.get("icon") != ref["icon"]:
            step["icon"] = ref["icon"]
            step["title"] = ref["title"]
            step["description"] = ref["description"]
            out["steps_updated"] += 1

    # 2) Scan dossiers step_N pour les fichiers media + _links.json
    if cog_media_root.exists():
        for i, step in enumerate(steps_sorted):
            cog_dir = cog_media_root / f"step_{i + 1}"
            if not cog_dir.exists():
                continue
            sid = step["id"]
            target_dir = MEDIA_ROOT / sid
            target_dir.mkdir(parents=True, exist_ok=True)
            # Fichiers media
            existing_names = {m.get("name", "") for m in step.get("media", [])}
            for f in sorted(cog_dir.iterdir()):
                if not f.is_file() or f.name.startswith("_"):
                    continue
                if f.name in existing_names:
                    continue
                try:
                    target = target_dir / f.name
                    if not target.exists():
                        shutil.copy2(f, target)
                    size = target.stat().st_size
                    media = {
                        "id": uuid.uuid4().hex[:12],
                        "kind": kind_for_filename(f.name),
                        "name": f.name,
                        "path": str(target.as_posix()),
                        "url": "",
                        "size": size,
                    }
                    step.setdefault("media", []).append(media)
                    out["files_imported"] += 1
                except Exception as e:
                    out["errors"].append(f"step_{i+1}/{f.name}: {e}")
            # Liens Discord
            links_file = cog_dir / "_links.json"
            if links_file.exists():
                try:
                    raw = json.loads(links_file.read_text(encoding="utf-8"))
                    existing_urls = {m.get("url", "") for m in step.get("media", [])}
                    for entry in raw:
                        ch = entry.get("channel_id")
                        msg = entry.get("message_id")
                        if not ch or not msg:
                            continue
                        # Pas de guild_id stocke -> on construit avec @me
                        url = f"https://discord.com/channels/@me/{ch}/{msg}"
                        if url in existing_urls:
                            continue
                        files = entry.get("filenames", []) or []
                        name = files[0] if files else f"Discord msg {msg}"
                        media = {
                            "id": uuid.uuid4().hex[:12],
                            "kind": "link",
                            "name": name,
                            "path": "",
                            "url": url,
                            "size": 0,
                        }
                        step.setdefault("media", []).append(media)
                        out["links_imported"] += 1
                except Exception as e:
                    out["errors"].append(f"step_{i+1}/_links.json: {e}")

    _save(data)
    return out
