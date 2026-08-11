"""Source de médias pour l'automatisation de posting — depuis le SITE.

Remplace le dossier local (`Downloads\\PP`, `Downloads\\VIDEO`) par la
Vault PRO du site : les mêmes URL qu'avant, donc **les raccourcis iOS
n'ont rien à changer**.

    iPhone  →  tunnel  →  ce serveur  →  site (Vault PRO)

    /photo.jpg   une photo au hasard de l'identité courante
    /video.mp4   une vidéo au hasard
    /media       l'une ou l'autre
    /caption     une légende au hasard (texte brut)
    /bio         une bio au hasard (texte brut)
    /etat        ce qui est disponible (compteurs, jamais le contenu)
    /identite/<nom>   change l'identité servie

Confidentialité : les octets des médias transitent sans être ouverts ni
analysés ; seuls les NOMS et les compteurs sont manipulés.

Usage :
    python serveur_site_media.py --setup          (adresse, jeton, identité)
    python serveur_site_media.py 8099             (démarre le serveur)
    python serveur_site_media.py 8099 --identite beta
"""
import argparse
import json
import random
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

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
    print("Il manque une brique :  pip install requests")
    sys.exit(1)

CONF = Path(__file__).resolve().parent / "serveur_site_media.json"
_STATE = {"url": "", "token": "", "identity": "", "last": {},
          "noms": False}
_LOCK = threading.Lock()

# Le tunnel tourne SUR cette machine : l'adresse source est 127.0.0.1 dans les
# deux cas, elle ne distingue rien. Le signal fiable est l'en-tete « Host » :
# un appel local porte 127.0.0.1:<port>, un appel tunnele porte le domaine
# public. (Mesure : localtunnel n'ajoute PAS de X-Forwarded-*.)
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "[::1]", "::1"}


def _est_local(host: str) -> bool:
    h = (host or "").split(":")[0].strip().lower()
    return h in _LOCAL_HOSTS or h.startswith("192.168.") or h.startswith("10.")

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".mp4": "video/mp4", ".mov": "video/quicktime",
        ".webm": "video/webm", ".mkv": "video/x-matroska", ".m4v": "video/x-m4v"}


def _load():
    try:
        return json.loads(CONF.read_text(encoding="utf-8"))
    except Exception:
        return {}


def setup():
    c = _load()
    print("── Source de médias : le site ──\n")
    url = input(f"Adresse du site [{c.get('url', 'https://youl4b.com')}] : ").strip()
    c["url"] = (url or c.get("url") or "https://youl4b.com").rstrip("/")
    print(f"\nJeton : ouvre {c['url']}/sync/token en étant connecté.")
    tok = input("Jeton : ").strip()
    if tok:
        c["token"] = tok
    ident = input(f"\nIdentité à servir [{c.get('identity', 'beta')}] : ").strip()
    c["identity"] = (ident or c.get("identity") or "beta").lower()
    CONF.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Config enregistrée. Démarre avec :  python {Path(__file__).name} 8099")


def _api(path, **params):
    p = dict(params)
    p["t"] = _STATE["token"]
    r = requests.get(_STATE["url"] + path, params=p, timeout=30)
    r.raise_for_status()
    return r.json()


def _pick(kind):
    """Un nom de fichier au hasard, en évitant de resservir le précédent."""
    j = _api("/sync/list", identity=_STATE["identity"], kind=kind)
    files = j.get("files") or []
    if not files:
        return None
    with _LOCK:
        last = _STATE["last"].get(kind)
        pool = [f for f in files if f != last] or files
        pick = random.choice(pool)
        _STATE["last"][kind] = pick
    return pick


def _fetch(kind, name):
    """Octets du fichier — transmis tels quels, jamais ouverts."""
    r = requests.get(
        _STATE["url"] + "/sync/get",
        params={"identity": _STATE["identity"], "kind": kind,
                "file": name, "t": _STATE["token"]},
        timeout=300, stream=True)
    r.raise_for_status()
    return r.content


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):        # journal silencieux (pas de noms en clair)
        pass

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _media(self, kinds):
        for kind in kinds:
            try:
                name = _pick(kind)
            except Exception as e:
                self._send(502, f"site injoignable : {e}".encode()); return
            if not name:
                continue
            try:
                data = _fetch(kind, name)
            except Exception as e:
                self._send(502, f"téléchargement impossible : {e}".encode()); return
            ext = Path(name).suffix.lower()
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition",
                             f"inline; filename=\"{quote(name)}\"")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            # Aucun NOM dans le journal (il peut trahir le contenu).
            if _STATE.get("noms"):
                print(f"  -> {kind}/{name} ({len(data)//1024} Ko)")
            else:
                print(f"  -> [{kind}] 1 fichier ({len(data)//1024} Ko)")
            return
        self._send(404, b"aucun media disponible pour cette identite")

    def _text(self, kind):
        try:
            j = _api("/sync/text", identity=_STATE["identity"], kind=kind)
        except Exception as e:
            self._send(502, f"site injoignable : {e}".encode()); return
        texts = j.get("texts") or []
        if not texts:
            self._send(404, b""); return
        self._send(200, random.choice(texts).encode("utf-8"))

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        # PUBLIC (tunnel) : uniquement les octets et les textes dont l'iPhone a
        # besoin. Tout ce qui ENUMERE (etat, compteurs, identites) ou qui
        # PILOTE reste reserve au local.
        if not _est_local(self.headers.get("Host", "")) and (
                path in ("/", "/etat") or path.startswith("/identite/")):
            return self._send(404, b"inconnu")
        if path == "/photo.jpg":
            return self._media(["posts", "stories", "storyctas"])
        if path == "/video.mp4":
            return self._media(["reels", "brutes"])
        if path == "/media":
            return self._media(random.choice(
                [["posts", "stories"], ["reels", "brutes"]]))
        if path == "/pp.jpg":
            return self._media(["pp"])
        if path == "/caption":
            return self._text("captions")
        if path == "/bio":
            return self._text("bios")
        if path == "/cta":
            return self._text("ctas")
        if path.startswith("/identite/"):
            new = path.split("/identite/", 1)[1].strip().lower()
            if new:
                _STATE["identity"] = new
                c = _load(); c["identity"] = new
                CONF.write_text(json.dumps(c, indent=2, ensure_ascii=False),
                                encoding="utf-8")
            return self._send(200, f"identite : {_STATE['identity']}".encode())
        if path in ("/", "/etat"):
            lines = [f"identite : {_STATE['identity']}", f"site     : {_STATE['url']}", ""]
            try:
                ids = _api("/sync/identities").get("identities") or []
                lines.append("identites : " + (", ".join(ids) or "aucune"))
            except Exception as e:
                lines.append(f"site injoignable : {e}")
            for k in ("posts", "stories", "storyctas", "reels", "brutes", "pp"):
                try:
                    lines.append(f"  {k:10} {_api('/sync/list', identity=_STATE['identity'], kind=k).get('count', 0)}")
                except Exception:
                    lines.append(f"  {k:10} ?")
            for k in ("captions", "bios", "ctas"):
                try:
                    lines.append(f"  {k:10} {_api('/sync/text', identity=_STATE['identity'], kind=k).get('count', 0)}")
                except Exception:
                    lines.append(f"  {k:10} ?")
            lines += ["", "URL : /photo.jpg  /video.mp4  /media  /pp.jpg  /caption  /bio  /cta",
                      "      /identite/<nom> pour changer d'identite"]
            return self._send(200, "\n".join(lines).encode("utf-8"))
        self._send(404, b"inconnu")


def main():
    ap = argparse.ArgumentParser(description="Médias du site pour le posting")
    ap.add_argument("port", nargs="?", type=int, default=8099)
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--identite", default=None)
    ap.add_argument("--noms", action="store_true",
                    help="journaliser les NOMS de fichiers (débogage seulement)")
    a = ap.parse_args()
    if a.setup:
        return setup()
    c = _load()
    if not c.get("url") or not c.get("token"):
        print("Configuration absente — lance d'abord :  python serveur_site_media.py --setup")
        return
    _STATE.update({"url": c["url"], "token": c["token"],
                   "identity": (a.identite or c.get("identity") or "beta").lower(),
                   "noms": bool(getattr(a, "noms", False))})
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    print(f"🌐 http://0.0.0.0:{a.port}   identite : {_STATE['identity']}")
    print(f"   source : {_STATE['url']} (Vault PRO)")
    print("   /photo.jpg  /video.mp4  /media  /pp.jpg  /caption  /bio  /cta")
    print("   par le tunnel : octets et textes SEULEMENT — /etat, / et")
    print("   /identite/<nom> répondent 404 hors du local")
    print("   journal : NOMS affichés (--noms)" if a.noms
          else "   journal : sans noms de fichiers")
    print("   Ctrl+C pour arrêter\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêté.")


if __name__ == "__main__":
    main()
