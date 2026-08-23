"""Page « Création de vidéos » — branche le pipeline Node (dossier noctus/) sur
le dashboard Flask. Le pipeline tourne en subprocess (node noctus_runner.js) et
écrit data/noctus/models/<id>/_status.json que la page poll.

Wiring dans web_upload.create_app() :
    import noctus_web
    noctus_web.register(app, is_auth, _error, _success)
Et pour le contenu de l'onglet :
    noctus_web.render_page()
"""
import os
import re
import json
import shutil
import subprocess
import threading
from pathlib import Path
import safe_json

# Sérialise lecture+écriture de captions.json (partagé) + spawn du runner, pour ne pas
# perdre le label d'une génération concurrente (2 VA cliquent « Reel monté » en même temps).
_GEN_LOCK = threading.Lock()

BOT_DIR = Path(__file__).parent.resolve()
NOCTUS_SRC = BOT_DIR / "noctus"                 # pipeline-core.js + runner + fonts
NOCTUS_DATA = BOT_DIR / "data" / "noctus"       # données user (models/, captions.json, temp/)
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
V_FOLDERS = [f"V{i}" for i in range(1, 11)]

_PROCS = {}  # model_id -> subprocess.Popen

# Générations dont l'ASSEMBLAGE tourne, avant que le process Node existe.
# _PROCS ne les connaît pas encore : la préparation dure des dizaines de secondes
# (un ffmpeg par variante) et pendant tout ce temps le dossier n'était protégé de
# la purge que par sa fraîcheur — 12 générations lancées entre-temps et input/
# disparaissait sous les pieds de l'assemblage.
_EN_PREPARATION = set()
_PREP_LOCK = threading.Lock()


def _marquer_preparation(mid: str, actif: bool):
    if not mid:
        return
    with _PREP_LOCK:
        if actif:
            _EN_PREPARATION.add(mid)
        else:
            _EN_PREPARATION.discard(mid)


# Node "embarqué" téléchargé par le setup auto (si pas de node système)
_NODE_HOME = NOCTUS_SRC / ".node"
_SETUP_STATUS_FILE = NOCTUS_SRC / ".setup_status.json"
_NODE_VERSION = "v20.18.1"  # LTS épinglée


# ---------- helpers système ----------
def _node_bin() -> str:
    """Chemin vers node : système d'abord, sinon le node embarqué (.node/)."""
    sysnode = shutil.which("node")
    if sysnode:
        return sysnode
    if _NODE_HOME.exists():
        for pat in ("**/bin/node", "**/node.exe"):
            for c in _NODE_HOME.glob(pat):
                if c.is_file():
                    return str(c)
    return ""


def _npm_cli() -> str:
    """Chemin du npm-cli.js du node embarqué (pour lancer npm sans PATH)."""
    if _NODE_HOME.exists():
        for c in _NODE_HOME.glob("**/npm-cli.js"):
            if c.is_file():
                return str(c)
    return ""


def node_available() -> bool:
    return bool(_node_bin())


def deps_installed() -> bool:
    return (NOCTUS_SRC / "node_modules" / "@napi-rs" / "canvas").exists()


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def setup_ok() -> bool:
    return node_available() and deps_installed() and ffmpeg_available()


# ---------- setup auto (télécharge node + npm install, sans terminal) ----------
def _setup_status() -> dict:
    try:
        if _SETUP_STATUS_FILE.exists():
            return json.loads(_SETUP_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"state": "idle"}


def _set_setup(state, msg=""):
    try:
        safe_json.write_text(_SETUP_STATUS_FILE, json.dumps({"state": state, "msg": msg}))
    except Exception:
        pass


def _node_dist():
    import platform
    m = platform.machine().lower()
    arch = "arm64" if m in ("aarch64", "arm64") else ("x64" if m in ("x86_64", "amd64") else m)
    s = platform.system().lower()
    if s == "linux":
        return f"https://nodejs.org/dist/{_NODE_VERSION}/node-{_NODE_VERSION}-linux-{arch}.tar.xz", "tar.xz"
    if s == "darwin":
        return f"https://nodejs.org/dist/{_NODE_VERSION}/node-{_NODE_VERSION}-darwin-{arch}.tar.gz", "tar.gz"
    if s in ("windows", "win32"):
        return f"https://nodejs.org/dist/{_NODE_VERSION}/node-{_NODE_VERSION}-win-{arch}.zip", "zip"
    return None, None


def _do_setup():
    """Télécharge un node portable (si pas de node système) puis npm install.
    Tourne dans un thread ; l'avancement est dans .setup_status.json."""
    import urllib.request
    import tempfile
    import tarfile
    import zipfile
    try:
        if not ffmpeg_available():
            _set_setup("error", "ffmpeg absent du serveur (besoin de l'admin : apt install ffmpeg)")
            return
        # 1) Node : système ? sinon on le télécharge dans .node/
        if not shutil.which("node") and not _node_bin():
            url, ext = _node_dist()
            if not url:
                _set_setup("error", "plateforme non supportée pour l'auto-install de Node")
                return
            _set_setup("downloading", f"Téléchargement de Node {_NODE_VERSION}…")
            _NODE_HOME.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix="." + ext.split(".")[-1])
            tmp.close()
            with urllib.request.urlopen(url, timeout=120) as r, open(tmp.name, "wb") as f:
                shutil.copyfileobj(r, f)
            _set_setup("extracting", "Extraction de Node…")
            if ext == "zip":
                with zipfile.ZipFile(tmp.name) as z:
                    z.extractall(_NODE_HOME)
            else:
                with tarfile.open(tmp.name) as t:
                    t.extractall(_NODE_HOME)
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            nb = _node_bin()
            if nb and os.name != "nt":
                try:
                    os.chmod(nb, 0o755)
                except Exception:
                    pass
        node_bin = _node_bin()
        if not node_bin:
            _set_setup("error", "Node introuvable après téléchargement")
            return
        # 2) npm install dans noctus/
        _set_setup("installing", "npm install @napi-rs/canvas… (1-2 min)")
        npm_cli = _npm_cli()
        if npm_cli:
            cmd = [node_bin, npm_cli, "install", "--no-audit", "--no-fund"]
        elif shutil.which("npm"):
            cmd = [shutil.which("npm"), "install", "--no-audit", "--no-fund"]
        else:
            cmd = [node_bin, "-e", "process.exit(1)"]
        proc = subprocess.run(cmd, cwd=str(NOCTUS_SRC), capture_output=True, text=True, timeout=600)
        if deps_installed():
            _set_setup("done", "✅ Installé. Recharge la page.")
        else:
            tail = (proc.stderr or proc.stdout or "")[-400:]
            _set_setup("error", f"npm install a échoué : {tail}")
    except Exception as e:
        _set_setup("error", f"{type(e).__name__}: {e}")


def start_setup() -> bool:
    st = _setup_status().get("state")
    if st in ("downloading", "extracting", "installing"):
        return False  # déjà en cours
    import threading
    _set_setup("downloading", "Démarrage…")
    threading.Thread(target=_do_setup, daemon=True).start()
    return True


# ---------- helpers data ----------
def _models_dir() -> Path:
    return NOCTUS_DATA / "models"


def _safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "", (name or "").strip())[:40]


def list_models() -> list:
    d = _models_dir()
    out = []
    if not d.exists():
        return out
    for m in sorted(d.iterdir()):
        if not m.is_dir():
            continue
        inp = m / "input"
        n_in = len([f for f in inp.glob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXTS]) if inp.exists() else 0
        n_out = 0
        outd = m / "output"
        if outd.exists():
            for vf in outd.glob("V*"):
                n_out += len(list(vf.glob("*.mp4")))
        st = status(m.name).get("state", "idle")
        out.append({"id": m.name, "inputs": n_in, "outputs": n_out, "state": st})
    return out


def status(model_id: str) -> dict:
    mid = _safe(model_id)
    f = _models_dir() / mid / "_status.json"
    st = None
    try:
        if f.exists():
            st = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        st = None
    proc = _PROCS.get(mid)
    proc_dead = (proc is not None) and (proc.poll() is not None)

    def _tail_log():
        try:
            logf = _models_dir() / mid / "_run.log"
            if logf.exists():
                txt = logf.read_text(encoding="utf-8", errors="ignore").strip()
                if txt:
                    return txt[-400:]
        except Exception:
            pass
        return ""

    def _avec_rapport(d):
        """Joint le rapport d'assemblage à l'état. C'est status() que la page
        interroge pendant le rendu : sans ça, le repli sur le template nu
        (variante livrée sans vidéo brute) n'atteignait jamais l'appelant."""
        rap = assembly_report(mid)
        if rap:
            d = dict(d)
            d["assemblage"] = rap
        return d

    if st is not None:
        # Le fichier dit "running" mais le process est MORT -> crash silencieux du pipeline.
        if st.get("state") == "running" and proc_dead:
            err = _tail_log() or "le rendu s'est arrêté (crash pipeline)"
            return _avec_rapport({"state": "error", "error": err})
        return _avec_rapport(st)
    # Pas de fichier de statut
    if proc is not None and proc.poll() is None:
        return _avec_rapport({"state": "running"})
    if proc_dead:
        err = _tail_log() or "le rendu ne s'est pas lancé"
        return _avec_rapport({"state": "error", "error": err})
    return _avec_rapport({"state": "idle"})


def list_outputs(model_id: str) -> dict:
    mid = _safe(model_id)
    out = {}
    base = _models_dir() / mid / "output"
    if not base.exists():
        return out
    for vf in V_FOLDERS:
        d = base / vf
        if d.exists():
            files = sorted([f.name for f in d.glob("*.mp4")])
            if files:
                out[vf] = files
    return out


def read_captions() -> list:
    f = NOCTUS_DATA / "captions.json"
    try:
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def write_captions(data) -> bool:
    if not isinstance(data, list):
        return False
    try:
        NOCTUS_DATA.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(NOCTUS_DATA / "captions.json", json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception:
        return False


# ---------- rapport d'assemblage (repli sur le template nu) ----------
# Une génération « Reel monté » peut livrer des variantes SANS vidéo brute :
# soit parce qu'aucune brute n'était disponible, soit parce que l'assemblage
# ffmpeg a échoué. Le VA reçoit alors le TEMPLATE ENTIER — donc l'accroche
# d'une AUTRE vidéo — avec le message « poste cette vidéo telle quelle », et il
# la publie sur le compte de la model. Observé : 10 variantes demandées,
# 9 échecs d'assemblage, la page annonçait « 10 vidéos téléchargées » et la
# seule trace était un print sur la sortie standard du bot, invisible depuis le
# dashboard.
#
# Le rapport est donc remonté par TROIS chemins, tous alimentés par la même
# structure (deux structures divergentes = deux comportements) :
#   1. paramètre `report=` de _prepare_inputs() / gen_from_draft(), rempli sur
#      place — le tuple de retour, lui, ne bouge pas (appelants inchangés) ;
#   2. models/<id>/_assemblage.json, relu par assembly_report(model_id) et
#      joint à status() sous la clé « assemblage » (c'est status() que la page
#      interroge pendant le rendu) ;
#   3. en TÊTE de _run.log, le seul journal consultable depuis le dashboard
#      (/noctus/montage_log) — écrit par run() juste avant de lancer Node.
_RAPPORT_NOM = "_assemblage.json"

# Au-delà, la liste d'échecs ne sert plus qu'à gonfler le fichier ; le compte
# exact reste dans « echecs_total » (ne jamais écarter en silence).
_MAX_ECHECS = 40


def _rapport_vide(total=0) -> dict:
    """Structure du rapport d'assemblage, compteurs à zéro."""
    return {
        # un montage a-t-il été DEMANDÉ (point de coupe + dossier de brutes) ?
        # Sans ça, « template seul » est le comportement normal, pas un repli.
        "montage_demande": False,
        "mode": "sans_montage",     # "assemble" | "template_seul" | "sans_montage"
        # au moins une variante livrée SANS vidéo brute, OU pas livrée du tout
        # (voir « perdues ») : dans les deux cas ce n'est pas ce qui a été demandé.
        "repli": False,
        "total": 0,                 # variantes prévues
        "assemblees": 0,            # variantes réellement montées avec une brute
        "repliees": 0,              # variantes rendues à partir du template nu
        "perdues": 0,               # variantes qui n'ont produit aucun fichier
        "brutes_dispo": 0,
        "coupe": 0.0,
        "echecs": [],               # [{"brute", "variante", "erreur", "perdue"}]
        "echecs_total": 0,          # avant plafonnement de la liste
        "raison": "",               # pourquoi le repli, en clair
        "message": "",              # phrase prête à afficher (page, Discord, log)
        "fichiers": [],             # entrées préparées (= targets)
        "ts": 0,
    }


def _finaliser_rapport(rap: dict) -> dict:
    """Déduit mode / repli / message des compteurs. Appelé au point de sortie
    unique de _prepare_inputs pour qu'aucun chemin ne puisse rendre un rapport
    à moitié rempli."""
    if rap.get("montage_demande"):
        rap["mode"] = "assemble" if rap["assemblees"] else "template_seul"
    else:
        rap["mode"] = "sans_montage"
    # « perdues » = variantes qui n'ont produit AUCUN fichier. C'est une alerte
    # même quand aucun montage n'était demandé : observé en rejouant le cas où la
    # copie de la source échoue (source purgée sous nos pieds), le rapport
    # comptait bien perdues=2 mais sortait repli=False et le message
    # « aucun point de coupe » — un appelant qui lit `repli` croyait que tout
    # allait bien alors que rien n'avait été préparé.
    rap["repli"] = bool(rap["repliees"] or rap["perdues"])
    if not rap["repli"]:
        rap["message"] = rap["raison"] or (
            f"{rap['assemblees']} variante(s) montée(s) avec une brute"
            if rap["assemblees"] else "vidéo source utilisée telle quelle")
        return rap
    bouts = []
    if rap["repliees"]:
        bouts.append(f"{rap['repliees']}/{rap['total']} variante(s) SANS vidéo brute "
                     "(template entier : l'accroche n'est pas celle de la model)")
    if rap["perdues"]:
        bouts.append(f"{rap['perdues']}/{rap['total']} variante(s) PERDUE(S) "
                     "(aucune vidéo produite)")
    if rap["raison"]:
        bouts.append(rap["raison"])
    rap["message"] = " — ".join(bouts)
    return rap


def _ecrire_rapport(mdir, rap: dict) -> bool:
    """Pose le rapport à côté du rendu, en écriture atomique : status() le relit
    pendant que la page interroge l'état. backup=False : ce fichier est
    régénéré à chaque génération, une copie .prev n'apporterait rien."""
    try:
        return safe_json.write(Path(mdir) / _RAPPORT_NOM, rap, indent=None, backup=False)
    except Exception as e:
        print(f"[noctus] rapport d'assemblage non ecrit : {e}", flush=True)
        return False


def assembly_report(model_id) -> dict:
    """Rapport d'assemblage de la DERNIÈRE génération d'un modèle ({} si aucun).

    Entrée publique pour savoir si les vidéos livrées contiennent bien une
    vidéo brute. Clés utiles : « repli » (bool, au moins une variante sans
    brute), « repliees » / « assemblees » / « perdues » (comptes), « echecs »
    (détail par variante), « message » (phrase toute faite)."""
    mid = _safe(model_id)
    if not mid:
        return {}
    try:
        data = safe_json.load(_models_dir() / mid / _RAPPORT_NOM, default=None)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _rapport_si_courant(mdir, targets):
    """Le rapport posé dans models/<id> S'IL décrit bien la génération qui
    démarre, sinon None.

    Le dossier models/<id> est réutilisé d'une génération à l'autre (son
    identifiant ne dépend que du reel) : un rapport laissé par la précédente
    mentirait. On compare les fichiers d'entrée, pas un horodatage : c'est
    exact, alors qu'un délai serait une devinette.

    `targets` à None = l'appelant ne fixe aucune liste d'entrées (page
    « Création de vidéos », /reeltest) : ces lancements ne passent pas par
    _prepare_inputs, donc aucun rapport ne les décrit. Une liste VIDE, elle,
    est un vrai résultat — tout a été perdu — et correspond à un rapport sans
    fichiers : c'était justement le pire cas, et il ne laissait aucune trace
    dans le journal parce que la comparaison rejetait les rapports vides."""
    if targets is None:
        return None
    try:
        data = safe_json.load(Path(mdir) / _RAPPORT_NOM, default=None)
    except Exception as e:
        print(f"[noctus] rapport d'assemblage illisible : {e}", flush=True)
        return None
    if not isinstance(data, dict):
        return None
    if set(data.get("fichiers") or []) != set(targets):
        return None
    return data


def _entete_assemblage(mdir, targets) -> str:
    """Lignes à écrire en tête de _run.log (vide si aucun rapport ne décrit
    cette génération — voir _rapport_si_courant)."""
    try:
        data = _rapport_si_courant(mdir, targets)
        if data is None:
            return ""
        lignes = ["===== assemblage brute + template =====",
                  f"variantes : {data.get('total', 0)} — montées avec une brute : "
                  f"{data.get('assemblees', 0)} — template seul : "
                  f"{data.get('repliees', 0)} — perdues : {data.get('perdues', 0)}",
                  f"brutes disponibles : {data.get('brutes_dispo', 0)}, "
                  f"coupe à {data.get('coupe', 0)}s"]
        if data.get("message"):
            lignes.append(("/!\\ " if data.get("repli") else "") + str(data["message"]))
        for e in (data.get("echecs") or []):
            lignes.append(f"  echec {e.get('variante', '?')} / {e.get('brute', '?')} : "
                          f"{e.get('erreur', '?')}")
        reste = int(data.get("echecs_total") or 0) - len(data.get("echecs") or [])
        if reste > 0:
            lignes.append(f"  ... et {reste} autre(s) echec(s) non detaille(s)")
        lignes.append("=" * 39)
        return "\n".join(lignes) + "\n"
    except Exception as e:
        print(f"[noctus] entete d'assemblage illisible : {e}", flush=True)
        return ""


# ---------- run / stop ----------
def run(model_id: str, folders=None, captions=None, targets=None, folder_map=None,
        caption_map=None):
    mid = _safe(model_id)
    if not mid:
        return None
    user_dir = str(NOCTUS_DATA.resolve())
    payload = {
        "modelId": mid,
        "userDir": user_dir,
        "selectedFolders": folders or None,
        "selectedCaptions": captions or None,
        "targetFiles": targets or None,
        # {fichier: [variante]} — épingle chaque vidéo assemblée à SA variante,
        # sinon le moteur croise toutes les vidéos avec toutes les variantes.
        "videoFolderMap": folder_map or None,
        # {fichier: [label]} — captions PAR VIDÉO : les variantes dont le début
        # a été coupé (brute courte) utilisent une copie décalée des captions.
        "captionMap": caption_map or None,
    }
    old = _PROCS.get(mid)
    if old and old.poll() is None:
        stop(mid)
    kwargs = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True  # groupe de process -> kill propre
    node_bin = _node_bin() or "node"
    # Logs du pipeline -> _run.log (au lieu de DEVNULL) : si ça crashe, on voit pourquoi
    # et status() en renvoie un extrait au front.
    mdir = _models_dir() / mid
    logf = None                      # None = pas de fichier -> DEVNULL au Popen
    try:
        mdir.mkdir(parents=True, exist_ok=True)
        logf = open(str(mdir / "_run.log"), "wb")
    except Exception as e:
        # Sans journal, un crash du pipeline ne laisse plus AUCUNE trace : status()
        # ne peut plus en renvoyer d'extrait et le front affiche « erreur » tout
        # court. Au moins dire pourquoi le journal manque.
        print(f"[noctus] journal de rendu impossible a ouvrir ({mid}) : {e}", flush=True)
        logf = None
    if logf is not None:
        # Rapport d'assemblage EN TÊTE, pendant qu'on tient encore le fichier :
        # ensuite Node écrit dedans. C'est le seul journal consultable depuis le
        # dashboard ; les échecs d'assemblage n'allaient jusqu'ici que sur la
        # sortie standard du bot, que personne ne lit.
        try:
            entete = _entete_assemblage(mdir, targets)
            if entete:
                logf.write(entete.encode("utf-8", "replace"))
                logf.flush()
        except Exception as e:
            print(f"[noctus] entete d'assemblage non journalisee : {e}", flush=True)
    # `targets == []` = la préparation n'a produit AUCUN fichier (assemblage
    # perdu ET copie de la source impossible). Or une liste de cibles VIDE ne
    # filtre rien côté Node (`targetFiles.length > 0` dans pipeline-core.js) :
    # le moteur traiterait alors tout ce qui traîne dans input/ — un reste d'une
    # génération précédente que le VA recevrait avec « poste cette vidéo telle
    # quelle », sans la brute attendue et sans que rien ne le signale. On vide
    # donc le dossier : mieux vaut zéro vidéo qu'une vidéo au hasard sur le
    # compte d'une model. (`targets is None` = pas de liste de cibles du tout,
    # page « Création de vidéos » : là, tout input/ est bien le sujet.)
    if targets is not None and not targets:
        restes = 0
        try:
            for f in (mdir / "input").glob("*"):
                if not f.is_file():
                    continue
                try:
                    f.unlink()
                    restes += 1
                except OSError as e:
                    print(f"[noctus] {mid} : reste impossible a supprimer dans "
                          f"input/ ({f.name}) : {e} — il PEUT etre rendu a la "
                          "place du reel", flush=True)
        except OSError as e:
            print(f"[noctus] {mid} : input/ illisible : {e}", flush=True)
        if restes:
            print(f"[noctus] {mid} : {restes} reste(s) ecarte(s) de input/ — "
                  "aucune entree preparee pour cette generation", flush=True)
    # Le rapport d'assemblage posé dans le dossier est joint à status() par
    # _avec_rapport, donc renvoyé au front ET au bot. S'il décrit une AUTRE
    # génération (dossier réutilisé, ou lancement qui ne passe pas par
    # _prepare_inputs : page « Création de vidéos », /reeltest), status()
    # annoncerait un repli qui n'a pas eu lieu — ou tairait celui qui a lieu.
    # On le remplace donc par un rapport neutre décrivant CETTE génération,
    # au lieu de laisser l'ancien répondre à sa place.
    if _rapport_si_courant(mdir, targets) is None:
        import time as _tR
        neutre = _rapport_vide()
        neutre["ts"] = int(_tR.time())
        neutre["total"] = len(folders or []) or 1
        neutre["fichiers"] = list(targets or [])
        neutre["raison"] = "génération sans assemblage (pas de vidéo brute demandée)"
        _finaliser_rapport(neutre)
        _ecrire_rapport(mdir, neutre)
    # ÉTAT « running » ÉCRIT ICI, AVANT de lancer Node.
    # Sinon : l'identifiant du modèle est fixe pour un reel donné, donc
    # _status.json contient encore le « done » de la génération précédente. Le
    # front interroge l'état juste après la réponse HTTP, avant que Node ait
    # démarré et écrit son propre « running » : il lit l'ancien « done », va
    # chercher les vidéos dans output/ qui vient d'être vidé, et annonce
    # « aucune vidéo produite » alors que le rendu tourne encore.
    if not safe_json.write(mdir / "_status.json",
                           {"state": "running", "current": 0, "total": 0,
                            "pct": 0, "eta": None}, indent=None):
        print("[noctus] etat initial non ecrit", flush=True)
    # Occupé le temps que Popen rende la main : entre l'état « running » écrit
    # ci-dessus et l'inscription dans _PROCS, la génération n'apparaît occupée
    # NULLE PART, et une purge concurrente pourrait emporter le dossier.
    _marquer_preparation(mid, True)
    try:
        proc = subprocess.Popen(
            [node_bin, "noctus_runner.js", json.dumps(payload)],
            cwd=str(NOCTUS_SRC),
            stdout=(logf if logf is not None else subprocess.DEVNULL),
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        _PROCS[mid] = proc
    finally:
        _marquer_preparation(mid, False)
    return proc


def gen_from_path(src_path, caption="", font="Strong", folders=None,
                  start="00:00:00", end="99:99:99", model=None):
    """Prépare un modèle à partir d'UNE vidéo + lance la génération.
    Retourne le model_id (à poller via status()) ou None. Réutilisé par /reeltest."""
    import shutil as _sh
    import re as _re
    src = Path(src_path)
    if not src.exists() or not src.is_file():
        return None
    model = model or _re.sub(r"[^a-zA-Z0-9_\-]", "", f"reeltest-{src.stem}")[:40]
    inp = _models_dir() / model / "input"
    inp.mkdir(parents=True, exist_ok=True)
    for f in inp.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
    _sh.copy(str(src), str(inp / src.name))
    folders = folders or ["V1"]
    label = ("rt_" + model)[:40]
    caps = [c for c in read_captions() if not (isinstance(c, dict) and c.get("label") == label)]
    if caption:
        caps.append({"label": label, "font": font or "Strong",
                     "captions": [{"start": start, "end": end, "text": caption}]})
        sel = [label]
    else:
        if not any(isinstance(c, dict) and c.get("label") == "sans_texte" for c in caps):
            caps.append({"label": "sans_texte", "font": None, "captions": []})
        sel = ["sans_texte"]
    write_captions(caps)
    proc = run(model, folders, sel, targets=[src.name])
    return model if proc else None


def _hms_seconds(v):
    """Secondes (float) -> 'HH:MM:SS.mmm' (millisecondes gardées). Miroir du _hms
    de la route montage_gen (web_upload)."""
    try:
        sec = max(0.0, float(v))
    except Exception:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _clean_montage_style(raw):
    """Nettoie le style GLOBAL (réglages CapCut). Miroir du _clean_style de montage_gen."""
    import re as _re
    out = {}
    if not isinstance(raw, dict):
        return out
    try:
        if raw.get("size") is not None:
            out["size"] = max(16, min(160, int(float(raw["size"]))))
    except Exception:
        pass
    c = raw.get("color")
    if isinstance(c, str) and _re.match(r"^#[0-9a-fA-F]{3,8}$", c):
        out["color"] = c
    if raw.get("align") in ("left", "center", "right"):
        out["align"] = raw["align"]
    if raw.get("case") in ("upper", "lower", "title", "none"):
        out["case"] = raw["case"]
    for k in ("bold", "italic", "underline"):
        if k in raw:
            out[k] = bool(raw[k])
    if raw.get("box") in (True, "1", "true"):
        out["box"] = True
    bc = raw.get("boxColor")
    if isinstance(bc, str) and _re.match(r"^#[0-9a-fA-F]{3,8}$", bc):
        out["boxColor"] = bc
    if raw.get("effect") in ("shadow", "neon"):
        out["effect"] = raw["effect"]
    return out


def build_montage_caps(draft, label):
    """Construit l'entrée captions du moteur (segments chronométrés + style + position)
    à partir d'un brouillon de montage {segments, font, style} (le .montage.json de
    l'éditeur). Retourne (caps_entry|None, font). Logique = celle de la route montage_gen."""
    import json as _json
    font = draft.get("font") if isinstance(draft, dict) else None
    font = (font.strip() if isinstance(font, str) else "") or "Strong"
    style_raw = draft.get("style") if isinstance(draft, dict) else None
    if isinstance(style_raw, str):
        try:
            style_raw = _json.loads(style_raw or "{}")
        except Exception:
            style_raw = {}
    _style = _clean_montage_style(style_raw)
    seg_raw = draft.get("segments") if isinstance(draft, dict) else None
    if isinstance(seg_raw, str):
        try:
            seg_raw = _json.loads(seg_raw or "[]")
        except Exception:
            seg_raw = []
    segments = []
    if isinstance(seg_raw, list):
        for it in seg_raw[:40]:                 # garde-fou : 40 captions max
            if not isinstance(it, dict):
                continue
            txt = (it.get("text") or "").strip()
            if not txt:
                continue
            st, en = it.get("start"), it.get("end")
            if st is None or en is None:
                start, end = "00:00:00", "99:99:99"
            else:
                start, end = _hms_seconds(st), _hms_seconds(en)
            seg = {"start": start, "end": end, "text": txt}
            seg.update(_style)
            for _pk in ("x", "y"):
                _pv = it.get(_pk)
                try:
                    if _pv is not None:
                        _pf = float(_pv)
                        if 0.0 <= _pf <= 1.0:
                            seg[_pk] = round(_pf, 4)
                except Exception:
                    pass
            try:
                _wv = it.get("wrapW")
                if _wv is not None:
                    _wf = float(_wv)
                    if 0.2 <= _wf <= 0.97:
                        seg["wrapW"] = round(_wf, 4)
            except Exception:
                pass
            try:
                _lv = it.get("lineSpacing")
                if _lv is not None:
                    _lf = float(_lv)
                    if 0.9 <= _lf <= 3.0:
                        seg["lineSpacing"] = round(_lf, 3)
            except Exception:
                pass
            segments.append(seg)
    if segments:
        return {"label": label, "font": font, "captions": segments}, font
    return None, font


# ==========================================================================
# ASSEMBLAGE  brute + template
# --------------------------------------------------------------------------
# Un TEMPLATE est un export CapCut (~7 s) dont le DÉBUT est un plan d'accroche
# jetable. À la génération on remplace ce début [0 .. cut_at] par une vidéo
# BRUTE tirée au hasard, et on garde la piste sonore du template EN ENTIER
# (elle couvre donc aussi la partie brute, comme dans CapCut).
#
# La durée finale reste celle du template et la partie d'après la coupe garde
# ses timings d'origine -> les captions de l'éditeur restent valables telles
# quelles, sans recalcul.
# ==========================================================================

def _video_rotation(path) -> int:
    """Rotation déclarée d'une vidéo, en degrés (0, 90, 180, 270).

    Les vidéos filmées au téléphone sont stockées « couchées » avec une matrice
    de rotation ; ffmpeg les redresse au décodage mais ffprobe annonce les
    dimensions STOCKÉES. Sans ça un template filmé au téléphone donnerait un
    montage en paysage."""
    for args in (["-show_entries", "side_data=rotation"],
                 ["-show_entries", "stream_tags=rotate"]):   # anciens fichiers
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0"] + args
                + ["-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, timeout=20, text=True)
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line and line != "N/A":
                    return abs(int(float(line))) % 360
        except Exception:
            pass
    return 0


def probe_video(path):
    """(largeur, hauteur, fps, durée) d'une vidéo, dimensions TELLES QUE
    DÉCODÉES (rotation du téléphone appliquée). (0, 0, 0.0, 0.0) si illisible."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=30, text=True)
        vals = [v.strip() for v in (r.stdout or "").split() if v.strip()]
        w = h = 0
        fps = dur = 0.0
        for v in vals:
            if "/" in v and fps == 0.0:              # r_frame_rate, ex. "30/1"
                a, _, b = v.partition("/")
                try:
                    fps = float(a) / float(b or 1)
                except (ValueError, ZeroDivisionError):
                    fps = 0.0
            elif "." in v:                            # duration
                try:
                    dur = float(v)
                except ValueError:
                    pass
            elif w == 0:
                try:
                    w = int(v)
                except ValueError:
                    pass
            elif h == 0:
                try:
                    h = int(v)
                except ValueError:
                    pass
        # Quart de tour -> ffmpeg décode en portrait ce qui est stocké en
        # paysage : on renvoie les dimensions vues par le filtre, pas celles
        # du conteneur.
        if w and h and _video_rotation(path) in (90, 270):
            w, h = h, w
        return w, h, fps, dur
    except Exception:
        return 0, 0, 0.0, 0.0


def list_brutes(brutes_dir, ecartes=None):
    """Vidéos utilisables du dossier brutes/, triées par nom.
    Les fichiers annexes (.txt, .desc.txt, .montage.json, miniatures, fichiers
    cachés et restes d'upload) ne sont pas des vidéos et sont donc écartés par
    le filtre d'extension.

    `ecartes` : dict FACULTATIF {raison: nombre}, rempli sur place. Sans lui, un
    dossier ne contenant que des .example ou des miniatures ressemblait à un
    dossier VIDE : le repli sur le template nu devenait inexplicable pour le
    propriétaire, qui voyait pourtant des fichiers dans le dossier."""
    def _ecarte(raison):
        if isinstance(ecartes, dict):
            ecartes[raison] = ecartes.get(raison, 0) + 1

    d = Path(brutes_dir)
    if not d.exists() or not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            _ecarte("fichier caché")
            continue
        if ".example" in f.name:          # <stem>.example.mp4 = vidéo d'exemple
            _ecarte("vidéo d'exemple")    # (même convention que la Bibliothèque)
            continue
        if f.suffix.lower() not in VIDEO_EXTS:
            _ecarte("pas une vidéo")
            continue
        # Brute DESACTIVEE : elle porte deja une caption incrustee, en poser
        # une seconde par-dessus n'a aucun sens. C'est le seul enumerateur du
        # moteur : le montage, « Reel deja monte » et /noctus/montage_gen en
        # dependent tous les trois, donc ce test les ferme d'un coup.
        # On la compte dans `ecartes` avec sa vraie raison plutot que de la
        # laisser passer pour « pas une video » a cause de son voisin.
        try:
            import brutes_off as _off_nx
            if _off_nx.est_desactivee(f):
                _ecarte("désactivée (caption déjà incrustée)")
                continue
        except Exception:
            pass          # module absent : on ne bloque pas la generation
        try:
            # Seuil bas exprès : il ne sert qu'à jeter les fichiers vides ou les
            # uploads interrompus. Une vidéo courte mais valide doit passer — un
            # fichier réellement illisible sera écarté à l'assemblage (ffprobe).
            if f.stat().st_size < 1024:
                _ecarte("fichier vide ou upload interrompu")
                continue
        except OSError:
            _ecarte("fichier illisible")
            continue
        out.append(f)
    return out


def _has_audio(path) -> bool:
    """La vidéo a-t-elle une piste audio ? (référencer [1:a] dans un filtre
    ffmpeg plante si la piste n'existe pas — d'où ce contrôle)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True, timeout=20, text=True)
        return bool((r.stdout or "").strip())
    except Exception:
        return False


def brute_gap(template, brute, cut_at) -> float:
    """De combien la vidéo finale sera RACCOURCIE au début si cette brute est
    plus courte que la place à remplir (0.0 = pas de rognage). Les captions
    minutées doivent être décalées d'autant."""
    _w, _h, _f, dur = probe_video(template)
    if dur <= 0:
        return 0.0
    cut = max(0.0, min(float(cut_at or 0), max(0.0, dur - 0.10)))
    if cut < 0.05:
        return 0.0
    _bw, _bh, _bf, bdur = probe_video(brute)
    if bdur <= 0.2 or bdur >= cut - 0.05:
        return 0.0
    return round(cut - bdur, 3)


def assemble_brute_template(template, brute, cut_at, out_path):
    """Fabrique la vidéo assemblée : la BRUTE occupe le début jusqu'au trait de
    coupe, le TEMPLATE reprend du trait jusqu'à sa fin, et le son du TEMPLATE
    accompagne le tout. Renvoie (True, "") ou (False, raison).

    La brute est recadrée au format du template (on remplit puis on rogne au
    centre : jamais de bandes noires). Si elle est plus courte que la place,
    le DÉBUT de la vidéo finale est coupé, son compris : jamais de boucle ni
    d'arrêt sur image — l'image bouge toujours, et la transition reste calée
    sur le même instant de la musique (voir brute_gap pour le décalage des
    captions)."""
    template, brute, out_path = Path(template), Path(brute), Path(out_path)
    if not template.exists():
        return False, "template introuvable"
    if not brute.exists():
        return False, "vidéo brute introuvable"
    w, h, fps, dur = probe_video(template)
    if not (w and h and dur > 0):
        return False, "template illisible (ffprobe)"
    cut = max(0.0, min(float(cut_at or 0), max(0.0, dur - 0.10)))
    if cut < 0.05:
        return False, "pas de point de coupe"
    if not fps or fps > 121:
        fps = 30.0
    # libx264 + yuv420p refuse les dimensions impaires : on arrondit au pair
    # inférieur (au pire on perd 1 px sur un template exotique).
    w -= w % 2
    h -= h % 2
    if w < 2 or h < 2:
        return False, "dimensions du template invalides"
    bw, bh, _bf, bdur = probe_video(brute)
    if not (bw and bh):
        return False, f"brute illisible : {brute.name}"
    if 0 < bdur <= 0.2:
        # une "video" d'une poignee d'images : meme ralentie ca ne remplirait
        # pas la place -> cette variante repartira du template seul.
        return False, f"brute trop courte ({bdur:.2f}s) : {brute.name}"
    # La brute doit finir PILE sur le trait de coupe : c'est là que le son du
    # montage fait sa transition, et l'image doit basculer au même instant.
    #
    #  - brute plus LONGUE que la coupe : on prend une fenêtre au hasard (de la
    #    variété d'une génération à l'autre), sa fin tombe sur le trait.
    #  - brute plus COURTE : on COUPE LE DÉBUT de la vidéo finale, son compris.
    #    Elle démarre quand la brute démarre, la musique est raccourcie
    #    d'autant au début, et la transition reste calée sur le même instant
    #    de la musique. Jamais de boucle ni d'arrêt sur image.
    start, gap = 0.0, 0.0
    if bdur > cut + 0.30:
        import random as _rnd
        start = round(_rnd.uniform(0.0, bdur - cut - 0.10), 2)
    elif bdur < cut - 0.05:
        gap = round(cut - bdur, 3)
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
           f"crop={w}:{h},setsar=1,fps={fps:.4f}")
    fc = (f"[0:v]{fit},trim=duration={cut - gap:.3f},setpts=PTS-STARTPTS[a];"
          f"[1:v]{fit},trim=start={cut:.3f},setpts=PTS-STARTPTS[b];"
          f"[a][b]concat=n=2:v=1:a=0[v]")
    maps = ["-map", "[v]"]
    if gap > 0:
        if _has_audio(template):
            # son du template raccourci du même « gap » : au moment où la brute
            # finit, l'audio est exactement à l'instant du trait de coupe.
            fc += f";[1:a]atrim=start={gap:.3f},asetpts=PTS-STARTPTS[aud]"
            maps += ["-map", "[aud]"]
    else:
        maps += ["-map", "1:a?"]           # « ? » : template sans son -> muet

    def _cmd(seek):
        c = ["ffmpeg", "-y", "-loglevel", "error"]
        if seek > 0:
            c += ["-ss", f"{seek:.2f}"]
        return c + ["-t", f"{cut:.3f}", "-i", str(brute),
                    "-i", str(template),
                    "-filter_complex", fc] + maps + [
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(out_path)]

    # Deux essais : sous charge (plusieurs assemblages en parallele + le moteur
    # Node qui tourne encore), ffmpeg echoue parfois de facon passagere. Sans
    # reprise, cette variante-la repartirait du template seul, sans video brute.
    # Le 2e essai repart du DEBUT de la brute : rejouer le meme decalage
    # aleatoire rejouerait aussi l echec s'il venait de la.
    last = ""
    for essai in (1, 2):
        cmd = _cmd(start if essai == 1 else 0.0)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            return False, "assemblage trop long (>5 min)"
        except Exception as e:
            return False, f"ffmpeg indisponible : {e}"
        size = out_path.stat().st_size if out_path.exists() else 0
        if r.returncode == 0 and size >= 10000:
            return True, ""
        err = (r.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
        # stderr vide arrive : on garde alors le code de sortie, sinon le
        # message est « échec » tout court et le probleme est indiagnosticable.
        last = (err[-1].strip() if err else f"code {r.returncode}, {size} octets écrits")
        if essai == 1:
            print(f"[noctus] assemblage {brute.name} : {last} — 2e essai", flush=True)
            import time as _t
            _t.sleep(0.8)
    return False, f"ffmpeg : {last}"[:200]


def generations_en_cours() -> set:
    """Identifiants des modèles dont la génération est ENCORE en cours :
    rendu Node lancé, ou assemblage ffmpeg en train de remplir input/.

    _PROCS est la table des process lancés par run() ; `poll() is None` = vivant.
    _EN_PREPARATION couvre la phase d'AVANT le process (assemblage brute+template) :
    sans elle, un dossier en pleine préparation n'apparaissait nulle part comme
    occupé. En cas de doute (process illisible) on considère le rendu vivant :
    garder un dossier de trop coûte du disque, en supprimer un de trop tue un
    rendu."""
    vivants = set()
    for mid, p in list(_PROCS.items()):          # copie : la table bouge en parallèle
        if p is None:
            continue
        try:
            if p.poll() is None:
                vivants.add(mid)
        except Exception:
            vivants.add(mid)
    with _PREP_LOCK:
        vivants |= set(_EN_PREPARATION)
    return vivants


def _mtime_recursif(d: Path) -> float:
    """mtime le plus récent du dossier de génération, sous-dossiers compris.

    Le mtime de models/<id> NE BOUGE PAS pendant un rendu : Node écrit dans
    output/V1, pas à la racine. Trié sur ce seul mtime, un rendu long
    redevenait « ancien » au fil des générations suivantes et se faisait purger
    en pleine écriture."""
    best = 0.0
    try:
        best = d.stat().st_mtime
    except OSError:
        return 0.0
    for sub in ("input", "output"):
        p = d / sub
        try:
            best = max(best, p.stat().st_mtime)
            for c in p.iterdir():                # output/V1, output/V2, …
                try:
                    best = max(best, c.stat().st_mtime)
                except OSError:
                    pass
        except OSError:
            pass
    return best


def purge_old_models(prefix: str, keep: int = 12, details=None):
    """Supprime les vieux dossiers de génération `<prefix>*` en gardant les
    `keep` plus récents. Chacun contient les vidéos d'entrée ET les sorties :
    avec l'assemblage il y a maintenant une entrée PAR VARIANTE, donc plusieurs
    dizaines de Mo par génération — sans ça le disque du VPS se remplit.

    Un dossier dont la GÉNÉRATION EST EN COURS n'est jamais supprimé, même s'il
    est le plus ancien : 13 générations lancées pendant un rendu lourd
    effaçaient input/ et output/ sous les pieds du process Node, qui mourait, et
    le FileNotFoundError qui suivait faisait échouer la requête en cours.

    Un dossier qui disparaît en cours de route (purge concurrente) est compté et
    signalé, il n'annule plus toute la purge — auparavant un seul
    FileNotFoundError dans le tri laissait le disque se remplir en silence.
    Renvoie le nombre de dossiers réellement supprimés.

    `details` : dict FACULTATIF rempli sur place — supprimes / proteges /
    illisibles / candidats / erreur. Le nombre renvoyé ne dit que ce qui a été
    effacé : une purge entièrement BLOQUÉE par des rendus en cours renvoie 0,
    exactement comme une purge qui n'avait rien à faire. Les deux comptes ne
    partaient que sur la sortie standard du bot, que personne ne lit."""
    supprimes = proteges = illisibles = 0
    candidats = []

    def _details(erreur=""):
        if isinstance(details, dict):
            details.clear()
            details.update({"supprimes": supprimes, "proteges": proteges,
                            "illisibles": illisibles, "candidats": len(candidats),
                            "erreur": erreur})
    try:
        for d in _models_dir().glob(prefix + "*"):
            try:
                if not d.is_dir():
                    continue
                candidats.append((_mtime_recursif(d), d))
            except OSError:
                illisibles += 1                  # disparu entre le glob et le stat
        vivants = generations_en_cours()
        candidats.sort(key=lambda t: t[0], reverse=True)
        for _m, d in candidats[keep:]:
            if d.name in vivants:
                proteges += 1
                continue
            shutil.rmtree(str(d), ignore_errors=True)
            supprimes += 1
        if supprimes or proteges or illisibles:
            print(f"[noctus] purge {prefix}* : {supprimes} supprimé(s), "
                  f"{proteges} protégé(s) (rendu en cours), "
                  f"{illisibles} illisible(s)", flush=True)
        _details()
        return supprimes
    except Exception as e:
        print(f"[noctus] purge {prefix}* : {e}", flush=True)
        _details(f"{type(e).__name__}: {e}")
        return supprimes


def _prepare_inputs(src, inp, draft, folders, brutes_dir, report=None):
    """Remplit le dossier input/ du modèle — voir _preparer_entrees pour tout le
    détail. Ne fait qu'une chose de plus : signaler la génération comme OCCUPÉE
    pendant l'assemblage.

    Sans ça, un dossier en pleine préparation (plusieurs dizaines de secondes de
    ffmpeg) n'était protégé de purge_old_models que par sa fraîcheur : une fois
    12 générations lancées entre-temps, input/ était effacé pendant que ffmpeg y
    écrivait, et les variantes repartaient du template nu — ou disparaissaient.
    Le `finally` est obligatoire : une génération restée marquée occupée ne
    serait plus jamais purgée et le disque du VPS se remplirait."""
    mid = Path(inp).parent.name
    _marquer_preparation(mid, True)
    try:
        return _preparer_entrees(src, inp, draft, folders, brutes_dir, report)
    finally:
        _marquer_preparation(mid, False)


def _preparer_entrees(src, inp, draft, folders, brutes_dir, report=None):
    """Remplit le dossier input/ du modèle et renvoie
    (targets, videoFolderMap, gaps).

    Avec un point de coupe ET des vidéos brutes disponibles : une vidéo
    assemblée PAR VARIANTE, chacune avec une brute différente (on repioche
    seulement quand toutes ont été utilisées). Chaque assemblage est épinglé à
    sa variante via le videoFolderMap, sinon le moteur ferait le produit croisé
    (N vidéos × N variantes = N² exports).

    gaps = {fichier: secondes} : de combien le DÉBUT de cette variante a été
    coupé (brute plus courte que la place). Les captions minutées doivent être
    décalées d'autant — voir shifted_caption_entry.

    Sans coupe, sans brute, ou si tous les assemblages échouent : on retombe sur
    la vidéo source telle quelle (comportement d'avant).

    `report` : dict FACULTATIF rempli sur place avec le rapport d'assemblage
    (voir _rapport_vide pour les clés). Le tuple de retour ne change pas : les
    appelants qui l'ignorent gardent exactement le comportement d'avant. Le
    même rapport est de toute façon écrit dans models/<id>/_assemblage.json,
    donc relisible par assembly_report(model_id) et joint à status().
    Repère utile pour l'appelant : `repli` (bool) dit qu'au moins une des
    vidéos livrées est le TEMPLATE ENTIER, sans vidéo brute — à ne pas poster
    telle quelle sans le dire."""
    import shutil as _sh
    import random as _rnd
    import re as _re
    import time as _t
    rap = _rapport_vide()
    rap["ts"] = int(_t.time())
    rap["total"] = len(folders or []) or 1
    mdir = Path(inp).parent

    def _sortie(targets, fmap, gaps):
        """Point de sortie UNIQUE : quel que soit le chemin pris, le rapport est
        finalisé, écrit sur le disque et remonté à l'appelant."""
        rap["fichiers"] = list(targets)
        _finaliser_rapport(rap)
        _ecrire_rapport(mdir, rap)
        if isinstance(report, dict):
            report.clear()
            report.update(rap)
        if rap["repli"]:
            # Volontairement bruyant : c'est le cas où le VA publierait
            # l'accroche d'une autre vidéo sur le compte de la model.
            print(f"[noctus] /!\\ repli : {rap['message']}", flush=True)
        return targets, fmap, gaps

    def _copier_source():
        """Repli global : la vidéo source telle quelle. Renvoie [] si même la
        copie échoue (dossier purgé sous nos pieds) — jamais un nom de fichier
        qui n'existe pas, sinon le moteur annoncerait une vidéo introuvable."""
        try:
            Path(inp).mkdir(parents=True, exist_ok=True)
            _sh.copy(str(src), str(Path(inp) / src.name))
            return [src.name]
        except Exception as e:
            rap["repliees"] = 0
            rap["perdues"] = rap["total"]
            rap["echecs"].append({"brute": "", "variante": "*", "perdue": True,
                                  "erreur": f"copie de la source impossible : {e}"})
            rap["echecs_total"] += 1
            # La raison déjà posée (« aucun point de coupe », « aucun assemblage
            # n'a abouti ») n'explique PAS la perte : sans cette ligne le message
            # final gardait l'ancienne raison et taisait l'échec de copie, alors
            # que c'est LUI qui fait qu'aucune vidéo ne sortira.
            rap["raison"] = ((rap["raison"] + " — ") if rap["raison"] else "") \
                + f"copie de la source impossible : {e}"
            print(f"[noctus] copie de la source impossible : {e}", flush=True)
            return []

    try:
        cut = float((draft or {}).get("cut_at") or 0)
    except (TypeError, ValueError):
        cut = 0.0
    rap["coupe"] = round(cut, 3)
    rap["montage_demande"] = bool(brutes_dir) and cut > 0.05

    ecartes = {}
    brutes = list_brutes(brutes_dir, ecartes) if rap["montage_demande"] else []
    rap["brutes_dispo"] = len(brutes)
    if not brutes:
        # Trois situations que l'ancien code confondait dans un même repli muet.
        # Seule la troisième est un problème : un montage a été DEMANDÉ et le
        # VA va recevoir le template entier avec « poste-la telle quelle ».
        if not rap["montage_demande"]:
            rap["raison"] = ("aucun point de coupe" if cut <= 0.05
                             else "aucun dossier de brutes fourni")
        else:
            rap["repliees"] = rap["total"]
            d = Path(brutes_dir)
            if not d.is_dir():
                rap["raison"] = ("point de coupe posé mais le dossier de brutes "
                                 f"n'existe pas ({d.name})")
            else:
                det = ", ".join(f"{n} {k}" for k, n in sorted(ecartes.items()) if n)
                rap["raison"] = ("point de coupe posé mais AUCUNE vidéo brute "
                                 "utilisable dans " + d.name
                                 + (f" ({det})" if det else " (dossier vide)"))
        return _sortie(_copier_source(), None, {})
    stem = (_re.sub(r"[^A-Za-z0-9_-]", "", src.stem) or "reel")[:40]
    # 1) on attribue d'abord une brute à chaque variante (tirage sans remise,
    #    on ne repioche que quand toutes ont servi)
    plan, pool = [], []
    for i, vf in enumerate(folders):
        if not pool:
            pool = list(brutes)
            _rnd.shuffle(pool)
        plan.append((f"asm{i + 1}_{stem}.mp4", pool.pop(), vf))
    rap["total"] = len(plan)

    # Un échec d'assemblage n'est PAS un détail : la variante concernée part du
    # template nu. On les collecte pour les compter et les journaliser (list
    # .append est atomique, l'appel vient des workers ci-dessous).
    echecs = []

    # 2) puis on assemble EN PARALLÈLE : cet appel est synchrone dans le thread
    #    de la requête HTTP, et en série 10 variantes feraient patienter très
    #    longtemps. ffmpeg est un sous-processus, les threads ne bloquent pas.
    def _one(job):
        name, brute, vf = job
        ok, err = assemble_brute_template(src, brute, cut, inp / name)
        if ok:
            # brute plus courte que la place -> le début (image + son) a été coupé
            # de « gap » secondes : les captions minutées devront être décalées.
            return name, vf, brute_gap(src, brute, cut), True
        # Une brute abîmée ne doit pas faire disparaître une variante : on rend
        # le template seul pour celle-là, l'utilisateur a bien ses N vidéos.
        # Mais ce repli est COMPTÉ et remonté : sans ça « 10 vidéos
        # téléchargées » pouvait vouloir dire 9 templates nus.
        perdue = False
        try:
            _sh.copy(str(src), str(inp / name))
        except Exception as e:
            err = f"{err} ; repli sur le template impossible aussi ({e})"
            perdue = True
        echecs.append({"brute": brute.name, "variante": vf, "erreur": err,
                       "perdue": perdue})
        print(f"[noctus] assemblage {brute.name} -> {vf} : {err} "
              f"({'variante perdue' if perdue else 'cette variante partira du template seul'})",
              flush=True)
        return None if perdue else (name, vf, 0.0, False)

    targets, fmap, gaps = [], {}, {}
    workers = max(1, min(3, (os.cpu_count() or 2), len(plan)))
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            done = list(ex.map(_one, plan))
    else:
        done = [_one(j) for j in plan]
    for r in done:
        if not r:
            rap["perdues"] += 1
            continue
        targets.append(r[0])
        fmap[r[0]] = [r[1]]
        gaps[r[0]] = r[2]
        if r[3]:
            rap["assemblees"] += 1
        else:
            rap["repliees"] += 1
    rap["echecs_total"] += len(echecs)
    rap["echecs"] = echecs[:_MAX_ECHECS]
    if not targets:                        # aucun assemblage n'a abouti
        print("[noctus] aucun assemblage réussi -> template seul", flush=True)
        rap["assemblees"] = 0
        rap["repliees"] = rap["total"]     # le moteur rendra N fois le template nu
        rap["perdues"] = 0
        rap["raison"] = rap["raison"] or "aucun assemblage n'a abouti"
        return _sortie(_copier_source(), None, {})
    print(f"[noctus] {rap['assemblees']} variante(s) assemblée(s) avec une brute, "
          f"{rap['repliees']} sur template seul, {rap['perdues']} perdue(s) "
          f"(coupe à {cut:.2f}s, {len(brutes)} brute(s) dispo)", flush=True)
    return _sortie(targets, fmap, gaps)


def _shift_time(ts, gap):
    """Décale un temps 'HH:MM:SS(.mmm)' de -gap secondes (plancher 0).
    Le sentinelle '99:99:99' (= toute la vidéo) n'est jamais touché."""
    s = str(ts or "").strip()
    if not s or s.startswith("99:"):
        return s or "99:99:99"
    try:
        h, m, sec = s.split(":")
        total = float(h) * 3600 + float(m) * 60 + float(sec)
    except (ValueError, TypeError):
        return s
    return _hms_seconds(max(0.0, total - float(gap or 0)))


def shifted_caption_entry(entry, gap, new_label):
    """Copie d'une entrée captions avec tous les temps décalés de -gap.
    Sert aux variantes dont le DÉBUT a été coupé (brute plus courte que la
    place) : sans ce décalage, les captions minutées arriveraient en retard
    d'autant sur la vidéo raccourcie."""
    segs = []
    for sg in entry.get("captions") or []:
        c = dict(sg)
        c["start"] = _shift_time(c.get("start"), gap)
        c["end"] = _shift_time(c.get("end"), gap)
        segs.append(c)
    return {"label": new_label, "font": entry.get("font"), "captions": segs}


def caption_map_for(entry, targets, gaps, caps):
    """Construit le captionMap {fichier: [label]} d'une génération : les
    variantes rognées au début reçoivent une copie DÉCALÉE des captions
    (ajoutée à `caps`), les autres gardent l'entrée telle quelle.
    Renvoie None si aucune variante n'est rognée (comportement historique)."""
    if not entry or not any((gaps or {}).get(f, 0) > 0.01 for f in targets):
        return None
    cmap = {}
    for i, fn in enumerate(targets):
        g = (gaps or {}).get(fn, 0)
        if g > 0.01:
            lb = f"{entry['label']}_s{i + 1}"[:48]
            caps.append(shifted_caption_entry(entry, g, lb))
            cmap[fn] = [lb]
        else:
            cmap[fn] = [entry["label"]]
    return cmap


def gen_from_draft(src_path, draft, folders=None, model=None, brutes_dir=None,
                   report=None):
    """Génère une (ou N) variante MONTÉE d'un reel à partir d'un brouillon de montage
    {segments, font, style} — même moteur que l'éditeur web. À la demande (VA).
    Retourne le model_id (à poller via status()) ou None.

    `report` : dict FACULTATIF rempli sur place avec le rapport d'assemblage
    (voir _prepare_inputs / _rapport_vide). En particulier `repli` = True
    signale qu'au moins une vidéo livrée est le TEMPLATE ENTIER, sans vidéo
    brute. Le retour reste le model_id : le rapport est aussi relisible plus
    tard par assembly_report(model_id) et joint à status(model_id)."""
    import shutil as _sh
    import re as _re
    import time as _t
    import random as _rnd
    src = Path(src_path)
    if not src.exists() or not src.is_file():
        return None
    if not model:                                 # id UNIQUE par appel -> 2 VA simultanés
        base = _re.sub(r"[^a-zA-Z0-9_\-]", "", f"vam-{src.stem}")[:26]   # ne collisionnent pas
        model = f"{base}-{int(_t.time() * 1000) % 1000000}{_rnd.randint(100, 999)}"
    # PURGE des generations a la demande precedentes : chaque « Reel deja monte »
    # creait un dossier models/vam-... (video source + sorties) jamais supprime,
    # le disque du VPS se remplissait a l'infini. On garde les 12 plus recents.
    purge_old_models("vam-")
    inp = _models_dir() / model / "input"
    inp.mkdir(parents=True, exist_ok=True)
    for f in inp.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
    outdir = _models_dir() / model / "output"     # sorties fraîches à chaque appel
    try:
        if outdir.exists():
            _sh.rmtree(str(outdir), ignore_errors=True)
    except Exception:
        pass
    folders = folders or ["V1"]
    targets, folder_map, gaps = _prepare_inputs(src, inp, draft, folders, brutes_dir,
                                                report)
    label = ("vam_" + model)[:40]
    entry, _font = build_montage_caps(draft, label)
    # captions.json est PARTAGÉ (le runner Node le lit au démarrage) : on sérialise
    # lecture+écriture+spawn pour ne pas écraser le label d'une génération concurrente.
    # On garde les captions non-vam_ + les 200 dernières vam_ (évite la croissance infinie).
    with _GEN_LOCK:
        existing = read_captions()
        non_vam = [c for c in existing
                   if not (isinstance(c, dict) and str(c.get("label", "")).startswith("vam_"))]
        vam = [c for c in existing
               if isinstance(c, dict) and str(c.get("label", "")).startswith("vam_")
               and c.get("label") != label
               and not str(c.get("label", "")).startswith(label + "_s")][-200:]
        caps = non_vam + vam
        cmap = None
        if entry:
            caps.append(entry)
            sel = [label]
            # variantes rognées au début (brute courte) -> captions décalées
            cmap = caption_map_for(entry, targets, gaps, caps)
        else:
            if not any(isinstance(c, dict) and c.get("label") == "sans_texte" for c in caps):
                caps.append({"label": "sans_texte", "font": None, "captions": []})
            sel = ["sans_texte"]
        write_captions(caps)
        proc = run(model, folders, sel, targets=targets, folder_map=folder_map,
                   caption_map=cmap)
    return model if proc else None


def output_paths(model_id):
    """Liste des chemins absolus des mp4 générés pour un modèle."""
    out = []
    base = _models_dir() / _safe(model_id) / "output"
    if base.exists():
        for vf in V_FOLDERS:
            d = base / vf
            if d.exists():
                out.extend(sorted(d.glob("*.mp4")))
    return out


def stop(model_id: str) -> bool:
    mid = _safe(model_id)
    proc = _PROCS.get(mid)
    if not proc:
        return False
    if proc.poll() is not None:
        return True
    try:
        if os.name != "nt":
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)  # SIGTERM -> stopPipeline()
        else:
            proc.terminate()
        return True
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
        return False


# ---------- page HTML ----------
def render_page() -> str:
    from html import escape as esc
    models = list_models()
    caps = read_captions()
    cap_labels = [c.get("label", "") for c in caps if isinstance(c, dict) and c.get("label")]

    # Bandeau setup si Node/ffmpeg/deps manquent (probable sur le VPS au début)
    setup_banner = ""
    if not setup_ok():
        miss = []
        if not node_available():
            miss.append("Node.js")
        if not ffmpeg_available():
            miss.append("ffmpeg")
        if node_available() and not deps_installed():
            miss.append("@napi-rs/canvas (npm install)")
        ff_missing = not ffmpeg_available()
        if ff_missing:
            auto_block = (
                "<div style='margin-top:10px;font-size:12px;color:#fca5a5'>"
                "⚠️ <b>ffmpeg</b> manque et nécessite l'admin du VPS : "
                "<code style='color:#8ef'>sudo apt install -y ffmpeg</code></div>"
            )
        else:
            auto_block = (
                "<div style='margin-top:12px'>"
                "<button onclick='nxSetup(this)' style='padding:11px 20px;background:linear-gradient(135deg,#22c55e,#16a34a);"
                "border:0;color:#fff;border-radius:10px;font-weight:800;cursor:pointer;font-size:13px'>⚙️ Installer automatiquement</button>"
                "<span id='nx-setupmsg' style='margin-left:12px;font-size:12px;color:#aaa'></span>"
                "<div style='font-size:11px;color:#888;margin-top:6px'>télécharge Node + les dépendances sur le serveur, sans terminal (~1-2 min)</div>"
                "</div>"
            )
        setup_banner = (
            "<div style='background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.4);"
            "border-radius:12px;padding:16px 18px;margin-bottom:18px;color:#fca5a5;font-size:13px;line-height:1.6'>"
            "⚠️ <b>Setup incomplet sur ce serveur</b> — manque : <b>" + esc(", ".join(miss)) + "</b>."
            + auto_block +
            "<details style='margin-top:10px'><summary style='cursor:pointer;font-size:12px;color:#888'>ou en ligne de commande sur le VPS</summary>"
            "<code style='display:block;background:#0a0a0a;border:1px solid #2a2a2a;border-radius:8px;"
            "padding:10px 12px;margin-top:8px;color:#8ef;white-space:pre-wrap'>"
            "sudo apt install -y nodejs npm ffmpeg\n"
            "cd /opt/va-bot/noctus &amp;&amp; npm install &amp;&amp; sudo systemctl restart va-bot</code></details>"
            "</div>"
        )

    # Options modèles
    model_opts = "".join(
        f"<option value='{esc(m['id'])}'>{esc(m['id'])} — {m['inputs']} source(s), {m['outputs']} généré(s)</option>"
        for m in models
    )
    if not model_opts:
        model_opts = "<option value=''>(aucun modèle — crée-en un)</option>"

    # "Strong" = reproduction de la police Instagram Stories (Poppins italique gras)
    FONTS = ["Strong", "TikTokSans", "Inter", "Poppins", "Montserrat", "BebasNeue", "Anton"]
    # Strong = police par défaut (1er + selected)
    font_opts = "".join(f"<option{' selected' if f == 'Strong' else ''}>{f}</option>" for f in FONTS)

    cap_rows = ""
    for c in caps:
        if not isinstance(c, dict):
            continue
        lbl = c.get("label", "")
        font = c.get("font", "Strong") or "Strong"
        txt = "  ·  ".join(
            (seg.get("text", "") or "").replace("\n", " ")
            for seg in c.get("captions", []) if isinstance(seg, dict)
        )
        is_notext = (not txt) or lbl == "sans_texte"
        txt_disp = "<i style='color:#888'>— sans texte (juste les variations) —</i>" if is_notext else esc(txt)
        font_disp = "—" if is_notext else esc(font)
        # Badge timing (si chronométré)
        timing_badge = ""
        segs0 = c.get("captions", [])
        if segs0 and isinstance(segs0[0], dict) and not is_notext:
            en = (segs0[0].get("end", "") or "")
            if en and not en.startswith("99") and en != "∞":
                def _h2s(h):
                    try:
                        p = [int(x) for x in str(h).split(":")]
                        while len(p) < 3:
                            p = [0] + p
                        return p[0] * 3600 + p[1] * 60 + p[2]
                    except Exception:
                        return 0
                st = segs0[0].get("start", "00:00:00")
                timing_badge = (
                    f"<span style='font-size:10px;color:#fbbf24;background:#0a0a0a;border:1px solid #2a2a2a;"
                    f"padding:2px 6px;border-radius:5px;white-space:nowrap'>⏱ {_h2s(st)}–{_h2s(en)}s</span>"
                )
        cap_rows += (
            f"<label style='display:flex;align-items:center;gap:10px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:8px 12px'>"
            f"<input type='checkbox' class='nx-cap' value='{esc(lbl)}' checked style='accent-color:#a855f7'>"
            f"<span style='font-size:11px;color:#a855f7;font-weight:700;min-width:78px'>{font_disp}</span>"
            f"<span style='flex:1;font-size:13px;color:#ddd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{txt_disp}</span>"
            f"{timing_badge}"
            f"<button onclick='event.preventDefault();nxDelCaption(\"{esc(lbl)}\")' title='Supprimer' style='background:none;border:0;color:#666;cursor:pointer;font-size:15px'>🗑</button>"
            f"</label>"
        )
    if not cap_rows:
        cap_rows = "<span style='color:#666;font-size:12px'>aucune caption pour l'instant — écris-en une juste en dessous ⤵</span>"

    v_checks = "".join(
        f"<label style='display:inline-flex;align-items:center;gap:5px;background:#1a1a1a;border:1px solid #2a2a2a;"
        f"padding:6px 10px;border-radius:8px;font-size:12px;cursor:pointer'>"
        f"<input type='checkbox' class='nx-vf' value='{v}' {'checked' if v in ('V1','V2','V3') else ''} style='accent-color:#a855f7'> {v}</label>"
        for v in V_FOLDERS
    )

    caps_json = esc(json.dumps(caps, ensure_ascii=False, indent=2)) if caps else "[]"

    return f"""
<div style="max-width:1000px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">
    <h2 style="margin:0;font-size:22px">🎞️ Création de vidéos</h2>
    <span style="background:linear-gradient(135deg,#a855f7,#7c3aed);color:#fff;font-size:11px;font-weight:700;padding:3px 9px;border-radius:8px">V1 → V10 · anti-fingerprint</span>
  </div>
  <p style="margin:0 0 18px;color:#888;font-size:13px">Uploade une vidéo source → le pipeline génère jusqu'à 10 variations (zoom/couleurs/grain + captions) prêtes à poster.</p>
  {setup_banner}

  <!-- Modèles -->
  <div style="background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:18px;margin-bottom:16px">
    <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <div style="flex:1;min-width:220px">
        <label style="display:block;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px;font-weight:700;margin-bottom:6px">Modèle (projet)</label>
        <select id="nx-model" onchange="nxSelectModel()" style="width:100%;padding:10px 12px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:10px;font-size:13px">{model_opts}</select>
      </div>
      <div style="display:flex;gap:8px">
        <input id="nx-newmodel" placeholder="nouveau modèle…" style="padding:10px 12px;background:#1a1a1a;border:1px solid #2a2a2a;color:#fff;border-radius:10px;font-size:13px;width:160px">
        <button onclick="nxCreateModel()" style="padding:10px 16px;background:#1a1a1a;border:1px solid #3a3a3a;color:#ddd;border-radius:10px;font-weight:700;cursor:pointer;font-size:13px">+ Créer</button>
      </div>
    </div>
  </div>

  <!-- Upload -->
  <div style="background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:18px;margin-bottom:16px">
    <h3 style="margin:0 0 12px;font-size:15px">1. Vidéos sources</h3>
    <label id="nx-drop" style="display:flex;flex-direction:column;align-items:center;gap:8px;background:rgba(168,85,247,.05);border:2px dashed rgba(168,85,247,.35);border-radius:12px;padding:28px;cursor:pointer;position:relative">
      <input id="nx-files" type="file" accept="video/*" multiple style="position:absolute;inset:0;opacity:0;cursor:pointer">
      <div style="font-size:22px;color:#a855f7">+</div>
      <div style="color:#a855f7;font-weight:700;font-size:13px">Glisse tes vidéos ici (ou clique)</div>
      <div id="nx-droplbl" style="color:#666;font-size:12px">elles vont dans le dossier "input" du modèle</div>
    </label>
    <button onclick="nxUpload()" style="margin-top:12px;padding:10px 18px;background:linear-gradient(135deg,#a855f7,#7c3aed);border:0;color:#fff;border-radius:10px;font-weight:700;cursor:pointer;font-size:13px">⬆ Uploader</button>
    <div id="nx-inputs" style="margin-top:12px;color:#aaa;font-size:12px"></div>
  </div>

  <!-- Réglages + lancement -->
  <div style="background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:18px;margin-bottom:16px">
    <h3 style="margin:0 0 12px;font-size:15px">2. Variations &amp; captions</h3>
    <div style="font-size:12px;color:#888;margin-bottom:6px">Variations à générer :</div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px">{v_checks}</div>
    <button onclick="nxToggleAllV(this)" style="background:none;border:0;color:#a855f7;font-size:12px;cursor:pointer;padding:0">tout cocher / décocher</button>
    <div style="font-size:12px;color:#888;margin:14px 0 6px">Captions (texte incrusté sur la vidéo) — coche celles à appliquer :</div>
    <div id="nx-caps" style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px">{cap_rows}</div>
    <!-- Éditeur CapCut : place les textes sur la vidéo + timeline -->
    <button onclick="nxEdOpen()" style="display:flex;align-items:center;gap:10px;width:100%;justify-content:center;padding:14px;margin-bottom:12px;background:linear-gradient(135deg,#0ea5e9,#a855f7);border:0;color:#fff;border-radius:12px;font-weight:800;cursor:pointer;font-size:15px">
      🎬 Ouvrir l'éditeur CapCut <span style="font-weight:500;font-size:12px;opacity:.85">— place tes textes sur la vidéo, timeline, couleurs, tailles</span>
    </button>
    <div style="background:#0a0a0a;border:1px solid #2a2a2a;border-radius:10px;padding:14px">
      <div style="font-size:13px;color:#a855f7;font-weight:800;margin-bottom:8px">✍️ Écris ta caption ici :</div>
      <textarea id="nx-captext" placeholder="Le texte qui s'affichera sur la vidéo… (ex : Pov : quand tu rentres et que…)" style="width:100%;min-height:72px;background:#1a1a1a;border:1px solid #3a3a3a;color:#fff;border-radius:8px;padding:11px 13px;font-size:14px;resize:vertical;font-family:inherit;box-sizing:border-box;display:block"></textarea>
      <div style="display:flex;gap:10px;align-items:center;margin-top:9px;flex-wrap:wrap;font-size:12px;color:#aaa">
        <span style="color:#888">⏱ Affiché :</span>
        <label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer"><input type="radio" name="nxcaptime" value="perm" checked onchange="nxTimeToggle()" style="accent-color:#a855f7"> toute la vidéo</label>
        <label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer"><input type="radio" name="nxcaptime" value="range" onchange="nxTimeToggle()" style="accent-color:#a855f7"> de</label>
        <input id="nx-capstart" type="number" min="0" step="0.01" value="0" disabled style="width:64px;background:#1a1a1a;border:1px solid #3a3a3a;color:#fff;border-radius:6px;padding:5px 7px">
        <span>s à</span>
        <input id="nx-capend" type="number" min="0" step="0.01" value="3" disabled style="width:64px;background:#1a1a1a;border:1px solid #3a3a3a;color:#fff;border-radius:6px;padding:5px 7px">
        <span>s (le texte disparaît après)</span>
      </div>
      <div style="display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap">
        <span style="font-size:12px;color:#888">Police :</span>
        <select id="nx-capfont" title="Police" style="background:#1a1a1a;border:1px solid #3a3a3a;color:#fff;border-radius:8px;padding:9px 12px;font-size:13px;font-family:inherit">{font_opts}</select>
        <button onclick="nxAddCaption()" style="margin-left:auto;padding:11px 20px;background:linear-gradient(135deg,#a855f7,#7c3aed);border:0;color:#fff;border-radius:9px;font-weight:800;cursor:pointer;font-size:14px;white-space:nowrap">+ Ajouter la caption</button>
      </div>
    </div>
    <div style="font-size:12px;color:#888;margin-top:8px;line-height:1.5">💡 Pas obligé d'ajouter une caption : tu peux cliquer <b>▶ Générer</b> direct, ça fait les variations <b>sans texte</b>. Pour un test rapide : coche juste <b>V1</b> et génère.</div>
  </div>

  <!-- Run -->
  <div style="display:flex;gap:10px;align-items:center;margin-bottom:16px;flex-wrap:wrap">
    <button id="nx-run" onclick="nxRun()" style="padding:12px 24px;background:linear-gradient(135deg,#22c55e,#16a34a);border:0;color:#fff;border-radius:12px;font-weight:800;cursor:pointer;font-size:14px">▶ Générer</button>
    <button id="nx-stop" onclick="nxStop()" style="padding:12px 20px;background:#1a1a1a;border:1px solid #ef4444;color:#ef4444;border-radius:12px;font-weight:700;cursor:pointer;font-size:13px;display:none">⏹ Stop</button>
    <div id="nx-prog" style="flex:1;min-width:200px;display:none">
      <div style="height:10px;background:#1a1a1a;border-radius:6px;overflow:hidden"><div id="nx-bar" style="height:100%;width:0;background:linear-gradient(90deg,#a855f7,#22c55e);transition:width .4s"></div></div>
      <div id="nx-progtxt" style="font-size:11px;color:#888;margin-top:5px"></div>
    </div>
  </div>

  <!-- Outputs -->
  <div id="nx-outputs" style="background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:18px;margin-bottom:16px">
    <h3 style="margin:0 0 12px;font-size:15px">3. Résultats</h3>
    <div id="nx-outwrap" style="color:#666;font-size:12px">— sélectionne un modèle —</div>
  </div>

  <!-- Captions editor -->
  <details style="background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:14px 18px;margin-bottom:30px">
    <summary style="cursor:pointer;font-weight:700;font-size:14px;color:#ddd">📝 Éditer les captions (JSON)</summary>
    <p style="color:#888;font-size:12px;margin:10px 0">Format : liste de versions {{label, font, captions:[{{start,end,text}}]}}. Fonts : Strong (police Instagram), TikTokSans, Inter, Poppins, Montserrat, BebasNeue, Anton.</p>
    <textarea id="nx-capsjson" spellcheck="false" style="width:100%;min-height:200px;background:#0a0a0a;border:1px solid #2a2a2a;color:#8ef;border-radius:10px;padding:12px;font-family:monospace;font-size:12px">{caps_json}</textarea>
    <button onclick="nxSaveCaptions()" style="margin-top:10px;padding:9px 16px;background:#1a1a1a;border:1px solid #3a3a3a;color:#ddd;border-radius:10px;font-weight:700;cursor:pointer;font-size:13px">💾 Sauver les captions</button>
    <span id="nx-capsmsg" style="margin-left:10px;font-size:12px"></span>
  </details>
</div>

<script>
function nxModel(){{ const s=document.getElementById('nx-model'); return s? s.value : ''; }}
async function nxSetup(btn){{
  if(btn){{ btn.disabled=true; }}
  const msg=document.getElementById('nx-setupmsg');
  if(msg){{ msg.textContent='⏳ démarrage…'; }}
  try {{ await fetch('/noctus/setup',{{method:'POST'}}); nxSetupPoll(); }}
  catch(e){{ if(msg) msg.textContent='erreur: '+e; if(btn) btn.disabled=false; }}
}}
async function nxSetupPoll(){{
  const msg=document.getElementById('nx-setupmsg');
  const lbl={{downloading:'⏳ téléchargement de Node…',extracting:'⏳ extraction…',installing:'⏳ npm install (1-2 min)…',done:'✅ installé !',error:'❌ '}};
  try {{
    const r=await fetch('/noctus/setup_status'); const s=await r.json();
    if(msg) msg.textContent = (lbl[s.state]||'') + (s.state==='error'? (s.msg||'erreur'):'');
    if(s.state==='done'){{ setTimeout(function(){{ location.reload(); }}, 1200); return; }}
    if(s.state==='error'){{ return; }}
    setTimeout(nxSetupPoll, 2000);
  }} catch(e){{ setTimeout(nxSetupPoll, 3000); }}
}}
async function nxCreateModel(){{
  const n=(document.getElementById('nx-newmodel').value||'').trim();
  if(!n){{ alert('Nom du modèle ?'); return; }}
  const fd=new FormData(); fd.set('name', n);
  const r=await fetch('/noctus/create_model',{{method:'POST',body:fd}}); const j=await r.json();
  if(j.ok){{ location.reload(); }} else {{ alert('❌ '+(j.error||'?')); }}
}}
async function nxUpload(){{
  const m=nxModel(); if(!m){{ alert('Choisis/crée un modèle'); return; }}
  const inp=document.getElementById('nx-files'); if(!inp.files.length){{ alert('Aucune vidéo'); return; }}
  const fd=new FormData(); fd.set('model', m);
  for(const f of inp.files) fd.append('files', f);
  document.getElementById('nx-droplbl').textContent='⏳ upload…';
  const r=await fetch('/noctus/upload',{{method:'POST',body:fd}}); const j=await r.json();
  if(j.ok){{ inp.value=''; nxRefreshInputs(); document.getElementById('nx-droplbl').textContent='✓ '+(j.saved||0)+' ajoutée(s)'; }}
  else {{ alert('❌ '+(j.error||'?')); document.getElementById('nx-droplbl').textContent='erreur'; }}
}}
async function nxRefreshInputs(){{
  const m=nxModel(); if(!m){{ return; }}
  const r=await fetch('/noctus/inputs?model='+encodeURIComponent(m)); const j=await r.json();
  document.getElementById('nx-inputs').textContent = (j.files&&j.files.length)? ('📹 '+j.files.length+' source(s) : '+j.files.join(', ')) : 'aucune source';
}}
function nxToggleAllV(btn){{
  const cbs=document.querySelectorAll('.nx-vf'); const any=Array.from(cbs).some(c=>!c.checked);
  cbs.forEach(c=>c.checked=any);
}}
async function nxRun(){{
  const m=nxModel(); if(!m){{ alert('Choisis un modèle'); return; }}
  const folders=Array.from(document.querySelectorAll('.nx-vf:checked')).map(c=>c.value);
  const caps=Array.from(document.querySelectorAll('.nx-cap:checked')).map(c=>c.value);
  if(!folders.length){{ alert('Coche au moins une variation (V1…)'); return; }}
  const fd=new FormData(); fd.set('model',m); fd.set('folders',folders.join(',')); fd.set('captions',caps.join(','));
  const r=await fetch('/noctus/run',{{method:'POST',body:fd}}); const j=await r.json();
  if(!j.ok){{ alert('❌ '+(j.error||'?')); return; }}
  document.getElementById('nx-prog').style.display='block';
  document.getElementById('nx-stop').style.display='inline-block';
  document.getElementById('nx-run').disabled=true;
  nxPoll();
}}
async function nxStop(){{
  const m=nxModel(); const fd=new FormData(); fd.set('model',m);
  await fetch('/noctus/stop',{{method:'POST',body:fd}});
}}
let nxTimer=null;
async function nxPoll(){{
  const m=nxModel(); if(!m) return;
  const r=await fetch('/noctus/status?model='+encodeURIComponent(m)); const s=await r.json();
  const bar=document.getElementById('nx-bar'); const txt=document.getElementById('nx-progtxt');
  const pct = s.pct||0;
  bar.style.width = (s.state==='done'?100:pct)+'%';
  if(s.state==='running'){{ txt.textContent='⏳ '+(s.current||0)+'/'+(s.total||'?')+' — '+pct+'%'+(s.eta!=null?(' · ~'+s.eta+'s restantes'):''); }}
  else if(s.state==='done'){{ txt.textContent='✅ Terminé'; bar.style.width='100%'; }}
  else if(s.state==='stopped'){{ txt.textContent='⏹ Arrêté'; }}
  else if(s.state==='error'){{ txt.textContent='❌ '+(s.error||'erreur'); }}
  if(s.state==='running'){{ nxTimer=setTimeout(nxPoll, 1500); }}
  else {{
    document.getElementById('nx-stop').style.display='none';
    document.getElementById('nx-run').disabled=false;
    nxRefreshOutputs();
  }}
}}
async function nxRefreshOutputs(){{
  const m=nxModel(); const wrap=document.getElementById('nx-outwrap');
  if(!m){{ wrap.textContent='— sélectionne un modèle —'; return; }}
  const r=await fetch('/noctus/outputs?model='+encodeURIComponent(m)); const j=await r.json();
  const o=j.outputs||{{}}; const keys=Object.keys(o);
  if(!keys.length){{ wrap.innerHTML='<span style=color:#666>aucun résultat encore — lance une génération</span>'; return; }}
  let html='';
  keys.forEach(v=>{{
    html+='<div style="margin-bottom:12px"><div style="font-weight:700;color:#a855f7;font-size:12px;margin-bottom:6px">'+v+'</div><div style="display:flex;flex-wrap:wrap;gap:10px">';
    o[v].forEach(f=>{{
      const url='/noctus/file/'+encodeURIComponent(m)+'/'+v+'/'+encodeURIComponent(f);
      html+='<div style="width:130px"><video src="'+url+'#t=0.1" controls muted playsinline preload="metadata" style="width:130px;aspect-ratio:9/16;object-fit:cover;border-radius:8px;background:#000"></video><a href="'+url+'?dl=1" download="'+f+'" style="display:block;text-align:center;color:#8ef;font-size:11px;margin-top:3px;text-decoration:none">⬇ télécharger</a></div>';
    }});
    html+='</div></div>';
  }});
  wrap.innerHTML=html;
}}
function nxTimeToggle(){{
  const sel=document.querySelector('input[name=nxcaptime]:checked');
  const range = sel && sel.value==='range';
  const a=document.getElementById('nx-capstart'), b=document.getElementById('nx-capend');
  if(a) a.disabled=!range; if(b) b.disabled=!range;
}}
async function nxAddCaption(){{
  const ta=document.getElementById('nx-captext'); const text=(ta.value||'').trim();
  if(!text){{ alert('Écris un texte'); return; }}
  const font=document.getElementById('nx-capfont').value;
  const fd=new FormData(); fd.set('text',text); fd.set('font',font);
  const sel=document.querySelector('input[name=nxcaptime]:checked');
  if(sel && sel.value==='range'){{
    fd.set('start_s', document.getElementById('nx-capstart').value||'0');
    fd.set('end_s', document.getElementById('nx-capend').value||'999');
  }}
  const r=await fetch('/noctus/add_caption',{{method:'POST',body:fd}}); const j=await r.json();
  if(j.ok){{ location.reload(); }} else {{ alert('❌ '+(j.error||'?')); }}
}}
async function nxDelCaption(label){{
  if(!confirm('Supprimer cette caption ?')) return;
  const fd=new FormData(); fd.set('label',label);
  const r=await fetch('/noctus/del_caption',{{method:'POST',body:fd}}); const j=await r.json();
  if(j.ok){{ location.reload(); }} else {{ alert('❌ '+(j.error||'?')); }}
}}
async function nxSaveCaptions(){{
  const ta=document.getElementById('nx-capsjson'); const msg=document.getElementById('nx-capsmsg');
  let data; try {{ data=JSON.parse(ta.value); }} catch(e){{ msg.style.color='#ef4444'; msg.textContent='JSON invalide'; return; }}
  const fd=new FormData(); fd.set('json', JSON.stringify(data));
  const r=await fetch('/noctus/captions',{{method:'POST',body:fd}}); const j=await r.json();
  if(j.ok){{ msg.style.color='#22c55e'; msg.textContent='✓ sauvé — recharge pour voir les versions'; }}
  else {{ msg.style.color='#ef4444'; msg.textContent='❌ '+(j.error||'?'); }}
}}
function nxSelectModel(){{ nxRefreshInputs(); nxRefreshOutputs(); }}
// init
setTimeout(function(){{ if(document.getElementById('nx-model') && nxModel()){{ nxRefreshInputs(); nxRefreshOutputs(); }} }}, 200);
</script>
<script src="/noctus/editor.js" defer></script>
"""


# ---------- routes ----------
def register(app, is_auth, error_fn, success_fn):
    from flask import request, jsonify, send_file, redirect

    @app.route("/noctus/create_model", methods=["POST"])
    def noctus_create_model():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        mid = _safe(request.form.get("name") or "")
        if not mid:
            return jsonify({"ok": False, "error": "nom invalide"})
        (_models_dir() / mid / "input").mkdir(parents=True, exist_ok=True)
        return jsonify({"ok": True, "model": mid})

    @app.route("/noctus/upload", methods=["POST"])
    def noctus_upload():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        from werkzeug.utils import secure_filename
        mid = _safe(request.form.get("model") or "")
        if not mid:
            return jsonify({"ok": False, "error": "modèle manquant"})
        inp = _models_dir() / mid / "input"
        inp.mkdir(parents=True, exist_ok=True)
        saved = 0
        for f in request.files.getlist("files"):
            if not f or not f.filename:
                continue
            name = secure_filename(f.filename)
            if not name or Path(name).suffix.lower() not in VIDEO_EXTS:
                continue
            f.save(str(inp / name))
            saved += 1
        return jsonify({"ok": True, "saved": saved})

    @app.route("/noctus/inputs", methods=["GET"])
    def noctus_inputs():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        mid = _safe(request.args.get("model") or "")
        inp = _models_dir() / mid / "input"
        files = sorted([f.name for f in inp.glob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXTS]) if inp.exists() else []
        return jsonify({"ok": True, "files": files})

    @app.route("/noctus/run", methods=["POST"])
    def noctus_run():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        if not setup_ok():
            return jsonify({"ok": False, "error": "Setup incomplet (Node/ffmpeg/canvas) — voir le bandeau"})
        mid = _safe(request.form.get("model") or "")
        if not mid or not (_models_dir() / mid / "input").exists():
            return jsonify({"ok": False, "error": "modèle introuvable"})
        folders = [f for f in (request.form.get("folders") or "").split(",") if f in V_FOLDERS]
        if not folders:
            return jsonify({"ok": False, "error": "coche au moins une variation (V1…)"})
        captions = [c for c in (request.form.get("captions") or "").split(",") if c.strip()]
        if not captions:
            # Aucune caption -> on génère quand même, SANS texte (juste les variations).
            caps = read_captions()
            if not any(isinstance(c, dict) and c.get("label") == "sans_texte" for c in caps):
                caps.append({"label": "sans_texte", "font": None, "captions": []})
                write_captions(caps)
            captions = ["sans_texte"]
        proc = run(mid, folders, captions)
        if not proc:
            return jsonify({"ok": False, "error": "lancement impossible"})
        return jsonify({"ok": True})

    @app.route("/noctus/stop", methods=["POST"])
    def noctus_stop():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        ok = stop(_safe(request.form.get("model") or ""))
        return jsonify({"ok": True, "stopped": ok})

    @app.route("/noctus/status", methods=["GET"])
    def noctus_status():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        return jsonify(status(_safe(request.args.get("model") or "")))

    @app.route("/noctus/outputs", methods=["GET"])
    def noctus_outputs():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        return jsonify({"ok": True, "outputs": list_outputs(_safe(request.args.get("model") or ""))})

    @app.route("/noctus/file/<model>/<vf>/<path:name>", methods=["GET"])
    def noctus_file(model, vf, name):
        if not is_auth():
            return redirect("/")
        mid = _safe(model)
        if vf not in V_FOLDERS or "/" in name or "\\" in name or ".." in name:
            return "Not found", 404
        base = (_models_dir() / mid / "output" / vf).resolve()
        p = (base / name).resolve()
        if not str(p).startswith(str(base)) or not p.exists() or not p.is_file():
            return "Not found", 404
        dl = request.args.get("dl") == "1"   # ?dl=1 -> force le téléchargement
        return send_file(str(p), mimetype="video/mp4",
                         as_attachment=dl, download_name=name, conditional=True)

    @app.route("/noctus/input_file/<model>/<path:name>", methods=["GET"])
    def noctus_input_file(model, name):
        """Stream d'une vidéo SOURCE (input/) — preview de l'éditeur CapCut."""
        if not is_auth():
            return redirect("/")
        mid = _safe(model)
        if "/" in name or "\\" in name or ".." in name:
            return "Not found", 404
        base = (_models_dir() / mid / "input").resolve()
        p = (base / name).resolve()
        if not str(p).startswith(str(base)) or not p.exists() or not p.is_file():
            return "Not found", 404
        return send_file(str(p), mimetype="video/mp4", conditional=True)

    @app.route("/noctus/save_version", methods=["POST"])
    def noctus_save_version():
        """Upsert d'une VERSION de captions depuis l'éditeur CapCut.
        Params : label, font (défaut version), json = liste de captions
        [{start,end,text,x,y,size,color,font}] (style optionnel par caption)."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        label = re.sub(r"[^A-Za-z0-9_\-]", "_", (request.form.get("label") or "").strip())[:40]
        if not label:
            return jsonify({"ok": False, "error": "nom de version invalide"})
        font = (request.form.get("font") or "").strip() or None
        try:
            raw = json.loads(request.form.get("json") or "[]")
            assert isinstance(raw, list)
        except Exception as e:
            return jsonify({"ok": False, "error": f"JSON invalide: {e}"})
        segs = []
        for c in raw:
            if not isinstance(c, dict) or not (c.get("text") or "").strip():
                continue
            seg = {"start": str(c.get("start") or "00:00:00.000"),
                   "end": str(c.get("end") or "99:99:99.000"),
                   "text": str(c.get("text"))[:500]}
            # Style optionnel (éditeur) — champs absents = comportement historique
            try:
                if c.get("x") is not None:
                    seg["x"] = max(0.03, min(0.97, float(c["x"])))
                if c.get("y") is not None:
                    seg["y"] = max(0.03, min(0.96, float(c["y"])))
                if c.get("size") is not None:
                    seg["size"] = max(16, min(160, int(c["size"])))
            except Exception:
                pass
            col = str(c.get("color") or "")
            if re.match(r"^#[0-9a-fA-F]{3,8}$", col):
                seg["color"] = col
            if c.get("font"):
                seg["font"] = str(c["font"])[:40]
            segs.append(seg)
        caps = read_captions()
        caps = [c for c in caps if not (isinstance(c, dict) and c.get("label") == label)]
        caps.append({"label": label, "font": font, "captions": segs})
        if write_captions(caps):
            return jsonify({"ok": True, "label": label, "count": len(segs)})
        return jsonify({"ok": False, "error": "écriture échouée"})

    @app.route("/noctus/editor.js", methods=["GET"])
    def noctus_editor_js():
        """JS de l'éditeur CapCut (fichier séparé -> pas d'enfer d'échappement)."""
        if not is_auth():
            return "", 401
        p = BOT_DIR / "noctus_editor.js"
        if not p.exists():
            return "// editor manquant", 404
        return send_file(str(p), mimetype="text/javascript", conditional=True)

    @app.route("/noctus/captions", methods=["GET", "POST"])
    def noctus_captions():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        if request.method == "GET":
            return jsonify({"ok": True, "captions": read_captions()})
        try:
            data = json.loads(request.form.get("json") or "[]")
        except Exception as e:
            return jsonify({"ok": False, "error": f"JSON invalide: {e}"})
        if write_captions(data):
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "écriture échouée (doit être une liste)"})

    @app.route("/noctus/add_caption", methods=["POST"])
    def noctus_add_caption():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        text = (request.form.get("text") or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "texte vide"})
        font = (request.form.get("font") or "Strong").strip() or "Strong"

        def _sec_to_hms(v):
            # garde les décimales (millisecondes) -> timing précis au centième
            try:
                sec = max(0.0, float(v))
            except Exception:
                sec = 0.0
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s = sec - h * 3600 - m * 60
            return f"{h:02d}:{m:02d}:{s:06.3f}"

        # Timing : si start_s/end_s fournis (secondes) -> texte chronométré, sinon permanent
        start_s = request.form.get("start_s")
        end_s = request.form.get("end_s")
        if start_s is not None and end_s is not None:
            start = _sec_to_hms(start_s)
            end = _sec_to_hms(end_s)
        else:
            start = (request.form.get("start") or "00:00:00").strip() or "00:00:00"
            end = (request.form.get("end") or "99:99:99").strip() or "99:99:99"
        caps = read_captions()
        existing = {c.get("label") for c in caps if isinstance(c, dict)}
        i = 1
        while f"v{i}" in existing:
            i += 1
        label = f"v{i}"
        caps.append({"label": label, "font": font,
                     "captions": [{"start": start, "end": end, "text": text}]})
        if write_captions(caps):
            return jsonify({"ok": True, "label": label})
        return jsonify({"ok": False, "error": "écriture échouée"})

    @app.route("/noctus/del_caption", methods=["POST"])
    def noctus_del_caption():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        label = (request.form.get("label") or "").strip()
        caps = [c for c in read_captions() if not (isinstance(c, dict) and c.get("label") == label)]
        write_captions(caps)
        return jsonify({"ok": True})

    @app.route("/noctus/setup", methods=["POST"])
    def noctus_setup():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        started = start_setup()
        return jsonify({"ok": True, "started": started})

    @app.route("/noctus/setup_status", methods=["GET"])
    def noctus_setup_status():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        return jsonify(_setup_status())
