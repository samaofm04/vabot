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
import subprocess
from pathlib import Path

log = logging.getLogger("vabot.web")

BOT_DIR = Path(__file__).parent.resolve()
ENV_FILE = BOT_DIR / ".env"
DATA_DIR = Path("data")
IDENTITIES_DIR = DATA_DIR / "identities"
PROFILE_PICS_DIR = DATA_DIR / "profile_pics"
USERS_FILE = DATA_DIR / "users.json"
IDENTITIES_CONFIG_FILE = DATA_DIR / "identities_config.json"
THUMB_DIR = DATA_DIR / "thumbnails"
THUMB_SIZE = 360  # largeur max du thumbnail
THUMB_QUALITY = 72  # qualité JPEG (compromis taille/vitesse)

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

/* ============ ANIMATIONS ============ */
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes slideDown{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
@keyframes slideUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@keyframes slideRight{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:translateX(0)}}
@keyframes scaleIn{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:scale(1)}}
@keyframes pop{0%{transform:scale(1)}50%{transform:scale(1.15)}100%{transform:scale(1)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}
@keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}

/* Animation sur form-section visible */
.form-section[style*="block"]{animation:fadeIn .25s ease-out}

/* Animation sur les dropdowns */
#ig-sort-menu[style*="block"],#ig-filters-panel[style*="block"]{animation:slideDown .18s cubic-bezier(.16,1,.3,1)}

/* Sub-items des groupes */
.sidebar .group.open .items,.sidebar .subgroup.open .sub-items{animation:slideDown .2s ease-out}

/* Cards de preview - hover scale et shadow */
.cloud-card{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
.cloud-card:hover{transform:translateY(-2px);box-shadow:0 8px 20px rgba(0,0,0,.4);border-color:#444!important}

/* Pop quand checkbox sélectionnée */
.sel-cb:checked{animation:pop .25s ease}

/* Items de la sidebar - smooth hover */
.sidebar .item,.sidebar .group-head,.sidebar .subgroup-head,.sidebar .logout-btn{transition:background .15s,color .15s,padding-left .15s}
.sidebar .item:hover{padding-left:14px}

/* Sub-tabs */
.subtab{transition:color .15s,border-color .15s}

/* Boutons - hover lift */
button[type=submit],.btn,.danger-btn{transition:transform .12s ease,background .15s,box-shadow .15s}
button[type=submit]:hover,.btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(88,101,242,.3)}
.danger-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(217,83,79,.3)}

/* Tooltip sidebar - smooth */
.sidebar .ico .tip{transition:opacity .12s ease,transform .12s ease;transform:translateY(-50%) translateX(-4px)}
.sidebar .ico:hover .tip{transform:translateY(-50%) translateX(0)}

/* Flèches qui pivotent */
.arrow{transition:transform .2s cubic-bezier(.4,0,.2,1)!important}

/* Period buttons Day/Week/Month - smooth */
.ig-period{transition:background .18s ease,color .18s ease!important}

/* Action bar - slide up */
#action-bar{transition:opacity .2s ease,transform .25s cubic-bezier(.16,1,.3,1)}
#action-bar[style*="flex"]{animation:slideUp .3s cubic-bezier(.16,1,.3,1)}

/* Page title - subtle transition */
#page-title,#page-subtitle{transition:opacity .2s}

/* Input focus - glow ring */
input:focus,select:focus,textarea:focus{outline:0;border-color:#5865f2;box-shadow:0 0 0 3px rgba(88,101,242,.15);transition:border-color .15s,box-shadow .15s}

/* Sort options hover */
.ig-sort-opt{transition:background .12s,color .12s,padding-left .12s}
.ig-sort-opt:hover{padding-left:18px}

/* Loading skeleton effect (utile plus tard) */
.skeleton{background:linear-gradient(90deg,#1a1a1a 0%,#2a2a2a 50%,#1a1a1a 100%);background-size:200% 100%;animation:shimmer 1.5s infinite}

/* ============ TOAST NOTIFICATIONS ============ */
.toast-container{position:fixed;top:24px;right:24px;display:flex;flex-direction:column;gap:10px;z-index:9999;pointer-events:none;max-width:420px}
.toast{background:#1a1a1a;border:1px solid #2a2a2a;border-left:4px solid #5865f2;border-radius:10px;padding:14px 18px;color:#fff;font-size:14px;box-shadow:0 12px 32px rgba(0,0,0,.6);display:flex;align-items:flex-start;gap:12px;pointer-events:auto;animation:toastIn .4s cubic-bezier(.16,1,.3,1);min-width:280px;backdrop-filter:blur(10px)}
.toast.success{border-left-color:#00d68f;background:#0f1f17}
.toast.error{border-left-color:#ff4757;background:#1f0f0f}
.toast.info{border-left-color:#5865f2}
.toast.warning{border-left-color:#ffb800;background:#1f1a0f}
.toast .toast-icon{flex-shrink:0;font-size:18px;line-height:1.2}
.toast .toast-msg{flex:1;line-height:1.5}
.toast .toast-close{background:none;border:0;color:#888;cursor:pointer;font-size:18px;padding:0;width:20px;height:20px;display:flex;align-items:center;justify-content:center;margin:0;flex-shrink:0}
.toast .toast-close:hover{color:#fff}
.toast.exit{animation:toastOut .3s ease-in forwards}
@keyframes toastIn{from{opacity:0;transform:translateX(100%) scale(.9)}to{opacity:1;transform:translateX(0) scale(1)}}
@keyframes toastOut{to{opacity:0;transform:translateX(120%) scale(.9)}}

/* Custom confirm modal */
.confirm-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9998;display:none;align-items:center;justify-content:center;animation:fadeIn .2s;backdrop-filter:blur(4px)}
.confirm-overlay.show{display:flex}
.confirm-box{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:14px;padding:28px;max-width:420px;width:90%;animation:scaleIn .3s cubic-bezier(.16,1,.3,1);box-shadow:0 24px 48px rgba(0,0,0,.6)}
.confirm-box h3{margin:0 0 12px;font-size:18px;color:#fff}
.confirm-box p{margin:0 0 24px;color:#aaa;font-size:14px;line-height:1.5}
.confirm-box .actions{display:flex;gap:10px;justify-content:flex-end}
.confirm-box button{padding:10px 22px;border:0;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;margin:0;transition:all .15s}
.confirm-box .btn-cancel{background:#2a2a2a;color:#fff}
.confirm-box .btn-cancel:hover{background:#333}
.confirm-box .btn-confirm{background:#d9534f;color:#fff}
.confirm-box .btn-confirm:hover{background:#c9302c}
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
  showToast('🚧 Pas encore implémenté — viendra bientôt', 'warning');
}
// === SYSTÈME DE TOASTS ===
function showToast(message, type, duration){
  type = type || 'info';
  duration = duration || 4500;
  var container = document.getElementById('toast-container');
  if(!container){
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  var icon = type === 'success' ? '✅' : type === 'error' ? '❌' : type === 'warning' ? '⚠️' : 'ℹ️';
  var toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.innerHTML = '<div class="toast-icon">' + icon + '</div>' +
    '<div class="toast-msg">' + message + '</div>' +
    '<button class="toast-close" onclick="dismissToast(this.parentElement)">×</button>';
  container.appendChild(toast);
  // Auto-dismiss
  setTimeout(function(){ dismissToast(toast); }, duration);
}
function dismissToast(toast){
  if(!toast || !toast.parentElement) return;
  toast.classList.add('exit');
  setTimeout(function(){
    if(toast.parentElement) toast.parentElement.removeChild(toast);
  }, 300);
}
// === MODALE CONFIRM CUSTOM ===
function showConfirm(title, message, onConfirm){
  var overlay = document.getElementById('confirm-overlay');
  if(!overlay) return;
  document.getElementById('confirm-title').textContent = title || 'Confirmer';
  document.getElementById('confirm-message').textContent = message || '';
  overlay.classList.add('show');
  var confirmBtn = document.getElementById('confirm-yes');
  // Reset listener
  var newBtn = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);
  newBtn.addEventListener('click', function(){
    overlay.classList.remove('show');
    if(typeof onConfirm === 'function') onConfirm();
  });
}
function closeConfirm(){
  var overlay = document.getElementById('confirm-overlay');
  if(overlay) overlay.classList.remove('show');
}
// === INTERCEPT FORMS AVEC data-confirm ===
document.addEventListener('submit', function(e){
  var form = e.target;
  if(!form || !form.querySelector) return;
  var btn = form.querySelector('button[data-confirm]');
  if(btn && !form.dataset.confirmed){
    e.preventDefault();
    var msg = btn.getAttribute('data-confirm');
    var title = btn.getAttribute('data-confirm-title') || 'Confirmer cette action ?';
    showConfirm(title, msg, function(){
      form.dataset.confirmed = 'true';
      form.submit();
    });
  }
}, true);
// === FLASH MESSAGE depuis serveur → TOAST ===
window.addEventListener('DOMContentLoaded', function(){
  var data = document.getElementById('flash-data');
  if(data){
    var msg = data.getAttribute('data-msg');
    var type = data.getAttribute('data-type') === 'error' ? 'error' : 'success';
    if(msg) showToast(msg, type);
  }
  // Activer l'onglet depuis query string ?tab=
  var params = new URLSearchParams(window.location.search);
  var tabName = params.get('tab');
  if(tabName){
    var btn = document.getElementById('tab-' + tabName);
    if(btn){
      setTimeout(function(){ btn.click(); }, 50);
    }
  }
});
function igPeriod(btn, period){
  document.querySelectorAll('.ig-period').forEach(function(b){
    b.style.background='none';
    b.style.color='#aaa';
  });
  btn.style.background='#2a2a2a';
  btn.style.color='#fff';
}
function igToggleSort(){
  var menu = document.getElementById('ig-sort-menu');
  var arrow = document.getElementById('ig-sort-arrow');
  var open = menu.style.display === 'block';
  menu.style.display = open ? 'none' : 'block';
  if(arrow) arrow.style.transform = open ? 'rotate(0deg)' : 'rotate(180deg)';
}
function igSelectSort(btn, label){
  document.getElementById('ig-sort-label').textContent = label;
  document.querySelectorAll('.ig-sort-opt').forEach(function(b){
    b.style.color='#aaa';
    b.classList.remove('selected');
    var c = b.querySelector('.check');
    if(c) c.style.display='none';
  });
  btn.style.color='#fff';
  btn.classList.add('selected');
  var c = btn.querySelector('.check');
  if(c) c.style.display='block';
  igToggleSort(); // ferme le menu
}
function igToggleFilters(){
  var panel = document.getElementById('ig-filters-panel');
  if(!panel) return;
  panel.style.display = panel.style.display === 'block' ? 'none' : 'block';
}
function igClearFilters(){
  var panel = document.getElementById('ig-filters-panel');
  if(!panel) return;
  panel.querySelectorAll('input[type=number]').forEach(function(i){ i.value=0; });
  panel.querySelectorAll('input[type=text]').forEach(function(i){ i.value=''; });
}
// Fermer le menu si clic à l'extérieur
document.addEventListener('click', function(e){
  // Sort menu
  var menu = document.getElementById('ig-sort-menu');
  if(menu && menu.style.display === 'block'){
    var sortContainer = menu.parentNode;
    if(sortContainer && !sortContainer.contains(e.target)){
      menu.style.display = 'none';
      var arrow = document.getElementById('ig-sort-arrow');
      if(arrow) arrow.style.transform = 'rotate(0deg)';
    }
  }
  // Filters panel
  var fpanel = document.getElementById('ig-filters-panel');
  if(fpanel && fpanel.style.display === 'block'){
    var fContainer = fpanel.parentNode;
    if(fContainer && !fContainer.contains(e.target)){
      fpanel.style.display = 'none';
    }
  }
});
// Hover sur les options du dropdown
document.addEventListener('mouseover', function(e){
  if(e.target && e.target.classList && e.target.classList.contains('ig-sort-opt')){
    if(!e.target.classList.contains('selected')){
      e.target.style.background='#252525';
      e.target.style.color='#fff';
    }
  }
});
document.addEventListener('mouseout', function(e){
  if(e.target && e.target.classList && e.target.classList.contains('ig-sort-opt')){
    e.target.style.background='none';
    if(!e.target.classList.contains('selected')){
      e.target.style.color='#aaa';
    }
  }
});
// Sélection multiple Cloud
var selectedFiles = new Set();
function toggleSelect(fileId, checked){
  if(checked) selectedFiles.add(fileId);
  else selectedFiles.delete(fileId);
  updateActionBar();
}
function updateActionBar(){
  var bar = document.getElementById('action-bar');
  if(!bar) return;
  var n = selectedFiles.size;
  bar.style.display = n === 0 ? 'none' : 'flex';
  var lbl = document.getElementById('sel-count');
  if(lbl) lbl.textContent = n + ' fichier(s) sélectionné(s)';
}
function clearSelection(){
  selectedFiles.clear();
  document.querySelectorAll('.sel-cb').forEach(function(cb){ cb.checked = false; });
  updateActionBar();
}
// Lightbox pour voir le fichier complet
function openLightbox(url, isVideo, filename){
  var modal = document.getElementById('lightbox');
  var content = document.getElementById('lightbox-content');
  if(isVideo){
    content.innerHTML = '<video controls autoplay style="max-width:100%;max-height:80vh;background:#000;border-radius:8px"><source src="'+url+'"></video>';
  } else {
    content.innerHTML = '<img src="'+url+'" style="max-width:100%;max-height:80vh;object-fit:contain;display:block;border-radius:8px;background:#000">';
  }
  document.getElementById('lightbox-name').textContent = filename;
  modal.style.display = 'flex';
}
function closeLightbox(){
  var modal = document.getElementById('lightbox');
  var content = document.getElementById('lightbox-content');
  modal.style.display = 'none';
  content.innerHTML = ''; // stoppe la vidéo et libère la mémoire
}
// Fermer avec Escape
document.addEventListener('keydown', function(e){
  if(e.key === 'Escape') closeLightbox();
});
function deleteSelected(){
  if(selectedFiles.size === 0) return;
  showConfirm(
    'Supprimer ' + selectedFiles.size + ' fichier(s) ?',
    'Cette action est IRRÉVERSIBLE. Les vidéos/images seront supprimées du serveur ainsi que leurs metadata.',
    function(){
      var form = document.createElement('form');
      form.method = 'POST';
      form.action = '/cloud/delete';
      selectedFiles.forEach(function(fid){
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'files';
        input.value = fid;
        form.appendChild(input);
      });
      document.body.appendChild(form);
      form.submit();
    }
  );
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
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M12 12v9"/><path d="m16 16-4-4-4 4"/></svg>
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

<div class="group" id="grp-cloud">
  <button class="group-head" onclick="toggleGroup('cloud')">
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>
    <span class="label">Cloud</span>
    <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="items">
    <button class="item" onclick="showTab('cloud','cloudoverview','Cloud — Vue d ensemble','Tout ton stockage par type de contenu')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>
      Vue d'ensemble
    </button>
    <button class="item" onclick="showTab('cloud','cloudreels','Cloud — Reels','Tous les reels stockés par identité')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 8-6 4 6 4V8Z"/><rect width="14" height="12" x="2" y="6" rx="2" ry="2"/></svg>
      Reels
    </button>
    <button class="item" onclick="showTab('cloud','cloudposts','Cloud — Posts','Tous les posts stockés')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>
      Posts
    </button>
    <button class="item" onclick="showTab('cloud','cloudstories','Cloud — Stories','Toutes les stories stockées')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/></svg>
      Stories
    </button>
    <button class="item" onclick="showTab('cloud','cloudpps','Cloud — Photos de profil','Pool partagé des PPs')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="10" r="3"/><path d="M7 20.662V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.662"/></svg>
      Photos profil
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
        <button class="item" id="tab-igaccounts" onclick="showTab('trends','igaccounts','Instagram Accounts','Watchlist des comptes Instagram à scrape')"><span class="left">👤 Accounts</span></button>
        <button class="item" id="tab-igtrends" onclick="showTab('trends','igtrends','Instagram Trends','Tendances Instagram')"><span class="left">📈 Trends</span></button>
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
    <button class="item" id="tab-sinsta" onclick="showTab('settings','sinsta','Cookies Instagram','Auth scraper Instagram')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="20" x="2" y="2" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1.2" fill="currentColor"/></svg>
      Cookies Instagram
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

<!-- CLOUD : vue d'ensemble -->
<div class="form-section" id="form-cloudoverview" style="display:none">
<div class="box">
<h3 style="margin-top:0">☁️ Stockage Cloud</h3>
<small>Tout ton contenu hébergé sur le VPS</small>
<div class="stat-grid" style="margin-top:16px">
  <div class="stat"><div class="v">{stat_reels}</div><div class="l">Reels</div></div>
  <div class="stat"><div class="v">{stat_posts}</div><div class="l">Posts</div></div>
  <div class="stat"><div class="v">{stat_stories}</div><div class="l">Stories</div></div>
  <div class="stat"><div class="v">{stat_storyctas}</div><div class="l">Story CTAs</div></div>
  <div class="stat"><div class="v">{stat_pps}</div><div class="l">Photos profil</div></div>
  <div class="stat"><div class="v">{stat_identities}</div><div class="l">Identités</div></div>
</div>
</div>
<div class="box">
<h4 style="margin-top:0">Répartition par identité</h4>
{identity_stats_html}
</div>
</div>

<!-- CLOUD : reels -->
<div class="form-section" id="form-cloudreels" style="display:none">
<div class="box">
<h3 style="margin-top:0">🎬 Reels stockés</h3>
{cloud_reels_html}
</div>
</div>

<!-- CLOUD : posts -->
<div class="form-section" id="form-cloudposts" style="display:none">
<div class="box">
<h3 style="margin-top:0">📸 Posts stockés</h3>
{cloud_posts_html}
</div>
</div>

<!-- CLOUD : stories -->
<div class="form-section" id="form-cloudstories" style="display:none">
<div class="box">
<h3 style="margin-top:0">📱 Stories stockées</h3>
{cloud_stories_html}
</div>
</div>

<!-- CLOUD : PPs -->
<div class="form-section" id="form-cloudpps" style="display:none">
<div class="box">
<h3 style="margin-top:0">👤 Photos de profil (pool partagé)</h3>
{cloud_pps_html}
</div>
</div>

<!-- INSTAGRAM ACCOUNTS (watchlist) -->
<div class="form-section" id="form-igaccounts" style="display:none">
<div class="box">
<h3 style="margin-top:0">👤 Watchlist Instagram</h3>
<small style="margin-bottom:14px">Ajoute les comptes Instagram dont tu veux scraper les reels. Le scrape utilise les cookies configurés dans Settings → Instagram.</small>
{insta_accounts_html}
</div>
</div>

<!-- INSTAGRAM TRENDS -->
<div class="form-section" id="form-igtrends" style="display:none">

<!-- Header avec stats agency -->
<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:16px 20px;margin-bottom:24px;display:flex;align-items:center;gap:16px">
  <div style="display:flex;align-items:center;gap:10px;flex:1">
    <div style="width:36px;height:36px;background:#2a2a2a;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#888" stroke-width="2"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
    </div>
    <div style="width:44px;height:44px;background:#2a2a2a;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff">YO</div>
    <div>
      <div style="font-weight:700;font-size:18px;color:#fff">Youssef</div>
      <div style="font-size:11px;color:#888;letter-spacing:1px">AGENCY</div>
    </div>
  </div>
  <div style="display:flex;gap:18px;align-items:center;color:#888;font-size:14px">
    <span style="display:flex;align-items:center;gap:4px">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
      0
    </span>
    <span style="display:flex;align-items:center;gap:4px">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
      0
    </span>
    <span style="display:flex;align-items:center;gap:4px">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
      0
    </span>
    <span style="display:flex;align-items:center;gap:4px">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/></svg>
      0
    </span>
    <div style="width:40px;height:40px;border:2px solid #a855f7;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#a855f7;cursor:pointer">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2"/></svg>
    </div>
  </div>
</div>

<h2 style="margin:0 0 18px;font-size:26px">Trends</h2>

<!-- Barre de contrôles : Trending / Day / Week / Month / Filters -->
<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:24px">

  <div style="position:relative">
    <div onclick="igToggleSort()" style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:8px 14px;display:flex;align-items:center;gap:8px;cursor:pointer;color:#fff;user-select:none">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M6 12h12M10 18h4"/></svg>
      <span style="font-weight:600;font-size:14px" id="ig-sort-label">Trending</span>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" id="ig-sort-arrow" style="transition:transform .15s"><polyline points="6 9 12 15 18 9"/></svg>
    </div>
    <div id="ig-sort-menu" style="display:none;position:absolute;top:46px;left:0;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:6px;min-width:200px;box-shadow:0 8px 24px rgba(0,0,0,.5);z-index:50">
      <button onclick="igSelectSort(this,'Trending')" class="ig-sort-opt selected" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#fff;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Trending<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Newest')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Newest<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Oldest')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Oldest<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Views')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Views<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Views')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Views<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Likes')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Likes<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Likes')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Likes<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Comments')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Comments<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Comments')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Comments<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#5865f2" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
    </div>
  </div>

  <div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:4px;display:flex;gap:2px">
    <button onclick="igPeriod(this,'day')" class="ig-period" style="padding:8px 22px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;font-weight:600;border-radius:7px;margin:0">Day</button>
    <button onclick="igPeriod(this,'week')" class="ig-period active" style="padding:8px 22px;background:#2a2a2a;border:0;color:#fff;cursor:pointer;font-size:14px;font-weight:600;border-radius:7px;margin:0">Week</button>
    <button onclick="igPeriod(this,'month')" class="ig-period" style="padding:8px 22px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;font-weight:600;border-radius:7px;margin:0">Month</button>
  </div>

  <div style="position:relative;margin-left:auto">
    <div onclick="igToggleFilters()" id="ig-filters-btn" style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:8px 16px;display:flex;align-items:center;gap:8px;cursor:pointer;color:#fff;user-select:none">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
      <span style="font-weight:600;font-size:14px">Filters</span>
    </div>
    <div id="ig-filters-panel" style="display:none;position:absolute;top:48px;right:0;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:20px;width:340px;box-shadow:0 12px 32px rgba(0,0,0,.6);z-index:60;max-height:600px;overflow-y:auto">
      <h3 style="margin:0 0 16px;font-size:18px">Filters</h3>

      <div class="filter-section" style="margin-bottom:18px">
        <div style="display:flex;gap:10px">
          <div style="flex:1"><div style="font-size:12px;color:#888;margin-bottom:4px">Views — Min.</div><input type="number" value="0" min="0" style="width:100%;padding:9px 10px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:14px"></div>
          <div style="flex:1"><div style="font-size:12px;color:#888;margin-bottom:4px">Views — Max.</div><input type="number" value="0" min="0" style="width:100%;padding:9px 10px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:14px"></div>
        </div>
      </div>

      <div class="filter-section" style="margin-bottom:18px">
        <div style="font-weight:600;margin-bottom:8px;font-size:14px">Likes</div>
        <div style="display:flex;gap:10px">
          <div style="flex:1"><div style="font-size:12px;color:#888;margin-bottom:4px">Min. Value</div><input type="number" value="0" min="0" style="width:100%;padding:9px 10px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:14px"></div>
          <div style="flex:1"><div style="font-size:12px;color:#888;margin-bottom:4px">Max. Value</div><input type="number" value="0" min="0" style="width:100%;padding:9px 10px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:14px"></div>
        </div>
      </div>

      <div class="filter-section" style="margin-bottom:18px">
        <div style="font-weight:600;margin-bottom:8px;font-size:14px">Followers</div>
        <div style="display:flex;gap:10px">
          <div style="flex:1"><div style="font-size:12px;color:#888;margin-bottom:4px">Min. Value</div><input type="number" value="0" min="0" style="width:100%;padding:9px 10px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:14px"></div>
          <div style="flex:1"><div style="font-size:12px;color:#888;margin-bottom:4px">Max. Value</div><input type="number" value="0" min="0" style="width:100%;padding:9px 10px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:14px"></div>
        </div>
      </div>

      <div class="filter-section" style="margin-bottom:18px">
        <div style="font-weight:600;margin-bottom:8px;font-size:14px">Creators</div>
        <div style="padding:10px 12px;background:#0f0f0f;border:1px solid #333;color:#666;border-radius:6px;font-size:13px;margin-bottom:8px">No creators selected</div>
        <div style="position:relative">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#666" stroke-width="2" style="position:absolute;left:10px;top:50%;transform:translateY(-50%)"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input type="text" placeholder="Search creators" style="width:100%;padding:9px 10px 9px 32px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:14px">
        </div>
        <div style="margin-top:8px;padding:10px 12px;background:#0f0f0f;border:1px solid #333;border-radius:6px;color:#888;font-size:13px">
          You haven't added any creators yet.<br>
          <a href="#" onclick="comingSoon();return false;" style="color:#7289da">Add your first creator</a> now.
        </div>
      </div>

      <div class="filter-section" style="margin-bottom:18px">
        <div style="font-weight:600;margin-bottom:8px;font-size:14px">Custom Instagram Watchlists</div>
        <div style="padding:10px 12px;background:#0f0f0f;border:1px solid #333;color:#666;border-radius:6px;font-size:13px;margin-bottom:8px">No watchlist selected</div>
        <div style="padding:10px 12px;background:#0f0f0f;border:1px solid #333;border-radius:6px;color:#888;font-size:13px;margin-bottom:8px">
          Your Instagram watchlist is empty.<br>Start adding accounts you want to keep an eye on!
        </div>
        <button onclick="comingSoon()" style="width:100%;padding:10px;background:none;border:1px dashed #444;color:#aaa;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;margin:0">+ Create new watchlist</button>
      </div>

      <button onclick="igClearFilters()" style="width:100%;padding:11px;background:#2a2a2a;border:0;color:#fff;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;margin:8px 0 0">Clear Filters</button>
    </div>
  </div>
</div>

{insta_trends_html_or_empty}

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

<!-- SETTINGS - INSTAGRAM COOKIES -->
<div class="form-section" id="form-sinsta" style="display:none">

<!-- RapidAPI - méthode recommandée -->
<form method="POST" action="/settings/insta_rapidapi" class="box" style="border:2px solid #00d68f">
<h3 style="margin-top:0">🚀 RapidAPI <span style="background:#00d68f;color:#000;padding:2px 8px;border-radius:4px;font-size:11px;margin-left:8px">RECOMMANDÉ</span></h3>
<small>Méthode <b>fiable + illimitée</b> (~30€/mois) — pas de rate-limit, pas besoin de cookies, pas de risque ban.</small>
<details style="margin-top:12px;margin-bottom:14px"><summary style="cursor:pointer;color:#7289da;font-size:14px;font-weight:600">📖 Comment souscrire ?</summary>
<div style="padding:14px;background:#0f0f0f;border-radius:6px;margin-top:8px;font-size:13px;line-height:1.7;color:#aaa">
1. Crée un compte sur <a href="https://rapidapi.com/" target="_blank">RapidAPI.com</a> (gratuit)<br>
2. Va sur l'API : <a href="https://rapidapi.com/social-api1/api/instagram-scraper-stable-api/" target="_blank"><b>Instagram Scraper Stable API</b></a><br>
3. Clique <b>Subscribe to Test</b> → choisis un plan (commence par <b>BASIC ~$5/mois</b> pour tester)<br>
4. Dans l'onglet <b>Endpoints</b>, en haut tu vois ta <b>x-rapidapi-key</b> → copie-la<br>
5. Colle-la ci-dessous → Sauver<br><br>
<b>Alternative cheap :</b> Tu peux aussi essayer la version gratuite (limite : ~50 requêtes/mois)
</div>
</details>
<label>x-rapidapi-key</label>
<input type="password" name="rapidapi_key" placeholder="abcdefghijklmnopqrstuvwxyz1234567890..." required>
<label>x-rapidapi-host (défaut OK)</label>
<input type="text" name="rapidapi_host" value="instagram-scraper-stable-api.p.rapidapi.com">
<button type="submit">💾 Sauver la clé RapidAPI</button>
</form>

<div style="margin:24px 0;border-top:1px solid #2a2a2a;padding-top:20px">
<h4 style="margin:0 0 8px;color:#888">— OU méthode gratuite (rate-limitée) —</h4>
</div>

<!-- Import depuis fichier cookies.txt -->
<form method="POST" action="/settings/insta_auth_file" enctype="multipart/form-data" class="box" style="border:2px dashed #5865f2">
<h3 style="margin-top:0">⚡ Import rapide depuis fichier cookies.txt</h3>
<small>Méthode la plus simple : uploade le fichier cookies.txt téléchargé via l'extension <b>"Get cookies.txt"</b> de Chrome.</small>
<label style="margin-top:14px">Fichier cookies.txt</label>
<input type="file" name="cookies_file" accept=".txt,text/plain" required>
<small>Format Netscape (par défaut dans l'extension)</small>
<button type="submit">📥 Importer</button>
</form>

<form method="POST" action="/settings/insta_auth" class="box">
<h3 style="margin-top:0">🔧 Saisie manuelle des cookies</h3>
<small>Statut : <b>{insta_auth_status}</b></small>
<details style="margin-top:14px;margin-bottom:14px"><summary style="cursor:pointer;color:#7289da;font-size:14px;font-weight:600">📖 Comment récupérer mes cookies ?</summary>
<div style="padding:14px;background:#0f0f0f;border-radius:6px;margin-top:8px;font-size:13px;line-height:1.6;color:#aaa">
1. Ouvre <a href="https://www.instagram.com" target="_blank">instagram.com</a> dans Chrome/Firefox<br>
2. Connecte-toi avec un <b>compte secondaire</b> (pas ton compte perso — risque ban)<br>
3. Appuie sur <b>F12</b> → onglet <b>Application</b> (Chrome) ou <b>Storage</b> (Firefox)<br>
4. Section <b>Cookies → https://www.instagram.com</b><br>
5. Copie les valeurs de :<br>
&nbsp;&nbsp;• <code>sessionid</code> (obligatoire)<br>
&nbsp;&nbsp;• <code>ds_user_id</code> (recommandé)<br>
&nbsp;&nbsp;• <code>csrftoken</code> (recommandé)<br>
6. Colle-les ci-dessous
</div>
</details>
<label>sessionid <span style="color:#f99">*</span></label>
<input type="password" name="sessionid" placeholder="XXXXXXXXXX%3AYYYY%3A26%3A..." required>
<label>ds_user_id</label>
<input type="text" name="ds_user_id" placeholder="123456789">
<label>csrftoken</label>
<input type="text" name="csrftoken" placeholder="abc123...">
<label>Ton username Instagram (optionnel)</label>
<input type="text" name="username" placeholder="ton_compte_secondaire">
<small>⚠️ Utilise un <b>compte secondaire</b>. Risque de ban si Instagram détecte le scraping.</small>
<button type="submit">💾 Sauver les cookies</button>
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

</div>

<!-- Barre flottante d'actions (apparaît quand items sélectionnés) -->
<div id="action-bar" style="display:none;position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1a1a1a;border:1px solid #444;border-radius:14px;padding:12px 18px;box-shadow:0 6px 24px rgba(0,0,0,.6);z-index:200;align-items:center;gap:14px">
  <span id="sel-count" style="font-weight:600;color:#fff;font-size:14px">0 fichier(s) sélectionné(s)</span>
  <button onclick="clearSelection()" style="padding:8px 14px;background:#333;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;margin:0">Annuler</button>
  <button onclick="deleteSelected()" style="padding:8px 18px;background:#d9534f;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;margin:0">🗑 Supprimer</button>
</div>

<!-- Lightbox plein écran -->
<div id="lightbox" onclick="closeLightbox()" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:300;align-items:center;justify-content:center;padding:30px;animation:fadeIn .2s">
  <div style="position:relative;max-width:90vw;max-height:90vh" onclick="event.stopPropagation()">
    <button onclick="closeLightbox()" style="position:absolute;top:-46px;right:0;background:rgba(255,255,255,.1);border:0;color:#fff;width:36px;height:36px;border-radius:50%;cursor:pointer;font-size:22px;line-height:1;padding:0">×</button>
    <div id="lightbox-content"></div>
    <div id="lightbox-name" style="text-align:center;margin-top:14px;color:#aaa;font-family:monospace;font-size:13px"></div>
  </div>
</div>

<!-- Container pour les toasts -->
<div id="toast-container" class="toast-container"></div>

<!-- Modale confirm custom -->
<div id="confirm-overlay" class="confirm-overlay" onclick="closeConfirm()">
  <div class="confirm-box" onclick="event.stopPropagation()">
    <h3 id="confirm-title">Confirmer</h3>
    <p id="confirm-message">Es-tu sûr ?</p>
    <div class="actions">
      <button class="btn-cancel" onclick="closeConfirm()">Annuler</button>
      <button class="btn-confirm" id="confirm-yes">Confirmer</button>
    </div>
  </div>
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
                f"data-confirm=\"Reset @{username} ? Le VA gardera son salon Discord mais perdra son identité assignée.\">Reset</button>"
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


def _thumb_path_for(rel_key: str) -> Path:
    """Chemin du thumbnail pour une clé relative (genre 'amelia/videos/file.mp4')."""
    return THUMB_DIR / f"{rel_key}.jpg"


def _generate_image_thumbnail(src: Path, dest: Path) -> bool:
    """Génère un thumbnail JPEG à partir d'une image."""
    try:
        from PIL import Image
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            img.save(dest, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return True
    except Exception as e:
        log.error(f"Image thumbnail error pour {src}: {e}")
        return False


def _generate_video_thumbnail(src: Path, dest: Path) -> bool:
    """Extrait une frame de la vidéo comme thumbnail via ffmpeg."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", "0.5",  # commencer à 0.5 sec
            "-i", str(src),
            "-vframes", "1",
            "-vf", f"scale={THUMB_SIZE}:-2",
            "-q:v", "5",
            str(dest),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        return result.returncode == 0 and dest.exists()
    except Exception as e:
        log.error(f"Video thumbnail error pour {src}: {e}")
        return False


def _get_or_create_thumbnail(src: Path, rel_key: str, is_video: bool) -> Path:
    """Retourne le path du thumbnail, en le générant si besoin."""
    thumb = _thumb_path_for(rel_key)
    if thumb.exists():
        return thumb
    if is_video:
        ok = _generate_video_thumbnail(src, thumb)
    else:
        ok = _generate_image_thumbnail(src, thumb)
    return thumb if ok else None


def _fmt_size(p) -> str:
    try:
        size_kb = p.stat().st_size / 1024
        return f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
    except Exception:
        return "?"


def _preview_card(media_url: str, thumb_url: str, file_path, is_video: bool, file_id: str = "") -> str:
    """Une carte avec thumbnail (rapide) + clic pour ouvrir lightbox + checkbox."""
    name = file_path.name
    size = _fmt_size(file_path)
    # Badge "play" superposé pour les vidéos
    play_badge = ""
    if is_video:
        play_badge = (
            "<div style='position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);"
            "width:44px;height:44px;background:rgba(0,0,0,.65);border-radius:50%;"
            "display:flex;align-items:center;justify-content:center;pointer-events:none'>"
            "<svg viewBox='0 0 24 24' width='22' height='22' fill='#fff'><polygon points='5 3 19 12 5 21'/></svg>"
            "</div>"
        )
    is_video_js = "true" if is_video else "false"
    media_html = (
        f"<div onclick='openLightbox(\"{media_url}\",{is_video_js},\"{name}\")' "
        f"style='cursor:pointer;position:relative;width:100%;height:160px;background:#000;border-radius:6px 6px 0 0;overflow:hidden'>"
        f"<img src='{thumb_url}' loading='lazy' "
        f"style='width:100%;height:100%;object-fit:cover;display:block'>"
        f"{play_badge}"
        f"</div>"
    )
    checkbox_html = ""
    if file_id:
        checkbox_html = (
            f"<input type='checkbox' class='sel-cb' "
            f"onchange='toggleSelect(\"{file_id}\", this.checked)' "
            f"onclick='event.stopPropagation()' "
            f"style='position:absolute;top:8px;left:8px;width:20px;height:20px;cursor:pointer;z-index:5;accent-color:#5865f2;background:#000;border-radius:4px'>"
        )
    return (
        f"<div class='cloud-card' style='background:#0f0f0f;border:1px solid #2a2a2a;border-radius:8px;overflow:hidden;position:relative'>"
        f"{checkbox_html}"
        f"{media_html}"
        f"<div style='padding:8px 10px'>"
        f"<div style='font-size:12px;color:#ccc;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' title='{name}'>{name}</div>"
        f"<div style='font-size:11px;color:#666;margin-top:2px'>{size}</div>"
        f"</div>"
        f"</div>"
    )


def _render_cloud_content_html(subdir: str, exts) -> str:
    """Liste les fichiers de <subdir> par identité avec previews en grille."""
    identities = _list_identities()
    if not identities:
        return "<p style='color:#888'>Aucune identité créée.</p>"
    is_video = subdir == "videos"
    rows = []
    total = 0
    for ident in identities:
        folder = IDENTITIES_DIR / ident / subdir
        files = []
        if folder.exists():
            files = sorted([
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in exts and ".example" not in p.name
            ])
        if not files:
            continue
        total += len(files)
        rows.append(
            f"<div style='margin-top:22px;display:flex;align-items:center;gap:10px'>"
            f"<h4 style='margin:0;color:#5865f2;font-size:15px'>👤 {ident}</h4>"
            f"<small style='color:#666'>{len(files)} fichier(s)</small>"
            f"</div>"
        )
        rows.append("<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-top:10px'>")
        for p in files:
            url = f"/cloud/file/{ident}/{subdir}/{p.name}"
            thumb_url = f"/cloud/thumb/{ident}/{subdir}/{p.name}"
            file_id = f"{ident}|{subdir}|{p.name}"
            rows.append(_preview_card(url, thumb_url, p, is_video, file_id))
        rows.append("</div>")
    if not rows:
        return "<p style='color:#888'>Aucun fichier stocké.</p>"
    rows.append(f"<div style='margin-top:22px;padding-top:14px;border-top:1px solid #2a2a2a'><small>Total : <b>{total}</b> fichier(s)</small></div>")
    return "".join(rows)


def _render_cloud_pps_html() -> str:
    """PPs partagées avec preview en grille."""
    if not PROFILE_PICS_DIR.exists():
        return "<p style='color:#888'>Aucune PP uploadée.</p>"
    files = sorted([p for p in PROFILE_PICS_DIR.iterdir() if p.is_file()])
    if not files:
        return "<p style='color:#888'>Aucune PP uploadée.</p>"
    rows = ["<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px'>"]
    for p in files:
        url = f"/cloud/pp/{p.name}"
        thumb_url = f"/cloud/thumb/pp/{p.name}"
        file_id = f"_pp_|pp|{p.name}"
        rows.append(_preview_card(url, thumb_url, p, is_video=False, file_id=file_id))
    rows.append(f"</div><div style='margin-top:18px'><small>Total : <b>{len(files)}</b> PP(s) partagée(s)</small></div>")
    return "".join(rows)


def _render_insta_auth_status() -> str:
    try:
        from insta_scraper import auth_status
        return auth_status()
    except Exception:
        return "❌ Module pas chargé"


def _render_insta_accounts_html() -> str:
    """Render la page Accounts (watchlist + add/remove/scrape)."""
    try:
        from insta_scraper import watchlist_status, is_auth_configured
    except Exception as e:
        return f"<p style='color:#f99'>Module insta_scraper indisponible : {e}</p>"
    rows = [
        "<form method='POST' action='/insta/add_account' style='display:flex;gap:8px;margin-bottom:16px'>"
        "<input type='text' name='username' placeholder='@username ou URL profil' required "
        "style='flex:1;padding:10px 12px;background:#0f0f0f;border:1px solid #333;color:#fff;border-radius:6px;font-size:14px'>"
        "<button type='submit' style='padding:10px 18px;background:#5865f2;color:#fff;border:0;border-radius:6px;cursor:pointer;font-weight:600'>+ Ajouter</button>"
        "</form>"
    ]
    if not is_auth_configured():
        rows.append(
            "<div style='padding:12px;background:#3a1a1a;border:1px solid #5a2a2a;color:#f99;border-radius:8px;margin-bottom:14px;font-size:14px'>"
            "⚠️ Tu n'as pas configuré tes cookies Instagram — va dans <b>Settings → Instagram</b>."
            "</div>"
        )
    items = watchlist_status()
    if not items:
        rows.append("<p style='color:#888'>Aucun compte ajouté pour l'instant.</p>")
    else:
        rows.append(
            "<table style='width:100%;border-collapse:collapse'>"
            "<tr style='background:#1a1a1a'>"
            "<th style='padding:10px 8px;text-align:left'>Compte</th>"
            "<th style='padding:10px 8px;text-align:center'>Followers</th>"
            "<th style='padding:10px 8px;text-align:center'>Reels en cache</th>"
            "<th style='padding:10px 8px;text-align:center'>Dernier scrape</th>"
            "<th style='padding:10px 8px;text-align:right'>Actions</th>"
            "</tr>"
        )
        import datetime
        for it in items:
            u = it["username"]
            scraped = it["scraped_at"]
            if scraped:
                dt = datetime.datetime.fromtimestamp(scraped)
                scraped_str = dt.strftime("%d/%m %H:%M")
            else:
                scraped_str = "<span style='color:#888'>jamais</span>"
            fname = it["full_name"] or ""
            fname_html = f"<div style='font-size:11px;color:#888'>{fname}</div>" if fname else ""
            rows.append(
                f"<tr style='border-bottom:1px solid #2a2a2a'>"
                f"<td style='padding:10px 8px'><b>@{u}</b>{fname_html}</td>"
                f"<td style='padding:10px 8px;text-align:center'>{it['followers']:,}</td>"
                f"<td style='padding:10px 8px;text-align:center'>{it['nb_reels']}</td>"
                f"<td style='padding:10px 8px;text-align:center;font-size:13px;color:#aaa'>{scraped_str}</td>"
                f"<td style='padding:10px 8px;text-align:right'>"
                f"<form method='POST' action='/insta/scrape' style='display:inline'>"
                f"<input type='hidden' name='username' value='{u}'>"
                f"<button type='submit' style='padding:6px 12px;background:#5865f2;color:#fff;border:0;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600;margin:0'>🔄 Scrape</button>"
                f"</form>"
                f"<form method='POST' action='/insta/remove_account' style='display:inline;margin-left:6px'>"
                f"<input type='hidden' name='username' value='{u}'>"
                f"<button type='submit' class='danger-btn' data-confirm=\"Retirer @{u} de la watchlist Instagram ? Le cache des reels sera conservé.\">Retirer</button>"
                f"</form>"
                f"</td></tr>"
            )
        rows.append("</table>")
        rows.append(
            f"<form method='POST' action='/insta/scrape_all' style='margin-top:18px'>"
            f"<button type='submit' style='padding:12px 24px;background:#5865f2;color:#fff;border:0;border-radius:8px;cursor:pointer;font-weight:600' "
            f"data-confirm=\"Scraper tous les comptes de la watchlist ? Compte ~10 secondes par compte.\" data-confirm-title=\"Lancer le scrape global\">🔄 Scraper tous les comptes</button>"
            f"</form>"
        )
    return "".join(rows)


def _render_insta_trends_grid_html() -> str:
    """Grille des reels scrapés depuis tous les comptes en watchlist."""
    try:
        from insta_scraper import get_all_cached_reels
    except Exception:
        return ""
    reels = get_all_cached_reels()
    if not reels:
        return ""
    # Trier par views décroissant par défaut
    reels.sort(key=lambda r: (r.get("views") or 0), reverse=True)
    cards = ["<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin-top:14px'>"]
    for r in reels[:60]:
        thumb = r.get("thumbnail_url") or ""
        owner = r.get("_owner", "?")
        url = r.get("url", "#")
        views = r.get("views")
        likes = r.get("likes", 0)
        comments = r.get("comments", 0)
        caption = (r.get("caption") or "")[:80]
        is_video = r.get("is_video")
        play_badge = ""
        if is_video:
            play_badge = (
                "<div style='position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);"
                "width:44px;height:44px;background:rgba(0,0,0,.65);border-radius:50%;"
                "display:flex;align-items:center;justify-content:center'>"
                "<svg viewBox='0 0 24 24' width='22' height='22' fill='#fff'><polygon points='5 3 19 12 5 21'/></svg>"
                "</div>"
            )
        views_str = f"{views:,}" if views else "—"
        cards.append(
            f"<a href='{url}' target='_blank' class='cloud-card' style='background:#0f0f0f;border:1px solid #2a2a2a;border-radius:10px;overflow:hidden;text-decoration:none;color:inherit;display:block'>"
            f"<div style='position:relative;width:100%;height:280px;background:#000'>"
            f"<img src='{thumb}' loading='lazy' style='width:100%;height:100%;object-fit:cover'>"
            f"{play_badge}"
            f"</div>"
            f"<div style='padding:10px 12px'>"
            f"<div style='font-size:13px;color:#fff;font-weight:600;margin-bottom:4px'>@{owner}</div>"
            f"<div style='font-size:11px;color:#888;height:30px;overflow:hidden'>{caption}</div>"
            f"<div style='display:flex;gap:10px;margin-top:8px;font-size:12px;color:#aaa'>"
            f"<span>👁️ {views_str}</span>"
            f"<span>❤️ {likes:,}</span>"
            f"<span>💬 {comments:,}</span>"
            f"</div></div></a>"
        )
    cards.append("</div>")
    cards.append(f"<div style='margin-top:18px'><small>{len(reels)} reel(s) au total — affichage des 60 premiers</small></div>")
    return "".join(cards)


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


def _render_upload(msg=None, error=None):
    # Si appelé sans msg, lire depuis session (flash)
    try:
        from flask import session
        if msg is None:
            msg = session.pop("flash_msg", "")
        if error is None:
            error = session.pop("flash_error", False)
    except Exception:
        msg = msg or ""
        error = bool(error)
    identities = _list_identities()
    opts = "".join(f'<option value="{i}">{i}</option>' for i in identities)
    if not opts:
        opts = '<option value="">(aucune identité - crée-en sur Discord)</option>'
    msg_html = ""
    if msg:
        # Stocker comme attribut data-* sur un élément invisible, le JS l'animera comme toast
        msg_safe = str(msg).replace('"', '&quot;')
        msg_type = "error" if error else "success"
        msg_html = f'<div id="flash-data" data-msg="{msg_safe}" data-type="{msg_type}" style="display:none"></div>'
    # Stats globales pour le home
    users = _load_users()
    va_count = len(users)
    identities_list = _list_identities()
    stat_reels = sum(_identity_stats(i)["reels"] for i in identities_list)
    stat_posts = sum(_identity_stats(i)["posts"] for i in identities_list)
    stat_stories = sum(_identity_stats(i)["stories"] for i in identities_list)
    stat_storyctas = sum(_identity_stats(i)["storyctas"] for i in identities_list)
    # PPs partagées
    stat_pps = 0
    if PROFILE_PICS_DIR.exists():
        stat_pps = sum(1 for p in PROFILE_PICS_DIR.iterdir() if p.is_file())
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
        .replace("{stat_pps}", str(stat_pps))
        .replace("{cloud_reels_html}", _render_cloud_content_html("videos", VIDEO_EXTS))
        .replace("{cloud_posts_html}", _render_cloud_content_html("posts", IMAGE_EXTS))
        .replace("{cloud_stories_html}", _render_cloud_content_html("stories", IMAGE_EXTS))
        .replace("{cloud_pps_html}", _render_cloud_pps_html())
        .replace("{insta_auth_status}", _render_insta_auth_status())
        .replace("{insta_accounts_html}", _render_insta_accounts_html())
        .replace("{insta_trends_html_or_empty}", _render_insta_trends_grid_html() or
            "<div style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:60px 20px;text-align:center;color:#666'>"
            "<svg viewBox='0 0 24 24' width='48' height='48' fill='none' stroke='currentColor' stroke-width='1.5' style='margin-bottom:14px'><polyline points='22 7 13.5 15.5 8.5 10.5 2 17'/><polyline points='16 7 22 7 22 13'/></svg>"
            "<h3 style='margin:0 0 8px;color:#888'>Aucun reel scrapé</h3>"
            "<p style='margin:0;font-size:14px'>Ajoute des comptes dans <b>Instagram → Accounts</b> et lance un scrape.<br>Configure d'abord tes cookies dans <b>Settings → Cookies Instagram</b>.</p>"
            "</div>"
        )
    )


def create_app():
    from flask import Flask, request, session, redirect, make_response
    app = Flask(__name__)
    app.secret_key = os.environ.get("WEB_SECRET", os.urandom(24).hex())

    def is_auth():
        return session.get("auth") is True

    def _success(msg, tab=None):
        """Pattern POST-Redirect-GET : flash le message + redirige sur GET /."""
        session["flash_msg"] = msg
        session["flash_error"] = False
        url = "/"
        if tab:
            url += f"?tab={tab}"
        return redirect(url)

    def _error(msg, tab=None):
        session["flash_msg"] = msg
        session["flash_error"] = True
        url = "/"
        if tab:
            url += f"?tab={tab}"
        return redirect(url)

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "POST" and not is_auth():
            if request.form.get("password") == WEB_PASSWORD:
                session["auth"] = True
                return redirect("/")
            return _render_login("Mauvais mot de passe")
        if not is_auth():
            return _render_login()
        return _success()

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/")

    def _save_image_or_video_with_pair(form_files, form_text, subdir_name, allow_exts):
        identity = form_text.get("identity", "").strip().lower()
        if not identity or identity not in _list_identities():
            return _error("Identité invalide")
        photo = form_files.get("photo") or form_files.get("video")
        if not photo or not photo.filename:
            return _error("Fichier manquant")
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in allow_exts:
            return _error(f"Format non supporté ({ext})")
        target_dir = IDENTITIES_DIR / identity / subdir_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / photo.filename
        if target.exists():
            return _error(f"Fichier {photo.filename} existe déjà")
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
        return _success(f"✅ Ajouté à {identity}/{subdir_name} : {photo.filename}")

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
            return _error("Identité invalide")
        photo = request.files.get("photo")
        if not photo or not photo.filename:
            return _error("Photo manquante")
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in IMAGE_EXTS:
            return _error(f"Format non supporté ({ext})")
        target_dir = IDENTITIES_DIR / identity / "storyctas"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / photo.filename
        if target.exists():
            return _error(f"Fichier existe déjà")
        photo.save(str(target))
        return _success(f"✅ Story CTA ajoutée à {identity}")

    @app.route("/cloud/thumb/<identity>/<subdir>/<path:filename>")
    def cloud_thumb_file(identity, subdir, filename):
        if not is_auth():
            return redirect("/")
        if subdir not in {"videos", "posts", "stories", "storyctas"}:
            return "Not found", 404
        safe_identity = identity.lower().strip()
        if safe_identity not in _list_identities():
            return "Not found", 404
        if "/" in filename or "\\" in filename or ".." in filename:
            return "Forbidden", 403
        src = IDENTITIES_DIR / safe_identity / subdir / filename
        if not src.exists() or not src.is_file():
            return "Not found", 404
        rel_key = f"{safe_identity}/{subdir}/{filename}"
        is_video = subdir == "videos"
        thumb = _get_or_create_thumbnail(src, rel_key, is_video)
        if thumb is None or not thumb.exists():
            # Fallback : servir le fichier original
            from flask import send_file
            response = send_file(str(src))
            response.headers["Cache-Control"] = "public, max-age=3600"
            return response
        from flask import send_file
        response = send_file(str(thumb))
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    @app.route("/cloud/thumb/pp/<path:filename>")
    def cloud_thumb_pp(filename):
        if not is_auth():
            return redirect("/")
        if "/" in filename or "\\" in filename or ".." in filename:
            return "Forbidden", 403
        src = PROFILE_PICS_DIR / filename
        if not src.exists() or not src.is_file():
            return "Not found", 404
        rel_key = f"pp/{filename}"
        thumb = _get_or_create_thumbnail(src, rel_key, is_video=False)
        if thumb is None or not thumb.exists():
            from flask import send_file
            response = send_file(str(src))
            response.headers["Cache-Control"] = "public, max-age=3600"
            return response
        from flask import send_file
        response = send_file(str(thumb))
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    @app.route("/cloud/file/<identity>/<subdir>/<path:filename>")
    def cloud_serve_file(identity, subdir, filename):
        if not is_auth():
            return redirect("/")
        # Sécurité : restreindre aux dossiers valides
        if subdir not in {"videos", "posts", "stories", "storyctas"}:
            return "Not found", 404
        safe_identity = identity.lower().strip()
        if safe_identity not in _list_identities():
            return "Not found", 404
        # Empêcher path traversal
        if "/" in filename or "\\" in filename or ".." in filename:
            return "Forbidden", 403
        path = IDENTITIES_DIR / safe_identity / subdir / filename
        if not path.exists() or not path.is_file():
            return "Not found", 404
        from flask import send_file
        return send_file(str(path))

    @app.route("/cloud/delete", methods=["POST"])
    def cloud_delete():
        if not is_auth():
            return redirect("/")
        files = request.form.getlist("files")
        if not files:
            return _error("❌ Aucun fichier sélectionné")
        deleted = []
        failed = []
        identities_list = _list_identities()
        valid_subdirs = {"videos", "posts", "stories", "storyctas"}
        for fid in files:
            try:
                parts = fid.split("|", 2)
                if len(parts) != 3:
                    failed.append((fid, "format invalide"))
                    continue
                scope, subdir, filename = parts
                # Path traversal check
                if "/" in filename or "\\" in filename or ".." in filename or not filename:
                    failed.append((fid, "filename invalide"))
                    continue
                # PP partagée
                if scope == "_pp_" and subdir == "pp":
                    path = PROFILE_PICS_DIR / filename
                # Fichier identité
                elif scope in identities_list and subdir in valid_subdirs:
                    path = IDENTITIES_DIR / scope / subdir / filename
                else:
                    failed.append((fid, "scope/subdir invalide"))
                    continue
                if not path.exists() or not path.is_file():
                    failed.append((fid, "fichier introuvable"))
                    continue
                # Supprimer le fichier ET ses metadata éventuelles (.txt, .desc.txt, .example.*)
                stem = path.stem
                parent = path.parent
                to_delete = [path]
                for sibling in parent.iterdir():
                    if sibling.is_file() and sibling.stem.startswith(stem) and sibling != path:
                        # Métadonnées associées : <name>.txt, <name>.desc.txt, <name>.example.*
                        n = sibling.name
                        if (n == f"{stem}.txt" or n == f"{stem}.desc.txt"
                                or n.startswith(f"{stem}.example.")):
                            to_delete.append(sibling)
                for t in to_delete:
                    try:
                        t.unlink()
                    except Exception:
                        pass
                deleted.append(filename)
            except Exception as e:
                failed.append((fid, str(e)))
        msg_parts = []
        if deleted:
            msg_parts.append(f"✅ <b>{len(deleted)}</b> fichier(s) supprimé(s)")
        if failed:
            msg_parts.append(f"❌ <b>{len(failed)}</b> échec(s) : " + ", ".join(f"{fid} ({err})" for fid, err in failed[:3]))
        if bool(failed) and not deleted:
            return _error(" • ".join(msg_parts))
        return _success(" • ".join(msg_parts))

    @app.route("/cloud/pp/<path:filename>")
    def cloud_serve_pp(filename):
        if not is_auth():
            return redirect("/")
        if "/" in filename or "\\" in filename or ".." in filename:
            return "Forbidden", 403
        path = PROFILE_PICS_DIR / filename
        if not path.exists() or not path.is_file():
            return "Not found", 404
        from flask import send_file
        return send_file(str(path))

    @app.route("/upload/pp", methods=["POST"])
    def upload_pp():
        if not is_auth():
            return redirect("/")
        photo = request.files.get("photo")
        if not photo or not photo.filename:
            return _error("Photo manquante")
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in IMAGE_EXTS:
            return _error(f"Format non supporté ({ext})")
        PROFILE_PICS_DIR.mkdir(parents=True, exist_ok=True)
        existing = list(PROFILE_PICS_DIR.glob("*"))
        target = PROFILE_PICS_DIR / f"pp_{len(existing) + 1}{ext}"
        photo.save(str(target))
        return _success(f"✅ Photo de profil ajoutée ({target.name})")

    @app.route("/settings/insta_rapidapi", methods=["POST"])
    def settings_insta_rapidapi():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import save_auth, load_auth
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        key = (request.form.get("rapidapi_key") or "").strip()
        host = (request.form.get("rapidapi_host") or "").strip() or "instagram-scraper-stable-api.p.rapidapi.com"
        if not key or len(key) < 20:
            return _error("❌ Clé RapidAPI invalide (trop courte)")
        # Garder cookies existants si présents
        current = load_auth()
        current["rapidapi_key"] = key
        current["rapidapi_host"] = host
        save_auth(current)
        return _success("✅ Clé RapidAPI sauvegardée. Tu peux maintenant ajouter des comptes "
            "à scraper sans limite de rate.")

    @app.route("/settings/insta_auth_file", methods=["POST"])
    def settings_insta_auth_file():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import save_auth
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        f = request.files.get("cookies_file")
        if not f or not f.filename:
            return _error("❌ Aucun fichier")
        try:
            content = f.read().decode("utf-8", errors="ignore")
        except Exception as e:
            return _error(f"❌ Erreur lecture : {e}")
        # Parser le format Netscape : domain TRUE path TRUE expiry name value (séparés par tab)
        wanted = {"sessionid": None, "ds_user_id": None, "csrftoken": None}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            name = parts[5].strip()
            value = parts[6].strip()
            if name in wanted and value:
                wanted[name] = value
        if not wanted["sessionid"]:
            return _error("❌ Aucun <code>sessionid</code> trouvé dans le fichier. "
                "Assure-toi d'être connecté à Instagram avant d'exporter les cookies.",
                error=True,)
        save_auth({
            "sessionid": wanted["sessionid"],
            "ds_user_id": wanted["ds_user_id"] or "",
            "csrftoken": wanted["csrftoken"] or "",
            "username": "",
        })
        found = [k for k, v in wanted.items() if v]
        return _success(f"✅ Cookies importés ({', '.join(found)}). Tu peux maintenant ajouter des comptes à scraper.")

    @app.route("/settings/insta_auth", methods=["POST"])
    def settings_insta_auth():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import save_auth, load_auth
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        sessionid = (request.form.get("sessionid") or "").strip()
        ds_user_id = (request.form.get("ds_user_id") or "").strip()
        csrftoken = (request.form.get("csrftoken") or "").strip()
        username = (request.form.get("username") or "").strip()
        if not sessionid:
            return _error("❌ sessionid obligatoire")
        save_auth({
            "sessionid": sessionid,
            "ds_user_id": ds_user_id,
            "csrftoken": csrftoken,
            "username": username,
        })
        return _success("✅ Cookies Instagram sauvegardés")

    @app.route("/insta/add_account", methods=["POST"])
    def insta_add_account():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import add_to_watchlist, scrape_profile, is_auth_configured
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        u = (request.form.get("username") or "").strip()
        if not u:
            return _error("❌ username vide")
        added = add_to_watchlist(u)
        # Si pas de cookies, juste ajouter sans scrape
        if not is_auth_configured():
            if added:
                return _success(f"✅ <b>@{u}</b> ajouté à la watchlist. "
                    f"⚠️ Configure tes cookies dans <b>Settings → Cookies Instagram</b> pour pouvoir scraper.",)
            return _error(f"⚠️ @{u} déjà dans la watchlist")
        # Cookies OK -> scrape automatique
        from insta_scraper import _clean_username
        clean = _clean_username(u)
        result = scrape_profile(clean, limit=12)
        if "error" in result:
            if added:
                return _error(f"✅ <b>@{clean}</b> ajouté, mais le scrape a échoué : {result['error']}",
                    error=True,)
            return _error(f"❌ Scrape @{clean} : {result['error']}")
        n = len(result.get("reels", []))
        action = "ajouté + scrapé" if added else "déjà en watchlist, re-scrapé"
        return _success(f"✅ <b>@{clean}</b> {action} ({n} reels). Va voir <b>Instagram → Trends</b>.")

    @app.route("/insta/remove_account", methods=["POST"])
    def insta_remove_account():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import remove_from_watchlist
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        u = (request.form.get("username") or "").strip()
        ok = remove_from_watchlist(u)
        if ok:
            return _success(f"✅ <b>@{u}</b> retiré")
        return _error(f"⚠️ @{u} introuvable")

    @app.route("/insta/scrape", methods=["POST"])
    def insta_scrape():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import scrape_profile
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        u = (request.form.get("username") or "").strip()
        result = scrape_profile(u, limit=12)
        if "error" in result:
            return _error(f"❌ Scrape @{u} : {result['error']}")
        n = len(result.get("reels", []))
        return _success(f"✅ <b>@{u}</b> scrapé : {n} post(s) récupéré(s)")

    @app.route("/insta/scrape_all", methods=["POST"])
    def insta_scrape_all():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import load_watchlist, scrape_profile
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        wl = load_watchlist()
        if not wl:
            return _error("⚠️ Watchlist vide")
        ok_count = 0
        errors = []
        for u in wl:
            result = scrape_profile(u, limit=12)
            if "error" in result:
                errors.append(f"@{u}: {result['error']}")
            else:
                ok_count += 1
        msg = f"✅ {ok_count}/{len(wl)} compte(s) scrapé(s)"
        if errors:
            msg += " — erreurs : " + " | ".join(errors[:3])
        if bool(errors) and ok_count == 0:
            return _error(msg)
        return _success(msg)

    @app.route("/settings/admin_token", methods=["POST"])
    def settings_admin_token():
        if not is_auth():
            return redirect("/")
        token = (request.form.get("token") or "").strip()
        # Validation basique d'un token Discord (format MZ.XX.YY avec base64-like chars)
        if not token or len(token) < 50 or "." not in token:
            return _error("❌ Token invalide (trop court ou format incorrect)")
        ok = _write_env_var("DISCORD_ADMIN_TOKEN", token)
        if not ok:
            return _error("❌ Erreur ecriture .env (permissions ?)")
        # Programmer le redemarrage (systemd relance le service)
        _schedule_restart(2.0)
        return _success("✅ Token sauvegardé. Le bot redémarre dans 2 sec. "
            "Recharge cette page dans ~15 sec pour voir le statut.")

    @app.route("/settings/web_password", methods=["POST"])
    def settings_web_password():
        if not is_auth():
            return redirect("/")
        pwd = (request.form.get("password") or "").strip()
        if len(pwd) < 6:
            return _error("❌ Mot de passe trop court (min 6 caractères)")
        ok = _write_env_var("WEB_UPLOAD_PASSWORD", pwd)
        if not ok:
            return _error("❌ Erreur ecriture .env")
        _schedule_restart(2.0)
        return _success("✅ Mot de passe sauvegardé. Le bot redémarre dans 2 sec. "
            "Tu seras déco — reconnecte-toi avec le nouveau mot de passe.")

    @app.route("/va/reset", methods=["POST"])
    def va_reset():
        if not is_auth():
            return redirect("/")
        uid = (request.form.get("user_id") or "").strip()
        if not uid:
            return _error("❌ user_id manquant")
        users = _load_users()
        if uid not in users:
            return _error(f"❌ VA {uid} introuvable")
        identity = users[uid].get("identity") if isinstance(users[uid], dict) else users[uid]
        del users[uid]
        _save_users(users)
        return _success(f"✅ VA <code>{uid}</code> retiré (était assigné à <b>{identity}</b>). "
            "Son salon Discord n'est PAS supprimé — fais /resetva sur Discord si tu veux le supprimer.")

    @app.route("/va/change_identity", methods=["POST"])
    def va_change_identity():
        if not is_auth():
            return redirect("/")
        uid = (request.form.get("user_id") or "").strip()
        new_identity = (request.form.get("identity") or "").strip().lower()
        if not uid or not new_identity:
            return _error("❌ user_id ou identite manquant")
        if new_identity not in _list_identities():
            return _error(f"❌ Identité <code>{new_identity}</code> introuvable")
        users = _load_users()
        if uid not in users:
            return _error(f"❌ VA {uid} introuvable")

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

        return _success(f"✅ <b>@{username}</b> réassigné : <code>{old_identity}</code> → "
            f"<code>{new_identity}</code>.{moved_msg}")

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
