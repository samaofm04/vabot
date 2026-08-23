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
import pathlib
from pathlib import Path

import safe_json

DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
SA_FILE = DATA_DIR / "google_service_account.json"
CONFIG_FILE = DATA_DIR / "gdrive_sync.json"
STATE_FILE = DATA_DIR / "gdrive_sync_state.json"

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

#: Les fichiers VOISINS d'un media : caption (.txt), description
#: (.desc.txt), brouillon de montage et analyse (.json). Ils ne sont dans
#: aucun filet — data/ est hors git, et le zip de /admin/backup_data saute
#: tout chemin contenant « videos », c'est-a-dire justement les captions
#: des reels. Quelques dizaines de kilo-octets en tout.
#:
#: « .prev » (la copie de secours que safe_json laisse a cote de chaque
#: JSON) en est volontairement absent : c'est un artefact interne, pas du
#: travail a preserver, et le Drive n'a pas a en porter la trace.
SIDECAR_EXTS = {".txt", ".json"}


def _exts_de(sub: str, is_video=None) -> set:
    """Les extensions a traiter pour ce sous-dossier, voisins compris.

    Quatre endroits calculaient cet ensemble chacun de leur cote — la
    montee, la descente, et les deux moities de l'inventaire. Quand deux
    endroits decident la meme chose, ils divergent : c'est exactement ce
    qui avait rendu 598 fichiers du Drive invisibles.
    """
    if is_video is None:
        is_video = sub in ("brutes", "templates", "videos", "pro_videos")
    return (VIDEO_EXTS if is_video else IMAGE_EXTS) | SIDECAR_EXTS


def _est_voisin(nom: str) -> bool:
    """Vrai si ce fichier accompagne un media au lieu d'en etre un.

    Le site les cherche par leur nom EXACT, derive de celui du media
    (« <stem>.txt », « <stem>.example.* »). Renomme, meme d'un « _2 », un
    voisin n'est plus lu par personne.
    """
    return (Path(nom).suffix.lower() in SIDECAR_EXTS
            or ".example." in nom.lower())

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

# Identites qui n'ont rien a faire sur le Drive. Jessye n'est pas une model :
# elle sert de SOURCE au menu US (pseudo et name), elle n'a pas de contenu
# propre a sauvegarder.
EXCLURE_DRIVE = {"jessye"}


def _marche_de(ident: str) -> str:
    """« FR » ou « US » — un niveau de dossier dans le Drive. La regle vit
    dans marche.py, partagee avec le site et le bot."""
    try:
        import marche as _mk
        return _mk.libelle(ident)
    except Exception:
        return "FR"


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
    # Le jeton est ecrit AVANT d'interroger Google : _session() RELIT
    # data/gdrive_oauth.json pour savoir quel compte utiliser. Interroge
    # avant l'ecriture, il ne trouvait que le compte de service et la page
    # affichait SON adresse — precisement le compte qu'on vient de quitter.
    if not safe_json.write(OAUTH_FILE, c, indent=2):
        return "jeton recu mais impossible de l'enregistrer (data/gdrive_oauth.json)"
    try:                                   # a qui appartient ce Drive ?
        d = _session().get("https://www.googleapis.com/drive/v3/about",
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


_CREDS = None
_CREDS_SIG = None
_CREDS_LOCK = threading.Lock()


def _identifiants():
    """Les identifiants Google, fabriques UNE fois puis gardes.

    Chaque appelant en fabriquait des neufs, avec token=None : la premiere
    requete Drive commencait donc TOUJOURS par un aller-retour vers
    oauth2.googleapis.com pour battre un jeton neuf, alors qu'un jeton vaut
    une heure. Une synchro montante en battait treize (un par travailleur, plus
    celui du thread principal) : autant de temps avant le premier octet utile.

    La signature sert de cle : jeton durable + identifiants d'application, donc
    reconnecter un autre compte Google ou se deconnecter refabrique bien les
    identifiants. En mode compte de service, la date et la taille du fichier de
    cle entrent dans la signature : /sheetssync le RE-ECRIT au meme endroit, et
    sans ca une cle remplacee ne prenait effet qu'au redemarrage.
    """
    global _CREDS, _CREDS_SIG
    c = oauth_config()
    sig = (c.get("refresh_token"), c.get("client_id"), c.get("client_secret"))
    if not all(sig):
        try:
            stt = SA_FILE.stat()
            sig += (stt.st_mtime_ns, stt.st_size)
        except OSError:
            sig += (0, 0)
    with _CREDS_LOCK:
        if _CREDS is not None and _CREDS_SIG == sig:
            return _CREDS
        if all(sig[:3]):
            from google.oauth2.credentials import Credentials as UserCreds
            creds = UserCreds(None, refresh_token=sig[0], token_uri=_TOKEN_URI,
                              client_id=sig[1], client_secret=sig[2],
                              scopes=[OAUTH_SCOPE])
        else:
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(
                str(SA_FILE), scopes=[OAUTH_SCOPE])
        _CREDS, _CREDS_SIG = creds, sig
        return creds


def _session():
    """Ton compte Google si connecte (le stockage est le TIEN), sinon le
    compte de service (lecture/dossiers seulement : il n'a pas de quota).

    La session, elle, n'est jamais partagee sans raison (requests.Session
    n'aime pas ca) ; seuls les identifiants — donc le jeton — sont communs.
    Le pool est dimensionne sur le nombre de travailleurs : requests ne garde
    que dix connexions par hote, or _lister_paralleles lance jusqu'a douze
    listages sur UNE session — deux connexions etaient fermees a chaque vague
    et refaisaient la poignee de main TLS au tour suivant.
    """
    from google.auth.transport.requests import AuthorizedSession
    sess = AuthorizedSession(_identifiants())
    try:
        from requests.adapters import HTTPAdapter
        n = max(16, UPLOAD_WORKERS + 4)
        sess.mount("https://", HTTPAdapter(pool_connections=n, pool_maxsize=n))
    except Exception:
        pass
    return sess


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
def _identites_a_sauvegarder():
    """Les identites que la synchro couvre — et celles qu'elle laisse dehors.

    Rend (couvertes, exclues) :
      - couvertes : [(dossier, est_v2, label, biblio)], `biblio` etant le
        chemin Drive au-dessus de l'identite (« Bibliothèque/FR »…) ;
      - exclues   : {nom du dossier: raison}, pour pouvoir le DIRE.

    Trois endroits appliquaient cette regle chacun de leur cote (_iter_jobs,
    _creer_arborescence, sync_report). Resultat : sync_report donnait une
    carte « 100 % — tout est a jour » aux identites de la Bibliotheque 2,
    dont l'envoi ne prend RIEN. Quand deux endroits decident la meme chose,
    ils divergent : on les fusionne.
    """
    couvertes, exclues = [], {}
    if not IDENTITIES_DIR.exists():
        return couvertes, exclues
    for ident_dir in sorted(IDENTITIES_DIR.iterdir()):
        if not ident_dir.is_dir():
            continue
        nom = ident_dir.name
        est_v2 = nom.lower().startswith(V2_PREFIX)
        if est_v2 and not SYNC_VAULT2:
            exclues[nom] = "Bibliotheque 2 hors synchro (SYNC_VAULT2)"
            continue
        if nom.strip().lower() in EXCLURE_DRIVE:
            exclues[nom] = "identite exclue du Drive (EXCLURE_DRIVE)"
            continue
        label = nom[len(V2_PREFIX):] if est_v2 else nom
        # <Bibliotheque>/<FR|US>/<Identite>/<Type> : le marche d'abord, pour
        # ouvrir directement le bon lot.
        biblio = ("Bibliotheque 2" if est_v2
                  else RACINE_BIBLIO + "/" + _marche_de(nom))
        couvertes.append((ident_dir, est_v2, label, biblio))
    return couvertes, exclues


def _compte_fichiers(ident_dir: Path, est_v2: bool = False) -> int:
    """Combien de fichiers cette identite a-t-elle a sauvegarder ?

    Sert a DIRE ce qu'une exclusion laisse dehors : « 14 identites, 3 200
    fichiers » plutot qu'une carte verte a 0 fichier. Memes sections et
    memes extensions que l'envoi — d'ou le meme plan que _iter_jobs : le
    Vault PRO ne compte que s'il est reellement synchronise, sinon le
    chiffre annoncait des fichiers qu'aucune identite n'envoie, exclue ou
    non.
    """
    n = 0
    plan = tuple(SECTIONS) + (() if est_v2 or not SYNC_VAULT_PRO
                              else tuple(SECTIONS_PRO))
    for sub, _drive_name, is_video in plan:
        d = ident_dir / sub
        exts = _exts_de(sub, is_video)
        try:
            n += sum(1 for p in d.iterdir()
                     if p.is_file() and p.suffix.lower() in exts)
        except OSError:
            pass
    return n


def _iter_jobs(include_videos):
    """(chemin Drive, Path fichier) pour TOUT le site.

    `include_videos` est un MODE, pas un booleen : False/"" = photos seules,
    « montage » = + rushs bruts et templates SANS les reels, True/« all » =
    tout. Le passer dans un bool() ramenait « montage » a True, et les reels
    partaient quand meme.

    Rangement dans le Drive : <Bibliothèque>/<Identité>/<Type>. Les trois
    bibliothèques sont couvertes — sans ça, la Bibliothèque 2 arrivait en vrac
    sous « V2_Beta » et le Vault PRO n'était pas sauvegardé du tout."""
    for ident_dir, est_v2, label, biblio in _identites_a_sauvegarder()[0]:
        plan = list(SECTIONS) + ([] if est_v2 or not SYNC_VAULT_PRO else
                                 [(s, n, v, "Vault PRO") for s, n, v in SECTIONS_PRO])
        for entree in plan:
            if len(entree) == 4:
                sub, drive_name, is_video, biblio_x = entree
            else:
                sub, drive_name, is_video = entree
                biblio_x = biblio
            # Le reglage des videos ne concerne que les MEDIAS. Leurs
            # voisins partent toujours : ils pesent quelques dizaines de
            # kilo-octets, et ce sont eux que rien d'autre ne sauvegarde.
            # Avant, repondre « non » au choix des videos coupait aussi la
            # sauvegarde des captions, sans que personne puisse le deviner.
            medias_ecartes = False
            if is_video:
                mode = include_videos
                if not mode:
                    medias_ecartes = True
                # « montage » : les rushs et templates partent, PAS les reels
                # (ce sont eux qui pesent le plus lourd dans le quota).
                elif str(mode).lower() == "montage" and sub in ("videos",
                                                                "pro_videos"):
                    medias_ecartes = True
            exts = _exts_de(sub, is_video)
            folder = ident_dir / sub
            if not folder.exists():
                continue
            for p in sorted(folder.iterdir()):
                if not p.is_file():
                    continue
                suffixe = p.suffix.lower()
                if suffixe not in exts:
                    continue
                # La video exemple pese autant qu'un reel : elle suit le
                # sort des medias. Les captions, non.
                if medias_ecartes and suffixe not in SIDECAR_EXTS:
                    continue
                chemin = (tuple(biblio_x.split("/")) if biblio_x else ()) \
                    + (label.title(), drive_name)
                yield chemin, p


def non_sauvegardes(chemins) -> list:
    """Parmi ces fichiers, ceux dont le Drive n'a pas de copie a jour.

    On reutilise _iter_jobs et l'etat, exactement comme sync_report : la
    regle de « ce qui devrait etre sauvegarde » ne doit exister qu'a un
    seul endroit. Une seconde copie de cette regle finirait par diverger,
    et c'est deja ce qui avait rendu 598 fichiers du Drive invisibles.

    En cas de doute — etat illisible, fichier disparu — on repond « pas
    sauvegarde ». Mieux vaut une alerte de trop qu'un fichier perdu en
    silence.
    """
    voulus = [pathlib.Path(c) for c in chemins]
    if not voulus:
        return []
    try:
        up = (_load_state() or {}).get("uploaded") or {}
        etat = {}
        for chemin, p in _iter_jobs(True):
            try:
                etat[str(p.resolve())] = bool(
                    (up.get("/".join(chemin) + "/" + p.name) or {}).get("size")
                    == p.stat().st_size)
            except OSError:
                pass
    except Exception:
        return list(voulus)
    dehors = []
    for p in voulus:
        try:
            if not etat.get(str(p.resolve()), False):
                dehors.append(p)
        except OSError:
            dehors.append(p)
    return dehors


_MODE_COURANT = object()          # « le reglage enregistre », pas un mode


def sync_report(mode=_MODE_COURANT) -> dict:
    """Etat de la copie Drive, identite par identite.

    Quatre nombres par identite, et ils ne repondent PAS a la meme question :

      - « total » / « sync » : ce que le Drive porte vraiment, toutes
        sections et voisins compris. C'est le pourcentage affiche ;
      - « manque » : l'ecart avec le Drive, soit total - sync ;
      - « a_envoyer » : la part de cet ecart que le mode COURANT enverrait.
        Elle vient du MEME generateur que l'envoi — _iter_jobs(mode) — et
        c'est LE SEUL nombre a utiliser comme declencheur. La veille se
        servait de « manque » : en mode « montage » il comptait des reels
        qui ne partiront jamais, ne descendait donc jamais a zero, et
        relançait une synchro complete toutes les minutes, sans fin ;
      - « hors_mode » : le reste de l'ecart (manque = a_envoyer + hors_mode).
        Remonte, jamais passe sous silence.

    Les identites que la synchro ne touche pas (Bibliotheque 2, EXCLURE_DRIVE)
    n'ont plus de carte : a 0 fichier elles affichaient 100 % et le resume
    disait « tout est a jour » alors que RIEN n'est sauvegarde. Elles sont
    dans « exclues », avec leur raison et leur nombre de fichiers.

    Un fichier compte comme synchronise si son id Drive est connu ET que sa
    taille n'a pas bouge depuis l'envoi."""
    if mode is _MODE_COURANT:
        mode = load_config().get("include_videos")
    st = _load_state()
    up = st.get("uploaded") or {}
    par: dict = {}

    def _e(ident):
        return par.setdefault(ident, {"identity": ident, "total": 0,
                                      "sync": 0, "manque": 0, "octets": 0,
                                      "a_envoyer": 0, "hors_mode": 0})

    couvertes, exclues = _identites_a_sauvegarder()
    for ident_dir, _v2, _lb, _bib in couvertes:
        _e(ident_dir.name)
    # Ce que le mode courant enverrait : exactement la liste de run_sync.
    a_envoyer = {"/".join(chemin) + "/" + p.name
                 for chemin, p in _iter_jobs(mode)}
    for chemin, path in _iter_jobs(True):
        # data/identities/<ident>/<sous-dossier>/<fichier>
        ent = _e(path.parent.parent.name)
        ent["total"] += 1
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        cle = "/".join(chemin) + "/" + path.name
        rec = up.get(cle)
        if rec and rec.get("size") == size:
            ent["sync"] += 1
            continue
        ent["manque"] += 1
        ent["octets"] += max(0, size)
        if cle in a_envoyer:
            ent["a_envoyer"] += 1
        else:
            ent["hors_mode"] += 1
    lignes = []
    for ent in par.values():
        t = ent["total"]
        ent["pct"] = 100 if not t else int(round(ent["sync"] * 100.0 / t))
        lignes.append(ent)
    lignes.sort(key=lambda e: (e["pct"], -e["total"], e["identity"]))
    tot = sum(e["total"] for e in lignes)
    syn = sum(e["sync"] for e in lignes)
    return {"identities": lignes, "total": tot, "sync": syn,
            "manque": sum(e["manque"] for e in lignes),
            "a_envoyer": sum(e["a_envoyer"] for e in lignes),
            "hors_mode": sum(e["hors_mode"] for e in lignes),
            "octets": sum(e["octets"] for e in lignes),
            "pct": 100 if not tot else int(round(syn * 100.0 / tot)),
            "videos": mode if isinstance(mode, str) else bool(mode),
            "exclues": [{"identity": nom, "raison": raison,
                         "fichiers": _compte_fichiers(
                             IDENTITIES_DIR / nom,
                             nom.lower().startswith(V2_PREFIX))}
                        for nom, raison in sorted(exclues.items())],
            "mode": auth_mode(), "email": oauth_email()}


_RAPPORT_CACHE: dict = {"cle": None, "ts": 0.0, "data": None}
_RAPPORT_TTL = 30


def _empreinte_rapport():
    """Ce qui, en changeant, perime le rapport : l'etat des envois et le
    reglage des videos. Deux stat(), la ou le rapport coute deux parcours
    complets de data/identities."""
    out = []
    for f in (STATE_FILE, CONFIG_FILE):
        try:
            s = f.stat()
            out.append((s.st_mtime_ns, s.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def sync_report_cache(ttl: int = _RAPPORT_TTL) -> dict:
    """Le rapport pour l'AFFICHAGE, garde quelques secondes.

    sync_report parcourt DEUX fois tout data/identities (une passe pour ce que
    le mode enverrait, une passe pour l'etat reel) et fait un stat() par
    fichier. L'onglet Drive l'appelait a chaque ouverture, en plein rendu.

    La garde saute des que l'etat des envois bouge (run_sync ecrit STATE_FILE
    tous les 10 fichiers et a la fin) : sans ca, la page invitait a « recharger
    l'onglet pour suivre l'avancement » pendant que les cartes par identite
    restaient figees 30 s.

    La veille, elle, reste sur le chemin NON garde : c'est sur ce rapport
    qu'elle decide de relancer une synchro, et une valeur perimee y a deja
    fabrique une boucle sans fin.
    """
    cle = _empreinte_rapport()
    if (_RAPPORT_CACHE["data"] is not None and _RAPPORT_CACHE["cle"] == cle
            and (time.time() - _RAPPORT_CACHE["ts"]) < ttl):
        return _RAPPORT_CACHE["data"]
    d = sync_report()
    _RAPPORT_CACHE.update(cle=cle, ts=time.time(), data=d)
    return d


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


def _lister_paralleles(sess, taches, echecs=None):
    """Liste PLUSIEURS dossiers a la fois.

    `taches` : liste de (parent_id, dossiers). Retourne {(id, dossiers): files}
    — et **None**, jamais [], pour un dossier dont le listage a ECHOUE.

    C'est toute la difference : rendre une liste vide faisait passer un 429
    passager (12 listages en parallele) pour un dossier vide, sans compteur
    ni trace, et le dossier « Reels » d'une identite disparaissait de la page
    des manques. C'est le mode de panne des 598 fichiers invisibles. `echecs`,
    quand il est fourni, recoit les messages pour pouvoir les REMONTER.
    """
    from concurrent.futures import ThreadPoolExecutor
    taches = list(dict.fromkeys(taches))          # sans doublon
    if not taches:
        return {}
    res = {}

    def _un(t):
        try:
            return t, _lister(sess, t[0], dossiers=t[1]), ""
        except Exception as e:
            return t, None, ("%s: %s" % (type(e).__name__, e))[:160]

    # 5 suffisaient pour une poignee de dossiers ; l'inventaire en ouvre
    # plusieurs centaines d'un coup et attend uniquement le reseau.
    with ThreadPoolExecutor(max_workers=min(12, max(2, len(taches)))) as ex:
        for t, files, err in ex.map(_un, taches):
            res[t] = files
            if err and echecs is not None:
                echecs.append(err)
    return res


def _lister(sess, parent_id, dossiers=False):
    """Le contenu d'un dossier Drive, page par page.

    Chaque page passe par _avec_reprise : ce chemin-la n'en avait aucune,
    alors qu'il est le plus sollicite (12 listages en parallele). Un 429
    passager suffisait a faire remonter un dossier PLEIN comme vide.
    L'erreur remonte a l'appelant plutot que de se confondre avec « rien
    dedans » ; _lister_paralleles la compte.
    """
    q = (f"'{parent_id}' in parents and trashed = false and mimeType "
         + ("=" if dossiers else "!=") + " 'application/vnd.google-apps.folder'")
    out, page = [], None

    def _page(jeton):
        # md5Checksum : Google le calcule pour tout fichier binaire. Deux
        # fichiers de meme taille peuvent differer ; deux empreintes egales,
        # non. C'est ce qui autorise a jeter une copie sans la telecharger.
        prm = {"q": q,
               "fields": "nextPageToken, files(id,name,size,md5Checksum)",
               # Le nettoyage garde « le premier listé » : sans tri, ce n'etait
               # pas le plus ancien mais celui que Drive renvoyait en tete.
               "orderBy": "createdTime",
               "pageSize": 200, "supportsAllDrives": "true",
               "includeItemsFromAllDrives": "true"}
        if jeton:
            prm["pageToken"] = jeton
        r = sess.get("https://www.googleapis.com/drive/v3/files", params=prm, timeout=60)
        _ok(r, "listage d'un dossier")
        return r.json()

    while True:
        d = _avec_reprise(_page, page)
        out += d.get("files") or []
        page = d.get("nextPageToken")
        if not page:
            return out


def _telecharger(sess, file_id, cible: Path):
    """Ecrit le fichier sans jamais lire son contenu.

    Le « .part » n'est PAS une reservation de nom (c'etait le piege : une
    coupure bloquait « reel12.mp4 » pour toujours), juste l'ecriture en
    cours. Reste-t-il d'un essai rate ? Le prochain passage le reecrit, et
    _planifier_noms le compte.
    """
    r = sess.get(f"https://www.googleapis.com/drive/v3/files/{file_id}",
                 params={"alt": "media", "supportsAllDrives": "true"},
                 stream=True, timeout=900)
    _ok(r, "telechargement")          # le message de Google, pas « 403 » nu
    tmp = cible.with_suffix(cible.suffix + ".part")
    with tmp.open("wb") as fh:
        for bloc in r.iter_content(1 << 20):
            if bloc:
                fh.write(bloc)
    tmp.replace(cible)


def _parents_possibles(nom: str) -> list:
    """Les noms dont « nom » pourrait etre une copie, du plus proche au plus loin.

    « pp_69_2_3.png » -> [« pp_69_2.png », « pp_69.png », « pp.png »]

    L'import renomme en _2 quand le nom est pris ; ces copies repartent vers le
    Drive par la synchro montante, et l'import suivant en refait des _2 — d'ou
    les pp_69_2_2 et pp_69_2_3, chaque tour ajoutant une couche.

    On rend la liste plutot qu'un seul nom : « _69 » peut tres bien appartenir
    au nom d'origine. C'est l'EXISTENCE d'un candidat, a taille identique, qui
    tranche — jamais la seule forme du nom.
    """
    import re as _re
    p = Path(nom)
    out, tige = [], p.stem
    while True:
        neuf = _re.sub(r"_\d+$", "", tige)
        if neuf == tige or not neuf:
            break
        out.append(neuf + p.suffix)
        tige = neuf
    return out


def copies_du_dossier(fichiers: list) -> list:
    """Parmi ces fichiers, ceux qui sont des copies d'un autre du meme dossier.

    Rend la liste des fichiers JETABLES — jamais l'original. Deux garde-fous,
    parce qu'un faux positif detruirait du contenu unique :

      - la copie doit deriver d'un nom PRESENT dans ce meme dossier ;
      - les deux doivent peser exactement pareil.

    Un « reel_2.mp4 » sans « reel.mp4 » a cote n'est donc pas touche, ni un
    « IMG_1234.jpg » sous pretexte qu'il ressemble a « IMG.jpg ».
    """
    # Indexer par NOM serait un piege : Drive autorise deux fichiers homonymes
    # dans un dossier, et notre propre synchro en fabrique (un envoi rejoue
    # apres une coupure cree un second fichier au lieu d'ecraser). Le dernier
    # listé ecrasait alors l'autre dans le dictionnaire, et son empreinte
    # servait de verdict a un fichier qui n'etait pas le sien.
    par_nom: dict = {}
    for f in fichiers:
        par_nom.setdefault(Path(f.get("name") or "").name, []).append(f)

    def _unique(nom):
        """Le fichier de ce nom, s'il n'y en a qu'un. Sinon rien : sur des
        homonymes, le raisonnement par nom ne veut plus rien dire."""
        lot = par_nom.get(nom) or []
        return lot[0] if len(lot) == 1 else None

    jetables = []
    for f in fichiers:
        nom = Path(f.get("name") or "").name
        if not nom or not _unique(nom):
            continue
        # Chaque fichier est juge sur SES propres champs, jamais sur ceux d'un
        # homonyme. Sans empreinte, on s'abstient : mieux vaut garder un
        # doublon que perdre un original.
        mon_md5 = f.get("md5Checksum") or ""
        if not mon_md5:
            continue
        origine = None
        for p in _parents_possibles(nom):
            g = _unique(p)
            if g is not None and (g.get("md5Checksum") or "") == mon_md5:
                origine = g
                break
        if origine is None:
            continue
        try:
            taille = int(f.get("size") or 0)
        except Exception:
            taille = 0
        jetables.append({"id": f.get("id"), "nom": nom, "md5": mon_md5,
                         "origine": origine.get("name"),
                         "origine_id": origine.get("id"), "taille": taille})

    # Dernier verrou : pour chaque contenu qu'on s'apprete a jeter, un fichier
    # PORTANT LE MEME MD5 doit rester en place. Sans ce controle, deux regles
    # differentes pouvaient emporter le dernier exemplaire chacune de leur
    # cote. On ne repasse pas la liste en boucle : un seul tour, donc toujours
    # dans le sens prudent.
    ids_jetes = {j["id"] for j in jetables}
    survivants = {(f.get("md5Checksum") or "") for f in fichiers
                  if f.get("id") not in ids_jetes and f.get("md5Checksum")}
    return [j for j in jetables if j["md5"] in survivants]


def _cle_dossier(nom: str) -> str:
    """Nom de dossier Drive ramene a sa forme comparable.

    Sans accents, sans ponctuation, sans casse : « Vidéo brut », « video-brut »
    et « VIDEO BRUT » deviennent la meme chose.
    """
    import re as _re
    import unicodedata as _ud
    t = _ud.normalize("NFKD", nom or "").encode("ascii", "ignore").decode()
    return _re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


# Les noms qu'un dossier Drive peut porter pour chaque section.
#
# Indispensable : le site a affiche tour a tour « Rushs bruts », « Video brut »
# (dans sa propre consigne de depot !) et « Raw video » depuis le passage en
# anglais. Un dossier cree en suivant l'ecran n'etait pas reconnu, et les
# fichiers restaient invisibles sans le moindre message. On accepte donc toutes
# les formes plutot que d'imposer la bonne.
_ALIAS_SECTIONS = {
    "brutes": ["rushs bruts", "rush brut", "rushs brut", "rushes",
               "video brut", "videos brutes", "video brutes", "videos brut",
               "raw video", "raw videos", "brutes", "brut"],
    "videos": ["reels", "reel"],
    "posts": ["posts", "post"],
    "stories": ["stories", "story"],
    "storyctas": ["story cta", "story ctas", "storycta", "cta story",
                  "story cta s"],
    "profile_pics": ["photos de profil", "photo de profil", "profile pics",
                     "profile pictures", "profile pic", "pp"],
    "templates": ["templates montage", "template montage", "montage templates",
                  "templates", "template", "montage"],
}

# nom de dossier Drive -> sous-dossier de l'identite (sens inverse de SECTIONS)
_DRIVE_TO_SUB = {_cle_dossier(n): s for s, n, _ in SECTIONS}
for _sub, _noms in _ALIAS_SECTIONS.items():
    for _n in _noms:
        _DRIVE_TO_SUB.setdefault(_cle_dossier(_n), _sub)


# nom de sous-dossier local -> libelle affiche (inverse de SECTIONS)
_SUB_TO_LABEL = {s: n for s, n, _ in SECTIONS}
_LABEL_TO_SUB = {n: s for s, n, _ in SECTIONS}


# Rempli par le dernier _candidats_import : ce qui a ete ecarte, par raison.
trouves_ignores: dict = {}


def _candidats_import(sess, st, root):
    """Tout ce qui est depose dans le Drive et pas encore sur le site.

    UN SEUL parcours, utilise par l'apercu ET par l'import : impossible que
    le nombre annonce et le nombre rapatrie se contredisent."""
    # Ce que le scan ECARTE, et pourquoi : sans ca, « 0 a importer » ne
    # permettait pas de distinguer « tout est deja la » de « je n'ai rien vu ».
    _ignores: dict = {}
    _inconnus: set = set()      # dossiers deposes sous un nom non reconnu
    _identites_hs: set = set()  # dossiers d'identite inconnus du site
    _echecs: list = []          # listages Drive qui ont echoue
    deja = {r.get("id") for r in (st.get("uploaded") or {}).values() if r.get("id")}
    vus = st.get("imported") or {}
    trouves = []

    def _identite_connue(nom_drive: str, ident: str) -> bool:
        """Le site connait-il cette identite ? Sinon on REFUSE, et on le dit.

        Un dossier mal orthographie dans « A IMPORTER » (« Julia B ») etait
        pris pour argent comptant : run_import faisait mkdir(parents=True) et
        data/identities gagnait une model fantome — visible dans les galeries,
        les menus Discord et la rotation VA — pendant que les fichiers
        n'arrivaient jamais chez la vraie. La branche « arborescence rangee »
        refusait deja ces cas, mais sans un mot.
        """
        if (IDENTITIES_DIR / ident).is_dir():
            return True
        _identites_hs.add((nom_drive or ident).strip())
        return False

    def _prendre(dossier_id, ident, sub, canonique=False, contenu=None):
        """`canonique` : le fichier est deja RANGE au bon endroit du Drive
        (par opposition a un depot libre dans « A IMPORTER »).

        `contenu` : le listage deja fait par l'appelant, par vagues paralleles.
        Sans lui on redemande le dossier ici, un a la fois, et c'est ce mode
        file indienne qui faisait durer le scan."""
        exts = _exts_de(sub)
        try:
            contenu = _lister(sess, dossier_id) if contenu is None else contenu
        except Exception as e:
            # Un dossier illisible (429 passager, permission perdue) ne doit
            # ni passer pour un dossier vide, ni faire echouer le scan
            # ENTIER : les autres identites n'y sont pour rien. On compte, on
            # remonte, on continue.
            _echecs.append(("%s: %s" % (type(e).__name__, e))[:160])
            return
        # Les copies suffixees du dossier, reconnues par le MD5 que Drive
        # renvoie deja dans le listage. Le comptage de l'inventaire et ce
        # scan-ci en jugeaient chacun a sa facon (la taille seule, indexee
        # par nom donc ecrasee entre homonymes) : deux regles pour une seule
        # question, et deux resultats. copies_du_dossier porte les deux
        # garde-fous qu'il faut — empreinte identique, et abstention des
        # qu'un nom est porte par plusieurs fichiers.
        ids_copies = {j["id"] for j in copies_du_dossier(contenu)}
        for f in contenu:
            nom = Path(f["name"]).name
            if Path(nom).suffix.lower() not in exts:
                _ignores["format_non_gere"] = _ignores.get("format_non_gere", 0) + 1
                continue
            # 1) Copie fabriquee par un import precedent : le MEME contenu
            # sous un nom suffixe. Les rapatrier relance le cycle qui a
            # produit les pp_69_2_2 et pp_69_2_3 — chaque tour ajoute une
            # couche.
            #
            # Les VOISINS restent exemptes, et pas pour la raison qu'on
            # croyait. Ce n'est pas que la taille seule confondait deux
            # captions de meme longueur : c'est qu'un voisin n'a de sens que
            # RATTACHE A SON MEDIA. Le md5 ne le sauve pas — deux captions de
            # contenu identique sont NORMALES ici, les textes venant d'un pool
            # commun pose au hasard, et deux captions VIDES ont forcement la
            # meme empreinte. Les soumettre a la meme regle faisait ecarter
            # « f1_2.txt » alors que « f1_2.mp4 » etait un media distinct et
            # bien importe : reel muet, caption orpheline — exactement le
            # symptome que _planifier_noms existe pour eliminer.
            if not _est_voisin(nom) and f.get("id") in ids_copies:
                _ignores["copies_du_drive"] = _ignores.get("copies_du_drive", 0) + 1
                continue
            # 2) Le nom est deja pris sur le site : on n'importe pas. Choix du
            # proprietaire — mieux vaut manquer une version modifiee que
            # remplir la bibliotheque de _2 a trier a la main.
            try:
                if (IDENTITIES_DIR / ident / sub / nom).exists():
                    _ignores["nom_deja_pris"] = _ignores.get("nom_deja_pris", 0) + 1
                    continue
            except Exception:
                pass
            _ignores["vus"] = _ignores.get("vus", 0)
            if vus.get(f["id"]) or f["id"] in deja:
                # …SAUF s'il n'est plus sur le site. Ce test passait avant la
                # verification d'existence locale : un fichier parti du site
                # vers le Drive, puis disparu du site, n'etait donc JAMAIS
                # rapatrie — « tout est sur le Drive, rien sur le site ».
                # Aucun risque de doublon : on ne repart que si le fichier
                # est absent en local, et la protection nom+taille ci-dessous
                # reste active pour tous les autres cas.
                try:
                    if (IDENTITIES_DIR / ident / sub / nom).exists():
                        _ignores["deja_sur_le_site"] = _ignores.get("deja_sur_le_site", 0) + 1
                        continue
                except Exception:
                    continue
            # CEINTURE ET BRETELLES : meme si l'identifiant Drive s'est perdu
            # (etat reecrit, fichier renvoye...), un fichier de meme nom ET de
            # meme taille est deja sur le site — le rapatrier le mettrait en
            # double. C'est ce trou qui a rapatrie 4364 doublons le 15/08.
            try:
                local = IDENTITIES_DIR / ident / sub / nom
                if local.exists():
                    taille = int(f.get("size") or 0)
                    if not taille or local.stat().st_size == taille:
                        _ignores["identique_au_site"] = _ignores.get("identique_au_site", 0) + 1
                        continue
            except Exception:
                pass
            # « src » : le dossier Drive d'ou vient le fichier. Il faut le
            # garder pour que _planifier_noms rattache un voisin a SON media
            # et pas a l'homonyme d'un autre dossier.
            trouves.append({"id": f["id"], "nom": nom, "identity": ident,
                            "sub": sub, "canonique": canonique,
                            "src": dossier_id})

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
        if not _identite_connue(ident_dir["name"], ident):
            continue
        for type_dir in _lister(sess, ident_dir["id"], dossiers=True):
            # Un seul mapping pour tout le module : « A IMPORTER » et la
            # bibliotheque rangee acceptaient des noms differents, si bien
            # qu'un dossier valable d'un cote etait ignore de l'autre.
            sub = _DRIVE_TO_SUB.get(_cle_dossier(type_dir["name"]))
            if sub:
                _prendre(type_dir["id"], ident, sub)
            else:
                # Un dossier au nom inconnu ne disparait plus sans un mot :
                # c'est exactement ce qui laissait « 0 a importer » sans la
                # moindre explication.
                _inconnus.add(type_dir["name"].strip())

    # 2) l'arborescence normale : depot directement dans le bon dossier
    for dossier in _lister(sess, root, dossiers=True):
        nom_d = dossier["name"].strip()
        if nom_d.lower() in (IMPORT_FOLDER_NAME.lower(), "vault pro"):
            continue
        if _sansaccent(nom_d) == _sansaccent(RACINE_BIBLIO):
            for sous in _lister(sess, dossier["id"], dossiers=True):
                nom_s = sous["name"].strip()
                # niveau marche (FR / US) : on descend encore d'un cran
                grappes = ([(x["name"].strip().lower(), x["id"])
                            for x in _lister(sess, sous["id"], dossiers=True)]
                           if nom_s.upper() in ("FR", "US")
                           else [(nom_s.lower(), sous["id"])])
                # Les sous-dossiers de TOUTES les identites sont listes en une
                # fois : c'est la partie qui coutait le plus cher (une
                # quinzaine d'identites x un aller-retour chacune).
                _utiles = [(i, d) for i, d in grappes
                           if _identite_connue(i, i)]
                _types = _lister_paralleles(sess, [(d, True) for _i, d in _utiles],
                                            _echecs)
                _lots = []
                for ident_b, did in _utiles:
                    # None = listage en echec, pas dossier vide : le lot est
                    # deja compte dans _echecs, on ne le prend pas pour du vide.
                    for typ in (_types.get((did, True)) or []):
                        sub = _DRIVE_TO_SUB.get(_cle_dossier(typ["name"]))
                        if sub:
                            _lots.append((typ["id"], ident_b, sub))
                # Le CONTENU de ces dossiers, tous en meme temps. En file
                # indienne c'etait un aller-retour Google par (identite x
                # type) : une quinzaine d'identites font une centaine de
                # requetes l'une apres l'autre, et c'est ce scan-la que la
                # veille refait chaque minute et que le bouton attend.
                _fics = _lister_paralleles(
                    sess, [(_i, False) for _i, _b, _s in _lots], _echecs)
                for _tid, ident_b, sub in _lots:
                    _contenu = _fics.get((_tid, False))
                    if _contenu is None:      # listage en echec, deja compte
                        continue
                    _prendre(_tid, ident_b, sub, canonique=True,
                             contenu=_contenu)
            continue
        if nom_d.lower() == "bibliotheque 2":
            for sous in _lister(sess, dossier["id"], dossiers=True):
                ident_v = V2_PREFIX + sous["name"].strip().lower()
                # Meme regle que les trois autres branches. Sans elle, les
                # fichiers d'une identite que le site ne connait pas etaient
                # proposes a l'import, puis REFUSES au plan (_planifier_noms
                # ne fabrique jamais d'identite) : ils restaient candidats a
                # chaque tour, la veille voyait « N fichier(s) a importer »
                # toutes les minutes et relancait un import qui ne rapatriait
                # rien — sans que personne apprenne quel dossier corriger.
                if not _identite_connue(sous["name"], ident_v):
                    continue
                for typ in _lister(sess, sous["id"], dossiers=True):
                    sub = _DRIVE_TO_SUB.get(_cle_dossier(typ["name"]))
                    if sub:
                        _prendre(typ["id"], ident_v, sub, canonique=True)
            continue
        ident = nom_d.lower()          # ancien rangement : identite a la racine
        if not _identite_connue(nom_d, ident):
            continue
        for typ in _lister(sess, dossier["id"], dossiers=True):
            sub = _DRIVE_TO_SUB.get(_cle_dossier(typ["name"]))
            if sub:
                _prendre(typ["id"], ident, sub, canonique=True)
    try:
        trouves_ignores.clear()
        trouves_ignores.update(_ignores)
        if _inconnus:
            trouves_ignores["dossiers_non_reconnus"] = sorted(_inconnus)[:12]
        if _identites_hs:
            # Le contenu de ces dossiers n'ira nulle part tant que le nom
            # n'est pas corrige : le dire vaut mieux que de creer l'identite.
            trouves_ignores["identites_inconnues_du_site"] = \
                sorted(_identites_hs)[:12]
        if _echecs:
            trouves_ignores["listages_drive_en_echec"] = len(_echecs)
            trouves_ignores["listages_drive_detail"] = _echecs[:3]
    except Exception:
        pass
    return trouves


ATTENTE_FILE = DATA_DIR / "gdrive_attente.json"
VEILLE_SECONDES = 60           # une minute : « je ne veux plus sync a la main »

# Recul apres une synchro terminee EN ERREUR. Sans lui, la veille repartait
# 60 s plus tard : une synchro qui echoue n'envoie rien, « a_envoyer » ne
# descend donc pas, la condition de relance reste vraie et la boucle ne
# s'arrete jamais. Quand la cause est un 429 Drive, relancer toutes les
# minutes AGGRAVE precisement ce qui a fait echouer.
RECUL_APRES_ERREUR = 300       # 5 minutes


def attente() -> dict:
    """Dernier resultat connu de la veille, sans appeler Google."""
    d = safe_json.load(ATTENTE_FILE, default={}) or {}
    return d if isinstance(d, dict) else {}


def _veille_une_fois() -> dict:
    res = import_preview()
    safe_json.write(ATTENTE_FILE, res, indent=2)
    return res


def _recul_synchro(etat: dict, maintenant: float = None) -> float:
    """Combien de secondes attendre avant de relancer une synchro complete.

    0 = on peut y aller. Une synchro qui s'est terminee en erreur n'a, par
    definition, rien envoye : le rapport redemande les memes fichiers au tour
    suivant. Repartir 60 s plus tard donnait une boucle infinie — et sur un
    429 Drive, une boucle qui entretient sa propre cause.
    """
    if (etat or {}).get("state") != "error":
        return 0.0
    try:
        ts = float(etat.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if ts <= 0:                     # sans horodatage, on ne bloque pas
        return 0.0
    reste = RECUL_APRES_ERREUR - ((time.time() if maintenant is None
                                   else maintenant) - ts)
    return max(0.0, reste)


def _tour_envoi_auto(cfg: dict) -> float:
    """Un tour de veille du sens site -> Drive. Rend le recul a respecter (s).

    Sorti de la boucle pour etre verifiable : c'est ici que se decide la
    relance automatique, et c'est ici que la boucle infinie s'ecrivait.
    """
    # Le mode COURANT, pas « tout » : sinon le compteur ne descend jamais a
    # zero (les reels, en mode « montage ») et la synchro complete repartait
    # toutes les minutes, sans fin.
    rep = sync_report(cfg.get("include_videos"))
    if not rep.get("a_envoyer"):
        return 0.0
    etat = status()
    if etat.get("state") == "running":
        return 0.0
    recul = _recul_synchro(etat)
    if recul > 0:
        print(f"[gdrive-auto] derniere synchro en echec "
              f"({etat.get('errors') or 0} fichier(s) : "
              f"{str(etat.get('err') or '')[:80]}) : relance dans "
              f"{int(recul)}s au lieu de {max(30, VEILLE_SECONDES)}s",
              flush=True)
        return recul
    _hm = rep.get("hors_mode") or 0
    print(f"[gdrive-auto] {rep['a_envoyer']} fichier(s) a "
          f"envoyer -> synchro auto"
          + (f" ({_hm} hors du mode courant)" if _hm else ""),
          flush=True)
    start_background()
    return 0.0


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
                            attente = max(attente,
                                          int(_tour_envoi_auto(cfg)) + 1)
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
    return {"total": len(cands), "detail": detail, "ts": int(time.time()),
            "ignores": dict(trouves_ignores)}


_INVENTAIRE_CACHE: dict = {"ts": 0, "data": None}
_INVENTAIRE_TTL = 180          # 3 minutes : le temps de lire la page
_INV_STATUS: dict = {"state": "idle", "err": "", "ts": 0, "etape": ""}
_INV_DELAI_MAX = 420          # au-dela, on considere le comptage perdu


def _inv_etape(texte: str) -> None:
    """Ou en est le comptage — la page l'affiche pendant l'attente."""
    _INV_STATUS["etape"] = texte


def inventaire_lancer() -> dict:
    """Demarre le comptage en arriere-plan et rend la main aussitot.

    Parcourir tout le Drive prend de longues secondes : le faire pendant que
    le navigateur attend donne une page blanche qui « charge » sans fin, et le
    moindre delai d'attente coupe tout sans rien afficher.
    """
    if _INV_STATUS.get("state") == "running":
        # Un thread mort en silence (redemarrage, memoire) laissait l'etat
        # bloque sur « running » : la page se serait rafraichie sans fin.
        if (time.time() - (_INV_STATUS.get("ts") or 0)) < _INV_DELAI_MAX:
            return dict(_INV_STATUS)
        _INV_STATUS.update(state="error", err="comptage interrompu — relance")
    if _INVENTAIRE_CACHE["data"] is not None and \
            (time.time() - _INVENTAIRE_CACHE["ts"]) < _INVENTAIRE_TTL:
        _INV_STATUS.update(state="done", err="", ts=int(time.time()))
        return dict(_INV_STATUS)

    _INV_STATUS.update(state="running", err="", ts=int(time.time()),
                       etape="ouverture du Drive", debut=int(time.time()))

    def _travail():
        try:
            inventaire(force=True)
            _INV_STATUS.update(state="done", err="", ts=int(time.time()),
                               etape="")
        except Exception as e:
            _INV_STATUS.update(state="error", err=str(e)[:200],
                               ts=int(time.time()), etape="")

    threading.Thread(target=_travail, daemon=True,
                     name="gdrive-inventaire").start()
    return dict(_INV_STATUS)


def inventaire_etat() -> dict:
    """L'avancement, et le resultat des qu'il est pret."""
    out = dict(_INV_STATUS)
    if out.get("state") == "done" and _INVENTAIRE_CACHE["data"] is not None:
        out["data"] = _INVENTAIRE_CACHE["data"]
    return out


def inventaire(force: bool = False) -> dict:
    """Ce que le Drive contient, face a ce que le site possede.

    L'apercu d'import ne repond qu'a « qu'est-ce que je vais rapatrier ? ». Il
    peut donc annoncer « rien de nouveau » alors qu'il manque des centaines de
    fichiers : tout ce qu'il n'a pas SU voir — mauvais dossier, extension non
    geree, identite introuvable — n'entre dans aucun de ses compteurs.

    Ici on compte les deux cotes sans rien interpreter, et on montre l'ecart.
    C'est le seul moyen de reponder a « il ne capte pas qu'il lui manque des
    trucs » : encore faut-il regarder ce qu'on N'A PAS.
    """
    if not force and _INVENTAIRE_CACHE["data"] is not None and \
            (time.time() - _INVENTAIRE_CACHE["ts"]) < _INVENTAIRE_TTL:
        return _INVENTAIRE_CACHE["data"]

    cfg = load_config()
    root = folder_id_from(cfg.get("folder") or "")
    if not root:
        raise RuntimeError("dossier Drive non configuré")
    sess = _session()

    cote_drive: dict = {}          # (identite, sub) -> nb de fichiers
    copies = [0]                   # copies suffixees reperees sur le Drive
    inconnus: dict = {}            # nom de dossier ignore -> nb de fichiers
    orphelines: dict = {}          # identite vue sur le Drive, absente du site
    # Un listage qui echoue n'est PAS un dossier vide. Cette page est le
    # dernier recours quand « il manque des trucs » : compter un 429 passager
    # pour zero fichier faisait disparaitre la ligne entiere, sans un mot.
    echecs_listage: list = []
    illisibles: dict = {}          # (identite, type) -> nb de dossiers rates

    # Le parcours se fait par VAGUES : tous les dossiers d'un meme niveau sont
    # listes ensemble. En file indienne, une trentaine d'identites fois sept
    # sous-dossiers font plusieurs centaines d'allers-retours reseau — la page
    # tournait dans le vide plusieurs minutes.

    # vague 1 : la racine
    _inv_etape("lecture de la racine")
    niveau1 = _lister(sess, root, dossiers=True)

    # vague 2 : ce que contiennent « Bibliothèque » et « A IMPORTER »
    a_ouvrir, identites = [], []          # identites = (nom, id du dossier)
    for dossier in niveau1:
        nom_d = dossier["name"].strip()
        if nom_d.lower() == "vault pro":
            continue
        if nom_d.lower() == IMPORT_FOLDER_NAME.lower() or \
                _sansaccent(nom_d) == _sansaccent(RACINE_BIBLIO):
            a_ouvrir.append(dossier["id"])
        else:                              # ancien rangement : identite a la racine
            identites.append((nom_d.lower(), dossier["id"]))
    contenus = _lister_paralleles(sess, [(d, True) for d in a_ouvrir],
                                  echecs_listage)

    # vague 3 : sous « Bibliothèque », un niveau FR/US s'intercale
    marches = []
    for did in a_ouvrir:
        for sous in (contenus.get((did, True)) or []):
            nom_s = sous["name"].strip()
            if nom_s.upper() in ("FR", "US"):
                marches.append(sous["id"])
            else:
                identites.append((nom_s.lower(), sous["id"]))
    for cle, files in _lister_paralleles(sess, [(m, True) for m in marches],
                                         echecs_listage).items():
        for x in (files or []):
            identites.append((x["name"].strip().lower(), x["id"]))

    # vague 4 : les sous-dossiers de chaque identite
    _inv_etape("%d identite(s) trouvee(s)" % len(identites))
    types = _lister_paralleles(sess, [(d, True) for _i, d in identites],
                               echecs_listage)

    # vague 5 : le contenu de chaque sous-dossier, tout en meme temps
    a_compter = []                         # (id, identite, sub|None, connue)
    for ident, did in identites:
        connue = (IDENTITIES_DIR / ident).exists()
        if types.get((did, True)) is None:
            # Les sous-dossiers de cette identite n'ont pas pu etre listes :
            # on ne sait RIEN d'elle, ce n'est pas la meme chose que « vide ».
            illisibles[(ident, "(tous les dossiers)")] = \
                illisibles.get((ident, "(tous les dossiers)"), 0) + 1
            continue
        for typ in types.get((did, True)):
            sub = _DRIVE_TO_SUB.get(_cle_dossier(typ["name"]))
            a_compter.append((typ["id"], ident, sub, connue,
                              typ["name"].strip()))
    _inv_etape("comptage de %d dossier(s)" % len(a_compter))
    fichiers = _lister_paralleles(sess, [(t[0], False) for t in a_compter],
                                  echecs_listage)

    for did, ident, sub, connue, nom_typ in a_compter:
        liste = fichiers.get((did, False))
        if liste is None:
            # Listage en echec : ce dossier n'est pas vide, son contenu est
            # INCONNU. Le compter pour zero, c'est le mode de panne des 598
            # fichiers invisibles — la ligne n'apparaissait meme pas ici.
            cle_ill = (ident, _SUB_TO_LABEL.get(sub, nom_typ))
            illisibles[cle_ill] = illisibles.get(cle_ill, 0) + 1
            continue
        if not sub:
            if liste:
                inconnus[nom_typ] = inconnus.get(nom_typ, 0) + len(liste)
            continue
        if not connue:
            # Le scan d'import saute purement et simplement ces dossiers :
            # sans cette ligne, leurs fichiers restaient introuvables.
            if liste:
                orphelines[ident] = orphelines.get(ident, 0) + len(liste)
            continue
        exts = _exts_de(sub)
        # Meme regle que le scan d'import, et le meme code : les copies se
        # reconnaissent au md5, jamais a la seule taille.
        ids_copies = {j["id"] for j in copies_du_dossier(liste)}
        n = 0
        for f in liste:
            nom = Path(f["name"]).name
            if Path(nom).suffix.lower() not in exts:
                continue
            # Les copies (« pp_69_2.png » a cote de « pp_69.png », meme
            # contenu) ne sont pas du contenu manquant : les compter gonflait
            # l'ecart et faisait croire a des centaines de fichiers perdus.
            if f.get("id") in ids_copies:
                copies[0] += 1
                continue
            n += 1
        if n:
            cote_drive[(ident, sub)] = cote_drive.get((ident, sub), 0) + n

    # Cote site : on compte les memes paires, sans se fier a un quelconque etat
    lignes = []
    for (ident, sub), n_drive in cote_drive.items():
        d = IDENTITIES_DIR / ident / sub
        exts = _exts_de(sub)
        try:
            n_site = sum(1 for p in d.iterdir()
                         if p.is_file() and p.suffix.lower() in exts)
        except Exception:
            n_site = 0
        lignes.append({"identity": ident, "type": _SUB_TO_LABEL.get(sub, sub),
                       "drive": n_drive, "site": n_site,
                       "manque": max(0, n_drive - n_site)})
    # Ce que l'IMPORT, lui, compte prendre. Sans cette confrontation, la page
    # dit « il manque 192 fichiers » pendant que le bouton propose d'en
    # importer 2, sans que rien n'explique l'ecart.
    _inv_etape("analyse de ce que l'import sait voir")
    vus_import: dict = {}
    raisons: dict = {}
    try:
        st = _load_state()
        st.setdefault("imported", {})
        for c in _candidats_import(sess, st, root):
            cle = (c["identity"], c["sub"])
            vus_import[cle] = vus_import.get(cle, 0) + 1
        raisons = dict(trouves_ignores)
    except Exception as e:
        raisons = {"erreur": str(e)[:150]}
    if echecs_listage:
        # Range dans « raisons_import » parce que c'est le seul bloc que la
        # page affiche : un listage rate DOIT se voir, sinon la page annonce
        # « rien ne manque » sur un Drive qu'elle n'a pas su lire.
        #
        # On AJOUTE : le scan d'import remplit deja la meme cle (il a ses
        # propres listages), et l'ecraser effacait ses echecs a lui — le
        # comptage du Drive faisait disparaitre en silence ceux de l'import.
        try:
            _deja = int(raisons.get("listages_drive_en_echec") or 0)
        except Exception:
            _deja = 0
        raisons["listages_drive_en_echec"] = _deja + len(echecs_listage)
        raisons["listages_drive_detail"] = (
            list(raisons.get("listages_drive_detail") or []) + echecs_listage)[:3]
    for r in lignes:
        sub = _LABEL_TO_SUB.get(r["type"], r["type"])
        r["import"] = vus_import.get((r["identity"], sub), 0)
        r["invisible"] = max(0, r["manque"] - r["import"])

    lignes.sort(key=lambda r: (-r["manque"], r["identity"]))
    resultat = {
        "raisons_import": raisons,
        "copies_drive": copies[0],
        "listages_echoues": len(echecs_listage),
        "listages_echoues_detail": echecs_listage[:10],
        "dossiers_illisibles": [{"identity": i, "type": t, "n": n}
                                for (i, t), n in sorted(illisibles.items())],
        "total_import": sum(r.get("import", 0) for r in lignes),
        "total_invisible": sum(r.get("invisible", 0) for r in lignes),
        "lignes": lignes,
        "total_drive": sum(r["drive"] for r in lignes),
        "total_site": sum(r["site"] for r in lignes),
        "total_manque": sum(r["manque"] for r in lignes),
        "dossiers_non_reconnus": [{"nom": k, "n": v}
                                  for k, v in sorted(inconnus.items(),
                                                     key=lambda x: -x[1])],
        "identites_inconnues": [{"nom": k, "n": v}
                                for k, v in sorted(orphelines.items(),
                                                   key=lambda x: -x[1])],
        "ts": int(time.time()),
    }
    _INVENTAIRE_CACHE["ts"] = time.time()
    _INVENTAIRE_CACHE["data"] = resultat
    return resultat


def _tige_media(nom: str) -> str:
    """Le nom (sans extension) du media auquel ce fichier se rattache.

    « reel12.mp4 » -> « reel12 » ; « reel12.desc.txt » -> « reel12 » ;
    « reel12.example.mp4 » -> « reel12 ». Le site cherche les voisins par ce
    nom EXACT (<stem>.txt, <stem>.desc.txt, <stem>.montage.json…) : quand le
    media est renomme, ils doivent l'etre avec lui, sinon la caption reste
    orpheline a cote d'un reel muet.
    """
    bas = (nom or "").lower()
    i = bas.find(".example.")
    if i > 0:
        return nom[:i]
    p = Path(nom or "")
    if p.suffix.lower() in SIDECAR_EXTS:
        tige = p.stem                      # « reel12.desc » pour .desc.txt
        for marq in (".desc", ".acheck", ".montage", ".analyse"):
            if tige.lower().endswith(marq):
                return tige[:-len(marq)]
        return tige
    return p.stem


def _planifier_noms(cands: list) -> tuple:
    """Le nom LOCAL de chaque fichier a importer, choisi AVANT tout envoi.

    Rend (noms, conflits, parts, refuses) :
      - noms     : id Drive -> nom du fichier a ecrire (absent = on renonce) ;
      - conflits : voisins abandonnes parce que leur nom est deja pris ;
      - parts    : restes de telechargements interrompus rencontres ;
      - refuses  : fichiers d'une identite que le site ne connait pas.

    Pourquoi d'avance, et en un seul fil :

      - un media renomme (« reel12_2.mp4 », parce que « reel12.mp4 » existe
        deja) doit emporter SES VOISINS. Decide fichier par fichier dans un
        pool de cinq, la caption etait ecrite « reel12.txt » pendant que son
        media devenait « reel12_2.mp4 » : caption orpheline, reel muet ;
      - un « .part » laisse par un telechargement coupe (un 403, ou le
        redemarrage du VPS pendant l'import — c'est-a-dire a CHAQUE
        deploiement) ne reserve plus le nom. Il etait relu comme « nom pris »
        a tous les tours suivants : « reel12.mp4 » restait bloque pour
        toujours et chaque passage ajoutait un _2. Le telechargement suivant
        reecrit ce fichier de toute facon ; on se contente de le COMPTER,
        parce que ce module ne supprime rien (garde-fou du module, verifie
        par tests_site.py).
    """
    noms: dict = {}
    conflits = refuses = parts = 0
    pris: dict = {}                    # (identite, sub) -> noms deja attribues
    vus_dossiers: set = set()
    groupes: dict = {}
    for c in cands:
        # Un media et ses voisins forment UN lot : meme DOSSIER D'ORIGINE,
        # meme tige, meme sort.
        #
        # Sans le dossier d'origine, deux depots portant le meme nom (le meme
        # reel dans « A IMPORTER » et dans la bibliotheque rangee) tombaient
        # dans le meme lot : un seul media y gagnait le suffixe « _2 », et la
        # caption du second etait comptee en conflit puis abandonnee, pendant
        # que son media, lui, entrait sous « r1_2.mp4 ». Reel muet, caption
        # perdue — reproduit a l'execution.
        groupes.setdefault((c["identity"], c["sub"], str(c.get("src") or ""),
                            _tige_media(c["nom"])), []).append(c)
    for (ident, sub, _src, tige), lot in sorted(groupes.items()):
        if not (IDENTITIES_DIR / ident).is_dir():
            # Ceinture et bretelles avec le scan : jamais fabriquer une
            # identite a partir d'un nom de dossier Drive. mkdir(parents=True)
            # creait une model fantome dans data/identities — visible dans les
            # galeries, les menus Discord et la rotation VA.
            refuses += len(lot)
            continue
        dossier = IDENTITIES_DIR / ident / sub
        deja = pris.setdefault((ident, sub), set())
        if dossier not in vus_dossiers:
            vus_dossiers.add(dossier)
            try:
                parts += sum(1 for _p in dossier.glob("*.part"))
            except OSError:
                pass

        def _libre(n, _d=dossier, _pris=deja):
            return n not in _pris and not (_d / n).exists()

        # Les medias d'abord : c'est le media qui fixe le suffixe du lot.
        lot.sort(key=lambda c: (_est_voisin(c["nom"]), c["nom"]))
        suffixe = ""
        media = next((c for c in lot if not _est_voisin(c["nom"])), None)
        if media is not None:
            ext = Path(media["nom"]).suffix
            k = 2
            while not _libre(tige + suffixe + ext):
                suffixe = "_%d" % k
                k += 1
        for c in lot:
            nom = c["nom"]
            cible = (tige + suffixe + nom[len(tige):]
                     if suffixe and nom.startswith(tige) else nom)
            if not _libre(cible):
                if _est_voisin(nom):
                    # Un voisin renomme « IMG.desc_2.txt » n'est plus lu par
                    # personne : le site cherche le nom EXACT derive du media.
                    # Mieux vaut renoncer et le compter que de deposer un
                    # fichier que rien ne rattachera jamais — et qui
                    # repartirait sur le Drive a chaque synchro.
                    conflits += 1
                    continue
                p = Path(nom)
                k = 2
                while not _libre("%s_%d%s" % (p.stem, k, p.suffix)):
                    k += 1
                cible = "%s_%d%s" % (p.stem, k, p.suffix)
            noms[c["id"]] = cible
            deja.add(cible)
    return noms, conflits, parts, refuses


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
    ecrases = 0                  # noms pris entre le plan et le telechargement
    # Les noms de destination sont choisis ICI, en un seul fil, medias et
    # voisins ensemble : voir _planifier_noms.
    plan, conflits, parts_orphelins, refuses = _planifier_noms(cands)
    if parts_orphelins or refuses:
        print(f"[gdrive-import] {parts_orphelins} telechargement(s) interrompu(s) "
              f"retrouve(s), {refuses} fichier(s) d'identite inconnue refuse(s)",
              flush=True)
    _set_import(state="running", total=total, done=0, imported=0, errors=0,
                err="", voisins_en_conflit=conflits,
                parts_orphelins=parts_orphelins, identites_refusees=refuses,
                ts=int(time.time()))
    # Telechargements EN PARALLELE. Un import passe l'essentiel de son temps a
    # attendre le reseau : les faire un par un multipliait la duree par le
    # nombre de fichiers. Cinq a la fois, c'est net sans bousculer l'API.
    # Le verrou protege l'etat partage (compteurs, fichier d'etat) ; les noms
    # de destination, eux, sont deja attribues par _planifier_noms — deux
    # fichiers ne peuvent donc pas viser la meme cible.
    from concurrent.futures import ThreadPoolExecutor
    import threading as _th

    _verrou = _th.Lock()
    _faits = {"n": 0}

    def _un_fichier(c):
        nonlocal imported, errors, ecrases
        try:
            nom_local = plan.get(c["id"])
            if not nom_local:
                # Ecarte au plan (voisin en conflit, identite inconnue) : il
                # y est deja compte, on ne le compte pas deux fois.
                return
            cible_dir = IDENTITIES_DIR / c["identity"] / c["sub"]
            dst = cible_dir / nom_local
            # Le dossier de l'IDENTITE existe forcement (verifie au plan) :
            # seul le sous-dossier de type peut manquer.
            cible_dir.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                # Le nom etait libre au moment du plan ; s'il ne l'est plus
                # (un envoi depuis le site pendant l'import), on renonce :
                # _telecharger finit par un replace() qui ecraserait le
                # fichier en place.
                with _verrou:
                    ecrases += 1
                    _set_import(noms_pris=ecrases)
                return
            _telecharger(sess, c["id"], dst)
            with _verrou:
                st["imported"][c["id"]] = {"name": dst.name, "ts": int(time.time())}
                # Il etait DEJA range au bon endroit du Drive : sans cette
                # ligne, la synchro le renverrait juste a cote de lui-meme.
                if c.get("canonique"):
                    try:
                        cle = "/".join((RACINE_BIBLIO, _marche_de(c["identity"]),
                                        c["identity"].title(),
                                        _SUB_TO_LABEL.get(c["sub"], c["sub"]),
                                        dst.name))
                        st.setdefault("uploaded", {})[cle] = {
                            "size": dst.stat().st_size, "id": c["id"]}
                    except Exception:
                        pass
                imported += 1
                _save_state(st)
        except Exception as e:
            with _verrou:
                errors += 1
                _set_import(err=str(e)[:200])
        finally:
            # TOUJOURS, meme sur un abandon : un fichier ecarte compte dans le
            # total, et sans ce finally la barre d'avancement restait bloquee
            # sous 100 % jusqu'a la fin de l'import.
            with _verrou:
                _faits["n"] += 1
                _set_import(done=_faits["n"], imported=imported, errors=errors)

    if cands:
        with ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(_un_fichier, cands))
    _save_state(st)
    res = {"total": total, "imported": imported, "errors": errors,
           "voisins_en_conflit": conflits, "noms_pris": ecrases,
           "parts_orphelins": parts_orphelins, "identites_refusees": refuses,
           "ts": int(time.time())}
    _set_import(state="done", **res)
    return res


def _creer_arborescence(sess, root, st, include_videos):
    """Cree le dossier de CHAQUE identite et de chaque type, meme sans fichier.
    Ainsi tout est visible dans le Drive et on sait ou deposer.

    Les identites couvertes sont celles de _identites_a_sauvegarder : la
    regle vivait ici en double, et une identite ecartee de l'envoi recevait
    quand meme son arborescence."""
    _racine_biblio(sess, root, st)       # remet le cache d'aplomb si besoin
    for _ident_dir, est_v2, label_brut, biblio in _identites_a_sauvegarder()[0]:
        label = label_brut.title()
        parent = root
        for niveau in tuple(biblio.split("/")) + (label,):
            parent = _ensure_folder(sess, parent, niveau, st)
        # TOUS les dossiers, meme ceux dont le contenu ne part pas : ils
        # servent de point de depot et montrent ce qui est vide.
        for _sub, drive_name, _is_video in SECTIONS:
            _ensure_folder(sess, parent, drive_name, st)
        if not est_v2 and SYNC_VAULT_PRO:    # Vault PRO
            pro = _ensure_folder(sess, root, "Vault PRO", st)
            pro_ident = _ensure_folder(sess, pro, label, st)
            for _sub, drive_name, _is_video in SECTIONS_PRO:
                _ensure_folder(sess, pro_ident, drive_name, st)


_RANGEMENT_ERR: list = []


def _normaliser_cles(st) -> int:
    """Insere le niveau FR/US dans les cles de l'etat.

    INCONDITIONNEL et idempotent : la premiere version ne le faisait que si
    des dossiers avaient bouge, et un rangement deja effectue (ou effectue a
    moitie) laissait les cles a l'ancien format — la synchro croyait alors
    que TOUT etait a envoyer et recopiait 2900 fichiers a cote."""
    up = st.get("uploaded") or {}
    pref = RACINE_BIBLIO + "/"
    nouveau, change = {}, 0
    for cle, val in up.items():
        if cle.startswith(pref):
            reste = cle[len(pref):]
            tete = reste.split("/", 1)[0]
            if tete.upper() not in ("FR", "US"):
                cle = pref + _marche_de(tete.lower()) + "/" + reste
                change += 1
        nouveau[cle] = val
    if change:
        st["uploaded"] = nouveau
        _save_state(st)
        print(f"[gdrive] {change} cle(s) rangee(s) par marche", flush=True)
    return change


def _racine_biblio(sess, root, st) -> str:
    """Id du dossier « Bibliothèque », verifie a chaque passage.

    Le cache local avait garde l'id d'un dossier mis a la corbeille : tout
    partait dans un arbre fantome, et l'ancien contenu paraissait absent."""
    cle = f"{root}/{RACINE_BIBLIO}"
    fid = (st.get("folders") or {}).get(cle)
    if fid:
        try:
            r = sess.get(
                "https://www.googleapis.com/drive/v3/files/" + fid,
                params={"fields": "id,trashed", "supportsAllDrives": "true"},
                timeout=30)
            mort = (r.status_code == 404
                    or (r.status_code < 400 and (r.json() or {}).get("trashed")))
        except Exception:
            mort = False       # panne passagere : on GARDE le cache, sinon
                               # une coupure reseau ferait recreer tout l'arbre
        if not mort:
            return fid
        # id positivement mort : on le jette AVEC tout ce qui en descendait
        st["folders"] = {k: v for k, v in (st.get("folders") or {}).items()
                         if k != cle and not k.startswith(f"{fid}/")}
    return _ensure_folder(sess, root, RACINE_BIBLIO, st)


def _regrouper_par_marche(sess, root, st) -> int:
    """Range les identites deja presentes sous « Bibliotheque » dans un
    sous-dossier FR ou US — en les DEPLACANT, pas en les recopiant.

    Sans ca, ajouter ce niveau aurait fait repartir les 2144 fichiers vers
    de nouveaux dossiers et laisse les anciens a cote. Idempotent : une fois
    range, il n'y a plus rien a bouger."""
    biblio = _racine_biblio(sess, root, st)
    _RANGEMENT_ERR.clear()
    marches = {}
    bouges = 0
    for f in _lister(sess, biblio, dossiers=True):
        nom = (f["name"] or "").strip()
        if nom.upper() in ("FR", "US"):
            marches[nom.upper()] = f["id"]
    for f in _lister(sess, biblio, dossiers=True):
        nom = (f["name"] or "").strip()
        if nom.upper() in ("FR", "US") or not nom:
            continue
        cible = _marche_de(nom.lower())
        if cible not in marches:
            marches[cible] = _ensure_folder(sess, biblio, cible, st)
        try:
            r = sess.patch(
                "https://www.googleapis.com/drive/v3/files/" + f["id"]
                + "?addParents=" + marches[cible] + "&removeParents=" + biblio
                + "&fields=id&supportsAllDrives=true",
                json={}, timeout=60)
            if r.status_code < 400:
                bouges += 1
                st["folders"][f"{marches[cible]}/{nom}"] = f["id"]
                st["folders"].pop(f"{biblio}/{nom}", None)
            else:
                _RANGEMENT_ERR.append(f"{nom} : HTTP {r.status_code} "
                                      f"{(r.text or '')[:120]}")
        except Exception as e:
            _RANGEMENT_ERR.append(f"{nom} : {e}"[:160])
    if bouges:
        print(f"[gdrive] {bouges} identite(s) rangee(s) par marche", flush=True)
    return bouges


def run_sync() -> dict:
    """Synchro complète (bloquant — à lancer via start_background)."""
    cfg = load_config()
    root = folder_id_from(cfg.get("folder") or "")
    if not root:
        raise RuntimeError("dossier Drive non configuré")
    # PAS de bool() : _iter_jobs distingue "" (photos seules), « montage »
    # (rushs et templates, sans les reels) et True. bool("montage") valait
    # True — le select affichait « Reel montage » et tous les reels partaient
    # quand meme, /gdrive/debug_state annoncant, lui, le bon mode.
    include_videos = cfg.get("include_videos")
    st = _load_state()
    sess = _session()

    # Arborescence COMPLETE d'abord : on veut voir tous les dossiers dans le
    # Drive meme vides — c'est la qu'on depose, et ca montre ce qui manque.
    try:
        _normaliser_cles(st)                      # les cles d'abord
        _regrouper_par_marche(sess, root, st)     # puis les dossiers
        # Garde-fou : si une identite est restee a plat sous « Bibliotheque »,
        # ses fichiers ont une ancienne cle et TOUT repartirait en double dans
        # le nouvel arbre. Mieux vaut ne rien envoyer et le dire.
        _biblio_id = _racine_biblio(sess, root, st)
        _restants = [f["name"] for f in _lister(sess, _biblio_id, dossiers=True)
                     if (f["name"] or "").strip().upper() not in ("FR", "US")]
        if _restants:
            raise RuntimeError(
                "rangement par marché impossible ("
                + ", ".join(_restants[:4])
                + (f" +{len(_restants) - 4}" if len(_restants) > 4 else "")
                + ") — synchro annulée pour ne pas tout renvoyer en double. "
                + ("Détail : " + " | ".join(_RANGEMENT_ERR[:2])
                   if _RANGEMENT_ERR else ""))
        _creer_arborescence(sess, root, st, include_videos)
        _save_state(st)
    except Exception as e:
        _set_status(state="error", err=str(e)[:300], ts=int(time.time()))
        raise

    jobs = list(_iter_jobs(include_videos))
    total = len(jobs)
    done = skipped = uploaded = errors = 0
    _set_status(state="running", total=total, done=0, uploaded=0,
                skipped=0, errors=0, err="", ts=int(time.time()))

    # Envois EN PARALLELE : un fichier a la fois plafonnait a ~40/minute, la
    # liaison passait son temps a attendre. L'etat et le cache de dossiers
    # sont partages, donc proteges par un verrou.
    verrou = threading.Lock()

    # Ce que le Drive contient DEJA, dossier par dossier (un seul listage
    # REUSSI par dossier). Sans ca, une comptabilite perdue faisait
    # re-televerser des fichiers deja presents : d'ou des triplicats.
    index_dossiers: dict = {}
    INDEX_ESSAIS = 2               # deux listages par dossier, pas plus

    def _index(parent_id):
        """Le contenu du dossier Drive — ou une ERREUR, jamais « vide ».

        Un listage qui echoue etait rendu comme un dossier vide, et le
        resultat mis en cache pour toute la synchro : le dossier entier
        repartait une seconde fois. C'est exactement la comptabilite perdue
        que cet index existe pour eviter, et c'est ainsi qu'on a obtenu des
        triplicats — sans un compteur ni une trace.

        L'echec, lui, n'etait mesure qu'UNE fois et garde pour toute la
        synchro : un seul 429 passager condamnait alors les 500 fichiers du
        dossier jusqu'a la fin du run. Comme rien ne partait, « a_envoyer »
        ne descendait pas et la veille relançait la meme synchro toutes les
        minutes — sur la cause meme du 429. On retente donc le listage
        (INDEX_ESSAIS), et le premier fichier du dossier n'est plus perdu
        pour un dossier qui repond a la seconde tentative.

        Les essais restent bornes — _lister reprend deja quatre fois en
        s'espacant, et marteler un dossier qui repond 429 entretient le 429.
        Quota epuise : le dossier est memorise en echec (les fichiers
        suivants echouent SANS rappeler Google), ils comptent en erreur et
        sont remontes, et le recul de la veille (RECUL_APRES_ERREUR) laisse
        au Drive le temps de respirer avant le passage suivant.
        """
        idx = index_dossiers.get(parent_id)
        if idx is None:
            for _essai in range(INDEX_ESSAIS):
                try:
                    neuf = {}
                    for f in _lister(_session_thread(), parent_id):
                        neuf[f.get("name")] = (f.get("id"),
                                               int(f.get("size") or 0))
                    idx = neuf
                    break
                except Exception as e:
                    idx = ("%s: %s" % (type(e).__name__, e))[:160]
            index_dossiers[parent_id] = idx
        if isinstance(idx, str):
            raise RuntimeError("listage du dossier Drive impossible — envoi "
                               "reporte pour ne pas creer de doublon (" + idx + ")")
        return idx

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
        with verrou:
            # L'index est pris UNE fois, avant l'envoi : s'il devait echouer,
            # mieux vaut le savoir maintenant qu'apres avoir depose le fichier
            # — une erreur levee apres l'envoi le laisserait hors de l'etat, et
            # le passage suivant l'enverrait une seconde fois.
            idx = _index(parent)
            deja_bas = idx.get(path.name)
        if deja_bas and deja_bas[1] == size:
            # meme nom, meme taille, deja dans CE dossier du Drive : on ne
            # renvoie pas, on note simplement son identifiant
            return ("deja", key, deja_bas[0], size)
        fid = _avec_reprise(_upload_file, s_th, parent, path)
        with verrou:
            idx[path.name] = (fid, size)
        return ("up", key, fid, size)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        futurs = {pool.submit(_un, j): j for j in jobs}
        for fut in as_completed(futurs):
            done += 1
            try:
                quoi, key, fid, size = fut.result()
                if quoi == "deja":         # deja sur le Drive : on comptabilise
                    with verrou:
                        st["uploaded"][key] = {"size": size, "id": fid}
                    skipped += 1
                elif quoi == "skip":
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
    # « done » ne se dit que si tout est passe. La barre du dashboard affiche
    # « ✓ termine » a 100 % des que l'etat vaut « done » : une synchro ou
    # aucun fichier n'est parti s'annoncait donc terminee. C'est aussi cet
    # etat que la veille regarde pour prendre du recul (RECUL_APRES_ERREUR)
    # au lieu de relancer la meme synchro 60 s plus tard.
    _set_status(state=("error" if errors else "done"), **res)
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
                # Horodater l'echec : c'est sur ce « ts » que la veille
                # calcule son recul. Sans lui, une synchro tombee avant le
                # premier envoi gardait la date de la precedente et la
                # relance repartait aussitot.
                _set_status(state="error", err=str(e)[:300],
                            ts=int(time.time()))

        _THREAD = threading.Thread(target=_run, name="gdrive-sync", daemon=True)
        _THREAD.start()
        return True
