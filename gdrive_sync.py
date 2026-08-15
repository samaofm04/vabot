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

# Vault PRO retiree de la synchro le 15/08/2026 : elle a ete sortie du menu du
# site quand la Bibliotheque 2 est arrivee, elle ne contient AUCUN fichier
# (verifie : 0 sur les 5 onglets, 14 identites) et son dossier vide sur le
# Drive ne faisait qu'embrouiller. Remettre a True pour la resynchroniser.
SYNC_VAULT_PRO = False

# Idem pour la Bibliotheque 2 : on ne synchronise QUE la Bibliotheque
# principale pour l'instant (demande du 15/08/2026 : « fais uniquement un
# dossier, celui de Bibliotheque, sans les autres »).
SYNC_VAULT2 = False

# Tout part desormais SOUS ce dossier, au lieu d'etaler une trentaine de
# dossiers d'identites a la racine du Drive a cote de « Vault PRO » et
# « A IMPORTER » — c'etait illisible.
RACINE_BIBLIO = "Bibliothèque"


def _sansaccent(t: str) -> str:
    """Comparaison de noms de dossiers Drive sans se soucier des accents."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").strip().lower())
                   if unicodedata.category(c) != "Mn")

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

# Envois simultanes vers le Drive. 6 = net gain sans risquer le
# « userRateLimitExceeded » de Google (l'ancien mode sequentiel plafonnait
# a ~40 fichiers/minute).
UPLOAD_WORKERS = 12

# En dessous de cette taille, un fichier part en UNE requete (multipart) au
# lieu de deux (ouverture de session reprenable + envoi) : les photos, qui
# sont l'essentiel du volume, vont deux fois plus vite.
SEUIL_MULTIPART = 4 * 1024 * 1024

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STATUS: dict = {"state": "idle"}
_IMPORT_STATUS: dict = {"state": "idle"}
_IMPORT_THREAD = None


# ---------------------------------------------------------------- config
def available() -> bool:
    """Utilisable : ton compte Google connecté, ou le compte de service."""
    if oauth_ready():
        return True
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


# ---------------------------------------------------------------- OAuth user
# Un compte de service n'a AUCUN stockage Google : tout upload de fichier
# repond 403 « storageQuotaExceeded » (les dossiers passent, ils pesent 0).
# Pour deposer sur TON Drive (et donc TON quota), c'est TON compte qui doit
# televerser -> OAuth. Le compte de service reste le mode de secours.
OAUTH_FILE = DATA_DIR / "gdrive_oauth.json"
OAUTH_SCOPE = "https://www.googleapis.com/auth/drive"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def oauth_config() -> dict:
    d = safe_json.load(OAUTH_FILE, default={}) or {}
    return d if isinstance(d, dict) else {}


def oauth_ready() -> bool:
    c = oauth_config()
    return bool(c.get("refresh_token") and c.get("client_id") and c.get("client_secret"))


def oauth_email() -> str:
    return str(oauth_config().get("email") or "")


def auth_mode() -> str:
    """« oauth » (ton compte), « sa » (compte de service), « none »."""
    if oauth_ready():
        return "oauth"
    return "sa" if SA_FILE.exists() else "none"


def oauth_save_client(client_id: str, client_secret: str) -> bool:
    c = oauth_config()
    c["client_id"] = (client_id or "").strip()
    c["client_secret"] = (client_secret or "").strip()
    OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    return bool(safe_json.write(OAUTH_FILE, c, indent=2))


def oauth_reset() -> bool:
    """Deconnecte : on garde l'identifiant d'application, on jette le jeton."""
    c = oauth_config()
    c.pop("refresh_token", None)
    c.pop("email", None)
    return bool(safe_json.write(OAUTH_FILE, c, indent=2))


def oauth_auth_url(redirect_uri: str) -> str:
    from urllib.parse import urlencode
    c = oauth_config()
    if not c.get("client_id"):
        return ""
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect_uri,
        "response_type": "code", "scope": OAUTH_SCOPE,
        "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true",
    })


def oauth_exchange(code: str, redirect_uri: str) -> str:
    """Echange le code contre un jeton durable. Retourne "" si OK, sinon
    le message d'erreur."""
    import requests
    c = oauth_config()
    if not (c.get("client_id") and c.get("client_secret")):
        return "identifiants d'application manquants"
    try:
        r = requests.post(_TOKEN_URI, timeout=30, data={
            "code": code, "client_id": c["client_id"],
            "client_secret": c["client_secret"],
            "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        j = r.json() if r.content else {}
    except Exception as e:
        return str(e)[:200]
    if r.status_code >= 400 or not j.get("refresh_token"):
        return (j.get("error_description") or j.get("error")
                or f"HTTP {r.status_code}") + (
                    "" if j.get("refresh_token") or r.status_code >= 400
                    else " (aucun jeton durable renvoyé — révoque l'accès puis recommence)")
    c["refresh_token"] = j["refresh_token"]
    try:                                   # a qui appartient ce Drive ?
        from google.auth.transport.requests import AuthorizedSession
        sess = _session()
        d = sess.get("https://www.googleapis.com/drive/v3/about",
                     params={"fields": "user(emailAddress)"}, timeout=30)
        c["email"] = (d.json().get("user") or {}).get("emailAddress", "")
    except Exception:
        c["email"] = ""
    safe_json.write(OAUTH_FILE, c, indent=2)
    return ""


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
_LOCAL = threading.local()


def _session_thread():
    """Une session par thread : requests.Session n'est pas prevue pour etre
    partagee entre plusieurs uploads simultanes."""
    s = getattr(_LOCAL, "sess", None)
    if s is None:
        s = _session()
        _LOCAL.sess = s
    return s


def _session():
    """Ton compte Google si connecte (le stockage est le TIEN), sinon le
    compte de service (lecture/dossiers seulement : il n'a pas de quota)."""
    from google.auth.transport.requests import AuthorizedSession
    c = oauth_config()
    if c.get("refresh_token") and c.get("client_id") and c.get("client_secret"):
        from google.oauth2.credentials import Credentials as UserCreds
        return AuthorizedSession(UserCreds(
            None, refresh_token=c["refresh_token"], token_uri=_TOKEN_URI,
            client_id=c["client_id"], client_secret=c["client_secret"],
            scopes=[OAUTH_SCOPE]))
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        str(SA_FILE), scopes=[OAUTH_SCOPE])
    return AuthorizedSession(creds)


class ErreurDrive(RuntimeError):
    """Erreur Drive avec son code : sert a savoir si ca vaut le coup de
    retenter (429 / 5xx) ou non (403 quota, 404...)."""

    def __init__(self, msg, status=0, raison=""):
        super().__init__(msg)
        self.status = status
        self.raison = raison


_RAISONS_REPRISE = ("ratelimitexceeded", "userratelimitexceeded",
                    "backenderror", "internalerror")


def _avec_reprise(fn, *a, **kw):
    """Retente en s'espacant : avec 12 envois en parallele, Google renvoie
    parfois un 429 passager. Abandonner la ferait echouer un fichier pour
    rien."""
    for essai in range(4):
        try:
            return fn(*a, **kw)
        except ErreurDrive as e:
            reprenable = (e.status in (429, 500, 502, 503, 504)
                          or (e.raison or "").lower() in _RAISONS_REPRISE)
            if essai == 3 or not reprenable:
                raise
            time.sleep(1.5 * (2 ** essai))


def _ok(r, quoi=""):
    """Comme raise_for_status(), mais avec le MESSAGE de Google : « 403 »
    tout court ne dit pas quoi corriger."""
    if r.status_code < 400:
        return r
    raison = detail = ""
    try:
        j = (r.json() or {}).get("error") or {}
        detail = str(j.get("message") or "")
        errs = j.get("errors") or []
        raison = str((errs[0] or {}).get("reason") or "") if errs else ""
    except Exception:
        detail = (r.text or "")[:200]
    if raison == "storageQuotaExceeded" or "storage quota" in detail.lower():
        detail = ("le compte de service n'a pas de stockage Google. Va dans "
                  "Drive → « Connecter mon compte Google » pour déposer sur "
                  "ton propre Drive.")
    elif raison in ("insufficientFilePermissions", "forbidden") and not detail:
        detail = "accès refusé au dossier Drive"
    raise ErreurDrive(
        f"{quoi + ' — ' if quoi else ''}{detail or ('HTTP ' + str(r.status_code))}",
        status=r.status_code, raison=raison)


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
        _ok(r, f"dossier « {name} »")
        fid = r.json()["id"]
    st["folders"][key] = fid
    return fid


def _upload_file(sess, parent_id: str, path: Path) -> str:
    """Envoie un fichier. Petit -> une seule requete ; gros -> session
    reprenable. Retourne l'id Drive."""
    try:
        taille = path.stat().st_size
    except OSError:
        taille = SEUIL_MULTIPART + 1
    if taille <= SEUIL_MULTIPART:
        return _upload_multipart(sess, parent_id, path)
    return _upload_resumable(sess, parent_id, path)


def _upload_multipart(sess, parent_id: str, path: Path) -> str:
    """Metadonnees + octets dans UNE requete (limite Google : 5 Mo).
    Les octets ne sont ni ouverts ni analyses, juste recopies."""
    import json as _js
    import mimetypes
    bord = "----youl4bsync"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    meta = {"name": path.name, "parents": [parent_id]}
    corps = (
        (f"--{bord}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n").encode()
        + _js.dumps(meta).encode()
        + (f"\r\n--{bord}\r\nContent-Type: {mime}\r\n\r\n").encode()
        + path.read_bytes()
        + (f"\r\n--{bord}--\r\n").encode()
    )
    r = sess.post(
        "https://www.googleapis.com/upload/drive/v3/files"
        "?uploadType=multipart&fields=id&supportsAllDrives=true",
        data=corps,
        headers={"Content-Type": f"multipart/related; boundary={bord}"},
        timeout=(30, 900))
    _ok(r, "envoi")
    return r.json().get("id", "")


def _upload_resumable(sess, parent_id: str, path: Path) -> str:
    meta = {"name": path.name, "parents": [parent_id]}
    r = sess.post(
        "https://www.googleapis.com/upload/drive/v3/files"
        "?uploadType=resumable&fields=id&supportsAllDrives=true",
        json=meta, timeout=60)
    _ok(r, "envoi")
    put_url = r.headers.get("Location")
    if not put_url:
        raise RuntimeError("pas d'URL d'upload")
    with path.open("rb") as fh:
        r2 = sess.put(put_url, data=fh,
                      headers={"Content-Length": str(path.stat().st_size)},
                      timeout=(30, 1800))
    _ok(r2, "envoi")
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
        if est_v2 and not SYNC_VAULT2:
            continue
        label = nom[len(V2_PREFIX):] if est_v2 else nom
        # Chaque bibliotheque a SON dossier, identites a l'interieur.
        biblio = "Bibliotheque 2" if est_v2 else RACINE_BIBLIO
        plan = list(SECTIONS) + ([] if est_v2 or not SYNC_VAULT_PRO else
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


def sync_report() -> dict:
    """Etat de la copie Drive, identite par identite.

    Compte TOUT (photos + videos, les 3 bibliotheques) : le pourcentage dit
    ce qui est reellement sur le Drive, pas ce que le mode courant enverrait.
    Un fichier compte comme synchronise si son id Drive est connu ET que sa
    taille n'a pas bouge depuis l'envoi."""
    st = _load_state()
    up = st.get("uploaded") or {}
    par: dict = {}

    def _e(ident):
        return par.setdefault(ident, {"identity": ident, "total": 0,
                                      "sync": 0, "manque": 0, "octets": 0})

    if IDENTITIES_DIR.exists():
        for d in sorted(IDENTITIES_DIR.iterdir()):
            if d.is_dir():
                _e(d.name)
    for chemin, path in _iter_jobs(True):
        # data/identities/<ident>/<sous-dossier>/<fichier>
        ent = _e(path.parent.parent.name)
        ent["total"] += 1
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        rec = up.get("/".join(chemin) + "/" + path.name)
        if rec and rec.get("size") == size:
            ent["sync"] += 1
        else:
            ent["manque"] += 1
            ent["octets"] += max(0, size)
    lignes = []
    for ent in par.values():
        t = ent["total"]
        ent["pct"] = 100 if not t else int(round(ent["sync"] * 100.0 / t))
        lignes.append(ent)
    lignes.sort(key=lambda e: (e["pct"], -e["total"], e["identity"]))
    tot = sum(e["total"] for e in lignes)
    syn = sum(e["sync"] for e in lignes)
    return {"identities": lignes, "total": tot, "sync": syn,
            "manque": tot - syn, "octets": sum(e["octets"] for e in lignes),
            "pct": 100 if not tot else int(round(syn * 100.0 / tot)),
            "mode": auth_mode(), "email": oauth_email()}


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


# nom de dossier Drive -> sous-dossier de l'identite (sens inverse de SECTIONS)
_DRIVE_TO_SUB = {n.lower(): s for s, n, _ in SECTIONS}


# nom de sous-dossier local -> libelle affiche (inverse de SECTIONS)
_SUB_TO_LABEL = {s: n for s, n, _ in SECTIONS}


def _candidats_import(sess, st, root):
    """Tout ce qui est depose dans le Drive et pas encore sur le site.

    UN SEUL parcours, utilise par l'apercu ET par l'import : impossible que
    le nombre annonce et le nombre rapatrie se contredisent."""
    deja = {r.get("id") for r in (st.get("uploaded") or {}).values() if r.get("id")}
    vus = st.get("imported") or {}
    trouves = []

    def _prendre(dossier_id, ident, sub):
        exts = (VIDEO_EXTS if sub in ("brutes", "templates", "videos", "pro_videos")
                else IMAGE_EXTS)
        for f in _lister(sess, dossier_id):
            nom = Path(f["name"]).name
            if Path(nom).suffix.lower() not in exts:
                continue
            if vus.get(f["id"]) or f["id"] in deja:
                continue          # deja importe, ou c'est NOUS qui l'avons mis
            trouves.append({"id": f["id"], "nom": nom, "identity": ident, "sub": sub})

    # 1) depot libre : « A IMPORTER / <identite> / <type> »
    racine = None
    for f in _lister(sess, root, dossiers=True):
        if f["name"].strip().lower() == IMPORT_FOLDER_NAME.lower():
            racine = f["id"]
            break
    for ident_dir in (_lister(sess, racine, dossiers=True) if racine else []):
        ident = ident_dir["name"].strip().lower()
        if not ident:
            continue
        for type_dir in _lister(sess, ident_dir["id"], dossiers=True):
            sub = IMPORT_MAP.get(type_dir["name"].strip().lower())
            if sub:
                _prendre(type_dir["id"], ident, sub)

    # 2) l'arborescence normale : depot directement dans le bon dossier
    for dossier in _lister(sess, root, dossiers=True):
        nom_d = dossier["name"].strip()
        if nom_d.lower() in (IMPORT_FOLDER_NAME.lower(), "vault pro"):
            continue
        if _sansaccent(nom_d) == _sansaccent(RACINE_BIBLIO):
            for sous in _lister(sess, dossier["id"], dossiers=True):
                ident_b = sous["name"].strip().lower()
                if not (IDENTITIES_DIR / ident_b).exists():
                    continue
                for typ in _lister(sess, sous["id"], dossiers=True):
                    sub = _DRIVE_TO_SUB.get(typ["name"].strip().lower())
                    if sub:
                        _prendre(typ["id"], ident_b, sub)
            continue
        if nom_d.lower() == "bibliotheque 2":
            for sous in _lister(sess, dossier["id"], dossiers=True):
                ident_v = V2_PREFIX + sous["name"].strip().lower()
                for typ in _lister(sess, sous["id"], dossiers=True):
                    sub = _DRIVE_TO_SUB.get(typ["name"].strip().lower())
                    if sub:
                        _prendre(typ["id"], ident_v, sub)
            continue
        ident = nom_d.lower()          # ancien rangement : identite a la racine
        if not (IDENTITIES_DIR / ident).exists():
            continue
        for typ in _lister(sess, dossier["id"], dossiers=True):
            sub = _DRIVE_TO_SUB.get(typ["name"].strip().lower())
            if sub:
                _prendre(typ["id"], ident, sub)
    return trouves


ATTENTE_FILE = DATA_DIR / "gdrive_attente.json"
VEILLE_SECONDES = 60           # une minute : « je ne veux plus sync a la main »


def attente() -> dict:
    """Dernier resultat connu de la veille, sans appeler Google."""
    d = safe_json.load(ATTENTE_FILE, default={}) or {}
    return d if isinstance(d, dict) else {}


def _veille_une_fois() -> dict:
    res = import_preview()
    safe_json.write(ATTENTE_FILE, res, indent=2)
    return res


def start_watcher(interval: int = VEILLE_SECONDES) -> bool:
    """Surveille les DEUX sens, chaque minute, et agit tout seul :

      - un fichier depose dans le Drive  -> import automatique vers le site ;
      - un fichier ajoute sur le site    -> envoi automatique vers le Drive.

    Le sens site -> Drive se detecte SANS appeler Google (comparaison avec
    l'etat local), donc il ne coute rien. Les deux se coupent depuis la
    config (`auto_import`, `auto_sync`)."""
    def _boucle():
        time.sleep(45)                     # laisse le serveur demarrer
        while True:
            attente = max(30, interval)
            try:
                if available():
                    cfg = load_config()

                    # --- site -> Drive : detection purement locale ---
                    if cfg.get("auto_sync", True):
                        try:
                            rep = sync_report()
                            if rep.get("manque") and status().get("state") != "running":
                                print(f"[gdrive-auto] {rep['manque']} fichier(s) a "
                                      f"envoyer -> synchro auto", flush=True)
                                start_background()
                        except Exception as e:
                            print(f"[gdrive-auto] rapport: {e}", flush=True)

                    # --- Drive -> site : la, il faut interroger Google ---
                    r = _veille_une_fois()
                    if r.get("total"):
                        print(f"[gdrive-veille] {r['total']} fichier(s) a importer",
                              flush=True)
                        if (cfg.get("auto_import", True)
                                and import_status().get("state") != "running"):
                            print("[gdrive-auto] import automatique", flush=True)
                            start_import_background()
            except Exception as e:
                print(f"[gdrive-veille] {type(e).__name__}: {e}", flush=True)
                attente = max(attente, 300)      # en panne : on espace
            time.sleep(attente)

    threading.Thread(target=_boucle, daemon=True, name="gdrive-veille").start()
    print(f"[gdrive-veille] surveillance des 2 sens toutes les "
          f"{max(30, interval)}s (import et envoi automatiques)", flush=True)
    return True


def import_preview() -> dict:
    """Ce qui attend dans le Drive, SANS rien telecharger : combien, chez qui.
    Le bouton d'import partait a l'aveugle avant."""
    cfg = load_config()
    root = folder_id_from(cfg.get("folder") or "")
    if not root:
        raise RuntimeError("dossier Drive non configuré")
    st = _load_state()
    st.setdefault("imported", {})
    cands = _candidats_import(_session(), st, root)
    compte: dict = {}
    for c in cands:
        cle = (c["identity"], c["sub"])
        compte[cle] = compte.get(cle, 0) + 1
    detail = [{"identity": i, "type": _SUB_TO_LABEL.get(sub, sub), "n": n}
              for (i, sub), n in sorted(compte.items(), key=lambda x: -x[1])]
    return {"total": len(cands), "detail": detail, "ts": int(time.time())}


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

    # On liste TOUT d'abord : la barre connait son total des la premiere
    # seconde, au lieu de le voir grossir au fil du parcours.
    cands = _candidats_import(sess, st, root)
    total, imported, errors = len(cands), 0, 0
    _set_import(state="running", total=total, done=0, imported=0, errors=0,
                err="", ts=int(time.time()))
    for n, c in enumerate(cands, 1):
        cible_dir = IDENTITIES_DIR / c["identity"] / c["sub"]
        try:
            cible_dir.mkdir(parents=True, exist_ok=True)
            dst = cible_dir / c["nom"]
            k = 2
            while dst.exists():                # jamais d'ecrasement
                dst = cible_dir / f"{Path(c['nom']).stem}_{k}{Path(c['nom']).suffix}"
                k += 1
            _telecharger(sess, c["id"], dst)
            st["imported"][c["id"]] = {"name": dst.name, "ts": int(time.time())}
            imported += 1
            _save_state(st)
        except Exception as e:
            errors += 1
            _set_import(err=str(e)[:200])
        _set_import(done=n, imported=imported, errors=errors)
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
        if est_v2 and not SYNC_VAULT2:
            continue
        label = (nom[len(V2_PREFIX):] if est_v2 else nom).title()
        plans = [("Bibliotheque 2" if est_v2 else RACINE_BIBLIO, label), SECTIONS]
        parent = root
        for niveau in plans[0]:
            parent = _ensure_folder(sess, parent, niveau, st)
        # TOUS les dossiers, meme ceux dont le contenu ne part pas : ils
        # servent de point de depot et montrent ce qui est vide.
        for sub, drive_name, is_video in SECTIONS:
            _ensure_folder(sess, parent, drive_name, st)
        if not est_v2 and SYNC_VAULT_PRO:    # Vault PRO
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

    # Envois EN PARALLELE : un fichier a la fois plafonnait a ~40/minute, la
    # liaison passait son temps a attendre. L'etat et le cache de dossiers
    # sont partages, donc proteges par un verrou.
    verrou = threading.Lock()

    def _un(job):
        chemin, path = job
        key = "/".join(chemin) + "/" + path.name
        size = path.stat().st_size
        with verrou:
            rec = st["uploaded"].get(key)
        if rec and rec.get("size") == size:
            return ("skip", key, None, 0)
        s_th = _session_thread()
        parent = root
        for niveau in chemin:              # <Bibliothèque>/<Identité>/<Type>
            with verrou:                   # cache partage : jamais 2 creations
                parent = _ensure_folder(s_th, parent, niveau, st)
        fid = _avec_reprise(_upload_file, s_th, parent, path)
        return ("up", key, fid, size)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        futurs = {pool.submit(_un, j): j for j in jobs}
        for fut in as_completed(futurs):
            done += 1
            try:
                quoi, key, fid, size = fut.result()
                if quoi == "skip":
                    skipped += 1
                else:
                    with verrou:
                        st["uploaded"][key] = {"size": size, "id": fid}
                        uploaded += 1
                        if uploaded % 10 == 0:
                            _save_state(st)
            except Exception as e:   # un fichier en échec ne stoppe pas le reste
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
