"""Dossier synchronisé — Vault PRO.

À lancer SUR LE PC (pas sur le VPS). Surveille un dossier local et envoie
chaque nouveau fichier au site : tu déposes une photo dans
    Vault PRO\\beta\\Posts\\
et elle apparaît dans le Vault PRO du site, chez l'identité « beta ».

Confidentialité : le script n'OUVRE jamais les fichiers — il les transmet tels
quels et ne retient que leur nom + leur taille pour ne pas les renvoyer deux
fois. Rien n'est envoyé ailleurs qu'à ton propre site.

Usage :
    python sync_biblio2.py --setup     (une fois : demande l'adresse + le jeton)
    python sync_biblio2.py             (surveille en continu)
    python sync_biblio2.py --once      (envoie ce qui manque, puis s'arrête)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Console Windows : sans ça, un simple accent dans un message fait
# planter le programme au démarrage (cp1252).
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import requests
except ImportError:
    print("Il manque une brique : ouvre une invite de commandes et tape\n"
          "    pip install requests")
    sys.exit(1)

# Dossiers créés dans chaque identité (nom affiché -> type attendu par le site)
KINDS = {
    "Reels": "reels",
    "Posts": "posts",
    "Stories": "stories",
    "Story CTA": "storyctas",
    "Photos de profil": "pp",
    "Video brut": "brutes",
    "Templates montage": "templates",
}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED = {"reels": VIDEO_EXT, "brutes": VIDEO_EXT, "templates": VIDEO_EXT,
           "posts": IMAGE_EXT, "stories": IMAGE_EXT, "storyctas": IMAGE_EXT,
           "pp": IMAGE_EXT}

CONF = Path(__file__).resolve().parent / "sync_biblio2.json"
POLL_SECONDS = 5


def _load():
    try:
        return json.loads(CONF.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    CONF.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def setup():
    c = _load()
    print("── Dossier synchronisé — Vault PRO ──\n")
    url = input(f"Adresse du site [{c.get('url', 'https://youl4b.com')}] : ").strip()
    c["url"] = (url or c.get("url") or "https://youl4b.com").rstrip("/")
    print("\nLe jeton s'obtient en étant connecté au site : ouvre "
          f"{c['url']}/sync/token et copie la valeur de \"token\".")
    tok = input("Jeton : ").strip()
    if tok:
        c["token"] = tok
    default_root = str(Path.home() / "Desktop" / "Vault PRO")
    root = input(f"\nDossier local [{c.get('root', default_root)}] : ").strip()
    c["root"] = root or c.get("root") or default_root
    _save(c)
    Path(c["root"]).mkdir(parents=True, exist_ok=True)
    print(f"\n✅ Config enregistrée. Dossier : {c['root']}")
    print("Crée un dossier par identité dedans (ex. « beta »), les sous-dossiers "
          "Reels/Posts/… sont créés automatiquement.")
    print("Puis lance :  python sync_biblio2.py")


def _identites_du_site(cfg):
    """Identités déjà présentes dans le Vault PRO du site."""
    try:
        r = requests.get(cfg["url"] + "/sync/identities",
                         params={"t": cfg["token"]}, timeout=20)
        return [str(x) for x in (r.json().get("identities") or [])]
    except Exception:
        return []


def _ensure_tree(root: Path, cfg=None):
    """Crée les dossiers manquants — Y COMPRIS ceux des identités qui existent
    DÉJÀ sur le site : sinon on ne sait pas où déposer ses fichiers."""
    if cfg:
        for ident in _identites_du_site(cfg):
            try:
                (root / ident).mkdir(exist_ok=True)
            except Exception:
                pass
    for ident_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if ident_dir.name.startswith("_"):
            continue
        for label in KINDS:
            (ident_dir / label).mkdir(exist_ok=True)


def _lister_site(cfg, ident, kind):
    """Noms des fichiers présents sur le site pour cette identité/type."""
    try:
        r = requests.get(cfg["url"] + "/sync/list",
                         params={"identity": ident, "kind": kind, "t": cfg["token"]},
                         timeout=30)
        return list(r.json().get("files") or [])
    except Exception:
        return []


def _descendre(cfg, ident, kind, dossier: Path, done: set):
    """Récupère du site les fichiers absents en local. COPIE pure : rien n'est
    supprimé, ni ici ni là-bas. Les fichiers descendus sont marqués comme déjà
    connus pour ne pas repartir vers le site juste après."""
    n = 0
    for name in _lister_site(cfg, ident, kind):
        cible = dossier / name
        if cible.exists():
            continue
        try:
            r = requests.get(cfg["url"] + "/sync/get",
                             params={"identity": ident, "kind": kind,
                                     "file": name, "t": cfg["token"]},
                             timeout=600, stream=True)
            if r.status_code != 200:
                continue
            tmp = cible.with_suffix(cible.suffix + ".part")
            with tmp.open("wb") as fh:          # écrit sans jamais lire
                for bloc in r.iter_content(1 << 20):
                    if bloc:
                        fh.write(bloc)
            tmp.replace(cible)
            done.add(f"{cible}|{cible.stat().st_size}")
            n += 1
            print(f"  ⬇ {ident}/{dossier.name}/{name}")
        except Exception as e:
            print(f"  ⚠️  descente impossible : {e}")
    return n


def _push(cfg, ident, kind, path: Path):
    url = cfg["url"] + "/sync/push"
    with path.open("rb") as fh:                    # ouvert en BINAIRE, jamais lu
        r = requests.post(
            url,
            headers={"X-Sync-Token": cfg["token"]},
            data={"identity": ident, "kind": kind},
            files={"file": (path.name, fh)},
            timeout=600,
        )
    try:
        return r.json()
    except Exception:
        return {"ok": False, "error": f"HTTP {r.status_code}"}


def run(once=False, descendre=True):
    cfg = _load()
    if not cfg.get("url") or not cfg.get("token") or not cfg.get("root"):
        print("Configuration absente — lance d'abord :  python sync_biblio2.py --setup")
        return
    root = Path(cfg["root"])
    root.mkdir(parents=True, exist_ok=True)
    done = set(cfg.get("done") or [])          # clés « chemin|taille » déjà envoyées
    _ensure_tree(root, cfg)
    _ids = sorted(x.name for x in root.iterdir()
                  if x.is_dir() and not x.name.startswith("_"))
    print(f"👁  Surveillance de {root}\n    → {cfg['url']}")
    print(f"    identités : {', '.join(_ids) if _ids else 'aucune — crée un dossier ici'}")
    print("    les 2 sens : ce que tu déposes monte, ce qui est sur le site descend")
    print("    (rien n'est JAMAIS supprimé, ni ici ni là-bas)")
    print("    (Ctrl+C pour arrêter)\n")
    while True:
        try:
            _ensure_tree(root, cfg)
            for ident_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                ident = ident_dir.name.strip().lower()
                if not ident or ident.startswith("_"):
                    continue
                for label, kind in KINDS.items():
                    d = ident_dir / label
                    if not d.exists():
                        continue
                    if descendre:          # site -> PC (copie, aucune suppression)
                        if _descendre(cfg, ident, kind, d, done):
                            cfg["done"] = sorted(done)[-5000:]
                            _save(cfg)
                    for f in sorted(d.iterdir()):
                        if not f.is_file() or f.name.startswith("."):
                            continue
                        if f.suffix.lower() not in ALLOWED[kind]:
                            continue
                        try:
                            size = f.stat().st_size
                        except OSError:
                            continue
                        key = f"{f}|{size}"
                        if key in done or size == 0:
                            continue
                        # fichier encore en cours de copie ? on attend le tour suivant
                        time.sleep(0.4)
                        try:
                            if f.stat().st_size != size:
                                continue
                        except OSError:
                            continue
                        res = _push(cfg, ident, kind, f)
                        if res.get("ok"):
                            done.add(key)
                            cfg["done"] = sorted(done)[-5000:]
                            _save(cfg)
                            print(f"  ✅ {ident}/{label}/{f.name}")
                        else:
                            print(f"  ❌ {ident}/{label}/{f.name} — {res.get('error')}")
            if once:
                print("\nTerminé.")
                return
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nArrêté.")
            return
        except Exception as e:
            print(f"  ⚠️  {e}")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Dossier synchronisé — Vault PRO")
    ap.add_argument("--setup", action="store_true", help="configurer (adresse, jeton, dossier)")
    ap.add_argument("--once", action="store_true", help="envoyer une fois puis quitter")
    ap.add_argument("--sans-descente", action="store_true",
                    help="ne pas rapatrier les fichiers du site vers le PC")
    a = ap.parse_args()
    if a.setup:
        setup()
    else:
        run(once=a.once, descendre=not a.sans_descente)
