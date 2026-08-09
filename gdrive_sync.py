"""gdrive_sync.py — Copie le contenu par identité vers un VRAI Google Drive.

Principe (demande user : « avoir les trucs sur un Google Drive ») :
  - le user PARTAGE un dossier de SON Drive avec l'email du compte de service
    (le même que la synchro Sheets : data/google_service_account.json) ;
  - la synchro COPIE data/identities/<ident>/<bibliothèque> vers
    <dossier>/<Ident>/<Bibliothèque> ;
  - COPIE UNIQUEMENT : ce module ne supprime JAMAIS rien, ni sur le Drive ni
    en local (aucun appel delete nulle part — garde-fou volontaire) ;
  - re-lancer la synchro n'upload que le nouveau/modifié (état local par
    fichier : taille + id Drive dans data/gdrive_sync_state.json).

Dépendances : google-auth (déjà sur le VPS via gspread) + requests.
Uploads en « resumable single-shot » (multipart est limité à 5 Mo).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import safe_json

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
SA_FILE = DATA_DIR / "google_service_account.json"
CONFIG_FILE = DATA_DIR / "gdrive_sync.json"
STATE_FILE = DATA_DIR / "gdrive_sync_state.json"

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# (sous-dossier local, nom du dossier Drive, vidéo ?)
SECTIONS = (
    ("profile_pics", "Photos de profil", False),
    ("posts", "Posts", False),
    ("stories", "Stories", False),
    ("storyctas", "Story CTA", False),
    ("videos", "Reels", True),
    ("brutes", "Rushs bruts", True),
    ("templates", "Templates montage", True),
)

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STATUS: dict = {"state": "idle"}


# ---------------------------------------------------------------- config
def available() -> bool:
    """Compte de service présent + google-auth importable."""
    if not SA_FILE.exists():
        return False
    try:
        from google.oauth2.service_account import Credentials  # noqa: F401
        return True
    except Exception:
        return False


def sa_email() -> str:
    try:
        return json.loads(SA_FILE.read_text(encoding="utf-8")).get("client_email", "")
    except Exception:
        return ""


# Dossier Drive du user (collé dans le chat le 09/08/2026) — sert de valeur
# par défaut tant qu'aucun dossier n'a été enregistré depuis la page Drive.
DEFAULT_FOLDER_ID = "1qtkfg3ghV55DkXeWWruFUPQjkxHO6qL1"


def load_config() -> dict:
    d = safe_json.load(CONFIG_FILE, default={}) or {}
    d = d if isinstance(d, dict) else {}
    if not d.get("folder"):
        d["folder"] = DEFAULT_FOLDER_ID
    return d


def save_config(cfg: dict) -> bool:
    return bool(safe_json.write(CONFIG_FILE, cfg, indent=2))


def folder_id_from(raw: str) -> str:
    """Accepte un id nu OU une URL Drive (…/folders/<id>, ?id=<id>)."""
    import re
    raw = (raw or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_\-]+)", raw)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_\-]+)", raw)
    if m:
        return m.group(1)
    return raw if re.fullmatch(r"[A-Za-z0-9_\-]{10,}", raw) else ""


def status() -> dict:
    with _LOCK:
        return dict(_STATUS)


def _set_status(**kw):
    with _LOCK:
        _STATUS.update(kw)


# ---------------------------------------------------------------- état local
def _load_state() -> dict:
    d = safe_json.load(STATE_FILE, default={}) or {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("uploaded", {})
    d.setdefault("folders", {})
    return d


def _save_state(st: dict) -> None:
    safe_json.write(STATE_FILE, st, indent=2)


# ---------------------------------------------------------------- API Drive
def _session():
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import AuthorizedSession
    creds = Credentials.from_service_account_file(
        str(SA_FILE), scopes=["https://www.googleapis.com/auth/drive"])
    return AuthorizedSession(creds)


def _ensure_folder(sess, parent_id: str, name: str, st: dict) -> str:
    """Trouve/crée <name> sous parent_id (cache local : jamais de doublon)."""
    key = f"{parent_id}/{name}"
    cached = st["folders"].get(key)
    if cached:
        return cached
    safe = name.replace("'", "\\'")
    q = (f"name = '{safe}' and '{parent_id}' in parents "
         "and mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    r = sess.get("https://www.googleapis.com/drive/v3/files",
                 params={"q": q, "fields": "files(id)", "pageSize": 1,
                         "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"},
                 timeout=60)
    r.raise_for_status()
    files = r.json().get("files") or []
    if files:
        fid = files[0]["id"]
    else:
        r = sess.post("https://www.googleapis.com/drive/v3/files",
                      params={"fields": "id", "supportsAllDrives": "true"},
                      json={"name": name, "parents": [parent_id],
                            "mimeType": "application/vnd.google-apps.folder"},
                      timeout=60)
        r.raise_for_status()
        fid = r.json()["id"]
    st["folders"][key] = fid
    return fid


def _upload_file(sess, parent_id: str, path: Path) -> str:
    """Upload resumable en un coup (toutes tailles). Retourne l'id Drive."""
    meta = {"name": path.name, "parents": [parent_id]}
    r = sess.post(
        "https://www.googleapis.com/upload/drive/v3/files"
        "?uploadType=resumable&fields=id&supportsAllDrives=true",
        json=meta, timeout=60)
    r.raise_for_status()
    put_url = r.headers.get("Location")
    if not put_url:
        raise RuntimeError("pas d'URL d'upload")
    with path.open("rb") as fh:
        r2 = sess.put(put_url, data=fh,
                      headers={"Content-Length": str(path.stat().st_size)},
                      timeout=(30, 1800))
    r2.raise_for_status()
    return r2.json().get("id", "")


# ---------------------------------------------------------------- synchro
def _iter_jobs(include_videos: bool):
    """(identité, section Drive, Path fichier) pour tout ce qui est à couvrir."""
    if not IDENTITIES_DIR.exists():
        return
    for ident_dir in sorted(IDENTITIES_DIR.iterdir()):
        if not ident_dir.is_dir():
            continue
        for sub, drive_name, is_video in SECTIONS:
            if is_video and not include_videos:
                continue
            exts = VIDEO_EXTS if is_video else IMAGE_EXTS
            folder = ident_dir / sub
            if not folder.exists():
                continue
            for p in sorted(folder.iterdir()):
                if p.is_file() and p.suffix.lower() in exts and ".example" not in p.name:
                    yield ident_dir.name, drive_name, p


def run_sync() -> dict:
    """Synchro complète (bloquant — à lancer via start_background)."""
    cfg = load_config()
    root = folder_id_from(cfg.get("folder") or "")
    if not root:
        raise RuntimeError("dossier Drive non configuré")
    include_videos = bool(cfg.get("include_videos"))
    st = _load_state()
    sess = _session()

    jobs = list(_iter_jobs(include_videos))
    total = len(jobs)
    done = skipped = uploaded = errors = 0
    _set_status(state="running", total=total, done=0, uploaded=0,
                skipped=0, errors=0, err="", ts=int(time.time()))
    for ident, drive_name, path in jobs:
        done += 1
        key = f"{ident}/{drive_name}/{path.name}"
        try:
            size = path.stat().st_size
            rec = st["uploaded"].get(key)
            if rec and rec.get("size") == size:
                skipped += 1
            else:
                ident_folder = _ensure_folder(sess, root, ident.title(), st)
                sec_folder = _ensure_folder(sess, ident_folder, drive_name, st)
                fid = _upload_file(sess, sec_folder, path)
                st["uploaded"][key] = {"size": size, "id": fid}
                uploaded += 1
                if uploaded % 10 == 0:
                    _save_state(st)
        except Exception as e:  # un fichier en échec ne stoppe pas le reste
            errors += 1
            _set_status(err=str(e)[:200])
        _set_status(done=done, uploaded=uploaded, skipped=skipped, errors=errors)
    _save_state(st)
    res = {"total": total, "uploaded": uploaded, "skipped": skipped,
           "errors": errors, "ts": int(time.time())}
    cfg["last_run"] = res
    save_config(cfg)
    _set_status(state="done", **res)
    return res


def start_background() -> bool:
    """Lance la synchro dans un thread (une seule à la fois)."""
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False

        def _run():
            try:
                run_sync()
            except Exception as e:
                _set_status(state="error", err=str(e)[:300])

        _THREAD = threading.Thread(target=_run, name="gdrive-sync", daemon=True)
        _THREAD.start()
        return True
