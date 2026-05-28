"""Mini site web pour uploader des reels facilement.
Tourne dans un thread du process bot. Accès via http://<VPS_IP>:8080
Authentification par mot de passe (env WEB_UPLOAD_PASSWORD ou par défaut "changeme").
"""
import os
import json
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
USERS_FILE = DATA_DIR / "users.json"
IDENTITIES_CONFIG_FILE = DATA_DIR / "identities_config.json"

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
<html><head><title>VA Bot Dashboard</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#0f0f0f;color:#eee;margin:0;padding:0;min-height:100vh}
.layout{display:flex;min-height:100vh}
/* Panneau 1 : Icones étroits */
.sidebar{width:56px;background:#0a0a0a;border-right:1px solid #1a1a1a;padding:12px 0;flex-shrink:0;display:flex;flex-direction:column;align-items:center;gap:2px}
.sidebar .ico{width:40px;height:40px;display:flex;align-items:center;justify-content:center;background:none;border:0;color:#888;cursor:pointer;border-radius:8px;transition:all .15s;position:relative;margin:0;text-decoration:none;padding:0}
.sidebar .ico svg{width:20px;height:20px;display:block}
.sidebar .ico:hover{background:#1a1a1a;color:#fff}
.sidebar .ico.active{color:#fff;background:#1a1a1a}
.sidebar .ico.active::before{content:'';position:absolute;left:-12px;top:50%;transform:translateY(-50%);width:3px;height:24px;background:#fff;border-radius:0 2px 2px 0}
.sidebar .ico .tip{position:absolute;left:50px;top:50%;transform:translateY(-50%);background:#000;color:#fff;padding:6px 12px;border-radius:6px;white-space:nowrap;font-size:13px;pointer-events:none;opacity:0;transition:opacity .15s;font-family:system-ui;font-weight:500;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.5);border:1px solid #333}
.sidebar .ico:hover .tip{opacity:1}
.sidebar .sep{width:28px;height:1px;background:#1a1a1a;margin:6px 0}
.sidebar .spacer{flex:1}
.sidebar .logout-btn{color:#666}
.sidebar .logout-btn:hover{color:#f99;background:#2a1a1a}

/* Panneau 2 : Sous-navigation */
.subnav{width:220px;background:#141414;border-right:1px solid #1f1f1f;padding:18px 12px;flex-shrink:0;display:flex;flex-direction:column;gap:2px}
.subnav h3{margin:0 8px 12px;font-size:12px;text-transform:uppercase;color:#666;letter-spacing:1px;font-weight:700}
.subnav .panel{display:none;flex-direction:column;gap:2px}
.subnav .panel.active{display:flex}
.subnav .item{padding:10px 12px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;text-align:left;border-radius:6px;display:flex;align-items:center;gap:10px;font-weight:500;margin:0;transition:all .12s}
.subnav .item svg{width:16px;height:16px;flex-shrink:0;color:#666}
.subnav .item:hover{background:#1f1f1f;color:#fff}
.subnav .item:hover svg{color:#fff}
.subnav .item.active{background:#1f1f1f;color:#fff}
.subnav .item.active svg{color:#5865f2}
.subnav small{display:block;padding:0 8px;margin-top:4px;color:#555;font-size:11px}

/* Contenu */
.main{flex:1;padding:28px 36px;overflow-x:auto}
.main h1{margin:0 0 8px;font-size:24px}
.main .subtitle{font-size:13px;color:#888;margin-bottom:18px}
.box{background:#1a1a1a;padding:24px;border-radius:12px;margin-bottom:16px;border:1px solid #2a2a2a}
label{display:block;font-weight:600;margin-bottom:8px;margin-top:16px}
label:first-child{margin-top:0}
input,select,textarea{width:100%;padding:12px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:15px;font-family:inherit}
textarea{min-height:80px;resize:vertical}
button[type=submit],.btn{padding:12px 24px;background:#5865f2;color:#fff;border:0;border-radius:6px;font-size:15px;cursor:pointer;font-weight:600;margin-top:16px}
button[type=submit]:hover,.btn:hover{background:#4752c4}
.msg{padding:12px 16px;border-radius:6px;margin-bottom:16px;background:#1a3a1a;color:#9fe89f;border:1px solid #2a5a2a}
.err{background:#3a1a1a;color:#f99;border-color:#5a2a2a}
a{color:#7289da}
small{color:#888;display:block;margin-top:4px}
table{width:100%;border-collapse:collapse;margin-top:12px}
th{padding:10px 8px;text-align:left;background:#252525;font-weight:600;font-size:13px;text-transform:uppercase;color:#aaa}
td{padding:10px 8px;border-bottom:1px solid #2a2a2a;font-size:14px}
code{background:#0f0f0f;padding:2px 6px;border-radius:4px;font-size:13px}
.danger-btn{padding:6px 12px;background:#d9534f;font-size:13px;border:0;color:#fff;border-radius:4px;cursor:pointer;margin:0}
.danger-btn:hover{background:#c9302c}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px}
.stat{background:#1a1a1a;padding:16px;border-radius:10px;border:1px solid #2a2a2a}
.stat .v{font-size:28px;font-weight:700;color:#5865f2}
.stat .l{font-size:13px;color:#888;text-transform:uppercase;letter-spacing:.5px}
@media(max-width:768px){
  .layout{flex-direction:column}
  .sidebar{width:100%;border-right:0;border-bottom:1px solid #2a2a2a}
}
</style>
<script>
function showGroup(group){
  document.querySelectorAll('.sidebar .ico[data-group]').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.subnav .panel').forEach(p=>p.classList.remove('active'));
  var btn=document.getElementById('grp-'+group);
  var pan=document.getElementById('panel-'+group);
  if(btn)btn.classList.add('active');
  if(pan)pan.classList.add('active');
  // Activer le premier item du panel comme contenu par défaut
  var first=pan?pan.querySelector('.item'):null;
  if(first)first.click();
}
function showTab(name,title,subtitle){
  document.querySelectorAll('.subnav .item').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.form-section').forEach(f=>f.style.display='none');
  var btn=document.getElementById('tab-'+name);
  var sec=document.getElementById('form-'+name);
  if(btn)btn.classList.add('active');
  if(sec)sec.style.display='block';
  document.getElementById('page-title').textContent=title||'';
  document.getElementById('page-subtitle').textContent=subtitle||'';
}
</script>
</head><body><div class="layout">
<!-- PANNEAU 1 : ICONES -->
<div class="sidebar">
  <button class="ico active" id="grp-upload" data-group="upload" onclick="showGroup('upload')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>
    <span class="tip">Upload</span>
  </button>
  <div class="sep"></div>
  <button class="ico" id="grp-va" data-group="va" onclick="showGroup('va')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
    <span class="tip">VAs</span>
  </button>
  <div class="sep"></div>
  <button class="ico" id="grp-settings" data-group="settings" onclick="showGroup('settings')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
    <span class="tip">Settings</span>
  </button>
  <div class="spacer"></div>
  <a href="/logout" class="ico logout-btn">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/></svg>
    <span class="tip">Déconnexion</span>
  </a>
</div>

<!-- PANNEAU 2 : SOUS-NAVIGATION -->
<div class="subnav">

<div class="panel active" id="panel-upload">
<h3>Upload contenu</h3>
<button class="item active" id="tab-reel" onclick="showTab('reel','Upload Reel','Vidéo clean + caption + description (+ exemple optionnel)')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2" ry="2"/></svg>
  Reel
</button>
<button class="item" id="tab-post" onclick="showTab('post','Upload Post','Photo + caption + description')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>
  Post
</button>
<button class="item" id="tab-story" onclick="showTab('story','Upload Story','Photo simple pour story')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>
  Story
</button>
<button class="item" id="tab-storycta" onclick="showTab('storycta','Story CTA','Photo 1080x1920 pour CTA + lien')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>
  Story CTA
</button>
<button class="item" id="tab-pp" onclick="showTab('pp','Photo de profil','Pool partagé entre toutes les identités')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="10" r="3"/><path d="M7 20.662V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.662"/></svg>
  PP partagé
</button>
</div>

<div class="panel" id="panel-va">
<h3>Délégations VA</h3>
<button class="item" id="tab-home" onclick="showTab('home','Dashboard','Vue d ensemble globale')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>
  Dashboard
</button>
<button class="item" id="tab-valist" onclick="showTab('valist','Délégations VA','VAs assignés à chaque identité')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
  Liste VAs
</button>
<button class="item" id="tab-vastats" onclick="showTab('vastats','Statistiques par identité','Contenus dispo par identité')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="20" y2="10"/><line x1="18" x2="18" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="16"/></svg>
  Stats
</button>
</div>

<div class="panel" id="panel-settings">
<h3>Paramètres</h3>
<button class="item" id="tab-stoken" onclick="showTab('stoken','Token bot admin','Token du 2e bot Discord')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/></svg>
  Token bot admin
</button>
<button class="item" id="tab-spwd" onclick="showTab('spwd','Mot de passe site','Mot de passe d accès à ce site')">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
  Mot de passe site
</button>
</div>

</div>
<div class="main">
<h1 id="page-title">Upload Reel</h1>
<div class="subtitle" id="page-subtitle">Vidéo clean + caption + description (+ exemple optionnel)</div>
{msg_html}

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

<!-- HOME (clic sur "VA Bot") -->
<div class="form-section" id="form-home" style="display:none">
<div class="stat-grid">
  <div class="stat"><div class="v">{stat_va_count}</div><div class="l">VAs assignés</div></div>
  <div class="stat"><div class="v">{stat_identities}</div><div class="l">Identités</div></div>
  <div class="stat"><div class="v">{stat_reels}</div><div class="l">Reels totaux</div></div>
  <div class="stat"><div class="v">{stat_posts}</div><div class="l">Posts totaux</div></div>
  <div class="stat"><div class="v">{stat_stories}</div><div class="l">Stories totales</div></div>
  <div class="stat"><div class="v">{stat_storyctas}</div><div class="l">Story CTAs</div></div>
</div>
<div class="box">
<h3 style="margin-top:0">🎯 Raccourcis</h3>
<p>Utilise le menu à gauche pour :</p>
<ul>
<li><b>📤 Upload</b> — ajouter du contenu à une identité (reels, posts, stories, etc.)</li>
<li><b>👥 VAs</b> — voir qui est assigné à quoi + statistiques par identité</li>
<li><b>⚙️ Settings</b> — config du bot (token admin, mot de passe site)</li>
</ul>
</div>
</div>

<!-- VA LIST -->
<div class="form-section" id="form-valist" style="display:none">
<div class="box">
<h3 style="margin-top:0">👥 Délégations VA</h3>
<small>Liste de tous les VAs assignés. Tu peux reset leur attribution.</small>
{va_list_html}
</div>
</div>

<!-- VA STATS -->
<div class="form-section" id="form-vastats" style="display:none">
<div class="box">
<h3 style="margin-top:0">📊 Statistiques par identité</h3>
{identity_stats_html}
</div>
</div>

<!-- SETTINGS - TOKEN -->
<div class="form-section" id="form-stoken" style="display:none">
<form method="POST" action="/settings/admin_token" class="box">
<h3 style="margin-top:0">🤖 Token du bot Admin (2e bot)</h3>
<small>Statut actuel : <b>{admin_token_status}</b></small>
<label>Token Discord du bot admin</label>
<input type="password" name="token" placeholder="MTU... (colle le token Discord)" required>
<small>⚠️ Le bot va redémarrer automatiquement après sauvegarde (~5 sec)</small>
<button type="submit" style="background:#d9534f">💾 Sauver et redémarrer</button>
</form>
</div>

<!-- SETTINGS - MOT DE PASSE -->
<div class="form-section" id="form-spwd" style="display:none">
<form method="POST" action="/settings/web_password" class="box">
<h3 style="margin-top:0">🔐 Mot de passe du site</h3>
<small>Statut actuel : <b>{web_password_status}</b></small>
<label>Nouveau mot de passe</label>
<input type="password" name="password" placeholder="Choisis un mot de passe fort" required minlength="6">
<small>⚠️ Le bot va redémarrer automatiquement après sauvegarde (~5 sec)</small>
<button type="submit" style="background:#d9534f">💾 Sauver et redémarrer</button>
</form>
</div>

</div></div></body></html>
"""


def _list_identities():
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())


def _render_login(err=""):
    err_html = f'<div class="err">{err}</div>' if err else ""
    return LOGIN_HTML.replace("{err}", err_html)


def _load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_identities_config():
    if not IDENTITIES_CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(IDENTITIES_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _count_files(d: Path, exts=None) -> int:
    if not d.exists():
        return 0
    if exts is None:
        return sum(1 for p in d.iterdir() if p.is_file())
    return sum(
        1 for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in exts and ".example" not in p.name
    )


def _identity_stats(identity: str) -> dict:
    """Compte les contenus de cette identité."""
    base = IDENTITIES_DIR / identity
    reels = _count_files(base / "videos", VIDEO_EXTS)
    posts = _count_files(base / "posts", IMAGE_EXTS)
    stories = _count_files(base / "stories", IMAGE_EXTS)
    storyctas = _count_files(base / "storyctas", IMAGE_EXTS)
    # Bios / usernames / names from JSON files
    def _safe_len(p):
        if not p.exists():
            return 0
        try:
            return len(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return 0
    bios = _safe_len(base / "bios.json")
    usernames = _safe_len(base / "usernames.json")
    names = _safe_len(base / "names.json")
    return {
        "reels": reels,
        "posts": posts,
        "stories": stories,
        "storyctas": storyctas,
        "bios": bios,
        "usernames": usernames,
        "names": names,
    }


def _render_va_list_html() -> str:
    users = _load_users()
    if not users:
        return "<p style='color:#888'>Aucun VA assigné pour l'instant.</p>"
    rows = []
    rows.append(
        "<table style='width:100%;border-collapse:collapse;margin-top:12px'>"
        "<tr style='background:#1a1a1a'>"
        "<th style='padding:8px;text-align:left'>Discord ID</th>"
        "<th style='padding:8px;text-align:left'>Identité</th>"
        "<th style='padding:8px;text-align:left'>Salon</th>"
        "<th style='padding:8px;text-align:center'>Auto-post</th>"
        "<th style='padding:8px;text-align:right'>Actions</th>"
        "</tr>"
    )
    for uid, data in users.items():
        if isinstance(data, dict):
            identity = data.get("identity", "?")
            channel_id = data.get("channel_id", "")
            auto = "✅" if data.get("auto_post", True) else "❌"
        else:
            identity = str(data)
            channel_id = ""
            auto = "?"
        channel_link = (
            f"<a href='https://discord.com/channels/@me/{channel_id}'>{channel_id}</a>"
            if channel_id else "<span style='color:#888'>—</span>"
        )
        rows.append(
            f"<tr style='border-bottom:1px solid #333'>"
            f"<td style='padding:8px'><code>{uid}</code></td>"
            f"<td style='padding:8px'><b>{identity}</b></td>"
            f"<td style='padding:8px'>{channel_link}</td>"
            f"<td style='padding:8px;text-align:center'>{auto}</td>"
            f"<td style='padding:8px;text-align:right'>"
            f"<form method='POST' action='/va/reset' style='display:inline'>"
            f"<input type='hidden' name='user_id' value='{uid}'>"
            f"<button type='submit' style='padding:6px 12px;background:#d9534f;margin:0;font-size:13px' "
            f"onclick=\"return confirm('Reset {uid} ?')\">🗑 Reset</button>"
            f"</form>"
            f"</td></tr>"
        )
    rows.append("</table>")
    rows.append(f"<small>Total : <b>{len(users)}</b> VA(s)</small>")
    return "".join(rows)


def _render_identity_stats_html() -> str:
    identities = _list_identities()
    if not identities:
        return "<p style='color:#888'>Aucune identité créée.</p>"
    cfg = _load_identities_config()
    users = _load_users()
    # Compter VAs par identité
    va_per_identity = {}
    for uid, data in users.items():
        ident = data.get("identity") if isinstance(data, dict) else data
        if ident:
            va_per_identity[ident] = va_per_identity.get(ident, 0) + 1

    rows = [
        "<table style='width:100%;border-collapse:collapse;margin-top:12px;font-size:14px'>"
        "<tr style='background:#1a1a1a'>"
        "<th style='padding:6px;text-align:left'>Identité</th>"
        "<th style='padding:6px'>Statut</th>"
        "<th style='padding:6px'>Reels</th>"
        "<th style='padding:6px'>Posts</th>"
        "<th style='padding:6px'>Stories</th>"
        "<th style='padding:6px'>StoryCTA</th>"
        "<th style='padding:6px'>Bios</th>"
        "<th style='padding:6px'>Usernames</th>"
        "<th style='padding:6px'>Names</th>"
        "<th style='padding:6px'>VAs</th>"
        "</tr>"
    ]
    for ident in identities:
        s = _identity_stats(ident)
        enabled = True
        entry = cfg.get(ident)
        if isinstance(entry, dict):
            enabled = entry.get("enabled", True)
        statut = "✅" if enabled else "❌"
        rows.append(
            f"<tr style='border-bottom:1px solid #333'>"
            f"<td style='padding:6px'><b>{ident}</b></td>"
            f"<td style='padding:6px;text-align:center'>{statut}</td>"
            f"<td style='padding:6px;text-align:center'>{s['reels']}</td>"
            f"<td style='padding:6px;text-align:center'>{s['posts']}</td>"
            f"<td style='padding:6px;text-align:center'>{s['stories']}</td>"
            f"<td style='padding:6px;text-align:center'>{s['storyctas']}</td>"
            f"<td style='padding:6px;text-align:center'>{s['bios']}</td>"
            f"<td style='padding:6px;text-align:center'>{s['usernames']}</td>"
            f"<td style='padding:6px;text-align:center'>{s['names']}</td>"
            f"<td style='padding:6px;text-align:center'><b>{va_per_identity.get(ident, 0)}</b></td>"
            f"</tr>"
        )
    rows.append("</table>")
    return "".join(rows)


def _web_password_status() -> str:
    if WEB_PASSWORD == "changeme":
        return "⚠️ DÉFAUT (changeme) — change-le tout de suite !"
    return f"✅ Configuré ({len(WEB_PASSWORD)} caractères)"


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
    # Stats globales pour le home
    users = _load_users()
    va_count = len(users)
    identities_list = _list_identities()
    stat_reels = sum(_identity_stats(i)["reels"] for i in identities_list)
    stat_posts = sum(_identity_stats(i)["posts"] for i in identities_list)
    stat_stories = sum(_identity_stats(i)["stories"] for i in identities_list)
    stat_storyctas = sum(_identity_stats(i)["storyctas"] for i in identities_list)
    return (
        UPLOAD_HTML
        .replace("{ident_opts}", opts)
        .replace("{msg_html}", msg_html)
        .replace("{admin_token_status}", _admin_token_status())
        .replace("{web_password_status}", _web_password_status())
        .replace("{va_list_html}", _render_va_list_html())
        .replace("{identity_stats_html}", _render_identity_stats_html())
        .replace("{stat_va_count}", str(va_count))
        .replace("{stat_identities}", str(len(identities_list)))
        .replace("{stat_reels}", str(stat_reels))
        .replace("{stat_posts}", str(stat_posts))
        .replace("{stat_stories}", str(stat_stories))
        .replace("{stat_storyctas}", str(stat_storyctas))
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

    @app.route("/settings/web_password", methods=["POST"])
    def settings_web_password():
        if not is_auth():
            return redirect("/")
        pwd = (request.form.get("password") or "").strip()
        if len(pwd) < 6:
            return _render_upload(
                "❌ Mot de passe trop court (min 6 caractères)", error=True
            )
        ok = _write_env_var("WEB_UPLOAD_PASSWORD", pwd)
        if not ok:
            return _render_upload("❌ Erreur ecriture .env", error=True)
        _schedule_restart(2.0)
        return _render_upload(
            "✅ Mot de passe sauvegardé. Le bot redémarre dans 2 sec. "
            "Tu seras déco — reconnecte-toi avec le nouveau mot de passe."
        )

    @app.route("/va/reset", methods=["POST"])
    def va_reset():
        if not is_auth():
            return redirect("/")
        uid = (request.form.get("user_id") or "").strip()
        if not uid:
            return _render_upload("❌ user_id manquant", error=True)
        users = _load_users()
        if uid not in users:
            return _render_upload(f"❌ VA {uid} introuvable", error=True)
        identity = users[uid].get("identity") if isinstance(users[uid], dict) else users[uid]
        del users[uid]
        _save_users(users)
        return _render_upload(
            f"✅ VA <code>{uid}</code> retiré (était assigné à <b>{identity}</b>). "
            "Son salon Discord n'est PAS supprimé — fais /resetva sur Discord si tu veux le supprimer."
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
