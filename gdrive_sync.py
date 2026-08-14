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

# Vault PRO : mêmes types, dossiers pro_* (2e bibliothèque, mêmes identités)
SECTIONS_PRO = (
    ("pro_profile_pics", "Photos de profil", False),
    ("pro_posts", "Posts", False),
    ("pro_stories", "Stories", False),
    ("pro_storyctas", "Story CTA", False),
    ("pro_videos", "Reels", True),
)

# Bibliothèque 2 : identités préfixées, mêmes sous-dossiers que la Bibliothèque
V2_PREFIX = "v2_"

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STATUS: dict = {"state": "idle"}
_IMPORT_STATUS: dict = {"state": "idle"}
_IMPORT_THREAD = None


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


def import_status() -> dict:
    with _LOCK:
        return dict(_IMPORT_STATUS)


def _set_import(**kw):
    with _LOCK:
        _IMPORT_STATUS.update(kw)


def start_import_background() -> bool:
    """Lance l'import Drive -> site dans un thread (un seul a la fois)."""
    global _IMPORT_THREAD
    with _LOCK:
        if _IMPORT_THREAD is not None and _IMPORT_THREAD.is_alive():
            return False

        def _run():
            try:
                run_import()
            except Exception as e:
                _set_import(state="error", err=str(e)[:300])

        _IMPORT_THREAD = threading.Thread(target=_run, daemon=True)
        _IMPORT_THREAD.start()
        return True


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
def _iter_jobs(include_videos):
    """`include_videos` : False/"" = photos seules, "montage" = + rushs bruts et
    templates (Reel montage), True/"all" = tout (reels compris)."""
    """(chemin Drive, Path fichier) pour TOUT le site.

    Rangement dans le Drive : <Bibliothèque>/<Identité>/<Type>. Les trois
    bibliothèques sont couvertes — sans ça, la Bibliothèque 2 arrivait en vrac
    sous « V2_Beta » et le Vault PRO n'était pas sauvegardé du tout."""
    if not IDENTITIES_DIR.exists():
        return
    for ident_dir in sorted(IDENTITIES_DIR.iterdir()):
        if not ident_dir.is_dir():
            continue
        nom = ident_dir.name
        est_v2 = nom.lower().startswith(V2_PREFIX)
        label = nom[len(V2_PREFIX):] if est_v2 else nom
        # La Bibliotheque reste A LA RACINE (structure deja en place dans le
        # Drive de l'user) : y ajouter un niveau aurait recree TOUT en double
        # a cote de l'existant. Seules les 2 autres ont leur dossier.
        biblio = "Bibliotheque 2" if est_v2 else None
        plan = list(SECTIONS) + ([] if est_v2 else
                                 [(s, n, v, "Vault PRO") for s, n, v in SECTIONS_PRO])
        for entree in plan:
            if len(entree) == 4:
                sub, drive_name, is_video, biblio_x = entree
            else:
                sub, drive_name, is_video = entree
                biblio_x = biblio
            if is_video:
                mode = include_videos
                if not mode:
                    continue
                # « montage » : les rushs et templates partent, PAS les reels
                # (ce sont eux qui pesent le plus lourd dans le quota).
                if str(mode).lower() == "montage" and sub in ("videos", "pro_videos"):
                    continue
            exts = VIDEO_EXTS if is_video else IMAGE_EXTS
            folder = ident_dir / sub
            if not folder.exists():
                continue
            for p in sorted(folder.iterdir()):
                if p.is_file() and p.suffix.lower() in exts and ".example" not in p.name:
                    chemin = ((biblio_x,) if biblio_x else ()) + (label.title(), drive_name)
                    yield chemin, p


# ===== Import Drive -> site =====
# Dossier « A IMPORTER » a la racine du Drive : tu y deposes tes videos (par
# l'app Drive, sans limite de taille du navigateur), le serveur les rapatrie
# dans la bibliotheque. Les fichiers ne sont JAMAIS supprimes du Drive : ils
# sont simplement notes comme importes (etat local).
IMPORT_FOLDER_NAME = "A IMPORTER"

# sous-dossier du Drive -> dossier de l'identite
IMPORT_MAP = {
    # noms libres cote user
    "video brut": "brutes", "videos brutes": "brutes", "brutes": "brutes",
    "reels": "videos", "posts": "posts", "stories": "stories",
    "story cta": "storyctas", "photos de profil": "profile_pics",
    "templates montage": "templates", "templates": "templates",
    # memes noms que ceux crees par la synchro (aller-retour coherent)
    "rushs bruts": "brutes",
}


def _lister(sess, parent_id, dossiers=False):
    q = (f"'{parent_id}' in parents and trashed = false and mimeType "
         + ("=" if dossiers else "!=") + " 'application/vnd.google-apps.folder'")
    out, page = [], None
    while True:
        prm = {"q": q, "fields": "nextPageToken, files(id,name,size)",
               "pageSize": 200, "supportsAllDrives": "true",
               "includeItemsFromAllDrives": "true"}
        if page:
            prm["pageToken"] = page
        r = sess.get("https://www.googleapis.com/drive/v3/files", params=prm, timeout=60)
        r.raise_for_status()
        d = r.json()
        out += d.get("files") or []
        page = d.get("nextPageToken")
        if not page:
            return out


def _telecharger(sess, file_id, cible: Path):
    """Ecrit le fichier sans jamais lire son contenu."""
    r = sess.get(f"https://www.googleapis.com/drive/v3/files/{file_id}",
                 params={"alt": "media", "supportsAllDrives": "true"},
                 stream=True, timeout=900)
    r.raise_for_status()
    tmp = cible.with_suffix(cible.suffix + ".part")
    with tmp.open("wb") as fh:
        for bloc in r.iter_content(1 << 20):
            if bloc:
                fh.write(bloc)
    tmp.replace(cible)


def _importer_dossier(sess, dossier_id, ident, sub, st, deja_envoyes):
    """Descend les fichiers d'un dossier Drive vers <identite>/<sub>.
    Upload CLASSIQUE : le fichier tel quel, sans caption ni description."""
    exts = VIDEO_EXTS if sub in ("brutes", "templates", "videos", "pro_videos") else IMAGE_EXTS
    cible_dir = IDENTITIES_DIR / ident / sub
    total = imported = errors = 0
    for f in _lister(sess, dossier_id):
        nom = Path(f["name"]).name
        if Path(nom).suffix.lower() not in exts:
            continue
        total += 1
        if st["imported"].get(f["id"]) or f["id"] in deja_envoyes:
            continue                      # deja importe, ou c'est NOUS qui l'avons mis
        try:
            cible_dir.mkdir(parents=True, exist_ok=True)
            dst = cible_dir / nom
            k = 2
            while dst.exists():
                dst = cible_dir / f"{Path(nom).stem}_{k}{Path(nom).suffix}"
                k += 1
            _telecharger(sess, f["id"], dst)
            st["imported"][f["id"]] = {"name": dst.name, "ts": int(time.time())}
            imported += 1
            _save_state(st)
            _set_import(imported=imported, done=total)
        except Exception as e:
            errors += 1
            _set_status(err=str(e)[:200])
    return total, imported, errors


# nom de dossier Drive -> sous-dossier de l'identite (sens inverse de SECTIONS)
_DRIVE_TO_SUB = {n.lower(): s for s, n, _ in SECTIONS}


def run_import() -> dict:
    """Rapatrie ce qui a ete depose dans le Drive vers le site.

    Deux endroits acceptes :
      - « A IMPORTER/<identite>/<type>/ »  (depot libre)
      - directement dans l'arborescence creee par la synchro, ex.
        « Lillaroseconlon/Rushs bruts/ » — les fichiers que NOUS avons envoyes
        sont ignores (on les reconnait par leur identifiant Drive)."""
    cfg = load_config()
    root = folder_id_from(cfg.get("folder") or "")
    if not root:
        raise RuntimeError("dossier Drive non configuré")
    st = _load_state()
    st.setdefault("imported", {})
    sess = _session()
    racine = None
    for f in _lister(sess, root, dossiers=True):
        if f["name"].strip().lower() == IMPORT_FOLDER_NAME.lower():
            racine = f["id"]
            break
    total = imported = errors = 0
    _set_import(state="running", total=0, done=0, imported=0, errors=0,
                err="", ts=int(time.time()))
    for ident_dir in (_lister(sess, racine, dossiers=True) if racine else []):
        ident = ident_dir["name"].strip().lower()
        if not ident:
            continue
        for type_dir in _lister(sess, ident_dir["id"], dossiers=True):
            sub = IMPORT_MAP.get(type_dir["name"].strip().lower())
            if not sub:
                continue
            exts = VIDEO_EXTS if sub in ("brutes", "templates", "videos") else IMAGE_EXTS
            cible_dir = IDENTITIES_DIR / ident / sub
            for f in _lister(sess, type_dir["id"]):
                nom = Path(f["name"]).name
                if Path(nom).suffix.lower() not in exts:
                    continue
                total += 1
                cle = f["id"]
                if st["imported"].get(cle):
                    continue
                try:
                    cible_dir.mkdir(parents=True, exist_ok=True)
                    dst = cible_dir / nom
                    k = 2
                    while dst.exists():           # jamais d'ecrasement
                        dst = cible_dir / f"{Path(nom).stem}_{k}{Path(nom).suffix}"
                        k += 1
                    _telecharger(sess, f["id"], dst)
                    st["imported"][cle] = {"name": dst.name, "ts": int(time.time())}
                    imported += 1
                    _save_state(st)
                except Exception as e:
                    errors += 1
                    _set_status(err=str(e)[:200])
    # 2e source : l'arborescence normale (depot direct dans les dossiers crees)
    deja = {r.get("id") for r in st.get("uploaded", {}).values() if r.get("id")}
    for dossier in _lister(sess, root, dossiers=True):
        nom_d = dossier["name"].strip()
        if nom_d.lower() in (IMPORT_FOLDER_NAME.lower(), "vault pro"):
            continue
        if nom_d.lower() == "bibliotheque 2":
            for sous in _lister(sess, dossier["id"], dossiers=True):
                ident = V2_PREFIX + sous["name"].strip().lower()
                for typ in _lister(sess, sous["id"], dossiers=True):
                    sub = _DRIVE_TO_SUB.get(typ["name"].strip().lower())
                    if sub:
                        t, i, e = _importer_dossier(sess, typ["id"], ident, sub, st, deja)
                        total += t; imported += i; errors += e
            continue
        ident = nom_d.lower()
        if not (IDENTITIES_DIR / ident).exists():
            continue                       # dossier Drive sans identite -> ignore
        for typ in _lister(sess, dossier["id"], dossiers=True):
            sub = _DRIVE_TO_SUB.get(typ["name"].strip().lower())
            if sub:
                t, i, e = _importer_dossier(sess, typ["id"], ident, sub, st, deja)
                total += t; imported += i; errors += e
    _save_state(st)
    res = {"total": total, "imported": imported, "errors": errors,
           "ts": int(time.time())}
    _set_import(state="done", **res)
    return res


def _creer_arborescence(sess, root, st, include_videos):
    """Cree le dossier de CHAQUE identite et de chaque type, meme sans fichier.
    Ainsi tout est visible dans le Drive et on sait ou deposer."""
    if not IDENTITIES_DIR.exists():
        return
    for ident_dir in sorted(IDENTITIES_DIR.iterdir()):
        if not ident_dir.is_dir():
            continue
        nom = ident_dir.name
        est_v2 = nom.lower().startswith(V2_PREFIX)
        label = (nom[len(V2_PREFIX):] if est_v2 else nom).title()
        plans = [(("Bibliotheque 2",) if est_v2 else ()) + (label,), SECTIONS]
        parent = root
        for niveau in plans[0]:
            parent = _ensure_folder(sess, parent, niveau, st)
        # TOUS les dossiers, meme ceux dont le contenu ne part pas : ils
        # servent de point de depot et montrent ce qui est vide.
        for sub, drive_name, is_video in SECTIONS:
            _ensure_folder(sess, parent, drive_name, st)
        if not est_v2:                       # Vault PRO
            pro = _ensure_folder(sess, root, "Vault PRO", st)
            pro_ident = _ensure_folder(sess, pro, label, st)
            for sub, drive_name, is_video in SECTIONS_PRO:
                _ensure_folder(sess, pro_ident, drive_name, st)


def run_sync() -> dict:
    """Synchro complète (bloquant — à lancer via start_background)."""
    cfg = load_config()
    root = folder_id_from(cfg.get("folder") or "")
    if not root:
        raise RuntimeError("dossier Drive non configuré")
    include_videos = bool(cfg.get("include_videos"))
    st = _load_state()
    sess = _session()

    # Arborescence COMPLETE d'abord : on veut voir tous les dossiers dans le
    # Drive meme vides — c'est la qu'on depose, et ca montre ce qui manque.
    try:
        _creer_arborescence(sess, root, st, include_videos)
        _save_state(st)
    except Exception as e:
        _set_status(err=f"dossiers : {e}"[:200])

    jobs = list(_iter_jobs(include_videos))
    total = len(jobs)
    done = skipped = uploaded = errors = 0
    _set_status(state="running", total=total, done=0, uploaded=0,
                skipped=0, errors=0, err="", ts=int(time.time()))
    for chemin, path in jobs:
        done += 1
        key = "/".join(chemin) + "/" + path.name
        try:
            size = path.stat().st_size
            rec = st["uploaded"].get(key)
            if rec and rec.get("size") == size:
                skipped += 1
            else:
                parent = root
                for niveau in chemin:          # <Bibliothèque>/<Identité>/<Type>
                    parent = _ensure_folder(sess, parent, niveau, st)
                fid = _upload_file(sess, parent, path)
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
