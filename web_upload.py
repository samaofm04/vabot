"""Mini site web pour uploader des reels facilement.
Tourne dans un thread du process bot. Accès via http://<VPS_IP>:8080
Authentification par mot de passe (env WEB_UPLOAD_PASSWORD ou par défaut "changeme").
"""
import os
import logging
import threading
import sys
import time
from pathlib import Path

log = logging.getLogger("vabot.web")

BOT_DIR = Path(__file__).parent.resolve()
ENV_FILE = BOT_DIR / ".env"
DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
PROFILE_PICS_DIR = DATA_DIR / "profile_pics"

WEB_PASSWORD = os.environ.get("WEB_UPLOAD_PASSWORD", "changeme")
WEB_PORT = int(os.environ.get("WEB_UPLOAD_PORT", "8080"))


def _read_env_lines():
    """Lit .env en preservant les lignes (vide si fichier n'existe pas)."""
    if not ENV_FILE.exists():
        return []
    try:
        return ENV_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def _write_env_var(key: str, value: str) -> bool:
    """Ecrit/remplace la variable <key>=<value> dans le .env. Retourne True si OK."""
    try:
        lines = _read_env_lines()
        found = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        # Garantir un saut de ligne final
        content = "\n".join(new_lines).rstrip("\n") + "\n"
        ENV_FILE.write_text(content, encoding="utf-8")
        try:
            os.chmod(ENV_FILE, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        log.error(f"Erreur ecriture .env: {e}")
        return False


def _schedule_restart(delay_sec: float = 2.0):
    """Exit le process apres <delay_sec> -> systemd auto-restart."""
    def _do_exit():
        time.sleep(delay_sec)
        log.warning("Exit demande via web UI - systemd va relancer le bot")
        os._exit(0)
    threading.Thread(target=_do_exit, daemon=True).start()

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


LOGIN_HTML = """
<!DOCTYPE html>
<html><head><title>VA Bot</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;background:#1a1a1a;color:#eee;margin:0;padding:0;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{background:#2a2a2a;padding:32px;border-radius:12px;max-width:400px;width:90%;box-shadow:0 4px 16px rgba(0,0,0,0.3)}
h1{margin:0 0 24px;text-align:center}
input{width:100%;padding:12px;margin-bottom:16px;background:#1a1a1a;border:1px solid #444;color:#fff;border-radius:6px;font-size:16px;box-sizing:border-box}
button{width:100%;padding:14px;background:#5865f2;color:#fff;border:0;border-radius:6px;font-size:16px;cursor:pointer;font-weight:600}
button:hover{background:#4752c4}
.err{color:#f55;margin-bottom:16px;text-align:center}
</style></head><body>
<div class="box">
<h1>🤖 VA Bot Upload</h1>
{err}
<form method="POST"><input type="password" name="password" placeholder="Mot de passe" autofocus required><button type="submit">Connexion</button></form>
</div></body></html>
"""

UPLOAD_HTML = """
<!DOCTYPE html>
<html><head><title>Upload Reel</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;background:#1a1a1a;color:#eee;margin:0;padding:20px}
.container{max-width:700px;margin:0 auto}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
h1{margin:0}
.tabs{display:flex;gap:8px;margin-bottom:24px;border-bottom:1px solid #333}
.tab{padding:12px 20px;background:none;border:0;color:#888;cursor:pointer;font-size:15px;border-bottom:2px solid transparent}
.tab.active{color:#5865f2;border-color:#5865f2}
.box{background:#2a2a2a;padding:24px;border-radius:12px;margin-bottom:16px}
label{display:block;font-weight:600;margin-bottom:8px;margin-top:16px}
label:first-child{margin-top:0}
input,select,textarea{width:100%;padding:12px;background:#1a1a1a;border:1px solid #444;color:#fff;border-radius:6px;font-size:15px;box-sizing:border-box;font-family:inherit}
textarea{min-height:80px;resize:vertical}
button{padding:14px 28px;background:#5865f2;color:#fff;border:0;border-radius:6px;font-size:16px;cursor:pointer;font-weight:600;margin-top:16px}
button:hover{background:#4752c4}
.msg{padding:12px;border-radius:6px;margin-bottom:16px;background:#2a4a2a;color:#9fe89f}
.err{background:#4a2a2a;color:#f99}
a{color:#7289da}
.logout{color:#888;text-decoration:none}
small{color:#888}
</style>
<script>
function showTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.form-section').forEach(f=>f.style.display='none');
  document.getElementById('tab-'+name).classList.add('active');
  document.getElementById('form-'+name).style.display='block';
}
</script>
</head><body><div class="container">
<div class="header"><h1>🎬 Upload Reels</h1><a href="/logout" class="logout">Déconnexion</a></div>
{msg_html}
<div class="tabs">
  <button class="tab active" id="tab-reel" onclick="showTab('reel')">Reel</button>
  <button class="tab" id="tab-post" onclick="showTab('post')">Post</button>
  <button class="tab" id="tab-story" onclick="showTab('story')">Story</button>
  <button class="tab" id="tab-storycta" onclick="showTab('storycta')">Story CTA</button>
  <button class="tab" id="tab-pp" onclick="showTab('pp')">PP partagé</button>
  <button class="tab" id="tab-settings" onclick="showTab('settings')">⚙️ Settings</button>
</div>

<div class="form-section" id="form-reel">
<form method="POST" action="/upload/reel" enctype="multipart/form-data" class="box">
<label>Identité</label>
<select name="identity" required>{ident_opts}</select>
<label>Vidéo CLEAN (obligatoire)</label>
<input type="file" name="video" accept="video/*" required>
<label>Vidéo EXEMPLE (optionnel)</label>
<input type="file" name="example" accept="video/*">
<label>Caption (overlay sur la vidéo)</label>
<textarea name="caption" placeholder="Pov : j'ai fait la maline..."></textarea>
<label>Description (texte du post)</label>
<textarea name="description" placeholder="Ouais bon on va espérer hein 💀"></textarea>
<button type="submit">📤 Uploader le reel</button>
</form>
</div>

<div class="form-section" id="form-post" style="display:none">
<form method="POST" action="/upload/post" enctype="multipart/form-data" class="box">
<label>Identité</label>
<select name="identity" required>{ident_opts}</select>
<label>Photo CLEAN</label>
<input type="file" name="photo" accept="image/*" required>
<label>Photo EXEMPLE (optionnel)</label>
<input type="file" name="example" accept="image/*">
<label>Caption (overlay)</label>
<textarea name="caption"></textarea>
<label>Description</label>
<textarea name="description"></textarea>
<button type="submit">📤 Uploader le post</button>
</form>
</div>

<div class="form-section" id="form-story" style="display:none">
<form method="POST" action="/upload/story" enctype="multipart/form-data" class="box">
<label>Identité</label>
<select name="identity" required>{ident_opts}</select>
<label>Photo CLEAN</label>
<input type="file" name="photo" accept="image/*" required>
<label>Photo EXEMPLE (optionnel)</label>
<input type="file" name="example" accept="image/*">
<label>Caption</label>
<textarea name="caption"></textarea>
<label>Description</label>
<textarea name="description"></textarea>
<button type="submit">📤 Uploader la story</button>
</form>
</div>

<div class="form-section" id="form-storycta" style="display:none">
<form method="POST" action="/upload/storycta" enctype="multipart/form-data" class="box">
<label>Identité</label>
<select name="identity" required>{ident_opts}</select>
<label>Photo</label>
<input type="file" name="photo" accept="image/*" required>
<small>Les captions storycta sont partagées (utilise /addstoryctacaptions sur Discord)</small>
<button type="submit">📤 Uploader story CTA</button>
</form>
</div>

<div class="form-section" id="form-pp" style="display:none">
<form method="POST" action="/upload/pp" enctype="multipart/form-data" class="box">
<small>Pool partagé entre toutes les identités</small>
<label>Photo de profil</label>
<input type="file" name="photo" accept="image/*" required>
<button type="submit">📤 Uploader la PP</button>
</form>
</div>

<div class="form-section" id="form-settings" style="display:none">
<form method="POST" action="/settings/admin_token" class="box">
<h3 style="margin-top:0">🤖 Token du bot Admin (2e bot)</h3>
<small>Statut actuel : <b>{admin_token_status}</b></small>
<label>Token Discord du bot admin</label>
<input type="password" name="token" placeholder="MTU... (colle le token Discord)" required>
<small>⚠️ Le bot va redémarrer automatiquement après sauvegarde (~5 sec)</small>
<button type="submit" style="background:#d9534f">💾 Sauver et redémarrer</button>
</form>
</div>

</div></body></html>
"""


def _list_identities():
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())


def _render_login(err=""):
    err_html = f'<div class="err">{err}</div>' if err else ""
    return LOGIN_HTML.replace("{err}", err_html)


def _admin_token_status() -> str:
    """Resume du statut du token admin (sans jamais l'afficher en clair)."""
    val = os.environ.get("DISCORD_ADMIN_TOKEN")
    if val:
        return f"✅ Configuré (token de {len(val)} caractères)"
    # Re-check .env (au cas ou il a ete ajoute apres le start)
    for line in _read_env_lines():
        s = line.strip()
        if s.startswith("DISCORD_ADMIN_TOKEN=") and len(s) > len("DISCORD_ADMIN_TOKEN="):
            return "⚠️ Présent dans .env mais bot pas restart (relance via Settings)"
    return "❌ Non configuré — colle ton token ci-dessous"


def _render_upload(msg="", error=False):
    identities = _list_identities()
    opts = "".join(f'<option value="{i}">{i}</option>' for i in identities)
    if not opts:
        opts = '<option value="">(aucune identité - crée-en sur Discord)</option>'
    msg_html = ""
    if msg:
        cls = "err" if error else ""
        msg_html = f'<div class="msg {cls}">{msg}</div>'
    return (
        UPLOAD_HTML
        .replace("{ident_opts}", opts)
        .replace("{msg_html}", msg_html)
        .replace("{admin_token_status}", _admin_token_status())
    )


def create_app():
    from flask import Flask, request, session, redirect, make_response
    app = Flask(__name__)
    app.secret_key = os.environ.get("WEB_SECRET", os.urandom(24).hex())

    def is_auth():
        return session.get("auth") is True

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "POST" and not is_auth():
            if request.form.get("password") == WEB_PASSWORD:
                session["auth"] = True
                return redirect("/")
            return _render_login("Mauvais mot de passe")
        if not is_auth():
            return _render_login()
        return _render_upload()

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/")

    def _save_image_or_video_with_pair(form_files, form_text, subdir_name, allow_exts):
        identity = form_text.get("identity", "").strip().lower()
        if not identity or identity not in _list_identities():
            return _render_upload("Identité invalide", error=True)
        photo = form_files.get("photo") or form_files.get("video")
        if not photo or not photo.filename:
            return _render_upload("Fichier manquant", error=True)
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in allow_exts:
            return _render_upload(f"Format non supporté ({ext})", error=True)
        target_dir = IDENTITIES_DIR / identity / subdir_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / photo.filename
        if target.exists():
            return _render_upload(f"Fichier {photo.filename} existe déjà", error=True)
        photo.save(str(target))
        stem = target.stem
        caption = form_text.get("caption", "").strip()
        description = form_text.get("description", "").strip()
        if caption:
            (target_dir / f"{stem}.txt").write_text(caption, encoding="utf-8")
        if description:
            (target_dir / f"{stem}.desc.txt").write_text(description, encoding="utf-8")
        example = form_files.get("example")
        if example and example.filename:
            ex_ext = os.path.splitext(example.filename)[1].lower()
            if ex_ext in allow_exts:
                ex_target = target_dir / f"{stem}.example{ex_ext}"
                example.save(str(ex_target))
        return _render_upload(f"✅ Ajouté à {identity}/{subdir_name} : {photo.filename}")

    @app.route("/upload/reel", methods=["POST"])
    def upload_reel():
        if not is_auth():
            return redirect("/")
        # Reuse logic but with VIDEO_EXTS
        return _save_image_or_video_with_pair(
            {"photo": request.files.get("video"), "example": request.files.get("example")},
            request.form, "videos", VIDEO_EXTS,
        )

    @app.route("/upload/post", methods=["POST"])
    def upload_post():
        if not is_auth():
            return redirect("/")
        return _save_image_or_video_with_pair(
            {"photo": request.files.get("photo"), "example": request.files.get("example")},
            request.form, "posts", IMAGE_EXTS,
        )

    @app.route("/upload/story", methods=["POST"])
    def upload_story():
        if not is_auth():
            return redirect("/")
        return _save_image_or_video_with_pair(
            {"photo": request.files.get("photo"), "example": request.files.get("example")},
            request.form, "stories", IMAGE_EXTS,
        )

    @app.route("/upload/storycta", methods=["POST"])
    def upload_storycta():
        if not is_auth():
            return redirect("/")
        identity = request.form.get("identity", "").strip().lower()
        if not identity or identity not in _list_identities():
            return _render_upload("Identité invalide", error=True)
        photo = request.files.get("photo")
        if not photo or not photo.filename:
            return _render_upload("Photo manquante", error=True)
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in IMAGE_EXTS:
            return _render_upload(f"Format non supporté ({ext})", error=True)
        target_dir = IDENTITIES_DIR / identity / "storyctas"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / photo.filename
        if target.exists():
            return _render_upload(f"Fichier existe déjà", error=True)
        photo.save(str(target))
        return _render_upload(f"✅ Story CTA ajoutée à {identity}")

    @app.route("/upload/pp", methods=["POST"])
    def upload_pp():
        if not is_auth():
            return redirect("/")
        photo = request.files.get("photo")
        if not photo or not photo.filename:
            return _render_upload("Photo manquante", error=True)
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in IMAGE_EXTS:
            return _render_upload(f"Format non supporté ({ext})", error=True)
        PROFILE_PICS_DIR.mkdir(parents=True, exist_ok=True)
        existing = list(PROFILE_PICS_DIR.glob("*"))
        target = PROFILE_PICS_DIR / f"pp_{len(existing) + 1}{ext}"
        photo.save(str(target))
        return _render_upload(f"✅ Photo de profil ajoutée ({target.name})")

    @app.route("/settings/admin_token", methods=["POST"])
    def settings_admin_token():
        if not is_auth():
            return redirect("/")
        token = (request.form.get("token") or "").strip()
        # Validation basique d'un token Discord (format MZ.XX.YY avec base64-like chars)
        if not token or len(token) < 50 or "." not in token:
            return _render_upload(
                "❌ Token invalide (trop court ou format incorrect)", error=True
            )
        ok = _write_env_var("DISCORD_ADMIN_TOKEN", token)
        if not ok:
            return _render_upload(
                "❌ Erreur ecriture .env (permissions ?)", error=True
            )
        # Programmer le redemarrage (systemd relance le service)
        _schedule_restart(2.0)
        return _render_upload(
            "✅ Token sauvegardé. Le bot redémarre dans 2 sec. "
            "Recharge cette page dans ~15 sec pour voir le statut."
        )

    return app


def run_web_app():
    """À appeler dans un thread depuis main.py."""
    try:
        app = create_app()
        log.info(f"Web upload starting on port {WEB_PORT}")
        app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)
    except Exception as e:
        log.error(f"Web upload crashed: {e}")


def start_in_thread():
    thread = threading.Thread(target=run_web_app, daemon=True, name="WebUploadServer")
    thread.start()
    return thread
