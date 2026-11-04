#!/usr/bin/env python3
"""visage_worker.py — la machine qui fait les remplacements de visage du
Studio IA (youl4b.com), avec FaceFusion, en local et gratuitement.

Le site garde la file (studio_ia.py) ; ce programme, lancé sur une machine à
nous (le Mac du propriétaire aujourd'hui, le VPS quand il aura 2 Go de
libre), vient chercher le travail toutes les 10 s, télécharge la photo du
visage et la vidéo, lance FaceFusion, renvoie l'avancement puis le fichier.

Bibliothèque standard seulement (le Mac n'a que Python 3.9 hors venv) :
urllib, subprocess, json. FaceFusion tourne dans son propre venv (Python
3.10+), installé par `installer`.

    python3 visage_worker.py installer --site https://youl4b.com
        clone FaceFusion 3.9.2 + venv + dépendances (les modèles, ~1,7 Go,
        se téléchargent au premier travail), garde site/jeton dans
        ~/.vabot/visage/config.json, pose un agent launchd (macOS) qui le
        relance à l'ouverture de session. Aucun secret à recopier : la
        machine tire son propre jeton, se présente au site, et un admin
        l'accepte dans Studio IA (genre Visage). `--jeton` reste possible
        (jeton maître du site) pour brancher sans accord.
    python3 visage_worker.py tourner [--une-fois]
        la boucle (c'est ce que launchd lance).
    python3 visage_worker.py etat
        ce qui est installé, la dernière erreur.

Il se met à jour seul : le site sert sa propre copie (git) et son empreinte ;
quand elle change, le fichier est remplacé et le programme se relance.
"""
import argparse
import glob
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

DOSSIER_DEFAUT = os.path.join(os.path.expanduser("~"), ".vabot", "visage")
SITE_DEFAUT = "https://youl4b.com"
DEPOT_FACEFUSION = "https://github.com/facefusion/facefusion.git"
VERSION_FACEFUSION = "3.9.2"
#: Ce dont headless-run a besoin ; gradio (l'interface web) n'est pas
#: installé : 300 Mo pour rien, et il n'est importé que par `run`.
PAQUETS = ["onnxruntime", "numpy", "opencv-python-headless", "tqdm", "scipy", "onnx"]
PAUSE_S = 10
#: FaceFusion écrit sa progression par tqdm : « processing:  45%|███ | 150/333 ».
_RE_TQDM = re.compile(r"(analysing|extracting|processing|merging)\s*:\s*(\d+)%\|[^|]*\|\s*(\d+)/(\d+)", re.I)
#: Part de chaque étape dans la barre (l'analyse et l'extraction sont
#: rapides, le remplacement est le gros morceau).
_PARTS = {"analysing": (0, 8), "extracting": (8, 14), "processing": (14, 94), "merging": (94, 100)}
ETIQUETTE = "com.youl4b.visage"
#: Où ffmpeg se cache quand launchd ne donne qu'un PATH réduit : sur le Mac
#: du propriétaire il est dans ~/.local/bin (binaire statique) et FaceFusion
#: répondait « ffmpeg is not installed » au premier travail (04/11).
DOSSIERS_FFMPEG = [os.path.join(os.path.expanduser("~"), ".local", "bin"), "/opt/homebrew/bin",
                   "/usr/local/bin", "/usr/bin"]


def trouver_ffmpeg(conf=None, dossier=None):
    """Chemin d'un ffmpeg exécutable, ou None. L'ordre : celui noté dans la
    config, le PATH courant, le venv, puis les dossiers habituels."""
    cands = []
    if conf and conf.get("ffmpeg"):
        cands.append(conf["ffmpeg"])
    w = shutil.which("ffmpeg")
    if w:
        cands.append(w)
    if dossier:
        cands.append(os.path.join(dossier, "venv", "bin", "ffmpeg"))
    cands += [os.path.join(d, "ffmpeg") for d in DOSSIERS_FFMPEG]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)
    return None


def env_facefusion(ffmpeg):
    """L'environnement de FaceFusion : le dossier de ffmpeg (et de ffprobe,
    à côté) devant le PATH, quel que soit celui que launchd a donné."""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(ffmpeg) + os.pathsep + env.get("PATH", "")
    return env


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


# ------------------------------------------------------------ réglages --

def chemin_config(dossier):
    return os.path.join(dossier, "config.json")


def lire_config(dossier):
    try:
        with open(chemin_config(dossier), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def ecrire_config(dossier, conf):
    os.makedirs(dossier, exist_ok=True)
    tmp = chemin_config(dossier) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=2)
    os.replace(tmp, chemin_config(dossier))
    try:
        os.chmod(chemin_config(dossier), 0o600)
    except OSError:
        pass


def nom_machine_defaut():
    n = platform.node().split(".")[0] or "machine"
    return n[:40]


# ------------------------------------------------------- installation --

def python_recent():
    """Un Python 3.10+ pour le venv de FaceFusion (le python3 du Mac est 3.9)."""
    candidats = []
    for motif in ("~/.local/share/uv/python/cpython-3.1[0-9]*/bin/python3.1[0-9]",
                  "/opt/homebrew/bin/python3.1[0-9]", "/usr/local/bin/python3.1[0-9]",
                  "/usr/bin/python3.1[0-9]"):
        candidats.extend(sorted(glob.glob(os.path.expanduser(motif)), reverse=True))
    for nom in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
        p = shutil.which(nom)
        if p:
            candidats.append(p)
    for c in candidats:
        try:
            v = subprocess.run([c, "-c", "import sys;print(sys.version_info[0],sys.version_info[1])"],
                               capture_output=True, text=True, timeout=20).stdout.split()
            if len(v) == 2 and int(v[0]) == 3 and int(v[1]) >= 10:
                return c
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return None


def chemins(dossier):
    return {
        "app": os.path.join(dossier, "app"),
        "venv": os.path.join(dossier, "venv"),
        "python": os.path.join(dossier, "venv", "bin", "python"),
        "travaux": os.path.join(dossier, "travaux"),
        "tmp": os.path.join(dossier, "tmp"),
        "journal": os.path.join(dossier, "worker.log"),
        "moi": os.path.join(dossier, "visage_worker.py"),
    }


def installer_facefusion(dossier):
    c = chemins(dossier)
    os.makedirs(dossier, exist_ok=True)
    if not os.path.exists(os.path.join(c["app"], "facefusion.py")):
        log("clone de FaceFusion %s…" % VERSION_FACEFUSION)
        subprocess.run(["git", "clone", "--depth", "1", "--branch", VERSION_FACEFUSION, DEPOT_FACEFUSION, c["app"]],
                       check=True)
    else:
        log("FaceFusion déjà là : %s" % c["app"])
    if not os.path.exists(c["python"]):
        py = python_recent()
        if not py:
            raise SystemExit("Aucun Python 3.10+ trouvé (installe-le : brew install python@3.12, ou uv python install 3.12).")
        log("venv avec %s…" % py)
        subprocess.run([py, "-m", "venv", c["venv"]], check=True)
        subprocess.run([c["python"], "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([c["python"], "-m", "pip", "install"] + PAQUETS, check=True)
    else:
        log("venv déjà là : %s" % c["venv"])
    for d in (c["travaux"], c["tmp"]):
        os.makedirs(d, exist_ok=True)


def plist_launchd(dossier, ffmpeg=None):
    c = chemins(dossier)
    # launchd ne lit pas le profil du shell : sans ~/.local/bin dans ce PATH,
    # le ffmpeg du Mac restait invisible (04/11).
    path = []
    for d in ([os.path.dirname(ffmpeg)] if ffmpeg else []) + [os.path.join(c["venv"], "bin")] + DOSSIERS_FFMPEG + ["/bin"]:
        if d not in path:
            path.append(d)
    # --dossier avant la sous-commande : un worker d'avant le 04/11 ne le
    # comprenait qu'a cette place et mourait « unrecognized arguments »
    # toutes les 30 s sous launchd.
    args = [c["python"], c["moi"], "--dossier", dossier, "tourner"]
    lignes = "".join("    <string>%s</string>\n" % a.replace("&", "&amp;").replace("<", "&lt;") for a in args)
    return ("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key>
  <array>
%s  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>%s</string>
  <key>StandardErrorPath</key><string>%s</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>%s</string></dict>
</dict>
</plist>
""" % (ETIQUETTE, lignes, c["journal"], c["journal"], ":".join(path).replace("&", "&amp;")))


def poser_agent(dossier):
    """macOS : un agent launchd qui tourne à l'ouverture de session et se
    relance s'il tombe. Ailleurs : dire quoi faire."""
    if sys.platform != "darwin":
        log("Pas macOS : lance `%s %s tourner --dossier %s` sous systemd ou screen."
            % (chemins(dossier)["python"], chemins(dossier)["moi"], dossier))
        return
    rep = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(rep, exist_ok=True)
    plist = os.path.join(rep, ETIQUETTE + ".plist")
    with open(plist, "w", encoding="utf-8") as f:
        f.write(plist_launchd(dossier, trouver_ffmpeg(lire_config(dossier), dossier)))
    uid = str(os.getuid())
    subprocess.run(["launchctl", "bootout", "gui/" + uid, plist], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", "gui/" + uid, plist], capture_output=True, text=True)
    if r.returncode != 0:
        log("launchctl bootstrap : %s" % (r.stderr or r.stdout).strip())
        subprocess.run(["launchctl", "load", plist], capture_output=True)
    log("agent launchd posé : %s (journal : %s)" % (plist, chemins(dossier)["journal"]))


def installer(args):
    dossier = os.path.abspath(os.path.expanduser(args.dossier))
    conf = lire_config(dossier)
    if args.site:
        conf["site"] = args.site.rstrip("/")
    if args.jeton:
        conf["jeton"] = args.jeton.strip()
    if args.nom:
        conf["nom"] = args.nom
    conf.setdefault("site", SITE_DEFAUT)
    conf.setdefault("nom", nom_machine_defaut())
    conf.setdefault("threads", max(1, min(8, (os.cpu_count() or 2) // 2)))
    if not conf.get("jeton"):
        conf["jeton"] = secrets.token_hex(24)     # le nôtre : le site l'acceptera
        conf["acceptee"] = False
    installer_facefusion(dossier)
    ff = trouver_ffmpeg(conf, dossier)
    if ff:
        conf["ffmpeg"] = ff
        log("ffmpeg : %s" % ff)
    else:
        conf.pop("ffmpeg", None)
        log("ATTENTION : ffmpeg introuvable (PATH, ~/.local/bin, Homebrew) : FaceFusion en a besoin. "
            "Installe-le (brew install ffmpeg) puis relance `installer`.")
    ecrire_config(dossier, conf)
    moi = chemins(dossier)["moi"]
    if os.path.abspath(__file__) != os.path.abspath(moi):
        shutil.copyfile(__file__, moi)
    poser_agent(dossier)
    log("Installé. La machine « %s » se présente à %s : un admin doit l'accepter dans Studio IA (genre Visage) ; "
        "les modèles (~1,7 Go) se téléchargent au premier travail." % (conf["nom"], conf["site"]))


# ---------------------------------------------------------------- site --

class Site:
    def __init__(self, base, jeton, nom):
        self.base, self.jeton, self.nom = base.rstrip("/"), jeton, nom

    def _req(self, chemin, data=None, headers=None, timeout=60):
        h = {"X-Visage-Jeton": self.jeton, "User-Agent": "visage_worker/1"}
        h.update(headers or {})
        req = urllib.request.Request(self.base + chemin, data=data, headers=h, method="POST" if data is not None else "GET")
        return urllib.request.urlopen(req, timeout=timeout)

    def json(self, chemin, corps=None, timeout=60):
        data = None
        headers = {}
        if corps is not None:
            data = json.dumps(corps).encode("utf-8")
            headers["Content-Type"] = "application/json"
        with self._req(chemin, data, headers, timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def telecharger(self, chemin, dest):
        with self._req(chemin, timeout=600) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)

    def envoyer_fichier(self, chemin, fichier, champs=None):
        limite = "----visage" + uuid.uuid4().hex
        corps = bytearray()
        for k, v in (champs or {}).items():
            corps += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (limite, k, v)).encode("utf-8")
        corps += ("--%s\r\nContent-Disposition: form-data; name=\"fichier\"; filename=\"%s\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n" % (limite, os.path.basename(fichier))).encode("utf-8")
        with open(fichier, "rb") as f:
            corps += f.read()
        corps += ("\r\n--%s--\r\n" % limite).encode("utf-8")
        with self._req(chemin, bytes(corps), {"Content-Type": "multipart/form-data; boundary=" + limite}, timeout=1800) as r:
            return json.loads(r.read().decode("utf-8") or "{}")


# ------------------------------------------------------------- travail --

def commande_facefusion(c, finition, visage, cible, sortie, threads):
    proc = ["face_swapper"] + ([] if finition == "rapide" else ["face_enhancer"])
    cmd = [c["python"], "facefusion.py", "headless-run",
           "--source-paths", visage, "--target-path", cible, "--output-path", sortie,
           "--processors"] + proc + [
           "--face-swapper-model", "hyperswap_1a_256", "--face-swapper-pixel-boost", "512x512",
           "--execution-providers", "cpu", "--execution-thread-count", str(threads),
           "--face-selector-mode", "one", "--face-mask-types", "box", "occlusion",
           "--output-video-quality", "90", "--temp-path", c["tmp"], "--log-level", "info"]
    if finition != "rapide":
        cmd += ["--face-enhancer-model", "gfpgan_1.4", "--face-enhancer-blend", "70"]
    return cmd


def faire(site, dossier, conf, tache):
    c = chemins(dossier)
    tid = tache["id"]
    rep = os.path.join(c["travaux"], tid)
    os.makedirs(rep, exist_ok=True)
    visage = cible = None
    for e in tache.get("entrees") or []:
        ext = e.get("ext") or (".png" if e["role"] == "visage" else ".mp4")
        dest = os.path.join(rep, e["role"] + ext)
        log("%s : téléchargement %s" % (tid, e["role"]))
        site.telecharger(e["url"], dest)
        if e["role"] == "visage":
            visage = dest
        else:
            cible = dest
    if not visage or not cible:
        raise RuntimeError("entrées incomplètes (photo + vidéo attendues)")
    sortie = os.path.join(rep, "sortie" + os.path.splitext(cible)[1].lower())
    ff = trouver_ffmpeg(conf, dossier)
    if not ff:
        raise RuntimeError("ffmpeg introuvable sur « %s » (PATH, ~/.local/bin, Homebrew) : "
                           "installe-le (brew install ffmpeg) puis relance `installer`" % site.nom)
    cmd = commande_facefusion(c, tache.get("finition") or "nette", visage, cible, sortie, int(conf.get("threads") or 4))
    log("%s : FaceFusion (%s), ffmpeg %s" % (tid, tache.get("finition") or "nette", ff))
    p = subprocess.Popen(cmd, cwd=c["app"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         errors="replace", bufsize=1, env=env_facefusion(ff))
    dernier_envoi, dernier_pct, dernier_etape = 0.0, -1, ""
    dernieres = []
    tampon = ""
    while True:
        ch = p.stdout.read(1)
        if ch == "" and p.poll() is not None:
            break
        if ch in ("\r", "\n", ""):
            ligne, tampon = tampon.strip(), ""
            if not ligne:
                continue
            m = _RE_TQDM.search(ligne)
            if m:
                etape = m.group(1).lower()
                fait, total = int(m.group(3)), max(1, int(m.group(4)))
                base, fin = _PARTS.get(etape, (0, 100))
                pct = int(base + (fin - base) * fait / total)
            elif "download" in ligne.lower():
                etape, pct = "modeles", max(dernier_pct, 0)
            else:
                dernieres.append(ligne[:300])
                dernieres = dernieres[-12:]
                continue
            if (pct != dernier_pct or etape != dernier_etape) and time.time() - dernier_envoi > 2:
                try:
                    site.json("/studio-ia/visage/avancement/" + tid, {"progression": pct, "etape": etape, "machine": site.nom})
                except (urllib.error.URLError, OSError, ValueError) as e:
                    log("avancement non envoyé : %s" % e)
                dernier_envoi, dernier_pct, dernier_etape = time.time(), pct, etape
        else:
            tampon += ch
    code = p.wait()
    if code != 0 or not os.path.exists(sortie) or os.path.getsize(sortie) < 1000:
        detail = " | ".join(l for l in dernieres if "[FACEFUSION" in l or "error" in l.lower()) or " | ".join(dernieres[-3:])
        raise RuntimeError("FaceFusion a échoué (code %s) : %s" % (code, detail[:380]))
    try:
        site.json("/studio-ia/visage/avancement/" + tid, {"progression": 100, "etape": "envoi", "machine": site.nom})
    except (urllib.error.URLError, OSError, ValueError):
        pass
    log("%s : envoi du résultat (%d octets)" % (tid, os.path.getsize(sortie)))
    r = site.envoyer_fichier("/studio-ia/visage/resultat/" + tid, sortie, {"machine": site.nom})
    if not r.get("ok"):
        raise RuntimeError("le site a refusé le résultat : %s" % r)
    shutil.rmtree(rep, ignore_errors=True)
    log("%s : terminé" % tid)


def mon_sha():
    try:
        with open(os.path.abspath(__file__), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def se_mettre_a_jour(site, sha_site):
    """Le site sert la version de git ; si elle diffère, on la prend et on
    se relance (launchd garde le même processus de vue)."""
    if not sha_site or sha_site == mon_sha():
        return
    moi = os.path.abspath(__file__)
    try:
        with site._req("/studio-ia/visage/worker.py", timeout=60) as r:
            neuf = r.read()
    except (urllib.error.URLError, OSError) as e:
        log("mise à jour impossible : %s" % e)
        return
    if hashlib.sha256(neuf).hexdigest() != sha_site or b"def tourner(" not in neuf:
        log("mise à jour ignorée : empreinte ou contenu inattendu")
        return
    tmp = moi + ".neuf"
    with open(tmp, "wb") as f:
        f.write(neuf)
    os.replace(tmp, moi)
    log("mis à jour (%s…), relance" % sha_site[:10])
    os.execv(sys.executable, [sys.executable, moi] + sys.argv[1:])


def se_presenter(site, dossier, conf):
    """Appairage : tant que le site n'a pas accepté notre jeton, on se
    représente toutes les 10 s (un admin clique Accepter dans Studio IA)."""
    try:
        d = site.json("/studio-ia/visage/machine", {"nom": site.nom, "jeton": site.jeton}, timeout=30)
    except urllib.error.HTTPError as e:
        log("présentation refusée : HTTP %s" % e.code)
        return False
    except (urllib.error.URLError, OSError, ValueError) as e:
        log("site injoignable : %s" % e)
        return False
    if d.get("etat") == "acceptee":
        conf["acceptee"] = True
        ecrire_config(dossier, conf)
        log("machine acceptée par le site")
        return True
    return False


def tourner(args):
    dossier = os.path.abspath(os.path.expanduser(args.dossier))
    conf = lire_config(dossier)
    if not conf.get("site"):
        conf["site"] = SITE_DEFAUT
    if not conf.get("jeton"):
        conf["jeton"] = secrets.token_hex(24)
        conf["acceptee"] = False
        conf.setdefault("nom", nom_machine_defaut())
        ecrire_config(dossier, conf)
    c = chemins(dossier)
    if not os.path.exists(c["python"]):
        raise SystemExit("FaceFusion n'est pas installé dans %s : lance `installer`." % dossier)
    site = Site(conf["site"], conf["jeton"], conf.get("nom") or nom_machine_defaut())
    log("machine « %s » branchée sur %s (dossier %s)" % (site.nom, site.base, dossier))
    dernier_mot = 0.0
    while True:
        if not conf.get("acceptee"):
            if not se_presenter(site, dossier, conf):
                if time.time() - dernier_mot > 60:
                    log("en attente d'acceptation sur le site (Studio IA > Visage > Accepter « %s »)" % site.nom)
                    dernier_mot = time.time()
                if args.une_fois:
                    return
                time.sleep(PAUSE_S)
                continue
        try:
            d = site.json("/studio-ia/visage/travail?nom=" + urllib.request.quote(site.nom), timeout=30)
        except urllib.error.HTTPError as e:
            log("site : HTTP %s (%s)" % (e.code, "jeton refusé" if e.code == 401 else e.reason))
            if e.code == 401:
                conf["acceptee"] = False     # retiré du site : on se représente
                ecrire_config(dossier, conf)
            d = {}
        except (urllib.error.URLError, OSError, ValueError) as e:
            log("site injoignable : %s" % e)
            d = {}
        se_mettre_a_jour(site, d.get("worker_sha"))
        t = d.get("tache")
        if t:
            try:
                faire(site, dossier, conf, t)
            except Exception as e:      # le travail suivant ne doit pas en pâtir
                log("%s : ÉCHEC %s" % (t.get("id"), e))
                try:
                    site.json("/studio-ia/visage/echec/" + t["id"], {"erreur": str(e)[:400], "machine": site.nom})
                except (urllib.error.URLError, OSError, ValueError):
                    pass
            if args.une_fois:
                return
            continue
        if args.une_fois:
            return
        time.sleep(PAUSE_S)


def etat(args):
    dossier = os.path.abspath(os.path.expanduser(args.dossier))
    c = chemins(dossier)
    conf = lire_config(dossier)
    print("dossier :", dossier)
    print("FaceFusion :", "oui" if os.path.exists(os.path.join(c["app"], "facefusion.py")) else "non")
    print("venv :", "oui" if os.path.exists(c["python"]) else "non")
    modeles = glob.glob(os.path.join(c["app"], ".assets", "models", "*.onnx"))
    print("modèles :", len(modeles))
    print("ffmpeg :", trouver_ffmpeg(conf, dossier) or "INTROUVABLE (brew install ffmpeg)")
    print("site :", conf.get("site", "—"), "| machine :", conf.get("nom", "—"), "| jeton :", "oui" if conf.get("jeton") else "non",
          "| acceptée :", "oui" if conf.get("acceptee") else "non")
    if os.path.exists(c["journal"]):
        with open(c["journal"], "r", encoding="utf-8", errors="replace") as f:
            lignes = f.readlines()[-8:]
        print("journal :")
        for l in lignes:
            print("  " + l.rstrip())


def analyseur():
    ap = argparse.ArgumentParser(description="Machine des visages du Studio IA (FaceFusion).")
    ap.add_argument("--dossier", default=DOSSIER_DEFAUT)
    sub = ap.add_subparsers(dest="cmd")

    def sous(nom):
        # --dossier vaut aussi APRES la sous-commande : l'agent launchd pose
        # le 04/11 l'ecrivait ainsi et le worker mourait a chaque relance.
        # SUPPRESS, sinon la valeur de la sous-commande (None) ecrase celle
        # donnee avant.
        p = sub.add_parser(nom)
        p.add_argument("--dossier", default=argparse.SUPPRESS)
        return p

    i = sous("installer")
    i.add_argument("--site")
    i.add_argument("--jeton")
    i.add_argument("--nom")
    t = sous("tourner")
    t.add_argument("--une-fois", action="store_true", dest="une_fois")
    sous("etat")
    return ap


def main(argv=None):
    ap = analyseur()
    args = ap.parse_args(argv)
    if args.cmd == "installer":
        installer(args)
    elif args.cmd == "tourner":
        tourner(args)
    elif args.cmd == "etat":
        etat(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
