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
button{width:100%;padding:14px;background:#ef4444;color:#fff;border:0;border-radius:6px;font-size:16px;cursor:pointer;font-weight:600}
button:hover{background:#dc2626}
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
button[type=submit]:hover,.btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(239,68,68,.3)}
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
input:focus,select:focus,textarea:focus{outline:0;border-color:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.15);transition:border-color .15s,box-shadow .15s}

/* Sort options hover */
.ig-sort-opt{transition:background .12s,color .12s,padding-left .12s}
.ig-sort-opt:hover{padding-left:18px}

/* Loading skeleton effect (utile plus tard) */
.skeleton{background:linear-gradient(90deg,#1a1a1a 0%,#2a2a2a 50%,#1a1a1a 100%);background-size:200% 100%;animation:shimmer 1.5s infinite}

/* ============ TOAST NOTIFICATIONS ============ */
.toast-container{position:fixed;top:24px;right:24px;display:flex;flex-direction:column;gap:10px;z-index:9999;pointer-events:none;max-width:420px}
.toast{background:#1a1a1a;border:1px solid #2a2a2a;border-left:4px solid #ef4444;border-radius:10px;padding:14px 18px;color:#fff;font-size:14px;box-shadow:0 12px 32px rgba(0,0,0,.6);display:flex;align-items:flex-start;gap:12px;pointer-events:auto;animation:toastIn .4s cubic-bezier(.16,1,.3,1);min-width:280px;backdrop-filter:blur(10px)}
.toast.success{border-left-color:#00d68f;background:#0f1f17}
.toast.error{border-left-color:#ff4757;background:#1f0f0f}
.toast.info{border-left-color:#ef4444}
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
/* Sidebar large avec groupes pliables + flèches + section labels */
.sidebar{width:240px;background:#0a0a0a;border-right:1px solid #1a1a1a;padding:18px 0;flex-shrink:0;display:flex;flex-direction:column;gap:2px}
.sidebar .section-label{font-size:10px;color:#666;text-transform:uppercase;letter-spacing:1.5px;padding:14px 22px 6px;font-weight:700}
.sidebar .group{display:flex;flex-direction:column;margin:0 10px}
.sidebar .group-head{display:flex;align-items:center;gap:12px;padding:10px 12px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;font-weight:600;width:100%;text-align:left;margin:0;border-radius:8px;transition:all .15s}
.sidebar .group-head:hover{background:#181818;color:#fff}
.sidebar .group-head.active{background:#181818;color:#fff}
.sidebar .group-head svg.lead{width:18px;height:18px;flex-shrink:0;color:#888}
.sidebar .group-head.active svg.lead{color:#ef4444}
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
.sidebar .group .item.active{color:#ef4444;background:#181818}
.sidebar .group .item.active svg{color:#ef4444}
.sidebar .group .item.soon{cursor:not-allowed;opacity:.6}
.sidebar .group .item .badge{padding:2px 6px;font-size:9px;background:#ef4444;color:#fff;border-radius:4px;font-weight:700;letter-spacing:.5px}
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
button[type=submit],.btn{padding:12px 24px;background:#ef4444;color:#fff;border:0;border-radius:6px;font-size:15px;cursor:pointer;font-weight:600;margin-top:16px}
button[type=submit]:hover,.btn:hover{background:#dc2626}
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
.stat .v{font-size:28px;font-weight:700;color:#ef4444}
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
  // Stocke la période sélectionnée pour la réutiliser lors du tri
  window.__igCurrentPeriod = period;
  igApplyPeriodFilter();
}
function igApplyPeriodFilter(){
  var period = window.__igCurrentPeriod || 'week';
  var now = Math.floor(Date.now() / 1000);
  var threshold;
  if(period === 'day') threshold = now - 86400;       // 1 jour
  else if(period === 'week') threshold = now - 604800; // 7 jours
  else threshold = now - 2592000;                      // 30 jours
  var cards = document.querySelectorAll('.reel-card');
  var visible = 0, hidden = 0;
  cards.forEach(function(card){
    var ts = parseInt(card.getAttribute('data-ts')) || 0;
    if(ts === 0 || ts >= threshold){
      card.style.display = '';
      visible++;
    } else {
      card.style.display = 'none';
      hidden++;
    }
  });
  // Affiche un compteur si filtre actif
  var info = document.getElementById('ig-period-info');
  if(info){
    var labels = { 'day': '24 dernières heures', 'week': '7 derniers jours', 'month': '30 derniers jours' };
    info.textContent = visible + ' reel(s) — ' + (labels[period] || '');
  }
}
// Appliquer le filtre par défaut au chargement (week)
window.addEventListener('DOMContentLoaded', function(){
  window.__igCurrentPeriod = 'week';
  setTimeout(igApplyPeriodFilter, 100);
});
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
  // Appliquer le tri sur les cartes
  igApplySort(label);
}
function igApplySort(label){
  // Trouver la grille des reels
  var card = document.querySelector('.reel-card');
  if(!card) return;
  var grid = card.parentElement;
  var cards = Array.prototype.slice.call(grid.querySelectorAll('.reel-card'));
  // Définir la fonction de comparaison selon le label
  var cmp;
  switch(label){
    case 'Newest':
      cmp = function(a,b){ return parseInt(b.dataset.ts||0) - parseInt(a.dataset.ts||0); }; break;
    case 'Oldest':
      cmp = function(a,b){ return parseInt(a.dataset.ts||0) - parseInt(b.dataset.ts||0); }; break;
    case 'Most Views':
      cmp = function(a,b){ return parseInt(b.dataset.views||0) - parseInt(a.dataset.views||0); }; break;
    case 'Least Views':
      cmp = function(a,b){ return parseInt(a.dataset.views||0) - parseInt(b.dataset.views||0); }; break;
    case 'Most Likes':
      cmp = function(a,b){ return parseInt(b.dataset.likes||0) - parseInt(a.dataset.likes||0); }; break;
    case 'Least Likes':
      cmp = function(a,b){ return parseInt(a.dataset.likes||0) - parseInt(b.dataset.likes||0); }; break;
    case 'Most Comments':
      cmp = function(a,b){ return parseInt(b.dataset.comments||0) - parseInt(a.dataset.comments||0); }; break;
    case 'Least Comments':
      cmp = function(a,b){ return parseInt(a.dataset.comments||0) - parseInt(b.dataset.comments||0); }; break;
    case 'Trending':
    default:
      cmp = function(a,b){ return parseInt(b.dataset.trending||0) - parseInt(a.dataset.trending||0); }; break;
  }
  cards.sort(cmp);
  // Réordonner dans le DOM (avec fragment pour la perf)
  var frag = document.createDocumentFragment();
  cards.forEach(function(c){ frag.appendChild(c); });
  grid.appendChild(frag);
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
  // Mettre à jour l'URL pour que le Referer soit conservé après POST
  try{
    if(window.history && window.history.replaceState){
      window.history.replaceState(null, '', '?tab=' + encodeURIComponent(name));
    }
  }catch(e){}
}
</script>
</head><body><div class="layout">
<!-- SIDEBAR : groupes pliables avec flèches -->
<div class="sidebar">

<div class="section-label">Contenu</div>

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

<div class="section-label">Management</div>

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

<div class="section-label">Outils</div>

<div class="group" id="grp-business">
  <button class="group-head" onclick="toggleGroup('business')">
    <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="7" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>
    <span class="label">Business</span>
    <svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="items">
    <button class="item" id="tab-sfs" onclick="showTab('business','sfs','SFS — Planning','Share For Share planifies par identite')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/><polyline points="9 14 11 16 15 12"/></svg>
      SFS Planning
    </button>
    <button class="item" id="tab-revenus" onclick="showTab('business','revenus','💬 Revenus chatteurs','Revenus OnlyFans par chatteur et identité')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
      Revenus
    </button>
    <button class="item" id="tab-depenses" onclick="showTab('business','depenses','Dépenses','Suivi des couts')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="2" y2="22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
      Dépenses
    </button>
    <button class="item" id="tab-paievas" onclick="showTab('business','paievas','💸 Paie VAs','Ce que tu dois payer aux VAs')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
      Paie VAs
    </button>
    <button class="item" id="tab-bilan" onclick="showTab('business','bilan','Bilan','Synthese de ton activite')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" x2="18" y1="20" y2="10"/><line x1="12" x2="12" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="14"/></svg>
      Bilan
    </button>
  </div>
</div>

<div class="section-label">Settings</div>

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
    <div style="width:40px;height:40px;border:2px solid #ec4899;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#ec4899;cursor:pointer">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2"/></svg>
    </div>
  </div>
</div>

<h2 style="margin:0 0 18px;font-size:26px">Trends</h2>

<!-- Sub-tabs style Insta : Mes suivies / Explorer -->
<div style="display:flex;gap:4px;border-bottom:1px solid #2a2a2a;margin-bottom:20px">
  <button class="ig-feed-tab active" onclick="showFeed(this,'suivies')" style="padding:12px 24px;background:none;border:0;color:#fff;cursor:pointer;font-size:14px;font-weight:600;border-bottom:2px solid #ef4444;margin:0">👥 Mes suivies</button>
  <button class="ig-feed-tab" onclick="showFeed(this,'explore')" style="padding:12px 24px;background:none;border:0;color:#888;cursor:pointer;font-size:14px;font-weight:600;border-bottom:2px solid transparent;margin:0">🔍 Explorer</button>
</div>
<script>
function showFeed(btn,name){
  document.querySelectorAll('.ig-feed-tab').forEach(function(b){
    b.style.color='#888';
    b.style.borderBottomColor='transparent';
  });
  btn.style.color='#fff';
  btn.style.borderBottomColor='#ef4444';
  document.querySelectorAll('.ig-feed-content').forEach(function(c){ c.style.display='none'; });
  var c=document.getElementById('feed-'+name);
  if(c) c.style.display='block';
}
</script>

<div id="feed-suivies" class="ig-feed-content">

<!-- Barre de contrôles : Trending / Day / Week / Month / Filters -->
<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:24px">

  <div style="position:relative">
    <div onclick="igToggleSort()" style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:8px 14px;display:flex;align-items:center;gap:8px;cursor:pointer;color:#fff;user-select:none">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M6 12h12M10 18h4"/></svg>
      <span style="font-weight:600;font-size:14px" id="ig-sort-label">Trending</span>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" id="ig-sort-arrow" style="transition:transform .15s"><polyline points="6 9 12 15 18 9"/></svg>
    </div>
    <div id="ig-sort-menu" style="display:none;position:absolute;top:46px;left:0;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:6px;min-width:200px;box-shadow:0 8px 24px rgba(0,0,0,.5);z-index:50">
      <button onclick="igSelectSort(this,'Trending')" class="ig-sort-opt selected" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#fff;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Trending<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Newest')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Newest<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Oldest')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Oldest<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Views')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Views<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Views')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Views<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Likes')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Likes<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Likes')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Likes<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Most Comments')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Most Comments<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
      <button onclick="igSelectSort(this,'Least Comments')" class="ig-sort-opt" style="display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px 14px;background:none;border:0;color:#aaa;cursor:pointer;font-size:14px;border-radius:6px;text-align:left;margin:0;font-weight:500">Least Comments<svg class="check" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" style="display:none"><polyline points="20 6 9 17 4 12"/></svg></button>
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

</div><!-- /feed-suivies -->

<div id="feed-explore" class="ig-feed-content" style="display:none">
<div style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:60px 20px;text-align:center;color:#666">
  <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom:14px"><circle cx="12" cy="12" r="10"/><polyline points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>
  <h3 style="margin:0 0 8px;color:#888">Explorer — Coming soon</h3>
  <p style="margin:0;font-size:14px">Découverte de comptes Instagram populaires que tu ne suis pas encore.<br>Nécessite l'endpoint <code>Explore Feed</code> de RapidAPI (à brancher).</p>
</div>
</div>

</div><!-- /form-igtrends -->

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

<!-- BUSINESS - SFS PLANNING -->
<div class="form-section" id="form-sfs" style="display:none">
{sfs_html}
</div>

<!-- BUSINESS - REVENUS -->
<div class="form-section" id="form-revenus" style="display:none">
{revenus_html}
</div>

<!-- BUSINESS - DÉPENSES -->
<div class="form-section" id="form-depenses" style="display:none">
{depenses_html}
</div>

<!-- BUSINESS - PAIE VAs -->
<div class="form-section" id="form-paievas" style="display:none">
{paievas_html}
</div>

<!-- BUSINESS - BILAN -->
<div class="form-section" id="form-bilan" style="display:none">
{bilan_html}
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
<form method="POST" action="/insta/test_rapidapi" class="box">
<h4 style="margin-top:0">🧪 Tester ma config RapidAPI</h4>
<small>Lance un test avec @instagram pour vérifier que ta clé fonctionne.</small>
<button type="submit" style="background:#00d68f">▶ Tester maintenant</button>
</form>
<form method="POST" action="/insta/reset_rapidapi_host" class="box">
<h4 style="margin-top:0">🔄 Reset host (si tu l'as cassé)</h4>
<small>Réinitialise le host à <code>instagram-scraper-stable-api.p.rapidapi.com</code> (la clé est conservée).</small>
<button type="submit" style="background:#ffb800;color:#000">↻ Reset host par défaut</button>
</form>

<div style="margin:24px 0;border-top:1px solid #2a2a2a;padding-top:20px">
<h4 style="margin:0 0 8px;color:#888">— OU méthode gratuite (rate-limitée) —</h4>
</div>

<!-- Import depuis fichier cookies.txt -->
<form method="POST" action="/settings/insta_auth_file" enctype="multipart/form-data" class="box" style="border:2px dashed #ef4444">
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
            f"<h4 style='margin:0;color:#ef4444;font-size:15px'>👤 {identity}</h4>"
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
                f"<button type='submit' style='padding:6px 10px;background:#ef4444;color:#fff;border:0;border-radius:4px;font-size:12px;cursor:pointer;font-weight:600;margin:0'>OK</button>"
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
            f"style='position:absolute;top:8px;left:8px;width:20px;height:20px;cursor:pointer;z-index:5;accent-color:#ef4444;background:#000;border-radius:4px'>"
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
            f"<h4 style='margin:0;color:#ef4444;font-size:15px'>👤 {ident}</h4>"
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
        "<button type='submit' style='padding:10px 18px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer;font-weight:600'>+ Ajouter</button>"
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
        import datetime
        # Affichage en grille de cards (plus stylé que tableau)
        rows.append("<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-top:14px'>")
        for it in items:
            u = it["username"]
            scraped = it["scraped_at"]
            if scraped:
                dt = datetime.datetime.fromtimestamp(scraped)
                scraped_str = dt.strftime("%d/%m %H:%M")
            else:
                scraped_str = "jamais"
            fname = it["full_name"] or ""
            pic = it.get("profile_pic_url") or ""
            verified_badge = ""
            if it.get("is_verified"):
                verified_badge = "<span style='color:#ef4444;font-size:13px' title='Vérifié'>✓</span>"
            # Avatar : image ou initiale colorée
            if pic:
                avatar_html = (
                    f"<img src='{pic}' loading='lazy' "
                    f"style='width:48px;height:48px;border-radius:50%;object-fit:cover;background:#0f0f0f' "
                    f"onerror=\"this.style.display='none';this.nextElementSibling.style.display='flex'\">"
                    f"<div style='display:none;width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#ef4444,#ec4899);"
                    f"align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:18px'>{u[0].upper()}</div>"
                )
            else:
                avatar_html = (
                    f"<div style='width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#ef4444,#ec4899);"
                    f"display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:18px'>{u[0].upper()}</div>"
                )
            rows.append(
                f"<div class='cloud-card' style='background:#0f0f0f;border:1px solid #2a2a2a;border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:10px'>"
                f"<div style='display:flex;align-items:center;gap:12px'>"
                f"{avatar_html}"
                f"<div style='flex:1;min-width:0'>"
                f"<div style='font-weight:700;font-size:15px;color:#fff;display:flex;align-items:center;gap:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>@{u}{verified_badge}</div>"
                f"<div style='font-size:12px;color:#888;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{fname}</div>"
                f"</div>"
                f"</div>"
                f"<div style='display:flex;gap:14px;font-size:12px;color:#aaa;border-top:1px solid #2a2a2a;padding-top:10px'>"
                f"<div><b style='color:#fff'>{it['followers']:,}</b> followers</div>"
                f"<div><b style='color:#fff'>{it['nb_reels']}</b> reels</div>"
                f"</div>"
                f"<div style='font-size:11px;color:#666'>Dernier scrape : {scraped_str}</div>"
                f"<div style='display:flex;gap:6px;margin-top:auto'>"
                f"<form method='POST' action='/insta/scrape' style='flex:1;margin:0'>"
                f"<input type='hidden' name='username' value='{u}'>"
                f"<button type='submit' style='width:100%;padding:8px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;margin:0'>🔄 Scrape</button>"
                f"</form>"
                f"<form method='POST' action='/insta/remove_account' style='margin:0'>"
                f"<input type='hidden' name='username' value='{u}'>"
                f"<button type='submit' style='padding:8px 12px;background:#d9534f;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;margin:0' data-confirm=\"Retirer @{u} de la watchlist ? Le cache sera conservé.\">×</button>"
                f"</form>"
                f"</div>"
                f"</div>"
            )
        rows.append("</div>")
        rows.append(
            f"<form method='POST' action='/insta/scrape_all' style='margin-top:18px'>"
            f"<button type='submit' style='padding:12px 24px;background:#ef4444;color:#fff;border:0;border-radius:8px;cursor:pointer;font-weight:600' "
            f"data-confirm=\"Scraper tous les comptes de la watchlist ? Compte ~10 secondes par compte.\" data-confirm-title=\"Lancer le scrape global\">🔄 Scraper tous les comptes</button>"
            f"</form>"
        )
    return "".join(rows)


def _format_count(n) -> str:
    """1234 -> 1.2k, 1234567 -> 1.2M"""
    try:
        n = int(n or 0)
    except Exception:
        return "0"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n/1_000:.1f}k".replace(".0k", "k")
    return str(n)


def _time_ago(ts) -> str:
    """Timestamp Unix -> '3 days ago' / 'just now'..."""
    import time
    try:
        ts = int(ts or 0)
    except Exception:
        return ""
    if not ts:
        return ""
    delta = int(time.time()) - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60} min ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    days = delta // 86400
    if days < 30:
        return f"{days} day{'s' if days > 1 else ''} ago"
    if days < 365:
        return f"{days // 30} month{'s' if days // 30 > 1 else ''} ago"
    return f"{days // 365} year{'s' if days // 365 > 1 else ''} ago"


def _render_insta_trends_grid_html() -> str:
    """Grille des reels scrapés depuis tous les comptes en watchlist."""
    try:
        from insta_scraper import get_all_cached_reels, load_watchlist
    except Exception:
        return ""
    reels = get_all_cached_reels()
    wl = load_watchlist()
    # Si watchlist non vide mais cache vide → afficher CTA pour scrape
    if not reels and wl:
        return (
            "<div style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:40px 20px;text-align:center'>"
            f"<h3 style='margin:0 0 8px;color:#fff'>📥 {len(wl)} compte(s) en watchlist — aucun reel scrapé</h3>"
            "<p style='margin:0 0 20px;color:#888;font-size:14px'>Lance un scrape pour récupérer leurs reels.</p>"
            "<form method='POST' action='/insta/scrape_all' style='margin:0'>"
            "<button type='submit' style='padding:14px 28px;background:#ef4444;color:#fff;border:0;border-radius:10px;cursor:pointer;font-weight:700;font-size:15px;margin:0' "
            "data-confirm='Scraper tous les comptes ? Compte ~10 sec par compte.'>"
            "🔄 Scraper tous mes comptes maintenant</button>"
            "</form></div>"
        )
    if not reels:
        return ""

    # Calculer la moyenne de views par compte pour l'indicateur "Nx trending"
    avg_views_by_owner = {}
    counts_by_owner = {}
    for r in reels:
        owner = r.get("_owner", "?")
        v = r.get("views") or 0
        avg_views_by_owner[owner] = avg_views_by_owner.get(owner, 0) + v
        counts_by_owner[owner] = counts_by_owner.get(owner, 0) + 1
    for owner in avg_views_by_owner:
        if counts_by_owner[owner] > 0:
            avg_views_by_owner[owner] = avg_views_by_owner[owner] / counts_by_owner[owner]
    # Trier par views décroissant par défaut
    reels.sort(key=lambda r: (r.get("views") or 0), reverse=True)
    cards = ["<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-top:14px'>"]
    for r in reels[:60]:
        thumb = r.get("thumbnail_url") or ""
        owner = r.get("_owner", "?")
        owner_pic = r.get("_owner_pp") or ""
        url = r.get("url", "#")
        video_url = r.get("video_url") or ""
        views = r.get("views") or 0
        likes = r.get("likes", 0)
        comments = r.get("comments", 0)
        caption = (r.get("caption") or "").replace('"', '&quot;')
        caption_short = caption[:100]
        is_video = r.get("is_video")
        taken_at = r.get("taken_at", 0) or 0
        time_ago = _time_ago(taken_at)
        # Données pour le tri JS
        d_views = int(views or 0)
        d_likes = int(likes or 0)
        d_comments = int(comments or 0)
        # Indicateur trending : combien de fois la moyenne du compte
        avg = avg_views_by_owner.get(owner, 0)
        if avg > 0 and views > 0:
            ratio = views / avg
            trending_x = f"{ratio:.1f}x" if ratio < 10 else f"{int(ratio)}x"
        else:
            trending_x = ""
        trending_html = ""
        if trending_x:
            trending_html = (
                '<div style="display:flex;align-items:center;gap:4px;color:#5cf266;font-weight:700;font-size:13px;margin-bottom:4px">'
                '<svg viewBox="0 0 24 24" width="12" height="12" fill="#5cf266">'
                '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/></svg>'
                f'{trending_x}</div>'
            )
        # Avatar
        avatar = ""
        if owner_pic:
            avatar = f"<img src='{owner_pic}' style='width:22px;height:22px;border-radius:50%;object-fit:cover'>"
        # Video preview au hover
        video_html = ""
        if is_video and video_url:
            video_html = (
                f"<video class='reel-video' src='{video_url}' muted loop preload='none' "
                f"style='position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .25s'></video>"
            )
        cards.append(f"""
<div class="reel-card cloud-card" data-ts="{taken_at}" data-views="{d_views}" data-likes="{d_likes}" data-comments="{d_comments}" data-trending="{int((d_views/max(avg,1))*100) if avg > 0 else 0}" style="background:#0f0f0f;border:1px solid #2a2a2a;border-radius:14px;overflow:hidden;display:flex;flex-direction:column">
  <div class="reel-media" style="position:relative;width:100%;aspect-ratio:9/16;background:#000;cursor:pointer;overflow:hidden"
       onmouseenter='var v=this.querySelector(".reel-video");if(v){{v.play();v.style.opacity=1}}'
       onmouseleave='var v=this.querySelector(".reel-video");if(v){{v.pause();v.style.opacity=0}}'
       onclick='window.open("{url}","_blank")'>
    <img src="{thumb}" loading="lazy" style="width:100%;height:100%;object-fit:cover">
    {video_html}
    <!-- Top: time ago left, actions right -->
    <div style="position:absolute;top:10px;left:10px;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);color:#fff;font-size:11px;font-weight:600;padding:5px 10px;border-radius:14px;z-index:2">{time_ago}</div>
    <div style="position:absolute;top:10px;right:10px;display:flex;gap:6px;z-index:2" onclick="event.stopPropagation()">
      <button onclick='this.querySelector("svg").style.color = (this.querySelector("svg").style.color === "rgb(255, 71, 87)" ? "#fff" : "#ff4757")' title="Mute" style="width:28px;height:28px;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);border:0;border-radius:50%;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;margin:0">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>
      </button>
      <a href="{video_url or url}" target="_blank" download title="Télécharger" style="width:28px;height:28px;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);border-radius:50%;color:#fff;display:flex;align-items:center;justify-content:center;text-decoration:none">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      </a>
      <button onclick='navigator.clipboard.writeText("{url}");showToast("Lien copié","success")' title="Partager" style="width:28px;height:28px;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);border:0;border-radius:50%;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;margin:0">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
      </button>
      <button onclick='openLightbox("{video_url or thumb}", {"true" if is_video else "false"}, "@{owner}")' title="Plein écran" style="width:28px;height:28px;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);border:0;border-radius:50%;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;margin:0">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
      </button>
    </div>
    <!-- Bottom: caption overlay + stats right -->
    <div style="position:absolute;bottom:50px;left:10px;right:80px;color:#fff;font-size:12px;line-height:1.3;text-shadow:0 1px 3px rgba(0,0,0,.9);max-height:60px;overflow:hidden;z-index:1;pointer-events:none">{caption_short}</div>
    <div style="position:absolute;bottom:50px;right:10px;display:flex;flex-direction:column;gap:8px;align-items:flex-end;color:#fff;font-size:13px;font-weight:700;text-shadow:0 1px 3px rgba(0,0,0,.9);z-index:1;pointer-events:none">
      <div style="display:flex;align-items:center;gap:4px"><svg viewBox="0 0 24 24" width="14" height="14" fill="#fff"><polygon points="5 3 19 12 5 21"/></svg>{_format_count(views)}</div>
      <div style="display:flex;align-items:center;gap:4px"><svg viewBox="0 0 24 24" width="14" height="14" fill="#fff"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>{_format_count(likes)}</div>
      <div style="display:flex;align-items:center;gap:4px"><svg viewBox="0 0 24 24" width="14" height="14" fill="#fff"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>{_format_count(comments)}</div>
    </div>
    <!-- Trending indicator + username at bottom -->
    <div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(to top,rgba(0,0,0,.85),transparent);padding:8px 10px;z-index:2">
      {trending_html}
      <a href="https://www.instagram.com/{owner}/" target="_blank" onclick="event.stopPropagation()" style="display:flex;align-items:center;gap:6px;color:#fff;text-decoration:none;font-size:12px;font-weight:600">
        {avatar}@{owner}
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="margin-left:auto"><polyline points="9 18 15 12 9 6"/></svg>
      </a>
    </div>
  </div>
</div>""")
    cards.append("</div>")
    cards.append(f"<div style='margin-top:18px;display:flex;justify-content:space-between;align-items:center'>"
                 f"<small id='ig-period-info'>{len(reels)} reel(s) au total</small>"
                 f"<form method='POST' action='/insta/scrape_all' style='margin:0'>"
                 f"<button type='submit' style='padding:8px 18px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;margin:0' "
                 f"data-confirm='Rafraîchir tous les comptes ?'>"
                 f"🔄 Rafraîchir</button></form></div>")
    return "".join(cards)


def _identity_avatar_path(identity: str) -> Path:
    """Retourne le chemin de l'avatar d'une identité (s'il existe), None sinon."""
    safe = identity.lower().strip()
    base = IDENTITIES_DIR / safe
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = base / f"avatar.{ext}"
        if p.exists():
            return p
    return None


def _identity_avatar_url(identity: str) -> str:
    """URL publique de l'avatar (ou string vide si pas d'avatar)."""
    p = _identity_avatar_path(identity)
    if p:
        return f"/identity/avatar/{identity.lower().strip()}"
    return ""


def _identity_avatar_html(identity: str, size: int = 28) -> str:
    """Petit HTML : <img> si avatar, sinon initiale colorée."""
    url = _identity_avatar_url(identity)
    if url:
        return (
            f"<img src='{url}' style='width:{size}px;height:{size}px;border-radius:50%;"
            f"object-fit:cover;border:1px solid #2a2a2a;flex-shrink:0'>"
        )
    init = (identity[0] if identity else "?").upper()
    return (
        f"<div style='width:{size}px;height:{size}px;border-radius:50%;"
        f"background:linear-gradient(135deg,#ef4444,#ec4899);display:flex;"
        f"align-items:center;justify-content:center;font-weight:700;color:#fff;"
        f"font-size:{int(size*0.45)}px;flex-shrink:0'>{init}</div>"
    )


def _render_identity_avatars_section() -> str:
    """Section UI pour uploader les avatars de chaque identité."""
    identities = _list_identities()
    if not identities:
        return ""
    rows = ["<div class='box'><h4 style='margin-top:0'>🖼️ Avatars des identités</h4>"]
    rows.append("<small>Upload une photo de profil pour chaque identité (utilisée dans SFS, VAs, etc.)</small>")
    rows.append("<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:14px'>")
    for ident in identities:
        avatar = _identity_avatar_html(ident, size=64)
        rows.append(
            f"<div style='background:#0f0f0f;border:1px solid #2a2a2a;border-radius:10px;padding:12px;display:flex;flex-direction:column;align-items:center;gap:10px'>"
            f"{avatar}"
            f"<div style='font-weight:700;font-size:14px'>{ident}</div>"
            f"<form method='POST' action='/identity/upload_avatar' enctype='multipart/form-data' style='width:100%;margin:0'>"
            f"<input type='hidden' name='identity' value='{ident}'>"
            f"<input type='file' name='avatar' accept='image/*' required style='width:100%;padding:6px;background:#1a1a1a;border:1px solid #333;color:#fff;border-radius:4px;font-size:12px'>"
            f"<button type='submit' style='width:100%;padding:8px;background:#ef4444;color:#fff;border:0;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;margin-top:8px'>Upload</button>"
            f"</form>"
            f"</div>"
        )
    rows.append("</div></div>")
    return "".join(rows)


def _render_sfs_html() -> str:
    try:
        from business import list_sfs, sfs_stats, load_identity_platforms, identities_for_platform, PLATFORMS
    except Exception as e:
        return f"<p style='color:#f99'>Module business indispo : {e}</p>"
    import datetime, calendar as cal
    import json as _json
    today = datetime.date.today()
    today_iso = today.isoformat()
    items = list_sfs()
    stats = sfs_stats()
    platforms_map = load_identity_platforms()
    platform_idents = {p: identities_for_platform(p) for p in PLATFORMS}
    platform_idents_json = _json.dumps(platform_idents)

    # Lire le mois depuis l'URL (?sfs_month=YYYY-MM) ou prendre le mois courant
    from flask import request as flask_request
    month_param = flask_request.args.get("sfs_month", "")
    year = today.year
    month = today.month
    if month_param:
        try:
            parts = month_param.split("-")
            year = int(parts[0])
            month = int(parts[1])
            if month < 1 or month > 12:
                year, month = today.year, today.month
        except Exception:
            year, month = today.year, today.month

    # Calculer mois précédent et suivant
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    next_year = year if month < 12 else year + 1
    next_month = month + 1 if month < 12 else 1

    # Construire la date du 1er du mois affiché pour le nom
    first_day, days_in_month = cal.monthrange(year, month)
    displayed = datetime.date(year, month, 1)
    # Nom du mois en français
    fr_months = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
                 "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    month_name = f"{fr_months[month-1]} {year}"

    # SFS par date + par plateforme pour le rendu
    sfs_by_date_platform = {}  # {date: {OF: [...], MYM: [...]}}
    for it in items:
        d = it.get("date", "")
        p = it.get("platform", "OF")
        if d:
            sfs_by_date_platform.setdefault(d, {}).setdefault(p, []).append(it)
    # Aussi tous les SFS par date pour le modal
    sfs_by_date_all_json = _json.dumps({
        d: [
            {
                "id": x.get("id"),
                "identity": x.get("identity", ""),
                "partner": x.get("partner", ""),
                "time": x.get("time", ""),
                "platform": x.get("platform", "OF"),
                "status": x.get("status", "scheduled"),
                "notes": x.get("notes", ""),
                "done": x.get("done", False),
            }
            for x in v for k, items_list in sfs_by_date_platform.get(d, {}).items() for x_ in [None] if x in items_list
        ] for d, v in {d: sum(p.values(), []) for d, p in sfs_by_date_platform.items()}.items()
    })
    # Simpler: just send {date: [items]}
    sfs_by_date_simple = {}
    for d, plats in sfs_by_date_platform.items():
        merged = []
        for p_items in plats.values():
            merged.extend(p_items)
        sfs_by_date_simple[d] = [
            {
                "id": x.get("id"),
                "identity": x.get("identity", ""),
                "partner": x.get("partner", ""),
                "time": x.get("time", ""),
                "platform": x.get("platform", "OF"),
                "status": x.get("status", "scheduled"),
                "notes": x.get("notes", ""),
                "done": x.get("done", False),
            }
            for x in merged
        ]
    sfs_by_date_json = _json.dumps(sfs_by_date_simple)

    rows = []
    # Stats
    rows.append(
        "<div class='stat-grid' style='margin-bottom:16px'>"
        f"<div class='stat'><div class='v'>{stats['total']}</div><div class='l'>Total SFS</div></div>"
        f"<div class='stat'><div class='v'>{stats['today']}</div><div class='l'>Aujourd'hui</div></div>"
        f"<div class='stat'><div class='v' style='color:#ffb800'>{stats['pending']}</div><div class='l'>À faire</div></div>"
        f"<div class='stat'><div class='v' style='color:#00d68f'>{stats['done']}</div><div class='l'>Faits</div></div>"
        "</div>"
    )

    # === PLATFORM TABS EN HAUT ===
    rows.append(
        "<div style='display:flex;gap:0;border-bottom:2px solid #2a2a2a;margin-bottom:16px'>"
        "<button class='sfs-platform-tab active' data-platform='OF' onclick='switchSfsPlatform(this,\"OF\")' "
        "style='flex:1;padding:14px;background:none;border:0;color:#fff;cursor:pointer;font-size:16px;font-weight:700;border-bottom:3px solid #ef4444;margin:0'>"
        "OnlyFans (OF)</button>"
        "<button class='sfs-platform-tab' data-platform='MYM' onclick='switchSfsPlatform(this,\"MYM\")' "
        "style='flex:1;padding:14px;background:none;border:0;color:#888;cursor:pointer;font-size:16px;font-weight:700;border-bottom:3px solid transparent;margin:0'>"
        "MYM</button>"
        "</div>"
    )

    # === CALENDRIER ===
    rows.append("<div class='box'>")
    # Header du calendrier avec navigation
    today_link = f"?tab=sfs&sfs_month={today.year:04d}-{today.month:02d}"
    prev_link = f"?tab=sfs&sfs_month={prev_year:04d}-{prev_month:02d}"
    next_link = f"?tab=sfs&sfs_month={next_year:04d}-{next_month:02d}"
    is_current_month = (year == today.year and month == today.month)
    today_btn_html = ""
    if not is_current_month:
        today_btn_html = (
            f"<a href='{today_link}' style='padding:6px 12px;background:#ef4444;color:#fff;"
            f"border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;margin-right:6px'>Aujourd'hui</a>"
        )
    # Header type "planning OF" : flèches + mois à gauche, bouton today à droite
    rows.append("<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;flex-wrap:wrap;gap:10px'>")
    rows.append("<div style='display:flex;align-items:center;gap:4px'>")
    rows.append(
        f"<a href='{prev_link}' title='Mois précédent' "
        f"style='width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:transparent;color:#aaa;border-radius:6px;text-decoration:none;font-size:18px;line-height:1' "
        f"onmouseover='this.style.background=\"#1a1a1a\";this.style.color=\"#fff\"' onmouseout='this.style.background=\"transparent\";this.style.color=\"#aaa\"'>‹</a>"
    )
    rows.append(
        f"<a href='{next_link}' title='Mois suivant' "
        f"style='width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:transparent;color:#aaa;border-radius:6px;text-decoration:none;font-size:18px;line-height:1' "
        f"onmouseover='this.style.background=\"#1a1a1a\";this.style.color=\"#fff\"' onmouseout='this.style.background=\"transparent\";this.style.color=\"#aaa\"'>›</a>"
    )
    rows.append(f"<h3 style='margin:0 0 0 12px;font-size:17px;font-weight:600;color:#fff;text-transform:lowercase'>{month_name}</h3>")
    rows.append("</div>")
    if not is_current_month:
        rows.append(
            f"<a href='{today_link}' style='padding:6px 14px;background:#ef4444;color:#fff;"
            f"border-radius:6px;text-decoration:none;font-size:13px;font-weight:600'>Aujourd'hui</a>"
        )
    rows.append("</div>")

    # Header des jours de la semaine (juste lettres comme L M M J V S D)
    rows.append("<div style='display:grid;grid-template-columns:repeat(7,1fr)'>")
    for dn in ["L", "M", "M", "J", "V", "S", "D"]:
        rows.append(f"<div style='font-size:11px;color:#888;font-weight:600;padding:8px 12px;text-transform:uppercase'>{dn}</div>")
    rows.append("</div>")

    # Grille principale du calendrier (sans gap, bordures intégrées)
    rows.append("<div style='display:grid;grid-template-columns:repeat(7,1fr);border-top:1px solid #1a1a1a;border-left:1px solid #1a1a1a;border-radius:8px;overflow:hidden'>")

    # Jours du mois précédent (grisés - style référence)
    if first_day > 0:
        _, days_prev = cal.monthrange(prev_year, prev_month)
        prev_days_to_show = list(range(days_prev - first_day + 1, days_prev + 1))
        for d in prev_days_to_show:
            rows.append(
                f"<div style='min-height:120px;background:transparent;border-right:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:10px 12px;cursor:default'>"
                f"<div style='font-size:14px;color:#444;font-weight:500'>{d}</div>"
                f"</div>"
            )
    for d in range(1, days_in_month + 1):
        date_iso = f"{year:04d}-{month:02d}-{d:02d}"
        is_today = (date_iso == today_iso)
        # Compter par plateforme
        day_data = sfs_by_date_platform.get(date_iso, {})
        nb_of = len(day_data.get("OF", []))
        nb_mym = len(day_data.get("MYM", []))
        # Style "planning OF" : cellule rectangulaire, num top-left, événements en barres bas
        cell_bg = "#1f1410" if is_today else "transparent"
        weight = 700 if is_today else 500
        # Si c'est le 1er du mois, afficher aussi le nom du mois (style référence "mai 1")
        day_label_html = f"<span style='color:#888;font-size:12px;margin-right:4px'>{fr_months[month-1][:3].lower()}</span>{d}" if d == 1 else str(d)
        rows.append(
            f"<div class='sfs-day' data-date='{date_iso}' data-of='{nb_of}' data-mym='{nb_mym}' "
            f"onclick='openSfsModal(\"{date_iso}\")' "
            f"style='min-height:120px;background:{cell_bg};border-right:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:10px 12px;cursor:pointer;transition:background .15s;display:flex;flex-direction:column;position:relative' "
            f"onmouseover='this.style.background=\"#15100d\"' onmouseout='this.style.background=\"{cell_bg}\"'>"
            f"<div style='font-size:14px;font-weight:{weight};color:#fff'>{day_label_html}</div>"
            f"<div class='sfs-day-bars' style='margin-top:auto;display:flex;flex-direction:column;gap:3px'></div>"
            f"</div>"
        )
    # Jours du mois suivant (grisés)
    total_cells_used = first_day + days_in_month
    total_weeks = (total_cells_used + 6) // 7
    next_days_to_show = list(range(1, total_weeks * 7 - total_cells_used + 1))
    for d in next_days_to_show:
        rows.append(
            f"<div style='min-height:120px;background:transparent;border-right:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:10px 12px;cursor:default'>"
            f"<div style='font-size:14px;color:#444;font-weight:500'>{d}</div>"
            f"</div>"
        )
    rows.append("</div></div>")

    # JS pour platform switching + modal
    # Map des avatars pour le JS
    avatar_map = {ident: _identity_avatar_url(ident) for ident in _list_identities()}
    avatar_map_json = _json.dumps(avatar_map)
    rows.append(f"""
<script>
window.__sfsData = {sfs_by_date_json};
window.__platformIdents = {platform_idents_json};
window.__identityAvatars = {avatar_map_json};
window.__currentSfsPlatform = 'OF';
function identityAvatarHtml(ident, size){{
  var url = window.__identityAvatars[ident];
  if(url){{
    return '<img src="' + url + '" style="width:' + size + 'px;height:' + size + 'px;border-radius:50%;object-fit:cover;border:1px solid #2a2a2a;flex-shrink:0">';
  }}
  var init = (ident && ident.length ? ident[0] : '?').toUpperCase();
  return '<div style="width:' + size + 'px;height:' + size + 'px;border-radius:50%;background:linear-gradient(135deg,#ef4444,#ec4899);display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:' + Math.round(size*0.45) + 'px;flex-shrink:0">' + init + '</div>';
}}

function switchSfsPlatform(btn, platform){{
  window.__currentSfsPlatform = platform;
  document.querySelectorAll('.sfs-platform-tab').forEach(function(b){{
    b.style.color = '#888';
    b.style.borderBottomColor = 'transparent';
  }});
  btn.style.color = '#fff';
  btn.style.borderBottomColor = (platform === 'OF') ? '#ef4444' : '#ec4899';
  refreshSfsCalendar();
}}

function refreshSfsCalendar(){{
  var platform = window.__currentSfsPlatform;
  document.querySelectorAll('.sfs-day').forEach(function(day){{
    // Vider les anciennes barres (le sélecteur a changé : .sfs-day-bars maintenant)
    var barsEl = day.querySelector('.sfs-day-bars') || day.querySelector('.sfs-day-badges');
    if(barsEl) barsEl.innerHTML = '';
    var date = day.dataset.date;
    var allDay = window.__sfsData[date] || [];
    var filtered = allDay.filter(function(x){{ return x.platform === platform; }});
    if(filtered.length === 0 || !barsEl) return;
    var nb_sched = filtered.filter(function(x){{ return x.status === 'scheduled'; }}).length;
    var nb_prog = filtered.filter(function(x){{ return x.status === 'to_program'; }}).length;
    // Barre style référence (orange/rouge) au bas avec un nombre
    if(nb_sched){{
      var b = document.createElement('div');
      b.style.cssText = 'background:#ef4444;color:#fff;font-size:10px;padding:3px 8px;border-radius:4px;font-weight:700;text-align:center;width:100%;box-sizing:border-box';
      b.textContent = nb_sched;
      barsEl.appendChild(b);
    }}
    if(nb_prog){{
      var b = document.createElement('div');
      b.style.cssText = 'background:#f59e0b;color:#000;font-size:10px;padding:3px 8px;border-radius:4px;font-weight:700;text-align:center;width:100%;box-sizing:border-box';
      b.textContent = nb_prog;
      barsEl.appendChild(b);
    }}
  }});
  // Filtrer aussi la liste en bas
  document.querySelectorAll('.sfs-row').forEach(function(tr){{
    if(tr.dataset.platform === platform) tr.style.display = '';
    else tr.style.display = 'none';
  }});
}}

function openSfsModal(date){{
  var platform = window.__currentSfsPlatform;
  var modal = document.getElementById('sfs-modal');
  document.getElementById('sfs-modal-title').innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:8px"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/><polyline points="9 14 11 16 15 12"/></svg>SFS du ' + date + ' — ' + platform;
  document.getElementById('sfs-modal-date').value = date;
  document.getElementById('sfs-modal-platform-display').textContent = platform;
  // Hidden input pour la plateforme
  var hidden = document.getElementById('sfs-modal-platform');
  if(hidden) hidden.value = platform;
  // Populer le select des identités selon la plateforme
  var idents = window.__platformIdents[platform] || [];
  var select = document.getElementById('sfs-modal-identity');
  select.innerHTML = idents.length
    ? idents.map(function(i){{ return '<option value="' + i + '">' + i + '</option>'; }}).join('')
    : '<option value="">(aucune identité sur ' + platform + ')</option>';
  // Afficher les SFS existants ce jour pour cette plateforme
  var existing = (window.__sfsData[date] || []).filter(function(x){{ return x.platform === platform; }});
  var existingHtml = '';
  if(existing.length){{
    existingHtml = '<h4 style="margin:14px 0 8px">SFS déjà planifiés ce jour</h4><div style="display:flex;flex-direction:column;gap:6px">';
    existing.forEach(function(x){{
      var statusBadge = x.status === 'scheduled'
        ? '<span style="background:#ef4444;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700">SCHEDULED</span>'
        : '<span style="background:#ffb800;color:#000;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700">TO PROGRAM</span>';
      existingHtml += '<div style="background:#0f0f0f;border:1px solid #2a2a2a;border-radius:8px;padding:10px;display:flex;justify-content:space-between;align-items:center;gap:10px">'
        + '<div style="display:flex;align-items:center;gap:10px">' + identityAvatarHtml(x.identity, 32)
        + '<div><b>' + x.identity + '</b> × @' + x.partner + ' <span style="color:#888">à ' + x.time + '</span></div></div>'
        + '<div>' + statusBadge + '</div>'
        + '</div>';
    }});
    existingHtml += '</div>';
  }}
  document.getElementById('sfs-modal-existing').innerHTML = existingHtml;
  modal.classList.add('show');
}}
function closeSfsModal(){{
  document.getElementById('sfs-modal').classList.remove('show');
}}
// Init calendrier au chargement
window.addEventListener('DOMContentLoaded', function(){{
  setTimeout(refreshSfsCalendar, 50);
}});
</script>

<!-- Modal d'ajout SFS -->
<div id='sfs-modal' class='confirm-overlay' onclick='closeSfsModal()'>
  <div class='confirm-box' style='max-width:520px;width:90%' onclick='event.stopPropagation()'>
    <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:14px'>
      <h3 id='sfs-modal-title' style='margin:0'>📅 SFS</h3>
      <button onclick='closeSfsModal()' style='background:none;border:0;color:#888;font-size:20px;cursor:pointer;margin:0;padding:0'>×</button>
    </div>
    <div id='sfs-modal-existing'></div>
    <h4 style='margin:18px 0 8px'>➕ Nouvel SFS</h4>
    <form method='POST' action='/business/sfs/add'>
      <input type='hidden' name='date' id='sfs-modal-date'>
      <input type='hidden' name='platform' id='sfs-modal-platform' value='OF'>
      <div style='display:grid;grid-template-columns:1fr 1fr;gap:10px'>
        <div>
          <label>Identité (sur <span id='sfs-modal-platform-display'>OF</span>)</label>
          <select name='identity' id='sfs-modal-identity' required></select>
        </div>
        <div>
          <label>Heure</label>
          <input type='time' name='time' value='19:00' required>
        </div>
        <div>
          <label>Partenaire @</label>
          <input type='text' name='partner' placeholder='partner_username' required>
        </div>
        <div>
          <label>Statut</label>
          <select name='status'>
            <option value='scheduled'>✓ Scheduled</option>
            <option value='to_program'>⚙ To program</option>
          </select>
        </div>
      </div>
      <label>Notes (optionnel)</label>
      <input type='text' name='notes' placeholder='Story exchange, post tag...' maxlength='200'>
      <div style='display:flex;gap:8px;margin-top:14px;justify-content:flex-end'>
        <button type='button' class='btn-cancel' onclick='closeSfsModal()' style='padding:10px 22px;background:#2a2a2a;color:#fff;border:0;border-radius:8px;font-weight:600;cursor:pointer;margin:0'>Annuler</button>
        <button type='submit' style='padding:10px 22px;background:#ef4444;color:#fff;border:0;border-radius:8px;font-weight:600;cursor:pointer;margin:0'>Ajouter</button>
      </div>
    </form>
  </div>
</div>
""")

    # === LISTE DES SFS (filtré par platform aussi) ===
    if items:
        rows.append("<div class='box'><h4 style='margin-top:0'>📋 Tous les SFS</h4>")
        rows.append(
            "<table style='width:100%;border-collapse:collapse'>"
            "<tr style='background:#1a1a1a'>"
            "<th style='padding:8px;text-align:center'>État</th>"
            "<th style='padding:8px;text-align:left'>Date & H</th>"
            "<th style='padding:8px;text-align:left'>Plateforme</th>"
            "<th style='padding:8px;text-align:left'>Identité</th>"
            "<th style='padding:8px;text-align:left'>Partenaire</th>"
            "<th style='padding:8px;text-align:left'>Statut</th>"
            "<th style='padding:8px;text-align:left'>Notes</th>"
            "<th style='padding:8px'></th>"
            "</tr>"
        )
        for it in items:
            done = it.get("done", False)
            check = "✅" if done else "⏳"
            color_style = "opacity:.5;text-decoration:line-through" if done else ""
            status = it.get("status", "scheduled")
            status_badge = (
                "<span style='background:#ef4444;color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700'>SCHEDULED</span>"
                if status == "scheduled" else
                "<span style='background:#ffb800;color:#000;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700'>TO PROGRAM</span>"
            )
            platform = it.get("platform", "OF")
            platform_color = "#ef4444" if platform == "OF" else "#ec4899"
            ident_avatar = _identity_avatar_html(it.get("identity", ""), size=26)
            rows.append(
                f"<tr class='sfs-row' data-platform='{platform}' style='border-bottom:1px solid #2a2a2a;{color_style}'>"
                f"<td style='padding:8px;text-align:center'>"
                f"<form method='POST' action='/business/sfs/toggle' style='display:inline;margin:0'>"
                f"<input type='hidden' name='id' value='{it['id']}'>"
                f"<button type='submit' style='background:none;border:0;cursor:pointer;font-size:16px;margin:0;padding:0'>{check}</button>"
                f"</form></td>"
                f"<td style='padding:8px;font-size:13px'>{it.get('date','')} <b>{it.get('time','')}</b></td>"
                f"<td style='padding:8px'><span style='background:{platform_color};color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700'>{platform}</span></td>"
                f"<td style='padding:8px'><div style='display:flex;align-items:center;gap:8px'>{ident_avatar}<b>{it.get('identity','')}</b></div></td>"
                f"<td style='padding:8px'>@{it.get('partner','')}</td>"
                f"<td style='padding:8px'>{status_badge}</td>"
                f"<td style='padding:8px;font-size:13px;color:#aaa'>{it.get('notes','')}</td>"
                f"<td style='padding:8px;text-align:right'>"
                f"<form method='POST' action='/business/sfs/remove' style='display:inline;margin:0'>"
                f"<input type='hidden' name='id' value='{it['id']}'>"
                f"<button type='submit' class='danger-btn' data-confirm='Supprimer ce SFS ?'>×</button>"
                f"</form></td></tr>"
            )
        rows.append("</table></div>")

    # === SECTION AVATARS ===
    rows.append(_render_identity_avatars_section())

    # === CONFIG des plateformes ===
    rows.append("<div class='box'>")
    rows.append("<h4 style='margin-top:0'>⚙️ Mes identités par plateforme</h4>")
    rows.append("<small>Active/désactive les plateformes pour chaque identité (affecte ce qu'on peut sélectionner dans le form).</small>")
    rows.append("<form method='POST' action='/business/identity_platforms' style='margin-top:14px'>")
    rows.append("<table style='width:100%;border-collapse:collapse'>")
    rows.append("<tr style='background:#1a1a1a'><th style='padding:8px;text-align:left'>Identité</th>")
    for p in PLATFORMS:
        rows.append(f"<th style='padding:8px;text-align:center'>{p}</th>")
    rows.append("</tr>")
    all_idents = set(platforms_map.keys()) | set(_list_identities())
    for ident in sorted(all_idents):
        rows.append(f"<tr style='border-bottom:1px solid #2a2a2a'><td style='padding:8px;font-weight:600'>{ident}</td>")
        active_plats = platforms_map.get(ident, [])
        for p in PLATFORMS:
            checked = "checked" if p in active_plats else ""
            rows.append(
                f"<td style='padding:8px;text-align:center'>"
                f"<input type='checkbox' name='platform_{ident}' value='{p}' {checked} style='width:18px;height:18px;accent-color:#ef4444'>"
                f"</td>"
            )
        rows.append("</tr>")
    rows.append("</table>")
    rows.append("<button type='submit' style='margin-top:14px'>Sauver la config plateformes</button>")
    rows.append("</form></div>")

    return "".join(rows)


def _render_depenses_html() -> str:
    try:
        from business import list_expenses, expense_stats, CATEGORIES
    except Exception as e:
        return f"<p style='color:#f99'>Module business indispo : {e}</p>"
    cat_opts = "".join(f"<option value='{c}'>{c}</option>" for c in CATEGORIES)
    import datetime
    today = datetime.date.today().isoformat()
    items = list_expenses()
    rows = []
    rows.append(
        f"<form method='POST' action='/business/expense/add' class='box'>"
        f"<h4 style='margin-top:0'>➕ Nouvelle dépense</h4>"
        f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px'>"
        f"<div><label>Catégorie</label><select name='category' required>{cat_opts}</select></div>"
        f"<div><label>Montant (€)</label><input type='number' name='amount' step='0.01' min='0' value='29.99' required></div>"
        f"<div><label>Date</label><input type='date' name='date' value='{today}' required></div>"
        f"<div><label style='display:flex;align-items:center;gap:6px;margin-top:24px'><input type='checkbox' name='recurring' style='width:auto;margin:0'> Mensuel récurrent</label></div>"
        f"</div>"
        f"<label>Description</label>"
        f"<input type='text' name='description' placeholder='RapidAPI PRO, VPS Hostinger...' required maxlength='200'>"
        f"<button type='submit'>Ajouter</button>"
        f"</form>"
    )
    if not items:
        rows.append("<p style='color:#888'>Aucune dépense enregistrée.</p>")
    else:
        rows.append("<div class='box'>")
        rows.append(
            "<table style='width:100%;border-collapse:collapse'>"
            "<tr style='background:#1a1a1a'>"
            "<th style='padding:8px;text-align:left'>Date</th>"
            "<th style='padding:8px;text-align:left'>Catégorie</th>"
            "<th style='padding:8px;text-align:left'>Description</th>"
            "<th style='padding:8px;text-align:right'>Montant</th>"
            "<th style='padding:8px;text-align:center'>Récurrent</th>"
            "<th style='padding:8px;text-align:right'></th>"
            "</tr>"
        )
        for it in items:
            rec_icon = "🔄" if it.get("recurring") else ""
            rows.append(
                f"<tr style='border-bottom:1px solid #2a2a2a'>"
                f"<td style='padding:8px;font-size:13px'>{it.get('date','')}</td>"
                f"<td style='padding:8px;font-size:13px'>{it.get('category','')}</td>"
                f"<td style='padding:8px'>{it.get('description','')}</td>"
                f"<td style='padding:8px;text-align:right;font-weight:600;color:#f99'>-{it.get('amount',0):.2f} €</td>"
                f"<td style='padding:8px;text-align:center;font-size:18px'>{rec_icon}</td>"
                f"<td style='padding:8px;text-align:right'>"
                f"<form method='POST' action='/business/expense/remove' style='display:inline;margin:0'>"
                f"<input type='hidden' name='id' value='{it['id']}'>"
                f"<button type='submit' class='danger-btn' data-confirm='Supprimer cette dépense ?'>×</button>"
                f"</form></td></tr>"
            )
        rows.append("</table></div>")
    return "".join(rows)


def _render_revenus_html() -> str:
    try:
        from business import list_revenues, revenue_stats
    except Exception as e:
        return f"<p style='color:#f99'>Module business indispo : {e}</p>"
    identities = _list_identities()
    ident_opts = "".join(f"<option value='{i}'>{i}</option>" for i in identities)
    if not ident_opts:
        ident_opts = "<option value=''>(aucune identité)</option>"
    import datetime
    today = datetime.date.today().isoformat()
    items = list_revenues()
    stats = revenue_stats()
    rows = []
    rows.append(
        "<div class='stat-grid' style='margin-bottom:16px'>"
        f"<div class='stat'><div class='v' style='color:#00d68f'>+{stats['total_this_month']:.0f}€</div><div class='l'>Revenus ce mois</div></div>"
        f"<div class='stat'><div class='v' style='color:#00d68f'>+{stats['total_all_time']:.0f}€</div><div class='l'>Total revenus</div></div>"
        f"<div class='stat'><div class='v'>{len(stats.get('by_chatter', {}))}</div><div class='l'>Chatteurs uniques</div></div>"
        f"<div class='stat'><div class='v'>{len(stats.get('by_identity', {}))}</div><div class='l'>Identités sources</div></div>"
        "</div>"
    )
    rows.append(
        f"<form method='POST' action='/business/revenue/add' class='box'>"
        f"<h4 style='margin-top:0'>➕ Nouveau revenu</h4>"
        f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px'>"
        f"<div><label>Identité</label><select name='identity' required>{ident_opts}</select></div>"
        f"<div><label>Chatteur</label><input type='text' name='chatter' placeholder='Nom du chatteur' required></div>"
        f"<div><label>Montant (€)</label><input type='number' name='amount' step='0.01' min='0' value='100' required></div>"
        f"<div><label>Date</label><input type='date' name='date' value='{today}' required></div>"
        f"<div><label>Source</label><select name='source'><option>OnlyFans</option><option>Fansly</option><option>Snap</option><option>Autre</option></select></div>"
        f"</div>"
        f"<label>Notes</label>"
        f"<input type='text' name='notes' placeholder='PPV, abonnement, tip...' maxlength='200'>"
        f"<button type='submit'>Ajouter</button>"
        f"</form>"
    )
    # Breakdown par identité et chatteur
    if stats.get("by_identity"):
        rows.append("<div class='box'><h4 style='margin-top:0'>💰 Par identité</h4>")
        max_v = max(stats["by_identity"].values())
        for ident, amt in sorted(stats["by_identity"].items(), key=lambda x: x[1], reverse=True):
            pct = (amt / max_v) * 100 if max_v else 0
            rows.append(
                f"<div style='margin-bottom:10px'>"
                f"<div style='display:flex;justify-content:space-between;font-size:14px;margin-bottom:4px'>"
                f"<span><b>{ident}</b></span><b style='color:#00d68f'>+{amt:.2f}€</b></div>"
                f"<div style='background:#0f0f0f;border-radius:4px;height:8px;overflow:hidden'>"
                f"<div style='width:{pct:.1f}%;background:linear-gradient(90deg,#00d68f,#5cf266);height:100%'></div>"
                f"</div></div>"
            )
        rows.append("</div>")
    # Tableau revenus
    if not items:
        rows.append("<p style='color:#888'>Aucun revenu enregistré.</p>")
    else:
        rows.append("<div class='box'><h4 style='margin-top:0'>📋 Historique</h4>")
        rows.append(
            "<table style='width:100%;border-collapse:collapse'>"
            "<tr style='background:#1a1a1a'>"
            "<th style='padding:8px;text-align:left'>Date</th>"
            "<th style='padding:8px;text-align:left'>Identité</th>"
            "<th style='padding:8px;text-align:left'>Chatteur</th>"
            "<th style='padding:8px;text-align:left'>Source</th>"
            "<th style='padding:8px;text-align:left'>Notes</th>"
            "<th style='padding:8px;text-align:right'>Montant</th>"
            "<th style='padding:8px'></th>"
            "</tr>"
        )
        for it in items[:50]:
            rows.append(
                f"<tr style='border-bottom:1px solid #2a2a2a'>"
                f"<td style='padding:8px;font-size:13px'>{it.get('date','')}</td>"
                f"<td style='padding:8px'><b>{it.get('identity','')}</b></td>"
                f"<td style='padding:8px'>{it.get('chatter','')}</td>"
                f"<td style='padding:8px;font-size:12px;color:#aaa'>{it.get('source','')}</td>"
                f"<td style='padding:8px;font-size:13px;color:#aaa'>{it.get('notes','')}</td>"
                f"<td style='padding:8px;text-align:right;font-weight:600;color:#00d68f'>+{it.get('amount',0):.2f}€</td>"
                f"<td style='padding:8px;text-align:right'>"
                f"<form method='POST' action='/business/revenue/remove' style='display:inline;margin:0'>"
                f"<input type='hidden' name='id' value='{it['id']}'>"
                f"<button type='submit' class='danger-btn' data-confirm='Supprimer ce revenu ?'>×</button>"
                f"</form></td></tr>"
            )
        rows.append("</table></div>")
    return "".join(rows)


def _render_paievas_html() -> str:
    try:
        from business import list_va_payments, va_payment_stats
    except Exception as e:
        return f"<p style='color:#f99'>Module business indispo : {e}</p>"
    # Récupérer les VAs depuis users.json
    users = _load_users()
    va_opts = []
    for uid, data in users.items():
        if isinstance(data, dict):
            username = _resolve_username(uid)
            identity = data.get("identity", "?")
            va_opts.append((uid, username, identity))
    va_select = ""
    if va_opts:
        va_select = "".join(f"<option value='{u}'>@{u} ({i})</option>" for _, u, i in va_opts)
    else:
        va_select = "<option value=''>(aucun VA enregistré)</option>"
    import datetime
    today = datetime.date.today().isoformat()
    items = list_va_payments()
    stats = va_payment_stats()
    rows = []
    rows.append(
        "<div class='stat-grid' style='margin-bottom:16px'>"
        f"<div class='stat'><div class='v' style='color:#ffb800'>{stats['total_unpaid']:.0f}€</div><div class='l'>À payer (en attente)</div></div>"
        f"<div class='stat'><div class='v' style='color:#00d68f'>{stats['total_paid']:.0f}€</div><div class='l'>Déjà payé</div></div>"
        f"<div class='stat'><div class='v'>{stats['total_due']:.0f}€</div><div class='l'>Total dû</div></div>"
        f"<div class='stat'><div class='v'>{len(stats.get('by_va', {}))}</div><div class='l'>VAs concernés</div></div>"
        "</div>"
    )
    rows.append(
        f"<form method='POST' action='/business/vapayment/add' class='box'>"
        f"<h4 style='margin-top:0'>➕ Nouveau paiement VA</h4>"
        f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px'>"
        f"<div><label>VA</label><select name='va_username' required>{va_select}</select></div>"
        f"<div><label>Montant (€)</label><input type='number' name='amount' step='0.01' min='0' value='50' required></div>"
        f"<div><label>Date</label><input type='date' name='date' value='{today}' required></div>"
        f"<div><label>Méthode</label><select name='payment_method'><option value=''>(non spécifié)</option><option>PayPal</option><option>Virement</option><option>Crypto</option><option>Espèces</option><option>Autre</option></select></div>"
        f"<div><label style='display:flex;align-items:center;gap:6px;margin-top:24px'><input type='checkbox' name='paid' style='width:auto;margin:0'> Déjà payé</label></div>"
        f"</div>"
        f"<label>Description (ce qui est payé)</label>"
        f"<input type='text' name='description' placeholder='5 reels postés, mois mai...' required maxlength='200'>"
        f"<button type='submit'>Ajouter</button>"
        f"</form>"
    )
    # Breakdown par VA
    if stats.get("by_va"):
        rows.append("<div class='box'><h4 style='margin-top:0'>👥 Par VA</h4>")
        rows.append("<table style='width:100%;border-collapse:collapse'>")
        rows.append("<tr style='background:#1a1a1a'><th style='padding:8px;text-align:left'>VA</th><th style='padding:8px;text-align:right'>Payé</th><th style='padding:8px;text-align:right'>À payer</th><th style='padding:8px;text-align:right'>Total</th></tr>")
        for va, v in sorted(stats["by_va"].items(), key=lambda x: x[1]["paid"] + x[1]["unpaid"], reverse=True):
            total = v["paid"] + v["unpaid"]
            rows.append(
                f"<tr style='border-bottom:1px solid #2a2a2a'>"
                f"<td style='padding:8px'>@{va}</td>"
                f"<td style='padding:8px;text-align:right;color:#00d68f'>{v['paid']:.2f}€</td>"
                f"<td style='padding:8px;text-align:right;color:#ffb800'>{v['unpaid']:.2f}€</td>"
                f"<td style='padding:8px;text-align:right;font-weight:700'>{total:.2f}€</td>"
                f"</tr>"
            )
        rows.append("</table></div>")
    # Tableau de tous les paiements
    if not items:
        rows.append("<p style='color:#888'>Aucun paiement enregistré.</p>")
    else:
        rows.append("<div class='box'><h4 style='margin-top:0'>📋 Historique</h4>")
        rows.append(
            "<table style='width:100%;border-collapse:collapse'>"
            "<tr style='background:#1a1a1a'>"
            "<th style='padding:8px;text-align:center'>État</th>"
            "<th style='padding:8px;text-align:left'>Date</th>"
            "<th style='padding:8px;text-align:left'>VA</th>"
            "<th style='padding:8px;text-align:left'>Description</th>"
            "<th style='padding:8px;text-align:left'>Méthode</th>"
            "<th style='padding:8px;text-align:right'>Montant</th>"
            "<th style='padding:8px'></th>"
            "</tr>"
        )
        for it in items[:50]:
            paid = it.get("paid", False)
            badge = "<span style='background:#00d68f;color:#000;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700'>PAYÉ</span>" if paid else "<span style='background:#ffb800;color:#000;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700'>À PAYER</span>"
            color = "color:#00d68f" if paid else "color:#ffb800"
            rows.append(
                f"<tr style='border-bottom:1px solid #2a2a2a'>"
                f"<td style='padding:8px;text-align:center'>"
                f"<form method='POST' action='/business/vapayment/toggle' style='display:inline;margin:0'>"
                f"<input type='hidden' name='id' value='{it['id']}'>"
                f"<button type='submit' style='background:none;border:0;cursor:pointer;padding:0;margin:0'>{badge}</button>"
                f"</form></td>"
                f"<td style='padding:8px;font-size:13px'>{it.get('date','')}</td>"
                f"<td style='padding:8px'>@{it.get('va_username','')}</td>"
                f"<td style='padding:8px'>{it.get('description','')}</td>"
                f"<td style='padding:8px;font-size:12px;color:#aaa'>{it.get('payment_method','')}</td>"
                f"<td style='padding:8px;text-align:right;font-weight:600;{color}'>{it.get('amount',0):.2f}€</td>"
                f"<td style='padding:8px;text-align:right'>"
                f"<form method='POST' action='/business/vapayment/remove' style='display:inline;margin:0'>"
                f"<input type='hidden' name='id' value='{it['id']}'>"
                f"<button type='submit' class='danger-btn' data-confirm='Supprimer ce paiement ?'>×</button>"
                f"</form></td></tr>"
            )
        rows.append("</table></div>")
    return "".join(rows)


def _render_bilan_html() -> str:
    try:
        from business import expense_stats, sfs_stats, list_expenses, revenue_stats, va_payment_stats
        from insta_scraper import load_watchlist
    except Exception as e:
        return f"<p style='color:#f99'>Module business indispo : {e}</p>"
    exp = expense_stats()
    rev = revenue_stats()
    sfs = sfs_stats()
    pay = va_payment_stats()
    try:
        nb_va = len(_load_users())
    except Exception:
        nb_va = 0
    nb_ident = len(_list_identities())
    # Profit net = revenus - dépenses - paie VAs payés
    profit_month = rev["total_this_month"] - exp["total_this_month"]
    profit_all = rev["total_all_time"] - exp["total_all_time"] - pay["total_paid"]
    profit_color = "#00d68f" if profit_month >= 0 else "#f99"
    profit_sign = "+" if profit_month >= 0 else ""
    rows = []
    # Stats GROSSES en haut : profit net
    rows.append(
        "<div class='box' style='background:linear-gradient(135deg,#1a1a2e,#16213e);text-align:center;border:1px solid #ef4444;margin-bottom:16px'>"
        f"<div style='color:#888;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px'>Profit net ce mois</div>"
        f"<div style='font-size:48px;font-weight:800;color:{profit_color}'>{profit_sign}{profit_month:.0f}€</div>"
        f"<div style='display:flex;justify-content:center;gap:24px;margin-top:14px;font-size:14px;color:#aaa'>"
        f"<span>📈 +{rev['total_this_month']:.0f}€ revenus</span>"
        f"<span>📉 -{exp['total_this_month']:.0f}€ dépenses</span>"
        f"</div>"
        "</div>"
    )
    # Stats secondaires
    rows.append(
        "<div class='stat-grid'>"
        f"<div class='stat'><div class='v' style='color:#00d68f'>+{rev['total_all_time']:.0f}€</div><div class='l'>Revenus total</div></div>"
        f"<div class='stat'><div class='v' style='color:#f99'>-{exp['total_all_time']:.0f}€</div><div class='l'>Dépenses total</div></div>"
        f"<div class='stat'><div class='v' style='color:#ffb800'>{pay['total_unpaid']:.0f}€</div><div class='l'>À payer VAs</div></div>"
        f"<div class='stat'><div class='v' style='color:#ffb800'>-{exp['monthly_recurring']:.0f}€</div><div class='l'>Récurrent / mois</div></div>"
        f"<div class='stat'><div class='v'>{nb_va}</div><div class='l'>VAs actifs</div></div>"
        f"<div class='stat'><div class='v'>{nb_ident}</div><div class='l'>Identités</div></div>"
        "</div>"
    )
    # Top performers : revenus par identité
    if rev.get("by_identity"):
        rows.append("<div class='box'><h4 style='margin-top:0'>🏆 Revenus par identité</h4>")
        max_v = max(rev["by_identity"].values())
        for ident, amt in sorted(rev["by_identity"].items(), key=lambda x: x[1], reverse=True):
            pct = (amt / max_v) * 100 if max_v else 0
            rows.append(
                f"<div style='margin-bottom:10px'>"
                f"<div style='display:flex;justify-content:space-between;font-size:14px;margin-bottom:4px'>"
                f"<b>{ident}</b><b style='color:#00d68f'>+{amt:.2f}€</b></div>"
                f"<div style='background:#0f0f0f;border-radius:4px;height:8px;overflow:hidden'>"
                f"<div style='width:{pct:.1f}%;background:linear-gradient(90deg,#00d68f,#5cf266);height:100%'></div>"
                f"</div></div>"
            )
        rows.append("</div>")
    # Dépenses par catégorie
    rows.append("<div class='box'><h4 style='margin-top:0'>📊 Dépenses par catégorie</h4>")
    by_cat = exp.get("by_category", {})
    if not by_cat:
        rows.append("<p style='color:#888;margin:0'>Aucune dépense enregistrée.</p>")
    else:
        max_amount = max(by_cat.values())
        for cat, amount in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
            pct = (amount / max_amount) * 100 if max_amount > 0 else 0
            rows.append(
                f"<div style='margin-bottom:10px'>"
                f"<div style='display:flex;justify-content:space-between;font-size:14px;margin-bottom:4px'>"
                f"<span style='color:#ccc'>{cat}</span><b style='color:#f99'>-{amount:.2f}€</b></div>"
                f"<div style='background:#0f0f0f;border-radius:4px;height:8px;overflow:hidden'>"
                f"<div style='width:{pct:.1f}%;background:linear-gradient(90deg,#f87171,#ef4444);height:100%'></div>"
                f"</div></div>"
            )
    rows.append("</div>")
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
        .replace("{sfs_html}", _render_sfs_html())
        .replace("{revenus_html}", _render_revenus_html())
        .replace("{depenses_html}", _render_depenses_html())
        .replace("{paievas_html}", _render_paievas_html())
        .replace("{bilan_html}", _render_bilan_html())
        .replace("{insta_auth_status}", _render_insta_auth_status())
        .replace("{insta_accounts_html}", _render_insta_accounts_html())
        .replace("{insta_accounts_html_for_trends}", _render_insta_accounts_html())
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
        return _render_upload()

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

    @app.route("/identity/avatar/<identity>")
    def identity_avatar(identity):
        if not is_auth():
            return redirect("/")
        safe = identity.lower().strip()
        if safe not in _list_identities():
            return "Not found", 404
        path = _identity_avatar_path(safe)
        if not path:
            return "Not found", 404
        from flask import send_file
        response = send_file(str(path))
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    @app.route("/identity/upload_avatar", methods=["POST"])
    def identity_upload_avatar():
        if not is_auth():
            return redirect("/")
        identity = (request.form.get("identity") or "").strip().lower()
        if not identity or identity not in _list_identities():
            return _error("❌ Identité invalide")
        f = request.files.get("avatar")
        if not f or not f.filename:
            return _error("❌ Pas de fichier")
        ext = os.path.splitext(f.filename)[1].lower().lstrip(".")
        if ext not in ("png", "jpg", "jpeg", "webp"):
            return _error(f"❌ Format non supporté ({ext})")
        target_dir = IDENTITIES_DIR / identity
        target_dir.mkdir(parents=True, exist_ok=True)
        # Supprimer les anciens avatars
        for old_ext in ("png", "jpg", "jpeg", "webp"):
            old = target_dir / f"avatar.{old_ext}"
            if old.exists():
                try:
                    old.unlink()
                except Exception:
                    pass
        target = target_dir / f"avatar.{ext}"
        f.save(str(target))
        return _success(f"✅ Avatar de <b>{identity}</b> uploadé")

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

    # ============ BUSINESS ROUTES ============
    @app.route("/business/sfs/add", methods=["POST"])
    def business_sfs_add():
        if not is_auth():
            return redirect("/")
        try:
            from business import add_sfs
        except Exception as e:
            return _error(f"Module indispo: {e}")
        identity = (request.form.get("identity") or "").strip()
        partner = (request.form.get("partner") or "").strip()
        date = (request.form.get("date") or "").strip()
        time_s = (request.form.get("time") or "").strip()
        platform = (request.form.get("platform") or "OF").strip().upper()
        status = (request.form.get("status") or "scheduled").strip()
        notes = (request.form.get("notes") or "").strip()
        if not identity or not partner or not date or not time_s:
            return _error("❌ Champs requis manquants")
        add_sfs(identity, partner, date, time_s, platform, status, notes)
        return _success(f"✅ SFS ajouté : <b>{identity}</b> ({platform}) avec <b>@{partner}</b> le {date} à {time_s}")

    @app.route("/business/identity_platforms", methods=["POST"])
    def business_identity_platforms():
        if not is_auth():
            return redirect("/")
        try:
            from business import save_identity_platforms, PLATFORMS
        except Exception as e:
            return _error(f"Module indispo: {e}")
        # Récupérer tous les checkboxes platform_<identity>=<platform>
        # request.form.getlist permet d'avoir plusieurs valeurs pour la même clé
        new_map = {}
        for key in request.form.keys():
            if key.startswith("platform_"):
                ident = key[len("platform_"):]
                vals = request.form.getlist(key)
                new_map[ident] = [v for v in vals if v in PLATFORMS]
        # Garder même les identités sans plateforme cochée (liste vide)
        save_identity_platforms(new_map)
        return _success(f"✅ Plateformes sauvées pour {len(new_map)} identité(s)")

    @app.route("/business/sfs/remove", methods=["POST"])
    def business_sfs_remove():
        if not is_auth():
            return redirect("/")
        try:
            from business import remove_sfs
        except Exception as e:
            return _error(f"Module indispo: {e}")
        try:
            iid = int(request.form.get("id", "0"))
        except Exception:
            return _error("❌ ID invalide")
        if remove_sfs(iid):
            return _success("✅ SFS supprimé")
        return _error("❌ SFS introuvable")

    @app.route("/business/sfs/toggle", methods=["POST"])
    def business_sfs_toggle():
        if not is_auth():
            return redirect("/")
        try:
            from business import toggle_sfs_done
        except Exception as e:
            return _error(f"Module indispo: {e}")
        try:
            iid = int(request.form.get("id", "0"))
        except Exception:
            return _error("❌ ID invalide")
        if toggle_sfs_done(iid):
            return _success("✅ Statut SFS modifié")
        return _error("❌ SFS introuvable")

    @app.route("/business/expense/add", methods=["POST"])
    def business_expense_add():
        if not is_auth():
            return redirect("/")
        try:
            from business import add_expense
        except Exception as e:
            return _error(f"Module indispo: {e}")
        category = (request.form.get("category") or "").strip()
        description = (request.form.get("description") or "").strip()
        date = (request.form.get("date") or "").strip()
        try:
            amount = float(request.form.get("amount") or "0")
        except Exception:
            return _error("❌ Montant invalide")
        recurring = request.form.get("recurring") == "on"
        if not category or not description or not date or amount <= 0:
            return _error("❌ Champs requis manquants ou invalides")
        add_expense(category, description, amount, date, recurring)
        return _success(f"✅ Dépense ajoutée : <b>{description}</b> ({amount:.2f}€)")

    @app.route("/business/expense/remove", methods=["POST"])
    def business_expense_remove():
        if not is_auth():
            return redirect("/")
        try:
            from business import remove_expense
        except Exception as e:
            return _error(f"Module indispo: {e}")
        try:
            iid = int(request.form.get("id", "0"))
        except Exception:
            return _error("❌ ID invalide")
        if remove_expense(iid):
            return _success("✅ Dépense supprimée")
        return _error("❌ Dépense introuvable")

    @app.route("/business/revenue/add", methods=["POST"])
    def business_revenue_add():
        if not is_auth():
            return redirect("/")
        try:
            from business import add_revenue
        except Exception as e:
            return _error(f"Module indispo: {e}")
        identity = (request.form.get("identity") or "").strip()
        chatter = (request.form.get("chatter") or "").strip()
        date = (request.form.get("date") or "").strip()
        source = (request.form.get("source") or "OnlyFans").strip()
        notes = (request.form.get("notes") or "").strip()
        try:
            amount = float(request.form.get("amount") or "0")
        except Exception:
            return _error("❌ Montant invalide")
        if not identity or not chatter or not date or amount <= 0:
            return _error("❌ Champs requis manquants")
        add_revenue(identity, chatter, amount, date, source, notes)
        return _success(f"✅ Revenu ajouté : <b>+{amount:.2f}€</b> via {chatter} pour {identity}")

    @app.route("/business/revenue/remove", methods=["POST"])
    def business_revenue_remove():
        if not is_auth():
            return redirect("/")
        try:
            from business import remove_revenue
        except Exception as e:
            return _error(f"Module indispo: {e}")
        try:
            iid = int(request.form.get("id", "0"))
        except Exception:
            return _error("❌ ID invalide")
        if remove_revenue(iid):
            return _success("✅ Revenu supprimé")
        return _error("❌ Revenu introuvable")

    @app.route("/business/vapayment/add", methods=["POST"])
    def business_vapayment_add():
        if not is_auth():
            return redirect("/")
        try:
            from business import add_va_payment
        except Exception as e:
            return _error(f"Module indispo: {e}")
        va_username = (request.form.get("va_username") or "").strip()
        description = (request.form.get("description") or "").strip()
        date = (request.form.get("date") or "").strip()
        method = (request.form.get("payment_method") or "").strip()
        paid = request.form.get("paid") == "on"
        try:
            amount = float(request.form.get("amount") or "0")
        except Exception:
            return _error("❌ Montant invalide")
        if not va_username or not description or not date or amount <= 0:
            return _error("❌ Champs requis manquants")
        add_va_payment(va_username, amount, date, description, paid, method)
        status = "payé" if paid else "à payer"
        return _success(f"✅ Paiement ajouté : <b>@{va_username}</b> {amount:.2f}€ ({status})")

    @app.route("/business/vapayment/toggle", methods=["POST"])
    def business_vapayment_toggle():
        if not is_auth():
            return redirect("/")
        try:
            from business import toggle_va_payment_paid
        except Exception as e:
            return _error(f"Module indispo: {e}")
        try:
            iid = int(request.form.get("id", "0"))
        except Exception:
            return _error("❌ ID invalide")
        if toggle_va_payment_paid(iid):
            return _success("✅ Statut paiement modifié")
        return _error("❌ Paiement introuvable")

    @app.route("/business/vapayment/remove", methods=["POST"])
    def business_vapayment_remove():
        if not is_auth():
            return redirect("/")
        try:
            from business import remove_va_payment
        except Exception as e:
            return _error(f"Module indispo: {e}")
        try:
            iid = int(request.form.get("id", "0"))
        except Exception:
            return _error("❌ ID invalide")
        if remove_va_payment(iid):
            return _success("✅ Paiement supprimé")
        return _error("❌ Paiement introuvable")

    @app.route("/settings/insta_rapidapi", methods=["POST"])
    def settings_insta_rapidapi():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import save_auth, load_auth
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        key = (request.form.get("rapidapi_key") or "").strip()
        host = (request.form.get("rapidapi_host") or "").strip()
        # Validation host : doit ressembler à un domaine
        DEFAULT_HOST = "instagram-scraper-stable-api.p.rapidapi.com"
        looks_valid_host = (
            host
            and "." in host
            and "/" not in host
            and ":" not in host
            and " " not in host
            and len(host) < 100
            and not host.startswith("http")
        )
        if not looks_valid_host:
            host = DEFAULT_HOST
        if not key or len(key) < 20:
            return _error("❌ Clé RapidAPI invalide (trop courte). Récupère-la sur RapidAPI → ton API → x-rapidapi-key")
        # Garder cookies existants si présents
        current = load_auth()
        current["rapidapi_key"] = key
        current["rapidapi_host"] = host
        save_auth(current)
        return _success(
            f"✅ Sauvegardé. Host : <code>{host}</code> — Clé : <code>{key[:6]}...{key[-4:]}</code>. "
            f"Teste avec le bouton ▶ Tester maintenant."
        )

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
        result = scrape_profile(clean, limit=50)
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

    @app.route("/insta/reset_rapidapi_host", methods=["POST"])
    def insta_reset_host():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import load_auth, save_auth
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        current = load_auth()
        current["rapidapi_host"] = "instagram-scraper-stable-api.p.rapidapi.com"
        save_auth(current)
        return _success("✅ Host réinitialisé à <code>instagram-scraper-stable-api.p.rapidapi.com</code>")

    @app.route("/insta/test_rapidapi", methods=["POST"])
    def insta_test_rapidapi():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import load_auth, _scrape_via_rapidapi
        except Exception as e:
            return _error(f"Module indispo: {e}")
        auth = load_auth()
        if not auth.get("rapidapi_key"):
            return _error("❌ Pas de clé RapidAPI configurée — sauve-la d'abord")
        # Test avec un profil public connu
        test_user = "instagram"
        result = _scrape_via_rapidapi(test_user, limit=3)
        if "error" in result:
            return _error(f"❌ Test RapidAPI échoué : {result['error']}")
        prof = result.get("profile", {})
        return _success(
            f"✅ RapidAPI fonctionne ! Test @{test_user} → "
            f"<b>{prof.get('followers', 0):,}</b> followers, "
            f"<b>{len(result.get('reels', []))}</b> reels récupérés."
        )

    @app.route("/insta/scrape", methods=["POST"])
    def insta_scrape():
        if not is_auth():
            return redirect("/")
        try:
            from insta_scraper import scrape_profile
        except Exception as e:
            return _error(f"❌ Module indispo: {e}")
        u = (request.form.get("username") or "").strip()
        result = scrape_profile(u, limit=50)
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
            result = scrape_profile(u, limit=50)
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
