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

# Reference au bot Discord pour resolver les usernames depuis user_id
_BOT_REF = None


def set_bot_ref(bot):
    """Appelé depuis main.py pour que le site web puisse lookup les users."""
    global _BOT_REF
    _BOT_REF = bot


def _resolve_username(user_id) -> str:
    """Retourne le username Discord depuis l'ID, ou l'ID si pas trouvé.

    Essaie d'abord le cache global, puis tous les members des guildes.
    """
    if _BOT_REF is None:
        return str(user_id)
    try:
        uid_int = int(user_id)
    except Exception:
        return str(user_id)
    # 1) Cache global (bot.get_user)
    try:
        u = _BOT_REF.get_user(uid_int)
        if u:
            return getattr(u, "name", None) or getattr(u, "display_name", None) or str(user_id)
    except Exception:
        pass
    # 2) Iterer les guildes et chercher dans members (cache populé par intents.members)
    try:
        for g in _BOT_REF.guilds:
            m = g.get_member(uid_int)
            if m:
                return getattr(m, "name", None) or getattr(m, "display_name", None) or str(user_id)
    except Exception:
        pass
    return str(user_id)


def _find_identity_category(guild, identity: str):
    """Trouve la categorie portant le nom de l'identite (case-insensitive)."""
    target = identity.lower().strip()
    for cat in guild.categories:
        if cat.name.lower().strip() == target:
            return cat
    return None


def _move_channel_to_identity(channel_id: int, new_identity: str):
    """Déplace le salon <channel_id> dans la catégorie de <new_identity>.

    Tourne dans le thread Flask, mais l'action Discord doit etre dans le loop asyncio.
    Retourne (success: bool, info: str).
    """
    import asyncio
    if _BOT_REF is None:
        return False, "bot pas initialisé"
    if not channel_id:
        return False, "channel_id vide"
    loop = getattr(_BOT_REF, "loop", None)
    if loop is None or not loop.is_running():
        return False, "loop bot non actif"

    async def _do_move():
        for guild in _BOT_REF.guilds:
            channel = guild.get_channel(int(channel_id))
            if channel is None:
                continue
            category = _find_identity_category(guild, new_identity)
            if category is None:
                return False, f"pas de catégorie nommée '{new_identity}' sur le serveur"
            if channel.category and channel.category.id == category.id:
                return True, "déjà dans la bonne catégorie"
            try:
                await channel.edit(category=category, reason="Web: changement identité VA")
                return True, "ok"
            except Exception as e:
                return False, f"erreur edit: {e}"
        return False, f"salon {channel_id} introuvable"

    try:
        fut = asyncio.run_coroutine_threadsafe(_do_move(), loop)
        ok, info = fut.result(timeout=10)
        return ok, info
    except Exception as e:
        return False, f"timeout / erreur: {e}"


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
/* Sidebar large avec groupes pliables + flèches */
.sidebar{width:240px;background:#0a0a0a;border-right:1px solid #1a1a1a;padding:18px 0;flex-shrink:0;display:flex;flex-direction:column;gap:2px}
.sidebar .group{display:flex;flex-direction:column;margin:0 10px}
.sidebar .group-head{display:flex;align-items:center;gap:12px;padding:10px 12px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;font-weight:600;width:100%;text-align:left;margin:0;border-radius:8px;transition:all .15s}
.sidebar .group-head:hover{background:#181818;color:#fff}
.sidebar .group-head.active{background:#181818;color:#fff}
.sidebar .group-head svg.lead{width:18px;height:18px;flex-shrink:0;color:#888}
.sidebar .group-head.active svg.lead{color:#5865f2}
.sidebar .group-head .label{flex:1}
.sidebar .group-head .arrow{width:14px;height:14px;color:#666;transition:transform .15s}
.sidebar .group.open .group-head .arrow{transform:rotate(180deg);color:#fff}
.sidebar .group .items{display:none;flex-direction:column;gap:1px;padding:2px 0 6px 14px;border-left:1px solid #222;margin:2px 0 2px 24px}
.sidebar .group.open .items{display:flex}
.sidebar .group .item{padding:8px 12px;background:none;border:0;color:#888;cursor:pointer;font-size:13.5px;text-align:left;border-radius:6px;display:flex;align-items:center;gap:10px;font-weight:500;margin:0;transition:all .12s;justify-content:space-between}
.sidebar .group .item svg{width:14px;height:14px;color:#666}
.sidebar .group .item .left{display:flex;align-items:center;gap:10px;flex:1}
.sidebar .group .item:hover{background:#181818;color:#fff}
.sidebar .group .item:hover svg{color:#fff}
.sidebar .group .item.active{color:#5865f2;background:#181818}
.sidebar .group .item.active svg{color:#5865f2}
.sidebar .group .item.soon{cursor:not-allowed;opacity:.6}
.sidebar .group .item .badge{padding:2px 6px;font-size:9px;background:#5865f2;color:#fff;border-radius:4px;font-weight:700;letter-spacing:.5px}
/* Sous-groupes imbriqués (Instagram, TikTok, etc. dans Trends) */
.sidebar .subgroup{display:flex;flex-direction:column}
.sidebar .subgroup-head{display:flex;align-items:center;gap:10px;padding:8px 12px;background:none;border:0;color:#bbb;cursor:pointer;font-size:13.5px;font-weight:600;border-radius:6px;width:100%;text-align:left;margin:0;transition:all .12s}
.sidebar .subgroup-head:hover{background:#181818;color:#fff}
.sidebar .subgroup-head .brand{width:18px;height:18px;flex-shrink:0;display:flex;align-items:center;justify-content:center}
.sidebar .subgroup-head .brand svg{width:18px;height:18px;display:block}
.sidebar .subgroup-head .label{flex:1}
.sidebar .subgroup-head .arrow{width:12px;height:12px;color:#666;transition:transform .15s}
.sidebar .subgroup.open .subgroup-head .arrow{transform:rotate(180deg)}
.sidebar .subgroup .sub-items{display:none;flex-direction:column;padding:2px 0 4px 12px;border-left:1px solid #222;margin:1px 0 1px 16px}
.sidebar .subgroup.open .sub-items{display:flex}
.sidebar .subgroup .sub-items .item{padding:6px 10px;font-size:13px}
.sidebar .sep{height:1px;background:#1a1a1a;margin:8px 16px}
.sidebar .spacer{flex:1}
.sidebar .logout-btn{display:flex;align-items:center;gap:10px;padding:10px 12px;background:none;border:0;color:#777;cursor:pointer;font-size:13.5px;text-decoration:none;border-radius:8px;font-weight:500;margin:0 10px 0}
.sidebar .logout-btn:hover{background:#2a1a1a;color:#f99}
.sidebar .logout-btn svg{width:16px;height:16px}

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
function toggleGroup(group){
  var el=document.getElementById('grp-'+group);
  el.classList.toggle('open');
}
function toggleSubGroup(id){
  var el=document.getElementById('sub-'+id);
  el.classList.toggle('open');
}
function comingSoon(){
  alert('🚧 Pas encore implémenté — viendra bientôt');
}
function showTab(group,name,title,subtitle){
  // Ouvrir le groupe parent
  var grp=document.getElementById('grp-'+group);
  if(grp && !grp.classList.contains('open'))grp.classList.add('open');
  // Désactiver tous
  document.querySelectorAll('.sidebar .item').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.sidebar .group-head').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.form-section').forEach(f=>f.style.display='none');
  // Activer
  var btn=document.getElementById('tab-'+name);
  var sec=document.getElementById('form-'+name);
  var head=grp?grp.querySelector('.group-head'):null;
  if(btn)btn.classList.add('active');
  if(head)head.classList.add('active');
  if(sec)sec.style.display='block';
  document.getElementById('page-title').textContent=title||'';
  document.getElementById('page-subtitle').textContent=subtitle||'';
}
</script>
</head><body><div class="layout">
<!-- SIDEBAR : groupes pliables avec flèches -->
<div class="sidebar">

<div class="group open" id="grp-upload">
  <button class="group-head active" onclick="toggleGroup('upload')">
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>
    <span class="label">Upload</span>
    <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="items">
    <button class="item active" id="tab-reel" onclick="showTab('upload','reel','Upload Reel','Vidéo clean + caption + description (+ exemple optionnel)')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2" ry="2"/></svg>
      Reel
    </button>
    <button class="item" id="tab-post" onclick="showTab('upload','post','Upload Post','Photo + caption + description')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>
      Post
    </button>
    <button class="item" id="tab-story" onclick="showTab('upload','story','Upload Story','Photo simple pour story')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>
      Story
    </button>
    <button class="item" id="tab-storycta" onclick="showTab('upload','storycta','Story CTA','Photo 1080x1920 pour CTA + lien')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>
      Story CTA
    </button>
    <button class="item" id="tab-pp" onclick="showTab('upload','pp','Photo de profil','Pool partagé entre toutes les identités')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="10" r="3"/><path d="M7 20.662V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.662"/></svg>
      PP partagé
    </button>
  </div>
</div>

<div class="group" id="grp-va">
  <button class="group-head" onclick="toggleGroup('va')">
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
    <span class="label">VAs</span>
    <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="items">
    <button class="item" id="tab-home" onclick="showTab('va','home','Dashboard','Vue d ensemble globale')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>
      Dashboard
    </button>
    <button class="item" id="tab-valist" onclick="showTab('va','valist','Délégations VA','VAs assignés à chaque identité')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
      Liste VAs
    </button>
    <button class="item" id="tab-vastats" onclick="showTab('va','vastats','Statistiques par identité','Contenus dispo par identité')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="20" y2="10"/><line x1="18" x2="18" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="16"/></svg>
      Stats par identité
    </button>
  </div>
</div>

<div class="group" id="grp-trends">
  <button class="group-head" onclick="toggleGroup('trends')">
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
    <span class="label">Trends</span>
    <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="items">

    <div class="subgroup" id="sub-instagram">
      <button class="subgroup-head" onclick="toggleSubGroup('instagram')">
        <span class="brand">
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="igGrad" x1="0%" y1="100%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#FFC107"/><stop offset="35%" stop-color="#F44336"/>
                <stop offset="70%" stop-color="#E91E63"/><stop offset="100%" stop-color="#9C27B0"/>
              </linearGradient>
            </defs>
            <rect x="2" y="2" width="20" height="20" rx="5" fill="url(#igGrad)"/>
            <circle cx="12" cy="12" r="4.2" fill="none" stroke="#fff" stroke-width="2"/>
            <circle cx="17.5" cy="6.5" r="1.4" fill="#fff"/>
          </svg>
        </span>
        <span class="label">Instagram</span>
        <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="sub-items">
        <button class="item" onclick="comingSoon()"><span class="left">👤 Accounts</span><span class="badge">SOON</span></button>
        <button class="item soon" onclick="comingSoon()"><span class="left">📈 Trends</span><span class="badge">SOON</span></button>
      </div>
    </div>

    <div class="subgroup" id="sub-tiktok">
      <button class="subgroup-head" onclick="toggleSubGroup('tiktok')">
        <span class="brand">
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#fff">
            <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5.3 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1.34-.1z"/>
          </svg>
        </span>
        <span class="label">TikTok</span>
        <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="sub-items">
        <button class="item" onclick="comingSoon()"><span class="left">👤 Accounts</span><span class="badge">SOON</span></button>
        <button class="item soon" onclick="comingSoon()"><span class="left">📈 Trends</span><span class="badge">SOON</span></button>
      </div>
    </div>

    <div class="subgroup" id="sub-twitter">
      <button class="subgroup-head" onclick="toggleSubGroup('twitter')">
        <span class="brand">
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#fff">
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
          </svg>
        </span>
        <span class="label">Twitter / X</span>
        <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="sub-items">
        <button class="item" onclick="comingSoon()"><span class="left">👤 Accounts</span><span class="badge">SOON</span></button>
        <button class="item soon" onclick="comingSoon()"><span class="left">📈 Trends</span><span class="badge">SOON</span></button>
      </div>
    </div>

    <div class="subgroup" id="sub-threads">
      <button class="subgroup-head" onclick="toggleSubGroup('threads')">
        <span class="brand">
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#fff">
            <path d="M12.186 24h-.007c-3.581-.024-6.334-1.205-8.184-3.509C2.35 18.44 1.5 15.586 1.472 12.01v-.017c.03-3.579.879-6.43 2.525-8.482C5.845 1.205 8.6.024 12.18 0h.014c2.746.02 5.043.725 6.826 2.098 1.677 1.29 2.858 3.13 3.509 5.467l-2.04.569c-1.104-3.96-3.898-5.984-8.304-6.015-2.91.022-5.11.936-6.54 2.717C4.307 6.504 3.616 8.914 3.589 12c.027 3.086.718 5.496 2.057 7.164 1.43 1.783 3.631 2.698 6.54 2.717 2.623-.02 4.358-.631 5.8-2.045 1.647-1.613 1.618-3.593 1.09-4.798-.31-.71-.873-1.3-1.634-1.75-.192 1.352-.622 2.446-1.284 3.272-.886 1.102-2.14 1.704-3.73 1.79-1.202.065-2.361-.218-3.259-.801-1.063-.689-1.685-1.74-1.752-2.964-.065-1.19.408-2.285 1.33-3.082.88-.76 2.119-1.207 3.583-1.291a13.853 13.853 0 0 1 3.02.142c-.126-.742-.375-1.332-.74-1.757-.512-.595-1.295-.895-2.32-.901h-.024c-.831 0-1.957.221-2.696 1.346L7.36 7.405c.99-1.51 2.6-2.337 4.535-2.337h.036c3.235.02 5.158 2.022 5.348 5.527.108.046.215.094.32.144 1.49.7 2.58 1.761 3.156 3.071.802 1.83.875 4.81-1.553 7.207-1.847 1.835-4.115 2.668-7.045 2.683l-.001-.001zm.972-13.245c-.331 0-.668.011-1.001.026-1.84.106-2.978.946-2.91 2.143.07 1.255 1.45 1.838 2.766 1.767 1.213-.066 2.788-.531 3.05-3.681a10.347 10.347 0 0 0-1.91-.255l.005-.001z"/>
          </svg>
        </span>
        <span class="label">Threads</span>
        <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="sub-items">
        <button class="item" onclick="comingSoon()"><span class="left">👤 Accounts</span><span class="badge">SOON</span></button>
        <button class="item soon" onclick="comingSoon()"><span class="left">📈 Trends</span><span class="badge">SOON</span></button>
      </div>
    </div>

  </div>
</div>

<div class="group" id="grp-settings">
  <button class="group-head" onclick="toggleGroup('settings')">
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
    <span class="label">Settings</span>
    <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="items">
    <button class="item" id="tab-stoken" onclick="showTab('settings','stoken','Token bot admin','Token du 2e bot Discord')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/></svg>
      Token bot admin
    </button>
    <button class="item" id="tab-spwd" onclick="showTab('settings','spwd','Mot de passe site','Mot de passe d accès à ce site')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
      Mot de passe site
    </button>
  </div>
</div>

<div class="spacer"></div>
<a href="/logout" class="logout-btn">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/></svg>
  Déconnexion
</a>

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

    # Regrouper par identité
    by_identity = {}
    for uid, data in users.items():
        if isinstance(data, dict):
            identity = data.get("identity", "?")
        else:
            identity = str(data)
        by_identity.setdefault(identity, []).append((uid, data))

    rows = []
    for identity in sorted(by_identity.keys()):
        members = by_identity[identity]
        rows.append(
            f"<div style='margin-top:18px;display:flex;align-items:center;gap:10px'>"
            f"<h4 style='margin:0;color:#5865f2;font-size:15px'>👤 {identity}</h4>"
            f"<small style='color:#666'>{len(members)} VA(s)</small>"
            f"</div>"
        )
        rows.append(
            "<table style='width:100%;border-collapse:collapse;margin-top:8px'>"
            "<tr style='background:#1a1a1a'>"
            "<th style='padding:8px;text-align:left'>Username Discord</th>"
            "<th style='padding:8px;text-align:left'>Discord ID</th>"
            "<th style='padding:8px;text-align:left'>Salon</th>"
            "<th style='padding:8px;text-align:center'>Auto-post</th>"
            "<th style='padding:8px;text-align:left'>Changer d'identité</th>"
            "<th style='padding:8px;text-align:right'>Actions</th>"
            "</tr>"
        )
        all_identities = _list_identities()
        for uid, data in members:
            if isinstance(data, dict):
                channel_id = data.get("channel_id", "")
                auto = "✅" if data.get("auto_post", True) else "❌"
                cur_identity = data.get("identity", identity)
            else:
                channel_id = ""
                auto = "?"
                cur_identity = identity
            username = _resolve_username(uid)
            if username == str(uid):
                username_html = "<span style='color:#888'>—</span>"
            else:
                username_html = f"<b>@{username}</b>"
            channel_link = (
                f"<a href='https://discord.com/channels/@me/{channel_id}'>{channel_id}</a>"
                if channel_id else "<span style='color:#888'>—</span>"
            )
            # Select pour changer l'identité
            opts = "".join(
                f"<option value='{i}'{' selected' if i == cur_identity else ''}>{i}</option>"
                for i in all_identities
            )
            change_form = (
                f"<form method='POST' action='/va/change_identity' style='display:flex;gap:6px;margin:0'>"
                f"<input type='hidden' name='user_id' value='{uid}'>"
                f"<select name='identity' style='padding:6px 8px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:4px;font-size:13px;width:auto;flex:1'>"
                f"{opts}"
                f"</select>"
                f"<button type='submit' style='padding:6px 10px;background:#5865f2;color:#fff;border:0;border-radius:4px;font-size:12px;cursor:pointer;font-weight:600;margin:0'>OK</button>"
                f"</form>"
            )
            rows.append(
                f"<tr style='border-bottom:1px solid #333'>"
                f"<td style='padding:8px'>{username_html}</td>"
                f"<td style='padding:8px'><code style='font-size:12px'>{uid}</code></td>"
                f"<td style='padding:8px'>{channel_link}</td>"
                f"<td style='padding:8px;text-align:center'>{auto}</td>"
                f"<td style='padding:8px;min-width:180px'>{change_form}</td>"
                f"<td style='padding:8px;text-align:right'>"
                f"<form method='POST' action='/va/reset' style='display:inline'>"
                f"<input type='hidden' name='user_id' value='{uid}'>"
                f"<button type='submit' class='danger-btn' "
                f"onclick=\"return confirm('Reset {username} ?')\">Reset</button>"
                f"</form>"
                f"</td></tr>"
            )
        rows.append("</table>")
    rows.append(f"<div style='margin-top:18px;padding-top:14px;border-top:1px solid #2a2a2a'><small>Total : <b>{len(users)}</b> VA(s) sur <b>{len(by_identity)}</b> identité(s)</small></div>")
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

    @app.route("/va/change_identity", methods=["POST"])
    def va_change_identity():
        if not is_auth():
            return redirect("/")
        uid = (request.form.get("user_id") or "").strip()
        new_identity = (request.form.get("identity") or "").strip().lower()
        if not uid or not new_identity:
            return _render_upload("❌ user_id ou identite manquant", error=True)
        if new_identity not in _list_identities():
            return _render_upload(
                f"❌ Identité <code>{new_identity}</code> introuvable", error=True
            )
        users = _load_users()
        if uid not in users:
            return _render_upload(f"❌ VA {uid} introuvable", error=True)

        # Update users.json (en gardant le reste : channel_id, auto_post...)
        entry = users[uid]
        if isinstance(entry, dict):
            old_identity = entry.get("identity", "?")
            channel_id = entry.get("channel_id")
            entry["identity"] = new_identity
        else:
            old_identity = str(entry)
            channel_id = None
            users[uid] = {"identity": new_identity, "channel_id": None, "auto_post": True}
        _save_users(users)
        username = _resolve_username(uid)

        # Tenter de déplacer le salon Discord dans la catégorie de la nouvelle identité
        moved_msg = ""
        if _BOT_REF is not None and channel_id:
            try:
                ok, info = _move_channel_to_identity(channel_id, new_identity)
                if ok:
                    moved_msg = f" Salon Discord déplacé dans la catégorie <b>{new_identity}</b>."
                else:
                    moved_msg = f" ⚠️ Salon non déplacé : {info}"
            except Exception as e:
                moved_msg = f" ⚠️ Erreur déplacement salon : {e}"
        elif not channel_id:
            moved_msg = " (Pas de salon associé à déplacer.)"

        return _render_upload(
            f"✅ <b>@{username}</b> réassigné : <code>{old_identity}</code> → "
            f"<code>{new_identity}</code>.{moved_msg}"
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
